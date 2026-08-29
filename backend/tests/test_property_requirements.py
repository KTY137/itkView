# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-FileComment: itkflow-9c8517ed18b1
"""Institute-configured required upload properties, e.g. the used jig (docs/07).

Certain steps (hybrid gluing, metrology) need the jig recorded on the upload or
the PDB rejects it. The required keys per test type live in the institute
profile, so the check is data-driven (hard rule #4) and off by default.
"""

from sqlalchemy import select

from app.ingestion import missing_required_properties
from app.models import Component, IngestFile, InstituteProfile

TEST_TYPE = "MODULE_METROLOGY"


# --- pure resolver ---------------------------------------------------------


def test_missing_required_properties_flags_absent_key():
    settings = {"required_properties": {TEST_TYPE: ["JIG"]}}
    assert missing_required_properties({}, settings, TEST_TYPE) == ["JIG"]
    assert missing_required_properties({"JIG": ""}, settings, TEST_TYPE) == ["JIG"]
    assert missing_required_properties({"JIG": None}, settings, TEST_TYPE) == ["JIG"]


def test_missing_required_properties_ok_when_present():
    settings = {"required_properties": {TEST_TYPE: ["JIG"]}}
    assert missing_required_properties({"JIG": "R5-jig-3"}, settings, TEST_TYPE) == []


def test_missing_required_properties_no_config_is_noop():
    assert missing_required_properties({}, {}, TEST_TYPE) == []
    assert missing_required_properties({}, {"required_properties": {}}, TEST_TYPE) == []
    assert (
        missing_required_properties({}, {"required_properties": {"OTHER": ["X"]}}, TEST_TYPE)
        == []
    )
    assert missing_required_properties({}, "not-a-dict", TEST_TYPE) == []
    assert (
        missing_required_properties({}, {"required_properties": {TEST_TYPE: ["JIG"]}}, None)
        == []
    )


# --- endpoint integration --------------------------------------------------


def _require_jig(session_factory):
    with session_factory() as s:
        profile = s.scalar(select(InstituteProfile).where(InstituteProfile.code == "TUDO"))
        profile.settings = {"required_properties": {TEST_TYPE: ["JIG"]}}
        s.add(
            Component(
                sn="20USE5M0000701",
                component_type="MODULE",
                type_code="R5M0",
                stage="GLUED",
                location="TUDO",
                institute_code="TUDO",
                is_dummy=True,
            )
        )
        s.commit()


def _add_ingest(session_factory, *, properties):
    payload = {
        "component": "20USE5M0000701",
        "testType": TEST_TYPE,
        "passed": True,
        "runNumber": "1",
        "date": "2025-01-01T00:00:00Z",
        "results": {"HEIGHT_MEAN": 0.42},
        "properties": properties,
    }
    with session_factory() as s:
        ingest = IngestFile(
            filename="metro.json",
            sha256="a" * 64,
            size_bytes=10,
            status="received",
            component_sn="20USE5M0000701",
            test_type=TEST_TYPE,
            payload=payload,
            uploaded_by="op@x",
        )
        s.add(ingest)
        s.commit()
        s.refresh(ingest)
        return ingest.id


def test_preview_flags_missing_jig(client, session_factory, tudo):
    _require_jig(session_factory)
    fid = _add_ingest(session_factory, properties={})
    body = client.get(f"/api/ingest/files/{fid}/preview").json()
    assert body["upload_ready"] is False
    assert any("JIG" in issue for issue in body["issues"])


def test_preview_ok_with_jig(client, session_factory, tudo):
    _require_jig(session_factory)
    fid = _add_ingest(session_factory, properties={"JIG": "R5-jig-3"})
    body = client.get(f"/api/ingest/files/{fid}/preview").json()
    assert body["upload_ready"] is True
    assert not any("JIG" in issue for issue in body["issues"])


def test_propose_blocks_without_jig(as_operator, session_factory, tudo):
    _require_jig(session_factory)
    fid = _add_ingest(session_factory, properties={})
    resp = as_operator.post(f"/api/ingest/files/{fid}/propose-outbox", json={})
    assert resp.status_code == 409
    assert "JIG" in resp.text


def test_propose_succeeds_with_jig(as_operator, session_factory, tudo):
    _require_jig(session_factory)
    fid = _add_ingest(session_factory, properties={"JIG": "R5-jig-3"})
    resp = as_operator.post(f"/api/ingest/files/{fid}/propose-outbox", json={})
    assert resp.status_code == 201, resp.text
