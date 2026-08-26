"""Withdrawn PDB test runs must not count as evidence anywhere.

The PDB marks a retracted test run with `state='deleted'` and keeps serving it
from `getComponent`, so it reaches the mirror exactly like a valid run. Until
the mirror grew a state column, a retracted measurement was indistinguishable
from a real one: on the owner's live mirror that is 102 of 14 759 runs — 13% of
all `GLUE_WEIGHT` and 25% of all `MODULE_BOW`, including 14 of the 15 runs in
the suspicious "1.859" block the owner had spotted.

Covered here, layer by layer: the fetch maps the state, the upsert stores it
(including the case where the payload is deliberately left untouched), an
existing database is backfilled without a re-sync, and the state then removes
the run from the stage gate and from the measurement statistics — while the
run itself stays visible on the endpoint that lists mirrored runs, marked.

The worksheet's own behaviour lives in `test_preview_worksheet.py`.
"""

from datetime import datetime, timezone

import pytest
from authutil import authenticate
from sqlalchemy import select, text

from app.db import Base, ensure_phase0_sqlite_schema, make_engine, make_session_factory
from app.measurement_stats import measurement_dimensions, measurement_series
from app.models import Component, TestRunEvidence
from app.pdb_test_evidence import fetch_test_run_evidence
from app.stage_service import satisfied_test_results
from app.test_run_evidence import (
    TestRunEvidenceRecord,
    is_withdrawn,
    upsert_test_run_evidence,
)

SN = "20USE5L0000031"


class _Gateway:
    """Minimal stand-in for the PDB gateway. Never reaches a network."""

    is_configured = True

    def __init__(self, payload):
        self._payload = payload

    def client(self):
        return self

    def get(self, route, json=None):  # noqa: A002 - mirrors the itkdb signature
        assert route == "getComponent"
        return self._payload


def _run(ref, state, *, passed=True):
    return {
        "id": ref,
        "state": state,
        "passed": passed,
        "problems": False,
        "date": "2024-11-12T08:20:00Z",
    }


# --- Mirroring the state -----------------------------------------------------


def test_fetch_maps_the_pdb_run_state_onto_the_record():
    gateway = _Gateway(
        {
            "tests": [
                {
                    "testType": "GLUE_WEIGHT",
                    "testRuns": [_run("RUN-LIVE", "ready"), _run("RUN-GONE", "deleted")],
                }
            ]
        }
    )
    records = {record.external_ref: record for record in fetch_test_run_evidence(gateway, SN)}
    assert records["RUN-LIVE"].run_state == "ready"
    assert records["RUN-GONE"].run_state == "deleted"
    # The payload copy stays: the incremental sweep fingerprints it.
    assert records["RUN-GONE"].payload["state"] == "deleted"


@pytest.mark.parametrize("raw", [None, "", 42, {"code": "deleted"}])
def test_a_malformed_state_becomes_unknown_rather_than_a_guess(raw):
    gateway = _Gateway(
        {"tests": [{"testType": "GLUE_WEIGHT", "testRuns": [{"id": "R", "state": raw}]}]}
    )
    (record,) = fetch_test_run_evidence(gateway, SN)
    assert record.run_state is None
    assert is_withdrawn(record.run_state) is False


def test_upsert_stores_and_later_updates_the_run_state(session_factory):
    record = TestRunEvidenceRecord(
        component_sn=SN,
        test_type="GLUE_WEIGHT",
        passed=True,
        external_ref="RUN-1",
        run_state="ready",
        payload={"state": "ready", "results": {"GW_GLUE_H1": 0.151}},
    )
    with session_factory() as session:
        upsert_test_run_evidence(session, [record])
        session.commit()

    # A withdrawal arrives on the cheap listing path, which may legitimately
    # skip the detail fetch — `detail_omitted=True` leaves the payload alone.
    # The state must be written anyway, or the retraction is silently dropped.
    with session_factory() as session:
        stats = upsert_test_run_evidence(
            session,
            [
                TestRunEvidenceRecord(
                    component_sn=SN,
                    test_type="GLUE_WEIGHT",
                    passed=True,
                    external_ref="RUN-1",
                    run_state="deleted",
                    payload={},
                    detail_omitted=True,
                )
            ],
        )
        session.commit()
    assert (stats.created, stats.updated, stats.unchanged) == (0, 1, 0)

    with session_factory() as session:
        row = session.scalar(select(TestRunEvidence))
    assert row.run_state == "deleted"
    # The mirrored measurements were not thrown away with the retraction.
    assert row.payload["results"] == {"GW_GLUE_H1": 0.151}


# --- Retrofitting an existing database ---------------------------------------


def _legacy_evidence_table(engine):
    """The `test_run_evidence` table as it looked before the state column."""
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE test_run_evidence ("
                " id INTEGER NOT NULL PRIMARY KEY,"
                " component_sn VARCHAR(20) NOT NULL,"
                " test_type VARCHAR(64) NOT NULL,"
                " passed BOOLEAN NOT NULL,"
                " source VARCHAR(24) NOT NULL,"
                " external_ref VARCHAR(64),"
                " payload JSON NOT NULL,"
                " measured_at DATETIME,"
                " synced_at DATETIME NOT NULL)"
            )
        )


def test_retrofit_adds_the_column_and_backfills_it_from_the_stored_payloads(tmp_path):
    """The state has been in the mirrored payload all along, so an existing
    database can be corrected without a full re-sync — which on the owner's
    mirror means 102 rows fixed the moment the app next starts."""
    engine = make_engine(f"sqlite:///{tmp_path / 'legacy-evidence.db'}")
    _legacy_evidence_table(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO test_run_evidence "
                "(id, component_sn, test_type, passed, source, external_ref, payload, synced_at)"
                " VALUES "
                "(1, '20USE5L0000031', 'GLUE_WEIGHT', 1, 'pdb', 'R1',"
                " '{\"state\": \"deleted\"}', '2026-08-26 10:00:00'),"
                "(2, '20USE5L0000031', 'GLUE_WEIGHT', 1, 'pdb', 'R2',"
                " '{\"state\": \"ready\"}', '2026-08-26 10:00:00'),"
                # No state key at all: stays unknown, which still counts.
                "(3, '20USE5L0000031', 'MODULE_BOW', 1, 'pdb', 'R3',"
                " '{\"problems\": false}', '2026-08-26 10:00:00')"
            )
        )

    ensure_phase0_sqlite_schema(engine)
    ensure_phase0_sqlite_schema(engine)  # every later app start

    with engine.connect() as conn:
        assert dict(
            conn.execute(text("SELECT external_ref, run_state FROM test_run_evidence")).all()
        ) == {"R1": "deleted", "R2": "ready", "R3": None}


def test_retrofit_never_overwrites_a_state_a_newer_sync_already_wrote(tmp_path):
    """A row whose column is already set is left alone, so a re-sync that has
    seen a *newer* truth than the stored payload cannot be rolled back by a
    later application start."""
    engine = make_engine(f"sqlite:///{tmp_path / 'fresh-evidence.db'}")
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    with factory() as session:
        session.add(
            TestRunEvidence(
                component_sn=SN,
                test_type="GLUE_WEIGHT",
                passed=True,
                source="pdb",
                external_ref="R1",
                run_state="deleted",
                payload={"state": "ready"},
            )
        )
        session.commit()

    ensure_phase0_sqlite_schema(engine)

    with factory() as session:
        assert session.scalar(select(TestRunEvidence)).run_state == "deleted"


# --- What the state then changes ---------------------------------------------


def _mirror(session, *, test_type, ref, passed, run_state, measured_at, results):
    session.add(
        TestRunEvidence(
            component_sn=SN,
            test_type=test_type,
            passed=passed,
            source="pdb",
            external_ref=ref,
            run_state=run_state,
            measured_at=measured_at,
            payload={"state": run_state, "results": results, "detail_synced": True},
        )
    )


def test_a_withdrawn_run_does_not_satisfy_a_required_test(session_factory):
    """The stage gate is the sharpest consequence: a retracted measurement must
    not be able to move a module forward."""
    with session_factory() as session:
        _mirror(
            session,
            test_type="GLUE_WEIGHT",
            ref="RUN-GONE",
            passed=True,
            run_state="deleted",
            measured_at=datetime(2024, 11, 12, tzinfo=timezone.utc),
            results={"GW_GLUE_H1": 1.859},
        )
        session.commit()
        assert satisfied_test_results(session, SN) == {}

        _mirror(
            session,
            test_type="GLUE_WEIGHT",
            ref="RUN-LIVE",
            passed=False,
            run_state="ready",
            measured_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            results={"GW_GLUE_H1": 0.151},
        )
        session.commit()
        # The live run decides, even though the withdrawn one is "newer" and
        # claims to have passed.
        assert satisfied_test_results(session, SN) == {"GLUE_WEIGHT": False}


def test_withdrawn_runs_are_excluded_from_the_measurement_statistics(
    client, session_factory
):
    """The owner's "suspicious block of values" was 14 already-retracted runs.
    A distribution that includes them describes a production problem that does
    not exist."""
    with session_factory() as session:
        session.add(
            Component(
                sn=SN,
                component_type="MODULE",
                type_code="R5M1_HALFMODULE",
                stage="GLUED",
                location="TUDO",
                institute_code="TUDO",
            )
        )
        for index in range(3):
            _mirror(
                session,
                test_type="GLUE_WEIGHT",
                ref=f"RUN-GONE-{index}",
                passed=True,
                run_state="deleted",
                measured_at=datetime(2024, 11, 12, tzinfo=timezone.utc),
                results={"GW_GLUE_H1": 1.859},
            )
        _mirror(
            session,
            test_type="GLUE_WEIGHT",
            ref="RUN-LIVE",
            passed=True,
            run_state="ready",
            measured_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            results={"GW_GLUE_H1": 0.151},
        )
        session.commit()

        series = measurement_series(
            session, test_type="GLUE_WEIGHT", result_code="GW_GLUE_H1"
        )
        assert [value.value for value in series.values] == [0.151]
        assert series.summary["count"] == 1

        dimensions = measurement_dimensions(session, institute_code="TUDO")
        glue = next(entry for entry in dimensions if entry["test_type"] == "GLUE_WEIGHT")
        assert glue["results"][0]["runs"] == 1


def test_a_withdrawn_run_stays_listed_by_the_tests_endpoint_but_carries_its_state(
    client, session_factory
):
    """Judgement call (a): the run is not erased. The PDB still holds it, and
    hiding it would be its own kind of false statement — so it stays in the
    mirrored-run list with the state that says not to trust it."""
    with session_factory() as session:
        _mirror(
            session,
            test_type="GLUE_WEIGHT",
            ref="RUN-GONE",
            passed=True,
            run_state="deleted",
            measured_at=datetime(2024, 11, 12, tzinfo=timezone.utc),
            results={"GW_GLUE_H1": 1.859},
        )
        _mirror(
            session,
            test_type="GLUE_WEIGHT",
            ref="RUN-LIVE",
            passed=True,
            run_state="ready",
            measured_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            results={"GW_GLUE_H1": 0.151},
        )
        session.commit()

    authenticate(client, session_factory, role="viewer")
    body = client.get(f"/api/components/{SN}/tests").json()
    states = {run["external_ref"]: run["run_state"] for run in body}
    assert states == {"RUN-GONE": "deleted", "RUN-LIVE": "ready"}
