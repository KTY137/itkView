# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-FileComment: itkflow-70f19e09abc9
"""Detailed test-run mirroring: measured values, properties, attachments.

These are what the glue-weight, metrology and IV views read; the shallow
pass/fail walk stays cheap and must keep working unchanged.
"""

import pytest

from app.pdb_test_evidence import fetch_test_run_evidence

COMPONENT = {
    "serialNumber": "20USEM20000041",
    "tests": [
        {
            "testType": {"code": "GLUE_WEIGHT"},
            "testRuns": [{"id": "RUN-GW", "passed": True, "date": "2023-01-19T08:32:00Z"}],
        },
        {
            "testType": {"code": "MODULE_IV_PS_V1"},
            "testRuns": [{"id": "RUN-IV", "passed": True, "date": "2023-01-24T11:11:00Z"}],
        },
    ],
}

RUN_DETAIL = {
    "RUN-GW": {
        "runNumber": "1",
        "properties": [
            {"code": "GW_METHOD", "name": "Glue application method", "dataType": "string",
             "valueType": "single", "value": "Stencil"},
        ],
        "results": [
            {"code": "GW_GLUE_H1", "name": "Weight of glue under hybrid 1 [g]",
             "dataType": "float", "valueType": "single", "value": 0.166},
            {"code": "GW_GLUE_PB", "name": "Weight of glue under powerboard [g]",
             "dataType": "float", "valueType": "single", "value": 0.132},
            {"code": "GW_HYBRID2", "name": "Weight of hybrid 2 (without tabs) [g]",
             "dataType": "float", "valueType": "single", "value": None},
        ],
        "attachments": [
            {"code": "abc123", "filename": "scale.jpg", "contentType": "image/jpeg",
             "title": None, "description": None},
        ],
    },
    "RUN-IV": {
        "properties": [{"code": "RSERIES", "name": "Rseries [MOhm]", "value": "1.0 MOhm"}],
        "results": [
            {"code": "CURRENT", "name": "Current [nA]", "dataType": "float",
             "valueType": "array", "value": [5.15, -26.41, -36.18]},
            {"code": "VOLTAGE", "name": "Voltage [V]", "dataType": "float",
             "valueType": "array", "value": [0.0, -10.0, -20.0]},
        ],
    },
}


class _FakeClient:
    def __init__(self, component=None, details=None, fail_detail=False):
        self._component = COMPONENT if component is None else component
        self._details = RUN_DETAIL if details is None else details
        self._fail_detail = fail_detail
        self.calls: list[str] = []
        self.requests: list[tuple[str, dict | None]] = []

    def get(self, action, json=None):
        self.calls.append(action)
        self.requests.append((action, json))
        if action == "getComponent":
            return self._component
        if action == "getTestRun":
            if self._fail_detail:
                raise RuntimeError("PDB hiccup")
            return self._details[json["testRun"]]
        raise AssertionError(f"unexpected action {action}")


class _FakeGateway:
    is_configured = True

    def __init__(self, client):
        self._client = client

    def client(self):
        return self._client


def _records(**kwargs):
    client = _FakeClient(**kwargs)
    gateway = _FakeGateway(client)
    return fetch_test_run_evidence(gateway, "20USEM20000041", with_detail=True), client


def test_shallow_walk_makes_one_request():
    client = _FakeClient()
    fetch_test_run_evidence(_FakeGateway(client), "20USEM20000041")
    # The institute-wide sweep runs this per component; a hidden per-run
    # request here would multiply an already long sync by the run count.
    assert client.calls == ["getComponent"]


def test_detail_walk_fetches_each_run():
    _, client = _records()
    assert client.calls == ["getComponent", "getTestRun", "getTestRun"]
    detail_requests = [body for action, body in client.requests if action == "getTestRun"]
    assert all(body["noEosToken"] is True for body in detail_requests)


def test_measured_values_are_keyed_by_code():
    records, _ = _records()
    glue = next(r for r in records if r.test_type == "GLUE_WEIGHT")
    assert glue.payload["results"]["GW_GLUE_H1"] == 0.166
    assert glue.payload["results"]["GW_GLUE_PB"] == 0.132


def test_unmeasured_results_are_kept_as_none():
    """A missing weight is not the same as a weight of zero."""
    records, _ = _records()
    glue = next(r for r in records if r.test_type == "GLUE_WEIGHT")
    assert "GW_HYBRID2" in glue.payload["results"]
    assert glue.payload["results"]["GW_HYBRID2"] is None


def test_result_names_carry_the_unit():
    records, _ = _records()
    glue = next(r for r in records if r.test_type == "GLUE_WEIGHT")
    assert glue.payload["result_meta"]["GW_GLUE_H1"]["name"].endswith("[g]")


def test_properties_are_mirrored():
    records, _ = _records()
    glue = next(r for r in records if r.test_type == "GLUE_WEIGHT")
    assert glue.payload["properties"]["GW_METHOD"] == "Stencil"


def test_attachment_metadata_is_mirrored_without_bytes():
    records, _ = _records()
    glue = next(r for r in records if r.test_type == "GLUE_WEIGHT")
    attachment = glue.payload["attachments"][0]
    assert attachment["code"] == "abc123"
    assert attachment["content_type"] == "image/jpeg"
    assert attachment["filename"] == "scale.jpg"


def test_attachment_type_and_safe_url_metadata_are_retained():
    details = {
        **RUN_DETAIL,
        "RUN-GW": {
            **RUN_DETAIL["RUN-GW"],
            "attachments": [
                {
                    "code": "eos-1",
                    "filename": "image.png",
                    "contentType": "image/png",
                    "type": "eos",
                    "url": "https://eosatlas.cern.ch/eos/image.png?signature=must-not-persist",
                }
            ],
        },
    }
    records, _ = _records(details=details)
    attachment = next(r for r in records if r.external_ref == "RUN-GW").payload["attachments"][0]

    assert attachment["type"] == "eos"
    assert attachment["source"] == "pdb"
    assert attachment["url"] == "https://eosatlas.cern.ch/eos/image.png"


def test_result_urls_become_deduplicated_share_link_descriptors():
    details = {
        **RUN_DETAIL,
        "RUN-GW": {
            **RUN_DETAIL["RUN-GW"],
            "results": [
                {
                    "code": "URLS",
                    "name": "Visual inspection images",
                    "value": [
                        "https://cernbox.cern.ch/s/public/photo-1.jpg",
                        "failed",
                        "https://cernbox.cern.ch/s/public/photo-1.jpg",
                        "https://cernbox.cern.ch/s/public/photo-2.png",
                    ],
                }
            ],
            "attachments": [],
        },
    }
    records, _ = _records(details=details)
    attachments = next(r for r in records if r.external_ref == "RUN-GW").payload["attachments"]

    assert len(attachments) == 2
    assert {entry["source"] for entry in attachments} == {"share_link"}
    assert {entry["type"] for entry in attachments} == {"share_link"}
    assert all(len(entry["code"]) == 64 for entry in attachments)
    assert all(entry["url"].startswith("https://cernbox.cern.ch/") for entry in attachments)


def test_iv_arrays_survive_intact():
    """The whole point of mirroring detail: plotting a curve without re-fetching."""
    records, _ = _records()
    iv = next(r for r in records if r.test_type == "MODULE_IV_PS_V1")
    assert iv.payload["results"]["CURRENT"] == [5.15, -26.41, -36.18]
    assert iv.payload["results"]["VOLTAGE"] == [0.0, -10.0, -20.0]


def test_a_failed_detail_call_still_yields_pass_fail():
    records, _ = _records(fail_detail=True)
    assert len(records) == 2
    assert all(record.passed for record in records)
    # Degraded, not lost: the stage engine keeps working on pass/fail alone.
    assert all("results" not in record.payload for record in records)


def test_run_number_is_kept_when_present():
    records, _ = _records()
    glue = next(r for r in records if r.test_type == "GLUE_WEIGHT")
    assert glue.payload["run_number"] == "1"


def test_runs_without_detail_keep_state_fields():
    records, _ = _records()
    for record in records:
        assert "state" in record.payload and "problems" in record.payload


# --- unreachable vs. empty -------------------------------------------------


class _DeadClient:
    def get(self, action, json=None):
        raise RuntimeError("connection reset")


class _DeadGateway:
    is_configured = True

    def client(self):
        return _DeadClient()


def test_a_sweep_treats_an_unreachable_pdb_as_no_records():
    """One bad component must not abort a whole-institute sweep."""
    assert fetch_test_run_evidence(_DeadGateway(), "SN") == []


def test_strict_mode_reports_an_unreachable_pdb():
    """A person who pressed sync on one module is owed the truth.

    Returning [] here is what makes an outage indistinguishable from a module
    that genuinely has no tests.
    """
    from app.pdb_test_evidence import PdbEvidenceUnavailable

    with pytest.raises(PdbEvidenceUnavailable):
        fetch_test_run_evidence(_DeadGateway(), "SN", strict=True)


def test_strict_mode_reports_a_missing_connection():
    from app.pdb_test_evidence import PdbEvidenceUnavailable

    class _Unconfigured:
        is_configured = False

    with pytest.raises(PdbEvidenceUnavailable, match="No personal PDB connection"):
        fetch_test_run_evidence(_Unconfigured(), "SN", strict=True)


def test_strict_failure_does_not_chain_the_itkdb_error():
    """An itkdb error can carry the request, and the request can carry codes."""
    from app.pdb_test_evidence import PdbEvidenceUnavailable

    try:
        fetch_test_run_evidence(_DeadGateway(), "SN", strict=True)
    except PdbEvidenceUnavailable as exc:
        assert exc.__cause__ is None
        assert "connection reset" not in str(exc)
    else:
        raise AssertionError("expected PdbEvidenceUnavailable")
