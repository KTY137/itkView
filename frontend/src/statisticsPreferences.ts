import type { CollectiveCurveFamily } from "./measurements";

export type CollectiveDisplayMode = "representative" | "all";

const PREFIX = "itkflow.statistics.collective.display";

function key(family: CollectiveCurveFamily): string {
  return `${PREFIX}.${family}`;
}

export function readCollectiveDisplayMode(
  family: CollectiveCurveFamily,
): CollectiveDisplayMode {
  try {
    return window.localStorage.getItem(key(family)) === "all" ? "all" : "representative";
  } catch {
    return "representative";
  }
}

export function writeCollectiveDisplayMode(
  family: CollectiveCurveFamily,
  mode: CollectiveDisplayMode,
): void {
  try {
    window.localStorage.setItem(key(family), mode);
  } catch {
    // A blocked preference store must not make the chart unusable.
  }
}
