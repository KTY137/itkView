"""PDB → mirror fetch path: list an institute's components, map to sync records.

Strictly read-only: the only PDB call here is `listComponents`. Mapping is
tolerant by design — payloads that cannot become a valid `SyncRecord`
(deleted, uninitialised, malformed) are counted as skipped instead of failing
the whole sync. The write side of the mirror lives in `app.sync`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from time import sleep
from typing import TYPE_CHECKING, Any, Protocol

from pydantic import ValidationError

from app.config import Settings
from app.models import InstituteProfile
from app.pdb_gateway import PDB_REQUEST_TIMEOUT, PdbClientUnavailable, PdbGateway
from app.pdb_scope import DUMMY_BATCH_PREFIX
from app.sync import StageEventRecord, SyncRecord

if TYPE_CHECKING:
    from app.pdb_credentials import PdbAccessCodes

# Component payloads that never made it past registration have no stage or
# subtype yet; the mirror columns are non-null, so those show up as UNKNOWN.
UNKNOWN = "UNKNOWN"

# Baseline PDB filter for every institute; extend or override per institute
# via `InstituteProfile.settings["pdb_filters"]` (hard rule #4 — the profile,
# not the code, owns institute specifics).
DEFAULT_PDB_FILTERS: dict[str, Any] = {"project": "S"}

# Keep pages deliberately modest: production ``full`` payloads contain parent,
# batch and complete stage-history data and can be very uneven. A real TUDO
# page at offset 300 repeatedly exceeded the 60 s read timeout with 100 items,
# while the same range completed as two 50-item pages in 4.49 s and 2.24 s.
# Explicit paging also lets the job API report real progress and applies a
# timeout/retry to every request instead of itkdb's implicit, unbounded paging.
PDB_PAGE_SIZE = 50
PDB_PAGE_MAX_ATTEMPTS = 3
PDB_RETRY_BACKOFF_SECONDS = 0.5


class SyncProgress(Protocol):
    """Persistable progress callback used by foreground and background syncs."""

    def __call__(
        self,
        phase: str,
        current: int,
        total: int | None,
        message: str | None = None,
    ) -> None: ...


class PdbSyncUnavailable(RuntimeError):
    """The production PDB cannot be queried (configuration or connectivity)."""


@dataclass
class FetchResult:
    records: list[SyncRecord]
    skipped: int  # payloads that could not be mapped into the mirror


def _code(value: Any) -> str | None:
    """PDB fields arrive either as a plain string or as a dict with a `code`."""
    if isinstance(value, str) and value:
        return value
    if isinstance(value, dict):
        code = value.get("code")
        if isinstance(code, str) and code:
            return code
    return None


def _is_dummy(payload: dict) -> bool:
    """Whether a component is a test part safe for itkFlow to write to.

    The collaboration separates test parts with a `DUMMY_<institute>` *batch*
    (supervisor guidance, docs/09) — that batch membership is the authoritative
    marker and is what a freshly registered dummy carries (its per-component
    `dummy` boolean stays false). We also honour that legacy `dummy` flag so
    pre-existing dummy parts (e.g. dummy hybrids) still qualify. Batch names are
    matched case-insensitively (`DUMMY_UT`, `Dummy_O1` both occur in the PDB).
    """
    if payload.get("dummy"):
        return True
    for batch in payload.get("batches") or []:
        number = batch.get("number") if isinstance(batch, dict) else batch
        if isinstance(number, str) and number.upper().startswith(DUMMY_BATCH_PREFIX):
            return True
    return False


def _stage_events(payload: dict) -> list[StageEventRecord]:
    """Dated stage transitions from a component's `stages[]` log.

    Each entry is `{code, dateTime, rework, ...}`; entries without a code or a
    timestamp are skipped. The log is noisy (same-second correction entries,
    rework loops) but faithful — downstream stats smooth it, they don't lose it.
    """
    events: list[StageEventRecord] = []
    for entry in payload.get("stages") or []:
        if not isinstance(entry, dict):
            continue
        code = entry.get("code")
        when = entry.get("dateTime")
        if not code or not when:
            continue
        try:
            events.append(
                StageEventRecord(stage=code, entered_at=when, rework=bool(entry.get("rework")))
            )
        except ValidationError:
            continue
    return events


def _live_parent_object_id(payload: dict) -> str | None:
    """Internal object-id of the assembly this part is currently mounted into.

    Each `parents` entry carries the parent's **internal PDB object id** as a
    bare string in `component` (not a nested object, and *not* a serial
    number); empty slots carry `None`. A disassembled relationship drops its
    id (goes null) and, where present, a `state` other than `ready` marks a
    non-live link. A part sits in at most one live assembly, so the first
    entry that still names a component wins. The caller maps this object id
    back to a serial number via the batch's `id_to_sn` lookup.
    """
    for member in payload.get("parents") or []:
        component = member.get("component")
        if not isinstance(component, str) or not component:
            continue
        if member.get("state", "ready") != "ready":
            continue
        return component
    return None


def build_id_to_sn(payloads: list[dict]) -> dict[str, str]:
    """Map every component's internal object id to its serial number.

    Parents are referenced by object id, so resolving assembly links to serial
    numbers needs this lookup built across the whole fetched batch first.
    """
    return {
        payload["id"]: payload["serialNumber"]
        for payload in payloads
        if payload.get("state") == "ready" and payload.get("id") and payload.get("serialNumber")
    }


def map_pdb_component(payload: dict, id_to_sn: dict[str, str] | None = None) -> SyncRecord | None:
    """Turn one PDB component payload into a `SyncRecord`, or None to skip it.

    `id_to_sn` resolves the parent's internal object id to its serial number;
    a parent outside the fetched batch stays unresolved (`parent_sn=None`)
    rather than dangling. Skipped: components not in state `ready` (deleted),
    without a serial number (registered but never initialised), or with values
    the mirror schema rejects.
    """
    if payload.get("state") != "ready":
        return None
    sn = payload.get("serialNumber")
    component_type = _code(payload.get("componentType"))
    institute_code = _code(payload.get("institution")) or _code(payload.get("currentLocation"))
    if not sn or component_type is None or institute_code is None:
        return None
    parent_oid = _live_parent_object_id(payload)
    parent_sn = (id_to_sn or {}).get(parent_oid) if parent_oid else None
    try:
        return SyncRecord(
            sn=sn,
            component_type=component_type,
            type_code=_code(payload.get("type")) or UNKNOWN,
            stage=_code(payload.get("currentStage")) or UNKNOWN,
            location=_code(payload.get("currentLocation")) or institute_code,
            institute_code=institute_code,
            local_name=payload.get("alternativeIdentifier") or None,
            parent_sn=parent_sn,
            is_dummy=_is_dummy(payload),
            trashed=bool(payload.get("trashed", False)),
            stage_events=_stage_events(payload),
        )
    except ValidationError:
        return None


def fetch_for_institute(
    settings: Settings,
    institute: InstituteProfile,
    access_codes: PdbAccessCodes,
    progress: SyncProgress | None = None,
) -> FetchResult:
    """List every component at (or owned by) one institute from the PDB.

    This is the default `component_fetcher` wired into the app; tests swap
    it for a fake so the offline suite never touches the network.
    """
    gateway = PdbGateway(settings, access_codes=access_codes)
    if not gateway.is_configured:
        raise PdbSyncUnavailable(
            "No personal ITKDB access codes are connected for this account."
        )
    try:
        client = gateway.client()
    except PdbClientUnavailable:
        raise PdbSyncUnavailable("PDB client support is unavailable on this server.") from None
    except RuntimeError:  # covers ProductionAccessError and missing itkdb
        # itkdb authentication exceptions may render the original grantToken
        # request. Never forward an upstream exception string into API/job state.
        raise PdbSyncUnavailable("The personal PDB connection could not be opened.") from None

    profile_filters = (institute.settings or {}).get("pdb_filters") or {}
    data = {
        "filterMap": {
            **DEFAULT_PDB_FILTERS,
            **profile_filters,
            # Deleted/uninitialised components cannot enter the mirror. Asking
            # the PDB for ready rows only avoids transferring them, while the
            # mapper keeps its defensive state check for malformed responses.
            "state": "ready",
            # Institute scoping is never overridable from the profile.
            "institute": [institute.code],
            "currentLocation": [institute.code],
        },
        # Match components at the institute OR owned by it (as zFlow did).
        "useOrInLocationSearch": True,
        "outputType": "full",  # includes parents, needed for assembly links
    }
    try:
        payloads = _fetch_pages(client, data, progress)
        # Parents reference components by internal object id; resolving those
        # links to serial numbers needs the whole batch mapped up front.
        id_to_sn = build_id_to_sn(payloads)
        mapped = []
        if progress is not None:
            progress("mapping", 0, len(payloads))
        for index, payload in enumerate(payloads, start=1):
            mapped.append(map_pdb_component(payload, id_to_sn))
            if progress is not None and (
                index == len(payloads) or index % PDB_PAGE_SIZE == 0
            ):
                progress("mapping", index, len(payloads))
    except PdbSyncUnavailable:
        raise
    except Exception:
        raise PdbSyncUnavailable("PDB component listing failed.") from None

    records = [record for record in mapped if record is not None]
    return FetchResult(records=records, skipped=len(mapped) - len(records))


def _fetch_pages(
    client: Any,
    data: dict[str, Any],
    progress: SyncProgress | None = None,
) -> list[dict]:
    """Fetch ``listComponents`` explicitly, one bounded page at a time.

    Reading ``PagedResponse.data`` consumes only the response already fetched;
    unlike iterating it, it cannot trigger itkdb's internal follow-up requests
    (which have no timeout). The server-reported total remains authoritative and
    a short result is rejected before the caller can prune the mirror.
    """

    payloads: list[dict] = []
    expected: int | None = None
    frozen_page_size: int | None = None
    page_index = 0
    if progress is not None:
        progress("fetching", 0, None)

    while True:
        page_request = {
            **data,
            "pageInfo": {"pageIndex": page_index, "pageSize": PDB_PAGE_SIZE},
        }
        retry_progress = None
        if progress is not None:

            def retry_progress(
                failed_attempt: int,
                _error: Exception,
                page_number: int = page_index + 1,
                page_total: int | None = expected,
            ) -> None:
                progress(
                    "fetching",
                    len(payloads),
                    page_total,
                    f"PDB page {page_number} request failed; retrying attempt "
                    f"{failed_attempt + 1} of {PDB_PAGE_MAX_ATTEMPTS}.",
                )

        response = _request_page(
            client,
            page_request,
            page_index,
            retry_progress=retry_progress,
        )
        items, page_info, terminal_list = _extract_page(response)

        # Any non-empty metadata-free list is unverifiable: it could be a
        # truncated first page. Only an empty result can safely authorize an
        # authoritative prune without total/pageSize/pageIndex.
        if terminal_list:
            if items:
                raise PdbSyncUnavailable(
                    "PDB component listing returned data without pagination "
                    "metadata; refusing an unverifiable sync."
                )
            payloads.extend(items)
            if expected is None:
                expected = len(payloads)
            if progress is not None:
                progress("fetching", len(payloads), expected)
            break

        reported_total = page_info.get("total")
        reported_size = page_info.get("pageSize")
        reported_index = page_info.get("pageIndex")
        if not isinstance(reported_total, int) or reported_total < 0:
            raise PdbSyncUnavailable("PDB component page omitted a valid total.")
        if not isinstance(reported_size, int) or reported_size <= 0:
            raise PdbSyncUnavailable("PDB component page omitted a valid pageSize.")
        if not isinstance(reported_index, int) or reported_index < 0:
            raise PdbSyncUnavailable("PDB component page omitted a valid pageIndex.")
        if reported_size != PDB_PAGE_SIZE:
            raise PdbSyncUnavailable(
                f"PDB component pageSize differed from the request: "
                f"requested {PDB_PAGE_SIZE}, received {reported_size}."
            )
        if reported_index != page_index:
            raise PdbSyncUnavailable(
                f"PDB component page index drifted: requested {page_index}, "
                f"received {reported_index}."
            )

        if expected is None:
            expected = reported_total
            frozen_page_size = reported_size
        else:
            if reported_total != expected:
                raise PdbSyncUnavailable(
                    f"PDB component total changed during pagination: "
                    f"expected {expected}, received {reported_total}."
                )
            if reported_size != frozen_page_size:
                raise PdbSyncUnavailable(
                    f"PDB component pageSize changed during pagination: "
                    f"expected {frozen_page_size}, received {reported_size}."
                )
        if len(items) > reported_size:
            raise PdbSyncUnavailable(
                f"PDB component page {page_index} contained {len(items)} items "
                f"for pageSize {reported_size}."
            )

        remaining_before_page = expected - len(payloads)
        expected_on_page = min(reported_size, max(0, remaining_before_page))
        if len(items) != expected_on_page:
            raise PdbSyncUnavailable(
                f"PDB component page {page_index} contained {len(items)} items; "
                f"expected {expected_on_page} from frozen pagination metadata."
            )

        payloads.extend(items)
        if progress is not None:
            progress("fetching", len(payloads), expected)
        if len(payloads) == expected:
            break
        page_index += 1

    if expected is not None and len(payloads) != expected:
        raise PdbSyncUnavailable(
            f"Paginated component listing incomplete: fetched {len(payloads)} "
            f"of {expected} reported components; refusing a truncated sync."
        )
    return payloads


def _request_page(
    client: Any,
    data: dict[str, Any],
    page_index: int,
    *,
    retry_progress: Callable[[int, Exception], None] | None = None,
) -> Any:
    """Request one read-only page with bounded exponential retry."""

    last_error: Exception | None = None
    for attempt in range(1, PDB_PAGE_MAX_ATTEMPTS + 1):
        try:
            return client.get(
                "listComponents",
                json=data,
                timeout=PDB_REQUEST_TIMEOUT,
            )
        except Exception as exc:  # itkdb wraps requests errors in several types
            last_error = exc
            if attempt < PDB_PAGE_MAX_ATTEMPTS and _is_transient_page_error(exc):
                # Keep the durable job heartbeat fresh while a slow PDB page is
                # retried. The UI can then distinguish a retry from a frozen
                # worker even though no new component has completed yet.
                if retry_progress is not None:
                    retry_progress(attempt, exc)
                sleep(PDB_RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1)))
                continue
            break
    raise PdbSyncUnavailable(
        f"PDB component page {page_index + 1} failed after {attempt} "
        f"{'attempt' if attempt == 1 else 'attempts'} "
        f"({_safe_page_error_summary(last_error)})."
    ) from None


def _safe_page_error_summary(error: Exception | None) -> str:
    """Return operationally useful error context without upstream text.

    In particular, itkdb's authentication exception may contain a rendered
    grant-token request. Only an HTTP status or a coarse transport category is
    safe to persist and show to users.
    """

    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        response = getattr(current, "response", None)
        status = getattr(response, "status_code", None)
        if status is None:
            status = getattr(current, "status_code", None)
        if isinstance(status, int):
            return f"HTTP {status}"
        current = current.__cause__ or current.__context__
    if error is not None and _is_transient_page_error(error):
        return "transient network error"
    return "non-retryable PDB error"


def _is_transient_page_error(error: Exception) -> bool:
    """Return whether a PDB request error is safe and useful to retry.

    ``itkdb`` wraps requests/urllib3 exceptions differently between releases,
    so inspect the exception chain without importing the optional dependency.
    Explicit HTTP client errors remain permanent; timeouts, transport errors,
    408/429 and server errors are retried.
    """

    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        response = getattr(current, "response", None)
        status = getattr(response, "status_code", None)
        if status is None:
            status = getattr(current, "status_code", None)
        if isinstance(status, int):
            return status in {408, 429} or 500 <= status < 600

        name = type(current).__name__.lower()
        detail = str(current).lower()
        transient_type_markers = (
            "timeout",
            "connectionerror",
            "proxyerror",
            "sslerror",
            "chunkedencodingerror",
            "protocolerror",
            "nameresolutionerror",
            "newconnectionerror",
            "maxretryerror",
        )
        transient_detail_markers = (
            "timed out",
            "timeout",
            "name resolution",
            "getaddrinfo",
            "remote end closed",
            "connection reset",
            "connection aborted",
            "connection refused",
            "max retries exceeded",
            "temporary failure",
            "temporarily unavailable",
            "incomplete read",
        )
        if (
            isinstance(current, (TimeoutError, ConnectionError))
            or any(marker in name for marker in transient_type_markers)
            or any(marker in detail for marker in transient_detail_markers)
        ):
            return True
        current = current.__cause__ or current.__context__
    return False


def _extract_page(response: Any) -> tuple[list[dict], dict[str, Any], bool]:
    """Return items/pageInfo without iterating an itkdb PagedResponse."""

    if isinstance(response, dict):
        items = response.get("itemList", [])
        page_info = response.get("pageInfo") or {}
        terminal_list = not bool(page_info)
    elif isinstance(response, list):
        items = response
        page_info = {}
        terminal_list = True
    elif hasattr(response, "data") and hasattr(response, "page_info"):
        items = response.data or []
        page_info = response.page_info or {}
        terminal_list = False
    else:
        raise PdbSyncUnavailable(
            f"Unexpected PDB component page response: {type(response).__name__}."
        )
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise PdbSyncUnavailable("PDB component page did not contain a valid item list.")
    if not isinstance(page_info, dict):
        page_info = {}
    return items, page_info, terminal_list


def _materialise(response: Any) -> list[dict]:
    """Collect every component across all pages, refusing a truncated result.

    itkdb wraps `listComponents` in an iterable `PagedResponse` that fetches
    each page transparently as it is iterated, so `list(response)` yields the
    full set. We cross-check against the reported `total` and treat any
    shortfall as a failed sync rather than silently mirroring a partial view.
    A plain dict (a small unwrapped result) is tolerated but likewise checked
    against its `pageInfo.total`.
    """
    if isinstance(response, dict):
        payloads = response.get("itemList", [])
        expected = (response.get("pageInfo") or {}).get("total")
    else:
        payloads = list(response)
        expected = getattr(response, "total", None)
    if isinstance(expected, int) and len(payloads) != expected:
        raise PdbSyncUnavailable(
            f"Paginated component listing incomplete: fetched {len(payloads)} "
            f"of {expected} reported components; refusing a truncated sync."
        )
    return payloads
