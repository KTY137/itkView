// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
// SPDX-FileComment: itkflow-5fa1c4e95558
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Reminder, ReminderOccurrence } from "../api";
import {
  acknowledgeReminderOccurrence,
  getNotificationChannels,
  getReminderOccurrences,
  getReminders,
} from "../api";
import RemindersScreen from "./RemindersScreen";

const showToast = vi.fn();

vi.mock("../auth", () => ({
  useAuth: () => ({
    canWrite: true,
    isAdmin: false,
    demo: false,
    showToast,
  }),
}));

vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api")>();
  return {
    ...actual,
    acknowledgeReminderOccurrence: vi.fn(),
    getNotificationChannels: vi.fn(),
    getReminderOccurrences: vi.fn(),
    getReminders: vi.fn(),
  };
});

const reminder: Reminder = {
  id: 7,
  title: "Clean flow bench",
  note: null,
  channel: "lab-ops",
  schedule_kind: "weekly",
  next_due_at: "2026-08-27T08:00:00Z",
  active: true,
  last_fired_at: "2026-08-26T08:00:00Z",
  last_error: null,
  created_by: "operator@example.org",
  institute_id: 1,
  created_at: "2026-08-20T08:00:00Z",
  updated_at: "2026-08-26T08:00:00Z",
};

const occurrence: ReminderOccurrence = {
  id: 11,
  reminder_id: reminder.id,
  institute_id: 1,
  due_at: "2026-08-26T08:00:00Z",
  fired_at: "2026-08-26T08:00:01Z",
  delivery_status: "sent",
  delivery_error: null,
  escalation_due_at: "2026-08-26T08:15:01Z",
  escalation_channel: "supervisors",
  escalated_at: "2026-08-26T08:15:02Z",
  escalation_error: null,
  acknowledged_at: null,
  acknowledged_by: null,
};

describe("RemindersScreen acknowledgement tasks", () => {
  beforeEach(() => {
    vi.mocked(getReminders).mockResolvedValue([reminder]);
    vi.mocked(getReminderOccurrences).mockResolvedValue([occurrence]);
    vi.mocked(getNotificationChannels).mockResolvedValue([
      { name: "lab-ops", kind: "mattermost" },
    ]);
    vi.mocked(acknowledgeReminderOccurrence).mockResolvedValue({
      ...occurrence,
      acknowledged_at: "2026-08-26T08:20:00Z",
      acknowledged_by: "operator@example.org",
    });
  });

  it("shows durable escalation state and removes a task only after acknowledgement", async () => {
    const user = userEvent.setup();
    render(<RemindersScreen />);

    const section = (await screen.findByRole("heading", { name: "Open reminder tasks" }))
      .closest("section") as HTMLElement;
    expect(within(section).getByText("Clean flow bench")).toBeInTheDocument();
    expect(within(section).getByText("Delivered")).toBeInTheDocument();
    expect(within(section).getByText("Escalated")).toBeInTheDocument();

    await user.click(within(section).getByRole("button", { name: "Acknowledge" }));

    await waitFor(() => expect(acknowledgeReminderOccurrence).toHaveBeenCalledWith(11));
    expect(await within(section).findByText("No reminder tasks need acknowledgement."))
      .toBeInTheDocument();
    expect(showToast).toHaveBeenCalledWith("Reminder task acknowledged.");
  });
});
