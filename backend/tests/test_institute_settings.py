# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-FileComment: itkflow-3202f6f850c8
"""Admin editing of institute profile config, incl. required_properties (docs/07).

This is what makes the data-driven features (jig requirements, stage
requirements) configurable in-app instead of only at institute creation.
"""

import json

import pytest
from authutil import authenticate
from sqlalchemy import select

from app.domain.stages import (
    DEFAULT_STAGE_ORDER,
    DEFAULT_STAGE_REQUIREMENTS,
    stage_model_from_settings,
)
from app.institute_settings import (
    InstituteSettingsValidationError,
    normalize_institute_settings_update,
)
from app.models import AuditEvent, InstituteProfile


def test_update_institute_requires_login(client, tudo):
    assert client.patch("/api/institutes/TUDO", json={"settings": {"x": 1}}).status_code == 401


def test_update_institute_forbidden_for_viewer(as_viewer, tudo):
    assert as_viewer.patch("/api/institutes/TUDO", json={"settings": {"x": 1}}).status_code == 403


def test_update_institute_forbidden_for_operator(as_operator, tudo):
    assert as_operator.patch("/api/institutes/TUDO", json={"settings": {"x": 1}}).status_code == 403


def test_admin_merges_settings(as_admin, session_factory, tudo):
    with session_factory() as s:
        prof = s.scalar(select(InstituteProfile).where(InstituteProfile.code == "TUDO"))
        prof.settings = {"logo_url": "x.png"}
        s.commit()
    resp = as_admin.patch(
        "/api/institutes/TUDO",
        json={"settings": {"required_properties": {"GLUE_WEIGHT": ["JIG"]}}},
    )
    assert resp.status_code == 200, resp.text
    settings = resp.json()["settings"]
    assert settings["logo_url"] == "x.png"  # unrelated config preserved
    assert settings["required_properties"] == {"GLUE_WEIGHT": ["JIG"]}


def test_unknown_nullable_setting_keeps_legacy_shallow_merge_semantics(
    as_admin, session_factory, tudo
):
    response = as_admin.patch(
        "/api/institutes/TUDO",
        json={"settings": {"future_optional_setting": None}},
    )
    assert response.status_code == 200, response.text
    assert "future_optional_setting" in response.json()["settings"]
    assert response.json()["settings"]["future_optional_setting"] is None
    with session_factory() as session:
        institute = session.get(InstituteProfile, tudo["id"])
        event = session.scalar(
            select(AuditEvent).where(AuditEvent.action == "institute.updated")
        )
    assert "future_optional_setting" in institute.settings
    assert event.detail == {"settings_keys": ["future_optional_setting"]}


def test_admin_update_unknown_institute(as_admin):
    assert as_admin.patch("/api/institutes/NOPE", json={"settings": {}}).status_code == 404


def test_create_institute_uses_the_same_operational_settings_contract(
    as_admin, session_factory
):
    rejected = as_admin.post(
        "/api/institutes",
        json={
            "code": "BADCFG",
            "name": "Bad configuration",
            "settings": {
                "notification_channels": {
                    "ops": {"kind": "webhook", "url": "http://secret.example.org/hook"}
                }
            },
        },
    )
    assert rejected.status_code == 422, rejected.text
    assert "secret.example.org" not in rejected.text

    secret_url = "https://hooks.example.org/create-secret"
    created = as_admin.post(
        "/api/institutes",
        json={
            "code": "NEWLAB",
            "name": "New laboratory",
            "settings": {
                "custom_compatible_setting": {"enabled": True},
                "glue_pot_life_minutes": {" EPOXY ": 1440},
                "notification_channels": {
                    " ops ": {"kind": " WebHook ", "url": secret_url}
                },
            },
        },
    )
    assert created.status_code == 201, created.text
    assert secret_url not in created.text
    assert created.json()["settings"] == {
        "custom_compatible_setting": {"enabled": True},
        "glue_pot_life_minutes": {"EPOXY": 1440},
        "notification_channels": {
            "ops": {"kind": "webhook", "url": "***"},
        },
    }
    with session_factory() as session:
        institute = session.scalar(
            select(InstituteProfile).where(InstituteProfile.code == "NEWLAB")
        )
    assert institute is not None
    assert institute.settings["notification_channels"]["ops"]["url"] == secret_url
    with session_factory() as session:
        event = session.scalar(
            select(AuditEvent).where(AuditEvent.action == "institute.created")
        )
    assert event is not None
    assert event.subject == "institute:NEWLAB"
    assert secret_url not in json.dumps(event.detail)


def test_per_institute_admin_is_scoped(client, session_factory, tudo):
    with session_factory() as s:
        s.add(InstituteProfile(code="DESYZ", name="DESY Zeuthen"))
        s.commit()
    authenticate(
        client, session_factory, role="admin", institute_id=tudo["id"], email="tudoadmin@x"
    )
    # own institute: allowed
    assert client.patch("/api/institutes/TUDO", json={"name": "TU Dortmund X"}).status_code == 200
    # someone else's: forbidden
    assert client.patch("/api/institutes/DESYZ", json={"name": "nope"}).status_code == 403


def test_admin_normalizes_operational_settings_and_audits_no_values(
    as_admin, session_factory, tudo
):
    secret_url = "https://hooks.example.org/very-secret-token"
    with session_factory() as session:
        institute = session.get(InstituteProfile, tudo["id"])
        institute.settings = {"logo_url": "existing.svg"}
        session.commit()

    response = as_admin.patch(
        "/api/institutes/TUDO",
        json={
            "settings": {
                "notification_channels": {
                    " alerts ": {
                        "kind": " MatterMost ",
                        "url": f" {secret_url} ",
                        "channel": " lab-ops ",
                    }
                },
                "shipment_reception_checklist": [
                    " Count modules ",
                    "",
                    "Count modules",
                    "Check humidity strip",
                ],
                "glue_pot_life_minutes": {" POLARIS_EPOXY ": 45},
                "evidence_component_types": [" module ", "SENSOR", "module"],
            }
        },
    )

    assert response.status_code == 200, response.text
    assert secret_url not in response.text
    settings = response.json()["settings"]
    assert settings["logo_url"] == "existing.svg"
    assert settings["notification_channels"] == {
        "alerts": {"kind": "mattermost", "url": "***", "channel": "lab-ops"}
    }
    assert settings["shipment_reception_checklist"] == [
        "Count modules",
        "Check humidity strip",
    ]
    assert settings["glue_pot_life_minutes"] == {"POLARIS_EPOXY": 45}
    assert settings["evidence_component_types"] == ["MODULE", "SENSOR"]

    with session_factory() as session:
        institute = session.get(InstituteProfile, tudo["id"])
        assert institute.settings["notification_channels"]["alerts"]["url"] == secret_url
        event = session.scalar(
            select(AuditEvent)
            .where(AuditEvent.action == "institute.updated")
            .order_by(AuditEvent.id.desc())
        )

    assert event is not None
    assert event.detail == {
        "settings_keys": [
            "evidence_component_types",
            "glue_pot_life_minutes",
            "notification_channels",
            "shipment_reception_checklist",
        ],
        "notification_channels": ["alerts"],
    }
    audit_json = json.dumps(event.detail)
    assert secret_url not in audit_json
    assert "very-secret-token" not in audit_json


def test_mask_preserves_existing_url_and_complete_object_deletes_omitted_channels(
    as_admin, session_factory, tudo
):
    lab_url = "https://hooks.example.org/lab-secret"
    ops_url = "https://hooks.example.org/ops-secret"
    with session_factory() as session:
        institute = session.get(InstituteProfile, tudo["id"])
        institute.settings = {
            "logo_url": "keep.svg",
            "notification_channels": {
                "lab": {"kind": "mattermost", "url": lab_url, "channel": "old"},
                "ops": {"kind": "webhook", "url": ops_url},
            },
        }
        session.commit()

    response = as_admin.patch(
        "/api/institutes/TUDO",
        json={
            "settings": {
                "notification_channels": {
                    "lab": {"kind": "mattermost", "url": "***", "channel": "new"}
                }
            }
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["settings"]["notification_channels"] == {
        "lab": {"kind": "mattermost", "url": "***", "channel": "new"}
    }
    with session_factory() as session:
        institute = session.get(InstituteProfile, tudo["id"])
        assert institute.settings["logo_url"] == "keep.svg"
        assert institute.settings["notification_channels"] == {
            "lab": {"kind": "mattermost", "url": lab_url, "channel": "new"}
        }
        assert "***" not in json.dumps(institute.settings)
        event = session.scalar(
            select(AuditEvent)
            .where(AuditEvent.action == "institute.updated")
            .order_by(AuditEvent.id.desc())
        )
    assert event.detail["notification_channels"] == ["lab", "ops"]
    assert lab_url not in json.dumps(event.detail)
    assert ops_url not in json.dumps(event.detail)

    deleted = as_admin.patch(
        "/api/institutes/TUDO",
        json={"settings": {"notification_channels": {}}},
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["settings"]["notification_channels"] == {}
    with session_factory() as session:
        institute = session.get(InstituteProfile, tudo["id"])
        assert institute.settings["notification_channels"] == {}


def test_mask_for_new_channel_and_insecure_url_are_rejected_atomically(
    as_admin, session_factory, tudo
):
    original_name = tudo["name"]
    for url in ("***", "http://secret.example.org/hook"):
        response = as_admin.patch(
            "/api/institutes/TUDO",
            json={
                "name": "Must roll back",
                "settings": {
                    "notification_channels": {
                        "new": {"kind": "webhook", "url": url},
                    }
                },
            },
        )
        assert response.status_code == 422
        assert "secret.example.org" not in response.text

    with session_factory() as session:
        institute = session.get(InstituteProfile, tudo["id"])
        assert institute.name == original_name
        assert "notification_channels" not in institute.settings
        events = list(
            session.scalars(select(AuditEvent).where(AuditEvent.action == "institute.updated"))
        )
    assert events == []


def test_institute_get_projects_legacy_channels_through_a_safe_allowlist(
    client, session_factory, tudo
):
    with session_factory() as session:
        institute = session.get(InstituteProfile, tudo["id"])
        institute.settings = {
            "logo_url": "keep.svg",
            "notification_channels": {
                "lab": {
                    "kind": "mattermost",
                    "url": "https://hooks.example.org/real-secret",
                    "channel": "operations",
                    "token": "unknown-secret",
                    "backup_url": "https://backup.example.org/secret",
                },
                "malformed": {
                    "kind": "email",
                    "url": "https://mail.example.org/secret",
                    "api_key": "mail-secret",
                },
                "raw": "https://raw.example.org/secret",
            },
        }
        session.commit()

    response = client.get("/api/institutes")
    assert response.status_code == 200, response.text
    settings = response.json()[0]["settings"]
    assert settings == {
        "logo_url": "keep.svg",
        "notification_channels": {
            "lab": {
                "kind": "mattermost",
                "url": "***",
                "channel": "operations",
            }
        },
    }
    for secret_fragment in (
        "real-secret",
        "unknown-secret",
        "backup.example.org",
        "mail.example.org",
        "mail-secret",
        "raw.example.org",
    ):
        assert secret_fragment not in response.text


def test_noop_profile_and_masked_channel_patch_emits_no_update_audit(
    as_admin, session_factory, tudo
):
    with session_factory() as session:
        institute = session.get(InstituteProfile, tudo["id"])
        institute.settings = {
            "logo_url": "keep.svg",
            "notification_channels": {
                "lab": {
                    "kind": "mattermost",
                    "url": "https://hooks.example.org/secret",
                    "channel": "operations",
                }
            },
        }
        session.commit()

    response = as_admin.patch(
        "/api/institutes/TUDO",
        json={
            "name": tudo["name"],
            "local_name_prefix": tudo["local_name_prefix"],
            "settings": {
                "logo_url": "keep.svg",
                "notification_channels": {
                    "lab": {
                        "kind": "mattermost",
                        "url": "***",
                        "channel": "operations",
                    }
                },
            },
        },
    )
    assert response.status_code == 200, response.text
    with session_factory() as session:
        events = list(
            session.scalars(select(AuditEvent).where(AuditEvent.action == "institute.updated"))
        )
        institute = session.get(InstituteProfile, tudo["id"])
    assert events == []
    assert institute.settings["notification_channels"]["lab"]["url"].endswith("/secret")


def test_stage_model_normalizer_cleans_names_and_keeps_order(as_admin, session_factory, tudo):
    response = as_admin.patch(
        "/api/institutes/TUDO",
        json={
            "settings": {
                "stage_order": [" hv_tab_attached ", "GLUED", "tested"],
                "stage_requirements": {
                    " glued ": [" glue_weight ", "MODULE_BOW"],
                    "TESTED": ["module_iv_amac"],
                    "HV_TAB_ATTACHED": [],
                },
            }
        },
    )

    assert response.status_code == 200, response.text
    settings = response.json()["settings"]
    assert settings["stage_order"] == ["HV_TAB_ATTACHED", "GLUED", "TESTED"]
    assert settings["stage_requirements"] == {
        "GLUED": ["GLUE_WEIGHT", "MODULE_BOW"],
        "TESTED": ["MODULE_IV_AMAC"],
        # An explicit empty list is a real override: this stage requires nothing.
        "HV_TAB_ATTACHED": [],
    }
    with session_factory() as session:
        institute = session.get(InstituteProfile, tudo["id"])
        model = stage_model_from_settings(institute.settings)
    assert model.order[:3] == ("HV_TAB_ATTACHED", "GLUED", "TESTED")
    assert model.required_tests["TESTED"] == ("MODULE_IV_AMAC",)
    assert model.required_tests["HV_TAB_ATTACHED"] == ()


def test_stray_requirement_stage_is_appended_to_the_stored_order(as_admin, session_factory, tudo):
    """`stage_model_from_settings` appends it anyway — say so in the profile."""

    response = as_admin.patch(
        "/api/institutes/TUDO",
        json={
            "settings": {
                "stage_order": ["ALPHA", "BETA"],
                "stage_requirements": {"GAMMA": ["SOME_TEST"]},
            }
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["settings"]["stage_order"] == ["ALPHA", "BETA", "GAMMA"]
    with session_factory() as session:
        institute = session.get(InstituteProfile, tudo["id"])
    model = stage_model_from_settings(institute.settings)
    assert model.requirements_through("GAMMA")[-1] == ("GAMMA", "SOME_TEST")


def test_null_stage_model_restores_the_seed_default(as_admin, session_factory, tudo):
    with session_factory() as session:
        institute = session.get(InstituteProfile, tudo["id"])
        institute.settings = {"stage_order": ["ONLY_STAGE"], "stage_requirements": {}}
        session.commit()

    response = as_admin.patch(
        "/api/institutes/TUDO",
        json={"settings": {"stage_order": None, "stage_requirements": None}},
    )

    assert response.status_code == 200, response.text
    assert response.json()["settings"]["stage_order"] is None
    with session_factory() as session:
        institute = session.get(InstituteProfile, tudo["id"])
    assert stage_model_from_settings(institute.settings).order == DEFAULT_STAGE_ORDER


@pytest.mark.parametrize(
    "patch",
    [
        pytest.param({"stage_order": []}, id="empty-order"),
        pytest.param({"stage_order": "GLUED"}, id="order-not-a-list"),
        pytest.param({"stage_order": ["GLUED", 7]}, id="order-item-not-a-string"),
        pytest.param({"stage_order": ["GLUED", "  "]}, id="blank-stage"),
        pytest.param({"stage_order": ["GLUED", "glued"]}, id="duplicate-stage"),
        pytest.param({"stage_order": ["1_GLUED"]}, id="stage-name-shape"),
        pytest.param({"stage_order": ["G" * 65]}, id="stage-name-too-long"),
        pytest.param({"stage_requirements": ["GLUED"]}, id="requirements-not-an-object"),
        pytest.param({"stage_requirements": {"GLUED": "GLUE_WEIGHT"}}, id="tests-not-a-list"),
        pytest.param({"stage_requirements": {"GLUED": [3]}}, id="test-not-a-string"),
        pytest.param({"stage_requirements": {"GLUED": ["glue weight"]}}, id="test-shape"),
        pytest.param(
            {"stage_requirements": {"GLUED": ["GLUE_WEIGHT", "glue_weight"]}},
            id="duplicate-test",
        ),
        pytest.param(
            {"stage_requirements": {"GLUED": ["X"], " glued ": ["Y"]}},
            id="duplicate-requirement-stage",
        ),
    ],
)
def test_invalid_stage_model_is_rejected(patch):
    with pytest.raises(InstituteSettingsValidationError):
        normalize_institute_settings_update({}, patch)


def test_empty_requirements_object_is_a_valid_no_override():
    assert normalize_institute_settings_update({}, {"stage_requirements": {}}) == {
        "stage_requirements": {},
        "stage_policy_approved": False,
    }


def test_stage_workflow_edit_clears_approval_unless_deliberately_reapproved():
    explicit_requirements = {
        stage: list(DEFAULT_STAGE_REQUIREMENTS[stage]) for stage in DEFAULT_STAGE_ORDER
    }
    existing = {
        "stage_order": list(DEFAULT_STAGE_ORDER),
        "stage_requirements": explicit_requirements,
        "stage_policy_approved": True,
    }

    assert normalize_institute_settings_update(
        existing,
        {"stage_requirements": {stage: [] for stage in DEFAULT_STAGE_ORDER}},
    )["stage_policy_approved"] is False
    assert normalize_institute_settings_update(
        existing,
        {
            "stage_requirements": {stage: [] for stage in DEFAULT_STAGE_ORDER},
            "stage_policy_approved": True,
        },
    )["stage_policy_approved"] is True


@pytest.mark.parametrize(
    "existing,patch",
    [
        ({}, {"stage_policy_approved": True}),
        (
            {"stage_order": list(DEFAULT_STAGE_ORDER)},
            {"stage_policy_approved": True},
        ),
        (
            {},
            {
                "stage_order": list(DEFAULT_STAGE_ORDER),
                "stage_requirements": {"GLUED": []},
                "stage_policy_approved": True,
            },
        ),
    ],
    ids=["seed-only", "missing-requirements", "partial-requirements"],
)
def test_stage_policy_approval_rejects_seed_or_partial_profiles(existing, patch):
    with pytest.raises(
        InstituteSettingsValidationError,
        match="fully define the effective stage policy",
    ):
        normalize_institute_settings_update(existing, patch)


@pytest.mark.parametrize("value", [None, 0, 1, "true", [], {}])
def test_stage_policy_approval_requires_a_boolean(value):
    with pytest.raises(
        InstituteSettingsValidationError,
        match="stage_policy_approved must be true or false",
    ):
        normalize_institute_settings_update({}, {"stage_policy_approved": value})


def test_invalid_stage_model_leaves_the_profile_untouched(as_admin, session_factory, tudo):
    with session_factory() as session:
        institute = session.get(InstituteProfile, tudo["id"])
        institute.settings = {"stage_order": ["KEEP_ME"]}
        session.commit()

    response = as_admin.patch(
        "/api/institutes/TUDO",
        json={"name": "Must roll back", "settings": {"stage_order": ["A", "A"]}},
    )

    assert response.status_code == 422, response.text
    with session_factory() as session:
        institute = session.get(InstituteProfile, tudo["id"])
        assert institute.settings["stage_order"] == ["KEEP_ME"]
        assert institute.name == tudo["name"]


def test_telegram_and_email_secrets_survive_an_unrelated_structured_save(
    as_admin, session_factory, tudo
):
    telegram_url = "https://api.telegram.org/bot123:SECRET/sendMessage"
    smtp_password = "mail-secret"
    with session_factory() as session:
        institute = session.get(InstituteProfile, tudo["id"])
        institute.settings = {
            "notification_channels": {
                "telegram": {
                    "kind": "telegram",
                    "url": telegram_url,
                    "chat_id": "-1001234567890",
                },
                "email": {
                    "kind": "email",
                    "smtp_host": "smtp.example.org",
                    "smtp_port": 587,
                    "smtp_security": "starttls",
                    "smtp_username": "mailer@example.org",
                    "smtp_password": smtp_password,
                    "from_address": "itkflow@example.org",
                    "to_address": "lab@example.org",
                },
            }
        }
        session.commit()

    response = as_admin.patch(
        "/api/institutes/TUDO",
        json={
            "settings": {
                "shipment_reception_checklist": ["Count modules"],
                "notification_channels": {
                    "telegram": {
                        "kind": "telegram",
                        "url": "***",
                        "chat_id": "-1001234567890",
                    },
                    "email": {
                        "kind": "email",
                        "smtp_host": "smtp.example.org",
                        "smtp_port": 587,
                        "smtp_security": "starttls",
                        "smtp_username": "mailer@example.org",
                        "smtp_password": "***",
                        "from_address": "itkflow@example.org",
                        "to_address": "lab@example.org",
                    },
                },
            }
        },
    )
    assert response.status_code == 200, response.text
    assert telegram_url not in response.text
    assert smtp_password not in response.text
    public = response.json()["settings"]["notification_channels"]
    assert public["telegram"]["url"] == "***"
    assert public["email"]["smtp_password"] == "***"

    with session_factory() as session:
        stored = session.get(InstituteProfile, tudo["id"])
    assert stored.settings["notification_channels"]["telegram"]["url"] == telegram_url
    assert stored.settings["notification_channels"]["email"]["smtp_password"] == smtp_password


# -- unattended sync schedule (`auto_sync`) ---------------------------------
#
# The one institute setting that makes itkFlow contact the PDB on its own,
# without anyone asking for it at that moment. The reader in `app.auto_sync`
# fails closed (a malformed block reads as "off", a too-small interval is
# lifted to the floor), so this validator is the only thing that ever tells a
# person their input was wrong — which is why every rejection is pinned here.


def _schedule(**overrides):
    """The documented block, with the field under test replaced."""

    block = {
        "enabled": True,
        "interval_minutes": 60,
        "window_start": "07:00",
        "window_end": "19:00",
        "weekdays": [1, 2, 3, 4, 5],
    }
    block.update(overrides)
    return block


def _normalize_auto_sync(block, existing=None):
    return normalize_institute_settings_update(existing or {}, {"auto_sync": block})[
        "auto_sync"
    ]


def test_auto_sync_accepts_the_documented_shape():
    assert _normalize_auto_sync(_schedule()) == {
        "enabled": True,
        "interval_minutes": 60,
        "window_start": "07:00",
        "window_end": "19:00",
        "weekdays": [1, 2, 3, 4, 5],
    }


def test_auto_sync_is_absent_unless_the_patch_mentions_it():
    normalised = normalize_institute_settings_update(
        {}, {"shipment_reception_checklist": ["Count modules"]}
    )

    # An unrelated save must never write a schedule into a profile that has
    # none: absence is how "no unattended traffic" is stored.
    assert "auto_sync" not in normalised


def test_auto_sync_null_clears_the_schedule_back_to_off():
    from app.auto_sync import read_auto_sync_schedule

    normalised = normalize_institute_settings_update(
        {"auto_sync": _schedule()}, {"auto_sync": None}
    )

    assert normalised["auto_sync"] is None
    assert read_auto_sync_schedule(normalised).enabled is False


def test_auto_sync_keeps_an_overnight_window_as_written():
    from app.auto_sync import read_auto_sync_schedule

    stored = _normalize_auto_sync(
        _schedule(window_start="22:00", window_end="06:00", weekdays=[5])
    )

    # Crossing midnight is what "sync overnight" means; a validator demanding
    # start <= end would forbid the most considerate schedule there is.
    assert stored["window_start"] == "22:00"
    assert stored["window_end"] == "06:00"
    schedule = read_auto_sync_schedule({"auto_sync": stored})
    assert (schedule.window_start, schedule.window_end) == ("22:00", "06:00")
    assert schedule.weekdays == (5,)


def test_auto_sync_disabled_block_keeps_its_window_and_stays_inert():
    from app.auto_sync import read_auto_sync_schedule

    stored = _normalize_auto_sync(_schedule(enabled=False))

    # A schedule may be prepared and switched off without losing what it says,
    # but "off" has to mean off for the scheduler.
    assert stored["enabled"] is False
    assert stored["window_start"] == "07:00"
    assert read_auto_sync_schedule({"auto_sync": stored}).enabled is False


def test_auto_sync_interval_floor_matches_the_scheduler():
    from app.auto_sync import MIN_INTERVAL_MINUTES
    from app.institute_settings import _MIN_AUTO_SYNC_INTERVAL_MINUTES

    # If these drift apart, one side rejects what the other accepts and a
    # schedule looks configured on screen while never firing.
    assert _MIN_AUTO_SYNC_INTERVAL_MINUTES == MIN_INTERVAL_MINUTES


def test_auto_sync_accepts_exactly_the_floor():
    assert _normalize_auto_sync(_schedule(interval_minutes=15))["interval_minutes"] == 15


@pytest.mark.parametrize("interval", [14, 1, 0, -60])
def test_auto_sync_rejects_an_interval_below_the_floor(interval):
    with pytest.raises(InstituteSettingsValidationError, match="interval_minutes"):
        _normalize_auto_sync(_schedule(interval_minutes=interval))


@pytest.mark.parametrize("interval", ["60", 60.5, True, None, 10_081])
def test_auto_sync_rejects_a_non_integer_or_oversized_interval(interval):
    with pytest.raises(InstituteSettingsValidationError, match="interval_minutes"):
        _normalize_auto_sync(_schedule(interval_minutes=interval))


def test_auto_sync_requires_an_interval():
    block = _schedule()
    del block["interval_minutes"]

    with pytest.raises(InstituteSettingsValidationError, match="interval_minutes"):
        _normalize_auto_sync(block)


@pytest.mark.parametrize(
    "block",
    [
        {"enabled": True, "interval_minutes": 60, "window_start": "07:00"},
        {"enabled": True, "interval_minutes": 60, "window_end": "19:00"},
        {
            "enabled": True,
            "interval_minutes": 60,
            "window_start": "07:00",
            "window_end": None,
        },
    ],
)
def test_auto_sync_rejects_half_a_window(block):
    with pytest.raises(InstituteSettingsValidationError, match="set together"):
        _normalize_auto_sync(block)


@pytest.mark.parametrize(
    "moment", ["7:00", "24:00", "07:60", "0700", "07:00:00", "", "noon", 700]
)
def test_auto_sync_rejects_a_malformed_time(moment):
    with pytest.raises(InstituteSettingsValidationError, match="HH:MM"):
        _normalize_auto_sync(_schedule(window_start=moment))


def test_auto_sync_trims_surrounding_whitespace_from_a_time():
    assert _normalize_auto_sync(_schedule(window_start=" 07:00 "))["window_start"] == "07:00"


def test_auto_sync_rejects_a_window_that_starts_and_ends_at_the_same_minute():
    # The reader treats an identical pair as no window at all, so storing one
    # would promise a daytime limit that never applies.
    with pytest.raises(InstituteSettingsValidationError, match="must differ"):
        _normalize_auto_sync(_schedule(window_start="07:00", window_end="07:00"))


def test_auto_sync_accepts_a_schedule_without_a_window():
    stored = _normalize_auto_sync(_schedule(window_start=None, window_end=None))

    assert stored["window_start"] is None
    assert stored["window_end"] is None


@pytest.mark.parametrize("weekdays", [[0], [8], [-1], [1, 8]])
def test_auto_sync_rejects_a_weekday_outside_the_iso_range(weekdays):
    with pytest.raises(InstituteSettingsValidationError, match=r"1 \(Monday\)"):
        _normalize_auto_sync(_schedule(weekdays=weekdays))


@pytest.mark.parametrize("weekdays", [["1"], [True], [1.0], [None]])
def test_auto_sync_rejects_weekdays_that_are_not_whole_numbers(weekdays):
    with pytest.raises(InstituteSettingsValidationError, match="whole numbers"):
        _normalize_auto_sync(_schedule(weekdays=weekdays))


def test_auto_sync_rejects_duplicate_weekdays():
    with pytest.raises(InstituteSettingsValidationError, match="repeat a day"):
        _normalize_auto_sync(_schedule(weekdays=[1, 2, 1]))


def test_auto_sync_rejects_an_empty_weekday_list():
    # Unticking every day means "never". Stored as an empty list the reader
    # would read it as "every day" — the opposite, and unattended traffic in
    # exactly the case somebody tried to prevent.
    with pytest.raises(InstituteSettingsValidationError, match="at least one day"):
        _normalize_auto_sync(_schedule(weekdays=[]))


def test_auto_sync_rejects_weekdays_that_are_not_a_list():
    with pytest.raises(InstituteSettingsValidationError, match="weekdays"):
        _normalize_auto_sync(_schedule(weekdays={"monday": True}))


def test_auto_sync_null_weekdays_mean_every_day():
    from app.auto_sync import read_auto_sync_schedule

    stored = _normalize_auto_sync(_schedule(weekdays=None))

    assert stored["weekdays"] is None
    assert read_auto_sync_schedule({"auto_sync": stored}).weekdays == ()


def test_auto_sync_sorts_the_weekdays_it_stores():
    assert _normalize_auto_sync(_schedule(weekdays=[7, 1, 3]))["weekdays"] == [1, 3, 7]


def test_auto_sync_rejects_an_unknown_key():
    # Above all `timezone`: the window is server local time on purpose, and a
    # profile carrying a zone nobody reads would be a promise that is not kept.
    with pytest.raises(InstituteSettingsValidationError, match="only supports"):
        _normalize_auto_sync({**_schedule(), "timezone": "Europe/Berlin"})


@pytest.mark.parametrize("block", [[], "on", 60, True])
def test_auto_sync_rejects_a_block_that_is_not_an_object(block):
    with pytest.raises(InstituteSettingsValidationError, match="must be an object"):
        _normalize_auto_sync(block)


@pytest.mark.parametrize("enabled", ["true", 1, None, ...])
def test_auto_sync_requires_enabled_to_be_a_boolean(enabled):
    block = _schedule()
    if enabled is ...:
        del block["enabled"]
    else:
        block["enabled"] = enabled

    with pytest.raises(InstituteSettingsValidationError, match="true or false"):
        _normalize_auto_sync(block)


def test_admin_saves_an_auto_sync_schedule(as_admin, session_factory, tudo):
    response = as_admin.patch(
        "/api/institutes/TUDO",
        json={
            "settings": {
                "auto_sync": {
                    "enabled": True,
                    "interval_minutes": 120,
                    "window_start": "22:00",
                    "window_end": "06:00",
                    "weekdays": [5, 6],
                }
            }
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["settings"]["auto_sync"] == {
        "enabled": True,
        "interval_minutes": 120,
        "window_start": "22:00",
        "window_end": "06:00",
        "weekdays": [5, 6],
    }
    with session_factory() as session:
        stored = session.get(InstituteProfile, tudo["id"])
        assert stored.settings["auto_sync"]["interval_minutes"] == 120


def test_admin_cannot_save_a_schedule_below_the_floor(as_admin, session_factory, tudo):
    response = as_admin.patch(
        "/api/institutes/TUDO",
        json={"settings": {"auto_sync": {"enabled": True, "interval_minutes": 5}}},
    )

    assert response.status_code == 422, response.text
    with session_factory() as session:
        stored = session.get(InstituteProfile, tudo["id"])
        assert "auto_sync" not in (stored.settings or {})


def test_an_unrelated_admin_save_does_not_switch_a_schedule_on(
    as_admin, session_factory, tudo
):
    from app.auto_sync import read_auto_sync_schedule

    response = as_admin.patch(
        "/api/institutes/TUDO",
        json={"settings": {"shipment_reception_checklist": ["Count modules"]}},
    )

    assert response.status_code == 200, response.text
    with session_factory() as session:
        stored = session.get(InstituteProfile, tudo["id"])
        assert "auto_sync" not in (stored.settings or {})
        assert read_auto_sync_schedule(stored.settings).enabled is False
