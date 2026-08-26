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


def test_masked_smtp_password_requires_the_same_connection_identity():
    existing = {
        "notification_channels": {
            "mail": {
                "kind": "email",
                "smtp_host": "smtp.example.org",
                "smtp_port": 587,
                "smtp_security": "starttls",
                "smtp_username": "itkflow",
                "smtp_password": "stored-secret",
                "from_address": "itkflow@example.org",
                "to_address": "ops@example.org",
            }
        }
    }
    unchanged = {
        **existing["notification_channels"]["mail"],
        "smtp_password": "***",
    }
    normalised = normalize_institute_settings_update(
        existing,
        {"notification_channels": {"mail": unchanged}},
    )
    assert normalised["notification_channels"]["mail"]["smtp_password"] == "stored-secret"

    redirected = {**unchanged, "smtp_host": "attacker.example.org"}
    with pytest.raises(InstituteSettingsValidationError) as caught:
        normalize_institute_settings_update(
            existing,
            {"notification_channels": {"mail": redirected}},
        )
    assert "stored-secret" not in str(caught.value)
    assert "attacker.example.org" not in str(caught.value)


def test_authenticated_email_can_remove_credentials_without_reusing_password():
    existing = {
        "notification_channels": {
            "mail": {
                "kind": "email",
                "smtp_host": "smtp.example.org",
                "smtp_port": 587,
                "smtp_security": "starttls",
                "smtp_username": "itkflow",
                "smtp_password": "stored-secret",
                "from_address": "itkflow@example.org",
                "to_address": "ops@example.org",
            }
        }
    }
    normalised = normalize_institute_settings_update(
        existing,
        {
            "notification_channels": {
                "mail": {
                    "kind": "email",
                    "smtp_host": "smtp.example.org",
                    "smtp_port": 587,
                    "smtp_security": "starttls",
                    "from_address": "itkflow@example.org",
                    "to_address": "ops@example.org",
                }
            }
        },
    )
    assert "smtp_username" not in normalised["notification_channels"]["mail"]
    assert "smtp_password" not in normalised["notification_channels"]["mail"]


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
        {"assembly_tool_slots": {}},
        {"assembly_tool_slots": ["not-an-object"]},
        {"assembly_tool_slots": [{"key": "top", "label": "Top", "extra": "nope"}]},
        {"assembly_tool_slots": [{"label": "Top"}]},
        {"assembly_tool_slots": [{"key": "   ", "label": "Top"}]},
        {"assembly_tool_slots": [{"key": "bad key!", "label": "Top"}]},
        {"assembly_tool_slots": [{"key": "a" * 33, "label": "Top"}]},
        {
            "assembly_tool_slots": [
                {"key": "top", "label": "Top"},
                {"key": "top", "label": "Top again"},
            ]
        },
        {"assembly_tool_slots": [{"key": "top"}]},
        {"assembly_tool_slots": [{"key": "top", "label": "x" * 61}]},
        {"assembly_tool_slots": [{"key": "top", "label": "Top", "kinds": "jig"}]},
        {"assembly_tool_slots": [{"key": "top", "label": "Top", "kinds": [42]}]},
        {"assembly_tool_slots": [{"key": "top", "label": "Top", "multiple": 1}]},
        {"assembly_tool_slots": [{"key": "top", "label": "Top", "multiple": "true"}]},
        {
            "assembly_tool_slots": [
                {"key": "top", "label": "Top", "property_key": "not valid!"}
            ]
        },
        {"assembly_tool_slots": [{"key": "top", "label": "Top", "property_key": "1_INVALID"}]},
        {"assembly_tool_slots": [{"key": "top", "label": "Top", "property_key": "A" * 65}]},
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


def test_normalizes_assembly_tool_slots_and_tolerates_snake_and_kebab_keys():
    """Each entry names one scannable tool role in a combined assembly step
    (e.g. the production sheet's separate top/bottom hybrid glue jig and
    pickup tool columns next to a single module jig). Keys double as JSON
    object keys in the ``tools`` payload, so both naming styles must survive.
    """

    patch = {
        "assembly_tool_slots": [
            {
                "key": " hybrid_glue_jig_top ",
                "label": " Hybrid glue jig, top ",
                "kinds": [" jig ", "JIG", "jig"],
                "multiple": True,
                "property_key": " jig_hybrid_alignment ",
            },
            {"key": "hybrid-pickup-bottom", "label": "Hybrid pickup, bottom"},
        ]
    }

    normalised = normalize_institute_settings_update({}, patch)

    assert normalised == {
        "assembly_tool_slots": [
            {
                "key": "hybrid_glue_jig_top",
                "label": "Hybrid glue jig, top",
                "kinds": ["jig", "JIG"],
                "multiple": True,
                "property_key": "JIG_HYBRID_ALIGNMENT",
            },
            {"key": "hybrid-pickup-bottom", "label": "Hybrid pickup, bottom"},
        ]
    }
    # The caller owns the original request object; normalisation is pure.
    assert patch["assembly_tool_slots"][0]["key"] == " hybrid_glue_jig_top "


def test_assembly_tool_slot_accepts_contract_boundaries():
    long_key = "k" * 32
    long_label = "l" * 60
    long_property_key = "P" * 64

    normalised = normalize_institute_settings_update(
        {},
        {
            "assembly_tool_slots": [
                {
                    "key": long_key,
                    "label": long_label,
                    "property_key": long_property_key,
                    "multiple": False,
                }
            ]
        },
    )

    assert normalised == {
        "assembly_tool_slots": [
            {
                "key": long_key,
                "label": long_label,
                "multiple": False,
                "property_key": long_property_key,
            }
        ]
    }


def test_assembly_tool_slots_defaults_are_absent_when_unconfigured():
    """No ``kinds``/``multiple``/``property_key`` in means none out; callers
    (app.assembly) must treat their absence as "single tool, no kind filter,
    no direct PDB property", matching today's implicit default slot."""

    normalised = normalize_institute_settings_update(
        {}, {"assembly_tool_slots": [{"key": "tool", "label": "Module jig"}]}
    )
    assert normalised == {"assembly_tool_slots": [{"key": "tool", "label": "Module jig"}]}


def test_assembly_tool_slots_reject_duplicate_property_keys():
    """Review M7: two slots writing the same PDB property would silently
    last-writer-win into the staged payload."""
    import pytest

    from app.institute_settings import (
        InstituteSettingsValidationError,
        normalize_institute_settings_update,
    )

    with pytest.raises(InstituteSettingsValidationError, match="property_key"):
        normalize_institute_settings_update(
            {},
            {
                "assembly_tool_slots": [
                    {"key": "a", "label": "A", "property_key": "JIG_HYBRID_ALIGNMENT"},
                    {"key": "b", "label": "B", "property_key": "JIG_HYBRID_ALIGNMENT"},
                ]
            },
        )
