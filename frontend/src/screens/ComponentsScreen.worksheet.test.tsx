/**
 * Integration of the module worksheet into the component detail view
 * (spec 2026-08-25-staged-first-module-page-design.md §H3).
 *
 * ModuleWorksheet itself is a parallel deliverable and is mocked here — these
 * tests pin the CONTRACT between the detail panel and the worksheet: which
 * props it receives, that it mounts as the primary view in every preview mode,
 * that the previous full run list is demoted to a collapsed, lazily-fetched
 * "All mirrored runs" element, and that the required-tests ghost pencil now
 * routes into the worksheet edit strip instead of the Add-test-result card.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ScreenId } from "../App";
import type {
  ComponentDetail,
  ComponentPreview,
  StageSuggestion,
  TestTypeSchema,
} from "../api";
import {
  getComponent,
  getComponentAttachments,
  getComponentPreview,
  getComponentStaged,
  getComponentTests,
  getStageSuggestion,
  getTestTypeSchemas,
} from "../api";
import type { ModuleWorksheetProps } from "../ModuleWorksheet";
import { ComponentDetailPanel } from "./ComponentsScreen";

const authState = vi.hoisted(() => ({
  current: {
    canWrite: true,
    isAdmin: false,
    showToast: vi.fn(),
    user: {
      email: "operator@example.org",
      role: "operator",
      institute_code: "TUDO" as string | null,
      institute_id: 1 as number | null,
    },
  },
}));

vi.mock("../auth", () => ({
  useAuth: () => authState.current,
}));

// The worksheet is Agent A's file; the integration only owns the props.
const worksheetCalls = vi.hoisted(() => ({ log: [] as unknown[] }));
vi.mock("../ModuleWorksheet", () => ({
  default: (props: unknown) => {
    worksheetCalls.log.push(props);
    return <div data-testid="module-worksheet" />;
  },
}));

// The Add-test-result card stays mounted (spec §H3) but its internals belong
// to another file; recording its props is enough to assert intent routing.
const addTestCalls = vi.hoisted(() => ({ log: [] as unknown[] }));
vi.mock("../AddTestResult", () => ({
  default: (props: unknown) => {
    addTestCalls.log.push(props);
    return <div data-testid="add-test-result" />;
  },
}));

vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api")>();
  return {
    ...actual,
    getComponent: vi.fn(),
    getComponentAttachments: vi.fn(),
    getComponentPreview: vi.fn(),
    getComponentStaged: vi.fn(),
    getComponentTests: vi.fn(),
    getStageSuggestion: vi.fn(),
    getTestTypeSchemas: vi.fn(),
  };
});

const detailFixture: ComponentDetail = {
  sn: "20USEM00000001",
  local_name: "TUDO-M-001",
  component_type: "MODULE",
  type_code: "BM",
  stage: "GLUED",
  location: "TUDO",
  institute_code: "TUDO",
  parent_sn: null,
  is_dummy: true,
  trashed: false,
  stale: false,
  synced_at: "2026-08-26T10:00:00Z",
  children: [],
};

const previewFixture: ComponentPreview = {
  current: { stage: "GLUED", checks: [] },
  staged_actions: [],
  projected: { stage: "GLUED", checks: [], ghost_tests: [] },
  worksheet: {
    groups: [
      {
        stage: "GLUED",
        reached: true,
        rows: [
          {
            test_type: "GLUE_WEIGHT",
            status: "missing",
            latest: null,
            staged: [],
            run_count: 0,
          },
        ],
      },
    ],
  },
};

const suggestionFixture: StageSuggestion = {
  sn: detailFixture.sn,
  current_stage: "GLUED",
  next_stage: "BONDED",
  move_suggested: false,
  suggested_stage: null,
  checks: [{ stage: "GLUED", test_type: "MODULE_BOW", status: "missing" }],
  blocking: [],
};

const schemaFixture: TestTypeSchema = {
  id: 7,
  component_type: "MODULE",
  test_code: "GLUE_WEIGHT",
  name: "Glue weight",
  schema: { code: "GLUE_WEIGHT", results: [{ code: "GW", dataType: "float" }] },
  synced_at: "2026-08-26T09:00:00Z",
};

function lastWorksheetProps(): ModuleWorksheetProps {
  expect(worksheetCalls.log.length).toBeGreaterThan(0);
  return worksheetCalls.log[worksheetCalls.log.length - 1] as ModuleWorksheetProps;
}

type AddTestObservedProps = { initialTestType?: { testType: string; token: number } };

function renderDetail(onNavigate?: (screen: ScreenId) => void) {
  return render(
    <ComponentDetailPanel
      sn={detailFixture.sn}
      backLabel="Back"
      onBack={vi.fn()}
      onOpen={vi.fn()}
      evidenceJobId={null}
      evidenceEpoch={0}
      pinnedTestType={null}
      testIntentToken={0}
      onNavigate={onNavigate}
    />,
  );
}

beforeEach(() => {
  worksheetCalls.log = [];
  addTestCalls.log = [];
  authState.current = {
    canWrite: true,
    isAdmin: false,
    showToast: vi.fn(),
    user: {
      email: "operator@example.org",
      role: "operator",
      institute_code: "TUDO",
      institute_id: 1,
    },
  };
  vi.mocked(getComponent).mockResolvedValue(detailFixture);
  vi.mocked(getComponentPreview).mockResolvedValue(previewFixture);
  vi.mocked(getComponentStaged).mockResolvedValue([]);
  vi.mocked(getStageSuggestion).mockResolvedValue(suggestionFixture);
  vi.mocked(getTestTypeSchemas).mockResolvedValue([schemaFixture]);
  vi.mocked(getComponentAttachments).mockResolvedValue({
    component_sn: "20USEM20000041",
    attachments: [],
    children: [],
  });
  vi.mocked(getComponentTests).mockResolvedValue([]);
});

afterEach(() => {
  window.localStorage.clear();
});

describe("worksheet as the primary detail view", () => {
  it("mounts the worksheet with the preview payload and resolved write permission", async () => {
    renderDetail();

    await screen.findByTestId("module-worksheet");
    // Schemas arrive after their own fetch; an intermediate render can still
    // carry the pre-fetch `[]` (not `null`) shape, so wait for the settled
    // value itself rather than a weaker "is not null" check that a transient
    // render could satisfy first.
    let props!: ModuleWorksheetProps;
    await waitFor(() => {
      props = lastWorksheetProps();
      expect(props.schemas).toEqual([schemaFixture]);
    });

    expect(props.componentSn).toBe(detailFixture.sn);
    expect(props.componentType).toBe("MODULE");
    expect(props.instituteCode).toBe("TUDO");
    expect(props.worksheet).toEqual(previewFixture.worksheet);
    expect(props.canWrite).toBe(true);
    // Review finding I7: the full mirrored `TestTypeSchema` rows are passed
    // through untouched — `test_code`/`component_type`/`id` intact — rather
    // than unwrapped to the bare PDB schema JSON, whose own `code`/`testType`
    // the mirror explicitly tolerates being null.
    expect(props.schemas).toEqual([schemaFixture]);
  });

  it("wires 'View in Staged' to the app's existing navigation instead of leaving it dead (I3)", async () => {
    const onNavigate = vi.fn();
    renderDetail(onNavigate);

    await screen.findByTestId("module-worksheet");
    const props = lastWorksheetProps();
    expect(props.onViewStaged).toBeInstanceOf(Function);

    props.onViewStaged?.();
    expect(onNavigate).toHaveBeenCalledWith("staged");
  });

  it("resolves canWrite exactly like the other edit affordances (institute mismatch)", async () => {
    authState.current = {
      ...authState.current,
      user: { ...authState.current.user, institute_code: "DESYZ" },
    };
    renderDetail();

    await screen.findByTestId("module-worksheet");
    expect(lastWorksheetProps().canWrite).toBe(false);
  });

  it("demotes the run list to a collapsed element that only fetches once opened", async () => {
    renderDetail();
    await screen.findByTestId("module-worksheet");

    const summary = screen.getByText("All mirrored runs");
    expect(summary).toBeInTheDocument();
    // Collapsed by default: no run-list heading, no run fetch.
    expect(screen.queryByRole("heading", { name: "Test results" })).not.toBeInTheDocument();
    expect(vi.mocked(getComponentTests)).not.toHaveBeenCalled();

    await userEvent.setup().click(summary);
    await screen.findByRole("heading", { name: "Test results" });
    expect(vi.mocked(getComponentTests)).toHaveBeenCalledTimes(1);
  });

  it("still mounts the worksheet when the staged-preview preference is off", async () => {
    window.localStorage.setItem("itkflow.stagedPreview", "off");
    renderDetail();

    await screen.findByTestId("module-worksheet");
    // "Off" keeps the compact staged-changes list visible (docs/05).
    expect(await screen.findByRole("heading", { name: "Staged changes" })).toBeInTheDocument();
    expect(screen.getByText("All mirrored runs")).toBeInTheDocument();
  });
});

describe("ghost-pencil routing", () => {
  it("opens the worksheet edit strip instead of the form card, with a fresh token per click", async () => {
    renderDetail();
    await screen.findByTestId("module-worksheet");
    const user = userEvent.setup();

    const pencil = await screen.findByRole("button", { name: "Record MODULE_BOW result" });
    await user.click(pencil);
    await waitFor(() => {
      expect(lastWorksheetProps().editIntent).toEqual({ testType: "MODULE_BOW", token: 1 });
    });

    // A re-click of the same row must still re-open the strip: the token is
    // what distinguishes it from unchanged state.
    await user.click(pencil);
    await waitFor(() => {
      expect(lastWorksheetProps().editIntent).toEqual({ testType: "MODULE_BOW", token: 2 });
    });

    // The Add-test-result card never received the prefill intent.
    for (const call of addTestCalls.log) {
      expect((call as AddTestObservedProps).initialTestType).toBeUndefined();
    }
  });

  it("keeps the legacy form-card prefill when no worksheet can mount", async () => {
    vi.mocked(getComponentPreview).mockRejectedValue(new Error("preview down"));
    renderDetail();

    // Legacy fallback: full run list, no worksheet, no collapsed element.
    await screen.findByRole("heading", { name: "Test results" });
    expect(screen.queryByTestId("module-worksheet")).not.toBeInTheDocument();
    expect(screen.queryByText("All mirrored runs")).not.toBeInTheDocument();

    const pencil = await screen.findByRole("button", { name: "Record MODULE_BOW result" });
    await userEvent.setup().click(pencil);
    await waitFor(() => {
      const last = addTestCalls.log[addTestCalls.log.length - 1] as AddTestObservedProps;
      expect(last.initialTestType).toEqual({ testType: "MODULE_BOW", token: 1 });
    });
  });
});
