"""PDB→local sync for the component mirror — upsert logic, no PDB I/O.

Whoever fetches records (the PDB gateway, or a fixture file for demos and
tests) produces `SyncRecord`s; this module folds them into the `component`
mirror table idempotently. Two passes: pass 1 upserts every component by
serial number, pass 2 resolves parent links — so children may arrive before
their parents. The caller owns the transaction (commit/rollback).
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Component, utcnow

# Mirror fields copied verbatim from a record to the row. Changing any of
# them counts the row as "updated"; `synced_at` alone does not.
_MIRROR_FIELDS = (
    "component_type",
    "type_code",
    "stage",
    "location",
    "institute_code",
    "local_name",
    "is_dummy",
    "trashed",
)


class SyncRecord(BaseModel):
    """One component as reported by the PDB (parents referenced by SN)."""

    sn: str = Field(min_length=1, max_length=20)
    component_type: str = Field(min_length=1, max_length=32)
    type_code: str = Field(min_length=1, max_length=32)
    stage: str = Field(min_length=1, max_length=48)
    location: str = Field(min_length=1, max_length=16)
    institute_code: str = Field(min_length=1, max_length=16)
    local_name: str | None = Field(default=None, max_length=64)
    parent_sn: str | None = Field(default=None, max_length=20)
    is_dummy: bool = False
    trashed: bool = False


@dataclass
class SyncStats:
    created: int = 0
    updated: int = 0
    unchanged: int = 0

    @property
    def total(self) -> int:
        return self.created + self.updated + self.unchanged


class UnknownParentError(ValueError):
    def __init__(self, sn: str, parent_sn: str) -> None:
        self.sn = sn
        self.parent_sn = parent_sn
        super().__init__(
            f"Component '{sn}' references parent '{parent_sn}', which is neither "
            "in this sync batch nor already mirrored."
        )


def sync_components(session: Session, records: Sequence[SyncRecord]) -> SyncStats:
    """Upsert PDB component records into the local mirror. Idempotent.

    Duplicate serial numbers within one batch are allowed; the last record
    wins. `synced_at` is refreshed on every seen component, changed or not.
    """
    now = utcnow()
    by_sn: dict[str, Component] = {}
    created: set[str] = set()
    updated: set[str] = set()

    # Pass 1: upsert mirror fields by serial number.
    for record in records:
        component = by_sn.get(record.sn) or session.scalar(
            select(Component).where(Component.sn == record.sn)
        )
        if component is None:
            component = Component(synced_at=now, **record.model_dump(exclude={"parent_sn"}))
            session.add(component)
            created.add(record.sn)
        else:
            for field in _MIRROR_FIELDS:
                value = getattr(record, field)
                if getattr(component, field) != value:
                    setattr(component, field, value)
                    if record.sn not in created:
                        updated.add(record.sn)
            component.synced_at = now
        by_sn[record.sn] = component
    session.flush()  # assign ids before linking parents

    # Pass 2: resolve parent links by SN (order-independent).
    for record in records:
        component = by_sn[record.sn]
        parent: Component | None = None
        if record.parent_sn is not None:
            parent = by_sn.get(record.parent_sn) or session.scalar(
                select(Component).where(Component.sn == record.parent_sn)
            )
            if parent is None:
                raise UnknownParentError(record.sn, record.parent_sn)
        parent_id = parent.id if parent is not None else None
        if component.parent_id != parent_id:
            component.parent_id = parent_id
            if record.sn not in created:
                updated.add(record.sn)
    session.flush()

    return SyncStats(
        created=len(created),
        updated=len(updated),
        unchanged=len(by_sn) - len(created) - len(updated),
    )


def load_fixture_records(path: str | Path) -> list[SyncRecord]:
    """Read a JSON array of component records (see app/fixtures/)."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"Fixture '{path}' must contain a JSON array of component records.")
    return [SyncRecord.model_validate(item) for item in raw]
