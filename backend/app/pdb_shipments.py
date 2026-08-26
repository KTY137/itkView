"""Read-only fetch of an institute's shipments from the PDB.

Mirrors what zeuthenflow's shipmentManager read (`listShipmentsByInstitution`
plus `listShipmentItems` per shipment) into plain `ShipmentRecord`s for
`app.shipment_sync`. Strictly read-only, only reachable behind the production
opt-in, and quiet about upstream failure details — itkdb errors can carry the
request, and the request can carry access codes, so only our own message
crosses this boundary (same contract as `app.pdb_sync`).

The institution filter is queried twice — once as recipient, once as sender —
and merged by id, so both incoming and outgoing shipments land in the mirror.
Items of shipments the mirror already holds as `delivered` are not re-fetched:
a delivered shipment's content cannot change (zeuthenflow relied on the same
invariant for its cache).
"""

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class PdbShipmentsUnavailable(RuntimeError):
    """The PDB could not be read, as opposed to having no shipments."""


class ShipmentRecord(BaseModel):
    """One shipment as fetched from the PDB, ready for the mirror upsert."""

    pdb_id: str
    name: str | None = None
    sender_code: str
    recipient_code: str
    status: str
    sent_at: datetime | None = None
    items: list[dict] = Field(default_factory=list)
    # False when the fetch skipped the per-shipment item request (already
    # delivered and mirrored) — the upsert then keeps the existing items.
    items_fetched: bool = True


def _code(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    if isinstance(value, dict):
        code = value.get("code")
        if isinstance(code, str) and code:
            return code
    return None


def _parse_dt(value: Any) -> datetime | None:
    """ISO timestamp to naive UTC (stable across the SQLite round-trip)."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _shipment_rows(raw: Any) -> list[dict]:
    """The PDB wraps lists inconsistently; accept the shapes we have seen."""
    if isinstance(raw, dict):
        for key in ("itemList", "pageItemList"):
            rows = raw.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
        return []
    if isinstance(raw, list):
        return [row for row in raw if isinstance(row, dict)]
    try:  # itkdb PagedResponse is iterable
        return [row for row in raw if isinstance(row, dict)]
    except TypeError:
        return []


def _item_entries(raw: Any) -> list[dict]:
    entries: list[dict] = []
    for row in _shipment_rows(raw):
        component = row.get("component")
        sn = None
        component_type = None
        if isinstance(component, dict):
            sn = component.get("serialNumber")
            component_type = _code(component.get("componentType"))
        sn = sn or row.get("serialNumber") or _code(row.get("code"))
        if not isinstance(sn, str) or not sn:
            continue
        entry: dict[str, Any] = {"sn": sn}
        if component_type:
            entry["component_type"] = component_type
        entries.append(entry)
    return entries


def _list_by_institution(client: Any, institute_code: str, role: str) -> list[dict]:
    payload = {"filterMap": {role: institute_code}}
    raw = client.get("listShipmentsByInstitution", json=payload)
    return _shipment_rows(raw)


def fetch_shipments_for_institute(
    gateway: Any, institute_code: str, *, skip_items_for: set[str] | None = None
) -> list[ShipmentRecord]:
    """Fetch every shipment where the institute is sender or recipient.

    `skip_items_for` holds PDB shipment ids whose item lists need not be
    re-fetched (already mirrored as delivered).
    """
    if not getattr(gateway, "is_configured", False):
        raise PdbShipmentsUnavailable(
            "No personal PDB connection is available for this account."
        )
    skip_items_for = skip_items_for or set()
    try:
        client = gateway.client()
        rows_by_id: dict[str, dict] = {}
        for role in ("recipient", "sender"):
            for row in _list_by_institution(client, institute_code, role):
                pdb_id = row.get("id") or _code(row.get("code"))
                if pdb_id is None:
                    continue
                rows_by_id[str(pdb_id)] = row
    except Exception:
        # Deliberately not chained — see module docstring.
        raise PdbShipmentsUnavailable("The PDB shipment list could not be read.") from None

    records: list[ShipmentRecord] = []
    for pdb_id, row in rows_by_id.items():
        sender = _code(row.get("sender")) or ""
        recipient = _code(row.get("recipient")) or ""
        status = row.get("status")
        record = ShipmentRecord(
            pdb_id=pdb_id,
            name=row.get("name") if isinstance(row.get("name"), str) else None,
            sender_code=sender,
            recipient_code=recipient,
            status=status if isinstance(status, str) and status else "unknown",
            sent_at=_parse_dt(row.get("sentTs") or row.get("cts")),
        )
        if pdb_id in skip_items_for:
            record.items_fetched = False
        else:
            try:
                raw_items = client.get("listShipmentItems", json={"shipment": pdb_id})
            except Exception:
                # Best effort per shipment: keep the header row, mark the items
                # as not fetched so the mirror keeps whatever it already has.
                record.items_fetched = False
            else:
                record.items = _item_entries(raw_items)
        records.append(record)
    return records
