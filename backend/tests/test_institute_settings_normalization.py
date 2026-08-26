import pytest

from app.institute_settings import (
    InstituteSettingsValidationError,
    normalize_institute_settings_update,
)


def test_normalizes_operational_settings_without_touching_unknown_keys():
    patch = {
        "logo_url": "logo.svg",
        "notification_channels": {
            " alerts ": {
                "kind": " MatterMost ",
                "url": " HTTPS://hooks.example.org/secret-token ",
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
        "evidence_component_types": [" module ", "SENSOR", "module", " "],
        "shipment_reception_tests": {
            " module ": [" reception_iv ", "RECEPTION_VISUAL", "RECEPTION_IV"],
            "HYBRID": ["HYBRID_RECEPTION"],
        },
    }

    normalised = normalize_institute_settings_update({}, patch)

    assert normalised == {
        "logo_url": "logo.svg",
        "notification_channels": {
            "alerts": {
                "kind": "mattermost",
                "url": "https://hooks.example.org/secret-token",
                "channel": "lab-ops",
            }
        },
        "shipment_reception_checklist": ["Count modules", "Check humidity strip"],
        "glue_pot_life_minutes": {"POLARIS_EPOXY": 45},
        "evidence_component_types": ["MODULE", "SENSOR"],
        "shipment_reception_tests": {
            "MODULE": ["RECEPTION_IV", "RECEPTION_VISUAL"],
            "HYBRID": ["HYBRID_RECEPTION"],
        },
    }
    # The caller owns the original request object; normalisation is pure.
    assert " alerts " in patch["notification_channels"]


def test_mask_resolves_only_against_same_channel_name_and_kind():
    existing = {
        "notification_channels": {
            "lab": {
                "kind": "mattermost",
                "url": "https://hooks.example.org/existing-secret",
            }
        }
    }

    normalised = normalize_institute_settings_update(
        existing,
        {
            "notification_channels": {
                "lab": {"kind": "mattermost", "url": "***"},
            }
        },
    )

    assert normalised["notification_channels"] == {
        "lab": {
            "kind": "mattermost",
            "url": "https://hooks.example.org/existing-secret",
        }
    }
    assert "***" not in str(normalised)

    with pytest.raises(InstituteSettingsValidationError):
        normalize_institute_settings_update(
            existing,
            {
                "notification_channels": {
                    "lab": {"kind": "telegram", "url": "***", "chat_id": "@lab"},
                }
            },
        )


@pytest.mark.parametrize(
    "patch",
    [
        {"notification_channels": []},
        {"notification_channels": {"new": {"kind": "webhook", "url": "***"}}},
        {
            "notification_channels": {
                "https://secret.example.org": {
                    "kind": "webhook",
                    "url": "https://hooks.example.org/hook",
                }
            }
        },
        {
            "notification_channels": {
                "bad": {"kind": "webhook", "url": "http://secret.example.org/hook"}
            }
        },
        {
            "notification_channels": {
                "bad": {"kind": "email", "url": "https://secret.example.org/hook"}
            }
        },
        {
            "notification_channels": {
                "bad": {
                    "kind": "webhook",
                    "url": "https://secret.example.org/hook",
                    "token": "not-a-supported-field",
                }
            }
        },
        {"shipment_reception_checklist": ["Valid", 42]},
        {"glue_pot_life_minutes": {"EPOXY": True}},
        {"glue_pot_life_minutes": {"EPOXY": 0}},
        {"glue_pot_life_minutes": {"EPOXY": 1441}},
        {"evidence_component_types": ["MODULE", 42]},
        {"evidence_component_types": ["NOT A CODE"]},
        {"shipment_reception_tests": []},
        {"shipment_reception_tests": {"MODULE": "RECEPTION_IV"}},
        {"shipment_reception_tests": {"BAD TYPE": ["RECEPTION_IV"]}},
        {"shipment_reception_tests": {"MODULE": ["BAD TEST"]}},
        {"shipment_reception_tests": {"MODULE": [42]}},
    ],
)
def test_rejects_invalid_operational_settings_without_echoing_values(patch):
    with pytest.raises(InstituteSettingsValidationError) as caught:
        normalize_institute_settings_update({}, patch)

    assert "secret.example.org" not in str(caught.value)


def test_glue_pot_life_accepts_contract_boundaries():
    assert normalize_institute_settings_update(
        {}, {"glue_pot_life_minutes": {"FAST": 1, "SLOW": 1440}}
    ) == {"glue_pot_life_minutes": {"FAST": 1, "SLOW": 1440}}
