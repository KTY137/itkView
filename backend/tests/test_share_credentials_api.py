import socket

import pytest
from authutil import authenticate, create_account, login_as
from sqlalchemy import select

from app import attachment_store
from app.models import AuditEvent, ExternalShareCredential
from app.share_credentials import (
    ShareLinkValidationError,
    load_share_passwords,
    public_share_identity,
)

PUBLIC_URL = "https://cernbox.cern.ch/s/abcdefghijklmnop"
PUBLIC_PASSWORD = "share-password-sentinel"


def test_public_share_identity_rejects_nonstandard_https_port():
    with pytest.raises(ShareLinkValidationError, match="standard HTTPS port"):
        public_share_identity("https://cernbox.cern.ch:8443/s/abcdefghijklmnop")

    assert (
        public_share_identity("https://cernbox.cern.ch:443/s/abcdefghijklmnop").share_key
        == public_share_identity(PUBLIC_URL).share_key
    )


def test_share_credentials_require_login(client):
    assert client.get("/api/account/share-credentials").status_code == 401
    assert client.put(
        "/api/account/share-credentials",
        json={"url": PUBLIC_URL, "password": PUBLIC_PASSWORD},
    ).status_code == 401
    assert client.delete("/api/account/share-credentials/1").status_code == 401


def test_share_password_is_encrypted_owner_scoped_and_put_is_network_inert(
    client, session_factory, monkeypatch
):
    me = authenticate(
        client,
        session_factory,
        role="viewer",
        email="share-owner@example.test",
    )
    outbound_attempts = []

    def forbid_outbound(*args, **kwargs):
        outbound_attempts.append((args, kwargs))
        raise AssertionError("saving a public-share password must be network-inert")

    # Guard both itkFlow's outbound downloader seam and Python's common direct
    # socket helper. PUT must only validate the URL shape and write encrypted
    # local data.
    monkeypatch.setattr(attachment_store, "_open_public_url", forbid_outbound)
    monkeypatch.setattr(socket, "create_connection", forbid_outbound)
    response = client.put(
        "/api/account/share-credentials",
        json={"url": PUBLIC_URL, "password": PUBLIC_PASSWORD},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    credential_id = body["id"]
    assert body["provider_host"] == "cernbox.cern.ch"
    assert body["token_hint"] == "...mnop"
    assert PUBLIC_PASSWORD not in response.text
    assert PUBLIC_URL not in response.text
    assert "abcdefghijklmnop" not in response.text
    assert outbound_attempts == []

    listing = client.get("/api/account/share-credentials")
    assert listing.status_code == 200
    assert listing.json() == [body]

    identity = public_share_identity(PUBLIC_URL)
    with session_factory() as session:
        row = session.get(ExternalShareCredential, credential_id)
        assert row is not None
        assert row.user_id == me["id"]
        assert row.share_key == identity.share_key
        assert PUBLIC_PASSWORD not in row.encrypted_password
        resolver = load_share_passwords(
            session,
            user_id=me["id"],
            encryption_key=client.app.state.settings.pdb_credential_encryption_key,
        )
        assert resolver.password_for_url(PUBLIC_URL) == PUBLIC_PASSWORD
        audit_text = " ".join(
            str(event.detail)
            for event in session.scalars(
                select(AuditEvent).where(AuditEvent.user_id == me["id"])
            )
        )
        assert PUBLIC_PASSWORD not in audit_text
        assert "abcdefghijklmnop" not in audit_text

    second_id = create_account(
        session_factory,
        email="share-other@example.test",
        password="other-password",
        role="viewer",
    )
    assert second_id != me["id"]
    login_as(client, "share-other@example.test", "other-password")
    assert client.get("/api/account/share-credentials").json() == []
    assert (
        client.delete(f"/api/account/share-credentials/{credential_id}").status_code
        == 404
    )


def test_share_credential_rejects_private_login_link_without_fetching(
    client, session_factory, monkeypatch
):
    authenticate(client, session_factory, role="viewer")
    outbound_attempts = []

    def forbid_outbound(*args, **kwargs):
        outbound_attempts.append((args, kwargs))
        raise AssertionError("private account links must be rejected before a request")

    monkeypatch.setattr(attachment_store, "_open_public_url", forbid_outbound)
    monkeypatch.setattr(socket, "create_connection", forbid_outbound)
    response = client.put(
        "/api/account/share-credentials",
        json={
            "url": "https://cernbox.cern.ch/apps/files/files/12345",
            "password": PUBLIC_PASSWORD,
        },
    )

    assert response.status_code == 422
    assert "CERN sign-in" in response.json()["detail"]
    assert outbound_attempts == []


def test_share_credential_maps_utf8_byte_limit_to_422_without_partial_save(
    client, session_factory, monkeypatch
):
    me = authenticate(client, session_factory, role="viewer")
    outbound_attempts = []

    def forbid_outbound(*args, **kwargs):
        outbound_attempts.append((args, kwargs))
        raise AssertionError("password validation must not make a network request")

    monkeypatch.setattr(attachment_store, "_open_public_url", forbid_outbound)
    monkeypatch.setattr(socket, "create_connection", forbid_outbound)
    # Pydantic's 1024-character limit accepts this value, but AES-GCM storage
    # deliberately caps the UTF-8 payload at 1024 bytes.
    response = client.put(
        "/api/account/share-credentials",
        json={"url": PUBLIC_URL, "password": "€" * 1024},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "The share password is too long."
    assert outbound_attempts == []
    with session_factory() as session:
        assert session.scalar(
            select(ExternalShareCredential).where(
                ExternalShareCredential.user_id == me["id"]
            )
        ) is None
