"""Read-only fetch of a component's test-run results from the PDB.

Turns `getComponent`'s test runs into `TestRunEvidenceRecord`s so the stage
engine knows which required tests actually passed for real (synced) components,
not just itkFlow's own confirmed uploads. Strictly read-only and only reachable
behind the production opt-in; returns nothing when the gateway is not
configured. The exact field mapping lives here so it can be tuned after a live
validation without touching callers.
"""

from datetime import datetime, timezone
from typing import Any

from app.test_run_evidence import TestRunEvidenceRecord


def _code(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    if isinstance(value, dict):
        code = value.get("code")
        if isinstance(code, str) and code:
            return code
    return None


def _parse_dt(value: Any) -> datetime | None:
    """Parse an ISO timestamp to naive UTC, so re-syncs compare equal after the
    SQLite datetime round-trip (which drops tzinfo)."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _passed(run: dict) -> bool:
    passed = run.get("passed")
    if isinstance(passed, bool):
        return passed
    problems = run.get("problems")
    if isinstance(problems, bool):
        return not problems
    return False


def fetch_test_run_evidence(gateway: Any, sn: str) -> list[TestRunEvidenceRecord]:
    """Fetch a component's test-run pass/fail evidence. Empty when unavailable."""
    if not getattr(gateway, "is_configured", False):
        return []
    try:
        client = gateway.client()
        component = client.get("getComponent", json={"component": sn})
    except Exception:
        # Read-only best effort — never break the caller on a PDB hiccup.
        return []
    if not isinstance(component, dict):
        return []

    records: list[TestRunEvidenceRecord] = []
    for test in component.get("tests") or []:
        if not isinstance(test, dict):
            continue
        test_type = _code(test.get("testType")) or _code(test.get("code"))
        if not test_type:
            continue
        for run in test.get("testRuns") or []:
            if not isinstance(run, dict):
                continue
            run_id = run.get("id") or run.get("code")
            records.append(
                TestRunEvidenceRecord(
                    component_sn=sn,
                    test_type=test_type,
                    passed=_passed(run),
                    source="pdb",
                    external_ref=str(run_id) if run_id else None,
                    measured_at=_parse_dt(run.get("date") or run.get("cts") or run.get("stateTs")),
                    payload={"state": run.get("state"), "problems": run.get("problems")},
                )
            )
    return records
