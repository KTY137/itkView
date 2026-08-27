/**
 * Read-only presentation of a server-computed glue derivation.
 *
 * This module deliberately contains formatting only. Targets, tolerances,
 * measured glue weights and verdicts all arrive from the backend; keeping the
 * arithmetic out of the browser prevents the worksheet, dry-run and approval
 * surfaces from drifting apart.
 */
import type {
  WorksheetDerived,
  WorksheetDerivedInput,
  WorksheetDerivedStep,
} from "./api";
import { t } from "./i18n";
import { formatScalar } from "./TestResults";

export type DerivedSource = "preview" | "latest_run" | "staged";

const VERDICT_CHIP_CLASS: Record<WorksheetDerivedStep["verdict"], string> = {
  ok: "chip green",
  too_little: "chip red",
  too_much: "chip red",
  // Never neutral: a missing input must not read like a passing result.
  unknown: "chip amber",
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isNullableFiniteNumber(value: unknown): value is number | null {
  return value === null || (typeof value === "number" && Number.isFinite(value));
}

function parseDerivedInput(value: unknown): WorksheetDerivedInput | null {
  if (!isRecord(value)) return null;
  if (typeof value.code !== "string" || typeof value.name !== "string") return null;
  if (!isNullableFiniteNumber(value.value)) return null;
  return { code: value.code, name: value.name, value: value.value };
}

function parseDerivedStep(value: unknown): WorksheetDerivedStep | null {
  if (!isRecord(value)) return null;
  if (typeof value.key !== "string" || typeof value.label !== "string") return null;
  if (!isNullableFiniteNumber(value.measured_mg)) return null;
  if (!isNullableFiniteNumber(value.target_mg)) return null;
  if (!isNullableFiniteNumber(value.tolerance_mg)) return null;
  if (!(["ok", "too_little", "too_much", "unknown"] as const).includes(
    value.verdict as WorksheetDerivedStep["verdict"],
  )) return null;
  if (value.reason !== null && typeof value.reason !== "string") return null;
  if (
    value.result_code !== undefined &&
    value.result_code !== null &&
    typeof value.result_code !== "string"
  ) return null;
  if (!Array.isArray(value.inputs)) return null;
  const inputs = value.inputs.map(parseDerivedInput);
  if (inputs.some((input) => input === null)) return null;
  return {
    key: value.key,
    label: value.label,
    measured_mg: value.measured_mg,
    target_mg: value.target_mg,
    tolerance_mg: value.tolerance_mg,
    verdict: value.verdict as WorksheetDerivedStep["verdict"],
    reason: value.reason,
    result_code:
      typeof value.result_code === "string" || value.result_code === null
        ? value.result_code
        : undefined,
    inputs: inputs as WorksheetDerivedInput[],
  };
}

/**
 * Narrow the untyped JSON stored in an outbox payload before rendering it.
 * Older or malformed actions simply omit the derivation instead of crashing
 * the whole approval queue or presenting a partial server judgement.
 */
export function parseWorksheetDerived(value: unknown): WorksheetDerived | null {
  if (!isRecord(value) || value.kind !== "glue_weight") return null;
  if (value.process !== null && typeof value.process !== "string") return null;
  if (!(["run", "profile_default", "unknown"] as const).includes(
    value.process_source as WorksheetDerived["process_source"],
  )) return null;
  if (!Array.isArray(value.steps)) return null;
  const steps = value.steps.map(parseDerivedStep);
  if (steps.some((step) => step === null)) return null;
  return {
    kind: "glue_weight",
    process: value.process,
    process_source: value.process_source as WorksheetDerived["process_source"],
    steps: steps as WorksheetDerivedStep[],
  };
}

/**
 * The verdict as a word. `unknown` resolves to its reason rather than to a
 * blank or a bare "unknown" — an absent reading must never look like a pass.
 */
function verdictLabel(step: WorksheetDerivedStep): string {
  switch (step.verdict) {
    case "ok":
      return t.worksheet.verdictOk;
    case "too_little":
      return t.worksheet.verdictTooLittle;
    case "too_much":
      return t.worksheet.verdictTooMuch;
    case "unknown":
      break;
  }
  switch (step.reason) {
    case "no_target":
      return t.worksheet.verdictNoTarget;
    case "missing_inputs":
      return t.worksheet.verdictMissingInputs;
    case "implausible_result":
      return t.worksheet.verdictImplausible;
    case "no_run":
      return t.worksheet.verdictNoRun;
    case null:
      return t.worksheet.verdictUnknown;
    default:
      return t.worksheet.verdictUnknownReason(step.reason);
  }
}

/** Formatting only: `formatScalar` trims float noise, but changes no value. */
function derivedNumber(value: number | null): string {
  return value === null ? t.common.none : formatScalar(value);
}

/** Keep target and tolerance verbatim; the browser never resolves a band. */
function derivedFigure(step: WorksheetDerivedStep): string {
  return t.worksheet.derivedFigure(
    derivedNumber(step.measured_mg),
    step.target_mg === null ? null : derivedNumber(step.target_mg),
    step.tolerance_mg === null ? null : derivedNumber(step.tolerance_mg),
  );
}

/** Compact server verdict used in worksheet and staged-action summaries. */
export function DerivedVerdicts({ derived }: { derived: WorksheetDerived }) {
  if (derived.steps.length === 0) return null;
  return (
    <span className="ws-derived">
      {derived.steps.map((step) => (
        <span
          className="ws-derived-step"
          key={step.key}
          title={t.worksheet.derivedStepTitle(step.label, verdictLabel(step))}
        >
          <span className={VERDICT_CHIP_CLASS[step.verdict]}>{verdictLabel(step)}</span>
          <span className="ws-val-name">{step.label}</span>
          <span className="mono">{derivedFigure(step)}</span>
        </span>
      ))}
    </span>
  );
}

function derivedProcessSourceLabel(source: WorksheetDerived["process_source"]): string {
  switch (source) {
    case "run":
      return t.worksheet.derivedProcessFromRun;
    case "profile_default":
      return t.worksheet.derivedProcessFromProfile;
    case "unknown":
      return t.worksheet.derivedProcessUnknownSource;
  }
}

/** Detailed read-only server derivation used next to reviewable raw readings. */
export function DerivedDetail({
  derived,
  source,
}: {
  derived: WorksheetDerived;
  source: DerivedSource;
}) {
  const sourceNote =
    source === "preview"
      ? t.worksheet.derivedFromPreview
      : source === "staged"
        ? t.worksheet.derivedFromStaged
        : t.worksheet.derivedFromLatestRun;
  return (
    <div className="ws-derived-detail">
      <div className="field-label">{t.worksheet.derivedTitle}</div>
      <p className="muted ws-derived-note">{sourceNote}</p>
      <p className="ws-derived-process">
        <span className="ws-val-name">{t.worksheet.derivedProcessLabel}</span>{" "}
        <span className="mono">
          {derived.process ?? t.worksheet.derivedProcessUnresolved}
        </span>{" "}
        <span className="chip neutral">{derivedProcessSourceLabel(derived.process_source)}</span>
      </p>
      {derived.steps.length === 0 ? (
        <p className="state-note">{t.worksheet.derivedNoSteps}</p>
      ) : (
        <ul className="ws-derived-steps">
          {derived.steps.map((step) => (
            <li key={step.key}>
              <div className="ws-derived-step-head">
                <span className={VERDICT_CHIP_CLASS[step.verdict]}>{verdictLabel(step)}</span>
                <span className="ws-derived-step-label">{step.label}</span>
              </div>
              <dl className="ws-derived-figures">
                <dt>{t.worksheet.derivedWeightLabel}</dt>
                <dd className="mono">
                  {step.measured_mg === null
                    ? t.common.none
                    : t.worksheet.derivedMg(derivedNumber(step.measured_mg))}
                </dd>
                <dt>{t.worksheet.derivedTargetLabel}</dt>
                <dd className="mono">
                  {step.target_mg === null
                    ? t.common.none
                    : t.worksheet.derivedMg(derivedNumber(step.target_mg))}
                </dd>
                <dt>{t.worksheet.derivedToleranceLabel}</dt>
                <dd className="mono">
                  {step.tolerance_mg === null
                    ? t.common.none
                    : t.worksheet.derivedToleranceMg(derivedNumber(step.tolerance_mg))}
                </dd>
                {step.inputs.length > 0 && (
                  <>
                    <dt>{t.worksheet.derivedInputsLabel}</dt>
                    <dd className="ws-derived-inputs">
                      {step.inputs.map((input) => (
                        <span className="ws-val" key={input.code} title={input.code}>
                          <span className="ws-val-name">{input.name}</span>{" "}
                          <span className="mono">{formatScalar(input.value)}</span>
                        </span>
                      ))}
                    </dd>
                  </>
                )}
              </dl>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
