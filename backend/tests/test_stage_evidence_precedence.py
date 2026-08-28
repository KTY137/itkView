from datetime import datetime, timedelta, timezone

from authutil import create_institute_profile
from sqlalchemy.orm import Session, sessionmaker

from app.models import Component, OutboxAction, TestRunEvidence
from app.outbox import OutboxStatus
from app.stage_service import satisfied_test_results

NOW = datetime(2026, 8, 28, 8, 0, tzinfo=timezone.utc)


def seed_component(session_factory: sessionmaker[Session]) -> tuple[int, int]:
    own = create_institute_profile(
        session_factory, code="OWN", name="Own institute", settings={}
    )
    other = create_institute_profile(
        session_factory, code="OTHER", name="Other institute", settings={}
    )
    with session_factory() as session:
        session.add(
            Component(
                sn="MODULE-1",
                component_type="MODULE",
                type_code="TEST",
                stage="GLUED",
                location="OWN",
                institute_code="OWN",
            )
        )
        session.commit()
    return own["id"], other["id"]


def action(
    institute_id: int,
    *,
    external_ref: str | None,
    passed: object,
    updated_at: datetime = NOW,
    measured_at: datetime | None = None,
) -> OutboxAction:
    payload = {"component_sn": "MODULE-1", "test_type": "TEST", "passed": passed}
    if measured_at is not None:
        payload["measured_at"] = measured_at.isoformat()
    return OutboxAction(
        institute_id=institute_id,
        kind="upload_test_run",
        status=OutboxStatus.CONFIRMED.value,
        created_by="worker",
        external_ref=external_ref,
        payload=payload,
        created_at=updated_at,
        updated_at=updated_at,
    )


def test_only_worker_shaped_same_institute_confirmation_counts_before_mirror(
    session_factory: sessionmaker[Session],
):
    own_id, other_id = seed_component(session_factory)
    with session_factory() as session:
        session.add_all(
            [
                action(own_id, external_ref=None, passed=True),
                action(own_id, external_ref="malformed", passed="false"),
                action(other_id, external_ref="wrong-institute", passed=True),
                action(own_id, external_ref="worker-confirmed", passed=False),
            ]
        )
        session.commit()
        assert satisfied_test_results(session, "MODULE-1") == {"TEST": False}


def test_mirror_lifecycle_and_newer_mirror_result_override_local_confirmation(
    session_factory: sessionmaker[Session],
):
    own_id, _ = seed_component(session_factory)
    with session_factory() as session:
        session.add(action(own_id, external_ref="withdrawn-run", passed=True))
        session.add(
            TestRunEvidence(
                component_sn="MODULE-1",
                test_type="TEST",
                passed=True,
                source="pdb",
                external_ref="withdrawn-run",
                run_state="deleted",
                synced_at=NOW + timedelta(minutes=1),
            )
        )
        session.commit()
        # The mirror owns the exact run's withdrawal; the old local pass must
        # not resurrect it.
        assert satisfied_test_results(session, "MODULE-1") == {}

        session.add(action(own_id, external_ref="older-local-pass", passed=True))
        session.add(
            TestRunEvidence(
                component_sn="MODULE-1",
                test_type="TEST",
                passed=False,
                source="pdb",
                external_ref="newer-pdb-fail",
                run_state="ready",
                measured_at=NOW + timedelta(minutes=2),
                synced_at=NOW + timedelta(minutes=2),
            )
        )
        session.commit()
        assert satisfied_test_results(session, "MODULE-1") == {"TEST": False}


def test_live_mirror_row_owns_an_identical_confirmed_external_reference(
    session_factory: sessionmaker[Session],
):
    own_id, _ = seed_component(session_factory)
    with session_factory() as session:
        session.add(action(own_id, external_ref="same-pdb-run", passed=False))
        session.add(
            TestRunEvidence(
                component_sn="MODULE-1",
                test_type="TEST",
                passed=True,
                source="pdb",
                external_ref="same-pdb-run",
                run_state="ready",
                measured_at=NOW,
                synced_at=NOW + timedelta(minutes=1),
            )
        )
        session.commit()

        assert satisfied_test_results(session, "MODULE-1") == {"TEST": True}


def test_measurement_chronology_beats_later_local_confirmation_time(
    session_factory: sessionmaker[Session],
):
    own_id, _ = seed_component(session_factory)
    with session_factory() as session:
        # This fail was measured later but happened to be mirrored before an
        # operator uploaded an older pass. Confirmation time must not make the
        # older measurement the current run and briefly clear a safety gate.
        session.add(
            TestRunEvidence(
                component_sn="MODULE-1",
                test_type="TEST",
                passed=False,
                source="pdb",
                external_ref="newer-measurement",
                run_state="ready",
                measured_at=NOW + timedelta(minutes=5),
                synced_at=NOW,
            )
        )
        session.add(
            action(
                own_id,
                external_ref="older-local-measurement",
                passed=True,
                measured_at=NOW - timedelta(minutes=5),
                updated_at=NOW + timedelta(minutes=10),
            )
        )
        session.commit()

        assert satisfied_test_results(session, "MODULE-1") == {"TEST": False}


def test_multiple_confirmations_follow_measurement_time_not_confirmation_order(
    session_factory: sessionmaker[Session],
):
    own_id, _ = seed_component(session_factory)
    with session_factory() as session:
        session.add_all(
            [
                action(
                    own_id,
                    external_ref="newer-measured-fail",
                    passed=False,
                    measured_at=NOW + timedelta(minutes=5),
                    updated_at=NOW,
                ),
                action(
                    own_id,
                    external_ref="older-measured-pass",
                    passed=True,
                    measured_at=NOW - timedelta(minutes=5),
                    updated_at=NOW + timedelta(minutes=10),
                ),
            ]
        )
        session.commit()

        assert satisfied_test_results(session, "MODULE-1") == {"TEST": False}


def test_later_undated_mirror_run_supersedes_older_undated_confirmation(
    session_factory: sessionmaker[Session],
):
    own_id, _ = seed_component(session_factory)
    with session_factory() as session:
        session.add(
            action(
                own_id,
                external_ref="older-undated-local-pass",
                passed=True,
                updated_at=NOW,
            )
        )
        session.add(
            TestRunEvidence(
                component_sn="MODULE-1",
                test_type="TEST",
                passed=False,
                source="pdb",
                external_ref="later-undated-mirror-fail",
                measured_at=None,
                synced_at=NOW + timedelta(minutes=1),
            )
        )
        session.commit()

        assert satisfied_test_results(session, "MODULE-1") == {"TEST": False}
