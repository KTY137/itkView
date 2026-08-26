"""Measurement statistics: overlaid curves (IV) and scalar distributions.

The Statistics page aggregates mirrored test-run measurements across an
institute: array-valued results become overlaid curves (one per run), scalar
results become a distribution summary. Everything is derived from the local
evidence mirror — no PDB call, no hardcoded test types (hard rule #4: which
codes exist is data, not code).
"""

from datetime import datetime, timedelta

from app.test_run_evidence import TestRunEvidenceRecord, upsert_test_run_evidence


def _seed(session_factory, records):
    with session_factory() as session:
        upsert_test_run_evidence(session, records)
        session.commit()


def _iv_run(sn: str, ref: str, *, days_ago: int, passed: bool = True, points=None):
    voltage = [0, -10, -20]
    current = points or [1.0, 2.0, 3.0]
    return TestRunEvidenceRecord(
        component_sn=sn,
        test_type="MODULE_IV_PS_V1",
        passed=passed,
        external_ref=ref,
        measured_at=datetime(2026, 8, 1) - timedelta(days=days_ago),
        payload={
            "results": {"VOLTAGE": voltage, "CURRENT": current, "HUMIDITY": 8.6},
            "result_meta": {
                "VOLTAGE": {"name": "Voltage [V]", "value_type": "array"},
                "CURRENT": {"name": "Current [nA]", "value_type": "array"},
                "HUMIDITY": {"name": "Humidity [%]", "value_type": "single"},
            },
            "detail_synced": True,
        },
    )


def _scalar_run(sn: str, ref: str, value: float, *, days_ago: int = 0):
    return TestRunEvidenceRecord(
        component_sn=sn,
        test_type="MODULE_BOW",
        passed=True,
        external_ref=ref,
        measured_at=datetime(2026, 8, 1) - timedelta(days=days_ago),
        payload={
            "results": {"BOW": value},
            "result_meta": {"BOW": {"name": "Bow [um]", "value_type": "single"}},
            "detail_synced": True,
        },
    )


def test_measurement_dimensions_lists_result_codes_by_kind(client, session_factory):
    _seed(
        session_factory,
        [
            _iv_run("20USEM00000001", "R1", days_ago=1),
            _iv_run("20USEM00000002", "R2", days_ago=2),
            _scalar_run("20USEM00000001", "R3", 12.5),
        ],
    )
    body = client.get("/api/stats/measurements/dimensions").json()
    by_type = {entry["test_type"]: entry for entry in body["test_types"]}
    assert set(by_type) == {"MODULE_IV_PS_V1", "MODULE_BOW"}

    iv_results = {r["code"]: r for r in by_type["MODULE_IV_PS_V1"]["results"]}
    assert iv_results["CURRENT"]["kind"] == "array"
    assert iv_results["CURRENT"]["name"] == "Current [nA]"
    assert iv_results["CURRENT"]["runs"] == 2
    assert iv_results["HUMIDITY"]["kind"] == "scalar"
    assert by_type["MODULE_BOW"]["results"][0]["code"] == "BOW"


def test_curves_pair_x_and_y_arrays_per_run(client, session_factory):
    _seed(
        session_factory,
        [
            _iv_run("20USEM00000001", "R1", days_ago=1, points=[1.0, 2.0, 3.0]),
            _iv_run("20USEM00000002", "R2", days_ago=2, passed=False, points=[4.0, 5.0, 6.0]),
        ],
    )
    body = client.get(
        "/api/stats/measurements",
        params={"test_type": "MODULE_IV_PS_V1", "result": "CURRENT", "x_result": "VOLTAGE"},
    ).json()
    assert body["kind"] == "array"
    assert body["result_name"] == "Current [nA]"
    assert body["x_name"] == "Voltage [V]"
    curves = {c["component_sn"]: c for c in body["curves"]}
    assert curves["20USEM00000001"]["y"] == [1.0, 2.0, 3.0]
    assert curves["20USEM00000001"]["x"] == [0, -10, -20]
    assert curves["20USEM00000002"]["passed"] is False


def test_curves_without_x_fall_back_to_the_index(client, session_factory):
    _seed(session_factory, [_iv_run("20USEM00000001", "R1", days_ago=1)])
    body = client.get(
        "/api/stats/measurements",
        params={"test_type": "MODULE_IV_PS_V1", "result": "CURRENT"},
    ).json()
    assert body["curves"][0]["x"] is None
    assert body["curves"][0]["y"] == [1.0, 2.0, 3.0]


def test_scalar_measurements_come_with_a_distribution_summary(client, session_factory):
    _seed(
        session_factory,
        [
            _scalar_run("20USEM00000001", "S1", 10.0, days_ago=3),
            _scalar_run("20USEM00000002", "S2", 20.0, days_ago=2),
            _scalar_run("20USEM00000003", "S3", 30.0, days_ago=1),
        ],
    )
    body = client.get(
        "/api/stats/measurements",
        params={"test_type": "MODULE_BOW", "result": "BOW"},
    ).json()
    assert body["kind"] == "scalar"
    assert [v["value"] for v in body["values"]] == [30.0, 20.0, 10.0]  # newest first
    summary = body["summary"]
    assert summary["count"] == 3
    assert summary["min"] == 10.0 and summary["max"] == 30.0
    assert summary["median"] == 20.0


def test_measurements_respect_the_limit_newest_first(client, session_factory):
    _seed(
        session_factory,
        [_scalar_run(f"20USEM0000{i:04d}", f"L{i}", float(i), days_ago=i) for i in range(1, 6)],
    )
    body = client.get(
        "/api/stats/measurements",
        params={"test_type": "MODULE_BOW", "result": "BOW", "limit": 2},
    ).json()
    assert [v["value"] for v in body["values"]] == [1.0, 2.0]
    assert body["truncated"] is True


def test_non_numeric_and_missing_results_are_skipped(client, session_factory):
    weird = TestRunEvidenceRecord(
        component_sn="20USEM00000009",
        test_type="MODULE_BOW",
        passed=True,
        external_ref="W1",
        measured_at=datetime(2026, 7, 1),
        payload={
            "results": {"BOW": {"nested": "dict"}},
            "result_meta": {"BOW": {"name": "Bow [um]", "value_type": "single"}},
            "detail_synced": True,
        },
    )
    _seed(session_factory, [weird, _scalar_run("20USEM00000001", "S1", 5.0)])
    body = client.get(
        "/api/stats/measurements",
        params={"test_type": "MODULE_BOW", "result": "BOW"},
    ).json()
    assert [v["value"] for v in body["values"]] == [5.0]


def test_unknown_test_type_yields_an_empty_series(client):
    body = client.get(
        "/api/stats/measurements",
        params={"test_type": "NOPE", "result": "NOPE"},
    ).json()
    assert body["kind"] == "scalar"
    assert body["values"] == [] and body["curves"] == []
