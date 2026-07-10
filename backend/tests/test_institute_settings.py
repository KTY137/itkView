"""Admin editing of institute profile config, incl. required_properties (docs/07).

This is what makes the data-driven features (jig requirements, stage
requirements) configurable in-app instead of only at institute creation.
"""

from authutil import authenticate
from sqlalchemy import select

from app.models import InstituteProfile


def test_update_institute_requires_login(client, tudo):
    assert client.patch("/api/institutes/TUDO", json={"settings": {"x": 1}}).status_code == 401


def test_update_institute_forbidden_for_viewer(as_viewer, tudo):
    assert as_viewer.patch("/api/institutes/TUDO", json={"settings": {"x": 1}}).status_code == 403


def test_update_institute_forbidden_for_operator(as_operator, tudo):
    assert as_operator.patch("/api/institutes/TUDO", json={"settings": {"x": 1}}).status_code == 403


def test_admin_merges_settings(as_admin, session_factory, tudo):
    with session_factory() as s:
        prof = s.scalar(select(InstituteProfile).where(InstituteProfile.code == "TUDO"))
        prof.settings = {"logo_url": "x.png"}
        s.commit()
    resp = as_admin.patch(
        "/api/institutes/TUDO",
        json={"settings": {"required_properties": {"GLUE_WEIGHT": ["JIG"]}}},
    )
    assert resp.status_code == 200, resp.text
    settings = resp.json()["settings"]
    assert settings["logo_url"] == "x.png"  # unrelated config preserved
    assert settings["required_properties"] == {"GLUE_WEIGHT": ["JIG"]}


def test_admin_update_unknown_institute(as_admin):
    assert as_admin.patch("/api/institutes/NOPE", json={"settings": {}}).status_code == 404


def test_per_institute_admin_is_scoped(client, session_factory, tudo):
    with session_factory() as s:
        s.add(InstituteProfile(code="DESYZ", name="DESY Zeuthen"))
        s.commit()
    authenticate(
        client, session_factory, role="admin", institute_id=tudo["id"], email="tudoadmin@x"
    )
    # own institute: allowed
    assert client.patch("/api/institutes/TUDO", json={"name": "TU Dortmund X"}).status_code == 200
    # someone else's: forbidden
    assert client.patch("/api/institutes/DESYZ", json={"name": "nope"}).status_code == 403
