"""Tests for the stage-move suggestion engine (pure domain + API)."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.domain.stages import (
    DEFAULT_STAGE_MODEL,
    RequirementStatus,
    evaluate_stage,
    stage_model_from_settings,
)
from app.models import OutboxAction
from app.outbox import OutboxStatus
from app.seed_demo import DEMO_FIXTURE_PATH
from app.sync import load_fixture_records, sync_components

# --------------------------------------------------------------------------
# Pure domain
# --------------------------------------------------------------------------


def test_evaluate_suggests_move_when_all_current_requirements_pass():
    results = {"GLUE_WEIGHT": True, "MODULE_BOW": True, "MODULE_METROLOGY": True}
    ev = evaluate_stage("GLUED", results, DEFAULT_STAGE_MODEL)
    assert ev.move_suggested is True
    assert ev.next_stage == "STITCH_BONDING"
    assert ev.suggested_stage == "STITCH_BONDING"
    assert ev.blocking == []


def test_evaluate_blocks_on_failed_required_test():
    results = {"GLUE_WEIGHT": True, "MODULE_BOW": False, "MODULE_METROLOGY": True}
    ev = evaluate_stage("GLUED", results, DEFAULT_STAGE_MODEL)
    assert ev.move_suggested is False
    assert ev.suggested_stage is None
    blocked = {(c.test_type, c.status) for c in ev.blocking}
    assert ("MODULE_BOW", RequirementStatus.FAILED) in blocked


def test_evaluate_blocks_on_missing_required_test():
    ev = evaluate_stage("GLUED", {"GLUE_WEIGHT": True}, DEFAULT_STAGE_MODEL)
    assert ev.move_suggested is False
    statuses = {c.test_type: c.status for c in ev.blocking}
    assert statuses["MODULE_BOW"] is RequirementStatus.MISSING
    assert statuses["MODULE_METROLOGY"] is RequirementStatus.MISSING


def test_evaluate_includes_earlier_stage_requirements_in_checks():
    ev = evaluate_stage("BONDED", {}, DEFAULT_STAGE_MODEL)
    stages = {c.stage for c in ev.checks}
    # Requirements roadmap up to and including BONDED, so earlier stages appear.
    assert {"HV_TAB_ATTACHED", "GLUED", "BONDED"} <= stages
    # But only BONDED's own requirements block the move from BONDED.
    assert all(c.stage == "BONDED" for c in ev.blocking)


def test_evaluate_terminal_stage_never_suggests():
    ev = evaluate_stage("FINISHED", {}, DEFAULT_STAGE_MODEL)
    assert ev.next_stage is None
    assert ev.move_suggested is False


def test_stage_model_override_replaces_requirements_per_stage():
    model = stage_model_from_settings(
        {"stage_requirements": {"GLUED": ["GLUE_WEIGHT"]}}
    )
    # GLUED now needs only GLUE_WEIGHT; other stages keep the default.
    assert model.required_tests["GLUED"] == ("GLUE_WEIGHT",)
    assert model.required_tests["BONDED"] == ("MODULE_WIRE_BONDING",)
    ev = evaluate_stage("GLUED", {"GLUE_WEIGHT": True}, model)
    assert ev.move_suggested is True


def test_stage_model_override_can_reorder_and_ignores_bad_shapes():
    model = stage_model_from_settings(
        {"stage_order": ["A", "B"], "stage_requirements": {"A": ["T1"], "bad": "nope"}}
    )
    assert model.order[:2] == ("A", "B")
    assert model.required_tests["A"] == ("T1",)
    assert "bad" not in model.required_tests  # invalid value ignored


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------


def confirm_upload(
    session_factory: sessionmaker[Session],
    institute_id: int,
    *,
    sn: str,
    test_type: str,
    passed: bool,
) -> None:
    with session_factory() as session:
        session.add(
            OutboxAction(
                institute_id=institute_id,
                kind="upload_test_run",
                status=OutboxStatus.CONFIRMED.value,
                created_by="worker",
                external_ref="PDB-RUN-X",
                payload={"component_sn": sn, "test_type": test_type, "passed": passed},
            )
        )
        session.commit()


def test_stage_suggestion_endpoint_suggests_after_confirmed_uploads(
    client: TestClient, session_factory, tudo
):
    with session_factory() as session:
        sync_components(session, load_fixture_records(DEMO_FIXTURE_PATH))
        session.commit()
    sn = "20USE5M0000703"  # demo module at stage GLUED
    for test_type in ("GLUE_WEIGHT", "MODULE_BOW", "MODULE_METROLOGY"):
        confirm_upload(session_factory, tudo["id"], sn=sn, test_type=test_type, passed=True)

    body = client.get(f"/api/components/{sn}/stage-suggestion").json()
    assert body["current_stage"] == "GLUED"
    assert body["move_suggested"] is True
    assert body["suggested_stage"] == "STITCH_BONDING"
    assert body["blocking"] == []
    passed_checks = {c["test_type"]: c["status"] for c in body["checks"]}
    assert passed_checks["GLUE_WEIGHT"] == "passed"


def test_stage_suggestion_endpoint_blocks_on_failed_upload(
    client: TestClient, session_factory, tudo
):
    with session_factory() as session:
        sync_components(session, load_fixture_records(DEMO_FIXTURE_PATH))
        session.commit()
    sn = "20USE5M0000703"
    confirm_upload(session_factory, tudo["id"], sn=sn, test_type="GLUE_WEIGHT", passed=True)
    confirm_upload(session_factory, tudo["id"], sn=sn, test_type="MODULE_BOW", passed=False)
    confirm_upload(session_factory, tudo["id"], sn=sn, test_type="MODULE_METROLOGY", passed=True)

    body = client.get(f"/api/components/{sn}/stage-suggestion").json()
    assert body["move_suggested"] is False
    blocking = {c["test_type"]: c["status"] for c in body["blocking"]}
    assert blocking["MODULE_BOW"] == "failed"


def test_stage_suggestion_respects_institute_profile_override(
    client: TestClient, session_factory
):
    # Institute profile relaxes GLUED to require only GLUE_WEIGHT.
    inst = client.post(
        "/api/institutes",
        json={
            "code": "TUDO",
            "name": "TU Dortmund",
            "local_name_prefix": "TUDO-",
            "settings": {"stage_requirements": {"GLUED": ["GLUE_WEIGHT"]}},
        },
    ).json()
    with session_factory() as session:
        sync_components(session, load_fixture_records(DEMO_FIXTURE_PATH))
        session.commit()
    sn = "20USE5M0000703"
    confirm_upload(session_factory, inst["id"], sn=sn, test_type="GLUE_WEIGHT", passed=True)

    body = client.get(f"/api/components/{sn}/stage-suggestion").json()
    assert body["move_suggested"] is True  # only GLUE_WEIGHT required, and it passed


def test_stage_suggestion_404_for_unknown_component(client: TestClient):
    assert client.get("/api/components/20USE0X0000000/stage-suggestion").status_code == 404
