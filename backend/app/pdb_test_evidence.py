"""Read-only fetch of a component's test-run results from the PDB.

Turns `getComponent`'s test runs into `TestRunEvidenceRecord`s so the stage
engine knows which required tests actually passed for real (synced) components,
not just itkFlow's own confirmed uploads. Strictly read-only and only reachable
behind the production opt-in; returns nothing when the gateway is not
configured. The exact field mapping lives here so it can be tuned after a live
validation without touching callers.

Two depths, because they cost very differently:

* the default walks `getComponent` alone -- one request per component, enough
  for pass/fail and therefore for stage requirements;
* `with_detail=True` additionally calls `getTestRun` per run, which is what
  carries measured values (glue weights, metrology, IV arrays), the run's
  properties and its attachment list. That is one request per *run*, so it
  belongs on a single opened component, not on a whole-institute sweep.
"""

from datetime import datetime, timezone
from typing import Any

from app.test_run_evidence import TestRunEvidenceRecord


class PdbEvidenceUnavailable(RuntimeError):
    """The PDB could not be read, as opposed to having nothing to report.

    The distinction matters at the UI: an empty mirror and an unreachable PDB
    look identical once both are an empty list, and the person is left staring
    at "no test results" for a module that has plenty.
    """


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


def _named_values(entries: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split a PDB results/properties list into values and their descriptions.

    Values stay flat and keyed by code so a caller can look one up directly.
    The names are kept beside them because they carry the unit ("Weight of glue
    under hybrid 1 [g]") that a bare number is useless without.
    """
    values: dict[str, Any] = {}
    meta: dict[str, Any] = {}
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        code = _code(entry.get("code"))
        if not code:
            continue
        values[code] = entry.get("value")
        described = {
            "name": entry.get("name"),
            "data_type": entry.get("dataType"),
            "value_type": entry.get("valueType"),
        }
        meta[code] = {key: value for key, value in described.items() if value is not None}
    return values, meta


def _attachment_summaries(entries: Any) -> list[dict[str, Any]]:
    """Attachment metadata only. The bytes are fetched separately, on demand."""
    summaries: list[dict[str, Any]] = []
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        code = _code(entry.get("code"))
        if not code:
            continue
        summaries.append(
            {
                "code": code,
                "filename": entry.get("filename"),
                "content_type": entry.get("contentType"),
                "title": entry.get("title"),
                "description": entry.get("description"),
            }
        )
    return summaries


def _run_detail_payload(client: Any, run_id: str) -> dict[str, Any]:
    """Measured values, properties and attachments for one run. Best effort."""
    try:
        detail = client.get("getTestRun", json={"testRun": run_id})
    except Exception:
        # A detail miss must degrade to pass/fail, never lose the whole run.
        return {}
    if not isinstance(detail, dict):
        return {}

    results, result_meta = _named_values(detail.get("results"))
    properties, _ = _named_values(detail.get("properties"))
    payload: dict[str, Any] = {}
    if results:
        payload["results"] = results
        payload["result_meta"] = result_meta
    if properties:
        payload["properties"] = properties
    attachments = _attachment_summaries(detail.get("attachments"))
    if attachments:
        payload["attachments"] = attachments
    if detail.get("runNumber") is not None:
        payload["run_number"] = detail.get("runNumber")
    return payload


def fetch_test_run_evidence(
    gateway: Any, sn: str, *, with_detail: bool = False, strict: bool = False
) -> list[TestRunEvidenceRecord]:
    """Fetch a component's test-run evidence.

    `with_detail` adds one `getTestRun` request per run; see the module
    docstring for when that cost is worth paying.

    `strict` decides what an unreachable PDB means. A whole-institute sweep
    stays best effort — one bad component must not abort the run — but a person
    who just pressed sync on one module is owed the truth, so that path raises
    `PdbEvidenceUnavailable` instead of quietly reporting nothing.
    """
    if not getattr(gateway, "is_configured", False):
        if strict:
            raise PdbEvidenceUnavailable(
                "No personal PDB connection is available for this account."
            )
        return []
    try:
        client = gateway.client()
        component = client.get("getComponent", json={"component": sn})
    except Exception as exc:
        if strict:
            # Deliberately not chained: an itkdb error can carry the request,
            # and the request can carry access codes.
            raise PdbEvidenceUnavailable("The PDB could not be read.") from None
        # Read-only best effort — never break a sweep on a PDB hiccup.
        del exc
        return []
    if not isinstance(component, dict):
        if strict:
            raise PdbEvidenceUnavailable("The PDB returned an unusable component response.")
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
            payload: dict[str, Any] = {
                "state": run.get("state"),
                "problems": run.get("problems"),
            }
            if with_detail and run_id:
                payload.update(_run_detail_payload(client, str(run_id)))
            records.append(
                TestRunEvidenceRecord(
                    component_sn=sn,
                    test_type=test_type,
                    passed=_passed(run),
                    source="pdb",
                    external_ref=str(run_id) if run_id else None,
                    measured_at=_parse_dt(run.get("date") or run.get("cts") or run.get("stateTs")),
                    payload=payload,
                )
            )
    return records
