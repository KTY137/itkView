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
