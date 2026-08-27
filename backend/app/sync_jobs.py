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
from collections import deque
from collections.abc import Callable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import wait as futures_wait
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from time import sleep
from typing import Any, Literal

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.attachment_store import (
    AttachmentSyncStats,
    OutageCircuitBreaker,
    download_attachments,
    pending_attachments,
)
from app.config import Settings
from app.db import is_sqlite_busy as _is_sqlite_busy
from app.models import Component, InstituteProfile, SyncJob, TestRunEvidence, utcnow
from app.pdb_credentials import PdbAccessCodes, PdbCredentialError, load_pdb_credentials
from app.pdb_gateway import PdbGateway
from app.pdb_sync import FetchResult, PdbSyncUnavailable, SyncProgress
from app.pdb_test_evidence import (
    IndexedTestRun,
    PdbEvidenceUnavailable,
    PdbIndexUnusable,
    fetch_test_run_detail,
    fetch_test_run_details_bulk,
    fetch_test_run_evidence,
    fetch_test_run_index,
    flat_fingerprint,
    records_from_index,
)
from app.sync import UnknownParentError, sync_components
from app.test_run_evidence import EvidenceSyncStats, is_withdrawn, upsert_test_run_evidence
from app.tool_sync import sync_tools_from_components

log = logging.getLogger(__name__)

COMPONENT_SYNC_KIND = "components"
COMPONENT_SYNC_ACTIVE_KEY = "components"
EVIDENCE_SYNC_KIND = "evidence"
EVIDENCE_SYNC_ACTIVE_KEY_PREFIX = "evidence:"
EVIDENCE_FOLLOWUP_PENDING_KEY = "_evidence_followup_pending"
EVIDENCE_FOLLOWUP_RETRY_KEY = "_evidence_followup_retry"
FOLLOWUP_RETRY_DUE = "due"
FOLLOWUP_RETRY_BLOCKED = "blocked"
FOLLOWUP_RETRY_EXHAUSTED = "exhausted"
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
# How long the job thread waits on an in-flight pooled evidence fetch before
# writing an intermediate heartbeat. The retry ladders run inside the fetch
# workers, which never touch the database — without this the job row could go
# quiet for longer than SYNC_HEARTBEAT_GRACE while a slow component retries.
PARALLEL_FETCH_HEARTBEAT_SECONDS = 30.0
# How often the manager refreshes the heartbeat of jobs that are queued but
# still waiting for their per-kind worker thread. Must stay well below
# SYNC_HEARTBEAT_GRACE so a waiting job is never reaped as orphaned while the
# owning process is alive.
QUEUED_HEARTBEAT_INTERVAL_SECONDS = 60.0

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
    # True when this attempt covered a durable component generation. Its retry
    # is reconstructed from that component row, so the process-local timer
    # must re-enter reconciliation rather than enqueue blindly.
    followup_retry_managed: bool = False


def auto_retry_requested_by(original: str) -> str:
    """The retry job's durable requester label, marker prefix included."""

    return f"{AUTO_RETRY_REQUESTED_BY_PREFIX} ({original})"[:120]


def component_followup_requested_by(original: str) -> str:
    """Keep the evidence retry budget independent from a component retry.

    A successful automatic *component* retry still starts the first evidence
    attempt for that new component generation.  Carrying the component job's
    ``automatic retry`` prefix into that evidence job would incorrectly spend
    the evidence job's own one-retry budget before it had made any attempt.
    """

    if not original.startswith(AUTO_RETRY_REQUESTED_BY_PREFIX):
        return original
    return f"component follow-up ({original})"[:120]


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
                if not _close_stale_job_if_unchanged(session, active):
                    session.rollback()
                    continue
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
                if not _close_stale_job_if_unchanged(session, active):
                    session.rollback()
                    continue
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


def _timestamp_after(value: datetime | None, boundary: datetime | None) -> bool:
    """Compare persisted UTC timestamps conservatively across DB backends."""

    if value is None or boundary is None:
        return False
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    if boundary.tzinfo is None:
        boundary = boundary.replace(tzinfo=timezone.utc)
    # Equality can be a database timestamp-resolution tie between an older
    # scope claim and the later component commit. One redundant sweep is safer
    # than declaring that ambiguous generation covered.
    return value > boundary


def _close_stale_job_if_unchanged(session: Session, job: SyncJob) -> bool:
    """Close a stale lease only if no other process refreshed it meanwhile."""

    if not _job_heartbeat_stale(job):
        return False
    observed_heartbeat = job.updated_at
    heartbeat_unchanged = (
        SyncJob.updated_at.is_(None)
        if observed_heartbeat is None
        else SyncJob.updated_at == observed_heartbeat
    )
    finished = utcnow()
    previous_phase = job.phase
    if job.kind == EVIDENCE_SYNC_KIND:
        message = "Evidence sync was interrupted by a server restart."
        error = (
            f"Server restarted during phase '{previous_phase}'. Evidence and files "
            "already mirrored remain valid; start the sync again to continue."
        )
    else:
        message = "Component sync was interrupted by a server restart."
        error = (
            f"Server restarted during phase '{previous_phase}'; "
            "no partial mirror changes were committed. Start the sync again."
        )
    closed = session.execute(
        update(SyncJob)
        .where(
            SyncJob.id == job.id,
            SyncJob.status.in_(ACTIVE_SYNC_STATUSES),
            SyncJob.active_key == job.active_key,
            heartbeat_unchanged,
        )
        .values(
            status="interrupted",
            message=message,
            error=error,
            active_key=None,
            updated_at=finished,
            finished_at=finished,
        )
        .execution_options(synchronize_session=False)
    )
    return closed.rowcount == 1


class SyncJobManager:
    """Submit sync jobs to one background worker per job kind.

    The database's unique ``active_key`` is the actual per-scope single-flight
    guard. Each kind (components / evidence) owns a single worker thread, so
    mirror writes stay serialized per kind while a multi-hour evidence sweep
    can no longer starve a component sync queued behind it. Jobs that are
    queued but still waiting for their worker get their durable heartbeat
    refreshed by a keeper thread — otherwise a job waiting longer than
    ``SYNC_HEARTBEAT_GRACE`` would look orphaned and be closed by lease
    takeover although this process is alive and will run it.
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
        self._component_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="itkflow-sync-components"
        )
        self._evidence_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="itkflow-sync-evidence"
        )
        self._retry_timers: list[threading.Timer] = []
        self._retry_lock = threading.Lock()
        # Job ids this process submitted that may still be waiting in an
        # executor queue. The keeper thread refreshes their heartbeats while
        # they are queued and forgets them as soon as they progress.
        self._queued_watch: set[int] = set()
        self._watch_lock = threading.Lock()
        self._watch_stop = threading.Event()
        self._watch_thread: threading.Thread | None = None
        self._resume_evidence_followups()

    def start(self, job_id: int, fetcher: ComponentFetcher) -> None:
        def schedule_retry(context: ComponentSyncContext) -> None:
            self._schedule_retry(lambda: self._start_component_retry(fetcher, context))

        self._watch_queued(job_id)
        self._component_executor.submit(
            run_component_sync_job,
            self._session_factory,
            self._settings,
            fetcher,
            job_id,
            self.enqueue_evidence,
            schedule_retry,
        )

    def start_evidence(self, job_id: int) -> None:
        self._watch_queued(job_id)
        try:
            future = self._evidence_executor.submit(
                run_evidence_sync_job,
                self._session_factory,
                self._settings,
                self._evidence_gateway_factory,
                job_id,
                self._schedule_evidence_retry,
            )
        except Exception:
            # A rejected submit has no Future whose completion callback could
            # clean up the watch. Leaving it watched would keep a never-run
            # queued lease fresh forever.
            self._unwatch_queued(job_id)
            raise
        if isinstance(future, Future):
            future.add_done_callback(
                lambda _completed, completed_id=job_id: self._after_evidence_future(
                    completed_id
                )
            )

    def _resume_evidence_followups(self) -> None:
        """Reconcile durable component-success generations after startup."""

        with self._session_factory() as session:
            jobs = list(
                session.scalars(
                    select(SyncJob).where(
                        SyncJob.kind == COMPONENT_SYNC_KIND,
                        SyncJob.status == "succeeded",
                    )
                )
            )
            institute_codes = {
                job.institute_code
                for job in jobs
                if bool((job.result or {}).get(EVIDENCE_FOLLOWUP_PENDING_KEY))
            }
        for institute_code in institute_codes:
            self._submit_followup_reconcile(institute_code)

    def _submit_followup_reconcile(self, institute_code: str) -> None:
        if self._watch_stop.is_set():
            return
        try:
            self._evidence_executor.submit(
                self._reconcile_evidence_followup, institute_code
            )
        except RuntimeError:
            if not self._watch_stop.is_set():
                log.error(
                    "Could not schedule evidence follow-up reconciliation for %s.",
                    institute_code,
                )

    def _after_evidence_future(self, job_id: int) -> None:
        """Retry an unclaimed row or reconcile its component generation."""

        if self._watch_stop.is_set():
            return
        with self._session_factory() as session:
            job = session.get(SyncJob, job_id)
            if job is None:
                return
            institute_code = job.institute_code
            status = job.status
        if status == "queued":
            # A component transaction can be active when this evidence worker
            # first reaches the queue. Its durable row stays canonical and a
            # later attempt claims it after that commit becomes visible.
            self._schedule_retry(lambda: self.start_evidence(job_id))
            return
        self._submit_followup_reconcile(institute_code)

    @staticmethod
    def _after(value: datetime | None, boundary: datetime | None) -> bool:
        return _timestamp_after(value, boundary)

    def _reconcile_evidence_followup(
        self, institute_code: str, *, retry_now: bool = False
    ) -> None:
        """Ensure the latest committed component generation gets one attempt."""

        if self._watch_stop.is_set():
            return
        try:
            with self._session_factory() as session:
                component_jobs = list(
                    session.scalars(
                        select(SyncJob)
                        .where(
                            SyncJob.kind == COMPONENT_SYNC_KIND,
                            SyncJob.institute_code == institute_code,
                            SyncJob.status == "succeeded",
                        )
                        .order_by(SyncJob.id.desc())
                    )
                )
                pending = [
                    job
                    for job in component_jobs
                    if bool((job.result or {}).get(EVIDENCE_FOLLOWUP_PENDING_KEY))
                ]
                if not pending:
                    return
                latest_component = pending[0]
                attempts = list(
                    session.scalars(
                        select(SyncJob)
                        .where(
                            SyncJob.kind == EVIDENCE_SYNC_KIND,
                            SyncJob.institute_code == institute_code,
                            SyncJob.started_at.is_not(None),
                        )
                        .order_by(SyncJob.started_at.desc(), SyncJob.id.desc())
                    )
                )
                covering_attempt = next(
                    (
                        job
                        for job in attempts
                        if self._after(job.started_at, latest_component.finished_at)
                    ),
                    None,
                )
                if covering_attempt is not None and covering_attempt.status == "succeeded":
                    for component_job in pending:
                        result = dict(component_job.result or {})
                        result[EVIDENCE_FOLLOWUP_PENDING_KEY] = False
                        result.pop(EVIDENCE_FOLLOWUP_RETRY_KEY, None)
                        component_job.result = result
                    session.commit()
                    return
                if (
                    covering_attempt is not None
                    and covering_attempt.status == "interrupted"
                    and covering_attempt.requested_by.startswith(
                        AUTO_RETRY_REQUESTED_BY_PREFIX
                    )
                ):
                    # The one automatic retry had already started when its
                    # owning process died. Treat that budget as consumed; a
                    # restart must not silently turn it into a fresh first
                    # attempt with another retry of its own.
                    for component_job in pending:
                        if not _timestamp_after(
                            covering_attempt.started_at, component_job.finished_at
                        ):
                            continue
                        result = dict(component_job.result or {})
                        result[EVIDENCE_FOLLOWUP_RETRY_KEY] = (
                            FOLLOWUP_RETRY_EXHAUSTED
                        )
                        component_job.result = result
                    session.commit()
                    return
                if covering_attempt is not None and covering_attempt.status == "failed":
                    retry_state = (latest_component.result or {}).get(
                        EVIDENCE_FOLLOWUP_RETRY_KEY
                    )
                    if retry_state != FOLLOWUP_RETRY_DUE:
                        # Permanent failures and an exhausted automatic retry
                        # stay visible without spinning. A later manual run may
                        # still satisfy and clear the durable intent.
                        return
                    if not retry_now:
                        # Preserve the normal outage backoff. Startup and the
                        # Future callback both discover the same durable state;
                        # any duplicate timers re-check it before acquiring the
                        # unique lease, so they cannot create a second retry.
                        self._schedule_retry(
                            lambda: self._reconcile_evidence_followup(
                                institute_code, retry_now=True
                            )
                        )
                        return
                    requester = auto_retry_requested_by(covering_attempt.requested_by)
                else:
                    requester = component_followup_requested_by(
                        latest_component.requested_by
                    )
                user_id = latest_component.user_id

            if user_id is None:
                log.error(
                    "Component evidence follow-up for %s has no credential owner.",
                    institute_code,
                )
                return
            with self._session_factory() as session:
                lease = acquire_evidence_sync_lease(
                    session,
                    institute_code=institute_code,
                    requested_by=requester,
                    user_id=user_id,
                )
            if lease.created:
                try:
                    self.start_evidence(lease.job.id)
                except Exception:
                    fail_sync_job(
                        self._session_factory,
                        lease.job.id,
                        "Evidence sync could not be scheduled.",
                    )
                    # Keep the component intent durable, but avoid a timer loop
                    # that would manufacture one failed queued row per minute
                    # while an executor is permanently broken. A later startup
                    # or manual reconciliation can try the released lease.
                    self._submit_followup_reconcile(institute_code)
                    return
            else:
                # Another process (or the older snapshot) owns the canonical
                # scope. Recheck after it finishes or crosses the normal stale
                # heartbeat grace; never take over a fresh live worker.
                self._schedule_retry(
                    lambda: self._submit_followup_reconcile(institute_code)
                )
        except Exception:
            log.error(
                "Could not reconcile evidence after the component sync for %s.",
                institute_code,
            )
            if not self._watch_stop.is_set():
                self._schedule_retry(
                    lambda: self._submit_followup_reconcile(institute_code)
                )

    # -- queued-job heartbeat keeper ----------------------------------------

    def _watch_queued(self, job_id: int) -> None:
        with self._watch_lock:
            self._queued_watch.add(job_id)
            if self._watch_thread is None or not self._watch_thread.is_alive():
                self._watch_thread = threading.Thread(
                    target=self._queued_heartbeat_loop,
                    name="itkflow-sync-queued-heartbeat",
                    daemon=True,
                )
                self._watch_thread.start()

    def _unwatch_queued(self, job_id: int) -> None:
        with self._watch_lock:
            self._queued_watch.discard(job_id)

    def _queued_heartbeat_loop(self) -> None:
        while not self._watch_stop.wait(QUEUED_HEARTBEAT_INTERVAL_SECONDS):
            self._refresh_queued_heartbeats()

    def _refresh_queued_heartbeats(self) -> None:
        """Keep owned, still-queued jobs looking alive while they wait."""

        with self._watch_lock:
            watched = list(self._queued_watch)
        finished: list[int] = []
        for job_id in watched:
            try:
                with self._session_factory() as session:
                    job = session.get(SyncJob, job_id)
                    if job is None or job.status != "queued":
                        # Running jobs heartbeat through their own progress
                        # writes; terminal jobs need nothing anymore.
                        finished.append(job_id)
                        continue
                    job.updated_at = utcnow()
                    session.commit()
            except Exception:
                # Best effort: a busy database simply means the next tick
                # refreshes instead. Telemetry must never kill the keeper.
                log.warning(
                    "Could not refresh the queued heartbeat for sync job %s", job_id
                )
        with self._watch_lock:
            self._queued_watch.difference_update(finished)

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
            try:
                self.start_evidence(lease.job.id)
            except Exception:
                # Lease creation is already committed. Release that lease and
                # leave a truthful terminal row so a durable component marker
                # or a manual start can enqueue a replacement.
                fail_sync_job(
                    self._session_factory,
                    lease.job.id,
                    "Evidence sync could not be scheduled.",
                )
                self._submit_followup_reconcile(institute_code)
                raise
        else:
            self._submit_followup_reconcile(institute_code)
        return lease

    # -- bounded automatic retry after a transient job failure --------------
    #
    # No durable row exists while the delay timer runs: the failed job stays
    # visible and lease-free, so a person can start a new sync at any moment.
    # When the timer fires it goes through the normal lease acquisition — if
    # someone already queued a job, the retry converges on it instead of
    # stacking a second one. A standalone evidence/component retry remains
    # process-local; component-follow-up evidence additionally persists its
    # retry verdict on the component job and reconstructs this timer at boot.

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
            if context.followup_retry_managed:
                self._reconcile_evidence_followup(
                    context.institute.code, retry_now=True
                )
                return
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
        self._watch_stop.set()
        with self._retry_lock:
            timers, self._retry_timers = self._retry_timers, []
        for timer in timers:
            timer.cancel()
        self._component_executor.shutdown(wait=False, cancel_futures=True)
        self._evidence_executor.shutdown(wait=False, cancel_futures=True)


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
            if on_success is not None:
                # This private extra survives the component commit but is
                # ignored by ComponentSyncOut. It is the restart-safe wake-up
                # intent; evidence reconciliation clears it only after a
                # post-commit snapshot attempt reaches a terminal outcome.
                result[EVIDENCE_FOLLOWUP_PENDING_KEY] = True
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
                    component_followup_requested_by(context.requested_by),
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
        component_sync = session.scalar(
            select(SyncJob).where(
                SyncJob.active_key == COMPONENT_SYNC_ACTIVE_KEY
            )
        )
        if component_sync is not None:
            if not _job_heartbeat_stale(component_sync):
                return None
            if not _close_stale_job_if_unchanged(session, component_sync):
                session.rollback()
                return None
            session.commit()
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
        user_id = job.user_id
        requested_by = job.requested_by
        expected_active_key = job.active_key
        if expected_active_key is None:
            return None
        canonical_active_key = evidence_sync_active_key(job.institute_code)
        started = utcnow()
        try:
            claimed = session.execute(
                update(SyncJob)
                .where(
                    SyncJob.id == job_id,
                    SyncJob.status == "queued",
                    SyncJob.active_key == expected_active_key,
                )
                .values(
                    status="running",
                    phase="fetching",
                    current=0,
                    total=None,
                    percent=None,
                    message="Loading the local evidence sync scope.",
                    result=None,
                    active_key=canonical_active_key,
                    started_at=started,
                    updated_at=started,
                )
                .execution_options(synchronize_session=False)
            )
            if claimed.rowcount != 1:
                session.rollback()
                return None
            # The conditional UPDATE is the final cross-process claim arbiter.
            session.expunge(institute)
            session.commit()
        except IntegrityError:
            session.rollback()
            return None
        except OperationalError as exc:
            session.rollback()
            if _is_sqlite_busy(exc):
                # The Future completion callback resubmits this still-queued
                # row; a transient SQLite writer must not turn it into a
                # terminal failed sync and lose the durable component intent.
                return None
            raise
        return EvidenceSyncContext(
            institute=institute,
            user_id=user_id,
            requested_by=requested_by,
            auto_retry=requested_by.startswith(AUTO_RETRY_REQUESTED_BY_PREFIX),
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


@dataclass(frozen=True)
class MirroredEvidence:
    """What the local mirror already knows about one scope's PDB test runs.

    Read once per sweep, in bounded chunks, and used for three different
    questions:

    * `known_flat` — which runs may skip their detail round trip (the
      incremental contract; only rows that really carry mirrored detail).
    * `live_refs` — which runs of a component the PDB still stood behind last
      time. The batched index has to account for every one of them, or its
      answer for that component is not provably complete.
    * `run_meta` — the mirrored `(run_state, measured_at)` of a run, so a
      batched answer can never write "unknown" over something we know. That
      would silently un-withdraw a retracted run, or drop the timestamp that
      decides which run is the latest one.
    """

    known_flat: dict[str, tuple]
    live_refs: dict[str, set[str]]
    run_meta: dict[str, tuple[str | None, datetime | None]]


def _mirrored_evidence(session: Session, component_sns: list[str]) -> MirroredEvidence:
    known_flat: dict[str, tuple] = {}
    live_refs: dict[str, set[str]] = {}
    run_meta: dict[str, tuple[str | None, datetime | None]] = {}
    if not component_sns:
        return MirroredEvidence(known_flat, live_refs, run_meta)
    # Production scopes reach thousands of serial numbers; keep every IN list
    # bounded (same batch size as the tool sync). The payload JSON column is
    # still read whole per chunk: its `detail_synced`/`state`/`problems` keys
    # would need dialect-specific JSON extraction to project in SQL, and that
    # is not worth a behavioural risk between SQLite and PostgreSQL.
    for offset in range(0, len(component_sns), FINGERPRINT_CHUNK_SIZE):
        sn_chunk = component_sns[offset : offset + FINGERPRINT_CHUNK_SIZE]
        rows = session.execute(
            select(
                TestRunEvidence.component_sn,
                TestRunEvidence.external_ref,
                TestRunEvidence.passed,
                TestRunEvidence.measured_at,
                TestRunEvidence.run_state,
                TestRunEvidence.payload,
            ).where(
                TestRunEvidence.source == "pdb",
                TestRunEvidence.external_ref.is_not(None),
                TestRunEvidence.component_sn.in_(sn_chunk),
            )
        )
        for component_sn, external_ref, passed, measured_at, run_state, payload in rows:
            payload = payload or {}
            run_meta[external_ref] = (run_state, measured_at)
            if not is_withdrawn(run_state):
                live_refs.setdefault(component_sn, set()).add(external_ref)
            if not payload.get("detail_synced"):
                continue
            known_flat[external_ref] = flat_fingerprint(
                passed=passed,
                measured_at=measured_at,
                state=payload.get("state"),
                problems=payload.get("problems"),
            )
    return MirroredEvidence(known_flat, live_refs, run_meta)


def _mirrored_flat_fingerprints(
    session: Session, component_sns: list[str]
) -> dict[str, tuple]:
    """Fingerprints of mirrored runs that already carry their fetched detail.

    Only rows marked `detail_synced` qualify: a flat-only row (from an older
    sweep, or a run whose detail fetch failed) must take the detail round trip
    on the next sync rather than being frozen in its shallow state.
    """
    return _mirrored_evidence(session, component_sns).known_flat


def index_answer_is_trustworthy(
    component_sn: str,
    runs: Sequence[IndexedTestRun],
    *,
    mirror: MirroredEvidence,
    multi_serial_proven: bool,
) -> bool:
    """Whether the batched index may be believed for this one component.

    Completeness over speed. Three ways an answer stays unproven, each of which
    sends exactly that component back through `getComponent` rather than
    letting it look like a component with fewer runs than it has:

    1. It does not account for a run we mirrored as live. A withdrawal and a
       lossy filter are indistinguishable from here, and only one of them is
       safe to believe. (A run already mirrored as `deleted` is exempt: that
       state is terminal, so the index dropping it proves nothing.)
    2. It would replace a known run state or a known timestamp with "unknown".
    3. It reports *no* runs at all while the same batch never demonstrated that
       the multi-serial filter was honoured — "this component has nothing" is
       exactly the answer a silently ignored filter produces.
    """
    indexed_refs = {run.run_id for run in runs}
    if mirror.live_refs.get(component_sn, set()) - indexed_refs:
        return False
    for run in runs:
        previous = mirror.run_meta.get(run.run_id)
        if previous is None:
            continue
        previous_state, previous_measured_at = previous
        if previous_state is not None and run.run_state is None:
            return False
        if previous_measured_at is not None and run.measured_at is None:
            return False
    return bool(runs) or multi_serial_proven


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

        # What the mirror already holds, read once: which runs may skip their
        # detail round trip (the incremental contract), which runs a batched
        # answer has to account for, and which states/timestamps it may not
        # overwrite with "unknown".
        with session_factory() as mirror_session:
            mirror = _mirrored_evidence(mirror_session, component_sns)
        known_flat = mirror.known_flat

        component_total = len(component_sns)
        evidence_stats = EvidenceSyncStats()
        runs_seen = 0
        completed = 0
        _update_progress(
            session_factory,
            job_id,
            "fetching",
            0,
            component_total,
            message=f"Fetching detailed evidence for {component_total} components.",
        )

        def commit_component_records(records: list) -> None:
            # Commit each component as it arrives. A whole-institute sweep runs
            # for a long time; collecting everything for one final transaction
            # meant that closing the app — or any PDB hiccup — discarded every
            # fetched run, and the UI then showed each required test as
            # "missing". The upsert is idempotent, so a resumed sweep simply
            # re-confirms.
            nonlocal evidence_stats, runs_seen
            runs_seen += len(records)
            if not records:
                return
            with session_factory() as evidence_session:
                batch_stats = upsert_test_run_evidence(evidence_session, records)
                evidence_session.commit()
            evidence_stats = EvidenceSyncStats(
                created=evidence_stats.created + batch_stats.created,
                updated=evidence_stats.updated + batch_stats.updated,
                unchanged=evidence_stats.unchanged + batch_stats.unchanged,
            )

        def report_component_done() -> None:
            # One shared counter for both routes, so a sweep that mirrors part
            # of its scope in batches and re-reads the rest per component still
            # counts every component exactly once and never moves backwards.
            nonlocal completed
            completed += 1
            _update_progress(
                session_factory,
                job_id,
                "fetching",
                completed,
                component_total,
                message=(
                    f"Fetched {completed}/{component_total} components "
                    f"and {runs_seen} test runs."
                ),
            )

        def calibrate_index(probe_sn: str, indexed_runs: Sequence[IndexedTestRun]) -> None:
            """Check the batched index against the endpoint we already trust.

            One extra `getComponent` per sweep buys the only real evidence
            available offline that `listTestRunsByComponent` reports the same
            runs, the same pass/fail, the same state and the same timestamps as
            the path the whole mirror was built on. Disagreement demotes the
            sweep rather than quietly mirroring a second opinion.
            """
            probe = fetch_test_run_evidence(gateway, probe_sn, with_detail=False, strict=True)
            listed = {
                record.external_ref: (
                    record.test_type,
                    flat_fingerprint(
                        passed=record.passed,
                        measured_at=record.measured_at,
                        state=(record.payload or {}).get("state"),
                        problems=(record.payload or {}).get("problems"),
                    ),
                )
                for record in probe
                if record.external_ref
            }
            observed = {run.run_id: (run.test_type, run.fingerprint) for run in indexed_runs}
            if listed != observed:
                raise PdbIndexUnusable(
                    "The batched test-run index disagrees with getComponent about "
                    f"{probe_sn} ({len(observed)} indexed run(s) against "
                    f"{len(listed)} listed)."
                )

        def sweep_via_index(serial_numbers: list[str]) -> list[str]:
            """Mirror what the batched endpoints can prove; return the rest.

            Three steps per batch: index the runs of many components in one
            request, diff them against the mirrored fingerprints exactly as the
            per-component sweep does, then pull the detail of the new/changed
            runs in bulk. Anything unproven is returned to the caller for the
            per-component path — never mirrored as if it were whole.
            """
            try:
                client = gateway.client()
            except Exception:
                # The per-component path owns the canonical "no connection"
                # failure; producing a second phrasing here would only make the
                # same outage look like two different problems.
                return list(serial_numbers)

            deferred: list[str] = []
            batch_size = max(1, int(getattr(settings, "sync_evidence_index_batch_size", 50)))
            page_size = max(1, int(getattr(settings, "sync_evidence_index_page_size", 100)))
            bulk_size = max(1, int(getattr(settings, "sync_evidence_bulk_batch_size", 50)))
            calibrated = False
            bulk_usable = True

            def batch_retry_heartbeat(attempt: int) -> None:
                _update_progress(
                    session_factory,
                    job_id,
                    "fetching",
                    completed,
                    component_total,
                    message=(
                        "Retrying a batched PDB test-run read after a transient "
                        f"error (attempt {attempt + 1}/"
                        f"{settings.sync_page_max_attempts})."
                    ),
                )

            def batch_progress_heartbeat(seen: int, total: int | None) -> None:
                # Fired per index page and per bulk batch. A batch can span
                # several slow pages while no component finishes, and a job
                # that stays silent past SYNC_HEARTBEAT_GRACE is reaped as
                # orphaned by any second instance.
                _update_progress(
                    session_factory,
                    job_id,
                    "fetching",
                    completed,
                    component_total,
                    message=(
                        f"Indexing test runs in batches ({completed}/"
                        f"{component_total} components done; {seen}"
                        f"{f' of {total}' if total is not None else ''} runs read)."
                    ),
                )

            for start in range(0, len(serial_numbers), batch_size):
                batch = serial_numbers[start : start + batch_size]
                try:
                    indexed = fetch_test_run_index(
                        client,
                        batch,
                        page_size=page_size,
                        max_attempts=settings.sync_page_max_attempts,
                        on_retry=batch_retry_heartbeat,
                        on_page=batch_progress_heartbeat,
                        sleeper=sleep,
                    )
                    if not calibrated:
                        calibrate_index(batch[0], indexed.get(batch[0]) or [])
                        calibrated = True
                except PdbIndexUnusable as exc:
                    # Not an outage — this PDB does not answer in a way we can
                    # verify. Hand the remainder to the proven path in one go
                    # instead of buying a doomed request per batch.
                    log.info(
                        "Batched evidence index unusable; the rest of job %s uses "
                        "the per-component sweep: %s",
                        job_id,
                        exc,
                    )
                    deferred.extend(serial_numbers[start:])
                    return deferred

                # Did this batch demonstrate that the multi-serial filter was
                # honoured at all? Runs attributed to two different requested
                # components is the cheapest available proof, and it is what
                # makes an empty answer for a third component believable.
                multi_serial_proven = sum(1 for runs in indexed.values() if runs) >= 2
                trusted: dict[str, list[IndexedTestRun]] = {}
                for component_sn in batch:
                    runs = indexed.get(component_sn) or []
                    if index_answer_is_trustworthy(
                        component_sn,
                        runs,
                        mirror=mirror,
                        multi_serial_proven=multi_serial_proven,
                    ):
                        trusted[component_sn] = runs
                    else:
                        deferred.append(component_sn)

                changed_runs = [
                    run.run_id
                    for runs in trusted.values()
                    for run in runs
                    if known_flat.get(run.run_id) != run.fingerprint
                ]
                details: dict[str, dict[str, Any]] = {}
                if changed_runs and bulk_usable:
                    details, bulk_usable = fetch_test_run_details_bulk(
                        client,
                        changed_runs,
                        batch_size=bulk_size,
                        max_attempts=settings.sync_page_max_attempts,
                        on_retry=batch_retry_heartbeat,
                        on_batch=lambda seen: batch_progress_heartbeat(seen, None),
                        sleeper=sleep,
                    )

                for component_sn in batch:
                    runs = trusted.get(component_sn)
                    if runs is None:
                        continue
                    commit_component_records(
                        records_from_index(
                            runs,
                            details=details,
                            known_flat=known_flat,
                            # A run the bulk answer skipped is repaired with the
                            # same single-run call the per-component sweep uses,
                            # so a partial bulk answer costs requests, not data.
                            repair=lambda run_id: fetch_test_run_detail(client, run_id),
                        )
                    )
                    report_component_done()
            return deferred

        def sweep_per_component(serial_numbers: list[str]) -> None:
            """The proven route: one `getComponent` per component, plus one
            `getTestRun` per new or changed run."""

            if not serial_numbers:
                return
            fetch_concurrency = max(1, int(getattr(settings, "sync_fetch_concurrency", 1)))
            if fetch_concurrency == 1:
                # Fully serial sweep (the historical behavior, selectable via
                # ITKFLOW_SYNC_FETCH_CONCURRENCY=1): one shared gateway, and the
                # retry ladder writes its own heartbeat before every backoff.
                for component_sn in serial_numbers:

                    def fetch_retry_heartbeat(attempt: int, *, sn: str = component_sn) -> None:
                        _update_progress(
                            session_factory,
                            job_id,
                            "fetching",
                            completed,
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
                    commit_component_records(records)
                    report_component_done()
                return

            # Bounded fetch pool: the per-component evidence reads
            # (getComponent plus per-run getTestRun) are independent network
            # round trips — on a real sweep they dominate the runtime at
            # roughly a second each, strictly one after another. Each worker
            # builds its own gateway because itkdb clients subclass
            # requests.Session and are NOT thread-safe, while every database
            # write (evidence commits, progress rows) stays on this job
            # thread. Results are consumed in submission order, so commits,
            # progress and the failure point are as deterministic as the
            # serial sweep and memory stays bounded by the pool width.
            thread_gateways = threading.local()

            def fetch_component(sn: str):
                worker_gateway = getattr(thread_gateways, "gateway", None)
                if worker_gateway is None:
                    worker_gateway = gateway_factory(settings, access_codes)
                    thread_gateways.gateway = worker_gateway
                return _fetch_evidence_with_retry(
                    worker_gateway,
                    sn,
                    known_flat=known_flat,
                    max_attempts=settings.sync_page_max_attempts,
                )

            pool = ThreadPoolExecutor(
                max_workers=fetch_concurrency,
                thread_name_prefix="itkflow-evidence-fetch",
            )
            try:
                pending: deque[tuple[str, Future]] = deque()
                submitted: set[Future] = set()
                sn_iter = iter(serial_numbers)

                def top_up() -> None:
                    while len(pending) < fetch_concurrency:
                        next_sn = next(sn_iter, None)
                        if next_sn is None:
                            return
                        future = pool.submit(fetch_component, next_sn)
                        submitted.add(future)
                        pending.append((next_sn, future))

                top_up()
                while pending:
                    component_sn, future = pending.popleft()
                    top_up()
                    while True:
                        done, _ = futures_wait(
                            [future], timeout=PARALLEL_FETCH_HEARTBEAT_SECONDS
                        )
                        if done:
                            break
                        # The retry ladders now run inside the fetch workers,
                        # which never write the database; this wait-side
                        # heartbeat keeps the durable row visibly alive.
                        _update_progress(
                            session_factory,
                            job_id,
                            "fetching",
                            completed,
                            component_total,
                            message=(
                                f"Fetching evidence ({completed}/{component_total} "
                                "components done; waiting on in-flight PDB reads)."
                            ),
                        )
                    # Raises PdbEvidenceUnavailable once this component's own
                    # retry budget is exhausted — the job then fails
                    # transiently, exactly like the serial sweep.
                    records = future.result()
                    commit_component_records(records)
                    report_component_done()
            finally:
                # Stop work that has not started, then drain active reads with
                # the same heartbeat cadence as the normal consume loop. A
                # sibling can still be inside its full retry ladder when the
                # first Future fails; a bare shutdown(wait=True) could stay
                # silent past SYNC_HEARTBEAT_GRACE and let another process
                # steal this live lease.
                for submitted_future in submitted:
                    if not submitted_future.done():
                        submitted_future.cancel()
                active = [future for future in submitted if not future.done()]
                while active:
                    futures_wait(active, timeout=PARALLEL_FETCH_HEARTBEAT_SECONDS)
                    active = [future for future in active if not future.done()]
                    if active:
                        _update_progress(
                            session_factory,
                            job_id,
                            "fetching",
                            completed,
                            component_total,
                            message=(
                                "Stopping in-flight PDB reads after a fetch failure; "
                                f"{len(active)} still running."
                            ),
                        )
                pool.shutdown(wait=True, cancel_futures=True)

        # Index-then-bulk first, per component for whatever it could not prove.
        # `per_component` restores the historical sweep without a code change.
        outstanding = list(component_sns)
        if getattr(settings, "sync_evidence_strategy", "index_bulk") == "index_bulk":
            outstanding = sweep_via_index(outstanding)
        sweep_per_component(outstanding)

        # One planning pass drives both the file total and the downloads.
        # Short-lived sessions on purpose: each component's evidence rows
        # (payload JSON included) enter one identity map briefly and are
        # released again, instead of the whole evidence scope accumulating in
        # a single session only to be re-read per component during the
        # download loop.
        attachment_plan: list[tuple[str, list[dict[str, Any]]]] = []
        attachment_total = 0
        for component_sn in component_sns:
            with session_factory() as plan_session:
                descriptors = pending_attachments(plan_session, component_sn)
            if descriptors:
                attachment_plan.append((component_sn, descriptors))
                attachment_total += len(descriptors)
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

        # Outage circuit breaker across the whole phase: every transient file
        # failure has already burned its full retry ladder, so several in a
        # row mean the connection is down. Without this, hundreds of pending
        # files each crawled through minutes of retries while the job looked
        # alive — the "frozen sync" a person actually observes.
        breaker = OutageCircuitBreaker()
        for component_index, (component_sn, descriptors) in enumerate(
            attachment_plan, start=1
        ):
            with session_factory() as attachment_session:
                stats = download_attachments(
                    attachment_session,
                    gateway,
                    settings,
                    component_sn,
                    heartbeat=attachment_heartbeat,
                    descriptors=descriptors,
                    breaker=breaker,
                )
                attachment_session.commit()
            attachment_stats = AttachmentSyncStats(
                downloaded=attachment_stats.downloaded + stats.downloaded,
                reused=attachment_stats.reused + stats.reused,
                failed=attachment_stats.failed + stats.failed,
            )
            processed_files += stats.total
            if breaker.tripped:
                # Everything mirrored so far is already committed and the
                # upserts are idempotent — failing transiently hands the rest
                # to the existing single automatic retry instead of crawling.
                raise PdbEvidenceUnavailable(
                    "Attachment mirroring hit repeated transient network "
                    "failures; files mirrored so far are kept and the sync "
                    "will be retried."
                )
            _update_progress(
                session_factory,
                job_id,
                "attachments",
                processed_files,
                attachment_total,
                message=(
                    f"Mirrored attachments for {component_index}/{len(attachment_plan)} "
                    f"components ({processed_files}/{attachment_total} files)."
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
        followup_retry_state: Literal["due", "blocked", "exhausted"] | None = None
        if context is not None:
            if _is_transient_job_failure(exc):
                followup_retry_state = (
                    FOLLOWUP_RETRY_EXHAUSTED
                    if context.auto_retry
                    else FOLLOWUP_RETRY_DUE
                )
            else:
                followup_retry_state = FOLLOWUP_RETRY_BLOCKED
        followup_retry_managed = fail_sync_job(
            session_factory,
            job_id,
            detail,
            followup_retry_state=followup_retry_state,
        )
        retry_context = (
            replace(context, followup_retry_managed=followup_retry_managed)
            if context is not None
            else None
        )
        _maybe_schedule_auto_retry(exc, retry_context, on_transient_failure)


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
    session_factory: sessionmaker[Session],
    job_id: int,
    error: Exception | str,
    *,
    followup_retry_state: Literal["due", "blocked", "exhausted"] | None = None,
) -> bool:
    """Move a live job to failed and release its lease.

    For an evidence attempt that covered a pending component generation, the
    retry verdict is written into that component job's private result in the
    same transaction.  A crash can therefore lose the process-local timer but
    never the information needed to recreate exactly its one allowed retry.
    """

    detail = (
        error.strip() if isinstance(error, str) else _public_sync_error(error).strip()
    ) or "Component sync failed."
    followup_retry_managed = False
    with session_factory() as session:
        job = session.get(SyncJob, job_id)
        if job is None or job.status not in ACTIVE_SYNC_STATUSES:
            return False
        finished = utcnow()
        job.status = "failed"
        job.message = (
            "Evidence sync failed." if job.kind == EVIDENCE_SYNC_KIND else "Component sync failed."
        )
        job.error = detail[:8000]
        job.active_key = None
        job.updated_at = finished
        job.finished_at = finished
        if (
            job.kind == EVIDENCE_SYNC_KIND
            and job.started_at is not None
            and followup_retry_state is not None
        ):
            component_jobs = session.scalars(
                select(SyncJob).where(
                    SyncJob.kind == COMPONENT_SYNC_KIND,
                    SyncJob.institute_code == job.institute_code,
                    SyncJob.status == "succeeded",
                )
            )
            for component_job in component_jobs:
                result = dict(component_job.result or {})
                if not bool(result.get(EVIDENCE_FOLLOWUP_PENDING_KEY)):
                    continue
                if not _timestamp_after(job.started_at, component_job.finished_at):
                    continue
                result[EVIDENCE_FOLLOWUP_RETRY_KEY] = followup_retry_state
                component_job.result = result
                followup_retry_managed = True
        session.commit()
    return followup_retry_managed


def recover_interrupted_sync_jobs(session_factory: sessionmaker[Session]) -> int:
    """Close stale process-owned jobs before follow-up reconciliation.

    Only jobs whose progress heartbeat has gone stale are closed. Starting a
    second app instance therefore no longer aborts a sync the first one is
    still running — that turned "open the app again" into "lose the sync",
    observed against production at 600 of 3766 components. A pending component
    generation lives in the terminal component result, so closing an orphaned
    evidence attempt cannot lose the startup-resumable intent.
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
            if _close_stale_job_if_unchanged(session, job):
                recovered += 1
        session.commit()
    return recovered
