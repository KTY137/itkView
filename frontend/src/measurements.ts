/** Pure helpers for the measurement charts on the Statistics screen.
 *
 * Kept free of React/DOM so the geometry is unit-testable: curves are scaled
 * into an SVG viewBox, scalars are binned into a histogram. */

import type {
  MeasurementCurve,
  MeasurementDimensions,
  MeasurementResultDimension,
  MeasurementValue,
} from "./api";

export type CurveGeometry = {
  /** SVG polyline points strings, same order as the input curves. */
  points: string[];
  xMin: number;
  xMax: number;
  yMin: number;
  yMax: number;
};

export type CollectiveCurveFamily = "iv" | "cv";

export type CollectiveCurveCandidate = {
  family: CollectiveCurveFamily;
  testType: string;
  xResult: MeasurementResultDimension;
  yResult: MeasurementResultDimension;
  /** Upper bound from the dimension counts; exact pairing is checked per run. */
  runs: number;
};

export const REPRESENTATIVE_CURVE_LIMIT = 32;

function evenlySpacedIndices(indices: number[], count: number): number[] {
  if (count <= 0 || indices.length === 0) return [];
  if (indices.length <= count) return indices;
  if (count === 1) return [indices[0]];
  return Array.from({ length: count }, (_, position) =>
    indices[Math.round((position * (indices.length - 1)) / (count - 1))],
  );
}

/**
 * A deterministic readable subset for the collective charts. The API returns
 * newest-first, so evenly spacing indices keeps the whole returned time span
 * visible. Up to one quarter of the budget is reserved for failed runs before
 * the general sample is filled; a failure therefore cannot disappear merely
 * because passed runs dominate the population.
 */
export function representativeCurves(
  curves: MeasurementCurve[],
  limit = REPRESENTATIVE_CURVE_LIMIT,
): MeasurementCurve[] {
  const bounded = Math.max(1, Math.floor(limit));
  if (curves.length <= bounded) return curves;

  const allIndices = curves.map((_, index) => index);
  const failedIndices = allIndices.filter((index) => !curves[index].passed);
  const failedBudget = Math.min(failedIndices.length, Math.max(1, Math.floor(bounded / 4)));
  const picked = new Set(evenlySpacedIndices(failedIndices, failedBudget));

  // Sample the remaining population with the remaining budget. Because the
  // sets cannot overlap, both ends of the returned time span stay eligible
  // even when the reserved failures sit near the newest end.
  const remainingIndices = allIndices.filter((index) => !picked.has(index));
  for (const index of evenlySpacedIndices(remainingIndices, bounded - picked.size)) {
    picked.add(index);
  }
  return [...picked].sort((left, right) => left - right).map((index) => curves[index]);
}

const CURVE_FAMILY_RESULTS: Record<
  CollectiveCurveFamily,
  { x: "voltage"; y: "current" | "capacitance" }
> = {
  iv: { x: "voltage", y: "current" },
  cv: { x: "voltage", y: "capacitance" },
};

function semanticScore(result: MeasurementResultDimension, wanted: string): number {
  const normalize = (value: string) => value.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
  const code = normalize(result.code);
  const name = normalize(result.name ?? "");
  if (code === wanted) return 100;
  if (name === wanted) return 90;
  if (code.split(" ").includes(wanted)) return 70;
  if (name.split(" ").includes(wanted)) return 60;
  return 0;
}

function hasFamilyMarker(
  testType: string,
  xResult: MeasurementResultDimension,
  yResult: MeasurementResultDimension,
  family: CollectiveCurveFamily,
): boolean {
  const tokens = (value: string) =>
    value.toLowerCase().split(/[^a-z0-9]+/).filter((token) => token !== "");
  if (tokens(testType).includes(family)) return true;
  // Some older schemas use a generic test-type name but carry the family on
  // both axes (for example IV_CURRENT + IV_VOLTAGE).
  return tokens(xResult.code).includes(family) && tokens(yResult.code).includes(family);
}

/** Discover curve datasets by measured quantity, never by institute or exact
 * PDB test-type code. Schemas stay separate because their units and sweep
 * protocols may differ; the caller lets the operator choose among them. */
export function collectiveCurveCandidates(
  dimensions: MeasurementDimensions,
  family: CollectiveCurveFamily,
): CollectiveCurveCandidate[] {
  const semantics = CURVE_FAMILY_RESULTS[family];
  const candidates: CollectiveCurveCandidate[] = [];
  for (const testType of dimensions.test_types) {
    const arrays = testType.results.filter((result) => result.kind === "array");
    const ranked = (wanted: string) =>
      arrays
        .map((result) => ({ result, score: semanticScore(result, wanted) }))
        .filter((entry) => entry.score > 0)
        .sort(
          (left, right) =>
            right.score - left.score || right.result.runs - left.result.runs ||
            left.result.code.localeCompare(right.result.code),
        )[0]?.result;
    const xResult = ranked(semantics.x);
    const yResult = ranked(semantics.y);
    if (
      xResult === undefined ||
      yResult === undefined ||
      xResult.code === yResult.code ||
      !hasFamilyMarker(testType.test_type, xResult, yResult, family)
    ) {
      continue;
    }
    candidates.push({
      family,
      testType: testType.test_type,
      xResult,
      yResult,
      runs: Math.min(xResult.runs, yResult.runs),
    });
  }
  return candidates.sort(
    (left, right) => right.runs - left.runs || left.testType.localeCompare(right.testType),
  );
}

/** Explicit IV/CV panels must never silently fall back to sample index: only
 * runs for which the backend found a same-length x array are honest pairs. */
export function pairedCurves(curves: MeasurementCurve[]): MeasurementCurve[] {
  return curves.filter((curve) => curve.x !== null && curve.x.length === curve.y.length);
}

/** Scale curves into a `width`×`height` box (y flipped for SVG). Curves
 * without an x array plot against the sample index. Degenerate ranges pad by
 * ±1 so a flat line stays visible instead of collapsing onto an edge. */
export function curveGeometry(
  curves: MeasurementCurve[],
  width: number,
  height: number,
): CurveGeometry | null {
  const pairs = curves.map((curve) => {
    const xs = curve.x ?? curve.y.map((_, index) => index);
    return { xs, ys: curve.y };
  });
  const allX = pairs.flatMap((p) => p.xs);
  const allY = pairs.flatMap((p) => p.ys);
  if (allX.length === 0 || allY.length === 0) return null;

  let xMin = Math.min(...allX);
  let xMax = Math.max(...allX);
  let yMin = Math.min(...allY);
  let yMax = Math.max(...allY);
  if (xMin === xMax) {
    xMin -= 1;
    xMax += 1;
  }
  if (yMin === yMax) {
    yMin -= 1;
    yMax += 1;
  }

  const sx = (x: number) => ((x - xMin) / (xMax - xMin)) * width;
  const sy = (y: number) => height - ((y - yMin) / (yMax - yMin)) * height;
  const points = pairs.map((pair) =>
    pair.xs
      .map((x, index) => `${sx(x).toFixed(1)},${sy(pair.ys[index]).toFixed(1)}`)
      .join(" "),
  );
  return { points, xMin, xMax, yMin, yMax };
}

export type HistogramBin = { start: number; end: number; count: number };

/** Equal-width bins over the value range; a single distinct value still gets
 * one full bin. Returns [] for no values. */
export function histogramBins(values: MeasurementValue[], binCount: number): HistogramBin[] {
  const numbers = values.map((entry) => entry.value);
  if (numbers.length === 0) return [];
  let min = Math.min(...numbers);
  let max = Math.max(...numbers);
  if (min === max) {
    min -= 0.5;
    max += 0.5;
  }
  const bins: HistogramBin[] = Array.from({ length: binCount }, (_, index) => ({
    start: min + ((max - min) * index) / binCount,
    end: min + ((max - min) * (index + 1)) / binCount,
    count: 0,
  }));
  for (const value of numbers) {
    const index = Math.min(binCount - 1, Math.floor(((value - min) / (max - min)) * binCount));
    bins[index].count += 1;
  }
  return bins;
}

/** Compact number for axis/summary labels: 3 significant digits, no
 * exponent noise for everyday magnitudes. */
export function compactNumber(value: number): string {
  if (!Number.isFinite(value)) return "–";
  const absolute = Math.abs(value);
  if (absolute !== 0 && (absolute >= 100000 || absolute < 0.01)) {
    return value.toExponential(1);
  }
  const rounded = Number.parseFloat(value.toPrecision(3));
  return String(rounded);
}

/** Default x-axis result for a y result: the first OTHER array code, so an IV
 * pick of CURRENT lands on VOLTAGE automatically. */
export function defaultXResult(
  resultCodes: { code: string; kind: string }[],
  yCode: string,
): string | null {
  const other = resultCodes.find((entry) => entry.kind === "array" && entry.code !== yCode);
  return other ? other.code : null;
}
