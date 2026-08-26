from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import Component, TestRunAttachment
from app.pdb_test_evidence import fetch_test_run_evidence
from app.stage_service import satisfied_test_results

COMPONENT = {
    "serialNumber": "20USEM00000001",
    "tests": [
        {
            "testType": {"code": "MODULE_METROLOGY"},
            "testRuns": [{"id": "R1", "passed": True, "date": "2026-02-08T15:15:39Z"}],
        },
        {
            "testType": "MODULE_BOW",
            "testRuns": [
                {"id": "R2", "passed": False, "date": "2026-02-01T00:00:00Z"},
                {"id": "R3", "problems": False, "date": "2026-03-01T00:00:00Z"},  # later, passes
            ],
        },
    ],
}


class _FakeClient:
    def __init__(self, component):
        self._component = component

    def get(self, action, json=None):
        assert action == "getComponent"
        return self._component


class _FakeGateway:
    def __init__(self, configured=True, component=None):
        self.is_configured = configured
        self._client = _FakeClient(component)

    def client(self):
        return self._client


def test_fetch_maps_test_runs_to_evidence():
    records = fetch_test_run_evidence(_FakeGateway(component=COMPONENT), "20USEM00000001")
    by_ref = {r.external_ref: r for r in records}
    assert set(by_ref) == {"R1", "R2", "R3"}
    assert by_ref["R1"].test_type == "MODULE_METROLOGY" and by_ref["R1"].passed is True
    assert by_ref["R2"].passed is False
    assert by_ref["R3"].passed is True  # problems=False -> passed
    assert all(r.source == "pdb" for r in records)


def test_fetch_empty_when_not_configured():
    assert fetch_test_run_evidence(_FakeGateway(configured=False, component=COMPONENT), "X") == []


def test_sync_evidence_endpoint_populates_and_feeds_stage_engine(
    client: TestClient, session_factory, tudo, as_operator
):
    with session_factory() as session:
        session.add(_module("20USEM00000001"))
        session.commit()
    client.app.state.pdb_gateway = _FakeGateway(component=COMPONENT)
    resp = client.post("/api/components/20USEM00000001/sync-evidence").json()
    assert resp["created"] == 3
    assert resp["component_sn"] == "20USEM00000001"

    with session_factory() as session:
        results = satisfied_test_results(session, "20USEM00000001")
    assert results["MODULE_METROLOGY"] is True
    assert results["MODULE_BOW"] is True  # latest run (R3) passed

    # Re-syncing the same runs is idempotent (by source + external_ref).
    again = client.post("/api/components/20USEM00000001/sync-evidence").json()
    assert again["created"] == 0 and again["unchanged"] == 3


def test_sync_evidence_endpoint_reports_a_missing_connection(
    client: TestClient, session_factory, tudo, as_operator
):
    """Without a PDB connection this must say so, not report a successful zero.

    "created: 0" is indistinguishable from "this module genuinely has no test
    runs", which is how a whole institute ends up looking like every required
    test is missing.
    """
    with session_factory() as session:
        session.add(_module("20USEM00000001"))
        session.commit()
    client.app.state.pdb_gateway = _FakeGateway(configured=False, component=COMPONENT)
    response = client.post("/api/components/20USEM00000001/sync-evidence")

    assert response.status_code == 503
    assert "PDB" in response.json()["detail"]


class _AttachmentClient:
    def get(self, action, json=None):
        if action == "getComponent":
            return {
                "tests": [
                    {
                        "testType": {"code": "VISUAL_INSPECTION"},
                        "testRuns": [{"id": "RUN-ATT", "passed": True}],
                    }
                ]
            }
        if action == "getTestRun":
            assert json == {"testRun": "RUN-ATT", "noEosToken": True}
            return {
                "attachments": [
                    {
                        "code": "image-code",
                        "filename": "inspection.jpg",
                        "contentType": "image/jpeg",
                        "type": "file",
                    }
                ]
            }
        if action == "getTestRunAttachment":
            assert json == {"code": "image-code", "testRun": "RUN-ATT"}

            class _BinaryFile:
                content = b"\xff\xd8\xff itkflow"
                mimetype = "image/jpeg"

            return _BinaryFile()
        raise AssertionError(f"unexpected request {action}")


def test_component_evidence_sync_also_downloads_attachments(
    client: TestClient, session_factory, tudo, as_operator, tmp_path
):
    with session_factory() as session:
        session.add(_module("20USEM00000001"))
        session.commit()
    client.app.state.settings.attachment_dir = str(tmp_path / "attachments")
    client.app.state.pdb_gateway = _FakeGateway(component=COMPONENT)
    client.app.state.pdb_gateway._client = _AttachmentClient()

    response = client.post("/api/components/20USEM00000001/sync-evidence")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["attachments_downloaded"] == 1
    assert body["attachments_failed"] == 0
    with session_factory() as session:
        row = session.scalar(select(TestRunAttachment))
        assert row is not None and row.relative_path.endswith("image-code.jpg")
        assert (tmp_path / "attachments" / row.relative_path).is_file()

    again = client.post("/api/components/20USEM00000001/sync-evidence").json()
    assert again["attachments_downloaded"] == 0
    assert again["attachments_reused"] == 1


class _MultiClient:
    def __init__(self, by_sn):
        self._by_sn = by_sn

    def get(self, action, json=None):
        assert action == "getComponent"
        return self._by_sn.get(json["component"], {})


class _MultiGateway:
    def __init__(self, by_sn):
        self.is_configured = True
        self._client = _MultiClient(by_sn)

    def client(self):
        return self._client


def _module(sn: str) -> Component:
    return Component(
        sn=sn, component_type="MODULE", type_code="R0", stage="GLUED",
        location="TUDO", institute_code="TUDO",
    )


def test_institute_evidence_sync_covers_only_live_modules(
    client: TestClient, session_factory, tudo, as_operator
):
    with session_factory() as session:
        session.add(_module("20USEM00000001"))
        session.add(_module("20USEM00000002"))
        trashed = _module("20USEM00000003")
        trashed.trashed = True
        session.add(trashed)  # skipped
        session.add(  # non-module skipped
            Component(sn="20USES00000001", component_type="SENSOR", type_code="X",
                      stage="X", location="TUDO", institute_code="TUDO")
        )
        session.commit()

    by_sn = {
        "20USEM00000001": {"tests": [{"testType": {"code": "MODULE_BOW"},
                                      "testRuns": [{"id": "a", "passed": True}]}]},
        "20USEM00000002": {"tests": [{"testType": {"code": "MODULE_BOW"},
                                      "testRuns": [{"id": "b", "passed": True}]}]},
    }
    client.app.state.pdb_gateway = _MultiGateway(by_sn)
    resp = client.post("/api/sync/evidence/TUDO").json()
    assert resp["components_processed"] == 2  # only the two live modules
    assert resp["created"] == 2

    with session_factory() as session:
        assert satisfied_test_results(session, "20USEM00000001")["MODULE_BOW"] is True
        assert satisfied_test_results(session, "20USEM00000002")["MODULE_BOW"] is True


class _CountingDetailClient:
    """getComponent plus a per-run getTestRun counter for incremental tests."""

    def __init__(self, component):
        self._component = component
        self.detail_calls = []

    def get(self, action, json=None):
        if action == "getComponent":
            return self._component
        if action == "getTestRun":
            self.detail_calls.append(json["testRun"])
            return {"runNumber": f"run-{json['testRun']}"}
        raise AssertionError(f"unexpected request {action}")


def _known_flat(records):
    from app.pdb_test_evidence import flat_fingerprint

    return {
        r.external_ref: flat_fingerprint(
            passed=r.passed,
            measured_at=r.measured_at,
            state=(r.payload or {}).get("state"),
            problems=(r.payload or {}).get("problems"),
        )
        for r in records
    }


def test_detail_fetch_skips_runs_whose_flat_state_is_already_mirrored():
    gateway = _FakeGateway(component=COMPONENT)
    counting = _CountingDetailClient(COMPONENT)
    gateway._client = counting

    first = fetch_test_run_evidence(gateway, "20USEM00000001", with_detail=True)
    assert sorted(counting.detail_calls) == ["R1", "R2", "R3"]
    assert all(r.payload.get("detail_synced") is True for r in first)
    assert all(not r.detail_omitted for r in first)

    counting.detail_calls.clear()
    second = fetch_test_run_evidence(
        gateway, "20USEM00000001", with_detail=True, known_flat=_known_flat(first)
    )
    assert counting.detail_calls == []
    assert {r.external_ref for r in second} == {"R1", "R2", "R3"}
    assert all(r.detail_omitted for r in second)


def test_detail_fetch_refetches_a_run_whose_flat_state_changed():
    import copy

    gateway = _FakeGateway(component=COMPONENT)
    counting = _CountingDetailClient(COMPONENT)
    gateway._client = counting
    first = fetch_test_run_evidence(gateway, "20USEM00000001", with_detail=True)

    changed = copy.deepcopy(COMPONENT)
    changed["tests"][0]["testRuns"][0]["passed"] = False  # R1 flips
    counting._component = changed
    counting.detail_calls.clear()

    second = fetch_test_run_evidence(
        gateway, "20USEM00000001", with_detail=True, known_flat=_known_flat(first)
    )
    assert counting.detail_calls == ["R1"]
    by_ref = {r.external_ref: r for r in second}
    assert not by_ref["R1"].detail_omitted
    assert by_ref["R2"].detail_omitted and by_ref["R3"].detail_omitted


def test_upsert_keeps_the_mirrored_detail_for_detail_omitted_records(client, session_factory):
    from datetime import datetime

    from app.test_run_evidence import TestRunEvidenceRecord, upsert_test_run_evidence

    measured = datetime(2026, 2, 8, 15, 15, 39)
    detailed = TestRunEvidenceRecord(
        component_sn="20USEM00000001",
        test_type="MODULE_METROLOGY",
        passed=True,
        external_ref="R1",
        measured_at=measured,
        payload={"state": "ready", "problems": False, "results": {"BOW": 1}, "detail_synced": True},
    )
    with session_factory() as session:
        upsert_test_run_evidence(session, [detailed])
        session.commit()

    # A skipped re-sync must not wipe the mirrored measurement payload.
    flat_only = TestRunEvidenceRecord(
        component_sn="20USEM00000001",
        test_type="MODULE_METROLOGY",
        passed=True,
        external_ref="R1",
        measured_at=measured,
        payload={"state": "ready", "problems": False},
        detail_omitted=True,
    )
    with session_factory() as session:
        stats = upsert_test_run_evidence(session, [flat_only])
        session.commit()
    assert stats.unchanged == 1

    with session_factory() as session:
        from app.models import TestRunEvidence

        row = session.scalar(select(TestRunEvidence).where(TestRunEvidence.external_ref == "R1"))
        assert row.payload.get("results") == {"BOW": 1}
        assert row.payload.get("detail_synced") is True


class _FlakyDetailClient:
    """getComponent works; the per-run detail request fails."""

    def get(self, action, json=None):
        if action == "getComponent":
            return COMPONENT
        if action == "getTestRun":
            raise RuntimeError("detail request failed")
        raise AssertionError(f"unexpected request {action}")


def test_a_failed_detail_fetch_is_not_recorded_as_mirrored():
    """A detail miss must stay retryable, not be frozen as 'already synced'.

    Marking it synced would make every later sweep skip the run, so measured
    values and attachments for it would never arrive.
    """
    gateway = _FakeGateway(component=COMPONENT)
    gateway._client = _FlakyDetailClient()

    records = fetch_test_run_evidence(gateway, "20USEM00000001", with_detail=True)

    assert records, "the runs themselves must still be mirrored"
    assert all(not r.payload.get("detail_synced") for r in records)
    assert all(not r.detail_omitted for r in records)


def test_a_refless_run_never_clobbers_a_referenced_rows_detail(client, session_factory):
    """The ref-less fallback matcher must only match ref-less rows.

    A PDB run without an id (defensive-parsing artifact) used to grab an
    arbitrary referenced row of the same test type and wipe its mirrored
    detail (audit repro T3).
    """
    from datetime import datetime

    from app.models import TestRunEvidence
    from app.test_run_evidence import TestRunEvidenceRecord, upsert_test_run_evidence

    detailed = TestRunEvidenceRecord(
        component_sn="20USEM00000001",
        test_type="MODULE_METROLOGY",
        passed=True,
        external_ref="RUN9",
        measured_at=datetime(2026, 2, 8),
        payload={"state": "ready", "problems": False, "results": {"BOW": 1}, "detail_synced": True},
    )
    refless = TestRunEvidenceRecord(
        component_sn="20USEM00000001",
        test_type="MODULE_METROLOGY",
        passed=False,
        external_ref=None,
        measured_at=None,
        payload={"state": "requestedToDelete", "problems": True},
    )
    with session_factory() as session:
        upsert_test_run_evidence(session, [detailed])
        session.commit()
    with session_factory() as session:
        upsert_test_run_evidence(session, [refless])
        session.commit()

    with session_factory() as session:
        ref_row = session.scalar(
            select(TestRunEvidence).where(TestRunEvidence.external_ref == "RUN9")
        )
        assert ref_row.passed is True
        assert ref_row.payload.get("results") == {"BOW": 1}
        refless_rows = session.scalars(
            select(TestRunEvidence).where(TestRunEvidence.external_ref.is_(None))
        ).all()
        assert len(refless_rows) == 1 and refless_rows[0].passed is False


def test_upsert_compares_timestamps_timezone_insensitively(client, session_factory):
    """PostgreSQL returns aware datetimes; records carry naive UTC. The change
    detector must treat them as equal or every sweep reports phantom updates."""
    from datetime import datetime, timezone

    from app.test_run_evidence import TestRunEvidenceRecord, upsert_test_run_evidence

    naive = datetime(2026, 2, 8, 15, 15, 39)
    aware = naive.replace(tzinfo=timezone.utc)
    base = dict(
        component_sn="20USEM00000001",
        test_type="MODULE_BOW",
        passed=True,
        external_ref="TZ1",
        payload={"state": "ready", "problems": False},
    )
    with session_factory() as session:
        upsert_test_run_evidence(session, [TestRunEvidenceRecord(measured_at=naive, **base)])
        session.commit()
    with session_factory() as session:
        stats = upsert_test_run_evidence(
            session, [TestRunEvidenceRecord(measured_at=aware, **base)]
        )
        session.commit()
    assert stats.unchanged == 1 and stats.updated == 0


def test_evidence_endpoints_commit_before_the_attachment_download(
    client: TestClient, session_factory, tudo, as_operator, tmp_path, monkeypatch
):
    """The two sync-evidence endpoints must not hold a write transaction open
    across the network download phase (review C1): evidence commits first,
    downloads run on a clean session, per-component for the institute sweep.
    """
    client.app.state.settings.attachment_dir = str(tmp_path / "attachments")
    with session_factory() as session:
        session.add(_module("20USEM00000001"))
        session.add(_module("20USEM00000002"))
        session.commit()
    client.app.state.pdb_gateway = _FakeGateway(component=COMPONENT)

    import app.attachment_store as store

    real_download = store.download_attachments
    observed: list[tuple[bool, bool, bool]] = []

    def observing_download(session, *args, **kwargs):
        observed.append((session.in_transaction(), bool(session.dirty), bool(session.new)))
        return real_download(session, *args, **kwargs)

    monkeypatch.setattr(store, "download_attachments", observing_download)

    single = client.post("/api/components/20USEM00000001/sync-evidence")
    assert single.status_code == 200, single.text

    institute = client.post("/api/sync/evidence/TUDO")
    assert institute.status_code == 200, institute.text

    assert observed, "download_attachments was never reached"
    for in_transaction, dirty, new in observed:
        # `flush()` clears dirty/new while still holding the write lock, so
        # the sharp check is the transaction itself: the endpoint must have
        # committed immediately before entering the network phase.
        assert not in_transaction, observed
        assert not dirty and not new, observed
