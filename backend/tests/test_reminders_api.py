# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-FileComment: itkflow-e8ba8b3ed28e
"""Tests for the reminders API, channel listing and the test-notification endpoint."""

from datetime import datetime, timezone

from authutil import authenticate, create_institute_profile
from fastapi.testclient import TestClient

from app.models import InstituteProfile, Reminder, ReminderOccurrence

CHANNELS = {
    "lab": {"kind": "mattermost", "url": "https://mm.example.org/hooks/abc", "channel": "lab"},
    "ops": {"kind": "webhook", "url": "https://hooks.example.org/ops"},
}


def configure_channels(session_factory, institute_id: int) -> None:
    with session_factory() as session:
        institute = session.get(InstituteProfile, institute_id)
        institute.settings = {**(institute.settings or {}), "notification_channels": CHANNELS}
        session.commit()


def test_reminder_crud_and_channel_validation(client: TestClient, session_factory, tudo: dict):
    configure_channels(session_factory, tudo["id"])
    authenticate(client, session_factory, role="operator", institute_id=tudo["id"])

    unknown = client.post(
        "/api/reminders",
        json={"title": "Clean bench", "channel": "nope", "next_due_at": "2026-09-01T08:00:00Z"},
    )
    assert unknown.status_code == 422, unknown.text

    created = client.post(
        "/api/reminders",
        json={
            "title": "Clean bench",
            "channel": "lab",
            "schedule_kind": "weekly",
            "next_due_at": "2026-09-01T08:00:00Z",
        },
    )
    assert created.status_code == 201, created.text
    reminder = created.json()
    assert reminder["active"] is True
    assert reminder["channel"] == "lab"

    updated = client.patch(
        f"/api/reminders/{reminder['id']}", json={"active": False, "channel": ""}
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["active"] is False
    assert updated.json()["channel"] is None

    listed = client.get("/api/reminders").json()
    assert [row["id"] for row in listed] == [reminder["id"]]
    assert client.get("/api/reminders", params={"active": "true"}).json() == []

    deleted = client.delete(f"/api/reminders/{reminder['id']}")
    assert deleted.status_code == 204
    assert client.get("/api/reminders").json() == []

    actions = {event["action"] for event in client.get("/api/audit").json()}
    assert {"reminder.created", "reminder.updated", "reminder.deleted"} <= actions


def test_reminder_writes_require_operator(client: TestClient, as_viewer: TestClient):
    response = as_viewer.post(
        "/api/reminders", json={"title": "X", "next_due_at": "2026-09-01T08:00:00Z"}
    )
    assert response.status_code == 403


def test_deleting_schedule_preserves_open_occurrence(
    client: TestClient, session_factory, tudo: dict
):
    authenticate(
        client,
        session_factory,
        role="operator",
        institute_id=tudo["id"],
        email="durable-task@example.org",
    )
    due_at = datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc)
    with session_factory() as session:
        reminder = Reminder(
            title="Durable task",
            schedule_kind="once",
            next_due_at=due_at,
            created_by="durable-task@example.org",
            institute_id=tudo["id"],
        )
        session.add(reminder)
        session.flush()
        occurrence = ReminderOccurrence(
            reminder_id=reminder.id,
            institute_id=tudo["id"],
            due_at=due_at,
            fired_at=due_at,
        )
        session.add(occurrence)
        session.commit()
        reminder_id = reminder.id
        occurrence_id = occurrence.id

    deleted = client.delete(f"/api/reminders/{reminder_id}")
    assert deleted.status_code == 204, deleted.text
    assert client.get("/api/reminders").json() == []
    open_tasks = client.get(
        "/api/reminder-occurrences",
        params={"open_only": "true"},
    )
    assert open_tasks.status_code == 200, open_tasks.text
    assert [item["id"] for item in open_tasks.json()] == [occurrence_id]

    with session_factory() as session:
        stored_reminder = session.get(Reminder, reminder_id)
        stored_occurrence = session.get(ReminderOccurrence, occurrence_id)
        assert stored_reminder is not None
        assert stored_reminder.deleted_at is not None
        assert stored_reminder.active is False
        assert stored_occurrence is not None


def test_channels_endpoint_lists_names_without_urls(
    client: TestClient, session_factory, tudo: dict
):
    configure_channels(session_factory, tudo["id"])
    authenticate(client, session_factory, role="viewer", institute_id=tudo["id"])
    response = client.get("/api/notifications/channels")
    assert response.status_code == 200, response.text
    assert response.json() == [
        {"name": "lab", "kind": "mattermost"},
        {"name": "ops", "kind": "webhook"},
    ]
    # Never leak the webhook URL anywhere in the response.
    assert "hooks" not in response.text


def test_institute_api_redacts_channel_urls(client: TestClient, session_factory, tudo: dict):
    configure_channels(session_factory, tudo["id"])
    listed = client.get("/api/institutes").json()
    channels = listed[0]["settings"]["notification_channels"]
    assert channels["lab"]["url"] == "***"
    assert channels["ops"]["url"] == "***"
    # The stored profile keeps the real URL — only API responses are masked.
    with session_factory() as session:
        stored = session.get(InstituteProfile, tudo["id"])
        assert stored.settings["notification_channels"]["lab"]["url"].startswith("https://")


def test_notification_test_endpoint_uses_injected_notifier(
    client: TestClient, session_factory, tudo: dict
):
    configure_channels(session_factory, tudo["id"])
    authenticate(client, session_factory, role="admin", institute_id=tudo["id"])

    sent: list[tuple[dict, str, str]] = []
    client.app.state.notifier = lambda channel, title, text: sent.append((channel, title, text))

    response = client.post("/api/notifications/test", json={"channel": "lab"})
    assert response.status_code == 200, response.text
    assert response.json() == {"channel": "lab", "sent": True}
    assert len(sent) == 1
    assert sent[0][0]["kind"] == "mattermost"

    missing = client.post("/api/notifications/test", json={"channel": "nope"})
    assert missing.status_code == 422

    actions = {event["action"] for event in client.get("/api/audit").json()}
    assert "notification.test_sent" in actions


def test_notification_test_requires_admin(client: TestClient, session_factory, tudo: dict):
    configure_channels(session_factory, tudo["id"])
    authenticate(client, session_factory, role="operator", institute_id=tudo["id"])
    response = client.post("/api/notifications/test", json={"channel": "lab"})
    assert response.status_code == 403


def test_global_admin_must_select_and_can_test_a_target_institute(
    as_admin: TestClient, session_factory, tudo: dict
):
    configure_channels(session_factory, tudo["id"])
    sent: list[tuple[dict, str, str]] = []
    as_admin.app.state.notifier = lambda channel, title, text: sent.append(
        (channel, title, text)
    )

    missing_target = as_admin.post("/api/notifications/test", json={"channel": "lab"})
    assert missing_target.status_code == 400, missing_target.text
    assert sent == []

    response = as_admin.post(
        "/api/notifications/test",
        json={"channel": "lab", "institute_code": "TUDO"},
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"channel": "lab", "sent": True}
    assert len(sent) == 1

    unknown = as_admin.post(
        "/api/notifications/test",
        json={"channel": "lab", "institute_code": "NOPE"},
    )
    assert unknown.status_code == 404, unknown.text
    assert len(sent) == 1


def test_institute_admin_cannot_test_another_institutes_channel(
    client: TestClient, session_factory, tudo: dict
):
    other = create_institute_profile(
        session_factory,
        code="DESYZ",
        name="Other institute",
    )
    configure_channels(session_factory, tudo["id"])
    configure_channels(session_factory, other["id"])
    authenticate(client, session_factory, role="admin", institute_id=tudo["id"])
    sent: list[tuple[dict, str, str]] = []
    client.app.state.notifier = lambda channel, title, text: sent.append((channel, title, text))

    forbidden = client.post(
        "/api/notifications/test",
        json={"channel": "lab", "institute_code": "DESYZ"},
    )
    assert forbidden.status_code == 403, forbidden.text
    assert sent == []

    own = client.post(
        "/api/notifications/test",
        json={"channel": "lab", "institute_code": "TUDO"},
    )
    assert own.status_code == 200, own.text
    assert len(sent) == 1


def test_occurrence_acknowledgement_is_audited_and_institute_scoped(
    client: TestClient, session_factory, tudo: dict
):
    other = create_institute_profile(
        session_factory,
        code="DESYZ",
        name="DESY Zeuthen",
    )
    due_at = datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc)
    fired_at = datetime(2026, 9, 1, 8, 0, 1, tzinfo=timezone.utc)
    with session_factory() as session:
        own_reminder = Reminder(
            title="Own task",
            schedule_kind="once",
            next_due_at=due_at,
            created_by="operator@example.org",
            institute_id=tudo["id"],
        )
        foreign_reminder = Reminder(
            title="Foreign task",
            schedule_kind="once",
            next_due_at=due_at,
            created_by="other@example.org",
            institute_id=other["id"],
        )
        session.add_all([own_reminder, foreign_reminder])
        session.flush()
        own = ReminderOccurrence(
            reminder_id=own_reminder.id,
            institute_id=tudo["id"],
            due_at=due_at,
            fired_at=fired_at,
        )
        foreign = ReminderOccurrence(
            reminder_id=foreign_reminder.id,
            institute_id=other["id"],
            due_at=due_at,
            fired_at=fired_at,
        )
        session.add_all([own, foreign])
        session.commit()
        own_id, foreign_id = own.id, foreign.id

    authenticate(
        client,
        session_factory,
        role="operator",
        institute_id=tudo["id"],
        email="ack@example.org",
    )
    listed = client.get("/api/reminder-occurrences", params={"open_only": "true"})
    assert listed.status_code == 200, listed.text
    assert [row["id"] for row in listed.json()] == [own_id]

    forbidden = client.post(f"/api/reminder-occurrences/{foreign_id}/ack")
    assert forbidden.status_code == 403
    acknowledged = client.post(f"/api/reminder-occurrences/{own_id}/ack")
    assert acknowledged.status_code == 200, acknowledged.text
    assert acknowledged.json()["acknowledged_by"] == "ack@example.org"
    assert acknowledged.json()["acknowledged_at"] is not None
    # Idempotent acknowledgement does not create duplicate audit rows.
    assert client.post(f"/api/reminder-occurrences/{own_id}/ack").status_code == 200
    events = [
        event
        for event in client.get("/api/audit").json()
        if event["action"] == "reminder.acknowledged"
    ]
    assert len(events) == 1
