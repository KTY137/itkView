"""Server-side reception-test projection for mirrored shipments.

Reception requirements are institute profile data.  This module projects the
local test evidence and staged upload queue over shipment items without
touching the PDB or mutating the mirror.  Open uploads are deliberately
``pending`` even when their payload says ``passed``; only mirrored evidence or
an already confirmed itkFlow upload can satisfy a reception requirement.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal, TypedDict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Component,
    InstituteProfile,
    OutboxAction,
    Shipment,
    TestRunEvidence,
)
from app.outbox import TERMINAL, OutboxStatus

ReceptionTestStatus = Literal["missing", "pending", "passed", "failed"]


class ReceptionTestRequirement(TypedDict):
    test_type: str
    status: ReceptionTestStatus


class ReceptionItemProjection(TypedDict):
    sn: str
    component_type: str | None
    component_mirrored: bool
    is_dummy: bool
    submittable: bool
    submittable_reason: str | None
    reception_tests_configured: bool
    reception_test_status: ReceptionTestStatus
    reception_tests: list[ReceptionTestRequirement]


class ReceptionShipmentProjection(TypedDict):
    reception_tests_configured: bool
    reception_test_status: ReceptionTestStatus
    items: list[ReceptionItemProjection]


def reception_test_mapping(settings: Any) -> dict[str, tuple[str, ...]]:
    """Read the normalized mapping defensively from profile JSON.

    Invalid legacy values are ignored instead of making all shipment reads
    fail.  New writes are validated by :mod:`app.institute_settings`.
    """

    if not isinstance(settings, Mapping):
        return {}
    raw = settings.get("shipment_reception_tests")
    if not isinstance(raw, Mapping):
        return {}

    mapping: dict[str, tuple[str, ...]] = {}
    for raw_component_type, raw_test_types in raw.items():
        if not isinstance(raw_component_type, str) or not isinstance(raw_test_types, list):
            continue
        component_type = raw_component_type.strip().upper()
        if not component_type:
            continue
        test_types: list[str] = []
        for raw_test_type in raw_test_types:
            if not isinstance(raw_test_type, str):
                continue
            test_type = raw_test_type.strip().upper()
            if test_type and test_type not in test_types:
                test_types.append(test_type)
        if test_types:
            mapping[component_type] = tuple(test_types)
    return mapping


def _action_target(action: OutboxAction) -> tuple[str, str] | None:
    payload = action.payload if isinstance(action.payload, dict) else {}
    component_sn = payload.get("component_sn")
    test_type = payload.get("test_type")
    if not isinstance(component_sn, str) or not isinstance(test_type, str):
        return None
    component_sn = component_sn.strip()
    test_type = test_type.strip().upper()
    if not component_sn or not test_type:
        return None
    return component_sn, test_type


def _aggregate(statuses: Sequence[ReceptionTestStatus]) -> ReceptionTestStatus:
    """Collapse detailed requirements without ever treating pending as pass."""

    if "failed" in statuses:
        return "failed"
    if "pending" in statuses:
        return "pending"
    if "missing" in statuses:
        return "missing"
    return "passed"


def project_shipment_reception_tests(
    session: Session,
    shipments: Sequence[Shipment],
) -> dict[int, ReceptionShipmentProjection]:
    """Bulk-project reception tests for ``shipments`` from local state only."""

    if not shipments:
        return {}

    institute_ids = {
        shipment.institute_id
        for shipment in shipments
        if shipment.institute_id is not None
    }
    institutes = (
        {
            profile.id: profile
            for profile in session.scalars(
                select(InstituteProfile).where(InstituteProfile.id.in_(institute_ids))
            )
        }
        if institute_ids
        else {}
    )
    mappings = {
        institute_id: reception_test_mapping(profile.settings)
        for institute_id, profile in institutes.items()
    }

    serials = {
        item.get("sn")
        for shipment in shipments
        for item in (shipment.items if isinstance(shipment.items, list) else [])
        if isinstance(item, dict) and isinstance(item.get("sn"), str) and item.get("sn")
    }
    components = (
        {
            component.sn: component
            for component in session.scalars(select(Component).where(Component.sn.in_(serials)))
        }
        if serials
        else {}
    )

    # Ordered oldest to newest so assignment leaves the most recent local
    # evidence for each component/test pair.
    evidence_results: dict[tuple[str, str], bool] = {}
    if serials:
        evidence = session.scalars(
            select(TestRunEvidence)
            .where(TestRunEvidence.component_sn.in_(serials))
            .order_by(
                TestRunEvidence.measured_at,
                TestRunEvidence.synced_at,
                TestRunEvidence.id,
            )
        )
        for row in evidence:
            test_type = row.test_type.strip().upper() if row.test_type else ""
            if test_type:
                evidence_results[(row.component_sn, test_type)] = bool(row.passed)

    pending_by_institute: dict[int, set[tuple[str, str]]] = {}
    confirmed_by_institute: dict[int, dict[tuple[str, str], bool]] = {}
    if institute_ids:
        actions = session.scalars(
            select(OutboxAction)
            .where(
                OutboxAction.institute_id.in_(institute_ids),
                OutboxAction.kind == "upload_test_run",
                OutboxAction.status != OutboxStatus.CANCELLED.value,
            )
            .order_by(OutboxAction.updated_at, OutboxAction.id)
        )
        terminal_values = {status.value for status in TERMINAL}
        for action in actions:
            target = _action_target(action)
            if target is None:
                continue
            if action.status == OutboxStatus.CONFIRMED.value:
                payload = action.payload if isinstance(action.payload, dict) else {}
                confirmed_by_institute.setdefault(action.institute_id, {})[target] = bool(
                    payload.get("passed")
                )
            elif action.status not in terminal_values:
                pending_by_institute.setdefault(action.institute_id, set()).add(target)

    projections: dict[int, ReceptionShipmentProjection] = {}
    for shipment in shipments:
        mapping = mappings.get(shipment.institute_id, {})
        pending = pending_by_institute.get(shipment.institute_id or -1, set())
        confirmed = confirmed_by_institute.get(shipment.institute_id or -1, {})
        item_projections: list[ReceptionItemProjection] = []
        item_statuses: list[ReceptionTestStatus] = []

        for raw_item in shipment.items if isinstance(shipment.items, list) else []:
            if not isinstance(raw_item, dict):
                continue
            raw_sn = raw_item.get("sn")
            if not isinstance(raw_sn, str) or not raw_sn:
                continue
            component = components.get(raw_sn)
            raw_component_type = raw_item.get("component_type")
            component_type = (
                raw_component_type.strip().upper()
                if isinstance(raw_component_type, str) and raw_component_type.strip()
                else component.component_type.upper()
                if component is not None
                else None
            )
            required = mapping.get(component_type or "", ())
            requirements: list[ReceptionTestRequirement] = []
            for test_type in required:
                key = (raw_sn, test_type)
                if key in pending:
                    status: ReceptionTestStatus = "pending"
                else:
                    result = confirmed.get(key, evidence_results.get(key))
                    status = "missing" if result is None else "passed" if result else "failed"
                requirements.append({"test_type": test_type, "status": status})

            item_status = _aggregate([requirement["status"] for requirement in requirements])
            configured = bool(requirements)
            item_statuses.extend(requirement["status"] for requirement in requirements)
            is_dummy = bool(component is not None and component.is_dummy)
            item_projections.append(
                {
                    "sn": raw_sn,
                    "component_type": component_type,
                    "component_mirrored": component is not None,
                    "is_dummy": is_dummy,
                    "submittable": is_dummy,
                    "submittable_reason": None if is_dummy else (
                        "not_dummy" if component is not None else "component_not_mirrored"
                    ),
                    "reception_tests_configured": configured,
                    "reception_test_status": item_status,
                    "reception_tests": requirements,
                }
            )

        projections[shipment.id] = {
            "reception_tests_configured": bool(item_statuses),
            "reception_test_status": _aggregate(item_statuses),
            "items": item_projections,
        }
    return projections
