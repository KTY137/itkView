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
from sqlalchemy import delete, insert, or_, select
from sqlalchemy.orm import Session

from app.models import Component, LocationEvent, StageEvent, utcnow

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


class LocationEventRecord(BaseModel):
    """One dated relocation from a component's PDB `locations[]` log."""

    location: str = Field(min_length=1, max_length=32)
    entered_at: datetime
    stage: str | None = Field(default=None, max_length=48)


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
    location_events: list[LocationEventRecord] = Field(default_factory=list)


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

    # Load the whole working set in bounded IN queries. The previous per-record
    # SELECT made a production-sized refresh issue thousands of local queries,
    # even when every component was unchanged. Parent SNs are included so pass
    # 2 never falls back to another N+1 lookup.
    record_sns = {record.sn for record in records}
    lookup_sns = record_sns | {
        record.parent_sn for record in records if record.parent_sn is not None
    }
    existing_by_sn: dict[str, Component] = {}
    for sn_chunk in _chunks(sorted(lookup_sns), 500):
        for component in session.scalars(
            select(Component).where(Component.sn.in_(sn_chunk))
        ):
            existing_by_sn[component.sn] = component

    # Pass 1: upsert mirror fields by serial number.
    for record in records:
        component = by_sn.get(record.sn) or existing_by_sn.get(record.sn)
        if component is None:
            component = Component(
                synced_at=now, **record.model_dump(exclude={"parent_sn", "stage_events", "location_events"})
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
            parent = by_sn.get(record.parent_sn) or existing_by_sn.get(record.parent_sn)
            if parent is None:
                raise UnknownParentError(record.sn, record.parent_sn)
        parent_id = parent.id if parent is not None else None
        if component.parent_id != parent_id:
            component.parent_id = parent_id
            if record.sn not in created:
                updated.add(record.sn)
    session.flush()

    _sync_stage_events(session, records, by_sn)
    _sync_location_events(session, records)

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


def _chunks(values: list[str], size: int) -> list[list[str]]:
    """Split values below SQLite's conservative bind-parameter ceiling."""

    return [values[offset : offset + size] for offset in range(0, len(values), size)]


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
    for sn_chunk in _chunks(sorted(events_by_sn), 500):
        session.execute(delete(StageEvent).where(StageEvent.component_sn.in_(sn_chunk)))
    session.flush()
    rows: list[dict] = []
    for sn, events in events_by_sn.items():
        component = by_sn[sn]
        deduped: dict[tuple[str, datetime], StageEventRecord] = {}
        for ev in events:
            deduped[(ev.stage, ev.entered_at)] = ev  # collapse identical entries
        for ev in deduped.values():
            rows.append(
                {
                    "component_sn": sn,
                    "component_type": component.component_type,
                    "type_code": component.type_code,
                    "institute_code": component.institute_code,
                    "stage": ev.stage,
                    "entered_at": ev.entered_at,
                    "rework": ev.rework,
                }
            )
    if rows:
        # No StageEvent ORM instances are consumed later, so SQLAlchemy's bulk
        # path is equivalent here and turns thousands of individual INSERTs
        # into one executemany operation.
        session.execute(insert(StageEvent), rows)
    session.flush()


def _sync_location_events(session: Session, records: Sequence[SyncRecord]) -> None:
    """Rebuild the relocation history for every component that reports one.

    Delete-and-reinsert per component, like the stage log and for the same
    reason: the two scoped listings return a component twice when it is both
    owned by and located at the institute, and an insert-only pass would
    double every move. Components without moves are untouched, so a fixture or
    demo sync never clears a real history.
    """
    events_by_sn = {r.sn: r.location_events for r in records if r.location_events}
    if not events_by_sn:
        return
    for sn_chunk in _chunks(sorted(events_by_sn), 500):
        session.execute(delete(LocationEvent).where(LocationEvent.component_sn.in_(sn_chunk)))
    session.flush()
    rows: list[dict] = []
    for sn, events in events_by_sn.items():
        deduped: dict[tuple[str, datetime], LocationEventRecord] = {}
        for ev in events:
            deduped[(ev.location, ev.entered_at)] = ev  # collapse identical entries
        for ev in deduped.values():
            rows.append(
                {
                    "component_sn": sn,
                    "location": ev.location,
                    "entered_at": ev.entered_at,
                    "stage": ev.stage,
                }
            )
    if rows:
        session.execute(insert(LocationEvent), rows)
    session.flush()


def load_fixture_records(path: str | Path) -> list[SyncRecord]:
    """Read a JSON array of component records (see app/fixtures/)."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"Fixture '{path}' must contain a JSON array of component records.")
    return [SyncRecord.model_validate(item) for item in raw]
