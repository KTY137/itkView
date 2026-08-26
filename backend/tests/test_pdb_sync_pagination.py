import pytest

from app.config import Settings
from app.models import InstituteProfile
from app.pdb_credentials import PdbAccessCodes
from app.pdb_sync import (
    PDB_PAGE_MAX_ATTEMPTS,
    PDB_PAGE_SIZE,
    PDB_REQUEST_TIMEOUT,
    PdbSyncUnavailable,
    _fetch_pages,
    fetch_for_institute,
)


def item(number: int) -> dict:
    return {"id": f"OID-{number}", "serialNumber": f"20USEM{number:08d}"}


def page(index: int, total: int, values: list[dict], size: int = PDB_PAGE_SIZE) -> dict:
    return {
        "itemList": values,
        "pageInfo": {"pageIndex": index, "pageSize": size, "total": total},
    }


class FakeClient:
    def __init__(self, pages: dict[int, object], failures: dict[int, int] | None = None) -> None:
        self.pages = pages
        self.failures = dict(failures or {})
        self.calls: list[dict] = []

    def get(self, action: str, *, json: dict, timeout):
        assert action == "listComponents"
        self.calls.append({"json": json, "timeout": timeout})
        index = json["pageInfo"]["pageIndex"]
        if self.failures.get(index, 0):
            self.failures[index] -= 1
            raise TimeoutError(f"page {index} timed out")
        return self.pages[index]


def test_fetch_pages_is_serial_bounded_and_reports_server_total():
    # Regression guard for the production range that times out in 100-item pages.
    assert PDB_PAGE_SIZE == 50
    total = PDB_PAGE_SIZE * 2 + 5
    client = FakeClient(
        {
            0: page(0, total, [item(i) for i in range(PDB_PAGE_SIZE)]),
            1: page(1, total, [item(i) for i in range(PDB_PAGE_SIZE, PDB_PAGE_SIZE * 2)]),
            2: page(2, total, [item(i) for i in range(PDB_PAGE_SIZE * 2, total)]),
        }
    )
    progress: list[tuple] = []

    result = _fetch_pages(client, {"filterMap": {}}, lambda *args: progress.append(args))

    assert len(result) == total
    assert [call["json"]["pageInfo"] for call in client.calls] == [
        {"pageIndex": 0, "pageSize": PDB_PAGE_SIZE},
        {"pageIndex": 1, "pageSize": PDB_PAGE_SIZE},
        {"pageIndex": 2, "pageSize": PDB_PAGE_SIZE},
    ]
    assert all(call["timeout"] == PDB_REQUEST_TIMEOUT for call in client.calls)
    assert progress == [
        ("fetching", 0, None),
        ("fetching", PDB_PAGE_SIZE, total),
        ("fetching", PDB_PAGE_SIZE * 2, total),
        ("fetching", total, total),
    ]


def test_fetch_pages_retries_the_same_page_with_timeout(monkeypatch):
    client = FakeClient({0: page(0, 1, [item(1)])}, failures={0: 2})
    progress: list[tuple] = []
    monkeypatch.setattr("app.pdb_sync.sleep", lambda seconds: None)

    assert _fetch_pages(
        client,
        {"filterMap": {}},
        lambda *args: progress.append(args),
    ) == [item(1)]
    assert len(client.calls) == 3
    assert {call["json"]["pageInfo"]["pageIndex"] for call in client.calls} == {0}
    assert progress == [
        ("fetching", 0, None),
        (
            "fetching",
            0,
            None,
            f"PDB page 1 request failed; retrying attempt 2 of {PDB_PAGE_MAX_ATTEMPTS}.",
        ),
        (
            "fetching",
            0,
            None,
            f"PDB page 1 request failed; retrying attempt 3 of {PDB_PAGE_MAX_ATTEMPTS}.",
        ),
        ("fetching", 1, 1),
    ]


def test_fetch_pages_stops_after_bounded_transient_attempts(monkeypatch):
    client = FakeClient({}, failures={0: PDB_PAGE_MAX_ATTEMPTS})
    monkeypatch.setattr("app.pdb_sync.sleep", lambda seconds: None)

    with pytest.raises(
        PdbSyncUnavailable,
        match=f"page 1 failed after {PDB_PAGE_MAX_ATTEMPTS} attempts",
    ):
        _fetch_pages(client, {"filterMap": {}})

    assert len(client.calls) == PDB_PAGE_MAX_ATTEMPTS


@pytest.mark.parametrize(
    "second_page, match",
    [
        (
            page(
                1,
                PDB_PAGE_SIZE * 2 + 1,
                [item(i) for i in range(PDB_PAGE_SIZE, PDB_PAGE_SIZE * 2)],
            ),
            "total changed",
        ),
        (
            page(
                1,
                PDB_PAGE_SIZE * 2,
                [item(i) for i in range(PDB_PAGE_SIZE, PDB_PAGE_SIZE * 2)],
                size=PDB_PAGE_SIZE // 2,
            ),
            "pageSize differed from the request",
        ),
        (
            page(
                0,
                PDB_PAGE_SIZE * 2,
                [item(i) for i in range(PDB_PAGE_SIZE, PDB_PAGE_SIZE * 2)],
            ),
            "index drifted",
        ),
    ],
)
def test_fetch_pages_rejects_pagination_drift(second_page, match):
    total = PDB_PAGE_SIZE * 2
    client = FakeClient(
        {
            0: page(0, total, [item(i) for i in range(PDB_PAGE_SIZE)]),
            1: second_page,
        }
    )
    with pytest.raises(PdbSyncUnavailable, match=match):
        _fetch_pages(client, {"filterMap": {}})


@pytest.mark.parametrize("count", [1, PDB_PAGE_SIZE, PDB_PAGE_SIZE + 1])
def test_fetch_pages_rejects_nonempty_bare_list_without_total(count):
    client = FakeClient({0: [item(i) for i in range(count)]})
    with pytest.raises(PdbSyncUnavailable, match="without pagination metadata"):
        _fetch_pages(client, {"filterMap": {}})


def test_fetch_pages_accepts_empty_bare_list():
    assert _fetch_pages(FakeClient({0: []}), {"filterMap": {}}) == []


class PermanentHttpError(RuntimeError):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"HTTP {status_code}")
        self.response = type("Response", (), {"status_code": status_code})()


def test_fetch_pages_does_not_retry_permanent_http_error(monkeypatch):
    client = FakeClient({})

    def fail(*args, **kwargs):
        client.calls.append({"json": kwargs["json"], "timeout": kwargs["timeout"]})
        raise PermanentHttpError(403)

    client.get = fail
    monkeypatch.setattr("app.pdb_sync.sleep", lambda seconds: None)

    with pytest.raises(PdbSyncUnavailable, match=r"failed after 1 attempt \(HTTP 403\)"):
        _fetch_pages(client, {"filterMap": {}})
    assert len(client.calls) == 1


def test_fetch_pages_never_exposes_upstream_exception_text(monkeypatch):
    sentinel = "sentinel-personal-access-code"
    client = FakeClient({})

    def fail(*args, **kwargs):
        raise TimeoutError(f"request body contained {sentinel}")

    client.get = fail
    monkeypatch.setattr("app.pdb_sync.sleep", lambda seconds: None)

    with pytest.raises(PdbSyncUnavailable) as caught:
        _fetch_pages(client, {"filterMap": {}})

    assert sentinel not in str(caught.value)
    assert "transient network error" in str(caught.value)


def test_fetch_for_institute_requests_ready_state_as_a_string(monkeypatch):
    client = FakeClient({0: page(0, 0, [])})
    codes = PdbAccessCodes(access_code1="user-code-1", access_code2="user-code-2")

    class FakeGateway:
        is_configured = True

        def __init__(self, settings, *, access_codes):
            assert access_codes is codes

        def client(self):
            return client

    monkeypatch.setattr("app.pdb_sync.PdbGateway", FakeGateway)
    settings = Settings(_env_file=None)
    institute = InstituteProfile(
        code="TUDO",
        name="TU Dortmund",
        local_name_prefix="TUDO-",
        settings={},
    )

    result = fetch_for_institute(settings, institute, codes)
    assert result.records == []
    assert result.skipped == 0
    assert client.calls[0]["json"]["filterMap"]["state"] == "ready"
