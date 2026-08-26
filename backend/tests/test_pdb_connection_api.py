from types import SimpleNamespace

from authutil import authenticate, create_account, login_as
from sqlalchemy import select

from app.models import AuditEvent, OutboxAction, OutboxPdbPrincipal, PdbCredential
from app.pdb_gateway import PdbClientUnavailable


class FakePdbFailure(RuntimeError):
    def __init__(self, status_code: int) -> None:
        super().__init__("sentinel upstream body that must never reach the API")
        self.response = SimpleNamespace(status_code=status_code)


def install_gateway_factory(client, *, identity: str = "u-pdb-1", institutions=()):
    received = []

    class Gateway:
        def __init__(self, codes) -> None:
            self.codes = codes

        def verify_connection(self):
            received.append(self.codes)
            if self.codes.access_code1 == "server-misconfigured":
                raise PdbClientUnavailable("safe local dependency failure")
            if self.codes.access_code1 == "invalid-code":
                raise FakePdbFailure(403)
            if self.codes.access_code1 == "offline-code":
                raise FakePdbFailure(503)
            return {
                "instance": "test",
                "identity": identity,
                "first_name": "Personal",
                "last_name": "User",
                "institutions": list(institutions),
            }

    client.app.state.pdb_gateway_factory = lambda _settings, codes: Gateway(codes)
    return received


def test_connection_status_requires_login_and_starts_empty(client, session_factory):
    assert client.get("/api/account/pdb-connection").status_code == 401
    assert client.put(
        "/api/account/pdb-connection",
        json={"access_code1": "one", "access_code2": "two"},
    ).status_code == 401
    assert client.post("/api/account/pdb-connection/test").status_code == 401
    assert client.delete("/api/account/pdb-connection").status_code == 401

    authenticate(client, session_factory, role="viewer", email="viewer@personal.example")
    response = client.get("/api/account/pdb-connection")

    assert response.status_code == 200
    assert response.json() == {
        "configured": False,
        "state": "not_configured",
        "instance": "test",
        "identity": None,
        "institutions": [],
        "last_checked_at": None,
        "verified_at": None,
    }


def test_connect_verifies_encrypts_and_never_echoes_codes(client, session_factory):
    me = authenticate(client, session_factory, role="viewer", email="one@personal.example")
    received = install_gateway_factory(client, identity="uu-person-one", institutions=("TUDO",))
    secret1 = "access-code-one-sentinel"
    secret2 = "access-code-two-sentinel"

    response = client.put(
        "/api/account/pdb-connection",
        json={"access_code1": secret1, "access_code2": secret2},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["configured"] is True
    assert body["state"] == "verified"
    assert body["identity"] == "uu-person-one"
    assert body["institutions"] == ["TUDO"]
    assert secret1 not in response.text
    assert secret2 not in response.text
    assert received[0].access_code1 == secret1
    assert received[0].access_code2 == secret2

    with session_factory() as session:
        row = session.get(PdbCredential, me["id"])
        assert row is not None
        assert secret1 not in row.encrypted_payload
        assert secret2 not in row.encrypted_payload
        audit_text = " ".join(
            str(event.detail)
            for event in session.scalars(
                select(AuditEvent).where(AuditEvent.user_id == me["id"])
            )
        )
        assert secret1 not in audit_text
        assert secret2 not in audit_text


def test_connection_requires_membership_in_local_institute(client, session_factory, tudo):
    authenticate(
        client,
        session_factory,
        role="operator",
        institute_id=tudo["id"],
        email="scoped@personal.example",
    )
    install_gateway_factory(client, identity="uu-wrong-institute", institutions=("OTHER",))

    response = client.put(
        "/api/account/pdb-connection",
        json={"access_code1": "first", "access_code2": "second"},
    )

    assert response.status_code == 422
    assert "TUDO" in response.json()["detail"]
    assert client.get("/api/account/pdb-connection").json()["configured"] is False


def test_one_pdb_identity_cannot_be_linked_to_two_local_accounts(client, session_factory):
    install_gateway_factory(client, identity="uu-shared")
    first = authenticate(
        client,
        session_factory,
        role="viewer",
        email="first@personal.example",
        password="first-password",
    )
    assert client.put(
        "/api/account/pdb-connection",
        json={"access_code1": "first-a", "access_code2": "first-b"},
    ).status_code == 200
    client.post("/api/auth/logout")

    create_account(
        session_factory,
        email="second@personal.example",
        password="second-password",
        role="viewer",
    )
    login_as(client, "second@personal.example", "second-password")
    response = client.put(
        "/api/account/pdb-connection",
        json={"access_code1": "second-a", "access_code2": "second-b"},
    )

    assert response.status_code == 409
    with session_factory() as session:
        assert session.get(PdbCredential, first["id"]) is not None
        assert len(list(session.scalars(select(PdbCredential)))) == 1


def test_failed_replacement_preserves_the_previous_connection(client, session_factory):
    me = authenticate(client, session_factory, role="viewer", email="replace@personal.example")
    install_gateway_factory(client, identity="uu-original")
    assert client.put(
        "/api/account/pdb-connection",
        json={"access_code1": "original-one", "access_code2": "original-two"},
    ).status_code == 200
    with session_factory() as session:
        before = session.get(PdbCredential, me["id"]).encrypted_payload

    invalid = client.put(
        "/api/account/pdb-connection",
        json={"access_code1": "invalid-code", "access_code2": "replacement"},
    )
    unavailable = client.put(
        "/api/account/pdb-connection",
        json={"access_code1": "offline-code", "access_code2": "replacement"},
    )

    assert invalid.status_code == 422
    assert unavailable.status_code == 503
    assert "sentinel upstream" not in invalid.text
    assert "sentinel upstream" not in unavailable.text
    with session_factory() as session:
        row = session.get(PdbCredential, me["id"])
        assert row.encrypted_payload == before
        assert row.pdb_identity == "uu-original"
        assert row.status == "verified"


def test_local_pdb_client_failure_is_not_reported_as_a_network_outage(
    client, session_factory
):
    authenticate(client, session_factory, role="viewer", email="local-error@personal.example")
    install_gateway_factory(client)

    response = client.put(
        "/api/account/pdb-connection",
        json={"access_code1": "server-misconfigured", "access_code2": "second"},
    )

    assert response.status_code == 500
    assert response.json()["detail"] == (
        "PDB client support is unavailable on this itkFlow server."
    )
    assert "network" not in response.text.lower()


def test_wrapped_auth_rejection_is_still_classified_as_invalid(client, session_factory):
    authenticate(client, session_factory, role="viewer", email="wrapped@personal.example")

    class WrappedAuthFailureGateway:
        def verify_connection(self):
            try:
                raise FakePdbFailure(403)
            except FakePdbFailure as exc:
                raise RuntimeError("safe wrapper") from exc

    client.app.state.pdb_gateway_factory = lambda _settings, _codes: WrappedAuthFailureGateway()
    response = client.put(
        "/api/account/pdb-connection",
        json={"access_code1": "wrapped-invalid", "access_code2": "second"},
    )

    assert response.status_code == 422
    assert "sentinel upstream" not in response.text


def test_saved_connection_test_updates_state_and_disconnects(client, session_factory):
    me = authenticate(client, session_factory, role="viewer", email="test@personal.example")
    install_gateway_factory(client, identity="uu-test")
    assert client.put(
        "/api/account/pdb-connection",
        json={"access_code1": "working-code", "access_code2": "second-code"},
    ).status_code == 200

    install_gateway_factory(client, identity="uu-test")
    assert client.post("/api/account/pdb-connection/test").json()["state"] == "verified"

    response = client.delete("/api/account/pdb-connection")
    assert response.status_code == 204
    assert client.get("/api/account/pdb-connection").json()["state"] == "not_configured"
    assert client.post("/api/account/pdb-connection/test").status_code == 409
    with session_factory() as session:
        assert session.get(PdbCredential, me["id"]) is None


def test_failed_saved_connection_test_persists_safe_status(client, session_factory):
    authenticate(client, session_factory, role="viewer", email="state@personal.example")
    install_gateway_factory(client, identity="uu-state")
    assert client.put(
        "/api/account/pdb-connection",
        json={"access_code1": "working", "access_code2": "working-too"},
    ).status_code == 200

    # The stored codes are still supplied to the fake, which now simulates a
    # transient outage regardless of their value.
    class OfflineGateway:
        def verify_connection(self):
            raise FakePdbFailure(503)

    client.app.state.pdb_gateway_factory = lambda _settings, _codes: OfflineGateway()
    response = client.post("/api/account/pdb-connection/test")

    assert response.status_code == 503
    assert "sentinel upstream" not in response.text
    status = client.get("/api/account/pdb-connection").json()
    assert status["configured"] is True
    assert status["state"] == "unreachable"


def test_approval_binds_the_approvers_personal_pdb_identity(
    client, session_factory, tudo
):
    creator = authenticate(
        client,
        session_factory,
        role="operator",
        email="creator@personal.example",
        password="creator-password",
    )
    created = client.post(
        "/api/outbox",
        json={"institute_code": "TUDO", "kind": "stage_move", "payload": {}},
    ).json()
    assert client.post(
        f"/api/outbox/{created['id']}/transition", json={"to": "validated"}
    ).status_code == 200
    client.post("/api/auth/logout")

    approver_id = create_account(
        session_factory,
        email="approver@personal.example",
        password="approver-password",
        role="operator",
    )
    login_as(client, "approver@personal.example", "approver-password")
    install_gateway_factory(client, identity="uu-approver")
    assert client.put(
        "/api/account/pdb-connection",
        json={"access_code1": "approver-one", "access_code2": "approver-two"},
    ).status_code == 200

    approved = client.post(
        f"/api/outbox/{created['id']}/transition", json={"to": "approved"}
    )

    assert approved.status_code == 200, approved.text
    with session_factory() as session:
        action = session.get(OutboxAction, created["id"])
        principal = session.get(OutboxPdbPrincipal, created["id"])
        assert action.user_id == creator["id"]
        assert principal.user_id == approver_id
        assert principal.pdb_identity == "uu-approver"


def test_approval_without_personal_connection_fails_closed(client, session_factory, tudo):
    authenticate(
        client,
        session_factory,
        role="operator",
        email="unlinked@personal.example",
    )
    action = client.post(
        "/api/outbox",
        json={"institute_code": "TUDO", "kind": "stage_move", "payload": {}},
    ).json()
    assert client.post(
        f"/api/outbox/{action['id']}/transition", json={"to": "validated"}
    ).status_code == 200

    response = client.post(
        f"/api/outbox/{action['id']}/transition", json={"to": "approved"}
    )

    assert response.status_code == 409
    with session_factory() as session:
        assert session.get(OutboxAction, action["id"]).status == "validated"
        assert session.get(OutboxPdbPrincipal, action["id"]) is None
