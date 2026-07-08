import pytest

from app.domain.glue import (
    DEFAULT_MODULE_GLUE_TARGETS,
    GlueTarget,
    GlueVerdict,
    evaluate_glue_weight,
    glue_weight_mg,
    hybrid_chip_glue_target,
    parse_decimal,
)


def test_glue_weight_from_scale_readings():
    # Example from the module gluing wizard: 12.1185 - 9.7522 - 2.2330 = 0.1333 g
    assert glue_weight_mg(9.7522, 2.2330, 12.1185) == pytest.approx(133.3)


def test_parse_decimal_accepts_comma_and_dot():
    assert parse_decimal("12,1185") == pytest.approx(12.1185)
    assert parse_decimal("12.1185") == pytest.approx(12.1185)
    assert parse_decimal(" 7,0162 ") == pytest.approx(7.0162)


@pytest.mark.parametrize(
    ("measured", "expected"),
    [
        (133.3, GlueVerdict.OK),
        (115.0, GlueVerdict.OK),  # lower boundary is inclusive
        (155.0, GlueVerdict.OK),  # upper boundary is inclusive
        (114.9, GlueVerdict.TOO_LITTLE),
        (155.1, GlueVerdict.TOO_MUCH),
        (-9010.0, GlueVerdict.TOO_LITTLE),  # sheet-era artifact: missing weighing
    ],
)
def test_evaluate_against_r5m0_hybrid_target(measured: float, expected: GlueVerdict):
    target = DEFAULT_MODULE_GLUE_TARGETS["R5M0"]["hybrids"]  # 135 ± 20 mg
    assert evaluate_glue_weight(measured, target) is expected


def test_half_module_types_have_no_powerboard_target():
    assert "powerboard" not in DEFAULT_MODULE_GLUE_TARGETS["R3M1"]
    assert "powerboard" not in DEFAULT_MODULE_GLUE_TARGETS["R5M1"]
    assert "powerboard" in DEFAULT_MODULE_GLUE_TARGETS["R5M0"]


def test_hybrid_chip_glue_target_is_linear_in_chip_counts():
    # R5H1-like hybrid: 9 ABCs, 2 HCCs with the default per-chip amounts
    target = hybrid_chip_glue_target(9, 2)
    assert target == GlueTarget(target_mg=pytest.approx(40.8), tolerance_mg=pytest.approx(2.45))
    # Parameters are profile data, not constants baked into the formula:
    custom = hybrid_chip_glue_target(9, 2, abc_target_mg=5.0, hcc_target_mg=2.0)
    assert custom.target_mg == pytest.approx(49.0)
