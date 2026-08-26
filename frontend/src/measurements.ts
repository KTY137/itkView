/** Pure helpers for the measurement charts on the Statistics screen.
 *
 * Kept free of React/DOM so the geometry is unit-testable: curves are scaled
 * into an SVG viewBox, scalars are binned into a histogram. */

import type { MeasurementCurve, MeasurementValue } from "./api";

export type CurveGeometry = {
  /** SVG polyline points strings, same order as the input curves. */
  points: string[];
  xMin: number;
  xMax: number;
  yMin: number;
  yMax: number;
};

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
