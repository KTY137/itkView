"""Encrypted per-user PDB credentials.

Access codes are encrypted with AES-256-GCM before they reach the database.
The authenticated associated data includes the owning local user id, so moving
an encrypted payload to another credential row makes decryption fail. This
module deliberately contains no logging of keys, plaintext codes, or payloads.

The mutation helpers flush but do not commit; transaction ownership stays with
the API request or worker that called them.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import secrets
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PdbCredential, User, utcnow

_PAYLOAD_VERSION = "v1"
_NONCE_BYTES = 12
_KEY_BYTES = 32
_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_-]+={0,2}$")

PdbCredentialStoredStatus = Literal["verified", "invalid", "unreachable"]
PdbCredentialStatusValue = Literal[
    "not_configured", "verified", "invalid", "unreachable"
]
PDB_CREDENTIAL_STORED_STATUSES = frozenset({"verified", "invalid", "unreachable"})

EncryptionKey = SecretStr | str | bytes | None


class PdbCredentialError(RuntimeError):
    """Base class for safe, user-credential-specific failures."""


class CredentialValidationError(PdbCredentialError, ValueError):
    """Credential metadata or access-code input is malformed."""


class CredentialKeyMissingError(PdbCredentialError):
    """The server-side credential encryption key is not configured."""


class CredentialKeyInvalidError(PdbCredentialError):
    """The configured credential encryption key has an invalid format."""


class CredentialEncryptionError(PdbCredentialError):
    """Plaintext access codes could not be encrypted."""


class CredentialDecryptionError(PdbCredentialError):
    """A stored payload failed authentication or decoding."""


class CredentialNotFoundError(PdbCredentialError):
    """The requested user has no stored PDB credentials."""


class CredentialUserNotFoundError(PdbCredentialError):
    """The local owner account does not exist."""


class CredentialInactiveUserError(PdbCredentialError):
    """Inactive local accounts cannot use or manage PDB credentials."""


class CredentialIdentityConflictError(PdbCredentialError):
    """The PDB identity is already owned by another local account."""


# Explicit PDB-prefixed aliases keep call sites self-documenting while the
# shorter canonical names remain convenient in focused exception handlers.
PdbCredentialValidationError = CredentialValidationError
PdbCredentialKeyMissingError = CredentialKeyMissingError
PdbCredentialKeyInvalidError = CredentialKeyInvalidError
PdbCredentialEncryptionError = CredentialEncryptionError
PdbCredentialDecryptionError = CredentialDecryptionError
PdbCredentialNotFoundError = CredentialNotFoundError
PdbCredentialUserNotFoundError = CredentialUserNotFoundError
PdbCredentialInactiveUserError = CredentialInactiveUserError
PdbCredentialIdentityConflictError = CredentialIdentityConflictError


@dataclass(frozen=True, slots=True, repr=False)
class PdbAccessCodes:
    """The two PDB access codes, with a representation that always redacts."""

    access_code1: str
    access_code2: str

    def __post_init__(self) -> None:
        if not isinstance(self.access_code1, str) or not self.access_code1:
            raise CredentialValidationError("Both PDB access codes must be non-empty strings.")
        if not isinstance(self.access_code2, str) or not self.access_code2:
            raise CredentialValidationError("Both PDB access codes must be non-empty strings.")

    def __repr__(self) -> str:
        return "PdbAccessCodes(access_code1=<redacted>, access_code2=<redacted>)"

    __str__ = __repr__


@dataclass(frozen=True, slots=True)
class PdbCredentialStatus:
    """Secret-free account connection status for API/UI consumers."""

    configured: bool
    status: PdbCredentialStatusValue
    pdb_identity: str | None = None
    pdb_display_name: str | None = None
    institutions: tuple[str, ...] = ()
    verified_at: datetime | None = None
    last_checked_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


def generate_pdb_credential_encryption_key() -> str:
    """Return a new URL-safe base64-encoded 256-bit master key."""
    return base64.urlsafe_b64encode(AESGCM.generate_key(bit_length=256)).decode("ascii")


def _decode_encryption_key(encryption_key: EncryptionKey) -> bytes:
    if isinstance(encryption_key, SecretStr):
        value: str | bytes | None = encryption_key.get_secret_value()
    else:
        value = encryption_key

    if value is None:
        raise CredentialKeyMissingError("PDB credential encryption is not configured.")
    if isinstance(value, bytes):
        try:
            encoded = value.decode("ascii")
        except UnicodeDecodeError as exc:
            raise CredentialKeyInvalidError(
                "The PDB credential encryption key must be URL-safe base64."
            ) from exc
    elif isinstance(value, str):
        encoded = value
    else:
        raise CredentialKeyInvalidError(
            "The PDB credential encryption key must be URL-safe base64."
        )

    encoded = encoded.strip()
    if not encoded:
        raise CredentialKeyMissingError("PDB credential encryption is not configured.")
    if not _KEY_PATTERN.fullmatch(encoded):
        raise CredentialKeyInvalidError(
            "The PDB credential encryption key must be URL-safe base64."
        )

    padded = encoded + "=" * (-len(encoded) % 4)
    try:
        key = base64.b64decode(padded, altchars=b"-_", validate=True)
    except (binascii.Error, ValueError) as exc:
        raise CredentialKeyInvalidError(
            "The PDB credential encryption key must be URL-safe base64."
        ) from exc
    if len(key) != _KEY_BYTES:
        raise CredentialKeyInvalidError(
            "The PDB credential encryption key must encode exactly 32 bytes."
        )
    return key


def _validate_user_id(user_id: int) -> int:
    if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
        raise CredentialValidationError("A positive local user id is required.")
    return user_id


def _associated_data(user_id: int) -> bytes:
    valid_user_id = _validate_user_id(user_id)
    return f"itkflow:pdb:{_PAYLOAD_VERSION}:user:{valid_user_id}".encode("ascii")


def encrypt_access_codes(
    access_codes: PdbAccessCodes,
    encryption_key: EncryptionKey = None,
    *,
    user_id: int,
) -> str:
    """Encrypt codes into a versioned payload authenticated for ``user_id``."""
    if not isinstance(access_codes, PdbAccessCodes):
        raise CredentialValidationError("PDB access codes must be a PdbAccessCodes value.")

    key = _decode_encryption_key(encryption_key)
    plaintext = json.dumps(
        {
            "access_code1": access_codes.access_code1,
            "access_code2": access_codes.access_code2,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    nonce = secrets.token_bytes(_NONCE_BYTES)
    try:
        ciphertext = AESGCM(key).encrypt(nonce, plaintext, _associated_data(user_id))
    except (OverflowError, ValueError) as exc:
        raise CredentialEncryptionError("PDB access codes could not be encrypted.") from exc

    token = base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii").rstrip("=")
    return f"{_PAYLOAD_VERSION}.{token}"


def decrypt_access_codes(
    encrypted_payload: str,
    encryption_key: EncryptionKey = None,
    *,
    user_id: int,
) -> PdbAccessCodes:
    """Authenticate and decrypt a versioned payload for its owning ``user_id``."""
    key = _decode_encryption_key(encryption_key)
    generic_error = "Stored PDB credentials could not be decrypted."

    try:
        version, token = encrypted_payload.split(".", maxsplit=1)
        if version != _PAYLOAD_VERSION or not token:
            raise ValueError
        padded = token + "=" * (-len(token) % 4)
        combined = base64.b64decode(padded, altchars=b"-_", validate=True)
        if len(combined) <= _NONCE_BYTES:
            raise ValueError
        nonce = combined[:_NONCE_BYTES]
        ciphertext = combined[_NONCE_BYTES:]
        plaintext = AESGCM(key).decrypt(nonce, ciphertext, _associated_data(user_id))
        decoded = json.loads(plaintext.decode("utf-8"))
        if not isinstance(decoded, dict):
            raise ValueError
        return PdbAccessCodes(
            access_code1=decoded["access_code1"],
            access_code2=decoded["access_code2"],
        )
    except (
        AttributeError,
        binascii.Error,
        InvalidTag,
        KeyError,
        TypeError,
        UnicodeError,
        ValueError,
    ) as exc:
        raise CredentialDecryptionError(generic_error) from exc


def _require_active_user(session: Session, user_id: int) -> User:
    valid_user_id = _validate_user_id(user_id)
    user = session.get(User, valid_user_id)
    if user is None:
        raise CredentialUserNotFoundError("The local credential owner does not exist.")
    if not user.is_active:
        raise CredentialInactiveUserError(
            "Inactive local accounts cannot use or manage PDB credentials."
        )
    return user


def _normalise_identity(pdb_identity: str) -> str:
    if not isinstance(pdb_identity, str) or not pdb_identity.strip():
        raise CredentialValidationError("A non-empty PDB identity is required.")
    return pdb_identity.strip()


def _normalise_institutions(institutions: Sequence[str] | None) -> list[str]:
    if institutions is None:
        return []
    if isinstance(institutions, (str, bytes)):
        raise CredentialValidationError("PDB institutions must be a sequence of strings.")
    result = list(institutions)
    if any(not isinstance(institution, str) or not institution for institution in result):
        raise CredentialValidationError("PDB institutions must be non-empty strings.")
    return result


def save_pdb_credentials(
    session: Session,
    *,
    user_id: int,
    access_codes: PdbAccessCodes,
    pdb_identity: str,
    encryption_key: EncryptionKey = None,
    pdb_display_name: str | None = None,
    institutions: Sequence[str] | None = (),
    verified_at: datetime | None = None,
) -> PdbCredential:
    """Create or replace one active user's encrypted PDB credentials."""
    _require_active_user(session, user_id)
    identity = _normalise_identity(pdb_identity)
    institution_list = _normalise_institutions(institutions)

    existing_owner = session.scalar(
        select(PdbCredential.user_id).where(
            PdbCredential.pdb_identity == identity,
            PdbCredential.user_id != user_id,
        )
    )
    if existing_owner is not None:
        raise CredentialIdentityConflictError(
            "This PDB identity is already linked to another local account."
        )

    checked_at = verified_at or utcnow()
    encrypted_payload = encrypt_access_codes(
        access_codes,
        encryption_key,
        user_id=user_id,
    )
    credential = session.get(PdbCredential, user_id)
    if credential is None:
        credential = PdbCredential(
            user_id=user_id,
            encrypted_payload=encrypted_payload,
            pdb_identity=identity,
            pdb_display_name=pdb_display_name,
            institutions=institution_list,
            status="verified",
            verified_at=checked_at,
            last_checked_at=checked_at,
            created_at=checked_at,
            updated_at=checked_at,
        )
        session.add(credential)
    else:
        credential.encrypted_payload = encrypted_payload
        credential.pdb_identity = identity
        credential.pdb_display_name = pdb_display_name
        credential.institutions = institution_list
        credential.status = "verified"
        credential.verified_at = checked_at
        credential.last_checked_at = checked_at
        credential.updated_at = checked_at
    session.flush()
    return credential


def load_pdb_credentials(
    session: Session,
    *,
    user_id: int,
    encryption_key: EncryptionKey = None,
) -> PdbAccessCodes:
    """Load one active user's codes, authenticating both key and row owner."""
    _require_active_user(session, user_id)
    credential = session.get(PdbCredential, user_id)
    if credential is None:
        raise CredentialNotFoundError("No PDB credentials are configured for this account.")
    return decrypt_access_codes(
        credential.encrypted_payload,
        encryption_key,
        user_id=user_id,
    )


def delete_pdb_credentials(session: Session, *, user_id: int) -> bool:
    """Delete one active user's stored credentials; return whether they existed."""
    _require_active_user(session, user_id)
    credential = session.get(PdbCredential, user_id)
    if credential is None:
        return False
    session.delete(credential)
    session.flush()
    return True


def _status_from_credential(credential: PdbCredential) -> PdbCredentialStatus:
    stored_status = credential.status
    if stored_status not in PDB_CREDENTIAL_STORED_STATUSES:
        # A corrupt database value must not silently become an API contract.
        raise CredentialValidationError("Stored PDB credential status is invalid.")
    return PdbCredentialStatus(
        configured=True,
        status=stored_status,  # type: ignore[arg-type]
        pdb_identity=credential.pdb_identity,
        pdb_display_name=credential.pdb_display_name,
        institutions=tuple(credential.institutions or ()),
        verified_at=credential.verified_at,
        last_checked_at=credential.last_checked_at,
        created_at=credential.created_at,
        updated_at=credential.updated_at,
    )


def get_pdb_credential_status(session: Session, *, user_id: int) -> PdbCredentialStatus:
    """Return connection metadata without ever exposing encrypted payload data."""
    _require_active_user(session, user_id)
    credential = session.get(PdbCredential, user_id)
    if credential is None:
        return PdbCredentialStatus(configured=False, status="not_configured")
    return _status_from_credential(credential)


def update_pdb_credential_status(
    session: Session,
    *,
    user_id: int,
    status: PdbCredentialStoredStatus,
    checked_at: datetime | None = None,
) -> PdbCredentialStatus:
    """Record a credential check while preserving the encrypted access codes."""
    _require_active_user(session, user_id)
    if status not in PDB_CREDENTIAL_STORED_STATUSES:
        raise CredentialValidationError("PDB credential status is invalid.")
    credential = session.get(PdbCredential, user_id)
    if credential is None:
        raise CredentialNotFoundError("No PDB credentials are configured for this account.")

    now = checked_at or utcnow()
    credential.status = status
    credential.last_checked_at = now
    if status == "verified":
        credential.verified_at = now
    credential.updated_at = now
    session.flush()
    return _status_from_credential(credential)


set_pdb_credential_status = update_pdb_credential_status
