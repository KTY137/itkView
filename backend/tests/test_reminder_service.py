"""Tests for reminder scheduling and the worker tick (app/reminders.py)."""

import asyncio
import contextlib
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from app.models import AuditEvent, InstituteProfile, Reminder, ReminderOccurrence
from app.notifications import NotificationError
from app.reminders import (
    ReminderScheduler,
    _claim_occurrence,
    compute_next_due,
    process_due_reminders,
)

NOW = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)

CHANNELS = {"lab": {"kind": "mattermost", "url": "https://mm.example.org/hooks/abc"}}


def test_compute_next_due_schedules():
    due = NOW - timedelta(hours=1)
    assert compute_next_due("once", due, NOW) is None
    assert compute_next_due("daily", due, NOW) == due + timedelta(days=1)
    assert compute_next_due("weekly", due, NOW) == due + timedelta(weeks=1)
    monthly = compute_next_due("monthly", datetime(2026, 1, 31, tzinfo=timezone.utc), NOW)
    # Month arithmetic clamps Jan 31 → Feb 28 and the clamp sticks (the usual
    # scheduling trade-off); catch-up lands strictly past `now`.
    assert monthly == datetime(2026, 8, 28, tzinfo=timezone.utc)


def test_compute_next_due_catches_up_past_now():
    stale = NOW - timedelta(days=30)
    result = compute_next_due("daily", stale, NOW)
    assert result == stale + timedelta(days=31)
    assert result > NOW


def _add_reminder(session, institute_id: int | None, **overrides) -> Reminder:
    reminder = Reminder(
        title=overrides.pop("title", "Clean bench"),
        channel=overrides.pop("channel", "lab"),
        schedule_kind=overrides.pop("schedule_kind", "weekly"),
        next_due_at=overrides.pop("next_due_at", NOW - timedelta(minutes=5)),
        created_by="op@example.org",
        institute_id=institute_id,
        **overrides,
    )
    session.add(reminder)
    session.commit()
    session.refresh(reminder)
    return reminder


def test_process_due_reminders_fires_and_reschedules(
    client: TestClient, session_factory, tudo: dict
):
    with session_factory() as session:
        institute = session.get(InstituteProfile, tudo["id"])
        institute.settings = {"notification_channels": CHANNELS}
        session.commit()
        reminder = _add_reminder(session, tudo["id"])
        future = _add_reminder(
            session, tudo["id"], title="Later", next_due_at=NOW + timedelta(days=1)
        )

        sent: list[tuple[str, str]] = []
        stats = process_due_reminders(
            session, lambda channel, title, text: sent.append((title, text)), now=NOW
        )
        assert stats.fired == 1 and stats.failed == 0
        assert sent == [("Clean bench", "")]

        session.refresh(reminder)
        assert reminder.last_fired_at is not None
        assert reminder.last_error is None
        assert reminder.next_due_at.replace(tzinfo=timezone.utc) > NOW
        assert reminder.active is True

        session.refresh(future)
        assert future.last_fired_at is None  # not due yet

        audit = set(session.scalars(select(AuditEvent.action)))
        assert "reminder.fired" in audit


def test_once_reminder_deactivates_after_firing(client: TestClient, session_factory, tudo):
    with session_factory() as session:
        institute = session.get(InstituteProfile, tudo["id"])
        institute.settings = {"notification_channels": CHANNELS}
        session.commit()
        reminder = _add_reminder(session, tudo["id"], schedule_kind="once")
        process_due_reminders(session, lambda *args: None, now=NOW)
        session.refresh(reminder)
        assert reminder.active is False


def test_delivery_failure_records_error_but_advances(
    client: TestClient, session_factory, tudo: dict
):
    def broken(channel: dict, title: str, text: str) -> None:
        raise NotificationError("The notification endpoint answered HTTP 500.")

    with session_factory() as session:
        institute = session.get(InstituteProfile, tudo["id"])
        institute.settings = {"notification_channels": CHANNELS}
        session.commit()
        reminder = _add_reminder(session, tudo["id"])
        stats = process_due_reminders(session, broken, now=NOW)
        assert stats.failed == 1
        session.refresh(reminder)
        # The schedule advances anyway: a broken webhook must not be hammered
        # on every poll cycle, and the error stays visible.
        assert reminder.next_due_at.replace(tzinfo=timezone.utc) > NOW
        assert "HTTP 500" in reminder.last_error
        audit = set(session.scalars(select(AuditEvent.action)))
        assert "reminder.failed" in audit


def test_missing_channel_config_fails_visibly(client: TestClient, session_factory, tudo):
    with session_factory() as session:
        # No notification_channels configured on the profile at all.
        reminder = _add_reminder(session, tudo["id"], channel="lab")
        stats = process_due_reminders(session, lambda *args: None, now=NOW)
        assert stats.failed == 1
        session.refresh(reminder)
        assert "not configured" in reminder.last_error


def test_channelless_reminder_fires_into_audit_only(client: TestClient, session_factory, tudo):
    with session_factory() as session:
        reminder = _add_reminder(session, tudo["id"], channel=None)

        def never(*args) -> None:
            raise AssertionError("no channel — notifier must not be called")

        stats = process_due_reminders(session, never, now=NOW)
        assert stats.fired == 1
        session.refresh(reminder)
        assert reminder.last_error is None


def test_claim_makes_delivery_at_most_once(client: TestClient, session_factory, tudo: dict):
    """A second tick for the same instant must not re-send an occurrence.

    This is what protects a deployment that accidentally runs two schedulers
    (worker plus in-app) from double-pinging a channel.
    """
    with session_factory() as session:
        institute = session.get(InstituteProfile, tudo["id"])
        institute.settings = {"notification_channels": CHANNELS}
        session.commit()
        reminder = _add_reminder(session, tudo["id"])

        sent: list[str] = []
        notifier = lambda channel, title, text: sent.append(title)  # noqa: E731

        first = process_due_reminders(session, notifier, now=NOW)
        second = process_due_reminders(session, notifier, now=NOW)
        assert (first.fired, second.fired) == (1, 0)
        assert sent == ["Clean bench"]

        session.refresh(reminder)
        assert reminder.next_due_at.replace(tzinfo=timezone.utc) > NOW


def test_claim_happens_before_delivery(client: TestClient, session_factory, tudo: dict):
    """The schedule must already be advanced while the webhook POST runs.

    A slow endpoint plus a second scheduler is exactly when a duplicate would
    otherwise slip out, so assert the ordering rather than trusting it.
    """
    with session_factory() as session:
        institute = session.get(InstituteProfile, tudo["id"])
        institute.settings = {"notification_channels": CHANNELS}
        session.commit()
        reminder = _add_reminder(session, tudo["id"])
        reminder_id = reminder.id
        seen: list[datetime] = []

        def notifier(channel: dict, title: str, text: str) -> None:
            with session_factory() as probe:
                seen.append(probe.get(Reminder, reminder_id).next_due_at)

        process_due_reminders(session, notifier, now=NOW)
        assert len(seen) == 1
        assert seen[0].replace(tzinfo=timezone.utc) > NOW


def test_scheduler_tick_fires_through_its_own_session(
    client: TestClient, session_factory, tudo: dict
):
    with session_factory() as session:
        institute = session.get(InstituteProfile, tudo["id"])
        institute.settings = {"notification_channels": CHANNELS}
        session.commit()
        _add_reminder(session, tudo["id"])

    sent: list[str] = []
    scheduler = ReminderScheduler(
        session_factory, lambda channel, title, text: sent.append(title), poll_seconds=60
    )
    stats = scheduler.tick()
    assert stats.fired == 1
    assert sent == ["Clean bench"]
    # Nothing is due any more, so a second tick stays quiet.
    assert scheduler.tick().total == 0


def test_scheduler_treats_a_busy_database_as_a_quiet_skip(
    client: TestClient, session_factory, capsys
):
    """A SQLite `database is locked` under concurrent load is expected, not a
    real failure — it must neither log "tick failed" nor flip the ops health
    heartbeat to "error" for one transient blip (docs/09)."""
    scheduler = ReminderScheduler(session_factory, lambda *a: None, poll_seconds=60)
    busy = OperationalError("SELECT 1", {}, Exception("database is locked"))

    recorded: list[Exception] = []
    scheduler.record_failure = recorded.append

    scheduler._handle_tick_failure(busy)  # noqa: SLF001 — exercising the classifier directly

    out = capsys.readouterr().out
    assert "database busy" in out
    assert "tick failed" not in out
    assert recorded == []  # no failure heartbeat for an expected, transient skip


def test_scheduler_still_reports_a_real_failure(client: TestClient, session_factory, capsys):
    """Only the SQLite-busy message is downgraded; any other exception (a
    broken webhook endpoint, a real bug) stays a visible, heartbeat-recorded
    failure exactly like before."""
    scheduler = ReminderScheduler(session_factory, lambda *a: None, poll_seconds=60)
    boom = RuntimeError("webhook endpoint unreachable")

    recorded: list[Exception] = []
    scheduler.record_failure = recorded.append

    scheduler._handle_tick_failure(boom)  # noqa: SLF001 — exercising the classifier directly

    out = capsys.readouterr().out
    assert "tick failed: RuntimeError" in out
    assert "database busy" not in out
    assert recorded == [boom]


def test_run_loop_routes_a_failed_tick_through_the_quiet_skip_classifier(session_factory):
    """Wiring check for `_run`: a tick exception must reach
    `_handle_tick_failure` with the original exception, not just get swallowed
    somewhere else in the loop."""

    async def scenario() -> list[Exception]:
        scheduler = ReminderScheduler(session_factory, lambda *a: None, poll_seconds=60)
        scheduler._poll_seconds = 0  # skip the real sleep between polls
        handled = asyncio.Event()
        received: list[Exception] = []

        def failing_tick() -> None:
            raise OperationalError("SELECT 1", {}, Exception("database is locked"))

        def fake_handle(exc: Exception) -> None:
            received.append(exc)
            handled.set()

        scheduler.tick = failing_tick
        scheduler._handle_tick_failure = fake_handle  # noqa: SLF001

        task = asyncio.create_task(scheduler._run())  # noqa: SLF001
        try:
            await asyncio.wait_for(handled.wait(), timeout=5)
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        return received

    received = asyncio.run(scenario())
    assert len(received) == 1
    assert isinstance(received[0], OperationalError)


def test_app_starts_a_scheduler_only_when_it_is_the_configured_one():
    """The API process must tick exactly when it is configured to.

    Compose has a worker doing it; the desktop bundle and the dev launcher do
    not, and that difference is the whole point of the setting.
    """
    from app.config import Settings
    from app.main import create_app
    from app.pdb_credentials import generate_pdb_credential_encryption_key

    def build(scheduler: str):
        return create_app(
            Settings(
                database_url="sqlite:///:memory:",
                pdb_credential_encryption_key=generate_pdb_credential_encryption_key(),
                reminder_scheduler=scheduler,
                _env_file=None,
            )
        )

    assert build("worker").state.reminder_scheduler is None
    assert build("off").state.reminder_scheduler is None
    in_app = build("app")
    assert isinstance(in_app.state.reminder_scheduler, ReminderScheduler)

    # Wired to the lifecycle, so it actually runs and stops with the server.
    with TestClient(in_app):
        assert in_app.state.reminder_scheduler._task is not None
    assert in_app.state.reminder_scheduler._task is None


def test_a_stale_claim_loses_the_race(client: TestClient, session_factory, tudo: dict):
    """Two schedulers that both read the same occurrence: only one may claim it.

    Sequential ticks never reach this state because the second re-reads an
    already advanced row, so the guard has to be exercised directly.
    """
    with session_factory() as setup:
        reminder = _add_reminder(setup, tudo["id"])
        reminder_id = reminder.id

    with session_factory() as first, session_factory() as second:
        # Both sessions hold the pre-claim view of the same occurrence.
        seen_by_first = first.get(Reminder, reminder_id)
        seen_by_second = second.get(Reminder, reminder_id)
        assert seen_by_first.next_due_at == seen_by_second.next_due_at

        assert _claim_occurrence(first, seen_by_first, NOW) is True
        assert _claim_occurrence(second, seen_by_second, NOW) is False


def test_unacknowledged_occurrence_escalates_once_on_the_configured_channel(
    client: TestClient, session_factory, tudo: dict
):
    channels = {
        **CHANNELS,
        "ops": {"kind": "webhook", "url": "https://hooks.example.org/ops"},
    }
    sent: list[tuple[str, str]] = []
    with session_factory() as session:
        institute = session.get(InstituteProfile, tudo["id"])
        institute.settings = {
            "notification_channels": channels,
            "reminder_escalation": {"after_minutes": 5, "channel": "ops"},
        }
        session.commit()
        _add_reminder(session, tudo["id"])

        initial = process_due_reminders(
            session,
            lambda channel, title, text: sent.append((channel["url"], title)),
            now=NOW,
        )
        occurrence = session.scalar(select(ReminderOccurrence))
        assert initial.fired == 1
        assert occurrence is not None
        assert occurrence.acknowledged_at is None
        assert occurrence.escalation_channel == "ops"
        assert occurrence.escalation_due_at.replace(tzinfo=timezone.utc) == NOW + timedelta(
            minutes=5
        )

        escalated = process_due_reminders(
            session,
            lambda channel, title, text: sent.append((channel["url"], title)),
            now=NOW + timedelta(minutes=6),
        )
        repeated = process_due_reminders(
            session,
            lambda channel, title, text: sent.append((channel["url"], title)),
            now=NOW + timedelta(minutes=7),
        )
        session.refresh(occurrence)

        assert escalated.escalated == 1
        assert repeated.escalated == 0
        assert occurrence.escalated_at is not None
        assert occurrence.escalation_error is None
        assert sent == [
            ("https://mm.example.org/hooks/abc", "Clean bench"),
            ("https://hooks.example.org/ops", "Escalation: Clean bench"),
        ]
        actions = set(session.scalars(select(AuditEvent.action)))
        assert "reminder.escalated" in actions


def test_acknowledged_occurrence_does_not_escalate(
    client: TestClient, session_factory, tudo: dict
):
    with session_factory() as session:
        institute = session.get(InstituteProfile, tudo["id"])
        institute.settings = {
            "notification_channels": {
                **CHANNELS,
                "ops": {"kind": "webhook", "url": "https://hooks.example.org/ops"},
            },
            "reminder_escalation": {"after_minutes": 5, "channel": "ops"},
        }
        session.commit()
        _add_reminder(session, tudo["id"])
        process_due_reminders(session, lambda *args: None, now=NOW)
        occurrence = session.scalar(select(ReminderOccurrence))
        occurrence.acknowledged_at = NOW + timedelta(minutes=1)
        occurrence.acknowledged_by = "operator@example.org"
        session.commit()

        sent: list[str] = []
        stats = process_due_reminders(
            session,
            lambda channel, title, text: sent.append(title),
            now=NOW + timedelta(minutes=10),
        )
        assert stats.escalated == 0
        assert sent == []
