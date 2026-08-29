/**
 * The module page's history panel.
 *
 * WHY THIS FILE EXISTS. Both facts a production history is made of were
 * already mirrored and already displayed — the stage log fed the statistics
 * screen, the runs sat behind the worksheet — but never on one axis, so "what
 * happened to this module, and when" had to be reconstructed by hand. The
 * panel is deliberately not a filtered view of evidence: a retracted run is
 * shown, marked, because a gap in a record is itself a claim.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import type { ComponentHistory } from "../api";
import {
  getComponent,
  getComponentAttachments,
  getComponentHistory,
  getComponentPreview,
  getComponentStaged,
  getComponentTests,
  getMe,
  getStageSuggestion,
  getTestTypeSchemas,
} from "../api";
import { AuthProvider } from "../auth";
import { t } from "../i18n";
import {
  moduleDetail,
  MODULE_SN,
  operatorMe,
  previewPayload,
  stageSuggestion,
  testTypeSchemas,
} from "../test/moduleWorksheetFixtures";
import { ComponentDetailPanel } from "./ComponentsScreen";

vi.mock("../api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api")>()),
  getComponent: vi.fn(),
  getComponentAttachments: vi.fn(),
  getComponentHistory: vi.fn(),
  getComponentPreview: vi.fn(),
  getComponentStaged: vi.fn(),
  getComponentTests: vi.fn(),
  getMe: vi.fn(),
  getStageSuggestion: vi.fn(),
  getTestTypeSchemas: vi.fn(),
}));

const history: ComponentHistory = {
  component_sn: MODULE_SN,
  events: [
    {
      kind: "test",
      at: "2026-02-02T11:15:00",
      stage: null,
      location: null,
      rework: null,
      test_type: "GLUE_WEIGHT",
      passed: false,
      withdrawn: false,
      external_ref: "RUN-GW",
    },
    {
      kind: "stage",
      at: "2026-02-01T10:00:00",
      stage: "GLUED",
      location: null,
      rework: true,
      test_type: null,
      passed: null,
      withdrawn: null,
      external_ref: null,
    },
    {
      kind: "test",
      at: "2026-01-06T09:30:00",
      stage: null,
      location: null,
      rework: null,
      test_type: "MODULE_BOW",
      passed: true,
      withdrawn: true,
      external_ref: "RUN-BOW",
    },
    {
      kind: "location",
      at: "2026-01-20T07:00:00",
      stage: "GLUED",
      location: "UNIFREIBURG",
      rework: null,
      test_type: null,
      passed: null,
      withdrawn: null,
      external_ref: null,
    },
    {
      kind: "test",
      at: null,
      stage: null,
      location: null,
      rework: null,
      test_type: "MODULE_METROLOGY",
      passed: true,
      withdrawn: false,
      external_ref: "RUN-UNDATED",
    },
  ],
};

beforeEach(() => {
  vi.mocked(getMe).mockResolvedValue(operatorMe);
  vi.mocked(getComponent).mockResolvedValue(moduleDetail);
  vi.mocked(getComponentPreview).mockResolvedValue(previewPayload());
  vi.mocked(getComponentStaged).mockResolvedValue([]);
  vi.mocked(getStageSuggestion).mockResolvedValue(stageSuggestion);
  vi.mocked(getTestTypeSchemas).mockResolvedValue(testTypeSchemas);
  vi.mocked(getComponentTests).mockResolvedValue([]);
  vi.mocked(getComponentAttachments).mockResolvedValue({
    component_sn: MODULE_SN,
    attachments: [],
    children: [],
  });
  vi.mocked(getComponentHistory).mockResolvedValue(history);
});

function renderModulePage() {
  return render(
    <AuthProvider>
      <ComponentDetailPanel
        sn={MODULE_SN}
        backLabel="Back"
        onBack={vi.fn()}
        onOpen={vi.fn()}
        evidenceJobId={null}
        evidenceEpoch={0}
        pinnedTestType={null}
        testIntentToken={0}
        onNavigate={vi.fn()}
      />
    </AuthProvider>,
  );
}

async function historyPanel(): Promise<HTMLElement> {
  const heading = await screen.findByRole("heading", { name: t.images.historyTitle });
  const panel = heading.nextElementSibling;
  if (!(panel instanceof HTMLElement)) throw new Error("history panel not found");
  return panel;
}

/** The panel fetches its own events, so the rows arrive after the heading. */
async function historyItems(): Promise<HTMLElement[]> {
  const panel = await historyPanel();
  return within(panel).findAllByRole("listitem");
}

it("shows stages and runs on one axis, in the order the server sent them", async () => {
  renderModulePage();

  const items = await historyItems();

  expect(items).toHaveLength(5);
  expect(items[0]).toHaveTextContent("GLUE_WEIGHT");
  expect(items[1]).toHaveTextContent(/Glued/i);
  expect(items[2]).toHaveTextContent("MODULE_BOW");
  expect(items[3]).toHaveTextContent(t.images.historyMovedTo("UNIFREIBURG"));
  expect(items[4]).toHaveTextContent("MODULE_METROLOGY");
});

it("marks rework, retraction and a missing measurement time", async () => {
  renderModulePage();
  const items = await historyItems();

  expect(items[1]).toHaveTextContent(t.images.historyRework);
  // Retracted, but present: omitting it would leave an unexplained gap.
  expect(items[2]).toHaveTextContent(t.images.historyWithdrawn);
  expect(items[4]).toHaveTextContent(t.images.historyUndated);
});

it("says so plainly when the mirror holds nothing for this component", async () => {
  vi.mocked(getComponentHistory).mockResolvedValue({
    component_sn: MODULE_SN,
    events: [],
  });

  renderModulePage();

  await waitFor(async () => {
    expect(await historyPanel()).toHaveTextContent(t.images.historyEmpty);
  });
});

it("degrades to the empty state instead of taking the page down", async () => {
  // A panel is one part of the page. If its payload is unreadable it must
  // report nothing, not throw during render and unmount everything around it.
  vi.mocked(getComponentHistory).mockResolvedValue(
    undefined as unknown as ComponentHistory,
  );

  renderModulePage();

  await waitFor(async () => {
    expect(await historyPanel()).toHaveTextContent(t.images.historyEmpty);
  });
});
