from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.models import StageEvent
from app.stats import STAGE_ORDER, lead_time, rework, stage_dwell, throughput, yield_stats

BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _rows_from(events):
    """(sn, stage, day, rework) tuples -> the shape the stats helpers consume."""
    return [(sn, stage, BASE + timedelta(days=day), rw) for sn, stage, day, rw in events]


def test_throughput_counts_first_reach_per_period():
    rows = _rows_from(
        [
            ("M1", "HV_TAB_ATTACHED", 0, False),
            ("M1", "FINISHED", 5, False),
            ("M2", "HV_TAB_ATTACHED", 2, False),
            ("M2", "FINISHED", 40, False),  # next month
            ("M2", "FINISHED", 41, False),  # re-entry ignored (first-reach only)
            ("M3", "HV_TAB_ATTACHED", 3, False),  # never finished
        ]
    )
    out = throughput(rows, stage="FINISHED", bucket="month")
    assert out == [{"period": "2026-01", "count": 1}, {"period": "2026-02", "count": 1}]


def test_lead_time_distribution():
    rows = _rows_from(
        [
            ("M1", "HV_TAB_ATTACHED", 0, False),
            ("M1", "FINISHED", 10, False),
            ("M2", "HV_TAB_ATTACHED", 0, False),
            ("M2", "FINISHED", 20, False),
            ("M3", "HV_TAB_ATTACHED", 0, False),  # unfinished, excluded
        ]
    )
    out = lead_time(rows, target_stage="FINISHED")
    assert out["count"] == 2
    assert out["median_days"] == 15.0


def test_stage_dwell_ignores_same_stage_corrections():
    rows = _rows_from(
        [
            ("M1", "HV_TAB_ATTACHED", 0, False),
            ("M1", "HV_TAB_ATTACHED", 0, False),  # same-second correction, no dwell
            ("M1", "GLUED", 4, False),
            ("M1", "BONDED", 6, False),
        ]
    )
    out = {d["stage"]: d for d in stage_dwell(rows)}
    assert out["HV_TAB_ATTACHED"]["median_days"] == 4.0
    assert out["GLUED"]["median_days"] == 2.0
    assert "BONDED" not in out  # terminal in this data — no following event


def test_stage_dwell_is_returned_in_production_order():
    rows = _rows_from(
        [
            ("M1", "BONDED", 0, False),
            ("M1", "GLUED", 1, False),  # out-of-order input
            ("M1", "TESTED", 2, False),
            ("M1", "HV_TAB_ATTACHED", 3, False),
            ("M1", "FINISHED", 4, False),
        ]
    )
    stages = [d["stage"] for d in stage_dwell(rows)]
    ranks = [STAGE_ORDER.index(s) for s in stages if s in STAGE_ORDER]
    assert ranks == sorted(ranks)  # canonical order regardless of input order


def test_yield_counts_good_failed_and_in_progress():
    rows = _rows_from(
        [
            ("M1", "HV_TAB_ATTACHED", 0, False),
            ("M1", "FINISHED", 5, False),  # good
            ("M2", "GLUED", 0, False),
            ("M2", "FAILED", 3, False),  # failed
            ("M3", "BONDED", 0, False),  # still in progress
            ("M4", "FAILED", 0, False),
            ("M4", "FINISHED", 2, False),  # recovered → good (reached target)
        ]
    )
    y = yield_stats(rows, target_stage="FINISHED")
    assert (y["good"], y["failed"], y["in_progress"], y["concluded"]) == (2, 1, 1, 3)
    assert y["rate"] == round(2 / 3, 3)


def test_yield_none_when_nothing_concluded():
    rows = _rows_from([("M1", "GLUED", 0, False), ("M2", "BONDED", 0, False)])
    y = yield_stats(rows, target_stage="FINISHED")
    assert y["concluded"] == 0 and y["rate"] is None and y["in_progress"] == 2


def test_rework_rate_and_by_stage():
    rows = _rows_from(
        [
            ("M1", "GLUED", 0, True),
            ("M1", "GLUED", 1, False),
            ("M2", "TESTED", 0, True),
            ("M3", "BONDED", 0, False),
        ]
    )
    out = rework(rows)
    assert out["total_components"] == 3
    assert out["reworked_components"] == 2
    assert out["rate"] == round(2 / 3, 3)
    assert {"stage": "GLUED", "count": 1} in out["by_stage"]
    assert {"stage": "TESTED", "count": 1} in out["by_stage"]


# --------------------------------------------------------------------------
# End-to-end through the DB + API
# --------------------------------------------------------------------------


def _seed(session_factory: sessionmaker[Session]):
    with session_factory() as s:
        rows = [
            ("20USEM00000001", "HV_TAB_ATTACHED", 0, False),
            ("20USEM00000001", "GLUED", 3, False),
            ("20USEM00000001", "FINISHED", 12, False),
            ("20USEM00000002", "HV_TAB_ATTACHED", 1, False),
            ("20USEM00000002", "GLUED", 2, True),
            ("20USES00000001", "BARE", 0, False),  # a SENSOR, filtered out by type
        ]
        for sn, stage, day, rw in rows:
            ctype = "MODULE" if sn.startswith("20USEM") else "SENSOR"
            s.add(
                StageEvent(
                    component_sn=sn,
                    component_type=ctype,
                    type_code="R0" if ctype == "MODULE" else "ATLAS18R0",
                    institute_code="TUDO",
                    stage=stage,
                    entered_at=BASE + timedelta(days=day),
                    rework=rw,
                )
            )
        s.commit()


def test_production_stats_endpoint(client: TestClient, session_factory):
    _seed(session_factory)
    body = client.get("/api/stats/production", params={"component_type": "MODULE"}).json()
    assert body["components_tracked"] == 2
    assert body["target_stage"] == "FINISHED"
    assert body["throughput"] == [{"period": "2026-01", "count": 1}]
    assert body["rework"]["reworked_components"] == 1
    assert body["stage_order"][0] == "HV_TAB_ATTACHED"
    # 20USEM00000001 reached FINISHED; 20USEM00000002 is still in progress.
    assert body["yield_"]["good"] == 1
    assert body["yield_"]["concluded"] == 1
    assert body["yield_"]["rate"] == 1.0


def test_production_stats_filters_by_type(client: TestClient, session_factory):
    _seed(session_factory)
    # SENSOR history exists but only under its own type.
    sensors = client.get("/api/stats/production", params={"component_type": "SENSOR"}).json()
    assert sensors["components_tracked"] == 1
    assert sensors["throughput"] == []  # no SENSOR reached FINISHED


def test_stats_dimensions_endpoint(client: TestClient, session_factory):
    _seed(session_factory)
    dims = client.get("/api/stats/dimensions").json()
    assert set(dims["component_types"]) == {"MODULE", "SENSOR"}
    assert "R0" in dims["type_codes"]
    assert dims["institutes"] == ["TUDO"]


def test_production_stats_rejects_bad_bucket(client: TestClient):
    assert client.get("/api/stats/production", params={"bucket": "fortnight"}).status_code == 422


def test_stage_events_populated_through_sync(client: TestClient, session_factory, tudo):
    """The sync path turns SyncRecord.stage_events into StageEvent rows."""
    from app.sync import StageEventRecord, SyncRecord, sync_components

    rec = SyncRecord(
        sn="20USEM00000009",
        component_type="MODULE",
        type_code="R0",
        stage="GLUED",
        location="TUDO",
        institute_code="TUDO",
        stage_events=[
            StageEventRecord(stage="HV_TAB_ATTACHED", entered_at=BASE),
            StageEventRecord(stage="GLUED", entered_at=BASE + timedelta(days=3)),
        ],
    )
    with session_factory() as s:
        sync_components(s, [rec, rec])  # duplicate record must not double-insert
        s.commit()
    dwell = client.get("/api/stats/production", params={"component_type": "MODULE"}).json()
    assert dwell["components_tracked"] == 1
    assert {d["stage"] for d in dwell["stage_dwell"]} == {"HV_TAB_ATTACHED"}
