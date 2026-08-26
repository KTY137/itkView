"""Persistent background jobs for authoritative component-mirror syncs.

The existing synchronous endpoint remains available for scripts/tests. This
module powers the pollable UI path: one process-local worker executes a job,
while a unique database lease prevents overlapping component syncs globally.
Mirror rows, stage history, derived tools and the terminal job result commit in
one transaction.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from time import sleep
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.attachment_store import AttachmentSyncStats, download_attachments, pending_attachments
from app.config import Settings
from app.db import is_sqlite_busy as _is_sqlite_busy
from app.models import Component, InstituteProfile, SyncJob, TestRunEvidence, utcnow
from app.pdb_credentials import PdbAccessCodes, PdbCredentialError, load_pdb_credentials
from app.pdb_gateway import PdbGateway
from app.pdb_sync import FetchResult, PdbSyncUnavailable, SyncProgress
from app.pdb_test_evidence import (
    PdbEvidenceUnavailable,
    fetch_test_run_evidence,
    flat_fingerprint,
)
from app.sync import UnknownParentError, sync_components
from app.test_run_evidence import EvidenceSyncStats, upsert_test_run_evidence
from app.tool_sync import sync_tools_from_components

log = logging.getLogger(__name__)

COMPONENT_SYNC_KIND = "components"
COMPONENT_SYNC_ACTIVE_KEY = "components"
EVIDENCE_SYNC_KIND = "evidence"
EVIDENCE_SYNC_ACTIVE_KEY_PREFIX = "evidence:"
ACTIVE_SYNC_STATUSES = frozenset({"queued", "running"})
# How long a job may go without a progress heartbeat before startup recovery
# treats it as orphaned. The slowest legitimate quiet stretch is one PDB page
# read-timeout (~60s, heartbeats fire on every retry), so three minutes never
# mistakes a live sync for a dead one — while a genuinely crashed job releases
# its single-flight lease after at most this long.
SYNC_HEARTBEAT_GRACE = timedelta(minutes=3)
SYNC_LEASE_MAX_ATTEMPTS = 6
SYNC_LEASE_RETRY_SECONDS = 0.02

# Component types the evidence sweep mirrors unless the institute profile says
# otherwise. These are collaboration-wide PDB type codes, not institute
# specifics (hard rule #4) — chosen by sampling which types actually carry test
# runs: sensors hold most of the mirrored attachments, hybrids/flexes and the
# powerboard flex carry assembly evidence, and the DAQ-side chip types
# (ABC/HCC/AMAC) are deliberately left out because they multiply the sweep by
# ~5x for wafer-level QA that is not this site's production record. Add them
# through `evidence_component_types` when a site wants them.
DEFAULT_EVIDENCE_COMPONENT_TYPES = (
    "MODULE",
    "SENSOR",
    "SENSOR_S_TEST",
    "HYBRID",
    "HYBRID_ASSEMBLY",
    "HYBRID_FLEX",
    "HYBRID_TEST_PANEL",
    "EC_POWERBOARD_FLEX",
    "PWB",
    "HV_TAB_SHEET",
)
# Delay before the one automatic retry of a transiently failed sync job. Long
# enough for a router reconnect, short enough that nobody has to babysit the
# app. Must stay well below SYNC_HEARTBEAT_GRACE so the queued retry row is
# never mistaken for an orphan.
SYNC_AUTO_RETRY_DELAY_SECONDS = 60.0
# Durable marker on the retry job's requested_by. It shows up honestly in the
# UI and caps the chain: a job claimed with it never schedules another retry.
AUTO_RETRY_REQUESTED_BY_PREFIX = "automatic retry"
# Bounded IN-list size for mirror lookups (same batch size as the tool sync).
FINGERPRINT_CHUNK_SIZE = 500

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
    # True when this job *is* the one automatic retry; its own failure must
    # never schedule another.
    auto_retry: bool = False


@dataclass(frozen=True)
class EvidenceSyncContext:
    """Detached, secret-free facts required by an evidence job."""

    institute: InstituteProfile
    user_id: int
    requested_by: str = ""
    auto_retry: bool = False


def auto_retry_requested_by(original: str) -> str:
    """The retry job's durable requester label, marker prefix included."""

    return f"{AUTO_RETRY_REQUESTED_BY_PREFIX} ({original})"[:120]


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
                if not _job_heartbeat_stale(active):
                    return SyncLease(job=active, created=False)
                # A stale heartbeat means the lease owner died and startup
                # recovery did not notice (a crash followed by an immediate
                # restart leaves the heartbeat looking fresh at boot). Close
                # the zombie so its lease cannot stay blocked forever, then
                # create the replacement below.
                _close_interrupted_job(active)
                session.commit()

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
                if not _job_heartbeat_stale(active):
                    return SyncLease(job=active, created=False)
                # Same zombie takeover as the component lease (see there).
                _close_interrupted_job(active)
                session.commit()

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


def _job_heartbeat_stale(job: SyncJob, *, now: datetime | None = None) -> bool:
    """Whether nobody has touched this active job within the heartbeat grace."""

    heartbeat = job.updated_at or job.created_at
    if heartbeat is None:
        return True
    # SQLite hands timestamps back without their timezone.
    if heartbeat.tzinfo is None:
        heartbeat = heartbeat.replace(tzinfo=timezone.utc)
    return heartbeat <= (now or utcnow()) - SYNC_HEARTBEAT_GRACE


def _close_interrupted_job(job: SyncJob) -> None:
    """Close one orphaned active job and release its single-flight lease."""

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
        self._retry_timers: list[threading.Timer] = []
        self._retry_lock = threading.Lock()

    def start(self, job_id: int, fetcher: ComponentFetcher) -> None:
        def schedule_retry(context: ComponentSyncContext) -> None:
            self._schedule_retry(lambda: self._start_component_retry(fetcher, context))

        self._executor.submit(
            run_component_sync_job,
            self._session_factory,
            self._settings,
            fetcher,
            job_id,
            self.enqueue_evidence,
            schedule_retry,
        )

    def start_evidence(self, job_id: int) -> None:
        self._executor.submit(
            run_evidence_sync_job,
            self._session_factory,
            self._settings,
            self._evidence_gateway_factory,
            job_id,
            self._schedule_evidence_retry,
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

    # -- bounded automatic retry after a transient job failure --------------
    #
    # No durable row exists while the delay timer runs: the failed job stays
    # visible and lease-free, so a person can start a new sync at any moment.
    # When the timer fires it goes through the normal lease acquisition — if
    # someone already queued a job, the retry converges on it instead of
    # stacking a second one. A process death during the delay simply drops
    # the retry; the failed job row keeps telling the truth.

    def _schedule_retry(self, runner: Callable[[], None]) -> None:
        timer = threading.Timer(SYNC_AUTO_RETRY_DELAY_SECONDS, runner)
        timer.daemon = True
        with self._retry_lock:
            self._retry_timers = [t for t in self._retry_timers if t.is_alive()]
            self._retry_timers.append(timer)
        timer.start()

    def _schedule_evidence_retry(self, context: EvidenceSyncContext) -> None:
        self._schedule_retry(lambda: self._start_evidence_retry(context))

    def _start_component_retry(
        self, fetcher: ComponentFetcher, context: ComponentSyncContext
    ) -> None:
        try:
            with self._session_factory() as session:
                lease = acquire_component_sync_lease(
                    session,
                    institute_code=context.institute.code,
                    requested_by=auto_retry_requested_by(context.requested_by),
                    user_id=context.user_id,
                )
            if lease.created:
                self.start(lease.job.id, fetcher)
        except Exception:
            # Best effort by design; the failed job row remains authoritative.
            log.error("The automatic component sync retry could not be queued.")

    def _start_evidence_retry(self, context: EvidenceSyncContext) -> None:
        try:
            self.enqueue_evidence(
                context.institute.code,
                auto_retry_requested_by(context.requested_by),
                context.user_id,
            )
        except Exception:
            log.error("The automatic evidence sync retry could not be queued.")

    def shutdown(self) -> None:
        # A running requests call cannot be cancelled safely. Dev shutdown uses
        # process termination; the next app instance marks the durable row as
        # interrupted and releases its lease. Pending retry timers are
        # cancelled so nothing fires into a torn-down app.
        with self._retry_lock:
            timers, self._retry_timers = self._retry_timers, []
        for timer in timers:
            timer.cancel()
        self._executor.shutdown(wait=False, cancel_futures=True)


def _default_evidence_gateway(settings: Settings, access_codes: PdbAccessCodes) -> PdbGateway:
    return PdbGateway(settings, access_codes=access_codes)


def run_component_sync_job(
    session_factory: sessionmaker[Session],
    settings: Settings,
    fetcher: ComponentFetcher,
    job_id: int,
    on_success: ComponentSyncSucceeded | None = None,
    on_transient_failure: Callable[[ComponentSyncContext], None] | None = None,
) -> None:
    """Claim and execute one queued component sync using fresh sessions."""

    access_codes: PdbAccessCodes | None = None
    context: ComponentSyncContext | None = None
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
        _maybe_schedule_auto_retry(exc, context, on_transient_failure)


def _evidence_component_types(institute: InstituteProfile) -> tuple[str, ...]:
    raw = (institute.settings or {}).get("evidence_component_types")
    if not isinstance(raw, list):
        return DEFAULT_EVIDENCE_COMPONENT_TYPES
    values: list[str] = []
    for value in raw:
        if not isinstance(value, str) or not value.strip():
            continue
        normalized = value.strip().upper()
        if normalized not in values:
            values.append(normalized)
    return tuple(values) or DEFAULT_EVIDENCE_COMPONENT_TYPES


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
        return EvidenceSyncContext(
            institute=institute,
            user_id=job.user_id,
            requested_by=job.requested_by,
            auto_retry=job.requested_by.startswith(AUTO_RETRY_REQUESTED_BY_PREFIX),
        )


def _fetch_evidence_with_retry(
    gateway,
    component_sn: str,
    *,
    known_flat: dict[str, tuple],
    max_attempts: int,
    on_retry: Callable[[int], None] | None = None,
):
    """Strict per-component fetch with a bounded transient-retry budget.

    The sweep stays honest — a component that never answers still fails the
    job — but one network hiccup no longer aborts a whole institute at zero,
    which is exactly what a flaky home connection produced in practice. Shares
    the page-retry budget (`sync_page_max_attempts`) and backoff shape.
    ``on_retry`` fires with the just-failed attempt number *before* the
    backoff sleep, so the caller can keep its durable heartbeat fresh: the
    full retry ladder can otherwise stay quiet for longer than the
    startup-recovery grace and a second app instance would kill a live job.
    """
    attempt = 0
    while True:
        attempt += 1
        try:
            return fetch_test_run_evidence(
                gateway,
                component_sn,
                with_detail=True,
                strict=True,
                known_flat=known_flat,
            )
        except PdbEvidenceUnavailable:
            if attempt >= max_attempts:
                raise
            if on_retry is not None:
                on_retry(attempt)
            sleep(0.5 * (2 ** (attempt - 1)))


def _mirrored_flat_fingerprints(
    session: Session, component_sns: list[str]
) -> dict[str, tuple]:
    """Fingerprints of mirrored runs that already carry their fetched detail.

    Only rows marked `detail_synced` qualify: a flat-only row (from an older
    sweep, or a run whose detail fetch failed) must take the detail round trip
    on the next sync rather than being frozen in its shallow state.
    """
    fingerprints: dict[str, tuple] = {}
    if not component_sns:
        return fingerprints
    # Production scopes reach thousands of serial numbers; keep every IN list
    # bounded (same batch size as the tool sync). The payload JSON column is
    # still read whole per chunk: its `detail_synced`/`state`/`problems` keys
    # would need dialect-specific JSON extraction to project in SQL, and that
    # is not worth a behavioural risk between SQLite and PostgreSQL.
    for offset in range(0, len(component_sns), FINGERPRINT_CHUNK_SIZE):
        sn_chunk = component_sns[offset : offset + FINGERPRINT_CHUNK_SIZE]
        rows = session.execute(
            select(
                TestRunEvidence.external_ref,
                TestRunEvidence.passed,
                TestRunEvidence.measured_at,
                TestRunEvidence.payload,
            ).where(
                TestRunEvidence.source == "pdb",
                TestRunEvidence.external_ref.is_not(None),
                TestRunEvidence.component_sn.in_(sn_chunk),
            )
        )
        for external_ref, passed, measured_at, payload in rows:
            payload = payload or {}
            if not payload.get("detail_synced"):
                continue
            fingerprints[external_ref] = flat_fingerprint(
                passed=passed,
                measured_at=measured_at,
                state=payload.get("state"),
                problems=payload.get("problems"),
            )
    return fingerprints


def run_evidence_sync_job(
    session_factory: sessionmaker[Session],
    settings: Settings,
    gateway_factory: EvidenceGatewayFactory,
    job_id: int,
    on_transient_failure: Callable[[EvidenceSyncContext], None] | None = None,
) -> None:
    """Mirror detailed evidence and every downloadable attachment for an institute."""

    access_codes: PdbAccessCodes | None = None
    context: EvidenceSyncContext | None = None
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
                        # Owned by us OR standing here: an assembly site works
                        # on parts the sending institute still owns, and their
                        # test evidence is exactly what the stage engine needs.
                        # Mirrors the component fetch's own two-scope shape.
                        or_(
                            Component.institute_code == context.institute.code,
                            Component.location == context.institute.code,
                        ),
                        Component.component_type.in_(component_types),
                        Component.trashed.is_(False),
                        Component.stale.is_(False),
                    )
                    .order_by(Component.sn)
                )
            )

        # Incremental detail: runs whose cheap listing data still matches the
        # mirrored fingerprint skip their per-run getTestRun round trip. On a
        # repeat sync that collapses the fetch phase from one request per run
        # to one request per component.
        with session_factory() as fingerprint_session:
            known_flat = _mirrored_flat_fingerprints(fingerprint_session, component_sns)

        component_total = len(component_sns)
        evidence_stats = EvidenceSyncStats()
        runs_seen = 0
        _update_progress(
            session_factory,
            job_id,
            "fetching",
            0,
            component_total,
            message=f"Fetching detailed evidence for {component_total} components.",
        )
        for index, component_sn in enumerate(component_sns, start=1):

            def fetch_retry_heartbeat(
                attempt: int,
                *,
                sn: str = component_sn,
                done: int = index - 1,
            ) -> None:
                _update_progress(
                    session_factory,
                    job_id,
                    "fetching",
                    done,
                    component_total,
                    message=(
                        f"Retrying {sn} after a transient PDB read error "
                        f"(attempt {attempt + 1}/{settings.sync_page_max_attempts})."
                    ),
                )

            records = _fetch_evidence_with_retry(
                gateway,
                component_sn,
                known_flat=known_flat,
                max_attempts=settings.sync_page_max_attempts,
                on_retry=fetch_retry_heartbeat,
            )
            runs_seen += len(records)
            # Commit each component as it arrives. A whole-institute sweep runs
            # for minutes; collecting everything for one final transaction meant
            # that closing the app — or any PDB hiccup — discarded every fetched
            # run, and the UI then showed each required test as "missing".
            # The upsert is idempotent, so a resumed sweep simply re-confirms.
            if records:
                with session_factory() as evidence_session:
                    batch_stats = upsert_test_run_evidence(evidence_session, records)
                    evidence_session.commit()
                evidence_stats = EvidenceSyncStats(
                    created=evidence_stats.created + batch_stats.created,
                    updated=evidence_stats.updated + batch_stats.updated,
                    unchanged=evidence_stats.unchanged + batch_stats.unchanged,
                )
            _update_progress(
                session_factory,
                job_id,
                "fetching",
                index,
                component_total,
                message=(
                    f"Fetched {index}/{component_total} components "
                    f"and {runs_seen} test runs."
                ),
            )

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
        def attachment_heartbeat() -> None:
            # Fired by the store after every processed file and before every
            # retry backoff. Same numbers, fresh `updated_at`: one component
            # with many slow or flaky downloads must not look orphaned.
            _update_progress(
                session_factory,
                job_id,
                "attachments",
                processed_files,
                attachment_total,
                message=(
                    f"Mirroring attachments ({processed_files}/{attachment_total} "
                    "files done; still working)."
                ),
            )

        for component_index, component_sn in enumerate(component_sns, start=1):
            with session_factory() as attachment_session:
                stats = download_attachments(
                    attachment_session,
                    gateway,
                    settings,
                    component_sn,
                    heartbeat=attachment_heartbeat,
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
        _maybe_schedule_auto_retry(exc, context, on_transient_failure)


def _is_transient_job_failure(error: Exception) -> bool:
    """Connectivity-shaped failures worth one delayed automatic retry.

    Mirrors the outbox convention (``PdbSubmitUnavailable`` == transient): the
    ``*Unavailable`` exception family means the PDB read did not produce a
    trustworthy result — not that anything local is wrong. Credential
    problems, vanished institutes and genuine bugs stay failed until a person
    looks at them; retrying those would only repeat the same failure.
    """

    return isinstance(error, (PdbSyncUnavailable, PdbEvidenceUnavailable))


def _maybe_schedule_auto_retry(
    error: Exception,
    context: ComponentSyncContext | EvidenceSyncContext | None,
    schedule: Callable[[Any], None] | None,
) -> None:
    """Hand a transiently failed job to the manager for its one retry.

    The cap lives in the durable requested_by marker: a job that *is* the
    automatic retry (``context.auto_retry``) never schedules another, so the
    chain is at most original + one retry regardless of restarts.
    """

    if schedule is None or context is None or context.auto_retry:
        return
    if not _is_transient_job_failure(error):
        return
    try:
        schedule(context)
    except Exception:
        # Best effort: the failed job row already tells the truth.
        log.error("Could not schedule the automatic sync retry.")


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
            auto_retry=job.requested_by.startswith(AUTO_RETRY_REQUESTED_BY_PREFIX),
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
    """Fail closed after restart; never resume a partial authoritative fetch.

    Only jobs whose progress heartbeat has gone stale are closed. Starting a
    second app instance therefore no longer aborts a sync the first one is
    still running — that turned "open the app again" into "lose the sync",
    observed against production at 600 of 3766 components.
    """

    recovered = 0
    with session_factory() as session:
        jobs = list(
            session.scalars(select(SyncJob).where(SyncJob.status.in_(ACTIVE_SYNC_STATUSES)))
        )
        now = utcnow()
        for job in jobs:
            if not _job_heartbeat_stale(job, now=now):
                continue  # someone is still working on this one
            _close_interrupted_job(job)
            recovered += 1
        session.commit()
    return recovered
