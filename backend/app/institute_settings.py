# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-FileComment: itkflow-f259512a5048
"""Validation for the operational part of an institute profile.

``InstituteProfile.settings`` intentionally remains extensible JSON.  Only the
keys consumed by backend operations are normalised here; callers shallow-merge
the returned patch so unrelated institute configuration survives unchanged.

Notification webhook URLs and SMTP passwords are bearer credentials. API
responses replace them with ``***`` and this module is the only place where
that placeholder may enter an update: it is resolved back to the already
stored secret only for the same channel name and adapter kind, and is never
persisted as data itself.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any

from app.domain.stages import has_explicit_stage_policy
from app.notifications import REDACTED_URL, is_https_notification_url

_CHANNEL_KINDS = frozenset({"mattermost", "telegram", "webhook", "email"})
_CHANNEL_FIELDS = frozenset(
    {
        "kind",
        "url",
        "channel",
        "chat_id",
        "smtp_host",
        "smtp_port",
        "smtp_security",
        "smtp_username",
        "smtp_password",
        "from_address",
        "to_address",
    }
)
_CHANNEL_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_COMPONENT_TYPE_RE = re.compile(r"[A-Z][A-Z0-9_]{0,31}\Z")
_CHAT_ID_RE = re.compile(r"-?[0-9]{1,32}\Z|@[A-Za-z0-9_]{1,64}\Z")
_EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+\Z")
_TEST_TYPE_RE = re.compile(r"[A-Z][A-Z0-9_]{0,63}\Z")
# Production stage codes, e.g. HV_TAB_ATTACHED. Which stages exist is profile
# data (hard rule #4); only their *shape* is validated here.
_STAGE_NAME_RE = re.compile(r"[A-Z][A-Z0-9_]{0,63}\Z")
# Slot keys are the dict keys an assembly payload's ``tools`` map and the
# per-slot PDB property mapping key off — "snake/kebab tolerant" so either
# house style works, but not free text (they double as JSON object keys).
_ASSEMBLY_TOOL_SLOT_KEY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,31}\Z")
# Mirrors app.assembly._PROPERTY_KEY: a slot's own PDB property code, e.g.
# JIG_HYBRID_ALIGNMENT.
_ASSEMBLY_PROPERTY_KEY_RE = re.compile(r"[A-Z][A-Z0-9_]{0,63}\Z")
_ASSEMBLY_TOOL_SLOT_FIELDS = frozenset({"key", "label", "kinds", "multiple", "property_key"})
# A tool-bearing field of a test type: the PDB code plus the registry kinds
# it accepts. Nothing else — a label would only duplicate the definition's.
_TEST_TOOL_FIELD_FIELDS = frozenset({"code", "kinds", "step"})
# A PDB result code, e.g. GW_MODULE_H1PB. Which codes exist is schema data;
# only their shape is validated here.
_RESULT_CODE_RE = re.compile(r"[A-Z][A-Z0-9_]{0,63}\Z")
# A glue process name, e.g. TRUEBLUE. Institute vocabulary, never a fixed list.
_GLUE_PROCESS_RE = re.compile(r"[A-Z][A-Z0-9_]{0,31}\Z")
# Derivation step keys double as JSON object keys and as the join between
# `glue_weight_inputs` and each module type in `glue_targets`.
_GLUE_STEP_KEY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,31}\Z")
_GLUE_TARGET_FIELDS = frozenset({"process", "label", "valid_from", "module_types"})
_GLUE_INPUT_FIELDS = frozenset(
    {"label", "test_type", "measured", "subtract", "result_code", "by_type_code"}
)
_GLUE_INPUT_OVERRIDE_FIELDS = frozenset({"measured", "subtract", "result_code"})
_GLUE_STEP_TARGET_FIELDS = frozenset({"target_mg", "tolerance_mg"})
# Milligrams. A glue step is a smear of adhesive, not a payload: the ceiling
# only exists so a slipped decimal point cannot be stored as a target.
_MAX_GLUE_MG = 100_000.0

# The unattended sync schedule read by `app.auto_sync.read_auto_sync_schedule`.
# This is the only institute setting that makes itkFlow contact the ITk
# Production Database on its own, without anyone asking for it at that moment
# (the outbox worker also runs unattended, but it only executes a write a
# person already approved). Its reader fails closed — a malformed block reads
# as "off" and a too-small interval is lifted to the floor — which makes this
# validator the only thing that ever *tells* a person their input was wrong.
# Every message therefore names what was rejected and what is accepted.
_AUTO_SYNC_FIELDS = frozenset(
    {"enabled", "interval_minutes", "window_start", "window_end", "weekdays"}
)
# Wall-clock "HH:MM" on a 24-hour clock, zero-padded so the stored value is
# unambiguous.
_HHMM_RE = re.compile(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]\Z")
# Mirrors `app.auto_sync.MIN_INTERVAL_MINUTES` (a contract test keeps the two
# equal). Below this an unattended loop would hammer a shared production
# database. Rejected here instead of clamped: the reader lifts a smaller
# number to the floor, so without this rejection a person would be left
# believing a five-minute schedule they never got.
_MIN_AUTO_SYNC_INTERVAL_MINUTES = 15
# A week. Past that, "on a timer" stops meaning anything and the honest way to
# say it is `enabled: false`.
_MAX_AUTO_SYNC_INTERVAL_MINUTES = 7 * 24 * 60


class InstituteSettingsValidationError(ValueError):
    """An operational institute setting has an invalid public shape."""


def _clean_string(value: Any, *, label: str, max_length: int) -> str:
    if not isinstance(value, str):
        raise InstituteSettingsValidationError(f"{label} must be a string.")
    cleaned = value.strip()
    if not cleaned:
        raise InstituteSettingsValidationError(f"{label} must not be blank.")
    if len(cleaned) > max_length:
        raise InstituteSettingsValidationError(f"{label} is too long.")
    if any(ord(character) < 32 for character in cleaned):
        raise InstituteSettingsValidationError(f"{label} contains invalid characters.")
    return cleaned


def _https_url(value: Any) -> str:
    if not isinstance(value, str):
        raise InstituteSettingsValidationError(
            "Every notification channel requires an HTTPS URL."
        )
    cleaned = value.strip()
    if any(character.isspace() for character in cleaned) or "\\" in cleaned:
        raise InstituteSettingsValidationError(
            "Every notification channel requires an HTTPS URL."
        )
    if not is_https_notification_url(cleaned):
        raise InstituteSettingsValidationError(
            "Every notification channel requires an HTTPS URL."
        )
    # Canonicalise only the scheme; the path/query can contain the webhook's
    # opaque credential and must otherwise remain byte-for-byte intact.
    return f"https:{cleaned.split(':', 1)[1]}"


def _existing_channel_secret(
    existing: Any,
    name: str,
    field: str,
    *,
    kind: str,
    matching: dict[str, Any] | None = None,
) -> str | None:
    if not isinstance(existing, dict):
        return None
    config = existing.get(name)
    if not isinstance(config, dict):
        return None
    existing_kind = config.get("kind")
    if not isinstance(existing_kind, str) or existing_kind.strip().lower() != kind:
        return None
    if matching is not None and any(config.get(key) != value for key, value in matching.items()):
        return None
    secret = config.get(field)
    if not isinstance(secret, str) or not secret or secret.strip() == REDACTED_URL:
        return None
    if field == "url":
        try:
            return _https_url(secret)
        except InstituteSettingsValidationError:
            return None
    return secret


def _email_address(value: Any, label: str) -> str:
    address = _clean_string(value, label=label, max_length=254)
    if _EMAIL_RE.fullmatch(address) is None:
        raise InstituteSettingsValidationError(f"{label} must be a valid email address.")
    return address


def _smtp_host(value: Any) -> str:
    host = _clean_string(value, label="SMTP host", max_length=253)
    if any(character in host for character in "/\\@") or any(
        character.isspace() for character in host
    ):
        raise InstituteSettingsValidationError("SMTP host is invalid.")
    return host


def _secret(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InstituteSettingsValidationError(f"{label} must not be blank.")
    if len(value) > 512:
        raise InstituteSettingsValidationError(f"{label} is too long.")
    return value


def _notification_channels(value: Any, existing: Any) -> dict[str, dict[str, str]]:
    if not isinstance(value, dict):
        raise InstituteSettingsValidationError("notification_channels must be an object.")

    normalised: dict[str, dict[str, str]] = {}
    for raw_name, raw_config in value.items():
        name = _clean_string(raw_name, label="Notification channel name", max_length=64)
        if _CHANNEL_NAME_RE.fullmatch(name) is None:
            raise InstituteSettingsValidationError(
                "Notification channel names may contain letters, digits, dots, "
                "dashes, and underscores."
            )
        if name in normalised:
            raise InstituteSettingsValidationError("Notification channel names must be unique.")
        if not isinstance(raw_config, dict):
            raise InstituteSettingsValidationError(
                "Every notification channel must be an object."
            )
        if set(raw_config) - _CHANNEL_FIELDS:
            raise InstituteSettingsValidationError(
                "Notification channel contains unsupported fields."
            )

        kind = _clean_string(
            raw_config.get("kind"), label="Notification channel kind", max_length=24
        ).lower()
        if kind not in _CHANNEL_KINDS:
            raise InstituteSettingsValidationError(
                "Notification channel kind must be mattermost, telegram, webhook, or email."
            )

        if kind == "email":
            allowed = {
                "kind",
                "smtp_host",
                "smtp_port",
                "smtp_security",
                "smtp_username",
                "smtp_password",
                "from_address",
                "to_address",
            }
            if set(raw_config) - allowed:
                raise InstituteSettingsValidationError(
                    "Email channels contain unsupported fields."
                )
            port = raw_config.get("smtp_port")
            if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
                raise InstituteSettingsValidationError(
                    "SMTP port must be an integer between 1 and 65535."
                )
            security = _clean_string(
                raw_config.get("smtp_security"),
                label="SMTP security",
                max_length=16,
            ).lower()
            if security not in {"ssl", "starttls"}:
                raise InstituteSettingsValidationError(
                    "SMTP security must be ssl or starttls."
                )
            username_raw = raw_config.get("smtp_username")
            password_raw = raw_config.get("smtp_password")
            host = _smtp_host(raw_config.get("smtp_host"))
            username = (
                _clean_string(username_raw, label="SMTP username", max_length=254)
                if username_raw is not None
                else None
            )
            if isinstance(password_raw, str) and password_raw.strip() == REDACTED_URL:
                password = _existing_channel_secret(
                    existing,
                    name,
                    "smtp_password",
                    kind=kind,
                    matching={
                        "smtp_host": host,
                        "smtp_port": port,
                        "smtp_security": security,
                        "smtp_username": username,
                    },
                )
                if password is None:
                    raise InstituteSettingsValidationError(
                        "A new or changed authenticated email channel requires an SMTP password."
                    )
            elif password_raw is None:
                password = None
            else:
                password = _secret(password_raw, "SMTP password")
            if (username is None) != (password is None):
                raise InstituteSettingsValidationError(
                    "SMTP username and password must be configured together."
                )
            config: dict[str, Any] = {
                "kind": kind,
                "smtp_host": host,
                "smtp_port": port,
                "smtp_security": security,
                "from_address": _email_address(
                    raw_config.get("from_address"), "From address"
                ),
                "to_address": _email_address(raw_config.get("to_address"), "To address"),
            }
            if username is not None and password is not None:
                config["smtp_username"] = username
                config["smtp_password"] = password
            normalised[name] = config
            continue

        allowed = (
            {"kind", "url", "channel"}
            if kind == "mattermost"
            else {"kind", "url", "chat_id"}
            if kind == "telegram"
            else {"kind", "url"}
        )
        if set(raw_config) - allowed:
            raise InstituteSettingsValidationError(
                f"{kind.capitalize()} channels contain unsupported fields."
            )

        raw_url = raw_config.get("url")
        if isinstance(raw_url, str) and raw_url.strip() == REDACTED_URL:
            url = _existing_channel_secret(existing, name, "url", kind=kind)
            if url is None:
                raise InstituteSettingsValidationError(
                    "A new notification channel requires an HTTPS URL."
                )
        else:
            url = _https_url(raw_url)

        config = {"kind": kind, "url": url}
        if kind == "telegram":
            if set(raw_config) - {"kind", "url", "chat_id"}:
                raise InstituteSettingsValidationError(
                    "Telegram channels only support kind, url, and chat_id."
                )
            chat_id = _clean_string(
                raw_config.get("chat_id"), label="Telegram chat ID", max_length=65
            )
            if _CHAT_ID_RE.fullmatch(chat_id) is None:
                raise InstituteSettingsValidationError("Telegram chat ID is invalid.")
            config["chat_id"] = chat_id
        raw_target = raw_config.get("channel")
        if raw_target is not None:
            if not isinstance(raw_target, str):
                raise InstituteSettingsValidationError(
                    "Notification channel override must be a string."
                )
            target = raw_target.strip()
            if target:
                config["channel"] = _clean_string(
                    target,
                    label="Notification channel override",
                    max_length=120,
                )
        normalised[name] = config
    return normalised


def _clean_string_list(
    value: Any,
    *,
    setting_name: str,
    item_label: str,
    max_length: int,
    uppercase: bool = False,
) -> list[str]:
    if not isinstance(value, list):
        raise InstituteSettingsValidationError(f"{setting_name} must be a list.")
    normalised: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise InstituteSettingsValidationError(f"Every {item_label} must be a string.")
        cleaned = item.strip()
        if not cleaned:
            continue
        if uppercase:
            cleaned = cleaned.upper()
        cleaned = _clean_string(cleaned, label=item_label.capitalize(), max_length=max_length)
        if uppercase and _COMPONENT_TYPE_RE.fullmatch(cleaned) is None:
            raise InstituteSettingsValidationError(
                "Component type codes may contain uppercase letters, digits, and underscores."
            )
        if cleaned not in normalised:
            normalised.append(cleaned)
    return normalised


def _glue_pot_life_minutes(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        raise InstituteSettingsValidationError("glue_pot_life_minutes must be an object.")
    normalised: dict[str, int] = {}
    for raw_glue_type, minutes in value.items():
        glue_type = _clean_string(raw_glue_type, label="Glue type", max_length=48)
        if glue_type in normalised:
            raise InstituteSettingsValidationError("Glue type names must be unique.")
        if (
            isinstance(minutes, bool)
            or not isinstance(minutes, int)
            or not 1 <= minutes <= 24 * 60
        ):
            raise InstituteSettingsValidationError(
                "Glue pot-life values must be integers between 1 and 1440 minutes."
            )
        normalised[glue_type] = minutes
    return normalised


def _reminder_escalation(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {"after_minutes", "channel"}:
        raise InstituteSettingsValidationError(
            "reminder_escalation must contain after_minutes and channel."
        )
    after_minutes = value.get("after_minutes")
    if (
        isinstance(after_minutes, bool)
        or not isinstance(after_minutes, int)
        or not 1 <= after_minutes <= 7 * 24 * 60
    ):
        raise InstituteSettingsValidationError(
            "Reminder escalation must be between 1 and 10080 minutes."
        )
    channel = _clean_string(
        value.get("channel"),
        label="Reminder escalation channel",
        max_length=64,
    )
    if _CHANNEL_NAME_RE.fullmatch(channel) is None:
        raise InstituteSettingsValidationError("Reminder escalation channel is invalid.")
    return {"after_minutes": after_minutes, "channel": channel}


def _shipment_reception_tests(value: Any) -> dict[str, list[str]]:
    """Normalize component-type to required reception-test mapping."""

    if not isinstance(value, dict):
        raise InstituteSettingsValidationError(
            "shipment_reception_tests must be an object."
        )
    normalised: dict[str, list[str]] = {}
    for raw_component_type, raw_test_types in value.items():
        component_type = _clean_string(
            raw_component_type,
            label="Reception component type",
            max_length=32,
        ).upper()
        if _COMPONENT_TYPE_RE.fullmatch(component_type) is None:
            raise InstituteSettingsValidationError(
                "Reception component types may contain uppercase letters, digits, "
                "and underscores."
            )
        if component_type in normalised:
            raise InstituteSettingsValidationError(
                "Reception component types must be unique."
            )
        if not isinstance(raw_test_types, list):
            raise InstituteSettingsValidationError(
                "Every reception component type must map to a list of test types."
            )
        test_types: list[str] = []
        for raw_test_type in raw_test_types:
            test_type = _clean_string(
                raw_test_type,
                label="Reception test type",
                max_length=64,
            ).upper()
            if _TEST_TYPE_RE.fullmatch(test_type) is None:
                raise InstituteSettingsValidationError(
                    "Reception test types may contain uppercase letters, digits, "
                    "and underscores."
                )
            if test_type not in test_types:
                test_types.append(test_type)
        if test_types:
            normalised[component_type] = test_types
    return normalised


def _stage_name(value: Any) -> str:
    stage = _clean_string(value, label="Stage name", max_length=64).upper()
    if _STAGE_NAME_RE.fullmatch(stage) is None:
        raise InstituteSettingsValidationError(
            "Stage names may contain uppercase letters, digits, and underscores."
        )
    return stage


def _stage_order(value: Any) -> list[str] | None:
    """Normalize the institute's ordered production stages.

    ``None`` clears the override, which is the only way to fall back to the
    seed default order in ``app.domain.stages.stage_model_from_settings``: it
    keeps the default whenever the value is not a list of stage names. An
    empty list is therefore rejected — it *is* a valid list and would leave
    the model with no stages at all, so every stage move would silently stop
    being suggested.
    """

    if value is None:
        return None
    if not isinstance(value, list):
        raise InstituteSettingsValidationError("stage_order must be a list.")
    normalised: list[str] = []
    for item in value:
        stage = _stage_name(item)
        if stage in normalised:
            raise InstituteSettingsValidationError("Stage names must be unique.")
        normalised.append(stage)
    if not normalised:
        raise InstituteSettingsValidationError(
            "stage_order must contain at least one stage; use null to restore the default."
        )
    return normalised


def _stage_requirements(value: Any) -> dict[str, list[str]] | None:
    """Normalize the required test types per production stage.

    ``None`` clears the override. An empty list for one stage is meaningful
    and preserved: it replaces that stage's default requirements with "none".
    """

    if value is None:
        return None
    if not isinstance(value, dict):
        raise InstituteSettingsValidationError("stage_requirements must be an object.")
    normalised: dict[str, list[str]] = {}
    for raw_stage, raw_tests in value.items():
        stage = _stage_name(raw_stage)
        if stage in normalised:
            raise InstituteSettingsValidationError("Stage names must be unique.")
        if not isinstance(raw_tests, list):
            raise InstituteSettingsValidationError(
                "Every stage must map to a list of required test types."
            )
        tests: list[str] = []
        for raw_test_type in raw_tests:
            test_type = _clean_string(
                raw_test_type, label="Required test type", max_length=64
            ).upper()
            if _TEST_TYPE_RE.fullmatch(test_type) is None:
                raise InstituteSettingsValidationError(
                    "Required test types may contain uppercase letters, digits, "
                    "and underscores."
                )
            if test_type in tests:
                raise InstituteSettingsValidationError(
                    "Required test types must be unique per stage."
                )
            tests.append(test_type)
        normalised[stage] = tests
    return normalised



def _result_code(value: Any, label: str) -> str:
    code = _clean_string(value, label=label, max_length=64).upper()
    if _RESULT_CODE_RE.fullmatch(code) is None:
        raise InstituteSettingsValidationError(
            f"{label} must look like a PDB result code."
        )
    return code


def _glue_process(value: Any, label: str) -> str:
    process = _clean_string(value, label=label, max_length=32).upper()
    if _GLUE_PROCESS_RE.fullmatch(process) is None:
        raise InstituteSettingsValidationError(
            f"{label} may contain uppercase letters, digits, and underscores."
        )
    return process


def _glue_step_key(value: Any) -> str:
    key = _clean_string(value, label="Glue step key", max_length=32)
    if _GLUE_STEP_KEY_RE.fullmatch(key) is None:
        raise InstituteSettingsValidationError(
            "Glue step keys may contain letters, digits, underscores, and hyphens."
        )
    return key


def _glue_milligrams(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InstituteSettingsValidationError(f"{label} must be a number.")
    amount = float(value)
    if not math.isfinite(amount):
        raise InstituteSettingsValidationError(f"{label} must be a finite number.")
    if amount < 0:
        raise InstituteSettingsValidationError(f"{label} must not be negative.")
    if amount > _MAX_GLUE_MG:
        raise InstituteSettingsValidationError(f"{label} is implausibly large.")
    return amount


def _glue_valid_from(value: Any) -> str | None:
    """Normalize a rule's validity start to a canonical UTC timestamp.

    ``null`` means "always valid" and is the fallback a process falls back to
    when no dated rule covers the measurement. A plain date is read as midnight
    UTC so that two generations of the same rule can be compared at all.
    """

    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise InstituteSettingsValidationError(
            "Glue target valid_from must be an ISO 8601 date or null."
        )
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        raise InstituteSettingsValidationError(
            "Glue target valid_from must be an ISO 8601 date or null."
        ) from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.isoformat()


def _glue_module_types(value: Any) -> dict[str, dict[str, dict[str, float]]]:
    if not isinstance(value, dict):
        raise InstituteSettingsValidationError(
            "Glue target module_types must be an object."
        )
    normalised: dict[str, dict[str, dict[str, float]]] = {}
    for raw_type_code, raw_steps in value.items():
        type_code = _clean_string(
            raw_type_code, label="Glue target module type", max_length=32
        ).upper()
        if _COMPONENT_TYPE_RE.fullmatch(type_code) is None:
            raise InstituteSettingsValidationError(
                "Glue target module types may contain uppercase letters, digits, "
                "and underscores."
            )
        if type_code in normalised:
            raise InstituteSettingsValidationError(
                "Glue target module types must be unique."
            )
        if not isinstance(raw_steps, dict):
            raise InstituteSettingsValidationError(
                "Every glue target module type must map to an object of steps."
            )
        steps: dict[str, dict[str, float]] = {}
        for raw_step_key, raw_target in raw_steps.items():
            step_key = _glue_step_key(raw_step_key)
            if step_key in steps:
                raise InstituteSettingsValidationError(
                    "Glue step keys must be unique per module type."
                )
            if not isinstance(raw_target, dict):
                raise InstituteSettingsValidationError(
                    "Every glue target must be an object with target_mg and tolerance_mg."
                )
            if set(raw_target) - _GLUE_STEP_TARGET_FIELDS:
                raise InstituteSettingsValidationError(
                    "Glue targets only support target_mg and tolerance_mg."
                )
            steps[step_key] = {
                "target_mg": _glue_milligrams(
                    raw_target.get("target_mg"), "Glue target weight"
                ),
                "tolerance_mg": _glue_milligrams(
                    raw_target.get("tolerance_mg"), "Glue tolerance"
                ),
            }
        # An empty step map is meaningful and preserved: it states that this
        # module type is glued in no derived step at all (a half-module carries
        # no powerboard), which is a different fact from "not configured yet".
        normalised[type_code] = steps
    return normalised


def _glue_targets(value: Any) -> list[dict[str, Any]] | None:
    """Normalize the institute's glue targets per process, module type and step.

    ``None`` disables target-based derivation. An empty list is rejected so an
    accidental form submission cannot silently disable a configured profile.

    Several entries may name the same process as long as their ``valid_from``
    differs. That is not decoration — the sheet this replaces runs two
    generations of the same rule side by side, and a profile that knows only
    one set of constants judges historical runs by today's numbers.
    """

    if value is None:
        return None
    if not isinstance(value, list):
        raise InstituteSettingsValidationError("glue_targets must be a list.")
    normalised: list[dict[str, Any]] = []
    seen: set[tuple[str, str | None]] = set()
    for entry in value:
        if not isinstance(entry, dict):
            raise InstituteSettingsValidationError("Every glue target set must be an object.")
        if set(entry) - _GLUE_TARGET_FIELDS:
            raise InstituteSettingsValidationError(
                "Glue target set contains unsupported fields."
            )
        process = _glue_process(entry.get("process"), "Glue process")
        valid_from = _glue_valid_from(entry.get("valid_from"))
        if (process, valid_from) in seen:
            raise InstituteSettingsValidationError(
                "Glue target sets must be unique per process and valid_from."
            )
        seen.add((process, valid_from))
        raw_label = entry.get("label")
        label = (
            _clean_string(raw_label, label="Glue process label", max_length=120)
            if raw_label is not None
            else process
        )
        normalised.append(
            {
                "process": process,
                "label": label,
                "valid_from": valid_from,
                "module_types": _glue_module_types(entry.get("module_types", {})),
            }
        )
    if not normalised:
        raise InstituteSettingsValidationError(
            "glue_targets must contain at least one rule set; use null to disable it."
        )
    return normalised


def _glue_formula(
    value: dict[str, Any],
    *,
    defaults: dict[str, Any] | None = None,
    label: str,
) -> dict[str, Any]:
    """Normalize one effective measured-minus-subtract formula."""
    fallback = defaults or {}
    measured = _result_code(
        value.get("measured", fallback.get("measured")),
        f"{label} measured code",
    )
    raw_subtract = value.get("subtract", fallback.get("subtract", []))
    if not isinstance(raw_subtract, list):
        raise InstituteSettingsValidationError(
            f"{label} subtract must be a list of result codes."
        )
    subtract: list[str] = []
    for raw_code in raw_subtract:
        code = _result_code(raw_code, f"{label} subtracted code")
        if code == measured:
            raise InstituteSettingsValidationError(
                f"{label} must not subtract the code it measures."
            )
        if code in subtract:
            raise InstituteSettingsValidationError(
                f"{label} subtracted codes must be unique."
            )
        subtract.append(code)

    raw_result_code = value.get("result_code", fallback.get("result_code"))
    result_code = (
        _result_code(raw_result_code, f"{label} result code")
        if raw_result_code is not None
        else None
    )
    if result_code == measured or result_code in subtract:
        raise InstituteSettingsValidationError(
            f"{label} must not store its result in one of its input codes."
        )
    formula: dict[str, Any] = {"measured": measured, "subtract": subtract}
    if result_code is not None or defaults is not None:
        formula["result_code"] = result_code
    return formula


def _glue_weight_inputs(value: Any) -> dict[str, dict[str, Any]] | None:
    """Normalize which PDB result codes feed which derived glue weight.

    The formula is data: ``measured`` minus every code in ``subtract``, stored
    under ``result_code``. Which codes those are is schema and institute
    business — an institute gluing two hybrids in one step weighs a different
    chain than one gluing a single hybrid — so none of them may be a literal in
    the derivation. ``None`` disables input-based derivation.
    """

    if value is None:
        return None
    if not isinstance(value, dict):
        raise InstituteSettingsValidationError("glue_weight_inputs must be an object.")
    normalised: dict[str, dict[str, Any]] = {}
    for raw_key, raw_step in value.items():
        key = _glue_step_key(raw_key)
        if key in normalised:
            raise InstituteSettingsValidationError("Glue step keys must be unique.")
        if not isinstance(raw_step, dict):
            raise InstituteSettingsValidationError("Every glue step must be an object.")
        if set(raw_step) - _GLUE_INPUT_FIELDS:
            raise InstituteSettingsValidationError("Glue step contains unsupported fields.")
        step = _glue_formula(raw_step, label="Glue step")
        raw_label = raw_step.get("label")
        if raw_label is not None:
            step["label"] = _clean_string(raw_label, label="Glue step label", max_length=60)
        raw_test_type = raw_step.get("test_type")
        if raw_test_type is not None:
            test_type = _clean_string(
                raw_test_type, label="Glue step test type", max_length=64
            ).upper()
            if _TEST_TYPE_RE.fullmatch(test_type) is None:
                raise InstituteSettingsValidationError(
                    "Glue step test types may contain uppercase letters, digits, "
                    "and underscores."
                )
            step["test_type"] = test_type
        if "by_type_code" in raw_step:
            raw_overrides = raw_step["by_type_code"]
            if not isinstance(raw_overrides, dict):
                raise InstituteSettingsValidationError(
                    "Glue step by_type_code must be an object."
                )
            overrides: dict[str, dict[str, Any]] = {}
            for raw_type_code, raw_override in raw_overrides.items():
                type_code = _clean_string(
                    raw_type_code,
                    label="Glue input override module type",
                    max_length=32,
                ).upper()
                if _COMPONENT_TYPE_RE.fullmatch(type_code) is None:
                    raise InstituteSettingsValidationError(
                        "Glue input override module types may contain uppercase "
                        "letters, digits, and underscores."
                    )
                if type_code in overrides:
                    raise InstituteSettingsValidationError(
                        "Glue input override module types must be unique."
                    )
                if not isinstance(raw_override, dict):
                    raise InstituteSettingsValidationError(
                        "Every glue input override must be an object."
                    )
                if set(raw_override) - _GLUE_INPUT_OVERRIDE_FIELDS:
                    raise InstituteSettingsValidationError(
                        "Glue input overrides only support measured, subtract, "
                        "and result_code."
                    )
                overrides[type_code] = _glue_formula(
                    raw_override,
                    defaults=step,
                    label="Glue input override",
                )
            step["by_type_code"] = overrides
        normalised[key] = step
    if not normalised:
        raise InstituteSettingsValidationError(
            "glue_weight_inputs must contain at least one step; "
            "use null to disable it."
        )
    _validate_unique_glue_result_codes(normalised)
    return normalised


def _validate_unique_glue_result_codes(steps: dict[str, dict[str, Any]]) -> None:
    """Reject ambiguous outputs and every cross-step output/input collision.

    The upload map is keyed by result code, so a duplicate would otherwise be
    silent last-write-wins. Check the base formulas and every exact type-code
    context mentioned by an override; steps belonging to different test types
    are separate runs and may legitimately reuse a code.
    """
    type_codes: set[str | None] = {None}
    for step in steps.values():
        type_codes.update(step.get("by_type_code", {}))

    for type_code in type_codes:
        outputs_by_test: dict[str, set[str]] = {}
        inputs_by_test: dict[str, set[str]] = {}
        for step in steps.values():
            formula = step
            if type_code is not None:
                formula = step.get("by_type_code", {}).get(type_code, step)
            test_type = step.get("test_type", "GLUE_WEIGHT")
            inputs_by_test.setdefault(test_type, set()).update(
                [formula["measured"], *formula.get("subtract", [])]
            )
            result_code = formula.get("result_code")
            if result_code is None:
                continue
            outputs = outputs_by_test.setdefault(test_type, set())
            if result_code in outputs:
                context = "base formulas" if type_code is None else f"module type {type_code}"
                raise InstituteSettingsValidationError(
                    f"Glue result codes must be unique per test type in {context}."
                )
            outputs.add(result_code)
        if any(
            outputs & inputs_by_test.get(test_type, set())
            for test_type, outputs in outputs_by_test.items()
        ):
            context = "base formulas" if type_code is None else f"module type {type_code}"
            raise InstituteSettingsValidationError(
                "Glue result codes must not also be raw inputs in the same "
                f"test type and {context}."
            )


def _glue_default_process(value: Any) -> str | None:
    """The explicit process used when a run does not name one."""

    if value is None:
        return None
    return _glue_process(value, "glue_default_process")


def _glue_process_property(value: Any) -> str | None:
    """The PDB code under which a run names its glue process. ``None`` clears it."""

    if value is None:
        return None
    return _result_code(value, "glue_process_property")


def _validate_glue_process_contract(
    existing: dict[str, Any],
    normalised: dict[str, Any],
    settings_patch: dict[str, Any],
) -> None:
    """Require an explicit default to name an effective target process.

    Settings updates are shallow patches, so changing either side of this
    relationship must be checked against the other side after applying the
    patch. Unrelated updates deliberately leave old profiles alone.
    """

    contract_keys = {
        "glue_targets",
        "glue_default_process",
        "glue_process_default",
    }
    if contract_keys.isdisjoint(settings_patch):
        return

    if "glue_default_process" in normalised:
        default_process = normalised["glue_default_process"]
    elif "glue_default_process" in existing:
        default_process = _glue_default_process(existing["glue_default_process"])
    else:
        default_process = _glue_default_process(existing.get("glue_process_default"))
    if default_process is None:
        return

    raw_targets = normalised.get("glue_targets", existing.get("glue_targets"))
    targets = _glue_targets(raw_targets)
    processes = {
        target["process"]
        for target in targets or []
        if isinstance(target, dict) and isinstance(target.get("process"), str)
    }
    if default_process not in processes:
        raise InstituteSettingsValidationError(
            "glue_default_process must match a process configured in glue_targets."
        )


def _reconcile_stage_model(normalised: dict[str, Any]) -> None:
    """Keep a stage that only exists in ``stage_requirements`` visible.

    ``stage_model_from_settings`` appends every requirement stage that is
    missing from the order, so such an entry is still evaluated — it just
    happens at the end of the flow. Mirroring that here means the stored
    profile states what the engine does instead of hiding it in the merge.
    Only a patch that carries both keys can be reconciled; otherwise the
    engine's own append remains the single source of truth.
    """

    order = normalised.get("stage_order")
    requirements = normalised.get("stage_requirements")
    if not isinstance(order, list) or not isinstance(requirements, dict):
        return
    for stage in requirements:
        if stage not in order:
            order.append(stage)


def _assembly_tool_slots(value: Any) -> list[dict[str, Any]]:
    """Normalize the combined-tool assembly slots an institute exposes.

    A single assembly step can use several tools in combination — the
    production sheets this replaces track e.g. "Hybrid glue jigs used, top,
    bottom" and "Hybrid pickups used, top, bottom" next to a single "Module
    jig used" column. Each entry here names one such scannable role; the
    assembly payload's ``tools`` map and the PDB property mapping both key off
    ``key``, never off ``label``. ``property_key`` is only meaningful for
    slots other than the implicit default ("tool") slot, which keeps using
    the existing ``assembly_property_keys["tool"]`` mapping.
    """

    if not isinstance(value, list):
        raise InstituteSettingsValidationError("assembly_tool_slots must be a list.")
    normalised: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    seen_property_keys: set[str] = set()
    for raw_slot in value:
        if not isinstance(raw_slot, dict):
            raise InstituteSettingsValidationError("Every assembly tool slot must be an object.")
        if set(raw_slot) - _ASSEMBLY_TOOL_SLOT_FIELDS:
            raise InstituteSettingsValidationError(
                "Assembly tool slot contains unsupported fields."
            )
        key = _clean_string(raw_slot.get("key"), label="Assembly tool slot key", max_length=32)
        if _ASSEMBLY_TOOL_SLOT_KEY_RE.fullmatch(key) is None:
            raise InstituteSettingsValidationError(
                "Assembly tool slot keys may contain letters, digits, underscores, and hyphens."
            )
        if key in seen_keys:
            raise InstituteSettingsValidationError("Assembly tool slot keys must be unique.")
        seen_keys.add(key)
        label = _clean_string(
            raw_slot.get("label"), label="Assembly tool slot label", max_length=60
        )
        slot: dict[str, Any] = {"key": key, "label": label}
        if "kinds" in raw_slot:
            slot["kinds"] = _clean_string_list(
                raw_slot["kinds"],
                setting_name="Assembly tool slot kinds",
                item_label="tool kind",
                max_length=24,
            )
        if "multiple" in raw_slot:
            multiple = raw_slot["multiple"]
            if not isinstance(multiple, bool):
                raise InstituteSettingsValidationError(
                    "Assembly tool slot 'multiple' must be true or false."
                )
            slot["multiple"] = multiple
        if raw_slot.get("property_key") is not None:
            property_key = _clean_string(
                raw_slot["property_key"],
                label="Assembly tool slot property key",
                max_length=64,
            ).upper()
            if _ASSEMBLY_PROPERTY_KEY_RE.fullmatch(property_key) is None:
                raise InstituteSettingsValidationError(
                    "Assembly tool slot property keys must look like PDB property codes."
                )
            if property_key in seen_property_keys:
                # Two slots writing the same PDB property would silently
                # last-writer-win into the staged payload.
                raise InstituteSettingsValidationError(
                    "Assembly tool slot property_key values must be unique."
                )
            seen_property_keys.add(property_key)
            slot["property_key"] = property_key
        normalised.append(slot)
    return normalised


def _test_tool_fields(value: Any) -> dict[str, list[dict[str, Any]]] | None:
    """Normalize which test-type fields hold a registry tool, not a typed value.

    Shape: ``{"<TEST_TYPE>": [{"code": "<FIELD_CODE>", "kinds": ["jig"]}]}``.

    A PDB test definition cannot say "this field is a jig" — it says
    ``dataType: string`` — so the generated form renders free text wherever an
    institute records tooling in a test rather than on the assembly. The
    mirrored evidence shows the cost: one institute's 28 ``MODULE_BOW`` runs
    carry the same jig under three spellings, its 17 wire-bonding runs one
    machine under four. Naming the field here turns it into a picker over the
    tool registry, which is what the production sheet's data-validation
    dropdown always did.

    Which fields those are is institute business (harte Regel 4): no test
    type, field code or tool kind may be a literal in application code.
    ``kinds`` is optional and filters the registry by ``Tool.kind``; omitting
    it offers every active, compatible tool. ``None`` clears the mapping.
    """

    if value is None:
        return None
    if not isinstance(value, dict):
        raise InstituteSettingsValidationError("test_tool_fields must be an object.")
    normalised: dict[str, list[dict[str, Any]]] = {}
    for raw_test_type, raw_fields in value.items():
        test_type = _clean_string(
            raw_test_type, label="Tool field test type", max_length=64
        ).upper()
        if _TEST_TYPE_RE.fullmatch(test_type) is None:
            raise InstituteSettingsValidationError(
                "Tool field test types may contain uppercase letters, digits, "
                "and underscores."
            )
        if test_type in normalised:
            raise InstituteSettingsValidationError(
                "Tool field test types must be unique."
            )
        if not isinstance(raw_fields, list):
            raise InstituteSettingsValidationError(
                "Every tool field test type must map to a list of field objects."
            )
        if not raw_fields:
            # Silently dropping it would leave an admin staring at a key that
            # vanished on save; say what the accepted value is instead.
            raise InstituteSettingsValidationError(
                "A tool field test type must list at least one field; "
                "remove the test type instead of mapping it to an empty list."
            )
        fields: list[dict[str, Any]] = []
        seen_codes: set[str] = set()
        for raw_field in raw_fields:
            if not isinstance(raw_field, dict):
                raise InstituteSettingsValidationError(
                    "Every tool field must be an object."
                )
            if set(raw_field) - _TEST_TOOL_FIELD_FIELDS:
                raise InstituteSettingsValidationError(
                    "Tool fields only support code and kinds."
                )
            code = _result_code(raw_field.get("code"), "Tool field code")
            if code in seen_codes:
                raise InstituteSettingsValidationError(
                    "Tool field codes must be unique per test type."
                )
            seen_codes.add(code)
            field: dict[str, Any] = {"code": code}
            if "kinds" in raw_field:
                kinds = _clean_string_list(
                    raw_field["kinds"],
                    setting_name="Tool field kinds",
                    item_label="tool kind",
                    max_length=24,
                )
                # Tool.kind is canonical lower-case registry data. Store the
                # profile filter the same way so a harmless `JIG` spelling
                # cannot produce an apparently valid but empty picker.
                field["kinds"] = list(dict.fromkeys(kind.lower() for kind in kinds))
            if raw_field.get("step") is not None:
                # The band this field is shown under, named by a
                # `glue_weight_inputs` step key — the production sheet keeps
                # its tooling rows inside the gluing band they belong to, and
                # no derivation formula names a jig, so the band cannot be
                # recovered from the formula. Only the *shape* is checked
                # here: a patch may legitimately set this before (or without)
                # the steps it points at, and an unknown key degrades to the
                # unnamed remainder rather than blocking the save.
                field["step"] = _glue_step_key(raw_field["step"])
            fields.append(field)
        normalised[test_type] = fields
    return normalised


def _auto_sync_time_of_day(value: Any, label: str) -> str:
    if not isinstance(value, str) or _HHMM_RE.fullmatch(value.strip()) is None:
        raise InstituteSettingsValidationError(
            f"{label} must be a time of day as HH:MM on a 24-hour clock, e.g. 07:00."
        )
    return value.strip()


def _auto_sync_weekdays(value: Any) -> list[int] | None:
    """Normalize the ISO weekdays an unattended sweep may run on.

    ``None`` (or an absent key) means every day, which is exactly what
    ``read_auto_sync_schedule`` does with an empty weekday tuple. An empty
    list is rejected instead of being read that way: somebody who unticks
    every day means "never", and storing that as "every day" would create
    unattended PDB traffic in the one case where it was being prevented.
    """

    if value is None:
        return None
    if not isinstance(value, list):
        raise InstituteSettingsValidationError(
            "auto_sync weekdays must be a list of ISO weekday numbers, "
            "1 = Monday to 7 = Sunday."
        )
    weekdays: list[int] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int) or not 1 <= item <= 7:
            raise InstituteSettingsValidationError(
                "auto_sync weekdays must be whole numbers from 1 (Monday) to 7 (Sunday)."
            )
        if item in weekdays:
            raise InstituteSettingsValidationError(
                "auto_sync weekdays must not repeat a day; name each of 1 (Monday) "
                "to 7 (Sunday) at most once."
            )
        weekdays.append(item)
    if not weekdays:
        raise InstituteSettingsValidationError(
            "auto_sync weekdays must name at least one day; use null to run every day."
        )
    return sorted(weekdays)


def _auto_sync(value: Any) -> dict[str, Any] | None:
    """Normalize the unattended sync schedule (``app.auto_sync``).

    ``None`` clears the key back to the default, which is *off*: an institute
    nobody configured never syncs on a timer, and neither does one whose block
    says ``enabled: false``. The rest of the block is validated either way, so
    a schedule can be prepared, switched off, and switched back on without
    losing its window.

    Two clocks, deliberately. ``window_start``/``window_end`` and ``weekdays``
    are wall-clock in the **server's own local time** (docs/09): Windows ships
    no IANA zone database, and for both real deployment shapes — the desktop
    bundle on an operator's machine and one VM per institute — the server's
    clock already is the institute's clock. ``interval_minutes`` is measured
    against the last successful sync's ``finished_at``, which is stored in
    UTC; the two must not be described as one clock, or the difference is a
    silent two hours every Berlin summer.

    A window may cross midnight, so ``22:00``-``06:00`` is an overnight window
    rather than an empty set; the pair is deliberately **not** checked for
    ``start <= end``. Only an identical pair is rejected, because the reader
    treats it as no window at all and a stored ``07:00``-``07:00`` would
    promise a daytime limit it does not deliver.
    """

    if value is None:
        return None
    if not isinstance(value, dict):
        raise InstituteSettingsValidationError(
            "auto_sync must be an object; use null to restore the default (off)."
        )
    if set(value) - _AUTO_SYNC_FIELDS:
        raise InstituteSettingsValidationError(
            "auto_sync only supports enabled, interval_minutes, window_start, "
            "window_end, and weekdays."
        )

    enabled = value.get("enabled")
    if not isinstance(enabled, bool):
        raise InstituteSettingsValidationError(
            "auto_sync must state enabled as true or false."
        )

    interval = value.get("interval_minutes")
    if (
        isinstance(interval, bool)
        or not isinstance(interval, int)
        or not _MIN_AUTO_SYNC_INTERVAL_MINUTES
        <= interval
        <= _MAX_AUTO_SYNC_INTERVAL_MINUTES
    ):
        raise InstituteSettingsValidationError(
            "auto_sync interval_minutes must be a whole number of minutes from "
            f"{_MIN_AUTO_SYNC_INTERVAL_MINUTES} to {_MAX_AUTO_SYNC_INTERVAL_MINUTES}. "
            "A smaller number is refused rather than sped up, and switching the "
            "schedule off is enabled: false."
        )

    raw_start = value.get("window_start")
    raw_end = value.get("window_end")
    if (raw_start is None) != (raw_end is None):
        raise InstituteSettingsValidationError(
            "auto_sync window_start and window_end must be set together; "
            "leave both empty to allow any time of day."
        )
    window_start = window_end = None
    if raw_start is not None:
        window_start = _auto_sync_time_of_day(raw_start, "auto_sync window_start")
        window_end = _auto_sync_time_of_day(raw_end, "auto_sync window_end")
        if window_start == window_end:
            raise InstituteSettingsValidationError(
                "auto_sync window_start and window_end must differ; leave both "
                "empty to allow any time of day. A window may cross midnight, "
                "so 22:00 to 06:00 is a valid overnight window."
            )

    return {
        "enabled": enabled,
        "interval_minutes": interval,
        "window_start": window_start,
        "window_end": window_end,
        "weekdays": _auto_sync_weekdays(value.get("weekdays")),
    }


def normalize_institute_settings_update(
    existing_settings: Any,
    settings_patch: dict[str, Any],
) -> dict[str, Any]:
    """Return a validated patch for backend-owned operational settings.

    Unknown keys pass through unchanged and are shallow-merged by the API.
    ``notification_channels`` is intentionally a complete replacement object,
    making omission of a channel an explicit deletion.
    """
    existing = existing_settings if isinstance(existing_settings, dict) else {}
    normalised = dict(settings_patch)

    if "notification_channels" in settings_patch:
        normalised["notification_channels"] = _notification_channels(
            settings_patch["notification_channels"],
            existing.get("notification_channels"),
        )
    if "shipment_reception_checklist" in settings_patch:
        normalised["shipment_reception_checklist"] = _clean_string_list(
            settings_patch["shipment_reception_checklist"],
            setting_name="shipment_reception_checklist",
            item_label="checklist label",
            max_length=200,
        )
    if "shipment_reception_tests" in settings_patch:
        normalised["shipment_reception_tests"] = _shipment_reception_tests(
            settings_patch["shipment_reception_tests"]
        )
    if "glue_pot_life_minutes" in settings_patch:
        normalised["glue_pot_life_minutes"] = _glue_pot_life_minutes(
            settings_patch["glue_pot_life_minutes"]
        )
    if "evidence_component_types" in settings_patch:
        normalised["evidence_component_types"] = _clean_string_list(
            settings_patch["evidence_component_types"],
            setting_name="evidence_component_types",
            item_label="component type code",
            max_length=32,
            uppercase=True,
        )
    if "reminder_escalation" in settings_patch:
        normalised["reminder_escalation"] = _reminder_escalation(
            settings_patch["reminder_escalation"]
        )
    if "assembly_tool_slots" in settings_patch:
        normalised["assembly_tool_slots"] = _assembly_tool_slots(
            settings_patch["assembly_tool_slots"]
        )
    if "test_tool_fields" in settings_patch:
        normalised["test_tool_fields"] = _test_tool_fields(
            settings_patch["test_tool_fields"]
        )
    if "glue_targets" in settings_patch:
        normalised["glue_targets"] = _glue_targets(settings_patch["glue_targets"])
    if "glue_weight_inputs" in settings_patch:
        normalised["glue_weight_inputs"] = _glue_weight_inputs(
            settings_patch["glue_weight_inputs"]
        )
    # `glue_process_default` was briefly used during development. Accept it at
    # the boundary for old clients, but persist/return only the canonical key.
    if "glue_default_process" in settings_patch:
        normalised["glue_default_process"] = _glue_default_process(
            settings_patch["glue_default_process"]
        )
        normalised.pop("glue_process_default", None)
    elif "glue_process_default" in settings_patch:
        normalised["glue_default_process"] = _glue_default_process(
            settings_patch["glue_process_default"]
        )
        normalised.pop("glue_process_default", None)
    if "glue_process_property" in settings_patch:
        normalised["glue_process_property"] = _glue_process_property(
            settings_patch["glue_process_property"]
        )
    if "auto_sync" in settings_patch:
        normalised["auto_sync"] = _auto_sync(settings_patch["auto_sync"])
    if "stage_order" in settings_patch:
        normalised["stage_order"] = _stage_order(settings_patch["stage_order"])
    if "stage_requirements" in settings_patch:
        normalised["stage_requirements"] = _stage_requirements(
            settings_patch["stage_requirements"]
        )
    if "stage_policy_approved" in settings_patch:
        approved = settings_patch["stage_policy_approved"]
        if not isinstance(approved, bool):
            raise InstituteSettingsValidationError(
                "stage_policy_approved must be true or false."
            )
        normalised["stage_policy_approved"] = approved
    elif {"stage_order", "stage_requirements"} & settings_patch.keys():
        # Approval belongs to the exact workflow that was reviewed. API clients
        # other than the bundled UI must not be able to edit that workflow and
        # accidentally retain an earlier approval by omitting this field.
        normalised["stage_policy_approved"] = False
    _validate_glue_process_contract(existing, normalised, settings_patch)
    _reconcile_stage_model(normalised)
    if normalised.get("stage_policy_approved") is True:
        resulting_settings = {**existing, **normalised}
        if not has_explicit_stage_policy(resulting_settings):
            raise InstituteSettingsValidationError(
                "stage_policy_approved may be true only when stage_order and "
                "stage_requirements fully define the effective stage policy."
            )
    return normalised
