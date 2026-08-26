"""Tests for the glue-batch registry: lifecycle, pot-life timer, usage (docs/11)."""

from datetime import datetime, timedelta, timezone

from authutil import authenticate
from fastapi.testclient import TestClient

from app.domain.glue import pot_life_state
from app.models import GlueBatch, InstituteProfile


def make_batch(client: TestClient, **overrides) -> dict:
    payload = {"glue_type": "POLARIS_EPOXY", "batch_no": "AB12CD34EF", **overrides}
    response = client.post("/api/glue-batches", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_pot_life_state_counts_down_and_expires():
    mixed_at = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
    running = pot_life_state(mixed_at, 30, now=mixed_at + timedelta(minutes=10))
    assert running is not None
    assert running.remaining_seconds == 20 * 60
    assert not running.expired

    over = pot_life_state(mixed_at, 30, now=mixed_at + timedelta(minutes=31))
    assert over is not None
    assert over.remaining_seconds == 0
    assert over.expired

    # Naive timestamps (SQLite round-trip) are treated as UTC, not rejected.
    naive = pot_life_state(mixed_at.replace(tzinfo=None), 30, now=mixed_at)
    assert naive is not None and naive.remaining_seconds == 30 * 60

    assert pot_life_state(None, 30) is None
    assert pot_life_state(mixed_at, None) is None


def test_glue_batch_create_requires_operator(client: TestClient, as_viewer: TestClient):
    response = as_viewer.post(
        "/api/glue-batches", json={"glue_type": "TRUE_BLUE", "batch_no": "X1"}
    )
    assert response.status_code == 403, response.text


def test_glue_batch_crud_and_scan(as_operator: TestClient):
    batch = make_batch(as_operator, pdb_sn="20USEGT0000098")
    assert batch["status"] == "new"
    assert batch["usage_count"] == 0
    assert batch["pot_life_remaining_seconds"] is None

    # Scan resolves by PDB serial and by batch number, case-insensitively.
    by_sn = as_operator.get("/api/glue-batches/scan", params={"code": "20usegt0000098"})
    assert by_sn.status_code == 200, by_sn.text
    assert by_sn.json()["id"] == batch["id"]
    by_batch = as_operator.get("/api/glue-batches/scan", params={"code": "AB12CD34EF"})
    assert by_batch.json()["id"] == batch["id"]
    missing = as_operator.get("/api/glue-batches/scan", params={"code": "nope"})
    assert missing.status_code == 404

    updated = as_operator.patch(
        f"/api/glue-batches/{batch['id']}", json={"status": "empty", "note": "used up"}
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["status"] == "empty"

    audit = as_operator.get("/api/audit").json()
    actions = {event["action"] for event in audit}
    assert {"glue_batch.created", "glue_batch.updated"} <= actions


def test_glue_batch_list_filters(as_operator: TestClient):
    make_batch(as_operator, glue_type="TRUE_BLUE", batch_no="TB1")
    make_batch(as_operator, glue_type="POLARIS_EPOXY", batch_no="PE1")

    only_tb = as_operator.get("/api/glue-batches", params={"glue_type": "TRUE_BLUE"}).json()
    assert [b["batch_no"] for b in only_tb] == ["TB1"]

    by_q = as_operator.get("/api/glue-batches", params={"q": "pe1"}).json()
    assert [b["batch_no"] for b in by_q] == ["PE1"]


def test_glue_batch_list_and_scan_filter_by_parent_institute(
    as_operator: TestClient, session_factory, tudo: dict
):
    with session_factory() as session:
        other = InstituteProfile(code="FZU", name="FZU", local_name_prefix="FZU-")
        session.add(other)
        session.flush()
        session.add_all(
            [
                GlueBatch(
                    institute_id=tudo["id"],
                    glue_type="POLARIS_EPOXY",
                    batch_no="SHARED-BATCH",
                    pdb_sn="20USEGT0000199",
                    status="in_use",
                ),
                GlueBatch(
                    institute_id=other.id,
                    glue_type="TRUE_BLUE",
                    batch_no="SHARED-BATCH",
                    pdb_sn="20USEGT0000199",
                    status="in_use",
                ),
            ]
        )
        session.commit()

    tudo_rows = as_operator.get(
        "/api/glue-batches", params={"status": "in_use", "institute": "tudo"}
    )
    assert tudo_rows.status_code == 200
    assert [batch["glue_type"] for batch in tudo_rows.json()] == ["POLARIS_EPOXY"]

    fzu_scan = as_operator.get(
        "/api/glue-batches/scan",
        params={"code": "shared-batch", "institute": "fzu"},
    )
    assert fzu_scan.status_code == 200
    assert fzu_scan.json()["glue_type"] == "TRUE_BLUE"

    assert as_operator.get(
        "/api/glue-batches", params={"institute": "UNKNOWN"}
    ).json() == []
    assert (
        as_operator.get(
            "/api/glue-batches/scan",
            params={"code": "SHARED-BATCH", "institute": "UNKNOWN"},
        ).status_code
        == 404
    )


def test_glue_batch_mutations_reject_foreign_institute_ids_without_side_effects(
    client: TestClient, session_factory, tudo: dict
):
    authenticate(
        client,
        session_factory,
        role="operator",
        institute_id=tudo["id"],
        email="scoped-glue-operator@example.test",
    )
    with session_factory() as session:
        other = InstituteProfile(code="FZU", name="FZU", local_name_prefix="FZU-")
        session.add(other)
        session.flush()
        batch = GlueBatch(
            institute_id=other.id,
            glue_type="POLARIS_EPOXY",
            batch_no="FOREIGN-BATCH",
            status="new",
            note="unchanged",
        )
        session.add(batch)
        session.commit()
        batch_id = batch.id

    requests = [
        client.patch(
            f"/api/glue-batches/{batch_id}",
            json={"status": "empty", "note": "must not change"},
        ),
        client.post(f"/api/glue-batches/{batch_id}/mix", json={"pot_life_minutes": 10}),
        client.post(
            f"/api/glue-batches/{batch_id}/usage",
            json={"component_sn": "20USEM00000436", "amount_mg": 12.5},
        ),
    ]
    assert [response.status_code for response in requests] == [403, 403, 403]

    with session_factory() as session:
        stored = session.get(GlueBatch, batch_id)
        assert stored is not None
        assert stored.status == "new"
        assert stored.note == "unchanged"
        assert stored.mixed_at is None
        assert stored.pot_life_minutes is None
        assert stored.usages == []


def test_mix_starts_pot_life_from_profile_default(
    client: TestClient, session_factory, tudo: dict
):
    # Institute profile carries the per-type pot life — hard rule #4.
    response = client.patch(
        f"/api/institutes/{tudo['code']}",
        json={"settings": {"glue_pot_life_minutes": {"POLARIS_EPOXY": 45}}},
    )
    # PATCH needs an admin session bound to the institute.
    assert response.status_code in (401, 403)  # anonymous refused first
    authenticate(client, session_factory, role="admin", institute_id=tudo["id"])
    response = client.patch(
        f"/api/institutes/{tudo['code']}",
        json={"settings": {"glue_pot_life_minutes": {"POLARIS_EPOXY": 45}}},
    )
    assert response.status_code == 200, response.text

    batch = make_batch(client)
    mixed = client.post(f"/api/glue-batches/{batch['id']}/mix", json={})
    assert mixed.status_code == 200, mixed.text
    body = mixed.json()
    assert body["status"] == "in_use"
    assert body["pot_life_minutes"] == 45
    assert body["mixed_at"] is not None
    assert body["opening_date"] is not None
    assert 0 < body["pot_life_remaining_seconds"] <= 45 * 60
    assert body["pot_life_expired"] is False


def test_mix_explicit_pot_life_wins_and_terminal_batches_refuse(
    client: TestClient, session_factory, tudo: dict
):
    authenticate(client, session_factory, role="operator", institute_id=tudo["id"])
    batch = make_batch(client)
    mixed = client.post(f"/api/glue-batches/{batch['id']}/mix", json={"pot_life_minutes": 20})
    assert mixed.json()["pot_life_minutes"] == 20

    client.patch(f"/api/glue-batches/{batch['id']}", json={"status": "empty"})
    refused = client.post(f"/api/glue-batches/{batch['id']}/mix", json={})
    assert refused.status_code == 409


def test_usage_recording_links_component_and_blocks_dead_batches(
    as_operator: TestClient, session_factory
):
    batch = make_batch(as_operator)
    usage = as_operator.post(
        f"/api/glue-batches/{batch['id']}/usage",
        json={"component_sn": "20USEM00000435", "amount_mg": 135.2},
    )
    assert usage.status_code == 201, usage.text
    assert usage.json()["component_sn"] == "20USEM00000435"

    # First use flips a fresh batch to in_use and shows up in the counts.
    listed = as_operator.get("/api/glue-batches").json()
    assert listed[0]["status"] == "in_use"
    assert listed[0]["usage_count"] == 1

    log = as_operator.get(f"/api/glue-batches/{batch['id']}/usage").json()
    assert len(log) == 1 and log[0]["amount_mg"] == 135.2

    as_operator.patch(f"/api/glue-batches/{batch['id']}", json={"status": "expired"})
    refused = as_operator.post(
        f"/api/glue-batches/{batch['id']}/usage", json={"component_sn": "20USEM00000436"}
    )
    assert refused.status_code == 409

    with session_factory() as session:
        stored = session.get(GlueBatch, batch["id"])
        assert stored is not None and stored.status == "expired"
