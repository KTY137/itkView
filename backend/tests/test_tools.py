"""Tests for the jig/tool registry and type-filtered quick-select (docs/07)."""

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.auth import hash_password
from app.db import make_engine, make_session_factory
from app.models import Tool, User


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


def test_scan_tool_matches_rfid_or_code_case_insensitively(client: TestClient, session_factory):
    add_tool(session_factory, kind="jig", code="HV-TAB-JIG-R5", rfid="E280-AA", compatible_types=[])

    def scan(code: str):
        return client.get("/api/tools/scan", params={"code": code})

    assert scan("e280-aa").json()["code"] == "HV-TAB-JIG-R5"  # by RFID
    assert scan("hv-tab-jig-r5").json()["rfid"] == "E280-AA"  # by printed code
    assert scan("nope").status_code == 404
    assert scan("  ").status_code == 422


def test_create_tool_requires_operator(client: TestClient, session_factory, tudo):
    assert client.post("/api/tools", json={"kind": "jig", "code": "X"}).status_code == 401

    email, password = add_operator(session_factory, tudo["id"])
    client.post("/api/auth/login", json={"email": email, "password": password})
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
    client.post("/api/auth/login", json={"email": email, "password": password})
    resp = client.patch(f"/api/tools/{tool_id}", json={"status": "blacklisted"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "blacklisted"


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
