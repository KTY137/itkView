# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-FileComment: itkflow-d169209d4fc7
"""DUMMY component-registration draft endpoint + worker revalidation (docs/10).

The registration endpoint only ever creates a reviewed outbox draft; the actual
PDB write happens later in the worker and is doubly guarded (registrable type +
dummy scope). These tests stay offline and never touch a PDB.
"""

from app.models import OutboxAction
from app.outbox_worker import revalidate_register

REGISTER = "/api/components/register"
MODULE = {"component_type": "MODULE", "type_code": "R5M0", "institute_code": "TUDO"}


def test_register_requires_login(client, tudo):
    assert client.post(REGISTER, json=MODULE).status_code == 401


def test_register_forbidden_for_viewer(as_viewer, tudo):
    assert as_viewer.post(REGISTER, json=MODULE).status_code == 403


def test_register_rejects_sensor(as_operator, tudo):
    resp = as_operator.post(
        REGISTER,
        json={"component_type": "SENSOR", "type_code": "ATLAS18R5", "institute_code": "TUDO"},
    )
    assert resp.status_code == 400
    assert "never be registered" in resp.text


def test_register_rejects_asic(as_operator, tudo):
    resp = as_operator.post(
        REGISTER,
        json={"component_type": "ABC", "type_code": "ABCStar", "institute_code": "TUDO"},
    )
    assert resp.status_code == 400


def test_register_creates_draft_for_module(as_operator, tudo):
    resp = as_operator.post(REGISTER, json={**MODULE, "local_name": "TUDO-R5M0-99"})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["kind"] == "register_component"
    assert body["status"] == "draft"
    assert body["payload"]["component_type"] == "MODULE"
    assert body["payload"]["type_code"] == "R5M0"
    assert body["payload"]["local_name"] == "TUDO-R5M0-99"
    assert body["payload"]["subproject"] == "SE"


def test_register_allows_hybrid(as_operator, tudo):
    resp = as_operator.post(
        REGISTER,
        json={"component_type": "HYBRID", "type_code": "R5H0", "institute_code": "TUDO"},
    )
    assert resp.status_code == 201, resp.text


def test_register_unknown_institute(as_operator):
    resp = as_operator.post(
        REGISTER,
        json={"component_type": "MODULE", "type_code": "R5M0", "institute_code": "NOPE"},
    )
    assert resp.status_code == 404


def test_revalidate_register_flags_missing_fields(tudo):
    action = OutboxAction(
        institute_id=tudo["id"],
        kind="register_component",
        payload={"component_type": "MODULE"},
        created_by="x",
    )
    issues = revalidate_register(None, action)
    assert issues and "missing" in issues[0]


def test_revalidate_register_ok(tudo):
    action = OutboxAction(
        institute_id=tudo["id"],
        kind="register_component",
        payload=dict(MODULE),
        created_by="x",
    )
    assert revalidate_register(None, action) == []
