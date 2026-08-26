"""Read-only mirror input for PDB test-type schemas.

The component page uses these definitions to build controlled manual-entry
forms. Fetching stays behind the caller's personal gateway and deliberately
returns plain records; database mutation is handled separately so a failed
remote read can never leave a partial schema refresh.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

DEFAULT_PDB_PROJECT = "S"


class PdbTestTypesUnavailable(RuntimeError):
    """The schema catalogue could not be read from the PDB."""


@dataclass(frozen=True)
class TestTypeSchemaRecord:
    __test__ = False

    component_type: str
    test_code: str
    name: str
    schema: dict[str, Any]


def _code(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    if isinstance(value, dict):
        code = value.get("code")
        if isinstance(code, str) and code:
            return code
    return None


def _rows(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, dict):
        for key in ("pageItemList", "itemList"):
            if key not in raw:
                continue
            value = raw[key]
            if not isinstance(value, list) or any(
                not isinstance(row, dict) for row in value
            ):
                raise PdbTestTypesUnavailable(
                    "The PDB returned an unusable test-type catalogue."
                )
            return value
        raise PdbTestTypesUnavailable(
            "The PDB returned an unusable test-type catalogue."
        )
    if isinstance(raw, list):
        if any(not isinstance(row, dict) for row in raw):
            raise PdbTestTypesUnavailable(
                "The PDB returned an unusable test-type catalogue."
            )
        return raw
    # itkdb returns neither a dict nor a list for a catalogue that carries
    # `pageItemList` (and for any `itemList` spanning more than one page): it
    # hands back a `PagedResponse`, whose `.data` holds only the page fetched
    # last. Iterating walks every page, which is what a complete catalogue
    # needs — the same shape `pdb_sync._extract_page` already accounts for.
    if hasattr(raw, "data") and hasattr(raw, "page_info"):
        rows = list(raw)
        if any(not isinstance(row, dict) for row in rows):
            raise PdbTestTypesUnavailable(
                "The PDB returned an unusable test-type catalogue."
            )
        # Refuse a truncated catalogue; presenting a partial form inventory as
        # complete is exactly what this module is strict about. Only a
        # shortfall is an error: PDB listings have been observed repeating
        # rows across pages, and the caller de-duplicates by code anyway.
        total = getattr(raw, "total", -1)
        if isinstance(total, int) and total >= 0 and len(rows) < total:
            raise PdbTestTypesUnavailable(
                "The PDB returned an incomplete test-type catalogue."
            )
        return rows
    raise PdbTestTypesUnavailable(
        "The PDB returned an unusable test-type catalogue."
    )


def fetch_test_type_schemas(
    gateway: Any,
    component_type: str,
    *,
    project: str,
) -> list[TestTypeSchemaRecord]:
    """Fetch complete schemas for every active test type of a component type.

    This is strict by design: a catalogue that lists three definitions but
    only resolves two is not safe to present as the complete form inventory.
    Upstream exception text is never propagated because requests may contain
    personal access material.
    """
    if not getattr(gateway, "is_configured", False):
        raise PdbTestTypesUnavailable(
            "No personal PDB connection is available for this account."
        )
    try:
        client = gateway.client()
        raw = client.get(
            "listTestTypes",
            json={"project": project, "componentType": component_type},
        )
    except Exception:
        raise PdbTestTypesUnavailable("The PDB test-type catalogue could not be read.") from None
    listed = _rows(raw)

    records: list[TestTypeSchemaRecord] = []
    seen: set[str] = set()
    for row in listed:
        test_code = _code(row.get("code")) or _code(row.get("testType"))
        if test_code is None:
            raise PdbTestTypesUnavailable(
                "The PDB returned an unusable test-type catalogue entry."
            )
        if test_code in seen:
            continue
        # Ignore catalogue tombstones; absent state is accepted for older API
        # responses that did not expose it.
        state = row.get("state")
        if isinstance(state, str) and state not in {"ready", "active"}:
            continue
        try:
            detail = client.get(
                "getTestTypeByCode",
                json={
                    "project": project,
                    "componentType": component_type,
                    "code": test_code,
                },
            )
        except Exception:
            raise PdbTestTypesUnavailable("A PDB test-type schema could not be read.") from None
        if not isinstance(detail, dict):
            raise PdbTestTypesUnavailable("The PDB returned an unusable test-type schema.")

        detail_code = _code(detail.get("code")) or _code(detail.get("testType"))
        if detail_code is not None and detail_code != test_code:
            raise PdbTestTypesUnavailable("The PDB returned a mismatched test-type schema.")
        name = detail.get("name") or row.get("name") or test_code
        records.append(
            TestTypeSchemaRecord(
                component_type=component_type,
                test_code=test_code,
                name=name if isinstance(name, str) and name else test_code,
                schema=detail,
            )
        )
        seen.add(test_code)
    return records
