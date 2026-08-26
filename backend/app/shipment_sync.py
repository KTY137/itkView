"""Upsert PDB shipment records into the local mirror (Phase 4).

Same division of labour as `app.sync` / `app.tool_sync`: the fetch layer
(`app.pdb_shipments`) talks to the PDB, this module only writes mirror rows and
never touches the network. The PDB-owned columns are overwritten on every sync;
the locally-leading `reception_*` columns are never touched here — receiving
checks are people's work and survive any number of re-syncs.

The receiving checklist template is institute-profile data
(`settings['shipment_reception_checklist']`, a list of labels) and is
instantiated once when a shipment first appears; later template edits do not
rewrite checklists people may already have worked through.

The caller commits.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import InstituteProfile, Shipment
from app.pdb_shipments import ShipmentRecord

# Seed default: deliberately generic; institutes override via their profile.
DEFAULT_RECEPTION_CHECKLIST = (
    "Packaging intact",
    "Contents match the shipment list",
    "No visible damage",
)


@dataclass(frozen=True)
class ShipmentSyncStats:
    created: int = 0
    updated: int = 0
    unchanged: int = 0

    @property
    def total(self) -> int:
        return self.created + self.updated + self.unchanged


def reception_checklist_template(institute: InstituteProfile) -> list[str]:
    raw = (institute.settings or {}).get("shipment_reception_checklist")
    if isinstance(raw, list):
        labels = [label for label in raw if isinstance(label, str) and label.strip()]
        if labels:
            return labels
    return list(DEFAULT_RECEPTION_CHECKLIST)


def delivered_pdb_ids(session: Session) -> set[str]:
    """Shipments whose items need no re-fetch (delivered content is final)."""
    return set(
        session.scalars(select(Shipment.pdb_id).where(Shipment.status == "delivered"))
    )


def sync_shipments(
    session: Session, institute: InstituteProfile, records: Sequence[ShipmentRecord]
) -> ShipmentSyncStats:
    """Mirror the fetched records. PDB fields win; reception fields are kept."""
    now = datetime.now(timezone.utc)
    checklist_template = reception_checklist_template(institute)
    existing = {
        shipment.pdb_id: shipment
        for shipment in session.scalars(
            select(Shipment).where(Shipment.pdb_id.in_([r.pdb_id for r in records]))
        )
    }
    created = updated = unchanged = 0
    for record in records:
        shipment = existing.get(record.pdb_id)
        if shipment is None:
            session.add(
                Shipment(
                    pdb_id=record.pdb_id,
                    name=record.name,
                    sender_code=record.sender_code,
                    recipient_code=record.recipient_code,
                    status=record.status,
                    sent_at=record.sent_at,
                    items=record.items if record.items_fetched else [],
                    institute_id=institute.id,
                    synced_at=now,
                    reception_checklist=[
                        {"label": label, "done": False} for label in checklist_template
                    ],
                )
            )
            created += 1
            continue
        changed = (
            shipment.name != record.name
            or shipment.sender_code != record.sender_code
            or shipment.recipient_code != record.recipient_code
            or shipment.status != record.status
            or shipment.sent_at != record.sent_at
            or (record.items_fetched and shipment.items != record.items)
        )
        shipment.name = record.name
        shipment.sender_code = record.sender_code
        shipment.recipient_code = record.recipient_code
        shipment.status = record.status
        shipment.sent_at = record.sent_at
        if record.items_fetched:
            shipment.items = record.items
        shipment.institute_id = institute.id
        shipment.synced_at = now
        if changed:
            updated += 1
        else:
            unchanged += 1
    session.flush()
    return ShipmentSyncStats(created=created, updated=updated, unchanged=unchanged)
