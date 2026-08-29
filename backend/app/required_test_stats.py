# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-FileComment: itkflow-56ca2d3bea39
"""Required-test coverage by configured production stage.

This read model uses only the local component/evidence mirror. Its denominator
is deliberately ``at_or_beyond_stage``: the stage gate requires a stage's tests
before a component may advance, so a component currently in that stage or any
later configured stage belongs in the cohort. Looking only at components still
exactly in the stage would hide missing or failed evidence after a move.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.stages import RequirementStatus, stage_model_from_settings
from app.models import Component, InstituteProfile
from app.stage_service import satisfied_test_results_for_components

DENOMINATOR = "at_or_beyond_stage"


@dataclass(frozen=True)
class RequiredTestStageRow:
    stage: str
    test_type: str
    component_total: int
    passed: int
    failed: int
    missing: int


@dataclass(frozen=True)
class RequiredTestStats:
    institute: str
    denominator: str
    stage_order: list[str]
    rows: list[RequiredTestStageRow]


def required_test_stats(
    session: Session, institute: InstituteProfile
) -> RequiredTestStats:
    """Aggregate authoritative stage-gate evidence for one institute."""
    model = stage_model_from_settings(institute.settings)
    rank = {stage: index for index, stage in enumerate(model.order)}
    components = list(
        session.scalars(
            select(Component)
            .where(
                Component.institute_code == institute.code,
                Component.stale.is_(False),
                Component.trashed.is_(False),
                Component.stage.in_(model.order),
            )
            .order_by(Component.sn)
        )
    )
    evidence = satisfied_test_results_for_components(
        session, [component.sn for component in components]
    )

    rows: list[RequiredTestStageRow] = []
    for stage_index, stage in enumerate(model.order):
        cohort = [component for component in components if rank[component.stage] >= stage_index]
        for test_type in model.required_tests.get(stage, ()):
            passed = failed = missing = 0
            for component in cohort:
                results = evidence.get(component.sn, {})
                if test_type not in results:
                    status = RequirementStatus.MISSING
                elif results[test_type]:
                    status = RequirementStatus.PASSED
                else:
                    status = RequirementStatus.FAILED
                if status is RequirementStatus.PASSED:
                    passed += 1
                elif status is RequirementStatus.FAILED:
                    failed += 1
                else:
                    missing += 1
            rows.append(
                RequiredTestStageRow(
                    stage=stage,
                    test_type=test_type,
                    component_total=len(cohort),
                    passed=passed,
                    failed=failed,
                    missing=missing,
                )
            )

    return RequiredTestStats(
        institute=institute.code,
        denominator=DENOMINATOR,
        stage_order=list(model.order),
        rows=rows,
    )
