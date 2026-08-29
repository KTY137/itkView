# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-FileComment: itkflow-ff719e8d4981
"""Local mirror of PDB test-run attachments (images, plots, instrument output).

The bytes live on disk, not in the database: the mirror stays small, and a
person can open the folder and look at the pictures with any viewer. Layout is
one directory per serial number, which is what makes that browsing useful:

    <attachment_dir>/20USEM20000041/pdb/<pdb-code>.jpg

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

One remote answers with an *archive* rather than a file: a CERNBox folder
share serves no bytes over WebDAV (501) and only answers on a download route
that packs the requested entry into a tar. Such a response is never written to
disk as an archive and never extracted as a tree — exactly one member is
selected, read in memory and handed to the storage path above. Every rule that
selection obeys is written down at ``_archive_member`` and its neighbours.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import logging
import os
import re
import tarfile
import tempfile
import zlib
from collections.abc import Callable, Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass
from io import BytesIO
from ipaddress import ip_address
from pathlib import Path
from threading import Lock, RLock
from time import sleep
from typing import Any, Literal
from urllib.error import HTTPError
from urllib.parse import unquote, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from weakref import WeakValueDictionary

from sqlalchemy import case, event, exists, func, select
from sqlalchemy.orm import Session, aliased

from app.models import (
    Component,
    TestRunAttachment,
    TestRunAttachmentReference,
    TestRunEvidence,
    utcnow,
)
from app.share_credentials import SharePasswordResolver, public_share_identity

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
    "image/avif": ".avif",
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

# The inverse of `_EXTENSION_BY_CONTENT_TYPE`, written out rather than derived
# so the two ambiguous pairs (`image/jpeg` vs `image/jpg`, `.tif` vs `.tiff`)
# resolve to one deliberate answer instead of to whichever entry happened to be
# last. A test asserts that every extension the mirror is willing to write
# appears here, so the two tables cannot drift apart.
_CONTENT_TYPE_BY_EXTENSION = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".avif": "image/avif",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".svg": "image/svg+xml",
    ".pdf": "application/pdf",
    ".json": "application/json",
    ".zip": "application/zip",
    ".txt": "text/plain",
    ".csv": "text/csv",
}

# Keep this in lockstep with frontend/src/ui.ts DISPLAYABLE_IMAGE_TYPES. The
# broader `image/*` predicate remains correct for galleries, where TIFF is a
# truthful stored-image placeholder; list thumbnails must be paintable by the
# browser because they have no placeholder UI.
_DISPLAYABLE_IMAGE_CONTENT_TYPES = frozenset(
    {
        "image/jpeg",
        "image/jpg",
        "image/png",
        "image/gif",
        "image/webp",
        "image/bmp",
        "image/avif",
        "image/svg+xml",
    }
)

_SAFE_CODE = re.compile(r"[^A-Za-z0-9_-]")
_SAFE_SN = re.compile(r"[^A-Za-z0-9_-]")


class _AttachmentKeyLock:
    """Weak-referenceable lock for one physical attachment identity."""

    __slots__ = ("lock", "__weakref__")

    def __init__(self) -> None:
        self.lock = RLock()


_ATTACHMENT_KEY_LOCKS: WeakValueDictionary[
    tuple[str, str, str], _AttachmentKeyLock
] = WeakValueDictionary()
_ATTACHMENT_KEY_LOCKS_GUARD = Lock()
_ATTACHMENT_LOCK_RELEASES_INFO_KEY = "_itkflow_attachment_lock_releases"


@dataclass(frozen=True)
class AttachmentSyncStats:
    downloaded: int = 0
    reused: int = 0
    failed: int = 0
    skipped: int = 0
    authentication_required: int = 0

    @property
    def total(self) -> int:
        return self.downloaded + self.reused + self.failed + self.skipped


@dataclass(frozen=True)
class AttachmentView:
    """Association metadata paired with its one physical attachment blob.

    The public API historically consumed ``TestRunAttachment`` rows directly.
    This small view preserves that attribute-shaped contract while separating
    the two identities the old row had conflated: ``blob`` says which bytes
    exist once, while the remaining fields say which component/test run
    references those bytes.
    """

    blob: TestRunAttachment
    component_sn: str
    test_type: str
    test_run_ref: str | None
    filename: str | None
    title: str | None

    @property
    def id(self) -> int:
        return self.blob.id

    @property
    def source(self) -> str:
        return self.blob.source

    @property
    def pdb_code(self) -> str:
        return self.blob.pdb_code

    @property
    def content_type(self) -> str | None:
        return self.blob.content_type

    @property
    def size_bytes(self) -> int | None:
        return self.blob.size_bytes

    @property
    def relative_path(self) -> str | None:
        return self.blob.relative_path

    @property
    def is_image(self) -> bool:
        return self.blob.is_image


def attachment_root(settings: Any) -> Path:
    """The configured attachment directory, created if needed."""
    configured = getattr(settings, "attachment_dir", None)
    root = Path(configured) if configured else Path(DEFAULT_ATTACHMENT_DIRNAME)
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def _acquire_attachment_key_locks(
    root: Path, descriptors: list[dict[str, Any]]
) -> list[_AttachmentKeyLock]:
    """Serialize overlapping blob downloads without serializing unrelated ones.

    A component refresh and a background sweep can plan the same absent blob
    concurrently. Besides racing the database unique key, they would perform
    redundant network work. Locks are acquired in sorted order to avoid
    deadlocks when two components share more than one code. The weak registry
    does not retain one lock forever for every attachment the mirror has ever
    seen. Unique staging paths remain the cross-process safety boundary because
    separate server processes do not share this registry.
    """
    root_key = os.path.normcase(str(root))
    keys = sorted(
        {
            (root_key, str(descriptor["source"]), str(descriptor["code"]))
            for descriptor in descriptors
        }
    )
    with _ATTACHMENT_KEY_LOCKS_GUARD:
        locks: list[_AttachmentKeyLock] = []
        for key in keys:
            lock = _ATTACHMENT_KEY_LOCKS.get(key)
            if lock is None:
                lock = _AttachmentKeyLock()
                _ATTACHMENT_KEY_LOCKS[key] = lock
            locks.append(lock)
    for item in locks:
        item.lock.acquire()
    return locks


def _release_attachment_key_locks(locks: list[_AttachmentKeyLock]) -> None:
    for item in reversed(locks):
        item.lock.release()


@event.listens_for(Session, "after_transaction_end")
def _release_attachment_locks_at_registered_root(
    session: Session, transaction: Any
) -> None:
    """Release only batches registered for this exact root transaction.

    SQLAlchemy also emits ``after_transaction_end`` for flush subtransactions
    and SAVEPOINTs. A fixed class listener with mutable ``Session.info`` state
    avoids both early release and dynamically removing an event listener while
    its dispatch collection is being iterated (which SQLAlchemy forbids).
    """
    pending = session.info.get(_ATTACHMENT_LOCK_RELEASES_INFO_KEY)
    if not pending:
        return
    remaining = []
    for expected_transaction, locks in pending:
        if transaction is expected_transaction:
            _release_attachment_key_locks(locks)
        else:
            remaining.append((expected_transaction, locks))
    if remaining:
        session.info[_ATTACHMENT_LOCK_RELEASES_INFO_KEY] = remaining
    else:
        session.info.pop(_ATTACHMENT_LOCK_RELEASES_INFO_KEY, None)


def _release_attachment_key_locks_after_transaction(
    session: Session, locks: list[_AttachmentKeyLock]
) -> None:
    """Keep locks until another session can observe the committed blob row."""
    root_transaction = session.get_transaction()
    if root_transaction is None:
        _release_attachment_key_locks(locks)
        return
    session.info.setdefault(_ATTACHMENT_LOCK_RELEASES_INFO_KEY, []).append(
        (root_transaction, locks)
    )


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


def _safe_source_segment(source: str) -> str:
    """Return a path-safe, identity-preserving source directory name.

    The current source names already consist only of safe characters and stay
    readable. If a future source contains punctuation or Unicode, a digest
    prevents two names that sanitise alike from targeting the same file.
    """
    raw_source = source
    safe_source = _SAFE_CODE.sub("_", raw_source)
    if raw_source and safe_source == raw_source:
        return safe_source
    digest = hashlib.sha256(raw_source.encode("utf-8")).hexdigest()[:12]
    return f"{safe_source or 'unknown'}-{digest}"


def storage_path(
    component_sn: str,
    pdb_code: str,
    content_type: str | None,
    filename: str | None,
    *,
    source: str,
) -> str:
    """Relative path for a new blob, qualified by its public source identity."""
    safe_sn = _SAFE_SN.sub("_", component_sn or "unknown")
    safe_source = _safe_source_segment(source)
    safe_code = _SAFE_CODE.sub("_", pdb_code)
    return f"{safe_sn}/{safe_source}/{safe_code}{_extension_for(content_type, filename)}"


def resolve_path(settings: Any, attachment: TestRunAttachment | AttachmentView) -> Path | None:
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


def _reference_view(
    attachment: TestRunAttachment,
    reference: TestRunAttachmentReference | None = None,
) -> AttachmentView:
    if reference is None:
        return AttachmentView(
            blob=attachment,
            component_sn=attachment.component_sn,
            test_type=attachment.test_type,
            test_run_ref=attachment.test_run_ref,
            filename=attachment.filename,
            title=attachment.title,
        )
    return AttachmentView(
        blob=attachment,
        component_sn=reference.component_sn,
        test_type=reference.test_type,
        test_run_ref=reference.test_run_ref or None,
        filename=reference.filename,
        title=reference.title,
    )


def attachment_references_for_components(
    session: Session,
    component_sns: list[str] | tuple[str, ...],
    *,
    stored_images_only: bool = False,
) -> dict[str, list[AttachmentView]]:
    """All attachment associations for several components in constant queries.

    New rows come from ``test_run_attachment_reference``.  Directly-created
    legacy rows (old databases and focused fixtures) remain readable whenever
    no association exists for that same blob/component pair.  The fallback is
    deliberately additive: once a real association exists, stale representative
    fields on the blob can no longer invent a second run association.
    """
    serials = tuple(dict.fromkeys(component_sns))
    grouped: dict[str, list[AttachmentView]] = {sn: [] for sn in serials}
    if not serials:
        return grouped
    dialect_name = session.get_bind().dialect.name

    reference_statement = (
        select(TestRunAttachmentReference, TestRunAttachment)
        .join(
            TestRunAttachment,
            TestRunAttachment.id == TestRunAttachmentReference.attachment_id,
        )
        .where(TestRunAttachmentReference.component_sn.in_(serials))
        .order_by(
            TestRunAttachmentReference.component_sn,
            TestRunAttachmentReference.test_type,
            TestRunAttachmentReference.test_run_ref,
            TestRunAttachmentReference.id,
        )
    )
    if stored_images_only:
        reference_statement = reference_statement.where(
            TestRunAttachment.relative_path.is_not(None),
            is_image_sql(dialect_name),
        )
    rows = session.execute(reference_statement)
    for reference, attachment in rows:
        grouped[reference.component_sn].append(_reference_view(attachment, reference))

    matching_reference = exists().where(
        TestRunAttachmentReference.attachment_id == TestRunAttachment.id,
        TestRunAttachmentReference.component_sn == TestRunAttachment.component_sn,
    )
    legacy_statement = (
        select(TestRunAttachment)
        .where(
            TestRunAttachment.component_sn.in_(serials),
            ~matching_reference,
        )
        .order_by(
            TestRunAttachment.component_sn,
            TestRunAttachment.test_type,
            TestRunAttachment.id,
        )
    )
    if stored_images_only:
        legacy_statement = legacy_statement.where(
            TestRunAttachment.relative_path.is_not(None),
            is_image_sql(dialect_name),
        )
    legacy_rows = session.scalars(legacy_statement)
    for attachment in legacy_rows:
        grouped[attachment.component_sn].append(_reference_view(attachment))
    return grouped


def attachment_references(session: Session, component_sn: str) -> list[AttachmentView]:
    """Every run association for one component, including legacy fallback."""
    return attachment_references_for_components(session, [component_sn])[component_sn]


def known_attachments(session: Session, component_sn: str) -> list[AttachmentView]:
    """One gallery/index entry per physical blob referenced by a component."""
    unique: dict[tuple[str, str], AttachmentView] = {}
    for attachment in attachment_references(session, component_sn):
        unique.setdefault((attachment.source, attachment.pdb_code), attachment)
    return list(unique.values())


def _trim_content_type_sql(value, dialect_name: str):
    """Trim HTTP whitespace on both supported SQL engines."""
    whitespace = " \t\r\n\f\v"
    if dialect_name == "postgresql":
        return func.btrim(value, whitespace)
    return func.trim(value, whitespace)


def is_image_sql(dialect_name: str):
    """SQL form of ``TestRunAttachment.is_image``, for filtering in the database.

    The Python property answers per row; a listing endpoint has to ask the
    question of thousands of rows at once, and doing that after the fact makes
    a row limit meaningless. Lower-cased explicitly because ``LIKE`` is
    case-sensitive on PostgreSQL and case-insensitive on SQLite — the same
    statement must select the same rows on both.
    """
    normalized = _trim_content_type_sql(
        TestRunAttachment.content_type, dialect_name
    )
    return func.lower(normalized).like("image/%")


def _base_content_type_sql(dialect_name: str):
    """Normalised MIME base type, before parameters, for supported databases.

    Python and the frontend both split on the first semicolon and trim the
    resulting base type. SQL must do the same *before* choosing ``MIN(id)``;
    otherwise a valid value such as ``" image/jpeg ; charset=binary"`` is
    paintable in a detail gallery but silently excluded from list thumbnails.
    SQLite and PostgreSQL expose different delimiter functions, so this small
    adapter keeps the public selection semantics identical on both engines.
    """
    raw = TestRunAttachment.content_type
    if dialect_name == "postgresql":
        base = func.split_part(raw, ";", 1)
    else:
        # SQLite is the desktop/dev database. Keep it as the conservative
        # fallback too: unsupported dialects are outside the deployment
        # contract, while ``instr``/``substr`` are widely available.
        semicolon = func.instr(raw, ";")
        base = case(
            (semicolon > 0, func.substr(raw, 1, semicolon - 1)),
            else_=raw,
        )
    return func.lower(_trim_content_type_sql(base, dialect_name))


def is_displayable_image_sql(dialect_name: str):
    """SQL predicate for browser-paintable image MIME types.

    MIME comparison is case-insensitive, trims leading/trailing whitespace
    from the base type and permits parameters after a semicolon, matching the
    frontend's split/trim/lower normalisation.
    """
    normalized = _base_content_type_sql(dialect_name)
    return normalized.in_(sorted(_DISPLAYABLE_IMAGE_CONTENT_TYPES))


def _assembled_parts_for_parents(
    session: Session, parent_ids: Sequence[int]
) -> dict[int, list[Component]]:
    """The single definition of "the parts a component is assembled from".

    Direct children, plus one more hop through a child that is itself a module.
    That second hop is the stitch of an R3-R5 module: the full module's direct
    child is a half module, and the sensors, powerboard and hybrid assemblies
    hang off the half module rather than off the full module. Without it a
    stitched module shows its half modules and nothing they are made of — on
    the owner's mirror that hid 70 image-bearing and 114 evidence-bearing
    parts.

    The walk never follows a sensor's or powerboard's own children, so this
    stays the assembly relation the page displays rather than a tree walk.
    Two queries for any number of parents, never one per component: the
    gallery, the worksheet and the list column must agree on which parts belong
    to a component, and they can only agree by asking here.
    """
    parents = list(dict.fromkeys(parent_ids))
    if not parents:
        return {}
    parts: dict[int, list[Component]] = {parent_id: [] for parent_id in parents}
    stitched: dict[int, int] = {}
    for child in session.scalars(
        select(Component).where(Component.parent_id.in_(parents)).order_by(Component.sn)
    ):
        parts[child.parent_id].append(child)
        if (child.component_type or "").upper() == "MODULE":
            stitched[child.id] = child.parent_id
    if stitched:
        for grandchild in session.scalars(
            select(Component)
            .where(Component.parent_id.in_(stitched))
            .order_by(Component.sn)
        ):
            parts[stitched[grandchild.parent_id]].append(grandchild)
        for group in parts.values():
            group.sort(key=lambda component: component.sn)
    return parts


def assembled_parts(session: Session, parent_id: int) -> list[Component]:
    """The parts of one component; see :func:`_assembled_parts_for_parents`."""

    return _assembled_parts_for_parents(session, [parent_id]).get(parent_id, [])


def child_image_attachments(
    session: Session, parent_sn: str
) -> list[tuple[Component, list[AttachmentView]]]:
    """Stored images of the parts assembled into a component, grouped per part.

    An operator works on a module while the photographs hang on the parts
    bonded into it: in the owner's mirror 3 of 432 mirrored images sit on a
    module and 241 on sensors that are one module's direct child. Those images
    are unreachable from any module page as long as the index is filtered by
    serial number alone.

    One hop covers an unstitched module, but R3-R5 modules are stitched: the
    full module's direct child is a half module, and the sensors, powerboard
    and hybrid assemblies carrying the photographs are that half module's
    children. Stopping at one hop left 22 of the owner's module pages empty
    while their pictures existed one level below. So the walk takes a second
    hop, and only through a child that is itself a module — the stitch — never
    through a sensor's or powerboard's own children. That keeps the gallery to
    the assembly relation the page displays instead of walking the tree.

    Only images, and only rows that claim a file: this feeds a gallery, and
    pulling a sensor's several hundred instrument `.txt` rows into a module
    page would cost far more than it shows.

    A constant query set for the whole family, never one per child.
    """
    parent_id = session.scalar(select(Component.id).where(Component.sn == parent_sn))
    children = assembled_parts(session, parent_id) if parent_id is not None else []
    by_component = attachment_references_for_components(
        session,
        [child.sn for child in children],
        stored_images_only=True,
    )
    grouped: list[tuple[Component, list[AttachmentView]]] = []
    for child in children:
        unique: dict[tuple[str, str], AttachmentView] = {}
        for attachment in by_component[child.sn]:
            if attachment.relative_path is None or not attachment.is_image:
                continue
            unique.setdefault((attachment.source, attachment.pdb_code), attachment)
        if unique:
            grouped.append((child, list(unique.values())))
    return grouped


def attachment_counts_by_run(
    session: Session, component_sns: list[str] | tuple[str, ...]
) -> dict[str, dict[str, dict[str | None, int]]]:
    """Association counts keyed by component, test type and then run.

    A run reference is normally globally unique, but legacy/custom evidence
    may have no reference at all. Keeping the component in the key prevents
    several children's empty-reference buckets from leaking into one another;
    keeping the test type prevents two no-run associations on one component
    from being credited to both worksheet rows.
    """
    counts: dict[str, dict[str, dict[str | None, int]]] = {
        component_sn: {} for component_sn in dict.fromkeys(component_sns)
    }
    for component_sn, attachments in attachment_references_for_components(
        session, component_sns
    ).items():
        for attachment in attachments:
            by_run = counts[component_sn].setdefault(attachment.test_type, {})
            by_run[attachment.test_run_ref] = (
                by_run.get(attachment.test_run_ref, 0) + 1
            )
    return counts


def attachment_for_component(
    session: Session,
    component_sn: str,
    pdb_code: str,
    *,
    source: str | None = None,
) -> AttachmentView | None:
    """Resolve a binary route through an association, then legacy fields.

    ``source`` completes the blob's public identity. It stays optional so old
    bookmarked URLs remain usable; a new client always supplies it and can
    therefore address both blobs even if two sources reuse the same code.
    """
    reference_statement = (
        select(TestRunAttachmentReference, TestRunAttachment)
        .join(
            TestRunAttachment,
            TestRunAttachment.id == TestRunAttachmentReference.attachment_id,
        )
        .where(
            TestRunAttachmentReference.component_sn == component_sn,
            TestRunAttachment.pdb_code == pdb_code,
        )
        .order_by(TestRunAttachmentReference.id)
        .limit(1)
    )
    if source is not None:
        reference_statement = reference_statement.where(
            TestRunAttachment.source == source
        )
    row = session.execute(reference_statement).first()
    if row is not None:
        reference, attachment = row
        return _reference_view(attachment, reference)
    legacy_statement = (
        select(TestRunAttachment)
        .where(
            TestRunAttachment.component_sn == component_sn,
            TestRunAttachment.pdb_code == pdb_code,
        )
        .order_by(TestRunAttachment.id)
        .limit(1)
    )
    if source is not None:
        legacy_statement = legacy_statement.where(
            TestRunAttachment.source == source
        )
    attachment = session.scalar(legacy_statement)
    return _reference_view(attachment) if attachment is not None else None


def _own_thumbnail_attachments(
    session: Session,
    *,
    institute_code: str | None = None,
    limit: int | None = None,
    component_sns: Sequence[str] | None = None,
) -> list[tuple[str, TestRunAttachment]]:
    """One browser-displayable stored blob per component, with legacy fallback.

    Physical blobs are deduplicated globally, so grouping on the blob's legacy
    ``component_sn`` loses every additional component reference. The union,
    grouping and component limit therefore all stay in SQL: repeated run
    associations cannot make the endpoint materialise an unbounded candidate
    set before applying its public limit. Filtering unsupported formats before
    ``MIN(id)`` lets a later JPEG/PNG win over an older TIFF.

    ``component_sns`` restricts the candidates to a known set, which is how the
    part pass below asks the same question about an already bounded family.
    """
    dialect_name = session.get_bind().dialect.name
    reference_statement = (
        select(
            TestRunAttachmentReference.component_sn.label("component_sn"),
            TestRunAttachment.id.label("attachment_id"),
        )
        .join(
            TestRunAttachment,
            TestRunAttachment.id == TestRunAttachmentReference.attachment_id,
        )
        .where(
            TestRunAttachment.relative_path.is_not(None),
            is_displayable_image_sql(dialect_name),
        )
    )
    if component_sns is not None:
        reference_statement = reference_statement.where(
            TestRunAttachmentReference.component_sn.in_(component_sns)
        )
    if institute_code:
        reference_statement = reference_statement.join(
            Component, Component.sn == TestRunAttachmentReference.component_sn
        ).where(Component.institute_code == institute_code)

    matching_reference = exists().where(
        TestRunAttachmentReference.attachment_id == TestRunAttachment.id,
        TestRunAttachmentReference.component_sn == TestRunAttachment.component_sn,
    )
    legacy_statement = select(
        TestRunAttachment.component_sn.label("component_sn"),
        TestRunAttachment.id.label("attachment_id"),
    ).where(
        TestRunAttachment.relative_path.is_not(None),
        is_displayable_image_sql(dialect_name),
        ~matching_reference,
    )
    if component_sns is not None:
        legacy_statement = legacy_statement.where(
            TestRunAttachment.component_sn.in_(component_sns)
        )
    if institute_code:
        legacy_statement = legacy_statement.join(
            Component, Component.sn == TestRunAttachment.component_sn
        ).where(Component.institute_code == institute_code)
    candidates = reference_statement.union_all(legacy_statement).subquery()
    chosen = (
        select(
            candidates.c.component_sn,
            func.min(candidates.c.attachment_id).label("attachment_id"),
        )
        .group_by(candidates.c.component_sn)
        .order_by(candidates.c.component_sn)
    )
    if limit is not None:
        chosen = chosen.limit(limit)
    chosen = chosen.subquery()
    return list(
        session.execute(
            select(chosen.c.component_sn, TestRunAttachment)
            .join(TestRunAttachment, TestRunAttachment.id == chosen.c.attachment_id)
            .order_by(chosen.c.component_sn)
        )
    )


def thumbnail_attachments(
    session: Session,
    *,
    institute_code: str | None = None,
    limit: int = 2000,
) -> list[tuple[str, TestRunAttachment, Component | None]]:
    """One list tile per component: its own picture, else one of its parts'.

    Almost no photograph is taken of a module — 3 of 432 on the owner's mirror,
    the rest of the sensors, powerboards and hybrids built into it. Filtered by
    serial number alone the list column is therefore blank on nearly every
    module row while the pictures exist one hop away.

    So a component without a picture of its own borrows one from the parts it
    is assembled from (`assembled_parts`, which follows the R3-R5 stitch). The
    third element names that part, and is `None` when the tile is the
    component's own. It is not decoration: whose part is in the picture is part
    of what the picture says, so the caller must mark a borrowed tile rather
    than pass a sensor's photograph off as the module's.

    Own pictures win, and the borrow never enlarges the answer: `limit` bounds
    components in the own pass, and the part pass only fills rows already in
    that bounded set. Cost stays a fixed number of statements — two component
    queries for the whole family and one candidate query for all parts at once,
    never one per row.
    """
    capped_limit = max(1, min(limit, 5000))
    own = _own_thumbnail_attachments(
        session, institute_code=institute_code, limit=capped_limit
    )
    tiles: list[tuple[str, TestRunAttachment, Component | None]] = [
        (component_sn, attachment, None) for component_sn, attachment in own
    ]
    covered = {component_sn for component_sn, _ in own}

    listed = select(Component.id, Component.sn)
    if institute_code:
        listed = listed.where(Component.institute_code == institute_code)
    blank = [
        (component_id, component_sn)
        for component_id, component_sn in session.execute(
            listed.order_by(Component.sn).limit(capped_limit)
        )
        if component_sn not in covered
    ]
    if not blank:
        return sorted(tiles, key=lambda tile: tile[0])[:capped_limit]

    parts_by_parent = _assembled_parts_for_parents(
        session, [component_id for component_id, _ in blank]
    )
    part_sns = {part.sn for parts in parts_by_parent.values() for part in parts}
    if not part_sns:
        return sorted(tiles, key=lambda tile: tile[0])[:capped_limit]

    by_part = {
        part_sn: attachment
        for part_sn, attachment in _own_thumbnail_attachments(
            session, component_sns=sorted(part_sns)
        )
    }
    for component_id, component_sn in blank:
        for part in parts_by_parent.get(component_id, ()):
            attachment = by_part.get(part.sn)
            if attachment is not None:
                tiles.append((component_sn, attachment, part))
                break
    # Both passes are bounded by the same component limit, but they select
    # different components — the own pass takes the first N *with a picture*,
    # the borrow pass fills blanks among the first N overall. Cap the union so
    # the endpoint cannot return more components than it was asked for.
    return sorted(tiles, key=lambda tile: tile[0])[:capped_limit]


def attachment_read_model(
    settings: Any, attachment: TestRunAttachment | AttachmentView
) -> dict[str, Any]:
    """Return the public, local-only representation of a mirrored attachment.

    Deliberately omit the storage path and any remote source URL.  Both the
    regular test-run endpoint and the staged preview use this projection, so a
    raw share link (or a future signed URL) can never leak through one of the
    read models by accident.
    """
    return {
        "source": attachment.source,
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
    """Upsert the one physical blob row for ``(source, pdb_code)``.

    Component/run metadata on this legacy row is only a representative kept
    for backwards compatibility.  It must never be overwritten on reuse:
    the authoritative many-to-one associations live in
    ``TestRunAttachmentReference``.
    """
    existing = _existing_attachment_row(session, source, pdb_code)
    if existing is None:
        existing = TestRunAttachment(
            component_sn=component_sn,
            test_type=test_type,
            test_run_ref=test_run_ref,
            source=source,
            pdb_code=pdb_code,
            filename=filename,
            content_type=content_type,
            title=title,
        )
        session.add(existing)
    # A PDB listing usually declares no content type at all. The real one is
    # sniffed from the response when the file is downloaded, and `is_image`
    # derives from it — so letting a later listing overwrite a type the
    # download already established turns every mirrored image invisible. That
    # is not hypothetical: a whole-site re-sweep once reused 3734 files and
    # blanked 430 of 432 images this way, because the reuse path returns
    # before the line that writes the sniffed type back.
    if existing.downloaded_at is None or content_type is not None:
        existing.content_type = content_type
    existing.synced_at = utcnow()
    return existing


def _upsert_reference(
    session: Session,
    attachment: TestRunAttachment,
    *,
    component_sn: str,
    test_type: str,
    test_run_ref: str | None,
    filename: str | None,
    title: str | None,
) -> TestRunAttachmentReference:
    """Upsert one component/test-run association to a physical blob."""
    run_key = test_run_ref or ""
    identity = [
        TestRunAttachmentReference.attachment_id == attachment.id,
        TestRunAttachmentReference.component_sn == component_sn,
        TestRunAttachmentReference.test_run_ref == run_key,
    ]
    if not run_key:
        # A real run id is the stable upstream identity and its test type is
        # updateable metadata. Without one, test type is the only field that
        # keeps two valid associations on the same component distinct.
        identity.append(TestRunAttachmentReference.test_type == test_type)
    reference = session.scalar(
        select(TestRunAttachmentReference)
        .where(*identity)
        .order_by(TestRunAttachmentReference.id)
    )
    if reference is None:
        reference = TestRunAttachmentReference(
            attachment_id=attachment.id,
            component_sn=component_sn,
            test_run_ref=run_key,
            test_type=test_type,
        )
        session.add(reference)
    reference.test_type = test_type
    reference.filename = filename
    reference.title = title
    reference.synced_at = utcnow()
    return reference


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


def _write_temp_bytes(root: Path, relative_path: str, data: bytes) -> Path:
    """Write attachment bytes to an owner-scoped ``.part`` staging file.

    Never the final name: a reader must never be able to open a half-written
    attachment. Bytes are fully in hand before this is called (no network
    happens while this — or any later disk write — is in progress).

    The kernel creates an exclusive, unpredictable sibling for every fetch.
    That matters across processes: the in-memory blob-key locks coordinate
    threads in one server process, but an old packaged worker and its retry
    have separate lock registries. They must never truncate the same staging
    path or unlink each other's bytes after one of them loses its lease fence.
    """
    target = (root / relative_path).resolve()
    if not target.is_relative_to(root):
        raise ValueError("refusing to write an attachment outside its directory")
    target.parent.mkdir(parents=True, exist_ok=True)
    temp: Path | None = None
    file_descriptor = -1
    try:
        file_descriptor, raw_temp_path = tempfile.mkstemp(
            prefix=f".{target.name}.",
            suffix=".part",
            dir=target.parent,
        )
        temp = Path(raw_temp_path)
        with os.fdopen(file_descriptor, "wb") as handle:
            file_descriptor = -1
            handle.write(data)
    except OSError:
        if file_descriptor >= 0:
            os.close(file_descriptor)
        if temp is not None:
            temp.unlink(missing_ok=True)
        raise
    assert temp is not None
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


class _ShareLinkSkipped(RuntimeError):
    """A share attachment needs user action instead of another retry."""

    def __init__(self, *, authentication_required: bool) -> None:
        super().__init__("Share-link attachment requires user intervention.")
        self.authentication_required = authentication_required


# HTTP statuses worth retrying: request timeout, too-early, rate limit, 5xx.
_TRANSIENT_HTTP_STATUSES = frozenset({408, 425, 429})

# 5xx statuses that are a permanent statement about capability, not an outage.
# Retrying them cannot help, and treating them as transient is worse than
# merely wasteful: measured against the live TUDO mirror, CERNBox answers
# `501 Not Implemented` for a DAV request against a *folder* share, and 87
# consecutive attachments point into one such share. Classified as transient,
# each burned its full retry ladder and the run of them tripped the outage
# breaker, so every sweep aborted at the same file while the PDB itself was
# answering perfectly. 505 is the same kind of answer.
_PERMANENT_5XX_STATUSES = frozenset({501, 505})

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
            if status in _TRANSIENT_HTTP_STATUSES:
                return True
            return 500 <= status < 600 and status not in _PERMANENT_5XX_STATUSES

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
        authorization = req.get_header("Authorization")
        if authorization:
            previous = urlsplit(req.full_url)
            following = urlsplit(newurl)
            try:
                previous_port = previous.port or (
                    443 if previous.scheme.lower() == "https" else 80
                )
                following_port = following.port or (
                    443 if following.scheme.lower() == "https" else 80
                )
                same_origin = (
                    previous.hostname is not None
                    and following.hostname is not None
                    and previous.scheme.lower() == following.scheme.lower()
                    and previous.hostname.rstrip(".").lower()
                    == following.hostname.rstrip(".").lower()
                    and previous_port == following_port
                )
            except ValueError:
                same_origin = False
            if not same_origin:
                raise HTTPError(
                    newurl,
                    code,
                    "Credential-bearing attachment redirect refused",
                    headers,
                    fp,
                )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _share_authorization(password: str) -> str:
    token = base64.b64encode(f"public:{password}".encode()).decode("ascii")
    return f"Basic {token}"


def _open_public_url(url: str, timeout: int, password: str | None = None):
    opener = build_opener(_SafeShareRedirects())
    request_headers = {"User-Agent": "itkFlow attachment mirror"}
    if password is not None:
        request_headers["Authorization"] = _share_authorization(password)
    request = Request(url, headers=request_headers)
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


# --- archives served in place of a file -------------------------------------
#
# A *folder* share does not serve bytes over WebDAV. Measured live and
# anonymously against the owner's own share links on 2026-08-27:
#
#   /files/link/public/<token>/<name>          200 text/html (the web app)
#   /remote.php/dav/public-files/<token>[/...] 501 Not Implemented
#   /s/<token>/download?files=<name>           200 application/octet-stream,
#                                              chunked, and a POSIX **ustar**
#                                              archive - not a zip
#   /s/<token>/download?path=/&files=<name>    500 Internal Server Error
#   /s/<token>/download                        200, the *whole* share as one
#                                              archive (minutes, never used)
#
# So the bytes exist, but only inside an archive, and unpacking one is the
# single most dangerous thing this module does: the archive comes from a
# remote host, its member names are attacker-influenceable, and the result is
# written to an operator's disk. The rules below are therefore absolute.
#
#   * `extractall` is never called and no member is ever written under its own
#     name. Exactly one member is selected and read **into memory**; the bytes
#     then take the ordinary storage path, whose file name is derived from the
#     PDB attachment code and an extension allowlist.
#   * Only regular files are eligible. Directories, symlinks, hardlinks,
#     devices, fifos and GNU sparse entries are refused by type, before their
#     name is even looked at.
#   * Names are refused on `..`, a leading `/`, a backslash, a colon (drive
#     letters, NTFS streams), NUL and control characters.
#   * Sizes are checked twice: the declared size decides whether a member is
#     read at all, and the bytes actually read must match it exactly.
#   * The archive as a whole is capped in compressed bytes off the wire, in
#     decompressed tar bytes (including headers and GNU/PAX metadata), in
#     declared member bytes, and in member count.
#
# Extraction *filters* (`tarfile.data_filter`, Python 3.12 / 3.10.12+) are not
# relied upon: they sanitise a tree being written to disk, and this code never
# writes a tree. The runtime here is 3.10.11, where they do not exist at all.
# The equivalent checks are implemented directly above and each has a test.

# Enough to cover the ustar magic at offset 257 of the first header block.
_ARCHIVE_SNIFF_BYTES = 512
# A gzip header can legally carry optional extra/name/comment fields before
# the deflate stream. Inspect a larger but still fixed prefix only after gzip
# magic was seen; ordinary files retain the small 512-byte sniff. Headers that
# do not terminate inside this ceiling are refused instead of being stored as
# an opaque pseudo-file. A separate bounded probe follows the complete header:
# otherwise a legal header ending at the ceiling would leave no compressed
# bytes from which to distinguish a tar from an ordinary gzip file.
_GZIP_ARCHIVE_SNIFF_BYTES = 128 * 1024
_GZIP_DEFLATE_SNIFF_BYTES = 128 * 1024
_USTAR_MAGIC_OFFSET = 257
_USTAR_MAGIC = b"ustar"
_GZIP_MAGIC = b"\x1f\x8b"

# Enough bytes for every magic check below. This is the only part of a new
# candidate held alongside the current best full member while its rank is
# decided.
_MEMBER_CONTENT_SNIFF_BYTES = 512
_MEMBER_READ_CHUNK_BYTES = 64 * 1024

# A share folder holds a handful of files. Thousands of members is not a
# folder share, it is either a mistake or an attempt to make this loop the
# expensive part of a sweep.
ARCHIVE_MEMBER_LIMIT = 2048

# How much bigger than one attachment an archive is allowed to be. The
# operator configures `attachment_max_bytes` for a *file*; an archive
# legitimately carries several (the owner's largest measured share folder
# declares 79 MB around an 8.8 MB picture), so the budget is a multiple of the
# same setting rather than a second knob that could be forgotten. Deliberately
# derived: lowering the attachment limit lowers this one too.
ARCHIVE_SIZE_BUDGET_FACTOR = 4

# Leading bytes that identify a stored format better than any remote-supplied
# name can. Sniffing wins over the member's extension for exactly that reason.
_CONTENT_TYPE_BY_MAGIC = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"BM", "image/bmp"),
    (b"II*\x00", "image/tiff"),
    (b"MM\x00*", "image/tiff"),
    (b"%PDF-", "application/pdf"),
)


class _ArchiveRefused(ValueError):
    """Marker: the archive broke one of the limits above and is not usable.

    A refusal, never a retry: the same archive would break the same limit
    again. Carries a short static reason only — never a member name, never a
    URL.
    """


class _CappedStream:
    """A readable byte stream with a hard ceiling and a small pushback buffer.

    Two jobs. The ceiling is what stops a remote host from streaming for as
    long as it likes into a sweep that has no idea how much it has taken; the
    pushback buffer is what lets the first bytes be sniffed for an archive
    signature without consuming them, so the ordinary "read the file" path
    stays byte-for-byte what it was.

    Reads are passed straight through, one call at a time, exactly like the
    plain ``response.read(n)`` this replaced. Nothing here ever buffers more
    than the sniff window. The same wrapper also sits *after* gzip
    decompression: tar readers consume GNU longname and PAX records before
    yielding a member, so declared member sizes alone cannot bound that
    attacker-controlled metadata.
    """

    def __init__(
        self,
        response: Any,
        limit: int,
        *,
        refusal_reason: str = "the archive exceeded its byte budget",
    ) -> None:
        self._response = response
        self._limit = max(1, int(limit))
        self._refusal_reason = refusal_reason
        self._buffer = b""
        self.consumed = 0

    def _pull(self, size: int) -> bytes:
        if size <= 0:
            return b""
        if self.consumed >= self._limit:
            raise _ArchiveRefused(self._refusal_reason)
        chunk = self._response.read(min(size, self._limit - self.consumed + 1))
        if not isinstance(chunk, (bytes, bytearray)):
            return b""
        chunk = bytes(chunk)
        self.consumed += len(chunk)
        if self.consumed > self._limit:
            raise _ArchiveRefused(self._refusal_reason)
        return chunk

    def peek(self, size: int) -> bytes:
        """Buffer and return up to ``size`` leading bytes without consuming."""
        while len(self._buffer) < size:
            chunk = self._pull(size - len(self._buffer))
            if not chunk:
                break
            self._buffer += chunk
        return self._buffer[:size]

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            size = self._limit - self.consumed + len(self._buffer)
        if not self._buffer:
            return self._pull(size)
        taken = self._buffer[:size]
        self._buffer = self._buffer[len(taken) :]
        if len(taken) >= size:
            return taken
        return taken + self._pull(size - len(taken))


def _archive_stream_mode(head: bytes) -> str | None:
    """Whether these leading bytes open an archive, and how to read it.

    Only two transports are accepted: an uncompressed POSIX tar and a
    gzip-compressed one, because those are what a share host actually serves
    and gzip is in the standard library. bzip2 and xz are refused by omission
    — nothing has ever been observed serving them here, and they are the two
    formats with the most extreme decompression ratios.

    A gzip stream is only accepted once the ustar magic has been found in its
    *decompressed* prefix. That keeps a gzip-compressed ordinary file (which
    would otherwise be mistaken for an archive and lost) on the normal path.
    """
    if head[_USTAR_MAGIC_OFFSET : _USTAR_MAGIC_OFFSET + len(_USTAR_MAGIC)] == _USTAR_MAGIC:
        return "r|"
    if head[: len(_GZIP_MAGIC)] != _GZIP_MAGIC:
        return None
    try:
        prefix = zlib.decompressobj(wbits=31).decompress(
            head, _USTAR_MAGIC_OFFSET + len(_USTAR_MAGIC)
        )
    except zlib.error:
        return None
    if prefix[_USTAR_MAGIC_OFFSET : _USTAR_MAGIC_OFFSET + len(_USTAR_MAGIC)] == _USTAR_MAGIC:
        return "r|gz"
    return None


def _gzip_header_end(head: bytes) -> int | None:
    """Offset after a complete gzip header, bounded by the supplied prefix."""
    if len(head) < 10 or head[: len(_GZIP_MAGIC)] != _GZIP_MAGIC:
        return None
    flags = head[3]
    offset = 10
    if flags & 0x04:  # FEXTRA
        if len(head) < offset + 2:
            return None
        extra_size = int.from_bytes(head[offset : offset + 2], "little")
        offset += 2 + extra_size
        if len(head) < offset:
            return None
    for flag in (0x08, 0x10):  # FNAME, FCOMMENT
        if flags & flag:
            terminator = head.find(b"\x00", offset)
            if terminator < 0:
                return None
            offset = terminator + 1
    if flags & 0x02:  # FHCRC
        offset += 2
    return offset if len(head) >= offset else None


def _sniff_archive_stream_mode(stream: _CappedStream) -> str | None:
    """Detect tar transports with separate bounded header/deflate probes."""
    head = stream.peek(_ARCHIVE_SNIFF_BYTES)
    mode = _archive_stream_mode(head)
    if mode is not None or head[: len(_GZIP_MAGIC)] != _GZIP_MAGIC:
        return mode

    header_probe = stream.peek(_GZIP_ARCHIVE_SNIFF_BYTES)
    header_end = _gzip_header_end(header_probe)
    if header_end is None:
        raise _ArchiveRefused("the gzip header exceeded its byte budget or was incomplete")

    # The header may end on the final byte of its own budget. Probe a second,
    # independent and bounded region for enough deflate output to classify the
    # payload. A valid short ordinary gzip reaches EOF; a longer ordinary gzip
    # yields the full prefix without the ustar magic. An undecidable stream is
    # refused rather than silently stored as an opaque successful attachment.
    extended = stream.peek(header_end + _GZIP_DEFLATE_SNIFF_BYTES)
    try:
        detector = zlib.decompressobj(wbits=31)
        prefix = detector.decompress(
            extended, _USTAR_MAGIC_OFFSET + len(_USTAR_MAGIC)
        )
    except zlib.error:
        # Gzip magic alone does not make arbitrary bytes an archive. Preserve
        # the ordinary-file path for a malformed/non-gzip payload, as before.
        return None
    if prefix[
        _USTAR_MAGIC_OFFSET : _USTAR_MAGIC_OFFSET + len(_USTAR_MAGIC)
    ] == _USTAR_MAGIC:
        return "r|gz"
    if len(prefix) >= _USTAR_MAGIC_OFFSET + len(_USTAR_MAGIC) or detector.eof:
        return None
    raise _ArchiveRefused(
        "the gzip payload did not yield enough bytes inside its sniff budget"
    )


def safe_archive_member_name(info: Any) -> str | None:
    """Normalise one archive member's name, or refuse it.

    Refuses everything that is not a plain regular file and every name that
    could address something other than a plain relative path: `..` anywhere,
    a leading `/`, a backslash (Windows separator), a colon (drive letter or
    NTFS stream), NUL and any other control character. `./` prefixes are
    normalised away because GNU tar writes them routinely.

    Public because the guard is worth testing on its own — every rule here is
    one that a single missing line would silently remove.
    """
    if getattr(info, "type", None) not in (tarfile.REGTYPE, tarfile.AREGTYPE):
        return None
    # PAX sparse entries can present as REGTYPE/isreg(), unlike the dedicated
    # GNU sparse type. `issparse()` is therefore a separate mandatory guard.
    is_sparse = getattr(info, "issparse", None)
    if callable(is_sparse) and is_sparse():
        return None
    name = getattr(info, "name", None)
    if not isinstance(name, str) or not name:
        return None
    if name.startswith("/") or "\\" in name or ":" in name:
        return None
    if any(character < " " or character == "\x7f" for character in name):
        return None
    parts: list[str] = []
    for segment in name.split("/"):
        if segment in ("", "."):
            continue
        if segment == "..":
            return None
        parts.append(segment)
    if not parts:
        return None
    return "/".join(parts)


def _member_is_in_scope(name: str, wanted: str) -> bool:
    """Whether a member lies at, or inside, the path the descriptor asked for.

    This is the guard against substitution. The descriptor names one entry of
    the share; anything the host puts *outside* that entry is not the file
    that was asked for, however plausible it looks. Measured: requesting the
    whole share instead of one entry really does answer with a different tree
    (rooted at the share token), and that tree must select nothing.
    """
    if not wanted:
        return True
    return name == wanted or name.startswith(wanted + "/")


def _member_rank(name: str, wanted: str, content_type: str | None) -> int:
    """Preference order among members that are all legitimate candidates.

    Lower wins; ties between distinct members are broken by the member path.
    Duplicate normalised paths are handled before this function and keep their
    first eligible occurrence. Being explicit here is the whole point: a
    folder share can hold several files, and a wrong file stored under the
    right attachment code would look correct forever.

      0  the entry the descriptor named, exactly
      1  bytes sniffed as an image format a browser can paint
      2  bytes sniffed as another real image format (for example TIFF)
      3  any other format the mirror is willing to write an extension for
      4  everything else (stored without an extension, so nothing can open it)
    """
    if wanted and name == wanted:
        return 0
    suffix = Path(name).suffix.lower()
    if content_type in _DISPLAYABLE_IMAGE_CONTENT_TYPES:
        return 1
    if content_type and content_type.startswith("image/"):
        return 2
    declared_type = _CONTENT_TYPE_BY_EXTENSION.get(suffix)
    if (
        content_type
        or suffix in _TRUSTED_DATA_SUFFIXES
        or (declared_type is not None and not declared_type.startswith("image/"))
    ):
        return 3
    return 4


def _sniffed_content_type(data: bytes) -> str | None:
    """The stored format according to the bytes themselves.

    Preferred over the member's extension, because the extension is part of
    the name the remote host chose and the bytes are the thing being stored.
    """
    for magic, content_type in _CONTENT_TYPE_BY_MAGIC:
        if data.startswith(magic):
            return content_type
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if len(data) >= 16 and data[4:8] == b"ftyp":
        box_size = int.from_bytes(data[:4], "big")
        box_end = min(len(data), box_size) if box_size >= 16 else len(data)
        brands = [data[8:12]]
        brands.extend(data[index : index + 4] for index in range(16, box_end, 4))
        if any(brand in {b"avif", b"avis"} for brand in brands):
            return "image/avif"
    sample = data.lstrip()
    if sample.startswith(b"\xef\xbb\xbf"):
        sample = sample[3:].lstrip()
    if re.match(br"<svg(?:\s|>)", sample, flags=re.IGNORECASE):
        return "image/svg+xml"
    return None


def _member_content_type(name: str, data: bytes) -> str | None:
    return _sniffed_content_type(data) or _CONTENT_TYPE_BY_EXTENSION.get(
        Path(name).suffix.lower()
    )


def _archive_member(
    stream: _CappedStream, *, mode: str, wanted: str, max_bytes: int, budget: int
) -> tuple[str, bytes] | None:
    """Select and read **one** member of a streamed archive. Never extracts.

    Single forward pass: the archive is read straight off the socket and is
    never materialised, so memory is bounded by one full member plus a fixed
    sniff prefix, not by the archive. The best candidate seen so far is kept
    while at most 512 bytes of a possible successor establish its MIME rank,
    then dropped *before* the successor's remaining body is read.

    Returns the chosen member's normalised path and its bytes, or ``None``
    when nothing in the archive is the file that was asked for. Raises
    ``_ArchiveRefused`` when the archive itself breaks a limit.
    """
    # `tarfile`'s built-in `r|gz` stream accounts only for compressed reads on
    # our outer wrapper. Decompress explicitly and put a second cap before the
    # tar parser so headers, padding, GNU longnames and PAX records all consume
    # the same total archive budget as ordinary member bytes.
    gzip_reader: gzip.GzipFile | None = None
    archive_stream: Any = stream
    archive_mode = mode
    if mode == "r|gz":
        gzip_reader = gzip.GzipFile(fileobj=stream, mode="rb")
        archive_stream = _CappedStream(
            gzip_reader,
            budget,
            refusal_reason="the decompressed archive exceeded its byte budget",
        )
        archive_mode = "r|"

    archive: tarfile.TarFile | None = None
    try:
        try:
            archive = tarfile.open(fileobj=archive_stream, mode=archive_mode)
        except (tarfile.TarError, gzip.BadGzipFile, EOFError, zlib.error):
            return None
        try:
            return _walk_archive(archive, wanted=wanted, max_bytes=max_bytes, budget=budget)
        except (tarfile.TarError, gzip.BadGzipFile, EOFError, zlib.error):
            # Truncated or malformed. Never a partial store, and never a generic
            # exception either: this is a verdict about the archive, so it is
            # logged and counted as one rather than guessed at by the network
            # error classifier.
            raise _ArchiveRefused("the archive could not be read to its end") from None
    finally:
        if archive is not None:
            archive.close()
        if gzip_reader is not None:
            gzip_reader.close()


def _walk_archive(
    archive: Any, *, wanted: str, max_bytes: int, budget: int
) -> tuple[str, bytes] | None:
    """The single forward pass of ``_archive_member``. See its docstring."""
    best_key: tuple[int, str] | None = None
    best_name = ""
    best_bytes: bytes | None = None
    eligible = 0
    members = 0
    declared_total = 0
    seen_paths: set[str] = set()

    for info in archive:
        members += 1
        if members > ARCHIVE_MEMBER_LIMIT:
            raise _ArchiveRefused("the archive declares too many members")
        size = getattr(info, "size", 0)
        size = int(size) if isinstance(size, int) else 0
        if size < 0:
            raise _ArchiveRefused("an archive member declares a negative size")
        declared_total += size
        if declared_total > budget:
            raise _ArchiveRefused("the archive members declare more bytes than allowed")

        name = safe_archive_member_name(info)
        if name is None or not _member_is_in_scope(name, wanted):
            continue
        # The declared size decides whether the member is read at all, so
        # an oversized one costs nothing but its header.
        if size > max_bytes:
            continue
        # Tar permits duplicate names. Treat the first eligible occurrence as
        # authoritative so byte-distinct duplicates cannot change the result
        # later merely because their sniffed MIME rank differs.
        if name in seen_paths:
            continue
        seen_paths.add(name)
        eligible += 1

        # An exact path has rank 0; every other member has a best possible rank
        # of 1. If even that optimistic key cannot win, tarfile can stream past
        # the member without allocating any of its payload.
        optimistic_key = (0 if wanted and name == wanted else 1, name)
        if best_key is not None and optimistic_key >= best_key:
            continue
        handle = archive.extractfile(info)
        if handle is None:
            continue
        prefix_size = min(size, _MEMBER_CONTENT_SNIFF_BYTES)
        prefix = handle.read(prefix_size)
        if not isinstance(prefix, (bytes, bytearray)) or len(prefix) != prefix_size:
            raise _ArchiveRefused("an archive member did not deliver its declared size")
        prefix = bytes(prefix)
        key = (_member_rank(name, wanted, _sniffed_content_type(prefix)), name)
        if best_key is not None and key >= best_key:
            continue

        # Release the weaker candidate before reading the better one's body.
        # Only the fixed-size sniff prefix overlaps it in memory.
        best_key, best_name, best_bytes = None, "", None
        payload = BytesIO()
        payload.write(prefix)
        remaining = size - len(prefix)
        while remaining:
            chunk = handle.read(min(remaining, _MEMBER_READ_CHUNK_BYTES))
            if not isinstance(chunk, (bytes, bytearray)) or not chunk:
                raise _ArchiveRefused(
                    "an archive member did not deliver its declared size"
                )
            if len(chunk) > remaining:
                raise _ArchiveRefused(
                    "an archive member delivered more than its declared size"
                )
            payload.write(chunk)
            remaining -= len(chunk)
        data = payload.getvalue()
        if len(data) != size:
            # Defence in depth, and honest about it: the streaming reader used
            # here raises on a short member before this line can see one, so
            # this catches only a reader that would tolerate the short read.
            # What no tar reader can catch is a header that *overstates* a
            # real file's length — the surplus is simply the archive's own
            # padding, which is why the extracted bytes still go through the
            # HTML guard, the size limit and content sniffing below.
            raise _ArchiveRefused("an archive member did not deliver its declared size")
        best_key, best_name, best_bytes = key, name, data

    if best_bytes is None:
        return None
    if not wanted and eligible != 1:
        # Nothing in the URL says which entry is meant, so only an archive
        # holding exactly one candidate is unambiguous. Guessing here is how a
        # wrong file ends up under a right code.
        return None
    return best_name, best_bytes


# Web *file-browser* routes of an ownCloud/Reva deployment (CERNBox, DESY
# syncandshare, Nextcloud). These address a signed-in session's own storage,
# not a public share: there is no share token to turn into a download route,
# itkFlow holds no credentials for them and never will (ADR 006, point 6), and
# every request returns the same login-walled single-page app. Recognising the
# shape lets the mirror refuse such a link once and for free, instead of
# fetching the same HTML page on every sweep forever.
_PRIVATE_WEB_UI_ROUTES = (("apps", "files"), ("files", "spaces"))

# The web UI's own route to a *public* share: `/files/link/public/<token>` for
# a shared file, plus one or more path segments when the share is a folder.
_PUBLIC_SHARE_WEB_ROUTE = ("files", "link", "public")


def _dav_public_url(base: tuple[str, str], token: str, rest: list[str]) -> str:
    """The WebDAV route that serves a public share's bytes."""
    return urlunsplit((*base, "/".join(["/remote.php/dav/public-files", token, *rest]), "", ""))


def _archive_public_url(base: tuple[str, str], token: str, rest: list[str]) -> str:
    """The route that answers for a *folder* share, with an archive.

    `?files=<entry>` is the only form measured to work: `?path=/&files=<entry>`
    answers 500, and `?path=/<entry>` answers with the whole share instead of
    the entry. The entry is url-decoded first so `urlencode` cannot encode an
    already-encoded name twice.
    """
    query = urlencode({"files": unquote("/".join(rest))})
    return urlunsplit((*base, f"/s/{token}/download", query, ""))


def _share_member_path(url: str) -> str:
    """The path *inside* a share that a URL names, decoded; "" when it names none.

    This is what an archive member is matched against, so it is the decoded
    form rather than the wire form.
    """
    parsed = urlsplit(url)
    routed = [
        segment
        for segment in parsed.path.rstrip("/").split("/")
        if segment and segment != "index.php"
    ]
    if tuple(routed[:3]) == _PUBLIC_SHARE_WEB_ROUTE and len(routed) >= 4:
        return unquote("/".join(routed[4:]))
    return ""


def _share_link_candidates(url: str) -> list[str]:
    """URLs to try for one public share link, most direct first.

    An empty list means "do not even ask": the URL is recognisably not a
    public share (see ``_PRIVATE_WEB_UI_ROUTES``).

    ownCloud/Reva-family shares (CERNBox, DESY syncandshare, …) render an
    HTML viewer page at the plain ``/s/<token>`` URL — verified live: it
    answers 200 ``text/html`` while the file itself sits behind two stable
    routes. Preferred is ``remote.php/dav/public-files/<token>`` (it also
    reports a content length), then ``/s/<token>/download``; the original URL
    stays as the last resort for providers that do serve bytes directly.
    ``/index.php/s/<token>/download`` is deliberately never generated — that
    form failed name resolution during the live validation.

    The same share also has a *web UI* address,
    ``/files/link/public/<token>[/<path inside the share>]``, and links pasted
    out of a browser carry that form: 20 powerboard pictures in the owner's
    mirror do, were never rewritten, received the single-page app's HTML and
    were correctly refused, so their bytes were never stored. It maps onto the
    same DAV route, path and all.

    For that folder form the DAV route answers ``501 Not Implemented`` — a
    statement about capability that no credential changes — so a third
    candidate follows it: ``/s/<token>/download?files=<entry>``. That one
    answers, but with a **tar archive** rather than the file (measured live,
    ustar magic at byte 257; the "zip" this comment once claimed was wrong).
    The archive is unpacked in memory and exactly the named entry is stored;
    see ``_archive_member``. A bare ``/s/<token>/download`` is never generated
    for a folder share: it answers with the *whole* share, and storing an
    arbitrary part of that under one attachment's code is exactly the failure
    a missing file is preferable to.

    The pattern is recognised by URL *shape* (a ``/s/<token>`` or
    ``/files/link/public/<token>`` path), not by host name: this is a
    share-provider convention, not an institute detail.
    """
    parsed = urlsplit(url)
    path = parsed.path.rstrip("/")
    if path.endswith("/download") or "/download/" in path:
        return [url]
    segments = [segment for segment in path.split("/") if segment]
    # `index.php` is an optional prefix of every route in this family.
    routed = [segment for segment in segments if segment != "index.php"]
    base = (parsed.scheme, parsed.netloc)
    if tuple(routed[:2]) in _PRIVATE_WEB_UI_ROUTES:
        return []
    if tuple(routed[:3]) == _PUBLIC_SHARE_WEB_ROUTE and len(routed) >= 4:
        token, rest = routed[3], routed[4:]
        candidates = [_dav_public_url(base, token, rest)]
        if rest:
            candidates.append(_archive_public_url(base, token, rest))
        else:
            candidates.append(urlunsplit((*base, f"/s/{token}/download", "", "")))
        candidates.append(url)
        return candidates
    if len(segments) >= 2 and segments[-2] == "s":
        token = segments[-1]
        return [
            _dav_public_url(base, token, []),
            urlunsplit((*base, f"/s/{token}/download", "", "")),
            url,
        ]
    return [url]


def _fetch_share_link(
    descriptor: dict[str, Any],
    *,
    timeout: int,
    max_bytes: int,
    share_passwords: SharePasswordResolver,
) -> tuple[bytes, str | None] | None:
    url = descriptor.get("url")
    if not isinstance(url, str) or not _safe_http_url(url):
        raise _ShareLinkSkipped(authentication_required=False)
    candidates = _share_link_candidates(url)
    if not candidates:
        # Not a public share at all but a personal web-UI location (one such
        # row is in the owner's mirror). No request is made, this sweep or any
        # later one: asking again cannot start working, and the answer would
        # be the same login page every time. Never log the URL itself.
        log.info(
            "Share-link attachment %s addresses a private web-UI location rather "
            "than a public share; skipped without a request.",
            descriptor.get("code"),
        )
        raise _ShareLinkSkipped(authentication_required=True)
    share_password = share_passwords.password_for_url(url)
    wanted = _share_member_path(url)
    archive_budget = max_bytes * ARCHIVE_SIZE_BUDGET_FACTOR
    transient_seen = False
    html_seen = False
    authentication_seen = False
    archive_response_seen = False
    for candidate in candidates:
        if not _safe_http_url(candidate):
            continue
        try:
            response_handle = (
                _open_public_url(candidate, timeout, share_password)
                if share_password is not None
                else _open_public_url(candidate, timeout)
            )
            with closing(response_handle) as response:
                final_url = getattr(response, "geturl", lambda u=candidate: u)()
                if not isinstance(final_url, str) or not _safe_http_url(final_url):
                    continue
                stream = _CappedStream(response, archive_budget)
                mode = _sniff_archive_stream_mode(stream)
                if mode is None:
                    data = stream.read(max_bytes + 1)
                    content_type = _response_content_type(response)
                else:
                    archive_response_seen = True
                    # A folder share answers with an archive. Take the one
                    # member the descriptor asked for and nothing else — and
                    # send it through exactly the same guards below, because
                    # an archive is a new transport, not a new trust level.
                    selected = _archive_member(
                        stream,
                        mode=mode,
                        wanted=wanted,
                        max_bytes=max_bytes,
                        budget=archive_budget,
                    )
                    if selected is None:
                        log.warning(
                            "Share-link attachment %s answered with an archive holding no "
                            "unambiguous match for the entry it names. Nothing was stored.",
                            descriptor.get("code"),
                        )
                        continue
                    member_name, data = selected
                    content_type = _member_content_type(member_name, data)
                    # Size and type, never the member's name: it is chosen by
                    # a remote host and can carry somebody's name (CLAUDE.md,
                    # hard rule 3 — no personal data in logs). Which member
                    # was picked stays reconstructible from the selection
                    # rule, which is a pure function of the archive's content
                    # and written down in docs/12 §2.3a.
                    log.info(
                        "Share-link attachment %s was unpacked from an archive; "
                        "stored one selected member (%d bytes, %s).",
                        descriptor.get("code"),
                        len(data),
                        content_type or "unknown type",
                    )
        except _ArchiveRefused as refusal:
            archive_response_seen = True
            # A limit was broken, not a network hiccup: the same archive would
            # break it again, so this candidate is finished for this sweep.
            log.warning(
                "Share-link attachment %s answered with an archive that was refused: %s. "
                "Nothing was stored.",
                descriptor.get("code"),
                refusal,
            )
            continue
        except HTTPError as exc:
            if exc.code in {401, 403}:
                authentication_seen = True
            else:
                # Do not stringify: urllib errors may carry the complete URL.
                transient_seen = transient_seen or is_transient_download_error(exc)
            continue
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
    if archive_response_seen:
        # A real archive is proof that the public route was reachable. If its
        # named member was unsafe, ambiguous, malformed, or HTML, a later
        # viewer-page fallback must not relabel that content failure as a
        # missing password.
        return None
    if authentication_seen:
        raise _ShareLinkSkipped(authentication_required=True)
    if html_seen:
        # Storing the page would fake a mirrored attachment that renders as a
        # broken image. Log the code (never the URL) so the miss is visible.
        log.warning(
            "Share-link attachment %s only served HTML pages; the share may be "
            "expired or require sign-in. Nothing was stored.",
            descriptor.get("code"),
        )
        raise _ShareLinkSkipped(authentication_required=True)
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
    share_passwords: SharePasswordResolver | None = None,
) -> tuple[bytes, str | None] | None:
    if descriptor.get("source") == "share_link":
        return _fetch_share_link(
            descriptor,
            timeout=timeout,
            max_bytes=max_bytes,
            share_passwords=share_passwords or SharePasswordResolver(),
        )
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


# Consecutive transient-failure budget before a sweep concludes that the
# network (not the individual files) is down. Each transient file failure has
# already burned its complete retry ladder (attempts x read timeout plus
# backoff, minutes per file), so five in a row is a strong outage signal —
# while hundreds of pending files would otherwise crawl for hours at zero
# progress (docs/09).
ATTACHMENT_OUTAGE_BREAKER_THRESHOLD = 5


PDB_ROUTE = "pdb"


def descriptor_route(descriptor: Mapping[str, Any]) -> str:
    """Which remote a descriptor is fetched from.

    Attachments do not all come from the same place, and they fail
    independently: the PDB serves the binary store, EOS serves signed
    downloads, and zFlow-era results point at institute share hosts. Grouping
    by remote is what lets one unreachable host be contained instead of
    stopping the sweep.
    """

    if descriptor.get("source") == "share_link" or descriptor.get("type") == "eos":
        url = descriptor.get("url")
        if isinstance(url, str) and url:
            host = urlsplit(url).hostname
            if host:
                return host.rstrip(".").lower()
        return "share_link"
    return PDB_ROUTE


class OutageCircuitBreaker:
    """Contain a dead remote without failing a sweep that is otherwise fine.

    Per-file *permanent* answers (a 404, an HTML page where a binary was
    requested, an oversized body) are real verdicts about that file: they stay
    best effort, reset the streak and never trip anything. Only network-shaped
    failures — each of which already exhausted its own retry ladder — count.

    Streaks are counted **per remote**, which was the whole lesson of the
    first version. Failures cluster by host, because attachments are grouped
    by component and a component's files tend to live in one place. A single
    global streak therefore could not tell "the network is down" from "this
    one host is unreachable from here", and a site whose CERNBox share links
    need a VPN saw every sweep aborted at the same file — while the PDB
    itself was answering perfectly.

    So a tripped remote is skipped for the rest of the sweep (its remaining
    files fail immediately rather than each burning minutes of retries), and
    only the PDB route going dark means the sweep itself cannot proceed.
    """

    #: How many final per-file verdicts are remembered for one sweep. Bounded
    #: because the memo lives as long as the sweep and a mirror can hold tens
    #: of thousands of attachments; the oldest entry is dropped first.
    PERMANENT_MISS_MEMO_LIMIT = 4096

    def __init__(self, threshold: int = ATTACHMENT_OUTAGE_BREAKER_THRESHOLD) -> None:
        self.threshold = max(1, int(threshold))
        self._streaks: dict[str, int] = {}
        self.tripped_routes: set[str] = set()
        # Insertion-ordered, values unused: a set with a bounded eviction
        # order. Holds keys only — never bytes, never a URL.
        self._permanent_misses: dict[tuple[str, str], None] = {}
        # SHA-256 public-share identities that challenged for authentication
        # in this sweep. One protected folder can back many attachment codes
        # across many components; after the first honest challenge, do not
        # fetch the same login response dozens of times.
        self.authentication_blocked_shares: set[str] = set()

    def note_permanent_miss(self, key: tuple[str, str]) -> None:
        """Remember that this exact attachment got a *final* answer.

        One share folder backs 87 descriptors on 76 components in the owner's
        mirror, and the download runs once per component. A success needs no
        memo — the mirrored file is found on disk and reused — but a permanent
        refusal has nothing on disk to be found, so without this the same
        multi-megabyte archive is fetched and discarded once per referring
        component. Only *final* answers are remembered; a transient failure
        must stay retryable.

        Deliberately in memory and deliberately only for this sweep. A
        persisted "permanently failed" flag was considered and rejected: it
        would freeze exactly the descriptors that the next code change fixes,
        which is how the 20 folder-share rows repaired here would have been
        frozen instead (docs/12 §2.3).
        """
        if key in self._permanent_misses:
            return
        if len(self._permanent_misses) >= self.PERMANENT_MISS_MEMO_LIMIT:
            self._permanent_misses.pop(next(iter(self._permanent_misses)), None)
        self._permanent_misses[key] = None

    def has_permanent_miss(self, key: tuple[str, str]) -> bool:
        return key in self._permanent_misses

    def record_success(self, route: str = PDB_ROUTE) -> None:
        self._streaks[route] = 0

    def record_failure(self, route: str = PDB_ROUTE, *, transient: bool) -> None:
        if not transient:
            self._streaks[route] = 0
            return
        streak = self._streaks.get(route, 0) + 1
        self._streaks[route] = streak
        if streak >= self.threshold:
            self.tripped_routes.add(route)

    def is_tripped(self, route: str) -> bool:
        """Whether this remote has stopped answering and should be skipped."""

        return route in self.tripped_routes

    @property
    def sweep_is_doomed(self) -> bool:
        """Whether the failure is broad enough to abandon the whole sweep.

        Only the PDB route qualifies. An unreachable share host costs those
        files and nothing else; the mirror, the evidence and every other
        attachment still arrive, and the failed files are never recorded as
        stored, so the next sweep simply tries them again.
        """

        return PDB_ROUTE in self.tripped_routes


@dataclass
class _FetchOutcome:
    """One descriptor's result, carried from the fetch phase to the commit
    phase without a live network handle or a ``Session`` anywhere in sight."""

    descriptor: dict[str, Any]
    outcome: Literal["reused", "downloaded", "failed", "skipped"]
    content_type: str | None = None
    relative_path: str | None = None
    temp_path: Path | None = None
    size: int = 0
    # Whether a failed fetch died network-shaped (after its full retry
    # ladder) rather than receiving a permanent per-file answer. Feeds the
    # outage circuit breaker; meaningless for non-failed outcomes.
    transient: bool = False
    # A subset of skipped public-share results need a password or account
    # login; keeping the flag here lets the UI state that explicitly.
    authentication_required: bool = False


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
    share_passwords: SharePasswordResolver,
    heartbeat: Callable[[], None] | None,
    breaker: OutageCircuitBreaker | None = None,
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

    ``breaker`` (if given) is fed every file outcome; once it trips, the
    remaining descriptors are left unattempted for this call so the caller
    can fail its whole sweep transiently instead of burning one full retry
    ladder per file through an outage. Everything fetched so far still
    commits.
    """
    outcomes: list[_FetchOutcome] = []
    downloaded_keys: set[tuple[str, str]] = set()
    authentication_blocked_shares = (
        breaker.authentication_blocked_shares if breaker is not None else set()
    )

    def note(outcome: _FetchOutcome) -> None:
        outcomes.append(outcome)
        if breaker is None:
            return
        route = descriptor_route(outcome.descriptor)
        if outcome.outcome == "failed":
            breaker.record_failure(route, transient=outcome.transient)
        elif outcome.outcome == "downloaded":
            # Only a real network response proves that the remote is back.
            # Reusing an already mirrored file is deliberately neutral.
            breaker.record_success(route)

    client: Any = None
    # Set once client construction has exhausted its own retry budget: every
    # remaining PDB descriptor would fail identically, so fail them fast this
    # sweep instead of hammering the gateway once per file. None of them is
    # recorded as stored, so the next sweep retries them all. Whether that
    # unavailability was network-shaped is remembered so the fast-failed
    # files still count toward the outage breaker.
    client_unavailable = False
    client_unavailable_transient = False

    for descriptor in descriptors:
        key = (descriptor["source"], descriptor["code"])
        descriptor_url = descriptor.get("url")
        share_identity = None
        if descriptor.get("source") == "share_link" and isinstance(
            descriptor_url, str
        ):
            try:
                share_identity = public_share_identity(descriptor_url)
            except ValueError:
                pass
        if (
            share_identity is not None
            and share_identity.share_key in authentication_blocked_shares
        ):
            note(
                _FetchOutcome(
                    descriptor,
                    "skipped",
                    authentication_required=True,
                )
            )
            _beat(heartbeat)
            continue

        # A remote that has stopped answering is skipped for the rest of the
        # sweep: its files fail immediately instead of each burning a full
        # retry ladder. Only that remote is affected — the PDB, EOS and every
        # other share host keep being fetched normally, which is what stops
        # one dead host from costing a whole sync.
        if breaker is not None and not force and not resolved.get(key):
            if breaker.is_tripped(descriptor_route(descriptor)):
                outcomes.append(_FetchOutcome(descriptor, "failed", transient=True))
                _beat(heartbeat)
                continue
            # This exact attachment already got a final answer earlier in the
            # sweep, from another component that lists the same file. Asking
            # again cannot answer differently and, for a folder share, costs
            # a whole archive. Deliberately not fed back into the breaker:
            # it is a remembered verdict, not a new observation.
            if breaker.has_permanent_miss(key):
                outcomes.append(_FetchOutcome(descriptor, "failed"))
                _beat(heartbeat)
                continue

        # A forced sweep re-fetches each physical blob once, not once per run
        # association. Reusing a successful fetch from this same call avoids
        # redundant network and staging work. If the first descriptor failed,
        # the next one still gets its own attempt because the key has not
        # entered `downloaded_keys`.
        if key in downloaded_keys or (not force and resolved.get(key)):
            note(_FetchOutcome(descriptor, "reused"))
            _beat(heartbeat)
            continue

        needs_pdb_client = descriptor["source"] != "share_link"
        if needs_pdb_client and client is None and client_unavailable:
            note(
                _FetchOutcome(descriptor, "failed", transient=client_unavailable_transient)
            )
            _beat(heartbeat)
            continue

        fetched: tuple[bytes, str | None] | None = None
        transient_failure = False
        share_skipped = False
        attempt = 0
        while True:
            attempt += 1
            try:
                if needs_pdb_client and client is None:
                    client = _open_pdb_client(gateway)
                configured_share_password = (
                    descriptor.get("source") == "share_link"
                    and isinstance(descriptor_url, str)
                    and share_passwords.password_for_url(descriptor_url) is not None
                )
                if configured_share_password:
                    fetched = _fetch_bytes(
                        client,
                        descriptor,
                        timeout=timeout,
                        max_bytes=max_bytes,
                        share_passwords=share_passwords,
                    )
                else:
                    # Preserve the long-standing private helper signature for
                    # ordinary/unprotected downloads and test doubles.
                    fetched = _fetch_bytes(
                        client,
                        descriptor,
                        timeout=timeout,
                        max_bytes=max_bytes,
                    )
                break
            except _ShareLinkSkipped as skipped:
                if skipped.authentication_required and share_identity is not None:
                    authentication_blocked_shares.add(share_identity.share_key)
                note(
                    _FetchOutcome(
                        descriptor,
                        "skipped",
                        authentication_required=skipped.authentication_required,
                    )
                )
                share_skipped = True
                break
            except _PdbClientUnavailable:
                break
            except _TransientDownloadFailure:
                if attempt >= max_attempts:
                    transient_failure = True
                    break
                _beat(heartbeat)
                sleep(DOWNLOAD_RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1)))
        if needs_pdb_client and client is None:
            client_unavailable = True
            client_unavailable_transient = transient_failure

        if share_skipped:
            _beat(heartbeat)
            continue
        if fetched is None:
            if breaker is not None and not transient_failure:
                breaker.note_permanent_miss(key)
            note(_FetchOutcome(descriptor, "failed", transient=transient_failure))
            _beat(heartbeat)
            continue
        data, reported_type = fetched

        # itkdb sniffs the actual type from the response; the listing metadata
        # is often just "file". Prefer the sniffed one for both the stored
        # extension and what the API later serves.
        content_type = reported_type or descriptor["content_type"]
        relative_path = storage_path(
            component_sn,
            descriptor["code"],
            content_type,
            descriptor["filename"],
            source=descriptor["source"],
        )
        try:
            temp_path = _write_temp_bytes(root, relative_path, data)
        except (OSError, ValueError):
            # A local disk problem, not the network: never breaker-relevant.
            note(_FetchOutcome(descriptor, "failed"))
            _beat(heartbeat)
            continue

        resolved[key] = True
        downloaded_keys.add(key)
        note(
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
    downloaded = reused = failed = skipped = authentication_required = 0
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
        _upsert_reference(
            session,
            row,
            component_sn=descriptor["component_sn"],
            test_type=descriptor["test_type"],
            test_run_ref=descriptor["test_run_ref"],
            filename=descriptor["filename"],
            title=descriptor["title"],
        )
        # The same descriptor can occur twice in one payload; make the new
        # association visible to the next autoflush-disabled lookup too.
        session.flush()

        if item.outcome == "reused":
            reused += 1
            continue
        if item.outcome == "skipped":
            skipped += 1
            if item.authentication_required:
                authentication_required += 1
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

    return AttachmentSyncStats(
        downloaded=downloaded,
        reused=reused,
        failed=failed,
        skipped=skipped,
        authentication_required=authentication_required,
    )


def download_attachments(
    session: Session,
    gateway: Any,
    settings: Any,
    component_sn: str,
    *,
    force: bool = False,
    heartbeat: Callable[[], None] | None = None,
    descriptors: list[dict[str, Any]] | None = None,
    breaker: OutageCircuitBreaker | None = None,
    before_commit: Callable[[Session], None] | None = None,
    share_passwords: SharePasswordResolver | None = None,
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

    ``descriptors`` lets a sweep hand in the pending plan it already computed
    (one ``pending_attachments`` read per component instead of two); left as
    ``None``, the plan is read here. ``breaker`` (if given) turns several
    consecutive transient file failures into a stopped phase — see
    ``OutageCircuitBreaker`` — while everything fetched so far still commits.
    ``before_commit`` runs after network fetching but before a temporary file
    is renamed or a database row is written. Background jobs use it to verify
    and lock their durable lease in this same transaction, so a stale worker
    cannot publish files after a newer retry took ownership.
    """
    if descriptors is None:
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

    # The same physical key can arrive through a direct refresh while the
    # background sweep is already handling it. Hold only those overlapping
    # keys, and hold them through the caller's transaction end: releasing
    # after flush but before commit would let the waiter plan against a row
    # that is not visible yet and fetch the same bytes again.
    key_locks = _acquire_attachment_key_locks(root, descriptors)
    outcomes: list[_FetchOutcome] = []
    try:
        # Phase 1 - plan (read-only).
        resolved = _plan_resolved(session, settings, descriptors)

        # Phase 2 - fetch (network only; no session write is even possible
        # here, since this helper is never handed a session).
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
            share_passwords=share_passwords or SharePasswordResolver(),
            heartbeat=heartbeat,
            breaker=breaker,
        )

        # Phase 3 - commit (short, network-free transaction).
        if before_commit is not None:
            before_commit(session)
        stats = _commit_outcomes(session, root, outcomes)
    except Exception:
        for outcome in outcomes:
            if outcome.temp_path is not None:
                outcome.temp_path.unlink(missing_ok=True)
        _release_attachment_key_locks(key_locks)
        raise

    _release_attachment_key_locks_after_transaction(session, key_locks)
    return stats
