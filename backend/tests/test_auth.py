"""Tests for local-account auth, sessions and role enforcement (docs/06)."""

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

    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "anna@tudo.example"


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


def test_me_requires_auth(client: TestClient):
    assert client.get("/api/auth/me").status_code == 401


def test_logout_ends_the_session(client: TestClient, session_factory):
    make_user(session_factory, email="a@b.example", password="right-pass", role="viewer")
    client.post("/api/auth/login", json={"email": "a@b.example", "password": "right-pass"})
    assert client.get("/api/auth/me").status_code == 200
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 401


# --------------------------------------------------------------------------
# Role enforcement & user management
# --------------------------------------------------------------------------


def login(client: TestClient, email: str, password: str) -> None:
    resp = client.post("/api/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text


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


def test_auth_endpoints_in_openapi(client: TestClient):
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/auth/login" in paths
    assert "/api/auth/me" in paths
    assert "/api/users" in paths
