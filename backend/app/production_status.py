"""Production status projection for component overview surfaces.

The current stage is a work area: missing or failed tests assigned to that
stage are normal until the component advances. A component is held only when
it crossed a configured gate with failed evidence. Missing evidence after a
gate remains visible as incomplete, but is not presented as a physical defect.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.stages import has_explicit_stage_policy, stage_model_from_settings
from app.models import Component, InstituteProfile
from app.stage_service import satisfied_test_results_for_components


@dataclass(frozen=True)
class ProductionStatusReason:
    code: str
    stage: str | None = None
    test_type: str | None = None


@dataclass(frozen=True)
class ComponentProductionStatus:
    production_status: str
    production_policy_source: str | None
    production_policy_approved: bool | None
    production_status_reasons: list[ProductionStatusReason]


def production_status_for_components(
    session: Session, components: list[Component]
) -> dict[str, ComponentProductionStatus]:
    """Return one batched, institute-configured status per component.

    Only modules use the module-production stage model. Other component types
    remain visible but are explicitly not applicable, avoiding false holds on
    sensor and hybrid lifecycles that use different PDB stages.
    """

    module_rows = [component for component in components if component.component_type == "MODULE"]
    module_sns = [component.sn for component in module_rows]
    evidence = satisfied_test_results_for_components(session, module_sns)
    institute_codes = {component.institute_code for component in module_rows}
    profiles = {
        profile.code: profile
        for profile in session.scalars(
            select(InstituteProfile).where(InstituteProfile.code.in_(institute_codes))
        )
    }

    projected: dict[str, ComponentProductionStatus] = {}
    for component in components:
        if component.component_type != "MODULE":
            projected[component.sn] = ComponentProductionStatus(
                "not_applicable", None, None, []
            )
            continue

        reasons: list[ProductionStatusReason] = []
        if component.trashed:
            reasons.append(ProductionStatusReason("trashed"))
            projected[component.sn] = ComponentProductionStatus(
                "not_applicable", None, None, reasons
            )
            continue
        if component.stale:
            reasons.append(ProductionStatusReason("stale_mirror"))

        profile = profiles.get(component.institute_code)
        if profile is None:
            reasons.append(ProductionStatusReason("missing_profile"))
            projected[component.sn] = ComponentProductionStatus(
                "unknown", "missing_profile", False, reasons
            )
            continue

        settings = profile.settings or {}
        model = stage_model_from_settings(settings)
        # A partial override still inherits seed stages/requirements. It may
        # produce useful holds, but never a domain-approved clear.
        explicit_profile = has_explicit_stage_policy(settings)
        policy_source = "profile_override" if explicit_profile else "seed_default"
        policy_approved = explicit_profile and settings.get("stage_policy_approved") is True
        if not policy_approved:
            reasons.append(ProductionStatusReason("provisional_profile"))

        if component.stage not in model.order:
            reasons.append(ProductionStatusReason("unknown_stage", stage=component.stage))
            projected[component.sn] = ComponentProductionStatus(
                "unknown", policy_source, policy_approved, reasons
            )
            continue

        if component.stale:
            projected[component.sn] = ComponentProductionStatus(
                "unknown", policy_source, policy_approved, reasons
            )
            continue

        stage_index = model.order.index(component.stage)
        # Evidence becomes due only after its owning stage gate was crossed.
        # This stays strict even at the terminal stage: requirements assigned
        # to FINISHED describe a hypothetical move out of FINISHED, while a
        # component at FINISHED must have cleared every earlier gate.
        evidence_is_due_through = stage_index - 1
        results = evidence.get(component.sn, {})
        for requirement_index, stage in enumerate(model.order[: stage_index + 1]):
            for test_type in model.required_tests.get(stage, ()):
                if requirement_index > evidence_is_due_through:
                    continue
                if test_type in results and not results[test_type]:
                    reasons.append(
                        ProductionStatusReason(
                            "required_test_failed", stage=stage, test_type=test_type
                        )
                    )
                elif test_type not in results:
                    reasons.append(
                        ProductionStatusReason(
                            "required_test_missing", stage=stage, test_type=test_type
                        )
                    )

        has_failed_gate = any(
            reason.code == "required_test_failed" for reason in reasons
        )
        has_missing_gate = any(
            reason.code == "required_test_missing" for reason in reasons
        )
        status = (
            "hold"
            if has_failed_gate
            else "incomplete"
            if has_missing_gate
            else "clear"
            if policy_approved
            else "unknown"
        )
        projected[component.sn] = ComponentProductionStatus(
            status, policy_source, policy_approved, reasons
        )
    return projected


def annotate_production_status(session: Session, components: list[Component]) -> None:
    """Attach the read projection for Pydantic's from-attributes serializer."""

    statuses = production_status_for_components(session, components)
    for component in components:
        status = statuses[component.sn]
        component.production_status = status.production_status
        component.production_policy_source = status.production_policy_source
        component.production_policy_approved = status.production_policy_approved
        component.production_status_reasons = status.production_status_reasons
