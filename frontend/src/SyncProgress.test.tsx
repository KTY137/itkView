import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { SyncJob, SyncJobKind } from "./api";
import type { SyncJobController } from "./componentSync";
import { CompactSyncStatus, SyncProgressPanel } from "./SyncProgress";

function job(kind: SyncJobKind, overrides: Partial<SyncJob> = {}): SyncJob {
  return {
    id: 7,
    kind,
    institute_code: "EXAMPLE",
    status: "failed",
    phase: "fetching",
    current: 4,
    total: 10,
    percent: 40,
    message: "",
    result: null,
    error: "The remote service stopped responding.",
    created_at: "2026-08-27T09:59:00Z",
    started_at: "2026-08-27T09:59:00Z",
    updated_at: "2026-08-27T09:59:50Z",
    finished_at: "2026-08-27T10:00:00Z",
    ...overrides,
  } as SyncJob;
}

function controller(syncJob: SyncJob, overrides: Partial<SyncJobController> = {}) {
  return {
    kind: syncJob.kind,
    job: syncJob,
    active: syncJob.status === "queued" || syncJob.status === "running",
    discovering: false,
    starting: false,
    startError: null,
    pollError: null,
    dataEpoch: 0,
    start: vi.fn(async () => undefined),
    dismiss: vi.fn(),
    ...overrides,
  } satisfies SyncJobController;
}

afterEach(() => {
  vi.useRealTimers();
});

describe("SyncProgressPanel recovery", () => {
  it("explains atomic component preservation and retries the job institute", () => {
    const state = controller(job("components"));
    render(<SyncProgressPanel controller={state} canRetry />);

    expect(
      screen.getByText(/previous complete component snapshot remains unchanged/i),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry sync" }));
    expect(state.start).toHaveBeenCalledWith("EXAMPLE");
  });

  it("honestly preserves partial evidence and disables actions while retry starts", () => {
    const state = controller(job("evidence"), { starting: true });
    render(<SyncProgressPanel controller={state} canRetry />);

    expect(screen.getByText(/evidence and files already mirrored remain valid/i)).toBeInTheDocument();
    const retry = screen.getByRole("button", { name: "Starting retry…" });
    expect(retry).toBeDisabled();
    expect(retry).toHaveAttribute("aria-busy", "true");
    expect(screen.getByRole("button", { name: "Dismiss" })).toBeDisabled();
  });

  it("keeps elapsed and heartbeat age moving while the status connection is lost", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] });
    vi.setSystemTime(new Date("2026-08-27T10:00:00Z"));
    const state = controller(
      job("evidence", {
        status: "running",
        finished_at: null,
      }),
      { active: true, pollError: "network unavailable" },
    );
    render(<SyncProgressPanel controller={state} canRetry />);

    expect(screen.getByText("Last update 10s ago")).toBeInTheDocument();
    expect(screen.getByText(/sync may still be running/i)).toBeInTheDocument();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2_000);
    });
    expect(screen.getByText("Last update 12s ago")).toBeInTheDocument();
  });

  it("offers server-arbitrated recovery for an authoritatively stale active job", () => {
    const state = controller(
      job("components", {
        status: "running",
        finished_at: null,
        heartbeat_stale: true,
        stale_after_seconds: 180,
      }),
      { active: true },
    );
    const { container } = render(<SyncProgressPanel controller={state} canRetry />);

    expect(container.querySelector(".sync-progress-panel")).toHaveAttribute(
      "data-tone",
      "warning",
    );
    expect(screen.getByText(/no heartbeat within 3m 00s; the sync may be stalled/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Check and retry" }));
    expect(state.start).toHaveBeenCalledWith("EXAMPLE");
    expect(screen.queryByRole("button", { name: "Dismiss" })).not.toBeInTheDocument();
  });

  it("keeps stale recovery permission-scoped and shows its pending state", () => {
    const staleJob = job("evidence", {
      status: "running",
      finished_at: null,
      heartbeat_stale: true,
      stale_after_seconds: 180,
    });
    const { rerender } = render(
      <SyncProgressPanel controller={controller(staleJob)} canRetry={false} />,
    );
    expect(screen.queryByRole("button", { name: "Check and retry" })).not.toBeInTheDocument();

    rerender(
      <SyncProgressPanel
        controller={controller(staleJob, { starting: true })}
        canRetry
      />,
    );
    const pending = screen.getByRole("button", { name: "Checking and retrying…" });
    expect(pending).toBeDisabled();
    expect(pending).toHaveAttribute("aria-busy", "true");
  });

  it("treats an absent stale field as healthy or unknown", () => {
    const state = controller(
      job("components", { status: "running", finished_at: null }),
      { active: true },
    );
    const { container } = render(<SyncProgressPanel controller={state} canRetry />);

    expect(container.querySelector(".sync-progress-panel")).toHaveAttribute(
      "data-tone",
      "running",
    );
    expect(screen.queryByText(/may be stalled/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Check and retry" })).not.toBeInTheDocument();
  });

  it("names a stale job in the compact global status instead of relying on amber alone", () => {
    const onOpen = vi.fn();
    render(
      <CompactSyncStatus
        job={job("components", {
          status: "running",
          finished_at: null,
          heartbeat_stale: true,
          stale_after_seconds: 180,
        })}
        onOpen={onOpen}
      />,
    );

    const status = screen.getByRole("button", { name: /sync may be stalled/i });
    expect(status).toHaveAttribute("data-tone", "warning");
    expect(screen.getByText(/sync may be stalled · fetching components/i)).toBeInTheDocument();
    fireEvent.click(status);
    expect(onOpen).toHaveBeenCalledOnce();
  });
});
