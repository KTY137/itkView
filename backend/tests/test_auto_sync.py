"""Unattended mirror refresh (`app.auto_sync`).

This is the only place in itkFlow where PDB traffic can happen with nobody
watching, so these tests pin the limits rather than the happy path: it stays
off unless configured, it only ever runs as someone who already synced this
institute by hand, it stops on its own when that permission goes away, and it
cannot stack sweeps.
"""

import asyncio
from datetime import timedelta
from threading import Event

from authutil import create_account, create_institute_profile

from app.auto_sync import (
    SCHEDULED_REQUESTED_BY_PREFIX,
    AutoSyncScheduler,
    find_credential_owner,
    institutes_by_staleness,
    is_scheduled_job,
    scheduled_requested_by,
)
from app.config import Settings
from app.db import Base, make_engine, make_session_factory
from app.main import create_app
from app.models import PdbCredential, SyncJob, User, utcnow
from app.pdb_credentials import (
    PdbAccessCodes,
    generate_pdb_credential_encryption_key,
    save_pdb_credentials,
)
from app.sync_jobs import auto_retry_requested_by

ENCRYPTION_KEY = generate_pdb_credential_encryption_key()

# The schedule now lives in the institute profile (Admin Settings). Every
# fixture that expects an unattended sweep has to opt in the same way a
# real site would; a profile without this block never syncs on a timer.
ENABLED_SCHEDULE = {"auto_sync": {"enabled": True, "interval_minutes": 15}}


def _settings(**overrides) -> Settings:
    base = {
        "_env_file": None,
        "pdb_instance": "production",
        "allow_production": True,
        "pdb_credential_encryption_key": ENCRYPTION_KEY,
        "auto_sync_poll_minutes": 5,
    }
    base.update(overrides)
    return Settings(**base)


class RecordingManager:
    """Stands in for SyncJobManager: records what would have been started."""

    def __init__(self) -> None:
        self.started: list[int] = []

    def start(self, job_id: int, fetcher) -> None:
        self.started.append(job_id)


def _factory(tmp_path, name="auto-sync.db"):
    engine = make_engine(f"sqlite:///{tmp_path / name}")
    Base.metadata.create_all(engine)
    return make_session_factory(engine)


def _account_with_codes(factory, email="operator@example.org", institute_id=None) -> int:
    user_id = create_account(
        factory,
        email=email,
        password="correct horse battery staple",
        role="admin",
        institute_id=institute_id,
    )
    with factory() as session:
        save_pdb_credentials(
            session,
            user_id=user_id,
            access_codes=PdbAccessCodes(access_code1="code-one", access_code2="code-two"),
            # Unique per account: the column is unique, so a shared literal
            # would make the second fixture account collide rather than fail
            # the assertion under test.
            pdb_identity=f"pdb-{email}",
            encryption_key=ENCRYPTION_KEY,
        )
        session.commit()
    return user_id


def _succeeded_component_sync(factory, *, institute_code: str, user_id: int, minutes_ago=5):
    finished = utcnow() - timedelta(minutes=minutes_ago)
    with factory() as session:
        session.add(
            SyncJob(
                kind="components",
                institute_code=institute_code,
                status="succeeded",
                phase="complete",
                current=1,
                total=1,
                percent=100.0,
                message="Component sync completed.",
                requested_by="operator@example.org",
                user_id=user_id,
                active_key=None,
                created_at=finished,
                started_at=finished,
                updated_at=finished,
                finished_at=finished,
            )
        )
        session.commit()


def _failed_component_sync(
    factory,
    *,
    institute_code: str,
    user_id: int,
    requested_by: str,
    minutes_ago: int = 5,
) -> None:
    finished = utcnow() - timedelta(minutes=minutes_ago)
    with factory() as session:
        session.add(
            SyncJob(
                kind="components",
                institute_code=institute_code,
                status="failed",
                phase="fetching",
                current=0,
                total=None,
                percent=None,
                message="Component sync failed.",
                error="PDB unavailable.",
                requested_by=requested_by,
                user_id=user_id,
                active_key=None,
                created_at=finished,
                started_at=finished,
                updated_at=finished,
                finished_at=finished,
            )
        )
        session.commit()


# -- the requester marker ----------------------------------------------------


def test_a_scheduled_job_is_labelled_as_scheduled_and_names_whose_codes_ran():
    label = scheduled_requested_by("anna.abel@example.org")

    # The marker leads, so nothing reads as if this person pressed sync; the
    # owner is still named because their access is what reached the PDB.
    assert label.startswith(SCHEDULED_REQUESTED_BY_PREFIX)
    assert "anna.abel@example.org" in label
    assert is_scheduled_job(label)
    assert not is_scheduled_job("anna.abel@example.org")


def test_the_evaluation_cadence_never_drops_below_a_minute(tmp_path):
    factory = _factory(tmp_path)
    scheduler = AutoSyncScheduler(
        factory, _settings(auto_sync_poll_minutes=0), RecordingManager(), lambda *a: None
    )

    # The per-institute interval floor lives in read_auto_sync_schedule; this
    # is only how often the scheduler wakes to look, and it must not spin.
    assert scheduler._poll_seconds >= 60


# -- who it may run as -------------------------------------------------------


def test_it_runs_as_whoever_last_synced_this_institute_by_hand(tmp_path):
    factory = _factory(tmp_path)
    institute = create_institute_profile(
        factory, code="TUDO", name="TU Dortmund", settings=ENABLED_SCHEDULE
    )["id"]
    older = _account_with_codes(factory, "older@example.org", institute)
    recent = _account_with_codes(factory, "recent@example.org", institute)
    _succeeded_component_sync(factory, institute_code="TUDO", user_id=older, minutes_ago=90)
    _succeeded_component_sync(factory, institute_code="TUDO", user_id=recent, minutes_ago=5)

    with factory() as session:
        owner = find_credential_owner(session, "TUDO")

    assert owner is not None
    assert owner.id == recent


def test_an_institute_nobody_ever_synced_is_never_synced_automatically(tmp_path):
    factory = _factory(tmp_path)
    institute = create_institute_profile(
        factory, code="DESYZ", name="DESY Zeuthen", settings=ENABLED_SCHEDULE
    )["id"]
    _account_with_codes(factory, "operator@example.org", institute)
    # Credentials exist, but nobody ever chose to mirror this institute.

    with factory() as session:
        assert find_credential_owner(session, "DESYZ") is None


def test_a_disconnected_credential_stops_the_schedule_for_that_institute(tmp_path):
    factory = _factory(tmp_path)
    institute = create_institute_profile(
        factory, code="TUDO", name="TU Dortmund", settings=ENABLED_SCHEDULE
    )["id"]
    user_id = _account_with_codes(factory, "operator@example.org", institute)
    _succeeded_component_sync(factory, institute_code="TUDO", user_id=user_id)

    with factory() as session:
        session.delete(session.get(PdbCredential, user_id))
        session.commit()

    with factory() as session:
        # Revoking codes must silently stop unattended traffic, not fall back
        # to some other account.
        assert find_credential_owner(session, "TUDO") is None


def test_a_deactivated_account_stops_the_schedule_for_that_institute(tmp_path):
    factory = _factory(tmp_path)
    institute = create_institute_profile(
        factory, code="TUDO", name="TU Dortmund", settings=ENABLED_SCHEDULE
    )["id"]
    user_id = _account_with_codes(factory, "operator@example.org", institute)
    _succeeded_component_sync(factory, institute_code="TUDO", user_id=user_id)

    with factory() as session:
        session.get(User, user_id).is_active = False
        session.commit()

    with factory() as session:
        assert find_credential_owner(session, "TUDO") is None


def test_a_viewer_cannot_remain_the_credential_owner_after_a_role_downgrade(tmp_path):
    factory = _factory(tmp_path)
    institute = create_institute_profile(
        factory, code="TUDO", name="TU Dortmund", settings=ENABLED_SCHEDULE
    )["id"]
    user_id = _account_with_codes(factory, "operator@example.org", institute)
    _succeeded_component_sync(factory, institute_code="TUDO", user_id=user_id)

    with factory() as session:
        session.get(User, user_id).role = "viewer"
        session.commit()

    with factory() as session:
        assert find_credential_owner(session, "TUDO") is None


def test_an_institute_bound_owner_cannot_be_reused_outside_their_scope(tmp_path):
    factory = _factory(tmp_path)
    create_institute_profile(
        factory, code="TUDO", name="TU Dortmund", settings=ENABLED_SCHEDULE
    )
    other_institute = create_institute_profile(
        factory, code="DESYZ", name="DESY Zeuthen", settings=ENABLED_SCHEDULE
    )["id"]
    user_id = _account_with_codes(factory, "operator@example.org", other_institute)
    # A historical row can outlive a scope change. Current authorisation, not
    # that old success, decides whether unattended access is still allowed.
    _succeeded_component_sync(factory, institute_code="TUDO", user_id=user_id)

    with factory() as session:
        assert find_credential_owner(session, "TUDO") is None


def test_it_falls_back_to_an_earlier_syncer_when_the_latest_one_lost_access(tmp_path):
    factory = _factory(tmp_path)
    institute = create_institute_profile(
        factory, code="TUDO", name="TU Dortmund", settings=ENABLED_SCHEDULE
    )["id"]
    keeps = _account_with_codes(factory, "keeps@example.org", institute)
    lost = _account_with_codes(factory, "lost@example.org", institute)
    _succeeded_component_sync(factory, institute_code="TUDO", user_id=keeps, minutes_ago=90)
    _succeeded_component_sync(factory, institute_code="TUDO", user_id=lost, minutes_ago=5)

    with factory() as session:
        session.delete(session.get(PdbCredential, lost))
        session.commit()

    with factory() as session:
        owner = find_credential_owner(session, "TUDO")

    assert owner is not None
    assert owner.id == keeps


def test_credentials_already_known_to_be_rejected_are_skipped(tmp_path):
    factory = _factory(tmp_path)
    institute = create_institute_profile(
        factory, code="TUDO", name="TU Dortmund", settings=ENABLED_SCHEDULE
    )["id"]
    user_id = _account_with_codes(factory, "operator@example.org", institute)
    _succeeded_component_sync(factory, institute_code="TUDO", user_id=user_id)

    with factory() as session:
        session.get(PdbCredential, user_id).status = "invalid"
        session.commit()

    with factory() as session:
        # Otherwise this manufactures one failed job per interval, forever,
        # for a person to keep dismissing.
        assert find_credential_owner(session, "TUDO") is None


def test_an_unknown_credential_status_fails_closed(tmp_path):
    factory = _factory(tmp_path)
    institute = create_institute_profile(
        factory, code="TUDO", name="TU Dortmund", settings=ENABLED_SCHEDULE
    )["id"]
    user_id = _account_with_codes(factory, "operator@example.org", institute)
    _succeeded_component_sync(factory, institute_code="TUDO", user_id=user_id)

    with factory() as session:
        session.get(PdbCredential, user_id).status = "mystery"
        session.commit()

    with factory() as session:
        assert find_credential_owner(session, "TUDO") is None


def test_a_credential_that_was_merely_unreachable_is_still_used(tmp_path):
    factory = _factory(tmp_path)
    institute = create_institute_profile(
        factory, code="TUDO", name="TU Dortmund", settings=ENABLED_SCHEDULE
    )["id"]
    user_id = _account_with_codes(factory, "operator@example.org", institute)
    _succeeded_component_sync(factory, institute_code="TUDO", user_id=user_id)

    with factory() as session:
        session.get(PdbCredential, user_id).status = "unreachable"
        session.commit()

    with factory() as session:
        owner = find_credential_owner(session, "TUDO")

    # "unreachable" means the network was down when it was last checked —
    # exactly the case a later scheduled attempt exists to retry.
    assert owner is not None
    assert owner.id == user_id


# -- what a tick does --------------------------------------------------------


def test_a_tick_queues_one_component_sync_and_marks_it_scheduled(tmp_path):
    factory = _factory(tmp_path)
    institute = create_institute_profile(
        factory, code="TUDO", name="TU Dortmund", settings=ENABLED_SCHEDULE
    )["id"]
    user_id = _account_with_codes(factory, "operator@example.org", institute)
    _succeeded_component_sync(
        factory, institute_code="TUDO", user_id=user_id, minutes_ago=90
    )
    manager = RecordingManager()

    AutoSyncScheduler(factory, _settings(), manager, lambda *a: None).tick()

    assert len(manager.started) == 1
    with factory() as session:
        job = session.get(SyncJob, manager.started[0])
        assert job.kind == "components"
        assert job.institute_code == "TUDO"
        assert job.user_id == user_id
        assert is_scheduled_job(job.requested_by)


def test_a_second_tick_converges_on_the_running_sweep_instead_of_stacking(tmp_path):
    factory = _factory(tmp_path)
    institute = create_institute_profile(
        factory, code="TUDO", name="TU Dortmund", settings=ENABLED_SCHEDULE
    )["id"]
    user_id = _account_with_codes(factory, "operator@example.org", institute)
    _succeeded_component_sync(
        factory, institute_code="TUDO", user_id=user_id, minutes_ago=90
    )
    manager = RecordingManager()
    scheduler = AutoSyncScheduler(factory, _settings(), manager, lambda *a: None)

    scheduler.tick()
    scheduler.tick()

    # The durable single-flight lease is the arbiter: the second tick sees the
    # live job and hands nothing new to the manager.
    assert len(manager.started) == 1
    with factory() as session:
        assert session.query(SyncJob).filter(SyncJob.active_key.is_not(None)).count() == 1


def test_a_failed_scheduled_attempt_is_throttled_by_the_profile_interval(tmp_path):
    factory = _factory(tmp_path)
    institute = create_institute_profile(
        factory, code="TUDO", name="TU Dortmund", settings=ENABLED_SCHEDULE
    )["id"]
    user_id = _account_with_codes(factory, "operator@example.org", institute)
    _succeeded_component_sync(
        factory, institute_code="TUDO", user_id=user_id, minutes_ago=90
    )
    _failed_component_sync(
        factory,
        institute_code="TUDO",
        user_id=user_id,
        requested_by=scheduled_requested_by("operator@example.org"),
        minutes_ago=5,
    )
    manager = RecordingManager()

    AutoSyncScheduler(factory, _settings(), manager, lambda *a: None).tick()

    # The failure released its single-flight lease, but the scheduler must not
    # turn the five-minute deployment poll into the institute's retry rate.
    assert manager.started == []


def test_a_scheduled_jobs_automatic_retry_also_moves_the_throttle_boundary(tmp_path):
    factory = _factory(tmp_path)
    institute = create_institute_profile(
        factory, code="TUDO", name="TU Dortmund", settings=ENABLED_SCHEDULE
    )["id"]
    user_id = _account_with_codes(factory, "operator@example.org", institute)
    _succeeded_component_sync(
        factory, institute_code="TUDO", user_id=user_id, minutes_ago=90
    )
    scheduled_label = scheduled_requested_by("operator@example.org")
    _failed_component_sync(
        factory,
        institute_code="TUDO",
        user_id=user_id,
        requested_by=scheduled_label,
        minutes_ago=20,
    )
    _failed_component_sync(
        factory,
        institute_code="TUDO",
        user_id=user_id,
        requested_by=auto_retry_requested_by(scheduled_label),
        minutes_ago=5,
    )
    manager = RecordingManager()

    AutoSyncScheduler(factory, _settings(), manager, lambda *a: None).tick()

    assert manager.started == []


def test_a_manual_failure_does_not_postpone_an_already_due_schedule(tmp_path):
    factory = _factory(tmp_path)
    institute = create_institute_profile(
        factory, code="TUDO", name="TU Dortmund", settings=ENABLED_SCHEDULE
    )["id"]
    user_id = _account_with_codes(factory, "operator@example.org", institute)
    _succeeded_component_sync(
        factory, institute_code="TUDO", user_id=user_id, minutes_ago=90
    )
    _failed_component_sync(
        factory,
        institute_code="TUDO",
        user_id=user_id,
        requested_by="operator@example.org",
        minutes_ago=5,
    )
    manager = RecordingManager()

    AutoSyncScheduler(factory, _settings(), manager, lambda *a: None).tick()

    assert len(manager.started) == 1


def test_an_offline_deployment_never_schedules_anything(tmp_path):
    factory = _factory(tmp_path)
    institute = create_institute_profile(
        factory, code="TUDO", name="TU Dortmund", settings=ENABLED_SCHEDULE
    )["id"]
    user_id = _account_with_codes(factory, "operator@example.org", institute)
    _succeeded_component_sync(factory, institute_code="TUDO", user_id=user_id)
    manager = RecordingManager()

    AutoSyncScheduler(
        factory,
        _settings(pdb_instance="offline", allow_production=False),
        manager,
        lambda *a: None,
    ).tick()

    # Offline reaches no PDB; scheduling would only manufacture failed jobs.
    assert manager.started == []
    with factory() as session:
        assert session.query(SyncJob).count() == 1  # only the seeded history


def test_a_failing_tick_never_escapes_and_kills_the_loop(tmp_path):
    factory = _factory(tmp_path)
    institute = create_institute_profile(
        factory, code="TUDO", name="TU Dortmund", settings=ENABLED_SCHEDULE
    )["id"]
    user_id = _account_with_codes(factory, "operator@example.org", institute)
    _succeeded_component_sync(
        factory, institute_code="TUDO", user_id=user_id, minutes_ago=90
    )

    class ExplodingManager:
        attempted: list[int] = []

        def start(self, job_id: int, fetcher) -> None:
            self.attempted.append(job_id)
            raise RuntimeError("manager is gone")

    manager = ExplodingManager()
    # One bad cycle must not stop every future refresh, and the lease committed
    # immediately before submit must not remain live after submit is rejected.
    AutoSyncScheduler(factory, _settings(), manager, lambda *a: None).tick()

    assert len(manager.attempted) == 1
    with factory() as session:
        job = session.get(SyncJob, manager.attempted[0])
        assert job.status == "failed"
        assert job.active_key is None
        assert job.error == "Component sync could not be scheduled."


def test_the_institute_that_waited_longest_is_swept_first(tmp_path):
    factory = _factory(tmp_path)
    create_institute_profile(
        factory, code="TUDO", name="TU Dortmund", settings=ENABLED_SCHEDULE
    )
    create_institute_profile(
        factory, code="DESYZ", name="DESY Zeuthen", settings=ENABLED_SCHEDULE
    )
    # A global admin can legitimately have started both institute scopes.
    user_id = _account_with_codes(factory, "operator@example.org")
    # TUDO was swept minutes ago, DESYZ hours ago.
    _succeeded_component_sync(factory, institute_code="TUDO", user_id=user_id, minutes_ago=5)
    _succeeded_component_sync(factory, institute_code="DESYZ", user_id=user_id, minutes_ago=600)
    manager = RecordingManager()

    AutoSyncScheduler(factory, _settings(), manager, lambda *a: None).tick()

    # The component-sync lease is global, so one tick can only start ONE
    # sweep. Without staleness ordering the same institute would win every
    # tick and the other would never be refreshed at all.
    assert len(manager.started) == 1
    with factory() as session:
        assert session.get(SyncJob, manager.started[0]).institute_code == "DESYZ"


def test_ordering_survives_the_naive_and_aware_timestamp_mix(tmp_path):
    factory = _factory(tmp_path)
    tudo = create_institute_profile(
        factory, code="TUDO", name="TU Dortmund", settings=ENABLED_SCHEDULE
    )["id"]
    create_institute_profile(
        factory, code="DESYZ", name="DESY Zeuthen", settings=ENABLED_SCHEDULE
    )
    user_id = _account_with_codes(factory, "operator@example.org", tudo)
    _succeeded_component_sync(factory, institute_code="TUDO", user_id=user_id, minutes_ago=5)

    with factory() as session:
        # DESYZ has never been swept: a missing timestamp must sort as the
        # longest wait rather than raising when compared against a real one.
        order = institutes_by_staleness(session)

    assert order[0].code == "DESYZ"


def test_scheduler_stop_joins_an_in_flight_to_thread_tick(tmp_path):
    factory = _factory(tmp_path)
    scheduler = AutoSyncScheduler(factory, _settings(), RecordingManager(), lambda *a: None)
    entered = Event()
    release = Event()
    calls: list[str] = []

    def blocking_tick() -> None:
        calls.append("tick")
        entered.set()
        release.wait(timeout=5)

    scheduler._tick = blocking_tick
    scheduler._poll_seconds = 0

    async def exercise() -> bool:
        await scheduler.start()
        assert await asyncio.wait_for(asyncio.to_thread(entered.wait), timeout=2)
        stopping = asyncio.create_task(scheduler.stop())
        await asyncio.sleep(0.05)
        stopped_before_thread = stopping.done()
        release.set()
        await asyncio.wait_for(stopping, timeout=2)
        return stopped_before_thread

    assert asyncio.run(exercise()) is False
    assert calls == ["tick"]
    # A late worker that only begins after stop sees the barrier flag and does
    # not enter the scheduling pass at all.
    scheduler.tick()
    assert calls == ["tick"]


def test_app_stops_the_scheduler_before_its_shared_sync_manager(tmp_path):
    app = create_app(
        _settings(database_url=f"sqlite:///{tmp_path / 'shutdown-order.db'}")
    )
    scheduler = app.state.auto_sync_scheduler
    manager = app.state.sync_job_manager
    assert scheduler is not None
    try:
        assert app.router.on_shutdown.index(scheduler.stop) < app.router.on_shutdown.index(
            manager.shutdown
        )
    finally:
        manager.shutdown()
