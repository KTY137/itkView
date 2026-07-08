"""End-to-end write test against the production PDB — DUMMY scope only.

Registers (or reuses) a DUMMY test module owned by this institute, uploads a
test run through the full ingest → outbox → worker pipeline with the *real*
submitter, then performs a stage move. Every write targets exclusively the
self-registered DUMMY part (docs/09, ADR 003).

Never runs by default. Requires, all deliberately set by a human:

    ITKFLOW_PDB_INSTANCE=production
    ITKFLOW_ALLOW_PRODUCTION=true
    ITKFLOW_ALLOW_PDB_WRITES=true
    ITKFLOW_ITKDB_ACCESS_CODE1/2
    pytest -m pdb_write

Optional: ITKFLOW_PDB_WRITE_TEST_SN reuses an existing DUMMY module instead of
registering a new one (recommended after the first run — do not litter the PDB
with parts). The registered SN is printed so it can be reused.
"""

import os

import pytest
from sqlalchemy import select

from app.config import Settings
from app.db import Base, ensure_phase0_sqlite_schema, make_engine, make_session_factory
from app.models import Component, IngestFile, InstituteProfile, OutboxAction
from app.outbox import OutboxStatus
from app.outbox_worker import process_due_actions
from app.pdb_submit import make_pdb_submitter, register_dummy_component

pytestmark = pytest.mark.pdb_write

# The dummy part registered by this test: a strip end-cap R5 half module.
DUMMY_TYPE_CODE = "R5M0"


@pytest.fixture(scope="module")
def settings(tmp_path_factory) -> Settings:
    base = Settings()
    if not (base.itkdb_access_code1 and base.itkdb_access_code2):
        pytest.skip("No ITKDB access codes configured.")
    if base.pdb_instance != "production" or not base.allow_production:
        pytest.skip("Needs ITKFLOW_PDB_INSTANCE=production and ITKFLOW_ALLOW_PRODUCTION=true.")
    if not base.allow_pdb_writes:
        pytest.skip("Writes are opt-in: set ITKFLOW_ALLOW_PDB_WRITES=true to run this test.")
    db = tmp_path_factory.mktemp("pdbwrite") / "e2e.db"
    return Settings(database_url=f"sqlite:///{db}")


@pytest.fixture(scope="module")
def session_factory(settings: Settings):
    engine = make_engine(settings.database_url)
    Base.metadata.create_all(engine)
    ensure_phase0_sqlite_schema(engine)
    factory = make_session_factory(engine)
    with factory() as session:
        session.add(
            InstituteProfile(code="TUDO", name="TU Dortmund", local_name_prefix="TUDO-")
        )
        session.commit()
    return factory


@pytest.fixture(scope="module")
def dummy_module(settings: Settings, session_factory) -> Component:
    """The DUMMY module all writes in this test target."""
    reuse_sn = os.environ.get("ITKFLOW_PDB_WRITE_TEST_SN")
    with session_factory() as session:
        if reuse_sn:
            # Reusing a known DUMMY part: mirror it locally as ours.
            from app.sync import SyncRecord, sync_components

            sync_components(
                session,
                [
                    SyncRecord(
                        sn=reuse_sn,
                        component_type="MODULE",
                        type_code=DUMMY_TYPE_CODE,
                        stage="UNKNOWN",
                        location="TUDO",
                        institute_code="TUDO",
                        local_name=None,
                        parent_sn=None,
                        is_dummy=True,
                        trashed=False,
                    )
                ],
            )
            session.commit()
            component = session.scalar(select(Component).where(Component.sn == reuse_sn))
        else:
            component = register_dummy_component(
                session,
                settings,
                component_type="MODULE",
                type_code=DUMMY_TYPE_CODE,
                institute_code="TUDO",
                local_name="TUDO-ITKFLOW-DUMMY-1",
            )
            print(
                f"\nRegistered DUMMY module {component.sn} — reuse it next time via "
                f"ITKFLOW_PDB_WRITE_TEST_SN={component.sn}"
            )
        assert component is not None and component.is_dummy
        return component


def test_upload_test_run_to_dummy_module(settings, session_factory, dummy_module):
    """Full loop: ingest file → approved outbox action → real submitter."""
    with session_factory() as session:
        ingest = IngestFile(
            filename="e2e-visual-inspection.json",
            sha256="e" * 64,
            size_bytes=1,
            status="proposed",
            component_sn=dummy_module.sn,
            test_type="VISUAL_INSPECTION",
            parser="e2e",
            payload={
                "component": dummy_module.sn,
                "testType": "VISUAL_INSPECTION",
                "institution": "TUDO",
                "runNumber": "1",
                "date": "2026-07-08T12:00:00.000Z",
                "passed": True,
                "problems": False,
                "properties": {},
                "results": {},
            },
            uploaded_by="pdb-write-e2e",
        )
        session.add(ingest)
        session.flush()
        institute = session.scalar(select(InstituteProfile).where(InstituteProfile.code == "TUDO"))
        action = OutboxAction(
            institute_id=institute.id,
            kind="upload_test_run",
            payload={"ingest_file_id": ingest.id, "component_sn": dummy_module.sn},
            status=OutboxStatus.APPROVED.value,
            created_by="pdb-write-e2e",
        )
        session.add(action)
        session.commit()
        action_id = action.id

    submitter = make_pdb_submitter(settings)
    with session_factory() as session:
        process_due_actions(session, submitter=submitter, max_attempts=1)
        session.commit()

    with session_factory() as session:
        action = session.get(OutboxAction, action_id)
        assert action.status == OutboxStatus.CONFIRMED.value, action.error
        assert action.external_ref
        print(f"\nUploaded test run, PDB ref: {action.external_ref}")


def test_stage_move_on_dummy_module(settings, session_factory, dummy_module):
    """Direct submitter call for the stage move (independent of the local
    stage-suggestion engine — the PDB validates the transition itself)."""
    submitter = make_pdb_submitter(settings)

    class _Action:
        kind = "stage_move"
        payload = {"sn": dummy_module.sn, "to_stage": "GLUED"}

    with session_factory() as session:
        outcome = submitter(session, _Action())
    # Either the PDB accepts the move, or it rejects it with a stage-flow
    # message (e.g. already at/past the stage from a previous run). Both prove
    # the write path works end to end; a transport failure would have raised.
    if outcome.is_confirmed:
        print(f"\nStage move confirmed: {dummy_module.sn} -> GLUED")
    else:
        assert "PDB rejected" in (outcome.rejected_reason or "")
        print(f"\nStage move answered by PDB: {outcome.rejected_reason}")
