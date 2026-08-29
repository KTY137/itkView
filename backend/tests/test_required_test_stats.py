# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-FileComment: itkflow-83df61684513
from datetime import datetime, timedelta, timezone

from authutil import authenticate, create_institute_profile
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.models import Component, OutboxAction, TestRunEvidence
from app.outbox import OutboxStatus

BASE = datetime(2026, 8, 27, tzinfo=timezone.utc)


def _profile(session_factory: sessionmaker[Session], code: str = "EXAMPLE") -> dict:
    # Empty replacements keep the seed stages from contributing test rows; the
    # service itself remains driven by the same merged model as the stage gate.
    requirements = {
        "A": ["T_A1", "T_A2"],
        "B": ["T_B"],
        "C": [],
        "HV_TAB_ATTACHED": [],
        "GLUED": [],
        "STITCH_BONDING": [],
        "BONDED": [],
        "TESTED": [],
        "FINISHED": [],
    }
    return create_institute_profile(
        session_factory,
        code=code,
        name=f"{code} Institute",
        settings={"stage_order": ["A", "B", "C"], "stage_requirements": requirements},
    )


def _seed(session_factory: sessionmaker[Session], institute_id: int) -> None:
    with session_factory() as session:
        for sn, stage, stale, trashed in (
            ("COMP-A", "A", False, False),
            ("COMP-B", "B", False, False),
            ("COMP-C", "C", False, False),
            ("COMP-STALE", "B", True, False),
            ("COMP-TRASH", "B", False, True),
            ("COMP-UNKNOWN", "OFF_FLOW", False, False),
        ):
            session.add(
                Component(
                    sn=sn,
                    component_type="MODULE",
                    type_code="CUSTOM",
                    stage=stage,
                    location="EXAMPLE",
                    institute_code="EXAMPLE",
                    stale=stale,
                    trashed=trashed,
                )
            )

        # A: pass, B: latest live run fails, C: only a withdrawn run -> missing.
        session.add_all(
            [
                TestRunEvidence(
                    component_sn="COMP-A",
                    test_type="T_A1",
                    passed=True,
                    external_ref="A-live",
                    measured_at=BASE,
                ),
                TestRunEvidence(
                    component_sn="COMP-B",
                    test_type="T_A1",
                    passed=True,
                    external_ref="B-old",
                    measured_at=BASE,
                ),
                TestRunEvidence(
                    component_sn="COMP-B",
                    test_type="T_A1",
                    passed=False,
                    external_ref="B-new",
                    measured_at=BASE + timedelta(minutes=1),
                ),
                TestRunEvidence(
                    component_sn="COMP-C",
                    test_type="T_A1",
                    passed=True,
                    external_ref="C-withdrawn",
                    run_state="deleted",
                    measured_at=BASE,
                ),
                # requestedToDelete is still live until the PDB completes it.
                TestRunEvidence(
                    component_sn="COMP-C",
                    test_type="T_A2",
                    passed=True,
                    external_ref="C-pending-delete",
                    run_state="requestedToDelete",
                    measured_at=BASE,
                ),
                TestRunEvidence(
                    component_sn="COMP-B",
                    test_type="T_B",
                    passed=False,
                    external_ref="B-stage-fail",
                    measured_at=BASE,
                    synced_at=BASE,
                ),
            ]
        )
        # Confirmed overrides mirrored evidence; draft is deliberately ignored.
        session.add_all(
            [
                OutboxAction(
                    institute_id=institute_id,
                    kind="upload_test_run",
                    status=OutboxStatus.CONFIRMED.value,
                    created_by="worker",
                    external_ref="confirmed-b-t-a2",
                    updated_at=BASE + timedelta(minutes=2),
                    payload={"component_sn": "COMP-B", "test_type": "T_A2", "passed": True},
                ),
                OutboxAction(
                    institute_id=institute_id,
                    kind="upload_test_run",
                    status=OutboxStatus.CONFIRMED.value,
                    created_by="worker",
                    external_ref="confirmed-b-t-b",
                    updated_at=BASE + timedelta(minutes=2),
                    payload={
                        "component_sn": "COMP-B",
                        "test_type": "T_B",
                        "passed": True,
                        "measured_at": (BASE + timedelta(minutes=2)).isoformat(),
                    },
                ),
                OutboxAction(
                    institute_id=institute_id,
                    kind="upload_test_run",
                    status=OutboxStatus.DRAFT.value,
                    created_by="operator",
                    payload={"component_sn": "COMP-A", "test_type": "T_A2", "passed": True},
                ),
            ]
        )
        session.commit()


def test_required_test_stats_use_gate_semantics_and_at_or_beyond_denominator(
    client: TestClient, session_factory
):
    institute = _profile(session_factory)
    _seed(session_factory, institute["id"])
    authenticate(client, session_factory, role="viewer", institute_id=institute["id"])

    response = client.get("/api/stats/required-tests")
    assert response.status_code == 200
    body = response.json()
    assert body["institute"] == "EXAMPLE"
    assert body["denominator"] == "at_or_beyond_stage"
    assert body["stage_order"][:3] == ["A", "B", "C"]
    assert body["rows"] == [
        {
            "stage": "A",
            "test_type": "T_A1",
            "component_total": 3,
            "passed": 1,
            "failed": 1,
            "missing": 1,
        },
        {
            "stage": "A",
            "test_type": "T_A2",
            "component_total": 3,
            "passed": 2,
            "failed": 0,
            "missing": 1,
        },
        {
            "stage": "B",
            "test_type": "T_B",
            "component_total": 2,
            "passed": 1,
            "failed": 0,
            "missing": 1,
        },
    ]
    assert all(
        row["passed"] + row["failed"] + row["missing"] == row["component_total"]
        for row in body["rows"]
    )


def test_required_test_stats_are_viewer_readable_but_institute_scoped(
    client: TestClient, session_factory
):
    own = _profile(session_factory)
    _profile(session_factory, "OTHER")

    unauthenticated = client.get(
        "/api/stats/required-tests", params={"institute": "EXAMPLE"}
    )
    assert unauthenticated.status_code == 401
    authenticate(client, session_factory, role="viewer", institute_id=own["id"])
    assert client.get("/api/stats/required-tests").status_code == 200
    assert (
        client.get("/api/stats/required-tests", params={"institute": "OTHER"}).status_code
        == 403
    )


def test_unbound_user_must_choose_when_several_stage_profiles_exist(
    client: TestClient, session_factory
):
    _profile(session_factory)
    _profile(session_factory, "OTHER")
    authenticate(client, session_factory, role="viewer")

    assert client.get("/api/stats/required-tests").status_code == 422
    selected = client.get("/api/stats/required-tests", params={"institute": "OTHER"})
    assert selected.status_code == 200
    assert selected.json()["institute"] == "OTHER"
