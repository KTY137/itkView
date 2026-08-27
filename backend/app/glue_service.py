"""Application service tying the pure glue-weight engine to the database.

The engine in `app.domain.glue` stays pure; this module supplies its inputs
from the local tables — an institute's glue rules, a component's type code and
a run's results — so the module page, the ingest dry-run and anything else that
needs a verdict all derive it the same way. Same relationship
`app.stage_service` has to `app.domain.stages`.

**Units are part of the contract.** The PDB holds every `GW_` result in grams
while glue targets and tolerances are stated in milligrams. The conversion
happens exactly twice and only here at the edges: `domain.glue` returns derived
weights in mg for judging and display, and `derived_result_grams` converts them
back to grams for the value that is uploaded. No renderer ever multiplies by a
thousand, and there is no second copy of the formula anywhere.

**The PDB does not judge.** All 14 module test schemas carry
`automaticGrading=false` with every threshold null, and the single `passed` bit
reproduces the production sheet's verdict only 80% of the time — for two
separate verdicts at once (hybrid and powerboard). Target, tolerance and
verdict can therefore only come from the institute profile.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.glue import (
    GlueDerivation,
    GlueDerivationModel,
    derive_run,
    derive_test_run_document,
    glue_model_from_settings,
    mg_to_grams,
)
from app.models import Component, InstituteProfile, TestRunEvidence
from app.test_run_evidence import live_runs_only

DERIVATION_KIND = "glue_weight"

# Re-exported so callers depend on the adapter rather than reaching past it into
# the pure engine; `app.ingestion` deliberately takes the domain route instead,
# because a payload parser must not pull the ORM in behind it.
__all__ = [
    "DERIVATION_KIND",
    "GlueDerivationModel",
    "derivation_payload",
    "derive_evidence",
    "derive_for_component",
    "derived_result_grams",
    "glue_model_from_settings",
    "institute_glue_model",
]


def institute_glue_model(session: Session, institute_code: str | None) -> GlueDerivationModel:
    """The explicitly configured derivation model of one institute."""
    profile = (
        session.scalar(select(InstituteProfile).where(InstituteProfile.code == institute_code))
        if institute_code
        else None
    )
    settings = profile.settings if profile is not None else None
    return glue_model_from_settings(settings if isinstance(settings, dict) else None)


def derive_evidence(
    model: GlueDerivationModel,
    *,
    test_type: str | None,
    type_code: str | None,
    evidence: TestRunEvidence | None,
) -> GlueDerivation | None:
    """Derive from a mirrored run, or from no run at all when `evidence` is None."""
    if evidence is None:
        return derive_run(model, test_type=test_type, type_code=type_code, results=None)
    return derive_test_run_document(
        model,
        test_type=test_type,
        type_code=type_code,
        payload=evidence.payload,
        measured_at=evidence.measured_at,
    )


def derive_for_component(
    session: Session, component: Component, *, test_type: str
) -> GlueDerivation | None:
    """Derive one component's newest live run of `test_type`.

    The session-bound entry point: it fetches the institute profile, the
    component's type code and the run, and hands the pure engine everything it
    needs. Withdrawn runs are excluded — a measurement the PDB no longer stands
    behind must not produce a verdict.
    """
    model = institute_glue_model(session, component.institute_code)
    if not model.derives(test_type):
        return None
    # Same winner rule as `stage_service.satisfied_test_results`: newest by
    # measured_at with undated runs losing to any dated one, ties broken on
    # synced_at then id. NULLS FIRST is pinned explicitly so SQLite and
    # PostgreSQL agree on which run is current.
    evidence = session.scalars(
        select(TestRunEvidence)
        .where(
            TestRunEvidence.component_sn == component.sn,
            TestRunEvidence.test_type == test_type,
            live_runs_only(),
        )
        .order_by(
            TestRunEvidence.measured_at.nullsfirst(),
            TestRunEvidence.synced_at,
            TestRunEvidence.id,
        )
    ).all()
    return derive_evidence(
        model,
        test_type=test_type,
        type_code=component.type_code,
        evidence=evidence[-1] if evidence else None,
    )


def derivation_payload(derivation: GlueDerivation | None) -> dict[str, Any] | None:
    """The wire shape of a derivation (spec 2026-08-27 §9.3).

    Weights are milligrams here — grams are the PDB's unit and stop at
    `derived_result_grams`. Every step always carries a verdict, and a verdict
    of `unknown` always carries a reason: a blank input must never render as if
    it were a result, which is how 8 of 13 powerboard verdicts on the owner's
    real sheet became arithmetic garbage.
    """
    if derivation is None:
        return None
    return {
        "kind": DERIVATION_KIND,
        "process": derivation.process,
        "process_source": derivation.process_source,
        "steps": [
            {
                "key": step.key,
                "label": step.label,
                "measured_mg": step.measured_mg,
                "target_mg": step.target.target_mg if step.target is not None else None,
                "tolerance_mg": step.target.tolerance_mg if step.target is not None else None,
                "verdict": step.verdict.value,
                "reason": step.reason.value if step.reason is not None else None,
                "result_code": step.result_code,
                "inputs": [
                    {"code": item.code, "name": item.name, "value": item.value}
                    for item in step.inputs
                ],
            }
            for step in derivation.steps
        ],
    }


def derived_result_grams(derivation: GlueDerivation | None) -> dict[str, float]:
    """The computed values keyed by the PDB result code they are uploaded under.

    Grams, because that is the unit every `GW_` code is declared in. This is the
    only place the milligrams the rest of the derivation speaks are converted
    back, and steps without a computed value or without a result code
    contribute nothing — an upload must never carry a fabricated zero.
    """
    if derivation is None:
        return {}
    return {
        # Derived weights are already rounded to 0.1 mg, so six decimal places
        # in grams are lossless; without the rounding the division leaves
        # binary-float debris (0.13269999999999998) in a PDB upload.
        step.result_code: round(mg_to_grams(step.measured_mg), 6)
        for step in derivation.steps
        if step.result_code is not None and step.measured_mg is not None
    }
