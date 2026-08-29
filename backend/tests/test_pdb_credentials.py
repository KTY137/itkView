# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-FileComment: itkflow-c3b7c3eec2f7
"""Offline tests for encrypted, account-owned PDB credentials."""

from datetime import datetime, timezone

import pytest
from pydantic import SecretStr
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.models import PdbCredential, User
from app.pdb_credentials import (
    CredentialDecryptionError,
    CredentialIdentityConflictError,
    CredentialInactiveUserError,
    CredentialKeyInvalidError,
    CredentialKeyMissingError,
    CredentialUserNotFoundError,
    PdbAccessCodes,
    delete_pdb_credentials,
    generate_pdb_credential_encryption_key,
    get_pdb_credential_status,
    load_pdb_credentials,
    save_pdb_credentials,
    update_pdb_credential_status,
)


def _add_user(
    session_factory: sessionmaker[Session],
    email: str,
    *,
    is_active: bool = True,
) -> int:
    with session_factory() as session:
        user = User(
            email=email,
            display_name=email,
            role="operator",
            is_active=is_active,
        )
        session.add(user)
        session.commit()
        return user.id


def test_encrypted_credentials_round_trip_without_secret_repr(session_factory):
    user_id = _add_user(session_factory, "credential-owner@example.org")
    key = generate_pdb_credential_encryption_key()
    codes = PdbAccessCodes(
        access_code1="offline-alpha-access-code",
        access_code2="offline-beta-access-code",
    )

    assert codes.access_code1 not in repr(codes)
    assert codes.access_code2 not in repr(codes)
    assert codes.access_code1 not in str(codes)
    assert codes.access_code2 not in str(codes)

    with session_factory() as session:
        saved = save_pdb_credentials(
            session,
            user_id=user_id,
            access_codes=codes,
            encryption_key=SecretStr(key),
            pdb_identity="pdb-user-001",
            pdb_display_name="Example Operator",
            institutions=["EXAMPLE_LAB"],
        )
        assert saved.encrypted_payload.startswith("v1.")
        assert codes.access_code1 not in saved.encrypted_payload
        assert codes.access_code2 not in saved.encrypted_payload
        session.commit()

    with session_factory() as session:
        assert load_pdb_credentials(
            session,
            user_id=user_id,
            encryption_key=SecretStr(key),
        ) == codes
        status = get_pdb_credential_status(session, user_id=user_id)
        assert status.configured is True
        assert status.status == "verified"
        assert status.pdb_identity == "pdb-user-001"
        assert status.institutions == ("EXAMPLE_LAB",)
        assert status.last_checked_at == status.verified_at
        assert not hasattr(status, "encrypted_payload")
        assert saved.encrypted_payload not in repr(status)


def test_load_rejects_missing_invalid_and_wrong_keys(session_factory):
    user_id = _add_user(session_factory, "key-check@example.org")
    key = generate_pdb_credential_encryption_key()
    with session_factory() as session:
        save_pdb_credentials(
            session,
            user_id=user_id,
            access_codes=PdbAccessCodes("offline-code-a", "offline-code-b"),
            encryption_key=key,
            pdb_identity="pdb-user-key-check",
        )
        session.commit()

    with session_factory() as session:
        with pytest.raises(CredentialKeyMissingError):
            load_pdb_credentials(session, user_id=user_id, encryption_key=None)
        with pytest.raises(CredentialKeyInvalidError):
            load_pdb_credentials(session, user_id=user_id, encryption_key="not-a-key")
        with pytest.raises(CredentialDecryptionError):
            load_pdb_credentials(
                session,
                user_id=user_id,
                encryption_key=generate_pdb_credential_encryption_key(),
            )

    settings = Settings(
        pdb_credential_encryption_key=key,
        database_url="sqlite:///:memory:",
        _env_file=None,
    )
    assert key not in repr(settings)
    assert settings.pdb_credential_encryption_key is not None
    assert settings.pdb_credential_encryption_key.get_secret_value() == key


def test_ciphertext_cannot_be_swapped_between_users(session_factory):
    first_user_id = _add_user(session_factory, "first-owner@example.org")
    second_user_id = _add_user(session_factory, "second-owner@example.org")
    key = generate_pdb_credential_encryption_key()

    with session_factory() as session:
        save_pdb_credentials(
            session,
            user_id=first_user_id,
            access_codes=PdbAccessCodes("first-offline-code", "first-offline-code-2"),
            encryption_key=key,
            pdb_identity="pdb-user-first",
        )
        save_pdb_credentials(
            session,
            user_id=second_user_id,
            access_codes=PdbAccessCodes("second-offline-code", "second-offline-code-2"),
            encryption_key=key,
            pdb_identity="pdb-user-second",
        )
        first = session.get(PdbCredential, first_user_id)
        second = session.get(PdbCredential, second_user_id)
        assert first is not None and second is not None
        first.encrypted_payload, second.encrypted_payload = (
            second.encrypted_payload,
            first.encrypted_payload,
        )
        session.commit()

    with session_factory() as session:
        with pytest.raises(CredentialDecryptionError):
            load_pdb_credentials(session, user_id=first_user_id, encryption_key=key)
        with pytest.raises(CredentialDecryptionError):
            load_pdb_credentials(session, user_id=second_user_id, encryption_key=key)


def test_pdb_identity_is_unique_and_inactive_or_missing_users_are_rejected(session_factory):
    first_user_id = _add_user(session_factory, "identity-owner@example.org")
    second_user_id = _add_user(session_factory, "identity-conflict@example.org")
    inactive_user_id = _add_user(
        session_factory,
        "inactive-owner@example.org",
        is_active=False,
    )
    key = generate_pdb_credential_encryption_key()

    with session_factory() as session:
        save_pdb_credentials(
            session,
            user_id=first_user_id,
            access_codes=PdbAccessCodes("first-code-a", "first-code-b"),
            encryption_key=key,
            pdb_identity="globally-unique-pdb-user",
        )
        session.commit()

    with session_factory() as session:
        with pytest.raises(CredentialIdentityConflictError):
            save_pdb_credentials(
                session,
                user_id=second_user_id,
                access_codes=PdbAccessCodes("second-code-a", "second-code-b"),
                encryption_key=key,
                pdb_identity="globally-unique-pdb-user",
            )
        with pytest.raises(CredentialInactiveUserError):
            load_pdb_credentials(session, user_id=inactive_user_id, encryption_key=key)
        with pytest.raises(CredentialUserNotFoundError):
            load_pdb_credentials(session, user_id=999_999, encryption_key=key)


def test_status_updates_preserve_ciphertext_and_delete_is_idempotent(session_factory):
    user_id = _add_user(session_factory, "status-owner@example.org")
    key = generate_pdb_credential_encryption_key()
    checked_at = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)

    with session_factory() as session:
        assert get_pdb_credential_status(session, user_id=user_id).status == "not_configured"
        save_pdb_credentials(
            session,
            user_id=user_id,
            access_codes=PdbAccessCodes("status-code-a", "status-code-b"),
            encryption_key=key,
            pdb_identity="pdb-user-status",
        )
        credential = session.get(PdbCredential, user_id)
        assert credential is not None
        encrypted_payload = credential.encrypted_payload

        status = update_pdb_credential_status(
            session,
            user_id=user_id,
            status="unreachable",
            checked_at=checked_at,
        )
        assert status.status == "unreachable"
        assert status.last_checked_at == checked_at
        assert credential.encrypted_payload == encrypted_payload

        assert delete_pdb_credentials(session, user_id=user_id) is True
        assert delete_pdb_credentials(session, user_id=user_id) is False
        assert get_pdb_credential_status(session, user_id=user_id).status == "not_configured"
