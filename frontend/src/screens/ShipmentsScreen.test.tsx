// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
// SPDX-FileComment: itkflow-0380ae3c8930
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Shipment } from "../api";
import {
  getInstitutes,
  getShipments,
  postShipmentReception,
} from "../api";
import ShipmentsScreen from "./ShipmentsScreen";

const authState = vi.hoisted(() => ({
  current: {
    canWrite: true,
    showToast: vi.fn(),
    user: {
      email: "receiver@example.org",
      role: "operator",
      institute_code: "TUDO",
    },
  },
}));

vi.mock("../auth", () => ({
  useAuth: () => authState.current,
}));

vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api")>();
  return {
    ...actual,
    getInstitutes: vi.fn(),
    getShipments: vi.fn(),
    postShipmentReception: vi.fn(),
    postShipmentSync: vi.fn(),
  };
});

const missingShipment: Shipment = {
  id: 4,
  pdb_id: "shipment-4",
  name: "Incoming modules",
  sender_code: "SENDER",
  recipient_code: "TUDO",
  status: "delivered",
  direction: "incoming",
  sent_at: "2026-08-26T08:00:00Z",
  items: [
    {
      sn: "20USEM00000004",
      component_type: "MODULE",
      component_mirrored: true,
      is_dummy: false,
      submittable: false,
      submittable_reason: "not_dummy",
      reception_tests_configured: true,
      reception_test_status: "missing",
      reception_tests: [{ test_type: "RECEPTION_IV", status: "missing" }],
    },
  ],
  institute_id: 1,
  synced_at: "2026-08-26T08:05:00Z",
  reception_status: "in_progress",
  reception_checklist: [{ label: "Packaging intact", done: true }],
  reception_items: [{ sn: "20USEM00000004", received: true, note: null }],
  reception_note: null,
  reception_by: "receiver@example.org",
  reception_updated_at: "2026-08-26T08:10:00Z",
  reception_tests_configured: true,
  reception_test_status: "missing",
};

describe("ShipmentsScreen reception tests", () => {
  beforeEach(() => {
    authState.current = {
      canWrite: true,
      showToast: vi.fn(),
      user: {
        email: "receiver@example.org",
        role: "operator",
        institute_code: "TUDO",
      },
    };
    vi.mocked(getInstitutes).mockResolvedValue([
      {
        id: 1,
        code: "TUDO",
        name: "Example institute",
        local_name_prefix: "TUDO-",
        settings: {},
        created_at: "2026-08-26T07:00:00Z",
      },
    ]);
    vi.mocked(getShipments).mockResolvedValue([missingShipment]);
    vi.mocked(postShipmentReception).mockResolvedValue(missingShipment);
  });

  it("shows projected requirements, keeps done blocked, and deep-links the exact test", async () => {
    const user = userEvent.setup();
    const onAddTest = vi.fn();
    render(
      <ShipmentsScreen
        onOpenComponent={vi.fn()}
        onAddTest={onAddTest}
      />,
    );

    const shipmentName = await screen.findByText("Incoming modules");
    await user.click(shipmentName.closest("tr") as HTMLTableRowElement);

    expect(await screen.findByText("RECEPTION_IV")).toBeInTheDocument();
    expect(screen.getByText(/Production writes remain disabled/)).toBeInTheDocument();
    const finish = screen.getByRole("button", { name: "Finish receiving check" });
    expect(finish).toBeDisabled();
    expect(screen.getByText(/Only an admin can override/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Record test" }));
    expect(onAddTest).toHaveBeenCalledWith("20USEM00000004", "RECEPTION_IV");
  });

  it("requires an admin override reason and sends it explicitly", async () => {
    authState.current = {
      canWrite: true,
      showToast: vi.fn(),
      user: {
        email: "admin@example.org",
        role: "admin",
        institute_code: "TUDO",
      },
    };
    vi.mocked(postShipmentReception).mockResolvedValue({
      ...missingShipment,
      reception_status: "done",
    });
    const user = userEvent.setup();
    render(
      <ShipmentsScreen
        onOpenComponent={vi.fn()}
        onAddTest={vi.fn()}
      />,
    );

    const shipmentName = await screen.findByText("Incoming modules");
    await user.click(shipmentName.closest("tr") as HTMLTableRowElement);
    const override = screen.getByRole("checkbox", {
      name: "Override incomplete reception tests",
    });
    await user.click(override);
    const finish = screen.getByRole("button", { name: "Finish with admin override" });
    expect(finish).toBeDisabled();
    await user.type(
      screen.getByLabelText("Override reason"),
      "Documented transport exception",
    );
    expect(finish).toBeEnabled();
    await user.click(finish);

    await waitFor(() => expect(postShipmentReception).toHaveBeenCalledTimes(1));
    expect(vi.mocked(postShipmentReception).mock.calls[0]).toEqual([
      4,
      expect.objectContaining({
        status: "done",
        test_override: true,
        test_override_reason: "Documented transport exception",
      }),
    ]);
  });

  it("enables normal completion only after the projected evidence passes", async () => {
    const passedShipment: Shipment = {
      ...missingShipment,
      items: missingShipment.items.map((item) => ({
        ...item,
        reception_test_status: "passed",
        reception_tests: item.reception_tests.map((test) => ({
          ...test,
          status: "passed",
        })),
      })),
      reception_test_status: "passed",
    };
    vi.mocked(getShipments).mockResolvedValue([passedShipment]);
    vi.mocked(postShipmentReception).mockResolvedValue({
      ...passedShipment,
      reception_status: "done",
    });
    const user = userEvent.setup();
    render(
      <ShipmentsScreen
        onOpenComponent={vi.fn()}
        onAddTest={vi.fn()}
      />,
    );

    const shipmentName = await screen.findByText("Incoming modules");
    await user.click(shipmentName.closest("tr") as HTMLTableRowElement);
    expect(screen.getByText("Every configured reception test has passed.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Record test" })).not.toBeInTheDocument();

    const finish = screen.getByRole("button", { name: "Finish receiving check" });
    expect(finish).toBeEnabled();
    await user.click(finish);

    await waitFor(() => expect(postShipmentReception).toHaveBeenCalledTimes(1));
    expect(vi.mocked(postShipmentReception).mock.calls[0]?.[1]).toEqual(
      expect.objectContaining({ status: "done" }),
    );
    expect(vi.mocked(postShipmentReception).mock.calls[0]?.[1]).not.toHaveProperty(
      "test_override",
    );
  });
});
