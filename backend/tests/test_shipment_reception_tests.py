"""Reception-test projection and completion gate for Phase-4 shipments."""

from authutil import authenticate
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import (
    AuditEvent,
    Component,
    InstituteProfile,
    OutboxAction,
    Shipment,
    TestRunEvidence,
)
from app.pdb_shipments import ShipmentRecord
from app.shipment_reception import project_shipment_reception_tests
from app.shipment_sync import sync_shipments


def _component(sn: str, component_type: str, institute: str, *, dummy: bool = False):
    return Component(
        sn=sn,
        component_type=component_type,
        type_code=component_type,
        stage="RECEPTION",
        location=institute,
        institute_code=institute,
        is_dummy=dummy,
    )


def _shipment(session, institute: InstituteProfile, *items: dict) -> Shipment:
    sync_shipments(
        session,
        institute,
        [
            ShipmentRecord(
                pdb_id="reception-shipment",
                sender_code="SENDER",
                recipient_code=institute.code,
                status="delivered",
                items=list(items),
            )
        ],
    )
    session.flush()
    return session.scalar(
        select(Shipment).where(Shipment.pdb_id == "reception-shipment")
    )


def test_projection_is_profile_driven_and_pending_never_counts_as_passed(
    session_factory,
    tudo,
):
    with session_factory() as session:
        institute = session.get(InstituteProfile, tudo["id"])
        institute.settings = {
            "shipment_reception_tests": {
                "MODULE": ["RECEPTION_IV"],
                "HYBRID": ["RECEPTION_VISUAL"],
                "PWB": ["RECEPTION_POWER"],
            }
        }
        session.add_all(
            [
                _component("PASS", "MODULE", tudo["code"], dummy=True),
                _component("PENDING", "HYBRID", tudo["code"]),
                _component("FAILED", "PWB", tudo["code"]),
                _component("UNMAPPED", "SENSOR", tudo["code"]),
            ]
        )
        shipment = _shipment(
            session,
            institute,
            {"sn": "PASS", "component_type": "MODULE"},
            {"sn": "PENDING", "component_type": "HYBRID"},
            {"sn": "FAILED", "component_type": "PWB"},
            {"sn": "UNMIRRORED_MODULE", "component_type": "MODULE"},
            {"sn": "MISSING_TYPE"},
            {"sn": "UNMAPPED", "component_type": "SENSOR"},
        )
        session.add_all(
            [
                TestRunEvidence(
                    component_sn="PASS",
                    test_type="RECEPTION_IV",
                    passed=True,
                    external_ref="pass-run",
                ),
                TestRunEvidence(
                    component_sn="PENDING",
                    test_type="RECEPTION_VISUAL",
                    passed=True,
                    external_ref="old-pass-run",
                ),
                TestRunEvidence(
                    component_sn="FAILED",
                    test_type="RECEPTION_POWER",
                    passed=False,
                    external_ref="failed-run",
                ),
                OutboxAction(
                    institute_id=institute.id,
                    kind="upload_test_run",
                    status="draft",
                    payload={
                        "component_sn": "PENDING",
                        "test_type": "RECEPTION_VISUAL",
                        "passed": True,
                    },
                    created_by="operator@example.org",
                ),
            ]
        )
        session.flush()

        projected = project_shipment_reception_tests(session, [shipment])[shipment.id]

        by_sn = {item["sn"]: item for item in projected["items"]}
        assert by_sn["PASS"]["reception_test_status"] == "passed"
        assert by_sn["PASS"]["submittable"] is True
        assert by_sn["PENDING"]["reception_test_status"] == "pending"
        assert by_sn["PENDING"]["submittable_reason"] == "not_dummy"
        assert by_sn["FAILED"]["reception_test_status"] == "failed"
        assert by_sn["UNMIRRORED_MODULE"]["reception_test_status"] == "missing"
        assert by_sn["UNMIRRORED_MODULE"]["submittable_reason"] == "component_not_mirrored"
        assert by_sn["MISSING_TYPE"]["reception_tests_configured"] is False
        assert by_sn["MISSING_TYPE"]["submittable_reason"] == "component_not_mirrored"
        assert by_sn["UNMAPPED"]["reception_tests_configured"] is False
        assert projected["reception_test_status"] == "failed"


def test_confirmed_upload_satisfies_requirement_before_next_evidence_sync(
    session_factory,
    tudo,
):
    with session_factory() as session:
        institute = session.get(InstituteProfile, tudo["id"])
        institute.settings = {"shipment_reception_tests": {"MODULE": ["RECEPTION_IV"]}}
        session.add(_component("CONFIRMED", "MODULE", tudo["code"], dummy=True))
        shipment = _shipment(
            session,
            institute,
            {"sn": "CONFIRMED", "component_type": "MODULE"},
        )
        session.add(
            OutboxAction(
                institute_id=institute.id,
                kind="upload_test_run",
                status="confirmed",
                payload={
                    "component_sn": "CONFIRMED",
                    "test_type": "RECEPTION_IV",
                    "passed": True,
                },
                created_by="operator@example.org",
                external_ref="confirmed-run",
            )
        )
        session.flush()

        projected = project_shipment_reception_tests(session, [shipment])[shipment.id]

        assert projected["reception_test_status"] == "passed"


def test_resync_preserves_reception_and_projection_remains_derived(
    session_factory,
    tudo,
):
    with session_factory() as session:
        institute = session.get(InstituteProfile, tudo["id"])
        institute.settings = {"shipment_reception_tests": {"MODULE": ["RECEPTION_IV"]}}
        session.add(_component("RESYNC", "MODULE", tudo["code"], dummy=True))
        shipment = _shipment(
            session,
            institute,
            {"sn": "RESYNC", "component_type": "MODULE"},
        )
        shipment.reception_status = "in_progress"
        shipment.reception_note = "Locally checked"
        session.add(
            TestRunEvidence(
                component_sn="RESYNC",
                test_type="RECEPTION_IV",
                passed=True,
                external_ref="resync-run",
            )
        )
        session.flush()

        sync_shipments(
            session,
            institute,
            [
                ShipmentRecord(
                    pdb_id=shipment.pdb_id,
                    sender_code="SENDER",
                    recipient_code=institute.code,
                    status="received",
                    items=[{"sn": "RESYNC", "component_type": "MODULE"}],
                )
            ],
        )
        session.flush()
        projected = project_shipment_reception_tests(session, [shipment])[shipment.id]

        assert shipment.reception_status == "in_progress"
        assert shipment.reception_note == "Locally checked"
        assert projected["reception_test_status"] == "passed"


def test_done_is_gated_and_admin_override_is_reasoned_and_audited(
    client: TestClient,
    session_factory,
    tudo,
):
    with session_factory() as session:
        institute = session.get(InstituteProfile, tudo["id"])
        institute.settings = {"shipment_reception_tests": {"MODULE": ["RECEPTION_IV"]}}
        session.add(_component("GATED", "MODULE", tudo["code"]))
        shipment = _shipment(
            session,
            institute,
            {"sn": "GATED", "component_type": "MODULE"},
        )
        session.commit()
        shipment_id = shipment.id

    authenticate(
        client,
        session_factory,
        role="operator",
        institute_id=tudo["id"],
        email="receiver@example.org",
    )
    blocked = client.post(
        f"/api/shipments/{shipment_id}/reception",
        json={"status": "done"},
    )
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["detail"]["reception_test_status"] == "missing"

    forbidden = client.post(
        f"/api/shipments/{shipment_id}/reception",
        json={
            "status": "done",
            "test_override": True,
            "test_override_reason": "Urgent transfer",
        },
    )
    assert forbidden.status_code == 403, forbidden.text

    authenticate(
        client,
        session_factory,
        role="admin",
        institute_id=tudo["id"],
        email="reception-admin@example.org",
    )
    no_reason = client.post(
        f"/api/shipments/{shipment_id}/reception",
        json={"status": "done", "test_override": True},
    )
    assert no_reason.status_code == 422, no_reason.text

    overridden = client.post(
        f"/api/shipments/{shipment_id}/reception",
        json={
            "status": "done",
            "test_override": True,
            "test_override_reason": "Documented transport exception",
        },
    )
    assert overridden.status_code == 200, overridden.text
    assert overridden.json()["reception_status"] == "done"

    with session_factory() as session:
        audit = session.scalar(
            select(AuditEvent)
            .where(AuditEvent.action == "shipment.reception_test_override")
            .order_by(AuditEvent.id.desc())
        )
        assert audit is not None
        assert audit.user_id is not None
        assert audit.detail == {
            "pdb_id": "reception-shipment",
            "reception_test_status": "missing",
            "reason": "Documented transport exception",
        }


def test_passed_evidence_allows_done_without_override(
    client: TestClient,
    session_factory,
    tudo,
):
    with session_factory() as session:
        institute = session.get(InstituteProfile, tudo["id"])
        institute.settings = {"shipment_reception_tests": {"MODULE": ["RECEPTION_IV"]}}
        session.add(_component("READY", "MODULE", tudo["code"], dummy=True))
        shipment = _shipment(
            session,
            institute,
            {"sn": "READY", "component_type": "MODULE"},
        )
        session.add(
            TestRunEvidence(
                component_sn="READY",
                test_type="RECEPTION_IV",
                passed=True,
                external_ref="ready-run",
            )
        )
        session.commit()
        shipment_id = shipment.id

    authenticate(
        client,
        session_factory,
        role="operator",
        institute_id=tudo["id"],
        email="ready-receiver@example.org",
    )
    response = client.post(
        f"/api/shipments/{shipment_id}/reception",
        json={"status": "done"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["reception_test_status"] == "passed"


def test_shipment_mutations_enforce_institute_scope(
    client: TestClient,
    session_factory,
    tudo,
):
    with session_factory() as session:
        own = InstituteProfile(code="OTHER", name="Other", local_name_prefix="OTHER-")
        session.add(own)
        session.flush()
        tudo_profile = session.get(InstituteProfile, tudo["id"])
        shipment = _shipment(
            session,
            tudo_profile,
            {"sn": "SCOPED", "component_type": "MODULE"},
        )
        session.commit()
        own_id = own.id
        shipment_id = shipment.id

    authenticate(
        client,
        session_factory,
        role="operator",
        institute_id=own_id,
        email="foreign-receiver@example.org",
    )
    reception = client.post(
        f"/api/shipments/{shipment_id}/reception",
        json={"note": "foreign edit"},
    )
    assert reception.status_code == 403, reception.text

    # Scope is evaluated before any personal-PDB gateway call.
    sync = client.post(f"/api/sync/shipments/{tudo['code']}")
    assert sync.status_code == 403, sync.text
