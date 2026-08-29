# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-FileComment: itkflow-93a517228dbe
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

Both are per-component. For a whole-institute sweep that is one request per
component even when nothing changed, so this module also offers the batched
pair the PDB exposes and `itkdb` itself uses:

* `fetch_test_run_index` asks `listTestRunsByComponent` for many serial
  numbers at once and returns the same cheap listing data `getComponent`
  carries (pass/fail, state, timestamp) -- the *index*;
* `fetch_test_run_details_bulk` asks `getTestRunBulk` for many run ids at once
  and returns the detail payloads.

Neither could be validated against a live PDB, so both are written to refuse
rather than to guess: any answer they cannot prove complete raises
`PdbIndexUnusable`, and the caller is expected to fall back to the
per-component path for the components involved.
"""

import hashlib
import logging
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import PurePosixPath
from time import sleep as _sleep
from typing import Any
from urllib.parse import unquote, urlsplit, urlunsplit

from app.pdb_sync import _is_transient_page_error, _safe_page_error_summary
from app.test_run_evidence import TestRunEvidenceRecord

log = logging.getLogger(__name__)

#: Batched read endpoints. `itkdb` calls both itself (see
#: `itkdb/client.py::_get_duplicate_test_runs`), which is where their request
#: and response shapes are taken from.
INDEX_ACTION = "listTestRunsByComponent"
BULK_DETAIL_ACTION = "getTestRunBulk"
#: Same backoff shape as the component listing pages and the per-component
#: evidence retry; the budget itself comes from `sync_page_max_attempts`.
INDEX_RETRY_BACKOFF_SECONDS = 0.5


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


def _state(value: Any) -> str | None:
    """Narrow the PDB's run state to the mirrored column's type.

    Anything that is not a non-empty string (missing, null, an unexpected
    object) becomes ``None`` — "unknown", which counts as still valid. Guessing
    a state from a malformed field would be worse than admitting we have none.
    """
    if isinstance(value, str) and value.strip():
        return value.strip()[:32]
    return None


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


def detail_payload(detail: Any) -> dict[str, Any] | None:
    """Turn one full test-run object into the payload fragment we mirror.

    Shared by the per-run `getTestRun` fetch and the batched `getTestRunBulk`
    answer, so both mirror byte-identical payloads and an incremental sweep
    never sees a phantom change just because the detail arrived by another
    route. ``None`` means "not a usable answer"; an empty dict means "a real
    answer that carries no detail".
    """
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


def fetch_test_run_detail(client: Any, run_id: str) -> dict[str, Any] | None:
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
    return detail_payload(detail)


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
            # Also mirrored as a first-class column so a withdrawn run can be
            # excluded from evidence in SQL; the payload copy stays because the
            # incremental sweep fingerprints the payload (`sync_jobs`).
            run_state = _state(run.get("state"))
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
                    detail = fetch_test_run_detail(client, ref)
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
                    run_state=run_state,
                    payload=payload,
                    detail_omitted=detail_omitted,
                )
            )
    return records


# --- batched reads -----------------------------------------------------------
#
# Everything below trades one request per component for one request per batch.
# None of it could be checked against a live PDB, so it is written to *refuse*
# rather than to guess: `PdbIndexUnusable` means "ask the per-component path
# instead", never "this component has no runs".


class PdbIndexUnusable(RuntimeError):
    """The batched answer cannot be proven complete; fall back per component.

    Deliberately distinct from `PdbEvidenceUnavailable`: that one means the PDB
    could not be read and the job should fail (and be retried), while this one
    means the *cheap* route did not work out and the proven route must be used.
    """


@dataclass(frozen=True)
class IndexedTestRun:
    """One run as the batched index reports it — the cheap listing data only."""

    component_sn: str
    run_id: str
    test_type: str
    passed: bool
    measured_at: datetime | None
    run_state: str | None
    raw_state: Any
    problems: Any

    @property
    def fingerprint(self) -> tuple:
        """Identical to what the per-component path fingerprints, so the two
        routes agree about which runs still need their detail fetched."""
        return flat_fingerprint(
            passed=self.passed,
            measured_at=self.measured_at,
            state=self.raw_state,
            problems=self.problems,
        )

    def flat_payload(self) -> dict[str, Any]:
        return {"state": self.raw_state, "problems": self.problems}


def _request_batch(
    client: Any,
    action: str,
    body: dict[str, Any],
    *,
    max_attempts: int,
    on_retry: Callable[[int], None] | None = None,
    sleeper: Callable[[float], None] = _sleep,
) -> Any:
    """One batched read with the shared transient-retry budget.

    Transient exhaustion raises `PdbEvidenceUnavailable` (the line is down —
    the per-component path would fail just the same, so the job should fail and
    take its one automatic retry). Anything else raises `PdbIndexUnusable`,
    which demotes the sweep to the per-component path instead of failing it:
    an endpoint this deployment's PDB does not serve is not an outage.
    """
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return client.get(action, json=body)
        except Exception as exc:  # itkdb wraps transport errors in many types
            last_error = exc
            if attempt < max_attempts and _is_transient_page_error(exc):
                if on_retry is not None:
                    on_retry(attempt)
                sleeper(INDEX_RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1)))
                continue
            break
    summary = _safe_page_error_summary(last_error)
    if last_error is not None and _is_transient_page_error(last_error):
        # Deliberately not chained: an itkdb error can carry the request, and
        # the request can carry access codes.
        raise PdbEvidenceUnavailable(
            f"The PDB did not answer a batched test-run request ({summary})."
        ) from None
    raise PdbIndexUnusable(f"{action} is not usable here ({summary}).") from None


def _batched_items(response: Any) -> tuple[list[dict], dict[str, Any], bool]:
    """Return `(items, page_info, has_metadata)` for a batched answer.

    itkdb hands back a plain list for a `testRunList` body and a `PagedResponse`
    when the body paginates. A `PagedResponse` is read through `.data` and never
    iterated: iterating it fires follow-up requests that carry no timeout.
    """
    if isinstance(response, list):
        items: list = response
        page_info: dict[str, Any] = {}
        has_metadata = False
    elif isinstance(response, dict):
        for key in ("testRunList", "pageItemList", "itemList"):
            if isinstance(response.get(key), list):
                items = response[key]
                break
        else:
            raise PdbIndexUnusable("A batched test-run answer carried no item list.")
        page_info = response.get("pageInfo") or {}
        has_metadata = bool(page_info)
    elif hasattr(response, "data") and hasattr(response, "page_info"):
        items = response.data or []
        page_info = response.page_info or {}
        has_metadata = bool(page_info)
    elif response is None:
        items, page_info, has_metadata = [], {}, False
    else:
        raise PdbIndexUnusable(
            f"Unexpected batched test-run answer: {type(response).__name__}."
        )
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise PdbIndexUnusable("A batched test-run answer carried a malformed item list.")
    if not isinstance(page_info, dict):
        page_info, has_metadata = {}, False
    return items, page_info, has_metadata


def _indexed_component_sn(entry: dict, requested: set[str]) -> str | None:
    """Which requested component this run belongs to.

    Only an identifier that is actually in the batch counts. That is not
    politeness, it is the guard: a bare string in `component` is the PDB's
    internal object id, not a serial number (see `pdb_sync`), and an answer
    naming a component we did not ask about means the filter was not honoured.
    """
    component = entry.get("component")
    candidates = [
        entry.get("serialNumber"),
        entry.get("componentSerialNumber"),
        component if isinstance(component, str) else None,
    ]
    if isinstance(component, dict):
        candidates.extend(
            [
                component.get("serialNumber"),
                component.get("alternativeIdentifier"),
                component.get("code"),
            ]
        )
    for candidate in candidates:
        if isinstance(candidate, str) and candidate in requested:
            return candidate
    return None


def _indexed_run(entry: dict, requested: set[str]) -> IndexedTestRun:
    """Parse one index entry, refusing anything we would have to guess at."""

    raw_id = entry.get("id")
    run_id = str(raw_id) if isinstance(raw_id, (str, int)) and str(raw_id) else None
    if not run_id:
        raise PdbIndexUnusable("A test-run index entry carried no run id.")
    # `code` is deliberately not consulted as a fallback: on a run entry that
    # is the run's own code, not the test type, and mirroring it would file
    # every measurement under an invented test type.
    test_type = _code(entry.get("testType"))
    if not test_type:
        raise PdbIndexUnusable("A test-run index entry carried no test type.")
    component_sn = _indexed_component_sn(entry, requested)
    if component_sn is None:
        raise PdbIndexUnusable(
            "A test-run index entry named a component that was not requested."
        )
    if not isinstance(entry.get("passed"), bool) and not isinstance(
        entry.get("problems"), bool
    ):
        # `_passed` would default to False here, which is a wrong measurement
        # result rather than a missing one. Refuse instead.
        raise PdbIndexUnusable("A test-run index entry carried no pass/fail result.")
    raw_state = entry.get("state")
    return IndexedTestRun(
        component_sn=component_sn,
        run_id=run_id,
        test_type=test_type,
        passed=_passed(entry),
        measured_at=_parse_dt(entry.get("date") or entry.get("cts") or entry.get("stateTs")),
        run_state=_state(raw_state),
        raw_state=raw_state,
        problems=entry.get("problems"),
    )


def _check_index_page_metadata(
    page_info: dict[str, Any],
    *,
    page_index: int,
    page_size: int,
    expected: int | None,
    frozen_page_size: int | None,
    item_count: int,
    fetched_before: int,
) -> int:
    """Same paranoia as the component listing, different consequence.

    `pdb_sync._fetch_pages` refuses a sync outright because it is about to
    prune the mirror; here a bad page only means "use the per-component path",
    so the identical checks raise `PdbIndexUnusable`.
    """
    reported_total = page_info.get("total")
    reported_size = page_info.get("pageSize")
    reported_index = page_info.get("pageIndex")
    if not isinstance(reported_total, int) or reported_total < 0:
        raise PdbIndexUnusable("A test-run index page omitted a valid total.")
    if not isinstance(reported_size, int) or reported_size <= 0:
        raise PdbIndexUnusable("A test-run index page omitted a valid pageSize.")
    if not isinstance(reported_index, int) or reported_index < 0:
        raise PdbIndexUnusable("A test-run index page omitted a valid pageIndex.")
    if reported_size != page_size:
        raise PdbIndexUnusable(
            f"A test-run index page used pageSize {reported_size} for a "
            f"requested {page_size}."
        )
    if reported_index != page_index:
        raise PdbIndexUnusable(
            f"A test-run index page index drifted: requested {page_index}, "
            f"received {reported_index}."
        )
    if expected is not None and reported_total != expected:
        raise PdbIndexUnusable(
            f"The test-run index total changed during pagination: expected "
            f"{expected}, received {reported_total}."
        )
    if frozen_page_size is not None and reported_size != frozen_page_size:
        raise PdbIndexUnusable("The test-run index pageSize changed during pagination.")
    total = reported_total if expected is None else expected
    expected_on_page = min(reported_size, max(0, total - fetched_before))
    if item_count != expected_on_page:
        raise PdbIndexUnusable(
            f"Test-run index page {page_index} carried {item_count} entries; "
            f"{expected_on_page} were expected from the frozen metadata."
        )
    return total


def fetch_test_run_index(
    client: Any,
    serial_numbers: Sequence[str],
    *,
    page_size: int,
    max_attempts: int,
    on_retry: Callable[[int], None] | None = None,
    on_page: Callable[[int, int | None], None] | None = None,
    sleeper: Callable[[float], None] = _sleep,
) -> dict[str, list[IndexedTestRun]]:
    """Ask `listTestRunsByComponent` about a whole batch of serial numbers.

    Returns a mapping that contains **every** requested serial number, so an
    absent component is an explicit empty list rather than a silent omission.
    Deliberately sends no `state` filter: a withdrawn run (`state='deleted'`)
    must keep arriving here, because this is the cheap path on which a
    withdrawal is detected at all.

    `on_page` fires after every page with `(runs so far, reported total)`, so
    the caller can keep its durable heartbeat fresh: a batch that paginates
    over several slow pages would otherwise stay silent for longer than the
    startup-recovery grace and a second app instance would reap a live job.

    Raises `PdbIndexUnusable` for anything unverifiable — a metadata-free page
    that exactly fills the requested page size (indistinguishable from a
    truncated one), drifting pagination metadata, a repeated run id, an entry
    naming a component nobody asked about, or a missing field the mirror would
    otherwise have to invent.
    """
    requested = [sn for sn in serial_numbers if isinstance(sn, str) and sn]
    if not requested:
        return {}
    wanted = set(requested)
    by_sn: dict[str, list[IndexedTestRun]] = {sn: [] for sn in requested}
    seen_ids: set[str] = set()
    expected: int | None = None
    frozen_page_size: int | None = None
    page_index = 0
    while True:
        response = _request_batch(
            client,
            INDEX_ACTION,
            {
                "filterMap": {"serialNumber": list(requested)},
                "pageInfo": {"pageIndex": page_index, "pageSize": page_size},
            },
            max_attempts=max_attempts,
            on_retry=on_retry,
            sleeper=sleeper,
        )
        items, page_info, has_metadata = _batched_items(response)
        fetched_before = len(seen_ids)
        for entry in items:
            run = _indexed_run(entry, wanted)
            if run.run_id in seen_ids:
                # Row count is no proof of completeness: the component listing
                # once returned the promised number of rows while repeating
                # some and omitting others.
                raise PdbIndexUnusable(
                    "The test-run index repeated a run id; the same number of "
                    "runs is therefore missing."
                )
            seen_ids.add(run.run_id)
            by_sn[run.component_sn].append(run)

        if not has_metadata:
            if len(items) == page_size:
                raise PdbIndexUnusable(
                    "The test-run index filled a page without pagination "
                    "metadata; a truncated answer would look identical."
                )
            if on_page is not None:
                on_page(len(seen_ids), None)
            break

        expected = _check_index_page_metadata(
            page_info,
            page_index=page_index,
            page_size=page_size,
            expected=expected,
            frozen_page_size=frozen_page_size,
            item_count=len(items),
            fetched_before=fetched_before,
        )
        frozen_page_size = page_info.get("pageSize")
        if on_page is not None:
            on_page(len(seen_ids), expected)
        if len(seen_ids) >= expected:
            break
        page_index += 1

    if expected is not None and len(seen_ids) != expected:
        raise PdbIndexUnusable(
            f"The test-run index returned {len(seen_ids)} of {expected} reported runs."
        )
    return by_sn


def fetch_test_run_details_bulk(
    client: Any,
    run_ids: Sequence[str],
    *,
    batch_size: int,
    max_attempts: int,
    on_retry: Callable[[int], None] | None = None,
    on_batch: Callable[[int], None] | None = None,
    sleeper: Callable[[float], None] = _sleep,
) -> tuple[dict[str, dict[str, Any]], bool]:
    """Ask `getTestRunBulk` for many run details at once.

    Returns `(payload by run id, endpoint still usable)`. Ids the answer omits
    are simply absent from the mapping — the caller repairs those with one
    `getTestRun` each, which is exactly what the per-component path already
    does. The flag goes false when the endpoint is not serving detail at all
    (it is missing, or its very first batch carried no detail fields); the
    caller then stops paying for bulk requests that repair nothing.
    """
    details: dict[str, dict[str, Any]] = {}
    ordered = [str(run_id) for run_id in run_ids if run_id]
    for offset in range(0, len(ordered), batch_size):
        chunk = ordered[offset : offset + batch_size]
        chunk_ids = set(chunk)
        try:
            response = _request_batch(
                client,
                BULK_DETAIL_ACTION,
                {"testRun": list(chunk)},
                max_attempts=max_attempts,
                on_retry=on_retry,
                sleeper=sleeper,
            )
            entries, _page_info, _has_metadata = _batched_items(response)
        except PdbIndexUnusable as exc:
            log.info("Bulk test-run detail is unusable, repairing per run: %s", exc)
            return details, False
        found: dict[str, dict[str, Any]] = {}
        with_payload = 0
        for entry in entries:
            raw_id = entry.get("id")
            run_id = str(raw_id) if isinstance(raw_id, (str, int)) and str(raw_id) else None
            if run_id is None or run_id not in chunk_ids:
                continue
            payload = detail_payload(entry)
            if payload is None:
                continue
            found[run_id] = payload
            if payload:
                with_payload += 1
        if offset == 0 and with_payload == 0 and chunk:
            # The endpoint answered but carries none of the fields detail is
            # about. Treat its answers as worthless rather than marking runs
            # `detail_synced` on the strength of an empty object — that would
            # freeze them shallow forever.
            log.info("Bulk test-run detail carried no measured values; repairing per run.")
            return details, False
        details.update(found)
        if on_batch is not None:
            on_batch(len(details))
    return details, True


def records_from_index(
    runs: Iterable[IndexedTestRun],
    *,
    details: Mapping[str, dict[str, Any]],
    known_flat: Mapping[str, tuple] | None = None,
    repair: Callable[[str], dict[str, Any] | None] | None = None,
) -> list[TestRunEvidenceRecord]:
    """Build mirror records for one component's indexed runs.

    Same contract as the per-component path: a run whose cheap listing data
    still matches its mirrored fingerprint is emitted with `detail_omitted`
    (leave the stored payload alone), and only a real detail answer may set
    `detail_synced`. `run_state` is always carried, `detail_omitted` or not —
    a withdrawal arrives on exactly this cheap data and must never be skipped.
    """
    records: list[TestRunEvidenceRecord] = []
    for run in runs:
        payload = run.flat_payload()
        detail_omitted = False
        if known_flat is not None and known_flat.get(run.run_id) == run.fingerprint:
            detail_omitted = True
        else:
            detail = details.get(run.run_id)
            if detail is None and repair is not None:
                detail = repair(run.run_id)
            if detail is not None:
                payload.update(detail)
                payload["detail_synced"] = True
        records.append(
            TestRunEvidenceRecord(
                component_sn=run.component_sn,
                test_type=run.test_type,
                passed=run.passed,
                source="pdb",
                external_ref=run.run_id,
                measured_at=run.measured_at,
                run_state=run.run_state,
                payload=payload,
                detail_omitted=detail_omitted,
            )
        )
    return records
