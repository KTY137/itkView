"""PDB → mirror fetch path: list an institute's components, map to sync records.

Strictly read-only: the only PDB call here is `listComponents`. Mapping is
tolerant by design — payloads that cannot become a valid `SyncRecord`
(deleted, uninitialised, malformed) are counted as skipped instead of failing
the whole sync. The write side of the mirror lives in `app.sync`.
"""

from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from app.config import Settings
from app.models import InstituteProfile
from app.pdb_gateway import PdbGateway
from app.pdb_scope import DUMMY_BATCH_PREFIX
from app.sync import StageEventRecord, SyncRecord

# Component payloads that never made it past registration have no stage or
# subtype yet; the mirror columns are non-null, so those show up as UNKNOWN.
UNKNOWN = "UNKNOWN"

# Baseline PDB filter for every institute; extend or override per institute
# via `InstituteProfile.settings["pdb_filters"]` (hard rule #4 — the profile,
# not the code, owns institute specifics).
DEFAULT_PDB_FILTERS: dict[str, Any] = {"project": "S"}


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


def fetch_for_institute(settings: Settings, institute: InstituteProfile) -> FetchResult:
    """List every component at (or owned by) one institute from the PDB.

    This is the default `component_fetcher` wired into the app; tests swap
    it for a fake so the offline suite never touches the network.
    """
    gateway = PdbGateway(settings)
    if not gateway.is_configured:
        raise PdbSyncUnavailable(
            "No ITKDB access codes configured for the PDB test instance. "
            "Set ITKFLOW_ITKDB_ACCESS_CODE1/2 to enable syncing."
        )
    try:
        client = gateway.client()
    except RuntimeError as exc:  # covers ProductionAccessError and missing itkdb
        raise PdbSyncUnavailable(str(exc)) from exc

    profile_filters = (institute.settings or {}).get("pdb_filters") or {}
    data = {
        "filterMap": {
            **DEFAULT_PDB_FILTERS,
            **profile_filters,
            # Institute scoping is never overridable from the profile.
            "institute": [institute.code],
            "currentLocation": [institute.code],
        },
        # Match components at the institute OR owned by it (as zFlow did).
        "useOrInLocationSearch": True,
        "outputType": "full",  # includes parents, needed for assembly links
    }
    try:
        response = client.get("listComponents", json=data)
        payloads = _materialise(response)
        # Parents reference components by internal object id; resolving those
        # links to serial numbers needs the whole batch mapped up front.
        id_to_sn = build_id_to_sn(payloads)
        mapped = [map_pdb_component(payload, id_to_sn) for payload in payloads]
    except PdbSyncUnavailable:
        raise
    except Exception as exc:
        raise PdbSyncUnavailable(f"PDB component listing failed: {exc}") from exc

    records = [record for record in mapped if record is not None]
    return FetchResult(records=records, skipped=len(mapped) - len(records))


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
