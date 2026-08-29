# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-FileComment: itkflow-0a80502e01ec
"""Pluggable notification adapter (Phase 4, replaces the Telegram watchdogs).

Channel *definitions* are institute-profile data, never code (hard rule #4):
``InstituteProfile.settings['notification_channels']`` maps a channel name to

    {"kind": "mattermost" | "telegram" | "webhook", "url": "https://…", …}

* ``mattermost`` posts a Mattermost incoming-webhook payload (``{"text": …}``
  plus the optional ``channel`` override).
* ``telegram`` posts to a bot's ``sendMessage`` with the required ``chat_id``.
  It needs its own kind because Telegram ignores the generic body shape below.
* ``webhook`` posts a generic ``{"title": …, "text": …}`` JSON body for
  anything else that accepts a webhook (n8n, Zapier, a hand-rolled receiver).

Webhook URLs are credentials in all but name: they never appear in logs,
errors, audit details or non-admin API responses (see ``redact_channel_urls``).

The transport is stdlib ``urllib`` — deliberately no new dependency for one
small POST. The app and worker hold a ``Notifier`` callable built by
``make_notifier``; tests inject a fake the same way ``component_fetcher`` and
the outbox ``Submitter`` are faked.
"""

import json
import re
import smtplib
import ssl
import urllib.error
import urllib.request
from collections.abc import Callable
from email.message import EmailMessage
from typing import Any
from urllib.parse import urlsplit

from app.config import Settings

REDACTED_URL = "***"
_CHANNEL_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_CHANNEL_KINDS = ("mattermost", "telegram", "webhook", "email")
# Telegram addresses a conversation by id (``-100…`` for groups) or ``@name``.
_CHAT_ID_RE = re.compile(r"-?[0-9]{1,32}\Z|@[A-Za-z0-9_]{1,64}\Z")
_EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+\Z")
_SMTP_SECURITY = frozenset({"ssl", "starttls"})

# A Notifier delivers one message (title, text) to one resolved channel config.
Notifier = Callable[[dict, str, str], None]


class NotificationError(RuntimeError):
    """A notification could not be delivered. Messages never carry the URL."""


def is_https_notification_url(value: Any) -> bool:
    """Return whether *value* is a usable, credential-free-authority HTTPS URL.

    The path and query may intentionally contain the webhook credential.  User
    info, whitespace and backslashes are rejected so neither the transport nor
    API redaction has to interpret ambiguous URL syntax.
    """
    if not isinstance(value, str) or not value or any(char.isspace() for char in value):
        return False
    if "\\" in value:
        return False
    try:
        parsed = urlsplit(value)
        # Accessing ``port`` also rejects malformed/out-of-range ports.
        _ = parsed.port
    except ValueError:
        return False
    return bool(
        parsed.scheme.lower() == "https"
        and parsed.hostname
        and parsed.username is None
        and parsed.password is None
    )


def _safe_channel_name(value: Any) -> str | None:
    if not isinstance(value, str) or _CHANNEL_NAME_RE.fullmatch(value) is None:
        return None
    return value


def _safe_channel_config(config: Any) -> dict[str, Any] | None:
    """Project free-form legacy JSON onto the supported server-side contract."""
    if not isinstance(config, dict):
        return None
    kind = config.get("kind")
    if kind not in _CHANNEL_KINDS:
        return None
    if kind == "email":
        host = config.get("smtp_host")
        port = config.get("smtp_port")
        security = config.get("smtp_security")
        sender = config.get("from_address")
        recipient = config.get("to_address")
        username = config.get("smtp_username")
        password = config.get("smtp_password")
        if (
            not isinstance(host, str)
            or not host
            or len(host) > 253
            or any(character.isspace() or ord(character) < 32 for character in host)
            or any(character in host for character in "/\\@")
            or isinstance(port, bool)
            or not isinstance(port, int)
            or not 1 <= port <= 65535
            or security not in _SMTP_SECURITY
            or not isinstance(sender, str)
            or _EMAIL_RE.fullmatch(sender) is None
            or not isinstance(recipient, str)
            or _EMAIL_RE.fullmatch(recipient) is None
            or (username is None) != (password is None)
            or (username is not None and (not isinstance(username, str) or not username))
            or (password is not None and (not isinstance(password, str) or not password))
        ):
            return None
        safe_email: dict[str, Any] = {
            "kind": kind,
            "smtp_host": host,
            "smtp_port": port,
            "smtp_security": security,
            "from_address": sender,
            "to_address": recipient,
        }
        if username is not None and password is not None:
            safe_email["smtp_username"] = username
            safe_email["smtp_password"] = password
        return safe_email

    url = config.get("url")
    if not is_https_notification_url(url):
        return None
    safe = {"kind": kind, "url": url}
    if kind == "telegram":
        # Without a valid chat id the bot call cannot address anyone, so the
        # channel is unusable rather than partially configured.
        chat_id = config.get("chat_id")
        if not isinstance(chat_id, str) or _CHAT_ID_RE.fullmatch(chat_id) is None:
            return None
        safe["chat_id"] = chat_id
    if "channel" in config:
        target = config["channel"]
        if (
            not isinstance(target, str)
            or target != target.strip()
            or not target
            or len(target) > 120
            or any(ord(character) < 32 for character in target)
        ):
            return None
        safe["channel"] = target
    return safe


def channel_configs(settings_dict: dict | None) -> dict[str, dict[str, Any]]:
    """Valid channel definitions from an institute settings dict.

    Malformed entries are dropped, not raised — profile settings are free-form
    JSON edited by admins, and one bad entry must not break the others.
    """
    raw = (settings_dict or {}).get("notification_channels")
    if not isinstance(raw, dict):
        return {}
    channels: dict[str, dict[str, Any]] = {}
    for name, config in raw.items():
        safe_name = _safe_channel_name(name)
        safe_config = _safe_channel_config(config)
        if safe_name is None or safe_config is None:
            continue
        channels[safe_name] = safe_config
    return channels


def redact_channel_urls(settings_dict: dict | None) -> dict:
    """A copy of an institute settings dict with every channel URL masked.

    Institute profiles are readable by every signed-in role, but webhook URLs
    are effectively write tokens for the channel they point at.
    """
    if not isinstance(settings_dict, dict):
        return {}
    # Never echo the free-form nested object.  Legacy profiles may predate
    # write-time validation and could contain another URL/token field.  Build
    # an allowlisted projection from the same validated configs the notifier
    # consumes, then mask the sole secret-bearing field.
    masked: dict[str, dict[str, Any]] = {}
    for name, config in channel_configs(settings_dict).items():
        public = {"kind": config["kind"]}
        if "url" in config:
            public["url"] = REDACTED_URL
        # The chat id addresses a conversation; the bot token lives in the URL,
        # which is the field being masked.
        for field in (
            "channel",
            "chat_id",
            "smtp_host",
            "smtp_port",
            "smtp_security",
            "smtp_username",
            "from_address",
            "to_address",
        ):
            if field in config:
                public[field] = config[field]
        if "smtp_password" in config:
            public["smtp_password"] = REDACTED_URL
        masked[name] = public
    return {**settings_dict, "notification_channels": masked}


def _payload_for(channel: dict, title: str, text: str) -> dict:
    kind = channel.get("kind")
    if kind == "mattermost":
        payload: dict[str, Any] = {"text": f"**{title}**\n{text}" if text else f"**{title}**"}
        target = channel.get("channel")
        if isinstance(target, str) and target:
            payload["channel"] = target
        return payload
    if kind == "telegram":
        # Plain text: the title carries no markup a bot has to escape, and a
        # stray character must not make Telegram reject the whole message.
        return {
            "chat_id": channel.get("chat_id"),
            "text": f"{title}\n{text}" if text else title,
        }
    return {"title": title, "text": text}


def make_notifier(settings: Settings) -> Notifier:
    """Build the real webhook notifier. One POST, bounded by the configured
    timeout; every failure surfaces as `NotificationError` without the URL."""

    def notify(channel: dict, title: str, text: str) -> None:
        if channel.get("kind") == "email":
            safe = _safe_channel_config(channel)
            if safe is None:
                raise NotificationError("The email notification channel is incomplete.")
            try:
                message = EmailMessage()
                # Reminder titles are user input. Collapse line breaks before
                # placing one in an RFC header; EmailMessage rejects raw header
                # injection, but a bad title must become a sanitized delivery
                # failure instead of killing the scheduler.
                subject = " ".join(title.splitlines()).strip() or "itkFlow notification"
                message["Subject"] = subject
                message["From"] = safe["from_address"]
                message["To"] = safe["to_address"]
                message.set_content(text or title)
                if safe["smtp_security"] == "ssl":
                    smtp = smtplib.SMTP_SSL(
                        safe["smtp_host"],
                        safe["smtp_port"],
                        timeout=settings.notify_timeout_seconds,
                        context=ssl.create_default_context(),
                    )
                else:
                    smtp = smtplib.SMTP(
                        safe["smtp_host"],
                        safe["smtp_port"],
                        timeout=settings.notify_timeout_seconds,
                    )
                with smtp:
                    if safe["smtp_security"] == "starttls":
                        smtp.starttls(context=ssl.create_default_context())
                    if "smtp_username" in safe:
                        smtp.login(safe["smtp_username"], safe["smtp_password"])
                    smtp.send_message(message)
            except Exception:
                raise NotificationError("The email notification could not be delivered.") from None
            return

        url = channel.get("url")
        if not is_https_notification_url(url):
            raise NotificationError("The notification channel has no usable https URL.")
        body = json.dumps(_payload_for(channel, title, text)).encode("utf-8")
        request = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(  # noqa: S310 — https enforced above
                request, timeout=settings.notify_timeout_seconds
            ) as response:
                status = getattr(response, "status", 200)
        except urllib.error.HTTPError as exc:
            # Deliberately not chained and without the URL: webhook URLs are
            # secrets and HTTPError reprs include them.
            raise NotificationError(
                f"The notification endpoint answered HTTP {exc.code}."
            ) from None
        except Exception:
            raise NotificationError("The notification endpoint could not be reached.") from None
        if status >= 300:
            raise NotificationError(f"The notification endpoint answered HTTP {status}.")

    return notify
