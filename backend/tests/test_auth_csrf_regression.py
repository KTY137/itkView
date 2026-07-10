"""Regression tests for two live CSRF bugs that blocked login (docs/06).

Both only surface with a *pre-existing* session cookie, which the offline suite
never created before — so 233 tests were green while the real app 500'd/403'd:

1. `GET /api/auth/me` crashed (500) when the session predated CSRF tokens and
   carried `csrf_token = NULL` — `whoami` passed None into `MeOut.csrf_token`.
2. `POST /api/auth/login` returned 403 when the browser still held a stale
   session cookie: `csrf_protect` refused to exempt login.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.auth import hash_password
from app.models import User, UserSession


def _make_user(session_factory, email: str, *, role: str = "operator") -> int:
    with session_factory() as s:
        user = User(
            email=email,
            display_name=email,
            role=role,
            is_active=True,
            password_hash=hash_password("pw-12345678"),
        )
        s.add(user)
        s.commit()
        s.refresh(user)
        return user.id


def _add_session(session_factory, *, token: str, user_id: int, csrf_token):
    with session_factory() as s:
        s.add(
            UserSession(
                token=token,
                user_id=user_id,
                csrf_token=csrf_token,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
        )
        s.commit()


def test_me_heals_legacy_session_without_csrf_token(client, session_factory):
    """A session row from before CSRF tokens (csrf_token NULL) must not 500 /me;
    `whoami` mints and persists a token instead."""
    uid = _make_user(session_factory, "legacy@x")
    _add_session(session_factory, token="legacytok", user_id=uid, csrf_token="")

    resp = client.get("/api/auth/me", cookies={"itkflow_session": "legacytok"})
    assert resp.status_code == 200, resp.text
    token = resp.json()["csrf_token"]
    assert isinstance(token, str) and token  # minted, non-empty

    with session_factory() as s:
        healed = s.scalar(select(UserSession).where(UserSession.token == "legacytok"))
        assert healed.csrf_token  # persisted onto the row


def test_login_not_blocked_by_stale_session_cookie(client, session_factory):
    """A leftover session cookie must not make login 403 — login is CSRF-exempt
    (it establishes a fresh session)."""
    uid = _make_user(session_factory, "user@x")
    _add_session(session_factory, token="staletok", user_id=uid, csrf_token="old-token")

    # No X-CSRF-Token header, but a resolvable session cookie is present.
    resp = client.post(
        "/api/auth/login",
        json={"email": "user@x", "password": "pw-12345678"},
        cookies={"itkflow_session": "staletok"},
    )
    assert resp.status_code == 200, resp.text


def test_writes_still_pass_with_a_legacy_null_csrf_session(client, session_factory, tudo):
    """Until /me heals it, a legacy NULL-csrf session should not 403 every write
    (csrf_protect skips the check when the session has no token yet)."""
    uid = _make_user(session_factory, "op@x", role="operator")
    _add_session(session_factory, token="legacyop", user_id=uid, csrf_token="")

    resp = client.post(
        "/api/components/register",
        json={"component_type": "MODULE", "type_code": "R5M0", "institute_code": "TUDO"},
        cookies={"itkflow_session": "legacyop"},
    )
    assert resp.status_code == 201, resp.text
