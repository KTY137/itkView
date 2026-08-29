# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-FileComment: itkflow-54299b0c9132
"""Canonical, PDB-inert assembly dry-run contract.

The assembly wizard and the outbox worker deliberately share this module.  A
request is first resolved entirely against the local mirror and local tool /
glue registries.  The resulting snapshot is safe to persist in an outbox
action; the worker evaluates the same inputs again immediately before a PDB
submit so a blacklisted tool, expired glue batch or changed component cannot
slip through after review.

The production write boundary is intentionally narrower than the general PDB
assembly model: both participants must be self-registered DUMMY components and
both component types must be on the MODULE/HYBRID safety allowlist.  Sensors
and ASICs are therefore never assembly-write targets in itkFlow (ADR 003).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.glue import pot_life_state
from app.models import Component, GlueBatch, InstituteProfile, Tool

ASSEMBLY_ACTION_KIND = "assemble_component"
SAFE_ASSEMBLY_COMPONENT_TYPES = frozenset({"MODULE", "HYBRID"})
SAFE_ASSEMBLY_RELATIONSHIPS = frozenset({("MODULE", "HYBRID")})
_PROPERTY_KEY = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")

# The reserved slot key a bare ``tool_id`` is always shorthand for. Kept
# stable so legacy callers and institutes that configure `assembly_tool_slots`
# (docs/07) share one identity for the primary tool.
DEFAULT_TOOL_SLOT_KEY = "tool"
# Sheet-observed combined-tool columns (e.g. "Hybrid pickups used, top,
# bottom") never exceed a handful of tools per step; this platform-wide cap
# bounds a `multiple: true` slot without institutes configuring it themselves.
# schemas.py bounds the wire payload to the same number; the wizard mirrors it.
MAX_SLOT_TOOLS = 4
_MAX_SLOT_TOOLS = MAX_SLOT_TOOLS


@dataclass(frozen=True)
class AssemblyIssue:
    code: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class AssemblyEvaluation:
    parent: Component | None
    child: Component | None
    institute: InstituteProfile | None
    # Legacy single-tool view: the default slot's tool when it resolved to
    # exactly one (the only shape the pre-slots contract ever had). ``None``
    # whenever the default slot is unused or holds more than one tool.
    tool: Tool | None
    # Every resolved slot, default included, as ``{slot_key: [tool, ...]}``.
    # Entries can hold ``None`` placeholders for ids that failed to resolve so
    # a blocked preview can still show which id was invalid.
    tools_by_slot: dict[str, list[Tool | None]]
    glue_batch: GlueBatch | None
    slot: str
    issues: tuple[AssemblyIssue, ...]
    warnings: tuple[AssemblyIssue, ...]
    submittable: bool
    submittable_reason: str | None
    pdb_properties: dict[str, str]

    @property
    def valid(self) -> bool:
        return not self.issues

    @property
    def summary(self) -> str:
        parent = self.parent.sn if self.parent is not None else "unknown parent"
        child = self.child.sn if self.child is not None else "unknown child"
        return f"Assemble {child} into {parent} at {self.slot or 'unspecified slot'}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "submittable": self.submittable,
            "submittable_reason": self.submittable_reason,
            "summary": self.summary,
            "slot": self.slot,
            "parent": _component_dict(self.parent),
            "child": _component_dict(self.child),
            "tool": _tool_dict(self.tool),
            "tools": {
                # Unresolved ids stay out of the snapshot: the issue list
                # already names them, and a None entry would 500 the response
                # model instead of returning the preview with its issues.
                key: [_tool_dict(tool) for tool in tools if tool is not None]
                for key, tools in self.tools_by_slot.items()
            },
            "glue_batch": _glue_dict(self.glue_batch),
            "pdb_properties": dict(self.pdb_properties),
            "issues": [issue.as_dict() for issue in self.issues],
            "warnings": [warning.as_dict() for warning in self.warnings],
        }


def _component_dict(component: Component | None) -> dict[str, Any] | None:
    if component is None:
        return None
    return {
        "sn": component.sn,
        "local_name": component.local_name,
        "component_type": component.component_type,
        "type_code": component.type_code,
        "stage": component.stage,
        "location": component.location,
        "institute_code": component.institute_code,
        "parent_sn": component.parent_sn,
        "is_dummy": bool(component.is_dummy),
        "stale": bool(component.stale),
        "trashed": bool(component.trashed),
    }


def _tool_dict(tool: Tool | None) -> dict[str, Any] | None:
    if tool is None:
        return None
    return {
        "id": tool.id,
        "kind": tool.kind,
        "code": tool.code,
        "label": tool.label,
        "rfid": tool.rfid,
        "compatible_types": list(tool.compatible_types or []),
        "status": tool.status,
    }


def _glue_dict(batch: GlueBatch | None) -> dict[str, Any] | None:
    if batch is None:
        return None
    state = pot_life_state(batch.mixed_at, batch.pot_life_minutes)
    return {
        "id": batch.id,
        "glue_type": batch.glue_type,
        "batch_no": batch.batch_no,
        "pdb_sn": batch.pdb_sn,
        "status": batch.status,
        "mixed_at": batch.mixed_at,
        "pot_life_minutes": batch.pot_life_minutes,
        "pot_life_remaining_seconds": state.remaining_seconds if state is not None else None,
        "pot_life_expired": state.expired if state is not None else False,
    }


def _settings_value(settings: Any, key: str, default: Any) -> Any:
    if isinstance(settings, Mapping):
        return settings.get(key, default)
    return getattr(settings, key, default)


def _allowed_component_types(settings: Any) -> frozenset[str]:
    raw = _settings_value(settings, "pdb_dummy_component_types", None)
    if isinstance(raw, (list, tuple, set, frozenset)):
        configured = {
            value.strip().upper()
            for value in raw
            if isinstance(value, str) and value.strip()
        }
        # A configuration can narrow the safe allowlist, never broaden it to
        # sensors/ASICs or another collaboration component category.
        return frozenset(configured & SAFE_ASSEMBLY_COMPONENT_TYPES)
    return SAFE_ASSEMBLY_COMPONENT_TYPES


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _profile_property_keys(
    profile_settings: Mapping[str, Any], parent: Component | None
) -> dict[str, str]:
    """Resolve semantic assembly fields to PDB property codes.

    Institutes may configure a direct map or maps keyed by a parent type code,
    component type, or ``default``.  Invalid keys are ignored instead of being
    forwarded to the PDB.  No institute-specific PDB property name lives in
    application code.
    """

    raw: Any = profile_settings.get("assembly_property_keys")
    if not isinstance(raw, Mapping):
        return {}
    candidate: Any = raw
    if parent is not None and any(isinstance(value, Mapping) for value in raw.values()):
        candidate = raw.get(parent.type_code)
        if not isinstance(candidate, Mapping):
            candidate = raw.get(parent.component_type)
        if not isinstance(candidate, Mapping):
            candidate = raw.get("default")
    if not isinstance(candidate, Mapping):
        return {}
    result: dict[str, str] = {}
    for semantic in ("tool", "glue_batch", "slot"):
        value = candidate.get(semantic)
        if isinstance(value, str):
            code = value.strip().upper()
            if _PROPERTY_KEY.fullmatch(code):
                result[semantic] = code
    return result


def _configured_tool_slots(profile_settings: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Read institute-configured assembly tool slots defensively.

    ``institute_settings.normalize_institute_settings_update`` is the only
    writer of a well-formed ``assembly_tool_slots`` list, but this reader must
    never raise on stored data that predates validation or was edited
    directly; malformed entries are ignored rather than blocking every
    assembly dry-run (mirrors ``_profile_property_keys`` below).
    """

    raw = profile_settings.get("assembly_tool_slots")
    if not isinstance(raw, list):
        return {}
    slots: dict[str, dict[str, Any]] = {}
    for entry in raw:
        if not isinstance(entry, Mapping):
            continue
        key = entry.get("key")
        if not isinstance(key, str) or not key.strip():
            continue
        kinds = entry.get("kinds")
        property_key = entry.get("property_key")
        normalised_property_key = None
        if isinstance(property_key, str):
            candidate = property_key.strip().upper()
            if _PROPERTY_KEY.fullmatch(candidate):
                normalised_property_key = candidate
        slots[key.strip()] = {
            "kinds": (
                [value.strip() for value in kinds if isinstance(value, str) and value.strip()]
                if isinstance(kinds, list)
                else None
            ),
            "multiple": entry.get("multiple") is True,
            "property_key": normalised_property_key,
        }
    return slots


def _merge_tool_slot_selection(
    tool_id: int | None,
    tools: Mapping[str, Any] | None,
) -> tuple[dict[str, list[int]], list[AssemblyIssue]]:
    """Fold the legacy single ``tool_id`` and multi-slot ``tools`` map into one
    canonical ``{slot_key: [tool_id, ...]}`` selection.

    ``tool_id`` is always shorthand for ``DEFAULT_TOOL_SLOT_KEY``. Supplying
    both is only accepted when they agree on that slot; on a genuine conflict
    the ``tools``-supplied value for the slot is kept (it "wins") while the
    conflict itself is still surfaced as a blocking issue.
    """

    issues: list[AssemblyIssue] = []
    resolved: dict[str, list[int]] = {}
    if tools is not None:
        if not isinstance(tools, Mapping):
            issues.append(
                AssemblyIssue(
                    "tools_invalid", "The tools field must map slot keys to tool id lists."
                )
            )
        else:
            for raw_key, raw_ids in tools.items():
                if not isinstance(raw_key, str) or not raw_key.strip():
                    issues.append(
                        AssemblyIssue(
                            "tools_invalid", "Every tools slot key must be a non-empty string."
                        )
                    )
                    continue
                key = raw_key.strip()
                if (
                    not isinstance(raw_ids, (list, tuple))
                    or not raw_ids
                    or any(
                        isinstance(item, bool) or not isinstance(item, int) for item in raw_ids
                    )
                ):
                    issues.append(
                        AssemblyIssue(
                            "tools_invalid", f"Slot '{key}' must list one or more tool ids."
                        )
                    )
                    continue
                resolved[key] = list(raw_ids)

    if tool_id is not None:
        existing = resolved.get(DEFAULT_TOOL_SLOT_KEY)
        if existing is not None and existing != [tool_id]:
            issues.append(
                AssemblyIssue(
                    "tool_slot_conflict",
                    "tool_id and tools disagree on the default tool slot.",
                )
            )
        else:
            resolved[DEFAULT_TOOL_SLOT_KEY] = [tool_id]

    if not resolved and not issues:
        issues.append(AssemblyIssue("tools_required", "At least one tool must be selected."))
    return resolved, issues


def _validate_slot_tool(
    tool: Tool | None,
    tool_id_value: int,
    *,
    slot_key: str,
    is_default: bool,
    institute: InstituteProfile | None,
    parent: Component | None,
    child: Component | None,
    kinds: list[str] | None,
) -> list[AssemblyIssue]:
    """Validate one resolved tool for one slot.

    The default slot keeps its original, unprefixed issue codes and its
    ``compatible_types``-vs-parent check byte-for-byte so pre-existing
    consumers of those codes never regress. Every slot additionally honours a
    configured ``kinds`` allowlist.
    """

    prefix = "" if is_default else f"{slot_key}_"
    problems: list[AssemblyIssue] = []
    if tool is None:
        message = (
            "The selected tool no longer exists."
            if is_default
            else f"The tool selected for slot '{slot_key}' no longer exists."
        )
        problems.append(AssemblyIssue(f"{prefix}tool_not_found", message))
        return problems
    if tool.status != "active":
        problems.append(
            AssemblyIssue(
                f"{prefix}tool_not_active",
                f"Tool {tool.code} is {tool.status}; only active tools may be used.",
            )
        )
    compatible = list(tool.compatible_types or [])
    if is_default:
        # The default slot keeps its historical parent-only check byte-for-byte.
        type_mismatch = parent is not None and parent.type_code not in compatible
        mismatch_label = parent.type_code if parent is not None else ""
    else:
        # Extra slots serve either side of the assembly (a hybrid glue jig fits
        # the hybrid, the module jig fits the module), so the tool must be
        # compatible with the parent OR the child type. A tool matching neither
        # is rejected — the server must never validate weaker than the client's
        # quick-select filter (review I2).
        candidate_types = [
            component.type_code for component in (parent, child) if component is not None
        ]
        type_mismatch = bool(candidate_types) and not any(
            type_code in compatible for type_code in candidate_types
        )
        mismatch_label = " or ".join(candidate_types)
    if type_mismatch:
        problems.append(
            AssemblyIssue(
                f"{prefix}tool_incompatible",
                f"Tool {tool.code} is not compatible with {mismatch_label}.",
            )
        )
    if kinds and tool.kind not in kinds:
        problems.append(
            AssemblyIssue(
                f"{prefix}tool_kind_not_allowed",
                f"Tool {tool.code} has kind '{tool.kind}', which slot '{slot_key}' does not allow.",
            )
        )
    if institute is not None and tool.institute_id != institute.id:
        message = (
            "The selected tool does not belong to the parent institute."
            if is_default
            else f"The tool selected for slot '{slot_key}' does not belong to the parent institute."
        )
        problems.append(AssemblyIssue(f"{prefix}tool_institute_mismatch", message))
    return problems


def _resolve_tool_slots(
    session: Session,
    profile_settings: Mapping[str, Any],
    ids_by_slot: Mapping[str, list[int]],
    *,
    institute: InstituteProfile | None,
    parent: Component | None,
    child: Component | None,
) -> tuple[dict[str, list[Tool | None]], list[AssemblyIssue]]:
    """Look up and validate every tool named by ``ids_by_slot``.

    Unknown slot keys (anything but ``DEFAULT_TOOL_SLOT_KEY`` that is not
    configured via ``assembly_tool_slots``) are rejected outright; known slots
    enforce their configured cardinality (``multiple`` allows 1..4, otherwise
    exactly 1, matching today's single default tool) before each individual
    tool is validated.
    """

    configured = _configured_tool_slots(profile_settings)
    issues: list[AssemblyIssue] = []
    tools_by_slot: dict[str, list[Tool | None]] = {}

    for slot_key, ids in ids_by_slot.items():
        is_default = slot_key == DEFAULT_TOOL_SLOT_KEY
        slot_config = configured.get(slot_key)
        if slot_config is None and not is_default:
            issues.append(
                AssemblyIssue(
                    "unknown_tool_slot",
                    f"'{slot_key}' is not a configured assembly tool slot.",
                )
            )
            continue
        multiple = bool((slot_config or {}).get("multiple"))
        kinds = (slot_config or {}).get("kinds")
        if multiple:
            count_ok = 1 <= len(ids) <= _MAX_SLOT_TOOLS
            count_message = (
                f"Slot '{slot_key}' requires between 1 and {_MAX_SLOT_TOOLS} tools; "
                f"got {len(ids)}."
            )
        else:
            count_ok = len(ids) == 1
            count_message = f"Slot '{slot_key}' requires exactly 1 tool; got {len(ids)}."
        if not count_ok:
            prefix = "" if is_default else f"{slot_key}_"
            issues.append(AssemblyIssue(f"{prefix}tool_count_invalid", count_message))
            # Do not resolve the individual ids of an oversized list: the
            # cardinality violation already blocks the action, and looping an
            # attacker-sized list would amplify into one SELECT and one issue
            # per id (review finding I1).
            tools_by_slot[slot_key] = []
            continue

        resolved_tools: list[Tool | None] = []
        for tool_id_value in ids:
            tool = session.get(Tool, tool_id_value)
            resolved_tools.append(tool)
            issues.extend(
                _validate_slot_tool(
                    tool,
                    tool_id_value,
                    slot_key=slot_key,
                    is_default=is_default,
                    institute=institute,
                    parent=parent,
                    child=child,
                    kinds=kinds,
                )
            )
        tools_by_slot[slot_key] = resolved_tools

    return tools_by_slot, issues


def _pdb_properties(
    profile_settings: Mapping[str, Any],
    parent: Component | None,
    tools_by_slot: Mapping[str, list[Tool | None]],
    glue_batch: GlueBatch | None,
    slot: str,
) -> dict[str, str]:
    """Map resolved tools/glue/slot onto PDB property codes.

    The default tool slot keeps using the existing ``assembly_property_keys``
    semantic map (``keys["tool"]``); every other slot carries its own PDB
    property code on its ``assembly_tool_slots`` entry. Multiple tools in one
    slot are comma-joined, matching the production sheet's combined jig/pickup
    columns (e.g. ``JIG_HYBRID_ALIGNMENT`` = "4, 4", duplicates included when
    the same physical tool was scanned twice).
    """

    keys = _profile_property_keys(profile_settings, parent)
    configured = _configured_tool_slots(profile_settings)
    properties: dict[str, str] = {}

    default_codes = [
        tool.code for tool in tools_by_slot.get(DEFAULT_TOOL_SLOT_KEY, []) if tool is not None
    ]
    if default_codes and "tool" in keys:
        properties[keys["tool"]] = ", ".join(default_codes)

    for slot_key, tools in tools_by_slot.items():
        if slot_key == DEFAULT_TOOL_SLOT_KEY:
            continue
        property_key = (configured.get(slot_key) or {}).get("property_key")
        codes = [tool.code for tool in tools if tool is not None]
        if codes and property_key:
            properties[property_key] = ", ".join(codes)

    if glue_batch is not None and "glue_batch" in keys:
        properties[keys["glue_batch"]] = glue_batch.pdb_sn or glue_batch.batch_no
    if slot and "slot" in keys:
        properties[keys["slot"]] = slot
    return properties


def evaluate_assembly(
    session: Session,
    settings: Any,
    *,
    parent_sn: str,
    child_sn: str,
    slot: str,
    tool_id: int | None = None,
    tools: Mapping[str, Any] | None = None,
    glue_batch_id: int | None = None,
    now: datetime | None = None,
) -> AssemblyEvaluation:
    """Resolve and validate one assembly intent against current local state.

    A single tool remains the common case: pass ``tool_id`` alone, exactly as
    before. Institutes that configure ``assembly_tool_slots`` (docs/07) — e.g.
    separate top/bottom hybrid glue jigs and pickup tools used together with a
    module jig, mirroring the production sheet's combined tool columns — can
    additionally pass ``tools`` as ``{slot_key: [tool_id, ...]}``. ``tool_id``
    is always shorthand for ``tools[DEFAULT_TOOL_SLOT_KEY]``; see
    ``_merge_tool_slot_selection`` for how the two combine.
    """

    parent_value = parent_sn.strip()
    child_value = child_sn.strip()
    slot_value = slot.strip()
    parent = session.scalar(
        select(Component).where(func.lower(Component.sn) == parent_value.lower())
    )
    child = session.scalar(
        select(Component).where(func.lower(Component.sn) == child_value.lower())
    )
    glue_batch = session.get(GlueBatch, glue_batch_id) if glue_batch_id is not None else None
    institute = (
        session.scalar(
            select(InstituteProfile).where(InstituteProfile.code == parent.institute_code)
        )
        if parent is not None
        else None
    )
    profile_settings = (
        institute.settings
        if institute is not None and isinstance(institute.settings, Mapping)
        else {}
    )

    issues: list[AssemblyIssue] = []
    warnings: list[AssemblyIssue] = []
    allowed_types = _allowed_component_types(settings)

    tool_slot_ids, tool_slot_issues = _merge_tool_slot_selection(tool_id, tools)
    issues.extend(tool_slot_issues)
    tools_by_slot, tool_validation_issues = _resolve_tool_slots(
        session,
        profile_settings,
        tool_slot_ids,
        institute=institute,
        parent=parent,
        child=child,
    )
    issues.extend(tool_validation_issues)
    default_tools = [t for t in tools_by_slot.get(DEFAULT_TOOL_SLOT_KEY, []) if t is not None]
    tool = default_tools[0] if len(default_tools) == 1 else None

    if parent is None:
        issues.append(AssemblyIssue("parent_not_found", "Parent component is not in the mirror."))
    if child is None:
        issues.append(AssemblyIssue("child_not_found", "Child component is not in the mirror."))
    if parent is not None and child is not None:
        if parent.id == child.id:
            issues.append(
                AssemblyIssue("same_component", "A component cannot be assembled into itself.")
            )
        if parent.component_type not in allowed_types:
            issues.append(
                AssemblyIssue(
                    "parent_type_not_allowed",
                    "The assembly parent must be an allowed DUMMY module or hybrid type.",
                )
            )
        if child.component_type not in allowed_types:
            issues.append(
                AssemblyIssue(
                    "child_type_not_allowed",
                    "The assembly child must be an allowed DUMMY module or hybrid type; "
                    "sensors and ASICs are never written by itkFlow.",
                )
            )
        if (
            parent.component_type in allowed_types
            and child.component_type in allowed_types
            and (parent.component_type, child.component_type)
            not in SAFE_ASSEMBLY_RELATIONSHIPS
        ):
            issues.append(
                AssemblyIssue(
                    "component_type_relationship_not_allowed",
                    "The assembly relationship must place a hybrid into a module.",
                )
            )
        if parent.institute_code != child.institute_code:
            issues.append(
                AssemblyIssue(
                    "institute_mismatch",
                    "Parent and child must belong to the same institute.",
                )
            )
        if parent.location != child.location:
            issues.append(
                AssemblyIssue(
                    "location_mismatch",
                    "Parent and child must be at the same mirrored location.",
                )
            )
        if child.parent_sn == parent.sn:
            issues.append(
                AssemblyIssue(
                    "already_assembled",
                    "The child is already assembled into this parent.",
                )
            )
        elif child.parent_sn is not None:
            issues.append(
                AssemblyIssue(
                    "child_has_parent",
                    f"The child is already assembled into {child.parent_sn}.",
                )
            )
        for role, component in (("parent", parent), ("child", child)):
            if component.location != component.institute_code:
                issues.append(
                    AssemblyIssue(
                        f"{role}_not_at_institute",
                        f"The {role} component is not at its owning institute.",
                    )
                )
            if component.stale:
                issues.append(
                    AssemblyIssue(
                        f"{role}_stale", f"The {role} mirror row is stale; sync before assembly."
                    )
                )
            if component.trashed:
                issues.append(
                    AssemblyIssue(
                        f"{role}_trashed", f"The {role} component is trashed."
                    )
                )
    if institute is None and parent is not None:
        issues.append(
            AssemblyIssue(
                "institute_not_configured",
                f"Institute '{parent.institute_code}' is not configured locally.",
            )
        )
    if not slot_value:
        issues.append(AssemblyIssue("slot_required", "An assembly slot or position is required."))

    current_time = _as_utc(now or datetime.now(timezone.utc))
    if glue_batch_id is not None:
        if glue_batch is None:
            issues.append(
                AssemblyIssue("glue_batch_not_found", "The selected glue batch no longer exists.")
            )
        else:
            if glue_batch.status != "in_use":
                issues.append(
                    AssemblyIssue(
                        "glue_batch_not_in_use",
                        f"Glue batch {glue_batch.batch_no} is {glue_batch.status}; "
                        "only an in-use batch may be selected.",
                    )
                )
            if institute is not None and glue_batch.institute_id != institute.id:
                issues.append(
                    AssemblyIssue(
                        "glue_batch_institute_mismatch",
                        "The selected glue batch does not belong to the parent institute.",
                    )
                )
            if (
                glue_batch.expiry_date is not None
                and _as_utc(glue_batch.expiry_date) <= current_time
            ):
                issues.append(
                    AssemblyIssue(
                        "glue_batch_expired",
                        f"Glue batch {glue_batch.batch_no} has passed its expiry date.",
                    )
                )
            if glue_batch.mixed_at is None:
                issues.append(
                    AssemblyIssue(
                        "glue_batch_not_mixed",
                        f"Glue batch {glue_batch.batch_no} has no active mix time.",
                    )
                )
            state = pot_life_state(
                glue_batch.mixed_at,
                glue_batch.pot_life_minutes,
                now=current_time,
            )
            if state is not None and state.expired:
                issues.append(
                    AssemblyIssue(
                        "glue_pot_life_expired",
                        f"Glue batch {glue_batch.batch_no} is past its pot life.",
                    )
                )
            elif glue_batch.mixed_at is not None and glue_batch.pot_life_minutes is None:
                warnings.append(
                    AssemblyIssue(
                        "glue_pot_life_untimed",
                        f"Glue batch {glue_batch.batch_no} has no configured pot-life countdown.",
                    )
                )

    valid = not issues
    scope = _settings_value(settings, "pdb_write_scope", "dummy_only")
    if not valid:
        submittable, submittable_reason = False, "validation_failed"
    elif scope != "dummy_only":
        submittable, submittable_reason = False, "write_scope_unavailable"
    elif parent is None or child is None or not parent.is_dummy or not child.is_dummy:
        submittable, submittable_reason = False, "not_dummy"
    else:
        submittable, submittable_reason = True, None

    return AssemblyEvaluation(
        parent=parent,
        child=child,
        institute=institute,
        tool=tool,
        tools_by_slot=tools_by_slot,
        glue_batch=glue_batch,
        slot=slot_value,
        issues=tuple(issues),
        warnings=tuple(warnings),
        submittable=submittable,
        submittable_reason=submittable_reason,
        pdb_properties=_pdb_properties(
            profile_settings,
            parent,
            tools_by_slot,
            glue_batch,
            slot_value,
        ),
    )


def canonical_action_payload(evaluation: AssemblyEvaluation) -> dict[str, Any]:
    """Create the immutable snapshot persisted with a valid dry-run.

    When only the default tool slot is used with exactly one tool — every
    action staged before the multi-slot contract, and still the common case —
    this returns exactly the historical shape (``tool_id``/``expected_tool_code``,
    no ``tools`` key) so existing consumers (worker revalidation, the
    component preview's submittability check) keep working unchanged. Once a
    second slot or more than one default-slot tool is involved, a ``tools``/
    ``expected_tools`` snapshot is added alongside; ``tool_id``/
    ``expected_tool_code`` stay populated too whenever the default slot still
    resolves to exactly one tool.
    """

    if not evaluation.valid or evaluation.parent is None or evaluation.child is None:
        raise ValueError("Cannot build an assembly action from a blocked preview.")
    if not any(
        tool is not None for tools in evaluation.tools_by_slot.values() for tool in tools
    ):
        raise ValueError("Cannot build an assembly action without a tool.")

    payload: dict[str, Any] = {
        "parent_sn": evaluation.parent.sn,
        "child_sn": evaluation.child.sn,
        "slot": evaluation.slot,
        "glue_batch_id": (
            evaluation.glue_batch.id if evaluation.glue_batch is not None else None
        ),
        "expected_parent_component_type": evaluation.parent.component_type,
        "expected_parent_type_code": evaluation.parent.type_code,
        "expected_parent_stage": evaluation.parent.stage,
        "expected_parent_location": evaluation.parent.location,
        "expected_parent_institute_code": evaluation.parent.institute_code,
        "expected_child_component_type": evaluation.child.component_type,
        "expected_child_type_code": evaluation.child.type_code,
        "expected_child_parent_sn": evaluation.child.parent_sn,
        "expected_child_location": evaluation.child.location,
        "expected_child_institute_code": evaluation.child.institute_code,
        "expected_glue_batch_no": (
            evaluation.glue_batch.batch_no if evaluation.glue_batch is not None else None
        ),
        "pdb_properties": dict(evaluation.pdb_properties),
        "dry_run_required": True,
    }

    if evaluation.tool is not None:
        payload["tool_id"] = evaluation.tool.id
        payload["expected_tool_code"] = evaluation.tool.code

    extra_slots = {
        key: tools
        for key, tools in evaluation.tools_by_slot.items()
        if key != DEFAULT_TOOL_SLOT_KEY
    }
    default_is_single = len(evaluation.tools_by_slot.get(DEFAULT_TOOL_SLOT_KEY, [])) <= 1
    if extra_slots or not default_is_single:
        payload["tools"] = {
            key: [tool.id for tool in tools if tool is not None]
            for key, tools in evaluation.tools_by_slot.items()
        }
        payload["expected_tools"] = {
            key: [tool.code for tool in tools if tool is not None]
            for key, tools in evaluation.tools_by_slot.items()
        }
    return payload


def revalidate_assembly_action(
    session: Session,
    action_payload: Mapping[str, Any],
    settings: Any = None,
) -> list[str]:
    """Return worker-blocking issues for a persisted assembly action.

    Accepts both the legacy single-``tool_id`` snapshot (no ``tools`` key —
    every action staged before the multi-slot contract, and still the common
    shape) and the newer ``tools`` snapshot, so shipping the slot contract
    never breaks an action already sitting in someone's outbox.
    """

    parent_sn = action_payload.get("parent_sn")
    child_sn = action_payload.get("child_sn")
    slot = action_payload.get("slot")
    tool_id = action_payload.get("tool_id")
    glue_batch_id = action_payload.get("glue_batch_id")
    has_tools_field = "tools" in action_payload
    tools = action_payload.get("tools")

    if not isinstance(parent_sn, str) or not isinstance(child_sn, str) or not isinstance(slot, str):
        return ["Assembly payload is missing parent, child, slot or tool identifiers."]
    if has_tools_field:
        if not isinstance(tools, Mapping) or not tools:
            return ["Assembly payload has an invalid tools mapping."]
        if tool_id is not None and (isinstance(tool_id, bool) or not isinstance(tool_id, int)):
            return ["Assembly payload has an invalid tool identifier."]
    elif isinstance(tool_id, bool) or not isinstance(tool_id, int):
        return ["Assembly payload is missing parent, child, slot or tool identifiers."]
    if glue_batch_id is not None and (
        isinstance(glue_batch_id, bool) or not isinstance(glue_batch_id, int)
    ):
        return ["Assembly payload has an invalid glue-batch identifier."]

    evaluation = evaluate_assembly(
        session,
        settings,
        parent_sn=parent_sn,
        child_sn=child_sn,
        slot=slot,
        tool_id=tool_id,
        tools=tools if has_tools_field else None,
        glue_batch_id=glue_batch_id,
    )
    errors = [issue.message for issue in evaluation.issues]
    if evaluation.valid and not evaluation.submittable:
        if evaluation.submittable_reason == "not_dummy":
            errors.append(
                "Both assembly participants must be itkFlow-registered DUMMY test components."
            )
        else:
            errors.append("The configured PDB write scope does not permit this assembly.")

    snapshots: tuple[tuple[str, Any], ...] = (
        (
            "parent component type",
            evaluation.parent.component_type if evaluation.parent is not None else None,
        ),
        (
            "parent type code",
            evaluation.parent.type_code if evaluation.parent is not None else None,
        ),
        ("parent stage", evaluation.parent.stage if evaluation.parent is not None else None),
        (
            "parent location",
            evaluation.parent.location if evaluation.parent is not None else None,
        ),
        (
            "parent institute",
            evaluation.parent.institute_code if evaluation.parent is not None else None,
        ),
        (
            "child component type",
            evaluation.child.component_type if evaluation.child is not None else None,
        ),
        ("child type code", evaluation.child.type_code if evaluation.child is not None else None),
        ("child parent", evaluation.child.parent_sn if evaluation.child is not None else None),
        (
            "child location",
            evaluation.child.location if evaluation.child is not None else None,
        ),
        (
            "child institute",
            evaluation.child.institute_code if evaluation.child is not None else None,
        ),
        ("tool code", evaluation.tool.code if evaluation.tool is not None else None),
        (
            "glue batch",
            evaluation.glue_batch.batch_no if evaluation.glue_batch is not None else None,
        ),
    )
    snapshot_keys = (
        "expected_parent_component_type",
        "expected_parent_type_code",
        "expected_parent_stage",
        "expected_parent_location",
        "expected_parent_institute_code",
        "expected_child_component_type",
        "expected_child_type_code",
        "expected_child_parent_sn",
        "expected_child_location",
        "expected_child_institute_code",
        "expected_tool_code",
        "expected_glue_batch_no",
    )
    for snapshot_key, (label, current) in zip(snapshot_keys, snapshots, strict=True):
        if action_payload.get(snapshot_key) != current:
            errors.append(f"Assembly {label} changed after the dry-run; create a new preview.")
    if has_tools_field:
        current_tools = {
            key: [tool.code for tool in resolved if tool is not None]
            for key, resolved in evaluation.tools_by_slot.items()
        }
        recorded_tools = action_payload.get("expected_tools")
        if not isinstance(recorded_tools, Mapping) or dict(recorded_tools) != current_tools:
            errors.append("Assembly tools changed after the dry-run; create a new preview.")
    if action_payload.get("pdb_properties") != evaluation.pdb_properties:
        errors.append("Assembly PDB properties changed after the dry-run; create a new preview.")
    return errors
