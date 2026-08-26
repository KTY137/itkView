"""Tests for the notification adapter (app/notifications.py)."""

import io
import json
import urllib.error

import pytest

from app.config import Settings
from app.notifications import (
    NotificationError,
    channel_configs,
    make_notifier,
    redact_channel_urls,
)


def settings() -> Settings:
    return Settings(database_url="sqlite:///:memory:", _env_file=None)


def test_channel_configs_drops_malformed_entries():
    raw = {
        "notification_channels": {
            "ok": {
                "kind": "mattermost",
                "url": "https://mm.example.org/hooks/a",
                "channel": "lab",
                "unknown_secret": "must-not-propagate",
            },
            "http-url": {"kind": "webhook", "url": "http://insecure.example.org"},
            "bad-kind": {"kind": "email", "url": "https://x.example.org"},
            "no-url": {"kind": "webhook"},
            "not-a-dict": "nope",
            "bad-port": {"kind": "webhook", "url": "https://x.example.org:99999/hook"},
            "bad-target": {
                "kind": "mattermost",
                "url": "https://x.example.org/hook",
                "channel": {"secret": "not-a-string"},
            },
        }
    }
    assert channel_configs(raw) == {
        "ok": {
            "kind": "mattermost",
            "url": "https://mm.example.org/hooks/a",
            "channel": "lab",
        }
    }
    assert channel_configs({}) == {}
    assert channel_configs(None) == {}
    assert channel_configs({"notification_channels": "broken"}) == {}


def test_redact_channel_urls_masks_without_mutating():
    original = {
        "other_key": 1,
        "notification_channels": {
            "lab": {
                "kind": "mattermost",
                "url": "https://mm.example.org/hooks/a",
                "channel": "operations",
                "fallback_url": "https://secret.example.org/fallback",
                "token": "legacy-secret",
            },
            "broken": {
                "kind": "email",
                "url": "https://secret.example.org/broken",
                "api_key": "another-secret",
            },
            "not-an-object": "https://secret.example.org/raw",
        },
    }
    redacted = redact_channel_urls(original)
    assert redacted["notification_channels"] == {
        "lab": {"kind": "mattermost", "url": "***", "channel": "operations"}
    }
    assert redacted["other_key"] == 1
    assert "secret.example.org" not in json.dumps(redacted)
    assert "legacy-secret" not in json.dumps(redacted)
    # The source dict (the ORM row's JSON!) must stay untouched.
    assert original["notification_channels"]["lab"]["url"].startswith("https://")


def test_redaction_replaces_a_malformed_channel_container_with_an_empty_object():
    redacted = redact_channel_urls(
        {"notification_channels": "https://secret.example.org/raw", "keep": True}
    )
    assert redacted == {"notification_channels": {}, "keep": True}


def test_mattermost_payload_and_success(monkeypatch: pytest.MonkeyPatch):
    captured: dict = {}

    class FakeResponse(io.BytesIO):
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    notify = make_notifier(settings())
    channel = {"kind": "mattermost", "url": "https://mm.example.org/hooks/a", "channel": "lab"}
    notify(channel, "Clean bench", "Weekly duty")

    assert captured["url"] == "https://mm.example.org/hooks/a"
    assert captured["body"] == {"text": "**Clean bench**\nWeekly duty", "channel": "lab"}
    assert captured["timeout"] == settings().notify_timeout_seconds


def test_generic_webhook_payload(monkeypatch: pytest.MonkeyPatch):
    captured: dict = {}

    class FakeResponse(io.BytesIO):
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout=None):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    make_notifier(settings())({"kind": "webhook", "url": "https://x.example.org"}, "T", "B")
    assert captured["body"] == {"title": "T", "text": "B"}


def test_failures_never_leak_the_url(monkeypatch: pytest.MonkeyPatch):
    def http_error(request, timeout=None):
        raise urllib.error.HTTPError(
            request.full_url, 500, "boom", hdrs=None, fp=io.BytesIO(b"")
        )

    monkeypatch.setattr("urllib.request.urlopen", http_error)
    notify = make_notifier(settings())
    with pytest.raises(NotificationError) as excinfo:
        notify({"kind": "webhook", "url": "https://secret.example.org/hook"}, "T", "B")
    assert "500" in str(excinfo.value)
    assert "secret.example.org" not in str(excinfo.value)

    def network_error(request, timeout=None):
        raise urllib.error.URLError("https://secret.example.org unreachable")

    monkeypatch.setattr("urllib.request.urlopen", network_error)
    with pytest.raises(NotificationError) as excinfo:
        notify({"kind": "webhook", "url": "https://secret.example.org/hook"}, "T", "B")
    assert "secret.example.org" not in str(excinfo.value)


def test_channel_without_https_url_is_refused():
    notify = make_notifier(settings())
    with pytest.raises(NotificationError):
        notify({"kind": "webhook", "url": "http://x.example.org"}, "T", "B")
    with pytest.raises(NotificationError):
        notify({"kind": "webhook"}, "T", "B")


def test_telegram_channel_requires_a_valid_chat_id():
    """Telegram cannot address anyone without a chat id, so half a config is no
    config — it must be dropped rather than fail at delivery time."""
    def one(config: dict) -> dict:
        return channel_configs({"notification_channels": {"alerts": config}})

    url = "https://api.telegram.org/bot123:SECRET/sendMessage"
    assert one({"kind": "telegram", "url": url}) == {}
    assert one({"kind": "telegram", "url": url, "chat_id": 4711}) == {}
    assert one({"kind": "telegram", "url": url, "chat_id": "not a chat"}) == {}
    assert one({"kind": "telegram", "url": url, "chat_id": "-1001234567890"}) == {
        "alerts": {"kind": "telegram", "url": url, "chat_id": "-1001234567890"}
    }
    assert one({"kind": "telegram", "url": url, "chat_id": "@itkflow_alerts"}) == {
        "alerts": {"kind": "telegram", "url": url, "chat_id": "@itkflow_alerts"}
    }


def test_telegram_payload_and_token_redaction(monkeypatch: pytest.MonkeyPatch):
    captured: dict = {}

    class FakeResponse(io.BytesIO):
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    channel = {
        "kind": "telegram",
        "url": "https://api.telegram.org/bot123:SECRET/sendMessage",
        "chat_id": "-1001234567890",
    }
    make_notifier(settings())(channel, "Clean bench", "Weekly duty")
    assert captured["body"] == {
        "chat_id": "-1001234567890",
        "text": "Clean bench" + chr(10) + "Weekly duty",
    }

    # The bot token lives in the URL, so the profile API must never echo it.
    redacted = redact_channel_urls({"notification_channels": {"alerts": channel}})
    assert redacted["notification_channels"]["alerts"] == {
        "kind": "telegram",
        "url": "***",
        "chat_id": "-1001234567890",
    }
    assert "SECRET" not in json.dumps(redacted)


def test_email_channel_sends_through_smtp_ssl_and_redacts_password(
    monkeypatch: pytest.MonkeyPatch,
):
    captured: dict = {}

    class FakeSmtp:
        def __init__(self, host, port, *, timeout, context):
            captured.update(host=host, port=port, timeout=timeout, context=context)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def login(self, username, password):
            captured["login"] = (username, password)

        def send_message(self, message):
            captured["message"] = message

    monkeypatch.setattr("smtplib.SMTP_SSL", FakeSmtp)
    channel = {
        "kind": "email",
        "smtp_host": "smtp.example.org",
        "smtp_port": 465,
        "smtp_security": "ssl",
        "smtp_username": "mailer@example.org",
        "smtp_password": "smtp-secret",
        "from_address": "itkflow@example.org",
        "to_address": "lab@example.org",
    }
    assert channel_configs({"notification_channels": {"mail": channel}}) == {
        "mail": channel
    }

    make_notifier(settings())(channel, "Clean\nbench", "Weekly duty")
    assert captured["host"] == "smtp.example.org"
    assert captured["port"] == 465
    assert captured["timeout"] == settings().notify_timeout_seconds
    assert captured["login"] == ("mailer@example.org", "smtp-secret")
    assert captured["message"]["Subject"] == "Clean bench"
    assert captured["message"]["To"] == "lab@example.org"

    redacted = redact_channel_urls({"notification_channels": {"mail": channel}})
    assert redacted["notification_channels"]["mail"] == {
        "kind": "email",
        "smtp_host": "smtp.example.org",
        "smtp_port": 465,
        "smtp_security": "ssl",
        "smtp_username": "mailer@example.org",
        "smtp_password": "***",
        "from_address": "itkflow@example.org",
        "to_address": "lab@example.org",
    }
    assert "smtp-secret" not in json.dumps(redacted)


def test_email_delivery_failure_does_not_leak_smtp_configuration(
    monkeypatch: pytest.MonkeyPatch,
):
    def broken(*args, **kwargs):
        raise RuntimeError("smtp.example.org rejected smtp-secret")

    monkeypatch.setattr("smtplib.SMTP", broken)
    channel = {
        "kind": "email",
        "smtp_host": "smtp.example.org",
        "smtp_port": 587,
        "smtp_security": "starttls",
        "smtp_username": "mailer@example.org",
        "smtp_password": "smtp-secret",
        "from_address": "itkflow@example.org",
        "to_address": "lab@example.org",
    }
    with pytest.raises(NotificationError) as excinfo:
        make_notifier(settings())(channel, "Title", "Text")
    assert "smtp.example.org" not in str(excinfo.value)
    assert "smtp-secret" not in str(excinfo.value)
