import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db import make_engine, make_session_factory
from app.models import Component, InstituteProfile
from app.pdb_sync import (
    FetchResult,
    PdbSyncUnavailable,
    _materialise,
    build_id_to_sn,
    map_pdb_component,
)
from app.seed_demo import DEMO_FIXTURE_PATH, seed
from app.sync import SyncRecord, UnknownParentError, load_fixture_records, sync_components


def record(sn: str, **overrides) -> SyncRecord:
    defaults = {
        "sn": sn,
        "component_type": "MODULE",
        "type_code": "R5M0",
        "stage": "GLUED",
        "location": "TUDO",
        "institute_code": "TUDO",
    }
    return SyncRecord(**{**defaults, **overrides})


def run_sync(session_factory: sessionmaker[Session], records: list[SyncRecord]):
    with session_factory() as session:
        stats = sync_components(session, records)
        session.commit()
    return stats


# --------------------------------------------------------------------------
# Sync layer
# --------------------------------------------------------------------------


def test_sync_is_idempotent(session_factory: sessionmaker[Session]):
    records = [
        record("20USE5M0000801", local_name="TUDO-R5M0-01"),
        record("20USE5H0000801", component_type="HYBRID", type_code="R5H0", stage="BONDED"),
    ]
    first = run_sync(session_factory, records)
    assert (first.created, first.updated, first.unchanged) == (2, 0, 0)

    second = run_sync(session_factory, records)
    assert (second.created, second.updated, second.unchanged) == (0, 0, 2)
    assert second.total == 2


def test_sync_counts_a_stage_change_as_updated(session_factory: sessionmaker[Session]):
    run_sync(session_factory, [record("20USE5M0000801", stage="GLUED")])

    stats = run_sync(session_factory, [record("20USE5M0000801", stage="BONDED")])
    assert (stats.created, stats.updated, stats.unchanged) == (0, 1, 0)

    with session_factory() as session:
        component = session.scalar(select(Component).where(Component.sn == "20USE5M0000801"))
        assert component is not None and component.stage == "BONDED"


def test_sync_links_parent_even_when_child_comes_first(session_factory: sessionmaker[Session]):
    records = [
        record(
            "20USE5S0000801",
            component_type="SENSOR",
            type_code="ATLAS18R5",
            stage="FINISHED",
            parent_sn="20USE5M0000801",
        ),
        record("20USE5M0000801"),  # parent listed after its child
    ]
    stats = run_sync(session_factory, records)
    assert stats.created == 2

    with session_factory() as session:
        child = session.scalar(select(Component).where(Component.sn == "20USE5S0000801"))
        assert child is not None and child.parent_sn == "20USE5M0000801"
        parent = session.scalar(select(Component).where(Component.sn == "20USE5M0000801"))
        assert [c.sn for c in parent.children] == ["20USE5S0000801"]

    # Re-linking is idempotent too; a later parent change counts as updated.
    assert run_sync(session_factory, records).unchanged == 2
    reassigned = run_sync(
        session_factory,
        [record("20USE5M0000802"), records[0].model_copy(update={"parent_sn": "20USE5M0000802"})],
    )
    assert (reassigned.created, reassigned.updated) == (1, 1)


def test_sync_rejects_unknown_parent(session_factory: sessionmaker[Session]):
    with session_factory() as session:
        with pytest.raises(UnknownParentError, match="20USE5M0009999"):
            sync_components(session, [record("20USE5S0000801", parent_sn="20USE5M0009999")])


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------


@pytest.fixture()
def demo_mirror(session_factory: sessionmaker[Session]) -> list[SyncRecord]:
    records = load_fixture_records(DEMO_FIXTURE_PATH)
    run_sync(session_factory, records)
    return records


def test_demo_fixture_loads_fully(session_factory: sessionmaker[Session]):
    records = load_fixture_records(DEMO_FIXTURE_PATH)
    assert len(records) == 18

    stats = run_sync(session_factory, records)
    assert (stats.created, stats.updated, stats.unchanged) == (18, 0, 0)


def test_demo_seed_creates_institute_profile(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'demo.db'}"
    stats = seed(database_url)
    assert stats.created == 18

    engine = make_engine(database_url)
    with make_session_factory(engine)() as session:
        institutes = list(session.scalars(select(InstituteProfile)))
        assert [(i.code, i.name, i.local_name_prefix) for i in institutes] == [
            ("TUDO", "TU Dortmund", "TUDO-")
        ]
        # Demo branding: TUDO carries an institute logo in its profile settings.
        assert institutes[0].settings.get("logo_url", "").startswith("https://")


def test_list_components_sorted_by_local_name_then_sn(client: TestClient, demo_mirror):
    body = client.get("/api/components").json()
    assert len(body) == 18
    named = [c["local_name"] for c in body if c["local_name"] is not None]
    assert named == sorted(named)  # local names first, sorted
    unnamed = [c["sn"] for c in body if c["local_name"] is None]
    assert unnamed == sorted(unnamed)  # then the rest by serial number
    assert body[-len(unnamed) :] == [c for c in body if c["local_name"] is None]


def test_list_components_q_matches_sn_and_local_name(client: TestClient, demo_mirror):
    # Case-insensitive substring on the local name …
    by_name = client.get("/api/components", params={"q": "r5m0-07"}).json()
    assert [c["sn"] for c in by_name] == ["20USE5M0000701"]
    # … and on the serial number.
    by_sn = client.get("/api/components", params={"q": "use2h"}).json()
    assert {c["sn"] for c in by_sn} == {"20USE2H0000704", "20USE2H0000705"}


def test_list_components_filters_stage_type_institute(client: TestClient, demo_mirror):
    glued = client.get("/api/components", params={"stage": "GLUED"}).json()
    assert {c["sn"] for c in glued} == {"20USE5M0000703"}

    pwbs = client.get("/api/components", params={"component_type": "PWB"}).json()
    assert len(pwbs) == 3 and all(c["component_type"] == "PWB" for c in pwbs)

    assert client.get("/api/components", params={"institute": "TUDO"}).json() != []
    assert client.get("/api/components", params={"institute": "NOWHERE"}).json() == []

    combined = client.get(
        "/api/components", params={"component_type": "MODULE", "stage": "FAILED"}
    ).json()
    assert [c["sn"] for c in combined] == ["20USE5M0000699"]
    assert combined[0]["trashed"] is True


def test_component_detail_includes_children_and_parent_sn(client: TestClient, demo_mirror):
    detail = client.get("/api/components/20USE2M0000704").json()
    assert detail["local_name"] == "TUDO-R2-04"
    assert detail["parent_sn"] is None
    assert [c["sn"] for c in detail["children"]] == [
        "20USE2H0000704",
        "20USE2H0000705",
        "20USE2S0000704",
        "20USEPB0000704",
    ]
    assert all(c["parent_sn"] == "20USE2M0000704" for c in detail["children"])

    child = client.get("/api/components/20USE2S0000704").json()
    assert child["parent_sn"] == "20USE2M0000704"
    assert child["children"] == []


def test_component_detail_404_for_unknown_sn(client: TestClient):
    response = client.get("/api/components/20USE0X0000000")
    assert response.status_code == 404
    assert "20USE0X0000000" in response.json()["detail"]


def test_component_endpoints_are_in_openapi(client: TestClient):
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/components" in paths
    assert "/api/components/{sn}" in paths


# --------------------------------------------------------------------------
# Component sync API
# --------------------------------------------------------------------------


def test_component_sync_endpoint_uses_configured_fetcher(
    client: TestClient, tudo: dict
):
    def fake_fetcher(settings, institute):
        assert settings.pdb_instance == "test"
        assert institute.code == "TUDO"
        return FetchResult(
            records=[
                record("20USE5M0000801", local_name="TUDO-R5M0-01"),
                record(
                    "20USE5S0000801",
                    component_type="SENSOR",
                    type_code="ATLAS18R5",
                    stage="FINISHED",
                    parent_sn="20USE5M0000801",
                ),
            ],
            skipped=1,
        )

    client.app.state.component_fetcher = fake_fetcher

    response = client.post("/api/sync/components/TUDO")
    assert response.status_code == 200, response.text
    assert response.json() == {
        "institute_code": "TUDO",
        "fetched": 3,
        "skipped": 1,
        "created": 2,
        "updated": 0,
        "unchanged": 0,
        "stale": 0,
        "total": 2,
    }

    listed = client.get("/api/components", params={"q": "20USE5"}).json()
    assert {component["sn"] for component in listed} == {
        "20USE5M0000801",
        "20USE5S0000801",
    }

    second = client.post("/api/sync/components/TUDO")
    assert second.status_code == 200, second.text
    assert second.json()["unchanged"] == 2


def test_component_sync_requires_known_institute(client: TestClient):
    called = False

    def fake_fetcher(settings, institute):
        nonlocal called
        called = True
        return FetchResult(records=[], skipped=0)

    client.app.state.component_fetcher = fake_fetcher
    response = client.post("/api/sync/components/NOPE")

    assert response.status_code == 404
    assert called is False


def test_component_sync_reports_pdb_unavailable(client: TestClient, tudo: dict):
    def fake_fetcher(settings, institute):
        raise PdbSyncUnavailable("No sandbox token configured.")

    client.app.state.component_fetcher = fake_fetcher
    response = client.post("/api/sync/components/TUDO")

    assert response.status_code == 503
    assert "sandbox token" in response.json()["detail"]


def test_component_sync_rolls_back_unknown_parent(
    client: TestClient, tudo: dict
):
    def fake_fetcher(settings, institute):
        return FetchResult(
            records=[record("20USE5S0000801", parent_sn="20USE5M0009999")],
            skipped=0,
        )

    client.app.state.component_fetcher = fake_fetcher
    response = client.post("/api/sync/components/TUDO")

    assert response.status_code == 409
    assert "20USE5M0009999" in response.json()["detail"]
    assert client.get("/api/components").json() == []


def test_component_sync_endpoint_is_in_openapi(client: TestClient):
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/sync/components/{institute_code}" in paths


# --------------------------------------------------------------------------
# Dashboard summary
# --------------------------------------------------------------------------


def test_dashboard_summary_empty(client: TestClient):
    body = client.get("/api/dashboard/summary").json()
    assert body == {
        "total_components": 0,
        "last_synced_at": None,
        "submitted_outbox": 0,
        "failed_outbox": 0,
        "by_stage": [],
        "by_component_type": [],
        "by_institute": [],
        "outbox_by_status": [],
    }


def test_dashboard_summary_counts_components_and_outbox(
    client: TestClient, tudo: dict, demo_mirror
):
    client.post(
        "/api/outbox",
        json={"institute_code": "TUDO", "kind": "stage_move", "created_by": "aa"},
    )
    client.post(
        "/api/outbox",
        json={"institute_code": "TUDO", "kind": "upload_test_run", "created_by": "aa"},
    )
    failed = client.post(
        "/api/outbox",
        json={"institute_code": "TUDO", "kind": "stage_move", "created_by": "aa"},
    ).json()
    client.post(
        f"/api/outbox/{failed['id']}/transition",
        json={"to": "validated", "actor": "aa"},
    )
    client.post(
        f"/api/outbox/{failed['id']}/transition",
        json={"to": "approved", "actor": "aa"},
    )
    client.post(
        f"/api/outbox/{failed['id']}/transition",
        json={"to": "submitted", "actor": "aa"},
    )
    client.post(
        f"/api/outbox/{failed['id']}/transition",
        json={"to": "failed", "actor": "aa", "error": "PDB timeout"},
    )

    body = client.get("/api/dashboard/summary").json()

    assert body["total_components"] == 18
    assert body["last_synced_at"] is not None
    assert body["submitted_outbox"] == 0
    assert body["failed_outbox"] == 1
    assert {"label": "TUDO", "count": 18} in body["by_institute"]
    assert {"label": "MODULE", "count": 5} in body["by_component_type"]
    assert {"label": "draft", "count": 2} in body["outbox_by_status"]
    assert {"label": "failed", "count": 1} in body["outbox_by_status"]
    assert "/api/dashboard/summary" in client.get("/openapi.json").json()["paths"]


# --------------------------------------------------------------------------
# PDB payload mapping — shapes verified against a real production fetch
# --------------------------------------------------------------------------


def _pdb_payload(sn: str, oid: str, **overrides) -> dict:
    """A minimal 'ready' listComponents payload as production returns it."""
    payload = {
        "id": oid,
        "serialNumber": sn,
        "state": "ready",
        "componentType": {"code": "SENSOR"},
        "type": {"code": "ATLAS18R0"},
        "currentStage": {"code": "BONDED"},
        "institution": {"code": "TUDO"},
        "currentLocation": {"code": "TUDO"},
        "parents": [],
    }
    payload.update(overrides)
    return payload


def test_map_resolves_string_parent_object_id():
    """parents[].component is the parent's object-id *string*, not a nested dict."""
    parent = _pdb_payload("20USEM00000001", "OID_PARENT", componentType={"code": "MODULE"})
    child = _pdb_payload(
        "20USES00000001", "OID_CHILD", parents=[{"component": "OID_PARENT", "state": "ready"}]
    )
    id_to_sn = build_id_to_sn([parent, child])
    rec = map_pdb_component(child, id_to_sn)
    assert rec is not None
    assert rec.parent_sn == "20USEM00000001"


def test_map_string_parent_without_state_is_treated_live():
    """Most real parent entries omit `state`; a present component id is live."""
    child = _pdb_payload("20USES00000002", "C2", parents=[{"component": "OID_P"}])
    rec = map_pdb_component(child, {"OID_P": "20USEM00000002"})
    assert rec is not None and rec.parent_sn == "20USEM00000002"


def test_map_unresolved_parent_stays_none_without_crashing():
    """A parent outside the fetched batch must not dangle or raise."""
    child = _pdb_payload("20USES00000003", "C3", parents=[{"component": "OID_MISSING"}])
    rec = map_pdb_component(child, {})  # empty lookup
    assert rec is not None and rec.parent_sn is None


def test_map_ignores_empty_parent_slots():
    child = _pdb_payload("20USES00000004", "C4", parents=[{"component": None}, {"order": 0}])
    rec = map_pdb_component(child, {})
    assert rec is not None and rec.parent_sn is None


def test_map_accepts_long_institute_code():
    """Real codes like UCSC_STRIP_SENSORS (18 chars) exceed the old 16 limit."""
    payload = _pdb_payload(
        "20USES00000005", "C5", institution={"code": "UCSC_STRIP_SENSORS"}
    )
    rec = map_pdb_component(payload, {})
    assert rec is not None and rec.institute_code == "UCSC_STRIP_SENSORS"


def test_map_skips_deleted_and_serial_less():
    assert map_pdb_component(_pdb_payload("20USES00000006", "C6", state="deleted"), {}) is None
    assert map_pdb_component(_pdb_payload("", "C7"), {}) is None


def test_map_picks_up_pdb_dummy_flag():
    rec = map_pdb_component(_pdb_payload("20USES00000008", "C8", dummy=True), {})
    assert rec is not None and rec.is_dummy is True


def test_map_dummy_batch_membership_marks_dummy():
    """A part in a DUMMY_<institute> batch is a write target even if dummy=False.

    This is the authoritative marker: a freshly registered dummy module sits in
    DUMMY_TUDO but its per-component `dummy` boolean stays false.
    """
    payload = _pdb_payload(
        "20USEM00000435", "M435", dummy=False, batches=[{"number": "DUMMY_TUDO"}]
    )
    rec = map_pdb_component(payload, {})
    assert rec is not None and rec.is_dummy is True


def test_map_dummy_batch_match_is_case_insensitive():
    payload = _pdb_payload("20USES00000009", "C9", batches=[{"number": "Dummy_O1"}])
    assert map_pdb_component(payload, {}).is_dummy is True


def test_map_real_production_batch_is_not_dummy():
    payload = _pdb_payload(
        "20USES00000010", "C10", dummy=False, batches=[{"number": "VPA50980"}]
    )
    assert map_pdb_component(payload, {}).is_dummy is False


# --------------------------------------------------------------------------
# Pagination completeness guard (_materialise)
# --------------------------------------------------------------------------


class _FakePaged:
    """Stand-in for itkdb's PagedResponse: iterable, with a reported total."""

    def __init__(self, items: list, total: int) -> None:
        self._items = items
        self.total = total

    def __iter__(self):
        return iter(self._items)


def test_materialise_accepts_complete_paged():
    assert _materialise(_FakePaged([{"a": 1}, {"a": 2}], total=2)) == [{"a": 1}, {"a": 2}]


def test_materialise_rejects_truncated_paged():
    with pytest.raises(PdbSyncUnavailable):
        _materialise(_FakePaged([{"a": 1}], total=5))


def test_materialise_rejects_truncated_dict():
    with pytest.raises(PdbSyncUnavailable):
        _materialise({"itemList": [{"a": 1}], "pageInfo": {"total": 3}})


def test_materialise_accepts_complete_dict():
    assert _materialise({"itemList": [{"a": 1}], "pageInfo": {"total": 1}}) == [{"a": 1}]


# --------------------------------------------------------------------------
# Prune: a full institute sync flags rows the PDB no longer returns
# --------------------------------------------------------------------------


def test_prune_flags_and_clears_stale(session_factory):
    both = [record("20USE5M0000801"), record("20USE5M0000802")]
    with session_factory() as s:
        sync_components(s, both, prune_scope="TUDO")
        s.commit()

    # A later full sync returns only the first → the second is pruned as stale.
    with session_factory() as s:
        stats = sync_components(s, [record("20USE5M0000801")], prune_scope="TUDO")
        s.commit()
        assert stats.stale == 1
        gone = s.scalar(select(Component).where(Component.sn == "20USE5M0000802"))
        kept = s.scalar(select(Component).where(Component.sn == "20USE5M0000801"))
        assert gone is not None and gone.stale is True
        assert kept.stale is False

    # It reappears → un-staled, and reported stale drops back to zero.
    with session_factory() as s:
        stats = sync_components(s, both, prune_scope="TUDO")
        s.commit()
        assert stats.stale == 0
        back = s.scalar(select(Component).where(Component.sn == "20USE5M0000802"))
        assert back.stale is False


def test_sync_without_prune_scope_never_marks_stale(session_factory):
    with session_factory() as s:
        sync_components(s, [record("20USE5M0000801"), record("20USE5M0000802")])
        s.commit()
    with session_factory() as s:
        stats = sync_components(s, [record("20USE5M0000801")])  # partial, no prune
        s.commit()
        assert stats.stale == 0
        untouched = s.scalar(select(Component).where(Component.sn == "20USE5M0000802"))
        assert untouched.stale is False


def test_stale_filter_on_component_list(client: TestClient, tudo: dict):
    def fetch_two(settings, institute):
        return FetchResult(
            records=[record("20USE5M0000801"), record("20USE5M0000802")], skipped=0
        )

    def fetch_one(settings, institute):
        return FetchResult(records=[record("20USE5M0000801")], skipped=0)

    client.app.state.component_fetcher = fetch_two
    client.post("/api/sync/components/TUDO")
    client.app.state.component_fetcher = fetch_one
    assert client.post("/api/sync/components/TUDO").json()["stale"] == 1

    stale_only = client.get("/api/components", params={"stale": "true"}).json()
    assert {c["sn"] for c in stale_only} == {"20USE5M0000802"}
    live_only = client.get("/api/components", params={"stale": "false"}).json()
    assert {c["sn"] for c in live_only} == {"20USE5M0000801"}
