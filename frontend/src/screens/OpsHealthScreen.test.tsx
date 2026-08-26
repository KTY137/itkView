import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Institute, OpsHealth } from "../api";
import OpsHealthScreen from "./OpsHealthScreen";

const { getOpsHealthMock } = vi.hoisted(() => ({ getOpsHealthMock: vi.fn() }));

vi.mock("../api", () => ({
  getOpsHealth: getOpsHealthMock,
}));

const institute: Institute = {
  id: 1,
  code: "ALPHA",
  name: "Alpha Institute",
  local_name_prefix: "A-",
  settings: {},
  created_at: "2026-08-26T10:00:00Z",
};

const snapshot: OpsHealth = {
  status: "warning",
  generated_at: "2026-08-26T12:00:00Z",
  institute_code: "ALPHA",
  heartbeats: [
    {
      service: "outbox-worker",
      status: "healthy",
      last_seen_at: "2026-08-26T11:59:55Z",
      age_seconds: 5,
      stale_after_seconds: 180,
      detail: {},
    },
    {
      service: "reminder-scheduler",
      status: "stale",
      last_seen_at: "2026-08-26T11:50:00Z",
      age_seconds: 600,
      stale_after_seconds: 180,
      detail: {},
    },
  ],
  sync: {
    active: [],
    stale_active: 0,
    latest: [
      {
        id: 9,
        kind: "components",
        institute_code: "ALPHA",
        status: "succeeded",
        phase: "complete",
        current: 3,
        total: 3,
        percent: 100,
        message: "complete",
        result: null,
        error: null,
        created_at: "2026-08-26T11:00:00Z",
        started_at: "2026-08-26T11:00:00Z",
        updated_at: "2026-08-26T11:01:00Z",
        finished_at: "2026-08-26T11:01:00Z",
      },
    ],
  },
  outbox: {
    backlog: 4,
    failed: 1,
    at_attempt_limit: 1,
    oldest_open_at: "2026-08-26T10:00:00Z",
    oldest_open_age_seconds: 7200,
  },
  reminders: {
    active: 3,
    open_occurrences: 2,
    failed_occurrences: 1,
    escalated_open: 1,
    overdue: 0,
  },
  ingest: { total: 12, triage: 2, failed: 0, parser_issues: 2, unassigned: 0 },
};

describe("OpsHealthScreen", () => {
  beforeEach(() => {
    getOpsHealthMock.mockReset();
    getOpsHealthMock.mockResolvedValue(snapshot);
  });

  it("renders textual service status, local telemetry, and all deep links", async () => {
    const onNavigate = vi.fn();
    render(
      <OpsHealthScreen
        institutes={[institute]}
        selectedCode="ALPHA"
        allowAllInstitutes={false}
        onSelectedCodeChange={vi.fn()}
        onNavigate={onNavigate}
      />,
    );

    expect(await screen.findByRole("heading", { name: "Operations health" })).toBeVisible();
    expect(screen.getByText("Needs attention")).toBeVisible();
    expect(screen.getByText("Outbox worker")).toBeVisible();
    expect(screen.getByText("Reminder scheduler")).toBeVisible();
    expect(screen.getByText("Stale")).toBeVisible();
    expect(screen.getByText(/never contacts the PDB/i)).toBeVisible();
    expect(getOpsHealthMock).toHaveBeenCalledWith("ALPHA", expect.any(AbortSignal));

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Open Staged" }));
    await user.click(screen.getByRole("button", { name: "Open Ingest log" }));
    await user.click(screen.getByRole("button", { name: "Open Reminders" }));
    expect(onNavigate.mock.calls).toEqual([["staged"], ["triage"], ["reminders"]]);
  });

  it("offers a global scope and refreshes on demand", async () => {
    const onSelectedCodeChange = vi.fn();
    render(
      <OpsHealthScreen
        institutes={[institute]}
        selectedCode=""
        allowAllInstitutes
        onSelectedCodeChange={onSelectedCodeChange}
        onNavigate={vi.fn()}
      />,
    );
    await waitFor(() => expect(getOpsHealthMock).toHaveBeenCalledTimes(1));
    expect(getOpsHealthMock).toHaveBeenCalledWith(undefined, expect.any(AbortSignal));

    const user = userEvent.setup();
    await user.selectOptions(screen.getByLabelText("Institute"), "ALPHA");
    expect(onSelectedCodeChange).toHaveBeenCalledWith("ALPHA");
    await user.click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() => expect(getOpsHealthMock).toHaveBeenCalledTimes(2));
  });
});
