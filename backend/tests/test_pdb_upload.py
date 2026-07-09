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


def test_build_upload_payload_rejects_non_pdb_ready_payload():
    payload = upload_payload()
    del payload["passed"]

    with pytest.raises(UploadPayloadError, match="Dry-run validation failed"):
        build_upload_test_run_payload(payload, component_sn="20USE5M0000701")


def test_build_upload_payload_rejects_without_resolved_component():
    with pytest.raises(UploadPayloadError, match="not resolved"):
        build_upload_test_run_payload(upload_payload())
