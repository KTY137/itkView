from authutil import create_institute_profile
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db import ensure_phase0_sqlite_schema, make_engine
from app.ingestion import parse_payload
from app.seed_demo import DEMO_FIXTURE_PATH
from app.sync import load_fixture_records, sync_components


def pdb_payload(**overrides) -> dict:
    """A complete, valid PDB-shaped test-run payload (anonymised)."""
    payload = {
        "component": "20USE5M0000701",
        "testType": "MODULE_ASSEMBLY",
        "institution": "TUDO",
        "runNumber": "1",
        "date": "2026-07-01T09:30:00.000Z",
        "passed": True,
        "problems": False,
        "properties": {"MACHINE": "OGP Smartscope", "OPERATOR": "Anna Abel"},
        "results": {"HEIGHT": 12.5, "WIDTH": 97.5},
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Parser registry (pure, no DB)
# --------------------------------------------------------------------------


def test_parse_payload_accepts_pdb_test_run_shape():
    parsed = parse_payload(pdb_payload())
    assert parsed.parser == "pdb-test-run-v1"
    assert parsed.component_sn == "20USE5M0000701"
    assert parsed.local_name is None
    assert parsed.test_type == "MODULE_ASSEMBLY"
    assert parsed.run_number == "1"
    assert parsed.institution == "TUDO"
    assert parsed.passed is True
    assert parsed.problems is False
    assert parsed.n_properties == 2
    assert {(r.name, r.kind) for r in parsed.results} == {
        ("HEIGHT", "number"),
        ("WIDTH", "number"),
    }
    assert parsed.issues == []
    assert parsed.warnings == []


def test_parse_payload_flags_missing_passed_and_results():
    payload = pdb_payload()
    del payload["passed"]
    del payload["results"]
    parsed = parse_payload(payload)
    assert "Missing field 'passed' (must be true/false)" in parsed.issues
    assert "Missing or empty 'results' object" in parsed.issues


def test_parse_payload_glue_weight_checks_numeric_results():
    payload = pdb_payload(
        testType="GLUE_WEIGHT",
        passed=False,
        results={"GW_SENSOR": 6.1849, "GW_MODULE_H1H2": None, "GW_T1": "oops"},
    )
    parsed = parse_payload(payload)
    assert parsed.parser == "glue-weight-v1"
    assert parsed.passed is False  # a failed test is still a valid upload
    assert "Result 'GW_MODULE_H1H2' is empty" in parsed.warnings
    assert "Result 'GW_T1' must be a number" in parsed.issues


def test_parse_payload_treats_non_serial_component_as_local_name():
    parsed = parse_payload(pdb_payload(component="TUDO-R5M0-07"))
    assert parsed.component_sn is None
    assert parsed.local_name == "TUDO-R5M0-07"
    assert any("local name" in w for w in parsed.warnings)
    assert parsed.issues == []


def test_parse_payload_iv_curve_checks_paired_arrays():
    ok = parse_payload(
        pdb_payload(
            testType="ATLAS18_IV_TEST_V1",
            results={"VOLTAGE": [-0.0, -10.0, -20.0], "CURRENT": [-0.0, -26.6, -34.0]},
        )
    )
    assert ok.parser == "iv-curve-v1"
    assert ok.issues == []

    truncated = parse_payload(
        pdb_payload(
            testType="ATLAS18_IV_TEST_V1",
            results={"VOLTAGE": [-0.0, -10.0, -20.0], "CURRENT": [-0.0, -26.6]},
        )
    )
    assert truncated.parser == "iv-curve-v1"
    assert any("differ in length" in issue for issue in truncated.issues)


def test_parse_payload_pull_test_flags_wire_count_mismatch():
    parsed = parse_payload(
        pdb_payload(
            testType="PULL_TEST",
            properties={"NUMBER_WIRES": 4},
            results={
                "PULL_STRENGTH": [13.2, 13.7, 14.3],
                "PULL_GRADE": ["1", "1", "2"],
                "MEAN": 13.7,
            },
        )
    )
    assert parsed.parser == "pull-test-v1"
    assert parsed.issues == []  # strengths and grades match in length
    assert any("NUMBER_WIRES" in warning for warning in parsed.warnings)


def test_parse_payload_pull_test_flags_array_length_mismatch():
    parsed = parse_payload(
        pdb_payload(
            testType="PULL_TEST",
            results={"PULL_STRENGTH": [13.2, 13.7, 14.3], "PULL_GRADE": ["1", "1"]},
        )
    )
    assert any("differ in length" in issue for issue in parsed.issues)


def test_parse_payload_generic_fallback_guesses_fields():
    parsed = parse_payload({"data": {"sn": "20USE5M0000701", "test": "MODULE_METROLOGY"}})
    assert parsed.parser == "generic-json-v1"
    assert parsed.component_sn == "20USE5M0000701"
    assert parsed.test_type == "MODULE_METROLOGY"
    assert parsed.issues == []
    assert any("heuristically" in w for w in parsed.warnings)


# --------------------------------------------------------------------------
# Inbox API
# --------------------------------------------------------------------------


def test_ingest_file_extracts_metadata_and_audits(client: TestClient, as_operator):
    response = client.post(
        "/api/ingest/files",
        json={
            "filename": "metrology-result.json",
            "uploaded_by": "anna.abel@example.org",
            "payload": {
                "serialNumber": "20USE5M0000801",
                "result": {"testType": "MODULE_METROLOGY", "passed": True},
            },
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["filename"] == "metrology-result.json"
    assert body["status"] == "received"
    assert body["component_sn"] == "20USE5M0000801"
    assert body["test_type"] == "MODULE_METROLOGY"
    assert body["parser"] == "generic-json-v1"
    assert body["error"] is None
    assert len(body["sha256"]) == 64
    assert body["size_bytes"] > 0

    listed = client.get("/api/ingest/files").json()
    assert [item["id"] for item in listed] == [body["id"]]

    audit = client.get("/api/audit").json()
    assert audit[0]["action"] == "ingest.received"
    assert audit[0]["subject"] == f"ingest:{body['id']}"
    assert audit[0]["detail"]["component_sn"] == "20USE5M0000801"


def test_ingest_file_needing_triage_is_not_rejected(client: TestClient, as_operator):
    response = client.post(
        "/api/ingest/files",
        json={
            "filename": "unknown.json",
            "uploaded_by": "anna.abel@example.org",
            "payload": {"data": {"value": 42}},
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "triage"
    assert body["component_sn"] is None
    assert body["test_type"] is None
    assert body["error"] == "Missing component identifier; Missing test type"

    triage = client.get("/api/ingest/files", params={"status": "triage"}).json()
    assert [item["id"] for item in triage] == [body["id"]]
    assert client.get("/api/ingest/files", params={"status": "received"}).json() == []


def test_ingest_endpoints_are_in_openapi(client: TestClient):
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/ingest/files" in paths
    assert "/api/ingest/files/{file_id}/preview" in paths
    assert "/api/ingest/files/{file_id}/propose-outbox" in paths


def test_ingest_file_resolves_local_name_against_mirror(
    client: TestClient, session_factory, tudo, as_operator
):
    with session_factory() as session:
        sync_components(session, load_fixture_records(DEMO_FIXTURE_PATH))
        session.commit()

    response = client.post(
        "/api/ingest/files",
        json={
            "filename": "metrology-local-name.json",
            "uploaded_by": "anna.abel@example.org",
            "payload": pdb_payload(component="TUDO-R5M0-07"),
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    # The mirror maps the local name to its PDB serial number.
    assert body["component_sn"] == "20USE5M0000701"
    assert body["status"] == "received"
    assert body["error"] is None


def test_ingest_file_with_unknown_local_name_goes_to_triage(client: TestClient, as_operator):
    response = client.post(
        "/api/ingest/files",
        json={
            "filename": "metrology-unknown-name.json",
            "uploaded_by": "anna.abel@example.org",
            "payload": pdb_payload(component="SOMEWHERE-R5M0-99"),
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["component_sn"] is None
    assert body["status"] == "triage"
    assert "does not match any mirrored component" in body["error"]


def test_ingest_preview_reports_dry_run_and_mirror_state(
    client: TestClient, session_factory, tudo, as_operator
):
    with session_factory() as session:
        sync_components(session, load_fixture_records(DEMO_FIXTURE_PATH))
        session.commit()

    ingest = client.post(
        "/api/ingest/files",
        json={
            "filename": "metrology-result.json",
            "uploaded_by": "anna.abel@example.org",
            "payload": pdb_payload(),
        },
    ).json()

    preview = client.get(f"/api/ingest/files/{ingest['id']}/preview")
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["file_id"] == ingest["id"]
    assert body["parser"] == "pdb-test-run-v1"
    assert body["upload_ready"] is True
    assert body["component_sn"] == "20USE5M0000701"
    assert body["component_mirrored"] is True
    assert body["component_stage"] == "STITCH_BONDING"
    assert body["institute_code"] == "TUDO"
    assert body["passed"] is True
    assert body["issues"] == []
    assert {r["name"] for r in body["results"]} == {"HEIGHT", "WIDTH"}

    assert client.get("/api/ingest/files/99999/preview").status_code == 404


def test_ingest_preview_of_incomplete_file_is_not_upload_ready(client: TestClient, as_operator):
    payload = pdb_payload()
    del payload["passed"]
    ingest = client.post(
        "/api/ingest/files",
        json={
            "filename": "broken.json",
            "uploaded_by": "anna.abel@example.org",
            "payload": payload,
        },
    ).json()
    assert ingest["status"] == "triage"

    body = client.get(f"/api/ingest/files/{ingest['id']}/preview").json()
    assert body["upload_ready"] is False
    assert "Missing field 'passed' (must be true/false)" in body["issues"]


def test_ingest_proposal_blocked_by_dry_run_issues(client: TestClient, tudo: dict, as_operator):
    payload = pdb_payload(component="20USE5M9999999")
    del payload["results"]
    ingest = client.post(
        "/api/ingest/files",
        json={
            "filename": "no-results.json",
            "uploaded_by": "anna.abel@example.org",
            "payload": payload,
        },
    ).json()

    response = client.post(
        f"/api/ingest/files/{ingest['id']}/propose-outbox",
        json={"created_by": "anna.abel@example.org", "institute_code": "TUDO"},
    )

    assert response.status_code == 409
    assert "Dry-run validation failed" in response.json()["detail"]
    assert "Missing or empty 'results' object" in response.json()["detail"]


def test_ingest_file_can_propose_outbox_action(client: TestClient, session_factory, as_operator):
    create_institute_profile(
        session_factory,
        code="TUDO",
        name="TU Dortmund",
        local_name_prefix="TUDO-",
    )
    with session_factory() as session:
        sync_components(session, load_fixture_records(DEMO_FIXTURE_PATH))
        session.commit()

    ingest = client.post(
        "/api/ingest/files",
        json={
            "filename": "metrology-result.json",
            "uploaded_by": "anna.abel@example.org",
            "payload": pdb_payload(),
        },
    ).json()
    assert ingest["status"] == "received"

    response = client.post(
        f"/api/ingest/files/{ingest['id']}/propose-outbox",
        json={"created_by": "anna.abel@example.org"},
    )

    assert response.status_code == 201, response.text
    action = response.json()
    assert action["kind"] == "upload_test_run"
    assert action["status"] == "draft"
    assert action["payload"]["ingest_file_id"] == ingest["id"]
    assert action["payload"]["component_sn"] == "20USE5M0000701"
    assert action["payload"]["test_type"] == "MODULE_ASSEMBLY"
    assert action["payload"]["run_number"] == "1"
    assert action["payload"]["passed"] is True
    assert action["payload"]["dry_run_required"] is True

    files = client.get("/api/ingest/files").json()
    assert files[0]["status"] == "proposed"
    assert files[0]["outbox_action_id"] == action["id"]

    duplicate = client.post(
        f"/api/ingest/files/{ingest['id']}/propose-outbox",
        json={"created_by": "anna.abel@example.org"},
    )
    assert duplicate.status_code == 409


def test_ingest_file_proposal_can_use_explicit_institute(
    client: TestClient, tudo: dict, as_operator
):
    ingest = client.post(
        "/api/ingest/files",
        json={
            "filename": "metrology-result.json",
            "uploaded_by": "anna.abel@example.org",
            "payload": pdb_payload(component="20USE5M9999999"),
        },
    ).json()

    response = client.post(
        f"/api/ingest/files/{ingest['id']}/propose-outbox",
        json={"created_by": "anna.abel@example.org", "institute_code": "TUDO"},
    )

    assert response.status_code == 201, response.text
    assert response.json()["institute_id"] == tudo["id"]


def test_ingest_file_proposal_requires_triage_complete(client: TestClient, as_operator):
    ingest = client.post(
        "/api/ingest/files",
        json={
            "filename": "unknown.json",
            "uploaded_by": "anna.abel@example.org",
            "payload": {"value": 42},
        },
    ).json()

    response = client.post(
        f"/api/ingest/files/{ingest['id']}/propose-outbox",
        json={"created_by": "anna.abel@example.org"},
    )

    assert response.status_code == 409
    assert "component serial number and test type" in response.json()["detail"]


def test_phase0_sqlite_schema_patch_adds_outbox_link_column(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE ingest_file (
                    id INTEGER PRIMARY KEY,
                    filename VARCHAR(240) NOT NULL
                )
                """
            )
        )

    ensure_phase0_sqlite_schema(engine)

    with engine.begin() as connection:
        columns = {row[1] for row in connection.execute(text("PRAGMA table_info(ingest_file)"))}
    assert "outbox_action_id" in columns
