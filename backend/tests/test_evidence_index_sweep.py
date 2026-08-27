"""The institute evidence sweep as index-then-bulk instead of per component.

Every fake here answers offline. The response shapes are the ones `itkdb`
itself sends and reads (`itkdb/client.py::_get_duplicate_test_runs`):
`listTestRunsByComponent` takes a `filterMap` and returns test-run entries
carrying at least `id`; `getTestRunBulk` takes `{"testRun": [...]}` and returns
full run objects. None of it can be validated against the live PDB, so these
tests spend most of their weight on the degenerate answers and on proving that
each one degrades to the proven per-component sweep rather than mirroring less.
"""

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import Component, SyncJob, TestRunEvidence
from app.pdb_test_evidence import IndexedTestRun
from app.sync_jobs import MirroredEvidence, index_answer_is_trustworthy, run_evidence_sync_job

# --- fake PDB ---------------------------------------------------------------


def make_run(
    run_id: str,
    *,
    test_type: str = "VISUAL_INSPECTION",
    passed: bool = True,
    state: str | None = "ready",
    date: str | None = "2026-08-01T10:00:00Z",
    problems: bool = False,
    results: list[dict] | None = None,
):
    return {
        "id": run_id,
        "test_type": test_type,
        "passed": passed,
        "state": state,
        "date": date,
        "problems": problems,
        "results": results if results is not None else [{"code": "SCORE", "value": 1}],
    }


class _PagedAnswer:
    """Stand-in for itkdb's `PagedResponse` (only `.data` / `.page_info`)."""

    def __init__(self, items, page_info):
        self.data = items
        self.page_info = page_info


class _IndexClient:
    """Serves the batched index, bulk detail, and the per-component fallback."""

    def __init__(self, runs_by_sn: dict[str, list[dict]]):
        self.runs_by_sn = runs_by_sn
        self.index_requests: list[list[str]] = []
        self.bulk_requests: list[list[str]] = []
        self.component_requests: list[str] = []
        self.detail_requests: list[str] = []

    # -- payload shaping ---------------------------------------------------
    def index_entry(self, sn: str, run: dict) -> dict:
        return {
            "id": run["id"],
            "testType": {"code": run["test_type"]},
            "component": {"serialNumber": sn},
            "passed": run["passed"],
            "problems": run["problems"],
            "state": run["state"],
            "date": run["date"],
        }

    def listing_entry(self, run: dict) -> dict:
        return {
            "id": run["id"],
            "passed": run["passed"],
            "problems": run["problems"],
            "state": run["state"],
            "date": run["date"],
        }

    def detail_entry(self, run: dict) -> dict:
        return {"id": run["id"], "results": run["results"], "runNumber": 1}

    # -- endpoints ---------------------------------------------------------
    def index(self, serial_numbers, page_index, page_size):
        entries = [
            self.index_entry(sn, run)
            for sn in serial_numbers
            for run in self.runs_by_sn.get(sn, [])
        ]
        return entries[page_index * page_size : (page_index + 1) * page_size], len(entries)

    def get(self, action, json=None):
        if action == "listTestRunsByComponent":
            serials = json["filterMap"]["serialNumber"]
            assert isinstance(serials, list)
            self.index_requests.append(list(serials))
            page = json.get("pageInfo") or {}
            entries, _total = self.index(
                serials, page.get("pageIndex", 0), page.get("pageSize", 1000)
            )
            return entries
        if action == "getTestRunBulk":
            ids = list(json["testRun"])
            self.bulk_requests.append(ids)
            by_id = {run["id"]: run for runs in self.runs_by_sn.values() for run in runs}
            return [self.detail_entry(by_id[rid]) for rid in ids if rid in by_id]
        if action == "getComponent":
            sn = json["component"]
            self.component_requests.append(sn)
            by_type: dict[str, list[dict]] = {}
            for run in self.runs_by_sn.get(sn, []):
                by_type.setdefault(run["test_type"], []).append(self.listing_entry(run))
            return {
                "tests": [
                    {"testType": {"code": test_type}, "testRuns": runs}
                    for test_type, runs in by_type.items()
                ]
            }
        if action == "getTestRun":
            run_id = json["testRun"]
            self.detail_requests.append(run_id)
            for runs in self.runs_by_sn.values():
                for run in runs:
                    if run["id"] == run_id:
                        return self.detail_entry(run)
            return None
        raise AssertionError(f"unexpected request {action}")


class _Gateway:
    is_configured = True

    def __init__(self, client):
        self._client = client

    def client(self):
        return self._client


SNS = ["20USEM00000801", "20USEM00000802", "20USEM00000803"]


# --- fixtures ---------------------------------------------------------------


class _NoopManager:
    """The endpoint only has to mint the job row; this test drives the sweep
    itself. Letting the real manager also run it would put two executions on
    the same in-memory SQLite connection."""

    def start(self, job_id: int, fetcher) -> None:  # pragma: no cover - unused
        pass

    def start_evidence(self, job_id: int) -> None:
        pass


@pytest.fixture()
def sweep(client: TestClient, session_factory, tudo: dict, as_operator, tmp_path, monkeypatch):
    """Run one institute evidence sweep against a fake client."""

    monkeypatch.setattr("app.sync_jobs.sleep", lambda seconds: None)
    client.app.state.sync_job_manager = _NoopManager()
    settings = client.app.state.settings
    settings.attachment_dir = str(tmp_path / "attachments")
    settings.sync_fetch_concurrency = 1

    def _run(fake_client, *, serial_numbers=SNS, on_transient=None, **overrides):
        for key, value in overrides.items():
            setattr(settings, key, value)
        with session_factory() as session:
            for sn in serial_numbers:
                if session.get(Component, sn) is None:
                    session.add(
                        Component(
                            sn=sn,
                            component_type="MODULE",
                            type_code="R5M0",
                            stage="GLUED",
                            location="TUDO",
                            institute_code="TUDO",
                        )
                    )
            session.commit()
        job_id = client.post("/api/sync/jobs/evidence/TUDO").json()["id"]
        run_evidence_sync_job(
            session_factory,
            settings,
            lambda _settings, _codes: _Gateway(fake_client),
            job_id,
            on_transient,
        )
        with session_factory() as session:
            return session.get(SyncJob, job_id)

    return _run


def mirrored(session_factory) -> dict[str, TestRunEvidence]:
    with session_factory() as session:
        rows = session.scalars(select(TestRunEvidence)).all()
        return {row.external_ref: row for row in rows}


def mirror_run(
    session_factory,
    sn: str,
    run_id: str,
    *,
    test_type: str = "VISUAL_INSPECTION",
    passed: bool = True,
    state: str | None = "ready",
    problems: bool = False,
    measured_at: str | None = "2026-08-01T10:00:00",
    detail_synced: bool = True,
    results: dict | None = None,
):
    """Put a run into the mirror the way a previous sweep would have."""

    payload: dict = {"state": state, "problems": problems}
    if results is not None:
        payload["results"] = results
    if detail_synced:
        payload["detail_synced"] = True
    with session_factory() as session:
        session.add(
            TestRunEvidence(
                component_sn=sn,
                test_type=test_type,
                passed=passed,
                source="pdb",
                external_ref=run_id,
                run_state=state,
                measured_at=datetime.fromisoformat(measured_at) if measured_at else None,
                payload=payload,
            )
        )
        session.commit()


# --- the happy path ---------------------------------------------------------


def test_index_sweep_mirrors_every_component_from_one_index_and_one_bulk_request(
    sweep, session_factory
):
    fake = _IndexClient(
        {
            SNS[0]: [make_run("run-a")],
            SNS[1]: [make_run("run-b"), make_run("run-c", test_type="IV_TEST")],
            SNS[2]: [make_run("run-d")],
        }
    )

    job = sweep(fake)

    assert job.status == "succeeded", job.error
    assert job.result["components_processed"] == 3
    assert fake.index_requests == [SNS]
    assert len(fake.bulk_requests) == 1
    assert sorted(fake.bulk_requests[0]) == ["run-a", "run-b", "run-c", "run-d"]
    # Exactly one `getComponent`: the calibration probe that checks the index
    # against the endpoint we already trust. No per-run `getTestRun` at all.
    assert fake.component_requests == [SNS[0]]
    assert fake.detail_requests == []

    rows = mirrored(session_factory)
    assert set(rows) == {"run-a", "run-b", "run-c", "run-d"}
    assert rows["run-c"].test_type == "IV_TEST"
    assert rows["run-b"].component_sn == SNS[1]
    assert rows["run-a"].payload["results"] == {"SCORE": 1}
    assert rows["run-a"].payload["detail_synced"] is True
    assert rows["run-a"].run_state == "ready"
    assert rows["run-a"].measured_at is not None


def test_index_sweep_skips_bulk_detail_for_runs_the_mirror_already_holds(
    sweep, session_factory
):
    """The incremental contract survives the move to batched endpoints."""

    fake = _IndexClient({SNS[0]: [make_run("run-a")], SNS[1]: [make_run("run-b")]})
    mirror_run(session_factory, SNS[0], "run-a", results={"SCORE": 1})

    job = sweep(fake, serial_numbers=SNS[:2])

    assert job.status == "succeeded", job.error
    assert fake.bulk_requests == [["run-b"]]
    assert mirrored(session_factory)["run-a"].payload["results"] == {"SCORE": 1}


def test_a_repeat_sweep_of_an_unchanged_mirror_asks_for_no_detail_at_all(
    sweep, session_factory
):
    fake = _IndexClient({SNS[0]: [make_run("run-a")], SNS[1]: [make_run("run-b")]})
    mirror_run(session_factory, SNS[0], "run-a")
    mirror_run(session_factory, SNS[1], "run-b")

    job = sweep(fake, serial_numbers=SNS[:2])

    assert job.status == "succeeded", job.error
    assert fake.bulk_requests == []
    assert fake.detail_requests == []
    assert fake.index_requests == [SNS[:2]]


# --- withdrawal must survive the cheap path ---------------------------------


def test_a_withdrawal_is_detected_on_the_batched_index_path(sweep, session_factory):
    """`state='deleted'` arrives on the cheap listing data, which is now the
    index. Mirroring it is what stops a retracted measurement counting."""

    fake = _IndexClient(
        {SNS[0]: [make_run("run-a", state="deleted")], SNS[1]: [make_run("run-b")]}
    )
    mirror_run(session_factory, SNS[0], "run-a", state="ready")
    mirror_run(session_factory, SNS[1], "run-b")

    job = sweep(fake, serial_numbers=SNS[:2])

    assert job.status == "succeeded", job.error
    rows = mirrored(session_factory)
    assert rows["run-a"].run_state == "deleted"
    assert rows["run-a"].payload["state"] == "deleted"


def test_requested_to_delete_stays_a_live_run_through_the_index(sweep, session_factory):
    """Only the terminal `deleted` retracts. `requestedToDelete` is a pending
    request the PDB has not acted on and must keep counting."""

    fake = _IndexClient(
        {
            SNS[0]: [make_run("run-a", state="requestedToDelete")],
            SNS[1]: [make_run("run-b")],
        }
    )

    job = sweep(fake, serial_numbers=SNS[:2])

    assert job.status == "succeeded", job.error
    assert mirrored(session_factory)["run-a"].run_state == "requestedToDelete"


# --- unverifiable answers fall back ------------------------------------------


class _NoIndexClient(_IndexClient):
    """A PDB that does not serve the batched endpoints at all."""

    def get(self, action, json=None):
        if action in {"listTestRunsByComponent", "getTestRunBulk"}:
            raise RuntimeError("uu-app: command not found")
        return super().get(action, json=json)


def test_an_unavailable_index_endpoint_falls_back_to_the_per_component_sweep(
    sweep, session_factory
):
    fake = _NoIndexClient({sn: [make_run(f"run-{sn}")] for sn in SNS})

    job = sweep(fake)

    assert job.status == "succeeded", job.error
    assert fake.index_requests == []  # the request itself raised
    assert fake.component_requests == SNS
    assert sorted(fake.detail_requests) == sorted(f"run-{sn}" for sn in SNS)
    assert set(mirrored(session_factory)) == {f"run-{sn}" for sn in SNS}


def test_a_component_whose_mirrored_run_the_index_omits_is_re_read_per_component(
    sweep, session_factory
):
    """The index must account for every run we already know is live. A gap is
    unverifiable — the run could have been withdrawn, or the filter could have
    dropped it — so that one component goes back through `getComponent`."""

    fake = _IndexClient(
        {SNS[0]: [make_run("run-a")], SNS[1]: [make_run("run-b")], SNS[2]: []}
    )
    mirror_run(session_factory, SNS[2], "run-lost")

    job = sweep(fake)

    assert job.status == "succeeded", job.error
    assert fake.index_requests == [SNS]
    # SNS[0] is the calibration probe; SNS[2] is the distrusted component.
    assert fake.component_requests == [SNS[0], SNS[2]]


def test_an_empty_index_answer_without_proof_is_re_read_per_component(
    sweep, session_factory
):
    """"No runs" is the most dangerous answer a filter can silently produce. It
    is only trusted once the same batch proved the multi-serial filter was
    honoured by returning runs for at least two different components."""

    fake = _IndexClient({SNS[0]: [make_run("run-a")], SNS[1]: [], SNS[2]: []})

    job = sweep(fake)

    assert job.status == "succeeded", job.error
    assert fake.component_requests == [SNS[0], SNS[1], SNS[2]]
    assert set(mirrored(session_factory)) == {"run-a"}


def test_an_empty_index_answer_is_trusted_once_the_batch_proved_the_filter(
    sweep, session_factory
):
    fake = _IndexClient(
        {SNS[0]: [make_run("run-a")], SNS[1]: [make_run("run-b")], SNS[2]: []}
    )

    job = sweep(fake)

    assert job.status == "succeeded", job.error
    assert fake.component_requests == [SNS[0]]
    assert job.result["components_processed"] == 3


class _StatelessIndexClient(_IndexClient):
    def index_entry(self, sn, run):
        entry = super().index_entry(sn, run)
        entry.pop("state")
        return entry


def test_an_index_that_disagrees_about_run_state_demotes_the_whole_sweep(
    sweep, session_factory
):
    """Writing `None` over a known state would silently un-withdraw a run, so
    the calibration probe treats a state-free index as a different endpoint."""

    fake = _StatelessIndexClient({sn: [make_run(f"run-{sn}")] for sn in SNS})

    job = sweep(fake)

    assert job.status == "succeeded", job.error
    # The probe read of the first component, then the whole scope again.
    assert fake.component_requests == [SNS[0], *SNS]
    assert all(row.run_state == "ready" for row in mirrored(session_factory).values())


class _DatelessIndexClient(_IndexClient):
    def index_entry(self, sn, run):
        entry = super().index_entry(sn, run)
        entry.pop("date")
        return entry


def test_an_index_that_disagrees_about_timestamps_demotes_the_whole_sweep(
    sweep, session_factory
):
    """`measured_at` decides which run is "latest" everywhere in the app."""

    fake = _DatelessIndexClient({sn: [make_run(f"run-{sn}")] for sn in SNS})

    job = sweep(fake)

    assert job.status == "succeeded", job.error
    assert fake.component_requests == [SNS[0], *SNS]
    assert all(row.measured_at is not None for row in mirrored(session_factory).values())


class _LeakyIndexClient(_IndexClient):
    """Answers with a component nobody asked about — the filter is not honoured."""

    def index(self, serial_numbers, page_index, page_size):
        entries, total = super().index(serial_numbers, page_index, page_size)
        entries.append(self.index_entry("20USEM00009999", make_run("run-foreign")))
        return entries, total + 1


def test_an_index_answering_for_unrequested_components_demotes_the_whole_sweep(
    sweep, session_factory
):
    fake = _LeakyIndexClient({sn: [make_run(f"run-{sn}")] for sn in SNS})

    job = sweep(fake)

    assert job.status == "succeeded", job.error
    assert fake.component_requests == SNS
    assert "run-foreign" not in mirrored(session_factory)


def test_a_metadata_free_answer_that_exactly_fills_the_page_is_refused(
    sweep, session_factory
):
    """Without `pageInfo` a full page is indistinguishable from a truncated
    one, so it may not be trusted — even though it happens to be complete."""

    fake = _IndexClient(
        {
            SNS[0]: [make_run(f"run-a{index}", test_type=f"T{index}") for index in range(5)],
            SNS[1]: [make_run(f"run-b{index}", test_type=f"T{index}") for index in range(5)],
        }
    )

    job = sweep(fake, serial_numbers=SNS[:2], sync_evidence_index_page_size=10)

    assert job.status == "succeeded", job.error
    assert fake.component_requests == SNS[:2]
    assert len(mirrored(session_factory)) == 10


class _PagedIndexClient(_IndexClient):
    def get(self, action, json=None):
        if action != "listTestRunsByComponent":
            return super().get(action, json=json)
        serials = json["filterMap"]["serialNumber"]
        self.index_requests.append(list(serials))
        page = json["pageInfo"]
        entries, total = self.index(serials, page["pageIndex"], page["pageSize"])
        return _PagedAnswer(
            entries,
            {
                "pageIndex": page["pageIndex"],
                "pageSize": page["pageSize"],
                "total": total,
            },
        )


def _many_runs() -> dict[str, list[dict]]:
    """Twelve runs over three components: more than one page of ten."""

    return {
        sn: [
            make_run(f"run-{position}{index}", test_type=f"T{index}")
            for index in range(4)
        ]
        for position, sn in enumerate(SNS)
    }


def test_the_index_walks_every_page_of_a_frozen_paginated_answer(sweep, session_factory):
    fake = _PagedIndexClient(_many_runs())

    job = sweep(fake, sync_evidence_index_page_size=10)

    assert job.status == "succeeded", job.error
    # Twelve runs at ten per page: two requests, and the metadata proves the
    # answer complete, so nothing is re-read per component.
    assert len(fake.index_requests) == 2
    assert len(mirrored(session_factory)) == 12
    assert fake.component_requests == [SNS[0]]


class _DriftingPageClient(_PagedIndexClient):
    """The reported total grows between pages — the answer is unverifiable."""

    def get(self, action, json=None):
        answer = super().get(action, json=json)
        if action == "listTestRunsByComponent" and len(self.index_requests) > 1:
            answer.page_info = {**answer.page_info, "total": answer.page_info["total"] + 5}
        return answer


def test_pagination_metadata_that_drifts_mid_answer_falls_back(sweep, session_factory):
    fake = _DriftingPageClient(_many_runs())

    job = sweep(fake, sync_evidence_index_page_size=10)

    assert job.status == "succeeded", job.error
    assert fake.component_requests == SNS
    assert len(mirrored(session_factory)) == 12


class _DisagreeingIndexClient(_IndexClient):
    """The index and `getComponent` do not tell the same story."""

    def index_entry(self, sn, run):
        entry = super().index_entry(sn, run)
        entry["passed"] = not entry["passed"]
        return entry


def test_a_calibration_probe_mismatch_demotes_the_whole_sweep(sweep, session_factory):
    fake = _DisagreeingIndexClient({sn: [make_run(f"run-{sn}")] for sn in SNS})

    job = sweep(fake)

    assert job.status == "succeeded", job.error
    assert fake.component_requests == [SNS[0], *SNS]
    # Everything came from the trusted per-component path, so `passed` is true.
    assert all(row.passed for row in mirrored(session_factory).values())


# --- bulk detail degradations ------------------------------------------------


class _PartialBulkClient(_IndexClient):
    """The bulk answer omits one requested id."""

    def get(self, action, json=None):
        if action == "getTestRunBulk":
            return [
                entry
                for entry in super().get(action, json=json)
                if entry["id"] != "run-b"
            ]
        return super().get(action, json=json)


def test_bulk_ids_the_answer_omits_fall_back_to_one_get_test_run_each(
    sweep, session_factory
):
    fake = _PartialBulkClient({SNS[0]: [make_run("run-a")], SNS[1]: [make_run("run-b")]})

    job = sweep(fake, serial_numbers=SNS[:2])

    assert job.status == "succeeded", job.error
    assert fake.detail_requests == ["run-b"]
    rows = mirrored(session_factory)
    assert rows["run-b"].payload["results"] == {"SCORE": 1}
    assert rows["run-b"].payload["detail_synced"] is True


class _EmptyBulkClient(_IndexClient):
    def get(self, action, json=None):
        if action == "getTestRunBulk":
            super().get(action, json=json)
            return []
        return super().get(action, json=json)


def test_a_bulk_endpoint_that_returns_no_detail_is_abandoned_after_one_batch(
    sweep, session_factory
):
    fake = _EmptyBulkClient({sn: [make_run(f"run-{sn}")] for sn in SNS})

    job = sweep(fake, sync_evidence_bulk_batch_size=1)

    assert job.status == "succeeded", job.error
    assert len(fake.bulk_requests) == 1
    assert sorted(fake.detail_requests) == sorted(f"run-{sn}" for sn in SNS)
    assert all(row.payload["detail_synced"] for row in mirrored(session_factory).values())


# --- bounds, failure semantics, durability -----------------------------------


def test_index_and_bulk_batches_respect_the_configured_sizes(sweep, session_factory):
    fake = _IndexClient({sn: [make_run(f"run-{sn}")] for sn in SNS})

    job = sweep(fake, sync_evidence_index_batch_size=2, sync_evidence_bulk_batch_size=1)

    assert job.status == "succeeded", job.error
    assert [len(batch) for batch in fake.index_requests] == [2, 1]
    assert [len(batch) for batch in fake.bulk_requests] == [1, 1, 1]


class _DownIndexClient(_IndexClient):
    def get(self, action, json=None):
        if action == "listTestRunsByComponent":
            raise ConnectionResetError("Connection reset by peer")
        return super().get(action, json=json)


def test_a_transient_index_outage_fails_the_job_transiently(sweep):
    """A dead line must not be mistaken for "the endpoint does not exist" and
    quietly demote into as many equally doomed per-component reads."""

    recorded = []
    fake = _DownIndexClient({sn: [make_run(f"run-{sn}")] for sn in SNS})

    job = sweep(fake, on_transient=recorded.append)

    assert job.status == "failed"
    assert fake.component_requests == []
    assert len(recorded) == 1


def test_the_persisted_failure_never_carries_upstream_error_text(sweep):
    class _LeakyError(_IndexClient):
        def get(self, action, json=None):
            if action == "listTestRunsByComponent":
                raise ConnectionResetError(
                    "POST /getTestRun accessCode1=SUPERSECRET1 accessCode2=SUPERSECRET2"
                )
            return super().get(action, json=json)

    job = sweep(_LeakyError({sn: [make_run(f"run-{sn}")] for sn in SNS}))

    assert job.status == "failed"
    blob = repr((job.error, job.message, job.result))
    assert "SUPERSECRET1" not in blob
    assert "accessCode" not in blob


class _BulkDiesAfterFirstBatch(_IndexClient):
    def get(self, action, json=None):
        if action == "getTestRunBulk" and self.bulk_requests:
            raise ConnectionResetError("Connection reset by peer")
        return super().get(action, json=json)


def test_components_finished_before_a_failure_stay_mirrored(sweep, session_factory):
    fake = _BulkDiesAfterFirstBatch({sn: [make_run(f"run-{sn}")] for sn in SNS})

    job = sweep(fake, sync_evidence_index_batch_size=1, sync_evidence_bulk_batch_size=1)

    assert job.status == "failed"
    # The first batch committed before the second one died.
    assert set(mirrored(session_factory)) == {f"run-{SNS[0]}"}


def test_the_per_component_strategy_never_touches_the_batched_endpoints(
    sweep, session_factory
):
    fake = _IndexClient({sn: [make_run(f"run-{sn}")] for sn in SNS})

    job = sweep(fake, sync_evidence_strategy="per_component")

    assert job.status == "succeeded", job.error
    assert fake.index_requests == []
    assert fake.bulk_requests == []
    assert fake.component_requests == SNS


def test_a_mixed_sweep_reports_every_component_exactly_once(sweep, session_factory):
    """Half the batch is trusted, half is re-read; the counter may not double
    count nor lose a component."""

    fake = _IndexClient(
        {SNS[0]: [make_run("run-a")], SNS[1]: [make_run("run-b")], SNS[2]: []}
    )
    mirror_run(session_factory, SNS[2], "run-lost")

    job = sweep(fake)

    assert job.status == "succeeded", job.error
    assert job.result["components_processed"] == 3
    assert job.percent == 100.0


# --- the trust rule, as a unit ----------------------------------------------


def indexed(run_id, *, sn=SNS[0], state="ready", measured_at="2026-08-01T10:00:00"):
    return IndexedTestRun(
        component_sn=sn,
        run_id=run_id,
        test_type="VISUAL_INSPECTION",
        passed=True,
        measured_at=datetime.fromisoformat(measured_at) if measured_at else None,
        run_state=state,
        raw_state=state,
        problems=False,
    )


def mirror_state(**kwargs) -> MirroredEvidence:
    return MirroredEvidence(
        known_flat=kwargs.get("known_flat", {}),
        live_refs=kwargs.get("live_refs", {}),
        run_meta=kwargs.get("run_meta", {}),
    )


def test_trust_rule_rejects_a_component_with_an_unaccounted_live_run():
    mirror = mirror_state(live_refs={SNS[0]: {"run-a", "run-b"}})
    assert not index_answer_is_trustworthy(
        SNS[0], [indexed("run-a")], mirror=mirror, multi_serial_proven=True
    )


def test_trust_rule_ignores_a_mirrored_run_that_is_already_withdrawn():
    """A withdrawal is terminal, so an index that no longer lists the run is
    not evidence of a lossy filter."""

    mirror = mirror_state(
        live_refs={SNS[0]: {"run-a"}},
        run_meta={"run-gone": ("deleted", None), "run-a": ("ready", None)},
    )
    assert index_answer_is_trustworthy(
        SNS[0], [indexed("run-a")], mirror=mirror, multi_serial_proven=True
    )


def test_trust_rule_rejects_an_answer_that_would_forget_a_known_state():
    mirror = mirror_state(
        live_refs={SNS[0]: {"run-a"}}, run_meta={"run-a": ("ready", None)}
    )
    assert not index_answer_is_trustworthy(
        SNS[0], [indexed("run-a", state=None)], mirror=mirror, multi_serial_proven=True
    )


def test_trust_rule_rejects_an_answer_that_would_forget_a_known_timestamp():
    mirror = mirror_state(
        live_refs={SNS[0]: {"run-a"}},
        run_meta={"run-a": ("ready", datetime(2026, 8, 1, 10, 0))},
    )
    assert not index_answer_is_trustworthy(
        SNS[0],
        [indexed("run-a", measured_at=None)],
        mirror=mirror,
        multi_serial_proven=True,
    )


def test_trust_rule_rejects_an_unproven_empty_answer_but_accepts_a_proven_one():
    mirror = mirror_state()
    assert not index_answer_is_trustworthy(
        SNS[0], [], mirror=mirror, multi_serial_proven=False
    )
    assert index_answer_is_trustworthy(
        SNS[0], [], mirror=mirror, multi_serial_proven=True
    )


def test_every_index_page_refreshes_the_durable_heartbeat(
    sweep, session_factory, monkeypatch
):
    """A batch can span several slow pages while no component finishes. Without
    a per-page heartbeat the job row goes quiet past SYNC_HEARTBEAT_GRACE and a
    second app instance reaps a live sync."""

    import app.sync_jobs as sync_jobs

    messages: list[str] = []
    real_update = sync_jobs._update_progress

    def spy(factory, job_id, phase, current, total, *, message=None):
        messages.append(message or "")
        return real_update(factory, job_id, phase, current, total, message=message)

    monkeypatch.setattr(sync_jobs, "_update_progress", spy)

    job = sweep(_PagedIndexClient(_many_runs()), sync_evidence_index_page_size=10)

    assert job.status == "succeeded", job.error
    assert sum(1 for text in messages if "Indexing test runs in batches" in text) >= 2
