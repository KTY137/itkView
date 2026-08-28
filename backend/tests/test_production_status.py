from datetime import datetime, timezone

from authutil import create_institute_profile
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.orm import Session, sessionmaker

from app.domain.stages import DEFAULT_STAGE_ORDER
from app.models import Component, TestRunEvidence
from app.production_status import production_status_for_components

NOW = datetime(2026, 8, 28, tzinfo=timezone.utc)


def explicit_profile(session_factory: sessionmaker[Session]) -> dict:
    requirements = {stage: [] for stage in DEFAULT_STAGE_ORDER}
    requirements["HV_TAB_ATTACHED"] = ["EARLY_TEST"]
    requirements["GLUED"] = ["CURRENT_TEST"]
    requirements["FINISHED"] = ["TERMINAL_TEST"]
    return create_institute_profile(
        session_factory,
        code="EXPLICIT",
        name="Explicit workflow",
        settings={
            "stage_order": list(DEFAULT_STAGE_ORDER),
            "stage_requirements": requirements,
            "stage_policy_approved": True,
        },
    )


def add_component(
    session: Session,
    sn: str,
    stage: str,
    *,
    institute: str = "EXPLICIT",
    component_type: str = "MODULE",
    stale: bool = False,
    trashed: bool = False,
) -> None:
    session.add(
        Component(
            sn=sn,
            component_type=component_type,
            type_code="TEST",
            stage=stage,
            location=institute,
            institute_code=institute,
            stale=stale,
            trashed=trashed,
        )
    )


def add_evidence(session: Session, sn: str, test_type: str, passed: bool) -> None:
    session.add(
        TestRunEvidence(
            component_sn=sn,
            test_type=test_type,
            passed=passed,
            source="pdb",
            external_ref=f"{sn}:{test_type}",
            measured_at=NOW,
        )
    )


def test_component_projection_marks_only_crossed_configured_gates(
    client: TestClient, session_factory: sessionmaker[Session]
):
    explicit_profile(session_factory)
    with session_factory() as session:
        add_component(session, "CURRENT-MISSING", "HV_TAB_ATTACHED")
        add_component(session, "CURRENT-FAILED", "GLUED")
        add_component(session, "PAST-MISSING", "GLUED")
        add_component(session, "PAST-FAILED", "STITCH_BONDING")
        add_component(session, "FINISHED-FAILED", "FINISHED")
        add_component(session, "CLEAR", "STITCH_BONDING")

        # A current-stage fail is ordinary WIP once the earlier gate passed.
        add_evidence(session, "CURRENT-FAILED", "EARLY_TEST", True)
        add_evidence(session, "CURRENT-FAILED", "CURRENT_TEST", False)
        # Both prior-stage failure cases have their other gate satisfied.
        add_evidence(session, "PAST-FAILED", "EARLY_TEST", True)
        add_evidence(session, "PAST-FAILED", "CURRENT_TEST", False)
        add_evidence(session, "FINISHED-FAILED", "EARLY_TEST", True)
        add_evidence(session, "FINISHED-FAILED", "CURRENT_TEST", False)
        add_evidence(session, "CLEAR", "EARLY_TEST", True)
        add_evidence(session, "CLEAR", "CURRENT_TEST", True)
        session.commit()

    rows = {row["sn"]: row for row in client.get("/api/components").json()}
    assert rows["CURRENT-MISSING"]["production_status"] == "clear"
    assert rows["CURRENT-FAILED"]["production_status"] == "clear"
    assert rows["CLEAR"]["production_status"] == "clear"

    assert rows["PAST-MISSING"]["production_status"] == "hold"
    assert rows["PAST-MISSING"]["production_status_reasons"] == [
        {
            "code": "required_test_missing",
            "stage": "HV_TAB_ATTACHED",
            "test_type": "EARLY_TEST",
        }
    ]
    assert rows["PAST-FAILED"]["production_status"] == "hold"
    assert any(
        reason["code"] == "required_test_failed"
        and reason["test_type"] == "CURRENT_TEST"
        for reason in rows["PAST-FAILED"]["production_status_reasons"]
    )
    assert rows["FINISHED-FAILED"]["production_status"] == "hold"
    assert not any(
        reason["test_type"] == "TERMINAL_TEST"
        for reason in rows["FINISHED-FAILED"]["production_status_reasons"]
    )

    detail = client.get("/api/components/FINISHED-FAILED").json()
    assert detail["production_status"] == rows["FINISHED-FAILED"]["production_status"]
    assert detail["production_status_reasons"] == rows["FINISHED-FAILED"][
        "production_status_reasons"
    ]


def test_projection_is_fail_closed_for_unassessed_and_provisional_workflows(
    client: TestClient, session_factory: sessionmaker[Session]
):
    explicit_profile(session_factory)
    create_institute_profile(
        session_factory,
        code="SEED",
        name="Provisional seed workflow",
        settings={},
    )
    create_institute_profile(
        session_factory,
        code="PARTIAL",
        name="Partial workflow with ineffective raw approval",
        settings={
            "stage_requirements": {"GLUED": []},
            "stage_policy_approved": True,
        },
    )
    with session_factory() as session:
        add_component(session, "OFF-FLOW", "ON_CORE")
        add_component(session, "STALE", "GLUED", stale=True)
        add_component(session, "TRASHED", "FINISHED", trashed=True)
        add_component(session, "SENSOR", "FINISHED", component_type="SENSOR")
        add_component(session, "SEED-WIP", "HV_TAB_ATTACHED", institute="SEED")
        add_component(session, "SEED-HOLD", "GLUED", institute="SEED")
        add_component(session, "PARTIAL", "HV_TAB_ATTACHED", institute="PARTIAL")
        add_component(session, "NO-PROFILE", "GLUED", institute="MISSING")
        session.commit()

    rows = {row["sn"]: row for row in client.get("/api/components").json()}
    assert rows["OFF-FLOW"]["production_status"] == "unknown"
    assert rows["STALE"]["production_status"] == "unknown"
    assert rows["TRASHED"]["production_status"] == "not_applicable"
    assert rows["SENSOR"]["production_status"] == "not_applicable"

    assert rows["SEED-WIP"]["production_status"] == "unknown"
    assert rows["SEED-WIP"]["production_policy_source"] == "seed_default"
    assert rows["SEED-WIP"]["production_policy_approved"] is False
    assert rows["SEED-WIP"]["production_status_reasons"] == [
        {"code": "provisional_profile", "stage": None, "test_type": None}
    ]
    assert rows["SEED-HOLD"]["production_status"] == "hold"
    assert {reason["code"] for reason in rows["SEED-HOLD"]["production_status_reasons"]} >= {
        "provisional_profile",
        "required_test_missing",
    }
    assert rows["PARTIAL"]["production_status"] == "unknown"
    assert rows["PARTIAL"]["production_policy_source"] == "seed_default"
    assert rows["PARTIAL"]["production_policy_approved"] is False
    assert rows["PARTIAL"]["production_status_reasons"] == [
        {"code": "provisional_profile", "stage": None, "test_type": None}
    ]
    assert rows["NO-PROFILE"]["production_status"] == "unknown"
    assert rows["NO-PROFILE"]["production_policy_source"] == "missing_profile"
    assert rows["NO-PROFILE"]["production_status_reasons"] == [
        {"code": "missing_profile", "stage": None, "test_type": None}
    ]


def test_projection_query_count_does_not_grow_per_component(
    session_factory: sessionmaker[Session],
):
    explicit_profile(session_factory)
    with session_factory() as session:
        for index in range(20):
            add_component(session, f"BATCH-{index:02d}", "STITCH_BONDING")
            add_evidence(session, f"BATCH-{index:02d}", "EARLY_TEST", True)
            add_evidence(session, f"BATCH-{index:02d}", "CURRENT_TEST", True)
        session.commit()
        components = list(session.scalars(select(Component).order_by(Component.sn)))
        engine = session.get_bind()

        def count_queries(rows: list[Component]) -> int:
            statements: list[str] = []

            def record(_connection, _cursor, statement, _parameters, _context, _many):
                if statement.lstrip().upper().startswith("SELECT"):
                    statements.append(statement)

            event.listen(engine, "before_cursor_execute", record)
            try:
                production_status_for_components(session, rows)
            finally:
                event.remove(engine, "before_cursor_execute", record)
            return len(statements)

        one = count_queries(components[:1])
        many = count_queries(components)

    assert one == many
    assert many <= 5
