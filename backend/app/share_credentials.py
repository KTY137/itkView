"""Encrypted, per-user passwords for public file-share links.

Only password-protected *public* ownCloud/Reva links are supported here. A
private browser URL represents an authenticated account session and must go
through a future CERN OAuth client; itkFlow never asks for a CERN account
password. Public share tokens are not duplicated into the credential table:
the stable lookup key is SHA-256(host + token), while the source URL remains in
the read-only evidence mirror that introduced it.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import datetime
from ipaddress import ip_address
from urllib.parse import unquote, urlsplit

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ExternalShareCredential, User, utcnow
from app.pdb_credentials import (
    CredentialKeyInvalidError,
    CredentialKeyMissingError,
    EncryptionKey,
    _decode_encryption_key,
)

_PAYLOAD_VERSION = "v1"
_NONCE_BYTES = 12
_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9._~-]{4,200}$")


class ShareCredentialError(RuntimeError):
    """Base class for safe public-share credential failures."""


class ShareLinkValidationError(ShareCredentialError, ValueError):
    """The supplied URL is not a safe password-capable public share."""


class SharePasswordValidationError(ShareCredentialError, ValueError):
    """A public-share password is empty or implausibly large."""


class ShareCredentialDecryptionError(ShareCredentialError):
    """A stored share password failed authenticated decryption."""


@dataclass(frozen=True, slots=True)
class PublicShareIdentity:
    host: str
    token: str
    share_key: str
    token_hint: str


@dataclass(frozen=True, slots=True)
class ShareCredentialStatus:
    id: int
    provider_host: str
    token_hint: str
    updated_at: datetime


class SharePasswordResolver:
    """Secret-bearing lookup with an always-redacted representation."""

    __slots__ = ("_passwords",)

    def __init__(self, passwords: dict[str, str] | None = None) -> None:
        self._passwords = dict(passwords or {})

    def password_for_url(self, url: str) -> str | None:
        try:
            identity = public_share_identity(url)
        except ShareLinkValidationError:
            return None
        return self._passwords.get(identity.share_key)

    def __repr__(self) -> str:
        return f"SharePasswordResolver(configured={len(self._passwords)}, passwords=<redacted>)"

    __str__ = __repr__


def public_share_identity(url: str) -> PublicShareIdentity:
    """Parse one HTTPS ownCloud/Reva public-share URL without fetching it."""

    if not isinstance(url, str) or not url.strip():
        raise ShareLinkValidationError("A public share URL is required.")
    parsed = urlsplit(url.strip())
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise ShareLinkValidationError("Public share URLs must use HTTPS.")
    if parsed.username is not None or parsed.password is not None:
        raise ShareLinkValidationError("Public share URLs must not contain credentials.")
    try:
        port = parsed.port
    except ValueError:
        raise ShareLinkValidationError("The public share URL has an invalid port.") from None
    if port not in {None, 443}:
        # Password lookup is intentionally keyed by host + token. Limiting
        # credential-bearing shares to the standard HTTPS origin prevents an
        # alternate service on the same host from inheriting that password.
        raise ShareLinkValidationError(
            "Public share URLs must use the standard HTTPS port."
        )
    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith(".localhost"):
        raise ShareLinkValidationError("The public share host is not allowed.")
    try:
        address = ip_address(host)
    except ValueError:
        pass
    else:
        if not address.is_global:
            raise ShareLinkValidationError("The public share host is not allowed.")

    segments = [unquote(segment) for segment in parsed.path.split("/") if segment]
    routed = [segment for segment in segments if segment != "index.php"]
    token: str | None = None
    if tuple(routed[:3]) == ("files", "link", "public") and len(routed) >= 4:
        token = routed[3]
    elif len(routed) >= 2 and routed[0] == "s":
        token = routed[1]
    else:
        for index in range(0, max(0, len(routed) - 3)):
            if tuple(routed[index : index + 3]) == ("remote.php", "dav", "public-files"):
                if len(routed) > index + 3:
                    token = routed[index + 3]
                break
    if token is None or not _TOKEN_PATTERN.fullmatch(token):
        raise ShareLinkValidationError(
            "This is not a password-capable public share link. Private CERNBox "
            "browser links require CERN sign-in."
        )

    share_key = hashlib.sha256(f"{host}\0{token}".encode()).hexdigest()
    hint_tail = token[-4:] if len(token) >= 4 else token
    return PublicShareIdentity(
        host=host,
        token=token,
        share_key=share_key,
        token_hint=f"...{hint_tail}",
    )


def _password_bytes(password: str) -> bytes:
    if not isinstance(password, str) or not password:
        raise SharePasswordValidationError("A share password is required.")
    encoded = password.encode("utf-8")
    if len(encoded) > 1024:
        raise SharePasswordValidationError("The share password is too long.")
    return encoded


def _associated_data(user_id: int, share_key: str) -> bytes:
    if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
        raise SharePasswordValidationError("A positive local user id is required.")
    if not re.fullmatch(r"[0-9a-f]{64}", share_key):
        raise SharePasswordValidationError("The public share identity is invalid.")
    return f"itkflow:share:{_PAYLOAD_VERSION}:user:{user_id}:key:{share_key}".encode("ascii")


def encrypt_share_password(
    password: str,
    encryption_key: EncryptionKey,
    *,
    user_id: int,
    share_key: str,
) -> str:
    key = _decode_encryption_key(encryption_key)
    nonce = secrets.token_bytes(_NONCE_BYTES)
    ciphertext = AESGCM(key).encrypt(
        nonce,
        _password_bytes(password),
        _associated_data(user_id, share_key),
    )
    return (
        f"{_PAYLOAD_VERSION}."
        f"{base64.urlsafe_b64encode(nonce + ciphertext).decode('ascii').rstrip('=')}"
    )


def decrypt_share_password(
    encrypted_password: str,
    encryption_key: EncryptionKey,
    *,
    user_id: int,
    share_key: str,
) -> str:
    key = _decode_encryption_key(encryption_key)
    try:
        version, token = encrypted_password.split(".", maxsplit=1)
        if version != _PAYLOAD_VERSION or not token:
            raise ValueError
        combined = base64.b64decode(
            token + "=" * (-len(token) % 4), altchars=b"-_", validate=True
        )
        if len(combined) <= _NONCE_BYTES:
            raise ValueError
        plaintext = AESGCM(key).decrypt(
            combined[:_NONCE_BYTES],
            combined[_NONCE_BYTES:],
            _associated_data(user_id, share_key),
        )
        return plaintext.decode("utf-8")
    except (
        AttributeError,
        binascii.Error,
        InvalidTag,
        TypeError,
        UnicodeError,
        ValueError,
    ) as exc:
        raise ShareCredentialDecryptionError(
            "A saved public-share password could not be decrypted."
        ) from exc


def save_share_password(
    session: Session,
    *,
    user_id: int,
    url: str,
    password: str,
    encryption_key: EncryptionKey,
) -> ExternalShareCredential:
    user = session.get(User, user_id)
    if user is None or not user.is_active:
        raise SharePasswordValidationError(
            "Only an active signed-in user can save a share password."
        )
    identity = public_share_identity(url)
    encrypted = encrypt_share_password(
        password,
        encryption_key,
        user_id=user_id,
        share_key=identity.share_key,
    )
    row = session.scalar(
        select(ExternalShareCredential).where(
            ExternalShareCredential.user_id == user_id,
            ExternalShareCredential.share_key == identity.share_key,
        )
    )
    now = utcnow()
    if row is None:
        row = ExternalShareCredential(
            user_id=user_id,
            share_key=identity.share_key,
            provider_host=identity.host,
            token_hint=identity.token_hint,
            encrypted_password=encrypted,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
    else:
        row.provider_host = identity.host
        row.token_hint = identity.token_hint
        row.encrypted_password = encrypted
        row.updated_at = now
    session.flush()
    return row


def list_share_credentials(session: Session, *, user_id: int) -> list[ShareCredentialStatus]:
    rows = session.scalars(
        select(ExternalShareCredential)
        .where(ExternalShareCredential.user_id == user_id)
        .order_by(ExternalShareCredential.provider_host, ExternalShareCredential.id)
    )
    return [
        ShareCredentialStatus(
            id=row.id,
            provider_host=row.provider_host,
            token_hint=row.token_hint,
            updated_at=row.updated_at,
        )
        for row in rows
    ]


def delete_share_credential(session: Session, *, user_id: int, credential_id: int) -> bool:
    row = session.get(ExternalShareCredential, credential_id)
    if row is None or row.user_id != user_id:
        return False
    session.delete(row)
    session.flush()
    return True


def load_share_passwords(
    session: Session,
    *,
    user_id: int,
    encryption_key: EncryptionKey,
) -> SharePasswordResolver:
    passwords: dict[str, str] = {}
    rows = session.scalars(
        select(ExternalShareCredential).where(ExternalShareCredential.user_id == user_id)
    )
    for row in rows:
        try:
            passwords[row.share_key] = decrypt_share_password(
                row.encrypted_password,
                encryption_key,
                user_id=user_id,
                share_key=row.share_key,
            )
        except ShareCredentialDecryptionError:
            # One damaged optional share credential must not block the PDB
            # evidence mirror. Its share will be reported as authentication-
            # required, and replacing it in Account settings repairs the row.
            continue
    return SharePasswordResolver(passwords)


__all__ = [
    "CredentialKeyInvalidError",
    "CredentialKeyMissingError",
    "PublicShareIdentity",
    "ShareCredentialDecryptionError",
    "ShareCredentialStatus",
    "ShareLinkValidationError",
    "SharePasswordResolver",
    "SharePasswordValidationError",
    "delete_share_credential",
    "decrypt_share_password",
    "encrypt_share_password",
    "list_share_credentials",
    "load_share_passwords",
    "public_share_identity",
    "save_share_password",
]
