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

import re
from typing import Any

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
    if "stage_order" in settings_patch:
        normalised["stage_order"] = _stage_order(settings_patch["stage_order"])
    if "stage_requirements" in settings_patch:
        normalised["stage_requirements"] = _stage_requirements(
            settings_patch["stage_requirements"]
        )
    _reconcile_stage_model(normalised)
    return normalised
