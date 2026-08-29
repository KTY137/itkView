# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-FileComment: itkflow-a68a4c307229
"""First-run setup: create the initial admin from the UI, never the CLI.

The bootstrap endpoint exists so a fresh deployment (desktop bundle or a
server) needs no shell access: while the user table is empty, the frontend
offers a "create the first admin" form; the moment any user exists the
endpoint is permanently closed (docs/06).
"""

from authutil import create_account
from sqlalchemy import select

from app.models import AuditEvent, User


def test_setup_reports_needs_admin_on_empty_database(client):
    response = client.get("/api/setup")
    assert response.status_code == 200, response.text
    assert response.json() == {"needs_admin": True}


def test_setup_reports_no_admin_needed_once_a_user_exists(client, session_factory):
    create_account(
        session_factory, email="viewer@auth.example", password="test-password-123", role="viewer"
    )
    response = client.get("/api/setup")
    assert response.status_code == 200, response.text
    assert response.json() == {"needs_admin": False}


def test_bootstrap_creates_admin_and_signs_in(client, session_factory):
    response = client.post(
        "/api/setup/admin",
        json={
            "email": "First.Admin@example.org",
            "display_name": "First Admin",
            "password": "a-strong-password",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["email"] == "first.admin@example.org"
    assert body["role"] == "admin"
    assert body["csrf_token"]

    # The bootstrap signs the new admin in: /me works without a separate login.
    me = client.get("/api/auth/me")
    assert me.status_code == 200, me.text
    assert me.json()["email"] == "first.admin@example.org"

    # The setup window closes with the very same request cycle.
    assert client.get("/api/setup").json() == {"needs_admin": False}

    with session_factory() as session:
        user = session.scalar(select(User))
        assert user is not None and user.role == "admin" and user.is_active


def test_bootstrap_is_closed_once_any_user_exists(client, session_factory):
    create_account(
        session_factory, email="viewer@auth.example", password="test-password-123", role="viewer"
    )
    response = client.post(
        "/api/setup/admin",
        json={
            "email": "admin@example.org",
            "display_name": "Late Admin",
            "password": "a-strong-password",
        },
    )
    assert response.status_code == 409, response.text
    with session_factory() as session:
        assert session.scalar(select(User).where(User.email == "admin@example.org")) is None


def test_bootstrap_writes_an_audit_event(client, session_factory):
    response = client.post(
        "/api/setup/admin",
        json={
            "email": "admin@example.org",
            "display_name": "First Admin",
            "password": "a-strong-password",
        },
    )
    assert response.status_code == 201, response.text
    with session_factory() as session:
        event = session.scalar(select(AuditEvent).where(AuditEvent.action == "setup.admin_created"))
        assert event is not None
        assert event.actor == "admin@example.org"


def test_bootstrap_rejects_a_too_short_password(client):
    response = client.post(
        "/api/setup/admin",
        json={"email": "admin@example.org", "display_name": "Admin", "password": "short"},
    )
    assert response.status_code == 422, response.text
