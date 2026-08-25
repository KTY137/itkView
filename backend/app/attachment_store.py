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
fetched again.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import TestRunAttachment, TestRunEvidence, utcnow

DEFAULT_ATTACHMENT_DIRNAME = "attachments"

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
        # Only accept a suffix we already trust from the content-type table.
        if suffix in set(_EXTENSION_BY_CONTENT_TYPE.values()):
            return suffix
    return ""


def storage_path(component_sn: str, pdb_code: str, content_type: str | None,
                 filename: str | None) -> str:
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
    existing = session.scalar(
        select(TestRunAttachment).where(
            TestRunAttachment.source == source,
            TestRunAttachment.pdb_code == pdb_code,
        )
    )
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
            descriptors.append(
                {
                    "component_sn": component_sn,
                    "test_type": evidence.test_type,
                    "test_run_ref": evidence.external_ref,
                    "code": str(summary["code"]),
                    "filename": summary.get("filename"),
                    "content_type": summary.get("content_type"),
                    "title": summary.get("title"),
                }
            )
    return descriptors


def _write_bytes(root: Path, relative_path: str, data: bytes) -> int:
    target = (root / relative_path).resolve()
    if not target.is_relative_to(root):
        raise ValueError("refusing to write an attachment outside its directory")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return len(data)


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


def _fetch_bytes(client: Any, descriptor: dict[str, Any]) -> bytes | None:
    """Pull one attachment's bytes. None when the PDB will not hand them over.

    The binary store is the route the live image proxy already uses
    (`app.pdb_attachments`). The test-run route is kept as a fallback because
    attachment handles have historically been served by either, and a download
    that silently returns nothing is worse than one extra request.
    """
    attempts: list[tuple[str, dict[str, Any]]] = [
        ("uu-app-binarystore/getBinaryData", {"code": descriptor["code"]}),
    ]
    if descriptor.get("test_run_ref"):
        attempts.append(
            (
                "getTestRunAttachment",
                {"code": descriptor["code"], "testRun": descriptor["test_run_ref"]},
            )
        )

    for action, request in attempts:
        try:
            result = client.get(action, json=request)
        except Exception:
            continue
        data = _as_bytes(result)
        if data:
            return data
    return None


def download_attachments(
    session: Session,
    gateway: Any,
    settings: Any,
    component_sn: str,
    *,
    force: bool = False,
) -> AttachmentSyncStats:
    """Mirror this component's attachment bytes to the local folder.

    Read-only against the PDB and best effort per attachment: one unavailable
    file must not cost the others.
    """
    descriptors = pending_attachments(session, component_sn)
    if not descriptors:
        return AttachmentSyncStats()

    root = attachment_root(settings)
    downloaded = reused = failed = 0
    client = None

    for descriptor in descriptors:
        row = _upsert_row(
            session,
            component_sn=descriptor["component_sn"],
            test_type=descriptor["test_type"],
            test_run_ref=descriptor["test_run_ref"],
            pdb_code=descriptor["code"],
            filename=descriptor["filename"],
            content_type=descriptor["content_type"],
            title=descriptor["title"],
        )
        session.flush()

        if not force and resolve_path(settings, row) is not None:
            reused += 1
            continue

        if client is None:
            if not getattr(gateway, "is_configured", False):
                failed += 1
                continue
            try:
                client = gateway.client()
            except Exception:
                failed += 1
                continue

        data = _fetch_bytes(client, descriptor)
        if data is None:
            failed += 1
            continue

        relative_path = storage_path(
            component_sn, descriptor["code"], descriptor["content_type"], descriptor["filename"]
        )
        try:
            size = _write_bytes(root, relative_path, data)
        except (OSError, ValueError):
            failed += 1
            continue

        row.relative_path = relative_path
        row.size_bytes = size
        row.downloaded_at = utcnow()
        downloaded += 1

    return AttachmentSyncStats(downloaded=downloaded, reused=reused, failed=failed)
