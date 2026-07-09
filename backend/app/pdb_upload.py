"""Build canonical PDB test-run upload payloads from parsed ingest files.

This module is pure conversion logic: no database access, no PDB client. The
worker revalidates the ingest file, then the real submitter uses this builder
to send a normalized `uploadTestRunResults` body instead of the raw instrument
JSON. In particular, locally named files are uploaded with the resolved PDB
serial number from the mirror.
"""

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from app.ingestion import parse_payload


class UploadPayloadError(ValueError):
    """Raised when an ingest payload cannot become a PDB upload body."""


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def build_upload_test_run_payload(
    payload: Mapping[str, Any],
    *,
    component_sn: str | None = None,
    institute_code: str | None = None,
) -> dict[str, Any]:
    """Return a normalized `uploadTestRunResults` payload.

    `component_sn` is the mirror-resolved target. It deliberately wins over
    whatever the uploaded file carried, so local names and `serialNumber`
    variants cannot leak into the write call.
    """
    raw = dict(payload)
    parsed = parse_payload(raw)
    if parsed.issues:
        raise UploadPayloadError("Dry-run validation failed: " + "; ".join(parsed.issues))

    sn = component_sn or parsed.component_sn
    if sn is None:
        raise UploadPayloadError("Upload target component is not resolved to a PDB serial number.")
    if parsed.test_type is None:
        raise UploadPayloadError("Upload payload is missing test type.")
    if parsed.passed is None:
        raise UploadPayloadError("Upload payload is missing boolean passed result.")

    results = raw.get("results")
    if not isinstance(results, Mapping) or not results:
        raise UploadPayloadError("Upload payload is missing non-empty results.")

    upload = deepcopy(raw)
    upload["component"] = sn
    upload.pop("serialNumber", None)
    upload["testType"] = parsed.test_type
    upload["passed"] = parsed.passed
    upload["properties"] = _dict_or_empty(raw.get("properties"))
    upload["results"] = deepcopy(dict(results))

    if parsed.run_number is not None:
        upload["runNumber"] = parsed.run_number
    if parsed.measured_at is not None:
        upload["date"] = parsed.measured_at
    if parsed.problems is not None:
        upload["problems"] = parsed.problems

    institution = parsed.institution or institute_code
    if institution is not None:
        upload["institution"] = institution

    return upload
