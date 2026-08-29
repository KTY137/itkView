// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
// SPDX-FileComment: itkflow-cd0d043800e6
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Institute, Tool } from "../api";
import { deleteTool, getInstitutes, getTools, patchTool, postTool } from "../api";
import { resetDemoTools } from "../demoData";
import ToolsScreen from "./ToolsScreen";

const authState = vi.hoisted(() => ({
  current: {
    canWrite: true,
    isAdmin: true,
    demo: false,
    showToast: vi.fn(),
    user: { institute_code: "TUDO" },
  },
}));

vi.mock("../auth", () => ({
  useAuth: () => authState.current,
}));

vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api")>();
  return {
    ...actual,
    deleteTool: vi.fn(),
    getInstitutes: vi.fn(),
    getTools: vi.fn(),
    patchTool: vi.fn(),
    postTool: vi.fn(),
    postToolSync: vi.fn(),
    scanTool: vi.fn(),
  };
});

const institute: Institute = {
  id: 1,
  code: "TUDO",
  name: "Example institute",
  local_name_prefix: "TUDO-",
  settings: {},
  created_at: "2026-08-26T08:00:00Z",
};

const existing: Tool = {
  id: 7,
  institute_id: 1,
  kind: "jig",
  code: "JIG-07",
  label: "Assembly jig",
  rfid: "RFID-07",
  compatible_types: ["R5M0"],
  status: "active",
  created_at: "2026-08-26T08:00:00Z",
};

describe("ToolsScreen", () => {
  beforeEach(() => {
    resetDemoTools();
    authState.current = {
      canWrite: true,
      isAdmin: true,
      demo: false,
      showToast: vi.fn(),
      user: { institute_code: "TUDO" },
    };
    vi.mocked(getInstitutes).mockResolvedValue([institute]);
    vi.mocked(getTools).mockResolvedValue([existing]);
  });

  it("creates normalized structured tool data in the selected institute", async () => {
    const created: Tool = {
      ...existing,
      id: 8,
      code: "PICKUP-08",
      kind: "pickup_tool",
      compatible_types: ["R5M0", "R5M1"],
    };
    vi.mocked(postTool).mockResolvedValue(created);
    const user = userEvent.setup();
    render(<ToolsScreen />);
    expect(await screen.findByText("JIG-07")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Add tool" }));
    await user.clear(screen.getByLabelText("Tool kind"));
    await user.type(screen.getByLabelText("Tool kind"), "pickup_tool");
    await user.type(screen.getByLabelText("Tool code"), "PICKUP-08");
    await user.type(screen.getByLabelText("Label (optional)"), "Pickup station");
    await user.type(screen.getByLabelText("RFID (optional)"), "TAG-08");
    await user.type(screen.getByLabelText("Compatible component types"), "r5m0, R5M1 r5m0");
    await user.click(screen.getByRole("button", { name: "Save tool" }));

    await waitFor(() =>
      expect(postTool).toHaveBeenCalledWith({
        institute_code: "TUDO",
        kind: "pickup_tool",
        code: "PICKUP-08",
        label: "Pickup station",
        rfid: "TAG-08",
        compatible_types: ["R5M0", "R5M1"],
        status: "active",
      }),
    );
    expect(await screen.findByText("PICKUP-08")).toBeInTheDocument();
  });

  it("supports audited status changes and explicitly clears optional fields", async () => {
    vi.mocked(patchTool)
      .mockResolvedValueOnce({ ...existing, status: "blacklisted" })
      .mockResolvedValueOnce({ ...existing, label: null, rfid: null, status: "blacklisted" });
    const user = userEvent.setup();
    render(<ToolsScreen />);
    const row = (await screen.findByText("JIG-07")).closest("tr") as HTMLTableRowElement;

    await user.click(within(row).getByRole("button", { name: "Blacklist" }));
    await waitFor(() => expect(patchTool).toHaveBeenNthCalledWith(1, 7, { status: "blacklisted" }));

    await user.click(within(row).getByRole("button", { name: "Edit" }));
    await user.clear(screen.getByLabelText("Label (optional)"));
    await user.clear(screen.getByLabelText("RFID (optional)"));
    await user.click(screen.getByRole("button", { name: "Save tool" }));
    await waitFor(() =>
      expect(patchTool).toHaveBeenNthCalledWith(2, 7, {
        kind: "jig",
        code: "JIG-07",
        label: null,
        rfid: null,
        compatible_types: ["R5M0"],
        status: "blacklisted",
      }),
    );
  });

  it("gates permanent removal to an explicit confirmation", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.mocked(deleteTool).mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<ToolsScreen />);
    const row = (await screen.findByText("JIG-07")).closest("tr") as HTMLTableRowElement;
    await user.click(within(row).getByRole("button", { name: "Edit" }));
    await user.click(screen.getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(deleteTool).toHaveBeenCalledWith(7));
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining("JIG-07"));
    expect(screen.queryByText("JIG-07")).not.toBeInTheDocument();
  });

  it("keeps offline registry edits when filters change", async () => {
    authState.current = {
      canWrite: true,
      isAdmin: true,
      demo: true,
      showToast: vi.fn(),
      user: { institute_code: "TUDO" },
    };
    const user = userEvent.setup();
    render(<ToolsScreen />);
    await user.click(screen.getByRole("button", { name: "Add tool" }));
    await user.clear(screen.getByLabelText("Tool kind"));
    await user.type(screen.getByLabelText("Tool kind"), "pickup_tool");
    await user.type(screen.getByLabelText("Tool code"), "OFFLINE-PICKUP-1");
    await user.type(screen.getByLabelText("Compatible component types"), "R5M0");
    await user.click(screen.getByRole("button", { name: "Save tool" }));
    expect(await screen.findByText("OFFLINE-PICKUP-1")).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Filter by kind"), "pickup_tool");
    expect(await screen.findByText("OFFLINE-PICKUP-1")).toBeInTheDocument();
  });
});
