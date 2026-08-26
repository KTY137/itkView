import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AssemblyPreview, ComponentOut, Tool } from "../api";
import {
  getGlueBatches,
  getTools,
  postAssemblyAction,
  postAssemblyPreview,
  scanAssemblyComponent,
} from "../api";
import AssemblyWizardScreen from "./AssemblyWizardScreen";

const authState = vi.hoisted(() => ({
  current: {
    canWrite: true,
    demo: true,
    showToast: vi.fn(),
  },
}));

vi.mock("../auth", () => ({
  useAuth: () => authState.current,
}));

vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api")>();
  return {
    ...actual,
    getGlueBatches: vi.fn(),
    getTools: vi.fn(),
    postAssemblyAction: vi.fn(),
    postAssemblyPreview: vi.fn(),
    scanAssemblyComponent: vi.fn(),
    scanGlueBatch: vi.fn(),
    scanTool: vi.fn(),
  };
});

const parent: ComponentOut = {
  sn: "20USBML9990001",
  local_name: "TUDO-DUMMY-M-01",
  component_type: "MODULE",
  type_code: "R5M0",
  stage: "GLUED",
  location: "TUDO",
  institute_code: "TUDO",
  parent_sn: null,
  is_dummy: true,
  trashed: false,
  stale: false,
  synced_at: "2026-08-26T08:00:00Z",
};

const child: ComponentOut = {
  ...parent,
  sn: "20USBHL9990002",
  local_name: "TUDO-DUMMY-H-02",
  component_type: "HYBRID",
  type_code: "R5H0",
  stage: "READY",
};

const tool: Tool = {
  id: 9,
  institute_id: 1,
  kind: "jig",
  code: "R5-JIG-09",
  label: "R5 assembly jig",
  rfid: "RFID-09",
  compatible_types: ["R5M0"],
  status: "active",
  created_at: "2026-08-26T08:00:00Z",
};

function preview(overrides: Partial<AssemblyPreview> = {}): AssemblyPreview {
  return {
    valid: true,
    submittable: true,
    submittable_reason: null,
    summary: `Assemble ${child.sn} into ${parent.sn} at H0`,
    slot: "H0",
    parent,
    child,
    tool,
    glue_batch: null,
    pdb_properties: { TOOL: tool.code, SLOT: "H0" },
    issues: [],
    warnings: [],
    ...overrides,
  };
}

describe("AssemblyWizardScreen", () => {
  beforeEach(() => {
    authState.current = { canWrite: true, demo: true, showToast: vi.fn() };
  });

  it("runs the complete scanner-first demo flow and stages only after dry-run", async () => {
    const user = userEvent.setup();
    const onStaged = vi.fn();
    render(<AssemblyWizardScreen onBack={vi.fn()} onStaged={onStaged} />);

    await user.type(screen.getByLabelText("Parent component"), "TUDO-DUMMY-M-01{enter}");
    expect(await screen.findByText("20USBML9990001")).toBeInTheDocument();

    await user.type(screen.getByLabelText("Child component"), "TUDO-DUMMY-H-02{enter}");
    expect(await screen.findByText("20USBHL9990002")).toBeInTheDocument();

    await user.type(screen.getByLabelText("Assembly slot"), "H0");
    await user.selectOptions(screen.getByLabelText("Compatible tool"), "900");
    expect(screen.queryByText("Server dry-run")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Run server dry-run" }));
    const dryRun = await screen.findByText("Server dry-run");
    expect(within(dryRun.closest("section") as HTMLElement).getByText("Ready to stage"))
      .toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Stage assembly action" }));
    await waitFor(() => expect(onStaged).toHaveBeenCalledTimes(1));
    expect(onStaged.mock.calls[0][0]).toMatchObject({
      kind: "assemble_component",
      status: "draft",
      payload: {
        parent_sn: parent.sn,
        child_sn: child.sn,
        slot: "H0",
        tool_id: 900,
        dry_run_required: true,
      },
    });
  });

  it("uses the canonical server request and keeps a blocked preview unstageable", async () => {
    authState.current = { canWrite: true, demo: false, showToast: vi.fn() };
    vi.mocked(scanAssemblyComponent).mockImplementation(async (code) =>
      code === parent.sn ? parent : child,
    );
    vi.mocked(getTools).mockResolvedValue([tool]);
    vi.mocked(getGlueBatches).mockResolvedValue([]);
    vi.mocked(postAssemblyPreview).mockResolvedValue(
      preview({
        valid: false,
        submittable: false,
        submittable_reason: "validation_failed",
        issues: [{ code: "child_has_parent", message: "Child already has a parent." }],
      }),
    );
    const user = userEvent.setup();
    render(<AssemblyWizardScreen onBack={vi.fn()} onStaged={vi.fn()} />);

    await user.type(screen.getByLabelText("Parent component"), `${parent.sn}{enter}`);
    await waitFor(() => expect(getTools).toHaveBeenCalled());
    await user.type(screen.getByLabelText("Child component"), `${child.sn}{enter}`);
    await user.type(screen.getByLabelText("Assembly slot"), "H0");
    await user.selectOptions(screen.getByLabelText("Compatible tool"), "9");
    await user.click(screen.getByRole("button", { name: "Run server dry-run" }));

    await waitFor(() =>
      expect(postAssemblyPreview).toHaveBeenCalledWith({
        parent_sn: parent.sn,
        child_sn: child.sn,
        slot: "H0",
        tool_id: tool.id,
        glue_batch_id: null,
      }),
    );
    expect(await screen.findByText("Child already has a parent.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Stage assembly action" })).toBeDisabled();
    expect(postAssemblyAction).not.toHaveBeenCalled();
  });

  it("discards an in-flight preview when an input changes", async () => {
    authState.current = { canWrite: true, demo: false, showToast: vi.fn() };
    vi.mocked(scanAssemblyComponent).mockImplementation(async (code) =>
      code === parent.sn ? parent : child,
    );
    vi.mocked(getTools).mockResolvedValue([tool]);
    vi.mocked(getGlueBatches).mockResolvedValue([]);
    let resolvePreview: (value: AssemblyPreview) => void = () => {};
    vi.mocked(postAssemblyPreview).mockReturnValue(
      new Promise((resolve) => {
        resolvePreview = resolve;
      }),
    );
    const user = userEvent.setup();
    render(<AssemblyWizardScreen onBack={vi.fn()} onStaged={vi.fn()} />);

    await user.type(screen.getByLabelText("Parent component"), `${parent.sn}{enter}`);
    await waitFor(() => expect(getTools).toHaveBeenCalled());
    await user.type(screen.getByLabelText("Child component"), `${child.sn}{enter}`);
    const slot = screen.getByLabelText("Assembly slot");
    await user.type(slot, "H0");
    await user.selectOptions(screen.getByLabelText("Compatible tool"), "9");
    await user.click(screen.getByRole("button", { name: "Run server dry-run" }));
    await waitFor(() => expect(postAssemblyPreview).toHaveBeenCalledTimes(1));

    await user.clear(slot);
    await user.type(slot, "H1");
    resolvePreview(preview());
    await waitFor(() => expect(screen.queryByText("Running dry-run…")).not.toBeInTheDocument());
    expect(screen.queryByRole("heading", { name: "Server dry-run" })).not.toBeInTheDocument();
  });
});
