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
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field
from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from app.models import Component, StageEvent, utcnow

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


class StageEventRecord(BaseModel):
    """One dated stage transition from a component's PDB `stages[]` log."""

    stage: str = Field(min_length=1, max_length=48)
    entered_at: datetime
    rework: bool = False


class SyncRecord(BaseModel):
    """One component as reported by the PDB (parents referenced by SN)."""

    sn: str = Field(min_length=1, max_length=20)
    component_type: str = Field(min_length=1, max_length=32)
    type_code: str = Field(min_length=1, max_length=32)
    stage: str = Field(min_length=1, max_length=48)
    location: str = Field(min_length=1, max_length=32)
    institute_code: str = Field(min_length=1, max_length=32)
    local_name: str | None = Field(default=None, max_length=64)
    parent_sn: str | None = Field(default=None, max_length=20)
    is_dummy: bool = False
    trashed: bool = False
    stage_events: list[StageEventRecord] = Field(default_factory=list)


@dataclass
class SyncStats:
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    stale: int = 0  # in-scope rows the PDB no longer returned (pruned)

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


def sync_components(
    session: Session,
    records: Sequence[SyncRecord],
    prune_scope: str | None = None,
) -> SyncStats:
    """Upsert PDB component records into the local mirror. Idempotent.

    Duplicate serial numbers within one batch are allowed; the last record
    wins. `synced_at` is refreshed on every seen component, changed or not.

    `prune_scope` is an institute code that makes this a *full* sync of that
    institute: after upserting, any mirror row governed by it (owned by or
    located at it) that this batch did not return is flagged `stale`, so a
    complete fetch also cleans up components that left the PDB's view. Rows
    seen this run are un-staled. Leave it None for partial/fixture syncs.
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
            component = Component(
                synced_at=now, **record.model_dump(exclude={"parent_sn", "stage_events"})
            )
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
        # A component we just saw is live; clear any earlier stale flag. This
        # is lifecycle state, not mirrored PDB data, so it never counts as an
        # "updated" field change.
        component.stale = False
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

    _sync_stage_events(session, records, by_sn)

    # Prune pass: flag governed rows this full sync did not return as stale.
    # Keyed on the seen serial numbers (not timestamps) so it is independent of
    # clock resolution and re-runnable.
    stale = 0
    if prune_scope is not None:
        seen = set(by_sn)
        governed = session.scalars(
            select(Component).where(
                or_(
                    Component.institute_code == prune_scope,
                    Component.location == prune_scope,
                )
            )
        )
        for row in governed:
            if row.sn not in seen:
                row.stale = True
                stale += 1
        session.flush()

    return SyncStats(
        created=len(created),
        updated=len(updated),
        unchanged=len(by_sn) - len(created) - len(updated),
        stale=stale,
    )


def _sync_stage_events(
    session: Session,
    records: Sequence[SyncRecord],
    by_sn: dict[str, Component],
) -> None:
    """Rebuild the stage-transition history for every component carrying one.

    Delete-and-reinsert per component (not per record) so the duplicate rows an
    OR-location search returns don't double-insert. Only components that report
    stage events are touched, so fixture/demo syncs (no history) are untouched.
    """
    events_by_sn = {r.sn: r.stage_events for r in records if r.stage_events}
    if not events_by_sn:
        return
    session.execute(
        delete(StageEvent).where(StageEvent.component_sn.in_(list(events_by_sn)))
    )
    session.flush()
    for sn, events in events_by_sn.items():
        component = by_sn[sn]
        deduped: dict[tuple[str, datetime], StageEventRecord] = {}
        for ev in events:
            deduped[(ev.stage, ev.entered_at)] = ev  # collapse identical entries
        for ev in deduped.values():
            session.add(
                StageEvent(
                    component_sn=sn,
                    component_type=component.component_type,
                    type_code=component.type_code,
                    institute_code=component.institute_code,
                    stage=ev.stage,
                    entered_at=ev.entered_at,
                    rework=ev.rework,
                )
            )
    session.flush()


def load_fixture_records(path: str | Path) -> list[SyncRecord]:
    """Read a JSON array of component records (see app/fixtures/)."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"Fixture '{path}' must contain a JSON array of component records.")
    return [SyncRecord.model_validate(item) for item in raw]
