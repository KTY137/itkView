"""Local mirror of PDB test-run attachments (images, plots, instrument output).

The bytes live on disk, not in the database: the mirror stays small, and a
person can open the folder and look at the pictures with any viewer. Layout is
one directory per serial number, which is what makes that browsing useful:

    <attachment_dir>/20USEM20000041/<pdb-code>.jpg

File names come from the PDB and are therefore untrusted. They are never used
to build a path — the storage name is the PDB attachment code (a hex handle)
plus an extension taken from an allowlist. The original name is kept in the
database for display only.

Downloading is idempotent: an attachment whose file is already present is not
fetched again. A *transient* network failure (DNS outage, connection reset,
timeout, HTTP 5xx) is retried with exponential backoff up to the shared
``sync_page_max_attempts`` budget; a *permanent* answer (4xx, an HTML error
page, an oversized body) fails immediately. Either way a failed attachment is
never recorded as stored, so the next sweep simply tries it again.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from ipaddress import ip_address
from pathlib import Path
from time import sleep
from typing import Any, Literal
from urllib.error import HTTPError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import TestRunAttachment, TestRunEvidence, utcnow

log = logging.getLogger(__name__)

DEFAULT_ATTACHMENT_DIRNAME = "attachments"
DEFAULT_ATTACHMENT_MAX_BYTES = 100 * 1024 * 1024
DEFAULT_ATTACHMENT_DOWNLOAD_TIMEOUT_SECONDS = 60
EOS_DOWNLOAD_HOST = "eosatlas.cern.ch"
# Fallback when the settings object carries no shared page-retry budget.
DEFAULT_DOWNLOAD_MAX_ATTEMPTS = 3
# Backoff base between transient download attempts; doubles per attempt.
# Deliberately the same shape as the evidence fetch retry in app.sync_jobs.
DOWNLOAD_RETRY_BACKOFF_SECONDS = 0.5

# Extensions itkFlow is willing to write. Anything else is stored without one:
# the content type in the database still drives how it is served, and an
# unknown extension is not worth the risk of writing an executable name.
_EXTENSION_BY_CONTENT_TYPE = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
    "image/tiff": ".tif",
    "image/svg+xml": ".svg",
    "application/pdf": ".pdf",
    "application/json": ".json",
    "application/zip": ".zip",
    "text/plain": ".txt",
    "text/csv": ".csv",
}

# Instrument output arrives as application/octet-stream, so the content type
# says nothing. These suffixes are accepted from the PDB's filename because
# they are inert data formats and keeping them lets a person open the file with
# the tool they already use. Nothing executable is on this list.
_TRUSTED_DATA_SUFFIXES = frozenset({".dat", ".log", ".xml", ".root", ".tsv", ".md"})

_SAFE_CODE = re.compile(r"[^A-Za-z0-9_-]")
_SAFE_SN = re.compile(r"[^A-Za-z0-9_-]")


@dataclass(frozen=True)
class AttachmentSyncStats:
    downloaded: int = 0
    reused: int = 0
    failed: int = 0

    @property
    def total(self) -> int:
        return self.downloaded + self.reused + self.failed


def attachment_root(settings: Any) -> Path:
    """The configured attachment directory, created if needed."""
    configured = getattr(settings, "attachment_dir", None)
    root = Path(configured) if configured else Path(DEFAULT_ATTACHMENT_DIRNAME)
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def _extension_for(content_type: str | None, filename: str | None) -> str:
    if content_type:
        known = _EXTENSION_BY_CONTENT_TYPE.get(content_type.split(";")[0].strip().lower())
        if known:
            return known
    if filename:
        suffix = Path(filename).suffix.lower()
        # Only ever a suffix from one of the two allowlists — never whatever
        # the PDB happens to put after the last dot.
        if suffix in set(_EXTENSION_BY_CONTENT_TYPE.values()) or suffix in _TRUSTED_DATA_SUFFIXES:
            return suffix
    return ""


def storage_path(
    component_sn: str, pdb_code: str, content_type: str | None, filename: str | None
) -> str:
    """Relative storage path for one attachment. Never derived from a PDB name."""
    safe_sn = _SAFE_SN.sub("_", component_sn or "unknown")
    safe_code = _SAFE_CODE.sub("_", pdb_code)
    return f"{safe_sn}/{safe_code}{_extension_for(content_type, filename)}"


def resolve_path(settings: Any, attachment: TestRunAttachment) -> Path | None:
    """Absolute path of a stored attachment, or None if it is not on disk.

    Containment is re-checked here rather than trusted from the database: a row
    edited by hand must not be able to read outside the attachment directory.
    """
    if not attachment.relative_path:
        return None
    root = attachment_root(settings)
    candidate = (root / attachment.relative_path).resolve()
    if not candidate.is_relative_to(root) or not candidate.is_file():
        return None
    return candidate


def known_attachments(session: Session, component_sn: str) -> list[TestRunAttachment]:
    return list(
        session.scalars(
            select(TestRunAttachment)
            .where(TestRunAttachment.component_sn == component_sn)
            .order_by(TestRunAttachment.test_type, TestRunAttachment.id)
        )
    )


def attachment_read_model(settings: Any, attachment: TestRunAttachment) -> dict[str, Any]:
    """Return the public, local-only representation of a mirrored attachment.

    Deliberately omit the storage path and any remote source URL.  Both the
    regular test-run endpoint and the staged preview use this projection, so a
    raw share link (or a future signed URL) can never leak through one of the
    read models by accident.
    """
    return {
        "code": attachment.pdb_code,
        "test_type": attachment.test_type,
        "test_run_ref": attachment.test_run_ref,
        "filename": attachment.filename,
        "content_type": attachment.content_type,
        "title": attachment.title,
        "size_bytes": attachment.size_bytes,
        "stored": resolve_path(settings, attachment) is not None,
        "is_image": attachment.is_image,
    }


def _existing_attachment_row(
    session: Session, source: str, pdb_code: str
) -> TestRunAttachment | None:
    """Look up a mirrored attachment by its natural key. Read-only."""
    return session.scalar(
        select(TestRunAttachment).where(
            TestRunAttachment.source == source,
            TestRunAttachment.pdb_code == pdb_code,
        )
    )


def _upsert_row(
    session: Session,
    *,
    component_sn: str,
    test_type: str,
    test_run_ref: str | None,
    pdb_code: str,
    filename: str | None,
    content_type: str | None,
    title: str | None,
    source: str = "pdb",
) -> TestRunAttachment:
    existing = _existing_attachment_row(session, source, pdb_code)
    if existing is None:
        existing = TestRunAttachment(
            component_sn=component_sn,
            test_type=test_type,
            test_run_ref=test_run_ref,
            source=source,
            pdb_code=pdb_code,
        )
        session.add(existing)
    existing.filename = filename
    existing.content_type = content_type
    existing.title = title
    existing.test_type = test_type
    existing.test_run_ref = test_run_ref
    existing.synced_at = utcnow()
    return existing


def pending_attachments(session: Session, component_sn: str) -> list[dict[str, Any]]:
    """Attachment descriptors recorded by the detailed evidence mirror.

    The evidence payload carries metadata only; this is what turns it into a
    download list.
    """
    rows = session.scalars(
        select(TestRunEvidence).where(TestRunEvidence.component_sn == component_sn)
    )
    descriptors: list[dict[str, Any]] = []
    for evidence in rows:
        for summary in (evidence.payload or {}).get("attachments") or []:
            if not isinstance(summary, dict) or not summary.get("code"):
                continue
            source = "share_link" if summary.get("source") == "share_link" else "pdb"
            descriptors.append(
                {
                    "component_sn": component_sn,
                    "test_type": evidence.test_type,
                    "test_run_ref": evidence.external_ref,
                    "code": str(summary["code"]),
                    "filename": summary.get("filename"),
                    "content_type": summary.get("content_type"),
                    "title": summary.get("title"),
                    "type": summary.get("type"),
                    "url": summary.get("url"),
                    "source": source,
                }
            )
    return descriptors


def _temp_path_for(target: Path) -> Path:
    """The ``.part`` sibling a download is staged under before it is renamed.

    Deterministic (not a random name): a ``.part`` file orphaned by a crash or
    a killed process sits at exactly this path, so the next attempt at the
    same attachment silently overwrites it (``Path.write_bytes`` truncates)
    instead of tripping over a stale leftover.
    """
    return target.with_name(target.name + ".part")


def _write_temp_bytes(root: Path, relative_path: str, data: bytes) -> Path:
    """Write attachment bytes to a ``.part`` file beside their final target.

    Never the final name: a reader must never be able to open a half-written
    attachment. Bytes are fully in hand before this is called (no network
    happens while this — or any later disk write — is in progress), so the
    only failure mode here is a local disk problem; that leaves no partial
    ``.part`` file behind either.
    """
    target = (root / relative_path).resolve()
    if not target.is_relative_to(root):
        raise ValueError("refusing to write an attachment outside its directory")
    temp = _temp_path_for(target)
    temp.parent.mkdir(parents=True, exist_ok=True)
    try:
        temp.write_bytes(data)
    except OSError:
        temp.unlink(missing_ok=True)
        raise
    return temp


def _finalize_download(temp_path: Path, root: Path, relative_path: str) -> None:
    """Atomically move a fetched ``.part`` file onto its public name.

    The only filesystem step in the commit phase: by the time this runs, the
    bytes are already durable on disk, so this is a rename, not a write.
    """
    target = (root / relative_path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    os.replace(temp_path, target)


def _as_bytes(result: Any) -> bytes | None:
    """itkdb answers with a BinaryFile-like object; some handles yield raw bytes."""
    if isinstance(result, (bytes, bytearray)):
        return bytes(result)
    content = getattr(result, "content", None)
    if isinstance(content, (bytes, bytearray)):
        return bytes(content)
    read = getattr(result, "read", None)
    if callable(read):
        try:
            data = read()
        except Exception:
            return None
        if isinstance(data, (bytes, bytearray)):
            return bytes(data)
    return None


# An HTML document where a binary was requested is the PDB answering with an
# error or sign-in page. Storing it produces a file that is the right size, has
# the right name, and renders as a broken image — a failure that looks like a
# success everywhere except the screen.
_HTML_PREFIXES = (b"<!doctype", b"<html", b"<?xml")


def looks_like_html(data: bytes) -> bool:
    sample = data[:512].lstrip().lower()
    return any(sample.startswith(prefix) for prefix in _HTML_PREFIXES)


def _reported_content_type(result: Any) -> str | None:
    """itkdb sniffs the real type; trust it over the listing's metadata."""
    for attribute in ("mimetype", "content_type"):
        value = getattr(result, attribute, None)
        if isinstance(value, str) and value:
            return value
    return None


def _valid_payload(data: bytes | None, max_bytes: int) -> bool:
    return bool(data) and len(data) <= max_bytes and not looks_like_html(data)


class _TransientDownloadFailure(RuntimeError):
    """Marker: this fetch failed in a way a later attempt may fix.

    Deliberately carries no upstream text. itkdb exceptions can embed a
    rendered request (credentials) and urllib errors can embed the complete
    share URL; neither may reach a log or a durable row through this path.
    """


class _PdbClientUnavailable(RuntimeError):
    """Marker: no authenticated PDB client can be built for this sweep."""


# HTTP statuses worth retrying: request timeout, too-early, rate limit, 5xx.
_TRANSIENT_HTTP_STATUSES = frozenset({408, 425, 429})

# Exception type names that mean transport trouble, not a data answer. itkdb
# wraps requests/urllib3 errors differently between releases, so the chain is
# matched by name instead of importing every optional dependency.
_TRANSIENT_ERROR_TYPE_MARKERS = (
    "timeout",
    "connectionerror",
    "proxyerror",
    "sslerror",
    "ssleoferror",
    "chunkedencodingerror",
    "protocolerror",
    "nameresolutionerror",
    "newconnectionerror",
    "maxretryerror",
    "gaierror",
    "herror",
    "remotedisconnected",
    "incompleteread",
)

_TRANSIENT_ERROR_DETAIL_MARKERS = (
    "timed out",
    "timeout",
    "name resolution",
    "name or service not known",
    "nodename nor servname",
    "getaddrinfo",
    "remote end closed",
    "connection reset",
    "connection aborted",
    "connection refused",
    "max retries exceeded",
    "temporary failure",
    "temporarily unavailable",
    "incomplete read",
    "handshake operation timed out",
)


def _http_status_of(error: BaseException) -> int | None:
    """Best-effort HTTP status from one exception object.

    Covers the shapes seen in this codebase: itkdb ``ResponseException``
    (``.response.status_code``), plain requests errors (``.status_code``) and
    urllib ``HTTPError`` (``.code``/``.status``).
    """
    response = getattr(error, "response", None)
    for candidate in (
        getattr(response, "status_code", None),
        getattr(error, "status_code", None),
        getattr(error, "code", None),
        getattr(error, "status", None),
    ):
        if isinstance(candidate, int) and 100 <= candidate < 600:
            return candidate
    return None


def is_transient_download_error(error: BaseException) -> bool:
    """Return whether a download failure is safe and useful to retry.

    An HTTP status decides first: 408/425/429 and 5xx are retried, any other
    4xx (404, 403, …) is a final answer. Without a status, DNS failures,
    connection resets, TLS handshake timeouts and friends count as transient.
    The cause/context chain is walked because itkdb and urllib both wrap the
    underlying socket errors.
    """
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        status = _http_status_of(current)
        if status is not None:
            return status in _TRANSIENT_HTTP_STATUSES or 500 <= status < 600

        name = type(current).__name__.lower()
        detail = str(current).lower()
        if (
            isinstance(current, (TimeoutError, ConnectionError))
            or any(marker in name for marker in _TRANSIENT_ERROR_TYPE_MARKERS)
            or any(marker in detail for marker in _TRANSIENT_ERROR_DETAIL_MARKERS)
        ):
            return True
        current = current.__cause__ or current.__context__
    return False


def _raise_if_transient(error: Exception, what: str) -> None:
    if is_transient_download_error(error):
        raise _TransientDownloadFailure(f"{what} failed with a transient error") from None


def _safe_http_url(url: str, *, eos: bool = False) -> bool:
    """Reject credential-bearing and obviously local URLs before any request."""

    try:
        parsed = urlsplit(url)
    except ValueError:
        return False
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return False
    if parsed.username is not None or parsed.password is not None:
        return False
    host = parsed.hostname.rstrip(".").lower()
    if eos:
        return parsed.scheme.lower() == "https" and host == EOS_DOWNLOAD_HOST
    if host == "localhost" or host.endswith(".localhost"):
        return False
    try:
        address = ip_address(host)
    except ValueError:
        return True
    return address.is_global


class _SafeShareRedirects(HTTPRedirectHandler):
    """Re-check every redirect before urllib follows it."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _safe_http_url(newurl):
            raise HTTPError(newurl, code, "Unsafe attachment redirect refused", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open_public_url(url: str, timeout: int):
    opener = build_opener(_SafeShareRedirects())
    request = Request(url, headers={"User-Agent": "itkFlow attachment mirror"})
    return opener.open(request, timeout=timeout)


def _response_content_type(response: Any) -> str | None:
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    get_content_type = getattr(headers, "get_content_type", None)
    if callable(get_content_type):
        value = get_content_type()
        return value if isinstance(value, str) and value else None
    value = headers.get("Content-Type") if hasattr(headers, "get") else None
    return value.split(";", 1)[0].strip() if isinstance(value, str) and value else None


def _share_link_candidates(url: str) -> list[str]:
    """URLs to try for one public share link, most direct first.

    ownCloud/Reva-family shares (CERNBox, DESY syncandshare, …) render an
    HTML viewer page at the plain ``/s/<token>`` URL — verified live: it
    answers 200 ``text/html`` while the file itself sits behind two stable
    routes. Preferred is ``remote.php/dav/public-files/<token>`` (it also
    reports a content length), then ``/s/<token>/download``; the original URL
    stays as the last resort for providers that do serve bytes directly.
    ``/index.php/s/<token>/download`` is deliberately never generated — that
    form failed name resolution during the live validation.

    The pattern is recognised by URL *shape* (a ``/s/<token>`` path), not by
    host name: this is a share-provider convention, not an institute detail.
    """
    parsed = urlsplit(url)
    path = parsed.path.rstrip("/")
    if path.endswith("/download") or "/download/" in path:
        return [url]
    segments = [segment for segment in path.split("/") if segment]
    if len(segments) >= 2 and segments[-2] == "s":
        token = segments[-1]
        base = (parsed.scheme, parsed.netloc)
        return [
            urlunsplit((*base, f"/remote.php/dav/public-files/{token}", "", "")),
            urlunsplit((*base, f"/s/{token}/download", "", "")),
            url,
        ]
    return [url]


def _fetch_share_link(
    descriptor: dict[str, Any], *, timeout: int, max_bytes: int
) -> tuple[bytes, str | None] | None:
    url = descriptor.get("url")
    if not isinstance(url, str) or not _safe_http_url(url):
        return None
    transient_seen = False
    html_seen = False
    for candidate in _share_link_candidates(url):
        if not _safe_http_url(candidate):
            continue
        try:
            with closing(_open_public_url(candidate, timeout)) as response:
                final_url = getattr(response, "geturl", lambda u=candidate: u)()
                if not isinstance(final_url, str) or not _safe_http_url(final_url):
                    continue
                data = response.read(max_bytes + 1)
                content_type = _response_content_type(response)
        except Exception as exc:
            # Every candidate is best effort. Do not stringify network
            # failures: redirect/error objects can contain the complete URL.
            transient_seen = transient_seen or is_transient_download_error(exc)
            continue
        if not isinstance(data, (bytes, bytearray)):
            continue
        payload = bytes(data)
        if content_type and content_type.lower() in {"text/html", "application/xhtml+xml"}:
            # The share's viewer page, not the file — try the next route.
            html_seen = True
            continue
        if looks_like_html(payload):
            html_seen = True
            continue
        if _valid_payload(payload, max_bytes):
            return payload, content_type
    if transient_seen:
        raise _TransientDownloadFailure("share-link download failed with a transient error")
    if html_seen:
        # Storing the page would fake a mirrored attachment that renders as a
        # broken image. Log the code (never the URL) so the miss is visible.
        log.warning(
            "Share-link attachment %s only served HTML pages; the share may be "
            "expired or require sign-in. Nothing was stored.",
            descriptor.get("code"),
        )
    return None


def _fresh_eos_url(client: Any, descriptor: dict[str, Any]) -> str | None:
    run_ref = descriptor.get("test_run_ref")
    if not run_ref:
        return None
    try:
        detail = client.get(
            "getTestRun",
            json={"testRun": run_ref, "noEosToken": False},
        )
    except Exception as exc:
        _raise_if_transient(exc, "EOS URL refresh")
        return None
    if not isinstance(detail, dict):
        return None
    for entry in detail.get("attachments") or []:
        if not isinstance(entry, dict):
            continue
        code = entry.get("code")
        if isinstance(code, dict):
            code = code.get("code")
        if str(code) != descriptor["code"]:
            continue
        url = entry.get("url")
        if isinstance(url, str) and _safe_http_url(url, eos=True):
            return url
    return None


def _fetch_eos_bytes(
    client: Any, descriptor: dict[str, Any], max_bytes: int
) -> tuple[bytes, str | None] | None:
    # Signed URLs are deliberately requested anew for every attempted
    # download, used immediately, and never written to the database.
    url = _fresh_eos_url(client, descriptor)
    if url is None:
        return None
    try:
        result = client.get(url)
    except Exception as exc:
        _raise_if_transient(exc, "EOS download")
        return None
    data = _as_bytes(result)
    if not _valid_payload(data, max_bytes):
        return None
    return data, _reported_content_type(result)


def _fetch_pdb_bytes(
    client: Any, descriptor: dict[str, Any], max_bytes: int
) -> tuple[bytes, str | None] | None:
    """Pull one attachment's bytes and its real type. None when unavailable.

    `getTestRunAttachment` is the route that actually returns the file; it needs
    the owning run, which is why the descriptor carries it. The binary store is
    tried only as a last resort and has been observed answering with an HTML
    page instead of the file, so anything it returns is validated the same way.
    """
    attempts: list[tuple[str, dict[str, Any]]] = []
    if descriptor.get("test_run_ref"):
        attempts.append(
            (
                "getTestRunAttachment",
                {"code": descriptor["code"], "testRun": descriptor["test_run_ref"]},
            )
        )
    attempts.append(("uu-app-binarystore/getBinaryData", {"code": descriptor["code"]}))

    transient_seen = False
    for action, request in attempts:
        try:
            result = client.get(action, json=request)
        except Exception as exc:
            # The fallback route may still answer, so keep going — but remember
            # that the miss was network-shaped: if no route delivers, the whole
            # fetch is worth retrying rather than a final "the file is broken".
            transient_seen = transient_seen or is_transient_download_error(exc)
            continue
        data = _as_bytes(result)
        if not _valid_payload(data, max_bytes):
            continue
        return data, _reported_content_type(result)
    if transient_seen:
        raise _TransientDownloadFailure("attachment download failed with a transient error")
    return None


def _fetch_bytes(
    client: Any | None,
    descriptor: dict[str, Any],
    *,
    timeout: int,
    max_bytes: int,
) -> tuple[bytes, str | None] | None:
    if descriptor.get("source") == "share_link":
        return _fetch_share_link(descriptor, timeout=timeout, max_bytes=max_bytes)
    if client is None:
        return None
    if descriptor.get("type") == "eos":
        return _fetch_eos_bytes(client, descriptor, max_bytes)
    return _fetch_pdb_bytes(client, descriptor, max_bytes)


def _open_pdb_client(gateway: Any) -> Any:
    """Build the authenticated client, mapping failures to retryability."""
    if not getattr(gateway, "is_configured", False):
        raise _PdbClientUnavailable("no PDB gateway is configured")
    try:
        return gateway.client()
    except Exception as exc:
        # Authentication/JWKS traffic fails exactly like any other request
        # during an outage; retrying it is what lets a sweep ride one out.
        _raise_if_transient(exc, "PDB client construction")
        raise _PdbClientUnavailable("the PDB client could not be built") from None


def _beat(heartbeat: Callable[[], None] | None) -> None:
    if heartbeat is not None:
        heartbeat()


@dataclass
class _FetchOutcome:
    """One descriptor's result, carried from the fetch phase to the commit
    phase without a live network handle or a ``Session`` anywhere in sight."""

    descriptor: dict[str, Any]
    outcome: Literal["reused", "downloaded", "failed"]
    content_type: str | None = None
    relative_path: str | None = None
    temp_path: Path | None = None
    size: int = 0


def _plan_resolved(
    session: Session, settings: Any, descriptors: list[dict[str, Any]]
) -> dict[tuple[str, str], bool]:
    """Phase 1 - plan (read-only): which ``(source, code)`` keys already have
    a mirrored file on disk.

    No row is created and no attribute is written here — only ``select``
    statements — so this may run freely while another connection elsewhere in
    the app holds a write transaction open.
    """
    resolved: dict[tuple[str, str], bool] = {}
    for descriptor in descriptors:
        key = (descriptor["source"], descriptor["code"])
        if key in resolved:
            continue
        existing = _existing_attachment_row(session, descriptor["source"], descriptor["code"])
        resolved[key] = existing is not None and resolve_path(settings, existing) is not None
    return resolved


def _fetch_all(
    gateway: Any,
    descriptors: list[dict[str, Any]],
    resolved: dict[tuple[str, str], bool],
    *,
    component_sn: str,
    root: Path,
    force: bool,
    timeout: int,
    max_bytes: int,
    max_attempts: int,
    heartbeat: Callable[[], None] | None,
) -> list[_FetchOutcome]:
    """Phase 2 - fetch: network only, no ``Session`` in reach at all.

    A retried download used to run *inside* an open database write
    transaction (the row was upserted and flushed before the bytes were
    fetched), which held SQLite's write lock for as long as a flaky line took
    to deliver a large image — every other request and worker tick failed
    with "database is locked" in the meantime. Bytes now land in a ``.part``
    file beside their final target as soon as they arrive, so a whole sweep's
    worth of images never accumulates in memory waiting for the commit phase
    either (docs/09, Attachment-Phase).
    """
    outcomes: list[_FetchOutcome] = []
    client: Any = None
    # Set once client construction has exhausted its own retry budget: every
    # remaining PDB descriptor would fail identically, so fail them fast this
    # sweep instead of hammering the gateway once per file. None of them is
    # recorded as stored, so the next sweep retries them all.
    client_unavailable = False

    for descriptor in descriptors:
        key = (descriptor["source"], descriptor["code"])

        # Resolved either before this call (a previous sweep) or by an
        # earlier descriptor in this same call (two test runs can list the
        # same attachment code) — `force` re-fetches either way.
        if not force and resolved.get(key):
            outcomes.append(_FetchOutcome(descriptor, "reused"))
            _beat(heartbeat)
            continue

        needs_pdb_client = descriptor["source"] != "share_link"
        if needs_pdb_client and client is None and client_unavailable:
            outcomes.append(_FetchOutcome(descriptor, "failed"))
            _beat(heartbeat)
            continue

        fetched: tuple[bytes, str | None] | None = None
        attempt = 0
        while True:
            attempt += 1
            try:
                if needs_pdb_client and client is None:
                    client = _open_pdb_client(gateway)
                fetched = _fetch_bytes(
                    client,
                    descriptor,
                    timeout=timeout,
                    max_bytes=max_bytes,
                )
                break
            except _PdbClientUnavailable:
                break
            except _TransientDownloadFailure:
                if attempt >= max_attempts:
                    break
                _beat(heartbeat)
                sleep(DOWNLOAD_RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1)))
        if needs_pdb_client and client is None:
            client_unavailable = True

        if fetched is None:
            outcomes.append(_FetchOutcome(descriptor, "failed"))
            _beat(heartbeat)
            continue
        data, reported_type = fetched

        # itkdb sniffs the actual type from the response; the listing metadata
        # is often just "file". Prefer the sniffed one for both the stored
        # extension and what the API later serves.
        content_type = reported_type or descriptor["content_type"]
        relative_path = storage_path(
            component_sn, descriptor["code"], content_type, descriptor["filename"]
        )
        try:
            temp_path = _write_temp_bytes(root, relative_path, data)
        except (OSError, ValueError):
            outcomes.append(_FetchOutcome(descriptor, "failed"))
            _beat(heartbeat)
            continue

        resolved[key] = True
        outcomes.append(
            _FetchOutcome(
                descriptor,
                "downloaded",
                content_type=content_type,
                relative_path=relative_path,
                temp_path=temp_path,
                size=len(data),
            )
        )
        _beat(heartbeat)

    return outcomes


def _commit_outcomes(
    session: Session, root: Path, outcomes: list[_FetchOutcome]
) -> AttachmentSyncStats:
    """Phase 3 - commit: the only phase that writes to ``session``.

    Short by construction: every byte is already durable on disk and every
    network retry already happened, so this loop is pure local bookkeeping —
    an upsert per descriptor plus one rename per successful download. The
    caller still commits afterwards, exactly as before.
    """
    downloaded = reused = failed = 0
    for item in outcomes:
        descriptor = item.descriptor
        row = _upsert_row(
            session,
            component_sn=descriptor["component_sn"],
            test_type=descriptor["test_type"],
            test_run_ref=descriptor["test_run_ref"],
            pdb_code=descriptor["code"],
            filename=descriptor["filename"],
            content_type=descriptor["content_type"],
            title=descriptor["title"],
            source=descriptor["source"],
        )
        # This app's sessions run with autoflush disabled: a later descriptor
        # sharing this (source, code) — the same attachment listed under two
        # test runs — must see this row already persisted, not add a
        # duplicate.
        session.flush()

        if item.outcome == "reused":
            reused += 1
            continue
        if item.outcome == "failed" or item.temp_path is None or item.relative_path is None:
            failed += 1
            continue

        try:
            _finalize_download(item.temp_path, root, item.relative_path)
        except OSError:
            item.temp_path.unlink(missing_ok=True)
            failed += 1
            continue

        row.content_type = item.content_type
        row.relative_path = item.relative_path
        row.size_bytes = item.size
        row.downloaded_at = utcnow()
        downloaded += 1

    return AttachmentSyncStats(downloaded=downloaded, reused=reused, failed=failed)


def download_attachments(
    session: Session,
    gateway: Any,
    settings: Any,
    component_sn: str,
    *,
    force: bool = False,
    heartbeat: Callable[[], None] | None = None,
) -> AttachmentSyncStats:
    """Mirror this component's attachment bytes to the local folder.

    Three strictly separated phases keep this from ever holding a database
    write transaction open across a network call: (1) a read-only plan of
    what already resolves to a file on disk, (2) network fetches — no
    ``Session`` write happens anywhere in this phase, and the phase is not
    even given a ``Session`` — that stage bytes in a ``.part`` file beside
    their final target, and (3) one short, network-free commit that renames
    the finished files into place and upserts their rows. See
    ``_fetch_all`` / ``_commit_outcomes`` and docs/09 (Attachment-Phase) for
    the incident this replaced.

    Read-only against the PDB and best effort per attachment: one unavailable
    file must not cost the others. Transient network failures are retried with
    exponential backoff up to the shared ``sync_page_max_attempts`` budget;
    permanent answers fail once. ``heartbeat`` (if given) is invoked after
    every processed file and before every retry backoff, so a durable job can
    prove it is alive while a slow or flaky download is in progress.
    """
    descriptors = pending_attachments(session, component_sn)
    if not descriptors:
        return AttachmentSyncStats()

    root = attachment_root(settings)
    max_bytes = max(
        1,
        int(getattr(settings, "attachment_max_bytes", DEFAULT_ATTACHMENT_MAX_BYTES)),
    )
    timeout = max(
        1,
        int(
            getattr(
                settings,
                "attachment_download_timeout_seconds",
                DEFAULT_ATTACHMENT_DOWNLOAD_TIMEOUT_SECONDS,
            )
        ),
    )
    max_attempts = max(
        1,
        int(getattr(settings, "sync_page_max_attempts", DEFAULT_DOWNLOAD_MAX_ATTEMPTS)),
    )

    # Phase 1 - plan (read-only).
    resolved = _plan_resolved(session, settings, descriptors)

    # Phase 2 - fetch (network only; no session write is even possible here,
    # since this helper is never handed a session).
    outcomes = _fetch_all(
        gateway,
        descriptors,
        resolved,
        component_sn=component_sn,
        root=root,
        force=force,
        timeout=timeout,
        max_bytes=max_bytes,
        max_attempts=max_attempts,
        heartbeat=heartbeat,
    )

    # Phase 3 - commit (short, network-free transaction).
    return _commit_outcomes(session, root, outcomes)
