# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-FileComment: itkflow-fba765a2fd18
from types import SimpleNamespace

import pytest

import app.complete_component_sync as complete_sync
from app.complete_component_sync import (
    assembled_child_ids,
    fetch_assembled_component_closure,
    fetch_complete_for_institute,
)
from app.models import InstituteProfile
from app.pdb_sync import PdbSyncUnavailable


class FakeComponentClient:
    def __init__(self, payloads, *, failing=()):
        self.payloads = payloads
        self.failing = set(failing)
        self.calls: list[str] = []

    def get(self, action, *, json, timeout):
        assert action == "getComponent"
        assert timeout > 0
        object_id = json["component"]
        self.calls.append(object_id)
        if object_id in self.failing:
            raise RuntimeError("offline fixture failure")
        return self.payloads[object_id]


def member(component, state=None):
    return {"component": component, "state": state}


def payload(object_id, serial, children=()):
    return {
        "id": object_id,
        "serialNumber": serial,
        "state": "ready",
        "children": list(children),
    }


def test_assembled_child_ids_accepts_both_id_shapes_and_only_live_links():
    row = payload(
        "root",
        "ROOT",
        [
            member("direct"),
            member({"id": "nested"}, "ready"),
            member("direct", "ready"),
            member("removed", "deleted"),
            {"component": None},
            "malformed",
        ],
    )

    assert assembled_child_ids(row) == ("direct", "nested")


def test_fetch_assembled_component_closure_walks_every_descendant_once():
    root = payload(
        "root-id",
        "ROOT",
        [member("half-id"), member("hybrid-id")],
    )
    rows = {
        "half-id": payload(
            "half-id",
            "HALF",
            [member("sensor-id"), member("shared-id")],
        ),
        "hybrid-id": payload(
            "hybrid-id",
            "HYBRID",
            [member("abc-id"), member("shared-id")],
        ),
        "sensor-id": payload("sensor-id", "SENSOR"),
        "abc-id": payload("abc-id", "ABC"),
        "shared-id": payload("shared-id", "SHARED"),
    }
    client = FakeComponentClient(rows)
    progress = []

    fetched = fetch_assembled_component_closure(
        client,
        [root],
        limit=20,
        progress=lambda *event: progress.append(event),
    )

    assert [row["serialNumber"] for row in fetched] == [
        "HALF",
        "HYBRID",
        "SENSOR",
        "SHARED",
        "ABC",
    ]
    assert client.calls == [
        "half-id",
        "hybrid-id",
        "sensor-id",
        "shared-id",
        "abc-id",
    ]
    assert progress[-1][0] == "fetching"
    assert progress[-1][2] is None


def test_fetch_assembled_component_closure_rejects_a_truncated_limit():
    root = payload("root-id", "ROOT", [member("half-id")])
    rows = {
        "half-id": payload("half-id", "HALF", [member("sensor-id")]),
        "sensor-id": payload("sensor-id", "SENSOR"),
    }
    client = FakeComponentClient(rows)

    with pytest.raises(PdbSyncUnavailable, match="sync_assembled_part_limit"):
        fetch_assembled_component_closure(client, [root], limit=1)

    assert client.calls == ["half-id"]


def test_fetch_assembled_component_closure_rejects_an_unreadable_child():
    root = payload("root-id", "ROOT", [member("half-id")])
    client = FakeComponentClient({}, failing={"half-id"})

    with pytest.raises(PdbSyncUnavailable, match="could not be read"):
        fetch_assembled_component_closure(client, [root], limit=10)


def test_fetch_complete_for_institute_maps_the_recursive_closure(monkeypatch):
    root = payload("root-id", "ROOT", [member("half-id")])
    half = payload("half-id", "HALF", [member("sensor-id")])
    sensor = payload("sensor-id", "SENSOR")
    onsite = payload("onsite-id", "ONSITE")
    client = FakeComponentClient({"half-id": half, "sensor-id": sensor})

    class FakeGateway:
        is_configured = True

        def __init__(self, _settings, *, access_codes):
            assert access_codes == "codes"

        def client(self):
            return client

    listing_filters = []

    def fake_pages(_client, request, _progress, *, max_attempts):
        assert max_attempts == 3
        filters = request["filterMap"]
        listing_filters.append(filters)
        if "institute" in filters:
            return [root]
        return [onsite]

    monkeypatch.setattr(complete_sync, "PdbGateway", FakeGateway)
    monkeypatch.setattr(complete_sync, "_fetch_pages", fake_pages)
    monkeypatch.setattr(complete_sync, "fetch_institution_codes", lambda _client: {})
    monkeypatch.setattr(
        complete_sync,
        "map_pdb_component",
        lambda row, _ids, _institutions: row["serialNumber"],
    )

    result = fetch_complete_for_institute(
        SimpleNamespace(sync_page_max_attempts=3, sync_assembled_part_limit=10),
        InstituteProfile(code="SCOPE", name="Scope", settings={}),
        "codes",
    )

    assert result.records == ["ROOT", "ONSITE", "HALF", "SENSOR"]
    assert result.skipped == 0
    assert listing_filters[0]["institute"] == ["SCOPE"]
    assert listing_filters[1]["currentLocation"] == ["SCOPE"]


def test_application_uses_complete_component_fetcher(client):
    assert client.app.state.component_fetcher is fetch_complete_for_institute
