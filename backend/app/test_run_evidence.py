# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-FileComment: itkflow-45fb139d8c9d
"""Helpers for local test-run evidence mirrored from external sources."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import ColumnElement, or_, select
from sqlalchemy.orm import Session

from app.models import TestRunEvidence, utcnow

#: The PDB's own state for a test run that has been withdrawn. `getComponent`
#: keeps returning such a run, so it reaches the mirror like any other; it must
#: not be read as evidence that a test was performed.
WITHDRAWN_RUN_STATE = "deleted"


def is_withdrawn(run_state: str | None) -> bool:
    """Whether a mirrored run has been retracted in the PDB.

    Deliberately an exact match on the single withdrawn state rather than
    "anything that is not `ready`": `requestedToDelete` is a pending request
    that the PDB has not acted on, and treating a still-served run as gone
    would be the same class of false statement in the other direction.
    ``None`` (unknown state — a pre-backfill row, or a non-PDB source) counts
    as valid, so this can never delete evidence it has no information about.
    """
    return run_state == WITHDRAWN_RUN_STATE


def live_runs_only() -> ColumnElement[bool]:
    """SQL predicate for the runs the PDB still stands behind.

    The SQL twin of `is_withdrawn`; expressed as an explicit NULL-or-not-equal
    pair rather than ``!=`` because a plain inequality is false for NULL in
    both SQLite and PostgreSQL and would silently drop every row whose state is
    unknown.
    """
    return or_(
        TestRunEvidence.run_state.is_(None),
        TestRunEvidence.run_state != WITHDRAWN_RUN_STATE,
    )


@dataclass(frozen=True)
class TestRunEvidenceRecord:
    __test__ = False

    component_sn: str
    test_type: str
    passed: bool
    source: str = "pdb"
    external_ref: str | None = None
    measured_at: datetime | None = None
    payload: dict[str, Any] | None = None
    # The source's own lifecycle state for this run; see
    # `models.TestRunEvidence.run_state`. ``None`` means the source does not
    # report one.
    run_state: str | None = None
    # True when the per-run detail fetch was skipped because the mirrored row
    # already holds it: the upsert then never touches the stored payload.
    detail_omitted: bool = False


@dataclass(frozen=True)
class EvidenceSyncStats:
    created: int = 0
    updated: int = 0
    unchanged: int = 0

    @property
    def total(self) -> int:
        return self.created + self.updated + self.unchanged


def _as_naive_utc(value: datetime | None) -> datetime | None:
    """PostgreSQL returns aware timestamps, records carry naive UTC — the
    change detector must not report a phantom update for the same instant."""
    if value is not None and value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _find_existing(session: Session, record: TestRunEvidenceRecord) -> TestRunEvidence | None:
    if record.external_ref:
        return session.scalar(
            select(TestRunEvidence).where(
                TestRunEvidence.source == record.source,
                TestRunEvidence.external_ref == record.external_ref,
            )
        )
    return session.scalar(
        select(TestRunEvidence).where(
            TestRunEvidence.source == record.source,
            TestRunEvidence.component_sn == record.component_sn,
            TestRunEvidence.test_type == record.test_type,
            # A ref-less record may only ever match a ref-less row: grabbing a
            # referenced row would overwrite its mirrored detail with the
            # shallow latest-state payload.
            TestRunEvidence.external_ref.is_(None),
        )
    )


def upsert_test_run_evidence(
    session: Session, records: list[TestRunEvidenceRecord]
) -> EvidenceSyncStats:
    """Insert/update mirrored test-run evidence by source reference.

    Records with an external reference are idempotent by `(source, external_ref)`.
    Records without one fall back to `(source, component_sn, test_type)`, useful
    for fixture or reconciliation sources that only provide latest state.
    """
    created = updated = unchanged = 0
    for record in records:
        payload = dict(record.payload or {})
        existing = _find_existing(session, record)
        if existing is None:
            session.add(
                TestRunEvidence(
                    component_sn=record.component_sn,
                    test_type=record.test_type,
                    passed=record.passed,
                    source=record.source,
                    external_ref=record.external_ref,
                    measured_at=record.measured_at,
                    run_state=record.run_state,
                    payload=payload,
                    synced_at=utcnow(),
                )
            )
            created += 1
            continue

        payload_changed = not record.detail_omitted and existing.payload != payload
        changed = (
            existing.component_sn != record.component_sn
            or existing.test_type != record.test_type
            or existing.passed != record.passed
            or _as_naive_utc(existing.measured_at) != _as_naive_utc(record.measured_at)
            # A withdrawal is exactly the change that must never be skipped: it
            # arrives on the cheap listing path, so `detail_omitted` may be set
            # and the payload comparison alone would call the row unchanged.
            or existing.run_state != record.run_state
            or payload_changed
        )
        if changed:
            existing.component_sn = record.component_sn
            existing.test_type = record.test_type
            existing.passed = record.passed
            existing.measured_at = record.measured_at
            existing.run_state = record.run_state
            if not record.detail_omitted:
                existing.payload = payload
            existing.synced_at = utcnow()
            updated += 1
        else:
            unchanged += 1
    return EvidenceSyncStats(created=created, updated=updated, unchanged=unchanged)
