"""Application service tying the pure stage engine to the database.

The engine in `app.domain.stages` stays pure; this module supplies its inputs
from the local tables — an institute's stage model and a component's satisfied
tests — so both the API and the outbox worker evaluate stage moves the same way.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.stages import StageEvaluation, evaluate_stage, stage_model_from_settings
from app.models import Component, InstituteProfile, OutboxAction, TestRunEvidence
from app.outbox import OutboxStatus


def satisfied_test_results(session: Session, sn: str) -> dict[str, bool]:
    """Map each test type uploaded for a component to whether it passed.

    Sources are mirrored test-run evidence plus itkFlow's own confirmed
    uploads. Confirmed local uploads are applied after external evidence, so a
    freshly confirmed outbox action can satisfy the workflow immediately even
    before the next PDB mirror sync.
    """
    results: dict[str, bool] = {}
    evidence_rows = session.scalars(
        select(TestRunEvidence)
        .where(TestRunEvidence.component_sn == sn)
        .order_by(
            # SQLite sorts NULLs first in ASC by default; PostgreSQL sorts them
            # last. Pin NULLS FIRST explicitly so both engines agree that a
            # dated run always outranks an undated one for the last-wins loop
            # below (see preview._worksheet_row, which selects the same winner
            # in Python and must never disagree with this ordering).
            TestRunEvidence.measured_at.nullsfirst(),
            TestRunEvidence.synced_at,
            TestRunEvidence.id,
        )
    )
    for row in evidence_rows:
        if row.test_type:
            results[row.test_type] = bool(row.passed)

    actions = session.scalars(
        select(OutboxAction)
        .where(
            OutboxAction.kind == "upload_test_run",
            OutboxAction.status == OutboxStatus.CONFIRMED.value,
        )
        .order_by(OutboxAction.updated_at, OutboxAction.id)
    )
    for action in actions:
        payload = action.payload or {}
        if payload.get("component_sn") != sn:
            continue
        test_type = payload.get("test_type")
        if isinstance(test_type, str) and test_type:
            results[test_type] = bool(payload.get("passed"))
    return results


def evaluate_for_component(session: Session, component: Component) -> StageEvaluation:
    """Evaluate stage-move readiness for one mirrored component."""
    institute = session.scalar(
        select(InstituteProfile).where(InstituteProfile.code == component.institute_code)
    )
    model = stage_model_from_settings(institute.settings if institute is not None else None)
    results = satisfied_test_results(session, component.sn)
    return evaluate_stage(component.stage, results, model)
