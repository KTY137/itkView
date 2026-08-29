# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-FileComment: itkflow-6e8773451cc5
"""Completeness-first scope for read-only PDB evidence mirror jobs.

The component mirror deliberately enriches an institute's own/onsite listing
with parts assembled below those components, even when the parts belong to and
stand at another institute.  The historical evidence sweep repeated only the
owner/location filter and therefore dropped those enriched descendants again.
It also used a collaboration-wide type allow-list that silently excluded chip
and future component families.

This module keeps the proven evidence runner intact and supplies the one input
it previously could not express: the complete live local production closure.
Standard syncs include every mirrored component owned by or located at the
institute plus every live assembled descendant, recursively and independent of
owner, location or component type.  A valid institute-profile type list remains
an explicit opt-in restriction; lightweight sync remains module-only.
"""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Iterator, Sequence
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models import Component, InstituteProfile, SyncJob
from app.sync_jobs import (
    EVIDENCE_SYNC_KIND,
    EVIDENCE_SYNC_MODE_KEY,
    EvidenceGatewayFactory,
    EvidenceSyncMode,
    SyncJobManager,
    run_evidence_sync_job as _run_evidence_sync_job,
)

EvidenceScopePolicy = Literal[
    "complete_local_production", "profile_type_filter", "lightweight"
]


@dataclass(frozen=True)
class EvidenceComponentScope:
    """Serials and audit metadata for one evidence mirror job."""

    component_sns: tuple[str, ...]
    component_types: tuple[str, ...]
    component_type_filter: tuple[str, ...] | None
    root_count: int
    assembled_descendant_count: int
    policy: EvidenceScopePolicy


def _component_type_filter(
    institute: InstituteProfile, sync_mode: EvidenceSyncMode
) -> tuple[str, ...] | None:
    """Return an explicit type restriction, or ``None`` for complete scope."""

    if sync_mode == "lightweight":
        return ("MODULE",)

    raw = (institute.settings or {}).get("evidence_component_types")
    if not isinstance(raw, list):
        return None

    values: list[str] = []
    for value in raw:
        if not isinstance(value, str) or not value.strip():
            continue
        normalized = value.strip().upper()
        if normalized not in values:
            values.append(normalized)
    return tuple(values) or None


def evidence_component_scope(
    session: Session,
    institute: InstituteProfile,
    sync_mode: EvidenceSyncMode = "standard",
) -> EvidenceComponentScope:
    """Return every live component whose evidence belongs in this mirror.

    Roots are all live components owned by or currently located at the target
    institute.  The closure then follows ``parent_id`` recursively through the
    already mirrored assembly graph.  Traversal happens before an optional type
    filter so a profile asking only for SENSOR evidence still reaches a sensor
    below an external half-module below a local full module.
    """

    rows = list(
        session.execute(
            select(
                Component.id,
                Component.sn,
                Component.parent_id,
                Component.component_type,
                Component.institute_code,
                Component.location,
            ).where(
                Component.trashed.is_(False),
                Component.stale.is_(False),
            )
        )
    )
    nodes = {
        component_id: (
            sn,
            parent_id,
            component_type,
            owner_code,
            location_code,
        )
        for component_id, sn, parent_id, component_type, owner_code, location_code in rows
    }
    children: dict[int, list[int]] = defaultdict(list)
    root_ids: set[int] = set()
    for component_id, (_sn, parent_id, _type, owner_code, location_code) in nodes.items():
        if parent_id is not None and parent_id in nodes:
            children[parent_id].append(component_id)
        if owner_code == institute.code or location_code == institute.code:
            root_ids.add(component_id)

    closure = set(root_ids)
    queue = deque(sorted(root_ids))
    while queue:
        parent_id = queue.popleft()
        for child_id in children.get(parent_id, ()):
            if child_id in closure:
                continue
            closure.add(child_id)
            queue.append(child_id)

    type_filter = _component_type_filter(institute, sync_mode)
    selected_ids = {
        component_id
        for component_id in closure
        if type_filter is None or nodes[component_id][2] in type_filter
    }
    serials = tuple(sorted(nodes[component_id][0] for component_id in selected_ids))
    component_types = tuple(sorted({nodes[component_id][2] for component_id in selected_ids}))
    selected_roots = selected_ids & root_ids
    if sync_mode == "lightweight":
        policy: EvidenceScopePolicy = "lightweight"
    elif type_filter is not None:
        policy = "profile_type_filter"
    else:
        policy = "complete_local_production"

    return EvidenceComponentScope(
        component_sns=serials,
        component_types=component_types,
        component_type_filter=type_filter,
        root_count=len(selected_roots),
        assembled_descendant_count=len(selected_ids - root_ids),
        policy=policy,
    )


class _ScopeScalarResult(Sequence[str]):
    """Small ScalarResult-compatible view used by the legacy runner's list()."""

    def __init__(self, values: tuple[str, ...]) -> None:
        self._values = values

    def __getitem__(self, index):
        return self._values[index]

    def __len__(self) -> int:
        return len(self._values)

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def all(self) -> list[str]:
        return list(self._values)

    def unique(self) -> _ScopeScalarResult:
        return self


@dataclass
class _ScopeOverride:
    scope: EvidenceComponentScope
    hits: int = 0


def _selects_component_serials(statement: Any) -> bool:
    descriptions = getattr(statement, "column_descriptions", ())
    if len(descriptions) != 1:
        return False
    description = descriptions[0]
    return description.get("entity") is Component and description.get("name") == "sn"


class _ScopeAwareSession:
    """Delegate a Session except for the evidence runner's one scope query."""

    def __init__(self, session: Session, override: _ScopeOverride) -> None:
        self._session = session
        self._override = override

    def __enter__(self) -> _ScopeAwareSession:
        self._session.__enter__()
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool | None:
        return self._session.__exit__(exc_type, exc, traceback)

    def scalars(self, statement, *args, **kwargs):
        if _selects_component_serials(statement):
            self._override.hits += 1
            return _ScopeScalarResult(self._override.scope.component_sns)
        return self._session.scalars(statement, *args, **kwargs)

    def __getattr__(self, name: str):
        return getattr(self._session, name)


class _ScopeAwareSessionFactory:
    def __init__(
        self,
        base: sessionmaker[Session],
        override: _ScopeOverride,
    ) -> None:
        self._base = base
        self._override = override

    def __call__(self, *args, **kwargs) -> _ScopeAwareSession:
        return _ScopeAwareSession(self._base(*args, **kwargs), self._override)


def _job_scope(
    session_factory: sessionmaker[Session], job_id: int
) -> EvidenceComponentScope | None:
    with session_factory() as session:
        job = session.get(SyncJob, job_id)
        if job is None or job.kind != EVIDENCE_SYNC_KIND:
            return None
        institute = session.scalar(
            select(InstituteProfile).where(InstituteProfile.code == job.institute_code)
        )
        if institute is None:
            return None
        raw_mode = (job.result or {}).get(EVIDENCE_SYNC_MODE_KEY)
        sync_mode: EvidenceSyncMode = (
            "lightweight" if raw_mode == "lightweight" else "standard"
        )
        return evidence_component_scope(session, institute, sync_mode)


def _record_scope_result(
    session_factory: sessionmaker[Session],
    job_id: int,
    scope: EvidenceComponentScope,
    intercepts: int,
) -> None:
    """Persist the effective scope and fail closed if the adapter drifted."""

    with session_factory() as session:
        job = session.get(SyncJob, job_id)
        if job is None or job.status != "succeeded":
            return
        if intercepts != 1:
            job.status = "failed"
            job.phase = "scope"
            job.message = "Evidence sync failed."
            job.error = (
                "The completeness-first evidence scope was not applied exactly once; "
                "already mirrored evidence remains valid, but this job cannot claim "
                "a complete snapshot."
            )
            session.commit()
            return

        result = dict(job.result or {})
        result.update(
            {
                "component_types": list(scope.component_types),
                "component_type_filter": (
                    list(scope.component_type_filter)
                    if scope.component_type_filter is not None
                    else None
                ),
                "scope_policy": scope.policy,
                "scope_roots": scope.root_count,
                "scope_assembled_descendants": scope.assembled_descendant_count,
            }
        )
        job.result = result
        session.commit()


def run_complete_evidence_sync_job(
    session_factory: sessionmaker[Session],
    settings,
    gateway_factory: EvidenceGatewayFactory,
    job_id: int,
    on_transient_failure: Any | None = None,
) -> None:
    """Run the proven evidence mirror against the complete production scope."""

    scope = _job_scope(session_factory, job_id)
    if scope is None:
        _run_evidence_sync_job(
            session_factory,
            settings,
            gateway_factory,
            job_id,
            on_transient_failure,
        )
        return

    override = _ScopeOverride(scope)
    scoped_factory = _ScopeAwareSessionFactory(session_factory, override)
    _run_evidence_sync_job(
        scoped_factory,
        settings,
        gateway_factory,
        job_id,
        on_transient_failure,
    )
    _record_scope_result(session_factory, job_id, scope, override.hits)


class CompleteEvidenceSyncJobManager(SyncJobManager):
    """Sync manager whose evidence worker uses the complete read scope."""

    def start_evidence(self, job_id: int) -> None:
        self._watch_queued(job_id)
        try:
            future = self._evidence_executor.submit(
                run_complete_evidence_sync_job,
                self._session_factory,
                self._settings,
                self._evidence_gateway_factory,
                job_id,
                self._schedule_evidence_retry,
            )
        except Exception:
            self._unwatch_queued(job_id)
            raise
        if isinstance(future, Future):
            future.add_done_callback(
                lambda _completed, completed_id=job_id: self._after_evidence_future(
                    completed_id
                )
            )
