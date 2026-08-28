from fastapi.testclient import TestClient


def test_health_reports_test_instance(client: TestClient):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["pdb_instance"] == "offline"


def test_institute_roundtrip_and_conflict(as_admin: TestClient, tudo: dict):
    assert tudo["code"] == "TUDO"
    listed = as_admin.get("/api/institutes").json()
    assert [i["code"] for i in listed] == ["TUDO"]

    duplicate = as_admin.post("/api/institutes", json={"code": "TUDO", "name": "again"})
    assert duplicate.status_code == 409


def test_institute_code_is_validated(as_admin: TestClient):
    response = as_admin.post("/api/institutes", json={"code": "tudo!", "name": "bad code"})
    assert response.status_code == 422


def test_outbox_lifecycle_with_audit_trail(client: TestClient, tudo: dict, as_operator):
    created = client.post(
        "/api/outbox",
        json={
            "institute_code": "TUDO",
            "kind": "stage_move",
            "payload": {"component": "20USE5R0000128", "to_stage": "BONDED"},
            "created_by": "anna.abel@example.org",
        },
    )
    assert created.status_code == 201, created.text
    action = created.json()
    assert action["status"] == "draft"
    action_id = action["id"]

    # Operators own review and submission; only the worker may resolve a
    # submitted action to failed/confirmed after talking to the PDB.
    steps = [
        ("validated", 200),
        ("approved", 200),
        ("submitted", 200),
    ]
    for target, expected in steps:
        response = client.post(
            f"/api/outbox/{action_id}/transition",
            json={"to": target, "actor": "anna.abel@example.org", "error": "PDB timeout"},
        )
        assert response.status_code == expected, response.text

    final = client.get(f"/api/outbox/{action_id}").json()
    assert final["status"] == "submitted"
    assert final["attempts"] == 1

    audit = client.get("/api/audit").json()
    subjects = {event["subject"] for event in audit}
    assert f"outbox:{action_id}" in subjects
    assert len([e for e in audit if e["action"] == "outbox.transition"]) == len(steps)

    targeted = client.get(f"/api/outbox/{action_id}/audit")
    assert targeted.status_code == 200, targeted.text
    action_audit = targeted.json()
    assert [event["action"] for event in action_audit] == [
        "outbox.created",
        *("outbox.transition" for _ in steps),
    ]
    assert all(event["outbox_action_id"] == action_id for event in action_audit)
    assert [event["id"] for event in action_audit] == sorted(
        event["id"] for event in action_audit
    )


def test_outbox_audit_returns_404_for_unknown_action(client: TestClient):
    response = client.get("/api/outbox/999999/audit")
    assert response.status_code == 404


def test_outbox_contract_is_public_and_not_an_action_id(client: TestClient):
    response = client.get("/api/outbox/contract")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["statuses"] == [
        "draft",
        "validated",
        "approved",
        "submitted",
        "confirmed",
        "failed",
        "cancelled",
    ]
    assert body["transitions"]["draft"] == ["validated", "cancelled"]
    assert body["transitions"]["submitted"] == ["confirmed", "failed"]
    assert body["terminal"] == ["cancelled", "confirmed"]
    assert body["worker_owned_targets"] == ["confirmed", "failed"]


def test_operator_cannot_forge_worker_owned_outbox_result(
    client: TestClient, tudo: dict, as_operator
):
    action = client.post(
        "/api/outbox",
        json={"institute_code": "TUDO", "kind": "upload_test_run", "created_by": "aa"},
    ).json()
    for target in ("validated", "approved", "submitted"):
        response = client.post(
            f"/api/outbox/{action['id']}/transition", json={"to": target, "actor": "aa"}
        )
        assert response.status_code == 200, response.text

    for target in ("confirmed", "failed"):
        response = client.post(
            f"/api/outbox/{action['id']}/transition", json={"to": target, "actor": "aa"}
        )
        assert response.status_code == 403
        assert "worker-owned" in response.json()["detail"]

    assert client.get(f"/api/outbox/{action['id']}").json()["status"] == "submitted"


def test_outbox_rejects_invalid_transition(client: TestClient, tudo: dict, as_operator):
    action = client.post(
        "/api/outbox",
        json={"institute_code": "TUDO", "kind": "register_component", "created_by": "aa"},
    ).json()

    response = client.post(
        f"/api/outbox/{action['id']}/transition",
        json={"to": "confirmed", "actor": "aa"},
    )
    assert response.status_code == 409
    assert "draft" in response.json()["detail"]


def test_outbox_requires_known_institute(client: TestClient, as_operator):
    response = client.post(
        "/api/outbox",
        json={"institute_code": "NOPE", "kind": "stage_move", "created_by": "aa"},
    )
    assert response.status_code == 404


def test_outbox_list_filters_by_status(client: TestClient, tudo: dict, as_operator):
    first = client.post(
        "/api/outbox",
        json={"institute_code": "TUDO", "kind": "stage_move", "created_by": "aa"},
    ).json()
    client.post(
        "/api/outbox",
        json={"institute_code": "TUDO", "kind": "upload_test_run", "created_by": "aa"},
    )
    client.post(f"/api/outbox/{first['id']}/transition", json={"to": "validated", "actor": "aa"})

    drafts = client.get("/api/outbox", params={"status": "draft"}).json()
    validated = client.get("/api/outbox", params={"status": "validated"}).json()
    assert {a["kind"] for a in drafts} == {"upload_test_run"}
    assert {a["kind"] for a in validated} == {"stage_move"}
