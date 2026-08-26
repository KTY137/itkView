import { describe, expect, it } from "vitest";

import type { MeasurementCurve, MeasurementValue } from "./api";
import {
  compactNumber,
  curveGeometry,
  defaultXResult,
  histogramBins,
} from "./measurements";

function curve(y: number[], x: number[] | null = null): MeasurementCurve {
  return {
    component_sn: "20USEM00000001",
    local_name: null,
    external_ref: "R1",
    measured_at: null,
    passed: true,
    x,
    y,
  };
}

function value(v: number): MeasurementValue {
  return {
    component_sn: "20USEM00000001",
    local_name: null,
    external_ref: "R1",
    measured_at: null,
    passed: true,
    value: v,
  };
}

describe("curveGeometry", () => {
  it("scales paired x/y into the box with the y axis flipped", () => {
    const geometry = curveGeometry([curve([0, 10], [0, 100])], 200, 100);
    expect(geometry).not.toBeNull();
    expect(geometry!.points[0]).toBe("0.0,100.0 200.0,0.0");
    expect(geometry!.xMax).toBe(100);
  });

  it("falls back to the sample index when x is missing", () => {
    const geometry = curveGeometry([curve([5, 5, 5])], 100, 50);
    expect(geometry!.points[0].split(" ")).toHaveLength(3);
    expect(geometry!.xMin).toBe(0);
    expect(geometry!.xMax).toBe(2);
  });

  it("pads a flat line instead of collapsing it onto the border", () => {
    const geometry = curveGeometry([curve([7, 7], [0, 1])], 100, 50);
    expect(geometry!.yMin).toBe(6);
    expect(geometry!.yMax).toBe(8);
    expect(geometry!.points[0]).toBe("0.0,25.0 100.0,25.0");
  });

  it("returns null when there is nothing to draw", () => {
    expect(curveGeometry([], 100, 50)).toBeNull();
  });
});

describe("histogramBins", () => {
  it("bins values across the range and keeps the max in the last bin", () => {
    const bins = histogramBins([value(0), value(5), value(10)], 2);
    expect(bins).toHaveLength(2);
    expect(bins[0].count).toBe(1); // [0, 5) holds only 0
    expect(bins[1].count).toBe(2); // [5, 10] holds 5 and the max
  });

  it("gives a single distinct value one visible bin", () => {
    const bins = histogramBins([value(3), value(3)], 4);
    expect(bins.reduce((sum, bin) => sum + bin.count, 0)).toBe(2);
  });

  it("is empty for no values", () => {
    expect(histogramBins([], 4)).toEqual([]);
  });
});

describe("compactNumber", () => {
  it("keeps everyday magnitudes plain and trims to 3 significant digits", () => {
    expect(compactNumber(-54.9666)).toBe("-55");
    expect(compactNumber(0.1234)).toBe("0.123");
  });

  it("switches to exponent notation for extremes", () => {
    expect(compactNumber(1234567)).toBe("1.2e+6");
    expect(compactNumber(0.0000032)).toBe("3.2e-6");
  });
});

describe("defaultXResult", () => {
  it("prefers the first other array result (CURRENT -> VOLTAGE)", () => {
    const codes = [
      { code: "VOLTAGE", kind: "array" },
      { code: "CURRENT", kind: "array" },
      { code: "HUMIDITY", kind: "scalar" },
    ];
    expect(defaultXResult(codes, "CURRENT")).toBe("VOLTAGE");
    expect(defaultXResult(codes, "VOLTAGE")).toBe("CURRENT");
  });

  it("returns null when no other array exists", () => {
    expect(defaultXResult([{ code: "BOW", kind: "scalar" }], "BOW")).toBeNull();
  });
});
