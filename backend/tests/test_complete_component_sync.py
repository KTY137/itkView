# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-FileComment: itkflow-fba765a2fd18
from types import SimpleNamespace

import pytest
from sqlalchemy import select

import app.complete_component_sync as complete_sync
from app.complete_component_sync import (
    assembled_child_ids,
    fetch_assembled_component_closure,
    fetch_complete_for_institute,
)
from app.models import Component, InstituteProfile
from app.pdb_sync import PdbSyncUnavailable
from app.sync import SyncRecord, sync_components


class FakeComponentClient:
    def __init__(self, payloads, *, failing=()):
        self.payloads = payloads
        self.failing = set(failing)
        self.calls: list[str] = []

    def get(self, action, *, json, timeout):
        assert action == "getComponent"
        assert timeout is not None
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


def mirror_record(
    sn,
    *,
    component_type="MODULE",
    owner="SCOPE",
    location="SCOPE",
    parent_sn=None,
):
    return SyncRecord(
        sn=sn,
        component_type=component_type,
        type_code="TEST",
        stage="READY",
        institute_code=owner,
        location=location,
        parent_sn=parent_sn,
    )


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


def test_fetch_assembled_component_closure_pins_a_missing_response_id():
    root = payload("root-id", "ROOT", [member("half-id")])
    half = payload("half-id", "HALF")
    del half["id"]

    fetched = fetch_assembled_component_closure(
        FakeComponentClient({"half-id": half}),
        [root],
        limit=10,
    )

    assert fetched[0]["id"] == "half-id"


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


def test_fetch_assembled_component_closure_rejects_non_ready_or_wrong_identity():
    root = payload("root-id", "ROOT", [member("half-id")])
    not_ready = payload("half-id", "HALF")
    not_ready["state"] = "deleted"
    with pytest.raises(PdbSyncUnavailable, match="not ready"):
        fetch_assembled_component_closure(
            FakeComponentClient({"half-id": not_ready}),
            [root],
            limit=10,
        )

    wrong_id = payload("other-id", "HALF")
    with pytest.raises(PdbSyncUnavailable, match="different object identity"):
        fetch_assembled_component_closure(
            FakeComponentClient({"half-id": wrong_id}),
            [root],
            limit=10,
        )


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


def test_prune_retires_external_descendants_missing_from_the_new_closure(session_factory):
    initial = [
        mirror_record("ROOT"),
        mirror_record(
            "HALF",
            owner="CERN",
            location="REMOTE",
            parent_sn="ROOT",
        ),
        mirror_record(
            "SENSOR",
            component_type="SENSOR",
            owner="CERN",
            location="REMOTE",
            parent_sn="HALF",
        ),
    ]
    with session_factory() as session:
        first = sync_components(session, initial, prune_scope="SCOPE")
        session.commit()
    assert first.stale == 0

    with session_factory() as session:
        second = sync_components(session, [mirror_record("ROOT")], prune_scope="SCOPE")
        session.commit()
    assert second.stale == 2

    with session_factory() as session:
        rows = {
            row.sn: row
            for row in session.scalars(
                select(Component).where(Component.sn.in_(("ROOT", "HALF", "SENSOR")))
            )
        }
        assert rows["ROOT"].stale is False
        assert rows["HALF"].stale is True and rows["HALF"].parent_id is None
        assert rows["SENSOR"].stale is True and rows["SENSOR"].parent_id is None

        restored = sync_components(session, initial, prune_scope="SCOPE")
        session.commit()
    assert restored.stale == 0

    with session_factory() as session:
        half = session.scalar(select(Component).where(Component.sn == "HALF"))
        sensor = session.scalar(select(Component).where(Component.sn == "SENSOR"))
        assert half is not None and half.stale is False and half.parent_sn == "ROOT"
        assert sensor is not None and sensor.stale is False and sensor.parent_sn == "HALF"


def test_application_uses_complete_component_fetcher(client):
    assert client.app.state.component_fetcher is fetch_complete_for_institute
