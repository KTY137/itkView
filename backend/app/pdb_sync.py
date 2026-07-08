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
from app.sync import SyncRecord

# Component payloads that never made it past registration have no stage or
# subtype yet; the mirror columns are non-null, so those show up as UNKNOWN.
UNKNOWN = "UNKNOWN"

# Baseline PDB filter for every institute; extend or override per institute
# via `InstituteProfile.settings["pdb_filters"]` (hard rule #4 — the profile,
# not the code, owns institute specifics).
DEFAULT_PDB_FILTERS: dict[str, Any] = {"project": "S"}


class PdbSyncUnavailable(RuntimeError):
    """The PDB test instance cannot be queried (configuration or connectivity)."""


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


def _parent_sn(payload: dict) -> str | None:
    """Serial number of the assembly parent, if any.

    `parents` entries carry `component: None` for slots that were never
    assembled; disassembled parents keep an entry whose component is no
    longer `ready`. A part sits in at most one live assembly, so the first
    ready parent is the assembly parent.
    """
    for member in payload.get("parents") or []:
        component = member.get("component")
        if not component or component.get("state") != "ready":
            continue
        sn = component.get("serialNumber")
        if sn:
            return sn
    return None


def map_pdb_component(payload: dict) -> SyncRecord | None:
    """Turn one PDB component payload into a `SyncRecord`, or None to skip it.

    Skipped: components not in state `ready` (deleted), without a serial
    number (registered but never initialised), or with values the mirror
    schema rejects.
    """
    if payload.get("state") != "ready":
        return None
    sn = payload.get("serialNumber")
    component_type = _code(payload.get("componentType"))
    institute_code = _code(payload.get("institution")) or _code(payload.get("currentLocation"))
    if not sn or component_type is None or institute_code is None:
        return None
    try:
        return SyncRecord(
            sn=sn,
            component_type=component_type,
            type_code=_code(payload.get("type")) or UNKNOWN,
            stage=_code(payload.get("currentStage")) or UNKNOWN,
            location=_code(payload.get("currentLocation")) or institute_code,
            institute_code=institute_code,
            local_name=payload.get("alternativeIdentifier") or None,
            parent_sn=_parent_sn(payload),
            is_dummy=bool(payload.get("dummy", False)),
            trashed=bool(payload.get("trashed", False)),
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
        # itkdb wraps paged list endpoints in an iterable PagedResponse;
        # tolerate a plain dict in case a small result comes back unwrapped.
        payloads = response.get("itemList", []) if isinstance(response, dict) else response
        mapped = [map_pdb_component(payload) for payload in payloads]
    except Exception as exc:
        raise PdbSyncUnavailable(f"PDB component listing failed: {exc}") from exc

    records = [record for record in mapped if record is not None]
    return FetchResult(records=records, skipped=len(mapped) - len(records))
