"""Offline tests for the async outbox worker.

The real PDB submitter is never used here: every test injects a fake, so the
full claim → revalidate → submit → confirm/fail state machine is exercised
without a network. The one real-PDB guarantee under test is negative — the
submitter is not even called when it must not be.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from app.db import ensure_phase0_sqlite_schema, make_engine
from app.models import AuditEvent, OutboxAction
from app.outbox import OutboxStatus
from app.outbox_worker import (
    PdbSubmitUnavailable,
    SubmitOutcome,
    process_due_actions,
    revalidate_upload,
)
from app.run_worker import main as worker_main
from app.seed_demo import DEMO_FIXTURE_PATH
from app.sync import load_fixture_records, sync_components


def valid_payload(component: str = "20USE5M0000701") -> dict:
    return {
        "component": component,
        "testType": "MODULE_METROLOGY",
        "institution": "TUDO",
        "runNumber": "1",
        "date": "2026-07-08T09:30:00.000Z",
        "passed": True,
        "problems": False,
        "properties": {"OPERATOR": "Anna Abel"},
        "results": {"BOW": 12.5},
    }


# ---- submitters ------------------------------------------------------------


def confirming(ref: str = "PDB-RUN-42"):
    def submit(session, action):
        return SubmitOutcome.confirmed(ref)

    return submit


def rejecting(reason: str = "stage does not allow this test"):
    def submit(session, action):
        return SubmitOutcome.rejected(reason)

    return submit


def unavailable(message: str = "connection refused"):
    def submit(session, action):
        raise PdbSubmitUnavailable(message)

    return submit


def never_called(session, action):
    raise AssertionError("submitter must not be called for this action")


# ---- seeding ---------------------------------------------------------------


def seed_upload_action(
    client: TestClient,
    session_factory: sessionmaker[Session],
    *,
    component: str = "20USE5M0000701",
    status: OutboxStatus = OutboxStatus.APPROVED,
    external_ref: str | None = None,
) -> int:
    """Create a mirrored component set, an ingest file and an outbox
    `upload_test_run` action moved to the requested status. Returns its id."""
    client.post(
        "/api/institutes",
        json={"code": "TUDO", "name": "TU Dortmund", "local_name_prefix": "TUDO-"},
    )
    with session_factory() as session:
        sync_components(session, load_fixture_records(DEMO_FIXTURE_PATH))
        session.commit()

    ingest = client.post(
        "/api/ingest/files",
        json={
            "filename": "metrology.json",
            "uploaded_by": "anna.abel@example.org",
            "payload": valid_payload(component),
        },
    ).json()
    action = client.post(
        f"/api/ingest/files/{ingest['id']}/propose-outbox",
        json={"created_by": "anna.abel@example.org"},
    ).json()

    with session_factory() as session:
        row = session.get(OutboxAction, action["id"])
        row.status = status.value
        row.external_ref = external_ref
        session.commit()
    return action["id"]


def load_action(session_factory: sessionmaker[Session], action_id: int) -> OutboxAction:
    with session_factory() as session:
        return session.get(OutboxAction, action_id)


def audit_actions(session_factory: sessionmaker[Session], action_id: int) -> list[str]:
    with session_factory() as session:
        events = session.scalars(
            select(AuditEvent)
            .where(AuditEvent.outbox_action_id == action_id)
            .order_by(AuditEvent.id)
        )
        return [event.action for event in events]


# ---- tests -----------------------------------------------------------------


def test_worker_confirms_approved_action(client, session_factory):
    action_id = seed_upload_action(client, session_factory)

    with session_factory() as session:
        stats = process_due_actions(session, confirming("PDB-RUN-42"))

    assert (stats.confirmed, stats.total) == (1, 1)
    action = load_action(session_factory, action_id)
    assert action.status == OutboxStatus.CONFIRMED.value
    assert action.external_ref == "PDB-RUN-42"
    assert action.attempts == 1
    assert action.error is None
    assert audit_actions(session_factory, action_id) == [
        "ingest.outbox_proposed",
        "outbox.submitting",
        "outbox.confirmed",
    ]


def test_worker_records_pdb_rejection(client, session_factory):
    action_id = seed_upload_action(client, session_factory)

    with session_factory() as session:
        stats = process_due_actions(session, rejecting("bad stage"))

    assert stats.rejected == 1
    action = load_action(session_factory, action_id)
    assert action.status == OutboxStatus.FAILED.value
    assert "bad stage" in action.error
    assert action.external_ref is None


def test_worker_marks_transient_unavailable_distinctly(client, session_factory):
    action_id = seed_upload_action(client, session_factory)

    with session_factory() as session:
        stats = process_due_actions(session, unavailable("connection refused"))

    assert stats.unavailable == 1
    action = load_action(session_factory, action_id)
    assert action.status == OutboxStatus.FAILED.value
    assert action.error.startswith("PDB unavailable")

    with session_factory() as session:
        failed_event = session.query(AuditEvent).filter_by(
            outbox_action_id=action_id, action="outbox.failed"
        ).one()
        assert failed_event.detail["transient"] is True


def test_worker_blocks_on_revalidation_without_submitting(client, session_factory):
    action_id = seed_upload_action(client, session_factory)
    # Corrupt the stored payload after approval so the dry-run now fails.
    with session_factory() as session:
        ingest_id = session.get(OutboxAction, action_id).payload["ingest_file_id"]
        # Drop 'passed' and 'results' so the dry-run now reports blocking issues.
        broken = '{"component": "20USE5M0000701", "testType": "MODULE_METROLOGY"}'
        session.execute(
            text("UPDATE ingest_file SET payload = :p WHERE id = :i"),
            {"p": broken, "i": ingest_id},
        )
        session.commit()

    with session_factory() as session:
        stats = process_due_actions(session, never_called)

    assert stats.revalidation_failed == 1
    action = load_action(session_factory, action_id)
    assert action.status == OutboxStatus.FAILED.value
    assert "Dry-run validation failed" in action.error


def test_worker_confirms_already_written_action_without_submitting(client, session_factory):
    # A submitted action carrying an external_ref means the write already
    # happened (crash-after-write); it must be confirmed, never re-sent.
    action_id = seed_upload_action(
        client, session_factory, status=OutboxStatus.SUBMITTED, external_ref="PDB-RUN-7"
    )

    with session_factory() as session:
        stats = process_due_actions(session, never_called)

    assert stats.confirmed == 1
    action = load_action(session_factory, action_id)
    assert action.status == OutboxStatus.CONFIRMED.value
    assert action.external_ref == "PDB-RUN-7"


def test_worker_processes_submitted_retry(client, session_factory):
    # failed → submitted (manual retry) leaves an action `submitted` with no
    # external_ref; the worker picks it up and completes it.
    action_id = seed_upload_action(client, session_factory, status=OutboxStatus.SUBMITTED)

    with session_factory() as session:
        stats = process_due_actions(session, confirming("PDB-RUN-99"))

    assert stats.confirmed == 1
    action = load_action(session_factory, action_id)
    assert action.status == OutboxStatus.CONFIRMED.value
    assert action.external_ref == "PDB-RUN-99"


@pytest.mark.parametrize(
    "status",
    [OutboxStatus.DRAFT, OutboxStatus.VALIDATED, OutboxStatus.CANCELLED, OutboxStatus.CONFIRMED],
)
def test_worker_ignores_non_due_statuses(client, session_factory, status):
    seed_upload_action(client, session_factory, status=status)

    with session_factory() as session:
        stats = process_due_actions(session, never_called)

    assert stats.total == 0


def test_revalidate_flags_missing_ingest_file(client, session_factory):
    action_id = seed_upload_action(client, session_factory)
    with session_factory() as session:
        ingest_id = session.get(OutboxAction, action_id).payload["ingest_file_id"]
        session.execute(text("DELETE FROM ingest_file WHERE id = :i"), {"i": ingest_id})
        session.commit()

    with session_factory() as session:
        issues = revalidate_upload(session, session.get(OutboxAction, action_id))
    assert any("no longer exists" in issue for issue in issues)


def test_phase0_sqlite_schema_patch_adds_external_ref_column(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE outbox_action (
                    id INTEGER PRIMARY KEY,
                    status VARCHAR(16) NOT NULL
                )
                """
            )
        )

    ensure_phase0_sqlite_schema(engine)

    with engine.begin() as connection:
        columns = {row[1] for row in connection.execute(text("PRAGMA table_info(outbox_action)"))}
    assert "external_ref" in columns


def test_run_worker_once_smoke(tmp_path):
    from app.config import Settings

    settings = Settings(database_url=f"sqlite:///{tmp_path / 'worker.db'}", _env_file=None)
    # No due actions and no PDB access: must run cleanly and write nothing.
    worker_main(["--once"], settings=settings)
