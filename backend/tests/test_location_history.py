"""Where a component has been, and when it moved.

The PDB records a shipment as an entry in `locations[]`, but names the site
only by its internal institution object id — so a mirrored entry without a
resolution step would read "moved somewhere on this date", which is worse than
saying nothing. `listInstitutions` resolves all 156 sites in one request, so
the sync can name the place.

Only components that actually moved carry entries. That is the right shape: a
relocation is an event, not a standing property, and the component's current
location is already a column.
"""

from datetime import datetime

import pytest
from authutil import authenticate
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models import Component, LocationEvent
from app.pdb_credentials import generate_pdb_credential_encryption_key
from app.pdb_sync import map_pdb_component
from app.sync import sync_components

MODULE_SN = "20USE5L0000754"


@pytest.fixture()
def client() -> TestClient:
    settings = Settings(
        database_url="sqlite:///:memory:",
        pdb_credential_encryption_key=generate_pdb_credential_encryption_key(),
        _env_file=None,
    )
    return TestClient(create_app(settings))


@pytest.fixture()
def as_operator(client) -> TestClient:
    authenticate(client, client.app.state.session_factory, role="operator")
    return client


def _payload(**overrides) -> dict:
    payload = {
        "id": "OID",
        "serialNumber": MODULE_SN,
        "state": "ready",
        "componentType": {"code": "MODULE"},
        "type": {"code": "R5M1_HALFMODULE"},
        "institution": {"code": "TUDO"},
        "currentLocation": {"code": "UNIFREIBURG"},
        "currentStage": {"code": "STITCH_BONDING"},
        "parents": [],
    }
    payload.update(overrides)
    return payload


def test_a_relocation_is_mapped_with_the_site_it_moved_to():
    """The entry names the institution by object id; the map supplies the code."""
    payload = _payload(
        locations=[
            {
                "institution": "5a84991d71b08600052cada2",
                "dateTime": "2026-08-10T12:56:57.168Z",
                "stage": "STITCH_BONDING",
            }
        ]
    )

    record = map_pdb_component(payload, {}, {"5a84991d71b08600052cada2": "UNIFREIBURG"})

    assert record is not None
    assert [(e.location, e.stage) for e in record.location_events] == [
        ("UNIFREIBURG", "STITCH_BONDING")
    ]
    assert record.location_events[0].entered_at.year == 2026


def test_an_unresolvable_site_is_dropped_rather_than_shown_as_an_object_id():
    """"Moved to 5a84991d…" is not information. Silence beats a raw id."""
    payload = _payload(
        locations=[{"institution": "UNKNOWN-OID", "dateTime": "2026-08-10T12:56:57.168Z"}]
    )

    record = map_pdb_component(payload, {}, {})

    assert record is not None and record.location_events == []


def test_an_entry_without_a_date_is_dropped():
    payload = _payload(locations=[{"institution": "OID-A"}, {"dateTime": "2026-08-10T00:00:00Z"}])

    record = map_pdb_component(payload, {}, {"OID-A": "CERN"})

    assert record is not None and record.location_events == []


def test_resyncing_the_same_component_does_not_duplicate_its_moves(session_factory):
    """The listing returns a component twice when it is owned *and* located here."""
    payload = _payload(
        locations=[
            {"institution": "OID-A", "dateTime": "2026-08-10T12:56:57.168Z"},
            {"institution": "OID-A", "dateTime": "2026-08-10T12:56:57.168Z"},
        ]
    )
    record = map_pdb_component(payload, {}, {"OID-A": "UNIFREIBURG"})
    assert record is not None

    with session_factory() as session:
        sync_components(session, [record])
        sync_components(session, [record])
        session.commit()

    with session_factory() as session:
        rows = session.query(LocationEvent).all()
        assert [(r.component_sn, r.location) for r in rows] == [
            (MODULE_SN, "UNIFREIBURG")
        ]


def test_the_history_shows_a_move_beside_stages_and_runs(as_operator):
    factory = as_operator.app.state.session_factory
    with factory() as session:
        session.add(
            Component(
                sn=MODULE_SN,
                component_type="MODULE",
                type_code="R5M1_HALFMODULE",
                stage="STITCH_BONDING",
                location="UNIFREIBURG",
                institute_code="TUDO",
                local_name="TUDO-0040",
            )
        )
        session.add(
            LocationEvent(
                component_sn=MODULE_SN,
                location="UNIFREIBURG",
                entered_at=datetime(2026, 8, 10, 12, 56, 57),
                stage="STITCH_BONDING",
            )
        )
        session.commit()

    events = as_operator.get(f"/api/components/{MODULE_SN}/history").json()["events"]

    assert [e["kind"] for e in events] == ["location"]
    assert events[0]["location"] == "UNIFREIBURG"
    assert events[0]["at"] == "2026-08-10T12:56:57"
