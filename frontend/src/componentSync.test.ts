/**
 * Rolling readout ("dataEpoch") of the persisted sync-job controllers.
 *
 * An evidence sweep commits each component as it arrives, so the mirror is
 * already filling while the job runs. These tests pin the contract consumers
 * rely on to show that progress: advance when the job actually moved, at most
 * once per refresh window, and never merely because a heartbeat refreshed.
 *
 * Time is driven explicitly rather than through `waitFor`, which does not
 * advance vitest's fake timers and simply blocks until the test times out.
 */
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { EvidenceSyncJob } from "./api";
import { getLatestSyncJob, getSyncJob } from "./api";
import { useEvidenceSyncJob } from "./componentSync";

vi.mock("./api", () => ({
  getLatestSyncJob: vi.fn(),
  getSyncJob: vi.fn(),
  startComponentSyncJob: vi.fn(),
  startEvidenceSyncJob: vi.fn(),
}));

const PROGRESSIVE_REFRESH_MS = 8_000;
const POLL_INTERVAL_MS = 1_000;
const FIRST_POLL_DELAY_MS = 350;

function evidenceJob(overrides: Partial<EvidenceSyncJob> = {}): EvidenceSyncJob {
  return {
    id: 7,
    kind: "evidence",
    institute_code: "EXAMPLE",
    status: "running",
    phase: "fetching",
    current: 0,
    total: 100,
    percent: 0,
    message: "Fetching detailed evidence.",
    result: null,
    error: null,
    created_at: "2026-08-27T10:00:00Z",
    started_at: "2026-08-27T10:00:00Z",
    updated_at: "2026-08-27T10:00:00Z",
    finished_at: null,
    ...overrides,
  };
}

async function settle(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

/** Mount and run far enough that discovery landed and the throttle is armed. */
async function mountRunning() {
  const hook = renderHook(() => useEvidenceSyncJob(true));
  await settle(0); // discovery resolves (its first attempt has no delay)
  await settle(FIRST_POLL_DELAY_MS); // first status poll arms the throttle
  return hook.result;
}

/** Deliver one status poll reporting `current`. */
async function pollOnce(current: number) {
  vi.mocked(getSyncJob).mockResolvedValueOnce(evidenceJob({ current }));
  await settle(POLL_INTERVAL_MS);
}

describe("useEvidenceSyncJob rolling readout", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"] });
    vi.mocked(getLatestSyncJob).mockResolvedValue(evidenceJob({ current: 0 }));
    vi.mocked(getSyncJob).mockResolvedValue(evidenceJob({ current: 0 }));
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it("does not advance on the first sighting of a job", async () => {
    const result = await mountRunning();

    expect(result.current.job).not.toBeNull();
    // Arming the throttle must not itself invite a mirror re-read: whoever
    // mounted has just fetched the list anyway.
    expect(result.current.dataEpoch).toBe(0);
  });

  it("advances once the job has moved and the refresh window has passed", async () => {
    const result = await mountRunning();

    await settle(PROGRESSIVE_REFRESH_MS);
    await pollOnce(25);

    expect(result.current.dataEpoch).toBe(1);
  });

  it("does not advance again inside the same refresh window", async () => {
    const result = await mountRunning();
    await settle(PROGRESSIVE_REFRESH_MS);
    await pollOnce(25);
    const afterFirst = result.current.dataEpoch;

    // Further real progress, but too soon to be worth another mirror read.
    await pollOnce(30);
    await pollOnce(35);

    expect(afterFirst).toBe(1);
    expect(result.current.dataEpoch).toBe(afterFirst);
  });

  it("does not advance when the job only heartbeats without progressing", async () => {
    const result = await mountRunning();
    await settle(PROGRESSIVE_REFRESH_MS);
    await pollOnce(25);
    const afterFirst = result.current.dataEpoch;

    // A retry ladder keeps `updated_at` fresh while `current` stands still —
    // re-reading the mirror for that would cost a request and show nothing.
    await settle(PROGRESSIVE_REFRESH_MS * 3);
    await pollOnce(25);

    expect(afterFirst).toBe(1);
    expect(result.current.dataEpoch).toBe(afterFirst);
  });
});
