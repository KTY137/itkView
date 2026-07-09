from sqlalchemy import select

from app.models import TestRunEvidence
from app.test_run_evidence import TestRunEvidenceRecord, upsert_test_run_evidence


def test_upsert_test_run_evidence_is_idempotent_by_external_ref(session_factory):
    with session_factory() as session:
        stats = upsert_test_run_evidence(
            session,
            [
                TestRunEvidenceRecord(
                    component_sn="20USE5M0000703",
                    test_type="MODULE_BOW",
                    passed=True,
                    source="pdb",
                    external_ref="PDB-RUN-1",
                    payload={"result": "ok"},
                )
            ],
        )
        session.commit()
    assert (stats.created, stats.updated, stats.unchanged) == (1, 0, 0)

    with session_factory() as session:
        stats = upsert_test_run_evidence(
            session,
            [
                TestRunEvidenceRecord(
                    component_sn="20USE5M0000703",
                    test_type="MODULE_BOW",
                    passed=False,
                    source="pdb",
                    external_ref="PDB-RUN-1",
                    payload={"result": "rerun-failed"},
                )
            ],
        )
        session.commit()
    assert (stats.created, stats.updated, stats.unchanged) == (0, 1, 0)

    with session_factory() as session:
        rows = list(session.scalars(select(TestRunEvidence)))
    assert len(rows) == 1
    assert rows[0].passed is False
    assert rows[0].payload == {"result": "rerun-failed"}
