"""The component history: one chronological record of what happened to a part.

Everything the mirror knows about a component's life is already stored, but it
was scattered across three read models — the stage log fed only the statistics
screen, the runs lived behind the worksheet, and nothing put them on a shared
time axis. A person asking "what happened to this module, and when" had to
read three panels and merge them in their head.
"""

from datetime import datetime, timezone

import pytest
from authutil import authenticate
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models import Component, StageEvent, TestRunEvidence
from app.pdb_credentials import generate_pdb_credential_encryption_key

MODULE_SN = "20USEM20000041"


@pytest.fixture()
def client() -> TestClient:
    settings = Settings(
        database_url="sqlite:///:memory:",
        pdb_credential_encryption_key=generate_pdb_credential_encryption_key(),
        _env_file=None,
    )
    return TestClient(create_app(settings))


@pytest.fixture()
def as_operator(client) -> TestClient:
    authenticate(client, client.app.state.session_factory, role="operator")
    return client


def _module(session, sn=MODULE_SN, stage="GLUED"):
    component = Component(
        sn=sn,
        component_type="MODULE",
        type_code="R2",
        stage=stage,
        location="TUDO",
        institute_code="TUDO",
        local_name=f"TUDO-{sn[-4:]}",
    )
    session.add(component)
    return component


def _stage(session, sn, stage, at, *, rework=False):
    session.add(
        StageEvent(
            component_sn=sn,
            component_type="MODULE",
            type_code="R2",
            institute_code="TUDO",
            stage=stage,
            entered_at=at,
            rework=rework,
        )
    )


def _run(session, sn, test_type, at, *, passed=True, ref=None, state=None):
    session.add(
        TestRunEvidence(
            component_sn=sn,
            test_type=test_type,
            passed=passed,
            source="pdb",
            external_ref=ref or f"{sn}:{test_type}",
            measured_at=at,
            run_state=state,
        )
    )


def test_history_merges_stages_and_runs_newest_first(as_operator):
    """One axis, both kinds of fact, and the newest thing that happened on top."""
    factory = as_operator.app.state.session_factory
    with factory() as session:
        _module(session)
        _stage(session, MODULE_SN, "HV_TAB_ATTACHED", datetime(2026, 1, 5, 8, 0))
        _run(session, MODULE_SN, "VISUAL_INSPECTION", datetime(2026, 1, 6, 9, 30))
        _stage(session, MODULE_SN, "GLUED", datetime(2026, 2, 1, 10, 0))
        _run(session, MODULE_SN, "GLUE_WEIGHT", datetime(2026, 2, 2, 11, 15), passed=False)
        session.commit()

    body = as_operator.get(f"/api/components/{MODULE_SN}/history").json()

    assert [(e["kind"], e["at"]) for e in body["events"]] == [
        ("test", "2026-02-02T11:15:00"),
        ("stage", "2026-02-01T10:00:00"),
        ("test", "2026-01-06T09:30:00"),
        ("stage", "2026-01-05T08:00:00"),
    ]
    glue = body["events"][0]
    assert glue["test_type"] == "GLUE_WEIGHT"
    assert glue["passed"] is False
    assert body["events"][1]["stage"] == "GLUED"
    assert body["events"][1]["rework"] is False


def test_history_marks_rework_and_withdrawn_runs_without_dropping_them(as_operator):
    """A retracted run is not evidence, but it is history.

    The stage gate ignores a withdrawn run — that is the honest verdict. The
    history must still show that it happened, and say that it was retracted;
    silently omitting it would leave an unexplained gap in the record.
    """
    factory = as_operator.app.state.session_factory
    with factory() as session:
        _module(session)
        _stage(session, MODULE_SN, "GLUED", datetime(2026, 3, 1, 8, 0), rework=True)
        _run(
            session,
            MODULE_SN,
            "MODULE_BOW",
            datetime(2026, 3, 2, 8, 0),
            ref="RUN-WITHDRAWN",
            state="deleted",
        )
        session.commit()

    events = as_operator.get(f"/api/components/{MODULE_SN}/history").json()["events"]

    assert [e["kind"] for e in events] == ["test", "stage"]
    assert events[0]["withdrawn"] is True
    assert events[1]["rework"] is True


def test_history_keeps_undated_runs_and_says_they_are_undated(as_operator):
    """Legacy rows carry no measurement time. They belong at the end, marked.

    Dropping them would hide real work; inventing a date would put a run in a
    place the instrument never claimed.
    """
    factory = as_operator.app.state.session_factory
    with factory() as session:
        _module(session)
        _stage(session, MODULE_SN, "GLUED", datetime(2026, 3, 1, 8, 0))
        _run(session, MODULE_SN, "MODULE_METROLOGY", None, ref="RUN-UNDATED")
        session.commit()

    events = as_operator.get(f"/api/components/{MODULE_SN}/history").json()["events"]

    assert events[-1]["kind"] == "test"
    assert events[-1]["at"] is None
    assert events[-1]["test_type"] == "MODULE_METROLOGY"


def test_history_is_scoped_to_the_component_and_404s_for_an_unknown_one(as_operator):
    factory = as_operator.app.state.session_factory
    with factory() as session:
        _module(session)
        _module(session, sn="20USEM20000042")
        _stage(session, MODULE_SN, "GLUED", datetime(2026, 3, 1, 8, 0))
        _stage(session, "20USEM20000042", "BONDED", datetime(2026, 3, 5, 8, 0))
        session.commit()

    events = as_operator.get(f"/api/components/{MODULE_SN}/history").json()["events"]
    assert [e["stage"] for e in events] == ["GLUED"]

    assert as_operator.get("/api/components/20USEM99999999/history").status_code == 404


def test_history_timestamps_are_utc_naive_regardless_of_how_they_were_stored(
    as_operator,
):
    """SQLite keeps naive datetimes, PostgreSQL aware ones. One axis needs one
    reading, or the merge order depends on the engine."""
    factory = as_operator.app.state.session_factory
    with factory() as session:
        _module(session)
        _stage(session, MODULE_SN, "GLUED", datetime(2026, 3, 1, 8, 0, tzinfo=timezone.utc))
        _run(session, MODULE_SN, "GLUE_WEIGHT", datetime(2026, 3, 1, 9, 0))
        session.commit()

    events = as_operator.get(f"/api/components/{MODULE_SN}/history").json()["events"]

    assert [e["at"] for e in events] == ["2026-03-01T09:00:00", "2026-03-01T08:00:00"]
