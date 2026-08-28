"""Application service tying the pure stage engine to the database.

The engine in `app.domain.stages` stays pure; this module supplies its inputs
from the local tables — an institute's stage model and a component's satisfied
tests — so both the API and the outbox worker evaluate stage moves the same way.
"""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.stages import StageEvaluation, evaluate_stage, stage_model_from_settings
from app.models import Component, InstituteProfile, OutboxAction, TestRunEvidence
from app.outbox import OutboxStatus
from app.test_run_evidence import is_withdrawn


def satisfied_test_results(session: Session, sn: str) -> dict[str, bool]:
    """Map each test type uploaded for a component to whether it passed.

    Sources are mirrored test-run evidence plus itkFlow's own worker-confirmed
    uploads. A fresh confirmation can satisfy the workflow before the next PDB
    mirror sync; once mirrored, the PDB row owns its lifecycle and precedence.

    Runs the PDB has withdrawn are not evidence and are excluded here, which is
    what makes a stage gate honest: if every run of a required test type has
    been retracted, the requirement reads `missing` again rather than keeping
    the verdict of a measurement nobody stands behind any more.
    """
    return satisfied_test_results_for_components(session, [sn]).get(sn, {})


def satisfied_test_results_for_components(
    session: Session, component_sns: list[str]
) -> dict[str, dict[str, bool]]:
    """Latest live pass/fail evidence for several components at once.

    This is the batch form of :func:`satisfied_test_results`, used by aggregate
    read models so they do not repeat the evidence and confirmed-outbox queries
    once per component. Latest live mirrored evidence wins within a test type.
    A worker-confirmed itkFlow upload is provisional evidence until its PDB
    reference reaches the mirror; a later mirror update always wins. Client-
    forged confirmations, malformed payloads and cross-institute actions never
    count as production evidence.
    """
    sns = list(dict.fromkeys(component_sns))
    if not sns:
        return {}
    wanted = set(sns)
    results: dict[str, dict[str, bool]] = {sn: {} for sn in sns}
    # Select only gate columns: evidence payloads can contain large arrays and
    # attachments, none of which belong in an overview projection.
    evidence_rows = list(
        session.execute(
            select(
                TestRunEvidence.component_sn,
                TestRunEvidence.test_type,
                TestRunEvidence.passed,
                TestRunEvidence.measured_at,
                TestRunEvidence.synced_at,
                TestRunEvidence.id,
                TestRunEvidence.external_ref,
                TestRunEvidence.run_state,
            )
            .where(TestRunEvidence.component_sn.in_(sns))
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
    )
    mirror_winner_rank: dict[tuple[str, str], tuple[bool, datetime, datetime, int]] = {}
    mirrored_refs: set[tuple[str, str]] = set()
    for row in evidence_rows:
        if row.external_ref:
            # A PDB run reference belongs to one component/test. If a legacy or
            # forged action reuses it under another test type, the already-
            # mirrored run still owns the identity and the action cannot count.
            mirrored_refs.add((row.component_sn, row.external_ref))
        if is_withdrawn(row.run_state):
            continue
        if row.test_type:
            results[row.component_sn][row.test_type] = bool(row.passed)
            mirror_winner_rank[(row.component_sn, row.test_type)] = _evidence_rank(
                measured_at=row.measured_at,
                fallback_at=row.synced_at,
                tie_breaker=row.id,
            )
    component_institutes = dict(
        session.execute(
            select(Component.sn, Component.institute_code).where(Component.sn.in_(sns))
        ).all()
    )
    institute_ids = dict(
        session.execute(
            select(InstituteProfile.code, InstituteProfile.id).where(
                InstituteProfile.code.in_(set(component_institutes.values()))
            )
        ).all()
    )

    actions = session.scalars(
        select(OutboxAction)
        .where(
            OutboxAction.kind == "upload_test_run",
            OutboxAction.status == OutboxStatus.CONFIRMED.value,
            OutboxAction.external_ref.is_not(None),
            OutboxAction.institute_id.in_(set(institute_ids.values())),
        )
        .order_by(OutboxAction.updated_at, OutboxAction.id)
    )
    winner_rank = dict(mirror_winner_rank)
    for action in actions:
        payload = action.payload or {}
        component_sn = payload.get("component_sn")
        if not isinstance(component_sn, str) or component_sn not in wanted:
            continue
        expected_institute_id = institute_ids.get(component_institutes.get(component_sn, ""))
        if expected_institute_id is None or action.institute_id != expected_institute_id:
            continue
        test_type = payload.get("test_type")
        passed = payload.get("passed")
        if not isinstance(test_type, str) or not test_type or not isinstance(passed, bool):
            continue
        if not isinstance(action.external_ref, str) or not action.external_ref.strip():
            continue
        # Once the action's exact PDB run is mirrored, the mirror owns its
        # lifecycle too (including a later withdrawal). Until then, count the
        # confirmation only if no newer mirror winner exists for this test.
        ref_key = (component_sn, action.external_ref)
        if ref_key in mirrored_refs:
            continue
        result_key = (component_sn, test_type)
        # The normal ingest path preserves the instrument's ISO measurement
        # time. Older payloads may omit it; keep that absence explicit so an
        # undated mirror row synced later can supersede an older undated local
        # confirmation through the shared fallback timestamp.
        measured_at = _payload_measured_at(payload.get("measured_at"))
        action_rank = _evidence_rank(
            measured_at=measured_at,
            fallback_at=action.updated_at,
            tie_breaker=action.id,
        )
        current_rank = winner_rank.get(result_key)
        if current_rank is not None and current_rank > action_rank:
            continue
        results[component_sn][test_type] = passed
        winner_rank[result_key] = action_rank
    return results


def _utc_naive(value: datetime) -> datetime:
    """Normalize SQLite-naive and PostgreSQL-aware timestamps for ordering."""

    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _payload_measured_at(value: object) -> datetime | None:
    """Parse the ISO timestamp staged with a confirmed upload, if usable."""

    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None


def _evidence_rank(
    *, measured_at: datetime | None, fallback_at: datetime, tie_breaker: int
) -> tuple[bool, datetime, datetime, int]:
    """Shared newest-run order for mirror rows and provisional confirmations."""

    epoch = datetime.min
    return (
        measured_at is not None,
        _utc_naive(measured_at) if measured_at is not None else epoch,
        _utc_naive(fallback_at),
        tie_breaker,
    )


def evaluate_for_component(session: Session, component: Component) -> StageEvaluation:
    """Evaluate stage-move readiness for one mirrored component."""
    institute = session.scalar(
        select(InstituteProfile).where(InstituteProfile.code == component.institute_code)
    )
    model = stage_model_from_settings(institute.settings if institute is not None else None)
    results = satisfied_test_results(session, component.sn)
    return evaluate_stage(component.stage, results, model)
