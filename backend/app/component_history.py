"""One chronological record of what happened to a component.

Everything here is already mirrored; what was missing is the shared time axis.
The stage log fed only the statistics screen, the runs sat behind the
worksheet, and a person asking "what happened to this module, and when" had to
read two panels and merge them in their head.

Read-only over the local mirror — no PDB I/O, and no judgement: this module
reports what the record says, it does not decide whether a requirement is met.
That distinction matters for withdrawn runs. The stage gate ignores a retracted
run, which is the honest verdict; the history still shows it and says it was
retracted, because a gap in a record is itself a claim.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import LocationEvent, StageEvent, TestRunEvidence
from app.test_run_evidence import is_withdrawn


@dataclass(frozen=True)
class HistoryEvent:
    kind: str
    at: datetime | None
    stage: str | None = None
    location: str | None = None
    rework: bool | None = None
    test_type: str | None = None
    passed: bool | None = None
    withdrawn: bool | None = None
    external_ref: str | None = None


def _utc_naive(value: datetime | None) -> datetime | None:
    """One reading of an instant, whatever engine stored it.

    SQLite hands back naive datetimes and PostgreSQL aware ones. Merging two
    sources on a shared axis has to compare them, so both are normalised here
    rather than in each caller.
    """
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _sort_key(event: HistoryEvent) -> tuple[int, datetime]:
    # Undated rows carry no claim about when they happened, so they sort after
    # everything dated instead of being given an invented position.
    if event.at is None:
        return (0, datetime.min)
    return (1, event.at)


def component_history(session: Session, sn: str) -> list[HistoryEvent]:
    """Stage transitions and mirrored test runs on one axis, newest first."""

    events: list[HistoryEvent] = [
        HistoryEvent(
            kind="stage",
            at=_utc_naive(row.entered_at),
            stage=row.stage,
            rework=bool(row.rework),
        )
        for row in session.execute(
            select(StageEvent.entered_at, StageEvent.stage, StageEvent.rework).where(
                StageEvent.component_sn == sn
            )
        )
    ]
    events.extend(
        HistoryEvent(
            kind="test",
            at=_utc_naive(row.measured_at),
            test_type=row.test_type,
            passed=bool(row.passed),
            withdrawn=is_withdrawn(row.run_state),
            external_ref=row.external_ref,
        )
        for row in session.execute(
            select(
                TestRunEvidence.measured_at,
                TestRunEvidence.test_type,
                TestRunEvidence.passed,
                TestRunEvidence.run_state,
                TestRunEvidence.external_ref,
            ).where(TestRunEvidence.component_sn == sn)
        )
    )
    events.extend(
        HistoryEvent(
            kind="location",
            at=_utc_naive(row.entered_at),
            location=row.location,
            stage=row.stage,
        )
        for row in session.execute(
            select(
                LocationEvent.entered_at, LocationEvent.location, LocationEvent.stage
            ).where(LocationEvent.component_sn == sn)
        )
    )
    events.sort(key=_sort_key, reverse=True)
    return events


def history_read_model(events: list[HistoryEvent]) -> list[dict[str, Any]]:
    """Public projection; the stored row itself never reaches the wire."""
    return [
        {
            "kind": event.kind,
            "at": event.at,
            "stage": event.stage,
            "location": event.location,
            "rework": event.rework,
            "test_type": event.test_type,
            "passed": event.passed,
            "withdrawn": event.withdrawn,
            "external_ref": event.external_ref,
        }
        for event in events
    ]
