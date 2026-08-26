from types import SimpleNamespace

import pytest

from app.pdb_test_types import PdbTestTypesUnavailable, fetch_test_type_schemas


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, route, *, json):
        self.calls.append((route, json))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def gateway(*responses, configured=True):
    client = FakeClient(responses)
    return SimpleNamespace(is_configured=configured, client=lambda: client), client


def test_fetches_each_complete_schema_with_the_component_scope():
    remote, client = gateway(
        {
            "pageItemList": [
                {"code": "MODULE_IV", "name": "Module IV", "state": "ready"},
                {"code": "MODULE_BOW", "name": "Module bow", "state": "active"},
            ]
        },
        {"code": "MODULE_IV", "name": "Module IV", "results": [{"code": "CURRENT"}]},
        {"code": "MODULE_BOW", "name": "Module bow", "properties": []},
    )

    records = fetch_test_type_schemas(remote, "MODULE", project="S")

    assert [record.test_code for record in records] == ["MODULE_IV", "MODULE_BOW"]
    assert records[0].schema["results"][0]["code"] == "CURRENT"
    assert client.calls == [
        ("listTestTypes", {"project": "S", "componentType": "MODULE"}),
        (
            "getTestTypeByCode",
            {"project": "S", "componentType": "MODULE", "code": "MODULE_IV"},
        ),
        (
            "getTestTypeByCode",
            {"project": "S", "componentType": "MODULE", "code": "MODULE_BOW"},
        ),
    ]


def test_skips_inactive_and_duplicate_catalogue_rows():
    remote, client = gateway(
        {
            "itemList": [
                {"code": "OLD", "state": "deleted"},
                {"code": "GOOD"},
                {"code": "GOOD"},
            ]
        },
        {"code": "GOOD", "name": "Good schema"},
    )

    records = fetch_test_type_schemas(remote, "MODULE", project="S")

    assert [record.test_code for record in records] == ["GOOD"]
    assert len(client.calls) == 2


@pytest.mark.parametrize(
    "catalogue",
    [
        {},
        {"unknown": []},
        {"pageItemList": "not-a-list"},
        {"pageItemList": ["not-an-object"]},
        "not-a-catalogue",
        [{"name": "No code"}],
    ],
)
def test_malformed_catalogue_is_not_mistaken_for_an_empty_snapshot(catalogue):
    remote, _ = gateway(catalogue)

    with pytest.raises(PdbTestTypesUnavailable, match="unusable"):
        fetch_test_type_schemas(remote, "MODULE", project="S")


@pytest.mark.parametrize("catalogue", [{"pageItemList": []}, {"itemList": []}, []])
def test_explicit_empty_catalogue_is_a_valid_snapshot(catalogue):
    remote, _ = gateway(catalogue)

    assert fetch_test_type_schemas(remote, "MODULE", project="S") == []


def test_unconfigured_gateway_is_distinct_from_an_empty_catalogue():
    remote, _ = gateway(configured=False)

    with pytest.raises(PdbTestTypesUnavailable, match="No personal PDB connection"):
        fetch_test_type_schemas(remote, "MODULE", project="S")


def test_detail_failure_is_strict_and_does_not_leak_upstream_text():
    remote, _ = gateway(
        {"pageItemList": [{"code": "MODULE_IV"}]},
        RuntimeError("grantToken secret-access-code"),
    )

    with pytest.raises(PdbTestTypesUnavailable) as caught:
        fetch_test_type_schemas(remote, "MODULE", project="S")

    assert "secret-access-code" not in str(caught.value)


def test_catalogue_failure_does_not_leak_upstream_text():
    remote, _ = gateway(RuntimeError("grantToken other-secret-access-code"))

    with pytest.raises(PdbTestTypesUnavailable) as caught:
        fetch_test_type_schemas(remote, "MODULE", project="S")

    assert "other-secret-access-code" not in str(caught.value)


def test_mismatched_detail_is_rejected():
    remote, _ = gateway(
        {"pageItemList": [{"code": "MODULE_IV"}]},
        {"code": "OTHER", "name": "Wrong"},
    )

    with pytest.raises(PdbTestTypesUnavailable, match="mismatched"):
        fetch_test_type_schemas(remote, "MODULE", project="S")
