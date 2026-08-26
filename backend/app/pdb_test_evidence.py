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

import hashlib
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import unquote, urlsplit, urlunsplit

from app.test_run_evidence import TestRunEvidenceRecord


def flat_fingerprint(
    *, passed: Any, measured_at: Any, state: Any, problems: Any
) -> tuple[Any, Any, Any, Any]:
    """Identity of a run's cheap `getComponent` listing data.

    The per-run `getTestRun` detail is refetched only when this changes.
    Datetimes are normalised to naive UTC so a timezone-aware database value
    compares equal to the parsed PDB timestamp.
    """
    if isinstance(measured_at, datetime) and measured_at.tzinfo is not None:
        measured_at = measured_at.astimezone(timezone.utc).replace(tzinfo=None)
    return (passed, measured_at, state, problems)


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
        raw_type = entry.get("type")
        attachment_type = raw_type.lower() if isinstance(raw_type, str) else raw_type
        raw_url = entry.get("url")
        url = raw_url if isinstance(raw_url, str) and raw_url else None
        # EOS download URLs can contain short-lived signatures. Detailed
        # mirroring explicitly asks the PDB not to mint one, but strip a query
        # defensively so a changed upstream default can never persist a token.
        if url and attachment_type == "eos":
            parsed = urlsplit(url)
            url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
        summaries.append(
            {
                "code": code,
                "filename": entry.get("filename"),
                "content_type": entry.get("contentType"),
                "title": entry.get("title"),
                "description": entry.get("description"),
                "type": attachment_type,
                "url": url,
                "source": "pdb",
            }
        )
    return summaries


def _http_urls(value: Any):
    """Yield public-link-shaped strings from one result value.

    zFlow-era visual-inspection fields can be either a single URL or an array
    of URLs. Nested containers are walked defensively; the historic sentinel
    value ``"failed"`` naturally falls out because it is not an HTTP URL.
    """

    if isinstance(value, str):
        candidate = value.strip()
        parsed = urlsplit(candidate)
        if parsed.scheme.lower() in {"http", "https"} and parsed.hostname:
            yield candidate
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            yield from _http_urls(item)


def _share_link_summaries(entries: Any) -> list[dict[str, Any]]:
    """Turn URL-valued PDB results into deterministic attachment descriptors."""

    summaries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        result_code = _code(entry.get("code"))
        for url in _http_urls(entry.get("value")):
            digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
            if digest in seen:
                continue
            seen.add(digest)
            path_name = PurePosixPath(unquote(urlsplit(url).path)).name
            summaries.append(
                {
                    "code": digest,
                    "filename": path_name[:255] or None,
                    "content_type": None,
                    "title": entry.get("name") or result_code or "Shared attachment",
                    "description": f"Mirrored from result {result_code}" if result_code else None,
                    "type": "share_link",
                    "url": url,
                    "source": "share_link",
                }
            )
    return summaries


def _run_detail_payload(client: Any, run_id: str) -> dict[str, Any] | None:
    """Measured values, properties and attachments for one run. Best effort.

    Returns ``None`` when the detail could not be read at all, which is
    different from a run that genuinely carries no detail: only a real answer
    may mark the run as mirrored, or a transient miss would be frozen forever
    and its measurements would never arrive.
    """
    try:
        # Never persist a short-lived EOS signature. The downloader asks for a
        # fresh URL only at the instant it needs the bytes.
        detail = client.get("getTestRun", json={"testRun": run_id, "noEosToken": True})
    except Exception:
        # A detail miss must degrade to pass/fail, never lose the whole run.
        return None
    if not isinstance(detail, dict):
        return None

    results, result_meta = _named_values(detail.get("results"))
    properties, _ = _named_values(detail.get("properties"))
    payload: dict[str, Any] = {}
    if results:
        payload["results"] = results
        payload["result_meta"] = result_meta
    if properties:
        payload["properties"] = properties
    attachments = _attachment_summaries(detail.get("attachments"))
    attachments.extend(_share_link_summaries(detail.get("results")))
    if attachments:
        payload["attachments"] = attachments
    if detail.get("runNumber") is not None:
        payload["run_number"] = detail.get("runNumber")
    return payload


def fetch_test_run_evidence(
    gateway: Any,
    sn: str,
    *,
    with_detail: bool = False,
    strict: bool = False,
    known_flat: Mapping[str, tuple] | None = None,
) -> list[TestRunEvidenceRecord]:
    """Fetch a component's test-run evidence.

    `with_detail` adds one `getTestRun` request per run; see the module
    docstring for when that cost is worth paying. `known_flat` (external_ref →
    `flat_fingerprint`) makes the detail incremental: a run whose cheap listing
    data still matches its mirrored fingerprint skips the detail round trip and
    is emitted with `detail_omitted=True`, which tells the upsert to leave the
    stored payload untouched.

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
            passed = _passed(run)
            measured_at = _parse_dt(run.get("date") or run.get("cts") or run.get("stateTs"))
            detail_omitted = False
            if with_detail and run_id:
                ref = str(run_id)
                fingerprint = flat_fingerprint(
                    passed=passed,
                    measured_at=measured_at,
                    state=payload["state"],
                    problems=payload["problems"],
                )
                if known_flat is not None and known_flat.get(ref) == fingerprint:
                    detail_omitted = True
                else:
                    detail = _run_detail_payload(client, ref)
                    if detail is not None:
                        payload.update(detail)
                        # Marker for the incremental sync: only runs that really
                        # carry mirrored detail may skip their next detail fetch.
                        payload["detail_synced"] = True
            records.append(
                TestRunEvidenceRecord(
                    component_sn=sn,
                    test_type=test_type,
                    passed=passed,
                    source="pdb",
                    external_ref=str(run_id) if run_id else None,
                    measured_at=measured_at,
                    payload=payload,
                    detail_omitted=detail_omitted,
                )
            )
    return records
