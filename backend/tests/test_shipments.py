"""Tests for the shipment mirror and the local receiving check (docs/11)."""

from authutil import authenticate
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import InstituteProfile, Shipment
from app.pdb_shipments import ShipmentRecord, fetch_shipments_for_institute
from app.shipment_sync import DEFAULT_RECEPTION_CHECKLIST, sync_shipments


class FakeClient:
    """Answers the two PDB shipment reads the fetch layer performs."""

    def __init__(self, shipments_by_role: dict[str, list], items_by_id: dict[str, list]):
        self.shipments_by_role = shipments_by_role
        self.items_by_id = items_by_id
        self.item_requests: list[str] = []

    def get(self, action: str, json: dict | None = None):
        if action == "listShipmentsByInstitution":
            filter_map = (json or {}).get("filterMap", {})
            for role in ("recipient", "sender"):
                if role in filter_map:
                    return {"itemList": self.shipments_by_role.get(role, [])}
            return {"itemList": []}
        if action == "listShipmentItems":
            shipment_id = (json or {}).get("shipment")
            self.item_requests.append(shipment_id)
            return {"itemList": self.items_by_id.get(shipment_id, [])}
        raise AssertionError(f"unexpected PDB action {action}")


class FakeGateway:
    is_configured = True

    def __init__(self, client: FakeClient):
        self._client = client

    def client(self) -> FakeClient:
        return self._client


def shipment_row(pdb_id: str, sender: str, recipient: str, status: str = "inTransit") -> dict:
    return {
        "id": pdb_id,
        "name": f"Shipment {pdb_id}",
        "sender": {"code": sender},
        "recipient": {"code": recipient},
        "status": status,
        "sentTs": "2026-08-20T10:00:00Z",
    }


def item_row(sn: str) -> dict:
    return {"component": {"serialNumber": sn, "componentType": {"code": "MODULE"}}}


def test_fetch_merges_both_directions_and_maps_items():
    client = FakeClient(
        shipments_by_role={
            "recipient": [shipment_row("s1", "DESYZ", "TUDO")],
            "sender": [shipment_row("s2", "TUDO", "DESYZ"), shipment_row("s1", "DESYZ", "TUDO")],
        },
        items_by_id={"s1": [item_row("20USEM00000435")], "s2": []},
    )
    records = fetch_shipments_for_institute(FakeGateway(client), "TUDO")
    by_id = {record.pdb_id: record for record in records}
    assert set(by_id) == {"s1", "s2"}  # duplicate s1 merged
    assert by_id["s1"].items == [{"sn": "20USEM00000435", "component_type": "MODULE"}]
    assert by_id["s1"].sent_at is not None
    assert by_id["s2"].items == []


def test_fetch_skips_items_for_delivered_mirrored_shipments():
    client = FakeClient(
        shipments_by_role={"recipient": [shipment_row("s1", "DESYZ", "TUDO", "delivered")]},
        items_by_id={"s1": [item_row("X")]},
    )
    records = fetch_shipments_for_institute(
        FakeGateway(client), "TUDO", skip_items_for={"s1"}
    )
    assert client.item_requests == []
    assert records[0].items_fetched is False


def test_sync_preserves_local_reception_fields(client: TestClient, session_factory, tudo: dict):
    with session_factory() as session:
        institute = session.get(InstituteProfile, tudo["id"])
        record = ShipmentRecord(
            pdb_id="s1",
            name="Box 1",
            sender_code="DESYZ",
            recipient_code="TUDO",
            status="inTransit",
            items=[{"sn": "20USEM00000435"}],
        )
        stats = sync_shipments(session, institute, [record])
        assert stats.created == 1
        session.commit()

        shipment = session.scalar(select(Shipment).where(Shipment.pdb_id == "s1"))
        # Checklist instantiated from the (default) template on first mirror.
        assert [item["label"] for item in shipment.reception_checklist] == list(
            DEFAULT_RECEPTION_CHECKLIST
        )
        shipment.reception_status = "done"
        shipment.reception_note = "all fine"
        session.commit()

        # A re-sync with new PDB state must keep the local receiving check.
        record2 = record.model_copy(update={"status": "delivered"})
        stats2 = sync_shipments(session, institute, [record2])
        assert stats2.updated == 1
        session.commit()
        shipment = session.scalar(select(Shipment).where(Shipment.pdb_id == "s1"))
        assert shipment.status == "delivered"
        assert shipment.reception_status == "done"
        assert shipment.reception_note == "all fine"


def test_checklist_template_from_institute_profile(client: TestClient, session_factory, tudo):
    with session_factory() as session:
        institute = session.get(InstituteProfile, tudo["id"])
        institute.settings = {"shipment_reception_checklist": ["Count modules", "Check RH strip"]}
        session.commit()
        record = ShipmentRecord(
            pdb_id="s9", sender_code="DESYZ", recipient_code="TUDO", status="inTransit"
        )
        sync_shipments(session, institute, [record])
        session.commit()
        shipment = session.scalar(select(Shipment).where(Shipment.pdb_id == "s9"))
        assert [item["label"] for item in shipment.reception_checklist] == [
            "Count modules",
            "Check RH strip",
        ]


def test_sync_endpoint_mirrors_and_answers_counts(
    as_operator: TestClient, session_factory, tudo: dict
):
    fake = FakeGateway(
        FakeClient(
            shipments_by_role={
                "recipient": [shipment_row("s1", "DESYZ", "TUDO")],
                "sender": [shipment_row("s2", "TUDO", "DESYZ")],
            },
            items_by_id={"s1": [item_row("20USEM00000435")], "s2": []},
        )
    )
    as_operator.app.state.pdb_gateway = fake
    response = as_operator.post(f"/api/sync/shipments/{tudo['code']}")
    assert response.status_code == 200, response.text
    assert response.json()["created"] == 2

    listed = as_operator.get("/api/shipments").json()
    directions = {row["pdb_id"]: row["direction"] for row in listed}
    assert directions == {"s1": "incoming", "s2": "outgoing"}

    incoming = as_operator.get("/api/shipments", params={"direction": "incoming"}).json()
    assert [row["pdb_id"] for row in incoming] == ["s1"]


def test_sync_endpoint_answers_503_when_pdb_unreachable(
    as_operator: TestClient, tudo: dict
):
    class DownGateway:
        is_configured = False

    as_operator.app.state.pdb_gateway = DownGateway()
    response = as_operator.post(f"/api/sync/shipments/{tudo['code']}")
    assert response.status_code == 503, response.text


def test_reception_update_is_operator_gated_and_audited(
    client: TestClient, session_factory, tudo: dict
):
    with session_factory() as session:
        institute = session.get(InstituteProfile, tudo["id"])
        sync_shipments(
            session,
            institute,
            [
                ShipmentRecord(
                    pdb_id="s1",
                    sender_code="DESYZ",
                    recipient_code="TUDO",
                    status="delivered",
                    items=[{"sn": "A"}, {"sn": "B"}],
                )
            ],
        )
        session.commit()
        shipment_id = session.scalar(select(Shipment.id).where(Shipment.pdb_id == "s1"))

    anonymous = client.post(f"/api/shipments/{shipment_id}/reception", json={"note": "x"})
    assert anonymous.status_code == 401

    authenticate(client, session_factory, role="operator", institute_id=tudo["id"])
    response = client.post(
        f"/api/shipments/{shipment_id}/reception",
        json={
            "items": [{"sn": "A", "received": True}, {"sn": "B", "received": False}],
            "checklist": [{"label": "Packaging intact", "done": True}],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    # First touch moves pending → in_progress without an explicit status.
    assert body["reception_status"] == "in_progress"
    assert body["reception_by"] is not None

    done = client.post(
        f"/api/shipments/{shipment_id}/reception", json={"status": "done"}
    )
    assert done.json()["reception_status"] == "done"
    # Partial update kept the previously recorded per-item state.
    assert done.json()["reception_items"][0] == {"sn": "A", "received": True, "note": None}

    audit = client.get("/api/audit").json()
    assert any(event["action"] == "shipment.reception_updated" for event in audit)
