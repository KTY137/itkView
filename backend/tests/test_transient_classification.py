"""Transient-vs-permanent failure classification across the write and sync paths.

Three layers share the same question — "is retrying useful?" — and each answers
it at its own boundary:

* the outbox worker retries actions whose failure is marked ``PDB
  unavailable:`` (`is_transient_failure`), a prefix only `PdbSubmitUnavailable`
  produces;
* the real submitter (`app.pdb_submit._call_pdb`) turns upstream HTTP statuses
  into that split: 4xx is a rejection of the data/request, while DNS failures,
  connection resets, TLS trouble, timeouts, 408/425/429 and 5xx stay retryable;
* the attachment mirror classifies raw transport errors itself
  (`app.attachment_store.is_transient_download_error`, covered in
  test_attachment_store.py).

These tests pin the classification for the outage shapes seen in practice so a
regression cannot silently turn a short outage into a permanent failure — or a
data rejection into an endless retry.
"""

import socket
import ssl
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.outbox import OutboxStatus
from app.outbox_worker import is_transient_failure, retry_ready
from app.pdb_submit import PdbSubmitUnavailable, _call_pdb, _PdbRequestRejected


class _HttpStatusError(RuntimeError):
    """Shape of an itkdb ResponseException: the response rides on the error."""

    def __init__(self, status: int):
        super().__init__("received HTTP response for following request <redacted>")
        self.response = SimpleNamespace(status_code=status)


def _raising(error: Exception):
    def method(*args, **kwargs):
        raise error

    return method


# ---- submitter boundary: _call_pdb ----------------------------------------


@pytest.mark.parametrize("status", [500, 502, 503, 504, 408, 425, 429])
def test_call_pdb_keeps_server_errors_and_timeouts_retryable(status):
    with pytest.raises(PdbSubmitUnavailable):
        _call_pdb(_raising(_HttpStatusError(status)), unavailable_message="try later")


@pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 422])
def test_call_pdb_treats_client_errors_as_final_rejections(status):
    with pytest.raises(_PdbRequestRejected):
        _call_pdb(_raising(_HttpStatusError(status)), unavailable_message="try later")


@pytest.mark.parametrize(
    "error",
    [
        socket.gaierror(-2, "Name or service not known"),
        ConnectionResetError(104, "Connection reset by peer"),
        ssl.SSLError("The handshake operation timed out"),
        TimeoutError("timed out"),
    ],
)
def test_call_pdb_keeps_transport_failures_retryable(error):
    with pytest.raises(PdbSubmitUnavailable):
        _call_pdb(_raising(error), unavailable_message="try later")


def test_call_pdb_never_leaks_the_upstream_error_text():
    """itkdb renders the request (credentials included) into its messages."""
    secret = "accessCode1=super-secret-value"
    with pytest.raises(PdbSubmitUnavailable) as caught:
        _call_pdb(_raising(RuntimeError(secret)), unavailable_message="try later")
    assert secret not in str(caught.value)
    assert caught.value.__cause__ is None


# ---- worker boundary: is_transient_failure / retry_ready -------------------


def _action(status=OutboxStatus.FAILED.value, error="PDB unavailable: x", attempts=1, age=None):
    updated = datetime.now(timezone.utc) - (age or timedelta(0))
    return SimpleNamespace(status=status, error=error, attempts=attempts, updated_at=updated)


def test_is_transient_failure_requires_the_unavailable_prefix_and_failed_status():
    assert is_transient_failure(_action()) is True
    # A data rejection must never be auto-retried.
    assert is_transient_failure(_action(error="PDB rejected the upload.")) is False
    # An exhausted action loses the prefix and with it the retry entitlement.
    assert (
        is_transient_failure(
            _action(error="Maximum attempts reached (5/5). Last error: PDB unavailable: x")
        )
        is False
    )
    assert is_transient_failure(_action(error=None)) is False
    assert is_transient_failure(_action(status=OutboxStatus.CONFIRMED.value)) is False


def test_retry_ready_honours_exponential_backoff():
    fresh = _action(attempts=2)
    aged = _action(attempts=2, age=timedelta(seconds=121))
    now = datetime.now(timezone.utc)
    assert (
        retry_ready(fresh, now=now, retry_backoff_seconds=60, max_attempts=5) is False
    )
    assert retry_ready(aged, now=now, retry_backoff_seconds=60, max_attempts=5) is True


def test_retry_ready_surfaces_exhausted_actions_immediately():
    """At the attempt limit the action is picked up once more — not to submit,
    but so the worker can close it out as retry_exhausted."""
    exhausted = _action(attempts=5)
    now = datetime.now(timezone.utc)
    assert (
        retry_ready(exhausted, now=now, retry_backoff_seconds=3600, max_attempts=5)
        is True
    )
