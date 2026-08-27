import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier, Event, Thread

from authutil import create_account, create_institute_profile
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text

from app.db import Base, make_engine, make_session_factory
from app.models import (
    Component,
    InstituteProfile,
    SyncJob,
    TestRunAttachment,
    TestRunEvidence,
    User,
    utcnow,
)
from app.pdb_credentials import (
    PdbAccessCodes,
    PdbCredentialNotFoundError,
    save_pdb_credentials,
)
from app.pdb_sync import FetchResult, PdbSyncUnavailable
from app.sync import SyncRecord
from app.sync_jobs import (
    SyncJobManager,
    acquire_component_sync_lease,
    acquire_evidence_sync_lease,
    auto_retry_requested_by,
    recover_interrupted_sync_jobs,
    run_component_sync_job,
    run_evidence_sync_job,
)


class RecordingManager:
    def __init__(self) -> None:
        self.started: list[int] = []
        self.evidence_started: list[int] = []

    def start(self, job_id: int, fetcher) -> None:
        self.started.append(job_id)

    def start_evidence(self, job_id: int) -> None:
        self.evidence_started.append(job_id)


def record(sn: str, **overrides) -> SyncRecord:
    values = {
        "sn": sn,
        "component_type": "MODULE",
        "type_code": "R5M0",
        "stage": "GLUED",
        "location": "TUDO",
        "institute_code": "TUDO",
    }
    return SyncRecord(**{**values, **overrides})


def test_component_job_is_global_single_flight_and_discoverable(
    client: TestClient, tudo: dict, as_operator
):
    manager = RecordingManager()
    client.app.state.sync_job_manager = manager

    first = client.post("/api/sync/jobs/components/TUDO")
    assert first.status_code == 202, first.text
    body = first.json()
    assert body["kind"] == "components"
    assert body["status"] == "queued"
    assert body["phase"] == "queued"
    assert isinstance(body["id"], int)

    second = client.post("/api/sync/jobs/components/TUDO")
    assert second.status_code == 202
    assert second.json()["id"] == body["id"]
    assert manager.started == [body["id"]]

    active = client.get("/api/sync/jobs/active", params={"kind": "components"})
    assert active.status_code == 200
    assert active.json()["id"] == body["id"]
    latest = client.get("/api/sync/jobs/latest", params={"kind": "components"})
    assert latest.status_code == 200
    assert latest.json()["id"] == body["id"]
    assert client.get(f"/api/sync/jobs/{body['id']}").json()["status"] == "queued"


def test_evidence_job_is_single_flight_and_discoverable(
    client: TestClient, tudo: dict, as_operator
):
    manager = RecordingManager()
    client.app.state.sync_job_manager = manager

    first = client.post("/api/sync/jobs/evidence/TUDO")
    assert first.status_code == 202, first.text
    body = first.json()
    assert body["kind"] == "evidence"
    assert body["status"] == "queued"

    second = client.post("/api/sync/jobs/evidence/TUDO")
    assert second.status_code == 202
    assert second.json()["id"] == body["id"]
    assert manager.evidence_started == [body["id"]]
    active = client.get("/api/sync/jobs/active", params={"kind": "evidence"})
    assert active.status_code == 200
    assert active.json()["id"] == body["id"]


def test_evidence_jobs_queue_independently_per_institute(
    client: TestClient, session_factory, tudo: dict, as_operator
):
    manager = RecordingManager()
    client.app.state.sync_job_manager = manager
    create_institute_profile(
        session_factory,
        code="DESYZ",
        name="DESY Zeuthen",
        local_name_prefix="DESYZ-",
    )

    tudo_job = client.post("/api/sync/jobs/evidence/TUDO")
    desyz_job = client.post("/api/sync/jobs/evidence/DESYZ")
    tudo_again = client.post("/api/sync/jobs/evidence/TUDO")

    assert tudo_job.status_code == 202
    assert desyz_job.status_code == 202
    assert tudo_job.json()["id"] != desyz_job.json()["id"]
    assert tudo_again.json()["id"] == tudo_job.json()["id"]
    assert manager.evidence_started == [tudo_job.json()["id"], desyz_job.json()["id"]]
    active_tudo = client.get(
        "/api/sync/jobs/active",
        params={"kind": "evidence", "institute_code": "TUDO"},
    )
    active_desyz = client.get(
        "/api/sync/jobs/active",
        params={"kind": "evidence", "institute_code": "DESYZ"},
    )
    assert active_tudo.json()["id"] == tudo_job.json()["id"]
    assert active_desyz.json()["id"] == desyz_job.json()["id"]


def test_latest_sync_job_returns_204_without_matching_history(
    client: TestClient, as_viewer
):
    assert client.get("/api/sync/jobs/latest", params={"kind": "components"}).status_code == 204
    assert (
        client.get(
            "/api/sync/jobs/latest",
            params={"kind": "evidence", "institute_code": "MISSING"},
        ).status_code
        == 204
    )


def test_legacy_sync_cannot_bypass_active_job(client: TestClient, tudo: dict, as_operator):
    client.app.state.sync_job_manager = RecordingManager()
    active_id = client.post("/api/sync/jobs/components/TUDO").json()["id"]
    called = False

    def fetcher(settings, institute, access_codes, report):
        nonlocal called
        called = True
        return FetchResult(records=[], skipped=0)

    client.app.state.component_fetcher = fetcher
    response = client.post("/api/sync/components/TUDO")
    assert response.status_code == 409
    assert str(active_id) in response.json()["detail"]
    assert called is False


def test_legacy_sync_commits_terminal_lease_with_mirror(
    client: TestClient, session_factory, tudo: dict, as_operator
):
    client.app.state.component_fetcher = lambda settings, institute, access_codes, report: (
        FetchResult(records=[record("20USEM00000077")], skipped=0)
    )

    response = client.post("/api/sync/components/TUDO")
    assert response.status_code == 200, response.text
    with session_factory() as session:
        job = session.scalar(select(SyncJob).order_by(SyncJob.id.desc()))
        component = session.scalar(select(Component).where(Component.sn == "20USEM00000077"))
        assert component is not None
        assert job is not None and job.status == "succeeded"
        assert job.active_key is None
        assert job.result["created"] == 1


def test_component_job_runner_commits_mirror_and_terminal_result_atomically(
    client: TestClient, session_factory, tudo: dict, as_operator
):
    manager = RecordingManager()
    client.app.state.sync_job_manager = manager
    job_id = client.post("/api/sync/jobs/components/TUDO").json()["id"]
    progress: list[tuple[str, int, int | None]] = []
    with session_factory() as session:
        owner_id = session.get(SyncJob, job_id).user_id

    def fetcher(settings, institute, access_codes, report):
        assert institute.code == "TUDO"
        assert access_codes.access_code1 == f"offline-code-1-user-{owner_id}"
        assert access_codes.access_code2 == f"offline-code-2-user-{owner_id}"
        report("fetching", 1, 1)
        report("mapping", 1, 1)
        progress.extend([("fetching", 1, 1), ("mapping", 1, 1)])
        return FetchResult(records=[record("20USEM00000001")], skipped=0)

    followups: list[tuple[str, str, int]] = []
    run_component_sync_job(
        session_factory,
        client.app.state.settings,
        fetcher,
        job_id,
        lambda institute_code, requested_by, user_id: followups.append(
            (institute_code, requested_by, user_id)
        ),
    )

    status = client.get(f"/api/sync/jobs/{job_id}").json()
    assert status["status"] == "succeeded"
    assert status["phase"] == "complete"
    assert status["percent"] == 100.0
    assert status["result"] == {
        "institute_code": "TUDO",
        "fetched": 1,
        "skipped": 0,
        "created": 1,
        "updated": 0,
        "unchanged": 0,
        "stale": 0,
        "total": 1,
    }
    assert progress == [("fetching", 1, 1), ("mapping", 1, 1)]
    assert len(followups) == 1
    assert followups[0][0] == "TUDO"
    assert "@" in followups[0][1]
    assert followups[0][2] == owner_id
    assert client.get("/api/sync/jobs/active", params={"kind": "components"}).status_code == 204
    latest = client.get("/api/sync/jobs/latest", params={"kind": "components"})
    assert latest.status_code == 200
    assert latest.json()["id"] == job_id
    assert latest.json()["status"] == "succeeded"
    assert client.get("/api/components/20USEM00000001").status_code == 200


def test_component_job_failure_rolls_back_mirror_and_releases_lease(
    client: TestClient, session_factory, tudo: dict, as_operator
):
    client.app.state.sync_job_manager = RecordingManager()
    job_id = client.post("/api/sync/jobs/components/TUDO").json()["id"]

    def fetcher(settings, institute, access_codes, report):
        assert access_codes.access_code1.startswith("offline-code-1-user-")
        return FetchResult(
            records=[record("20USES00000001", parent_sn="20USEM99999999")],
            skipped=0,
        )

    run_component_sync_job(
        session_factory,
        client.app.state.settings,
        fetcher,
        job_id,
    )

    status = client.get(f"/api/sync/jobs/{job_id}").json()
    assert status["status"] == "failed"
    assert status["phase"] == "upserting"
    assert "20USEM99999999" in status["error"]
    with session_factory() as session:
        assert session.scalar(select(func.count(Component.id))) == 0
    assert client.get("/api/sync/jobs/active", params={"kind": "components"}).status_code == 204


def test_component_job_without_personal_credential_fails_closed(
    client: TestClient, session_factory, tudo: dict, as_operator, monkeypatch
):
    client.app.state.sync_job_manager = RecordingManager()
    job_id = client.post("/api/sync/jobs/components/TUDO").json()["id"]
    fetch_called = False

    def missing_credential(session, *, user_id, encryption_key):
        raise PdbCredentialNotFoundError("No personal ITKDB credential is connected.")

    def fetcher(settings, institute, access_codes, report):
        nonlocal fetch_called
        fetch_called = True
        return FetchResult(records=[], skipped=0)

    monkeypatch.setattr("app.sync_jobs.load_pdb_credentials", missing_credential)

    run_component_sync_job(
        session_factory,
        client.app.state.settings,
        fetcher,
        job_id,
    )

    status = client.get(f"/api/sync/jobs/{job_id}").json()
    assert status["status"] == "failed"
    assert "personal ITKDB credential" in status["error"]
    assert fetch_called is False
    assert client.get("/api/sync/jobs/active", params={"kind": "components"}).status_code == 204


def test_component_job_redacts_untrusted_fetcher_error(
    client: TestClient,
    session_factory,
    tudo: dict,
    as_operator,
    monkeypatch,
    caplog,
):
    client.app.state.sync_job_manager = RecordingManager()
    job_id = client.post("/api/sync/jobs/components/TUDO").json()["id"]
    sentinel = "sentinel-personal-access-code"
    codes = PdbAccessCodes(access_code1=sentinel, access_code2="second-secret")
    monkeypatch.setattr(
        "app.sync_jobs.load_pdb_credentials",
        lambda session, *, user_id, encryption_key: codes,
    )

    def fetcher(settings, institute, access_codes, report):
        raise PdbSyncUnavailable(
            f"upstream request contained {access_codes.access_code1} / {access_codes.access_code2}"
        )

    run_component_sync_job(
        session_factory,
        client.app.state.settings,
        fetcher,
        job_id,
    )

    status = client.get(f"/api/sync/jobs/{job_id}").json()
    assert status["status"] == "failed"
    assert sentinel not in status["error"]
    assert "second-secret" not in status["error"]
    assert sentinel not in caplog.text
    assert "second-secret" not in caplog.text
    assert "<redacted>" in status["error"]


def test_background_jobs_use_only_their_starters_credentials(
    client: TestClient, session_factory, tudo: dict
):
    alice_id = create_account(
        session_factory,
        email="alice-sync@example.org",
        password="test-password-123",
        role="operator",
        institute_id=tudo["id"],
    )
    bob_id = create_account(
        session_factory,
        email="bob-sync@example.org",
        password="test-password-123",
        role="operator",
        institute_id=tudo["id"],
    )
    fetched_with: list[str] = []

    def fetcher(settings, institute, access_codes, report):
        fetched_with.append(access_codes.access_code1)
        return FetchResult(records=[], skipped=0)

    with session_factory() as session:
        for user_id, name in ((alice_id, "alice"), (bob_id, "bob")):
            save_pdb_credentials(
                session,
                user_id=user_id,
                access_codes=PdbAccessCodes(
                    access_code1=f"{name}-1",
                    access_code2=f"{name}-2",
                ),
                pdb_identity=f"pdb-{name}",
                institutions=["TUDO"],
                encryption_key=client.app.state.settings.pdb_credential_encryption_key,
            )
        session.commit()

    job_ids = []
    for user_id, email in (
        (alice_id, "alice-sync@example.org"),
        (bob_id, "bob-sync@example.org"),
    ):
        with session_factory() as session:
            lease = acquire_component_sync_lease(
                session,
                institute_code="TUDO",
                requested_by=email,
                user_id=user_id,
            )
            assert lease.created is True
            job_ids.append(lease.job.id)
        run_component_sync_job(
            session_factory,
            client.app.state.settings,
            fetcher,
            job_ids[-1],
        )

    assert fetched_with == ["alice-1", "bob-1"]
    with session_factory() as session:
        jobs = [session.get(SyncJob, job_id) for job_id in job_ids]
        assert all(job is not None and job.status == "succeeded" for job in jobs)
        serialized = repr([(job.message, job.result, job.error) for job in jobs if job is not None])
    assert "alice-1" not in serialized
    assert "bob-1" not in serialized


class _EvidenceClient:
    def __init__(self):
        self.component_requests: list[str] = []

    def get(self, action, json=None):
        if action == "getComponent":
            sn = json["component"]
            self.component_requests.append(sn)
            return {
                "tests": [
                    {
                        "testType": {"code": "VISUAL_INSPECTION"},
                        "testRuns": [{"id": f"run-{sn}", "passed": True}],
                    }
                ]
            }
        if action == "getTestRun":
            assert json["noEosToken"] is True
            return {
                "attachments": [
                    {
                        "code": f"attachment-{json['testRun']}",
                        "filename": "inspection.jpg",
                        "contentType": "image/jpeg",
                        "type": "file",
                    }
                ]
            }
        if action == "getTestRunAttachment":

            class _BinaryFile:
                content = b"\xff\xd8\xff evidence-job"
                mimetype = "image/jpeg"

            return _BinaryFile()
        raise AssertionError(f"unexpected evidence request {action}")


class _EvidenceGateway:
    is_configured = True

    def __init__(self, client):
        self._client = client

    def client(self):
        return self._client


def test_evidence_job_mirrors_detail_and_attachments_from_profile_scope(
    client: TestClient,
    session_factory,
    tudo: dict,
    as_operator,
    tmp_path,
):
    client.app.state.settings.attachment_dir = str(tmp_path / "attachments")
    with session_factory() as session:
        # Pin the sweep scope in the institute profile — that is what this
        # test is about — so the assertion does not depend on the value of
        # the collaboration-wide default type list.
        profile = session.scalar(
            select(InstituteProfile).where(InstituteProfile.code == "TUDO")
        )
        profile.settings = {
            **(profile.settings or {}),
            "evidence_component_types": ["MODULE"],
        }
        session.add(
            Component(
                sn="20USEM00000101",
                component_type="MODULE",
                type_code="R5M0",
                stage="GLUED",
                location="TUDO",
                institute_code="TUDO",
            )
        )
        session.add(
            Component(
                sn="20USES00000101",
                component_type="SENSOR",
                type_code="S",
                stage="READY",
                location="TUDO",
                institute_code="TUDO",
            )
        )
        session.commit()

    manager = RecordingManager()
    client.app.state.sync_job_manager = manager
    job_id = client.post("/api/sync/jobs/evidence/TUDO").json()["id"]
    fake_client = _EvidenceClient()

    def gateway_factory(settings, access_codes):
        assert access_codes.access_code1.startswith("offline-code-1-user-")
        return _EvidenceGateway(fake_client)

    run_evidence_sync_job(
        session_factory,
        client.app.state.settings,
        gateway_factory,
        job_id,
    )

    status = client.get(f"/api/sync/jobs/{job_id}").json()
    assert status["status"] == "succeeded"
    assert status["result"]["component_types"] == ["MODULE"]
    assert status["result"]["components_processed"] == 1
    assert status["result"]["total"] == 1
    assert status["result"]["attachments_downloaded"] == 1
    assert fake_client.component_requests == ["20USEM00000101"]
    with session_factory() as session:
        assert session.scalar(select(func.count(TestRunEvidence.id))) == 1
        attachment = session.scalar(select(TestRunAttachment))
        assert attachment is not None
        assert attachment.relative_path is not None
        assert (tmp_path / "attachments" / attachment.relative_path).is_file()
    assert client.get("/api/sync/jobs/active", params={"kind": "evidence"}).status_code == 204


def test_manager_wires_component_success_to_evidence_enqueue(client, session_factory):
    class _RecordingExecutor:
        def __init__(self):
            self.call = None

        def submit(self, function, *args):
            self.call = (function, args)

    manager = SyncJobManager(session_factory, client.app.state.settings)
    manager.shutdown()
    executor = _RecordingExecutor()
    manager._component_executor = executor

    def fetcher(settings, institute, access_codes, report):
        return FetchResult(records=[], skipped=0)

    manager.start(123, fetcher)

    function, args = executor.call
    assert function is run_component_sync_job
    assert args[:4] == (session_factory, client.app.state.settings, fetcher, 123)
    assert args[4] == manager.enqueue_evidence


def test_evidence_lease_converges_without_stacking(session_factory, tudo: dict, as_operator):
    with session_factory() as session:
        user_id = session.scalar(select(User.id))
        assert user_id is not None
        first = acquire_evidence_sync_lease(
            session,
            institute_code="TUDO",
            requested_by="operator@example.org",
            user_id=user_id,
        )
        second = acquire_evidence_sync_lease(
            session,
            institute_code="TUDO",
            requested_by="operator@example.org",
            user_id=user_id,
        )
    assert first.created is True
    assert second.created is False
    assert first.job.id == second.job.id


def test_restart_marks_live_jobs_interrupted(
    client: TestClient, session_factory, tudo: dict, as_operator
):
    from datetime import timedelta

    client.app.state.sync_job_manager = RecordingManager()
    job_id = client.post("/api/sync/jobs/components/TUDO").json()["id"]
    # Recovery targets jobs orphaned by a crash: their heartbeat has gone
    # stale. A job whose heartbeat is fresh is deliberately left alone (see
    # test_startup_recovery_leaves_a_live_sync_alone).
    with session_factory() as session:
        job = session.get(SyncJob, job_id)
        job.updated_at = utcnow() - timedelta(hours=1)
        session.commit()

    assert recover_interrupted_sync_jobs(session_factory) == 1
    with session_factory() as session:
        job = session.get(SyncJob, job_id)
        assert job is not None
        assert job.status == "interrupted"
        assert job.phase == "queued"
        assert job.active_key is None
        assert "no partial mirror changes" in job.error


def test_component_job_start_requires_operator(client: TestClient, tudo: dict, as_viewer):
    response = client.post("/api/sync/jobs/components/TUDO")
    assert response.status_code == 403


def test_sync_job_routes_are_in_openapi(client: TestClient):
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/sync/jobs/components/{institute_code}" in paths
    assert "/api/sync/jobs/evidence/{institute_code}" in paths
    assert "/api/sync/jobs/active" in paths
    assert "/api/sync/jobs/latest" in paths
    assert "/api/sync/jobs/{job_id}" in paths


def test_file_backed_concurrent_lease_starts_converge_on_one_job(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'lease-race.db'}")
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    barrier = Barrier(2)

    def start(index: int) -> tuple[int, bool]:
        with factory() as session:
            barrier.wait()
            lease = acquire_component_sync_lease(
                session,
                institute_code="TUDO",
                requested_by=f"operator-{index}@example.org",
                user_id=None,
            )
            return lease.job.id, lease.created

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [future.result() for future in [pool.submit(start, 1), pool.submit(start, 2)]]

    assert {job_id for job_id, created in results} == {results[0][0]}
    assert sorted(created for job_id, created in results) == [False, True]


def test_file_backed_sqlite_busy_is_retried_instead_of_escaping(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'lease-busy.db'}",
        connect_args={"check_same_thread": False, "timeout": 0.001},
    )
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    started = Event()

    def start() -> tuple[int, bool]:
        with factory() as session:
            started.set()
            lease = acquire_component_sync_lease(
                session,
                institute_code="TUDO",
                requested_by="operator@example.org",
                user_id=None,
            )
            return lease.job.id, lease.created

    with factory() as locker:
        locker.execute(text("BEGIN IMMEDIATE"))
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(start)
            assert started.wait(timeout=1)
            time.sleep(0.05)
            locker.commit()
            job_id, created = future.result(timeout=2)

    assert created is True
    assert isinstance(job_id, int)


class _FailingAfterNClient(_EvidenceClient):
    """Serves evidence for the first N components, then the PDB dies."""

    def __init__(self, fail_after: int):
        super().__init__()
        self._fail_after = fail_after

    def get(self, action, json=None):
        if action == "getComponent" and len(self.component_requests) >= self._fail_after:
            raise RuntimeError("PDB connection dropped mid-sweep")
        return super().get(action, json=json)


def test_evidence_job_keeps_what_it_already_mirrored_when_interrupted(
    client: TestClient,
    session_factory,
    tudo: dict,
    as_operator,
    tmp_path,
):
    """A sweep that dies partway must not throw away the components it finished.

    The whole institute sweep is long; closing the app (or any PDB hiccup)
    used to discard every fetched run because the job committed once at the
    very end. The user then sees every required test as "missing".
    """
    client.app.state.settings.attachment_dir = str(tmp_path / "attachments")
    # Serial fetch: this test pins *which* components were finished before the
    # failure, which is only deterministic without concurrent fetches.
    client.app.state.settings.sync_fetch_concurrency = 1
    with session_factory() as session:
        for index in range(1, 4):
            session.add(
                Component(
                    sn=f"20USEM0000020{index}",
                    component_type="MODULE",
                    type_code="R5M0",
                    stage="GLUED",
                    location="TUDO",
                    institute_code="TUDO",
                )
            )
        session.commit()

    manager = RecordingManager()
    client.app.state.sync_job_manager = manager
    job_id = client.post("/api/sync/jobs/evidence/TUDO").json()["id"]
    fake_client = _FailingAfterNClient(fail_after=2)

    run_evidence_sync_job(
        session_factory,
        client.app.state.settings,
        lambda settings, access_codes: _EvidenceGateway(fake_client),
        job_id,
    )

    status = client.get(f"/api/sync/jobs/{job_id}").json()
    assert status["status"] == "failed"
    # The two components fetched before the failure stay mirrored.
    with session_factory() as session:
        mirrored = session.scalars(select(TestRunEvidence.component_sn)).all()
    assert sorted(mirrored) == ["20USEM00000201", "20USEM00000202"]
    # And the lease is released, so the next attempt can continue where it stopped.
    assert client.get("/api/sync/jobs/active", params={"kind": "evidence"}).status_code == 204


def test_startup_recovery_leaves_a_live_sync_alone(session_factory):
    """A second app instance must not kill a sync another process is running.

    Startup recovery exists for jobs orphaned by a crash. It used to close
    every active row, so merely opening the app a second time aborted a sync
    that was making progress in the first one — observed against production
    at 600/3766 components.
    """
    from datetime import timedelta

    from app.sync_jobs import recover_interrupted_sync_jobs

    with session_factory() as session:
        live = SyncJob(
            kind="components",
            institute_code="TUDO",
            status="running",
            phase="fetching",
            current=600,
            total=3766,
            message="Fetching components.",
            requested_by="tester",
            active_key="components",
            updated_at=utcnow(),  # heartbeat from a second ago
        )
        orphaned = SyncJob(
            kind="evidence",
            institute_code="DESYZ",
            status="running",
            phase="fetching",
            current=29,
            total=262,
            message="Fetched 29/262 components.",
            requested_by="tester",
            active_key="evidence:DESYZ",
            updated_at=utcnow() - timedelta(hours=2),  # nobody has touched it
        )
        session.add_all([live, orphaned])
        session.commit()
        live_id, orphaned_id = live.id, orphaned.id

    recovered = recover_interrupted_sync_jobs(session_factory)

    assert recovered == 1
    with session_factory() as session:
        assert session.get(SyncJob, live_id).status == "running"
        assert session.get(SyncJob, live_id).active_key == "components"
        assert session.get(SyncJob, orphaned_id).status == "interrupted"
        assert session.get(SyncJob, orphaned_id).active_key is None


class _FlakyThenHealthyClient(_EvidenceClient):
    """getComponent fails N times per serial, then serves normally."""

    def __init__(self, failures_per_sn: int):
        super().__init__()
        self._budget: dict[str, int] = {}
        self._failures = failures_per_sn

    def get(self, action, json=None):
        if action == "getComponent":
            sn = json["component"]
            left = self._budget.setdefault(sn, self._failures)
            if left > 0:
                self._budget[sn] = left - 1
                raise RuntimeError("transient PDB hiccup")
        return super().get(action, json=json)


def test_evidence_job_retries_a_flaky_component_instead_of_failing_the_sweep(
    client: TestClient, session_factory, tudo: dict, as_operator, tmp_path, monkeypatch
):
    """One transient PDB hiccup must not abort a 262-component sweep at zero.

    Observed live: the first component's getComponent failed once on a flaky
    connection and the whole institute sweep failed with nothing mirrored.
    """
    monkeypatch.setattr("app.sync_jobs.sleep", lambda seconds: None)
    client.app.state.settings.attachment_dir = str(tmp_path / "attachments")
    with session_factory() as session:
        session.add(
            Component(
                sn="20USEM00000301",
                component_type="MODULE",
                type_code="R5M0",
                stage="GLUED",
                location="TUDO",
                institute_code="TUDO",
            )
        )
        session.commit()

    manager = RecordingManager()
    client.app.state.sync_job_manager = manager
    job_id = client.post("/api/sync/jobs/evidence/TUDO").json()["id"]
    fake_client = _FlakyThenHealthyClient(failures_per_sn=2)

    run_evidence_sync_job(
        session_factory,
        client.app.state.settings,
        lambda settings, access_codes: _EvidenceGateway(fake_client),
        job_id,
    )

    status = client.get(f"/api/sync/jobs/{job_id}").json()
    assert status["status"] == "succeeded", status["error"]
    with session_factory() as session:
        assert session.scalar(select(func.count(TestRunEvidence.id))) == 1


def _add_module(session_factory, sn: str) -> None:
    with session_factory() as session:
        session.add(
            Component(
                sn=sn,
                component_type="MODULE",
                type_code="R5M0",
                stage="GLUED",
                location="TUDO",
                institute_code="TUDO",
            )
        )
        session.commit()


def _wait_for(predicate, timeout: float = 8.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.02)
    raise AssertionError("condition was not reached in time")


def test_evidence_fetch_retry_keeps_the_job_heartbeat_fresh(
    client: TestClient, session_factory, tudo: dict, as_operator, tmp_path, monkeypatch
):
    """The quiet stretch between fetch attempts must carry a heartbeat.

    Three 60s attempts plus backoff exceed the 3-minute startup-recovery
    grace; without a heartbeat before each retry a second app instance would
    kill a live evidence job as orphaned.
    """
    monkeypatch.setattr("app.sync_jobs.sleep", lambda seconds: None)
    client.app.state.settings.attachment_dir = str(tmp_path / "attachments")
    # The per-retry heartbeat message is a serial-path contract; the pooled
    # path proves its liveness separately (see the parallel heartbeat test).
    client.app.state.settings.sync_fetch_concurrency = 1
    _add_module(session_factory, "20USEM00000401")
    client.app.state.sync_job_manager = RecordingManager()
    job_id = client.post("/api/sync/jobs/evidence/TUDO").json()["id"]
    observed: list[str] = []

    class _Client(_EvidenceClient):
        def __init__(self):
            super().__init__()
            self.failed_once = False

        def get(self, action, json=None):
            if action == "getComponent":
                if not self.failed_once:
                    self.failed_once = True
                    raise ConnectionResetError("Connection reset by peer")
                with session_factory() as session:
                    observed.append(session.get(SyncJob, job_id).message)
            return super().get(action, json=json)

    run_evidence_sync_job(
        session_factory,
        client.app.state.settings,
        lambda settings, access_codes: _EvidenceGateway(_Client()),
        job_id,
    )

    assert client.get(f"/api/sync/jobs/{job_id}").json()["status"] == "succeeded"
    # The durable message the retry attempt saw proves the heartbeat was
    # written *before* the backoff, not after the component finally answered.
    assert observed and "retry" in observed[0].lower()


def test_attachment_phase_heartbeats_during_a_flaky_download(
    client: TestClient, session_factory, tudo: dict, as_operator, tmp_path, monkeypatch
):
    """A single component with slow/flaky attachments must not go quiet for
    the whole download phase: the heartbeat fires per file and per retry."""
    monkeypatch.setattr("app.sync_jobs.sleep", lambda seconds: None)
    monkeypatch.setattr("app.attachment_store.sleep", lambda seconds: None)
    client.app.state.settings.attachment_dir = str(tmp_path / "attachments")
    _add_module(session_factory, "20USEM00000402")
    client.app.state.sync_job_manager = RecordingManager()
    job_id = client.post("/api/sync/jobs/evidence/TUDO").json()["id"]
    observed: list[str] = []

    class _Client(_EvidenceClient):
        def __init__(self):
            super().__init__()
            self.attachment_calls = 0

        def get(self, action, json=None):
            if action == "getTestRunAttachment":
                self.attachment_calls += 1
                if self.attachment_calls == 1:
                    raise ConnectionResetError("Connection reset by peer")
                with session_factory() as session:
                    observed.append(session.get(SyncJob, job_id).message)
            return super().get(action, json=json)

    run_evidence_sync_job(
        session_factory,
        client.app.state.settings,
        lambda settings, access_codes: _EvidenceGateway(_Client()),
        job_id,
    )

    status = client.get(f"/api/sync/jobs/{job_id}").json()
    assert status["status"] == "succeeded"
    assert status["result"]["attachments_downloaded"] == 1
    assert observed and "still working" in observed[0].lower()


def test_stale_component_lease_is_taken_over_at_acquire(session_factory, tudo: dict):
    """Crash + immediate restart leaves a fresh-looking zombie behind: startup
    recovery (rightly) skips it, so the next acquire must claim its lease."""
    from datetime import timedelta

    with session_factory() as session:
        zombie = SyncJob(
            kind="components",
            institute_code="TUDO",
            status="running",
            phase="fetching",
            message="Fetching components.",
            requested_by="tester",
            active_key="components",
            updated_at=utcnow() - timedelta(hours=1),
        )
        session.add(zombie)
        session.commit()
        zombie_id = zombie.id

    with session_factory() as session:
        lease = acquire_component_sync_lease(
            session,
            institute_code="TUDO",
            requested_by="operator@example.org",
            user_id=None,
        )

    assert lease.created is True
    assert lease.job.id != zombie_id
    with session_factory() as session:
        old = session.get(SyncJob, zombie_id)
        assert old.status == "interrupted"
        assert old.active_key is None
        new = session.get(SyncJob, lease.job.id)
        assert new.status == "queued"
        assert new.active_key == "components"


def test_stale_evidence_lease_is_taken_over_at_acquire(session_factory, tudo: dict):
    from datetime import timedelta

    with session_factory() as session:
        zombie = SyncJob(
            kind="evidence",
            institute_code="TUDO",
            status="running",
            phase="fetching",
            message="Fetching evidence.",
            requested_by="tester",
            active_key="evidence:TUDO",
            updated_at=utcnow() - timedelta(hours=1),
        )
        session.add(zombie)
        session.commit()
        zombie_id = zombie.id

    with session_factory() as session:
        lease = acquire_evidence_sync_lease(
            session,
            institute_code="TUDO",
            requested_by="operator@example.org",
            user_id=None,
        )

    assert lease.created is True and lease.job.id != zombie_id
    with session_factory() as session:
        assert session.get(SyncJob, zombie_id).status == "interrupted"
        assert session.get(SyncJob, zombie_id).active_key is None


def test_live_lease_is_not_taken_over_at_acquire(session_factory, tudo: dict):
    """The takeover must never race a job that is merely between heartbeats."""
    with session_factory() as session:
        live = SyncJob(
            kind="components",
            institute_code="TUDO",
            status="running",
            phase="fetching",
            message="Fetching components.",
            requested_by="tester",
            active_key="components",
            updated_at=utcnow(),
        )
        session.add(live)
        session.commit()
        live_id = live.id

    with session_factory() as session:
        lease = acquire_component_sync_lease(
            session,
            institute_code="TUDO",
            requested_by="operator@example.org",
            user_id=None,
        )

    assert lease.created is False
    assert lease.job.id == live_id


def test_mirrored_flat_fingerprints_chunk_large_scopes(session_factory, monkeypatch):
    """Production scopes reach thousands of serial numbers; the IN clause is
    read in bounded chunks. Shrinking the chunk proves the seams are correct."""
    from app.sync_jobs import _mirrored_flat_fingerprints

    monkeypatch.setattr("app.sync_jobs.FINGERPRINT_CHUNK_SIZE", 2)
    with session_factory() as session:
        for index in range(5):
            session.add(
                TestRunEvidence(
                    component_sn=f"20USEM0000050{index}",
                    test_type="VISUAL_INSPECTION",
                    passed=True,
                    source="pdb",
                    external_ref=f"run-{index}",
                    payload={"detail_synced": True, "state": "ready", "problems": False},
                )
            )
        # A shallow row must keep taking the detail round trip.
        session.add(
            TestRunEvidence(
                component_sn="20USEM00000500",
                test_type="OTHER",
                passed=True,
                source="pdb",
                external_ref="run-shallow",
                payload={},
            )
        )
        session.commit()

    with session_factory() as session:
        fingerprints = _mirrored_flat_fingerprints(
            session, [f"20USEM0000050{index}" for index in range(5)]
        )

    assert set(fingerprints) == {f"run-{index}" for index in range(5)}


# --- bounded automatic re-queue after a transient job failure ---------------


def _evidence_jobs(session_factory):
    with session_factory() as session:
        return list(
            session.scalars(
                select(SyncJob).where(SyncJob.kind == "evidence").order_by(SyncJob.id)
            )
        )


def _component_jobs(session_factory):
    with session_factory() as session:
        return list(
            session.scalars(
                select(SyncJob).where(SyncJob.kind == "components").order_by(SyncJob.id)
            )
        )


# The decision "does this failure earn an automatic retry?" is tested
# synchronously, against the runners themselves. No thread, no timer and no
# sleep is involved, so the cap is proven by construction rather than by
# waiting a moment and hoping nothing else shows up. Only the wiring test
# below uses the real timer/executor, and only for a positive outcome.


class _RecordingRetry:
    def __init__(self):
        self.contexts: list = []

    def __call__(self, context) -> None:
        self.contexts.append(context)


def _queue_evidence_job(session_factory, *, requested_by: str) -> int:
    with session_factory() as session:
        user_id = session.scalar(select(User.id))
        lease = acquire_evidence_sync_lease(
            session,
            institute_code="TUDO",
            requested_by=requested_by,
            user_id=user_id,
        )
        return lease.job.id


def _queue_component_job(session_factory, *, requested_by: str) -> int:
    with session_factory() as session:
        user_id = session.scalar(select(User.id))
        lease = acquire_component_sync_lease(
            session,
            institute_code="TUDO",
            requested_by=requested_by,
            user_id=user_id,
        )
        return lease.job.id


class _DownClient:
    def get(self, action, json=None):
        raise ConnectionResetError("Connection reset by peer")


def test_transient_evidence_failure_asks_for_one_automatic_retry(
    client: TestClient, session_factory, tudo: dict, as_operator, tmp_path, monkeypatch
):
    """A short outage must not leave the evidence mirror waiting for a click."""
    monkeypatch.setattr("app.sync_jobs.sleep", lambda seconds: None)
    client.app.state.settings.attachment_dir = str(tmp_path / "attachments")
    _add_module(session_factory, "20USEM00000601")
    job_id = _queue_evidence_job(session_factory, requested_by="operator@example.org")
    on_transient = _RecordingRetry()

    run_evidence_sync_job(
        session_factory,
        client.app.state.settings,
        lambda settings, codes: _EvidenceGateway(_DownClient()),
        job_id,
        on_transient,
    )

    with session_factory() as session:
        assert session.get(SyncJob, job_id).status == "failed"
    assert len(on_transient.contexts) == 1
    context = on_transient.contexts[0]
    assert context.institute.code == "TUDO"
    assert context.auto_retry is False


def test_an_automatic_retry_never_schedules_another_one(
    client: TestClient, session_factory, tudo: dict, as_operator, tmp_path, monkeypatch
):
    """The hard cap: a job that *is* the automatic retry fails without asking
    for a further one, so the chain is at most original + one retry."""
    monkeypatch.setattr("app.sync_jobs.sleep", lambda seconds: None)
    client.app.state.settings.attachment_dir = str(tmp_path / "attachments")
    _add_module(session_factory, "20USEM00000602")
    job_id = _queue_evidence_job(
        session_factory,
        requested_by=auto_retry_requested_by("operator@example.org"),
    )
    on_transient = _RecordingRetry()

    run_evidence_sync_job(
        session_factory,
        client.app.state.settings,
        lambda settings, codes: _EvidenceGateway(_DownClient()),
        job_id,
        on_transient,
    )

    with session_factory() as session:
        assert session.get(SyncJob, job_id).status == "failed"
    assert on_transient.contexts == []


def test_transient_component_failure_asks_for_one_automatic_retry(
    client: TestClient, session_factory, tudo: dict, as_operator
):
    job_id = _queue_component_job(session_factory, requested_by="operator@example.org")
    on_transient = _RecordingRetry()

    def outage_fetcher(settings, institute, access_codes, report):
        raise PdbSyncUnavailable("PDB component page 1 failed (transient network error).")

    run_component_sync_job(
        session_factory,
        client.app.state.settings,
        outage_fetcher,
        job_id,
        None,
        on_transient,
    )

    with session_factory() as session:
        assert session.get(SyncJob, job_id).status == "failed"
    assert len(on_transient.contexts) == 1
    assert on_transient.contexts[0].auto_retry is False


def test_an_automatic_component_retry_never_schedules_another_one(
    client: TestClient, session_factory, tudo: dict, as_operator
):
    job_id = _queue_component_job(
        session_factory,
        requested_by=auto_retry_requested_by("operator@example.org"),
    )
    on_transient = _RecordingRetry()

    def outage_fetcher(settings, institute, access_codes, report):
        raise PdbSyncUnavailable("PDB component page 1 failed (transient network error).")

    run_component_sync_job(
        session_factory,
        client.app.state.settings,
        outage_fetcher,
        job_id,
        None,
        on_transient,
    )

    assert on_transient.contexts == []


def test_successful_component_retry_does_not_spend_evidence_retry_budget(
    client: TestClient, session_factory, tudo: dict, as_operator
):
    job_id = _queue_component_job(
        session_factory,
        requested_by=auto_retry_requested_by("operator@example.org"),
    )
    followup_requesters: list[str] = []
    run_component_sync_job(
        session_factory,
        client.app.state.settings,
        lambda settings, institute, codes, report: FetchResult(
            records=[], skipped=0
        ),
        job_id,
        lambda institute_code, requested_by, user_id: followup_requesters.append(
            requested_by
        ),
    )

    assert len(followup_requesters) == 1
    assert followup_requesters[0].startswith("component follow-up")
    assert not followup_requesters[0].startswith("automatic retry")


def test_permanent_component_failure_does_not_schedule_a_retry(
    client: TestClient, session_factory, tudo: dict, as_operator
):
    """A bug or data problem will not fix itself in sixty seconds; only
    connectivity-shaped (Pdb*Unavailable) failures earn the automatic retry."""
    job_id = _queue_component_job(session_factory, requested_by="operator@example.org")
    on_transient = _RecordingRetry()

    def broken_fetcher(settings, institute, access_codes, report):
        raise RuntimeError("mapping bug")

    run_component_sync_job(
        session_factory,
        client.app.state.settings,
        broken_fetcher,
        job_id,
        None,
        on_transient,
    )

    with session_factory() as session:
        assert session.get(SyncJob, job_id).status == "failed"
    assert on_transient.contexts == []


def test_a_missing_credential_failure_does_not_schedule_a_retry(
    client: TestClient, session_factory, tudo: dict, as_operator, monkeypatch
):
    """Nothing about a disconnected account improves by retrying it."""

    def missing_credential(session, *, user_id, encryption_key):
        raise PdbCredentialNotFoundError("No personal ITKDB credential is connected.")

    monkeypatch.setattr("app.sync_jobs.load_pdb_credentials", missing_credential)
    job_id = _queue_component_job(session_factory, requested_by="operator@example.org")
    on_transient = _RecordingRetry()

    run_component_sync_job(
        session_factory,
        client.app.state.settings,
        lambda settings, institute, access_codes, report: FetchResult(records=[], skipped=0),
        job_id,
        None,
        on_transient,
    )

    assert on_transient.contexts == []


def test_the_retry_timer_uses_the_configured_delay(client, session_factory, monkeypatch):
    """The delay is real (no busy loop) and configurable, and shutdown cancels
    a pending timer so nothing fires into a torn-down app."""
    monkeypatch.setattr("app.sync_jobs.SYNC_AUTO_RETRY_DELAY_SECONDS", 42.0)
    manager = SyncJobManager(session_factory, client.app.state.settings)
    try:
        manager._schedule_retry(lambda: None)
        timer = manager._retry_timers[-1]
        assert timer.interval == 42.0
        assert timer.daemon is True
    finally:
        manager.shutdown()
    assert timer.finished.is_set()  # cancelled by shutdown, never fired


def test_the_automatic_retry_really_queues_a_second_job(
    client: TestClient, tmp_path, monkeypatch
):
    """End-to-end wiring through the real timer and executor: a transiently
    failed evidence job produces a second, durable, credential-owning job
    without anyone clicking. Only the positive outcome is awaited here; the
    cap itself is proven synchronously above.

    This intentionally uses file-backed SQLite. The timer and executor use
    genuinely concurrent sessions; an in-memory StaticPool gives all of them
    one sqlite3 connection and can fail with "cannot rollback - no transaction
    is active", which tests the fixture artifact rather than the job wiring.
    """
    monkeypatch.setattr("app.sync_jobs.sleep", lambda seconds: None)
    monkeypatch.setattr("app.sync_jobs.SYNC_AUTO_RETRY_DELAY_SECONDS", 0.0)
    client.app.state.settings.attachment_dir = str(tmp_path / "attachments")
    engine = make_engine(f"sqlite:///{tmp_path / 'automatic-retry.db'}")
    Base.metadata.create_all(engine)
    file_session_factory = make_session_factory(engine)
    institute = create_institute_profile(
        file_session_factory,
        code="TUDO",
        name="TU Dortmund",
        local_name_prefix="TUDO-",
    )
    user_id = create_account(
        file_session_factory,
        email="operator@example.org",
        password="test-password-123",
        role="operator",
        institute_id=institute["id"],
    )
    with file_session_factory() as session:
        save_pdb_credentials(
            session,
            user_id=user_id,
            access_codes=PdbAccessCodes("offline-code-1", "offline-code-2"),
            pdb_identity="offline-pdb-user",
            institutions=("TUDO",),
            encryption_key=client.app.state.settings.pdb_credential_encryption_key,
        )
        session.commit()
    _add_module(file_session_factory, "20USEM00000603")
    job_id = _queue_evidence_job(
        file_session_factory, requested_by="operator@example.org"
    )

    manager = SyncJobManager(
        file_session_factory,
        client.app.state.settings,
        evidence_gateway_factory=lambda settings, codes: _EvidenceGateway(_DownClient()),
    )
    try:
        manager.start_evidence(job_id)
        # Generous deadline: under a full-suite run every core is busy and the
        # timer thread plus the executor round-trip can take several seconds —
        # 8s flaked once on a loaded machine while passing in isolation.
        jobs = _wait_for(
            lambda: (lambda rows: rows if len(rows) == 2 else None)(
                _evidence_jobs(file_session_factory)
            ),
            timeout=30.0,
        )
    finally:
        manager.shutdown()
        # Production shutdown is intentionally non-blocking because an HTTP
        # read cannot be cancelled safely. This fake outage returns promptly,
        # so the test can join before disposing its temporary database and
        # guarantee no thread escapes into another test.
        manager._evidence_executor.shutdown(wait=True, cancel_futures=True)
        manager._component_executor.shutdown(wait=True, cancel_futures=True)
        engine.dispose()

    original, retry = jobs
    assert original.id == job_id and original.status == "failed"
    assert retry.requested_by.startswith("automatic retry")
    assert retry.user_id == original.user_id
    assert retry.institute_code == "TUDO"


def test_manager_start_evidence_passes_the_retry_hook(client, session_factory):
    class _RecordingExecutor:
        def __init__(self):
            self.call = None

        def submit(self, function, *args):
            self.call = (function, args)

    manager = SyncJobManager(session_factory, client.app.state.settings)
    manager.shutdown()
    executor = _RecordingExecutor()
    manager._evidence_executor = executor

    manager.start_evidence(77)

    function, args = executor.call
    assert function is run_evidence_sync_job
    assert args[3] == 77
    assert args[4] == manager._schedule_evidence_retry


def test_automatic_retry_converges_on_an_existing_manual_lease(
    client: TestClient, session_factory, tudo: dict, as_operator
):
    """If a person already queued a new sync, the automatic retry must join it
    instead of stacking a second job (single-flight lease stays authoritative)."""
    from app.models import InstituteProfile
    from app.sync_jobs import EvidenceSyncContext

    with session_factory() as session:
        user_id = session.scalar(select(User.id))
        manual = acquire_evidence_sync_lease(
            session,
            institute_code="TUDO",
            requested_by="operator@example.org",
            user_id=user_id,
        )
        institute = session.scalar(
            select(InstituteProfile).where(InstituteProfile.code == "TUDO")
        )
        session.expunge(institute)
    assert manual.created is True

    manager = SyncJobManager(session_factory, client.app.state.settings)
    started: list[int] = []
    manager.start_evidence = lambda job_id: started.append(job_id)
    try:
        manager._start_evidence_retry(
            EvidenceSyncContext(
                institute=institute,
                user_id=user_id,
                requested_by="operator@example.org",
            )
        )
    finally:
        manager.shutdown()

    assert started == []
    assert len(_evidence_jobs(session_factory)) == 1


def test_evidence_job_still_fails_honestly_when_a_component_never_answers(
    client: TestClient, session_factory, tudo: dict, as_operator, tmp_path, monkeypatch
):
    monkeypatch.setattr("app.sync_jobs.sleep", lambda seconds: None)
    client.app.state.settings.attachment_dir = str(tmp_path / "attachments")
    with session_factory() as session:
        session.add(
            Component(
                sn="20USEM00000302",
                component_type="MODULE",
                type_code="R5M0",
                stage="GLUED",
                location="TUDO",
                institute_code="TUDO",
            )
        )
        session.commit()

    manager = RecordingManager()
    client.app.state.sync_job_manager = manager
    job_id = client.post("/api/sync/jobs/evidence/TUDO").json()["id"]
    fake_client = _FlakyThenHealthyClient(failures_per_sn=99)

    run_evidence_sync_job(
        session_factory,
        client.app.state.settings,
        lambda settings, access_codes: _EvidenceGateway(fake_client),
        job_id,
    )

    assert client.get(f"/api/sync/jobs/{job_id}").json()["status"] == "failed"


def test_evidence_scope_covers_assembly_types_and_borrowed_components(
    client: TestClient, session_factory, tudo: dict, as_operator, tmp_path
):
    """The sweep must cover what the institute actually works on.

    Two real gaps found against production TUDO data: the default scope was
    MODULE-only although sensors, hybrids and flexes carry test runs (and the
    sensors carry most of the attachments), and the scope filtered on
    ownership although most components at an assembly site are owned by the
    sending institute and only located here.
    """
    client.app.state.settings.attachment_dir = str(tmp_path / "attachments")
    with session_factory() as session:
        session.add_all(
            [
                Component(
                    sn="20USEM00000401",
                    component_type="MODULE",
                    type_code="R5M0",
                    stage="GLUED",
                    location="TUDO",
                    institute_code="TUDO",
                ),
                # Owned by another institute, physically here: the common case.
                Component(
                    sn="20USES00000402",
                    component_type="SENSOR",
                    type_code="S",
                    stage="READY_FOR_MODULE",
                    location="TUDO",
                    institute_code="UCSC_STRIP_SENSORS",
                ),
                Component(
                    sn="20USEH00000403",
                    component_type="HYBRID_FLEX",
                    type_code="R5H0",
                    stage="ON_HYBRID",
                    location="TUDO",
                    institute_code="RAL",
                ),
                # Owned here but shipped away — not our evidence to mirror.
                Component(
                    sn="20USEM00000404",
                    component_type="MODULE",
                    type_code="R5M0",
                    stage="GLUED",
                    location="UNIFREIBURG",
                    institute_code="TUDO",
                ),
                # A type without test runs stays out of the default scope.
                Component(
                    sn="20USEG00000405",
                    component_type="GLUE",
                    type_code="G",
                    stage="IN_USE",
                    location="TUDO",
                    institute_code="TUDO",
                ),
            ]
        )
        session.commit()

    manager = RecordingManager()
    client.app.state.sync_job_manager = manager
    job_id = client.post("/api/sync/jobs/evidence/TUDO").json()["id"]
    fake_client = _EvidenceClient()

    run_evidence_sync_job(
        session_factory,
        client.app.state.settings,
        lambda settings, access_codes: _EvidenceGateway(fake_client),
        job_id,
    )

    assert sorted(fake_client.component_requests) == [
        "20USEH00000403",
        "20USEM00000401",
        "20USEM00000404",
        "20USES00000402",
    ]


def test_the_institute_profile_still_narrows_the_evidence_scope(
    client: TestClient, session_factory, tudo: dict, as_operator, tmp_path
):
    client.app.state.settings.attachment_dir = str(tmp_path / "attachments")
    with session_factory() as session:
        session.add_all(
            [
                Component(
                    sn="20USEM00000411",
                    component_type="MODULE",
                    type_code="R5M0",
                    stage="GLUED",
                    location="TUDO",
                    institute_code="TUDO",
                ),
                Component(
                    sn="20USES00000412",
                    component_type="SENSOR",
                    type_code="S",
                    stage="READY_FOR_MODULE",
                    location="TUDO",
                    institute_code="TUDO",
                ),
            ]
        )
        institute = session.scalar(select(InstituteProfile).where(InstituteProfile.code == "TUDO"))
        institute.settings = {**(institute.settings or {}), "evidence_component_types": ["MODULE"]}
        session.commit()

    client.app.state.sync_job_manager = RecordingManager()
    job_id = client.post("/api/sync/jobs/evidence/TUDO").json()["id"]
    fake_client = _EvidenceClient()
    run_evidence_sync_job(
        session_factory,
        client.app.state.settings,
        lambda settings, access_codes: _EvidenceGateway(fake_client),
        job_id,
    )
    assert fake_client.component_requests == ["20USEM00000411"]


# --- fast + outage-robust sweeps (docs/09) -----------------------------------


def _job_status(session_factory, job_id: int) -> str | None:
    with session_factory() as session:
        job = session.get(SyncJob, job_id)
        return job.status if job is not None else None


def test_component_and_evidence_jobs_run_on_separate_workers(
    client: TestClient, session_factory, tudo: dict, as_operator
):
    """A multi-hour evidence sweep must not starve a component sync: each job
    kind owns its own single worker (mirror writes stay serialized per kind,
    the durable active_key leases remain the single-flight guard)."""
    manager = SyncJobManager(session_factory, client.app.state.settings)
    release = Event()
    try:
        # Occupy the evidence worker the way a long institute sweep does.
        manager._evidence_executor.submit(lambda: release.wait(timeout=30))
        job_id = _queue_component_job(session_factory, requested_by="operator@example.org")
        manager.start(
            job_id,
            lambda settings, institute, access_codes, report: FetchResult(records=[], skipped=0),
        )
        _wait_for(lambda: _job_status(session_factory, job_id) == "succeeded")
    finally:
        release.set()
        manager.shutdown()


def test_component_followup_survives_restart_without_stealing_a_fresh_lease(
    client: TestClient,
    session_factory,
    tudo: dict,
    as_operator,
    tmp_path,
    monkeypatch,
):
    """The component commit, not its process-local callback, owns the rerun.

    This models the exact failure boundary: an older evidence snapshot already
    holds the canonical lease, the component mirror commits, and the process
    exits before its success callback can wake a successor. A new manager must
    leave the still-fresh foreign lease alone, then resume the durable component
    generation when that lease later crosses the existing heartbeat grace.
    """
    from app.sync_jobs import (
        EVIDENCE_FOLLOWUP_PENDING_KEY,
        SYNC_HEARTBEAT_GRACE,
    )

    client.app.state.settings.attachment_dir = str(tmp_path / "attachments")
    client.app.state.settings.sync_fetch_concurrency = 1
    old_sn = "20USEM00000741"
    new_sn = "20USEM00000742"

    old_evidence_id = _queue_evidence_job(
        session_factory, requested_by="operator@example.org"
    )
    old_snapshot_started = utcnow() - timedelta(minutes=1)
    with session_factory() as session:
        old_evidence = session.get(SyncJob, old_evidence_id)
        old_evidence.status = "running"
        old_evidence.phase = "fetching"
        old_evidence.started_at = old_snapshot_started
        old_evidence.updated_at = utcnow()
        session.commit()

    component_job_id = _queue_component_job(
        session_factory, requested_by="operator@example.org"
    )

    class _SimulatedProcessExit(BaseException):
        pass

    def exit_before_wakeup(institute_code, requested_by, user_id):
        raise _SimulatedProcessExit

    process_exited = False
    try:
        run_component_sync_job(
            session_factory,
            client.app.state.settings,
            lambda settings, institute, codes, report: FetchResult(
                records=[record(old_sn), record(new_sn)], skipped=0
            ),
            component_job_id,
            exit_before_wakeup,
        )
    except _SimulatedProcessExit:
        process_exited = True
    assert process_exited is True

    with session_factory() as session:
        component_job = session.get(SyncJob, component_job_id)
        old_evidence = session.get(SyncJob, old_evidence_id)
        assert component_job.status == "succeeded"
        assert component_job.result[EVIDENCE_FOLLOWUP_PENDING_KEY] is True
        assert old_evidence.status == "running"
        assert old_evidence.updated_at is not None
    # The private restart marker is an extra on a complete ComponentSyncOut and
    # never leaks through the public result union.
    public_result = client.get(f"/api/sync/jobs/{component_job_id}").json()["result"]
    assert EVIDENCE_FOLLOWUP_PENDING_KEY not in public_result
    latest_component_result = client.get(
        "/api/sync/jobs/latest", params={"kind": "components"}
    ).json()["result"]
    assert EVIDENCE_FOLLOWUP_PENDING_KEY not in latest_component_result

    scheduled: list = []
    monkeypatch.setattr(
        SyncJobManager,
        "_schedule_retry",
        lambda self, runner: scheduled.append(runner),
    )
    evidence_client = _EvidenceClient()
    manager = SyncJobManager(
        session_factory,
        client.app.state.settings,
        evidence_gateway_factory=lambda settings, codes: _EvidenceGateway(
            evidence_client
        ),
    )
    try:
        _wait_for(lambda: scheduled or None)
        with session_factory() as session:
            # Startup observed another process's fresh heartbeat. It neither
            # interrupted nor duplicated that canonical Evidence job.
            assert session.get(SyncJob, old_evidence_id).status == "running"
        assert len(_evidence_jobs(session_factory)) == 1
        manager._submit_followup_reconcile("TUDO")
        manager._submit_followup_reconcile("TUDO")
        _wait_for(lambda: len(scheduled) >= 3)
        assert len(_evidence_jobs(session_factory)) == 1
        active = client.get(
            "/api/sync/jobs/active",
            params={"kind": "evidence", "institute_code": "TUDO"},
        )
        assert active.json()["id"] == old_evidence_id

        with session_factory() as session:
            old_evidence = session.get(SyncJob, old_evidence_id)
            old_evidence.updated_at = utcnow() - SYNC_HEARTBEAT_GRACE - timedelta(
                seconds=1
            )
            session.commit()
        started: list[int] = []
        manager.start_evidence = lambda job_id: started.append(job_id)
        # Deterministically fire the manager's already-scheduled recheck. This
        # is the same process: no second restart is needed after grace elapses.
        scheduled.pop(0)()
        _wait_for(lambda: started or None)
        resumed_evidence_id = started[0]
        with session_factory() as session:
            assert session.get(SyncJob, old_evidence_id).status == "interrupted"
            assert session.get(SyncJob, resumed_evidence_id).status == "queued"
            component_job = session.get(SyncJob, component_job_id)
            assert component_job.result[EVIDENCE_FOLLOWUP_PENDING_KEY] is True
        # Run the claimed job synchronously: the test fixture deliberately uses
        # one in-memory SQLite connection, so concurrent writers would test
        # StaticPool transaction corruption rather than the durable state
        # machine under review.
        run_evidence_sync_job(
            session_factory,
            client.app.state.settings,
            lambda settings, codes: _EvidenceGateway(evidence_client),
            resumed_evidence_id,
        )
        manager._reconcile_evidence_followup("TUDO")
        jobs = _evidence_jobs(session_factory)
        assert len(jobs) == 2
        assert jobs[0].status == "interrupted"
        assert jobs[1].status == "succeeded"

        def followup_was_satisfied():
            with session_factory() as session:
                job = session.get(SyncJob, component_job_id)
                return (
                    job
                    if job.result[EVIDENCE_FOLLOWUP_PENDING_KEY] is False
                    else None
                )

        _wait_for(
            followup_was_satisfied,
            timeout=10.0,
        )
        # Replaying every duplicate startup/live-lease recheck is harmless once
        # the successful generation has cleared the durable pending bit.
        remaining_rechecks, scheduled[:] = list(scheduled), []
        for recheck in remaining_rechecks:
            recheck()
        manager._evidence_executor.submit(lambda: None).result(timeout=10)
        assert len(_evidence_jobs(session_factory)) == 2
    finally:
        manager.shutdown()

    with session_factory() as session:
        mirrored = sorted(session.scalars(select(TestRunEvidence.component_sn)))
        component_job = session.get(SyncJob, component_job_id)
        assert component_job.result[EVIDENCE_FOLLOWUP_PENDING_KEY] is False
    assert jobs[0].id == old_evidence_id
    assert mirrored == [old_sn, new_sn]
    assert evidence_client.component_requests == [old_sn, new_sn]


def _commit_pending_component_generation(
    session_factory, settings, component_sn: str
) -> int:
    job_id = _queue_component_job(
        session_factory, requested_by="operator@example.org"
    )
    run_component_sync_job(
        session_factory,
        settings,
        lambda settings, institute, codes, report: FetchResult(
            records=[record(component_sn)], skipped=0
        ),
        job_id,
        lambda institute_code, requested_by, user_id: None,
    )
    # Backdate the commit so the evidence attempt that follows unambiguously
    # starts *after* this generation. Every caller means "the component was
    # already committed when the evidence job was claimed", and coverage is
    # decided by a strict `started_at > finished_at` — deliberately, because
    # treating an ambiguous pair as covered would skip a sweep and lose data.
    # Windows resolves the clock to ~15.6 ms, so without this the two land in
    # one tick often enough to make these tests fail perhaps a third of the
    # time, on the correct behaviour. The precondition belongs in the fixture,
    # not in the clock.
    with session_factory() as session:
        job = session.get(SyncJob, job_id)
        backdated = job.finished_at - timedelta(seconds=5)
        job.finished_at = backdated
        job.updated_at = backdated
        session.commit()
    return job_id


def test_transient_covering_failure_retries_once_after_timer_is_lost_on_restart(
    client: TestClient,
    session_factory,
    tudo: dict,
    as_operator,
    tmp_path,
    monkeypatch,
):
    """The component result, not the process-local timer, owns retry state."""
    from app.sync_jobs import (
        EVIDENCE_FOLLOWUP_PENDING_KEY,
        EVIDENCE_FOLLOWUP_RETRY_KEY,
        FOLLOWUP_RETRY_DUE,
        FOLLOWUP_RETRY_EXHAUSTED,
    )

    monkeypatch.setattr("app.sync_jobs.sleep", lambda seconds: None)
    monkeypatch.setattr(
        SyncJobManager, "_resume_evidence_followups", lambda self: None
    )
    client.app.state.settings.attachment_dir = str(tmp_path / "attachments")
    client.app.state.settings.sync_evidence_strategy = "per_component"
    client.app.state.settings.sync_fetch_concurrency = 1
    component_id = _commit_pending_component_generation(
        session_factory, client.app.state.settings, "20USEM00000751"
    )
    original_id = _queue_evidence_job(
        session_factory, requested_by="operator@example.org"
    )
    lost_timer = _RecordingRetry()

    run_evidence_sync_job(
        session_factory,
        client.app.state.settings,
        lambda settings, codes: _EvidenceGateway(_DownClient()),
        original_id,
        lost_timer,
    )

    assert len(lost_timer.contexts) == 1  # process exits before invoking it
    with session_factory() as session:
        component_job = session.get(SyncJob, component_id)
        assert component_job.result[EVIDENCE_FOLLOWUP_PENDING_KEY] is True
        assert component_job.result[EVIDENCE_FOLLOWUP_RETRY_KEY] == FOLLOWUP_RETRY_DUE

    manager = SyncJobManager(session_factory, client.app.state.settings)
    started: list[int] = []
    delayed: list = []
    manager.start_evidence = lambda job_id: started.append(job_id)
    manager._schedule_retry = lambda runner: delayed.append(runner)
    try:
        # A fresh manager reconstructs the lost timer from the durable state.
        manager._reconcile_evidence_followup("TUDO")
        assert started == []
        assert len(delayed) == 1
        delayed.pop(0)()
        assert len(started) == 1
        retry_id = started[0]
        retry = _evidence_jobs(session_factory)[-1]
        assert retry.id == retry_id
        assert retry.requested_by.startswith("automatic retry")

        retry_requests = _RecordingRetry()
        run_evidence_sync_job(
            session_factory,
            client.app.state.settings,
            lambda settings, codes: _EvidenceGateway(_DownClient()),
            retry_id,
            retry_requests,
        )
        assert retry_requests.contexts == []
        with session_factory() as session:
            component_job = session.get(SyncJob, component_id)
            assert (
                component_job.result[EVIDENCE_FOLLOWUP_RETRY_KEY]
                == FOLLOWUP_RETRY_EXHAUSTED
            )

        # Exhaustion is durable too: repeated restart reconciliation cannot
        # produce a third evidence attempt.
        manager._reconcile_evidence_followup("TUDO")
        assert len(_evidence_jobs(session_factory)) == 2
        assert started == [retry_id]
    finally:
        manager.shutdown()

    public_result = client.get(f"/api/sync/jobs/{component_id}").json()["result"]
    assert EVIDENCE_FOLLOWUP_RETRY_KEY not in public_result


def test_non_transient_covering_failure_is_durably_blocked_not_retried(
    client: TestClient,
    session_factory,
    tudo: dict,
    as_operator,
    monkeypatch,
):
    from app.sync_jobs import (
        EVIDENCE_FOLLOWUP_RETRY_KEY,
        FOLLOWUP_RETRY_BLOCKED,
    )

    monkeypatch.setattr(
        SyncJobManager, "_resume_evidence_followups", lambda self: None
    )
    component_id = _commit_pending_component_generation(
        session_factory, client.app.state.settings, "20USEM00000752"
    )
    evidence_id = _queue_evidence_job(
        session_factory, requested_by="operator@example.org"
    )
    retries = _RecordingRetry()

    def broken_gateway(settings, codes):
        raise ValueError("broken adapter")

    run_evidence_sync_job(
        session_factory,
        client.app.state.settings,
        broken_gateway,
        evidence_id,
        retries,
    )
    assert retries.contexts == []

    manager = SyncJobManager(session_factory, client.app.state.settings)
    started: list[int] = []
    manager.start_evidence = lambda job_id: started.append(job_id)
    try:
        manager._reconcile_evidence_followup("TUDO")
    finally:
        manager.shutdown()

    with session_factory() as session:
        component_job = session.get(SyncJob, component_id)
        assert component_job.result[EVIDENCE_FOLLOWUP_RETRY_KEY] == FOLLOWUP_RETRY_BLOCKED
    assert started == []
    assert len(_evidence_jobs(session_factory)) == 1


def test_rejected_evidence_submit_releases_lease_and_unwatches_job(
    client: TestClient,
    session_factory,
    tudo: dict,
    as_operator,
    monkeypatch,
):
    monkeypatch.setattr(
        SyncJobManager, "_resume_evidence_followups", lambda self: None
    )
    _commit_pending_component_generation(
        session_factory, client.app.state.settings, "20USEM00000753"
    )
    manager = SyncJobManager(session_factory, client.app.state.settings)
    manager._evidence_executor.shutdown(wait=True, cancel_futures=True)

    class _RejectingExecutor:
        def submit(self, function, *args):
            raise RuntimeError("executor rejected submit")

        def shutdown(self, wait=True, *, cancel_futures=False):
            return None

    manager._evidence_executor = _RejectingExecutor()
    with session_factory() as session:
        user_id = session.scalar(select(User.id))
    assert user_id is not None
    rejected = False
    try:
        manager.enqueue_evidence("TUDO", "operator@example.org", user_id)
    except RuntimeError:
        rejected = True
    assert rejected is True

    failed = _evidence_jobs(session_factory)[0]
    assert failed.status == "failed"
    assert failed.active_key is None
    assert failed.id not in manager._queued_watch

    # The released lease lets the still-pending component marker reconcile to
    # a replacement instead of converging forever on a never-run queued job.
    started: list[int] = []
    manager.start_evidence = lambda job_id: started.append(job_id)
    try:
        manager._reconcile_evidence_followup("TUDO")
    finally:
        manager.shutdown()
    assert len(started) == 1
    assert len(_evidence_jobs(session_factory)) == 2


def test_a_queued_job_waiting_for_its_worker_is_kept_heartbeat_fresh(
    client: TestClient, session_factory, tudo: dict, as_operator
):
    """Institute B's evidence job can queue behind institute A's sweep for
    hours. While the owning process is alive its heartbeat must stay fresh, or
    the three-minute grace lets lease takeover / startup recovery close a job
    that is merely waiting for its worker."""
    from datetime import timedelta

    from app.sync_jobs import _job_heartbeat_stale

    manager = SyncJobManager(session_factory, client.app.state.settings)
    release = Event()
    try:
        manager._evidence_executor.submit(lambda: release.wait(timeout=30))
        job_id = _queue_evidence_job(session_factory, requested_by="operator@example.org")
        manager.start_evidence(job_id)
        assert manager._watch_thread is not None and manager._watch_thread.daemon

        # Simulate a long wait behind the busy worker.
        with session_factory() as session:
            job = session.get(SyncJob, job_id)
            assert job.status == "queued"
            job.updated_at = utcnow() - timedelta(hours=1)
            session.commit()

        manager._refresh_queued_heartbeats()

        with session_factory() as session:
            job = session.get(SyncJob, job_id)
            assert job.status == "queued"
            assert not _job_heartbeat_stale(job)
    finally:
        release.set()
        manager.shutdown()


class _BarrierClient(_EvidenceClient):
    """Proves overlap: getComponent blocks until N calls are in flight."""

    def __init__(self, barrier: Barrier):
        super().__init__()
        self._barrier = barrier

    def get(self, action, json=None):
        if action == "getComponent":
            self._barrier.wait(timeout=10)
        return super().get(action, json=json)


def test_evidence_fetches_run_concurrently_with_one_gateway_per_worker(
    client: TestClient, session_factory, tudo: dict, as_operator, tmp_path
):
    client.app.state.settings.attachment_dir = str(tmp_path / "attachments")
    client.app.state.settings.sync_fetch_concurrency = 3
    for index in range(1, 4):
        _add_module(session_factory, f"20USEM0000070{index}")
    client.app.state.sync_job_manager = RecordingManager()
    job_id = client.post("/api/sync/jobs/evidence/TUDO").json()["id"]

    barrier = Barrier(3)
    gateways: list[_EvidenceGateway] = []

    def gateway_factory(settings, access_codes):
        assert access_codes.access_code1.startswith("offline-code-1-user-")
        gateway = _EvidenceGateway(_BarrierClient(barrier))
        gateways.append(gateway)
        return gateway

    run_evidence_sync_job(
        session_factory, client.app.state.settings, gateway_factory, job_id
    )

    status = client.get(f"/api/sync/jobs/{job_id}").json()
    assert status["status"] == "succeeded", status["error"]
    with session_factory() as session:
        mirrored = sorted(session.scalars(select(TestRunEvidence.component_sn)))
    assert mirrored == ["20USEM00000701", "20USEM00000702", "20USEM00000703"]
    # The barrier only opens when three getComponent calls are in flight at
    # once, and itkdb clients are not thread-safe: every fetch worker must
    # build its own gateway instead of sharing one requests.Session.
    assert len(gateways) >= 3


def test_fetch_concurrency_one_keeps_the_serial_single_gateway_sweep(
    client: TestClient, session_factory, tudo: dict, as_operator, tmp_path
):
    client.app.state.settings.attachment_dir = str(tmp_path / "attachments")
    client.app.state.settings.sync_fetch_concurrency = 1
    for index in range(1, 3):
        _add_module(session_factory, f"20USEM0000071{index}")
    client.app.state.sync_job_manager = RecordingManager()
    job_id = client.post("/api/sync/jobs/evidence/TUDO").json()["id"]
    fake_client = _EvidenceClient()
    factory_calls = []

    def gateway_factory(settings, access_codes):
        factory_calls.append(1)
        return _EvidenceGateway(fake_client)

    run_evidence_sync_job(
        session_factory, client.app.state.settings, gateway_factory, job_id
    )

    assert client.get(f"/api/sync/jobs/{job_id}").json()["status"] == "succeeded"
    assert len(factory_calls) == 1
    assert fake_client.component_requests == ["20USEM00000711", "20USEM00000712"]


class _OneDeadComponentClient(_EvidenceClient):
    """One serial number never answers; everything else serves normally."""

    def __init__(self, dead_sn: str):
        super().__init__()
        self._dead_sn = dead_sn

    def get(self, action, json=None):
        if action == "getComponent" and json["component"] == self._dead_sn:
            raise ConnectionResetError("Connection reset by peer")
        return super().get(action, json=json)


def test_parallel_fetch_commits_finished_components_and_fails_transiently(
    client: TestClient, session_factory, tudo: dict, as_operator, tmp_path, monkeypatch
):
    """Fetch results are consumed in submission order: everything committed
    before the dead component stays mirrored, nothing after it is
    half-committed, and the job fails transiently so the existing single
    automatic retry takes over."""
    monkeypatch.setattr("app.sync_jobs.sleep", lambda seconds: None)
    client.app.state.settings.attachment_dir = str(tmp_path / "attachments")
    client.app.state.settings.sync_fetch_concurrency = 2
    for index in range(1, 4):
        _add_module(session_factory, f"20USEM0000072{index}")
    job_id = _queue_evidence_job(session_factory, requested_by="operator@example.org")
    on_transient = _RecordingRetry()

    run_evidence_sync_job(
        session_factory,
        client.app.state.settings,
        lambda settings, codes: _EvidenceGateway(_OneDeadComponentClient("20USEM00000722")),
        job_id,
        on_transient,
    )

    with session_factory() as session:
        assert session.get(SyncJob, job_id).status == "failed"
        mirrored = sorted(session.scalars(select(TestRunEvidence.component_sn)))
    assert mirrored == ["20USEM00000721"]
    assert len(on_transient.contexts) == 1
    assert on_transient.contexts[0].auto_retry is False


def test_parallel_fetch_joins_running_workers_before_job_returns(
    client: TestClient, session_factory, tudo: dict, as_operator, tmp_path, monkeypatch
):
    """A failed future must not orphan a sibling PDB read behind the job."""
    import app.sync_jobs as sync_jobs_module

    monkeypatch.setattr("app.sync_jobs.sleep", lambda seconds: None)
    monkeypatch.setattr("app.sync_jobs.PARALLEL_FETCH_HEARTBEAT_SECONDS", 0.05)
    client.app.state.settings.attachment_dir = str(tmp_path / "attachments")
    client.app.state.settings.sync_evidence_strategy = "per_component"
    client.app.state.settings.sync_fetch_concurrency = 2
    client.app.state.settings.sync_page_max_attempts = 1
    dead_sn = "20USEM00000741"
    blocked_sn = "20USEM00000742"
    _add_module(session_factory, dead_sn)
    _add_module(session_factory, blocked_sn)
    job_id = _queue_evidence_job(session_factory, requested_by="operator@example.org")

    blocked_started = Event()
    dead_failed = Event()
    release_blocked = Event()
    pool_shutdown_returned = Event()
    job_returned = Event()
    join_heartbeat = Event()
    active_blocked_fetches = [0]

    class _ObservedExecutor(ThreadPoolExecutor):
        def shutdown(self, wait=True, *, cancel_futures=False):
            result = super().shutdown(wait=wait, cancel_futures=cancel_futures)
            pool_shutdown_returned.set()
            return result

    monkeypatch.setattr(sync_jobs_module, "ThreadPoolExecutor", _ObservedExecutor)
    real_update = sync_jobs_module._update_progress

    def spy(spy_factory, spy_job_id, phase, current, total, *, message=None):
        if message and "stopping in-flight" in message.lower():
            join_heartbeat.set()
        real_update(spy_factory, spy_job_id, phase, current, total, message=message)

    monkeypatch.setattr(sync_jobs_module, "_update_progress", spy)

    class _OneDeadOneBlockedClient:
        def get(self, action, json=None):
            assert action == "getComponent"
            sn = json["component"]
            if sn == dead_sn:
                assert blocked_started.wait(timeout=5)
                dead_failed.set()
                raise ConnectionResetError("Connection reset by peer")
            assert sn == blocked_sn
            active_blocked_fetches[0] += 1
            blocked_started.set()
            try:
                assert release_blocked.wait(timeout=10)
            finally:
                active_blocked_fetches[0] -= 1
            return {"tests": []}

    def run_job() -> None:
        try:
            run_evidence_sync_job(
                session_factory,
                client.app.state.settings,
                lambda settings, codes: _EvidenceGateway(_OneDeadOneBlockedClient()),
                job_id,
            )
        finally:
            job_returned.set()

    runner = Thread(target=run_job, daemon=True)
    runner.start()
    try:
        assert blocked_started.wait(timeout=5)
        assert dead_failed.wait(timeout=5)
        assert join_heartbeat.wait(timeout=5)
        shutdown_returned_early = pool_shutdown_returned.wait(timeout=0.5)
        job_returned_early = job_returned.is_set()
        active_before_release = active_blocked_fetches[0]
    finally:
        release_blocked.set()
        runner.join(timeout=10)

    assert shutdown_returned_early is False
    assert job_returned_early is False
    assert active_before_release == 1
    assert not runner.is_alive()
    assert pool_shutdown_returned.is_set()
    assert job_returned.is_set()
    assert join_heartbeat.is_set()
    assert active_blocked_fetches[0] == 0
    with session_factory() as session:
        assert session.get(SyncJob, job_id).status == "failed"


def test_parallel_fetch_heartbeats_while_waiting_on_slow_reads(
    client: TestClient, session_factory, tudo: dict, as_operator, tmp_path, monkeypatch
):
    """A pool wait must never go quiet longer than the heartbeat interval: the
    retry ladders now run inside fetch workers, which cannot write the durable
    heartbeat themselves (all database writes stay on the job thread)."""
    import app.sync_jobs as sync_jobs_module

    monkeypatch.setattr("app.sync_jobs.PARALLEL_FETCH_HEARTBEAT_SECONDS", 0.05)
    client.app.state.settings.attachment_dir = str(tmp_path / "attachments")
    client.app.state.settings.sync_fetch_concurrency = 2
    _add_module(session_factory, "20USEM00000731")
    client.app.state.sync_job_manager = RecordingManager()
    job_id = client.post("/api/sync/jobs/evidence/TUDO").json()["id"]
    heartbeats: list[str] = []

    class _SlowClient(_EvidenceClient):
        def get(self, action, json=None):
            if action == "getComponent":
                time.sleep(0.4)
            return super().get(action, json=json)

    real_update = sync_jobs_module._update_progress

    def spy(spy_factory, spy_job_id, phase, current, total, *, message=None):
        if message and "waiting" in message.lower():
            heartbeats.append(message)
        real_update(spy_factory, spy_job_id, phase, current, total, message=message)

    monkeypatch.setattr("app.sync_jobs._update_progress", spy)

    run_evidence_sync_job(
        session_factory,
        client.app.state.settings,
        lambda settings, codes: _EvidenceGateway(_SlowClient()),
        job_id,
    )

    assert client.get(f"/api/sync/jobs/{job_id}").json()["status"] == "succeeded"
    assert heartbeats, "no heartbeat was written while the pool wait was pending"


class _AttachmentOutageClient(_EvidenceClient):
    """Evidence phase serves fine; every attachment byte-fetch dies
    network-shaped, exactly like an outage that begins mid-sweep."""

    def __init__(self):
        super().__init__()
        self.attachment_attempts = 0

    def get(self, action, json=None):
        if action in ("getTestRunAttachment", "uu-app-binarystore/getBinaryData"):
            self.attachment_attempts += 1
            raise ConnectionResetError("Connection reset by peer")
        return super().get(action, json=json)


def test_an_attachment_outage_fails_the_job_transiently_instead_of_crawling(
    client: TestClient, session_factory, tudo: dict, as_operator, tmp_path, monkeypatch
):
    """During an outage each remaining file burns a full transient-retry
    ladder (minutes each, at zero progress). After the breaker threshold of
    consecutive transient file failures the phase must stop and the job must
    fail transiently — handing over to the single automatic retry — while
    everything already mirrored stays committed."""
    from app.attachment_store import ATTACHMENT_OUTAGE_BREAKER_THRESHOLD

    monkeypatch.setattr("app.sync_jobs.sleep", lambda seconds: None)
    monkeypatch.setattr("app.attachment_store.sleep", lambda seconds: None)
    client.app.state.settings.attachment_dir = str(tmp_path / "attachments")
    for index in range(1, 9):
        _add_module(session_factory, f"20USEM0000080{index}")
    job_id = _queue_evidence_job(session_factory, requested_by="operator@example.org")
    on_transient = _RecordingRetry()
    shared = _AttachmentOutageClient()

    run_evidence_sync_job(
        session_factory,
        client.app.state.settings,
        lambda settings, codes: _EvidenceGateway(shared),
        job_id,
        on_transient,
    )

    with session_factory() as session:
        job = session.get(SyncJob, job_id)
        evidence_count = session.scalar(select(func.count(TestRunEvidence.id)))
        job_status, job_error = job.status, job.error
    assert job_status == "failed"
    assert "attachment" in (job_error or "").lower()
    assert evidence_count == 8  # every fetched run stays committed
    # Transient failure: the automatic retry takes over instead of a click.
    assert len(on_transient.contexts) == 1
    assert on_transient.contexts[0].auto_retry is False
    # The phase stopped after the breaker threshold, not after all 8 files.
    expected_attempts = (
        ATTACHMENT_OUTAGE_BREAKER_THRESHOLD
        * client.app.state.settings.sync_page_max_attempts
        * 2  # two download routes per attempt
    )
    assert shared.attachment_attempts == expected_attempts


class _MissingAttachmentClient(_EvidenceClient):
    """Attachment routes answer with an HTML page: permanent per-file misses."""

    def get(self, action, json=None):
        if action in ("getTestRunAttachment", "uu-app-binarystore/getBinaryData"):

            class _BinaryFile:
                content = b"<html><body>sign in</body></html>"
                mimetype = "text/html"

            return _BinaryFile()
        return super().get(action, json=json)


def test_permanent_attachment_failures_stay_best_effort_per_file(
    client: TestClient, session_factory, tudo: dict, as_operator, tmp_path
):
    client.app.state.settings.attachment_dir = str(tmp_path / "attachments")
    for index in range(1, 9):
        _add_module(session_factory, f"20USEM0000081{index}")
    job_id = _queue_evidence_job(session_factory, requested_by="operator@example.org")
    on_transient = _RecordingRetry()

    run_evidence_sync_job(
        session_factory,
        client.app.state.settings,
        lambda settings, codes: _EvidenceGateway(_MissingAttachmentClient()),
        job_id,
        on_transient,
    )

    with session_factory() as session:
        job = session.get(SyncJob, job_id)
        job_status, job_result = job.status, job.result
    assert job_status == "succeeded"
    assert job_result["attachments_failed"] == 8
    assert on_transient.contexts == []


def test_the_attachment_plan_is_computed_once_per_component(
    client: TestClient, session_factory, tudo: dict, as_operator, tmp_path, monkeypatch
):
    """The old sweep loaded every component's evidence payloads twice — one
    whole-scope counting pass in a single session, then again per download.
    The plan is now computed once, in short-lived sessions, and drives both
    the total and the downloads."""
    client.app.state.settings.attachment_dir = str(tmp_path / "attachments")
    for index in range(1, 4):
        _add_module(session_factory, f"20USEM0000082{index}")
    client.app.state.sync_job_manager = RecordingManager()
    job_id = client.post("/api/sync/jobs/evidence/TUDO").json()["id"]

    from app import attachment_store as store

    calls: dict[str, int] = {}
    real_pending = store.pending_attachments

    def counting(session, component_sn):
        calls[component_sn] = calls.get(component_sn, 0) + 1
        return real_pending(session, component_sn)

    monkeypatch.setattr("app.attachment_store.pending_attachments", counting)
    monkeypatch.setattr("app.sync_jobs.pending_attachments", counting)

    run_evidence_sync_job(
        session_factory,
        client.app.state.settings,
        lambda settings, codes: _EvidenceGateway(_EvidenceClient()),
        job_id,
    )

    status = client.get(f"/api/sync/jobs/{job_id}").json()
    assert status["status"] == "succeeded"
    assert status["result"]["attachments_total"] == 3
    assert calls == {f"20USEM0000082{index}": 1 for index in range(1, 4)}


def test_a_timestamp_tie_still_records_a_due_retry(session_factory, tudo: dict):
    """A clock-resolution tie must never cost the durable retry intent.

    `_timestamp_after` is strict on purpose: for the *coverage* question, a tie
    should mean "not covered" so the component is swept again. But the same
    helper also gates writing the retry verdict onto the component job, and
    there a tie meant the key was never written at all. An absent key is not
    `due`, and `_reconcile_evidence_followup` returns without scheduling
    anything — so a transiently failed follow-up was silently dropped until a
    person pressed sync.

    The tie is reachable in practice: Windows' system clock granularity is
    ~15.6 ms, and a component sync that commits immediately before its evidence
    follow-up is claimed lands both timestamps inside one tick. This is how it
    was found — as a "flaky" full-suite failure that reproduced nowhere else.
    """
    from app.sync_jobs import (
        EVIDENCE_FOLLOWUP_PENDING_KEY,
        EVIDENCE_FOLLOWUP_RETRY_KEY,
        FOLLOWUP_RETRY_DUE,
        fail_sync_job,
    )

    tie = utcnow().replace(microsecond=0)
    with session_factory() as session:
        component = SyncJob(
            kind="components",
            institute_code="TUDO",
            status="succeeded",
            phase="complete",
            current=1,
            total=1,
            percent=100.0,
            message="Component sync completed.",
            result={"institute_code": "TUDO", EVIDENCE_FOLLOWUP_PENDING_KEY: True},
            requested_by="operator@example.org",
            user_id=None,
            active_key=None,
            created_at=tie,
            started_at=tie,
            updated_at=tie,
            finished_at=tie,
        )
        evidence = SyncJob(
            kind="evidence",
            institute_code="TUDO",
            status="running",
            phase="fetching",
            current=0,
            total=None,
            percent=None,
            message="Fetching detailed evidence.",
            requested_by="operator@example.org",
            user_id=None,
            active_key="evidence:TUDO",
            created_at=tie,
            # Exactly the component's finished_at — the tie under test.
            started_at=tie,
            updated_at=tie,
        )
        session.add_all([component, evidence])
        session.commit()
        component_id, evidence_id = component.id, evidence.id

    fail_sync_job(
        session_factory,
        evidence_id,
        "PDB unreachable",
        followup_retry_state=FOLLOWUP_RETRY_DUE,
    )

    with session_factory() as session:
        result = session.get(SyncJob, component_id).result
        assert result[EVIDENCE_FOLLOWUP_PENDING_KEY] is True
        assert result[EVIDENCE_FOLLOWUP_RETRY_KEY] == FOLLOWUP_RETRY_DUE
