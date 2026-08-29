# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-FileComment: itkflow-1a6c29c71b0d
from app.pdb_test_types import (
    PdbTestTypesUnavailable,
    TestTypeSchemaRecord,
)


def schema_record():
    return TestTypeSchemaRecord(
        component_type="MODULE",
        test_code="MODULE_IV",
        name="Module IV",
        schema={
            "code": "MODULE_IV",
            "properties": [{"code": "TEMPERATURE", "dataType": "float"}],
            "results": [{"code": "CURRENT", "dataType": "float", "valueType": "array"}],
        },
    )


def test_schema_list_requires_authentication(client):
    assert client.get("/api/test-types?component_type=MODULE").status_code == 401


def test_operator_syncs_and_lists_schema(as_operator):
    calls = []

    def fetcher(gateway, component_type, *, project):
        calls.append((gateway.is_configured, component_type, project))
        return [schema_record()]

    as_operator.app.state.test_type_schema_fetcher = fetcher

    synced = as_operator.post("/api/test-types/sync?component_type=MODULE")
    assert synced.status_code == 200, synced.text
    assert synced.json() == {
        "component_type": "MODULE",
        "created": 1,
        "updated": 0,
        "unchanged": 0,
        "total": 1,
    }
    assert calls == [(True, "MODULE", "S")]

    listed = as_operator.get("/api/test-types?component_type=MODULE")
    assert listed.status_code == 200, listed.text
    body = listed.json()[0]
    assert body["test_code"] == "MODULE_IV"
    assert body["schema"]["results"][0]["code"] == "CURRENT"
    assert "schema_data" not in body


def test_schema_sync_is_operator_gated(as_viewer):
    response = as_viewer.post("/api/test-types/sync?component_type=MODULE")
    assert response.status_code == 403


def test_schema_sync_requires_session_bound_csrf(as_operator):
    del as_operator.headers["X-CSRF-Token"]

    response = as_operator.post("/api/test-types/sync?component_type=MODULE")

    assert response.status_code == 403
    assert response.json()["detail"] == "Missing or invalid CSRF token."


def test_schema_sync_reports_unavailable_as_503(as_operator):
    def unavailable(*args, **kwargs):
        raise PdbTestTypesUnavailable("The PDB test-type catalogue could not be read.")

    as_operator.app.state.test_type_schema_fetcher = unavailable
    response = as_operator.post("/api/test-types/sync?component_type=MODULE")

    assert response.status_code == 503
    assert response.json()["detail"] == "The PDB test-type catalogue could not be read."


def test_schema_endpoints_reject_blank_component_type(as_operator):
    assert as_operator.get("/api/test-types?component_type=%20").status_code == 422
    assert as_operator.post("/api/test-types/sync?component_type=%20").status_code == 422


def test_m3_openapi_uses_public_schema_aliases_and_ingest_fields(client):
    document = client.app.openapi()
    schema_properties = document["components"]["schemas"]["TestTypeSchemaOut"]["properties"]
    ingest_properties = document["components"]["schemas"]["IngestFileCreate"]["properties"]
    preview_attachments = document["components"]["schemas"]["ComponentPreviewTestOut"][
        "properties"
    ]["attachments"]

    assert "schema" in schema_properties
    assert "schema_data" not in schema_properties
    assert {"component_sn", "parser"} <= ingest_properties.keys()
    assert preview_attachments["items"]["$ref"].endswith("/TestRunAttachmentOut")
