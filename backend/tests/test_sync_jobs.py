import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

from authutil import create_account, create_institute_profile
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text

from app.db import Base, make_engine, make_session_factory
from app.models import Component, SyncJob, TestRunAttachment, TestRunEvidence, User, utcnow
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
    manager._executor.shutdown(wait=False)
    executor = _RecordingExecutor()
    manager._executor = executor

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


def test_evidence_job_transient_failure_schedules_one_automatic_retry(
    client: TestClient, session_factory, tudo: dict, as_operator, tmp_path, monkeypatch
):
    """A short outage must not leave the evidence mirror waiting for a human
    click — and the automatic retry must never loop."""
    monkeypatch.setattr("app.sync_jobs.sleep", lambda seconds: None)
    monkeypatch.setattr("app.sync_jobs.SYNC_AUTO_RETRY_DELAY_SECONDS", 0.0)
    client.app.state.settings.attachment_dir = str(tmp_path / "attachments")
    _add_module(session_factory, "20USEM00000601")
    client.app.state.sync_job_manager = RecordingManager()
    job_id = client.post("/api/sync/jobs/evidence/TUDO").json()["id"]

    class _DownGateway:
        is_configured = True

        def client(self):
            raise PdbSyncUnavailable("unused")

    class _DownClient:
        def get(self, action, json=None):
            raise ConnectionResetError("Connection reset by peer")

    manager = SyncJobManager(
        session_factory,
        client.app.state.settings,
        evidence_gateway_factory=lambda settings, codes: _EvidenceGateway(_DownClient()),
    )
    try:
        manager.start_evidence(job_id)

        jobs = _wait_for(
            lambda: (
                lambda rows: rows
                if len(rows) == 2 and all(job.status == "failed" for job in rows)
                else None
            )(_evidence_jobs(session_factory))
        )
        original, retry = jobs
        assert original.id == job_id
        assert retry.requested_by.startswith("automatic retry")
        assert retry.user_id == original.user_id
        assert retry.institute_code == "TUDO"

        # Bounded: the failed automatic retry must not spawn a third attempt.
        time.sleep(0.3)
        assert len(_evidence_jobs(session_factory)) == 2
    finally:
        manager.shutdown()


def test_component_job_transient_failure_schedules_one_automatic_retry(
    client: TestClient, session_factory, tudo: dict, as_operator, monkeypatch
):
    monkeypatch.setattr("app.sync_jobs.SYNC_AUTO_RETRY_DELAY_SECONDS", 0.0)
    client.app.state.sync_job_manager = RecordingManager()
    job_id = client.post("/api/sync/jobs/components/TUDO").json()["id"]

    def outage_fetcher(settings, institute, access_codes, report):
        raise PdbSyncUnavailable("PDB component page 1 failed (transient network error).")

    manager = SyncJobManager(session_factory, client.app.state.settings)
    try:
        manager.start(job_id, outage_fetcher)

        jobs = _wait_for(
            lambda: (
                lambda rows: rows
                if len(rows) == 2 and all(job.status == "failed" for job in rows)
                else None
            )(_component_jobs(session_factory))
        )
        original, retry = jobs
        assert original.id == job_id
        assert retry.requested_by.startswith("automatic retry")
        assert retry.user_id == original.user_id

        time.sleep(0.3)
        assert len(_component_jobs(session_factory)) == 2
    finally:
        manager.shutdown()


def test_permanent_component_failure_does_not_schedule_a_retry(
    client: TestClient, session_factory, tudo: dict, as_operator, monkeypatch
):
    """A bug or data problem will not fix itself in sixty seconds; only
    connectivity-shaped (Pdb*Unavailable) failures earn the automatic retry."""
    monkeypatch.setattr("app.sync_jobs.SYNC_AUTO_RETRY_DELAY_SECONDS", 0.0)
    client.app.state.sync_job_manager = RecordingManager()
    job_id = client.post("/api/sync/jobs/components/TUDO").json()["id"]

    def broken_fetcher(settings, institute, access_codes, report):
        raise RuntimeError("mapping bug")

    manager = SyncJobManager(session_factory, client.app.state.settings)
    try:
        manager.start(job_id, broken_fetcher)
        _wait_for(
            lambda: any(job.status == "failed" for job in _component_jobs(session_factory))
        )
        time.sleep(0.3)
        assert len(_component_jobs(session_factory)) == 1
    finally:
        manager.shutdown()


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
