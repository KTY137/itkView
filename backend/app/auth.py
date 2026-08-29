# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-FileComment: itkflow-eee38d4fd1c7
"""Authentication primitives — pure, no DB or web framework.

Local accounts for v1 (see docs/06-users-roles-audit.md): password hashing with
the standard library (PBKDF2-HMAC-SHA256, no extra dependency), opaque session
tokens, and the role vocabulary. An OIDC/SSO adapter can later establish the
same `User` identity without touching this module's callers.
"""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

# Roles, from least to most privileged. `admin` manages the institute profile
# and users; `operator` performs production writes; `viewer` is read-only.
ROLES = ("viewer", "operator", "admin")

SESSION_COOKIE = "itkflow_session"
VIEW_SESSION_COOKIE = "itkview_session"
# Readable (non-httpOnly) cookie carrying the CSRF token for the double-submit
# guard; the frontend echoes it back in the X-CSRF-Token header (docs/06).
CSRF_COOKIE = "itkflow_csrf"
VIEW_CSRF_COOKIE = "itkview_csrf"
CSRF_HEADER = "X-CSRF-Token"
SESSION_TTL = timedelta(hours=12)

_PBKDF2_ROUNDS = 200_000
_ALGO = "pbkdf2_sha256"


def session_cookie_name(product_variant: str) -> str:
    """Return the isolated session-cookie namespace for one product."""

    return VIEW_SESSION_COOKIE if product_variant == "view" else SESSION_COOKIE


def csrf_cookie_name(product_variant: str) -> str:
    """Return the isolated CSRF-cookie namespace for one product."""

    return VIEW_CSRF_COOKIE if product_variant == "view" else CSRF_COOKIE


def hash_password(password: str) -> str:
    """Return a self-describing hash: `pbkdf2_sha256$rounds$salt$hash` (hex)."""
    if not password:
        raise ValueError("Password must not be empty.")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ROUNDS)
    return f"{_ALGO}${_PBKDF2_ROUNDS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    """Constant-time verify against a `hash_password` string. False if no hash."""
    if not stored:
        return False
    try:
        algo, rounds_s, salt_hex, digest_hex = stored.split("$")
        if algo != _ALGO:
            return False
        rounds = int(rounds_s)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except (ValueError, AttributeError):
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
    return hmac.compare_digest(candidate, expected)


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def new_csrf_token() -> str:
    """A fresh, unguessable CSRF token, bound to the session at login."""
    return secrets.token_urlsafe(32)


def session_expiry(now: datetime | None = None) -> datetime:
    return (now or datetime.now(timezone.utc)) + SESSION_TTL
