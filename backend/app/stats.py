# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-FileComment: itkflow-28deaa6483f1
"""Production statistics derived from the StageEvent history.

Pure query + aggregation over the local `stage_event` mirror — no PDB I/O.
Every metric is reconstructed from the dated stage log the sync captured, so a
single fetch yields full history: throughput, lead time, per-stage dwell and
rework. The log is noisy (same-second correction entries, rework loops); the
aggregations use first-reach and median to stay robust against that.
"""

from collections import Counter, defaultdict
from datetime import datetime
from statistics import median

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import StageEvent

# Canonical strip module-assembly stage order (FINISHED-ward). Terminal/off-flow
# states are kept out of the ordered axis and surfaced separately.
STAGE_ORDER = [
    "HV_TAB_ATTACHED",
    "GLUED",
    "STITCH_BONDING",
    "BONDED",
    "TESTED",
    "FINISHED",
    "AT_LOADING_SITE",
]
DEFAULT_TARGET_STAGE = "FINISHED"

# Terminal failure stages — a component that hit one of these (and never reached
# the target) counts as a loss for yield.
FAIL_STAGES = {"FAILED", "TRASHED", "ABANDONED"}


def _period(dt: datetime, bucket: str) -> str:
    if bucket == "week":
        iso = dt.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    if bucket == "year":
        return f"{dt.year}"
    return f"{dt.year}-{dt.month:02d}"  # month (default)


def _percentile(sorted_days: list[float], pct: float) -> float:
    if not sorted_days:
        return 0.0
    k = (len(sorted_days) - 1) * (pct / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(sorted_days) - 1)
    return sorted_days[lo] + (sorted_days[hi] - sorted_days[lo]) * (k - lo)


def _rows(
    session: Session,
    *,
    component_type: str | None = None,
    type_code: str | None = None,
    institute: str | None = None,
) -> list[tuple[str, str, datetime, bool]]:
    stmt = select(
        StageEvent.component_sn,
        StageEvent.stage,
        StageEvent.entered_at,
        StageEvent.rework,
    )
    if component_type:
        stmt = stmt.where(StageEvent.component_type == component_type)
    if type_code:
        stmt = stmt.where(StageEvent.type_code == type_code)
    if institute:
        stmt = stmt.where(StageEvent.institute_code == institute)
    return [tuple(r) for r in session.execute(stmt).all()]


def _first_reach(rows, stage: str) -> dict[str, datetime]:
    """Earliest time each component entered `stage` (ignores later re-entries)."""
    out: dict[str, datetime] = {}
    for sn, st, at, _ in rows:
        if st == stage and (sn not in out or at < out[sn]):
            out[sn] = at
    return out


def _first_any(rows) -> dict[str, datetime]:
    out: dict[str, datetime] = {}
    for sn, _, at, _ in rows:
        if sn not in out or at < out[sn]:
            out[sn] = at
    return out


def throughput(rows, *, stage: str, bucket: str = "month") -> list[dict]:
    """Components that first reached `stage`, bucketed by calendar period."""
    counts: Counter[str] = Counter()
    for at in _first_reach(rows, stage).values():
        counts[_period(at, bucket)] += 1
    return [{"period": p, "count": counts[p]} for p in sorted(counts)]


def lead_time(rows, *, target_stage: str) -> dict:
    """Days from a component's first stage to first reaching `target_stage`."""
    first_any = _first_any(rows)
    durations: list[float] = []
    for sn, at in _first_reach(rows, target_stage).items():
        start = first_any.get(sn)
        if start is not None and at >= start:
            durations.append((at - start).total_seconds() / 86400.0)
    durations.sort()
    if not durations:
        return {"count": 0, "median_days": None, "p25_days": None, "p75_days": None}
    return {
        "count": len(durations),
        "median_days": round(median(durations), 1),
        "p25_days": round(_percentile(durations, 25), 1),
        "p75_days": round(_percentile(durations, 75), 1),
    }


def stage_dwell(rows) -> list[dict]:
    """Median days spent in each stage before moving to a *different* stage."""
    per: dict[str, list[tuple[datetime, str]]] = defaultdict(list)
    for sn, st, at, _ in rows:
        per[sn].append((at, st))
    dwell: dict[str, list[float]] = defaultdict(list)
    for events in per.values():
        events.sort()
        for (at1, st1), (at2, st2) in zip(events, events[1:], strict=False):
            if st1 != st2:  # skip same-second correction entries in one stage
                days = (at2 - at1).total_seconds() / 86400.0
                if days >= 0:
                    dwell[st1].append(days)
    ordered = [s for s in STAGE_ORDER if s in dwell] + [s for s in dwell if s not in STAGE_ORDER]
    return [
        {"stage": s, "median_days": round(median(dwell[s]), 2), "count": len(dwell[s])}
        for s in ordered
    ]


def rework(rows) -> dict:
    """Rework rate and the stages where rework happens most."""
    by_stage: Counter[str] = Counter()
    components: set[str] = set()
    reworked: set[str] = set()
    for sn, st, _, rw in rows:
        components.add(sn)
        if rw:
            by_stage[st] += 1
            reworked.add(sn)
    total = len(components)
    return {
        "rate": round(len(reworked) / total, 3) if total else 0.0,
        "reworked_components": len(reworked),
        "total_components": total,
        "by_stage": [{"stage": s, "count": c} for s, c in by_stage.most_common()],
    }


def yield_stats(rows, *, target_stage: str) -> dict:
    """Assembly yield: of the components that *concluded*, the share that made it.

    A component is a success if it ever reached `target_stage`, a loss if it hit
    a terminal failure stage without ever reaching the target. Components still
    in progress (neither) are excluded, so yield reflects concluded work only.
    """
    stages_by_sn: dict[str, set[str]] = defaultdict(set)
    for sn, stage, _, _ in rows:
        stages_by_sn[sn].add(stage)
    good = failed = 0
    for stages in stages_by_sn.values():
        if target_stage in stages:
            good += 1
        elif stages & FAIL_STAGES:
            failed += 1
    concluded = good + failed
    return {
        "good": good,
        "failed": failed,
        "concluded": concluded,
        "in_progress": len(stages_by_sn) - concluded,
        "rate": round(good / concluded, 3) if concluded else None,
    }


def production_stats(
    session: Session,
    *,
    component_type: str | None = "MODULE",
    type_code: str | None = None,
    institute: str | None = None,
    target_stage: str = DEFAULT_TARGET_STAGE,
    bucket: str = "month",
) -> dict:
    """Everything the Statistics panel needs, from one pass over the history."""
    rows = _rows(
        session, component_type=component_type, type_code=type_code, institute=institute
    )
    return {
        "component_type": component_type,
        "type_code": type_code,
        "institute": institute,
        "target_stage": target_stage,
        "bucket": bucket,
        "components_tracked": len({r[0] for r in rows}),
        "stage_order": STAGE_ORDER,
        "throughput": throughput(rows, stage=target_stage, bucket=bucket),
        "lead_time": lead_time(rows, target_stage=target_stage),
        "stage_dwell": stage_dwell(rows),
        "rework": rework(rows),
        "yield_": yield_stats(rows, target_stage=target_stage),
    }
