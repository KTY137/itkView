# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-FileComment: itkflow-88c1a2f3108e
"""Tests for local-account auth, sessions and role enforcement (docs/06)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.auth import hash_password, verify_password
from app.models import User


def make_user(
    session_factory: sessionmaker[Session],
    *,
    email: str,
    password: str,
    role: str,
    institute_id: int | None = None,
    is_active: bool = True,
) -> int:
    with session_factory() as session:
        user = User(
            email=email.lower(),
            display_name=email,
            role=role,
            is_active=is_active,
            institute_id=institute_id,
            password_hash=hash_password(password),
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        return user.id


# --------------------------------------------------------------------------
# Password hashing (pure)
# --------------------------------------------------------------------------


def test_password_hash_roundtrip():
    stored = hash_password("correct horse battery staple")
    assert stored.startswith("pbkdf2_sha256$")
    assert verify_password("correct horse battery staple", stored) is True
    assert verify_password("wrong", stored) is False
    assert verify_password("correct horse battery staple", None) is False
    assert verify_password("x", "not-a-valid-hash") is False


# --------------------------------------------------------------------------
# Login / me / logout
# --------------------------------------------------------------------------


def test_login_then_me_returns_the_user(client: TestClient, session_factory, tudo):
    make_user(
        session_factory,
        email="anna@tudo.example",
        password="s3cret-pass",
        role="operator",
        institute_id=tudo["id"],
    )
    login = client.post(
        "/api/auth/login", json={"email": "ANNA@tudo.example", "password": "s3cret-pass"}
    )
    assert login.status_code == 200, login.text
    body = login.json()
    assert body["email"] == "anna@tudo.example"
    assert body["role"] == "operator"
    assert body["institute_code"] == "TUDO"
    # Login also issues a CSRF token (readable cookie + body field, docs/06).
    assert body["csrf_token"]
    assert login.cookies.get("itkflow_csrf") == body["csrf_token"]

    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "anna@tudo.example"
    # /me re-issues the same session-bound CSRF token.
    assert me.json()["csrf_token"] == body["csrf_token"]


def test_login_rejects_wrong_password(client: TestClient, session_factory):
    make_user(session_factory, email="a@b.example", password="right-pass", role="viewer")
    resp = client.post("/api/auth/login", json={"email": "a@b.example", "password": "nope-nope"})
    assert resp.status_code == 401


def test_inactive_user_cannot_login(client: TestClient, session_factory):
    make_user(
        session_factory,
        email="gone@b.example",
        password="right-pass",
        role="operator",
        is_active=False,
    )
    resp = client.post(
        "/api/auth/login", json={"email": "gone@b.example", "password": "right-pass"}
    )
    assert resp.status_code == 401


def test_unknown_and_wrong_password_logins_return_the_same_message(
    client: TestClient, session_factory
):
    """A timing side-channel is out of reach for an offline test, but the
    response contract (status + message) must not distinguish the two
    failure modes either (2026-08-26 security review)."""
    make_user(session_factory, email="known@b.example", password="right-pass", role="viewer")
    unknown = client.post(
        "/api/auth/login", json={"email": "nobody@b.example", "password": "whatever"}
    )
    wrong = client.post(
        "/api/auth/login", json={"email": "known@b.example", "password": "wrong-pass"}
    )
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["detail"] == wrong.json()["detail"] == "Invalid email or password."


def test_login_with_unknown_email_still_verifies_a_password(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    """The unknown-email branch must still pay for a full `verify_password`
    call (against a fixed dummy hash) instead of short-circuiting — otherwise
    it would answer measurably faster than a wrong-password attempt and leak
    which emails have accounts (2026-08-26 security review)."""
    from app import api as api_module

    calls: list[tuple[str, str | None]] = []
    original = api_module.verify_password

    def spy(password: str, stored: str | None) -> bool:
        calls.append((password, stored))
        return original(password, stored)

    monkeypatch.setattr(api_module, "verify_password", spy)

    resp = client.post(
        "/api/auth/login", json={"email": "nobody@nowhere.example", "password": "whatever"}
    )
    assert resp.status_code == 401
    assert len(calls) == 1
    password, stored_hash = calls[0]
    assert password == "whatever"
    # A real, pre-computed hash was checked — not None / not skipped.
    assert stored_hash == api_module._dummy_password_hash()
    assert stored_hash is not None


def test_me_requires_auth(client: TestClient):
    assert client.get("/api/auth/me").status_code == 401


def test_logout_ends_the_session(client: TestClient, session_factory):
    make_user(session_factory, email="a@b.example", password="right-pass", role="viewer")
    body = client.post(
        "/api/auth/login", json={"email": "a@b.example", "password": "right-pass"}
    ).json()
    # logout is state-changing, so it needs the CSRF header too.
    client.headers["X-CSRF-Token"] = body["csrf_token"]
    assert client.get("/api/auth/me").status_code == 200
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 401


# --------------------------------------------------------------------------
# Role enforcement & user management
# --------------------------------------------------------------------------


def login(client: TestClient, email: str, password: str) -> None:
    resp = client.post("/api/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    # Later state-changing requests must carry the session's CSRF token.
    client.headers["X-CSRF-Token"] = resp.json()["csrf_token"]


def test_user_management_requires_admin(client: TestClient, session_factory, tudo):
    make_user(
        session_factory,
        email="op@tudo.example",
        password="op-password",
        role="operator",
        institute_id=tudo["id"],
    )
    login(client, "op@tudo.example", "op-password")
    forbidden = client.post(
        "/api/users",
        json={"email": "new@tudo.example", "display_name": "New", "password": "new-password"},
    )
    assert forbidden.status_code == 403
    assert client.get("/api/users").status_code == 403


def test_admin_creates_user_in_own_institute(client: TestClient, session_factory, tudo):
    make_user(
        session_factory,
        email="admin@tudo.example",
        password="admin-password",
        role="admin",
        institute_id=tudo["id"],
    )
    login(client, "admin@tudo.example", "admin-password")
    created = client.post(
        "/api/users",
        json={
            "email": "bruno@tudo.example",
            "display_name": "Bruno",
            "role": "operator",
            "password": "bruno-password",
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["institute_id"] == tudo["id"]
    assert created.json()["role"] == "operator"

    listed = client.get("/api/users").json()
    assert {u["email"] for u in listed} == {"admin@tudo.example", "bruno@tudo.example"}

    # New operator can log in but cannot manage users.
    login(client, "bruno@tudo.example", "bruno-password")
    assert client.get("/api/users").status_code == 403


def test_create_user_rejects_duplicate_email(client: TestClient, session_factory, tudo):
    make_user(
        session_factory,
        email="admin@tudo.example",
        password="admin-password",
        role="admin",
        institute_id=tudo["id"],
    )
    login(client, "admin@tudo.example", "admin-password")
    payload = {"email": "admin@tudo.example", "display_name": "Dup", "password": "some-password"}
    assert client.post("/api/users", json=payload).status_code == 409


# --------------------------------------------------------------------------
# Password reset invalidates existing sessions (2026-08-26 security review)
# --------------------------------------------------------------------------


def test_password_change_invalidates_existing_sessions(client: TestClient, session_factory, tudo):
    make_user(
        session_factory,
        email="admin3@tudo.example",
        password="admin-password",
        role="admin",
        institute_id=tudo["id"],
    )
    login(client, "admin3@tudo.example", "admin-password")
    target_id = client.post(
        "/api/users",
        json={
            "email": "target@tudo.example",
            "display_name": "Target",
            "password": "old-password",
        },
    ).json()["id"]

    # A second, independent client holds the target user's own live session —
    # same app/database (StaticPool in-memory), separate cookie jar.
    target_client = TestClient(client.app)
    assert (
        target_client.post(
            "/api/auth/login",
            json={"email": "target@tudo.example", "password": "old-password"},
        ).status_code
        == 200
    )
    assert target_client.get("/api/auth/me").status_code == 200

    changed = client.patch(f"/api/users/{target_id}", json={"password": "new-password"})
    assert changed.status_code == 200, changed.text

    # The session that predates the reset is dead now...
    assert target_client.get("/api/auth/me").status_code == 401
    # ...but the new password itself works for a fresh login.
    relogin = target_client.post(
        "/api/auth/login",
        json={"email": "target@tudo.example", "password": "new-password"},
    )
    assert relogin.status_code == 200, relogin.text


def test_role_change_without_password_keeps_sessions_alive(
    client: TestClient, session_factory, tudo
):
    make_user(
        session_factory,
        email="admin4@tudo.example",
        password="admin-password",
        role="admin",
        institute_id=tudo["id"],
    )
    login(client, "admin4@tudo.example", "admin-password")
    target_id = client.post(
        "/api/users",
        json={
            "email": "target2@tudo.example",
            "display_name": "Target",
            "password": "same-password",
        },
    ).json()["id"]

    target_client = TestClient(client.app)
    assert (
        target_client.post(
            "/api/auth/login",
            json={"email": "target2@tudo.example", "password": "same-password"},
        ).status_code
        == 200
    )

    changed = client.patch(
        f"/api/users/{target_id}",
        json={"role": "admin", "display_name": "Target Renamed"},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["role"] == "admin"

    # No password field was touched, so the pre-existing session survives.
    still_alive = target_client.get("/api/auth/me")
    assert still_alive.status_code == 200
    assert still_alive.json()["display_name"] == "Target Renamed"


def test_auth_endpoints_in_openapi(client: TestClient):
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/auth/login" in paths
    assert "/api/auth/me" in paths
    assert "/api/users" in paths
