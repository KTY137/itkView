# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-FileComment: itkflow-5cc9a4338309
import pytest

from app.outbox import (
    TERMINAL,
    TRANSITIONS,
    InvalidTransition,
    OutboxStatus,
    assert_transition,
    can_transition,
    transition_contract,
)


def test_happy_path_draft_to_confirmed():
    path = [
        OutboxStatus.DRAFT,
        OutboxStatus.VALIDATED,
        OutboxStatus.APPROVED,
        OutboxStatus.SUBMITTED,
        OutboxStatus.CONFIRMED,
    ]
    for current, target in zip(path, path[1:], strict=False):
        assert_transition(current, target)  # must not raise


def test_failed_submission_can_be_retried_or_cancelled():
    assert can_transition(OutboxStatus.SUBMITTED, OutboxStatus.FAILED)
    assert can_transition(OutboxStatus.FAILED, OutboxStatus.SUBMITTED)
    assert can_transition(OutboxStatus.FAILED, OutboxStatus.CANCELLED)


def test_terminal_states_allow_nothing():
    for terminal in TERMINAL:
        assert TRANSITIONS[terminal] == frozenset()


def test_cannot_skip_review():
    with pytest.raises(InvalidTransition):
        assert_transition(OutboxStatus.DRAFT, OutboxStatus.SUBMITTED)
    with pytest.raises(InvalidTransition):
        assert_transition(OutboxStatus.DRAFT, OutboxStatus.CONFIRMED)
    with pytest.raises(InvalidTransition):
        assert_transition(OutboxStatus.VALIDATED, OutboxStatus.SUBMITTED)


def test_every_status_is_reachable_or_initial():
    reachable = {target for targets in TRANSITIONS.values() for target in targets}
    assert reachable | {OutboxStatus.DRAFT} == set(OutboxStatus)


def test_error_message_names_both_states():
    with pytest.raises(InvalidTransition, match="draft.*confirmed"):
        assert_transition(OutboxStatus.DRAFT, OutboxStatus.CONFIRMED)


def test_transition_contract_is_json_friendly():
    contract = transition_contract()
    assert set(contract) == {status.value for status in OutboxStatus}
    assert contract["draft"] == ["validated", "cancelled"]
    assert contract["confirmed"] == []
    assert contract["cancelled"] == []
