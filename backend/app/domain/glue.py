"""Glue-weight domain logic — pure functions, institute-agnostic.

Targets and tolerances are *profile data*: the constants below are seed
defaults (taken from the TUDO production sheet, TrueBlue/FalseBlue process)
that an institute profile can override. Nothing here is hardcoded per site.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum


@dataclass(frozen=True)
class GlueTarget:
    target_mg: float
    tolerance_mg: float

    @property
    def low_mg(self) -> float:
        return self.target_mg - self.tolerance_mg

    @property
    def high_mg(self) -> float:
        return self.target_mg + self.tolerance_mg


class GlueVerdict(str, Enum):
    OK = "ok"
    TOO_LITTLE = "too_little"
    TOO_MUCH = "too_much"


def parse_decimal(value: str) -> float:
    """Accept both comma and dot as decimal separator (mixed-locale labs)."""
    return float(value.strip().replace(",", "."))


def glue_weight_mg(weight_before_g: float, parts_weight_g: float, weight_after_g: float) -> float:
    """Glue weight in mg from three scale readings (in grams)."""
    return round((weight_after_g - weight_before_g - parts_weight_g) * 1000.0, 1)


def evaluate_glue_weight(measured_mg: float, target: GlueTarget) -> GlueVerdict:
    if measured_mg < target.low_mg:
        return GlueVerdict.TOO_LITTLE
    if measured_mg > target.high_mg:
        return GlueVerdict.TOO_MUCH
    return GlueVerdict.OK


def hybrid_chip_glue_target(
    n_abc: int,
    n_hcc: int,
    *,
    abc_target_mg: float = 4.2,
    abc_tolerance_mg: float = 0.25,
    hcc_target_mg: float = 1.5,
    hcc_tolerance_mg: float = 0.1,
) -> GlueTarget:
    """Chip-attach glue target for a hybrid: linear in its ABC/HCC counts."""
    return GlueTarget(
        target_mg=n_abc * abc_target_mg + n_hcc * hcc_target_mg,
        tolerance_mg=n_abc * abc_tolerance_mg + n_hcc * hcc_tolerance_mg,
    )


@dataclass(frozen=True)
class PotLifeState:
    """Where a mixed glue batch stands relative to its pot life."""

    mixed_at: datetime
    expires_at: datetime
    remaining_seconds: int  # 0 once expired
    expired: bool


def pot_life_state(
    mixed_at: datetime | None, pot_life_minutes: int | None, now: datetime | None = None
) -> PotLifeState | None:
    """Pot-life countdown for a mixed batch; None while unmixed or untimed.

    Naive timestamps (SQLite round-trips drop the offset) are treated as UTC.
    """
    if mixed_at is None or pot_life_minutes is None or pot_life_minutes <= 0:
        return None
    if mixed_at.tzinfo is None:
        mixed_at = mixed_at.replace(tzinfo=timezone.utc)
    if now is None:
        now = datetime.now(timezone.utc)
    expires_at = mixed_at + timedelta(minutes=pot_life_minutes)
    remaining = int((expires_at - now).total_seconds())
    return PotLifeState(
        mixed_at=mixed_at,
        expires_at=expires_at,
        remaining_seconds=max(0, remaining),
        expired=remaining <= 0,
    )


# Seed defaults per module type (institute profiles may override).
# "hybrids" = all hybrids glued in one step; "powerboard" absent where the
# module type carries no powerboard (M1 half-modules).
DEFAULT_MODULE_GLUE_TARGETS: dict[str, dict[str, GlueTarget]] = {
    "R0": {"hybrids": GlueTarget(230, 35), "powerboard": GlueTarget(84, 13)},
    "R1": {"hybrids": GlueTarget(311, 46), "powerboard": GlueTarget(84, 13)},
    "R2": {"hybrids": GlueTarget(164, 25), "powerboard": GlueTarget(70, 11)},
    "R3M0": {"hybrids": GlueTarget(198, 30), "powerboard": GlueTarget(157, 23)},
    "R3M1": {"hybrids": GlueTarget(231, 35)},
    "R5M0": {"hybrids": GlueTarget(135, 20), "powerboard": GlueTarget(103, 16)},
    "R5M1": {"hybrids": GlueTarget(151, 22)},
}
