# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-FileComment: itkflow-236713d208a0
"""Local component preview built from the mirror and open outbox actions.

The preview is deliberately PDB-inert: it projects staged writes over the
current local read model, so a component page can show the operator what would
change without performing a network request or mutating either mirror or
outbox state.

Payload contract: the preview carries only what the module page needs *before*
the operator asks for detail — the projected stage, the requirement checks, the
compact worksheet, and the ghost entries for staged-but-unpushed uploads.
Mirrored runs are summarised in the worksheet and are otherwise served by
``GET /api/components/{sn}/tests``, which the page fetches lazily when the
collapsed "All mirrored runs" section is opened. Raw measured values (an IV
sweep is tens of kilobytes on its own) must therefore never be added back to
the preview response.

The worksheet also carries the evidence of the parts the component is assembled
from, in one group per part (``worksheet.children``). On real data that is where
nearly all of a module's history lives — 720 of 14 759 mirrored runs hang on
MODULE components, the rest on sensors, hybrids, powerboards and, for R5 ring
modules, on the two half-modules that carry their metrology, glue weight and PS
IV. A stitched module's sensors hang off those half-modules rather than off the
module itself, so the part list takes one hop through a child that is itself a
module (``attachment_store.assembled_parts``); one hop alone hid 114
evidence-bearing parts on the owner's mirror.
Child evidence is shown, never merged into the component's own rows: a
requirement check is a statement about *this* component, and whether a child's
passing test may satisfy its parent's requirement is a separate domain decision
(see docs/10 §7) that this projection deliberately does not take.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import String, cast, select
from sqlalchemy.orm import Session

from app.assembly import ASSEMBLY_ACTION_KIND, evaluate_assembly
from app.attachment_store import assembled_parts, attachment_counts_by_run
from app.domain.stages import StageModel, stage_model_from_settings
from app.glue_service import (
    GlueDerivationModel,
    derivation_payload,
    derive_evidence,
    glue_model_from_settings,
)
from app.models import (
    Component,
    IngestFile,
    InstituteProfile,
    OutboxAction,
    TestRunEvidence,
)
from app.outbox import TERMINAL
from app.stage_service import satisfied_test_results
from app.test_run_evidence import is_withdrawn


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


def _open_actions_for(session: Session, sn: str) -> list[OutboxAction]:
    """Open (non-terminal) outbox actions targeting ``sn``, oldest first.

    The set of open actions is site-wide, so loading all of them and filtering
    in Python grows with the institute's whole backlog on every module page
    open. The serial is stored inside the action's JSON payload under one of
    three keys, and no JSON path operator is portable across SQLite and
    PostgreSQL here (the column is a generic ``JSON``), so the query narrows
    with a plain substring match on the serialized payload — supported by both
    engines via ``CAST(payload AS VARCHAR) LIKE '%sn%'``.

    That match is a deliberate *superset*: any payload whose ``sn`` /
    ``component_sn`` / ``parent_sn`` equals the serial necessarily contains the
    serial verbatim in its JSON text (serials are plain ASCII, so no escaping
    can hide them), while payloads that merely mention the serial under some
    other key (``child_sn``, ...) survive the SQL and are then rejected by
    ``_targets_component``, which stays the only authority on membership.
    """
    statement = (
        select(OutboxAction)
        .where(
            OutboxAction.status.not_in([status.value for status in TERMINAL]),
            cast(OutboxAction.payload, String).contains(sn, autoescape=True),
        )
        .order_by(OutboxAction.created_at, OutboxAction.id)
    )
    return [action for action in session.scalars(statement) if _targets_component(action, sn)]


def _status_for(test_type: str, results: Mapping[str, bool], pending: frozenset[str]) -> str:
    """Shared passed/failed/missing/pending rule.

    Used by both the requirement checks and the worksheet rows so the two
    projections of the same open work can never disagree.
    """
    if test_type in pending:
        return "pending"
    if test_type not in results:
        return "missing"
    return "passed" if results[test_type] else "failed"


def _checks(
    stage: str,
    results: Mapping[str, bool],
    model: StageModel,
    *,
    pending: frozenset[str] = frozenset(),
) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []
    for required_stage, test_type in model.requirements_through(stage):
        status = _status_for(test_type, results, pending)
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
    tools = payload.get("tools")
    glue_batch_id = payload.get("glue_batch_id")
    # An action recorded through slot combinations carries `tools` and may have
    # no legacy default tool at all; the domain evaluation owns the detailed
    # validation of either shape.
    tool_reference_ok = (
        not isinstance(tool_id, bool) and isinstance(tool_id, int)
    ) or isinstance(tools, dict)
    if (
        parent_sn != component.sn
        or not isinstance(parent_sn, str)
        or not isinstance(child_sn, str)
        or not isinstance(slot, str)
        or not tool_reference_ok
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
        tool_id=tool_id if isinstance(tool_id, int) and not isinstance(tool_id, bool) else None,
        tools=tools if isinstance(tools, dict) else None,
        glue_batch_id=glue_batch_id,
    )
    return evaluation.submittable, evaluation.submittable_reason


def _safe_run_number(value: Any) -> str | int | None:
    """Narrow an untrusted value to the `run_number: str | int | None` schema
    field. Mirrored and staged payloads are external data; anything outside
    that type (a float, a dict, ...) must become ``None`` here rather than
    reach Pydantic validation, or it 500s the whole component page instead of
    just omitting one field."""
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    return value


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
    run_number = _safe_run_number(ingest_payload.get("runNumber"))
    if run_number is None:
        run_number = _safe_run_number(action_payload.get("run_number"))

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


def _worksheet_latest_run(
    row: TestRunEvidence,
    attachment_counts: Mapping[str | None, int],
) -> dict[str, Any]:
    """Project one mirrored run to the compact worksheet shape.

    Arrays *and* dict-valued results (real metrology payloads carry dicts of
    per-position measurements, e.g. glue thickness per pad) are reduced to a
    point/entry count here and never rebuilt anywhere else in the worksheet —
    neither the raw list nor the raw dict may leave the server, or the row-spam
    this feature exists to remove comes right back through a dict instead of a
    list.
    """
    payload = row.payload if isinstance(row.payload, dict) else {}
    raw_results = payload.get("results")
    raw_results = raw_results if isinstance(raw_results, dict) else {}
    raw_meta = payload.get("result_meta")
    raw_meta = raw_meta if isinstance(raw_meta, dict) else {}
    scalars: list[dict[str, Any]] = []
    arrays: list[dict[str, Any]] = []
    for code, value in raw_results.items():
        meta_entry = raw_meta.get(code)
        name = meta_entry.get("name") if isinstance(meta_entry, dict) else None
        if not isinstance(name, str) or not name:
            name = code
        if isinstance(value, (list, tuple, set)):
            arrays.append({"code": code, "name": name, "points": len(value), "kind": "array"})
        elif isinstance(value, dict):
            arrays.append({"code": code, "name": name, "points": len(value), "kind": "map"})
        else:
            scalars.append({"code": code, "name": name, "value": value})
    # Real VISUAL_INSPECTION-style payloads front-load unfilled slots (None):
    # a plain None-first rendering would show the operator three blanks before
    # the one value that matters. Stable-partition non-null values first,
    # keeping each partition's original insertion order — never a sort, so
    # equal-priority entries never reshuffle relative to each other.
    scalars = [s for s in scalars if s["value"] is not None] + [
        s for s in scalars if s["value"] is None
    ]
    return {
        "external_ref": row.external_ref,
        "measured_at": row.measured_at,
        "run_number": _safe_run_number(payload.get("run_number")),
        "passed": bool(row.passed),
        "scalars": scalars,
        "arrays": arrays,
        "attachment_count": attachment_counts.get(row.external_ref, 0),
    }


_EPOCH = datetime.min.replace(tzinfo=timezone.utc)


def _comparable_time(value: datetime | None) -> datetime:
    """Make a stored timestamp safely orderable in Python.

    The SQLite dialect loads DateTime columns as naive values while
    freshly-assigned ORM attributes stay timezone-aware, and comparing the two
    raises TypeError. Both are UTC by convention (``models.utcnow``), so naive
    values are pinned to UTC and ``None`` sorts before everything — the same
    NULLS-FIRST-ascending order the SQL queries use.
    """
    if value is None:
        return _EPOCH
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _run_rank(run: Any) -> tuple[bool, datetime, datetime, int]:
    """Ranking key for "which run is current".

    Newest by measured_at with NULLs losing to any dated run; ties break on
    synced_at then id. The selection happens in Python via an explicit tuple
    key, so it is engine-independent by construction, and it is deliberately
    identical to the winner `app.stage_service.satisfied_test_results` picks
    (its SQL ORDER BY pins NULLS FIRST for measured_at explicitly, so both
    engines agree with the ranking here) — otherwise a row's status and its
    `latest` run could disagree about which run is current.

    Accepts anything with `measured_at`/`synced_at`/`id`, so the child-evidence
    pass can rank lightweight metadata rows by exactly the same rule instead of
    growing a second, drifting copy of it.
    """
    return (
        run.measured_at is not None,
        _comparable_time(run.measured_at),
        _comparable_time(run.synced_at),
        run.id,
    )


def _partition_withdrawn(runs: Iterable[Any]) -> tuple[list[Any], int]:
    """Split runs into the ones that still count and a count of the withdrawn.

    The withdrawn ones are counted rather than dropped without trace: hiding
    data the PDB still holds is its own kind of false statement, so the row
    keeps saying "and n more that were retracted".
    """
    live: list[Any] = []
    withdrawn = 0
    for run in runs:
        if is_withdrawn(run.run_state):
            withdrawn += 1
        else:
            live.append(run)
    return live, withdrawn


def _worksheet_row(
    test_type: str,
    *,
    results: Mapping[str, bool],
    pending: frozenset[str],
    staged_by_test: Mapping[str, list[dict[str, Any]]],
    evidence_by_type: Mapping[str, list[TestRunEvidence]],
    attachment_counts: Mapping[str | None, int],
    glue_model: GlueDerivationModel,
    type_code: str | None,
) -> dict[str, Any]:
    """One worksheet row, plus whatever the institute profile derives from it.

    The derivation runs on exactly the run shown as ``latest`` — the same
    winner, never a second selection that could disagree with it — and is
    emitted even when there is none, so the row can still state the target the
    next measurement will be judged against.
    """
    live, withdrawn = _partition_withdrawn(evidence_by_type.get(test_type, ()))
    winner = max(live, key=_run_rank) if live else None
    latest = _worksheet_latest_run(winner, attachment_counts) if winner is not None else None
    return {
        "test_type": test_type,
        "status": _status_for(test_type, results, pending),
        "latest": latest,
        "staged": list(staged_by_test.get(test_type, ())),
        "run_count": len(live),
        "withdrawn_count": withdrawn,
        "derived": derivation_payload(
            derive_evidence(
                glue_model,
                test_type=test_type,
                type_code=type_code,
                evidence=winner,
            )
        ),
    }


def _build_worksheet(
    component: Component,
    model: StageModel,
    results: Mapping[str, bool],
    *,
    pending: frozenset[str],
    staged_by_test: Mapping[str, list[dict[str, Any]]],
    evidence_rows: list[TestRunEvidence],
    attachment_counts: Mapping[str, Mapping[str | None, int]],
    glue_model: GlueDerivationModel,
) -> dict[str, Any]:
    """One group per stage in the institute's model (incl. future stages).

    A trailing ``stage: None`` "Additional" group covers test types no stage
    requires that nonetheless have visible work — mirrored evidence, a staged
    upload, or a confirmed-but-not-yet-mirrored result; it is omitted entirely
    when there is nothing to show.
    """
    evidence_by_type: dict[str, list[TestRunEvidence]] = {}
    for row in evidence_rows:
        if row.test_type:
            evidence_by_type.setdefault(row.test_type, []).append(row)

    current_index = (
        model.order.index(component.stage) if component.stage in model.order else None
    )

    def _row(test_type: str) -> dict[str, Any]:
        return _worksheet_row(
            test_type,
            results=results,
            pending=pending,
            staged_by_test=staged_by_test,
            evidence_by_type=evidence_by_type,
            attachment_counts=attachment_counts.get(test_type, {}),
            glue_model=glue_model,
            type_code=component.type_code,
        )

    groups: list[dict[str, Any]] = []
    required_test_types: set[str] = set()
    for index, stage in enumerate(model.order):
        stage_tests = model.required_tests.get(stage, ())
        required_test_types.update(stage_tests)
        if current_index is None:
            # An off-model current stage (e.g. FAILED, or any other
            # institute-specific terminal stage the ordered model never lists)
            # is the common case on real production data, not an edge case —
            # we cannot know how far such a component actually progressed
            # through the ordered stages, so the honest default is to show the
            # whole sheet as reached/readable rather than dim it as entirely
            # not-yet-reached.
            reached = True
        else:
            reached = index <= current_index
        groups.append(
            {
                "stage": stage,
                "reached": reached,
                "rows": [_row(test_type) for test_type in stage_tests],
            }
        )

    # Union of everything that could show a row: mirrored evidence, open staged
    # uploads, confirmed-but-not-yet-mirrored results (`results` also holds
    # confirmed local uploads, see `satisfied_test_results`) and configured
    # glue derivations. The last set matters before the first run exists: its
    # row must already state the target and the explicit `no_run` verdict.
    additional_test_types = (
        set(evidence_by_type)
        | set(staged_by_test)
        | set(results)
        | set(glue_model.test_types)
    )
    additional = sorted(additional_test_types - required_test_types)
    if additional:
        groups.append(
            {
                "stage": None,
                "reached": True,
                "rows": [_row(test_type) for test_type in additional],
            }
        )

    return {"groups": groups}


class _RunMeta:
    """One mirrored run without its payload.

    Child evidence is planned on this shape first because the payload column is
    the expensive part: on the owner's mirror the child runs of a single module
    reach 31 MB of JSON (response curves and IV sweeps), while only the newest
    run per (child, test type) is ever summarised. Loading the whole thing to
    then discard 99% of it would make opening a module page cost more than the
    entire feature saves.
    """

    __slots__ = ("id", "component_sn", "test_type", "measured_at", "synced_at", "run_state")

    def __init__(self, id, component_sn, test_type, measured_at, synced_at, run_state) -> None:
        self.id = id
        self.component_sn = component_sn
        self.test_type = test_type
        self.measured_at = measured_at
        self.synced_at = synced_at
        self.run_state = run_state


def _child_evidence_groups(
    session: Session, children: Sequence[Component]
) -> list[dict[str, Any]]:
    """One evidence group per assembled part, in the same compact row shape.

    The caller selects the parts (`attachment_store.assembled_parts`): direct
    children, plus one hop through a child that is itself a module, because an
    R3-R5 module is stitched and its sensors and powerboards hang off its half
    modules.

    Cost is independent of how many children there are: one query for the
    children's run metadata, one for the payloads of the selected newest runs
    only, and a constant two-query association/legacy attachment read. Never
    one query per child.

    Child rows carry no requirement `status` on purpose — a requirement is a
    statement about the component whose page this is, and the parent's stage
    gate is unchanged by anything shown here. What a child row does carry is
    the run's own pass/fail, which is the fact the operator came for.
    """
    if not children:
        return []
    child_sns = [child.sn for child in children]

    meta_rows = [
        _RunMeta(*row)
        for row in session.execute(
            select(
                TestRunEvidence.id,
                TestRunEvidence.component_sn,
                TestRunEvidence.test_type,
                TestRunEvidence.measured_at,
                TestRunEvidence.synced_at,
                TestRunEvidence.run_state,
            ).where(TestRunEvidence.component_sn.in_(child_sns))
        )
    ]

    grouped: dict[str, dict[str, list[_RunMeta]]] = {}
    for meta in meta_rows:
        if not meta.test_type:
            continue
        grouped.setdefault(meta.component_sn, {}).setdefault(meta.test_type, []).append(meta)

    winners: dict[tuple[str, str], _RunMeta] = {}
    counts: dict[tuple[str, str], tuple[int, int]] = {}
    for child_sn, by_type in grouped.items():
        for test_type, runs in by_type.items():
            live, withdrawn = _partition_withdrawn(runs)
            counts[(child_sn, test_type)] = (len(live), withdrawn)
            if live:
                winners[(child_sn, test_type)] = max(live, key=_run_rank)

    payloads: dict[int, TestRunEvidence] = {}
    if winners:
        payloads = {
            row.id: row
            for row in session.scalars(
                select(TestRunEvidence).where(
                    TestRunEvidence.id.in_([meta.id for meta in winners.values()])
                )
            )
        }

    attachment_counts = attachment_counts_by_run(session, child_sns) if winners else {}

    groups: list[dict[str, Any]] = []
    for child in children:
        rows: list[dict[str, Any]] = []
        for test_type in sorted(grouped.get(child.sn, {})):
            run_count, withdrawn = counts[(child.sn, test_type)]
            winner = winners.get((child.sn, test_type))
            latest = (
                _worksheet_latest_run(
                    payloads[winner.id],
                    attachment_counts.get(child.sn, {}).get(test_type, {}),
                )
                if winner is not None and winner.id in payloads
                else None
            )
            rows.append(
                {
                    "test_type": test_type,
                    "latest": latest,
                    "run_count": run_count,
                    "withdrawn_count": withdrawn,
                }
            )
        groups.append(
            {
                "sn": child.sn,
                "component_type": child.component_type,
                "type_code": child.type_code,
                "local_name": child.local_name,
                "rows": rows,
            }
        )
    return groups


def build_component_preview(
    session: Session,
    component: Component,
    settings: Any,
) -> dict[str, Any]:
    """Project open actions for ``component`` over the local mirror.

    Stage moves are applied oldest first. Pending test uploads override the
    corresponding projected requirement check with the explicit ``pending``
    state; they never masquerade as already passed evidence, and they are the
    only runs in ``projected.ghost_tests`` — they exist nowhere else, whereas
    mirrored runs are already served in full by the dedicated tests endpoint.
    """
    profile_settings = _profile_settings(session, component)
    # Built once and threaded through: checks (current and projected) and the
    # worksheet must reason about the exact same stage model, structurally,
    # not merely by chance re-parsing identical settings three times.
    model = stage_model_from_settings(profile_settings)
    # Same reason the stage model is built once: every row must judge against
    # the identical glue rules structurally, not by re-parsing the same profile
    # per row. The server derives, the page renders — the formula exists once.
    glue_model = glue_model_from_settings(profile_settings)
    results = satisfied_test_results(session, component.sn)

    actions = _open_actions_for(session, component.sn)

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
    staged_by_test: dict[str, list[dict[str, Any]]] = {}
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
            staged_by_test.setdefault(test_type, []).append(
                {"outbox_action_id": action.id, "status": action.status}
            )
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

    # One query for the whole worksheet grouping. Mirrored runs are summarised
    # here and never leave in full: the raw values live behind
    # ``GET /api/components/{sn}/tests``, which the module page requests only
    # when the operator opens "All mirrored runs".
    #
    # Withdrawn runs are fetched too, not filtered out in SQL: the row reports
    # how many of its runs the PDB has retracted, and a test type whose runs
    # are *all* retracted must still appear (reading `missing`) instead of
    # disappearing from the sheet as if it had never been attempted.
    evidence_rows = list(
        session.scalars(
            select(TestRunEvidence)
            .where(TestRunEvidence.component_sn == component.sn)
            .order_by(
                TestRunEvidence.measured_at,
                TestRunEvidence.synced_at,
                TestRunEvidence.id,
            )
        )
    )
    # Only the per-run count is part of the worksheet contract, so count the
    # rows instead of building a read model per attachment: that projection
    # stats the attachment directory for its `stored` flag, which is pure waste
    # here and belongs to the endpoints that actually render attachments.
    attachment_counts = attachment_counts_by_run(session, [component.sn]).get(component.sn, {})
    pending = frozenset(pending_tests)
    worksheet = _build_worksheet(
        component,
        model,
        results,
        pending=pending,
        staged_by_test=staged_by_test,
        evidence_rows=evidence_rows,
        attachment_counts=attachment_counts,
        glue_model=glue_model,
    )
    worksheet["children"] = _child_evidence_groups(
        session, assembled_parts(session, component.id)
    )

    return {
        "current": {
            "stage": component.stage,
            "checks": _checks(component.stage, results, model),
        },
        "staged_actions": staged_actions,
        "projected": {
            "stage": projected_stage,
            "checks": _checks(
                projected_stage,
                results,
                model,
                pending=pending,
            ),
            "ghost_tests": ghost_tests,
        },
        "worksheet": worksheet,
    }
