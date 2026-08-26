"""Personal PDB identity isolation at the real outbox submit boundary."""

from types import SimpleNamespace

import pytest

from app.config import Settings
from app.models import (
    AuditEvent,
    Component,
    InstituteProfile,
    OutboxAction,
    OutboxPdbPrincipal,
    PdbCredential,
    User,
)
from app.outbox import OutboxStatus
from app.outbox_worker import PdbSubmitUnavailable, process_due_actions
from app.pdb_credentials import PdbAccessCodes, save_pdb_credentials
from app.pdb_submit import make_pdb_submitter

GLOBAL_CODES = PdbAccessCodes("GLOBAL-SENTINEL-ONE", "GLOBAL-SENTINEL-TWO")
ALICE_CODES = PdbAccessCodes("ALICE-SENTINEL-ONE", "ALICE-SENTINEL-TWO")
BOB_CODES = PdbAccessCodes("BOB-SENTINEL-ONE", "BOB-SENTINEL-TWO")
ALL_SENTINELS = (
    GLOBAL_CODES.access_code1,
    GLOBAL_CODES.access_code2,
    ALICE_CODES.access_code1,
    ALICE_CODES.access_code2,
    BOB_CODES.access_code1,
    BOB_CODES.access_code2,
)


def _settings(client) -> Settings:
    return Settings(
        itkdb_access_code1=GLOBAL_CODES.access_code1,
        itkdb_access_code2=GLOBAL_CODES.access_code2,
        pdb_credential_encryption_key=(client.app.state.settings.pdb_credential_encryption_key),
        _env_file=None,
    )


def _seed_accounts(session, settings: Settings) -> tuple[User, User, InstituteProfile]:
    institute = InstituteProfile(code="INST", name="Example Institute")
    alice = User(
        email="alice@example.org",
        display_name="Alice",
        role="operator",
        is_active=True,
        institute=institute,
    )
    bob = User(
        email="bob@example.org",
        display_name="Bob",
        role="operator",
        is_active=True,
        institute=institute,
    )
    session.add_all([institute, alice, bob])
    session.flush()
    save_pdb_credentials(
        session,
        user_id=alice.id,
        access_codes=ALICE_CODES,
        pdb_identity="pdb-alice",
        institutions=("INST",),
        encryption_key=settings.pdb_credential_encryption_key,
    )
    save_pdb_credentials(
        session,
        user_id=bob.id,
        access_codes=BOB_CODES,
        pdb_identity="pdb-bob",
        institutions=("INST",),
        encryption_key=settings.pdb_credential_encryption_key,
    )
    return alice, bob, institute


def _seed_dummy(session, *, sn: str = "20UPGM19990001") -> Component:
    component = Component(
        sn=sn,
        component_type="MODULE",
        type_code="R5M0",
        stage="GLUED",
        location="INST",
        institute_code="INST",
        is_dummy=True,
        trashed=False,
    )
    session.add(component)
    session.flush()
    return component


def _stage_action(
    session,
    *,
    institute: InstituteProfile,
    component: Component,
    creator: User,
    principal: User,
) -> OutboxAction:
    action = OutboxAction(
        institute_id=institute.id,
        kind="stage_move",
        payload={"sn": component.sn, "to_stage": "BONDED"},
        status=OutboxStatus.APPROVED.value,
        created_by=creator.email,
        user_id=creator.id,
    )
    session.add(action)
    session.flush()
    credential = session.get(PdbCredential, principal.id)
    session.add(
        OutboxPdbPrincipal(
            outbox_action_id=action.id,
            user_id=principal.id,
            pdb_identity=credential.pdb_identity,
        )
    )
    session.flush()
    return action


def _pairs(values: list[PdbAccessCodes]) -> list[tuple[str, str]]:
    return [(value.access_code1, value.access_code2) for value in values]


def test_service_override_requires_explicit_write_test_opt_in(client):
    with pytest.raises(PdbSubmitUnavailable, match="opted-in PDB write tests"):
        make_pdb_submitter(
            _settings(client),
            service_access_codes=ALICE_CODES,
        )


def test_each_action_uses_only_its_bound_identity(client, session_factory, monkeypatch):
    settings = _settings(client)
    with session_factory() as session:
        alice, bob, institute = _seed_accounts(session, settings)
        component = _seed_dummy(session)
        alice_action = _stage_action(
            session,
            institute=institute,
            component=component,
            creator=bob,
            principal=alice,
        )
        bob_action = _stage_action(
            session,
            institute=institute,
            component=component,
            creator=alice,
            principal=bob,
        )
        session.commit()
        action_ids = (alice_action.id, bob_action.id)

    received_codes: list[PdbAccessCodes] = []

    class _Client:
        def post(self, endpoint, json):
            assert endpoint == "setComponentStage"
            return {"ok": True}

    class _Gateway:
        def __init__(self, configured_settings, *, access_codes=None):
            assert configured_settings is settings
            received_codes.append(access_codes)

        def client(self):
            return _Client()

    monkeypatch.setattr("app.pdb_submit.PdbGateway", _Gateway)
    submitter = make_pdb_submitter(settings)

    with session_factory() as session:
        assert submitter(session, session.get(OutboxAction, action_ids[0])).is_confirmed
        assert submitter(session, session.get(OutboxAction, action_ids[1])).is_confirmed

    assert _pairs(received_codes) == [
        (ALICE_CODES.access_code1, ALICE_CODES.access_code2),
        (BOB_CODES.access_code1, BOB_CODES.access_code2),
    ]
    assert (GLOBAL_CODES.access_code1, GLOBAL_CODES.access_code2) not in _pairs(received_codes)


@pytest.mark.parametrize("failure", ["missing", "identity_mismatch", "not_verified"])
def test_missing_or_changed_principal_fails_closed(
    client,
    session_factory,
    monkeypatch,
    failure,
):
    settings = _settings(client)
    with session_factory() as session:
        alice, bob, institute = _seed_accounts(session, settings)
        component = _seed_dummy(session)
        action = _stage_action(
            session,
            institute=institute,
            component=component,
            creator=bob,
            principal=alice,
        )
        if failure == "missing":
            session.delete(session.get(OutboxPdbPrincipal, action.id))
        elif failure == "identity_mismatch":
            session.get(PdbCredential, alice.id).pdb_identity = "pdb-alice-replaced"
        else:
            session.get(PdbCredential, alice.id).status = "invalid"
        session.commit()
        action_id = action.id

    class _Gateway:
        def __init__(self, *args, **kwargs):
            raise AssertionError("A failed-closed action must not construct a PDB client")

    monkeypatch.setattr("app.pdb_submit.PdbGateway", _Gateway)
    submitter = make_pdb_submitter(settings)
    with session_factory() as session, pytest.raises(PdbSubmitUnavailable) as caught:
        submitter(session, session.get(OutboxAction, action_id))

    message = str(caught.value)
    assert "bound" in message or "personal PDB connection" in message
    assert all(sentinel not in message for sentinel in ALL_SENTINELS)


def test_pdb_rejection_never_copies_upstream_secret_to_outcome(
    client,
    session_factory,
    monkeypatch,
):
    settings = _settings(client)
    with session_factory() as session:
        alice, bob, institute = _seed_accounts(session, settings)
        action = _stage_action(
            session,
            institute=institute,
            component=_seed_dummy(session),
            creator=bob,
            principal=alice,
        )
        session.commit()
        action_id = action.id

    class _LeakyResponseError(Exception):
        def __init__(self):
            super().__init__(f"request body had {ALICE_CODES.access_code1}")
            self.response = SimpleNamespace(status_code=400)

    class _Client:
        def post(self, endpoint, json):
            raise _LeakyResponseError

    class _Gateway:
        def __init__(self, configured_settings, *, access_codes=None):
            pass

        def client(self):
            return _Client()

    monkeypatch.setattr("app.pdb_submit.PdbGateway", _Gateway)
    with session_factory() as session:
        outcome = make_pdb_submitter(settings)(
            session,
            session.get(OutboxAction, action_id),
        )

    assert outcome.rejected_reason == "PDB rejected the stage move."
    assert all(sentinel not in outcome.rejected_reason for sentinel in ALL_SENTINELS)


def test_worker_retry_keeps_same_bound_identity_and_sanitizes_error(
    client,
    session_factory,
    monkeypatch,
):
    settings = _settings(client)
    with session_factory() as session:
        alice, bob, institute = _seed_accounts(session, settings)
        action = OutboxAction(
            institute_id=institute.id,
            kind="register_component",
            payload={
                "component_type": "MODULE",
                "type_code": "R5M0",
                "institute_code": institute.code,
            },
            status=OutboxStatus.APPROVED.value,
            created_by=bob.email,
            user_id=bob.id,
        )
        session.add(action)
        session.flush()
        session.add(
            OutboxPdbPrincipal(
                outbox_action_id=action.id,
                user_id=alice.id,
                pdb_identity="pdb-alice",
            )
        )
        session.commit()
        action_id = action.id
        principal_user_id = alice.id

    received_codes: list[PdbAccessCodes] = []

    class _Client:
        register_attempts = 0

        def get(self, endpoint, json):
            assert endpoint == "listBatches"
            return {"itemList": [{"id": "batch-1"}]}

        def post(self, endpoint, json):
            if endpoint == "registerComponent":
                self.register_attempts += 1
                if self.register_attempts == 1:
                    raise RuntimeError(f"upstream request exposed {ALICE_CODES.access_code1}")
                return {
                    "component": {
                        "serialNumber": "20UPGM19990002",
                        "currentStage": {"code": "RECEPTION"},
                    }
                }
            assert endpoint == "addBatchComponent"
            return {"ok": True}

    pdb_client = _Client()

    class _Gateway:
        def __init__(self, configured_settings, *, access_codes=None):
            received_codes.append(access_codes)

        def client(self):
            return pdb_client

    monkeypatch.setattr("app.pdb_submit.PdbGateway", _Gateway)
    submitter = make_pdb_submitter(settings)

    with session_factory() as session:
        first = process_due_actions(
            session,
            submitter,
            retry_backoff_seconds=0,
        )
    assert first.unavailable == 1
    with session_factory() as session:
        failed = session.get(OutboxAction, action_id)
        principal = session.get(OutboxPdbPrincipal, action_id)
        audit = list(session.query(AuditEvent).filter(AuditEvent.outbox_action_id == action_id))
        persisted_text = failed.error + repr([event.detail for event in audit])
        assert principal.user_id == principal_user_id
        assert all(sentinel not in persisted_text for sentinel in ALL_SENTINELS)

    with session_factory() as session:
        second = process_due_actions(
            session,
            submitter,
            retry_backoff_seconds=0,
        )
    assert second.confirmed == 1
    assert _pairs(received_codes) == [
        (ALICE_CODES.access_code1, ALICE_CODES.access_code2),
        (ALICE_CODES.access_code1, ALICE_CODES.access_code2),
    ]
    assert (BOB_CODES.access_code1, BOB_CODES.access_code2) not in _pairs(received_codes)
    assert (GLOBAL_CODES.access_code1, GLOBAL_CODES.access_code2) not in _pairs(received_codes)

    with session_factory() as session:
        confirmed = session.get(OutboxAction, action_id)
        principal = session.get(OutboxPdbPrincipal, action_id)
        assert confirmed.status == OutboxStatus.CONFIRMED.value
        assert confirmed.external_ref == "20UPGM19990002"
        assert principal.user_id == principal_user_id
