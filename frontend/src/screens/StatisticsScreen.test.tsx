import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  MeasurementDimensions,
  MeasurementSeries,
  ProductionStats,
  StatsDimensions,
} from "../api";
import StatisticsScreen from "./StatisticsScreen";

const apiMocks = vi.hoisted(() => ({
  getMeasurementDimensions: vi.fn(),
  getMeasurementSeries: vi.fn(),
  getProductionStats: vi.fn(),
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
    apiMocks.getStatsDimensions.mockResolvedValue(productionDimensions);
    apiMocks.getProductionStats.mockResolvedValue(productionStats);
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

    await waitFor(() =>
      expect(apiMocks.getMeasurementSeries).toHaveBeenCalledWith(
        { test_type: "IV_LARGE", result: "CURRENT", x_result: "VOLTAGE" },
        expect.any(AbortSignal),
      ),
    );
    expect(apiMocks.getMeasurementSeries).toHaveBeenCalledWith(
      { test_type: "CV_SCAN", result: "CAP", x_result: "BIAS_VOLTAGE" },
      expect.any(AbortSignal),
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
        expect.any(AbortSignal),
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

    apiMocks.getMeasurementDimensions.mockRejectedValue(new Error("mirror unavailable"));
    render(<StatisticsScreen />);

    expect(await screen.findByRole("heading", { name: "Collective IV curves" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Collective CV curves" })).toBeVisible();
    const error = await screen.findByRole("alert");
    expect(error).toHaveTextContent("Could not load measurements: mirror unavailable");
    expect(screen.getAllByText("Could not load measurements: mirror unavailable")).toHaveLength(3);
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

    apiMocks.getMeasurementSeries.mockRejectedValue(new Error("series unavailable"));
    render(<StatisticsScreen />);

    await waitFor(() => expect(screen.getAllByRole("alert")).toHaveLength(3));
    expect(screen.getAllByText("Could not load measurements: series unavailable")).toHaveLength(3);
  });
});
