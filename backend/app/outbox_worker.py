"""Async outbox worker — the only path that turns a reviewed action into a
real PDB write.

The worker claims actions the reviewers have signed off (`approved`) plus any
left `submitted` by a previous crash or a manual retry, drives each through
one submission attempt, and records the outcome with a full audit trail. The
actual PDB call is injected as a `Submitter`, so the offline test suite drives
the whole state machine with a fake and never touches the network.

Safety properties:
- Nothing is written to the PDB except by a `Submitter` this worker invokes.
- An action that already carries an `external_ref` is treated as *already
  written* and confirmed without a second submit (idempotency guard, covers
  crash-after-write).
- For `upload_test_run`, the dry-run validation is re-run against the *current*
  mirror immediately before submitting; stale/invalid actions fail instead of
  being written.
- A `PdbSubmitUnavailable` (could not even attempt the write) is recorded as a
  transient failure — distinct from a PDB *rejection* of the data.
"""

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingestion import parse_payload
from app.models import AuditEvent, Component, IngestFile, OutboxAction
from app.outbox import OutboxStatus, assert_transition
from app.stage_service import evaluate_for_component

WORKER_ACTOR = "outbox-worker"

# Statuses the worker will pick up. `approved` = freshly signed off; `submitted`
# = a prior attempt that never resolved (crash) or a manual `failed → submitted`
# retry. Terminal and pre-review statuses are ignored.
DUE_STATUSES = (OutboxStatus.APPROVED, OutboxStatus.SUBMITTED)


class PdbSubmitUnavailable(RuntimeError):
    """The submitter could not attempt the write (config/connectivity).

    Distinct from a PDB *rejection*: raising this means nothing was written,
    so the action may safely be retried later.
    """


@dataclass(frozen=True)
class SubmitOutcome:
    """Result of a submission attempt (a rejection is a normal, non-raising
    outcome; only *inability to attempt* raises `PdbSubmitUnavailable`)."""

    external_ref: str | None
    rejected_reason: str | None

    @classmethod
    def confirmed(cls, external_ref: str) -> "SubmitOutcome":
        return cls(external_ref=external_ref, rejected_reason=None)

    @classmethod
    def rejected(cls, reason: str) -> "SubmitOutcome":
        return cls(external_ref=None, rejected_reason=reason)

    @property
    def is_confirmed(self) -> bool:
        return self.rejected_reason is None


# A submitter performs the actual PDB write for one action. It returns a
# `SubmitOutcome` (confirmed/rejected) or raises `PdbSubmitUnavailable`.
Submitter = Callable[[Session, OutboxAction], SubmitOutcome]


@dataclass
class WorkerStats:
    confirmed: int = 0
    rejected: int = 0
    unavailable: int = 0
    revalidation_failed: int = 0

    @property
    def total(self) -> int:
        return self.confirmed + self.rejected + self.unavailable + self.revalidation_failed


def revalidate(session: Session, action: OutboxAction) -> list[str]:
    """Re-check an action against the *current* mirror just before submitting.

    Returns blocking issues (empty list = good to submit). Dispatches by kind;
    kinds with no dry-run gate return no issues.
    """
    if action.kind == "upload_test_run":
        return revalidate_upload(session, action)
    if action.kind == "stage_move":
        return revalidate_stage_move(session, action)
    return []


def revalidate_upload(session: Session, action: OutboxAction) -> list[str]:
    """Re-run the dry-run for an `upload_test_run` action against the current
    mirror. Returns blocking issues (empty list = good to submit)."""
    ingest_id = action.payload.get("ingest_file_id")
    ingest = session.get(IngestFile, ingest_id) if ingest_id is not None else None
    if ingest is None:
        return ["The ingest file backing this action no longer exists."]

    parsed = parse_payload(ingest.payload)
    issues = list(parsed.issues)
    # The component must still resolve in the mirror (by SN, else local name).
    component = None
    if parsed.component_sn is not None:
        component = session.scalar(select(Component).where(Component.sn == parsed.component_sn))
    elif parsed.local_name is not None:
        component = session.scalar(
            select(Component).where(Component.local_name == parsed.local_name)
        )
    if component is None:
        issues.append("Component is no longer in the local mirror; re-sync before submitting.")
    return issues


def revalidate_stage_move(session: Session, action: OutboxAction) -> list[str]:
    """A stage move is only sent if the suggestion engine still endorses it:
    the component is at the recorded `from_stage` and the target is still the
    suggested next stage (required tests passed). This stops a move whose tests
    later failed, or a component that already advanced, from being written."""
    payload = action.payload or {}
    sn = payload.get("sn")
    to_stage = payload.get("to_stage")
    component = session.scalar(select(Component).where(Component.sn == sn)) if sn else None
    if component is None:
        return [f"Component '{sn}' is no longer in the local mirror."]

    from_stage = payload.get("from_stage")
    if from_stage is not None and component.stage != from_stage:
        return [
            f"Component already moved: expected stage '{from_stage}', now '{component.stage}'."
        ]

    evaluation = evaluate_for_component(session, component)
    if not evaluation.move_suggested:
        return ["Stage move is no longer suggested: required tests are failing or missing."]
    if evaluation.suggested_stage != to_stage:
        return [
            f"Suggested stage changed to '{evaluation.suggested_stage}', not '{to_stage}'."
        ]
    return []


def _audit(session: Session, action: OutboxAction, name: str, detail: dict) -> None:
    session.add(
        AuditEvent(
            actor=WORKER_ACTOR,
            action=name,
            subject=f"outbox:{action.id}",
            detail=detail,
            outbox_action_id=action.id,
        )
    )


def _move(session: Session, action: OutboxAction, target: OutboxStatus) -> None:
    assert_transition(OutboxStatus(action.status), target)
    action.status = target.value


def _fail(session: Session, action: OutboxAction, reason: str, *, transient: bool) -> None:
    _move(session, action, OutboxStatus.FAILED)
    action.error = reason
    _audit(
        session,
        action,
        "outbox.failed",
        {"reason": reason, "transient": transient, "attempts": action.attempts},
    )


def _process_one(session: Session, submitter: Submitter, action: OutboxAction) -> str:
    """Drive one due action through a single submission attempt.

    Returns a short outcome tag for the caller's stats.
    """
    if OutboxStatus(action.status) is OutboxStatus.APPROVED:
        _move(session, action, OutboxStatus.SUBMITTED)
        action.attempts += 1
        _audit(session, action, "outbox.submitting", {"attempts": action.attempts})

    # Idempotency: a recorded external_ref means the write already happened.
    if action.external_ref:
        _move(session, action, OutboxStatus.CONFIRMED)
        _audit(
            session,
            action,
            "outbox.confirmed",
            {"external_ref": action.external_ref, "note": "already written"},
        )
        return "confirmed"

    issues = revalidate(session, action)
    if issues:
        _fail(session, action, "Dry-run validation failed: " + "; ".join(issues), transient=False)
        return "revalidation_failed"

    try:
        outcome = submitter(session, action)
    except PdbSubmitUnavailable as exc:
        _fail(session, action, f"PDB unavailable: {exc}", transient=True)
        return "unavailable"

    if outcome.is_confirmed:
        action.external_ref = outcome.external_ref
        action.error = None
        _move(session, action, OutboxStatus.CONFIRMED)
        _audit(session, action, "outbox.confirmed", {"external_ref": outcome.external_ref})
        return "confirmed"

    _fail(session, action, outcome.rejected_reason or "PDB rejected the upload.", transient=False)
    return "rejected"


def process_due_actions(
    session: Session, submitter: Submitter, *, limit: int = 20
) -> WorkerStats:
    """Process one batch of due outbox actions. Commits after each action so a
    crash mid-batch leaves the queue in a consistent, resumable state."""
    stats = WorkerStats()
    actions = list(
        session.scalars(
            select(OutboxAction)
            .where(OutboxAction.status.in_([s.value for s in DUE_STATUSES]))
            .order_by(OutboxAction.id)
            .limit(limit)
        )
    )
    for action in actions:
        tag = _process_one(session, submitter, action)
        session.commit()
        setattr(stats, tag, getattr(stats, tag) + 1)
    return stats
