"""Local component preview built from the mirror and open outbox actions.

The preview is deliberately PDB-inert: it projects staged writes over the
current local read model, so a component page can show the operator what would
change without performing a network request or mutating either mirror or
outbox state.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assembly import ASSEMBLY_ACTION_KIND, evaluate_assembly
from app.attachment_store import attachment_read_model, known_attachments
from app.domain.stages import stage_model_from_settings
from app.models import Component, IngestFile, InstituteProfile, OutboxAction, TestRunEvidence
from app.outbox import TERMINAL
from app.stage_service import satisfied_test_results


def _profile_settings(session: Session, component: Component) -> Mapping[str, Any]:
    institute = session.scalar(
        select(InstituteProfile).where(InstituteProfile.code == component.institute_code)
    )
    if institute is None or not isinstance(institute.settings, dict):
        return {}
    return institute.settings


def _targets_component(action: OutboxAction, sn: str) -> bool:
    payload = action.payload or {}
    return (
        payload.get("sn") == sn
        or payload.get("component_sn") == sn
        or payload.get("parent_sn") == sn
    )


def _checks(
    stage: str,
    results: Mapping[str, bool],
    profile_settings: Mapping[str, Any],
    *,
    pending: frozenset[str] = frozenset(),
) -> list[dict[str, str]]:
    model = stage_model_from_settings(profile_settings)
    checks: list[dict[str, str]] = []
    for required_stage, test_type in model.requirements_through(stage):
        if test_type in pending:
            status = "pending"
        elif test_type not in results:
            status = "missing"
        else:
            status = "passed" if results[test_type] else "failed"
        checks.append({"stage": required_stage, "test_type": test_type, "status": status})
    return checks


def _summary(action: OutboxAction) -> str:
    payload = action.payload or {}
    if action.kind == "stage_move":
        target = payload.get("to_stage")
        return f"\u2192 {target}" if isinstance(target, str) and target else "Stage move"
    if action.kind == "upload_test_run":
        test_type = payload.get("test_type")
        return f"{test_type} upload" if isinstance(test_type, str) and test_type else "Test upload"
    if action.kind == "register_component":
        component_type = payload.get("component_type")
        return (
            f"Register {component_type}"
            if isinstance(component_type, str) and component_type
            else "Register component"
        )
    if action.kind == ASSEMBLY_ACTION_KIND:
        child_sn = payload.get("child_sn")
        slot = payload.get("slot")
        if isinstance(child_sn, str) and child_sn:
            suffix = f" at {slot}" if isinstance(slot, str) and slot else ""
            return f"Assemble {child_sn}{suffix}"
        return "Assembly change"
    return action.kind.replace("_", " ").strip().capitalize() or "Staged action"


def _application_setting(settings: Any, key: str, default: Any) -> Any:
    if isinstance(settings, Mapping):
        return settings.get(key, default)
    return getattr(settings, key, default)


def _submittability(
    component: Component, settings: Any
) -> tuple[bool, str | None]:
    """Describe the hard write-scope boundary without changing worker policy."""
    scope = _application_setting(settings, "pdb_write_scope", "dummy_only")
    if scope == "dummy_only" and not component.is_dummy:
        return False, "not_dummy"
    if scope != "dummy_only":
        # Unrestricted production writes are intentionally not implemented.
        return False, "write_scope_unavailable"
    return True, None


def _action_submittability(
    session: Session,
    action: OutboxAction,
    component: Component,
    settings: Any,
    default: tuple[bool, str | None],
) -> tuple[bool, str | None]:
    if action.kind != ASSEMBLY_ACTION_KIND:
        return default
    payload = action.payload or {}
    parent_sn = payload.get("parent_sn")
    child_sn = payload.get("child_sn")
    slot = payload.get("slot")
    tool_id = payload.get("tool_id")
    glue_batch_id = payload.get("glue_batch_id")
    if (
        parent_sn != component.sn
        or not isinstance(parent_sn, str)
        or not isinstance(child_sn, str)
        or not isinstance(slot, str)
        or isinstance(tool_id, bool)
        or not isinstance(tool_id, int)
        or (
            glue_batch_id is not None
            and (isinstance(glue_batch_id, bool) or not isinstance(glue_batch_id, int))
        )
    ):
        return False, "validation_failed"
    evaluation = evaluate_assembly(
        session,
        settings,
        parent_sn=parent_sn,
        child_sn=child_sn,
        slot=slot,
        tool_id=tool_id,
        glue_batch_id=glue_batch_id,
    )
    return evaluation.submittable, evaluation.submittable_reason


def _evidence_test(
    row: TestRunEvidence,
    attachments: list[dict[str, Any]],
) -> dict[str, Any]:
    payload = row.payload if isinstance(row.payload, dict) else {}
    return {
        "test_type": row.test_type,
        "passed": bool(row.passed),
        "external_ref": row.external_ref,
        "measured_at": row.measured_at,
        "synced_at": row.synced_at,
        "source": row.source,
        "run_number": payload.get("run_number"),
        "properties": payload.get("properties") or {},
        "results": payload.get("results") or {},
        "result_meta": payload.get("result_meta") or {},
        # Only expose the local attachment index.  The raw evidence payload may
        # contain public share URLs or transient EOS metadata and is not an API
        # representation.
        "attachments": attachments,
        "ghost": False,
        "outbox_action_id": None,
    }


def _datetime_value(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None


def _ghost_test(action: OutboxAction, ingest: IngestFile | None) -> dict[str, Any]:
    action_payload = action.payload or {}
    ingest_payload = (
        ingest.payload if ingest is not None and isinstance(ingest.payload, dict) else {}
    )

    test_type = (
        ingest.test_type if ingest is not None else None
    ) or action_payload.get("test_type")
    passed = ingest_payload.get("passed")
    if not isinstance(passed, bool):
        passed = action_payload.get("passed")
    if not isinstance(passed, bool):
        passed = None

    measured_at = _datetime_value(ingest_payload.get("date")) or _datetime_value(
        action_payload.get("measured_at")
    )
    run_number = ingest_payload.get("runNumber")
    if isinstance(run_number, bool) or not isinstance(run_number, (str, int)):
        run_number = action_payload.get("run_number")
    if isinstance(run_number, bool) or not isinstance(run_number, (str, int)):
        run_number = None

    properties = ingest_payload.get("properties")
    results = ingest_payload.get("results")
    result_meta = ingest_payload.get("result_meta")
    return {
        "test_type": test_type if isinstance(test_type, str) and test_type else "UNKNOWN",
        "passed": passed,
        "external_ref": None,
        "measured_at": measured_at,
        "synced_at": None,
        "source": "outbox",
        "run_number": run_number,
        "properties": properties if isinstance(properties, dict) else {},
        "results": results if isinstance(results, dict) else {},
        "result_meta": result_meta if isinstance(result_meta, dict) else {},
        "attachments": [],
        "ghost": True,
        "outbox_action_id": action.id,
    }


def build_component_preview(
    session: Session,
    component: Component,
    settings: Any,
) -> dict[str, Any]:
    """Project open actions for ``component`` over the local mirror.

    Stage moves are applied oldest first. Pending test uploads override the
    corresponding projected requirement check with the explicit ``pending``
    state; they never masquerade as already passed evidence.
    """
    profile_settings = _profile_settings(session, component)
    results = satisfied_test_results(session, component.sn)

    actions = [
        action
        for action in session.scalars(
            select(OutboxAction)
            .where(OutboxAction.status.not_in([status.value for status in TERMINAL]))
            .order_by(OutboxAction.created_at, OutboxAction.id)
        )
        if _targets_component(action, component.sn)
    ]

    # Resolve the ingest through its server-maintained action link, never by
    # blindly trusting an arbitrary ``ingest_file_id`` in action JSON.
    upload_action_ids = [action.id for action in actions if action.kind == "upload_test_run"]
    ingests_by_action = (
        {
            ingest.outbox_action_id: ingest
            for ingest in session.scalars(
                select(IngestFile).where(IngestFile.outbox_action_id.in_(upload_action_ids))
            )
        }
        if upload_action_ids
        else {}
    )

    submittable, reason = _submittability(component, settings)
    staged_actions: list[dict[str, Any]] = []
    projected_stage = component.stage
    pending_tests: set[str] = set()
    ghost_tests: list[dict[str, Any]] = []

    for action in actions:
        payload = action.payload or {}
        to_stage = payload.get("to_stage") if action.kind == "stage_move" else None
        test_type = payload.get("test_type") if action.kind == "upload_test_run" else None
        if isinstance(to_stage, str) and to_stage:
            projected_stage = to_stage
        if isinstance(test_type, str) and test_type:
            pending_tests.add(test_type)
            ghost_tests.append(_ghost_test(action, ingests_by_action.get(action.id)))
        action_submittable, action_reason = _action_submittability(
            session,
            action,
            component,
            settings,
            (submittable, reason),
        )
        staged_actions.append(
            {
                "id": action.id,
                "kind": action.kind,
                "status": action.status,
                "summary": _summary(action),
                "to_stage": to_stage if isinstance(to_stage, str) else None,
                "test_type": test_type if isinstance(test_type, str) else None,
                "created_by": action.created_by,
                "created_at": action.created_at,
                "submittable": action_submittable,
                "submittable_reason": action_reason,
            }
        )

    evidence = session.scalars(
        select(TestRunEvidence)
        .where(TestRunEvidence.component_sn == component.sn)
        .order_by(
            TestRunEvidence.measured_at,
            TestRunEvidence.synced_at,
            TestRunEvidence.id,
        )
    )
    attachments_by_run: dict[str | None, list[dict[str, Any]]] = {}
    for attachment in known_attachments(session, component.sn):
        attachments_by_run.setdefault(attachment.test_run_ref, []).append(
            attachment_read_model(settings, attachment)
        )
    tests = [
        _evidence_test(row, attachments_by_run.get(row.external_ref, []))
        for row in evidence
    ]
    tests.extend(ghost_tests)

    return {
        "current": {
            "stage": component.stage,
            "checks": _checks(component.stage, results, profile_settings),
        },
        "staged_actions": staged_actions,
        "projected": {
            "stage": projected_stage,
            "checks": _checks(
                projected_stage,
                results,
                profile_settings,
                pending=frozenset(pending_tests),
            ),
            "tests": tests,
        },
    }
