# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-FileComment: itkflow-29c50d0f5385
"""Drain the outbox from inside the API process.

Compose runs `app.run_worker` as its own service. The desktop bundle is a
single process, so without this an action reviewed in the UI advances to
`submitted` and then stops: the PDB write silently never happens, and the
staged change looks pushed while nothing reached the collaboration. (The dev
launcher deliberately keeps the drain off — development sessions should not
submit; `python -m app.run_worker --once` exists for a deliberate manual pass.)
This is the same split the reminder scheduler already makes (docs/11), and
`Settings.outbox_processor` decides which process owns the work.

Safety is unchanged. No deployment-wide service credentials are ever passed to
the submitter: every write runs as the PDB identity immutably bound when the
action was approved (ADR 004), and `pdb_write_scope="dummy_only"` still confines
writes to itkFlow-registered DUMMY components (ADR 003).
"""

import asyncio

from app.config import Settings
from app.db import is_sqlite_busy
from app.pdb_submit import make_pdb_submitter
from app.run_worker import run_once


class OutboxProcessor:
    """Polls the local outbox and submits approved actions to the PDB."""

    def __init__(self, session_factory, settings: Settings) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._poll_seconds = max(1, settings.worker_poll_seconds)
        self._task: asyncio.Task | None = None

    def _run_once(self):
        # Built per tick so a submitter that could not be constructed (missing
        # itkdb, disabled scope) fails this cycle instead of the whole process.
        # No `service_access_codes`: writes run as the approval-time identity.
        submitter = make_pdb_submitter(self._settings)
        return run_once(
            self._session_factory,
            submitter,
            max_attempts=self._settings.worker_max_attempts,
            retry_backoff_seconds=self._settings.worker_retry_backoff_seconds,
            # Reminders are owned by ReminderScheduler in this deployment
            # shape; ticking them here too would double-fire them.
            notifier=None,
        )

    def tick(self) -> None:
        """One drain cycle. Never raises: a drain that dies stops every push."""
        try:
            stats = self._run_once()
        except Exception as exc:  # noqa: BLE001 — a background drain must not die
            if is_sqlite_busy(exc):
                # Expected under concurrent load (the worker/API/reminder
                # scheduler share one SQLite file outside Compose) rather than
                # a real failure — stay quiet and let the next poll pick the
                # cycle back up instead of logging it as broken.
                print("[outbox-processor] database busy — skipped this cycle", flush=True)
                return
            # Print the type only: an itkdb error can carry the request, and the
            # request can carry access codes.
            print(f"[outbox-processor] cycle failed: {type(exc).__name__}", flush=True)
            return
        if getattr(stats, "total", 0):
            print(
                f"[outbox-processor] confirmed={stats.confirmed} "
                f"rejected={stats.rejected} unavailable={stats.unavailable}",
                flush=True,
            )

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
            # The database session and the PDB call both block, so the cycle
            # runs off the event loop.
            await asyncio.to_thread(self.tick)
