/**
 * Staged screen as an approval surface (spec §D + docs/05 "Ehrlichkeit im
 * Staged-Fenster").
 *
 * The load-bearing claims tested here:
 *  - a staged test upload shows the measurement it proposes, compacted the way
 *    the module worksheet compacts one (scalars inline, `+n`, extent chips) and
 *    NEVER as a raw curve or per-position map,
 *  - several staged changes on one component read as one group,
 *  - a non-submittable action explains itself instead of offering a button that
 *    would fail,
 *  - `Push to PDB` still chains the existing outbox transitions,
 *  - terminal actions live in the collapsed History, not in the work queue.
 *
 * The fixtures deliberately carry the shapes that would break each claim (a
 * 59-point array, a 20-key map, a leading empty scalar, a production
 * component, a ghost-less upload), so no assertion can pass by absence.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  ComponentOut,
  ComponentPreview,
  ComponentPreviewTest,
  OutboxAction,
} from "../api";
import {
  getComponentPreview,
  getComponentThumbnails,
  getComponents,
  getOutbox,
  getOutboxAudit,
  postOutboxTransition,
} from "../api";
import StagedScreen from "./StagedScreen";

const authState = vi.hoisted(() => ({
  current: {
    canWrite: true,
    isAdmin: false,
    showToast: vi.fn(),
    user: {
      email: "anna.abel@example.org",
      role: "operator",
      institute_code: "INST1" as string | null,
      institute_id: 1 as number | null,
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
    getComponentPreview: vi.fn(),
    getComponentThumbnails: vi.fn(),
    getComponents: vi.fn(),
    getOutbox: vi.fn(),
    getOutboxAudit: vi.fn(),
    postOutboxTransition: vi.fn(),
  };
});

const DUMMY_SN = "20USEM00000435";
const PRODUCTION_SN = "20USEM50000064";

/** A sentinel that only exists inside the staged IV curve: if it ever reaches
 * the DOM, the raw array was rendered. */
const CURVE_SENTINEL = 0.987654321;
const MAP_KEY = "ABC_R5H1_0";
const MAP_VALUE = 123.456;

const stagedGlueDerivation = {
  kind: "glue_weight",
  process: "TRUE_BLUE",
  process_source: "profile_default",
  steps: [
    {
      key: "hybrids",
      label: "Hybrid bondline",
      measured_mg: 166.4,
      target_mg: 164,
      tolerance_mg: 25,
      verdict: "ok",
      reason: null,
      result_code: "GW_GLUE_H1",
      inputs: [
        { code: "GW_SENSOR", name: "Sensor", value: 7.0162 },
        { code: "GW_MODULE_H1", name: "Module after hybrid", value: 9.3866 },
      ],
    },
  ],
};

const curve = [
  CURVE_SENTINEL,
  ...Array.from({ length: 58 }, (_, index) => index / 1000),
];
const thicknessMap = Object.fromEntries(
  Array.from({ length: 20 }, (_, index) =>
    index === 0 ? [MAP_KEY, MAP_VALUE] : [`PAD_${index}`, index + 0.5],
  ),
);

function component(overrides: Partial<ComponentOut> & { sn: string }): ComponentOut {
  return {
    local_name: "unnamed",
    component_type: "MODULE",
    type_code: "R5M0",
    stage: "GLUED",
    location: "INST1",
    institute_code: "INST1",
    parent_sn: null,
    is_dummy: false,
    trashed: false,
    stale: false,
    synced_at: "2026-08-26T10:00:00Z",
    ...overrides,
  };
}

const components: ComponentOut[] = [
  component({ sn: DUMMY_SN, local_name: "INST1-M-001", is_dummy: true }),
  component({ sn: PRODUCTION_SN, local_name: "INST1-M-002", is_dummy: false }),
];

function action(overrides: Partial<OutboxAction> & { id: number }): OutboxAction {
  return {
    institute_id: 1,
    kind: "upload_test_run",
    payload: { component_sn: DUMMY_SN, test_type: "GLUE_WEIGHT" },
    status: "draft",
    error: null,
    attempts: 0,
    external_ref: null,
    created_by: "anna.abel@example.org",
    created_at: "2026-08-26T08:00:00Z",
    updated_at: "2026-08-26T08:00:00Z",
    ...overrides,
  };
}

const actions: OutboxAction[] = [
  action({
    id: 501,
    payload: {
      component_sn: DUMMY_SN,
      test_type: "GLUE_WEIGHT",
      derived_results: { GW_GLUE_H1: 0.1664 },
      derived: stagedGlueDerivation,
    },
  }),
  action({
    id: 502,
    kind: "stage_move",
    payload: { component_sn: DUMMY_SN, to_stage: "BONDED" },
  }),
  action({
    id: 503,
    payload: { component_sn: PRODUCTION_SN, test_type: "MODULE_IV" },
  }),
  // Staged upload whose ghost projection is missing (component preview knows
  // the action but carries no ghost run for it).
  action({ id: 504, payload: { component_sn: DUMMY_SN, test_type: "MODULE_BOW" } }),
  action({ id: 505, status: "confirmed", external_ref: "PDB-1" }),
];

function ghost(overrides: Partial<ComponentPreviewTest>): ComponentPreviewTest {
  return {
    test_type: "GLUE_WEIGHT",
    passed: true,
    external_ref: null,
    measured_at: "2026-08-26T07:30:00Z",
    synced_at: null,
    source: "outbox",
    run_number: "3",
    properties: { JIG: "JIG-7", OPERATOR: "anna.abel" },
    results: {},
    result_meta: {},
    attachments: [],
    ghost: true,
    outbox_action_id: null,
    ...overrides,
  };
}

const dummyPreview: ComponentPreview = {
  current: { stage: "GLUED", checks: [] },
  staged_actions: [
    {
      id: 501,
      kind: "upload_test_run",
      status: "draft",
      summary: "GLUE_WEIGHT upload",
      to_stage: null,
      test_type: "GLUE_WEIGHT",
      created_by: "anna.abel@example.org",
      created_at: "2026-08-26T08:00:00Z",
      submittable: true,
      submittable_reason: null,
    },
    {
      id: 502,
      kind: "stage_move",
      status: "draft",
      summary: "→ BONDED",
      to_stage: "BONDED",
      test_type: null,
      created_by: "anna.abel@example.org",
      created_at: "2026-08-26T08:00:00Z",
      submittable: true,
      submittable_reason: null,
    },
    {
      id: 504,
      kind: "upload_test_run",
      status: "draft",
      summary: "MODULE_BOW upload",
      to_stage: null,
      test_type: "MODULE_BOW",
      created_by: "anna.abel@example.org",
      created_at: "2026-08-26T08:00:00Z",
      submittable: true,
      submittable_reason: null,
    },
  ],
  projected: {
    stage: "BONDED",
    checks: [],
    ghost_tests: [
      ghost({
        outbox_action_id: 501,
        // A leading empty scalar: filled values must still be the ones shown.
        results: {
          NOTE: null,
          GLUE_WEIGHT: 0.1664,
          TEMPERATURE: 21.5,
          HUMIDITY: 40,
          OPERATOR_NOTE: "clean",
          BATCH: "PX41A9F2K0",
          IV_CURRENT: curve,
          HYBRID_GLUE_THICKNESS: thicknessMap,
        },
        result_meta: {
          GLUE_WEIGHT: { name: "Glue weight" },
          IV_CURRENT: { name: "Current" },
          HYBRID_GLUE_THICKNESS: { name: "Hybrid glue thickness" },
        },
      }),
    ],
  },
  worksheet: { groups: [] },
};

const productionPreview: ComponentPreview = {
  current: { stage: "GLUED", checks: [] },
  staged_actions: [
    {
      id: 503,
      kind: "upload_test_run",
      status: "draft",
      summary: "MODULE_IV upload",
      to_stage: null,
      test_type: "MODULE_IV",
      created_by: "anna.abel@example.org",
      created_at: "2026-08-26T08:00:00Z",
      submittable: false,
      submittable_reason: "not_dummy",
    },
  ],
  projected: {
    stage: "GLUED",
    checks: [],
    ghost_tests: [
      ghost({
        outbox_action_id: 503,
        test_type: "MODULE_IV",
        passed: false,
        results: { I_500V: 12.5, IV_CURRENT: curve },
        result_meta: { I_500V: { name: "Leakage current" } },
      }),
    ],
  },
  worksheet: { groups: [] },
};

async function renderScreen(): Promise<void> {
  render(<StagedScreen onOpenComponent={vi.fn()} />);
  // The same component heads the open group and its History group, so wait on
  // the queue itself rather than on a name that legitimately appears twice.
  await waitFor(() => expect(openGroups()).toHaveLength(2));
}

/** The card for one outbox action, found by its stable `#id · kind` line. */
function cardFor(id: number, kind = "upload_test_run"): HTMLElement {
  const marker = screen.getByText(`#${id} · ${kind}`);
  const card = marker.closest("article");
  if (card === null) throw new Error(`No card rendered for action #${id}`);
  return card as HTMLElement;
}

function openGroups(): HTMLElement[] {
  return Array.from(
    document.querySelectorAll<HTMLElement>(".staged-groups .staged-component-group"),
  );
}

beforeEach(() => {
  authState.current = {
    canWrite: true,
    isAdmin: false,
    showToast: vi.fn(),
    user: {
      email: "anna.abel@example.org",
      role: "operator",
      institute_code: "INST1",
      institute_id: 1,
    },
  };
  vi.mocked(getOutbox).mockResolvedValue(actions);
  vi.mocked(getComponents).mockResolvedValue(components);
  vi.mocked(getComponentThumbnails).mockResolvedValue({});
  vi.mocked(getOutboxAudit).mockResolvedValue([]);
  vi.mocked(getComponentPreview).mockImplementation(async (sn: string) =>
    sn === DUMMY_SN ? dummyPreview : productionPreview,
  );
  vi.mocked(postOutboxTransition).mockImplementation(async (id, body) =>
    action({ id, status: body.to }),
  );
});

describe("staged measurement values", () => {
  it("shows the complete staged server derivation on the approval card and in details", async () => {
    await renderScreen();
    const card = cardFor(501);
    const summary = card.querySelector(".staged-action-summary") as HTMLElement;

    expect(within(summary).getByText("Hybrid bondline")).toBeInTheDocument();
    expect(within(summary).getByText("166.4 / 164 ± 25 mg")).toBeInTheDocument();

    const details = card.querySelector(".staged-action-details") as HTMLElement;
    await userEvent.setup().click(within(details).getByText("Action details"));
    expect(within(details).getByText("Derived by the server")).toBeInTheDocument();
    expect(within(details).getByText("166.4 mg")).toBeInTheDocument();
    expect(within(details).getByText(/revalidated by the worker/i)).toBeInTheDocument();
  });

  it("shows the proposed scalars inline and reduces arrays and maps to extent chips", async () => {
    await renderScreen();
    const card = cardFor(501);

    // Test type and run identity make the proposal judgeable in place.
    expect(within(card).getByText("GLUE_WEIGHT")).toBeInTheDocument();
    expect(within(card).getByText("run 3")).toBeInTheDocument();
    expect(within(card).getByText(/^measured /)).toBeInTheDocument();
    expect(within(card).getByText("2 conditions")).toBeInTheDocument();

    // Filled scalars come first even though an empty one is declared first.
    const values = card.querySelector(".staged-values");
    expect(values).not.toBeNull();
    const inline = within(values as HTMLElement);
    expect(inline.getByText("Glue weight")).toBeInTheDocument();
    expect(inline.getByText("0.1664")).toBeInTheDocument();
    expect(inline.getByText("TEMPERATURE")).toBeInTheDocument();
    expect(inline.getByText("21.5")).toBeInTheDocument();
    expect(inline.getByText("HUMIDITY")).toBeInTheDocument();
    // NOTE (empty) sorted behind the filled ones, so it is inside the `+n`.
    expect(inline.queryByText("NOTE")).not.toBeInTheDocument();
    expect(inline.getByText("+3")).toBeInTheDocument();

    // Extent chips, never the data.
    expect(inline.getByText("⌁ 59 pts")).toBeInTheDocument();
    expect(inline.getByText("⌁ 20 entries")).toBeInTheDocument();
  });

  it("never lets a raw array or map reach the DOM", async () => {
    await renderScreen();

    const rendered = document.body.textContent ?? "";
    expect(rendered).toContain("⌁ 59 pts");
    expect(rendered).not.toContain(String(CURVE_SENTINEL));
    expect(rendered).not.toContain(MAP_KEY);
    expect(rendered).not.toContain(String(MAP_VALUE));
    // The action details list is expandable but must obey the same rule.
    const detailText = cardFor(501).querySelector(".staged-action-details")?.textContent ?? "";
    expect(detailText).toContain("⌁ 20 entries");
    expect(detailText).not.toContain(MAP_KEY);
    expect(detailText).not.toContain(String(CURVE_SENTINEL));
  });

  it("lists every staged value in the expandable details, arrays still as counts", async () => {
    await renderScreen();
    const details = cardFor(501).querySelector(".staged-action-details") as HTMLElement;

    await userEvent.setup().click(within(details).getByText("Action details"));

    const list = within(details);
    expect(list.getByText("Staged values")).toBeInTheDocument();
    // The values hidden behind `+3` inline are reachable here.
    expect(list.getByText("OPERATOR_NOTE")).toBeInTheDocument();
    expect(list.getByText("clean")).toBeInTheDocument();
    expect(list.getByText("NOTE")).toBeInTheDocument();
    expect(list.getByText("Current")).toBeInTheDocument();
    expect(list.getByText("⌁ 59 pts")).toBeInTheDocument();
  });

  it("says so when a staged upload carries no readable measurement", async () => {
    await renderScreen();

    expect(
      within(cardFor(504)).getByText(/staged measurement could not be loaded/i),
    ).toBeInTheDocument();
    // A stage move proposes no measurement at all, so it must not claim a gap.
    expect(
      within(cardFor(502, "stage_move")).queryByText(/could not be loaded/i),
    ).not.toBeInTheDocument();
  });
});

describe("grouping by component", () => {
  it("collects every open action of one component under one header", async () => {
    await renderScreen();

    const groups = openGroups();
    expect(groups).toHaveLength(2);

    const dummyGroup = groups.find((group) =>
      group.textContent?.includes("INST1-M-001"),
    ) as HTMLElement;
    const scoped = within(dummyGroup);
    expect(scoped.getByText(DUMMY_SN)).toBeInTheDocument();
    expect(scoped.getByText("3 actions")).toBeInTheDocument();
    expect(dummyGroup.querySelectorAll("article")).toHaveLength(3);
    // The other component keeps its own group; no cross-contamination.
    expect(scoped.queryByText(PRODUCTION_SN)).not.toBeInTheDocument();

    const productionGroup = groups.find((group) =>
      group.textContent?.includes("INST1-M-002"),
    ) as HTMLElement;
    expect(within(productionGroup).getByText("1 action")).toBeInTheDocument();
  });
});

describe("honesty about what can be pushed", () => {
  it("replaces the push button with an explanation for a non-DUMMY component", async () => {
    await renderScreen();
    const card = cardFor(503);

    expect(within(card).queryByRole("button", { name: "Push to PDB" })).not.toBeInTheDocument();
    expect(
      within(card).getByText(
        "Production writes are not enabled — this stays staged (DUMMY-only scope).",
      ),
    ).toBeInTheDocument();
    // Its values are still shown: the action is reviewable, only not pushable.
    // (Inline strip plus the details list, hence All.)
    expect(within(card).getAllByText("Leakage current").length).toBeGreaterThan(0);
    expect(within(card).getAllByText("12.5").length).toBeGreaterThan(0);
    expect(within(card).getByText("failed")).toBeInTheDocument();
    // Discarding a non-pushable draft stays available.
    expect(within(card).getByRole("button", { name: "Discard" })).toBeInTheDocument();

    // A DUMMY-scoped action does get the button, so the assertion above is
    // about scope and not about the button being absent everywhere.
    expect(
      within(cardFor(501)).getByRole("button", { name: "Push to PDB" }),
    ).toBeInTheDocument();
  });

  it("explains the missing controls for a read-only user instead of showing nothing", async () => {
    authState.current = { ...authState.current, canWrite: false };
    await renderScreen();
    const card = cardFor(501);

    expect(within(card).queryByRole("button", { name: "Push to PDB" })).not.toBeInTheDocument();
    expect(within(card).queryByRole("button", { name: "Discard" })).not.toBeInTheDocument();
    expect(within(card).getByText(/do not have write permission/i)).toBeInTheDocument();
  });
});

describe("transitions", () => {
  it("chains the existing outbox transitions up to submitted", async () => {
    await renderScreen();

    await userEvent
      .setup()
      .click(within(cardFor(501)).getByRole("button", { name: "Push to PDB" }));

    await waitFor(() => {
      expect(vi.mocked(postOutboxTransition)).toHaveBeenCalledTimes(3);
    });
    const calls = vi.mocked(postOutboxTransition).mock.calls;
    expect(calls.map(([id, body]) => [id, body.to])).toEqual([
      [501, "validated"],
      [501, "approved"],
      [501, "submitted"],
    ]);
    expect(calls.every(([, body]) => body.actor === "anna.abel@example.org")).toBe(true);
    expect(authState.current.showToast).toHaveBeenCalled();
  });

  it("discards through the cancelled transition", async () => {
    await renderScreen();

    await userEvent
      .setup()
      .click(within(cardFor(501)).getByRole("button", { name: "Discard" }));

    await waitFor(() => {
      expect(vi.mocked(postOutboxTransition)).toHaveBeenCalledWith(501, {
        to: "cancelled",
        actor: "anna.abel@example.org",
      });
    });
  });
});

describe("history", () => {
  it("keeps terminal actions out of the work queue and inside History", async () => {
    await renderScreen();

    // #505 is confirmed: not part of any open group.
    for (const group of openGroups()) {
      expect(group.textContent).not.toContain("#505");
    }
    expect(screen.getByText("Open actions").nextElementSibling?.textContent).toBe("4");

    const history = document.querySelector(".staged-history") as HTMLElement;
    expect(history).not.toBeNull();
    const scoped = within(history);
    expect(scoped.getByText("History")).toBeInTheDocument();
    expect(scoped.getByText("#505 · upload_test_run")).toBeInTheDocument();
    // A terminal action offers no transition controls and claims no value gap.
    expect(scoped.queryByRole("button", { name: "Push to PDB" })).not.toBeInTheDocument();
    expect(scoped.queryByText(/could not be loaded/i)).not.toBeInTheDocument();
  });
});
