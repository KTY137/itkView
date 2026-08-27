import { describe, expect, it } from "vitest";

import type { MeasurementCurve, MeasurementValue } from "./api";
import {
  collectiveCurveCandidates,
  compactNumber,
  curveGeometry,
  defaultXResult,
  histogramBins,
  pairedCurves,
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

describe("collectiveCurveCandidates", () => {
  const dimensions = {
    test_types: [
      {
        test_type: "SENSOR_IV_A",
        results: [
          { code: "SHUNT_VOLTAGE", name: "Shunt voltage", kind: "array" as const, runs: 12 },
          { code: "VOLTAGE", name: "Voltage [V]", kind: "array" as const, runs: 12 },
          { code: "CURRENT_RMS", name: "Current RMS", kind: "array" as const, runs: 12 },
          { code: "CURRENT", name: "Current [nA]", kind: "array" as const, runs: 11 },
        ],
      },
      {
        test_type: "SENSOR_CV_B",
        results: [
          { code: "BIAS_VOLTAGE", name: "Voltage", kind: "array" as const, runs: 20 },
          { code: "CAP", name: "Capacitance", kind: "array" as const, runs: 18 },
        ],
      },
      {
        test_type: "STRIP_SCAN",
        results: [
          { code: "CURRENT", name: "Current", kind: "array" as const, runs: 99 },
          { code: "PROBE", name: "Probe index", kind: "array" as const, runs: 99 },
        ],
      },
    ],
  };

  it("finds current/voltage and capacitance/voltage pairs without exact test-type codes", () => {
    const iv = collectiveCurveCandidates(dimensions, "iv");
    expect(iv).toHaveLength(1);
    expect(iv[0]).toMatchObject({
      testType: "SENSOR_IV_A",
      xResult: { code: "VOLTAGE" },
      yResult: { code: "CURRENT" },
      runs: 11,
    });

    const cv = collectiveCurveCandidates(dimensions, "cv");
    expect(cv).toHaveLength(1);
    expect(cv[0]).toMatchObject({
      testType: "SENSOR_CV_B",
      xResult: { code: "BIAS_VOLTAGE" },
      yResult: { code: "CAP" },
      runs: 18,
    });
  });

  it("does not mistake an unpaired strip-current array for an IV curve", () => {
    expect(
      collectiveCurveCandidates(
        { test_types: [dimensions.test_types[2]] },
        "iv",
      ),
    ).toEqual([]);
  });

  it("does not label unrelated current/voltage samples as an IV sweep", () => {
    const unrelated = {
      test_types: [
        {
          test_type: "CURRENT_STABILITY",
          results: [
            { code: "CURRENT", name: "Current", kind: "array" as const, runs: 10 },
            { code: "SHUNT_VOLTAGE", name: "Shunt voltage", kind: "array" as const, runs: 10 },
          ],
        },
      ],
    };
    expect(collectiveCurveCandidates(unrelated, "iv")).toEqual([]);
  });

  it("accepts a legacy generic schema when both axes carry the IV marker", () => {
    const legacy = {
      test_types: [
        {
          test_type: "MANUFACTURING",
          results: [
            { code: "IV_CURRENT", name: "Leakage current", kind: "array" as const, runs: 7 },
            { code: "IV_VOLTAGE", name: "Bias voltage", kind: "array" as const, runs: 7 },
          ],
        },
      ],
    };
    expect(collectiveCurveCandidates(legacy, "iv")[0]).toMatchObject({
      testType: "MANUFACTURING",
      xResult: { code: "IV_VOLTAGE" },
      yResult: { code: "IV_CURRENT" },
    });
  });
});

describe("pairedCurves", () => {
  it("keeps only same-length explicit x/y pairs", () => {
    const paired = curve([1, 2], [0, 10]);
    const indexOnly = curve([1, 2]);
    const mismatch = curve([1, 2], [0]);
    expect(pairedCurves([paired, indexOnly, mismatch])).toEqual([paired]);
  });
});
