"""Glue-weight domain logic — pure functions, institute-agnostic.

Targets and tolerances are *profile data*. The constants below preserve the
TUDO production-sheet values as pure reference data, but runtime derivation is
enabled only by an institute profile. Nothing here is hardcoded per site.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any


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
    # No judgement was possible. Always paired with a `GlueUnknownReason`, never
    # rendered as a silent gap: on the production sheet this replaces 8 of 13
    # powerboard verdicts that were arithmetic on blank cells.
    UNKNOWN = "unknown"


class GlueUnknownReason(str, Enum):
    NO_TARGET = "no_target"  # the profile has no target for this type/step
    MISSING_INPUTS = "missing_inputs"  # a scale reading the formula needs is absent
    NO_RUN = "no_run"  # nothing has been measured for this test type yet


def parse_decimal(value: str) -> float:
    """Accept both comma and dot as decimal separator (mixed-locale labs)."""
    return float(value.strip().replace(",", "."))


MG_PER_GRAM = 1000.0


def grams_to_mg(value_g: float) -> float:
    return value_g * MG_PER_GRAM


def mg_to_grams(value_mg: float) -> float:
    return value_mg / MG_PER_GRAM


def glue_weight_from_readings_mg(measured_g: float, subtracted_g: Sequence[float]) -> float:
    """Glue weight in mg: the weighed assembly minus everything already on it.

    The PDB holds every `GW_` reading in grams while targets and tolerances are
    stated in milligrams, so this is the one place the two units meet. Which
    readings make up `measured_g` and `subtracted_g` is profile data
    (`glue_weight_inputs`), never a fixed chain of codes.
    """
    remainder = measured_g
    for part in subtracted_g:
        remainder -= part
    return round(grams_to_mg(remainder), 1)


def glue_weight_mg(weight_before_g: float, parts_weight_g: float, weight_after_g: float) -> float:
    """Glue weight in mg from three scale readings (in grams)."""
    return glue_weight_from_readings_mg(weight_after_g, (weight_before_g, parts_weight_g))


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


# Reference values per module type. Runtime profiles opt in explicitly.
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


# --------------------------------------------------------------------------
# Glue-weight derivation: profile data in, verdict out.
#
# Three things are institute configuration and none of them belong in code
# (hard rule #4):
#   settings["glue_targets"]        -> list of rule sets, see GlueTargetRule
#   settings["glue_weight_inputs"]  -> which PDB result codes feed which step
#   settings["glue_default_process"] / ["glue_process_property"]
#                                      -> how a run's glue process is determined
# The constants further down are reference/seed material only. The
# `*_from_settings` readers never activate them for an unconfigured profile.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class GlueStepSpec:
    """One derived quantity: `measured` minus every code in `subtract`.

    `result_code` is the PDB result the computed value is uploaded under (the
    production sheet uploads its computed glue weights the same way) and is
    optional, because a step may exist only to be judged locally.
    """

    key: str
    label: str
    test_type: str
    measured: str
    subtract: tuple[str, ...]
    result_code: str | None = None

    @property
    def input_codes(self) -> tuple[str, ...]:
        return (self.measured, *self.subtract)


@dataclass(frozen=True)
class GlueTargetRule:
    """Targets for one glue process, valid from one point in time onwards.

    A profile keeps several of these side by side. The production sheet this
    replaces runs two generations of the same rule at once (the newer hybrid
    tab uses different per-chip constants and a different tolerance shape than
    the older one), so a profile that knows only one set of constants cannot
    judge historical runs. `valid_from=None` is the always-valid fallback.
    """

    process: str
    label: str
    valid_from: datetime | None
    module_types: Mapping[str, Mapping[str, GlueTarget]]

    def knows(self, type_code: str | None) -> bool:
        return type_code is not None and type_code in self.module_types

    def target_for(self, type_code: str | None, step_key: str) -> GlueTarget | None:
        if type_code is None:
            return None
        return self.module_types.get(type_code, {}).get(step_key)


@dataclass(frozen=True)
class GlueInput:
    """One raw scale reading behind a derived value, in grams as the PDB holds it."""

    code: str
    name: str
    value: float | None


@dataclass(frozen=True)
class GlueStepEvaluation:
    key: str
    label: str
    measured_mg: float | None
    target: GlueTarget | None
    verdict: GlueVerdict
    reason: GlueUnknownReason | None
    inputs: tuple[GlueInput, ...]
    result_code: str | None


@dataclass(frozen=True)
class GlueDerivation:
    process: str | None
    process_source: str  # "run" | "profile_default" | "unknown"
    steps: tuple[GlueStepEvaluation, ...]


def _as_utc(value: datetime | None) -> datetime | None:
    """Naive timestamps (SQLite round-trips drop the offset) are UTC by convention."""
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def parse_valid_from(value: Any) -> datetime | None:
    """Read a rule's validity start. A plain date means midnight UTC."""
    if isinstance(value, datetime):
        return _as_utc(value)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return _as_utc(parsed)


_ALWAYS_VALID = datetime.min.replace(tzinfo=timezone.utc)


def select_glue_rule(
    rules: Sequence[GlueTargetRule], *, process: str | None, at: datetime | None
) -> GlueTargetRule | None:
    """The rule set that governed `process` at `at`.

    All entries for the process, then the one with the greatest `valid_from`
    that is not later than the measurement; `valid_from=None` always qualifies
    and loses to any dated rule. An undated run can only use that explicit
    always-valid fallback. It must not silently select a dated (possibly
    future) rule.
    """
    if process is None:
        return None
    at = _as_utc(at)
    if at is None:
        fallbacks = [
            rule
            for rule in rules
            if rule.process == process and rule.valid_from is None
        ]
        # Duplicate fallbacks are invalid profile data. The write validator
        # rejects them; legacy data fails closed instead of depending on order.
        return fallbacks[0] if len(fallbacks) == 1 else None
    eligible = [
        rule
        for rule in rules
        if rule.process == process
        and (rule.valid_from is None or rule.valid_from <= at)
    ]
    if not eligible:
        return None
    return max(eligible, key=lambda rule: rule.valid_from or _ALWAYS_VALID)


def _numeric(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _result_name(result_meta: Mapping[str, Any], code: str) -> str:
    entry = result_meta.get(code)
    if isinstance(entry, Mapping):
        name = entry.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return code


def evaluate_glue_step(
    spec: GlueStepSpec,
    *,
    rule: GlueTargetRule | None,
    type_code: str | None,
    results: Mapping[str, Any] | None,
    result_meta: Mapping[str, Any],
) -> GlueStepEvaluation:
    """Judge one step. `results=None` means no run has been recorded at all.

    The precedence of the unknown reasons follows the repair order: without a
    run nothing else matters, a missing scale reading belongs to the operator,
    a missing target belongs to the profile. Each one is stated explicitly —
    an absent input must never come out looking like a result.
    """
    target = rule.target_for(type_code, spec.key) if rule is not None else None
    values: list[float] = []
    inputs: list[GlueInput] = []
    missing = False
    for code in spec.input_codes:
        raw = _numeric(results.get(code)) if results is not None else None
        if raw is None:
            missing = True
        else:
            values.append(raw)
        inputs.append(GlueInput(code=code, name=_result_name(result_meta, code), value=raw))

    measured_mg = (
        None if missing else glue_weight_from_readings_mg(values[0], tuple(values[1:]))
    )
    if results is None:
        verdict, reason = GlueVerdict.UNKNOWN, GlueUnknownReason.NO_RUN
    elif missing:
        verdict, reason = GlueVerdict.UNKNOWN, GlueUnknownReason.MISSING_INPUTS
    elif target is None:
        verdict, reason = GlueVerdict.UNKNOWN, GlueUnknownReason.NO_TARGET
    else:
        verdict, reason = evaluate_glue_weight(measured_mg, target), None
    return GlueStepEvaluation(
        key=spec.key,
        label=spec.label,
        measured_mg=measured_mg,
        target=target,
        verdict=verdict,
        reason=reason,
        inputs=tuple(inputs),
        result_code=spec.result_code,
    )


def derive_glue_weights(
    specs: Sequence[GlueStepSpec],
    rules: Sequence[GlueTargetRule],
    *,
    process: str | None,
    process_source: str,
    type_code: str | None,
    results: Mapping[str, Any] | None,
    result_meta: Mapping[str, Any] | None = None,
    measured_at: datetime | None = None,
) -> GlueDerivation:
    """Evaluate every configured step of one run.

    A step is dropped only when the selected rule *knows* the module type and
    that type carries no entry for the step: that is the profile positively
    saying "this module type has no such gluing step" (half-modules carry no
    powerboard). A module type the rule has never heard of keeps all its steps
    and reports `no_target`, so a profile gap stays visible instead of quietly
    becoming an empty section.
    """
    rule = select_glue_rule(rules, process=process, at=measured_at)
    known_type = rule is not None and rule.knows(type_code)
    meta = result_meta if isinstance(result_meta, Mapping) else {}
    steps = [
        evaluate_glue_step(
            spec, rule=rule, type_code=type_code, results=results, result_meta=meta
        )
        for spec in specs
        if not (known_type and rule.target_for(type_code, spec.key) is None)
    ]
    return GlueDerivation(process=process, process_source=process_source, steps=tuple(steps))


# --- Reference seeds ------------------------------------------------------
# The test type a derived step belongs to is data, not a branch in the code:
# every seeded step names it explicitly and a profile can move the derivation
# to whatever test type its schema uses.
DEFAULT_GLUE_TEST_TYPE = "GLUE_WEIGHT"

# The production sheet names module types the way its operators say them; the
# PDB spells two of them differently. Both spellings are seeded so a mirrored
# component resolves without the lookup ever guessing at a naming scheme.
_SEED_TYPE_CODE_ALIASES: dict[str, tuple[str, ...]] = {
    "R5M0": ("R5M0", "R5M0_HALFMODULE"),
    "R5M1": ("R5M1", "R5M1_HALFMODULE"),
}

# Measured against the owner's mirror, not transcribed from the sheet: over 114
# live GLUE_WEIGHT runs the single-hybrid chain below reproduces the PDB's own
# stored glue weight to within 1 mg on 25 of 31 complete hybrid sets and 13 of
# 18 complete powerboard sets. All 11 mismatches are runs whose stored weight
# does not equal its own stored readings — two factor-ten typos, one swapped
# field and eight smaller inconsistencies. The chain the plan's §9.2 example
# uses (GW_MODULE_H1H2) is null in every one of the 132 mirrored runs.
DEFAULT_GLUE_WEIGHT_INPUTS: tuple[GlueStepSpec, ...] = (
    GlueStepSpec(
        key="hybrids",
        label="Hybrids",
        test_type=DEFAULT_GLUE_TEST_TYPE,
        measured="GW_MODULE_H1",
        subtract=("GW_SENSOR", "GW_HYBRID1"),
        result_code="GW_GLUE_H1",
    ),
    GlueStepSpec(
        key="powerboard",
        label="Powerboard",
        test_type=DEFAULT_GLUE_TEST_TYPE,
        measured="GW_MODULE_H1PB",
        subtract=("GW_MODULE_H1", "GW_PB"),
        result_code="GW_GLUE_PB",
    ),
)

# The module-type keys are PDB type codes (`Component.type_code`), which is what
# the derivation looks up. Where the sheet's own vocabulary differs from the
# PDB's, both spellings are seeded rather than guessed at runtime: the mirror
# proves `R5M0_HALFMODULE`/`R5M1_HALFMODULE` and `R2`, the remaining rows are
# the sheet's names and an institute that produces them replaces the key.
DEFAULT_GLUE_TARGET_RULES: tuple[GlueTargetRule, ...] = (
    GlueTargetRule(
        process="TRUEBLUE",
        label="True Blue / False Blue",
        valid_from=None,
        module_types={
            type_code: targets
            for name, targets in DEFAULT_MODULE_GLUE_TARGETS.items()
            for type_code in _SEED_TYPE_CODE_ALIASES.get(name, (name,))
        },
    ),
)

DEFAULT_GLUE_PROCESS: str | None = None


def glue_targets_from_settings(settings: Mapping | None) -> tuple[GlueTargetRule, ...]:
    """Read an institute profile's glue targets, failing closed.

    Rejecting bad input is the job of `app.institute_settings`, which every new
    write goes through. This reader also sees legacy profile JSON, so malformed
    configuration returns no rules. Missing, null, malformed, or empty data
    never activates the TUDO reference constants for another institute.
    """
    entries = (settings or {}).get("glue_targets")
    if not isinstance(entries, list):
        return ()
    rules: list[GlueTargetRule] = []
    for entry in entries:
        rule = _rule_from_entry(entry)
        if rule is None:
            return ()
        rules.append(rule)
    return tuple(rules)


def _rule_from_entry(entry: Any) -> GlueTargetRule | None:
    if not isinstance(entry, Mapping):
        return None
    process = entry.get("process")
    if not isinstance(process, str) or not process.strip():
        return None
    process = process.strip().upper()
    label = entry.get("label")
    raw_valid_from = entry.get("valid_from")
    valid_from = parse_valid_from(raw_valid_from)
    if raw_valid_from is not None and valid_from is None:
        return None
    module_types: dict[str, dict[str, GlueTarget]] = {}
    raw_types = entry.get("module_types")
    if not isinstance(raw_types, Mapping):
        return None
    for type_code, raw_steps in raw_types.items():
        if (
            not isinstance(type_code, str)
            or not type_code.strip()
            or not isinstance(raw_steps, Mapping)
        ):
            return None
        steps: dict[str, GlueTarget] = {}
        for step_key, raw_target in raw_steps.items():
            target = _target_from_entry(raw_target)
            if not isinstance(step_key, str) or not step_key.strip() or target is None:
                return None
            steps[step_key] = target
        module_types[type_code.strip().upper()] = steps
    return GlueTargetRule(
        process=process,
        label=label.strip() if isinstance(label, str) and label.strip() else process,
        valid_from=valid_from,
        module_types=module_types,
    )


def _target_from_entry(entry: Any) -> GlueTarget | None:
    if not isinstance(entry, Mapping):
        return None
    target_mg = _numeric(entry.get("target_mg"))
    tolerance_mg = _numeric(entry.get("tolerance_mg"))
    if (
        target_mg is None
        or tolerance_mg is None
        or not math.isfinite(target_mg)
        or not math.isfinite(tolerance_mg)
        or target_mg < 0
        or tolerance_mg < 0
    ):
        return None
    return GlueTarget(target_mg=target_mg, tolerance_mg=tolerance_mg)


def glue_weight_inputs_from_settings(settings: Mapping | None) -> tuple[GlueStepSpec, ...]:
    """Which PDB result codes feed which derivation step, per institute.

    Key order is the order the steps are presented in, which is why the setting
    is an object rather than an unordered mapping of anything else: the sheet
    glues hybrids first and the powerboard second, and the operator reads the
    derived rows in that order.
    """
    raw = (settings or {}).get("glue_weight_inputs")
    if not isinstance(raw, Mapping):
        return ()
    specs: list[GlueStepSpec] = []
    for key, entry in raw.items():
        spec = _spec_from_entry(key, entry)
        if spec is None:
            return ()
        specs.append(spec)
    return tuple(specs)


def _default_step_label(key: str) -> str:
    return key.replace("_", " ").replace("-", " ").strip().title() or key


def _spec_from_entry(key: Any, entry: Any) -> GlueStepSpec | None:
    if not isinstance(key, str) or not key.strip() or not isinstance(entry, Mapping):
        return None
    measured = entry.get("measured")
    if not isinstance(measured, str) or not measured.strip():
        return None
    raw_subtract = entry.get("subtract", [])
    if not isinstance(raw_subtract, list) or any(
        not isinstance(code, str) or not code.strip() for code in raw_subtract
    ):
        return None
    subtract = tuple(code.strip().upper() for code in raw_subtract)
    test_type = entry.get("test_type")
    label = entry.get("label")
    result_code = entry.get("result_code")
    key = key.strip()
    return GlueStepSpec(
        key=key,
        label=(
            label.strip()
            if isinstance(label, str) and label.strip()
            else _default_step_label(key)
        ),
        test_type=(
            test_type.strip().upper()
            if isinstance(test_type, str) and test_type.strip()
            else DEFAULT_GLUE_TEST_TYPE
        ),
        measured=measured.strip().upper(),
        subtract=subtract,
        result_code=(
            result_code.strip().upper()
            if isinstance(result_code, str) and result_code.strip()
            else None
        ),
    )


def glue_process_from_settings(
    settings: Mapping | None, rules: Sequence[GlueTargetRule]
) -> str | None:
    """The institute's explicit default glue process, when configured.

    `glue_default_process` is canonical. `glue_process_default` remains a
    read-only legacy alias for already persisted profiles. A candidate must
    name one of the configured target-rule processes; the sole configured rule
    is never inferred as a default.
    """
    profile = settings if isinstance(settings, Mapping) else {}
    if "glue_default_process" in profile:
        configured = profile.get("glue_default_process")
    else:
        configured = profile.get("glue_process_default", DEFAULT_GLUE_PROCESS)
    if not isinstance(configured, str) or not configured.strip():
        return None
    candidate = configured.strip().upper()
    return candidate if candidate in {rule.process for rule in rules} else None


def glue_process_property_from_settings(settings: Mapping | None) -> str | None:
    """The PDB property/result code under which a run names its glue process.

    No seed default: on the owner's mirror the only process-ish property is
    `GW_METHOD`, and its 132 values ("Stencil", "stencil", "stensil", ...)
    describe how the glue was applied, not which glue it was. An institute that
    does record the product per run points this setting at that code.
    """
    configured = (settings or {}).get("glue_process_property")
    if isinstance(configured, str) and configured.strip():
        return configured.strip().upper()
    return None


# --------------------------------------------------------------------------
# The whole configuration of one institute, and the entry point that uses it.
# --------------------------------------------------------------------------

PROCESS_FROM_RUN = "run"
PROCESS_FROM_PROFILE = "profile_default"
PROCESS_UNKNOWN = "unknown"


@dataclass(frozen=True)
class GlueDerivationModel:
    """One institute's complete glue-derivation configuration.

    The counterpart to `StageModel`: built once per request and threaded
    through, so every row of a worksheet reasons about the same rules
    structurally rather than by re-parsing identical settings once per row.
    """

    specs: tuple[GlueStepSpec, ...]
    rules: tuple[GlueTargetRule, ...]
    default_process: str | None
    process_property: str | None

    @property
    def test_types(self) -> frozenset[str]:
        return frozenset(spec.test_type for spec in self.specs)

    def specs_for(self, test_type: str | None) -> tuple[GlueStepSpec, ...]:
        return tuple(spec for spec in self.specs if spec.test_type == test_type)

    def derives(self, test_type: str | None) -> bool:
        return bool(self.specs_for(test_type))


def glue_model_from_settings(settings: Mapping | None) -> GlueDerivationModel:
    """Read an institute profile into a fail-closed derivation model."""
    rules = glue_targets_from_settings(settings)
    specs = glue_weight_inputs_from_settings(settings)
    if not rules or not specs:
        # Targets and inputs form one contract. A half-configured profile must
        # not compute using institute-specific assumptions from somewhere else.
        specs = ()
    return GlueDerivationModel(
        specs=specs,
        rules=rules,
        default_process=glue_process_from_settings(settings, rules),
        process_property=glue_process_property_from_settings(settings),
    )


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def process_for_run(
    model: GlueDerivationModel,
    properties: Mapping[str, Any],
    results: Mapping[str, Any],
) -> tuple[str | None, str]:
    """Which glue process a run was made with, and how we know.

    A run that names its own process wins: that is the only source that can be
    right for a historical run made with a process the institute has since
    stopped using. The value is free text in practice (the owner's mirror
    spells one such property four different ways across 132 runs), so it is
    folded to upper case before being matched against the configured rules.
    """
    configured_processes = {rule.process for rule in model.rules}
    code = model.process_property
    if code is not None:
        for source in (properties, results):
            raw = source.get(code)
            if isinstance(raw, str) and raw.strip():
                candidate = raw.strip().upper()
                if candidate in configured_processes:
                    return candidate, PROCESS_FROM_RUN
                return None, PROCESS_UNKNOWN
    if model.default_process in configured_processes:
        return model.default_process, PROCESS_FROM_PROFILE
    return None, PROCESS_UNKNOWN


def derive_run(
    model: GlueDerivationModel,
    *,
    test_type: str | None,
    type_code: str | None,
    results: Mapping[str, Any] | None,
    result_meta: Mapping[str, Any] | None = None,
    properties: Mapping[str, Any] | None = None,
    measured_at: datetime | None = None,
) -> GlueDerivation | None:
    """Derive one run, or None when the profile derives nothing for this test type.

    `results=None` means no run exists at all; every step then reports
    `verdict="unknown"` with reason `no_run` rather than disappearing, because
    the target is still worth stating to whoever is about to glue.
    """
    specs = model.specs_for(test_type)
    if not specs:
        return None
    process, source = process_for_run(model, _mapping(properties), _mapping(results))
    return derive_glue_weights(
        specs,
        model.rules,
        process=process,
        process_source=source,
        type_code=type_code,
        results=results,
        result_meta=result_meta,
        measured_at=measured_at,
    )


def derive_test_run_document(
    model: GlueDerivationModel,
    *,
    test_type: str | None,
    type_code: str | None,
    payload: Any,
    measured_at: datetime | None = None,
) -> GlueDerivation | None:
    """Derive from a raw PDB test-run document — an upload or a mirrored payload.

    Both arrive in the same shape (`results` / `result_meta` / `properties`),
    which is why a value staged from a file and a value read back from the
    mirror can never be judged by two different rules.
    """
    document = _mapping(payload)
    return derive_run(
        model,
        test_type=test_type,
        type_code=type_code,
        results=_mapping(document.get("results")),
        result_meta=_mapping(document.get("result_meta")),
        properties=_mapping(document.get("properties")),
        measured_at=measured_at,
    )
