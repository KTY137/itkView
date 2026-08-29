# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-FileComment: itkflow-5d85668cae7a
"""Keep the local mirror fresh without anyone pressing a button.

A sweep used to be worth avoiding: one request per in-scope component meant
1170 requests for a site like TUDO, so refreshing on a timer would have been
rude to a shared production database. Index-then-bulk (docs/09) cut a repeat
sweep to roughly 150 requests, which is what makes a scheduled refresh
reasonable at all — the cheap primitive, not the scheduler, is the reason this
module can exist.

Deliberate limits, because this is the only place in itkFlow where PDB traffic
happens with nobody watching:

* **Opt-in, per institute.** The schedule lives in the institute profile
  (`settings["auto_sync"]`, edited in Admin Settings) and is absent by
  default, so a site that configured nothing never talks to the PDB on a
  timer. `auto_sync_poll_minutes` is deployment-level only — how often the
  scheduler evaluates that profile; `0` switches the scheduler off outright.
* **It only ever continues what a person started.** The scheduler holds no
  credentials of its own and never picks an arbitrary account. For each
  institute it runs as the person whose own component sync last succeeded
  there — someone who already chose to mirror this institute — and only while
  that account is still active, still has operator/admin authority in the same
  institute scope, and still has usable connected codes. An institute nobody
  has ever synced by hand is never synced automatically.
* **It cannot stack.** Jobs are created through the same durable
  `active_key` lease as the UI, so a scheduled run converges on a sweep that
  is already going rather than queueing behind it.
* **It reads.** A component sync and the evidence job it chains (ADR 006) are
  read-only mirrors; `pdb_write_scope="dummy_only"` is untouched by this
  module, and no write path passes through it.
* **It is honest.** Jobs carry `SCHEDULED_REQUESTED_BY_PREFIX` in
  `requested_by`, so the UI shows a scheduled refresh as exactly that instead
  of implying the named person clicked something.
"""

import asyncio
import logging
import re
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import is_sqlite_busy
from app.models import InstituteProfile, PdbCredential, SyncJob, User
from app.sync_jobs import (
    AUTO_RETRY_REQUESTED_BY_PREFIX,
    COMPONENT_SYNC_KIND,
    SyncLeaseBusy,
    acquire_component_sync_lease,
    fail_sync_job,
)

log = logging.getLogger(__name__)

# Durable marker on a scheduled job's `requested_by`. Deliberately distinct
# from the auto-retry marker in `app.sync_jobs`: a scheduled run is still
# entitled to its own single retry when the network hiccups.
SCHEDULED_REQUESTED_BY_PREFIX = "scheduled refresh"

# Floor under any configured interval. A misconfigured "1" would point a
# request loop at a shared production database; a quarter of an hour is far
# below anything a production site changes in and still cannot become a
# hammer. Disabling is expressed by `enabled: false`, not by a small interval.
MIN_INTERVAL_MINUTES = 15
MIN_INTERVAL_SECONDS = MIN_INTERVAL_MINUTES * 60
MAX_INTERVAL_MINUTES = 7 * 24 * 60

# Institute-profile key holding the schedule. "How often and when" is an
# institute decision (hard rule 4), edited in Admin Settings, never in code.
AUTO_SYNC_SETTINGS_KEY = "auto_sync"
AUTO_SYNC_FIELDS = frozenset(
    {"enabled", "interval_minutes", "window_start", "window_end", "weekdays"}
)
_HHMM_RE = re.compile(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]\Z")
_USABLE_CREDENTIAL_STATUSES = frozenset({"verified", "unreachable"})


def _parse_hhmm(value: Any) -> time | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if _HHMM_RE.fullmatch(cleaned) is None:
        return None
    try:
        parsed = datetime.strptime(cleaned, "%H:%M")
    except (ValueError, TypeError):
        return None
    return parsed.time()


@dataclass(frozen=True)
class AutoSyncSchedule:
    """When an institute wants its mirror refreshed, and how often.

    Times are wall-clock and evaluated in the **server's local time**. The
    profile deliberately carries no named time zone: desktop deployments use
    the operating-system clock, while Compose installs ``tzdata`` and reads
    ``TZ`` from ``deploy/.env`` (default ``Etc/UTC``). Operators must configure
    that deployment clock to the institute's intended local time before using
    a restricted window. Documented in docs/09 so nobody has to rediscover it.
    """

    enabled: bool = False
    interval_minutes: int = MIN_INTERVAL_MINUTES
    window_start: str | None = None
    window_end: str | None = None
    # ISO weekdays, 1 = Monday … 7 = Sunday. Empty means every day.
    weekdays: tuple[int, ...] = ()

    def _within_window(self, moment: datetime) -> bool:
        start = _parse_hhmm(self.window_start)
        end = _parse_hhmm(self.window_end)
        if start is None or end is None or start == end:
            return True  # no usable window, or a full-day one
        now = moment.time()
        if start < end:
            return start <= now <= end
        # Crossing midnight: "22:00–06:00" is a night shift, not an empty set.
        return now >= start or now <= end

    def _window_day(self, moment: datetime) -> int:
        """The ISO weekday the *window admitting this moment* opened on.

        A Friday 22:00–06:00 window is still running at 02:00 on Saturday.
        Attributing that to Saturday would make "weekdays only" silently
        cancel half of every Friday night.
        """
        start = _parse_hhmm(self.window_start)
        end = _parse_hhmm(self.window_end)
        if (
            start is not None
            and end is not None
            and start > end
            and moment.time() <= end
        ):
            return (moment - timedelta(days=1)).isoweekday()
        return moment.isoweekday()

    def allows(self, local_now: datetime) -> bool:
        """Whether the configured window and weekdays admit this wall clock."""

        if not self.enabled:
            return False
        if not self._within_window(local_now):
            return False
        return not self.weekdays or self._window_day(local_now) in self.weekdays

    def interval_elapsed(
        self,
        utc_now: datetime,
        last_success: datetime | None,
        last_scheduled_attempt: datetime | None = None,
    ) -> bool:
        """Whether enough time passed since success or our last timer attempt.

        A manual failure does not move either boundary: the schedule remains
        free to recover a mirror a person tried to refresh. A failed scheduled
        attempt does move the second boundary, otherwise an old successful
        timestamp would make every deployment poll manufacture a fresh job
        (plus its automatic retry) regardless of the institute's interval.
        """

        observed = [
            value for value in (last_success, last_scheduled_attempt) if value is not None
        ]
        if not observed:
            return True
        last_activity = max(observed)
        # A clock change can leave a "future" last success behind; treat it as
        # recent rather than parking the schedule until the clock catches up.
        return (utc_now - last_activity) >= timedelta(minutes=self.interval_minutes)

    def is_due(
        self,
        *,
        local_now: datetime,
        utc_now: datetime,
        last_success: datetime | None,
        last_scheduled_attempt: datetime | None = None,
    ) -> bool:
        """Whether an unattended sweep should start for this institute now.

        Two clocks on purpose, and they must not be conflated. "When" is a
        wall-clock question a person answered in their own local time, so the
        window and weekday are judged against **local** time. "How often" is a
        duration since a stored timestamp, and those are written in **UTC**;
        measuring that against local time would be wrong by the UTC offset —
        two hours in Berlin summer — which is exactly the kind of quiet error
        this codebase has already paid for twice.
        """

        return self.enabled and self.allows(local_now) and self.interval_elapsed(
            utc_now, last_success, last_scheduled_attempt
        )


def read_auto_sync_schedule(settings: Mapping[str, Any] | None) -> AutoSyncSchedule:
    """Read the schedule out of an institute profile, failing closed.

    Anything malformed is read as "off" rather than repaired into a guess: the
    API validator is what tells a person their input was wrong, and a reader
    that guessed would produce PDB traffic at times nobody chose.
    """

    if not isinstance(settings, Mapping):
        return AutoSyncSchedule()
    block = settings.get(AUTO_SYNC_SETTINGS_KEY)
    if not isinstance(block, Mapping) or set(block) - AUTO_SYNC_FIELDS:
        return AutoSyncSchedule()

    enabled = block.get("enabled")
    if not isinstance(enabled, bool) or not enabled:
        return AutoSyncSchedule()

    raw_interval = block.get("interval_minutes")
    if (
        isinstance(raw_interval, bool)
        or not isinstance(raw_interval, int)
        or not MIN_INTERVAL_MINUTES <= raw_interval <= MAX_INTERVAL_MINUTES
    ):
        return AutoSyncSchedule()

    start_raw, end_raw = block.get("window_start"), block.get("window_end")
    start = end = None
    start_text = end_text = None
    if (start_raw is None) != (end_raw is None):
        return AutoSyncSchedule()
    if start_raw is not None:
        start, end = _parse_hhmm(start_raw), _parse_hhmm(end_raw)
        if start is None or end is None or start == end:
            return AutoSyncSchedule()
        start_text, end_text = start_raw.strip(), end_raw.strip()

    weekdays: tuple[int, ...] = ()
    raw_days = block.get("weekdays")
    if raw_days is not None:
        if not isinstance(raw_days, list) or not raw_days:
            return AutoSyncSchedule()
        parsed: list[int] = []
        for day in raw_days:
            if isinstance(day, bool) or not isinstance(day, int) or not 1 <= day <= 7:
                return AutoSyncSchedule()
            if day in parsed:
                return AutoSyncSchedule()
            parsed.append(day)
        weekdays = tuple(sorted(parsed))

    return AutoSyncSchedule(
        enabled=True,
        interval_minutes=raw_interval,
        window_start=start_text,
        window_end=end_text,
        weekdays=weekdays,
    )


def scheduled_requested_by(owner_email: str) -> str:
    """The requester label for a scheduled job, marker first, owner named.

    The owner is named because their credentials are what reached the PDB and
    an operator deserves to see whose access was used; the marker comes first
    so nothing reads as if that person pressed sync.
    """

    return f"{SCHEDULED_REQUESTED_BY_PREFIX} ({owner_email})"[:120]


def is_scheduled_job(requested_by: str | None) -> bool:
    return bool(requested_by) and requested_by.startswith(SCHEDULED_REQUESTED_BY_PREFIX)


def find_credential_owner(session: Session, institute_code: str) -> User | None:
    """The account a scheduled sweep for this institute may run as.

    Whoever ran the most recent *successful* component sync here by hand, as
    long as that account is still active, still has operator/admin authority in
    the same institute scope, and still has usable connected codes. This is the
    whole authorisation story of this module: the scheduler continues a
    person's own choice and can never widen it. A revoked credential or a
    deactivated/downgraded account silently stops the schedule for that
    institute, which is the correct failure direction.
    """

    institute = session.scalar(
        select(InstituteProfile).where(InstituteProfile.code == institute_code)
    )
    if institute is None:
        return None

    rows = session.execute(
        select(SyncJob.user_id)
        .where(
            SyncJob.kind == COMPONENT_SYNC_KIND,
            SyncJob.institute_code == institute_code,
            SyncJob.status == "succeeded",
            SyncJob.user_id.is_not(None),
        )
        .order_by(SyncJob.finished_at.desc(), SyncJob.id.desc())
    ).all()

    seen: set[int] = set()
    for (user_id,) in rows:
        if user_id in seen:
            continue
        seen.add(user_id)
        user = session.get(User, user_id)
        if (
            user is None
            or not user.is_active
            or user.role not in {"operator", "admin"}
            or (user.institute_id is not None and user.institute_id != institute.id)
        ):
            continue
        credential = session.get(PdbCredential, user_id)
        if credential is None:
            continue
        # Only states the credential subsystem itself knows are usable pass.
        # `unreachable` is deliberately included: that means the network was
        # down when it was last checked, which is precisely the situation a
        # later scheduled attempt should try again. Unknown/corrupt states fail
        # closed just like `invalid`.
        if credential.status not in _USABLE_CREDENTIAL_STATUSES:
            continue
        return user
    return None


def _naive_utc(value: datetime | None) -> datetime | None:
    """SQLite returns timestamps naive, fresh ORM values are aware; comparing
    the two raises, so everything is normalised to naive UTC before use."""

    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


@dataclass(frozen=True)
class InstituteSchedule:
    """One institute's configured schedule plus when it was last swept."""

    code: str
    schedule: AutoSyncSchedule
    last_success: datetime | None
    last_scheduled_attempt: datetime | None


def institutes_by_staleness(session: Session) -> list[InstituteSchedule]:
    """Institute codes, the one that has waited longest first.

    The component-sync lease is deliberately **global** — one authoritative
    mirror fetch at a time across the whole deployment — so a tick can only
    ever start one sweep. With a fixed order (alphabetical, or insertion) the
    first institute would win every tick and a second site would never be
    refreshed at all. Ordering by the newest relevant activity (successful
    sweep or scheduled attempt), oldest first, makes the schedule fair without
    any stored cursor to keep in sync.
    """

    profiles = list(
        session.execute(select(InstituteProfile.code, InstituteProfile.settings)).all()
    )
    codes = [code for code, _ in profiles]
    settings_by_code = {code: settings for code, settings in profiles}
    last_sync = dict(
        session.execute(
            select(SyncJob.institute_code, func.max(SyncJob.finished_at))
            .where(
                SyncJob.kind == COMPONENT_SYNC_KIND,
                SyncJob.status == "succeeded",
            )
            .group_by(SyncJob.institute_code)
        ).all()
    )
    last_scheduled_attempt = dict(
        session.execute(
            select(SyncJob.institute_code, func.max(SyncJob.created_at))
            .where(
                SyncJob.kind == COMPONENT_SYNC_KIND,
                or_(
                    SyncJob.requested_by.startswith(SCHEDULED_REQUESTED_BY_PREFIX),
                    SyncJob.requested_by.startswith(
                        f"{AUTO_RETRY_REQUESTED_BY_PREFIX} "
                        f"({SCHEDULED_REQUESTED_BY_PREFIX}"
                    ),
                ),
            )
            .group_by(SyncJob.institute_code)
        ).all()
    )

    def waited_since(code: str) -> datetime:
        observations = [
            value
            for value in (
                _naive_utc(last_sync.get(code)),
                _naive_utc(last_scheduled_attempt.get(code)),
            )
            if value is not None
        ]
        # Never swept here: the longest wait there is.
        return max(observations) if observations else datetime.min

    return [
        InstituteSchedule(
            code=code,
            schedule=read_auto_sync_schedule(settings_by_code.get(code)),
            last_success=_naive_utc(last_sync.get(code)),
            last_scheduled_attempt=_naive_utc(last_scheduled_attempt.get(code)),
        )
        for code in sorted(codes, key=waited_since)
    ]


class AutoSyncScheduler:
    """Enqueue a component sync per institute on a fixed interval."""

    def __init__(self, session_factory, settings: Settings, manager, fetcher) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._manager = manager
        self._fetcher = fetcher
        # Deployment-level: how often the scheduler wakes up to evaluate.
        # That is a database query, not PDB traffic — the per-institute
        # schedule decides whether anything actually reaches the PDB.
        self._poll_seconds = max(60, settings.auto_sync_poll_minutes * 60)
        self._task: asyncio.Task | None = None
        # ``asyncio.to_thread`` cancellation does not stop its worker thread.
        # This lock is therefore the shutdown barrier: stop requests prevent a
        # not-yet-started tick and wait for an in-flight one before the shared
        # SyncJobManager is allowed to shut down.
        self._tick_lock = threading.Lock()
        self._stopping = threading.Event()

    def tick(self) -> None:
        """One scheduling pass. Never raises: a dead loop stops every refresh."""

        with self._tick_lock:
            if self._stopping.is_set():
                return
            try:
                self._tick()
            except Exception as exc:
                if is_sqlite_busy(exc):
                    log.info("Auto sync skipped a cycle: the database was busy.")
                    return
                # Type only. An itkdb error can carry the request, and the request
                # can carry access codes.
                log.error("Auto sync cycle failed: %s", type(exc).__name__)

    def _tick(self) -> None:
        # An offline deployment reaches no PDB at all; scheduling jobs there
        # would only manufacture failures for a person to look at.
        if self._settings.pdb_instance != "production":
            return

        with self._session_factory() as session:
            candidates = institutes_by_staleness(session)

        # Local wall clock answers "when"; UTC answers "how long since". See
        # AutoSyncSchedule.is_due for why these must not be the same value.
        local_now = datetime.now()
        utc_now = datetime.now(timezone.utc).replace(tzinfo=None)

        for candidate in candidates:
            if not candidate.schedule.is_due(
                local_now=local_now,
                utc_now=utc_now,
                last_success=candidate.last_success,
                last_scheduled_attempt=candidate.last_scheduled_attempt,
            ):
                continue
            self._refresh_institute(candidate.code)

    def _refresh_institute(self, institute_code: str) -> None:
        with self._session_factory() as session:
            owner = find_credential_owner(session, institute_code)
            if owner is None:
                return
            owner_id, owner_email = owner.id, owner.email
            try:
                lease = acquire_component_sync_lease(
                    session,
                    institute_code=institute_code,
                    requested_by=scheduled_requested_by(owner_email),
                    user_id=owner_id,
                )
            except SyncLeaseBusy:
                # Someone else holds the coordinator right now. The next tick
                # is soon enough; a scheduled refresh never needs to insist.
                return

        # A sweep already running (or queued) is exactly what we wanted; leave
        # it alone rather than stacking a second one behind it.
        if lease.created:
            try:
                self._manager.start(lease.job.id, self._fetcher)
            except Exception:
                # Lease creation committed before executor submission. A
                # rejected submit must not leave a queued row holding the
                # global active_key until stale-heartbeat takeover or restart.
                fail_sync_job(
                    self._session_factory,
                    lease.job.id,
                    "Component sync could not be scheduled.",
                )
                raise

    async def start(self) -> None:
        if self._task is None:
            self._stopping.clear()
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stopping.set()
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        # Cancelling a Task awaiting ``to_thread`` only cancels the asyncio
        # Future. The OS thread keeps running, so join the tick barrier before
        # the following shutdown handler tears down SyncJobManager.
        await asyncio.to_thread(self._wait_for_tick)

    def _wait_for_tick(self) -> None:
        with self._tick_lock:
            return

    async def _run(self) -> None:
        while True:
            # Wait first: a restart loop must not turn into a burst of sweeps,
            # and startup recovery needs the tree settled before we add work.
            await asyncio.sleep(self._poll_seconds)
            # Lease acquisition and job start both block on the database.
            await asyncio.to_thread(self.tick)
