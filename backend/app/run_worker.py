"""Standalone async outbox worker process.

Runs the submission loop in its own container/process (see the `worker` service
in deploy/docker-compose.yml). Uses the same database as the API and the real
PDB submitter. Every write uses the personal PDB connection bound to the
approved action; deployment-wide access codes are never used.

    python -m app.run_worker          # loop forever, polling the outbox
    python -m app.run_worker --once   # process one batch and exit (ops/tests)
"""

import argparse
import time

from app.config import Settings, get_settings
from app.db import Base, ensure_phase0_sqlite_schema, make_engine, make_session_factory
from app.notifications import Notifier, make_notifier
from app.ops_health import OUTBOX_WORKER, record_service_heartbeat
from app.outbox_worker import Submitter, WorkerStats, process_due_actions
from app.pdb_submit import make_pdb_submitter
from app.reminders import ReminderTickStats, process_due_reminders


def run_once(
    session_factory,
    submitter: Submitter,
    *,
    max_attempts: int = 5,
    retry_backoff_seconds: int = 60,
    notifier: Notifier | None = None,
) -> WorkerStats:
    with session_factory() as session:
        stats = process_due_actions(
            session,
            submitter,
            max_attempts=max_attempts,
            retry_backoff_seconds=retry_backoff_seconds,
        )
        # Reminders ride the same poll cycle (docs/11): due rows fire through
        # the notification adapter, or into the audit trail alone when no
        # channel is configured.
        if notifier is not None:
            _log_reminders(process_due_reminders(session, notifier))
        record_service_heartbeat(
            session,
            OUTBOX_WORKER,
            detail={
                "confirmed": stats.confirmed,
                "rejected": stats.rejected,
                "unavailable": stats.unavailable,
                "revalidation_failed": stats.revalidation_failed,
                "attempt_limit_reached": stats.attempt_limit_reached,
            },
        )
        session.commit()
        return stats


def _log(stats: WorkerStats) -> None:
    if stats.total:
        print(
            f"[outbox-worker] confirmed={stats.confirmed} rejected={stats.rejected} "
            f"unavailable={stats.unavailable} revalidation_failed={stats.revalidation_failed} "
            f"attempt_limit_reached={stats.attempt_limit_reached}",
            flush=True,
        )


def _log_reminders(stats: ReminderTickStats) -> None:
    if stats.total:
        print(
            f"[reminder-worker] fired={stats.fired} failed={stats.failed} "
            f"escalated={stats.escalated} "
            f"escalation_failed={stats.escalation_failed}",
            flush=True,
        )


def main(argv: list[str] | None = None, settings: Settings | None = None) -> None:
    parser = argparse.ArgumentParser(description="itkFlow async outbox worker")
    parser.add_argument("--once", action="store_true", help="process one batch and exit")
    args = parser.parse_args(argv)

    settings = settings or get_settings()
    engine = make_engine(settings.database_url)
    # Idempotent: the worker shares the API's database, but stays self-sufficient
    # on a fresh one (same schema bootstrap as the app factory).
    Base.metadata.create_all(engine)
    ensure_phase0_sqlite_schema(engine)
    session_factory = make_session_factory(engine)
    # Deliberately no service credential: production work is always executed
    # as the PDB identity immutably bound when the action was approved.
    submitter = make_pdb_submitter(settings)
    # Only tick reminders when this process is the configured scheduler, so a
    # deployment that lets the API do it does not get two tickers (docs/11).
    notifier = make_notifier(settings) if settings.reminder_scheduler == "worker" else None

    if args.once:
        _log(
            run_once(
                session_factory,
                submitter,
                max_attempts=settings.worker_max_attempts,
                retry_backoff_seconds=settings.worker_retry_backoff_seconds,
                notifier=notifier,
            )
        )
        return

    print(
        f"[outbox-worker] polling every {settings.worker_poll_seconds}s "
        f"(pdb instance: {settings.pdb_instance})",
        flush=True,
    )
    while True:
        _log(
            run_once(
                session_factory,
                submitter,
                max_attempts=settings.worker_max_attempts,
                retry_backoff_seconds=settings.worker_retry_backoff_seconds,
                notifier=notifier,
            )
        )
        time.sleep(settings.worker_poll_seconds)


if __name__ == "__main__":
    main()
