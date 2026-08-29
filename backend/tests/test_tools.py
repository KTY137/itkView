# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-FileComment: itkflow-49fc19f89a22
"""Tests for the jig/tool registry and type-filtered quick-select (docs/07)."""

import pytest
from authutil import login_as
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.auth import hash_password
from app.db import make_engine, make_session_factory
from app.models import AuditEvent, InstituteProfile, Tool, User
from app.pdb_sync import FetchResult
from app.sync import SyncRecord, sync_components
from app.tool_sync import sync_tools_from_components


def add_tool(session_factory: sessionmaker[Session], **kwargs) -> int:
    with session_factory() as session:
        tool = Tool(**kwargs)
        session.add(tool)
        session.commit()
        session.refresh(tool)
        return tool.id


def add_operator(session_factory, institute_id: int) -> tuple[str, str]:
    email, password = "op@tudo.example", "op-password"
    with session_factory() as session:
        session.add(
            User(
                email=email,
                display_name="Op",
                role="operator",
                is_active=True,
                institute_id=institute_id,
                password_hash=hash_password(password),
            )
        )
        session.commit()
    return email, password


def tool_component(
    sn: str = "20USERT0605004",
    *,
    local_name: str | None = "Glue_Stencil_R5H0_5004",
    stage: str = "PRODUCED",
    location: str = "TUDO",
    institute_code: str = "FZU",
) -> SyncRecord:
    return SyncRecord(
        sn=sn,
        component_type="TOOLS",
        type_code="UNKNOWN",
        stage=stage,
        location=location,
        institute_code=institute_code,
        local_name=local_name,
        parent_sn=None,
        is_dummy=False,
        trashed=False,
    )


def test_list_tools_filters_by_kind_and_fitting_type(client: TestClient, session_factory):
    add_tool(session_factory, kind="jig", code="J-R5", compatible_types=["R5M0", "R5M1"])
    add_tool(session_factory, kind="jig", code="J-R2", compatible_types=["R2"])
    add_tool(session_factory, kind="pickup_tool", code="P-R5", compatible_types=["R5M0"])

    jigs = client.get("/api/tools", params={"kind": "jig"}).json()
    assert {t["code"] for t in jigs} == {"J-R5", "J-R2"}

    # The core quick-select behaviour: only tools that fit this module type.
    fits_r2 = client.get("/api/tools", params={"fits": "R2"}).json()
    assert {t["code"] for t in fits_r2} == {"J-R2"}

    jig_for_r5 = client.get("/api/tools", params={"kind": "jig", "fits": "R5M1"}).json()
    assert {t["code"] for t in jig_for_r5} == {"J-R5"}


def test_list_tools_filters_by_status(client: TestClient, session_factory):
    add_tool(session_factory, kind="jig", code="OK", compatible_types=[], status="active")
    add_tool(session_factory, kind="jig", code="BAD", compatible_types=[], status="blacklisted")
    active = client.get("/api/tools", params={"status": "active"}).json()
    assert {t["code"] for t in active} == {"OK"}


def test_tool_by_rfid(client: TestClient, session_factory):
    add_tool(session_factory, kind="jig", code="J", rfid="RFID-123", compatible_types=[])
    assert client.get("/api/tools/by-rfid/RFID-123").json()["code"] == "J"
    assert client.get("/api/tools/by-rfid/UNKNOWN").status_code == 404


def test_scan_tool_matches_rfid_code_or_label_case_insensitively(
    client: TestClient, session_factory
):
    add_tool(
        session_factory,
        kind="jig",
        code="HV-TAB-JIG-R5",
        label="Glue_Stencil_R5H0_5004",
        rfid="E280-AA",
        compatible_types=[],
    )

    def scan(code: str):
        return client.get("/api/tools/scan", params={"code": code})

    assert scan("e280-aa").json()["code"] == "HV-TAB-JIG-R5"  # by RFID
    assert scan("hv-tab-jig-r5").json()["rfid"] == "E280-AA"  # by printed code
    assert scan("glue_stencil_r5h0_5004").json()["code"] == "HV-TAB-JIG-R5"  # label
    assert scan("nope").status_code == 404
    assert scan("  ").status_code == 422


def test_create_tool_requires_operator(client: TestClient, session_factory, tudo):
    assert client.post("/api/tools", json={"kind": "jig", "code": "X"}).status_code == 401

    email, password = add_operator(session_factory, tudo["id"])
    login_as(client, email, password)
    created = client.post(
        "/api/tools",
        json={"kind": "jig", "code": "NEWJIG", "compatible_types": ["R5M0"]},
    )
    assert created.status_code == 201, created.text
    assert created.json()["institute_id"] == tudo["id"]
    assert created.json()["compatible_types"] == ["R5M0"]


def test_update_tool_can_blacklist(client: TestClient, session_factory, tudo):
    tool_id = add_tool(session_factory, kind="jig", code="J", compatible_types=["R2"])
    email, password = add_operator(session_factory, tudo["id"])
    login_as(client, email, password)
    resp = client.patch(f"/api/tools/{tool_id}", json={"status": "blacklisted"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "blacklisted"


def test_tool_create_normalizes_identifiers_and_writes_secret_free_audit(
    client: TestClient, session_factory, tudo
):
    email, password = add_operator(session_factory, tudo["id"])
    login_as(client, email, password)
    created = client.post(
        "/api/tools",
        json={
            "kind": "  Pickup_Tool ",
            "code": "  PICKUP-07 ",
            "label": "  Bench pickup 07 ",
            "rfid": "  RFID-07 ",
            "compatible_types": [" r5m0 ", "R5M0", "r5m1"],
            "status": "active",
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["kind"] == "pickup_tool"
    assert body["code"] == "PICKUP-07"
    assert body["label"] == "Bench pickup 07"
    assert body["rfid"] == "RFID-07"
    assert body["compatible_types"] == ["R5M0", "R5M1"]

    with session_factory() as session:
        event = session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "tool.created",
                AuditEvent.subject == f"tool:{body['id']}",
            )
        )
        assert event.actor == email
        assert event.detail == {
            "institute": "TUDO",
            "kind": "pickup_tool",
            "code": "PICKUP-07",
            "status": "active",
            "compatible_types": ["R5M0", "R5M1"],
        }


def test_tool_patch_edits_every_structured_field_can_clear_optional_values_and_audits_names(
    client: TestClient, session_factory, tudo
):
    tool_id = add_tool(
        session_factory,
        kind="jig",
        code="JIG-OLD",
        label="Old label",
        rfid="OLD-RFID",
        compatible_types=["R2"],
        institute_id=tudo["id"],
        status="active",
    )
    email, password = add_operator(session_factory, tudo["id"])
    login_as(client, email, password)
    response = client.patch(
        f"/api/tools/{tool_id}",
        json={
            "kind": "panel",
            "code": "PANEL-NEW",
            "label": None,
            "rfid": None,
            "compatible_types": ["r5m1"],
            "status": "blacklisted",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json() == {
        **response.json(),
        "kind": "panel",
        "code": "PANEL-NEW",
        "label": None,
        "rfid": None,
        "compatible_types": ["R5M1"],
        "status": "blacklisted",
    }
    with session_factory() as session:
        event = session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "tool.updated",
                AuditEvent.subject == f"tool:{tool_id}",
            )
        )
        assert event.detail == {
            "changed_fields": [
                "code",
                "compatible_types",
                "kind",
                "label",
                "rfid",
                "status",
            ],
            "status": "blacklisted",
        }

    # A no-op save is intentionally not another audit event.
    assert client.patch(f"/api/tools/{tool_id}", json={"status": "blacklisted"}).status_code == 200
    with session_factory() as session:
        events = list(
            session.scalars(
                select(AuditEvent).where(
                    AuditEvent.action == "tool.updated",
                    AuditEvent.subject == f"tool:{tool_id}",
                )
            )
        )
        assert len(events) == 1


def test_tool_patch_rejects_null_compatible_types_instead_of_crashing(
    client: TestClient, session_factory, tudo
):
    tool_id = add_tool(
        session_factory,
        kind="jig",
        code="JIG-LIST",
        compatible_types=["R5M0"],
        institute_id=tudo["id"],
    )
    email, password = add_operator(session_factory, tudo["id"])
    login_as(client, email, password)
    response = client.patch(f"/api/tools/{tool_id}", json={"compatible_types": None})
    assert response.status_code == 422
    assert "must be a list" in response.json()["detail"]


def test_tool_identifiers_are_unique_within_institute(client, session_factory, tudo):
    email, password = add_operator(session_factory, tudo["id"])
    login_as(client, email, password)
    first = client.post(
        "/api/tools",
        json={"kind": "jig", "code": "JIG-UNIQUE", "rfid": "RFID-UNIQUE"},
    )
    assert first.status_code == 201
    assert client.post(
        "/api/tools", json={"kind": "jig", "code": "jig-unique"}
    ).status_code == 409
    assert client.post(
        "/api/tools",
        json={"kind": "jig", "code": "OTHER", "rfid": "rfid-unique"},
    ).status_code == 409


def test_admin_can_delete_tool_and_deletion_is_audited(
    client: TestClient, session_factory, tudo, as_admin
):
    tool_id = add_tool(
        session_factory,
        kind="jig",
        code="REMOVE-ME",
        compatible_types=[],
        institute_id=tudo["id"],
    )
    response = client.delete(f"/api/tools/{tool_id}")
    assert response.status_code == 204
    with session_factory() as session:
        assert session.get(Tool, tool_id) is None
        event = session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "tool.deleted",
                AuditEvent.subject == f"tool:{tool_id}",
            )
        )
        assert event.detail["code"] == "REMOVE-ME"


def test_tool_sync_imports_pdb_tools_from_component_mirror(client, session_factory, tudo):
    with session_factory() as session:
        sync_components(session, [tool_component()])
        institute = session.get(InstituteProfile, tudo["id"])
        stats = sync_tools_from_components(session, institute)
        session.commit()

    assert (stats.created, stats.updated, stats.unchanged, stats.skipped) == (1, 0, 0, 0)
    tools = client.get("/api/tools", params={"kind": "jig", "fits": "R5H0"}).json()
    assert len(tools) == 1
    assert tools[0]["code"] == "20USERT0605004"
    assert tools[0]["label"] == "Glue_Stencil_R5H0_5004"
    assert tools[0]["status"] == "active"
    assert tools[0]["institute_id"] == tudo["id"]


def test_tool_sync_endpoint_uses_existing_mirror(
    client: TestClient, session_factory, tudo, as_operator
):
    with session_factory() as session:
        sync_components(
            session,
            [
                tool_component("20USERT0607040", local_name="Test_Jig_7040"),
                SyncRecord(
                    sn="20USEM00000001",
                    component_type="MODULE",
                    type_code="R5M0",
                    stage="GLUED",
                    location="TUDO",
                    institute_code="TUDO",
                    local_name="TUDO-R5",
                ),
            ],
        )
        session.commit()

    body = client.post("/api/sync/tools/TUDO").json()
    assert body == {
        "institute_code": "TUDO",
        "created": 1,
        "updated": 0,
        "unchanged": 0,
        "skipped": 0,
        "total": 1,
    }
    assert client.get("/api/tools/scan", params={"code": "20USERT0607040"}).json()[
        "kind"
    ] == "jig"


def test_tool_sync_keeps_identical_component_codes_isolated_per_institute(
    client: TestClient, session_factory, tudo
):
    with session_factory() as session:
        fzu = InstituteProfile(code="FZU", name="FZU", local_name_prefix="FZU-")
        session.add(fzu)
        session.flush()
        sync_components(session, [tool_component()])

        tudo_profile = session.get(InstituteProfile, tudo["id"])
        assert tudo_profile is not None
        first = sync_tools_from_components(session, tudo_profile)
        session.commit()
        tudo_tool_id = session.scalar(
            select(Tool.id).where(
                Tool.institute_id == tudo_profile.id,
                Tool.code == "20USERT0605004",
            )
        )

        second = sync_tools_from_components(session, fzu)
        session.commit()
        rows = list(
            session.scalars(
                select(Tool)
                .where(Tool.code == "20USERT0605004")
                .order_by(Tool.institute_id)
            )
        )

    assert first.created == 1
    assert second.created == 1
    assert len(rows) == 2
    assert {row.institute_id for row in rows} == {tudo["id"], fzu.id}
    assert next(row.id for row in rows if row.institute_id == tudo["id"]) == tudo_tool_id

    tudo_rows = client.get("/api/tools", params={"institute": "TUDO"}).json()
    fzu_rows = client.get("/api/tools", params={"institute": "FZU"}).json()
    assert [row["code"] for row in tudo_rows] == ["20USERT0605004"]
    assert [row["code"] for row in fzu_rows] == ["20USERT0605004"]
    assert tudo_rows[0]["id"] != fzu_rows[0]["id"]


def test_tool_schema_rejects_duplicate_code_inside_one_institute(session_factory, tudo):
    with session_factory() as session:
        session.add_all(
            [
                Tool(
                    institute_id=tudo["id"],
                    kind="jig",
                    code="SAME-CODE",
                    compatible_types=[],
                ),
                Tool(
                    institute_id=tudo["id"],
                    kind="panel",
                    code="SAME-CODE",
                    compatible_types=[],
                ),
            ]
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_tool_sync_endpoint_rejects_cross_institute_operator(
    client: TestClient, session_factory, tudo
):
    with session_factory() as session:
        session.add(InstituteProfile(code="FZU", name="FZU", local_name_prefix="FZU-"))
        session.commit()
    email, password = add_operator(session_factory, tudo["id"])
    login_as(client, email, password)

    response = client.post("/api/sync/tools/FZU")
    assert response.status_code == 403
    assert response.json()["detail"] == "You can only modify data for your own institute."


def test_tool_sync_extracts_side_suffixed_r_types(client: TestClient, session_factory, tudo):
    with session_factory() as session:
        sync_components(
            session,
            [tool_component("20USERT0205003", local_name="R2H0S_Module_Jig_01-003")],
        )
        institute = session.get(InstituteProfile, tudo["id"])
        sync_tools_from_components(session, institute)
        session.commit()

    tool = client.get("/api/tools/scan", params={"code": "20USERT0205003"}).json()
    assert tool["compatible_types"] == ["R2H0S"]


def test_component_sync_auto_refreshes_tool_registry(client: TestClient, tudo, as_operator):
    client.app.state.component_fetcher = lambda settings, institute, codes, progress: FetchResult(
        records=[tool_component("20USERT0606117", local_name="Bond_Jig_Large_6117")],
        skipped=0,
    )

    resp = client.post("/api/sync/components/TUDO")
    assert resp.status_code == 200, resp.text
    tools = client.get("/api/tools", params={"kind": "jig"}).json()
    assert {tool["code"] for tool in tools} == {"20USERT0606117"}


def test_tool_sync_preserves_manual_blacklist(client: TestClient, session_factory, tudo):
    add_tool(
        session_factory,
        kind="jig",
        code="20USERT0605004",
        label="old",
        compatible_types=[],
        institute_id=tudo["id"],
        status="blacklisted",
    )
    with session_factory() as session:
        sync_components(session, [tool_component()])
        institute = session.get(InstituteProfile, tudo["id"])
        sync_tools_from_components(session, institute)
        session.commit()

    tool = client.get("/api/tools/scan", params={"code": "20USERT0605004"}).json()
    assert tool["label"] == "Glue_Stencil_R5H0_5004"
    assert tool["compatible_types"] == ["R5H0"]
    assert tool["status"] == "blacklisted"


def test_seed_creates_type_tagged_demo_tools(tmp_path):
    from app.seed_demo import seed

    seed(f"sqlite:///{tmp_path / 'tools.db'}")
    engine = make_engine(f"sqlite:///{tmp_path / 'tools.db'}")
    with make_session_factory(engine)() as session:
        tools = list(session.scalars(select(Tool)))
    assert tools, "seed should create demo tools"
    # Every demo tool is type-tagged, and at least one jig fits an R5 module.
    assert all(isinstance(t.compatible_types, list) for t in tools)
    jigs_for_r5 = [t for t in tools if t.kind == "jig" and "R5M0" in t.compatible_types]
    assert jigs_for_r5
