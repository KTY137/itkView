import { beforeEach, describe, expect, it, vi } from "vitest";

import type { MeasurementDimensions, MeasurementSeries } from "./api";
import {
  clearMeasurementCache,
  loadMeasurementDimensions,
  loadMeasurementSeries,
} from "./measurementCache";

const apiMocks = vi.hoisted(() => ({
  getMeasurementDimensions: vi.fn(),
  getMeasurementSeries: vi.fn(),
}));

vi.mock("./api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api")>()),
  ...apiMocks,
}));

const dimensionsOne: MeasurementDimensions = {
  test_types: [
    {
      test_type: "MODULE_IV",
      results: [{ code: "CURRENT", name: "Current", kind: "array", runs: 1 }],
    },
  ],
};

const dimensionsTwo: MeasurementDimensions = {
  test_types: [
    {
      test_type: "MODULE_IV",
      results: [{ code: "CURRENT", name: "Current", kind: "array", runs: 2 }],
    },
  ],
};

function series(ref: string): MeasurementSeries {
  return {
    test_type: "MODULE_IV",
    result_code: "CURRENT",
    kind: "array",
    result_name: "Current",
    x_result: "VOLTAGE",
    x_name: "Voltage",
    curves: [
      {
        component_sn: "ANON-1",
        local_name: null,
        external_ref: ref,
        measured_at: null,
        passed: true,
        x: [0, 1],
        y: [1, 2],
      },
    ],
    values: [],
    summary: null,
    truncated: false,
  };
}

describe("measurement stale-while-revalidate cache", () => {
  beforeEach(() => {
    clearMeasurementCache();
    window.localStorage.clear();
    apiMocks.getMeasurementDimensions.mockResolvedValue(dimensionsOne);
    apiMocks.getMeasurementSeries.mockResolvedValue(series("RUN-1"));
  });

  it("reuses a matching revision across navigation/remount without another request", async () => {
    const first = loadMeasurementDimensions("user:1", "revision-1");
    expect(first.cached).toBeNull();
    expect(first.refresh).not.toBeNull();
    await first.refresh;

    const remounted = loadMeasurementDimensions("user:1", "revision-1");
    expect(remounted.cached).toEqual(dimensionsOne);
    expect(remounted.refresh).toBeNull();
    expect(apiMocks.getMeasurementDimensions).toHaveBeenCalledTimes(1);
    expect(window.localStorage.length).toBe(1);
  });

  it("renders the stale value and refreshes once in the background when the revision changes", async () => {
    await loadMeasurementDimensions("user:1", "revision-1").refresh;
    apiMocks.getMeasurementDimensions.mockResolvedValueOnce(dimensionsTwo);

    const changed = loadMeasurementDimensions("user:1", "revision-2");
    expect(changed.cached).toEqual(dimensionsOne);
    expect(changed.refresh).not.toBeNull();
    expect(apiMocks.getMeasurementDimensions).toHaveBeenCalledTimes(2);
    await changed.refresh;

    const current = loadMeasurementDimensions("user:1", "revision-2");
    expect(current.cached).toEqual(dimensionsTwo);
    expect(current.refresh).toBeNull();
  });

  it("deduplicates the same expensive series aggregation while it is in flight", async () => {
    let resolveRequest!: (value: MeasurementSeries) => void;
    apiMocks.getMeasurementSeries.mockReturnValue(
      new Promise<MeasurementSeries>((resolve) => {
        resolveRequest = resolve;
      }),
    );
    const query = { test_type: "MODULE_IV", result: "CURRENT", x_result: "VOLTAGE" };

    const first = loadMeasurementSeries("user:1", "revision-1", query);
    const second = loadMeasurementSeries("user:1", "revision-1", query);

    expect(first.refresh).toBe(second.refresh);
    expect(apiMocks.getMeasurementSeries).toHaveBeenCalledTimes(1);
    resolveRequest(series("RUN-2"));
    await first.refresh;
  });

  it("coalesces rapid revision changes behind one active aggregation", async () => {
    const resolvers: Array<(value: MeasurementDimensions) => void> = [];
    apiMocks.getMeasurementDimensions.mockImplementation(
      () =>
        new Promise<MeasurementDimensions>((resolve) => {
          resolvers.push(resolve);
        }),
    );

    const first = loadMeasurementDimensions("user:1", "revision-1");
    const second = loadMeasurementDimensions("user:1", "revision-2");
    const latest = loadMeasurementDimensions("user:1", "revision-3");

    expect(second.refresh).toBe(first.refresh);
    expect(latest.refresh).toBe(first.refresh);
    expect(apiMocks.getMeasurementDimensions).toHaveBeenCalledTimes(1);

    resolvers[0](dimensionsOne);
    await vi.waitFor(() => {
      expect(apiMocks.getMeasurementDimensions).toHaveBeenCalledTimes(2);
    });
    expect(resolvers).toHaveLength(2);

    resolvers[1](dimensionsTwo);
    await latest.refresh;

    const current = loadMeasurementDimensions("user:1", "revision-3");
    expect(current.cached).toEqual(dimensionsTwo);
    expect(current.refresh).toBeNull();
    expect(apiMocks.getMeasurementDimensions).toHaveBeenCalledTimes(2);
  });

  it("keeps a stale value after a failed refresh and retries the same revision", async () => {
    await loadMeasurementDimensions("user:1", "revision-1").refresh;
    apiMocks.getMeasurementDimensions.mockRejectedValueOnce(new Error("mirror unavailable"));

    const failed = loadMeasurementDimensions("user:1", "revision-2");
    expect(failed.cached).toEqual(dimensionsOne);
    await expect(failed.refresh).rejects.toThrow("mirror unavailable");

    apiMocks.getMeasurementDimensions.mockResolvedValueOnce(dimensionsTwo);
    const retry = loadMeasurementDimensions("user:1", "revision-2");
    expect(retry.cached).toEqual(dimensionsOne);
    expect(retry.refresh).not.toBeNull();
    await retry.refresh;

    const current = loadMeasurementDimensions("user:1", "revision-2");
    expect(current.cached).toEqual(dimensionsTwo);
    expect(current.refresh).toBeNull();
  });

  it("isolates cached mirror data between signed-in scopes", async () => {
    const query = { test_type: "MODULE_IV", result: "CURRENT", x_result: "VOLTAGE" };
    await loadMeasurementSeries("user:1", "revision-1", query).refresh;

    const otherUser = loadMeasurementSeries("user:2", "revision-1", query);
    expect(otherUser.cached).toBeNull();
    expect(otherUser.refresh).not.toBeNull();
    expect(apiMocks.getMeasurementSeries).toHaveBeenCalledTimes(2);
    await otherUser.refresh;
  });
});
