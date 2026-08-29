// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
// SPDX-FileComment: itkflow-3f4389bba746
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  MeasurementDimensions,
  MeasurementSeries,
  ProductionStats,
  RequiredTestStats,
  StatsDimensions,
} from "../api";
import { clearMeasurementCache } from "../measurementCache";
import StatisticsScreen from "./StatisticsScreen";

const apiMocks = vi.hoisted(() => ({
  getMeasurementDimensions: vi.fn(),
  getMeasurementSeries: vi.fn(),
  getProductionStats: vi.fn(),
  getRequiredTestStats: vi.fn(),
  getStatsDimensions: vi.fn(),
}));

vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api")>();
  return { ...actual, ...apiMocks };
});

const productionDimensions: StatsDimensions = {
  component_types: ["MODULE"],
  type_codes: [],
  institutes: [],
};

const productionStats: ProductionStats = {
  component_type: "MODULE",
  type_code: null,
  institute: null,
  target_stage: "FINISHED",
  bucket: "month",
  components_tracked: 3,
  stage_order: ["READY", "FINISHED"],
  throughput: [],
  lead_time: { count: 0, median_days: null, p25_days: null, p75_days: null },
  stage_dwell: [],
  rework: { total_components: 3, reworked_components: 0, rate: 0, by_stage: [] },
  yield_: { concluded: 0, good: 0, failed: 0, in_progress: 3, rate: null },
};

const requiredTestStats: RequiredTestStats = {
  institute: "EXAMPLE",
  denominator: "at_or_beyond_stage",
  stage_order: ["READY", "GLUED", "FINISHED"],
  rows: [
    {
      stage: "GLUED",
      test_type: "MODULE_METROLOGY",
      component_total: 10,
      passed: 6,
      failed: 1,
      missing: 3,
    },
    {
      stage: "FINISHED",
      test_type: "FINAL_VISUAL_INSPECTION",
      component_total: 0,
      passed: 0,
      failed: 0,
      missing: 0,
    },
  ],
};

const measurementDimensions: MeasurementDimensions = {
  test_types: [
    {
      test_type: "IV_SMALL",
      results: [
        { code: "CURRENT", name: "Current [nA]", kind: "array", runs: 8 },
        { code: "VOLTAGE", name: "Voltage [V]", kind: "array", runs: 8 },
      ],
    },
    {
      test_type: "IV_LARGE",
      results: [
        { code: "CURRENT", name: "Current", kind: "array", runs: 20 },
        { code: "SHUNT_VOLTAGE", name: "Shunt voltage", kind: "array", runs: 20 },
        { code: "VOLTAGE", name: "Voltage", kind: "array", runs: 20 },
      ],
    },
    {
      test_type: "CV_SCAN",
      results: [
        { code: "CAP", name: "Capacitance", kind: "array", runs: 6 },
        { code: "BIAS_VOLTAGE", name: "Voltage", kind: "array", runs: 6 },
      ],
    },
  ],
};

function arraySeries(
  testType: string,
  result: string,
  xResult: string,
  {
    includeUnpaired = false,
    truncated = false,
  }: { includeUnpaired?: boolean; truncated?: boolean } = {},
): MeasurementSeries {
  return {
    test_type: testType,
    result_code: result,
    kind: "array",
    result_name: result === "CAP" ? "Capacitance" : "Current",
    x_result: xResult,
    x_name: "Voltage",
    curves: [
      {
        component_sn: "ANON-1",
        local_name: "Example 1",
        external_ref: "RUN-1",
        measured_at: "2026-08-01T00:00:00Z",
        passed: true,
        x: [0, 10],
        y: [1, 2],
      },
      ...(includeUnpaired
        ? [
            {
              component_sn: "ANON-2",
              local_name: "Example 2",
              external_ref: "RUN-2",
              measured_at: "2026-08-02T00:00:00Z",
              passed: true,
              x: null,
              y: [2, 3],
            },
          ]
        : []),
    ],
    values: [],
    summary: null,
    truncated,
  };
}

describe("StatisticsScreen collective curves", () => {
  beforeEach(() => {
    clearMeasurementCache();
    window.localStorage.clear();
    apiMocks.getStatsDimensions.mockResolvedValue(productionDimensions);
    apiMocks.getProductionStats.mockResolvedValue(productionStats);
    apiMocks.getRequiredTestStats.mockResolvedValue({
      ...requiredTestStats,
      rows: [],
    });
    apiMocks.getMeasurementDimensions.mockResolvedValue(measurementDimensions);
    apiMocks.getMeasurementSeries.mockImplementation(
      async (query: { test_type: string; result: string; x_result?: string }) =>
        arraySeries(query.test_type, query.result, query.x_result ?? "", {
          includeUnpaired: query.test_type === "IV_LARGE",
          truncated: query.test_type === "IV_LARGE",
        }),
    );
  });

  it("shows explicit IV/CV panels, chooses the strongest semantic pair, and excludes unpaired runs", async () => {
    render(<StatisticsScreen />);

    expect(await screen.findByRole("heading", { name: "Collective IV curves" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Collective CV curves" })).toBeVisible();
    const explorerHeading = await screen.findByRole("heading", { name: "Measurements" });
    const collectiveHeading = screen.getByRole("heading", {
      name: "Collective IV and CV curves",
    });
    expect(
      explorerHeading.compareDocumentPosition(collectiveHeading) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).not.toBe(0);

    await waitFor(() =>
      expect(apiMocks.getMeasurementSeries).toHaveBeenCalledWith(
        { test_type: "IV_LARGE", result: "CURRENT", x_result: "VOLTAGE" },
      ),
    );
    expect(apiMocks.getMeasurementSeries).toHaveBeenCalledWith(
      { test_type: "CV_SCAN", result: "CAP", x_result: "BIAS_VOLTAGE" },
    );
    expect(await screen.findByText(/1 run was excluded because its axis arrays could not be paired/i)).toBeVisible();
    expect(
      screen.getByText("The endpoint checked the newest 2 runs; older runs were not returned."),
    ).toBeVisible();
    expect(screen.queryByText(/Showing the newest 1 run/u)).toBeNull();
    const ivCard = screen.getByRole("heading", { name: "Collective IV curves" }).closest("section");
    expect(ivCard).not.toBeNull();
    expect(
      within(ivCard as HTMLElement).getByRole("img", {
        name: /Current vs Voltage — 1 run overlaid; passed \(1\); failed \(0\)/i,
      }),
    ).toBeVisible();
    expect(within(ivCard as HTMLElement).getByText("passed (1)").closest(".curve-legend")).not.toHaveAttribute(
      "aria-hidden",
    );

    const user = userEvent.setup();
    await user.selectOptions(screen.getAllByLabelText("PDB test schema")[0], "IV_SMALL");
    await waitFor(() =>
      expect(apiMocks.getMeasurementSeries).toHaveBeenCalledWith(
        { test_type: "IV_SMALL", result: "CURRENT", x_result: "VOLTAGE" },
      ),
    );
  });

  it("keeps both collective panels visible with honest empty states", async () => {
    apiMocks.getMeasurementDimensions.mockResolvedValue({ test_types: [] });
    render(<StatisticsScreen />);

    expect(await screen.findByText(/no mirrored test schema contains paired current and voltage/i)).toBeVisible();
    expect(screen.getByText(/no mirrored test schema contains paired capacitance and voltage/i)).toBeVisible();
    expect(screen.getByRole("heading", { name: "Measurements" })).toBeVisible();
    expect(apiMocks.getMeasurementSeries).not.toHaveBeenCalled();
  });

  it("keeps both collective cards mounted while dimensions load and when they fail", async () => {
    apiMocks.getMeasurementDimensions.mockImplementation(
      () => new Promise<MeasurementDimensions>(() => undefined),
    );
    const { unmount } = render(<StatisticsScreen />);

    expect(await screen.findByRole("heading", { name: "Collective IV curves" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Collective CV curves" })).toBeVisible();
    expect(screen.getAllByRole("status")).toHaveLength(2);
    unmount();

    clearMeasurementCache();
    apiMocks.getMeasurementDimensions.mockRejectedValue(new Error("mirror unavailable"));
    render(<StatisticsScreen />);

    expect(await screen.findByRole("heading", { name: "Collective IV curves" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Collective CV curves" })).toBeVisible();
    const errors = await screen.findAllByText("Could not load measurements: mirror unavailable");
    expect(errors).toHaveLength(3);
  });

  it("shows the endpoint cap even when every returned collective run is unpaired", async () => {
    apiMocks.getMeasurementSeries.mockImplementation(
      async (query: { test_type: string; result: string; x_result?: string }) => {
        const result = arraySeries(query.test_type, query.result, query.x_result ?? "");
        if (query.test_type !== "IV_LARGE") return result;
        return {
          ...result,
          curves: [{ ...result.curves[0], x: null }],
          truncated: true,
        };
      },
    );
    render(<StatisticsScreen />);

    expect(await screen.findByText(/no mirrored run contains a same-length pair/i)).toBeVisible();
    expect(
      screen.getByText("The endpoint checked the newest 1 run; older runs were not returned."),
    ).toBeVisible();
    expect(
      screen.getByText(/1 run was excluded because its axis arrays could not be paired/i),
    ).toBeVisible();
  });

  it("announces per-series loading and failures inside each persistent card", async () => {
    apiMocks.getMeasurementSeries.mockImplementation(
      () => new Promise<MeasurementSeries>(() => undefined),
    );
    const { unmount } = render(<StatisticsScreen />);

    const ivCard = (await screen.findByRole("heading", { name: "Collective IV curves" }))
      .closest("section") as HTMLElement;
    const cvCard = screen.getByRole("heading", { name: "Collective CV curves" })
      .closest("section") as HTMLElement;
    const explorer = (await screen.findByRole("heading", { name: "Measurements" }))
      .closest("section") as HTMLElement;
    expect(await within(ivCard).findByRole("status")).toBeVisible();
    expect(within(cvCard).getByRole("status")).toBeVisible();
    expect(within(explorer).getByRole("status")).toBeVisible();
    unmount();

    clearMeasurementCache();
    apiMocks.getMeasurementSeries.mockRejectedValue(new Error("series unavailable"));
    render(<StatisticsScreen />);

    await waitFor(() => expect(screen.getAllByRole("alert")).toHaveLength(3));
    expect(screen.getAllByText("Could not load measurements: series unavailable")).toHaveLength(3);
  });

  it("defaults to a readable representative sample, includes failures, and persists All returned", async () => {
    apiMocks.getMeasurementSeries.mockImplementation(
      async (query: { test_type: string; result: string; x_result?: string }) => {
        const base = arraySeries(query.test_type, query.result, query.x_result ?? "");
        if (query.test_type !== "IV_LARGE") return base;
        return {
          ...base,
          curves: Array.from({ length: 40 }, (_, index) => ({
            ...base.curves[0],
            external_ref: `RUN-${index}`,
            component_sn: `ANON-${index}`,
            passed: index !== 39,
            y: [index, index + 1],
          })),
        };
      },
    );
    const { unmount } = render(
      <StatisticsScreen measurementRevision="revision-1" measurementCacheScope="user:1" />,
    );

    const ivCard = (await screen.findByRole("heading", { name: "Collective IV curves" }))
      .closest("section") as HTMLElement;
    expect(
      await within(ivCard).findByText(
        "Showing 32 representative curves from 40 pairable of 40 returned runs; failed runs are included when present.",
      ),
    ).toBeVisible();
    expect(ivCard.querySelectorAll(".curve-chart polyline.curve-line")).toHaveLength(32);
    expect(within(ivCard).getByText("failed (1)")).toBeVisible();

    const user = userEvent.setup();
    await user.selectOptions(within(ivCard).getByLabelText("Curve display"), "all");
    expect(
      within(ivCard).getByText("Showing all 40 pairable curves from 40 returned runs."),
    ).toBeVisible();
    expect(ivCard.querySelectorAll(".curve-chart polyline.curve-line")).toHaveLength(40);
    expect(window.localStorage.getItem("itkflow.statistics.collective.display.iv")).toBe("all");

    const callsAfterFirstMount = apiMocks.getMeasurementSeries.mock.calls.length;
    unmount();
    render(<StatisticsScreen measurementRevision="revision-1" measurementCacheScope="user:1" />);

    const remountedIvCard = (await screen.findByRole("heading", { name: "Collective IV curves" }))
      .closest("section") as HTMLElement;
    expect(await within(remountedIvCard).findByLabelText("Curve display")).toHaveValue("all");
    await waitFor(() => {
      expect(remountedIvCard.querySelectorAll(".curve-chart polyline.curve-line")).toHaveLength(40);
      expect(apiMocks.getMeasurementSeries).toHaveBeenCalledTimes(callsAfterFirstMount);
    });
  });

  it("renders profile-backed REQUIRED coverage before measurements and scopes it by institute", async () => {
    apiMocks.getRequiredTestStats.mockResolvedValue(requiredTestStats);

    render(<StatisticsScreen instituteCode="EXAMPLE" />);

    const requiredHeading = await screen.findByRole("heading", {
      name: "REQUIRED test coverage",
    });
    const measurementsHeading = await screen.findByRole("heading", { name: "Measurements" });
    expect(
      requiredHeading.compareDocumentPosition(measurementsHeading) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).not.toBe(0);
    expect(apiMocks.getRequiredTestStats).toHaveBeenCalledWith(
      "EXAMPLE",
      expect.any(AbortSignal),
    );
    expect(screen.getByText("EXAMPLE · cohort: components at or beyond each configured stage")).toBeVisible();

    const metrologyRow = screen.getByText("MODULE_METROLOGY").closest("tr");
    expect(metrologyRow).not.toBeNull();
    expect(within(metrologyRow as HTMLElement).getByText("Glued")).toBeVisible();
    expect(within(metrologyRow as HTMLElement).getByText("10")).toBeVisible();
    expect(within(metrologyRow as HTMLElement).getByText("6")).toBeVisible();
    expect(within(metrologyRow as HTMLElement).getByText("1")).toBeVisible();
    expect(within(metrologyRow as HTMLElement).getByText("3")).toBeVisible();
    expect(within(metrologyRow as HTMLElement).getByText("60 %")).toBeVisible();
    expect(
      within(metrologyRow as HTMLElement).getByRole("img", {
        name: "MODULE_METROLOGY at Glued: 6 passed, 1 failed, 3 missing out of 10 components",
      }),
    ).toBeVisible();

    const emptyCohortRow = screen.getByText("FINAL_VISUAL_INSPECTION").closest("tr");
    expect(emptyCohortRow).not.toBeNull();
    expect(within(emptyCohortRow as HTMLElement).getByText("—")).toBeVisible();
  });

  it("retries only the failed REQUIRED coverage request", async () => {
    apiMocks.getRequiredTestStats
      .mockRejectedValueOnce(new Error("coverage unavailable"))
      .mockResolvedValueOnce(requiredTestStats);

    render(<StatisticsScreen instituteCode="EXAMPLE" />);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(
      "Could not load REQUIRED test coverage: coverage unavailable",
    );
    await userEvent.setup().click(within(alert).getByRole("button", { name: "Retry" }));

    expect(await screen.findByText("MODULE_METROLOGY")).toBeVisible();
    expect(apiMocks.getRequiredTestStats).toHaveBeenCalledTimes(2);
    expect(apiMocks.getProductionStats).toHaveBeenCalledTimes(1);
  });
});
