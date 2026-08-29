# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-FileComment: itkflow-7d482b8dc83e
"""Module-metrology ingestion parser (docs/10).

The metrology instrument/zFlow already emits the standard PDB
`uploadTestRunResults` shape for MODULE_METROLOGY (positions as
deviation-from-nominal, glue heights in µm). This parser validates that shape;
structure mirrors the anonymized zFlow reference JSON.
"""

from app.ingestion import parse_payload


def _payload(results_override=None, **over):
    payload = {
        "component": "20USE5M0000701",
        "testType": "MODULE_METROLOGY",
        "date": "2025-02-20T12:53:12.000Z",
        "institution": "TUDO",
        "runNumber": "1",
        "passed": True,
        "problems": False,
        "properties": {"MACHINE": "OGP Smartscope CNC 300", "OPERATOR": "Anna Abel"},
        "results": {
            "HYBRID_POSITION": {"H_R5H0_P1": [-7.4, -11.7]},
            "PB_POSITION": {"PB_P1": [-8.5, -37.4]},
            "HYBRID_GLUE_THICKNESS": {"ABC_R5H0_0": 128.2, "H_R5H0_0": 167.8},
            "PB_GLUE_THICKNESS": {"PB_1": 109.2},
            "CAP_HEIGHT": {"C1": 2940.2},
            "SHIELDBOX_HEIGHT": 5420.8,
        },
    }
    if results_override is not None:
        payload["results"].update(results_override)
    payload.update(over)
    return payload


def test_metrology_parser_selected_and_clean():
    parsed = parse_payload(_payload())
    assert parsed.parser == "module-metrology-v1"
    assert parsed.test_type == "MODULE_METROLOGY"
    assert parsed.issues == []


def test_metrology_flags_non_numeric_thickness():
    parsed = parse_payload(_payload({"HYBRID_GLUE_THICKNESS": {"ABC_R5H0_0": "n/a"}}))
    assert parsed.parser == "module-metrology-v1"
    assert any("HYBRID_GLUE_THICKNESS" in issue for issue in parsed.issues)


def test_metrology_flags_bad_position_pair():
    parsed = parse_payload(_payload({"HYBRID_POSITION": {"H_R5H0_P1": [1.0]}}))
    assert any("HYBRID_POSITION" in issue for issue in parsed.issues)


def test_metrology_warns_when_no_recognised_groups():
    parsed = parse_payload(
        _payload(
            {
                "HYBRID_POSITION": None,
                "PB_POSITION": None,
                "HYBRID_GLUE_THICKNESS": None,
                "PB_GLUE_THICKNESS": None,
                "CAP_HEIGHT": None,
            }
        )
    )
    assert any("metrology result groups" in warning for warning in parsed.warnings)
