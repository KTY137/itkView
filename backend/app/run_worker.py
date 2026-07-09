"""Standalone async outbox worker process.

Runs the submission loop in its own container/process (see the `worker` service
in deploy/docker-compose.yml). Uses the same database as the API and the real
PDB submitter — but performs no write unless ITKDB access codes are configured.

    python -m app.run_worker          # loop forever, polling the outbox
    python -m app.run_worker --once   # process one batch and exit (ops/tests)
"""

import argparse
import time

from app.config import Settings, get_settings
from app.db import Base, ensure_phase0_sqlite_schema, make_engine, make_session_factory
from app.outbox_worker import Submitter, WorkerStats, process_due_actions
from app.pdb_submit import make_pdb_submitter


def run_once(
    session_factory,
    submitter: Submitter,
    *,
    max_attempts: int = 5,
    retry_backoff_seconds: int = 60,
) -> WorkerStats:
    with session_factory() as session:
        return process_due_actions(
            session,
            submitter,
            max_attempts=max_attempts,
            retry_backoff_seconds=retry_backoff_seconds,
        )


def _log(stats: WorkerStats) -> None:
    if stats.total:
        print(
            f"[outbox-worker] confirmed={stats.confirmed} rejected={stats.rejected} "
            f"unavailable={stats.unavailable} revalidation_failed={stats.revalidation_failed} "
            f"attempt_limit_reached={stats.attempt_limit_reached}",
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
    submitter = make_pdb_submitter(settings)

    if args.once:
        _log(
            run_once(
                session_factory,
                submitter,
                max_attempts=settings.worker_max_attempts,
                retry_backoff_seconds=settings.worker_retry_backoff_seconds,
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
            )
        )
        time.sleep(settings.worker_poll_seconds)


if __name__ == "__main__":
    main()
