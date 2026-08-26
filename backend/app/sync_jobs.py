"""Persistent background jobs for authoritative component-mirror syncs.

The existing synchronous endpoint remains available for scripts/tests. This
module powers the pollable UI path: one process-local worker executes a job,
while a unique database lease prevents overlapping component syncs globally.
Mirror rows, stage history, derived tools and the terminal job result commit in
one transaction.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from time import sleep
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.attachment_store import AttachmentSyncStats, download_attachments, pending_attachments
from app.config import Settings
from app.models import Component, InstituteProfile, SyncJob, utcnow
from app.pdb_credentials import PdbAccessCodes, PdbCredentialError, load_pdb_credentials
from app.pdb_gateway import PdbGateway
from app.pdb_sync import FetchResult, PdbSyncUnavailable, SyncProgress
from app.pdb_test_evidence import PdbEvidenceUnavailable, fetch_test_run_evidence
from app.sync import UnknownParentError, sync_components
from app.test_run_evidence import TestRunEvidenceRecord, upsert_test_run_evidence
from app.tool_sync import sync_tools_from_components

log = logging.getLogger(__name__)

COMPONENT_SYNC_KIND = "components"
COMPONENT_SYNC_ACTIVE_KEY = "components"
EVIDENCE_SYNC_KIND = "evidence"
EVIDENCE_SYNC_ACTIVE_KEY_PREFIX = "evidence:"
ACTIVE_SYNC_STATUSES = frozenset({"queued", "running"})
SYNC_LEASE_MAX_ATTEMPTS = 6
SYNC_LEASE_RETRY_SECONDS = 0.02

ComponentFetcher = Callable[
    [Settings, InstituteProfile, PdbAccessCodes, SyncProgress | None],
    FetchResult,
]
EvidenceGatewayFactory = Callable[[Settings, PdbAccessCodes], Any]
ComponentSyncSucceeded = Callable[[str, str, int], None]


def evidence_sync_active_key(institute_code: str) -> str:
    """Return the durable single-flight key for one institute's evidence sync."""

    return f"{EVIDENCE_SYNC_ACTIVE_KEY_PREFIX}{institute_code}"


class SyncLeaseBusy(RuntimeError):
    """The short database lease transaction stayed busy after bounded retry."""


@dataclass(frozen=True)
class SyncLease:
    job: SyncJob
    created: bool


@dataclass(frozen=True)
class ComponentSyncContext:
    """Detached, secret-free facts required to execute one claimed job."""

    institute: InstituteProfile
    user_id: int
    requested_by: str


@dataclass(frozen=True)
class EvidenceSyncContext:
    """Detached, secret-free facts required by an evidence job."""

    institute: InstituteProfile
    user_id: int


def acquire_component_sync_lease(
    session: Session,
    *,
    institute_code: str,
    requested_by: str,
    user_id: int | None,
    initial_status: str = "queued",
) -> SyncLease:
    """Acquire the global component-sync lease in a short transaction.

    The unique ``active_key`` remains the final arbiter. SQLite can return BUSY
    instead of waiting when two starts race, so only that narrow error is
    retried; callers never receive an accidental 500 for a normal double-click.
    """

    if initial_status not in ACTIVE_SYNC_STATUSES:
        raise ValueError(f"Invalid initial sync status '{initial_status}'.")

    last_busy: OperationalError | None = None
    for attempt in range(SYNC_LEASE_MAX_ATTEMPTS):
        try:
            active = session.scalar(
                select(SyncJob).where(SyncJob.active_key == COMPONENT_SYNC_ACTIVE_KEY)
            )
            if active is not None:
                return SyncLease(job=active, created=False)

            now = utcnow()
            job = SyncJob(
                kind=COMPONENT_SYNC_KIND,
                institute_code=institute_code,
                status=initial_status,
                phase="queued" if initial_status == "queued" else "fetching",
                current=0,
                total=None,
                percent=None,
                message=(
                    "Component sync is queued."
                    if initial_status == "queued"
                    else "Connecting to the PDB."
                ),
                requested_by=requested_by,
                user_id=user_id,
                active_key=COMPONENT_SYNC_ACTIVE_KEY,
                created_at=now,
                started_at=now if initial_status == "running" else None,
                updated_at=now,
            )
            session.add(job)
            session.commit()
            return SyncLease(job=job, created=True)
        except IntegrityError:
            # Another starter won the UNIQUE active_key race. Roll back and
            # retry the read so both callers converge on the same durable job.
            session.rollback()
        except OperationalError as exc:
            session.rollback()
            if not _is_sqlite_busy(exc):
                raise
            last_busy = exc

        if attempt + 1 < SYNC_LEASE_MAX_ATTEMPTS:
            sleep(SYNC_LEASE_RETRY_SECONDS * (attempt + 1))

    raise SyncLeaseBusy("The component sync coordinator is busy; retry shortly.") from last_busy


def acquire_evidence_sync_lease(
    session: Session,
    *,
    institute_code: str,
    requested_by: str,
    user_id: int | None,
) -> SyncLease:
    """Acquire one evidence-sync lease per institute without duplicate jobs.

    Evidence scopes do not overlap across institutes. Keeping a separate
    durable lease for each scope means a component sync for institute B cannot
    disappear merely because institute A is still mirroring attachments. The
    manager's single worker continues to serialize the actual writes.
    """

    last_busy: OperationalError | None = None
    active_key = evidence_sync_active_key(institute_code)
    for attempt in range(SYNC_LEASE_MAX_ATTEMPTS):
        try:
            active = session.scalar(
                select(SyncJob).where(SyncJob.active_key == active_key)
            )
            if active is not None:
                return SyncLease(job=active, created=False)

            now = utcnow()
            job = SyncJob(
                kind=EVIDENCE_SYNC_KIND,
                institute_code=institute_code,
                status="queued",
                phase="queued",
                current=0,
                total=None,
                percent=None,
                message="Evidence sync is queued.",
                requested_by=requested_by,
                user_id=user_id,
                active_key=active_key,
                created_at=now,
                updated_at=now,
            )
            session.add(job)
            session.commit()
            return SyncLease(job=job, created=True)
        except IntegrityError:
            session.rollback()
        except OperationalError as exc:
            session.rollback()
            if not _is_sqlite_busy(exc):
                raise
            last_busy = exc

        if attempt + 1 < SYNC_LEASE_MAX_ATTEMPTS:
            sleep(SYNC_LEASE_RETRY_SECONDS * (attempt + 1))

    raise SyncLeaseBusy("The evidence sync coordinator is busy; retry shortly.") from last_busy


def _is_sqlite_busy(error: OperationalError) -> bool:
    detail = str(error).lower()
    return "database is locked" in detail or "database table is locked" in detail


class SyncJobManager:
    """Submit component jobs to one background thread.

    The database's unique ``active_key`` is the actual per-scope single-flight
    guard. ``max_workers=1`` serializes mirror writers while allowing one
    durable evidence follow-up per institute to wait safely in the queue.
    """

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        settings: Settings,
        evidence_gateway_factory: EvidenceGatewayFactory | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._evidence_gateway_factory = evidence_gateway_factory or _default_evidence_gateway
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="itkflow-sync")

    def start(self, job_id: int, fetcher: ComponentFetcher) -> None:
        self._executor.submit(
            run_component_sync_job,
            self._session_factory,
            self._settings,
            fetcher,
            job_id,
            self.enqueue_evidence,
        )

    def start_evidence(self, job_id: int) -> None:
        self._executor.submit(
            run_evidence_sync_job,
            self._session_factory,
            self._settings,
            self._evidence_gateway_factory,
            job_id,
        )

    def enqueue_evidence(
        self,
        institute_code: str,
        requested_by: str,
        user_id: int,
    ) -> SyncLease:
        """Queue the post-component evidence mirror, converging on one live job."""

        with self._session_factory() as session:
            lease = acquire_evidence_sync_lease(
                session,
                institute_code=institute_code,
                requested_by=requested_by,
                user_id=user_id,
            )
        if lease.created:
            self.start_evidence(lease.job.id)
        return lease

    def shutdown(self) -> None:
        # A running requests call cannot be cancelled safely. Dev shutdown uses
        # process termination; the next app instance marks the durable row as
        # interrupted and releases its lease.
        self._executor.shutdown(wait=False, cancel_futures=True)


def _default_evidence_gateway(settings: Settings, access_codes: PdbAccessCodes) -> PdbGateway:
    return PdbGateway(settings, access_codes=access_codes)


def run_component_sync_job(
    session_factory: sessionmaker[Session],
    settings: Settings,
    fetcher: ComponentFetcher,
    job_id: int,
    on_success: ComponentSyncSucceeded | None = None,
) -> None:
    """Claim and execute one queued component sync using fresh sessions."""

    access_codes: PdbAccessCodes | None = None
    try:
        context = _claim_job(session_factory, job_id)
        if context is None:
            return

        # Resolve the starter's credential inside the worker thread and from a
        # fresh, short-lived session. The executor queue and durable SyncJob row
        # contain only the job/user ids, never either access code.
        with session_factory() as credential_session:
            access_codes = load_pdb_credentials(
                credential_session,
                user_id=context.user_id,
                encryption_key=settings.pdb_credential_encryption_key,
            )

        def report(
            phase: str,
            current: int,
            total: int | None,
            message: str | None = None,
        ) -> None:
            _update_progress(
                session_factory,
                job_id,
                phase,
                current,
                total,
                message=message,
            )

        fetched = fetcher(settings, context.institute, access_codes, report)
        fetched_count = len(fetched.records) + fetched.skipped
        _update_progress(
            session_factory,
            job_id,
            "upserting",
            0,
            len(fetched.records),
            message=f"Updating the local mirror ({len(fetched.records)} records) and tools.",
        )

        # One transaction owns every mirror mutation plus the terminal job
        # result. A crash/error therefore cannot expose a partial prune/history.
        with session_factory() as session:
            job = session.get(SyncJob, job_id)
            if job is None or job.status != "running":
                return
            live_institute = session.scalar(
                select(InstituteProfile).where(InstituteProfile.code == job.institute_code)
            )
            if live_institute is None:
                raise RuntimeError(
                    f"Institute '{job.institute_code}' disappeared while its sync was running."
                )

            stats = sync_components(
                session,
                fetched.records,
                prune_scope=live_institute.code,
            )
            sync_tools_from_components(session, live_institute)

            result = {
                "institute_code": live_institute.code,
                "fetched": fetched_count,
                "skipped": fetched.skipped,
                "created": stats.created,
                "updated": stats.updated,
                "unchanged": stats.unchanged,
                "stale": stats.stale,
                "total": stats.total,
            }
            finished = utcnow()
            job.status = "succeeded"
            job.phase = "complete"
            job.current = len(fetched.records)
            job.total = len(fetched.records)
            job.percent = 100.0
            job.message = "Component sync completed."
            job.result = result
            job.error = None
            job.active_key = None
            job.updated_at = finished
            job.finished_at = finished
            session.commit()
        if on_success is not None:
            try:
                on_success(
                    context.institute.code,
                    context.requested_by,
                    context.user_id,
                )
            except Exception:
                # Component data is already committed and truthful. Failure to
                # enqueue the follow-up must not rewrite that job as failed.
                log.error(
                    "Could not enqueue evidence sync after component job %s.",
                    job_id,
                )
    except Exception as exc:
        detail = _public_sync_error(exc, access_codes=access_codes)
        # Do not use log.exception here. Some versions of itkdb include a
        # rendered authentication request in an exception string; traceback
        # logging would therefore risk copying personal access codes to logs.
        log.error("Component sync job %s failed: %s", job_id, detail)
        fail_sync_job(session_factory, job_id, detail)


def _evidence_component_types(institute: InstituteProfile) -> tuple[str, ...]:
    raw = (institute.settings or {}).get("evidence_component_types")
    if not isinstance(raw, list):
        return ("MODULE",)
    values: list[str] = []
    for value in raw:
        if not isinstance(value, str) or not value.strip():
            continue
        normalized = value.strip().upper()
        if normalized not in values:
            values.append(normalized)
    return tuple(values) or ("MODULE",)


def _claim_evidence_job(
    session_factory: sessionmaker[Session], job_id: int
) -> EvidenceSyncContext | None:
    with session_factory() as session:
        job = session.get(SyncJob, job_id)
        if job is None or job.status != "queued" or job.kind != EVIDENCE_SYNC_KIND:
            return None
        if job.user_id is None:
            raise RuntimeError(
                "Evidence sync has no credential owner; start it again while signed in."
            )
        institute = session.scalar(
            select(InstituteProfile).where(InstituteProfile.code == job.institute_code)
        )
        if institute is None:
            raise RuntimeError(
                f"Institute '{job.institute_code}' disappeared before its evidence sync started."
            )
        started = utcnow()
        job.status = "running"
        job.phase = "fetching"
        job.current = 0
        job.total = None
        job.percent = None
        job.message = "Loading the local evidence sync scope."
        job.started_at = started
        job.updated_at = started
        session.expunge(institute)
        session.commit()
        return EvidenceSyncContext(institute=institute, user_id=job.user_id)


def run_evidence_sync_job(
    session_factory: sessionmaker[Session],
    settings: Settings,
    gateway_factory: EvidenceGatewayFactory,
    job_id: int,
) -> None:
    """Mirror detailed evidence and every downloadable attachment for an institute."""

    access_codes: PdbAccessCodes | None = None
    try:
        context = _claim_evidence_job(session_factory, job_id)
        if context is None:
            return
        with session_factory() as credential_session:
            access_codes = load_pdb_credentials(
                credential_session,
                user_id=context.user_id,
                encryption_key=settings.pdb_credential_encryption_key,
            )
        gateway = gateway_factory(settings, access_codes)
        component_types = _evidence_component_types(context.institute)
        with session_factory() as scope_session:
            component_sns = list(
                scope_session.scalars(
                    select(Component.sn)
                    .where(
                        Component.institute_code == context.institute.code,
                        Component.component_type.in_(component_types),
                        Component.trashed.is_(False),
                        Component.stale.is_(False),
                    )
                    .order_by(Component.sn)
                )
            )

        all_records: list[TestRunEvidenceRecord] = []
        component_total = len(component_sns)
        _update_progress(
            session_factory,
            job_id,
            "fetching",
            0,
            component_total,
            message=f"Fetching detailed evidence for {component_total} components.",
        )
        for index, component_sn in enumerate(component_sns, start=1):
            records = fetch_test_run_evidence(
                gateway,
                component_sn,
                with_detail=True,
                strict=True,
            )
            all_records.extend(records)
            _update_progress(
                session_factory,
                job_id,
                "fetching",
                index,
                component_total,
                message=(
                    f"Fetched {index}/{component_total} components "
                    f"and {len(all_records)} test runs."
                ),
            )

        # Evidence becomes available in one short transaction. Attachment
        # bytes are then mirrored component-by-component and are idempotent;
        # an interrupted job can safely continue on its next run.
        with session_factory() as evidence_session:
            evidence_stats = upsert_test_run_evidence(evidence_session, all_records)
            evidence_session.commit()

        with session_factory() as count_session:
            attachment_total = sum(
                len(pending_attachments(count_session, component_sn))
                for component_sn in component_sns
            )
        attachment_stats = AttachmentSyncStats()
        processed_files = 0
        _update_progress(
            session_factory,
            job_id,
            "attachments",
            0,
            attachment_total,
            message=f"Mirroring {attachment_total} attachment files.",
        )
        for component_index, component_sn in enumerate(component_sns, start=1):
            with session_factory() as attachment_session:
                stats = download_attachments(
                    attachment_session,
                    gateway,
                    settings,
                    component_sn,
                )
                attachment_session.commit()
            attachment_stats = AttachmentSyncStats(
                downloaded=attachment_stats.downloaded + stats.downloaded,
                reused=attachment_stats.reused + stats.reused,
                failed=attachment_stats.failed + stats.failed,
            )
            processed_files += stats.total
            _update_progress(
                session_factory,
                job_id,
                "attachments",
                processed_files,
                attachment_total,
                message=(
                    f"Mirrored attachments for {component_index}/{component_total} components "
                    f"({processed_files}/{attachment_total} files)."
                ),
            )

        _update_progress(
            session_factory,
            job_id,
            "committing",
            1,
            1,
            message="Finalizing the evidence mirror.",
        )
        result = {
            "institute_code": context.institute.code,
            "component_types": list(component_types),
            "components_processed": component_total,
            "created": evidence_stats.created,
            "updated": evidence_stats.updated,
            "unchanged": evidence_stats.unchanged,
            "total": evidence_stats.total,
            "attachments_downloaded": attachment_stats.downloaded,
            "attachments_reused": attachment_stats.reused,
            "attachments_failed": attachment_stats.failed,
            "attachments_total": attachment_stats.total,
        }
        with session_factory() as session:
            job = session.get(SyncJob, job_id)
            if job is None or job.status != "running":
                return
            finished = utcnow()
            job.status = "succeeded"
            job.phase = "complete"
            job.current = attachment_stats.total
            job.total = attachment_total
            job.percent = 100.0
            job.message = "Evidence sync completed."
            job.result = result
            job.error = None
            job.active_key = None
            job.updated_at = finished
            job.finished_at = finished
            session.commit()
    except Exception as exc:
        detail = _public_sync_error(exc, access_codes=access_codes, kind=EVIDENCE_SYNC_KIND)
        log.error("Evidence sync job %s failed: %s", job_id, detail)
        fail_sync_job(session_factory, job_id, detail)


def _public_sync_error(
    error: Exception,
    *,
    access_codes: PdbAccessCodes | None = None,
    kind: str = COMPONENT_SYNC_KIND,
) -> str:
    """Return a safe durable/loggable failure description for a sync job."""

    if isinstance(
        error,
        (PdbCredentialError, PdbSyncUnavailable, PdbEvidenceUnavailable, UnknownParentError),
    ):
        detail = str(error)
    else:
        label = "Evidence" if kind == EVIDENCE_SYNC_KIND else "Component"
        detail = f"{label} sync failed due to {type(error).__name__}."
    if access_codes is not None:
        for secret in (access_codes.access_code1, access_codes.access_code2):
            detail = detail.replace(secret, "<redacted>")
    return detail


def _claim_job(session_factory: sessionmaker[Session], job_id: int) -> ComponentSyncContext | None:
    """Move a queued job to running and return a detached secret-free context."""

    with session_factory() as session:
        job = session.get(SyncJob, job_id)
        if job is None or job.status != "queued":
            return None
        if job.user_id is None:
            raise RuntimeError(
                "Component sync has no credential owner; start it again while signed in."
            )
        institute = session.scalar(
            select(InstituteProfile).where(InstituteProfile.code == job.institute_code)
        )
        if institute is None:
            raise RuntimeError(
                f"Institute '{job.institute_code}' disappeared before its sync started."
            )

        started = utcnow()
        job.status = "running"
        job.phase = "fetching"
        job.current = 0
        job.total = None
        job.percent = None
        job.message = "Connecting to the PDB."
        job.started_at = started
        job.updated_at = started
        # Fetching must not keep a database transaction/read lock open; the
        # progress callback writes through short independent sessions.
        session.expunge(institute)
        session.commit()
        return ComponentSyncContext(
            institute=institute,
            user_id=job.user_id,
            requested_by=job.requested_by,
        )


def _update_progress(
    session_factory: sessionmaker[Session],
    job_id: int,
    phase: str,
    current: int,
    total: int | None,
    *,
    message: str | None = None,
) -> None:
    """Persist one monotonic-in-phase progress observation."""

    try:
        with session_factory() as session:
            job = session.get(SyncJob, job_id)
            if job is None or job.status not in ACTIVE_SYNC_STATUSES:
                return
            job.status = "running"
            job.phase = phase
            job.current = max(0, current)
            job.total = total if total is None else max(0, total)
            job.percent = _percent(job.current, job.total)
            job.message = message or _progress_message(phase, job.current, job.total)
            job.updated_at = utcnow()
            session.commit()
    except Exception:
        # Progress telemetry must never turn a successful read-only fetch into a
        # failed authoritative sync. Terminal state is still written atomically.
        log.warning("Could not persist progress for sync job %s", job_id, exc_info=True)


def _percent(current: int, total: int | None) -> float | None:
    if total is None:
        return None
    if total == 0:
        return 100.0
    return round(min(100.0, max(0.0, current * 100.0 / total)), 1)


def _progress_message(phase: str, current: int, total: int | None) -> str:
    if phase == "fetching":
        return (
            f"Fetching components from the PDB ({current}/{total})."
            if total is not None
            else "Connecting to the PDB."
        )
    if phase == "mapping":
        return (
            f"Mapping PDB components ({current}/{total})."
            if total is not None
            else "Mapping PDB components."
        )
    if phase == "upserting":
        return "Updating the local component mirror."
    if phase == "stage_events":
        return "Updating component stage history."
    if phase == "tools":
        return "Refreshing the local tool registry."
    if phase == "attachments":
        return (
            f"Mirroring attachments ({current}/{total})."
            if total is not None
            else "Mirroring attachments."
        )
    if phase == "committing":
        return "Committing the completed mirror snapshot."
    return "Component sync is running."


def fail_sync_job(
    session_factory: sessionmaker[Session], job_id: int, error: Exception | str
) -> None:
    """Move a live job to failed and release the global lease."""

    detail = (
        error.strip() if isinstance(error, str) else _public_sync_error(error).strip()
    ) or "Component sync failed."
    with session_factory() as session:
        job = session.get(SyncJob, job_id)
        if job is None or job.status not in ACTIVE_SYNC_STATUSES:
            return
        finished = utcnow()
        job.status = "failed"
        job.message = (
            "Evidence sync failed." if job.kind == EVIDENCE_SYNC_KIND else "Component sync failed."
        )
        job.error = detail[:8000]
        job.active_key = None
        job.updated_at = finished
        job.finished_at = finished
        session.commit()


def recover_interrupted_sync_jobs(session_factory: sessionmaker[Session]) -> int:
    """Fail closed after restart; never resume a partial authoritative fetch."""

    recovered = 0
    with session_factory() as session:
        jobs = list(
            session.scalars(select(SyncJob).where(SyncJob.status.in_(ACTIVE_SYNC_STATUSES)))
        )
        for job in jobs:
            previous_phase = job.phase
            finished = utcnow()
            job.status = "interrupted"
            if job.kind == EVIDENCE_SYNC_KIND:
                job.message = "Evidence sync was interrupted by a server restart."
                job.error = (
                    f"Server restarted during phase '{previous_phase}'. Evidence and files "
                    "already mirrored remain valid; start the sync again to continue."
                )
            else:
                job.message = "Component sync was interrupted by a server restart."
                job.error = (
                    f"Server restarted during phase '{previous_phase}'; "
                    "no partial mirror changes were committed. Start the sync again."
                )
            job.active_key = None
            job.updated_at = finished
            job.finished_at = finished
            recovered += 1
        session.commit()
    return recovered
