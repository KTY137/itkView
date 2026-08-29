// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
// SPDX-FileComment: itkflow-cc12dad70f15
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AssemblyPreview, ComponentOut, GlueBatch, Institute, Tool } from "../api";
import {
  getGlueBatches,
  getInstitutes,
  getTools,
  postAssemblyAction,
  postAssemblyPreview,
  scanAssemblyComponent,
  scanGlueBatch,
  scanTool,
} from "../api";
import { resetDemoTools } from "../demoData";
import { toolOptionLabel } from "../fieldLayout";
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
    getInstitutes: vi.fn(),
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

const glue: GlueBatch = {
  id: 12,
  institute_id: 1,
  glue_type: "POLARIS_EPOXY",
  batch_no: "BATCH-12",
  pdb_sn: "20USEGT0000012",
  status: "in_use",
  manufacturing_date: null,
  expiry_date: null,
  opening_date: "2026-08-26T08:00:00Z",
  bipack_count: 1,
  note: null,
  mixed_at: "2026-08-26T08:00:00Z",
  pot_life_minutes: 45,
  created_at: "2026-08-26T08:00:00Z",
  pot_life_remaining_seconds: 2_400,
  pot_life_expired: false,
  usage_count: 0,
};

// Institute.settings.assembly_tool_slots (docs/05 §8): two single jig slots
// plus one `multiple` pickup-tool slot, mirroring the TUDO hybrid-glue sheet
// (top/bottom jigs, top/bottom pickups, module jig).
const slotProfile: Institute = {
  id: 1,
  code: "TUDO",
  name: "TU Dortmund",
  local_name_prefix: "TUDO",
  settings: {
    assembly_tool_slots: [
      { key: "glue_jig_bottom", label: "Hybrid glue jig, bottom", kinds: ["jig"] },
      { key: "glue_jig_top", label: "Hybrid glue jig, top", kinds: ["jig"] },
      {
        key: "pickup_tools",
        label: "Hybrid pickup tools",
        kinds: ["pickup_tool"],
        multiple: true,
      },
    ],
  },
  created_at: "2026-08-26T08:00:00Z",
};

const jigBottom: Tool = {
  id: 21,
  institute_id: 1,
  kind: "jig",
  code: "JIG-BOT",
  label: "Bottom glue jig",
  rfid: null,
  compatible_types: ["R5M0"],
  status: "active",
  created_at: "2026-08-26T08:00:00Z",
};
const jigTop: Tool = { ...jigBottom, id: 22, code: "JIG-TOP", label: "Top glue jig" };
const pickupA: Tool = {
  id: 31,
  institute_id: 1,
  kind: "pickup_tool",
  code: "PICKUP-A",
  label: "Pickup A",
  rfid: null,
  compatible_types: ["R5M0"],
  status: "active",
  created_at: "2026-08-26T08:00:00Z",
};
const pickupB: Tool = { ...pickupA, id: 32, code: "PICKUP-B", label: "Pickup B" };
const pickupC: Tool = { ...pickupA, id: 33, code: "PICKUP-C", label: "Pickup C" };
const pickupD: Tool = { ...pickupA, id: 34, code: "PICKUP-D", label: "Pickup D" };
const pickupE: Tool = { ...pickupA, id: 35, code: "PICKUP-E", label: "Pickup E" };

/** The card rendered for one `assembly_tool_slots` entry, found via its
 * clickable slot-label button (also the scan-target toggle). */
function slotCard(label: string): HTMLElement {
  return screen.getByRole("button", { name: label }).closest(".assembly-tool-slot") as HTMLElement;
}

/** Just the selected-tool chips of one slot — unlike `slotCard`, this
 * excludes the quick-select `<option>`s, which legitimately still list a
 * tool that is selected in a *different* slot with an overlapping `kinds`
 * filter (there is no cross-slot exclusivity by design). */
function slotChips(label: string): HTMLElement {
  return slotCard(label).querySelector(".assembly-tool-slot-chips") as HTMLElement;
}

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
    tools: {},
    glue_batch: null,
    pdb_properties: { TOOL: tool.code, SLOT: "H0" },
    issues: [],
    warnings: [],
    ...overrides,
  };
}

describe("AssemblyWizardScreen", () => {
  beforeEach(() => {
    resetDemoTools();
    authState.current = { canWrite: true, demo: true, showToast: vi.fn() };
    // Default: no institute profile found -> legacy single-tool layout.
    // Tests that need `assembly_tool_slots` override this explicitly.
    vi.mocked(getInstitutes).mockResolvedValue([]);
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
    await waitFor(() => {
      expect(getTools).toHaveBeenCalledWith(
        { fits: "R5M0", status: "active", institute: "TUDO" },
        expect.any(AbortSignal),
      );
      expect(getGlueBatches).toHaveBeenCalledWith(
        { status: "in_use", institute: "TUDO" },
        expect.any(AbortSignal),
      );
    });
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

  it("invalidates an in-flight child scan when the parent is reset", async () => {
    authState.current = { canWrite: true, demo: false, showToast: vi.fn() };
    let resolveChild: (value: ComponentOut) => void = () => {};
    vi.mocked(scanAssemblyComponent).mockImplementation((code) => {
      if (code === parent.sn) return Promise.resolve(parent);
      return new Promise((resolve) => {
        resolveChild = resolve;
      });
    });
    vi.mocked(getTools).mockResolvedValue([]);
    vi.mocked(getGlueBatches).mockResolvedValue([]);
    const user = userEvent.setup();
    render(<AssemblyWizardScreen onBack={vi.fn()} onStaged={vi.fn()} />);

    const parentInput = screen.getByLabelText("Parent component");
    await user.type(parentInput, `${parent.sn}{enter}`);
    expect(await screen.findByText(parent.local_name as string)).toBeInTheDocument();
    const childInput = screen.getByLabelText("Child component");
    await user.type(childInput, `${child.sn}{enter}`);
    await waitFor(() => expect(scanAssemblyComponent).toHaveBeenCalledWith(child.sn));

    await user.clear(parentInput);
    resolveChild(child);
    await waitFor(() => expect(childInput).toHaveValue(""));
    expect(screen.queryByText(child.sn)).not.toBeInTheDocument();
  });

  it("aborts and discards stale tool and glue scans after a parent reset", async () => {
    authState.current = { canWrite: true, demo: false, showToast: vi.fn() };
    vi.mocked(scanAssemblyComponent).mockResolvedValue(parent);
    vi.mocked(getTools).mockResolvedValue([]);
    vi.mocked(getGlueBatches).mockResolvedValue([]);
    let resolveTool: (value: Tool) => void = () => {};
    let resolveGlue: (value: GlueBatch) => void = () => {};
    vi.mocked(scanTool).mockReturnValue(
      new Promise((resolve) => {
        resolveTool = resolve;
      }),
    );
    vi.mocked(scanGlueBatch).mockReturnValue(
      new Promise((resolve) => {
        resolveGlue = resolve;
      }),
    );
    const user = userEvent.setup();
    render(<AssemblyWizardScreen onBack={vi.fn()} onStaged={vi.fn()} />);

    const parentInput = screen.getByLabelText("Parent component");
    await user.type(parentInput, `${parent.sn}{enter}`);
    expect(await screen.findByText(parent.local_name as string)).toBeInTheDocument();
    await user.type(screen.getByLabelText("Scan compatible tool"), "RFID-09{enter}");
    await user.type(screen.getByLabelText("Scan glue batch"), "BATCH-12{enter}");
    await waitFor(() => {
      expect(scanTool).toHaveBeenCalledWith("RFID-09", "TUDO", expect.any(AbortSignal));
      expect(scanGlueBatch).toHaveBeenCalledWith(
        "BATCH-12",
        "TUDO",
        expect.any(AbortSignal),
      );
    });

    const toolSignal = vi.mocked(scanTool).mock.calls.at(-1)?.[2];
    const glueSignal = vi.mocked(scanGlueBatch).mock.calls.at(-1)?.[2];
    await user.clear(parentInput);
    expect(toolSignal?.aborted).toBe(true);
    expect(glueSignal?.aborted).toBe(true);

    resolveTool(tool);
    resolveGlue(glue);
    await waitFor(() => {
      expect(screen.queryByRole("option", { name: /R5 assembly jig/ })).not.toBeInTheDocument();
      expect(screen.queryByRole("option", { name: /BATCH-12/ })).not.toBeInTheDocument();
    });
  });

  it("renders institute-configured tool slots and builds a tools-keyed payload", async () => {
    authState.current = { canWrite: true, demo: false, showToast: vi.fn() };
    vi.mocked(scanAssemblyComponent).mockImplementation(async (code) =>
      code === parent.sn ? parent : child,
    );
    vi.mocked(getInstitutes).mockResolvedValue([slotProfile]);
    vi.mocked(getTools).mockResolvedValue([jigBottom, jigTop, pickupA, pickupB]);
    vi.mocked(getGlueBatches).mockResolvedValue([]);
    // The dry-run echoes back its OWN resolved tools per slot — deliberately
    // different codes from the locally selected ones below, so the Review
    // step can only pass by rendering the server response (CRITICAL #1).
    const slotPreview: AssemblyPreview = {
      valid: true,
      submittable: true,
      submittable_reason: null,
      summary: `Assemble ${child.sn} into ${parent.sn} at H0`,
      slot: "H0",
      parent,
      child,
      tool: null,
      tools: {
        glue_jig_bottom: [
          {
            id: 21,
            kind: "jig",
            code: "SRV-JIG-BOT",
            label: "Server-confirmed bottom jig",
            rfid: null,
            compatible_types: ["R5M0"],
            status: "active",
          },
        ],
        glue_jig_top: [
          {
            id: 22,
            kind: "jig",
            code: "SRV-JIG-TOP",
            label: "Server-confirmed top jig",
            rfid: null,
            compatible_types: ["R5M0"],
            status: "active",
          },
        ],
        pickup_tools: [
          {
            id: 98,
            kind: "pickup_tool",
            code: "SRV-PICKUP-X",
            label: "Server-confirmed pickup",
            rfid: null,
            compatible_types: ["R5M0"],
            status: "active",
          },
        ],
      },
      glue_batch: null,
      pdb_properties: {},
      issues: [],
      warnings: [],
    };
    vi.mocked(postAssemblyPreview).mockResolvedValue(slotPreview);
    vi.mocked(postAssemblyAction).mockResolvedValue({
      preview: slotPreview,
      action: {
        id: 4242,
        institute_id: 1,
        kind: "assemble_component",
        payload: {},
        status: "draft",
        error: null,
        attempts: 0,
        created_by: "demo.operator@example.org",
        external_ref: null,
        created_at: "2026-08-26T08:00:00Z",
        updated_at: "2026-08-26T08:00:00Z",
      },
    });
    const onStaged = vi.fn();
    const user = userEvent.setup();
    render(<AssemblyWizardScreen onBack={vi.fn()} onStaged={onStaged} />);

    await user.type(screen.getByLabelText("Parent component"), `${parent.sn}{enter}`);
    await screen.findByRole("button", { name: "Hybrid glue jig, bottom" });
    expect(screen.getByRole("button", { name: "Hybrid glue jig, top" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Hybrid pickup tools" })).toBeInTheDocument();
    // The legacy single-tool select never renders once a profile layout is active.
    expect(screen.queryByLabelText("Compatible tool")).not.toBeInTheDocument();

    await user.type(screen.getByLabelText("Child component"), `${child.sn}{enter}`);
    await user.type(screen.getByLabelText("Assembly slot"), "H0");
    const dryRunButton = () => screen.getByRole("button", { name: "Run server dry-run" });
    const bottomLabel = () => screen.getByRole("button", { name: "Hybrid glue jig, bottom" });
    const topLabel = () => screen.getByRole("button", { name: "Hybrid glue jig, top" });
    expect(dryRunButton()).toBeDisabled();
    // The first configured slot is the active scan target by default.
    expect(bottomLabel()).toHaveAttribute("aria-pressed", "true");
    expect(topLabel()).toHaveAttribute("aria-pressed", "false");

    await user.selectOptions(
      screen.getByLabelText("Add a tool to Hybrid glue jig, bottom"),
      String(jigBottom.id),
    );
    expect(within(slotCard("Hybrid glue jig, bottom")).getByText("Bottom glue jig · JIG-BOT"))
      .toBeInTheDocument();
    expect(dryRunButton()).toBeDisabled();
    // IMPORTANT #4b: filling a single-capacity slot auto-advances the active
    // slot to the next one with room, wrapping through the list in order.
    expect(bottomLabel()).toHaveAttribute("aria-pressed", "false");
    expect(topLabel()).toHaveAttribute("aria-pressed", "true");

    await user.selectOptions(
      screen.getByLabelText("Add a tool to Hybrid glue jig, top"),
      String(jigTop.id),
    );
    expect(dryRunButton()).toBeDisabled();

    // The `multiple` pickup slot only requires one tool, same as the single
    // jig slots — reaching its cap of four is optional, not required.
    await user.selectOptions(
      screen.getByLabelText("Add a tool to Hybrid pickup tools"),
      String(pickupA.id),
    );
    expect(within(slotCard("Hybrid pickup tools")).getByText("1/4")).toBeInTheDocument();
    expect(dryRunButton()).not.toBeDisabled();

    await user.selectOptions(
      screen.getByLabelText("Add a tool to Hybrid pickup tools"),
      String(pickupB.id),
    );
    expect(within(slotCard("Hybrid pickup tools")).getByText("2/4")).toBeInTheDocument();
    expect(dryRunButton()).not.toBeDisabled();

    await user.click(dryRunButton());
    await waitFor(() =>
      expect(postAssemblyPreview).toHaveBeenCalledWith({
        parent_sn: parent.sn,
        child_sn: child.sn,
        slot: "H0",
        tools: {
          glue_jig_bottom: [jigBottom.id],
          glue_jig_top: [jigTop.id],
          pickup_tools: [pickupA.id, pickupB.id],
        },
        glue_batch_id: null,
      }),
    );

    const dryRun = await screen.findByText("Server dry-run");
    const dryRunSection = dryRun.closest("section") as HTMLElement;
    expect(within(dryRunSection).getByText("Hybrid glue jig, bottom")).toBeInTheDocument();
    // CRITICAL #1: the Review step renders the server's echoed tools, not
    // the locally selected ones (which used the "JIG-BOT"/"PICKUP-A" codes).
    expect(within(dryRunSection).getByText("SRV-JIG-BOT")).toBeInTheDocument();
    expect(within(dryRunSection).getByText("SRV-JIG-TOP")).toBeInTheDocument();
    expect(within(dryRunSection).getByText("SRV-PICKUP-X")).toBeInTheDocument();
    expect(within(dryRunSection).queryByText("JIG-BOT")).not.toBeInTheDocument();
    expect(within(dryRunSection).queryByText("PICKUP-A, PICKUP-B")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Stage assembly action" }));
    await waitFor(() => expect(onStaged).toHaveBeenCalledTimes(1));
    expect(postAssemblyAction).toHaveBeenCalledWith({
      parent_sn: parent.sn,
      child_sn: child.sn,
      slot: "H0",
      tools: {
        glue_jig_bottom: [jigBottom.id],
        glue_jig_top: [jigTop.id],
        pickup_tools: [pickupA.id, pickupB.id],
      },
      glue_batch_id: null,
    });
  });

  it("enforces the multiple-slot maximum of four and a slot's tool-kind filter", async () => {
    authState.current = { canWrite: true, demo: false, showToast: vi.fn() };
    const allTools = [jigBottom, jigTop, pickupA, pickupB, pickupC, pickupD, pickupE];
    vi.mocked(scanAssemblyComponent).mockImplementation(async (code) =>
      code === parent.sn ? parent : child,
    );
    vi.mocked(getInstitutes).mockResolvedValue([slotProfile]);
    vi.mocked(getTools).mockResolvedValue(allTools);
    vi.mocked(getGlueBatches).mockResolvedValue([]);
    vi.mocked(scanTool).mockImplementation(async (code) => {
      const found = allTools.find((candidate) => candidate.code === code);
      if (found === undefined) throw new Error(`No tool matches "${code}".`);
      return found;
    });
    const user = userEvent.setup();
    render(<AssemblyWizardScreen onBack={vi.fn()} onStaged={vi.fn()} />);

    await user.type(screen.getByLabelText("Parent component"), `${parent.sn}{enter}`);
    await screen.findByRole("button", { name: "Hybrid pickup tools" });
    await user.type(screen.getByLabelText("Child component"), `${child.sn}{enter}`);

    expect(
      within(slotCard("Hybrid pickup tools")).getByText("Hybrid pickup tools needs at least one tool."),
    ).toBeInTheDocument();

    const pickupSelect = () => screen.getByLabelText("Add a tool to Hybrid pickup tools");
    for (const fixture of [pickupA, pickupB, pickupC, pickupD]) {
      await user.selectOptions(pickupSelect(), String(fixture.id));
    }
    expect(within(slotCard("Hybrid pickup tools")).getByText("4/4")).toBeInTheDocument();
    expect(pickupSelect()).toBeDisabled();
    expect(
      within(slotCard("Hybrid pickup tools")).getByText(
        "Hybrid pickup tools already has its maximum of 4 tools.",
      ),
    ).toBeInTheDocument();
    // Filling the last (and only other) slot with room auto-advanced the
    // active slot away from "Hybrid pickup tools" (IMPORTANT #4b) — retarget
    // it explicitly to exercise the "slot full" scan rejection below.
    await user.click(screen.getByRole("button", { name: "Hybrid pickup tools" }));

    const scanInput = () => screen.getByLabelText("Scan compatible tool");
    await user.type(scanInput(), "PICKUP-E{enter}");
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Hybrid pickup tools already has its maximum of 4 tools.",
    );
    expect(within(slotCard("Hybrid pickup tools")).getByText("4/4")).toBeInTheDocument();
    // IMPORTANT #5: a rejected scan clears the input so the next hardware
    // scan does not get appended to (and garbled by) the rejected code.
    expect(scanInput()).toHaveValue("");
    // IMPORTANT #6: the tool-scan error renders directly under the
    // tool-scan form, not in the bottom preview/stage banner.
    const scanForm = scanInput().closest("form");
    expect(scanForm?.nextElementSibling).toBe(screen.getByRole("alert"));

    await user.click(
      screen.getByRole("button", { name: "Remove PICKUP-A from Hybrid pickup tools" }),
    );
    expect(within(slotCard("Hybrid pickup tools")).getByText("3/4")).toBeInTheDocument();
    expect(pickupSelect()).not.toBeDisabled();

    // No need to clear first: the previous rejection already left it empty.
    await user.type(scanInput(), "JIG-BOT{enter}");
    expect(screen.getByRole("alert")).toHaveTextContent(
      "JIG-BOT is not a compatible tool kind for Hybrid pickup tools.",
    );
    expect(within(slotCard("Hybrid pickup tools")).getByText("3/4")).toBeInTheDocument();
    expect(scanInput()).toHaveValue("");
  });

  it("routes a scan by tool kind when unambiguous, falls back to the active slot when ambiguous, and auto-advances after filling a slot", async () => {
    authState.current = { canWrite: true, demo: false, showToast: vi.fn() };
    const pool = [jigBottom, jigTop, pickupA];
    vi.mocked(scanAssemblyComponent).mockImplementation(async (code) =>
      code === parent.sn ? parent : child,
    );
    vi.mocked(getInstitutes).mockResolvedValue([slotProfile]);
    vi.mocked(getTools).mockResolvedValue(pool);
    vi.mocked(getGlueBatches).mockResolvedValue([]);
    vi.mocked(scanTool).mockImplementation(async (code) => {
      const found = pool.find((candidate) => candidate.code === code);
      if (found === undefined) throw new Error(`No tool matches "${code}".`);
      return found;
    });
    const user = userEvent.setup();
    render(<AssemblyWizardScreen onBack={vi.fn()} onStaged={vi.fn()} />);

    await user.type(screen.getByLabelText("Parent component"), `${parent.sn}{enter}`);
    await screen.findByRole("button", { name: "Hybrid pickup tools" });
    await user.type(screen.getByLabelText("Child component"), `${child.sn}{enter}`);

    const bottomLabel = () => screen.getByRole("button", { name: "Hybrid glue jig, bottom" });
    const topLabel = () => screen.getByRole("button", { name: "Hybrid glue jig, top" });
    const pickupLabel = () => screen.getByRole("button", { name: "Hybrid pickup tools" });
    // The first configured slot is active by default.
    expect(bottomLabel()).toHaveAttribute("aria-pressed", "true");

    // IMPORTANT #4a: PICKUP-A's kind is only accepted by one slot, so it is
    // routed there even though "Hybrid glue jig, bottom" is still active.
    await user.type(screen.getByLabelText("Scan compatible tool"), "PICKUP-A{enter}");
    expect(within(slotCard("Hybrid pickup tools")).getByText("Pickup A · PICKUP-A"))
      .toBeInTheDocument();
    expect(within(slotChips("Hybrid glue jig, bottom")).queryByText(/PICKUP-A/)).not.toBeInTheDocument();
    expect(pickupLabel()).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("status")).toHaveTextContent("Hybrid pickup tools");

    // Both jig slots accept "jig" — ambiguous, so it must fall back to
    // whichever slot the operator explicitly made active.
    await user.click(topLabel());
    expect(topLabel()).toHaveAttribute("aria-pressed", "true");
    await user.type(screen.getByLabelText("Scan compatible tool"), "JIG-BOT{enter}");
    expect(within(slotCard("Hybrid glue jig, top")).getByText("Bottom glue jig · JIG-BOT"))
      .toBeInTheDocument();
    expect(within(slotChips("Hybrid glue jig, bottom")).queryByText(/JIG-BOT/)).not.toBeInTheDocument();

    // IMPORTANT #4b: "Hybrid glue jig, top" just reached its capacity of
    // one, so the active slot auto-advances (wrapping) to the next slot
    // with room — "Hybrid pickup tools" (1/4), not the still-empty
    // "Hybrid glue jig, bottom" which comes first in the list but only
    // after wrapping around.
    expect(topLabel()).toHaveAttribute("aria-pressed", "false");
    expect(bottomLabel()).toHaveAttribute("aria-pressed", "false");
    expect(pickupLabel()).toHaveAttribute("aria-pressed", "true");
  });

  it("falls back to the legacy single-tool layout when the institute profile cannot be loaded", async () => {
    authState.current = { canWrite: true, demo: false, showToast: vi.fn() };
    vi.mocked(scanAssemblyComponent).mockResolvedValue(parent);
    vi.mocked(getInstitutes).mockRejectedValue(new Error("network down"));
    vi.mocked(getTools).mockResolvedValue([tool]);
    vi.mocked(getGlueBatches).mockResolvedValue([]);
    const user = userEvent.setup();
    render(<AssemblyWizardScreen onBack={vi.fn()} onStaged={vi.fn()} />);

    await user.type(screen.getByLabelText("Parent component"), `${parent.sn}{enter}`);

    // IMPORTANT #9: a broken institute-profile request is a silent fallback
    // to the legacy layout, not a Resources-step error banner, and it must
    // not take the tool/glue fetch (a separate request) down with it.
    expect(await screen.findByLabelText("Compatible tool")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /R5 assembly jig/ })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("suppresses the redundant per-slot hint once the broader no-tool hint already explains it", async () => {
    authState.current = { canWrite: true, demo: false, showToast: vi.fn() };
    vi.mocked(scanAssemblyComponent).mockResolvedValue(parent);
    vi.mocked(getInstitutes).mockResolvedValue([slotProfile]);
    vi.mocked(getTools).mockResolvedValue([]);
    vi.mocked(getGlueBatches).mockResolvedValue([]);
    const user = userEvent.setup();
    render(<AssemblyWizardScreen onBack={vi.fn()} onStaged={vi.fn()} />);

    await user.type(screen.getByLabelText("Parent component"), `${parent.sn}{enter}`);

    expect(
      await screen.findByText("No active tool is registered for R5M0. Update the tool registry first."),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("No active compatible tool is available for Hybrid glue jig, bottom."),
    ).not.toBeInTheDocument();
  });

  it("names a tool the same way the test-form tool pickers do, and stays keyboard operable", async () => {
    // One naming rule across the app (`fieldLayout.toolOptionLabel`): the
    // shop-floor label leads, the serial follows. The production sheet names
    // jigs by their sticker ("#3 (orange)") and keeps serials in a separate
    // inventory tab, so an operator recognises the label but has to be able
    // to check the serial that will reach the PDB without leaving the field.
    authState.current = { canWrite: true, demo: false, showToast: vi.fn() };
    vi.mocked(scanAssemblyComponent).mockResolvedValue(parent);
    vi.mocked(getInstitutes).mockResolvedValue([slotProfile]);
    vi.mocked(getTools).mockResolvedValue([jigBottom, jigTop]);
    vi.mocked(getGlueBatches).mockResolvedValue([]);
    const user = userEvent.setup();
    render(<AssemblyWizardScreen onBack={vi.fn()} onStaged={vi.fn()} />);

    await user.type(screen.getByLabelText("Parent component"), `${parent.sn}{enter}`);

    const quickSelect = (await screen.findByLabelText(
      "Add a tool to Hybrid glue jig, bottom",
    )) as HTMLSelectElement;
    expect(toolOptionLabel(jigBottom)).toBe("Bottom glue jig · JIG-BOT");
    expect(
      within(quickSelect).getByRole("option", { name: toolOptionLabel(jigBottom) }),
    ).toBeInTheDocument();

    // No mouse: focus the native select and choose by value.
    quickSelect.focus();
    expect(document.activeElement).toBe(quickSelect);
    await user.selectOptions(quickSelect, String(jigBottom.id));
    expect(
      within(slotChips("Hybrid glue jig, bottom")).getByText(toolOptionLabel(jigBottom)),
    ).toBeInTheDocument();
  });
});
