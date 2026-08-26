"""Projection of open outbox work over one mirrored component."""

from authutil import authenticate

from app.models import (
    Component,
    IngestFile,
    OutboxAction,
    TestRunAttachment,
    TestRunEvidence,
)
from app.preview import build_component_preview

SN = "20USEM20000991"


def _component(session, *, institute_code="TUDO", stage="HV_TAB_ATTACHED", dummy=True):
    component = Component(
        sn=SN,
        component_type="MODULE",
        type_code="R5M0",
        stage=stage,
        location=institute_code,
        institute_code=institute_code,
        is_dummy=dummy,
    )
    session.add(component)
    session.flush()
    return component


def _action(session, institute_id, *, kind, payload, status="draft"):
    action = OutboxAction(
        institute_id=institute_id,
        kind=kind,
        payload=payload,
        status=status,
        created_by="operator@example.org",
    )
    session.add(action)
    session.flush()
    return action


def test_empty_preview_matches_the_current_mirror(session_factory, client, tudo):
    with session_factory() as session:
        component = _component(session)
        preview = build_component_preview(session, component, client.app.state.settings)

    assert preview["current"]["stage"] == "HV_TAB_ATTACHED"
    assert preview["projected"]["stage"] == "HV_TAB_ATTACHED"
    assert preview["staged_actions"] == []
    assert preview["projected"]["tests"] == []


def test_stage_moves_are_applied_in_creation_order(session_factory, client, tudo):
    with session_factory() as session:
        component = _component(session)
        first = _action(
            session,
            tudo["id"],
            kind="stage_move",
            payload={"sn": SN, "to_stage": "GLUED"},
        )
        second = _action(
            session,
            tudo["id"],
            kind="stage_move",
            payload={"sn": SN, "to_stage": "STITCH_BONDING"},
            status="validated",
        )
        preview = build_component_preview(session, component, client.app.state.settings)

    assert [row["id"] for row in preview["staged_actions"]] == [first.id, second.id]
    assert preview["projected"]["stage"] == "STITCH_BONDING"


def test_pending_upload_is_a_ghost_and_a_pending_check(session_factory, client, tudo):
    with session_factory() as session:
        component = _component(session, stage="GLUED")
        session.add(
            TestRunEvidence(
                component_sn=SN,
                test_type="GLUE_WEIGHT",
                passed=True,
                source="pdb",
                external_ref="RUN-1",
                payload={"results": {"WEIGHT": 0.14}},
            )
        )
        action = _action(
            session,
            tudo["id"],
            kind="upload_test_run",
            payload={
                "component_sn": SN,
                "test_type": "MODULE_BOW",
                "passed": True,
                "run_number": "7",
            },
        )
        preview = build_component_preview(session, component, client.app.state.settings)

    checks = {row["test_type"]: row["status"] for row in preview["projected"]["checks"]}
    assert checks["MODULE_BOW"] == "pending"
    tests = preview["projected"]["tests"]
    assert any(row["external_ref"] == "RUN-1" and row["ghost"] is False for row in tests)
    ghost = next(row for row in tests if row["ghost"])
    assert ghost["test_type"] == "MODULE_BOW"
    assert ghost["outbox_action_id"] == action.id


def test_upload_ghost_uses_the_linked_ingest_payload(session_factory, client, tudo):
    with session_factory() as session:
        component = _component(session, stage="GLUED")
        ingest = IngestFile(
            filename="manual-module-bow.json",
            sha256="a" * 64,
            size_bytes=123,
            status="proposed",
            component_sn=SN,
            test_type="MODULE_BOW",
            parser="manual-entry",
            payload={
                "component": SN,
                "testType": "MODULE_BOW",
                "runNumber": "12",
                "date": "2026-08-26T12:30:00Z",
                "passed": False,
                "problems": True,
                "properties": {"TEMPERATURE": 21.5},
                "results": {"BOW": 18.25},
                "result_meta": {"BOW": {"name": "Bow [um]"}},
            },
            uploaded_by="operator@example.org",
        )
        session.add(ingest)
        session.flush()
        action = _action(
            session,
            tudo["id"],
            kind="upload_test_run",
            payload={
                "ingest_file_id": ingest.id,
                "component_sn": SN,
                "test_type": "MODULE_BOW",
                # Deliberately stale summary values: the referenced ingest is
                # the authoritative source for the ghost detail.
                "passed": True,
                "run_number": "1",
            },
        )
        ingest.outbox_action_id = action.id
        session.flush()

        preview = build_component_preview(session, component, client.app.state.settings)

    ghost = next(row for row in preview["projected"]["tests"] if row["ghost"])
    assert ghost["test_type"] == "MODULE_BOW"
    assert ghost["passed"] is False
    assert ghost["run_number"] == "12"
    assert ghost["measured_at"].isoformat() == "2026-08-26T12:30:00+00:00"
    assert ghost["properties"] == {"TEMPERATURE": 21.5}
    assert ghost["results"] == {"BOW": 18.25}
    assert ghost["result_meta"] == {"BOW": {"name": "Bow [um]"}}


def test_preview_attachments_match_the_safe_local_test_output(
    client, session_factory, tudo
):
    with session_factory() as session:
        _component(session)
        session.add(
            TestRunEvidence(
                component_sn=SN,
                test_type="VISUAL_INSPECTION",
                passed=True,
                source="pdb",
                external_ref="RUN-IMAGE",
                payload={
                    "attachments": [
                        {
                            "code": "raw-code",
                            "url": "https://example.invalid/share?token=must-not-leak",
                        }
                    ]
                },
            )
        )
        session.add(
            TestRunAttachment(
                component_sn=SN,
                test_type="VISUAL_INSPECTION",
                test_run_ref="RUN-IMAGE",
                source="share_link",
                pdb_code="local-code",
                filename="inspection.jpg",
                content_type="image/jpeg",
                title="Inspection",
                size_bytes=321,
            )
        )
        session.commit()

    authenticate(client, session_factory, role="viewer")
    regular = client.get(f"/api/components/{SN}/tests")
    preview = client.get(f"/api/components/{SN}/preview")

    assert regular.status_code == 200, regular.text
    assert preview.status_code == 200, preview.text
    preview_attachment = preview.json()["projected"]["tests"][0]["attachments"]
    assert preview_attachment == regular.json()[0]["attachments"]
    assert preview_attachment == [
        {
            "code": "local-code",
            "test_type": "VISUAL_INSPECTION",
            "test_run_ref": "RUN-IMAGE",
            "filename": "inspection.jpg",
            "content_type": "image/jpeg",
            "title": "Inspection",
            "size_bytes": 321,
            "stored": False,
            "is_image": True,
        }
    ]
    assert "url" not in preview_attachment[0]


def test_non_dummy_component_is_truthfully_not_submittable(session_factory, client, tudo):
    with session_factory() as session:
        component = _component(session, dummy=False)
        _action(
            session,
            tudo["id"],
            kind="stage_move",
            payload={"sn": SN, "to_stage": "GLUED"},
        )
        preview = build_component_preview(session, component, client.app.state.settings)

    staged = preview["staged_actions"][0]
    assert staged["submittable"] is False
    assert staged["submittable_reason"] == "not_dummy"


def test_terminal_actions_do_not_appear_in_the_projection(session_factory, client, tudo):
    with session_factory() as session:
        component = _component(session)
        _action(
            session,
            tudo["id"],
            kind="stage_move",
            payload={"sn": SN, "to_stage": "GLUED"},
            status="confirmed",
        )
        _action(
            session,
            tudo["id"],
            kind="upload_test_run",
            payload={"component_sn": SN, "test_type": "MODULE_BOW"},
            status="cancelled",
        )
        preview = build_component_preview(session, component, client.app.state.settings)

    assert preview["staged_actions"] == []
    assert preview["projected"]["stage"] == component.stage
    assert preview["projected"]["tests"] == []


def test_preview_endpoint_is_authenticated_and_local(client, session_factory, tudo):
    with session_factory() as session:
        _component(session)
        session.commit()

    assert client.get(f"/api/components/{SN}/preview").status_code == 401
    authenticate(client, session_factory, role="viewer")
    client.app.state.pdb_gateway = object()  # would fail immediately if consulted

    response = client.get(f"/api/components/{SN}/preview")

    assert response.status_code == 200, response.text
    assert response.json()["projected"]["stage"] == "HV_TAB_ATTACHED"


def test_preview_endpoint_returns_404_for_unknown_component(
    client, session_factory, tudo
):
    authenticate(client, session_factory, role="viewer")
    response = client.get("/api/components/20USEM29999999/preview")
    assert response.status_code == 404
