"""Admin editing of institute profile config, incl. required_properties (docs/07).

This is what makes the data-driven features (jig requirements, stage
requirements) configurable in-app instead of only at institute creation.
"""

import json

import pytest
from authutil import authenticate
from sqlalchemy import select

from app.domain.stages import DEFAULT_STAGE_ORDER, stage_model_from_settings
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
        "stage_requirements": {}
    }


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
