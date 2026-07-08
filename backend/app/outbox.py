"""Outbox status machine — pure logic, no I/O.

draft ──▶ validated ──▶ approved ──▶ submitted ──▶ confirmed
  │            │             │            │
  │            ▼             │            └──▶ failed ──▶ submitted (retry)
  └──────▶ cancelled ◀───────┘                   │
                 ▲───────────────────────────────┘
"""

from enum import Enum


class OutboxStatus(str, Enum):
    DRAFT = "draft"
    VALIDATED = "validated"
    APPROVED = "approved"
    SUBMITTED = "submitted"
    CONFIRMED = "confirmed"
    FAILED = "failed"
    CANCELLED = "cancelled"


TRANSITIONS: dict[OutboxStatus, frozenset[OutboxStatus]] = {
    OutboxStatus.DRAFT: frozenset({OutboxStatus.VALIDATED, OutboxStatus.CANCELLED}),
    OutboxStatus.VALIDATED: frozenset(
        {OutboxStatus.APPROVED, OutboxStatus.DRAFT, OutboxStatus.CANCELLED}
    ),
    OutboxStatus.APPROVED: frozenset({OutboxStatus.SUBMITTED, OutboxStatus.CANCELLED}),
    OutboxStatus.SUBMITTED: frozenset({OutboxStatus.CONFIRMED, OutboxStatus.FAILED}),
    OutboxStatus.FAILED: frozenset({OutboxStatus.SUBMITTED, OutboxStatus.CANCELLED}),
    OutboxStatus.CONFIRMED: frozenset(),
    OutboxStatus.CANCELLED: frozenset(),
}

TERMINAL = frozenset({OutboxStatus.CONFIRMED, OutboxStatus.CANCELLED})


class InvalidTransition(ValueError):
    def __init__(self, current: OutboxStatus, target: OutboxStatus) -> None:
        self.current = current
        self.target = target
        super().__init__(
            f"Cannot move outbox action from '{current.value}' to '{target.value}'. "
            f"Allowed: {sorted(s.value for s in TRANSITIONS[current]) or 'none (terminal)'}."
        )


def can_transition(current: OutboxStatus, target: OutboxStatus) -> bool:
    return target in TRANSITIONS[current]


def assert_transition(current: OutboxStatus, target: OutboxStatus) -> None:
    if not can_transition(current, target):
        raise InvalidTransition(current, target)


def transition_contract() -> dict[str, list[str]]:
    """JSON-friendly status machine contract for UI/worker clients."""
    status_order = {status: index for index, status in enumerate(OutboxStatus)}
    return {
        status.value: [
            target.value for target in sorted(targets, key=lambda item: status_order[item])
        ]
        for status, targets in TRANSITIONS.items()
    }
