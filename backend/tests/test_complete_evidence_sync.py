# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-FileComment: itkflow-636c6be83d85
from sqlalchemy import or_, select

import app.complete_evidence_sync as complete_sync
from app.complete_evidence_sync import (
    CompleteEvidenceSyncJobManager,
    evidence_component_scope,
    run_complete_evidence_sync_job,
)
from app.models import Component, InstituteProfile, SyncJob
from app.sync_jobs import EVIDENCE_SYNC_ACTIVE_KEY_PREFIX, EVIDENCE_SYNC_MODE_KEY


def _component(
    *,
    sn: str,
    component_type: str,
    owner: str,
    location: str,
    parent: Component | None = None,
    stale: bool = False,
    trashed: bool = False,
) -> Component:
    return Component(
        sn=sn,
        component_type=component_type,
        type_code="TEST",
        stage="READY",
        institute_code=owner,
        location=location,
        parent_id=parent.id if parent is not None else None,
        stale=stale,
        trashed=trashed,
    )


def _scope_fixture(session_factory):
    with session_factory() as session:
        profile = InstituteProfile(code="SCOPE", name="Scope test", settings={})
        session.add(profile)
        session.flush()

        root = _component(
            sn="20USEM00001001",
            component_type="MODULE",
            owner="SCOPE",
            location="SCOPE",
        )
        session.add(root)
        session.flush()
        half = _component(
            sn="20USEM00001002",
            component_type="MODULE",
            owner="CERN",
            location="REMOTE",
            parent=root,
        )
        hybrid = _component(
            sn="20USEH00001003",
            component_type="HYBRID_ASSEMBLY",
            owner="CERN",
            location="REMOTE",
            parent=root,
        )
        session.add_all([half, hybrid])
        session.flush()
        sensor = _component(
            sn="20USES00001004",
            component_type="SENSOR",
            owner="CERN",
            location="REMOTE",
            parent=half,
        )
        chip = _component(
            sn="20USEA00001005",
            component_type="ABC",
            owner="CERN",
            location="REMOTE",
            parent=hybrid,
        )
        onsite = _component(
            sn="20USEP00001006",
            component_type="PWB",
            owner="CERN",
            location="SCOPE",
        )
        unrelated = _component(
            sn="20USES00001999",
            component_type="SENSOR",
            owner="CERN",
            location="REMOTE",
        )
        stale = _component(
            sn="20USES00001007",
            component_type="SENSOR",
            owner="CERN",
            location="REMOTE",
            parent=half,
            stale=True,
        )
        trashed = _component(
            sn="20USES00001008",
            component_type="SENSOR",
            owner="CERN",
            location="REMOTE",
            parent=half,
            trashed=True,
        )
        session.add_all([sensor, chip, onsite, unrelated, stale, trashed])
        session.commit()

    return {
        "all": {
            "20USEM00001001",
            "20USEM00001002",
            "20USEH00001003",
            "20USES00001004",
            "20USEA00001005",
            "20USEP00001006",
        },
        "unrelated": "20USES00001999",
        "stale": "20USES00001007",
        "trashed": "20USES00001008",
    }


def test_standard_scope_captures_all_types_and_recursive_assembled_parts(session_factory):
    expected = _scope_fixture(session_factory)
    with session_factory() as session:
        profile = session.scalar(select(InstituteProfile).where(InstituteProfile.code == "SCOPE"))
        scope = evidence_component_scope(session, profile, "standard")

    assert set(scope.component_sns) == expected["all"]
    assert expected["unrelated"] not in scope.component_sns
    assert expected["stale"] not in scope.component_sns
    assert expected["trashed"] not in scope.component_sns
    assert set(scope.component_types) == {
        "ABC",
        "HYBRID_ASSEMBLY",
        "MODULE",
        "PWB",
        "SENSOR",
    }
    assert scope.root_count == 2
    assert scope.assembled_descendant_count == 4
    assert scope.component_type_filter is None
    assert scope.policy == "complete_local_production"


def test_profile_filter_applies_after_recursive_traversal(session_factory):
    _scope_fixture(session_factory)
    with session_factory() as session:
        profile = session.scalar(select(InstituteProfile).where(InstituteProfile.code == "SCOPE"))
        profile.settings = {"evidence_component_types": ["sensor", "ABC", "sensor"]}
        session.commit()
        scope = evidence_component_scope(session, profile, "standard")

    assert set(scope.component_sns) == {"20USES00001004", "20USEA00001005"}
    assert scope.component_type_filter == ("SENSOR", "ABC")
    assert scope.root_count == 0
    assert scope.assembled_descendant_count == 2
    assert scope.policy == "profile_type_filter"


def test_lightweight_scope_keeps_module_descendants_but_skips_other_types(session_factory):
    _scope_fixture(session_factory)
    with session_factory() as session:
        profile = session.scalar(select(InstituteProfile).where(InstituteProfile.code == "SCOPE"))
        scope = evidence_component_scope(session, profile, "lightweight")

    assert set(scope.component_sns) == {"20USEM00001001", "20USEM00001002"}
    assert scope.component_type_filter == ("MODULE",)
    assert scope.root_count == 1
    assert scope.assembled_descendant_count == 1
    assert scope.policy == "lightweight"


def test_runner_replaces_the_legacy_scope_and_records_what_was_mirrored(
    session_factory, monkeypatch
):
    expected = _scope_fixture(session_factory)
    with session_factory() as session:
        job = SyncJob(
            kind="evidence",
            institute_code="SCOPE",
            status="queued",
            phase="queued",
            current=0,
            message="queued",
            result={EVIDENCE_SYNC_MODE_KEY: "standard"},
            requested_by="test@example.invalid",
            active_key=f"{EVIDENCE_SYNC_ACTIVE_KEY_PREFIX}SCOPE",
        )
        session.add(job)
        session.commit()
        job_id = job.id

    observed: list[str] = []

    def fake_runner(scoped_factory, _settings, _gateway_factory, target_job_id, _retry):
        with scoped_factory() as session:
            observed.extend(
                session.scalars(
                    select(Component.sn)
                    .where(
                        or_(
                            Component.institute_code == "SCOPE",
                            Component.location == "SCOPE",
                        ),
                        Component.component_type.in_(("MODULE",)),
                        Component.trashed.is_(False),
                        Component.stale.is_(False),
                    )
                    .order_by(Component.sn)
                )
            )
        with scoped_factory() as session:
            target = session.get(SyncJob, target_job_id)
            target.status = "succeeded"
            target.phase = "complete"
            target.active_key = None
            target.result = {
                "components_processed": len(observed),
                "component_types": ["MODULE"],
            }
            session.commit()

    monkeypatch.setattr(complete_sync, "_run_evidence_sync_job", fake_runner)
    run_complete_evidence_sync_job(
        session_factory,
        object(),
        lambda *_args: object(),
        job_id,
    )

    assert set(observed) == expected["all"]
    with session_factory() as session:
        result = session.get(SyncJob, job_id).result
    assert result["components_processed"] == len(expected["all"])
    assert result["component_type_filter"] is None
    assert result["scope_policy"] == "complete_local_production"
    assert result["scope_roots"] == 2
    assert result["scope_assembled_descendants"] == 4
    assert set(result["component_types"]) == {
        "ABC",
        "HYBRID_ASSEMBLY",
        "MODULE",
        "PWB",
        "SENSOR",
    }


def test_application_uses_complete_evidence_manager(client):
    assert isinstance(client.app.state.sync_job_manager, CompleteEvidenceSyncJobManager)
