import type { ComponentOut, ProductionStatusReason } from "./api";
import { t } from "./i18n";
import { stageLabel } from "./ui";

function reasonText(reason: ProductionStatusReason): string | null {
  switch (reason.code) {
    case "required_test_failed":
      return t.components.productionReasonFailed(
        reason.test_type ?? "Required test",
        stageLabel(reason.stage),
      );
    case "required_test_missing":
      return t.components.productionReasonMissing(
        reason.test_type ?? "Required test",
        stageLabel(reason.stage),
      );
    case "unknown_stage":
      return t.components.productionReasonUnknownStage(stageLabel(reason.stage));
    case "missing_profile":
      return t.components.productionReasonMissingProfile;
    case "stale_mirror":
      return t.components.productionReasonStale;
    case "trashed":
      return t.components.productionReasonTrashed;
    case "provisional_profile":
      return null;
  }
}

export function productionStatusExplanation(component: ComponentOut): string {
  const label =
    component.production_status === "hold"
      ? t.components.productionHold
      : component.production_status === "incomplete"
        ? t.components.productionIncomplete
      : t.components.productionUnknown;
  const provisional =
    component.production_policy_source !== "missing_profile" &&
    component.production_policy_approved !== true
      ? ` · ${t.components.productionProvisional}`
      : "";
  const reasons = (component.production_status_reasons ?? [])
    .map(reasonText)
    .filter((reason): reason is string => reason !== null);
  const visible = reasons.slice(0, 3);
  if (reasons.length > visible.length) {
    visible.push(t.components.productionMoreReasons(reasons.length - visible.length));
  }
  const detail = visible.length > 0 ? `: ${visible.join("; ")}` : "";
  const configuredHint =
    component.production_policy_source === "missing_profile"
      ? ""
      : ` ${t.components.productionConfiguredHint}`;
  return `${label}${provisional}${detail}.${configuredHint}`;
}

export function hasProductionStatusAttention(component: ComponentOut): boolean {
  if (
    component.production_status === "hold" ||
    component.production_status === "incomplete"
  ) {
    return true;
  }
  if (component.production_status !== "unknown") return false;
  return (component.production_status_reasons ?? []).some(
    (reason) => reason.code !== "provisional_profile",
  );
}

export function ProductionStatusMarker({
  component,
  mode = "compact",
}: {
  component: ComponentOut;
  mode?: "icon" | "compact" | "full";
}) {
  if (!hasProductionStatusAttention(component)) {
    return null;
  }
  const title = productionStatusExplanation(component);
  const label =
    component.production_status === "hold"
      ? t.components.productionHold
      : component.production_status === "incomplete"
        ? t.components.productionIncomplete
      : t.components.productionUnknown;
  const visibleLabel =
    mode === "full"
      ? label
      : mode === "compact"
        ? component.production_status === "hold"
          ? "Hold"
          : component.production_status === "incomplete"
            ? t.components.productionIncompleteShort
          : t.components.productionUnknownShort
        : null;
  return (
    <span
      className={`production-status-marker ${component.production_status} ${mode}`}
      role="img"
      title={title}
      aria-label={title}
    >
      <span aria-hidden="true">
        {component.production_status === "incomplete" ? "ℹ" : "!"}
      </span>
      {visibleLabel !== null && <span aria-hidden="true">{visibleLabel}</span>}
    </span>
  );
}
