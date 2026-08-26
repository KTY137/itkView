"""Local-only operational health aggregation for the Phase-4 Ops screen.

Opening the operations screen must be safe while the PDB is unavailable.  All
signals in this module come from itkFlow's own database: durable process
heartbeats, sync-job history, outbox state, reminder tasks, and ingest rows.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

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
    utcnow,
)

OUTBOX_WORKER = "outbox-worker"
REMINDER_SCHEDULER = "reminder-scheduler"
ACTIVE_SYNC_STATUSES = ("queued", "running")
OPEN_OUTBOX_STATUSES = ("draft", "validated", "approved", "submitted", "failed")


def _as_utc(value: datetime) -> datetime:
    """SQLite drops timezone metadata; stored application timestamps are UTC."""

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _age_seconds(now: datetime, value: datetime) -> int:
    return max(0, int((_as_utc(now) - _as_utc(value)).total_seconds()))


def record_service_heartbeat(
    session: Session,
    service: str,
    *,
    status: str = "ok",
    detail: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> ServiceHeartbeat:
    """Insert or update one service heartbeat in the caller's transaction."""

    seen_at = _as_utc(now or utcnow())
    row = session.get(ServiceHeartbeat, service)
    if row is None:
        row = ServiceHeartbeat(service=service)
        session.add(row)
    row.status = status
    row.detail = dict(detail or {})
    row.last_seen_at = seen_at
    return row


def _count(session: Session, statement) -> int:
    return int(session.scalar(statement) or 0)


def _heartbeat_projection(
    session: Session,
    service: str,
    *,
    enabled: bool,
    stale_after_seconds: int,
    now: datetime,
) -> dict[str, Any]:
    row = session.get(ServiceHeartbeat, service)
    if not enabled:
        return {
            "service": service,
            "status": "disabled",
            "last_seen_at": row.last_seen_at if row is not None else None,
            "age_seconds": (
                _age_seconds(now, row.last_seen_at) if row is not None else None
            ),
            "stale_after_seconds": stale_after_seconds,
            "detail": row.detail if row is not None else {},
        }
    if row is None:
        return {
            "service": service,
            "status": "missing",
            "last_seen_at": None,
            "age_seconds": None,
            "stale_after_seconds": stale_after_seconds,
            "detail": {},
        }
    age = _age_seconds(now, row.last_seen_at)
    heartbeat_status = "healthy" if age <= stale_after_seconds else "stale"
    if row.status != "ok" and heartbeat_status == "healthy":
        heartbeat_status = "error"
    return {
        "service": service,
        "status": heartbeat_status,
        "last_seen_at": row.last_seen_at,
        "age_seconds": age,
        "stale_after_seconds": stale_after_seconds,
        "detail": row.detail or {},
    }


def collect_ops_health(
    session: Session,
    settings: Settings,
    *,
    institute: InstituteProfile | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Aggregate one admin-visible, institute-scoped local health snapshot."""

    generated_at = _as_utc(now or utcnow())
    stale_after = max(1, settings.ops_heartbeat_stale_seconds)
    institute_id = institute.id if institute is not None else None
    institute_code = institute.code if institute is not None else None

    heartbeats = [
        _heartbeat_projection(
            session,
            OUTBOX_WORKER,
            enabled=True,
            stale_after_seconds=stale_after,
            now=generated_at,
        ),
        _heartbeat_projection(
            session,
            REMINDER_SCHEDULER,
            enabled=settings.reminder_scheduler != "off",
            stale_after_seconds=stale_after,
            now=generated_at,
        ),
    ]

    sync_scope = [] if institute_code is None else [SyncJob.institute_code == institute_code]
    active_sync = list(
        session.scalars(
            select(SyncJob)
            .where(SyncJob.status.in_(ACTIVE_SYNC_STATUSES), *sync_scope)
            .order_by(SyncJob.updated_at.desc(), SyncJob.id.desc())
        )
    )
    latest_sync: list[SyncJob] = []
    for kind in ("components", "evidence"):
        row = session.scalar(
            select(SyncJob)
            .where(SyncJob.kind == kind, *sync_scope)
            .order_by(SyncJob.id.desc())
        )
        if row is not None:
            latest_sync.append(row)
    stale_active_sync = sum(
        _age_seconds(generated_at, job.updated_at) > stale_after for job in active_sync
    )

    outbox_scope = [] if institute_id is None else [OutboxAction.institute_id == institute_id]
    backlog = _count(
        session,
        select(func.count())
        .select_from(OutboxAction)
        .where(OutboxAction.status.in_(OPEN_OUTBOX_STATUSES), *outbox_scope),
    )
    failed = _count(
        session,
        select(func.count())
        .select_from(OutboxAction)
        .where(OutboxAction.status == "failed", *outbox_scope),
    )
    at_attempt_limit = _count(
        session,
        select(func.count())
        .select_from(OutboxAction)
        .where(
            OutboxAction.status.in_(("failed", "submitted")),
            OutboxAction.attempts >= settings.worker_max_attempts,
            *outbox_scope,
        ),
    )
    oldest_open = session.scalar(
        select(func.min(OutboxAction.created_at)).where(
            OutboxAction.status.in_(OPEN_OUTBOX_STATUSES), *outbox_scope
        )
    )

    reminder_scope = (
        [] if institute_id is None else [ReminderOccurrence.institute_id == institute_id]
    )
    reminder_row_scope = [] if institute_id is None else [Reminder.institute_id == institute_id]
    open_occurrences = _count(
        session,
        select(func.count())
        .select_from(ReminderOccurrence)
        .where(ReminderOccurrence.acknowledged_at.is_(None), *reminder_scope),
    )
    failed_occurrences = _count(
        session,
        select(func.count())
        .select_from(ReminderOccurrence)
        .where(
            or_(
                ReminderOccurrence.delivery_status == "failed",
                ReminderOccurrence.escalation_error.is_not(None),
            ),
            *reminder_scope,
        ),
    )
    escalated_open = _count(
        session,
        select(func.count())
        .select_from(ReminderOccurrence)
        .where(
            ReminderOccurrence.acknowledged_at.is_(None),
            ReminderOccurrence.escalated_at.is_not(None),
            *reminder_scope,
        ),
    )
    active_reminders = _count(
        session,
        select(func.count())
        .select_from(Reminder)
        .where(Reminder.active.is_(True), *reminder_row_scope),
    )
    overdue_reminders = _count(
        session,
        select(func.count())
        .select_from(Reminder)
        .where(
            Reminder.active.is_(True),
            Reminder.next_due_at <= generated_at,
            *reminder_row_scope,
        ),
    )

    ingest_scope = []
    if institute_code is not None:
        ingest_scope = [Component.institute_code == institute_code]
    ingest_base = select(func.count()).select_from(IngestFile)
    if ingest_scope:
        ingest_base = ingest_base.join(Component, Component.sn == IngestFile.component_sn)
    total_ingest = _count(session, ingest_base.where(*ingest_scope))
    triage_ingest = _count(
        session, ingest_base.where(IngestFile.status == "triage", *ingest_scope)
    )
    failed_ingest = _count(
        session, ingest_base.where(IngestFile.status == "failed", *ingest_scope)
    )
    parser_issues = _count(
        session,
        ingest_base.where(
            or_(IngestFile.error.is_not(None), IngestFile.status.in_(("triage", "failed"))),
            *ingest_scope,
        ),
    )
    unassigned_ingest = (
        _count(
            session,
            select(func.count())
            .select_from(IngestFile)
            .where(IngestFile.component_sn.is_(None)),
        )
        if institute_code is None
        else 0
    )

    severe_heartbeat = any(
        heartbeat["status"] in {"missing", "stale", "error"} for heartbeat in heartbeats
    )
    latest_sync_failed = any(job.status in {"failed", "interrupted"} for job in latest_sync)
    if severe_heartbeat or at_attempt_limit > 0:
        overall = "critical"
    elif (
        stale_active_sync > 0
        or latest_sync_failed
        or failed > 0
        or failed_occurrences > 0
        or overdue_reminders > 0
        or parser_issues > 0
    ):
        overall = "warning"
    else:
        overall = "healthy"

    return {
        "status": overall,
        "generated_at": generated_at,
        "institute_code": institute_code,
        "heartbeats": heartbeats,
        "sync": {
            "active": active_sync,
            "latest": latest_sync,
            "stale_active": stale_active_sync,
        },
        "outbox": {
            "backlog": backlog,
            "failed": failed,
            "at_attempt_limit": at_attempt_limit,
            "oldest_open_at": oldest_open,
            "oldest_open_age_seconds": (
                _age_seconds(generated_at, oldest_open) if oldest_open is not None else None
            ),
        },
        "reminders": {
            "active": active_reminders,
            "open_occurrences": open_occurrences,
            "failed_occurrences": failed_occurrences,
            "escalated_open": escalated_open,
            "overdue": overdue_reminders,
        },
        "ingest": {
            "total": total_ingest,
            "triage": triage_ingest,
            "failed": failed_ingest,
            "parser_issues": parser_issues,
            "unassigned": unassigned_ingest,
        },
    }
