"""Server-side attribution, role gating and CSRF on write endpoints (docs/06).

These lock in the three guarantees added on top of the auth foundation:
  * every write is attributed to the signed-in user (`user_id` + a denormalised
    string), taken from the session and never from the request body;
  * the listed writes require operator/admin (401 unauth, 403 wrong role);
  * every state-changing request needs a session-bound CSRF token.
"""

import pytest
from authutil import authenticate, create_account, create_institute_profile, login_as
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.db import ensure_phase0_sqlite_schema, make_engine
from app.models import AuditEvent, IngestFile, OutboxAction

# (method, path, json-body) for each write that must be operator-gated. Bodies
# are valid so the only thing that can reject them is auth/role/CSRF.
GATED_WRITES = [
    ("post", "/api/sync/components/TUDO", None),
    ("post", "/api/sync/jobs/components/TUDO", None),
    ("post", "/api/components/20USEM00000001/sync-evidence", None),
    ("post", "/api/sync/evidence/TUDO", None),
    ("post", "/api/sync/tools/TUDO", None),
    ("post", "/api/outbox", {"institute_code": "TUDO", "kind": "stage_move"}),
    ("post", "/api/outbox/1/transition", {"to": "validated"}),
    ("post", "/api/ingest/files", {"filename": "x.json", "payload": {"data": {}}}),
    ("post", "/api/ingest/files/1/propose-outbox", {}),
    ("post", "/api/test-types/sync?component_type=MODULE", None),
]


def call(client: TestClient, method: str, path: str, body):
    return getattr(client, method)(path, json=body) if body is not None else getattr(
        client, method
    )(path)


# --------------------------------------------------------------------------
# Role gating: 401 unauthenticated, 403 for a viewer
# --------------------------------------------------------------------------


@pytest.mark.parametrize("method, path, body", GATED_WRITES)
def test_gated_write_requires_authentication(client: TestClient, method, path, body):
    assert call(client, method, path, body).status_code == 401


@pytest.mark.parametrize("method, path, body", GATED_WRITES)
def test_gated_write_forbidden_for_viewer(client: TestClient, session_factory, method, path, body):
    authenticate(client, session_factory, role="viewer")  # authenticated + CSRF header
    assert call(client, method, path, body).status_code == 403


# --------------------------------------------------------------------------
# Role gating: an operator is allowed through (200/201)
# --------------------------------------------------------------------------


def test_operator_may_sync_components(client: TestClient, session_factory, tudo, as_operator):
    from app.pdb_sync import FetchResult

    client.app.state.component_fetcher = lambda settings, institute, codes, progress: FetchResult(
        records=[], skipped=0
    )
    assert client.post("/api/sync/components/TUDO").status_code == 200


def test_operator_may_sync_tools(client: TestClient, tudo, as_operator):
    assert client.post("/api/sync/tools/TUDO").status_code == 200


def test_operator_may_create_outbox_and_transition(client: TestClient, tudo, as_operator):
    created = client.post("/api/outbox", json={"institute_code": "TUDO", "kind": "stage_move"})
    assert created.status_code == 201, created.text
    action_id = created.json()["id"]
    moved = client.post(f"/api/outbox/{action_id}/transition", json={"to": "validated"})
    assert moved.status_code == 200, moved.text


def test_institute_bound_operator_cannot_transition_foreign_actions(
    client: TestClient, session_factory, tudo, as_operator
):
    foreign = create_institute_profile(
        session_factory,
        code="DESYZ",
        name="DESY Zeuthen",
        local_name_prefix="DESYZ-",
    )
    transitions = [
        ("draft", "validated"),
        ("draft", "cancelled"),
        ("approved", "submitted"),
        ("failed", "submitted"),
    ]
    action_ids: list[int] = []
    with session_factory() as session:
        institute_id = foreign["id"]
        for status, _target in transitions:
            action = OutboxAction(
                institute_id=institute_id,
                kind="stage_move",
                payload={"sn": "20USEM00009999"},
                status=status,
                created_by="foreign@example.org",
            )
            session.add(action)
            session.flush()
            action_ids.append(action.id)
        session.commit()

    authenticate(
        client,
        session_factory,
        role="operator",
        institute_id=tudo["id"],
        email="bound-transition@example.org",
    )
    for action_id, (status, target) in zip(action_ids, transitions, strict=True):
        response = client.post(
            f"/api/outbox/{action_id}/transition",
            json={"to": target},
        )
        assert response.status_code == 403
        with session_factory() as session:
            assert session.get(OutboxAction, action_id).status == status


def test_operator_may_upload_and_propose(client: TestClient, tudo, as_operator):
    ingest = client.post(
        "/api/ingest/files",
        json={
            "filename": "m.json",
            "payload": {"serialNumber": "20USE5M0000801", "result": {"testType": "X"}},
        },
    )
    assert ingest.status_code == 201, ingest.text
    # Give it enough metadata to be proposable, then propose (both are gated).
    file_id = ingest.json()["id"]
    proposed = client.post(
        f"/api/ingest/files/{file_id}/propose-outbox", json={"institute_code": "TUDO"}
    )
    # 201 when accepted, or a 409 domain rejection — never an auth/role failure.
    assert proposed.status_code in (201, 409), proposed.text


# --------------------------------------------------------------------------
# Sensitive reads: any signed-in role suffices (2026-08-26 security review)
# --------------------------------------------------------------------------
#
# `GET /api/audit` returns actor emails and `GET /api/outbox`/`GET
# /api/outbox/{id}` return staged action payloads to anyone who could reach
# them before this change. Unlike GATED_WRITES these stay open to every
# signed-in role on purpose — the broader read rollout to fully anonymous
# callers remains deliberately open elsewhere and is out of scope here.

GATED_READS = ["/api/audit", "/api/outbox", "/api/outbox/1"]


@pytest.mark.parametrize("path", GATED_READS)
def test_gated_read_requires_authentication(client: TestClient, path):
    assert client.get(path).status_code == 401


def test_gated_reads_allowed_for_a_signed_in_viewer(
    client: TestClient, session_factory, tudo, as_operator
):
    action = client.post(
        "/api/outbox", json={"institute_code": "TUDO", "kind": "stage_move"}
    ).json()

    # Swap the operator session for a plain viewer on the same client: a
    # viewer has no write rights, but these reads must not need more than
    # "signed in".
    authenticate(client, session_factory, role="viewer", email="read-only@auth.example")

    assert client.get("/api/audit").status_code == 200
    assert client.get("/api/outbox").status_code == 200
    detail = client.get(f"/api/outbox/{action['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["id"] == action["id"]


# --------------------------------------------------------------------------
# Server-side attribution: user_id + denormalised string come from the session
# --------------------------------------------------------------------------


def test_outbox_create_attributes_to_session_user_ignoring_body(
    client: TestClient, session_factory, tudo
):
    me = authenticate(
        client, session_factory, role="operator", institute_id=tudo["id"], email="op1@auth.example"
    )
    resp = client.post(
        "/api/outbox",
        json={
            "institute_code": "TUDO",
            "kind": "stage_move",
            # A spoofed author in the body must be ignored.
            "created_by": "attacker@evil.example",
        },
    )
    assert resp.status_code == 201, resp.text
    action = resp.json()
    assert action["created_by"] == "op1@auth.example"
    assert action["user_id"] == me["id"]

    with session_factory() as session:
        stored = session.get(OutboxAction, action["id"])
        assert stored.user_id == me["id"]
        assert stored.created_by == "op1@auth.example"
        event = session.scalar(
            select(AuditEvent).where(AuditEvent.action == "outbox.created")
        )
        assert event.user_id == me["id"]
        assert event.actor == "op1@auth.example"


def test_ingest_upload_attributes_uploaded_by_to_session_user(
    client: TestClient, session_factory
):
    me = authenticate(client, session_factory, role="operator", email="op2@auth.example")
    resp = client.post(
        "/api/ingest/files",
        json={
            "filename": "metrology.json",
            "uploaded_by": "attacker@evil.example",  # ignored
            "payload": {"serialNumber": "20USE5M0000801", "result": {"testType": "X"}},
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["uploaded_by"] == "op2@auth.example"

    with session_factory() as session:
        stored = session.get(IngestFile, resp.json()["id"])
        assert stored.uploaded_by == "op2@auth.example"
        event = session.scalar(
            select(AuditEvent).where(AuditEvent.action == "ingest.received")
        )
        assert event.user_id == me["id"]
        assert event.actor == "op2@auth.example"


# --------------------------------------------------------------------------
# CSRF (double-submit, bound to the session)
# --------------------------------------------------------------------------


def test_csrf_rejects_missing_header(client: TestClient, session_factory, tudo):
    authenticate(client, session_factory, role="operator", institute_id=tudo["id"])
    del client.headers["X-CSRF-Token"]  # a logged-in client that omits the token
    resp = client.post("/api/outbox", json={"institute_code": "TUDO", "kind": "stage_move"})
    assert resp.status_code == 403


def test_csrf_rejects_mismatched_header(client: TestClient, session_factory, tudo):
    authenticate(client, session_factory, role="operator", institute_id=tudo["id"])
    client.headers["X-CSRF-Token"] = "not-the-session-token"
    resp = client.post("/api/outbox", json={"institute_code": "TUDO", "kind": "stage_move"})
    assert resp.status_code == 403


def test_csrf_accepts_matching_header(client: TestClient, session_factory, tudo):
    authenticate(client, session_factory, role="operator", institute_id=tudo["id"])
    resp = client.post("/api/outbox", json={"institute_code": "TUDO", "kind": "stage_move"})
    assert resp.status_code == 201, resp.text


def test_csrf_exempts_safe_methods(client: TestClient, session_factory):
    authenticate(client, session_factory, role="viewer")
    del client.headers["X-CSRF-Token"]  # GET never needs the token
    assert client.get("/api/auth/me").status_code == 200


def test_institute_creation_requires_authentication(client: TestClient):
    resp = client.post("/api/institutes", json={"code": "ABC", "name": "A B C"})
    assert resp.status_code == 401


def test_institute_creation_requires_global_admin(client: TestClient, session_factory, tudo):
    authenticate(client, session_factory, role="viewer", email="tenant-viewer@example.org")
    assert (
        client.post("/api/institutes", json={"code": "VIEW", "name": "Viewer"}).status_code
        == 403
    )

    authenticate(
        client,
        session_factory,
        role="admin",
        institute_id=tudo["id"],
        email="tenant-admin@example.org",
    )
    assert (
        client.post("/api/institutes", json={"code": "BOUND", "name": "Bound"}).status_code
        == 403
    )

    authenticate(client, session_factory, role="admin", email="global-admin@example.org")
    created = client.post("/api/institutes", json={"code": "GLOBAL", "name": "Global"})
    assert created.status_code == 201, created.text


# --------------------------------------------------------------------------
# Secure cookie flag follows the setting
# --------------------------------------------------------------------------


def _set_cookie_headers(response) -> str:
    return "\n".join(v for k, v in response.headers.multi_items() if k.lower() == "set-cookie")


def test_login_cookie_secure_flag_follows_setting():
    from app.config import Settings
    from app.main import create_app

    def login_set_cookies(secure: bool) -> str:
        c = TestClient(
            create_app(
                Settings(
                    database_url="sqlite:///:memory:",
                    session_cookie_secure=secure,
                    _env_file=None,
                )
            )
        )
        create_account(
            c.app.state.session_factory,
            email="secure@auth.example",
            password="secure-pass-123",
            role="viewer",
        )
        resp = c.post(
            "/api/auth/login",
            json={"email": "secure@auth.example", "password": "secure-pass-123"},
        )
        assert resp.status_code == 200, resp.text
        return _set_cookie_headers(resp)

    insecure = login_set_cookies(False)
    assert "itkflow_session=" in insecure
    assert "Secure" not in insecure

    secure = login_set_cookies(True)
    assert "itkflow_session=" in secure
    assert "Secure" in secure


def test_login_helpers_import_smoke():
    # Guard the shared helper surface the rest of the suite relies on.
    assert callable(authenticate) and callable(create_account) and callable(login_as)


# --------------------------------------------------------------------------
# Additive SQLite migration for the attribution/CSRF columns
# --------------------------------------------------------------------------


def test_phase0_patch_adds_attribution_and_csrf_columns(tmp_path):
    """An older dev DB gains user_id (audit_event, outbox_action) and csrf_token
    (user_session) without losing data — additive, like the existing patches."""
    engine = make_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE audit_event (id INTEGER PRIMARY KEY, actor VARCHAR(120))"))
        conn.execute(
            text("CREATE TABLE outbox_action (id INTEGER PRIMARY KEY, status VARCHAR(16))")
        )
        conn.execute(
            text("CREATE TABLE user_session (id INTEGER PRIMARY KEY, token VARCHAR(64))")
        )
        conn.execute(
            text("CREATE TABLE reminder (id INTEGER PRIMARY KEY, active BOOLEAN)")
        )

    ensure_phase0_sqlite_schema(engine)

    with engine.begin() as conn:
        audit_cols = {r[1] for r in conn.execute(text("PRAGMA table_info(audit_event)"))}
        outbox_cols = {r[1] for r in conn.execute(text("PRAGMA table_info(outbox_action)"))}
        session_cols = {r[1] for r in conn.execute(text("PRAGMA table_info(user_session)"))}
        reminder_cols = {r[1] for r in conn.execute(text("PRAGMA table_info(reminder)"))}
    assert "user_id" in audit_cols
    assert "user_id" in outbox_cols
    assert "csrf_token" in session_cols
    assert "deleted_at" in reminder_cols
