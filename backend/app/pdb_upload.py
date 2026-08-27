"""Build canonical PDB test-run upload payloads from parsed ingest files.

This module is pure conversion logic: no database access, no PDB client. The
worker revalidates the ingest file, then the real submitter uses this builder
to send a normalized `uploadTestRunResults` body instead of the raw instrument
JSON. In particular, locally named files are uploaded with the resolved PDB
serial number from the mirror.
"""

import math
import re
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from app.ingestion import parse_payload


class UploadPayloadError(ValueError):
    """Raised when an ingest payload cannot become a PDB upload body."""


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


_RESULT_CODE_RE = re.compile(r"[A-Z][A-Z0-9_]{0,63}\Z")


def _validated_derived_results(value: Any) -> dict[str, int | float]:
    """Validate server-derived result values carried by an outbox action.

    The ingest file remains the immutable received evidence, so derived glue
    weights live beside it on the reviewed action.  This is the boundary where
    those values enter the PDB document: reject malformed or non-finite action
    data rather than forwarding it to itkdb.
    """
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise UploadPayloadError("Derived results must be an object.")

    derived: dict[str, int | float] = {}
    for code, result in value.items():
        if not isinstance(code, str) or _RESULT_CODE_RE.fullmatch(code) is None:
            raise UploadPayloadError("Derived result codes must be canonical PDB codes.")
        try:
            finite = isinstance(result, (int, float)) and math.isfinite(result)
        except OverflowError:
            finite = False
        if isinstance(result, bool) or not finite:
            raise UploadPayloadError(f"Derived result '{code}' must be a finite number.")
        derived[code] = result
    return derived


def _validated_derived_result_codes(value: Any) -> list[str]:
    """Validate the complete set of result codes owned by server formulas."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise UploadPayloadError("Derived result codes must be a list.")
    codes: list[str] = []
    for code in value:
        if not isinstance(code, str) or _RESULT_CODE_RE.fullmatch(code) is None:
            raise UploadPayloadError("Derived result codes must be canonical PDB codes.")
        if code in codes:
            raise UploadPayloadError("Derived result codes must be unique.")
        codes.append(code)
    return codes


def build_upload_test_run_payload(
    payload: Mapping[str, Any],
    *,
    component_sn: str | None = None,
    institute_code: str | None = None,
    derived_results: Mapping[str, Any] | None = None,
    derived_result_codes: list[str] | None = None,
) -> dict[str, Any]:
    """Return a normalized `uploadTestRunResults` payload.

    `component_sn` is the mirror-resolved target. It deliberately wins over
    whatever the uploaded file carried, so local names and `serialNumber`
    variants cannot leak into the write call. `derived_results` comes from the
    server-computed, reviewed outbox action. `derived_result_codes` is the
    complete set of outputs controlled by that formula, including outputs
    with no value because an input was missing. Every controlled code is first
    removed from the received file, then the computed values are merged; a
    stale/raw formula value can therefore never survive by omission.
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
    controlled_codes = _validated_derived_result_codes(derived_result_codes)
    validated_derived = _validated_derived_results(derived_results)
    if not set(validated_derived).issubset(controlled_codes):
        raise UploadPayloadError("Every derived result must name a controlled result code.")
    merged_results = deepcopy(dict(results))
    for code in controlled_codes:
        merged_results.pop(code, None)
    merged_results.update(validated_derived)
    upload["results"] = merged_results

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
