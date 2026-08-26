"""Build the local jig/tool registry from mirrored PDB tool components.

The PDB already exposes physical tools as components (for strips these are
usually component type ``TOOLS`` and serials such as ``20USERT...``). The
component mirror keeps them read-only; this module derives local ``Tool`` rows
from that mirror so the assembly wizard can offer scanner-first quick-selects.

Institute-specific classification stays in ``InstituteProfile.settings``:

``tool_component_types``
    List of PDB component types to import. Defaults to ``["TOOLS"]``.
``tool_kind_rules``
    Ordered rules ``{"kind": "pickup_tool", "contains": ["pickup"]}``.
``tool_compatibility``
    Exact mapping from tool serial/local name to compatible type list.
``tool_compatibility_rules``
    Ordered contains/regex rules with ``compatible_types``.
``tool_status_by_stage``
    Optional stage-code to ``active``/``flagged``/``blacklisted`` mapping.

Defaults are deliberately generic and only inspect mirrored data; no PDB writes
or network calls happen here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import Component, InstituteProfile, Tool

DEFAULT_TOOL_COMPONENT_TYPES = ("TOOLS",)
DEFAULT_TOOL_KIND_RULES = (
    {"kind": "pickup_tool", "contains": ("pickup",)},
    {"kind": "panel", "contains": ("panel",)},
    {"kind": "jig", "contains": ("jig", "stencil", "frame")},
)
VALID_STATUSES = {"active", "flagged", "blacklisted"}
STATUS_RANK = {"active": 0, "flagged": 1, "blacklisted": 2}

TYPE_TOKEN_RE = re.compile(
    r"(?<![A-Z0-9])R[0-9](?:M[0-9]|H[0-9][A-Z]?|PB)?(?![A-Z0-9])", re.I
)


@dataclass(frozen=True)
class ToolSyncStats:
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped: int = 0

    @property
    def total(self) -> int:
        return self.created + self.updated + self.unchanged


def sync_tools_from_components(session: Session, institute: InstituteProfile) -> ToolSyncStats:
    """Upsert local ``Tool`` rows from mirrored PDB tool components.

    Scope is "available to this institute": owned by or currently located at
    the institute. ``Tool.institute_id`` is set to the local profile id even if
    the PDB owner differs, because this registry backs site-local operations.
    """

    settings = institute.settings or {}
    component_types = _component_types(settings)
    rows = list(
        session.scalars(
            select(Component)
            .where(Component.component_type.in_(component_types))
            .where(
                or_(
                    Component.institute_code == institute.code,
                    Component.location == institute.code,
                )
            )
            .order_by(Component.local_name.nulls_last(), Component.sn)
        )
    )

    desired_rows: list[dict[str, Any]] = []
    skipped = 0
    for component in rows:
        desired = _tool_values(component, institute, settings)
        if desired is None:
            skipped += 1
            continue
        desired_rows.append(desired)

    # Production mirrors can contain many TOOLS rows. Resolve existing local
    # entries in bounded batches instead of issuing one SELECT per component.
    existing_by_code: dict[str, Tool] = {}
    desired_codes = sorted({desired["code"] for desired in desired_rows})
    for offset in range(0, len(desired_codes), 500):
        code_chunk = desired_codes[offset : offset + 500]
        for tool in session.scalars(
            select(Tool).where(
                Tool.institute_id == institute.id,
                Tool.code.in_(code_chunk),
            )
        ):
            existing_by_code[tool.code] = tool

    created = updated = unchanged = 0
    for desired in desired_rows:
        tool = existing_by_code.get(desired["code"])
        if tool is None:
            tool = Tool(**desired)
            session.add(tool)
            existing_by_code[desired["code"]] = tool
            created += 1
            continue

        changed = False
        for field, value in desired.items():
            if field == "rfid":
                continue  # local RFID edits are authoritative until PDB mirroring exists
            if field == "status":
                value = _stronger_status(tool.status, value)
            if getattr(tool, field) != value:
                setattr(tool, field, value)
                changed = True
        if changed:
            updated += 1
        else:
            unchanged += 1
    session.flush()
    return ToolSyncStats(created=created, updated=updated, unchanged=unchanged, skipped=skipped)


def _component_types(settings: dict) -> tuple[str, ...]:
    raw = settings.get("tool_component_types")
    if isinstance(raw, list) and all(isinstance(item, str) and item for item in raw):
        return tuple(raw)
    return DEFAULT_TOOL_COMPONENT_TYPES


def _tool_values(
    component: Component, institute: InstituteProfile, settings: dict
) -> dict[str, Any] | None:
    kind = _kind(component, settings)
    if kind is None:
        return None
    return {
        "kind": kind,
        "code": component.sn,
        "label": component.local_name,
        "rfid": None,
        "compatible_types": _compatible_types(component, settings),
        "institute_id": institute.id,
        "status": _status(component, settings),
    }


def _haystack(component: Component) -> str:
    return " ".join(
        part
        for part in (component.sn, component.local_name, component.type_code, component.stage)
        if part
    ).lower()


def _kind(component: Component, settings: dict) -> str | None:
    haystack = _haystack(component)
    for rule in _kind_rules(settings):
        kind = rule["kind"]
        contains = rule.get("contains", ())
        if any(term.lower() in haystack for term in contains):
            return kind
    return "tool"


def _kind_rules(settings: dict) -> list[dict[str, Any]]:
    raw = settings.get("tool_kind_rules")
    if not isinstance(raw, list):
        return list(DEFAULT_TOOL_KIND_RULES)
    rules: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        contains = item.get("contains")
        if isinstance(kind, str) and isinstance(contains, list) and all(
            isinstance(term, str) and term for term in contains
        ):
            rules.append({"kind": kind, "contains": tuple(contains)})
    return rules or list(DEFAULT_TOOL_KIND_RULES)


def _compatible_types(component: Component, settings: dict) -> list[str]:
    exact = settings.get("tool_compatibility")
    if isinstance(exact, dict):
        for key in (component.sn, component.local_name):
            value = exact.get(key) if key is not None else None
            if _is_string_list(value):
                return _dedupe_types(value)

    text = _haystack(component)
    raw_rules = settings.get("tool_compatibility_rules")
    if isinstance(raw_rules, list):
        for rule in raw_rules:
            if not isinstance(rule, dict):
                continue
            value = rule.get("compatible_types")
            if not _is_string_list(value):
                continue
            contains = rule.get("contains")
            regex = rule.get("regex")
            if _matches_rule(text, contains, regex):
                return _dedupe_types(value)

    tokens = TYPE_TOKEN_RE.findall(text.upper())
    return _dedupe_types(tokens)


def _is_string_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _dedupe_types(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        item = value.strip().upper()
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _matches_rule(text: str, contains: Any, regex: Any) -> bool:
    if isinstance(contains, list) and any(
        isinstance(term, str) and term.lower() in text for term in contains
    ):
        return True
    if isinstance(regex, str):
        try:
            return re.search(regex, text, flags=re.IGNORECASE) is not None
        except re.error:
            return False
    return False


def _status(component: Component, settings: dict) -> str:
    if component.trashed:
        return "blacklisted"
    if component.stale:
        return "flagged"

    stage = component.stage.upper()
    mapping = settings.get("tool_status_by_stage")
    if isinstance(mapping, dict):
        mapped = mapping.get(component.stage) or mapping.get(stage)
        if isinstance(mapped, str) and mapped in VALID_STATUSES:
            return mapped

    if any(term in stage for term in ("FAILED", "TRASHED", "DAMAGED", "BROKEN")):
        return "blacklisted"
    if any(term in stage for term in ("MAINT", "REPAIR", "HOLD")):
        return "flagged"
    return "active"


def _stronger_status(current: str, desired: str) -> str:
    if current not in STATUS_RANK:
        return desired
    if desired not in STATUS_RANK:
        return current
    return current if STATUS_RANK[current] > STATUS_RANK[desired] else desired
