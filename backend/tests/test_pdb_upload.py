import pytest

from app.pdb_upload import UploadPayloadError, build_upload_test_run_payload


def upload_payload(**overrides) -> dict:
    payload = {
        "component": "TUDO-R5M0-07",
        "testType": "MODULE_METROLOGY",
        "runNumber": 7,
        "date": "2026-07-01T09:30:00.000Z",
        "passed": True,
        "problems": False,
        "properties": {"OPERATOR": "Anna Abel"},
        "results": {"BOW": 12.5},
    }
    payload.update(overrides)
    return payload


def test_build_upload_payload_replaces_local_name_with_resolved_sn():
    raw = upload_payload()

    converted = build_upload_test_run_payload(
        raw,
        component_sn="20USE5M0000701",
        institute_code="TUDO",
    )

    assert converted["component"] == "20USE5M0000701"
    assert converted["testType"] == "MODULE_METROLOGY"
    assert converted["institution"] == "TUDO"
    assert converted["runNumber"] == "7"
    assert converted["passed"] is True
    assert converted["problems"] is False
    assert converted["results"] == {"BOW": 12.5}
    assert raw["component"] == "TUDO-R5M0-07"


def test_build_upload_payload_normalizes_serial_number_variant():
    converted = build_upload_test_run_payload(
        upload_payload(component=None, serialNumber="20USE5M0000701"),
    )

    assert converted["component"] == "20USE5M0000701"
    assert "serialNumber" not in converted


def test_build_upload_payload_uses_institute_fallback_only_when_missing():
    converted = build_upload_test_run_payload(
        upload_payload(institution=""),
        component_sn="20USE5M0000701",
        institute_code="TUDO",
    )

    assert converted["institution"] == "TUDO"


def test_build_upload_payload_merges_reviewed_derived_results_without_mutating_source():
    raw = upload_payload(results={"GW_SENSOR": 7.0162, "GW_GLUE_H1": 9.999})
    derived = {"GW_GLUE_H1": 0.1327, "GW_GLUE_PB": 0.0961}

    converted = build_upload_test_run_payload(
        raw,
        component_sn="20USE5M0000701",
        derived_results=derived,
        derived_result_codes=list(derived),
    )

    assert converted["results"] == {
        "GW_SENSOR": 7.0162,
        "GW_GLUE_H1": 0.1327,
        "GW_GLUE_PB": 0.0961,
    }
    assert raw["results"]["GW_GLUE_H1"] == 9.999
    assert derived == {"GW_GLUE_H1": 0.1327, "GW_GLUE_PB": 0.0961}


def test_build_upload_payload_removes_a_controlled_raw_result_when_no_value_was_derived():
    raw = upload_payload(results={"GW_SENSOR": None, "GW_GLUE_H1": 9.999})

    converted = build_upload_test_run_payload(
        raw,
        component_sn="20USE5M0000701",
        derived_results={},
        derived_result_codes=["GW_GLUE_H1"],
    )

    assert converted["results"] == {"GW_SENSOR": None}
    assert raw["results"] == {"GW_SENSOR": None, "GW_GLUE_H1": 9.999}


@pytest.mark.parametrize(
    ("derived", "message"),
    [
        ([0.1327], "must be an object"),
        ({"not a code": 0.1327}, "canonical PDB codes"),
        ({"GW_GLUE_H1": True}, "finite number"),
        ({"GW_GLUE_H1": float("nan")}, "finite number"),
        ({"GW_GLUE_H1": 10**10000}, "finite number"),
    ],
)
def test_build_upload_payload_rejects_malformed_derived_results(derived, message):
    with pytest.raises(UploadPayloadError, match=message):
        build_upload_test_run_payload(
            upload_payload(),
            component_sn="20USE5M0000701",
            derived_results=derived,
            derived_result_codes=list(derived) if isinstance(derived, dict) else [],
        )


@pytest.mark.parametrize(
    ("codes", "message"),
    [
        ({"GW_GLUE_H1"}, "must be a list"),
        (["not a code"], "canonical PDB codes"),
        (["GW_GLUE_H1", "GW_GLUE_H1"], "must be unique"),
    ],
)
def test_build_upload_payload_rejects_malformed_controlled_result_codes(codes, message):
    with pytest.raises(UploadPayloadError, match=message):
        build_upload_test_run_payload(
            upload_payload(),
            component_sn="20USE5M0000701",
            derived_result_codes=codes,
        )


def test_build_upload_payload_rejects_a_derived_value_outside_the_controlled_codes():
    with pytest.raises(UploadPayloadError, match="controlled result code"):
        build_upload_test_run_payload(
            upload_payload(),
            component_sn="20USE5M0000701",
            derived_results={"GW_GLUE_H1": 0.1327},
            derived_result_codes=[],
        )


def test_build_upload_payload_rejects_non_pdb_ready_payload():
    payload = upload_payload()
    del payload["passed"]

    with pytest.raises(UploadPayloadError, match="Dry-run validation failed"):
        build_upload_test_run_payload(payload, component_sn="20USE5M0000701")


def test_build_upload_payload_rejects_without_resolved_component():
    with pytest.raises(UploadPayloadError, match="not resolved"):
        build_upload_test_run_payload(upload_payload())
