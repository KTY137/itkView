# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-FileComment: itkflow-25d089cd529f
"""Glue-weight derivation: profile data in, verdict out (spec 2026-08-27 §9).

The numbers in these tests are the numbers from the owner's production sheet
and from the mirror of the real PDB, so the file doubles as documentation of
what the replaced spreadsheet actually computed:

  * TrueBlue module targets — R5M1 151 ± 22 mg, R2 164 ± 25 mg, R5M0 135 ± 20 mg
    with a 103 ± 16 mg powerboard, all read off the "Daten" tab.
  * The chain of scale readings, verified against 114 live GLUE_WEIGHT runs.
  * The sheet's own R2 bug (a total tolerance of 22 where 25 + 11 = 36) is
    deliberately not reproduced: totals are computed, never transcribed.

What is *not* tested here is any institute name, module type or result code
appearing in the derivation logic — every one of them arrives as profile data.
"""

import hashlib
import json
from datetime import datetime, timezone

import pytest
from authutil import create_institute_profile
from sqlalchemy import select

from app.domain.glue import (
    DEFAULT_GLUE_TARGET_RULES,
    DEFAULT_GLUE_WEIGHT_INPUTS,
    GlueTarget,
    GlueUnknownReason,
    GlueVerdict,
    derive_run,
    evaluate_glue_weight,
    glue_model_from_settings,
    glue_targets_from_settings,
    glue_weight_from_readings_mg,
    glue_weight_inputs_from_settings,
    select_glue_rule,
)
from app.glue_service import (
    derivation_payload,
    derive_for_component,
    derived_result_codes,
    derived_result_grams,
)
from app.institute_settings import (
    InstituteSettingsValidationError,
    normalize_institute_settings_update,
)
from app.models import Component, IngestFile, InstituteProfile, TestRunEvidence
from app.outbox_worker import revalidate_upload
from app.pdb_upload import build_upload_test_run_payload
from app.preview import build_component_preview

TEST_TYPE = "GLUE_WEIGHT"
SN = "20USE5L0000751"

# One complete hybrid + powerboard set of scale readings, in the grams the PDB
# stores: 9.3819 - 7.0162 - 2.2330 = 0.1327 g of glue under the hybrid.
READINGS = {
    "GW_MODULE_H1": 9.3819,
    "GW_SENSOR": 7.0162,
    "GW_HYBRID1": 2.2330,
    "GW_MODULE_H1PB": 12.7640,
    "GW_PB": 3.2860,
}

GLUE_WEIGHT_INPUT_SETTINGS = {
    "hybrids": {
        "label": "Hybrids",
        "test_type": TEST_TYPE,
        "measured": "GW_MODULE_H1",
        "subtract": ["GW_SENSOR", "GW_HYBRID1"],
        "result_code": "GW_GLUE_H1",
    },
    "powerboard": {
        "label": "Powerboard",
        "test_type": TEST_TYPE,
        "measured": "GW_MODULE_H1PB",
        "subtract": ["GW_MODULE_H1", "GW_PB"],
        "result_code": "GW_GLUE_PB",
    },
    "total": {
        "label": "Hybrids + powerboard",
        "test_type": TEST_TYPE,
        "measured": "GW_MODULE_H1PB",
        "subtract": ["GW_SENSOR", "GW_HYBRID1", "GW_PB"],
        "result_code": "GW_GLUE_H1PB",
    },
}

SHEET_MODULE_TARGETS = {
    "R0": {
        "hybrids": {"target_mg": 230, "tolerance_mg": 35},
        "powerboard": {"target_mg": 84, "tolerance_mg": 13},
        "total": {"target_mg": 314, "tolerance_mg": 48},
    },
    "R1": {
        "hybrids": {"target_mg": 311, "tolerance_mg": 46},
        "powerboard": {"target_mg": 84, "tolerance_mg": 13},
        "total": {"target_mg": 395, "tolerance_mg": 59},
    },
    "R2": {
        "hybrids": {"target_mg": 164, "tolerance_mg": 25},
        "powerboard": {"target_mg": 70, "tolerance_mg": 11},
        "total": {"target_mg": 234, "tolerance_mg": 36},
    },
    "R3M0": {
        "hybrids": {"target_mg": 198, "tolerance_mg": 30},
        "powerboard": {"target_mg": 157, "tolerance_mg": 23},
        "total": {"target_mg": 355, "tolerance_mg": 53},
    },
    "R3M1": {"hybrids": {"target_mg": 231, "tolerance_mg": 35}},
    "R5M0": {
        "hybrids": {"target_mg": 135, "tolerance_mg": 20},
        "powerboard": {"target_mg": 103, "tolerance_mg": 16},
        "total": {"target_mg": 238, "tolerance_mg": 36},
    },
    "R5M0_HALFMODULE": {
        "hybrids": {"target_mg": 135, "tolerance_mg": 20},
        "powerboard": {"target_mg": 103, "tolerance_mg": 16},
        "total": {"target_mg": 238, "tolerance_mg": 36},
    },
    "R5M1": {"hybrids": {"target_mg": 151, "tolerance_mg": 22}},
    "R5M1_HALFMODULE": {
        "hybrids": {"target_mg": 151, "tolerance_mg": 22}
    },
}

SHEET_GLUE_SETTINGS = {
    "glue_targets": [
        {
            "process": "TRUEBLUE",
            "label": "True Blue / False Blue",
            "valid_from": None,
            "module_types": SHEET_MODULE_TARGETS,
        }
    ],
    "glue_weight_inputs": GLUE_WEIGHT_INPUT_SETTINGS,
    "glue_default_process": "TRUEBLUE",
}

TYPE_SPECIFIC_GLUE_SETTINGS = {
    **SHEET_GLUE_SETTINGS,
    "glue_weight_inputs": {
        **GLUE_WEIGHT_INPUT_SETTINGS,
        "hybrids": {
            **GLUE_WEIGHT_INPUT_SETTINGS["hybrids"],
            "by_type_code": {
                "R2": {
                    "measured": "GW_MODULE_H1H2",
                    "subtract": ["GW_SENSOR", "GW_HYBRID1", "GW_HYBRID2"],
                    "result_code": "GW_GLUE_H1H2",
                }
            },
        },
        "powerboard": {
            **GLUE_WEIGHT_INPUT_SETTINGS["powerboard"],
            "by_type_code": {
                "R2": {
                    "measured": "GW_MODULE_H1H2PB",
                    "subtract": ["GW_MODULE_H1H2", "GW_PB"],
                    "result_code": "GW_GLUE_PB",
                }
            },
        },
        "total": {
            **GLUE_WEIGHT_INPUT_SETTINGS["total"],
            "by_type_code": {
                "R2": {
                    "measured": "GW_MODULE_H1H2PB",
                    "subtract": ["GW_SENSOR", "GW_HYBRID1", "GW_HYBRID2", "GW_PB"],
                    "result_code": "GW_GLUE_H1H2PB",
                }
            },
        },
    },
}

H1H2_READINGS = {
    "GW_MODULE_H1H2": 12.1185,
    "GW_MODULE_H1H2PB": 15.2185,
    "GW_SENSOR": 9.7522,
    "GW_HYBRID1": 2.0,
    "GW_HYBRID2": 0.2330,
    "GW_PB": 3.0,
}


def _steps(derivation):
    return {step.key: step for step in derivation.steps}


def _derive(settings, *, type_code, results=READINGS, measured_at=None):
    return derive_run(
        glue_model_from_settings(settings),
        test_type=TEST_TYPE,
        type_code=type_code,
        results=results,
        measured_at=measured_at,
    )


# --- reference seeds and explicit profile configuration -------------------


@pytest.mark.parametrize(
    ("type_code", "target_mg", "tolerance_mg"),
    [
        ("R5M1", 151, 22),
        ("R5M1_HALFMODULE", 151, 22),
        ("R2", 164, 25),
        ("R5M0", 135, 20),
        ("R5M0_HALFMODULE", 135, 20),
    ],
)
def test_reference_seeds_preserve_the_sheets_hybrid_targets(
    type_code, target_mg, tolerance_mg
):
    step = DEFAULT_GLUE_TARGET_RULES[0].target_for(type_code, "hybrids")
    assert step == GlueTarget(target_mg=target_mg, tolerance_mg=tolerance_mg)


def test_explicit_profile_judges_a_real_r5m1_set():
    step = _steps(_derive(SHEET_GLUE_SETTINGS, type_code="R5M1_HALFMODULE"))["hybrids"]
    assert step.measured_mg == pytest.approx(132.7)
    # 132.7 mg against 151 ± 22 -> below the 129 mg floor? No: 129 <= 132.7.
    assert step.verdict is GlueVerdict.OK
    assert step.reason is None


def test_the_same_reading_fails_a_type_with_a_higher_target():
    """R2 wants 164 ± 25 mg, so 132.7 mg is too little — same numbers, other type."""
    assert (
        _steps(_derive(SHEET_GLUE_SETTINGS, type_code="R2"))["hybrids"].verdict
        is GlueVerdict.TOO_LITTLE
    )


def test_powerboard_target_and_verdict_come_from_the_profile():
    step = _steps(_derive(SHEET_GLUE_SETTINGS, type_code="R5M0_HALFMODULE"))[
        "powerboard"
    ]
    # 12.7640 - 9.3819 - 3.2860 = 0.0961 g against 103 ± 16 mg.
    assert step.measured_mg == pytest.approx(96.1)
    assert step.target == GlueTarget(target_mg=103, tolerance_mg=16)
    assert step.verdict is GlueVerdict.OK


def test_a_half_module_has_no_powerboard_step_at_all():
    """The profile knows R5M1 and gives it no powerboard entry: the step is dropped.

    That is a positive statement ("this type is not glued to a powerboard"),
    unlike an unknown module type, which keeps its steps and reports no_target.
    """
    assert "powerboard" not in _steps(
        _derive(SHEET_GLUE_SETTINGS, type_code="R5M1_HALFMODULE")
    )
    assert "powerboard" in _steps(
        _derive(SHEET_GLUE_SETTINGS, type_code="R5M0_HALFMODULE")
    )


def test_totals_are_never_transcribed_from_the_sheet():
    """The sheet's R2 row states a total tolerance of 22 where 25 + 11 = 36.

    The profile carries the recomputed sum, never the mistyped sheet cell.
    """
    steps = _steps(_derive(SHEET_GLUE_SETTINGS, type_code="R2"))
    assert steps["total"].target == GlueTarget(234, 36)
    assert steps["total"].target.tolerance_mg != 22


# --- a profile override ----------------------------------------------------


def _override(module_types, *, valid_from=None, process="TRUEBLUE"):
    return {
        "glue_targets": [
            {
                "process": process,
                "label": "Custom",
                "valid_from": valid_from,
                "module_types": module_types,
            }
        ],
        "glue_weight_inputs": GLUE_WEIGHT_INPUT_SETTINGS,
        "glue_default_process": process,
    }


def test_profile_targets_drive_the_verdict():
    settings = _override({"R5M1_HALFMODULE": {"hybrids": {"target_mg": 90, "tolerance_mg": 5}}})
    step = _steps(_derive(settings, type_code="R5M1_HALFMODULE"))["hybrids"]
    assert step.target == GlueTarget(target_mg=90, tolerance_mg=5)
    assert step.verdict is GlueVerdict.TOO_MUCH  # 132.7 mg against 90 ± 5


def test_profile_inputs_override_which_readings_are_weighed():
    """An institute gluing two hybrids in one step weighs a different chain."""
    settings = {
        "glue_targets": SHEET_GLUE_SETTINGS["glue_targets"],
        "glue_weight_inputs": {
            "hybrids": {
                "measured": "GW_MODULE_H1H2",
                "subtract": ["GW_SENSOR", "GW_HYBRID1", "GW_HYBRID2"],
                "result_code": "GW_GLUE_H1H2",
            }
        },
        "glue_default_process": "TRUEBLUE",
    }
    readings = {
        "GW_MODULE_H1H2": 12.1185,
        "GW_SENSOR": 9.7522,
        "GW_HYBRID1": 2.0,
        "GW_HYBRID2": 0.2330,
    }
    derivation = _derive(settings, type_code="R2", results=readings)
    step = _steps(derivation)["hybrids"]
    assert [item.code for item in step.inputs] == [
        "GW_MODULE_H1H2",
        "GW_SENSOR",
        "GW_HYBRID1",
        "GW_HYBRID2",
    ]
    assert step.measured_mg == pytest.approx(133.3)
    assert step.result_code == "GW_GLUE_H1H2"
    # The seeded second step is gone: the profile replaced the whole map.
    assert set(_steps(derivation)) == {"hybrids"}


def test_exact_type_code_selects_the_configured_formula_override():
    step = _steps(
        _derive(
            TYPE_SPECIFIC_GLUE_SETTINGS,
            type_code="R2",
            results=H1H2_READINGS,
        )
    )["hybrids"]
    assert [item.code for item in step.inputs] == [
        "GW_MODULE_H1H2",
        "GW_SENSOR",
        "GW_HYBRID1",
        "GW_HYBRID2",
    ]
    assert step.measured_mg == pytest.approx(133.3)
    assert step.result_code == "GW_GLUE_H1H2"


def test_two_hybrid_override_uploads_individual_and_combined_glue_results():
    derivation = _derive(
        TYPE_SPECIFIC_GLUE_SETTINGS,
        type_code="R2",
        results=H1H2_READINGS,
    )

    assert derived_result_grams(derivation) == {
        "GW_GLUE_H1H2": pytest.approx(0.1333),
        "GW_GLUE_PB": pytest.approx(0.1),
        "GW_GLUE_H1H2PB": pytest.approx(0.2333),
    }


@pytest.mark.parametrize("type_code", ["R5M1_HALFMODULE", "r2", None])
def test_unmatched_or_missing_type_code_uses_the_base_formula(type_code):
    step = _steps(
        _derive(TYPE_SPECIFIC_GLUE_SETTINGS, type_code=type_code, results=READINGS)
    )["hybrids"]
    assert [item.code for item in step.inputs] == [
        "GW_MODULE_H1",
        "GW_SENSOR",
        "GW_HYBRID1",
    ]
    assert step.measured_mg == pytest.approx(132.7)
    assert step.result_code == "GW_GLUE_H1"


def test_populated_h1h2_fields_alone_do_not_select_an_override():
    step = _steps(
        _derive(
            TYPE_SPECIFIC_GLUE_SETTINGS,
            type_code="R5M1_HALFMODULE",
            results=H1H2_READINGS,
        )
    )["hybrids"]
    assert [item.code for item in step.inputs] == [
        "GW_MODULE_H1",
        "GW_SENSOR",
        "GW_HYBRID1",
    ]
    assert step.measured_mg is None
    assert step.reason is GlueUnknownReason.MISSING_INPUTS


def test_absent_null_or_malformed_profile_settings_fail_closed():
    """Bad or missing profile data must not activate another site's constants."""
    assert glue_targets_from_settings(None) == ()
    assert glue_targets_from_settings({"glue_targets": None}) == ()
    assert glue_targets_from_settings({"glue_targets": "nonsense"}) == ()
    assert glue_targets_from_settings({"glue_targets": [{"no": "process"}]}) == ()
    assert glue_targets_from_settings(
        {
            "glue_targets": [
                {
                    "process": "TRUEBLUE",
                    "valid_from": "not-a-date",
                    "module_types": SHEET_MODULE_TARGETS,
                }
            ]
        }
    ) == ()
    assert glue_targets_from_settings(
        {
            "glue_targets": [
                SHEET_GLUE_SETTINGS["glue_targets"][0],
                {"process": "BROKEN"},
            ]
        }
    ) == ()
    assert glue_weight_inputs_from_settings(None) == ()
    assert glue_weight_inputs_from_settings({"glue_weight_inputs": None}) == ()
    assert glue_weight_inputs_from_settings({"glue_weight_inputs": []}) == ()
    assert glue_weight_inputs_from_settings(
        {
            "glue_weight_inputs": {
                **GLUE_WEIGHT_INPUT_SETTINGS,
                "broken": {"measured": "GW_A", "subtract": "GW_B"},
            }
        }
    ) == ()
    malformed_override = {
        **SHEET_GLUE_SETTINGS,
        "glue_weight_inputs": {
            **GLUE_WEIGHT_INPUT_SETTINGS,
            "hybrids": {
                **GLUE_WEIGHT_INPUT_SETTINGS["hybrids"],
                "by_type_code": {"R2": {"subtract": "GW_SENSOR"}},
            },
        },
    }
    assert glue_weight_inputs_from_settings(malformed_override) == ()
    assert not glue_model_from_settings(malformed_override).derives(TEST_TYPE)
    null_override_map = {
        **SHEET_GLUE_SETTINGS,
        "glue_weight_inputs": {
            "hybrids": {
                **GLUE_WEIGHT_INPUT_SETTINGS["hybrids"],
                "by_type_code": None,
            }
        },
    }
    assert glue_weight_inputs_from_settings(null_override_map) == ()
    assert derive_run(
        glue_model_from_settings(None),
        test_type=TEST_TYPE,
        type_code="R2",
        results=READINGS,
    ) is None


def test_reference_input_seeds_remain_available_without_being_runtime_defaults():
    assert [spec.key for spec in DEFAULT_GLUE_WEIGHT_INPUTS] == [
        "hybrids",
        "powerboard",
        "total",
    ]


@pytest.mark.parametrize(
    "settings",
    [
        {"glue_targets": SHEET_GLUE_SETTINGS["glue_targets"]},
        {"glue_weight_inputs": GLUE_WEIGHT_INPUT_SETTINGS},
    ],
)
def test_a_half_configured_profile_derives_nothing(settings):
    assert not glue_model_from_settings(settings).derives(TEST_TYPE)


# --- validity periods ------------------------------------------------------

BOUNDARY = "2023-10-24"
GENERATIONS = {
    "glue_targets": [
        {
            "process": "TRUEBLUE",
            "label": "First generation",
            "valid_from": None,
            "module_types": {"R2": {"hybrids": {"target_mg": 164, "tolerance_mg": 25}}},
        },
        {
            "process": "TRUEBLUE",
            "label": "Second generation",
            "valid_from": BOUNDARY,
            "module_types": {"R2": {"hybrids": {"target_mg": 180, "tolerance_mg": 18}}},
        },
    ],
    "glue_weight_inputs": GLUE_WEIGHT_INPUT_SETTINGS,
    "glue_default_process": "TRUEBLUE",
}


def _target_at(moment):
    return _steps(_derive(GENERATIONS, type_code="R2", measured_at=moment))["hybrids"].target


def test_a_run_before_the_boundary_is_judged_by_the_older_rule():
    assert _target_at(datetime(2023, 10, 23, 23, 59, tzinfo=timezone.utc)) == GlueTarget(164, 25)


def test_a_run_on_or_after_the_boundary_is_judged_by_the_newer_rule():
    assert _target_at(datetime(2023, 10, 24, 0, 0, tzinfo=timezone.utc)) == GlueTarget(180, 18)
    assert _target_at(datetime(2026, 1, 1, tzinfo=timezone.utc)) == GlueTarget(180, 18)


def test_a_naive_timestamp_is_read_as_utc_not_rejected():
    """SQLite hands back naive datetimes; the boundary must still hold."""
    assert _target_at(datetime(2023, 10, 23, 23, 59)) == GlueTarget(164, 25)
    assert _target_at(datetime(2023, 10, 24, 0, 1)) == GlueTarget(180, 18)


def test_an_undated_run_uses_only_the_always_valid_fallback():
    assert _target_at(None) == GlueTarget(164, 25)


def test_an_undated_run_never_selects_a_dated_rule_without_a_fallback():
    dated_only = glue_targets_from_settings(
        {
            "glue_targets": [
                {
                    "process": "TRUEBLUE",
                    "valid_from": BOUNDARY,
                    "module_types": SHEET_MODULE_TARGETS,
                }
            ]
        }
    )
    assert select_glue_rule(dated_only, process="TRUEBLUE", at=None) is None


def test_a_process_without_any_rule_selects_nothing():
    rules = glue_targets_from_settings(GENERATIONS)
    assert select_glue_rule(rules, process="POLARIS", at=None) is None
    assert select_glue_rule(rules, process=None, at=None) is None


# --- every unknown reason --------------------------------------------------


def test_unknown_no_run_when_nothing_has_been_measured():
    derivation = derive_run(
        glue_model_from_settings(SHEET_GLUE_SETTINGS),
        test_type=TEST_TYPE,
        type_code="R2",
        results=None,
    )
    step = _steps(derivation)["hybrids"]
    assert step.verdict is GlueVerdict.UNKNOWN
    assert step.reason is GlueUnknownReason.NO_RUN
    assert step.measured_mg is None
    # The target is still stated: it is what the next measurement must hit.
    assert step.target == GlueTarget(164, 25)
    assert [item.value for item in step.inputs] == [None, None, None]


def test_unknown_missing_inputs_never_becomes_arithmetic_on_a_blank():
    """A blank reading is exactly how the sheet produced -9010 mg verdicts."""
    readings = dict(READINGS)
    readings["GW_SENSOR"] = None
    step = _steps(_derive(SHEET_GLUE_SETTINGS, type_code="R2", results=readings))[
        "hybrids"
    ]
    assert step.verdict is GlueVerdict.UNKNOWN
    assert step.reason is GlueUnknownReason.MISSING_INPUTS
    assert step.measured_mg is None
    assert [item.value for item in step.inputs] == [9.3819, None, 2.2330]


def test_a_non_numeric_reading_counts_as_missing_not_as_zero():
    readings = dict(READINGS, GW_HYBRID1="2,2330")
    step = _steps(_derive(SHEET_GLUE_SETTINGS, type_code="R2", results=readings))[
        "hybrids"
    ]
    assert step.reason is GlueUnknownReason.MISSING_INPUTS


def test_unknown_no_target_for_a_module_type_the_profile_never_heard_of():
    step = _steps(_derive(SHEET_GLUE_SETTINGS, type_code="R7M9"))["hybrids"]
    assert step.verdict is GlueVerdict.UNKNOWN
    assert step.reason is GlueUnknownReason.NO_TARGET
    assert step.target is None
    # The arithmetic still happened — only the judgement is missing.
    assert step.measured_mg == pytest.approx(132.7)


def test_unknown_no_target_when_the_process_cannot_be_established():
    """Two processes, no default: the derivation says so instead of guessing."""
    settings = {
        "glue_targets": [
            {
                "process": "TRUEBLUE",
                "valid_from": None,
                "module_types": {"R2": {"hybrids": {"target_mg": 164, "tolerance_mg": 25}}},
            },
            {
                "process": "POLARIS",
                "valid_from": None,
                "module_types": {"R2": {"hybrids": {"target_mg": 155, "tolerance_mg": 23}}},
            },
        ],
        "glue_weight_inputs": GLUE_WEIGHT_INPUT_SETTINGS,
    }
    derivation = _derive(settings, type_code="R2")
    assert derivation.process is None
    assert derivation.process_source == "unknown"
    assert _steps(derivation)["hybrids"].reason is GlueUnknownReason.NO_TARGET


def test_a_run_that_names_its_process_beats_the_profile_default():
    settings = {
        "glue_process_property": "GW_PROCESS",
        "glue_targets": [
            {
                "process": "TRUEBLUE",
                "valid_from": None,
                "module_types": {"R2": {"hybrids": {"target_mg": 164, "tolerance_mg": 25}}},
            },
            {
                "process": "POLARIS",
                "valid_from": None,
                "module_types": {"R2": {"hybrids": {"target_mg": 100, "tolerance_mg": 9}}},
            },
        ],
        "glue_default_process": "TRUEBLUE",
        "glue_weight_inputs": GLUE_WEIGHT_INPUT_SETTINGS,
    }
    model = glue_model_from_settings(settings)
    derivation = derive_run(
        model,
        test_type=TEST_TYPE,
        type_code="R2",
        results=READINGS,
        # Free text in the wild: the owner's mirror spells one such property
        # four different ways, so it is matched case-insensitively.
        properties={"GW_PROCESS": " polaris "},
    )
    assert derivation.process == "POLARIS"
    assert derivation.process_source == "run"
    assert _steps(derivation)["hybrids"].target == GlueTarget(100, 9)


def test_a_single_configured_process_is_not_an_implicit_default():
    settings = dict(SHEET_GLUE_SETTINGS)
    settings.pop("glue_default_process")
    derivation = _derive(settings, type_code="R2")
    assert derivation.process is None
    assert derivation.process_source == "unknown"
    assert _steps(derivation)["hybrids"].reason is GlueUnknownReason.NO_TARGET


def test_an_unknown_run_process_is_not_replaced_by_the_profile_default():
    settings = dict(
        SHEET_GLUE_SETTINGS,
        glue_process_property="GW_PROCESS",
    )
    derivation = derive_run(
        glue_model_from_settings(settings),
        test_type=TEST_TYPE,
        type_code="R2",
        results=READINGS,
        properties={"GW_PROCESS": "POLARIS"},
    )
    assert derivation.process is None
    assert derivation.process_source == "unknown"
    assert _steps(derivation)["hybrids"].reason is GlueUnknownReason.NO_TARGET


def test_an_unknown_profile_default_fails_closed():
    settings = dict(SHEET_GLUE_SETTINGS, glue_default_process="POLARIS")
    derivation = _derive(settings, type_code="R2")
    assert derivation.process is None
    assert derivation.process_source == "unknown"
    assert _steps(derivation)["hybrids"].reason is GlueUnknownReason.NO_TARGET


def test_legacy_default_key_is_read_but_the_canonical_key_wins():
    legacy = dict(SHEET_GLUE_SETTINGS)
    legacy.pop("glue_default_process")
    legacy["glue_process_default"] = "TRUEBLUE"
    assert _derive(legacy, type_code="R2").process == "TRUEBLUE"

    both = dict(legacy, glue_default_process="POLARIS")
    assert _derive(both, type_code="R2").process is None


def test_no_derivation_at_all_for_a_test_type_the_profile_does_not_cover():
    assert (
        derive_run(
            glue_model_from_settings(SHEET_GLUE_SETTINGS),
            test_type="MODULE_BOW",
            type_code="R2",
            results=READINGS,
        )
        is None
    )


# --- grams and milligrams --------------------------------------------------


def test_the_pure_formula_converts_grams_to_milligrams_once():
    assert glue_weight_from_readings_mg(9.3819, (7.0162, 2.2330)) == pytest.approx(132.7)
    assert glue_weight_from_readings_mg(0.5, ()) == pytest.approx(500.0)


@pytest.mark.parametrize(
    ("module_weight", "verdict"),
    [
        (2.11496, GlueVerdict.TOO_LITTLE),
        (2.15504, GlueVerdict.TOO_MUCH),
    ],
)
def test_verdict_uses_the_unrounded_sheet_value_at_tolerance_boundaries(
    module_weight, verdict
):
    readings = {**READINGS, "GW_SENSOR": 1.0, "GW_HYBRID1": 1.0}
    readings["GW_MODULE_H1"] = module_weight

    hybrids = _steps(
        _derive(SHEET_GLUE_SETTINGS, type_code="R5M0_HALFMODULE", results=readings)
    )["hybrids"]

    assert hybrids.measured_mg in (115.0, 155.0)
    assert hybrids.verdict is verdict


def test_algebraically_equivalent_powerboard_chain_stays_on_inclusive_boundary():
    # R2 powerboard lower bound is 70 - 11 = 59 mg. The live sheet's expanded
    # formula and the backend's cancelled formula have different float
    # subtraction order, but both describe this exact decimal scale result.
    readings = {
        **READINGS,
        "GW_MODULE_H1": 10.8343,
        "GW_PB": 3.0526,
        "GW_MODULE_H1PB": 13.9459,
    }

    powerboard = _steps(
        _derive(SHEET_GLUE_SETTINGS, type_code="R2", results=readings)
    )["powerboard"]

    assert powerboard.measured_mg == 59.0
    assert powerboard.verdict is GlueVerdict.OK


def test_decimal_profile_target_keeps_its_inclusive_boundary():
    assert evaluate_glue_weight(100.1, GlueTarget(100.4, 0.3)) is GlueVerdict.OK


@pytest.mark.parametrize(
    "invalid",
    [float("nan"), float("inf"), pytest.param(10**10000, id="huge-int")],
)
def test_non_finite_or_unrepresentable_scale_readings_are_missing_inputs(invalid):
    readings = {**READINGS, "GW_MODULE_H1": invalid}

    hybrids = _steps(
        _derive(SHEET_GLUE_SETTINGS, type_code="R5M0_HALFMODULE", results=readings)
    )["hybrids"]

    assert hybrids.measured_mg is None
    assert hybrids.verdict is GlueVerdict.UNKNOWN
    assert hybrids.reason is GlueUnknownReason.MISSING_INPUTS


def test_finite_scale_readings_whose_arithmetic_overflows_are_missing_inputs():
    readings = {
        **READINGS,
        "GW_MODULE_H1": 1e308,
        "GW_SENSOR": -1e308,
        "GW_HYBRID1": 0.0,
    }

    hybrids = _steps(
        _derive(SHEET_GLUE_SETTINGS, type_code="R5M0_HALFMODULE", results=readings)
    )["hybrids"]

    assert hybrids.measured_mg is None
    assert hybrids.verdict is GlueVerdict.UNKNOWN
    assert hybrids.reason is GlueUnknownReason.MISSING_INPUTS


def test_derived_values_are_milligrams_and_uploads_are_grams():
    """The PDB declares every GW_ code in grams; targets are stated in mg.

    Both units appear, and each exactly once: the wire payload the page renders
    is milligrams, the value that would be uploaded is grams.
    """
    derivation = _derive(SHEET_GLUE_SETTINGS, type_code="R5M0_HALFMODULE")
    payload = derivation_payload(derivation)
    hybrids = next(step for step in payload["steps"] if step["key"] == "hybrids")
    assert hybrids["measured_mg"] == pytest.approx(132.7)
    assert hybrids["target_mg"] == 135
    assert derived_result_grams(derivation) == {
        "GW_GLUE_H1": pytest.approx(0.1327),
        "GW_GLUE_PB": pytest.approx(0.0961),
        "GW_GLUE_H1PB": pytest.approx(0.2288),
    }
    assert derived_result_codes(derivation) == [
        "GW_GLUE_H1",
        "GW_GLUE_PB",
        "GW_GLUE_H1PB",
    ]


def test_an_unmeasurable_step_contributes_no_uploaded_value():
    """An upload must never carry a fabricated zero for a reading nobody took."""
    readings = dict(READINGS)
    readings["GW_PB"] = None
    grams = derived_result_grams(
        _derive(SHEET_GLUE_SETTINGS, type_code="R5M0_HALFMODULE", results=readings)
    )
    assert grams == {"GW_GLUE_H1": pytest.approx(0.1327)}


def test_the_wire_payload_matches_the_contract():
    payload = derivation_payload(
        _derive(SHEET_GLUE_SETTINGS, type_code="R5M0_HALFMODULE")
    )
    assert payload["kind"] == "glue_weight"
    assert payload["process"] == "TRUEBLUE"
    assert payload["process_source"] == "profile_default"
    step = payload["steps"][0]
    assert set(step) == {
        "key",
        "label",
        "measured_mg",
        "target_mg",
        "tolerance_mg",
        "verdict",
        "reason",
        "result_code",
        "inputs",
    }
    assert set(step["inputs"][0]) == {"code", "name", "value"}
    assert step["verdict"] == "ok"
    assert step["reason"] is None
    assert derivation_payload(None) is None


# --- settings validation ---------------------------------------------------


def test_valid_glue_settings_are_normalised():
    out = normalize_institute_settings_update(
        {},
        {
            "glue_targets": [
                {
                    "process": "trueblue",
                    "label": "True Blue / False Blue",
                    "valid_from": "2023-10-24",
                    "module_types": {"r2": {"hybrids": {"target_mg": 164, "tolerance_mg": 25}}},
                }
            ],
            "glue_weight_inputs": {
                "hybrids": {
                    "measured": "gw_module_h1",
                    "subtract": ["gw_sensor", "gw_hybrid1"],
                    "result_code": "gw_glue_h1",
                    "by_type_code": {
                        "r2": {
                            "measured": "gw_module_h1h2",
                            "subtract": [
                                "gw_sensor",
                                "gw_hybrid1",
                                "gw_hybrid2",
                            ],
                            "result_code": "gw_glue_h1h2",
                        }
                    },
                }
            },
            "glue_default_process": "trueblue",
            "glue_process_property": "gw_process",
        },
    )
    rule = out["glue_targets"][0]
    assert rule["process"] == "TRUEBLUE"
    assert rule["valid_from"] == "2023-10-24T00:00:00+00:00"
    assert rule["module_types"] == {"R2": {"hybrids": {"target_mg": 164.0, "tolerance_mg": 25.0}}}
    assert out["glue_weight_inputs"]["hybrids"]["measured"] == "GW_MODULE_H1"
    assert out["glue_weight_inputs"]["hybrids"]["subtract"] == ["GW_SENSOR", "GW_HYBRID1"]
    assert out["glue_weight_inputs"]["hybrids"]["by_type_code"] == {
        "R2": {
            "measured": "GW_MODULE_H1H2",
            "subtract": ["GW_SENSOR", "GW_HYBRID1", "GW_HYBRID2"],
            "result_code": "GW_GLUE_H1H2",
        }
    }
    assert out["glue_default_process"] == "TRUEBLUE"
    assert out["glue_process_property"] == "GW_PROCESS"


def test_legacy_default_key_is_accepted_but_only_the_canonical_key_is_written():
    existing = {
        "glue_targets": [
            {"process": "TRUEBLUE", "valid_from": None, "module_types": {}}
        ]
    }
    out = normalize_institute_settings_update(
        existing, {"glue_process_default": "trueblue"}
    )
    assert out == {"glue_default_process": "TRUEBLUE"}

    canonical_wins = normalize_institute_settings_update(
        existing,
        {
            "glue_process_default": "POLARIS",
            "glue_default_process": "TRUEBLUE",
        },
    )
    assert canonical_wins == {"glue_default_process": "TRUEBLUE"}


def test_default_process_must_match_the_effective_target_processes():
    targets = [
        {"process": "TRUEBLUE", "valid_from": None, "module_types": {}}
    ]

    assert normalize_institute_settings_update(
        {"glue_targets": targets}, {"glue_default_process": "trueblue"}
    ) == {"glue_default_process": "TRUEBLUE"}

    with pytest.raises(
        InstituteSettingsValidationError,
        match="must match a process configured in glue_targets",
    ):
        normalize_institute_settings_update(
            {"glue_targets": targets}, {"glue_default_process": "POLARIS"}
        )

    with pytest.raises(
        InstituteSettingsValidationError,
        match="must match a process configured in glue_targets",
    ):
        normalize_institute_settings_update(
            {
                "glue_targets": targets,
                "glue_default_process": "TRUEBLUE",
            },
            {
                "glue_targets": [
                    {"process": "POLARIS", "valid_from": None, "module_types": {}}
                ]
            },
        )


def test_partial_type_override_is_normalised_against_the_base_formula():
    out = normalize_institute_settings_update(
        {},
        {
            "glue_weight_inputs": {
                "hybrids": {
                    "measured": "GW_A",
                    "subtract": ["GW_B"],
                    "result_code": "GW_RESULT",
                    "by_type_code": {
                        "r2": {"measured": "GW_C"},
                        "r5m0": {"result_code": None},
                    },
                }
            }
        },
    )
    assert out["glue_weight_inputs"]["hybrids"]["by_type_code"]["R2"] == {
        "measured": "GW_C",
        "subtract": ["GW_B"],
        "result_code": "GW_RESULT",
    }
    assert out["glue_weight_inputs"]["hybrids"]["by_type_code"]["R5M0"] == {
        "measured": "GW_A",
        "subtract": ["GW_B"],
        "result_code": None,
    }


def test_null_disables_glue_derivation_without_a_runtime_fallback():
    out = normalize_institute_settings_update(
        {}, {"glue_targets": None, "glue_weight_inputs": None}
    )
    assert out == {"glue_targets": None, "glue_weight_inputs": None}
    assert glue_targets_from_settings(out) == ()
    assert glue_weight_inputs_from_settings(out) == ()
    assert not glue_model_from_settings(out).derives(TEST_TYPE)


@pytest.mark.parametrize(
    "patch",
    [
        {"glue_targets": {}},
        {"glue_targets": []},
        {"glue_targets": [{"process": "TRUEBLUE", "unknown_field": 1}]},
        {"glue_targets": [{"process": "true blue"}]},
        {"glue_targets": [{"process": "TRUEBLUE", "valid_from": "not-a-date"}]},
        {
            "glue_targets": [
                {"process": "TB", "module_types": {"R2": {"hybrids": {"target_mg": -1}}}}
            ]
        },
        {
            "glue_targets": [
                {
                    "process": "TB",
                    "module_types": {"R2": {"hybrids": {"target_mg": 1, "tolerance_mg": "x"}}},
                }
            ]
        },
        # Two rule sets for the same process on the same day: which one wins
        # would depend on dict order, so it is rejected outright.
        {
            "glue_targets": [
                {"process": "TB", "valid_from": None},
                {"process": "TB", "valid_from": None},
            ]
        },
        {"glue_weight_inputs": []},
        {"glue_weight_inputs": {"hybrids": {"subtract": ["GW_SENSOR"]}}},
        {"glue_weight_inputs": {"hybrids": {"measured": "GW_A", "subtract": "GW_B"}}},
        {"glue_weight_inputs": {"hybrids": {"measured": "GW_A", "subtract": ["GW_A"]}}},
        {
            "glue_weight_inputs": {
                "hybrids": {"measured": "GW_A", "subtract": ["GW_B", "GW_B"]}
            }
        },
        # A result written back over one of its own inputs would make the next
        # derivation read its own output.
        {
            "glue_weight_inputs": {
                "hybrids": {"measured": "GW_A", "subtract": ["GW_B"], "result_code": "GW_B"}
            }
        },
        # A result from one step must not overwrite a raw input consumed by a
        # different step in the same test run.
        {
            "glue_weight_inputs": {
                "hybrids": {"measured": "GW_A", "result_code": "GW_PB"},
                "powerboard": {
                    "measured": "GW_AFTER_PB",
                    "subtract": ["GW_A", "GW_PB"],
                    "result_code": "GW_GLUE_PB",
                },
            }
        },
        {
            "glue_weight_inputs": {
                "hybrids": {"measured": "GW_A", "by_type_code": []}
            }
        },
        {
            "glue_weight_inputs": {
                "hybrids": {
                    "measured": "GW_A",
                    "by_type_code": {"bad type": {}},
                }
            }
        },
        {
            "glue_weight_inputs": {
                "hybrids": {
                    "measured": "GW_A",
                    "by_type_code": {"r2": {}, "R2": {}},
                }
            }
        },
        {
            "glue_weight_inputs": {
                "hybrids": {
                    "measured": "GW_A",
                    "by_type_code": {"R2": {"label": "Not allowed"}},
                }
            }
        },
        {
            "glue_weight_inputs": {
                "hybrids": {
                    "measured": "GW_A",
                    "by_type_code": {
                        "R2": {"measured": "GW_B", "subtract": ["GW_B"]}
                    },
                }
            }
        },
        {
            "glue_weight_inputs": {
                "hybrids": {
                    "measured": "GW_A",
                    "by_type_code": {
                        "R2": {"subtract": ["GW_B", "GW_B"]}
                    },
                }
            }
        },
        {
            "glue_weight_inputs": {
                "hybrids": {
                    "measured": "GW_A",
                    "by_type_code": {
                        "R2": {"subtract": ["GW_B"], "result_code": "GW_B"}
                    },
                }
            }
        },
        {
            "glue_weight_inputs": {
                "first": {"measured": "GW_A", "result_code": "GW_SAME"},
                "second": {"measured": "GW_B", "result_code": "GW_SAME"},
            }
        },
        {
            "glue_weight_inputs": {
                "first": {
                    "measured": "GW_A",
                    "result_code": "GW_FIRST",
                    "by_type_code": {"R2": {"result_code": "GW_SAME"}},
                },
                "second": {
                    "measured": "GW_B",
                    "result_code": "GW_SECOND",
                    "by_type_code": {"R2": {"result_code": "GW_SAME"}},
                },
            }
        },
        {"glue_weight_inputs": {"hybrids": {"measured": "GW_A", "test_type": "lower case"}}},
        {"glue_default_process": "true blue"},
        {"glue_process_default": "true blue"},
        {"glue_process_property": "not a code"},
    ],
)
def test_invalid_glue_settings_are_rejected(patch):
    with pytest.raises(InstituteSettingsValidationError):
        normalize_institute_settings_update({}, patch)


def test_legacy_duplicate_result_codes_disable_derivation_instead_of_overwriting():
    settings = {
        "glue_weight_inputs": {
            "first": {"measured": "GW_A", "result_code": "GW_SAME"},
            "second": {"measured": "GW_B", "result_code": "GW_SAME"},
        }
    }

    assert glue_weight_inputs_from_settings(settings) == ()


def test_legacy_output_input_collision_disables_derivation_instead_of_overwriting():
    settings = {
        "glue_weight_inputs": {
            "hybrids": {"measured": "GW_A", "result_code": "GW_PB"},
            "powerboard": {
                "measured": "GW_AFTER_PB",
                "subtract": ["GW_A", "GW_PB"],
                "result_code": "GW_GLUE_PB",
            },
        }
    }

    assert glue_weight_inputs_from_settings(settings) == ()


def test_glue_settings_survive_the_admin_endpoint(as_admin, session_factory, tudo):
    resp = as_admin.patch(
        f"/api/institutes/{tudo['code']}",
        json={
            "settings": {
                "glue_targets": [
                    {
                        "process": "trueblue",
                        "valid_from": None,
                        "module_types": {
                            "R5M1_HALFMODULE": {
                                "hybrids": {"target_mg": 151, "tolerance_mg": 22}
                            }
                        },
                    }
                ],
                "glue_weight_inputs": GLUE_WEIGHT_INPUT_SETTINGS,
                "glue_default_process": "trueblue",
            }
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["settings"]["glue_targets"][0]["process"] == "TRUEBLUE"
    assert resp.json()["settings"]["glue_default_process"] == "TRUEBLUE"


def test_admin_endpoint_removes_the_legacy_default_after_migration(
    as_admin, session_factory, tudo
):
    with session_factory() as session:
        profile = session.scalar(
            select(InstituteProfile).where(InstituteProfile.code == tudo["code"])
        )
        assert profile is not None
        profile.settings = {
            **(profile.settings or {}),
            "glue_targets": [
                {"process": "TRUEBLUE", "valid_from": None, "module_types": {}}
            ],
            "glue_process_default": "TRUEBLUE",
        }
        session.commit()

    resp = as_admin.patch(
        f"/api/institutes/{tudo['code']}",
        json={"settings": {"glue_default_process": "TRUEBLUE"}},
    )

    assert resp.status_code == 200, resp.text
    settings = resp.json()["settings"]
    assert settings["glue_default_process"] == "TRUEBLUE"
    assert "glue_process_default" not in settings


# --- the worksheet row -----------------------------------------------------


@pytest.fixture
def configured_tudo(tudo, session_factory):
    """Opt TUDO into glue derivation explicitly for integration tests."""
    with session_factory() as session:
        profile = session.scalar(
            select(InstituteProfile).where(InstituteProfile.code == tudo["code"])
        )
        assert profile is not None
        current = profile.settings if isinstance(profile.settings, dict) else {}
        profile.settings = {**current, **SHEET_GLUE_SETTINGS}
        session.commit()
    return tudo


def _module(session, *, type_code="R5M1_HALFMODULE", institute_code="TUDO"):
    component = Component(
        sn=SN,
        component_type="MODULE",
        type_code=type_code,
        stage="GLUED",
        location=institute_code,
        institute_code=institute_code,
        is_dummy=True,
    )
    session.add(component)
    session.flush()
    return component


def _glue_run(session, *, results, external_ref="run-1", run_state=None, measured_at=None):
    row = TestRunEvidence(
        component_sn=SN,
        test_type=TEST_TYPE,
        passed=True,
        source="pdb",
        external_ref=external_ref,
        measured_at=measured_at,
        run_state=run_state,
        payload={"results": results, "result_meta": {}},
    )
    session.add(row)
    session.flush()
    return row


def _glue_row(preview):
    for group in preview["worksheet"]["groups"]:
        for row in group["rows"]:
            if row["test_type"] == TEST_TYPE:
                return row
    raise AssertionError("no GLUE_WEIGHT row in the worksheet")


def test_worksheet_row_carries_the_derived_verdict(session_factory, configured_tudo):
    with session_factory() as session:
        component = _module(session)
        _glue_run(session, results=READINGS)
        row = _glue_row(build_component_preview(session, component, object()))
    derived = row["derived"]
    assert derived["kind"] == "glue_weight"
    hybrids = next(step for step in derived["steps"] if step["key"] == "hybrids")
    assert hybrids["measured_mg"] == pytest.approx(132.7)
    assert hybrids["target_mg"] == 151
    assert hybrids["verdict"] == "ok"


def test_worksheet_row_without_a_run_still_states_the_target(
    session_factory, configured_tudo
):
    with session_factory() as session:
        component = _module(session)
        row = _glue_row(build_component_preview(session, component, object()))
    hybrids = row["derived"]["steps"][0]
    assert row["latest"] is None
    assert hybrids["verdict"] == "unknown"
    assert hybrids["reason"] == "no_run"
    assert hybrids["target_mg"] == 151


def test_configured_custom_glue_type_gets_an_additional_no_run_row(
    session_factory, configured_tudo
):
    with session_factory() as session:
        profile = session.scalar(
            select(InstituteProfile).where(InstituteProfile.code == "TUDO")
        )
        assert profile is not None
        profile.settings = {
            **profile.settings,
            "glue_weight_inputs": {
                "hybrids": {
                    **GLUE_WEIGHT_INPUT_SETTINGS["hybrids"],
                    "test_type": "CUSTOM_GLUE",
                }
            },
        }
        component = _module(session)
        preview = build_component_preview(session, component, object())

    additional = next(
        group for group in preview["worksheet"]["groups"] if group["stage"] is None
    )
    row = next(row for row in additional["rows"] if row["test_type"] == "CUSTOM_GLUE")
    assert row["status"] == "missing"
    assert row["latest"] is None
    assert row["run_count"] == 0
    assert row["derived"]["steps"][0]["reason"] == "no_run"
    assert row["derived"]["steps"][0]["target_mg"] == 151


def test_a_withdrawn_run_never_produces_a_verdict(session_factory, configured_tudo):
    """A measurement the PDB has retracted is not evidence — for glue either."""
    with session_factory() as session:
        component = _module(session)
        _glue_run(session, results=READINGS, run_state="deleted")
        row = _glue_row(build_component_preview(session, component, object()))
        assert row["derived"]["steps"][0]["reason"] == "no_run"
        assert derive_for_component(session, component, test_type=TEST_TYPE).steps[0].reason is (
            GlueUnknownReason.NO_RUN
        )


def test_an_unconfigured_profile_has_no_glue_derivation(session_factory, tudo):
    with session_factory() as session:
        component = _module(session)
        row = _glue_row(build_component_preview(session, component, object()))
    assert row["derived"] is None


def test_the_session_bound_adapter_uses_the_newest_run(
    session_factory, configured_tudo
):
    with session_factory() as session:
        component = _module(session)
        _glue_run(
            session,
            results=dict(READINGS, GW_MODULE_H1=9.0),
            external_ref="old",
            measured_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        _glue_run(
            session,
            results=READINGS,
            external_ref="new",
            measured_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        derivation = derive_for_component(session, component, test_type=TEST_TYPE)
    assert derivation.steps[0].measured_mg == pytest.approx(132.7)


def test_the_adapter_reads_the_institutes_own_profile(session_factory, client):
    create_institute_profile(
        session_factory,
        code="EXIN",
        name="Example Institute",
        settings=_override({"R5M1_HALFMODULE": {"hybrids": {"target_mg": 90, "tolerance_mg": 5}}}),
    )
    with session_factory() as session:
        component = _module(session, institute_code="EXIN")
        _glue_run(session, results=READINGS)
        derivation = derive_for_component(session, component, test_type=TEST_TYPE)
    assert derivation.steps[0].target == GlueTarget(90, 5)
    assert derivation.steps[0].verdict is GlueVerdict.TOO_MUCH


# --- the dry-run -----------------------------------------------------------


def _ingest(
    session_factory,
    results,
    *,
    sn=SN,
    institution=None,
    properties=None,
):
    payload = {
        "component": sn,
        "testType": TEST_TYPE,
        "passed": True,
        "problems": False,
        "runNumber": "1",
        "date": "2026-02-13T10:46:00Z",
        "results": results,
        "properties": properties or {},
    }
    if institution is not None:
        payload["institution"] = institution
    canonical_payload = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    with session_factory() as session:
        ingest = IngestFile(
            filename="glue.json",
            sha256=hashlib.sha256(canonical_payload).hexdigest(),
            size_bytes=len(canonical_payload),
            status="received",
            component_sn=sn,
            test_type=TEST_TYPE,
            payload=payload,
            uploaded_by="operator@example.org",
        )
        session.add(ingest)
        session.commit()
        session.refresh(ingest)
        return ingest.id


def _mirror_module(session_factory, **kwargs):
    with session_factory() as session:
        _module(session, **kwargs)
        session.commit()


def _alternate_glue_profile(session_factory, *, require_jig=False):
    settings = _override({})
    settings["glue_weight_inputs"] = {
        "hybrids": {
            "label": "Alternate hybrids",
            "test_type": TEST_TYPE,
            "measured": "ALT_AFTER",
            "subtract": ["ALT_BEFORE"],
            "result_code": "ALT_GLUE",
        }
    }
    if require_jig:
        settings["required_properties"] = {TEST_TYPE: ["ALT_JIG"]}
    return create_institute_profile(
        session_factory,
        code="EXIN",
        name="Example Institute",
        settings=settings,
    )


def test_the_dry_run_computes_the_verdict_before_anything_is_staged(
    client, session_factory, configured_tudo
):
    _mirror_module(session_factory)
    file_id = _ingest(session_factory, READINGS)
    body = client.get(f"/api/ingest/files/{file_id}/preview").json()
    assert body["upload_ready"] is True
    hybrids = next(step for step in body["derived"]["steps"] if step["key"] == "hybrids")
    assert hybrids["measured_mg"] == pytest.approx(132.7)
    assert hybrids["target_mg"] == 151
    assert hybrids["verdict"] == "ok"
    assert hybrids["result_code"] == "GW_GLUE_H1"


def test_the_dry_run_reports_a_missing_reading_instead_of_computing_one(
    client, session_factory, configured_tudo
):
    _mirror_module(session_factory)
    file_id = _ingest(session_factory, dict(READINGS, GW_SENSOR=None))
    body = client.get(f"/api/ingest/files/{file_id}/preview").json()
    hybrids = next(step for step in body["derived"]["steps"] if step["key"] == "hybrids")
    assert hybrids["verdict"] == "unknown"
    assert hybrids["reason"] == "missing_inputs"
    assert hybrids["measured_mg"] is None


def test_a_staged_upload_carries_the_computed_values_in_grams(
    as_operator, session_factory, configured_tudo
):
    _mirror_module(session_factory, type_code="R5M0_HALFMODULE")
    file_id = _ingest(session_factory, READINGS)
    resp = as_operator.post(f"/api/ingest/files/{file_id}/propose-outbox", json={})
    assert resp.status_code == 201, resp.text
    with session_factory() as session:
        ingest = session.get(IngestFile, file_id)
        action = ingest.outbox_action
        action_payload = action.payload
        assert revalidate_upload(session, action) == []
    assert action_payload["derived_results"] == {
        "GW_GLUE_H1": pytest.approx(0.1327),
        "GW_GLUE_PB": pytest.approx(0.0961),
        "GW_GLUE_H1PB": pytest.approx(0.2288),
    }
    assert action_payload["derived_result_codes"] == [
        "GW_GLUE_H1",
        "GW_GLUE_PB",
        "GW_GLUE_H1PB",
    ]
    assert action_payload["derived"]["steps"][0]["verdict"] == "ok"
    # The received file itself is untouched, so its sha256 keeps meaning what
    # it says: the derived values ride on the write intent, not on the evidence.
    with session_factory() as session:
        assert "GW_GLUE_H1" not in session.get(IngestFile, file_id).payload["results"]


def test_target_change_after_review_requires_the_glue_upload_to_be_restaged(
    as_operator, session_factory, configured_tudo
):
    _mirror_module(session_factory, type_code="R5M0_HALFMODULE")
    file_id = _ingest(session_factory, READINGS)
    response = as_operator.post(f"/api/ingest/files/{file_id}/propose-outbox", json={})
    assert response.status_code == 201, response.text

    with session_factory() as session:
        profile = session.scalar(
            select(InstituteProfile).where(InstituteProfile.code == "TUDO")
        )
        assert profile is not None
        changed_targets = {
            **SHEET_MODULE_TARGETS,
            "R5M0_HALFMODULE": {
                **SHEET_MODULE_TARGETS["R5M0_HALFMODULE"],
                "hybrids": {"target_mg": 200, "tolerance_mg": 1},
            },
        }
        profile.settings = {
            **profile.settings,
            "glue_targets": [
                {
                    **SHEET_GLUE_SETTINGS["glue_targets"][0],
                    "module_types": changed_targets,
                }
            ],
        }
        session.commit()

    with session_factory() as session:
        ingest = session.get(IngestFile, file_id)
        issues = revalidate_upload(session, ingest.outbox_action)

    assert issues == [
        "The staged derivation no longer matches the server formula or targets; "
        "restage the upload."
    ]


def test_a_missing_input_cannot_let_a_raw_formula_result_survive_the_upload(
    as_operator, session_factory, configured_tudo
):
    _mirror_module(session_factory, type_code="R5M0_HALFMODULE")
    raw_readings = {**READINGS, "GW_SENSOR": None, "GW_GLUE_H1": 9.999}
    file_id = _ingest(session_factory, raw_readings)
    response = as_operator.post(f"/api/ingest/files/{file_id}/propose-outbox", json={})
    assert response.status_code == 201, response.text

    with session_factory() as session:
        ingest = session.get(IngestFile, file_id)
        action = ingest.outbox_action
        assert action.payload["derived_results"] == {"GW_GLUE_PB": pytest.approx(0.0961)}
        assert action.payload["derived_result_codes"] == [
            "GW_GLUE_H1",
            "GW_GLUE_PB",
            "GW_GLUE_H1PB",
        ]
        assert revalidate_upload(session, action) == []
        upload = build_upload_test_run_payload(
            ingest.payload,
            component_sn=SN,
            institute_code="TUDO",
            derived_results=action.payload["derived_results"],
            derived_result_codes=action.payload["derived_result_codes"],
        )

    assert "GW_GLUE_H1" not in upload["results"]
    assert upload["results"]["GW_GLUE_PB"] == pytest.approx(0.0961)
    assert raw_readings["GW_GLUE_H1"] == 9.999


def test_the_dry_run_derives_nothing_for_an_unconfigured_test_type(
    client, session_factory, configured_tudo
):
    _mirror_module(session_factory)
    with session_factory() as session:
        ingest = IngestFile(
            filename="bow.json",
            sha256="c" * 64,
            size_bytes=10,
            status="received",
            component_sn=SN,
            test_type="MODULE_BOW",
            payload={
                "component": SN,
                "testType": "MODULE_BOW",
                "passed": True,
                "problems": False,
                "runNumber": "1",
                "date": "2026-02-13T10:46:00Z",
                "results": {"BOW": 0.1},
            },
            uploaded_by="operator@example.org",
        )
        session.add(ingest)
        session.commit()
        file_id = ingest.id
    body = client.get(f"/api/ingest/files/{file_id}/preview").json()
    assert body["derived"] is None


def test_the_dry_run_uses_the_institute_of_the_resolved_component(
    as_operator, session_factory, tudo
):
    exin = create_institute_profile(
        session_factory,
        code="EXIN",
        name="Example Institute",
        settings=_override({"R5M1_HALFMODULE": {"hybrids": {"target_mg": 90, "tolerance_mg": 5}}}),
    )
    _mirror_module(session_factory, institute_code="EXIN")
    file_id = _ingest(session_factory, READINGS)
    preview_response = as_operator.get(
        f"/api/ingest/files/{file_id}/preview",
        # Even an explicit conflicting selection cannot move a mirrored
        # component out of the institute that owns its local mirror row.
        params={"institute_code": "TUDO"},
    )
    assert preview_response.status_code == 200, preview_response.text
    body = preview_response.json()
    assert body["institute_code"] == "EXIN"
    hybrids = body["derived"]["steps"][0]
    assert hybrids["target_mg"] == 90
    assert hybrids["verdict"] == "too_much"

    proposal = as_operator.post(
        f"/api/ingest/files/{file_id}/propose-outbox",
        json={"institute_code": "TUDO"},
    )
    assert proposal.status_code == 201, proposal.text
    assert proposal.json()["institute_id"] == exin["id"]


def test_unmirrored_preview_and_proposal_share_the_selected_profile(
    as_operator, session_factory, configured_tudo
):
    exin = _alternate_glue_profile(session_factory, require_jig=True)
    readings = {**READINGS, "ALT_AFTER": 1.4, "ALT_BEFORE": 1.0}
    file_id = _ingest(
        session_factory,
        readings,
        properties={"ALT_JIG": "fixture-jig"},
    )

    preview_response = as_operator.get(
        f"/api/ingest/files/{file_id}/preview",
        params={"institute_code": "EXIN"},
    )
    assert preview_response.status_code == 200, preview_response.text
    preview = preview_response.json()
    assert preview["component_mirrored"] is False
    assert preview["institute_code"] == "EXIN"
    step = preview["derived"]["steps"][0]
    assert [item["code"] for item in step["inputs"]] == ["ALT_AFTER", "ALT_BEFORE"]
    assert step["measured_mg"] == pytest.approx(400)

    proposal = as_operator.post(
        f"/api/ingest/files/{file_id}/propose-outbox",
        json={"institute_code": "EXIN"},
    )
    assert proposal.status_code == 201, proposal.text
    assert proposal.json()["institute_id"] == exin["id"]
    assert proposal.json()["payload"]["derived_results"] == {
        "ALT_GLUE": pytest.approx(0.4)
    }
    assert proposal.json()["payload"]["derived_result_codes"] == ["ALT_GLUE"]


def test_unmirrored_proposal_validates_with_the_selected_profile(
    as_operator, session_factory, configured_tudo
):
    _alternate_glue_profile(session_factory, require_jig=True)
    file_id = _ingest(
        session_factory,
        {**READINGS, "ALT_AFTER": 1.4, "ALT_BEFORE": 1.0},
    )

    preview = as_operator.get(
        f"/api/ingest/files/{file_id}/preview",
        params={"institute_code": "EXIN"},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["upload_ready"] is False
    assert preview.json()["issues"] == [
        "Missing required property for GLUE_WEIGHT: ALT_JIG."
    ]

    proposal = as_operator.post(
        f"/api/ingest/files/{file_id}/propose-outbox",
        json={"institute_code": "EXIN"},
    )
    assert proposal.status_code == 409
    assert "Missing required property for GLUE_WEIGHT: ALT_JIG." in proposal.json()["detail"]


def test_unmirrored_payload_and_selected_institute_conflict_fails_closed(
    as_operator, session_factory, configured_tudo
):
    _alternate_glue_profile(session_factory)
    file_id = _ingest(session_factory, READINGS, institution="TUDO")

    preview = as_operator.get(
        f"/api/ingest/files/{file_id}/preview",
        params={"institute_code": "EXIN"},
    )
    assert preview.status_code == 409
    assert preview.json()["detail"] == (
        "Payload institution 'TUDO' does not match selected institute 'EXIN'."
    )

    proposal = as_operator.post(
        f"/api/ingest/files/{file_id}/propose-outbox",
        json={"institute_code": "EXIN"},
    )
    assert proposal.status_code == 409
    assert proposal.json()["detail"] == preview.json()["detail"]


def test_an_unmirrored_component_still_reports_why_it_cannot_judge(
    client, session_factory, configured_tudo
):
    """No mirror row means no module type — stated as no_target, never guessed."""
    with session_factory() as session:
        profile = session.scalar(select(InstituteProfile).where(InstituteProfile.code == "TUDO"))
        assert profile is not None
    file_id = _ingest(session_factory, READINGS)
    with session_factory() as session:
        ingest = session.get(IngestFile, file_id)
        ingest.payload = dict(ingest.payload, institution="TUDO")
        session.commit()
    body = client.get(f"/api/ingest/files/{file_id}/preview").json()
    hybrids = body["derived"]["steps"][0]
    assert hybrids["measured_mg"] == pytest.approx(132.7)
    assert hybrids["verdict"] == "unknown"
    assert hybrids["reason"] == "no_target"


def test_a_negative_glue_weight_is_not_a_verdict():
    """Readings that contradict each other must not read as "too little".

    Two live runs in the TUDO mirror produce -8696 mg and -7771 mg because the
    module weight and the glue weight were entered into each other's field. The
    subtraction is faithful and the answer is still impossible; calling it
    `too_little` would tell an operator they under-applied glue, when the truth
    is that the readings cannot both be right. That is exactly the failure the
    spreadsheet makes — its own garbage values (-9010, -9886) sit in the sheet
    looking like measurements.
    """
    from app.domain.glue import (
        GlueStepSpec,
        GlueTarget,
        GlueTargetRule,
        GlueUnknownReason,
        GlueVerdict,
        evaluate_glue_step,
    )

    spec = GlueStepSpec(
        key="hybrids",
        label="Hybrids",
        measured="GW_MODULE_H1",
        subtract=("GW_SENSOR", "GW_HYBRID1"),
        result_code="GW_GLUE_H1",
        test_type="GLUE_WEIGHT",
    )
    rule = GlueTargetRule(
        process="TRUEBLUE",
        label="True Blue",
        valid_from=None,
        module_types={"R5M1": {"hybrids": GlueTarget(target_mg=151.0, tolerance_mg=22.0)}},
    )
    # The real swapped-field shape: the glue weight sits in the module field.
    swapped = evaluate_glue_step(
        spec,
        rule=rule,
        type_code="R5M1",
        results={"GW_MODULE_H1": 0.144, "GW_SENSOR": 6.981, "GW_HYBRID1": 1.859},
        result_meta={},
    )
    assert swapped.measured_mg == -8696.0
    assert swapped.verdict is GlueVerdict.UNKNOWN
    assert swapped.reason is GlueUnknownReason.IMPLAUSIBLE

    # The same chain entered correctly still judges normally.
    sane = evaluate_glue_step(
        spec,
        rule=rule,
        type_code="R5M1",
        results={"GW_MODULE_H1": 8.984, "GW_SENSOR": 6.981, "GW_HYBRID1": 1.859},
        result_meta={},
    )
    assert sane.measured_mg == 144.0
    assert sane.verdict is GlueVerdict.OK
    assert sane.reason is None


def test_the_dry_run_serializes_an_implausible_glue_reason(
    client, session_factory, configured_tudo
):
    """The public response model must accept the domain's fail-closed reason."""
    _mirror_module(session_factory, type_code="R5M1")
    swapped = dict(
        READINGS,
        GW_MODULE_H1=0.144,
        GW_SENSOR=6.981,
        GW_HYBRID1=1.859,
    )
    file_id = _ingest(session_factory, swapped)

    response = client.get(f"/api/ingest/files/{file_id}/preview")

    assert response.status_code == 200, response.text
    hybrids = next(
        step for step in response.json()["derived"]["steps"] if step["key"] == "hybrids"
    )
    assert hybrids["measured_mg"] == -8696.0
    assert hybrids["verdict"] == "unknown"
    assert hybrids["reason"] == "implausible_result"
