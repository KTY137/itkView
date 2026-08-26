"""Offline contract tests for scanner-first assembly staging and submission."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.assembly import canonical_action_payload, evaluate_assembly
from app.config import Settings
from app.models import AuditEvent, Component, GlueBatch, InstituteProfile, OutboxAction, Tool
from app.outbox import OutboxStatus
from app.outbox_worker import process_due_actions, revalidate_assembly_action
from app.pdb_credentials import PdbAccessCodes
from app.pdb_submit import make_pdb_submitter


def _component(
    sn: str,
    component_type: str,
    *,
    type_code: str,
    dummy: bool = True,
    local_name: str | None = None,
) -> Component:
    return Component(
        sn=sn,
        component_type=component_type,
        type_code=type_code,
        stage="GLUED",
        location="TUDO",
        institute_code="TUDO",
        local_name=local_name,
        is_dummy=dummy,
        stale=False,
        trashed=False,
    )


def seed_valid_assembly(session_factory, tudo, *, dummy: bool = True) -> dict[str, int | str]:
    with session_factory() as session:
        institute = session.get(InstituteProfile, tudo["id"])
        institute.settings = {
            **(institute.settings or {}),
            "assembly_property_keys": {
                "tool": "MODULE_ASSEMBLY_JIG",
                "glue_batch": "HYBRID_GLUE_SAMPLE",
                "slot": "HYBRID_POSITION",
            },
        }
        parent = _component(
            "20UPGM19990010",
            "MODULE",
            type_code="R5M0",
            dummy=dummy,
            local_name="DUMMY-MODULE-10",
        )
        child = _component(
            "20UPGH19990011",
            "HYBRID",
            type_code="R5H0",
            dummy=dummy,
            local_name="DUMMY-HYBRID-11",
        )
        tool = Tool(
            institute_id=institute.id,
            kind="jig",
            code="JIG-R5-01",
            label="R5 module jig",
            rfid="RFID-R5-01",
            compatible_types=["R5M0"],
            status="active",
        )
        glue = GlueBatch(
            institute_id=institute.id,
            glue_type="EPOXY",
            batch_no="EPOXY-42",
            pdb_sn="20USEGT0000042",
            status="in_use",
            mixed_at=datetime.now(timezone.utc) - timedelta(minutes=2),
            pot_life_minutes=30,
        )
        session.add_all([parent, child, tool, glue])
        session.commit()
        return {
            "parent_sn": parent.sn,
            "child_sn": child.sn,
            "tool_id": tool.id,
            "glue_batch_id": glue.id,
        }


def _body(seed: dict[str, int | str]) -> dict:
    return {
        "parent_sn": seed["parent_sn"],
        "child_sn": seed["child_sn"],
        "slot": "H0",
        "tool_id": seed["tool_id"],
        "glue_batch_id": seed["glue_batch_id"],
    }


def test_preview_and_stage_use_one_canonical_audited_contract(
    client: TestClient, session_factory, tudo, as_operator
):
    seed = seed_valid_assembly(session_factory, tudo)

    preview_response = client.post("/api/assembly/preview", json=_body(seed))
    assert preview_response.status_code == 200, preview_response.text
    preview = preview_response.json()
    assert preview["valid"] is True
    assert preview["submittable"] is True
    assert preview["pdb_properties"] == {
        "MODULE_ASSEMBLY_JIG": "JIG-R5-01",
        "HYBRID_GLUE_SAMPLE": "20USEGT0000042",
        "HYBRID_POSITION": "H0",
    }

    staged_response = client.post("/api/assembly/actions", json=_body(seed))
    assert staged_response.status_code == 201, staged_response.text
    staged = staged_response.json()
    assert staged["preview"] == preview
    action = staged["action"]
    assert action["kind"] == "assemble_component"
    assert action["status"] == "draft"
    assert action["created_by"] == "operator@auth.example"
    assert action["payload"] == {
        "parent_sn": seed["parent_sn"],
        "child_sn": seed["child_sn"],
        "slot": "H0",
        "tool_id": seed["tool_id"],
        "glue_batch_id": seed["glue_batch_id"],
        "expected_parent_component_type": "MODULE",
        "expected_parent_type_code": "R5M0",
        "expected_parent_stage": "GLUED",
        "expected_parent_location": "TUDO",
        "expected_parent_institute_code": "TUDO",
        "expected_child_component_type": "HYBRID",
        "expected_child_type_code": "R5H0",
        "expected_child_parent_sn": None,
        "expected_child_location": "TUDO",
        "expected_child_institute_code": "TUDO",
        "expected_tool_code": "JIG-R5-01",
        "expected_glue_batch_no": "EPOXY-42",
        "pdb_properties": preview["pdb_properties"],
        "dry_run_required": True,
    }
    with session_factory() as session:
        event = session.scalar(
            select(AuditEvent).where(AuditEvent.outbox_action_id == action["id"])
        )
        assert event.action == "outbox.created"
        assert event.detail["dry_run"] == "passed"
        assert event.detail["tool_code"] == "JIG-R5-01"


@pytest.mark.parametrize(
    ("mutation", "issue_code"),
    [
        ("tool_flagged", "tool_not_active"),
        ("tool_incompatible", "tool_incompatible"),
        ("glue_new", "glue_batch_not_in_use"),
        ("glue_pot_life", "glue_pot_life_expired"),
        ("child_sensor", "child_type_not_allowed"),
        ("reversed_types", "component_type_relationship_not_allowed"),
        ("offsite", "parent_not_at_institute"),
    ],
)
def test_preview_blocks_changed_tool_glue_and_unsafe_component_types(
    client: TestClient,
    session_factory,
    tudo,
    as_operator,
    mutation: str,
    issue_code: str,
):
    seed = seed_valid_assembly(session_factory, tudo)
    with session_factory() as session:
        tool = session.get(Tool, seed["tool_id"])
        glue = session.get(GlueBatch, seed["glue_batch_id"])
        child = session.scalar(select(Component).where(Component.sn == seed["child_sn"]))
        if mutation == "tool_flagged":
            tool.status = "flagged"
        elif mutation == "tool_incompatible":
            tool.compatible_types = ["R2"]
        elif mutation == "glue_new":
            glue.status = "new"
        elif mutation == "glue_pot_life":
            glue.mixed_at = datetime.now(timezone.utc) - timedelta(hours=2)
        elif mutation == "reversed_types":
            parent = session.scalar(select(Component).where(Component.sn == seed["parent_sn"]))
            parent.component_type = "HYBRID"
        elif mutation == "offsite":
            parent = session.scalar(select(Component).where(Component.sn == seed["parent_sn"]))
            parent.location = "ANOTHER_SITE"
            child.location = "ANOTHER_SITE"
        else:
            child.component_type = "SENSOR"
        session.commit()

    response = client.post("/api/assembly/preview", json=_body(seed))
    assert response.status_code == 200
    preview = response.json()
    assert preview["valid"] is False
    assert issue_code in {issue["code"] for issue in preview["issues"]}
    blocked = client.post("/api/assembly/actions", json=_body(seed))
    assert blocked.status_code == 409


def test_non_dummy_modules_can_be_staged_but_never_marked_submittable(
    client: TestClient, session_factory, tudo, as_operator
):
    seed = seed_valid_assembly(session_factory, tudo, dummy=False)
    preview = client.post("/api/assembly/preview", json=_body(seed)).json()
    assert preview["valid"] is True
    assert preview["submittable"] is False
    assert preview["submittable_reason"] == "not_dummy"

    staged = client.post("/api/assembly/actions", json=_body(seed))
    assert staged.status_code == 201
    component_preview = client.get(f"/api/components/{seed['parent_sn']}/preview").json()
    action_preview = component_preview["staged_actions"][0]
    assert action_preview["kind"] == "assemble_component"
    assert action_preview["submittable"] is False
    assert action_preview["submittable_reason"] == "not_dummy"


def test_scanner_resolves_exact_serial_or_local_name_and_requires_auth(
    client: TestClient, session_factory, tudo
):
    seed_valid_assembly(session_factory, tudo)
    assert client.get(
        "/api/assembly/scan-component", params={"code": "DUMMY-MODULE-10"}
    ).status_code == 401

    from authutil import authenticate

    authenticate(client, session_factory, role="viewer")
    by_name = client.get(
        "/api/assembly/scan-component", params={"code": "dummy-module-10"}
    )
    assert by_name.status_code == 200
    assert by_name.json()["sn"] == "20UPGM19990010"
    by_sn = client.get(
        "/api/assembly/scan-component", params={"code": "20upgh19990011"}
    )
    assert by_sn.json()["local_name"] == "DUMMY-HYBRID-11"


def test_worker_revalidates_tool_and_glue_immediately_before_submit(
    client: TestClient, session_factory, tudo, as_operator
):
    seed = seed_valid_assembly(session_factory, tudo)
    action_id = client.post("/api/assembly/actions", json=_body(seed)).json()["action"]["id"]
    with session_factory() as session:
        action = session.get(OutboxAction, action_id)
        action.status = OutboxStatus.APPROVED.value
        session.get(Tool, seed["tool_id"]).status = "blacklisted"
        session.commit()

    def never_called(session, action):
        raise AssertionError("A blocked assembly must never reach a submitter.")

    with session_factory() as session:
        stats = process_due_actions(session, never_called)
    assert stats.revalidation_failed == 1
    with session_factory() as session:
        action = session.get(OutboxAction, action_id)
        assert action.status == "failed"
        assert "only active tools" in action.error


def test_revalidation_detects_component_snapshot_changes(session_factory, tudo):
    seed = seed_valid_assembly(session_factory, tudo)
    with session_factory() as session:
        evaluation = evaluate_assembly(session, Settings(_env_file=None), **_body(seed))
        payload = canonical_action_payload(evaluation)
        parent = session.scalar(select(Component).where(Component.sn == seed["parent_sn"]))
        parent.stage = "BONDED"
        session.flush()
        issues = revalidate_assembly_action(session, payload)
    assert any("parent stage changed" in issue for issue in issues)


def test_real_submitter_gates_both_participants_before_client_and_uses_canonical_payload(
    session_factory, tudo, monkeypatch
):
    seed = seed_valid_assembly(session_factory, tudo)
    settings = Settings(allow_pdb_writes=True, _env_file=None)
    codes = PdbAccessCodes("offline-one", "offline-two")
    calls: list[tuple[str, dict]] = []

    class FakeClient:
        def post(self, endpoint, json):
            calls.append((endpoint, json))
            return {"id": "ASSEMBLY-42"}

    class FakeGateway:
        def __init__(self, configured, *, access_codes=None):
            assert configured is settings
            assert access_codes is codes

        def client(self):
            return FakeClient()

    monkeypatch.setattr("app.pdb_submit.PdbGateway", FakeGateway)
    submitter = make_pdb_submitter(settings, service_access_codes=codes)
    with session_factory() as session:
        payload = canonical_action_payload(
            evaluate_assembly(session, settings, **_body(seed))
        )
        action = SimpleNamespace(kind="assemble_component", payload=payload)
        outcome = submitter(session, action)
    assert outcome.external_ref == "ASSEMBLY-42"
    assert calls == [
        (
            "assembleComponent",
            {
                "parent": seed["parent_sn"],
                "children": [
                    {
                        "sn": seed["child_sn"],
                        "properties": {
                            "MODULE_ASSEMBLY_JIG": "JIG-R5-01",
                            "HYBRID_GLUE_SAMPLE": "20USEGT0000042",
                            "HYBRID_POSITION": "H0",
                        },
                    }
                ],
                "disassemble": [],
            },
        )
    ]

    # Turning the child into a sensor must close the gate before another PDB
    # client is constructed, even if a malicious database marks it DUMMY.
    with session_factory() as session:
        child = session.scalar(select(Component).where(Component.sn == seed["child_sn"]))
        child.component_type = "SENSOR"
        child.is_dummy = True
        session.commit()
        blocked = submitter(session, SimpleNamespace(kind="assemble_component", payload=payload))
    assert blocked.is_confirmed is False
    assert "sensors and ASICs" in (blocked.rejected_reason or "")
    assert len(calls) == 1
