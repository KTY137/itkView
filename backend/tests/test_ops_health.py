# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-FileComment: itkflow-6e9234f2eaf8
"""Offline tests for the admin-only Phase-4 operations health slice."""

from datetime import datetime, timedelta, timezone

from authutil import authenticate, create_institute_profile
from sqlalchemy import select

from app.config import Settings
from app.models import (
    Component,
    IngestFile,
    InstituteProfile,
    OutboxAction,
    Reminder,
    ReminderOccurrence,
    ServiceHeartbeat,
    SyncJob,
)
from app.ops_health import (
    OUTBOX_WORKER,
    REMINDER_SCHEDULER,
    collect_ops_health,
    record_service_heartbeat,
)
from app.outbox_worker import SubmitOutcome
from app.reminders import ReminderScheduler, ReminderTickStats, process_due_reminders
from app.run_worker import _log_reminders, run_once

NOW = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)


def test_ops_health_is_admin_only(client, session_factory):
    assert client.get("/api/ops/health").status_code == 401

    authenticate(client, session_factory, role="viewer", email="viewer.ops@example.org")
    assert client.get("/api/ops/health").status_code == 403

    authenticate(client, session_factory, role="operator", email="operator.ops@example.org")
    assert client.get("/api/ops/health").status_code == 403

    authenticate(client, session_factory, role="admin", email="admin.ops@example.org")
    response = client.get("/api/ops/health")
    assert response.status_code == 200
    assert response.json()["status"] == "critical"  # no worker heartbeat yet


def test_heartbeat_freshness_includes_the_boundary(client, session_factory):
    settings = Settings(
        database_url="sqlite:///:memory:",
        ops_heartbeat_stale_seconds=60,
        reminder_scheduler="off",
        _env_file=None,
    )
    with session_factory() as session:
        record_service_heartbeat(
            session,
            OUTBOX_WORKER,
            now=NOW - timedelta(seconds=60),
        )
        job = SyncJob(
            kind="components",
            institute_code="TUDO",
            status="running",
            phase="fetching",
            message="fetching",
            requested_by="operator@example.org",
            updated_at=NOW - timedelta(seconds=60),
        )
        session.add(job)
        session.commit()
        snapshot = collect_ops_health(session, settings, institute=None, now=NOW)
        worker = next(row for row in snapshot["heartbeats"] if row["service"] == OUTBOX_WORKER)
        scheduler = next(
            row for row in snapshot["heartbeats"] if row["service"] == REMINDER_SCHEDULER
        )
        assert worker["status"] == "healthy"
        assert worker["age_seconds"] == 60
        assert scheduler["status"] == "disabled"
        assert snapshot["sync"]["stale_active"] == 0

        row = session.get(ServiceHeartbeat, OUTBOX_WORKER)
        assert row is not None
        row.last_seen_at = NOW - timedelta(seconds=61)
        job.updated_at = NOW - timedelta(seconds=61)
        session.commit()
        snapshot = collect_ops_health(session, settings, institute=None, now=NOW)
        worker = next(row for row in snapshot["heartbeats"] if row["service"] == OUTBOX_WORKER)
        assert worker["status"] == "stale"
        assert snapshot["sync"]["stale_active"] == 1
        assert snapshot["status"] == "critical"


def test_worker_and_reminder_ticks_persist_heartbeats(client, session_factory):
    run_once(
        session_factory,
        lambda _session, _action: SubmitOutcome.confirmed("unused"),
        notifier=None,
    )
    with session_factory() as session:
        worker = session.get(ServiceHeartbeat, OUTBOX_WORKER)
        assert worker is not None
        assert worker.status == "ok"
        assert worker.detail["confirmed"] == 0

        stats = process_due_reminders(session, lambda *_args: None, now=NOW)
        assert stats.total == 0
        scheduler = session.get(ServiceHeartbeat, REMINDER_SCHEDULER)
        assert scheduler is not None
        assert scheduler.last_seen_at.replace(tzinfo=timezone.utc) == NOW
        assert scheduler.detail == {
            "fired": 0,
            "failed": 0,
            "escalated": 0,
            "escalation_failed": 0,
        }


def test_scheduler_failure_heartbeat_and_worker_log_are_sanitized(session_factory, capsys):
    scheduler = ReminderScheduler(session_factory, lambda *_args: None, poll_seconds=60)
    scheduler.record_failure(RuntimeError("https://secret.example.invalid/hook"))
    with session_factory() as session:
        row = session.get(ServiceHeartbeat, REMINDER_SCHEDULER)
        assert row is not None
        assert row.status == "error"
        assert row.detail == {"error_type": "RuntimeError"}
        assert "secret" not in str(row.detail)

    _log_reminders(
        ReminderTickStats(fired=1, failed=2, escalated=3, escalation_failed=4)
    )
    output = capsys.readouterr().out
    assert "fired=1 failed=2 escalated=3 escalation_failed=4" in output


def _seed_tenant_ops(session, institute: InstituteProfile, *, suffix: str, issues: bool) -> None:
    component = Component(
        sn=f"20USEM00000{suffix}",
        component_type="MODULE",
        type_code="R5M0",
        stage="GLUED",
        location=institute.code,
        institute_code=institute.code,
    )
    session.add(component)
    session.add(
        OutboxAction(
            institute_id=institute.id,
            kind="stage_move",
            payload={"component_sn": component.sn},
            status="failed" if issues else "draft",
            attempts=5 if issues else 0,
            created_by="operator@example.org",
        )
    )
    reminder = Reminder(
        title=f"Task {suffix}",
        schedule_kind="daily",
        next_due_at=NOW - timedelta(minutes=1) if issues else NOW + timedelta(days=1),
        active=True,
        created_by="operator@example.org",
        institute_id=institute.id,
    )
    session.add(reminder)
    session.flush()
    session.add(
        ReminderOccurrence(
            reminder_id=reminder.id,
            institute_id=institute.id,
            due_at=NOW - timedelta(hours=1),
            fired_at=NOW - timedelta(hours=1),
            delivery_status="failed" if issues else "sent",
            delivery_error="Delivery unavailable." if issues else None,
        )
    )
    session.add(
        IngestFile(
            filename=f"result-{suffix}.json",
            sha256=suffix[-1] * 64,
            size_bytes=2,
            status="triage" if issues else "received",
            component_sn=component.sn,
            parser="generic-v1",
            error="Component is missing." if issues else None,
            payload={},
            uploaded_by="operator@example.org",
        )
    )
    session.add(
        SyncJob(
            kind="components",
            institute_code=institute.code,
            status="failed" if issues else "succeeded",
            phase="complete",
            message="done",
            requested_by="operator@example.org",
            updated_at=NOW,
            finished_at=NOW,
        )
    )


def test_ops_health_scopes_every_tenant_metric(client, session_factory):
    tudo = create_institute_profile(session_factory, code="TUDO", name="TU Dortmund")
    other = create_institute_profile(session_factory, code="OTHER", name="Other Institute")
    with session_factory() as session:
        tudo_row = session.get(InstituteProfile, tudo["id"])
        other_row = session.get(InstituteProfile, other["id"])
        assert tudo_row is not None and other_row is not None
        _seed_tenant_ops(session, tudo_row, suffix="01", issues=False)
        _seed_tenant_ops(session, other_row, suffix="02", issues=True)
        session.add(
            IngestFile(
                filename="unassigned.json",
                sha256="f" * 64,
                size_bytes=2,
                status="triage",
                parser="generic-v1",
                error="No component.",
                payload={},
                uploaded_by="operator@example.org",
            )
        )
        record_service_heartbeat(session, OUTBOX_WORKER)
        record_service_heartbeat(session, REMINDER_SCHEDULER)
        session.commit()

    authenticate(
        client,
        session_factory,
        role="admin",
        institute_id=tudo["id"],
        email="tudo-admin.ops@example.org",
    )
    own = client.get("/api/ops/health")
    assert own.status_code == 200
    body = own.json()
    assert body["institute_code"] == "TUDO"
    assert body["outbox"] == {
        "backlog": 1,
        "failed": 0,
        "at_attempt_limit": 0,
        "oldest_open_at": body["outbox"]["oldest_open_at"],
        "oldest_open_age_seconds": body["outbox"]["oldest_open_age_seconds"],
    }
    assert body["reminders"]["open_occurrences"] == 1
    assert body["reminders"]["failed_occurrences"] == 0
    assert body["ingest"]["total"] == 1
    assert body["ingest"]["parser_issues"] == 0
    assert body["ingest"]["unassigned"] == 0
    assert [job["institute_code"] for job in body["sync"]["latest"]] == ["TUDO"]
    assert client.get("/api/ops/health?institute_code=OTHER").status_code == 403

    authenticate(
        client,
        session_factory,
        role="admin",
        email="global-admin.ops@example.org",
    )
    scoped = client.get("/api/ops/health?institute_code=OTHER")
    assert scoped.status_code == 200
    body = scoped.json()
    assert body["outbox"]["failed"] == 1
    assert body["outbox"]["at_attempt_limit"] == 1
    assert body["reminders"]["failed_occurrences"] == 1
    assert body["ingest"]["parser_issues"] == 1
    assert body["ingest"]["unassigned"] == 0

    global_view = client.get("/api/ops/health").json()
    assert global_view["institute_code"] is None
    assert global_view["outbox"]["backlog"] == 2
    assert global_view["ingest"]["total"] == 3
    assert global_view["ingest"]["unassigned"] == 1


def test_ops_health_does_not_call_pdb(client, session_factory):
    authenticate(client, session_factory, role="admin", email="offline.ops@example.org")

    def forbidden_remote_call(*_args, **_kwargs):
        raise AssertionError("Ops health must not contact the PDB")

    client.app.state.component_fetcher = forbidden_remote_call
    client.app.state.pdb_gateway = forbidden_remote_call
    response = client.get("/api/ops/health")
    assert response.status_code == 200
    with session_factory() as session:
        assert list(session.scalars(select(ServiceHeartbeat))) == []
