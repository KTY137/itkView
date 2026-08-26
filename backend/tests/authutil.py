"""Shared auth helpers for the offline test suite (docs/06).

Writes are now role-gated and CSRF-protected, so tests that exercise a write
endpoint must sign in first. `authenticate` creates a local account, logs the
client in, and wires the returned CSRF token onto the client's default headers
so every later state-changing request passes the double-submit guard.
"""

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.auth import hash_password
from app.models import InstituteProfile, User


def create_institute_profile(
    session_factory: sessionmaker[Session],
    *,
    code: str,
    name: str,
    local_name_prefix: str = "",
    settings: dict | None = None,
) -> dict:
    """Insert a tenant fixture without depending on the admin-only HTTP API."""
    with session_factory() as session:
        institute = InstituteProfile(
            code=code,
            name=name,
            local_name_prefix=local_name_prefix,
            settings=settings or {},
        )
        session.add(institute)
        session.commit()
        session.refresh(institute)
        return {
            "id": institute.id,
            "code": institute.code,
            "name": institute.name,
            "local_name_prefix": institute.local_name_prefix,
            "settings": institute.settings,
            "created_at": institute.created_at.isoformat(),
        }


def create_account(
    session_factory: sessionmaker[Session],
    *,
    email: str,
    password: str,
    role: str,
    institute_id: int | None = None,
    is_active: bool = True,
    display_name: str | None = None,
) -> int:
    """Insert a local user directly (bypassing the admin-gated /api/users)."""
    with session_factory() as session:
        user = User(
            email=email.lower(),
            display_name=display_name or email,
            role=role,
            is_active=is_active,
            institute_id=institute_id,
            password_hash=hash_password(password),
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        return user.id


def login_as(client: TestClient, email: str, password: str) -> dict:
    """Log in and pin the CSRF token onto the client's default headers."""
    resp = client.post("/api/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    client.headers["X-CSRF-Token"] = body["csrf_token"]
    return body


def authenticate(
    client: TestClient,
    session_factory: sessionmaker[Session],
    *,
    role: str = "operator",
    institute_id: int | None = None,
    email: str | None = None,
    password: str = "test-password-123",
    display_name: str | None = None,
) -> dict:
    """Create (if absent) an account with `role` and sign the client in as them."""
    resolved = (email or f"{role}@auth.example").lower()
    with session_factory() as session:
        exists = session.scalar(select(User).where(User.email == resolved))
        if exists is None:
            session.add(
                User(
                    email=resolved,
                    display_name=display_name or role.title(),
                    role=role,
                    is_active=True,
                    institute_id=institute_id,
                    password_hash=hash_password(password),
                )
            )
            session.commit()
    return login_as(client, resolved, password)
