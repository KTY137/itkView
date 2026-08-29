# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-FileComment: itkflow-228b36e1ab82
"""Completeness-first component fetch for the read-only production mirror.

The institute listings contain components owned by or located at the site, but
an assembly can contain parts satisfying neither condition.  The original
enrichment fetched only children named by the two listings.  A fetched child
was not inspected for its own children, so deeper assemblies could still enter
the local mirror without the parts carrying their test evidence.

This module keeps the proven paginated listings and mapping code, but expands
the referenced assembly graph breadth-first before a snapshot is accepted.  A
limit or an unreadable referenced component fails the fetch instead of letting
a truncated graph look authoritative.  All PDB calls remain read-only.
"""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING, Any

from app.config import Settings
from app.models import InstituteProfile
from app.pdb_gateway import PDB_REQUEST_TIMEOUT, PdbClientUnavailable, PdbGateway
from app.pdb_sync import (
    DEFAULT_PDB_FILTERS,
    PDB_PAGE_SIZE,
    FetchResult,
    PdbSyncUnavailable,
    SyncProgress,
    _fetch_pages,
    build_id_to_sn,
    fetch_institution_codes,
    map_pdb_component,
)

if TYPE_CHECKING:
    from app.pdb_credentials import PdbAccessCodes


def _component_object_id(value: Any) -> str | None:
    """Resolve the object-id forms used by PDB assembly members."""

    if isinstance(value, str) and value:
        return value
    if isinstance(value, dict):
        object_id = value.get("id")
        if isinstance(object_id, str) and object_id:
            return object_id
    return None


def assembled_child_ids(payload: dict[str, Any]) -> tuple[str, ...]:
    """Live child object ids, ordered and deduplicated.

    A missing/null member state is the common live shape.  Explicit non-ready
    states describe removed or otherwise inactive links and must not pull a
    historical component into the current production closure.
    """

    children: dict[str, None] = {}
    for member in payload.get("children") or []:
        if not isinstance(member, dict):
            continue
        state = member.get("state")
        if state is not None and state != "ready":
            continue
        object_id = _component_object_id(member.get("component"))
        if object_id is not None:
            children.setdefault(object_id, None)
    return tuple(children)


def fetch_assembled_component_closure(
    client: Any,
    payloads: list[dict[str, Any]],
    limit: int,
    progress: SyncProgress | None = None,
) -> list[dict[str, Any]]:
    """Fetch every missing live descendant named by the current payload graph.

    ``limit`` bounds attempted remote reads across the whole recursive closure.
    Hitting it is not a partial success: without the remaining descendants the
    snapshot cannot support a completeness claim, so the caller is told to
    raise the configured limit and retry.  A referenced child that cannot be
    read has the same fail-closed result; the previous committed mirror stays
    intact because mapping and pruning have not started yet.
    """

    known_ids = {
        payload["id"]
        for payload in payloads
        if isinstance(payload.get("id"), str) and payload["id"]
    }
    known_serials = {
        payload["serialNumber"]
        for payload in payloads
        if isinstance(payload.get("serialNumber"), str) and payload["serialNumber"]
    }
    queued = set(known_ids)
    pending: deque[str] = deque()

    def enqueue_children(payload: dict[str, Any]) -> None:
        for object_id in assembled_child_ids(payload):
            if object_id in queued:
                continue
            queued.add(object_id)
            pending.append(object_id)

    for payload in payloads:
        enqueue_children(payload)

    if not pending:
        return []
    if limit <= 0:
        raise PdbSyncUnavailable(
            "The component listing references assembled parts, but assembled-part "
            "enrichment is disabled; refusing an incomplete component snapshot."
        )

    fetched: list[dict[str, Any]] = []
    attempted = 0
    while pending and attempted < limit:
        object_id = pending.popleft()
        attempted += 1
        try:
            payload = client.get(
                "getComponent",
                json={"component": object_id},
                timeout=PDB_REQUEST_TIMEOUT,
            )
        except Exception:
            raise PdbSyncUnavailable(
                "A component referenced by the assembly graph could not be read; "
                "refusing an incomplete component snapshot."
            ) from None
        if not isinstance(payload, dict):
            raise PdbSyncUnavailable(
                "A component referenced by the assembly graph returned an invalid "
                "payload; refusing an incomplete component snapshot."
            )
        if payload.get("state") != "ready":
            raise PdbSyncUnavailable(
                "A live assembly link resolved to a component that is not ready; "
                "refusing an inconsistent component snapshot."
            )
        returned_id = payload.get("id")
        if returned_id is None:
            # The request itself pins the object identity. Preserve that fact
            # for build_id_to_sn instead of losing the parent link later.
            payload = {**payload, "id": object_id}
        elif not isinstance(returned_id, str) or returned_id != object_id:
            raise PdbSyncUnavailable(
                "A component lookup returned a different object identity; refusing "
                "an inconsistent component snapshot."
            )
        serial = payload.get("serialNumber")
        if not isinstance(serial, str) or not serial:
            raise PdbSyncUnavailable(
                "A component referenced by the assembly graph has no serial number; "
                "refusing an incomplete component snapshot."
            )
        if serial in known_serials:
            raise PdbSyncUnavailable(
                "The assembly graph reuses a serial number under different component "
                "identities; refusing an ambiguous component snapshot."
            )

        enqueue_children(payload)
        known_ids.add(object_id)
        known_serials.add(serial)
        fetched.append(payload)

        if progress is not None and (
            attempted % PDB_PAGE_SIZE == 0 or not pending or attempted == limit
        ):
            progress(
                "fetching",
                len(payloads) + attempted,
                None,
                f"Resolving assembled component closure ({attempted} referenced parts read).",
            )

    if pending:
        raise PdbSyncUnavailable(
            "The assembled component closure exceeds sync_assembled_part_limit; "
            "increase the limit and retry rather than accepting a truncated snapshot."
        )
    return fetched


def fetch_complete_for_institute(
    settings: Settings,
    institute: InstituteProfile,
    access_codes: PdbAccessCodes,
    progress: SyncProgress | None = None,
) -> FetchResult:
    """List an institute's components and recursively resolve their assemblies."""

    gateway = PdbGateway(settings, access_codes=access_codes)
    if not gateway.is_configured:
        raise PdbSyncUnavailable("No personal ITKDB access codes are connected for this account.")
    try:
        client = gateway.client()
    except PdbClientUnavailable:
        raise PdbSyncUnavailable("PDB client support is unavailable on this server.") from None
    except RuntimeError:
        raise PdbSyncUnavailable("The personal PDB connection could not be opened.") from None

    profile_filters = (institute.settings or {}).get("pdb_filters") or {}
    base_filters = {
        **DEFAULT_PDB_FILTERS,
        **profile_filters,
        "state": "ready",
    }
    # Institute scope is structural and may never be narrowed accidentally by
    # profile data: both authoritative listings are always performed.
    base_filters.pop("institute", None)
    base_filters.pop("currentLocation", None)
    scopes = (
        {"institute": [institute.code]},
        {"currentLocation": [institute.code]},
    )

    try:
        payloads: list[dict[str, Any]] = []
        seen_serials: set[str] = set()
        fetched_before = 0
        for scope in scopes:
            scope_progress: SyncProgress | None = None
            if progress is not None:

                def scope_progress(  # noqa: B023 — base pinned per iteration
                    phase: str,
                    current: int,
                    total: int | None,
                    message: str | None = None,
                    _base: int = fetched_before,
                ) -> None:
                    progress(
                        phase,
                        _base + current,
                        None if total is None else _base + total,
                        message,
                    )

            scope_payloads = _fetch_pages(
                client,
                {
                    "filterMap": {**base_filters, **scope},
                    "outputType": "full",
                },
                scope_progress,
                max_attempts=settings.sync_page_max_attempts,
            )
            fetched_before += len(scope_payloads)
            for payload in scope_payloads:
                serial = payload.get("serialNumber")
                if isinstance(serial, str) and serial:
                    if serial in seen_serials:
                        continue
                    seen_serials.add(serial)
                payloads.append(payload)

        payloads.extend(
            fetch_assembled_component_closure(
                client,
                payloads,
                settings.sync_assembled_part_limit,
                progress,
            )
        )
        id_to_sn = build_id_to_sn(payloads)
        institution_codes = fetch_institution_codes(client)
        mapped = []
        if progress is not None:
            progress("mapping", 0, len(payloads))
        for index, payload in enumerate(payloads, start=1):
            mapped.append(map_pdb_component(payload, id_to_sn, institution_codes))
            if progress is not None and (index == len(payloads) or index % PDB_PAGE_SIZE == 0):
                progress("mapping", index, len(payloads))
    except PdbSyncUnavailable:
        raise
    except Exception:
        raise PdbSyncUnavailable("PDB component listing failed.") from None

    records = [record for record in mapped if record is not None]
    return FetchResult(records=records, skipped=len(mapped) - len(records))
