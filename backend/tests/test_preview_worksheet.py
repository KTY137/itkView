"""H1 worksheet block of the component preview (spec 2026-08-25, section H).

Contract under test: one group per stage of the institute's stage model (all
stages, including not-yet-reached ones) plus a trailing ``stage: None``
"Additional" group for mirrored test types outside the model; per-row status
with the same semantics as the requirement checks; a compact ``latest`` run
whose arrays are point counts only — raw measurement arrays must never leave
the server through the worksheet.
"""

import json
from datetime import datetime, timezone

from authutil import authenticate, create_institute_profile
from sqlalchemy import event

from app.models import Component, OutboxAction, TestRunAttachment, TestRunEvidence
from app.preview import build_component_preview

SN = "20USEM20000662"
SENSOR_SN = "20USES40000771"


def _component(
    session,
    *,
    sn=SN,
    component_type="MODULE",
    type_code="R5M0",
    institute_code="TUDO",
    stage="GLUED",
):
    component = Component(
        sn=sn,
        component_type=component_type,
        type_code=type_code,
        stage=stage,
        location=institute_code,
        institute_code=institute_code,
        is_dummy=True,
    )
    session.add(component)
    session.flush()
    return component


def _evidence(
    session,
    *,
    sn=SN,
    test_type,
    passed,
    external_ref,
    measured_at=None,
    run_state=None,
    **payload,
):
    row = TestRunEvidence(
        component_sn=sn,
        test_type=test_type,
        passed=passed,
        source="pdb",
        external_ref=external_ref,
        measured_at=measured_at,
        run_state=run_state,
        payload=payload or {"results": {}},
    )
    session.add(row)
    session.flush()
    return row


def _upload_action(session, institute_id, *, test_type, status="draft", sn=SN, **extra):
    external_ref = extra.pop("external_ref", None)
    if status == "confirmed" and external_ref is None:
        external_ref = f"CONFIRMED-{sn}-{test_type}"
    action = OutboxAction(
        institute_id=institute_id,
        kind="upload_test_run",
        payload={"component_sn": sn, "test_type": test_type, **extra},
        status=status,
        created_by="operator@example.org",
        external_ref=external_ref,
    )
    session.add(action)
    session.flush()
    return action


def _groups_by_stage(preview):
    return {group["stage"]: group for group in preview["worksheet"]["groups"]}


def _row(preview, stage, test_type):
    for row in _groups_by_stage(preview)[stage]["rows"]:
        if row["test_type"] == test_type:
            return row
    raise AssertionError(f"no worksheet row {test_type!r} in group {stage!r}")


# --- Group formation --------------------------------------------------------


def test_groups_follow_the_institute_profile_not_the_seed_default(
    session_factory, client
):
    """Requirements come from the profile; a test the profile no longer
    requires falls into the Additional group when it has mirrored runs."""
    create_institute_profile(
        session_factory,
        code="EXIN",
        name="Example Institute",
        settings={
            "stage_requirements": {
                "GLUED": ["CUSTOM_GLUE_CHECK"],
                "STITCH_BONDING": ["BOND_PULL_TEST"],
            }
        },
    )
    with session_factory() as session:
        component = _component(session, institute_code="EXIN", stage="GLUED")
        # GLUE_WEIGHT is a seed-default GLUED requirement, but this profile
        # replaced the GLUED list — its mirrored run is now "additional".
        _evidence(
            session,
            test_type="GLUE_WEIGHT",
            passed=True,
            external_ref="RUN-GW",
            results={"WEIGHT": 0.15},
        )
        preview = build_component_preview(session, component, client.app.state.settings)

    groups = _groups_by_stage(preview)
    assert [r["test_type"] for r in groups["GLUED"]["rows"]] == ["CUSTOM_GLUE_CHECK"]
    assert [r["test_type"] for r in groups["STITCH_BONDING"]["rows"]] == [
        "BOND_PULL_TEST"
    ]
    additional = preview["worksheet"]["groups"][-1]
    assert additional["stage"] is None
    assert [r["test_type"] for r in additional["rows"]] == ["GLUE_WEIGHT"]
    assert additional["rows"][0]["status"] == "passed"
    assert additional["rows"][0]["run_count"] == 1


def test_reached_flag_at_the_first_and_last_stage_of_the_model(
    session_factory, client, tudo
):
    with session_factory() as session:
        first = _component(session, sn=SN, stage="HV_TAB_ATTACHED")
        last = _component(session, sn="20USEM20000663", stage="FINISHED")
        first_preview = build_component_preview(
            session, first, client.app.state.settings
        )
        last_preview = build_component_preview(session, last, client.app.state.settings)

    first_flags = [g["reached"] for g in first_preview["worksheet"]["groups"]]
    assert first_flags == [True, False, False, False, False, False]
    assert all(g["reached"] for g in last_preview["worksheet"]["groups"])


def test_component_type_outside_the_stage_model_gets_every_group_reached(
    session_factory, client, tudo
):
    """A sensor's stage is not in the (module) stage model. We cannot know how
    far an off-model stage actually progressed (this is the common case for
    real TUDO modules too: FAILED and other terminal stages sit outside the
    ordered model), so every group renders as reached rather than dimming the
    whole sheet as not-yet-reached; its mirrored tests still live in the
    Additional group."""
    with session_factory() as session:
        component = _component(
            session,
            sn=SENSOR_SN,
            component_type="SENSOR",
            type_code="ATLAS18R5",
            stage="APPROVED",
        )
        _evidence(
            session,
            sn=SENSOR_SN,
            test_type="SENSOR_IV",
            passed=False,
            external_ref="RUN-SIV",
            results={"CURRENT_AT_500V": 1.2e-8},
        )
        preview = build_component_preview(session, component, client.app.state.settings)

    ordered = [g for g in preview["worksheet"]["groups"] if g["stage"] is not None]
    assert ordered, "the model's stage groups must still be present"
    assert all(g["reached"] is True for g in ordered)
    assert all(r["status"] == "missing" for g in ordered for r in g["rows"])
    row = _row(preview, None, "SENSOR_IV")
    assert row["status"] == "failed"
    assert row["latest"]["external_ref"] == "RUN-SIV"


def test_component_without_an_institute_profile_uses_the_seed_model(
    session_factory, client
):
    """No InstituteProfile row at all must not crash the worksheet build."""
    with session_factory() as session:
        component = _component(session, institute_code="NOPR", stage="GLUED")
        preview = build_component_preview(session, component, client.app.state.settings)

    stages = [g["stage"] for g in preview["worksheet"]["groups"]]
    assert stages == [
        "HV_TAB_ATTACHED",
        "GLUED",
        "STITCH_BONDING",
        "BONDED",
        "TESTED",
        "FINISHED",
    ]
    # A stage with no required tests (STITCH_BONDING in the seed model) still
    # gets its own group, just an empty one — dropping the group entirely
    # would silently break "one group per stage" for that stage.
    rows_by_stage = {g["stage"]: g["rows"] for g in preview["worksheet"]["groups"]}
    assert rows_by_stage["STITCH_BONDING"] == []


def test_off_model_stage_on_an_in_model_component_type_reaches_every_group(
    session_factory, client, tudo
):
    """The domain-realistic case (spec H1): a MODULE stays a MODULE, but its
    *stage string* (e.g. TUDO's real ``FAILED``) is simply absent from the
    ordered stage model. Distinct from an off-model *component type* (covered
    above): both hit the ``current_index is None`` branch, but only this one
    proves it also holds when the component type itself is in-model."""
    with session_factory() as session:
        component = _component(session, stage="SCRAPPED")
        preview = build_component_preview(session, component, client.app.state.settings)

    assert preview["worksheet"]["groups"]
    assert all(group["reached"] is True for group in preview["worksheet"]["groups"])


# --- Latest-run selection ---------------------------------------------------


def test_latest_run_is_the_newest_by_measured_at(session_factory, client, tudo):
    with session_factory() as session:
        component = _component(session, stage="GLUED")
        _evidence(
            session,
            test_type="MODULE_BOW",
            passed=False,
            external_ref="RUN-JAN",
            measured_at=datetime(2026, 1, 5, tzinfo=timezone.utc),
            results={"BOW": 30.0},
        )
        # Deliberately inserted out of chronological order: insertion order and
        # id must not decide, measured_at must.
        _evidence(
            session,
            test_type="MODULE_BOW",
            passed=True,
            external_ref="RUN-MAR",
            measured_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
            results={"BOW": 11.0},
        )
        _evidence(
            session,
            test_type="MODULE_BOW",
            passed=False,
            external_ref="RUN-FEB",
            measured_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
            results={"BOW": 25.0},
        )
        preview = build_component_preview(session, component, client.app.state.settings)

    row = _row(preview, "GLUED", "MODULE_BOW")
    assert row["run_count"] == 3
    assert row["latest"]["external_ref"] == "RUN-MAR"
    # The row status must agree with the run it presents as latest.
    assert row["status"] == "passed"
    assert row["latest"]["passed"] is True


def test_latest_run_without_any_dates_falls_back_to_sync_order(
    session_factory, client, tudo
):
    """All-NULL measured_at (common for hand-mirrored legacy runs) must not
    crash and must pick the most recently synced row — the same winner the
    status projection uses."""
    with session_factory() as session:
        component = _component(session, stage="GLUED")
        _evidence(
            session,
            test_type="MODULE_BOW",
            passed=True,
            external_ref="RUN-OLD-SYNC",
            results={"BOW": 12.0},
        )
        newer = _evidence(
            session,
            test_type="MODULE_BOW",
            passed=False,
            external_ref="RUN-NEW-SYNC",
            results={"BOW": 44.0},
        )
        newer.synced_at = datetime(2030, 1, 1, tzinfo=timezone.utc)
        session.flush()
        preview = build_component_preview(session, component, client.app.state.settings)

    row = _row(preview, "GLUED", "MODULE_BOW")
    assert row["latest"]["external_ref"] == "RUN-NEW-SYNC"
    assert row["latest"]["measured_at"] is None
    assert row["status"] == "failed"


def test_latest_run_survives_mixed_naive_and_aware_timestamps(
    session_factory, client, tudo
):
    """Regression: SQLite loads DateTime columns as naive values while fresh
    ORM assignments are timezone-aware; the latest-run selection must not
    crash on the mix (it 500'd the whole preview) and must treat naive
    timestamps as UTC."""
    with session_factory() as session:
        component = _component(session, stage="GLUED")
        _evidence(
            session,
            test_type="MODULE_BOW",
            passed=False,
            external_ref="RUN-NAIVE",
            measured_at=datetime(2026, 1, 1),  # naive, as loaded from SQLite
            results={"BOW": 30.0},
        )
        _evidence(
            session,
            test_type="MODULE_BOW",
            passed=True,
            external_ref="RUN-AWARE",
            measured_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
            results={"BOW": 11.0},
        )
        preview = build_component_preview(session, component, client.app.state.settings)

    row = _row(preview, "GLUED", "MODULE_BOW")
    assert row["latest"]["external_ref"] == "RUN-AWARE"
    assert row["run_count"] == 2


def test_latest_run_prefers_a_dated_measurement_over_a_newer_null(
    session_factory, client, tudo
):
    """A dated run must win even against a NULL-dated run that is "newer" by
    every other signal (higher id, inserted later, synced far later) — this is
    the exact ranking Finding I1 depends on being engine-independent."""
    with session_factory() as session:
        component = _component(session, stage="GLUED")
        _evidence(
            session,
            test_type="MODULE_BOW",
            passed=False,
            external_ref="RUN-DATED",
            measured_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
            results={"BOW": 12.5},
        )
        newer_but_null = _evidence(
            session,
            test_type="MODULE_BOW",
            passed=True,
            external_ref="RUN-NULL",
            results={"BOW": 10.0},
        )
        newer_but_null.synced_at = datetime(2030, 1, 1, tzinfo=timezone.utc)
        session.flush()
        preview = build_component_preview(session, component, client.app.state.settings)

    row = _row(preview, "GLUED", "MODULE_BOW")
    assert row["run_count"] == 2
    assert row["latest"]["external_ref"] == "RUN-DATED"
    assert row["latest"]["passed"] is False


def test_latest_run_attachment_count_matches_only_its_own_run(
    session_factory, client, tudo
):
    with session_factory() as session:
        component = _component(session, stage="GLUED")
        _evidence(
            session,
            test_type="MODULE_BOW",
            passed=True,
            external_ref="RUN-BOW",
            results={"BOW": 12.5},
        )
        session.add(
            TestRunAttachment(
                component_sn=SN,
                test_type="MODULE_BOW",
                test_run_ref="RUN-BOW",
                pdb_code="bow-att-1",
                filename="bow-1.png",
            )
        )
        session.add(
            TestRunAttachment(
                component_sn=SN,
                test_type="MODULE_BOW",
                test_run_ref="RUN-BOW",
                pdb_code="bow-att-2",
                filename="bow-2.png",
            )
        )
        # Belongs to a different run and must not be counted here.
        session.add(
            TestRunAttachment(
                component_sn=SN,
                test_type="MODULE_BOW",
                test_run_ref="OTHER-RUN",
                pdb_code="bow-att-3",
                filename="bow-3.png",
            )
        )
        session.flush()
        preview = build_component_preview(session, component, client.app.state.settings)

    row = _row(preview, "GLUED", "MODULE_BOW")
    assert row["latest"]["attachment_count"] == 2


# --- Compactness: scalars vs arrays -----------------------------------------


def test_results_split_into_named_scalars_and_point_count_arrays(
    session_factory, client, tudo
):
    """Renamed from ``..._keep_insertion_order_...``: this fixture has no null
    scalars, so it never exercised the stable-partition rule despite the old
    name's claim (see
    ``test_scalars_put_non_null_values_first_without_reordering_within_a_partition``
    below for that). What it does cover: scalar vs. array/empty-array
    classification and the ``result_meta`` name lookup with a code fallback."""
    with session_factory() as session:
        component = _component(session, stage="HV_TAB_ATTACHED")
        _evidence(
            session,
            test_type="MODULE_IV_PS_V1",
            passed=True,
            external_ref="RUN-IV",
            results={
                "HUMIDITY": 31.0,
                "VOLTAGE": [0, -50, -100],
                "TEMPERATURE": 21.5,
                "CURRENT": [],  # an empty array is still an array: 0 points
                "COMMENT": "stable",
            },
            result_meta={"TEMPERATURE": {"name": "Temperature [C]"}},
        )
        preview = build_component_preview(session, component, client.app.state.settings)

    latest = _row(preview, "HV_TAB_ATTACHED", "MODULE_IV_PS_V1")["latest"]
    assert latest["scalars"] == [
        {"code": "HUMIDITY", "name": "HUMIDITY", "value": 31.0},
        {"code": "TEMPERATURE", "name": "Temperature [C]", "value": 21.5},
        {"code": "COMMENT", "name": "COMMENT", "value": "stable"},
    ]
    assert latest["arrays"] == [
        {"code": "VOLTAGE", "name": "VOLTAGE", "points": 3, "kind": "array"},
        {"code": "CURRENT", "name": "CURRENT", "points": 0, "kind": "array"},
    ]


def test_dict_valued_results_are_summarised_as_a_map_not_a_scalar(
    session_factory, client, tudo
):
    """Real MODULE_METROLOGY payloads carry per-position dicts (e.g. glue
    thickness per pad). A dict is exactly as spammy inline as a raw array and
    must be summarised the same way — never dumped into scalars."""
    with session_factory() as session:
        component = _component(session, stage="GLUED")
        _evidence(
            session,
            test_type="MODULE_METROLOGY",
            passed=True,
            external_ref="RUN-METRO",
            results={
                "Capacitor heights [um]": {},
                "Hybrid glue thickness [um]": {
                    "ABC_R5H1_0": 2.1,
                    "ABC_R5H1_1": 2.4,
                    "ABC_R5H1_2": 1.9,
                },
                "Comment": "nominal",
            },
        )
        preview = build_component_preview(session, component, client.app.state.settings)

    latest = _row(preview, "GLUED", "MODULE_METROLOGY")["latest"]
    assert latest["scalars"] == [{"code": "Comment", "name": "Comment", "value": "nominal"}]
    assert latest["arrays"] == [
        {
            "code": "Capacitor heights [um]",
            "name": "Capacitor heights [um]",
            "points": 0,
            "kind": "map",
        },
        {
            "code": "Hybrid glue thickness [um]",
            "name": "Hybrid glue thickness [um]",
            "points": 3,
            "kind": "map",
        },
    ]
    for scalar in latest["scalars"]:
        assert not isinstance(scalar["value"], dict)


def test_scalars_put_non_null_values_first_without_reordering_within_a_partition(
    session_factory, client, tudo
):
    """VISUAL_INSPECTION-style payloads front-load unfilled slots: the first
    three results are null and the fourth carries a value. The frontend shows
    only the first few scalars, so null-first ordering would hide the one
    value that matters. This is the true stable-partition test — its fixture
    actually contains null scalars, unlike the insertion-order test above."""
    with session_factory() as session:
        component = _component(session, stage="HV_TAB_ATTACHED")
        _evidence(
            session,
            test_type="VISUAL_INSPECTION",
            passed=True,
            external_ref="RUN-VI",
            results={
                "Location 1": None,
                "Damage Type 1": None,
                "Defect 1 - Images": None,
                "Location 2": "top-left",
                "Damage Type 2": None,
            },
        )
        preview = build_component_preview(session, component, client.app.state.settings)

    latest = _row(preview, "HV_TAB_ATTACHED", "VISUAL_INSPECTION")["latest"]
    # The one non-null value moves to the front; the nulls keep their original
    # relative order behind it (a stable partition, not a sort).
    assert latest["scalars"] == [
        {"code": "Location 2", "name": "Location 2", "value": "top-left"},
        {"code": "Location 1", "name": "Location 1", "value": None},
        {"code": "Damage Type 1", "name": "Damage Type 1", "value": None},
        {"code": "Defect 1 - Images", "name": "Defect 1 - Images", "value": None},
        {"code": "Damage Type 2", "name": "Damage Type 2", "value": None},
    ]


def test_raw_array_values_never_reach_the_wire_through_the_worksheet(
    client, session_factory, tudo
):
    """End-to-end over the endpoint: sentinel array points must be absent from
    the serialized preview (in a required-test row AND in the Additional
    group), while the on-demand tests endpoint still carries them.

    Since finding I3 the whole preview response is the assertion target, not
    just its worksheet block: mirrored runs no longer travel with the preview
    at all, so a raw array anywhere in that payload is a regression."""
    sentinels = [101010, 202020, 303030]
    with session_factory() as session:
        _component(session, stage="HV_TAB_ATTACHED")
        _evidence(
            session,
            test_type="MODULE_IV_PS_V1",
            passed=True,
            external_ref="RUN-IV",
            run_number="42",
            results={"VOLTAGE": sentinels, "TEMPERATURE": 21.5},
        )
        _evidence(
            session,
            test_type="EXTRA_SCAN",
            passed=True,
            external_ref="RUN-EXTRA",
            results={"TRACE": sentinels},
        )
        session.commit()

    authenticate(client, session_factory, role="viewer")
    response = client.get(f"/api/components/{SN}/preview")
    assert response.status_code == 200, response.text
    body = response.json()

    for sentinel in sentinels:
        assert str(sentinel) not in response.text
    # Prove the sentinels do exist server-side and survive on the endpoint that
    # the run list actually fetches, so the assertion above is meaningful.
    detail = client.get(f"/api/components/{SN}/tests")
    assert detail.status_code == 200, detail.text
    detail_wire = json.dumps(detail.json())
    for sentinel in sentinels:
        assert str(sentinel) in detail_wire

    iv_row = next(
        row
        for group in body["worksheet"]["groups"]
        for row in group["rows"]
        if row["test_type"] == "MODULE_IV_PS_V1"
    )
    assert iv_row["latest"]["run_number"] == "42"
    assert iv_row["latest"]["arrays"] == [
        {"code": "VOLTAGE", "name": "VOLTAGE", "points": 3, "kind": "array"}
    ]
    extra_group = body["worksheet"]["groups"][-1]
    assert extra_group["stage"] is None
    assert extra_group["rows"][0]["latest"]["arrays"][0]["points"] == 3


# --- Pending / staged interlocking ------------------------------------------


def test_open_actions_make_the_row_pending_and_are_listed_in_creation_order(
    session_factory, client, tudo
):
    with session_factory() as session:
        component = _component(session, stage="GLUED")
        _evidence(
            session,
            test_type="MODULE_BOW",
            passed=True,
            external_ref="RUN-BOW",
            results={"BOW": 12.0},
        )
        draft = _upload_action(session, tudo["id"], test_type="MODULE_BOW")
        # `failed` is not terminal (retryable) and must stay visible.
        failed = _upload_action(
            session, tudo["id"], test_type="MODULE_BOW", status="failed"
        )
        preview = build_component_preview(session, component, client.app.state.settings)

    row = _row(preview, "GLUED", "MODULE_BOW")
    # Open work overrides even passing evidence — never masquerade as done.
    assert row["status"] == "pending"
    assert row["staged"] == [
        {"outbox_action_id": draft.id, "status": "draft"},
        {"outbox_action_id": failed.id, "status": "failed"},
    ]
    # The mirrored run stays visible underneath the pending state.
    assert row["latest"]["external_ref"] == "RUN-BOW"
    assert row["run_count"] == 1
    # Worksheet and projected checks must tell the same story.
    checks = {c["test_type"]: c["status"] for c in preview["projected"]["checks"]}
    assert checks["MODULE_BOW"] == "pending"


def test_terminal_actions_leave_no_pending_or_staged_trace(
    session_factory, client, tudo
):
    with session_factory() as session:
        component = _component(session, stage="GLUED")
        _upload_action(session, tudo["id"], test_type="MODULE_BOW", status="cancelled")
        # A confirmed upload is terminal too, but it *is* satisfied evidence:
        # the row flips to passed even before the next mirror sync.
        _upload_action(
            session,
            tudo["id"],
            test_type="GLUE_WEIGHT",
            status="confirmed",
            passed=True,
        )
        preview = build_component_preview(session, component, client.app.state.settings)

    bow = _row(preview, "GLUED", "MODULE_BOW")
    assert bow["status"] == "missing"
    assert bow["staged"] == []
    glue = _row(preview, "GLUED", "GLUE_WEIGHT")
    assert glue["status"] == "passed"
    assert glue["staged"] == []
    assert glue["latest"] is None
    assert glue["run_count"] == 0


def test_row_statuses_always_agree_with_the_projected_checks(session_factory, client):
    """One mixed scenario, then a blanket consistency sweep, asserted per
    (group, row) — not by flattening rows into a single {test_type: status}
    dict. A flat dict silently collapses a test type required at two
    different stages into one entry, which would hide a divergence between
    the two rows it actually produces; the profile below deliberately makes
    MODULE_BOW required at two stages to exercise exactly that shape."""
    institute = create_institute_profile(
        session_factory,
        code="DUPR",
        name="Duplicate Requirement Institute",
        settings={
            "stage_requirements": {
                "HV_TAB_ATTACHED": ["VISUAL_INSPECTION", "MODULE_IV_PS_V1", "MODULE_BOW"],
                "GLUED": ["GLUE_WEIGHT", "MODULE_BOW", "MODULE_METROLOGY"],
            }
        },
    )
    with session_factory() as session:
        component = _component(session, institute_code="DUPR", stage="GLUED")
        _evidence(
            session,
            test_type="VISUAL_INSPECTION",
            passed=True,
            external_ref="RUN-VI",
            results={},
        )
        _evidence(
            session,
            test_type="MODULE_IV_PS_V1",
            passed=False,
            external_ref="RUN-IV",
            results={},
        )
        _upload_action(session, institute["id"], test_type="GLUE_WEIGHT")
        preview = build_component_preview(session, component, client.app.state.settings)

    checks_by_key = {
        (c["stage"], c["test_type"]): c["status"] for c in preview["projected"]["checks"]
    }
    assert checks_by_key == {
        ("HV_TAB_ATTACHED", "VISUAL_INSPECTION"): "passed",
        ("HV_TAB_ATTACHED", "MODULE_IV_PS_V1"): "failed",
        ("HV_TAB_ATTACHED", "MODULE_BOW"): "missing",
        ("GLUED", "GLUE_WEIGHT"): "pending",
        ("GLUED", "MODULE_BOW"): "missing",
        ("GLUED", "MODULE_METROLOGY"): "missing",
    }
    # `checks` only covers stages up to and including the projected stage;
    # restrict the sweep to those so a legitimately check-less future-stage
    # row (e.g. BONDED/TESTED here) isn't mistaken for a missing-check bug.
    covered_stages = {stage for stage, _ in checks_by_key}
    for group in preview["worksheet"]["groups"]:
        if group["stage"] not in covered_stages:
            continue
        for row in group["rows"]:
            key = (group["stage"], row["test_type"])
            assert key in checks_by_key, f"worksheet row {key} has no matching check"
            assert row["status"] == checks_by_key[key], key


# --- Additional group: sorting and the seed-default omission case ----------


def test_additional_group_covers_mirrored_types_outside_the_stage_model(
    session_factory, client, tudo
):
    with session_factory() as session:
        component = _component(session, stage="GLUED")
        _evidence(
            session,
            test_type="EXTRA_CHECK_B",
            passed=True,
            external_ref="RUN-EXTRA-B",
            results={"NOTE": "ok"},
        )
        _evidence(
            session,
            test_type="EXTRA_CHECK_A",
            passed=False,
            external_ref="RUN-EXTRA-A",
            results={"NOTE": "bad"},
        )
        preview = build_component_preview(session, component, client.app.state.settings)

    additional = preview["worksheet"]["groups"][-1]
    assert additional["stage"] is None
    assert additional["reached"] is True
    assert [row["test_type"] for row in additional["rows"]] == [
        "EXTRA_CHECK_A",
        "EXTRA_CHECK_B",
    ]
    assert {row["test_type"]: row["status"] for row in additional["rows"]} == {
        "EXTRA_CHECK_A": "failed",
        "EXTRA_CHECK_B": "passed",
    }


def test_additional_group_is_omitted_when_every_mirrored_type_is_required(
    session_factory, client, tudo
):
    """Distinct from the profile-override case above: this uses the plain
    seed-default model (no InstituteProfile override) to prove the omission
    rule holds there too, not only when a custom profile happens to line up."""
    with session_factory() as session:
        component = _component(session, stage="GLUED")
        _evidence(
            session,
            test_type="GLUE_WEIGHT",
            passed=True,
            external_ref="RUN-GLUE",
            results={"WEIGHT": 0.15},
        )
        preview = build_component_preview(session, component, client.app.state.settings)

    assert all(group["stage"] is not None for group in preview["worksheet"]["groups"])
    row = _row(preview, "GLUED", "GLUE_WEIGHT")
    assert row["status"] == "passed"
    assert row["run_count"] == 1


# --- Additional group visibility for staged/confirmed-only work ------------


def test_additional_group_shows_a_staged_only_test_type_with_no_mirrored_evidence(
    session_factory, client, tudo
):
    """MODULE_IV_AMAC is not a required test at TUDO (it lives in Additional).
    A first-ever staged upload of it has no mirrored evidence at all, so
    deriving the Additional group from evidence alone gives it no group to
    land in and the staged work becomes invisible on the worksheet."""
    with session_factory() as session:
        component = _component(session, stage="TESTED")
        action = _upload_action(session, tudo["id"], test_type="MODULE_IV_AMAC")
        preview = build_component_preview(session, component, client.app.state.settings)

    additional = preview["worksheet"]["groups"][-1]
    assert additional["stage"] is None
    row = next(r for r in additional["rows"] if r["test_type"] == "MODULE_IV_AMAC")
    assert row["status"] == "pending"
    assert row["latest"] is None
    assert row["run_count"] == 0
    assert row["staged"] == [{"outbox_action_id": action.id, "status": "draft"}]


def _child(session, parent, *, sn, component_type="SENSOR", type_code="ATLAS18R5", local_name=None):
    child = _component(
        session, sn=sn, component_type=component_type, type_code=type_code, stage="APPROVED"
    )
    child.local_name = local_name
    child.parent_id = parent.id
    session.flush()
    return child


# --- Withdrawn (PDB state='deleted') runs ------------------------------------


def test_a_withdrawn_run_is_never_the_latest_run(session_factory, client, tudo):
    """The PDB keeps serving a retracted run, so it reaches the mirror like any
    other. On the owner's data a whole block of implausible glue weights turned
    out to be exactly this. The newest *live* run must win even when a
    withdrawn run is strictly newer by every ordering signal."""
    with session_factory() as session:
        component = _component(session, stage="GLUED")
        _evidence(
            session,
            test_type="MODULE_BOW",
            passed=True,
            external_ref="RUN-LIVE",
            measured_at=datetime(2026, 1, 5, tzinfo=timezone.utc),
            results={"BOW": 11.0},
        )
        _evidence(
            session,
            test_type="MODULE_BOW",
            passed=False,
            external_ref="RUN-WITHDRAWN",
            measured_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
            run_state="deleted",
            results={"BOW": 1859.0},
        )
        preview = build_component_preview(session, component, client.app.state.settings)

    row = _row(preview, "GLUED", "MODULE_BOW")
    assert row["latest"]["external_ref"] == "RUN-LIVE"
    assert row["run_count"] == 1
    assert row["withdrawn_count"] == 1
    # ... and the requirement follows the run it presents, not the retracted one.
    assert row["status"] == "passed"
    checks = {c["test_type"]: c["status"] for c in preview["current"]["checks"]}
    assert checks["MODULE_BOW"] == "passed"


def test_a_test_type_whose_only_runs_are_withdrawn_reads_missing(
    session_factory, client, tudo
):
    """Judgement call (b): the requirement must fall back to `missing`, never
    keep the verdict of a measurement nobody stands behind. The row still
    exists and still says how many runs were retracted — the fact that someone
    once measured this is not erased."""
    with session_factory() as session:
        component = _component(session, stage="GLUED")
        _evidence(
            session,
            test_type="GLUE_WEIGHT",
            passed=True,
            external_ref="RUN-GONE-1",
            measured_at=datetime(2024, 11, 12, 8, 20, tzinfo=timezone.utc),
            run_state="deleted",
            results={"GW_GLUE_H1": 1.859},
        )
        _evidence(
            session,
            test_type="GLUE_WEIGHT",
            passed=True,
            external_ref="RUN-GONE-2",
            measured_at=datetime(2024, 11, 12, 8, 23, tzinfo=timezone.utc),
            run_state="deleted",
            results={"GW_GLUE_H1": 1.859},
        )
        preview = build_component_preview(session, component, client.app.state.settings)

    row = _row(preview, "GLUED", "GLUE_WEIGHT")
    assert row["status"] == "missing"
    assert row["latest"] is None
    assert row["run_count"] == 0
    assert row["withdrawn_count"] == 2
    checks = {c["test_type"]: c["status"] for c in preview["current"]["checks"]}
    assert checks["GLUE_WEIGHT"] == "missing"


def test_a_withdrawn_only_test_type_outside_the_model_still_gets_a_row(
    session_factory, client, tudo
):
    """The Additional group is derived from mirrored evidence, so a test type
    with nothing but retracted runs would vanish from the sheet entirely if
    withdrawn runs were filtered in SQL. It stays, reading `missing`."""
    with session_factory() as session:
        component = _component(session, stage="GLUED")
        _evidence(
            session,
            test_type="EXTRA_SCAN",
            passed=True,
            external_ref="RUN-EXTRA-GONE",
            run_state="deleted",
            results={"NOTE": "retracted"},
        )
        preview = build_component_preview(session, component, client.app.state.settings)

    row = _row(preview, None, "EXTRA_SCAN")
    assert row["status"] == "missing"
    assert row["latest"] is None
    assert row["run_count"] == 0
    assert row["withdrawn_count"] == 1


def test_an_unknown_or_pending_delete_state_still_counts_as_evidence(
    session_factory, client, tudo
):
    """Only the PDB's terminal `deleted` state withdraws a run. A NULL state
    (a row mirrored before this column existed, or a non-PDB source) and the
    PDB's own `requestedToDelete` — a request it has not acted on, present once
    in the owner's mirror — must both keep counting, or the fix would destroy
    evidence it has no information about."""
    with session_factory() as session:
        component = _component(session, stage="GLUED")
        _evidence(
            session,
            test_type="MODULE_BOW",
            passed=True,
            external_ref="RUN-NO-STATE",
            measured_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            results={"BOW": 12.0},
        )
        _evidence(
            session,
            test_type="GLUE_WEIGHT",
            passed=True,
            external_ref="RUN-PENDING-DELETE",
            measured_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
            run_state="requestedToDelete",
            results={"GW_GLUE_H1": 0.15},
        )
        preview = build_component_preview(session, component, client.app.state.settings)

    bow = _row(preview, "GLUED", "MODULE_BOW")
    assert (bow["status"], bow["run_count"], bow["withdrawn_count"]) == ("passed", 1, 0)
    glue = _row(preview, "GLUED", "GLUE_WEIGHT")
    assert (glue["status"], glue["run_count"], glue["withdrawn_count"]) == ("passed", 1, 0)


# --- Child-component evidence (worksheet.children) ---------------------------


def _child_group(preview, sn):
    for group in preview["worksheet"]["children"]:
        if group["sn"] == sn:
            return group
    raise AssertionError(f"no child evidence group for {sn!r}")


def test_a_stitched_modules_worksheet_reaches_through_its_half_modules(
    session_factory, client, tudo
):
    """R3-R5 modules are stitched, so their parts hang one hop further down.

    The full module's direct child is a half module, and the sensors and
    powerboards carrying the runs are that half module's children. One hop
    showed the half modules but hid everything below them: on the owner's
    mirror 23 stitched modules kept 114 evidence-bearing parts out of sight.
    The extra hop follows the stitch only — never a sensor's own children —
    which keeps this the same assembly relation the gallery shows.
    """
    with session_factory() as session:
        component = _component(session, stage="GLUED")
        half = _child(
            session,
            component,
            sn="20USEM50000901",
            component_type="MODULE",
            type_code="R5M0",
        )
        _child(
            session,
            half,
            sn=SENSOR_SN,
            component_type="SENSOR",
            local_name="TUDO-S-0042",
        )
        _evidence(
            session,
            sn=SENSOR_SN,
            test_type="ATLAS18_IV_TEST_V1",
            passed=True,
            external_ref="RUN-STITCHED-SENSOR-IV",
            measured_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
            results={"TEMPERATURE": 21.5},
        )
        preview = build_component_preview(session, component, client.app.state.settings)

    group = _child_group(preview, SENSOR_SN)
    assert group["component_type"] == "SENSOR"
    assert [row["test_type"] for row in group["rows"]] == ["ATLAS18_IV_TEST_V1"]
    # The half module itself stays a group of its own: whose measurement it is
    # remains part of what the page says.
    assert _child_group(preview, "20USEM50000901")["component_type"] == "MODULE"


def test_children_evidence_appears_in_its_own_group_never_merged_into_the_rows(
    session_factory, client, tudo
):
    """Only 720 of 14 759 mirrored runs hang on MODULE components; the rest sit
    on the children. The module page must show them — but as the child's
    evidence, never folded into the component's own rows, because a row there
    is a statement about this component."""
    with session_factory() as session:
        component = _component(session, stage="GLUED")
        _child(
            session,
            component,
            sn=SENSOR_SN,
            component_type="SENSOR",
            local_name="TUDO-S-0042",
        )
        _evidence(
            session,
            sn=SENSOR_SN,
            test_type="ATLAS18_IV_TEST_V1",
            passed=True,
            external_ref="RUN-SENSOR-IV",
            measured_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
            results={"VOLTAGE": [0, -50, -100], "TEMPERATURE": 21.5},
        )
        preview = build_component_preview(session, component, client.app.state.settings)

    group = _child_group(preview, SENSOR_SN)
    assert group["component_type"] == "SENSOR"
    assert group["type_code"] == "ATLAS18R5"
    assert group["local_name"] == "TUDO-S-0042"
    assert [row["test_type"] for row in group["rows"]] == ["ATLAS18_IV_TEST_V1"]
    assert group["rows"][0]["latest"]["passed"] is True
    assert group["rows"][0]["run_count"] == 1

    # The child's test type must not have leaked into the component's own sheet.
    own_types = {
        row["test_type"] for g in preview["worksheet"]["groups"] for row in g["rows"]
    }
    assert "ATLAS18_IV_TEST_V1" not in own_types


def test_child_evidence_does_not_change_what_gates_a_stage_move(
    session_factory, client, tudo
):
    """Whether a half-module's passing GLUE_WEIGHT satisfies the ring module's
    requirement is a real domain question (zFlow does aggregate across
    half-modules) and an owner decision that has not been made. Showing the
    evidence must not quietly answer it."""
    with session_factory() as session:
        component = _component(session, stage="GLUED")
        half = _child(
            session,
            component,
            sn="20USE5L0000031",
            component_type="MODULE",
            type_code="R5M1_HALFMODULE",
        )
        _evidence(
            session,
            sn=half.sn,
            test_type="GLUE_WEIGHT",
            passed=True,
            external_ref="RUN-HALF-GLUE",
            measured_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
            results={"GW_GLUE_H1": 0.151},
        )
        preview = build_component_preview(session, component, client.app.state.settings)

    assert _child_group(preview, half.sn)["rows"][0]["latest"]["passed"] is True
    # The parent still has no GLUE_WEIGHT of its own.
    assert _row(preview, "GLUED", "GLUE_WEIGHT")["status"] == "missing"
    checks = {c["test_type"]: c["status"] for c in preview["current"]["checks"]}
    assert checks["GLUE_WEIGHT"] == "missing"


def test_child_rows_obey_the_same_compactness_contract(session_factory, client, tudo):
    """Child runs carry the largest payloads in the mirror (response curves,
    IV sweeps). They are summarised by exactly the same rule as the component's
    own rows — scalars inline, arrays and maps as counts, never raw values."""
    sentinels = [404040, 505050]
    with session_factory() as session:
        component = _component(session, stage="GLUED")
        hybrid = _child(
            session,
            component,
            sn="20USEH30000123",
            component_type="HYBRID_ASSEMBLY",
            type_code="R5H1",
        )
        _evidence(
            session,
            sn=hybrid.sn,
            test_type="RESPONSE_CURVE_PPA",
            passed=True,
            external_ref="RUN-RC",
            measured_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
            run_number="189-6",
            results={
                "GAIN": sentinels,
                "VT50": {"ABC_0": 1.1, "ABC_1": 1.2},
                "TEMPERATURE": 20.5,
            },
        )
        session.commit()

    authenticate(client, session_factory, role="viewer")
    response = client.get(f"/api/components/{SN}/preview")
    assert response.status_code == 200, response.text
    for sentinel in sentinels:
        assert str(sentinel) not in response.text

    group = _child_group(response.json(), "20USEH30000123")
    latest = group["rows"][0]["latest"]
    assert latest["scalars"] == [
        {"code": "TEMPERATURE", "name": "TEMPERATURE", "value": 20.5}
    ]
    assert latest["arrays"] == [
        {"code": "GAIN", "name": "GAIN", "points": 2, "kind": "array"},
        {"code": "VT50", "name": "VT50", "points": 2, "kind": "map"},
    ]
    assert latest["run_number"] == "189-6"
    # A child row makes no claim about the parent's requirements.
    assert "status" not in group["rows"][0]


def test_child_rows_exclude_withdrawn_runs_too(session_factory, client, tudo):
    with session_factory() as session:
        component = _component(session, stage="GLUED")
        _child(session, component, sn=SENSOR_SN)
        _evidence(
            session,
            sn=SENSOR_SN,
            test_type="ATLAS18_IV_TEST_V1",
            passed=False,
            external_ref="RUN-S-GONE",
            measured_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
            run_state="deleted",
            results={"I_500V": 99.0},
        )
        _evidence(
            session,
            sn=SENSOR_SN,
            test_type="ATLAS18_IV_TEST_V1",
            passed=True,
            external_ref="RUN-S-LIVE",
            measured_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            results={"I_500V": 1.2},
        )
        preview = build_component_preview(session, component, client.app.state.settings)

    row = _child_group(preview, SENSOR_SN)["rows"][0]
    assert row["latest"]["external_ref"] == "RUN-S-LIVE"
    assert row["run_count"] == 1
    assert row["withdrawn_count"] == 1


def test_every_direct_child_gets_a_group_even_without_mirrored_runs(
    session_factory, client, tudo
):
    """"We looked and there is nothing" is a different statement from "we did
    not look" — and the family tree on the same page already lists the child."""
    with session_factory() as session:
        component = _component(session, stage="GLUED")
        _child(session, component, sn=SENSOR_SN)
        _child(session, component, sn="20USEP00000900", component_type="PWB", type_code="PBR5")
        preview = build_component_preview(session, component, client.app.state.settings)

    groups = preview["worksheet"]["children"]
    # Ordered by serial, deterministically.
    assert [group["sn"] for group in groups] == ["20USEP00000900", SENSOR_SN]
    assert all(group["rows"] == [] for group in groups)


def _preview_query_counts(session_factory, settings, *, parent_sn, child_prefix, child_count):
    """Build one preview and report how many statements hit which table."""
    statements: list[str] = []

    def _record(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
        statements.append(statement)

    with session_factory() as session:
        component = _component(session, sn=parent_sn, stage="GLUED")
        for index in range(child_count):
            child = _child(session, component, sn=f"{child_prefix}{index:02d}")
            for test_type in ("ATLAS18_IV_TEST_V1", "ATLAS18_VIS_INSPECTION_V2"):
                _evidence(
                    session,
                    sn=child.sn,
                    test_type=test_type,
                    passed=True,
                    external_ref=f"RUN-{parent_sn}-{index}-{test_type}",
                    measured_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
                    results={"VALUE": index},
                )
        session.flush()

        engine = session.get_bind()
        event.listen(engine, "before_cursor_execute", _record)
        try:
            preview = build_component_preview(session, component, settings)
        finally:
            event.remove(engine, "before_cursor_execute", _record)

    assert len(preview["worksheet"]["children"]) == child_count
    return {
        "evidence": len([s for s in statements if "FROM test_run_evidence" in s]),
        "attachment": len([s for s in statements if "FROM test_run_attachment" in s]),
        "component": len([s for s in statements if "FROM component" in s]),
    }


def test_child_evidence_cost_does_not_grow_with_the_number_of_children(
    session_factory, client, tudo
):
    """The invariant that makes this affordable on every module page open: the
    child pass is a fixed number of statements, not one per child. Asserted by
    comparing two components rather than by pinning a magic number, so the test
    keeps meaning what it says if an unrelated query is added elsewhere."""
    settings = client.app.state.settings
    one = _preview_query_counts(
        session_factory,
        settings,
        parent_sn="20USEM20000901",
        child_prefix="20USES400001",
        child_count=1,
    )
    many = _preview_query_counts(
        session_factory,
        settings,
        parent_sn="20USEM20000902",
        child_prefix="20USES400002",
        child_count=6,
    )
    assert one == many, (one, many)
    # And the absolute cost stays small: own runs + child metadata + the
    # payloads of the selected newest runs only.
    assert many["evidence"] <= 4, many


def test_additional_group_shows_a_confirmed_result_before_the_next_mirror_sync(
    session_factory, client, tudo
):
    """A confirmed (terminal) upload of a non-required test type satisfies
    `results` via `satisfied_test_results` immediately, before the next PDB
    mirror sync ever creates its TestRunEvidence row. It carries no staged
    entry (confirmed is terminal) and no mirrored evidence yet, so it must
    still be found through `results`, or the now-satisfied requirement has
    nowhere to render."""
    with session_factory() as session:
        component = _component(session, stage="TESTED")
        _upload_action(
            session,
            tudo["id"],
            test_type="MODULE_IV_AMAC",
            status="confirmed",
            passed=True,
        )
        preview = build_component_preview(session, component, client.app.state.settings)

    additional = preview["worksheet"]["groups"][-1]
    assert additional["stage"] is None
    row = next(r for r in additional["rows"] if r["test_type"] == "MODULE_IV_AMAC")
    assert row["status"] == "passed"
    assert row["latest"] is None
    assert row["run_count"] == 0
    assert row["staged"] == []
