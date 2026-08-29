# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-FileComment: itkflow-d52cb63276cc
"""Application factory.

Run locally with:
    uvicorn app.main:create_app --factory --reload
"""

from pathlib import Path

from fastapi import FastAPI

from app import __version__
from app.api import router
from app.auto_sync import AutoSyncScheduler
from app.complete_component_sync import fetch_complete_for_institute
from app.complete_evidence_sync import CompleteEvidenceSyncJobManager
from app.config import Settings, get_settings
from app.db import Base, ensure_phase0_sqlite_schema, make_engine, make_session_factory
from app.notifications import make_notifier
from app.outbox_processor import OutboxProcessor
from app.product_policy import ProductVariantPolicyMiddleware
from app.reminders import ReminderScheduler
from app.static_spa import mount_spa
from app.sync_jobs import recover_interrupted_sync_jobs


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    engine = make_engine(settings.database_url)
    # Phase 0: create the schema directly. Alembic migrations arrive with the
    # first real schema change in phase 1.
    Base.metadata.create_all(engine)
    ensure_phase0_sqlite_schema(engine)

    app = FastAPI(title=settings.app_name, version=__version__)
    app.add_middleware(
        ProductVariantPolicyMiddleware,
        product_variant=settings.product_variant,
    )
    app.state.settings = settings
    app.state.session_factory = make_session_factory(engine)
    # A process restart cannot resume the exact authoritative PDB snapshot. Any
    # durable live row is therefore closed as interrupted before accepting a
    # new job, which also releases the global single-flight lease.
    recover_interrupted_sync_jobs(app.state.session_factory)
    app.state.component_fetcher = fetch_complete_for_institute
    # Outbound notification seam (docs/11): the test-notification endpoint uses
    # this; tests inject a fake the same way they fake the component fetcher.
    app.state.notifier = make_notifier(settings)
    # Who fires scheduled reminders depends on the deployment shape: Compose has
    # a worker process, the desktop bundle and the dev launcher do not (docs/11).
    if settings.reminder_scheduler == "app":
        app.state.reminder_scheduler = ReminderScheduler(
            app.state.session_factory, app.state.notifier, settings.reminder_poll_seconds
        )
        app.router.add_event_handler("startup", app.state.reminder_scheduler.start)
        app.router.add_event_handler("shutdown", app.state.reminder_scheduler.stop)
    else:
        app.state.reminder_scheduler = None
    # Same split for PDB submission: Compose has `app.run_worker`; the desktop
    # bundle drains the outbox itself or a reviewed action never reaches the
    # PDB. The dev launcher deliberately keeps this off (docs/11).
    if settings.outbox_processor == "app":
        app.state.outbox_processor = OutboxProcessor(app.state.session_factory, settings)
        app.router.add_event_handler("startup", app.state.outbox_processor.start)
        app.router.add_event_handler("shutdown", app.state.outbox_processor.stop)
    else:
        app.state.outbox_processor = None
    app.state.sync_job_manager = CompleteEvidenceSyncJobManager(
        app.state.session_factory, settings
    )
    # Unattended mirror refresh, off unless a deployment asks for it. Built
    # after the manager because it hands jobs to it (docs/09, app/auto_sync.py).
    if settings.auto_sync_poll_minutes > 0:
        app.state.auto_sync_scheduler = AutoSyncScheduler(
            app.state.session_factory,
            settings,
            app.state.sync_job_manager,
            app.state.component_fetcher,
        )
        app.router.add_event_handler("startup", app.state.auto_sync_scheduler.start)
        app.router.add_event_handler("shutdown", app.state.auto_sync_scheduler.stop)
    else:
        app.state.auto_sync_scheduler = None
    # Shutdown is registration-ordered. The scheduler must first stop and join
    # any ``asyncio.to_thread`` tick; only then may its shared manager reject
    # new executor submissions and cancel queued work.
    app.router.add_event_handler("shutdown", app.state.sync_job_manager.shutdown)
    # FastAPI/Starlette in this environment stores included routers lazily as
    # `_IncludedRouter`, which TestClient resolves but the live Uvicorn server
    # did not expose reliably. Append concrete routes for a predictable dev app.
    for route in router.routes:
        app.router.routes.append(route)
    # Strictly after the API routes: the SPA fallback is a catch-all and
    # Starlette matches routes in registration order.
    if settings.static_dir:
        app.state.spa_mounted = mount_spa(app, Path(settings.static_dir))
    else:
        app.state.spa_mounted = False
    return app
