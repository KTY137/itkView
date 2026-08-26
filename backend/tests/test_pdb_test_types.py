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


class FakePagedResponse:
    """What itkdb actually hands back for a `pageItemList` catalogue.

    `client.get` never returns a plain dict in that case (itkdb/client.py):
    it wraps the response in a `PagedResponse`, which is neither dict nor
    list, exposes only the LAST fetched page through `.data`, and yields
    every row across every page when iterated. Modelling the dict shape in a
    fixture is what hid a live failure — the real sync answered "The PDB
    returned an unusable test-type catalogue" for every account.
    """

    def __init__(self, pages, total=None):
        self._pages = [list(page) for page in pages]
        self._page = 0
        self._index = 0
        self.total = sum(len(page) for page in self._pages) if total is None else total

    @property
    def data(self):
        return self._pages[self._page]

    @property
    def page_info(self):
        return {"pageIndex": self._page, "pageSize": len(self.data), "total": self.total}

    def __iter__(self):
        return self

    def __next__(self):
        if self._index >= len(self._pages[self._page]):
            if self._page + 1 >= len(self._pages):
                raise StopIteration
            self._page += 1
            self._index = 0
        self._index += 1
        return self._pages[self._page][self._index - 1]


def test_paged_catalogue_is_read_across_every_page():
    remote, client = gateway(
        FakePagedResponse(
            [
                [{"code": "MODULE_IV", "name": "Module IV", "state": "ready"}],
                [{"code": "MODULE_BOW", "name": "Module bow", "state": "ready"}],
            ]
        ),
        {"code": "MODULE_IV", "name": "Module IV", "results": [{"code": "CURRENT"}]},
        {"code": "MODULE_BOW", "name": "Module bow", "properties": []},
    )

    records = fetch_test_type_schemas(remote, "MODULE", project="S")

    # The second page must be reached: reading `.data` alone would mirror only
    # MODULE_BOW and silently drop the rest of the catalogue.
    assert [record.test_code for record in records] == ["MODULE_IV", "MODULE_BOW"]
    assert client.calls[0] == ("listTestTypes", {"project": "S", "componentType": "MODULE"})


def test_truncated_paged_catalogue_is_refused():
    remote, _ = gateway(
        FakePagedResponse([[{"code": "MODULE_IV", "state": "ready"}]], total=7)
    )

    with pytest.raises(PdbTestTypesUnavailable, match="incomplete"):
        fetch_test_type_schemas(remote, "MODULE", project="S")


def test_paged_catalogue_tolerates_rows_repeated_across_pages():
    """PDB listings have been observed repeating rows; a surplus is not a gap."""
    remote, _ = gateway(
        FakePagedResponse(
            [
                [{"code": "MODULE_IV", "state": "ready"}],
                [{"code": "MODULE_IV", "state": "ready"}],
            ],
            total=1,
        ),
        {"code": "MODULE_IV", "name": "Module IV", "results": []},
    )

    records = fetch_test_type_schemas(remote, "MODULE", project="S")

    assert [record.test_code for record in records] == ["MODULE_IV"]


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
