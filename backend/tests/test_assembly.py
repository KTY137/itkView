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


def seed_multi_slot_assembly(session_factory, tudo) -> dict[str, int | str]:
    """Extend the single-tool fixture with a ``multiple: true`` extra slot.

    Mirrors the production sheet's combined tool columns: a single default
    "Module jig used" plus a separate, possibly-repeated "Hybrid glue jigs
    used, top, bottom" slot.
    """

    seed = seed_valid_assembly(session_factory, tudo)
    with session_factory() as session:
        institute = session.get(InstituteProfile, tudo["id"])
        institute.settings = {
            **(institute.settings or {}),
            "assembly_tool_slots": [
                {
                    "key": "hybrid_glue_jig",
                    "label": "Hybrid glue jig, top/bottom",
                    "kinds": ["jig"],
                    "multiple": True,
                    "property_key": "JIG_HYBRID_ALIGNMENT",
                },
            ],
        }
        matching_kind = Tool(
            institute_id=institute.id,
            kind="jig",
            code="HGJ-01",
            label="Hybrid glue jig #1",
            compatible_types=["R5H0"],
            status="active",
        )
        wrong_kind = Tool(
            institute_id=institute.id,
            kind="pickup_tool",
            code="HGJ-02",
            label="Hybrid pickup tool (wrong kind for hybrid_glue_jig)",
            compatible_types=["R5H0"],
            status="active",
        )
        session.add_all([matching_kind, wrong_kind])
        session.commit()
        seed["hybrid_glue_jig_tool_id"] = matching_kind.id
        seed["wrong_kind_tool_id"] = wrong_kind.id
    return seed


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


# --- Combined-tool slots (assembly_tool_slots / `tools` payload) -----------
#
# The production sheets this replaces track several tools used together in
# one assembly step ("Hybrid glue jigs used, top, bottom", "Hybrid pickups
# used, top, bottom" next to a single "Module jig used"). `tool_id` remains
# valid on its own and is always shorthand for the default "tool" slot.


def test_legacy_tool_id_only_still_produces_the_original_payload_shape(
    session_factory, tudo
):
    seed = seed_valid_assembly(session_factory, tudo)
    with session_factory() as session:
        evaluation = evaluate_assembly(session, Settings(_env_file=None), **_body(seed))
        assert evaluation.valid, evaluation.issues
        assert set(evaluation.tools_by_slot) == {"tool"}
        assert evaluation.tool is not None and evaluation.tool.id == seed["tool_id"]
        payload = canonical_action_payload(evaluation)
    assert "tools" not in payload
    assert "expected_tools" not in payload
    assert payload["tool_id"] == seed["tool_id"]
    assert payload["expected_tool_code"] == "JIG-R5-01"


def test_multi_slot_tools_validate_and_snapshot_as_a_tools_map(session_factory, tudo):
    seed = seed_multi_slot_assembly(session_factory, tudo)
    with session_factory() as session:
        evaluation = evaluate_assembly(
            session,
            Settings(_env_file=None),
            parent_sn=seed["parent_sn"],
            child_sn=seed["child_sn"],
            slot="H0",
            tool_id=seed["tool_id"],
            tools={
                # Same physical jig scanned for both positions, exactly like
                # the sheet's observed "4, 4" (references/zeuthenflow,
                # read-only) for JIG_HYBRID_ALIGNMENT.
                "hybrid_glue_jig": [
                    seed["hybrid_glue_jig_tool_id"],
                    seed["hybrid_glue_jig_tool_id"],
                ]
            },
            glue_batch_id=seed["glue_batch_id"],
        )
        assert evaluation.valid, evaluation.issues
        assert evaluation.pdb_properties["JIG_HYBRID_ALIGNMENT"] == "HGJ-01, HGJ-01"
        assert evaluation.pdb_properties["MODULE_ASSEMBLY_JIG"] == "JIG-R5-01"
        payload = canonical_action_payload(evaluation)

    assert payload["tool_id"] == seed["tool_id"]
    assert payload["tools"] == {
        "tool": [seed["tool_id"]],
        "hybrid_glue_jig": [seed["hybrid_glue_jig_tool_id"], seed["hybrid_glue_jig_tool_id"]],
    }
    assert payload["expected_tools"] == {
        "tool": ["JIG-R5-01"],
        "hybrid_glue_jig": ["HGJ-01", "HGJ-01"],
    }
    with session_factory() as session:
        assert revalidate_assembly_action(session, payload) == []


def test_conflicting_tool_id_and_tools_default_slot_is_a_validation_error(
    session_factory, tudo
):
    seed = seed_multi_slot_assembly(session_factory, tudo)
    with session_factory() as session:
        evaluation = evaluate_assembly(
            session,
            Settings(_env_file=None),
            parent_sn=seed["parent_sn"],
            child_sn=seed["child_sn"],
            slot="H0",
            tool_id=seed["tool_id"],
            tools={"tool": [seed["wrong_kind_tool_id"]]},
        )
    assert not evaluation.valid
    assert "tool_slot_conflict" in {issue.code for issue in evaluation.issues}
    # A genuine conflict is a blocking issue, but the tools-supplied value
    # still wins the resolved slot rather than being silently overridden.
    assert evaluation.tools_by_slot["tool"][0].id == seed["wrong_kind_tool_id"]


def test_agreeing_tool_id_and_tools_default_slot_is_not_a_conflict(session_factory, tudo):
    seed = seed_valid_assembly(session_factory, tudo)
    with session_factory() as session:
        evaluation = evaluate_assembly(
            session,
            Settings(_env_file=None),
            parent_sn=seed["parent_sn"],
            child_sn=seed["child_sn"],
            slot="H0",
            tool_id=seed["tool_id"],
            tools={"tool": [seed["tool_id"]]},
            glue_batch_id=seed["glue_batch_id"],
        )
    assert evaluation.valid, evaluation.issues
    assert "tool_slot_conflict" not in {issue.code for issue in evaluation.issues}


def test_slot_kinds_violation_is_blocked(session_factory, tudo):
    seed = seed_multi_slot_assembly(session_factory, tudo)
    with session_factory() as session:
        evaluation = evaluate_assembly(
            session,
            Settings(_env_file=None),
            parent_sn=seed["parent_sn"],
            child_sn=seed["child_sn"],
            slot="H0",
            tool_id=seed["tool_id"],
            tools={"hybrid_glue_jig": [seed["wrong_kind_tool_id"]]},
        )
    assert not evaluation.valid
    assert "hybrid_glue_jig_tool_kind_not_allowed" in {
        issue.code for issue in evaluation.issues
    }


@pytest.mark.parametrize("count", [1, 4])
def test_slot_multiple_accepts_one_to_four_tools(session_factory, tudo, count):
    seed = seed_multi_slot_assembly(session_factory, tudo)
    with session_factory() as session:
        evaluation = evaluate_assembly(
            session,
            Settings(_env_file=None),
            parent_sn=seed["parent_sn"],
            child_sn=seed["child_sn"],
            slot="H0",
            tool_id=seed["tool_id"],
            tools={"hybrid_glue_jig": [seed["hybrid_glue_jig_tool_id"]] * count},
        )
    assert evaluation.valid, evaluation.issues


def test_slot_multiple_rejects_more_than_four_tools(session_factory, tudo):
    seed = seed_multi_slot_assembly(session_factory, tudo)
    with session_factory() as session:
        evaluation = evaluate_assembly(
            session,
            Settings(_env_file=None),
            parent_sn=seed["parent_sn"],
            child_sn=seed["child_sn"],
            slot="H0",
            tool_id=seed["tool_id"],
            tools={"hybrid_glue_jig": [seed["hybrid_glue_jig_tool_id"]] * 5},
        )
    assert not evaluation.valid
    assert "hybrid_glue_jig_tool_count_invalid" in {issue.code for issue in evaluation.issues}


def test_default_slot_without_multiple_configured_rejects_two_tools(session_factory, tudo):
    seed = seed_multi_slot_assembly(session_factory, tudo)
    with session_factory() as session:
        evaluation = evaluate_assembly(
            session,
            Settings(_env_file=None),
            parent_sn=seed["parent_sn"],
            child_sn=seed["child_sn"],
            slot="H0",
            # tools-only: no legacy tool_id at all for the default slot.
            tools={"tool": [seed["tool_id"], seed["hybrid_glue_jig_tool_id"]]},
        )
    assert not evaluation.valid
    assert "tool_count_invalid" in {issue.code for issue in evaluation.issues}


def test_unknown_tool_slot_key_is_rejected(session_factory, tudo):
    seed = seed_valid_assembly(session_factory, tudo)
    with session_factory() as session:
        evaluation = evaluate_assembly(
            session,
            Settings(_env_file=None),
            parent_sn=seed["parent_sn"],
            child_sn=seed["child_sn"],
            slot="H0",
            tool_id=seed["tool_id"],
            tools={"not_a_configured_slot": [seed["tool_id"]]},
        )
    assert not evaluation.valid
    assert "unknown_tool_slot" in {issue.code for issue in evaluation.issues}


def test_missing_and_malformed_tools_selection_are_validation_errors(session_factory, tudo):
    seed = seed_valid_assembly(session_factory, tudo)
    with session_factory() as session:
        no_tool = evaluate_assembly(
            session,
            Settings(_env_file=None),
            parent_sn=seed["parent_sn"],
            child_sn=seed["child_sn"],
            slot="H0",
        )
    assert "tools_required" in {issue.code for issue in no_tool.issues}

    with session_factory() as session:
        malformed = evaluate_assembly(
            session,
            Settings(_env_file=None),
            parent_sn=seed["parent_sn"],
            child_sn=seed["child_sn"],
            slot="H0",
            tools={"tool": []},
        )
    assert "tools_invalid" in {issue.code for issue in malformed.issues}


def test_revalidate_accepts_a_hand_built_pre_slots_snapshot(session_factory, tudo):
    """A real action staged before this module supported tool slots has no
    ``tools`` key at all; it must keep revalidating exactly as before."""

    seed = seed_valid_assembly(session_factory, tudo)
    old_shape_payload = {
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
        "pdb_properties": {
            "MODULE_ASSEMBLY_JIG": "JIG-R5-01",
            "HYBRID_GLUE_SAMPLE": "20USEGT0000042",
            "HYBRID_POSITION": "H0",
        },
        "dry_run_required": True,
    }
    with session_factory() as session:
        assert revalidate_assembly_action(session, old_shape_payload) == []

        tool = session.get(Tool, seed["tool_id"])
        tool.status = "blacklisted"
        session.commit()
        issues = revalidate_assembly_action(session, old_shape_payload)
    assert any("only active tools" in issue for issue in issues)


def test_revalidate_flags_inactive_extra_slot_tool_without_a_false_drift_signal(
    session_factory, tudo
):
    seed = seed_multi_slot_assembly(session_factory, tudo)
    with session_factory() as session:
        evaluation = evaluate_assembly(
            session,
            Settings(_env_file=None),
            parent_sn=seed["parent_sn"],
            child_sn=seed["child_sn"],
            slot="H0",
            tool_id=seed["tool_id"],
            tools={"hybrid_glue_jig": [seed["hybrid_glue_jig_tool_id"]]},
            glue_batch_id=seed["glue_batch_id"],
        )
        payload = canonical_action_payload(evaluation)
        extra_tool = session.get(Tool, seed["hybrid_glue_jig_tool_id"])
        extra_tool.status = "flagged"
        session.commit()
        issues = revalidate_assembly_action(session, payload)
    assert any("only active tools" in issue for issue in issues)
    assert not any("tools changed" in issue for issue in issues)


def test_revalidate_detects_tools_snapshot_drift_when_a_slot_is_removed(session_factory, tudo):
    seed = seed_multi_slot_assembly(session_factory, tudo)
    with session_factory() as session:
        evaluation = evaluate_assembly(
            session,
            Settings(_env_file=None),
            parent_sn=seed["parent_sn"],
            child_sn=seed["child_sn"],
            slot="H0",
            tool_id=seed["tool_id"],
            tools={"hybrid_glue_jig": [seed["hybrid_glue_jig_tool_id"]]},
            glue_batch_id=seed["glue_batch_id"],
        )
        payload = canonical_action_payload(evaluation)
        assert revalidate_assembly_action(session, payload) == []

        institute = session.get(InstituteProfile, tudo["id"])
        institute.settings = {**institute.settings, "assembly_tool_slots": []}
        session.commit()
        issues = revalidate_assembly_action(session, payload)
    assert any("not a configured assembly tool slot" in issue for issue in issues)
    assert any("tools changed" in issue for issue in issues)


def test_the_api_accepts_tool_slot_combinations(client, session_factory, tudo, as_operator):
    """`tools` must travel through POST /api/assembly/preview and /actions.

    The domain layer supports slot combinations; without the HTTP wiring the
    wizard cannot send them (orchestrator follow-up to the domain change).
    """
    seed = seed_multi_slot_assembly(session_factory, tudo)
    jig_id = seed["hybrid_glue_jig_tool_id"]

    body = {
        **_body(seed),
        # The sheet's "top, bottom" case: the same physical jig scanned twice.
        "tools": {"hybrid_glue_jig": [jig_id, jig_id]},
    }

    preview = client.post("/api/assembly/preview", json=body)
    assert preview.status_code == 200, preview.text
    snapshot = preview.json()
    assert [tool["id"] for tool in snapshot["tools"]["hybrid_glue_jig"]] == [jig_id, jig_id]

    staged = client.post("/api/assembly/actions", json=body)
    assert staged.status_code == 201, staged.text
    payload = staged.json()["action"]["payload"]
    assert payload["tools"]["hybrid_glue_jig"] == [jig_id, jig_id]


def test_the_api_still_accepts_a_plain_tool_id(client, session_factory, tudo, as_operator):
    seed = seed_multi_slot_assembly(session_factory, tudo)
    preview = client.post("/api/assembly/preview", json=_body(seed))
    assert preview.status_code == 200, preview.text


def test_a_slot_count_violation_stops_the_per_id_loop(client, session_factory, tudo, as_operator):
    """Review I1: an oversized id list must be recorded once and NOT resolve
    every id individually (unbounded SELECT/issue amplification)."""
    seed = seed_multi_slot_assembly(session_factory, tudo)
    body = {
        **_body(seed),
        "tools": {"hybrid_glue_jig": [seed["hybrid_glue_jig_tool_id"]] * 4 + [999_999]},
    }
    preview = client.post("/api/assembly/preview", json=body)
    # Rejected at the schema boundary: per-slot lists are capped at the domain
    # maximum, so the request never reaches the resolver at all.
    assert preview.status_code == 422, preview.text


def test_the_tools_mapping_size_is_bounded(client, session_factory, tudo, as_operator):
    seed = seed_multi_slot_assembly(session_factory, tudo)
    body = {
        **_body(seed),
        "tools": {f"slot_{i}": [1] for i in range(64)},
    }
    assert client.post("/api/assembly/preview", json=body).status_code == 422


def test_domain_count_violation_short_circuits_without_resolving_ids(session_factory, tudo):
    """Direct domain call (bypasses the schema cap): the resolver itself must
    short-circuit a cardinality violation."""
    from app.assembly import evaluate_assembly
    from app.config import Settings

    seed = seed_multi_slot_assembly(session_factory, tudo)
    with session_factory() as session:
        evaluation = evaluate_assembly(
            session,
            Settings(_env_file=None),
            parent_sn=seed["parent_sn"],
            child_sn=seed["child_sn"],
            slot="H0",
            tool_id=seed["tool_id"],
            tools={"hybrid_glue_jig": [seed["hybrid_glue_jig_tool_id"]] * 9},
            glue_batch_id=seed["glue_batch_id"],
        )
    codes = [issue.code for issue in evaluation.issues]
    assert "hybrid_glue_jig_tool_count_invalid" in codes
    # One count issue, no per-id follow-up issues for the oversized list.
    assert len([c for c in codes if c.startswith("hybrid_glue_jig_")]) == 1


def test_every_slot_enforces_parent_type_compatibility(session_factory, tudo):
    """Review I2: `compatible_types` must gate every slot, not only the
    default one — otherwise a slots-only layout ships with weaker server
    validation than the client's own quick-select filter."""
    from app.assembly import evaluate_assembly
    from app.config import Settings
    from app.models import Tool

    seed = seed_multi_slot_assembly(session_factory, tudo)
    with session_factory() as session:
        incompatible = Tool(
            institute_id=tudo["id"],
            kind="jig",
            code="HGJ-WRONGTYPE",
            label="Jig for a different module type",
            compatible_types=["R2"],
            status="active",
        )
        session.add(incompatible)
        session.commit()
        wrong_type_id = incompatible.id

    with session_factory() as session:
        evaluation = evaluate_assembly(
            session,
            Settings(_env_file=None),
            parent_sn=seed["parent_sn"],
            child_sn=seed["child_sn"],
            slot="H0",
            tool_id=seed["tool_id"],
            tools={"hybrid_glue_jig": [wrong_type_id]},
            glue_batch_id=seed["glue_batch_id"],
        )
    codes = [issue.code for issue in evaluation.issues]
    assert "hybrid_glue_jig_tool_incompatible" in codes
