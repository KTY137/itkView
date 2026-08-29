# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-FileComment: itkflow-ddcdef1ea610
"""Aggregate mirrored test-run measurements for the Statistics page.

Everything is derived from the local evidence mirror (`TestRunEvidence.payload`
as written by the detail fetch): array-valued results become overlaid curves —
one per run, e.g. every IV curve of an institute in a single chart — and
scalar results become a distribution. Which test types and result codes exist
is discovered from the data, never hardcoded (hard rule #4); the PDB is not
contacted here.

Runs the PDB has withdrawn are excluded from every aggregate, both from the
discovered dimensions and from the series themselves: a retracted measurement
would otherwise widen a distribution and draw a curve that nobody stands behind
any more, which reads exactly like a real production problem.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Component, TestRunEvidence
from app.test_run_evidence import live_runs_only

# One institute sweep holds a few hundred runs; the cap only guards against a
# pathological payload, not normal use.
DEFAULT_RUN_LIMIT = 300
MAX_RUN_LIMIT = 1000


@dataclass
class ResultDimension:
    code: str
    name: str | None
    kind: str  # "array" | "scalar"
    runs: int


@dataclass
class MeasurementCurve:
    component_sn: str
    local_name: str | None
    external_ref: str | None
    measured_at: Any
    passed: bool
    x: list[float] | None
    y: list[float]


@dataclass
class MeasurementValue:
    component_sn: str
    local_name: str | None
    external_ref: str | None
    measured_at: Any
    passed: bool
    value: float


@dataclass
class MeasurementSeries:
    test_type: str
    result_code: str
    kind: str  # "array" | "scalar"
    result_name: str | None = None
    x_result: str | None = None
    x_name: str | None = None
    curves: list[MeasurementCurve] = field(default_factory=list)
    values: list[MeasurementValue] = field(default_factory=list)
    summary: dict[str, float | int] | None = None
    truncated: bool = False


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _numeric_list(value: Any) -> list[float] | None:
    if not isinstance(value, list) or not value:
        return None
    if not all(_is_number(item) for item in value):
        return None
    return [float(item) for item in value]


def measurement_dimensions(
    session: Session, *, institute_code: str | None = None
) -> list[dict[str, Any]]:
    """Discover test types and their result codes from the mirrored payloads."""
    rows = _evidence_rows(session, institute_code=institute_code)
    by_type: dict[str, dict[str, ResultDimension]] = {}
    for row in rows:
        payload = row.payload or {}
        results = payload.get("results")
        if not isinstance(results, dict):
            continue
        meta = payload.get("result_meta") if isinstance(payload.get("result_meta"), dict) else {}
        bucket = by_type.setdefault(row.test_type, {})
        for code, value in results.items():
            kind = "array" if _numeric_list(value) is not None else "scalar"
            if kind == "scalar" and not _is_number(value):
                # Nested dicts / nulls carry no plottable value.
                continue
            entry_meta = meta.get(code) if isinstance(meta.get(code), dict) else {}
            existing = bucket.get(code)
            if existing is None:
                bucket[code] = ResultDimension(
                    code=code, name=entry_meta.get("name"), kind=kind, runs=1
                )
            else:
                existing.runs += 1
                if existing.name is None and entry_meta.get("name"):
                    existing.name = entry_meta["name"]
    return [
        {
            "test_type": test_type,
            "results": sorted(
                (vars(dim) for dim in dims.values()), key=lambda d: (-d["runs"], d["code"])
            ),
        }
        for test_type, dims in sorted(by_type.items())
    ]


def measurement_series(
    session: Session,
    *,
    test_type: str,
    result_code: str,
    x_result: str | None = None,
    institute_code: str | None = None,
    limit: int = DEFAULT_RUN_LIMIT,
) -> MeasurementSeries:
    limit = max(1, min(int(limit), MAX_RUN_LIMIT))
    rows = _evidence_rows(session, test_type=test_type, institute_code=institute_code)
    # Newest measurements first; rows without a timestamp go last.
    rows.sort(key=lambda r: (r.measured_at is None, r.measured_at), reverse=False)
    rows.sort(key=lambda r: (r.measured_at is not None, r.measured_at or 0), reverse=True)

    series = MeasurementSeries(test_type=test_type, result_code=result_code, kind="scalar")
    local_names = _local_names(session, {row.component_sn for row in rows})
    kept = 0
    for row in rows:
        payload = row.payload or {}
        results = payload.get("results")
        if not isinstance(results, dict) or result_code not in results:
            continue
        meta = payload.get("result_meta") if isinstance(payload.get("result_meta"), dict) else {}
        if series.result_name is None:
            entry_meta = meta.get(result_code)
            if isinstance(entry_meta, dict):
                series.result_name = entry_meta.get("name")
        value = results.get(result_code)
        y = _numeric_list(value)
        if y is not None:
            if kept >= limit:
                series.truncated = True
                break
            series.kind = "array"
            x = None
            if x_result:
                x_candidate = _numeric_list(results.get(x_result))
                if x_candidate is not None and len(x_candidate) == len(y):
                    x = x_candidate
                    if series.x_name is None:
                        x_meta = meta.get(x_result)
                        if isinstance(x_meta, dict):
                            series.x_name = x_meta.get("name")
            series.x_result = x_result
            series.curves.append(
                MeasurementCurve(
                    component_sn=row.component_sn,
                    local_name=local_names.get(row.component_sn),
                    external_ref=row.external_ref,
                    measured_at=row.measured_at,
                    passed=bool(row.passed),
                    x=x,
                    y=y,
                )
            )
            kept += 1
        elif _is_number(value):
            if kept >= limit:
                series.truncated = True
                break
            series.values.append(
                MeasurementValue(
                    component_sn=row.component_sn,
                    local_name=local_names.get(row.component_sn),
                    external_ref=row.external_ref,
                    measured_at=row.measured_at,
                    passed=bool(row.passed),
                    value=float(value),
                )
            )
            kept += 1

    if series.values and not series.curves:
        numbers = [entry.value for entry in series.values]
        ordered = sorted(numbers)
        series.summary = {
            "count": len(numbers),
            "min": ordered[0],
            "max": ordered[-1],
            "mean": sum(numbers) / len(numbers),
            "median": float(median(numbers)),
            "p25": ordered[max(0, int(0.25 * (len(ordered) - 1)))],
            "p75": ordered[min(len(ordered) - 1, int(0.75 * (len(ordered) - 1)))],
        }
    return series


def _evidence_rows(
    session: Session,
    *,
    test_type: str | None = None,
    institute_code: str | None = None,
) -> list[TestRunEvidence]:
    # Runs the PDB has withdrawn never enter an aggregate: a retracted glue
    # weight would otherwise still stretch the distribution and draw its curve,
    # and the resulting "suspicious block of values" is indistinguishable from
    # a real production problem.
    stmt = select(TestRunEvidence).where(TestRunEvidence.source == "pdb", live_runs_only())
    if test_type is not None:
        stmt = stmt.where(TestRunEvidence.test_type == test_type)
    if institute_code:
        stmt = stmt.join(
            Component, Component.sn == TestRunEvidence.component_sn
        ).where(Component.institute_code == institute_code)
    return list(session.scalars(stmt))


def _local_names(session: Session, sns: set[str]) -> dict[str, str | None]:
    if not sns:
        return {}
    names: dict[str, str | None] = {}
    ordered = sorted(sns)
    for offset in range(0, len(ordered), 500):
        chunk = ordered[offset : offset + 500]
        for sn, local_name in session.execute(
            select(Component.sn, Component.local_name).where(Component.sn.in_(chunk))
        ):
            names[sn] = local_name
    return names
