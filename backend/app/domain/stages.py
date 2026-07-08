"""Stage-move suggestion engine — pure domain logic, institute-agnostic.

A component may advance to the next production stage once every test its
*current* stage requires has been recorded as passed. This module answers, for
one component: which required tests are passed / failed / still missing, and
whether a stage move is therefore suggested.

Everything site-specific — the stage order and the required tests per stage —
is *profile data*, never hardcoded per institute (hard rule #4). The constants
below are a seed default (endcap strip module, taken from the itkFlow UI design
reference); an `InstituteProfile.settings` entry overrides them.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum


class TestStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"  # recorded but did not pass — blocks the move, needs review
    MISSING = "missing"  # never recorded for this component


@dataclass(frozen=True)
class StageModel:
    """Ordered production stages and the tests each one requires."""

    order: tuple[str, ...]
    required_tests: Mapping[str, tuple[str, ...]]

    def next_stage(self, stage: str) -> str | None:
        if stage not in self.order:
            return None
        index = self.order.index(stage)
        return self.order[index + 1] if index + 1 < len(self.order) else None

    def requirements_through(self, stage: str) -> list[tuple[str, str]]:
        """(stage, test_type) pairs up to and including `stage`, in order.

        Lets a detail view show the requirement roadmap so far, not just the
        current stage. Unknown stages fall back to their own requirements only.
        """
        if stage not in self.order:
            return [(stage, test) for test in self.required_tests.get(stage, ())]
        upto = self.order[: self.order.index(stage) + 1]
        return [(s, test) for s in upto for test in self.required_tests.get(s, ())]


# --- Seed default (endcap strip module) -----------------------------------
# Overridable per institute via InstituteProfile.settings:
#   settings["stage_order"]        -> list[str]
#   settings["stage_requirements"] -> {stage: [test_type, ...]}
DEFAULT_STAGE_ORDER: tuple[str, ...] = (
    "HV_TAB_ATTACHED",
    "GLUED",
    "STITCH_BONDING",
    "BONDED",
    "TESTED",
    "FINISHED",
)

DEFAULT_STAGE_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "HV_TAB_ATTACHED": ("VISUAL_INSPECTION", "MODULE_IV_PS_V1"),
    "GLUED": ("GLUE_WEIGHT", "MODULE_BOW", "MODULE_METROLOGY"),
    "STITCH_BONDING": (),
    "BONDED": ("MODULE_WIRE_BONDING",),
    "TESTED": ("MODULE_IV_AMAC_TC",),
    "FINISHED": (),
}

DEFAULT_STAGE_MODEL = StageModel(
    order=DEFAULT_STAGE_ORDER, required_tests=DEFAULT_STAGE_REQUIREMENTS
)


def stage_model_from_settings(settings: Mapping | None) -> StageModel:
    """Merge an institute profile's overrides over the seed default.

    `stage_requirements` is a per-stage replacement (not a deep merge): a stage
    present in the override uses exactly its listed tests. Absent stages keep
    the default. Invalid shapes are ignored in favour of the default so a
    malformed profile never breaks suggestions.
    """
    settings = settings or {}
    order = DEFAULT_STAGE_ORDER
    raw_order = settings.get("stage_order")
    if isinstance(raw_order, list) and all(isinstance(s, str) and s for s in raw_order):
        order = tuple(raw_order)

    requirements = dict(DEFAULT_STAGE_REQUIREMENTS)
    raw_reqs = settings.get("stage_requirements")
    if isinstance(raw_reqs, dict):
        for stage, tests in raw_reqs.items():
            if isinstance(stage, str) and isinstance(tests, list) and all(
                isinstance(t, str) for t in tests
            ):
                requirements[stage] = tuple(tests)

    # Every stage that has requirements must be placed in the order, else its
    # requirements could never be evaluated; append any stray ones at the end.
    ordered = list(order) + [s for s in requirements if s not in order]
    return StageModel(order=tuple(ordered), required_tests=requirements)


@dataclass(frozen=True)
class RequirementCheck:
    stage: str
    test_type: str
    status: TestStatus


@dataclass(frozen=True)
class StageEvaluation:
    current_stage: str
    next_stage: str | None
    checks: list[RequirementCheck]  # requirements up to and including current stage
    blocking: list[RequirementCheck]  # failed/missing at the *current* stage
    move_suggested: bool

    @property
    def suggested_stage(self) -> str | None:
        return self.next_stage if self.move_suggested else None


def _status(results: Mapping[str, bool], test_type: str) -> TestStatus:
    if test_type not in results:
        return TestStatus.MISSING
    return TestStatus.PASSED if results[test_type] else TestStatus.FAILED


def evaluate_stage(
    current_stage: str, results: Mapping[str, bool], model: StageModel
) -> StageEvaluation:
    """Evaluate one component's stage-move readiness.

    `results` maps a test type to whether its latest run passed. A stage move
    is suggested only when *every* test the current stage requires is passed
    and a next stage exists.
    """
    checks = [
        RequirementCheck(stage=stage, test_type=test, status=_status(results, test))
        for stage, test in model.requirements_through(current_stage)
    ]
    blocking = [
        check
        for check in checks
        if check.stage == current_stage and check.status is not TestStatus.PASSED
    ]
    next_stage = model.next_stage(current_stage)
    move_suggested = not blocking and next_stage is not None
    return StageEvaluation(
        current_stage=current_stage,
        next_stage=next_stage,
        checks=checks,
        blocking=blocking,
        move_suggested=move_suggested,
    )
