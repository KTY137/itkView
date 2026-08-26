"""Helpers for local test-run evidence mirrored from external sources."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import TestRunEvidence, utcnow


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
            or existing.measured_at != record.measured_at
            or payload_changed
        )
        if changed:
            existing.component_sn = record.component_sn
            existing.test_type = record.test_type
            existing.passed = record.passed
            existing.measured_at = record.measured_at
            if not record.detail_omitted:
                existing.payload = payload
            existing.synced_at = utcnow()
            updated += 1
        else:
            unchanged += 1
    return EvidenceSyncStats(created=created, updated=updated, unchanged=unchanged)
