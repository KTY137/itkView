# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-FileComment: itkflow-c61040c3b97a
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


def _row_for(preview, stage, test_type):
    """Find a worksheet row by group stage (``None`` selects "Additional")."""
    for group in preview["worksheet"]["groups"]:
        if group["stage"] == stage:
            for row in group["rows"]:
                if row["test_type"] == test_type:
                    return row
    raise AssertionError(f"No worksheet row for stage={stage!r} test_type={test_type!r}")


def test_empty_preview_matches_the_current_mirror(session_factory, client, tudo):
    with session_factory() as session:
        component = _component(session)
        preview = build_component_preview(session, component, client.app.state.settings)

    assert preview["current"]["stage"] == "HV_TAB_ATTACHED"
    assert preview["projected"]["stage"] == "HV_TAB_ATTACHED"
    assert preview["staged_actions"] == []
    assert preview["projected"]["ghost_tests"] == []


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
    ghosts = preview["projected"]["ghost_tests"]
    # Ghosts only: the mirrored RUN-1 is represented by its worksheet summary,
    # never by a second full copy of its measured values in this response.
    assert all(row["ghost"] is True for row in ghosts)
    assert [row["external_ref"] for row in ghosts] == [None]
    ghost = ghosts[0]
    assert ghost["test_type"] == "MODULE_BOW"
    assert ghost["outbox_action_id"] == action.id
    assert _row_for(preview, "GLUED", "GLUE_WEIGHT")["latest"]["external_ref"] == "RUN-1"


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

    ghost = next(row for row in preview["projected"]["ghost_tests"] if row["ghost"])
    assert ghost["test_type"] == "MODULE_BOW"
    assert ghost["passed"] is False
    assert ghost["run_number"] == "12"
    assert ghost["measured_at"].isoformat() == "2026-08-26T12:30:00+00:00"
    assert ghost["properties"] == {"TEMPERATURE": 21.5}
    assert ghost["results"] == {"BOW": 18.25}
    assert ghost["result_meta"] == {"BOW": {"name": "Bow [um]"}}


def test_preview_leaves_mirrored_runs_to_the_tests_endpoint(
    client, session_factory, tudo
):
    """Payload contract (review finding I3): mirrored runs — and therefore the
    raw evidence payload with its share URLs and measured arrays — are not part
    of the preview at all. The preview only summarises them in the worksheet;
    the safe local attachment read model is served by the tests endpoint the
    module page calls lazily."""
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
    body = preview.json()
    assert body["projected"]["ghost_tests"] == []
    assert "must-not-leak" not in preview.text
    row = next(
        row
        for group in body["worksheet"]["groups"]
        for row in group["rows"]
        if row["test_type"] == "VISUAL_INSPECTION"
    )
    assert row["latest"]["attachment_count"] == 1

    mirrored_attachment = regular.json()[0]["attachments"]
    assert mirrored_attachment == [
        {
            "source": "share_link",
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
    assert "url" not in mirrored_attachment[0]


def test_mirrored_runs_never_travel_with_the_preview(client, session_factory, tudo):
    """Finding I3: the module page must get *lighter*, not heavier.

    A single mirrored IV sweep is worth more bytes than the whole rest of this
    response, and the page already fetches the run list lazily, so no mirrored
    measured value may be serialized here — only the worksheet summary of it.
    """
    sweep = [round(-0.5 * index, 3) for index in range(200)]
    with session_factory() as session:
        _component(session, stage="GLUED")
        for index in range(3):
            session.add(
                TestRunEvidence(
                    component_sn=SN,
                    test_type="MODULE_IV_PS_V1",
                    passed=True,
                    source="pdb",
                    external_ref=f"RUN-IV-{index}",
                    payload={
                        "results": {"VOLTAGE": sweep, "CURRENT": sweep},
                        "properties": {"TEMPERATURE": 21.5},
                    },
                )
            )
        session.commit()

    authenticate(client, session_factory, role="viewer")
    response = client.get(f"/api/components/{SN}/preview")

    assert response.status_code == 200, response.text
    assert response.json()["projected"]["ghost_tests"] == []
    # 3 runs x 400 points: if any of them were still projected in full the
    # response could not possibly stay this small.
    assert len(response.content) < 8_000, len(response.content)
    row = next(
        row
        for group in response.json()["worksheet"]["groups"]
        for row in group["rows"]
        if row["test_type"] == "MODULE_IV_PS_V1"
    )
    assert row["run_count"] == 3
    assert {entry["points"] for entry in row["latest"]["arrays"]} == {len(sweep)}


def test_open_actions_are_narrowed_in_sql_but_decided_in_python(
    session_factory, client, tudo
):
    """Scaling guard: the action query filters on the payload text so a busy
    institute's whole backlog is not loaded per module page open — while
    `_targets_component` stays the only authority on membership.

    The child action below is the case that pins both halves: its payload
    mentions the serial (so the SQL narrowing lets it through) under a key that
    does not target this component (so it must still be dropped).
    """
    from app.preview import _open_actions_for

    class _CapturingSession:
        """Delegates to a real Session, recording every statement it runs."""

        def __init__(self, real):
            self._real = real
            self.statements: list = []

        def scalars(self, statement):
            self.statements.append(statement)
            return self._real.scalars(statement)

        def __getattr__(self, name):
            return getattr(self._real, name)

    with session_factory() as session:
        component = _component(session)
        mine = _action(
            session,
            tudo["id"],
            kind="stage_move",
            payload={"sn": SN, "to_stage": "GLUED"},
        )
        _action(
            session,
            tudo["id"],
            kind="stage_move",
            payload={"sn": "20USEM20000992", "to_stage": "GLUED"},
        )
        as_child = _action(
            session,
            tudo["id"],
            kind="assemble_component",
            payload={"parent_sn": "20USEM20000992", "child_sn": SN, "slot": "H0"},
        )
        capturing = _CapturingSession(session)
        selected = _open_actions_for(capturing, SN)
        preview = build_component_preview(session, component, client.app.state.settings)

    # Pin the narrowing itself: without it the statement is a plain status
    # filter and every open action in the institute is loaded and decoded.
    compiled = str(capturing.statements[0]).upper()
    assert "LIKE" in compiled
    assert "OUTBOX_ACTION.PAYLOAD" in compiled

    assert [action.id for action in selected] == [mine.id]
    assert as_child.id not in [row["id"] for row in preview["staged_actions"]]
    assert [row["id"] for row in preview["staged_actions"]] == [mine.id]


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
    assert preview["projected"]["ghost_tests"] == []


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


def test_a_slots_only_assembly_action_is_not_marked_validation_failed(
    session_factory, client, tudo, as_operator
):
    """A staged action whose tools live only in slot combinations (no legacy
    default tool) must be evaluated, not dismissed as validation_failed just
    because `tool_id` is absent (follow-up to the multi-slot contract)."""
    from test_assembly import seed_multi_slot_assembly

    seed = seed_multi_slot_assembly(session_factory, tudo)
    jig_id = seed["hybrid_glue_jig_tool_id"]

    staged = client.post(
        "/api/assembly/actions",
        json={
            "parent_sn": seed["parent_sn"],
            "child_sn": seed["child_sn"],
            "slot": "H0",
            "glue_batch_id": seed["glue_batch_id"],
            "tools": {
                "tool": [seed["tool_id"]],
                "hybrid_glue_jig": [jig_id, jig_id],
            },
        },
    )
    assert staged.status_code == 201, staged.text
    # The canonical payload keeps tool_id for the single default tool; strip it
    # to model an action recorded purely through slots.
    action_id = staged.json()["action"]["id"]
    from app.models import OutboxAction

    with session_factory() as session:
        action = session.get(OutboxAction, action_id)
        payload = dict(action.payload)
        payload.pop("tool_id", None)
        payload.pop("expected_tool_code", None)
        action.payload = payload
        session.commit()

    preview = client.get(f"/api/components/{seed['parent_sn']}/preview")
    assert preview.status_code == 200, preview.text
    actions = preview.json()["staged_actions"]
    target = next(entry for entry in actions if entry["id"] == action_id)
    assert target["submittable_reason"] != "validation_failed"


# --- H1 worksheet ------------------------------------------------------------
#
# The worksheet contract (group formation, latest-run selection, scalar/array
# compactness, Additional-group rules) lives in tests/test_preview_worksheet.py
# now; keeping it duplicated here in near-identical scenarios was pure
# redundancy (finding M2/M3). This file keeps exactly two worksheet tests: the
# checks-versus-worksheet agreement test, and one true end-to-end wire test
# that exercises the real HTTP endpoint plus Pydantic response validation
# (which a direct `build_component_preview` call never does).


def test_worksheet_pending_status_agrees_with_the_projected_check(
    session_factory, client, tudo
):
    with session_factory() as session:
        component = _component(session, stage="GLUED")
        action = _action(
            session,
            tudo["id"],
            kind="upload_test_run",
            payload={"component_sn": SN, "test_type": "MODULE_BOW", "run_number": "9"},
        )
        preview = build_component_preview(session, component, client.app.state.settings)

    checks = {row["test_type"]: row["status"] for row in preview["projected"]["checks"]}
    row = _row_for(preview, "GLUED", "MODULE_BOW")
    assert row["status"] == "pending"
    assert checks["MODULE_BOW"] == "pending"
    assert row["run_count"] == 0
    assert row["latest"] is None
    assert row["staged"] == [{"outbox_action_id": action.id, "status": "draft"}]


def test_worksheet_run_number_survives_a_malformed_mirrored_value_over_the_wire(
    client, session_factory, tudo
):
    """End-to-end regression for finding M1: a mirrored payload's run_number
    is untrusted external data. Before the guard, a non-``str | int`` value
    (e.g. a float) raised a Pydantic ``ValidationError`` inside
    ``ComponentPreviewOut.model_validate`` and 500'd the whole module page;
    `_worksheet_latest_run` must sanitize it to ``None`` the same way the
    ghost path (`_ghost_test`) already does for staged uploads, and the
    endpoint must still return 200 with the full worksheet contract intact."""
    with session_factory() as session:
        _component(session, stage="GLUED")
        session.add(
            TestRunEvidence(
                component_sn=SN,
                test_type="MODULE_BOW",
                passed=True,
                source="pdb",
                external_ref="RUN-BOW",
                payload={"run_number": 3.5, "results": {"BOW": 12.0}},
            )
        )
        session.commit()

    authenticate(client, session_factory, role="viewer")
    response = client.get(f"/api/components/{SN}/preview")

    assert response.status_code == 200, response.text
    row = next(
        row
        for group in response.json()["worksheet"]["groups"]
        for row in group["rows"]
        if row["test_type"] == "MODULE_BOW"
    )
    assert row["latest"]["run_number"] is None
    assert row["status"] == "passed"


# --- Finding I1: engine-independent NULL ordering ----------------------------


def test_satisfied_test_results_orders_measured_at_nulls_first(session_factory):
    """Pin the SQL ORDER BY clause itself, not just SQLite's behaviour.

    SQLite happens to sort NULLs first in ascending order, so a naive
    ``order_by(measured_at, ...)`` looks correct under this whole suite even
    though PostgreSQL — what `deploy/docker-compose.yml` actually runs — sorts
    NULLs *last* in ascending order there, which would let a NULL-dated run
    win `satisfied_test_results`'s last-wins loop over a genuinely newer dated
    run. This suite has no PostgreSQL engine available to catch that directly
    (a real cross-engine guarantee still needs a PostgreSQL job in CI); this
    test instead pins the NULLS FIRST modifier on the compiled statement so
    the invariant can never silently regress back to implicit engine
    behaviour.
    """
    from app.stage_service import satisfied_test_results

    class _CapturingSession:
        """Delegates to a real Session, recording every statement it runs."""

        def __init__(self, real):
            self._real = real
            self.captured_statements: list = []

        def scalars(self, statement):
            self.captured_statements.append(statement)
            return self._real.scalars(statement)

        def execute(self, statement):
            self.captured_statements.append(statement)
            return self._real.execute(statement)

        def __getattr__(self, name):
            return getattr(self._real, name)

    with session_factory() as session:
        capturing = _CapturingSession(session)
        satisfied_test_results(capturing, SN)

    evidence_statement = next(
        statement
        for statement in capturing.captured_statements
        if "test_run_evidence.measured_at" in str(statement)
    )
    assert "test_run_evidence.measured_at NULLS FIRST" in str(evidence_statement)
