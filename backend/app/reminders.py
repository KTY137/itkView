"""Reminder scheduling and firing (Phase 4, replaces emailReminderManager).

A `Reminder` row carries its own `next_due_at`. Whichever process is configured
as the scheduler (`Settings.reminder_scheduler`, see below) polls due rows and
delivers through the notification channel named on the reminder — resolved
against the owning institute's `settings['notification_channels']` (see
`app.notifications`). A reminder without a channel, or whose channel has
disappeared from the profile, still "fires" into the audit trail so the
schedule stays visible and honest.

Two processes can run the tick, because two deployments look different:
Compose has a standalone worker, while the desktop bundle and the dev launcher
are a single API process. `ReminderScheduler` covers the second case.

Delivery is *at most once*: an occurrence is claimed — the schedule advances in
its own committed transaction — before anything is sent. A second scheduler, or
a restarted one, then finds nothing to claim instead of sending a duplicate.
Delivery failures therefore advance the schedule too, which is deliberate: a
broken webhook must not make every poll cycle hammer the endpoint, and
`last_error` plus the `reminder.failed` audit event keep the failure visible.
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import AuditEvent, InstituteProfile, Reminder, ReminderOccurrence
from app.notifications import NotificationError, Notifier, channel_configs
from app.ops_health import REMINDER_SCHEDULER, record_service_heartbeat

REMINDER_ACTOR = "reminder-worker"

SCHEDULE_KINDS = ("once", "daily", "weekly", "monthly")


@dataclass(frozen=True)
class ReminderTickStats:
    fired: int = 0
    failed: int = 0
    escalated: int = 0
    escalation_failed: int = 0

    @property
    def total(self) -> int:
        return self.fired + self.failed + self.escalated + self.escalation_failed


def _as_utc(value: datetime) -> datetime:
    """SQLite round-trips drop tzinfo; treat naive timestamps as UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _add_months(value: datetime, months: int) -> datetime:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    # Clamp the day so Jan 31 + 1 month lands on Feb 28/29 instead of raising.
    for day in (value.day, 30, 29, 28):
        try:
            return value.replace(year=year, month=month, day=day)
        except ValueError:
            continue
    raise AssertionError("unreachable: day 28 exists in every month")


def compute_next_due(schedule_kind: str, due_at: datetime, now: datetime) -> datetime | None:
    """The next occurrence strictly after `now`; None ends the schedule.

    Catch-up semantics: a reminder that was due while the worker was down fires
    once, then skips ahead past `now` instead of replaying every missed slot.
    """
    if schedule_kind == "once":
        return None
    due_at = _as_utc(due_at)
    now = _as_utc(now)
    step = 0
    while due_at <= now:
        step += 1
        if step > 10_000:  # safety valve against absurd backlogs
            return now + timedelta(days=1)
        if schedule_kind == "daily":
            due_at = due_at + timedelta(days=1)
        elif schedule_kind == "weekly":
            due_at = due_at + timedelta(weeks=1)
        elif schedule_kind == "monthly":
            due_at = _add_months(due_at, 1)
        else:  # unknown kind — treat as once rather than loop forever
            return None
    return due_at


def _resolve_channel(session: Session, reminder: Reminder) -> dict | None:
    if not reminder.channel or reminder.institute_id is None:
        return None
    institute = session.get(InstituteProfile, reminder.institute_id)
    if institute is None:
        return None
    return channel_configs(institute.settings).get(reminder.channel)


def _escalation_config(session: Session, reminder: Reminder) -> tuple[int, str] | None:
    if reminder.institute_id is None:
        return None
    institute = session.get(InstituteProfile, reminder.institute_id)
    raw = (institute.settings or {}).get("reminder_escalation") if institute else None
    if not isinstance(raw, dict):
        return None
    minutes = raw.get("after_minutes")
    channel = raw.get("channel")
    if (
        isinstance(minutes, bool)
        or not isinstance(minutes, int)
        or not 1 <= minutes <= 7 * 24 * 60
        or not isinstance(channel, str)
        or not channel
    ):
        return None
    return minutes, channel


def _claim_occurrence(session: Session, reminder: Reminder, now: datetime) -> bool:
    """Advance the schedule in its own transaction, before delivering anything.

    The guarded `WHERE` is what makes the claim exclusive: it only matches while
    the row still carries the occurrence we read. Whoever commits first wins;
    the loser sees zero affected rows and skips the send.
    """
    stored_due = reminder.next_due_at
    next_due = compute_next_due(reminder.schedule_kind, _as_utc(stored_due), now)
    values: dict[str, object] = {"last_fired_at": now, "last_error": None}
    if next_due is None:
        values["active"] = False
    else:
        values["next_due_at"] = next_due
    claimed = session.execute(
        update(Reminder)
        .where(
            Reminder.id == reminder.id,
            Reminder.next_due_at == stored_due,
            Reminder.active.is_(True),
        )
        .values(**values)
    )
    if claimed.rowcount == 1:
        escalation = _escalation_config(session, reminder)
        session.add(
            ReminderOccurrence(
                reminder_id=reminder.id,
                institute_id=reminder.institute_id,
                due_at=_as_utc(stored_due),
                fired_at=now,
                delivery_status="audit_only",
                escalation_due_at=(
                    now + timedelta(minutes=escalation[0])
                    if escalation is not None
                    else None
                ),
                escalation_channel=escalation[1] if escalation is not None else None,
            )
        )
    session.commit()
    return claimed.rowcount == 1


def _process_due_escalations(
    session: Session,
    notifier: Notifier,
    now: datetime,
) -> tuple[int, int]:
    due = list(
        session.scalars(
            select(ReminderOccurrence)
            .where(
                ReminderOccurrence.acknowledged_at.is_(None),
                ReminderOccurrence.escalated_at.is_(None),
                ReminderOccurrence.escalation_due_at.is_not(None),
                ReminderOccurrence.escalation_due_at <= now,
            )
            .order_by(ReminderOccurrence.escalation_due_at, ReminderOccurrence.id)
        )
    )
    escalated = 0
    failed = 0
    for occurrence in due:
        claimed = session.execute(
            update(ReminderOccurrence)
            .where(
                ReminderOccurrence.id == occurrence.id,
                ReminderOccurrence.acknowledged_at.is_(None),
                ReminderOccurrence.escalated_at.is_(None),
            )
            .values(escalated_at=now, escalation_error=None)
        )
        session.commit()
        if claimed.rowcount != 1:
            continue

        reminder = session.get(Reminder, occurrence.reminder_id)
        institute = (
            session.get(InstituteProfile, occurrence.institute_id)
            if occurrence.institute_id is not None
            else None
        )
        channel_name = occurrence.escalation_channel
        channel = (
            channel_configs(institute.settings).get(channel_name)
            if institute is not None and channel_name
            else None
        )
        error: str | None = None
        if reminder is None:
            error = "The reminder no longer exists."
        elif channel is None:
            error = f"Notification channel '{channel_name}' is not configured."
        else:
            try:
                notifier(
                    channel,
                    f"Escalation: {reminder.title}",
                    (
                        f"{reminder.note or ''}\n\n"
                        "This reminder occurrence has not been acknowledged."
                    ).strip(),
                )
            except NotificationError as exc:
                error = str(exc)

        if error is None:
            escalated += 1
        else:
            failed += 1
            session.execute(
                update(ReminderOccurrence)
                .where(ReminderOccurrence.id == occurrence.id)
                .values(escalation_error=error)
            )
        session.add(
            AuditEvent(
                actor=REMINDER_ACTOR,
                action=(
                    "reminder.escalated" if error is None else "reminder.escalation_failed"
                ),
                subject=f"reminder:{occurrence.reminder_id}",
                detail={
                    "occurrence_id": occurrence.id,
                    "channel": channel_name,
                    **({"error": error} if error else {}),
                },
            )
        )
        session.commit()
    return escalated, failed


def process_due_reminders(
    session: Session, notifier: Notifier, now: datetime | None = None
) -> ReminderTickStats:
    """Fire every active reminder whose `next_due_at` has passed.

    The caller owns the session lifecycle. Each reminder is claimed, delivered
    and recorded in its own transaction, so a crash mid-tick keeps the work
    already done instead of replaying it.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    due = list(
        session.scalars(
            select(Reminder)
            .where(Reminder.active.is_(True), Reminder.next_due_at <= now)
            .order_by(Reminder.next_due_at)
        )
    )
    fired = 0
    failed = 0
    for reminder in due:
        # Read everything the delivery needs before the claim expires the row.
        reminder_id = reminder.id
        title = reminder.title
        note = reminder.note or ""
        channel_name = reminder.channel
        schedule_kind = reminder.schedule_kind
        channel = _resolve_channel(session, reminder)

        if not _claim_occurrence(session, reminder, now):
            # Another scheduler already took this occurrence.
            continue

        occurrence = session.scalar(
            select(ReminderOccurrence)
            .where(ReminderOccurrence.reminder_id == reminder_id)
            .order_by(ReminderOccurrence.id.desc())
        )
        if occurrence is None:
            raise RuntimeError("Claimed reminder occurrence was not persisted.")

        error: str | None = None
        if channel is not None:
            try:
                notifier(channel, title, note)
            except NotificationError as exc:
                error = str(exc)
        elif channel_name:
            error = f"Notification channel '{channel_name}' is not configured."

        if error is None:
            fired += 1
            occurrence.delivery_status = "sent" if channel is not None else "audit_only"
            occurrence.delivery_error = None
        else:
            failed += 1
            occurrence.delivery_status = "failed"
            occurrence.delivery_error = error
            session.execute(
                update(Reminder).where(Reminder.id == reminder_id).values(last_error=error)
            )
        session.add(
            AuditEvent(
                actor=REMINDER_ACTOR,
                action="reminder.fired" if error is None else "reminder.failed",
                subject=f"reminder:{reminder_id}",
                detail={
                    "title": title,
                    "channel": channel_name,
                    "schedule_kind": schedule_kind,
                    **({"error": error} if error else {}),
                },
            )
        )
        session.commit()
    escalated, escalation_failed = _process_due_escalations(session, notifier, now)
    stats = ReminderTickStats(
        fired=fired,
        failed=failed,
        escalated=escalated,
        escalation_failed=escalation_failed,
    )
    record_service_heartbeat(
        session,
        REMINDER_SCHEDULER,
        detail={
            "fired": stats.fired,
            "failed": stats.failed,
            "escalated": stats.escalated,
            "escalation_failed": stats.escalation_failed,
        },
        now=now,
    )
    session.commit()
    return stats


class ReminderScheduler:
    """Fires due reminders from inside the API process.

    Only used when `reminder_scheduler="app"`. The desktop bundle and the dev
    launcher have no worker process, so this is the difference between a
    reminder firing and a reminder silently never happening. The tick runs in a
    worker thread because the database session and the webhook POST both block.
    """

    def __init__(self, session_factory, notifier: Notifier, poll_seconds: int) -> None:
        self._session_factory = session_factory
        self._notifier = notifier
        self._poll_seconds = max(1, poll_seconds)
        self._task: asyncio.Task | None = None

    def tick(self) -> ReminderTickStats:
        with self._session_factory() as session:
            return process_due_reminders(session, self._notifier)

    def record_failure(self, exc: Exception) -> None:
        """Keep a failed scheduler cycle visible without persisting its message."""

        with self._session_factory() as session:
            record_service_heartbeat(
                session,
                REMINDER_SCHEDULER,
                status="error",
                detail={"error_type": type(exc).__name__},
            )
            session.commit()

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self._poll_seconds)
            try:
                stats = await asyncio.to_thread(self.tick)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — a scheduler must not die
                # One bad tick (locked database, unreachable endpoint) must not
                # end the loop, or reminders stop for the rest of the session.
                print(f"[reminder-scheduler] tick failed: {type(exc).__name__}", flush=True)
                await asyncio.to_thread(self.record_failure, exc)
                continue
            if stats.total:
                print(
                    f"[reminder-scheduler] fired={stats.fired} failed={stats.failed} "
                    f"escalated={stats.escalated} "
                    f"escalation_failed={stats.escalation_failed}",
                    flush=True,
                )
