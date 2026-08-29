# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-FileComment: itkflow-3406dedaefbf
from authutil import authenticate, create_institute_profile

from app.models import Component, IngestFile

TARGET_SN = "20USEM20000111"
OTHER_SN = "20USEM20000222"


def payload(component=TARGET_SN):
    return {
        "component": component,
        "testType": "GENERIC_TEST",
        "runNumber": "1",
        "date": "2026-08-26T10:00:00Z",
        "passed": True,
        "problems": False,
        "properties": {},
        "results": {"VALUE": 1.5},
    }


def mirror_component(session_factory, institute_code="TUDO"):
    with session_factory() as session:
        session.add(
            Component(
                sn=TARGET_SN,
                component_type="MODULE",
                type_code="R5M0",
                stage="GLUED",
                location=institute_code,
                institute_code=institute_code,
                is_dummy=True,
            )
        )
        session.commit()


def test_matching_component_pin_follows_the_normal_dry_run(
    as_operator, session_factory, tudo
):
    mirror_component(session_factory)
    created = as_operator.post(
        "/api/ingest/files",
        json={
            "filename": "manual.json",
            "component_sn": TARGET_SN,
            "payload": payload(),
        },
    )

    assert created.status_code == 201, created.text
    assert created.json()["component_sn"] == TARGET_SN
    preview = as_operator.get(f"/api/ingest/files/{created.json()['id']}/preview").json()
    assert preview["upload_ready"] is True
    assert preview["issues"] == []


def test_mismatching_payload_is_visible_and_cannot_be_staged(
    as_operator, session_factory, tudo
):
    mirror_component(session_factory)
    created = as_operator.post(
        "/api/ingest/files",
        json={
            "filename": "wrong-target.json",
            "component_sn": TARGET_SN,
            "payload": payload(OTHER_SN),
        },
    )

    assert created.status_code == 201, created.text
    body = created.json()
    assert body["component_sn"] == TARGET_SN
    assert body["status"] == "triage"
    assert OTHER_SN in body["error"]
    assert TARGET_SN in body["error"]
    with session_factory() as session:
        stored = session.get(IngestFile, body["id"])
        assert stored is not None
        assert stored.payload["component"] == OTHER_SN

    preview = as_operator.get(f"/api/ingest/files/{body['id']}/preview").json()
    assert preview["component_sn"] == TARGET_SN
    assert preview["upload_ready"] is False
    assert any("does not match pinned component" in issue for issue in preview["issues"])

    proposal = as_operator.post(
        f"/api/ingest/files/{body['id']}/propose-outbox",
        json={},
    )
    assert proposal.status_code == 409


def test_unknown_component_pin_is_rejected(as_operator, tudo):
    response = as_operator.post(
        "/api/ingest/files",
        json={
            "filename": "unknown.json",
            "component_sn": "20USEM29999999",
            "payload": payload(),
        },
    )
    assert response.status_code == 404


def test_manual_entry_marker_is_preserved_in_list_and_preview(
    as_operator, session_factory, tudo
):
    mirror_component(session_factory)
    created = as_operator.post(
        "/api/ingest/files",
        json={
            "filename": "manual-GENERIC_TEST.json",
            "component_sn": TARGET_SN,
            "parser": "manual-entry",
            "payload": payload(),
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["parser"] == "manual-entry"
    preview = as_operator.get(f"/api/ingest/files/{created.json()['id']}/preview")
    assert preview.json()["parser"] == "manual-entry"


def test_blank_pin_is_rejected(as_operator, tudo):
    response = as_operator.post(
        "/api/ingest/files",
        json={"filename": "blank.json", "component_sn": " ", "payload": payload()},
    )
    assert response.status_code == 422


def test_matching_test_type_pin_is_preserved(as_operator, session_factory, tudo):
    mirror_component(session_factory)
    created = as_operator.post(
        "/api/ingest/files",
        json={
            "filename": "reception.json",
            "component_sn": TARGET_SN,
            "test_type": "generic_test",
            "payload": payload(),
        },
    )

    assert created.status_code == 201, created.text
    assert created.json()["test_type"] == "GENERIC_TEST"
    preview = as_operator.get(f"/api/ingest/files/{created.json()['id']}/preview")
    assert preview.json()["upload_ready"] is True


def test_mismatching_test_type_pin_blocks_dry_run_and_staging(
    as_operator,
    session_factory,
    tudo,
):
    mirror_component(session_factory)
    created = as_operator.post(
        "/api/ingest/files",
        json={
            "filename": "wrong-reception-test.json",
            "component_sn": TARGET_SN,
            "test_type": "RECEPTION_IV",
            "payload": payload(),
        },
    )

    assert created.status_code == 201, created.text
    assert created.json()["status"] == "triage"
    assert created.json()["test_type"] == "RECEPTION_IV"
    preview = as_operator.get(f"/api/ingest/files/{created.json()['id']}/preview")
    assert preview.json()["upload_ready"] is False
    assert any(
        "does not match pinned test type" in issue
        for issue in preview.json()["issues"]
    )
    proposed = as_operator.post(
        f"/api/ingest/files/{created.json()['id']}/propose-outbox",
        json={},
    )
    assert proposed.status_code == 409


def test_institute_bound_operator_cannot_ingest_or_stage_foreign_component(
    as_operator, session_factory, tudo
):
    create_institute_profile(
        session_factory,
        code="DESYZ",
        name="DESY Zeuthen",
        local_name_prefix="DESYZ-",
    )
    mirror_component(session_factory, institute_code="DESYZ")

    # A global operator prepares an otherwise valid local ingest row. This
    # locks the proposal endpoint independently from the creation gate below.
    created = as_operator.post(
        "/api/ingest/files",
        json={
            "filename": "foreign.json",
            "component_sn": TARGET_SN,
            "payload": payload(),
        },
    )
    assert created.status_code == 201, created.text

    authenticate(
        as_operator,
        session_factory,
        role="operator",
        institute_id=tudo["id"],
        email="tudo-bound-ingest@example.org",
    )
    proposal = as_operator.post(
        f"/api/ingest/files/{created.json()['id']}/propose-outbox",
        json={},
    )
    assert proposal.status_code == 403

    direct = as_operator.post(
        "/api/ingest/files",
        json={
            "filename": "foreign-direct.json",
            "component_sn": TARGET_SN,
            "payload": payload(),
        },
    )
    assert direct.status_code == 403
