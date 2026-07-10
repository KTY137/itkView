"""Ingestion parser registry — pure payload parsing, no DB or PDB I/O.

Uploaded instrument JSONs arrive in very different states of readiness. Each
parser turns one payload into the same normalized `ParsedTestRun` preview,
which the triage UI and the outbox dry-run gate share. Registry order
matters: the first parser whose `sniff` accepts the payload wins, and the
generic fallback accepts anything.

Issues are blocking (the file cannot become an outbox proposal until they are
resolved); warnings are informational and never block.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

# ATLAS ITk serial numbers: "20U" + subproject/type letters + 7 digits.
# Anything else in a component field is treated as a local name and resolved
# against the component mirror by the API layer.
SERIAL_NUMBER_RE = re.compile(r"^20U[A-Z]{2}[A-Z0-9]{2}\d{7}$")


def looks_like_serial_number(value: str) -> bool:
    return SERIAL_NUMBER_RE.fullmatch(value) is not None


class ResultSummary(BaseModel):
    """One entry of a payload's `results` block, condensed for preview."""

    name: str
    kind: str  # number | array | string | bool | object | null
    value: str  # short human-readable rendering, never the raw data


class ParsedTestRun(BaseModel):
    """Normalized preview of one uploaded instrument JSON."""

    parser: str
    component_sn: str | None = None
    local_name: str | None = None
    test_type: str | None = None
    run_number: str | None = None
    institution: str | None = None
    measured_at: str | None = None
    passed: bool | None = None
    problems: bool | None = None
    n_properties: int = 0
    results: list[ResultSummary] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class Parser:
    name: str
    sniff: Callable[[dict], bool]
    parse: Callable[[dict], ParsedTestRun]


def _summarize_result(name: str, value: Any) -> ResultSummary:
    if value is None:
        return ResultSummary(name=name, kind="null", value="null")
    if isinstance(value, bool):
        return ResultSummary(name=name, kind="bool", value="true" if value else "false")
    if isinstance(value, (int, float)):
        return ResultSummary(name=name, kind="number", value=f"{value:.6g}")
    if isinstance(value, str):
        short = value if len(value) <= 40 else value[:37] + "..."
        return ResultSummary(name=name, kind="string", value=short)
    if isinstance(value, list):
        return ResultSummary(name=name, kind="array", value=f"{len(value)} values")
    if isinstance(value, dict):
        return ResultSummary(name=name, kind="object", value=f"{len(value)} entries")
    return ResultSummary(name=name, kind="object", value=type(value).__name__)


def _summarize_results(results: dict) -> list[ResultSummary]:
    return [_summarize_result(str(name), value) for name, value in results.items()]


def first_string(payload: Any, keys: set[str]) -> str | None:
    """Depth-first search for the first non-empty string under any given key."""
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in keys and isinstance(value, str) and value.strip():
                return value.strip()
        for value in payload.values():
            found = first_string(value, keys)
            if found is not None:
                return found
    if isinstance(payload, list):
        for item in payload:
            found = first_string(item, keys)
            if found is not None:
                return found
    return None


def _assign_component(parsed: ParsedTestRun, identifier: str) -> None:
    if looks_like_serial_number(identifier):
        parsed.component_sn = identifier
    else:
        parsed.local_name = identifier
        parsed.warnings.append(
            f"Component '{identifier}' is not an ITk serial number; treating it as a local name"
        )


# --------------------------------------------------------------------------
# PDB test-run shape: component/testType/runNumber/date/passed/problems/
# properties/results — the schema `uploadTestRunResults` expects.
# --------------------------------------------------------------------------


def _sniff_pdb_test_run(payload: dict) -> bool:
    return (
        isinstance(payload.get("testType"), str)
        and payload["testType"].strip() != ""
        and ("component" in payload or "serialNumber" in payload)
    )


def _parse_pdb_test_run(payload: dict, parser_name: str = "pdb-test-run-v1") -> ParsedTestRun:
    parsed = ParsedTestRun(parser=parser_name, test_type=payload["testType"].strip())

    identifier = payload.get("component") or payload.get("serialNumber")
    if isinstance(identifier, str) and identifier.strip():
        _assign_component(parsed, identifier.strip())
    else:
        parsed.issues.append("Missing component identifier")

    run_number = payload.get("runNumber")
    if isinstance(run_number, (str, int)) and not isinstance(run_number, bool):
        parsed.run_number = str(run_number)
    else:
        parsed.warnings.append("Missing run number")

    institution = payload.get("institution")
    if isinstance(institution, str) and institution.strip():
        parsed.institution = institution.strip()

    date = payload.get("date")
    if isinstance(date, str) and date.strip():
        parsed.measured_at = date.strip()
        try:
            datetime.fromisoformat(date.strip().replace("Z", "+00:00"))
        except ValueError:
            parsed.warnings.append(f"Date '{date.strip()}' is not ISO 8601")
    else:
        parsed.warnings.append("Missing measurement date")

    passed = payload.get("passed")
    if isinstance(passed, bool):
        parsed.passed = passed
    else:
        parsed.issues.append("Missing field 'passed' (must be true/false)")

    problems = payload.get("problems")
    if isinstance(problems, bool):
        parsed.problems = problems
    else:
        parsed.warnings.append("Missing field 'problems'")

    properties = payload.get("properties")
    if isinstance(properties, dict):
        parsed.n_properties = len(properties)

    results = payload.get("results")
    if isinstance(results, dict) and results:
        parsed.results = _summarize_results(results)
    else:
        parsed.issues.append("Missing or empty 'results' object")

    return parsed


# --------------------------------------------------------------------------
# Glue weight: PDB shape with numeric GW_* results (scale readings in grams).
# --------------------------------------------------------------------------


def _sniff_glue_weight(payload: dict) -> bool:
    return _sniff_pdb_test_run(payload) and payload["testType"].strip() == "GLUE_WEIGHT"


def _parse_glue_weight(payload: dict) -> ParsedTestRun:
    parsed = _parse_pdb_test_run(payload, parser_name="glue-weight-v1")
    results = payload.get("results")
    if isinstance(results, dict):
        for name, value in results.items():
            if value is None:
                parsed.warnings.append(f"Result '{name}' is empty")
            elif isinstance(value, bool) or not isinstance(value, (int, float)):
                parsed.issues.append(f"Result '{name}' must be a number")
    return parsed


# --------------------------------------------------------------------------
# IV curve: paired VOLTAGE/CURRENT arrays (sensor/module leakage-current scans).
# --------------------------------------------------------------------------


def _numeric_array(results: dict, name: str) -> list | None:
    value = results.get(name)
    return value if isinstance(value, list) else None


def _sniff_iv_curve(payload: dict) -> bool:
    if not _sniff_pdb_test_run(payload):
        return False
    results = payload.get("results")
    if not isinstance(results, dict):
        return False
    return isinstance(results.get("VOLTAGE"), list) and isinstance(results.get("CURRENT"), list)


def _parse_iv_curve(payload: dict) -> ParsedTestRun:
    parsed = _parse_pdb_test_run(payload, parser_name="iv-curve-v1")
    results = payload.get("results", {})
    voltage = _numeric_array(results, "VOLTAGE")
    current = _numeric_array(results, "CURRENT")
    if not voltage:
        parsed.issues.append("IV curve has an empty 'VOLTAGE' array")
    if not current:
        parsed.issues.append("IV curve has an empty 'CURRENT' array")
    if voltage and current and len(voltage) != len(current):
        parsed.issues.append(
            f"IV curve arrays differ in length: VOLTAGE has {len(voltage)}, "
            f"CURRENT has {len(current)} points"
        )
    return parsed


# --------------------------------------------------------------------------
# Pull test: PULL_STRENGTH / PULL_GRADE arrays plus a NUMBER_WIRES property.
# --------------------------------------------------------------------------


def _sniff_pull_test(payload: dict) -> bool:
    if not _sniff_pdb_test_run(payload):
        return False
    results = payload.get("results")
    return isinstance(results, dict) and isinstance(results.get("PULL_STRENGTH"), list)


def _parse_pull_test(payload: dict) -> ParsedTestRun:
    parsed = _parse_pdb_test_run(payload, parser_name="pull-test-v1")
    results = payload.get("results", {})
    strengths = _numeric_array(results, "PULL_STRENGTH")
    grades = _numeric_array(results, "PULL_GRADE")
    if not strengths:
        parsed.issues.append("Pull test has an empty 'PULL_STRENGTH' array")
    if strengths and grades is not None and len(strengths) != len(grades):
        parsed.issues.append(
            f"Pull-test arrays differ in length: PULL_STRENGTH has {len(strengths)}, "
            f"PULL_GRADE has {len(grades)} entries"
        )
    properties = payload.get("properties")
    if isinstance(properties, dict) and strengths:
        declared = properties.get("NUMBER_WIRES")
        is_int = isinstance(declared, int) and not isinstance(declared, bool)
        if is_int and declared != len(strengths):
            parsed.warnings.append(
                f"NUMBER_WIRES says {declared} but PULL_STRENGTH has {len(strengths)} measurements"
            )
    return parsed


# --------------------------------------------------------------------------
# Generic fallback: heuristic key search anywhere in the document.
# --------------------------------------------------------------------------

_COMPONENT_KEYS = {
    "component",
    "component_sn",
    "componentSN",
    "serialNumber",
    "serial_number",
    "sn",
}
_TEST_TYPE_KEYS = {"testType", "test_type", "test", "type"}


def _parse_generic_json(payload: dict) -> ParsedTestRun:
    parsed = ParsedTestRun(parser="generic-json-v1")

    identifier = first_string(payload, _COMPONENT_KEYS)
    if identifier is not None:
        _assign_component(parsed, identifier)
    else:
        parsed.issues.append("Missing component identifier")

    test_type = first_string(payload, _TEST_TYPE_KEYS)
    if test_type is not None:
        parsed.test_type = test_type
    else:
        parsed.issues.append("Missing test type")

    parsed.warnings.append(
        "Payload does not follow the PDB test-run schema; fields were guessed heuristically"
    )
    return parsed


# --------------------------------------------------------------------------
# Module metrology (OGP Smartscope): the instrument/zFlow already converts its
# raw position + glue-height scan into these PDB result groups — positions as
# deviation-from-nominal, heights in µm (see docs/10). We validate that shape;
# the raw .txt -> JSON geometry conversion itself stays upstream for now.
# --------------------------------------------------------------------------

_METROLOGY_HEIGHT_GROUPS = ("HYBRID_GLUE_THICKNESS", "PB_GLUE_THICKNESS", "CAP_HEIGHT")
_METROLOGY_POSITION_GROUPS = ("HYBRID_POSITION", "PB_POSITION")


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _sniff_metrology(payload: dict) -> bool:
    return _sniff_pdb_test_run(payload) and payload["testType"].strip() == "MODULE_METROLOGY"


def _parse_metrology(payload: dict) -> ParsedTestRun:
    parsed = _parse_pdb_test_run(payload, parser_name="module-metrology-v1")
    results = payload.get("results")
    if not isinstance(results, dict):
        return parsed  # the base parser already flagged missing results

    groups_seen = 0
    for group in _METROLOGY_HEIGHT_GROUPS:
        values = results.get(group)
        if values is None:
            continue
        groups_seen += 1
        if isinstance(values, dict):
            bad = sorted(k for k, v in values.items() if not _is_number(v))
            if bad:
                parsed.issues.append(f"{group} has non-numeric heights: {', '.join(bad[:5])}")
        elif not _is_number(values):
            parsed.issues.append(f"{group} must be a number or a map of numbers")

    for group in _METROLOGY_POSITION_GROUPS:
        positions = results.get(group)
        if positions is None:
            continue
        groups_seen += 1
        if isinstance(positions, dict):
            for name, xy in positions.items():
                if not (isinstance(xy, list) and len(xy) == 2 and all(_is_number(v) for v in xy)):
                    parsed.issues.append(f"{group}['{name}'] must be an [x, y] number pair")
                    break

    if groups_seen == 0:
        parsed.warnings.append(
            "No recognised metrology result groups (HYBRID_GLUE_THICKNESS, CAP_HEIGHT, …)"
        )
    return parsed


# Ordered registry: most specific first, generic fallback last (always matches).
PARSERS: tuple[Parser, ...] = (
    Parser("glue-weight-v1", _sniff_glue_weight, _parse_glue_weight),
    Parser("iv-curve-v1", _sniff_iv_curve, _parse_iv_curve),
    Parser("pull-test-v1", _sniff_pull_test, _parse_pull_test),
    Parser("module-metrology-v1", _sniff_metrology, _parse_metrology),
    Parser("pdb-test-run-v1", _sniff_pdb_test_run, _parse_pdb_test_run),
    Parser("generic-json-v1", lambda payload: True, _parse_generic_json),
)


def parse_payload(payload: dict) -> ParsedTestRun:
    """Run the first matching parser. Never raises on malformed content."""
    for parser in PARSERS:
        if parser.sniff(payload):
            return parser.parse(payload)
    raise AssertionError("unreachable: the generic parser accepts every payload")


def missing_required_properties(
    payload_properties: Any, institute_settings: Any, test_type: str | None
) -> list[str]:
    """Institute-required property keys absent from an upload's `properties`.

    Some steps (e.g. hybrid gluing) require the used jig recorded on the upload
    or the PDB rejects it. The required keys per test type are institute config,
    not code (hard rule #4): `settings['required_properties'][test_type]`. An
    empty or missing config means no requirement. See docs/07.
    """
    if test_type is None or not isinstance(institute_settings, dict):
        return []
    mapping = institute_settings.get("required_properties")
    if not isinstance(mapping, dict):
        return []
    required = mapping.get(test_type)
    if not isinstance(required, list):
        return []
    props = payload_properties if isinstance(payload_properties, dict) else {}
    return [
        key
        for key in required
        if isinstance(key, str) and key and (key not in props or props.get(key) in (None, ""))
    ]
