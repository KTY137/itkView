/**
 * End-to-end integration of the module page's test worksheet
 * (spec `2026-08-25-staged-first-module-page-design.md` §H).
 *
 * WHY THIS FILE EXISTS. `ComponentsScreen.worksheet.test.tsx` mocks
 * `ModuleWorksheet`, and `ModuleWorksheet.test.tsx` mocks `TestResults` — so
 * both stayed green while the two sides disagreed about the *shape* of the
 * schema prop. This suite renders the REAL tree instead:
 *
 *   ComponentDetailPanel → ModuleWorksheet → TestForm / TestResults renderers
 *   → testStaging (ingest → dry-run → propose-outbox)
 *
 * and mocks nothing but the network layer (`api.ts` request functions). Even
 * the auth context is the real `AuthProvider`, driven by a mocked `getMe`, so
 * write permission and the staged toast are resolved exactly as in the app.
 *
 * Fixtures live in `src/test/moduleWorksheetFixtures.ts` and follow the shapes
 * `app/preview.py` really emits (including a dict-valued metrology result).
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { IngestFileCreate } from "../api";
import {
  getComponent,
  getComponentAttachments,
  getComponentPreview,
  getComponentStaged,
  getComponentTests,
  getIngestPreview,
  getMe,
  getStageSuggestion,
  getTestTypeSchemas,
  postIngestFile,
  postIngestOutboxProposal,
} from "../api";
import { AuthProvider } from "../auth";
import { t } from "../i18n";
import {
  blockedDryRun,
  cleanDryRun,
  glueWeightSchema,
  ingestFile,
  INSTITUTE_CODE,
  ivSchema,
  IV_CURRENTS,
  IV_LENGTH_ISSUE,
  IV_VOLTAGES,
  METROLOGY_THICKNESS,
  mirroredRuns,
  moduleDetail,
  MODULE_SN,
  operatorMe,
  previewPayload,
  stageSuggestion,
  stagedAction,
  stagedActionMetadata,
  testTypeSchemas,
} from "../test/moduleWorksheetFixtures";
import { ComponentDetailPanel } from "./ComponentsScreen";

vi.mock("../api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api")>()),
  getComponent: vi.fn(),
  getComponentAttachments: vi.fn(),
  getComponentPreview: vi.fn(),
  getComponentStaged: vi.fn(),
  getComponentTests: vi.fn(),
  getIngestPreview: vi.fn(),
  getMe: vi.fn(),
  getStageSuggestion: vi.fn(),
  getTestTypeSchemas: vi.fn(),
  postIngestFile: vi.fn(),
  postIngestOutboxProposal: vi.fn(),
}));

/** Ordered record of the staging pipeline, so "in this order" is assertable. */
let pipeline: string[] = [];

beforeEach(() => {
  pipeline = [];
  vi.mocked(getMe).mockResolvedValue(operatorMe);
  vi.mocked(getComponent).mockResolvedValue(moduleDetail);
  vi.mocked(getComponentPreview).mockResolvedValue(previewPayload());
  vi.mocked(getComponentStaged).mockResolvedValue([]);
  vi.mocked(getStageSuggestion).mockResolvedValue(stageSuggestion);
  vi.mocked(getTestTypeSchemas).mockResolvedValue(testTypeSchemas);
  vi.mocked(getComponentAttachments).mockResolvedValue({
    component_sn: MODULE_SN,
    attachments: [],
    children: [],
  });
  vi.mocked(getComponentTests).mockResolvedValue(mirroredRuns);
  vi.mocked(postIngestFile).mockImplementation(async (body: IngestFileCreate) => {
    pipeline.push(`ingest:${body.filename}`);
    return ingestFile;
  });
  vi.mocked(getIngestPreview).mockImplementation(async (id: number) => {
    pipeline.push(`dry-run:${id}`);
    return cleanDryRun;
  });
  vi.mocked(postIngestOutboxProposal).mockImplementation(async (id: number) => {
    pipeline.push(`propose:${id}`);
    return stagedAction;
  });
});

// ---- Shared harness ---------------------------------------------------------

/** The real detail panel inside the real auth provider. */
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

async function openModulePage() {
  const view = renderModulePage();
  await screen.findByRole("heading", { name: t.worksheet.title });
  return view;
}

function worksheet(): HTMLElement {
  const heading = screen.getByRole("heading", { name: t.worksheet.title });
  const root = heading.parentElement;
  if (root === null) throw new Error("worksheet root not found");
  return root;
}

function worksheetRow(testType: string): HTMLElement {
  const cell = within(worksheet()).getByRole("cell", { name: testType });
  const row = cell.closest("tr");
  if (row === null) throw new Error(`no worksheet row for ${testType}`);
  return row;
}

/**
 * Everything a user could read off the page: rendered text plus the attributes
 * that surface on hover or to a screen reader. The worksheet's whole reason to
 * exist is that raw curves/maps never get here (spec §H1).
 */
function readableSurface(): string {
  const parts: string[] = [document.body.textContent ?? ""];
  for (const element of Array.from(
    document.body.querySelectorAll<HTMLElement>("[title], [aria-label], [alt]"),
  )) {
    for (const attribute of ["title", "aria-label", "alt"]) {
      const value = element.getAttribute(attribute);
      if (value !== null) parts.push(value);
    }
  }
  return parts.join("\u0000");
}

function leaked(tokens: readonly string[]): string[] {
  const surface = readableSurface();
  return tokens.filter((token) => surface.includes(token));
}

/** Raw per-position metrology content — never renderable, collapsed or not. */
const MAP_TOKENS = [
  ...Object.keys(METROLOGY_THICKNESS),
  ...Object.values(METROLOGY_THICKNESS).map(String),
  // What a dict reaching a scalar renderer stringifies to.
  "[object Object]",
] as const;

/** Raw sweep samples; only the expanded run detail may show any of these. */
const ARRAY_TOKENS = [...IV_CURRENTS.map(String), "-300"] as const;

// ---- 1. Compact rows --------------------------------------------------------

describe("compact worksheet rendering", () => {
  it("groups rows by stage and renders scalars inline, extras as +n, arrays and maps as count chips", async () => {
    await openModulePage();
    const sheet = within(worksheet());

    // One group per stage of the model, humanised; a stage with no required
    // tests renders no table at all.
    expect(sheet.getByText("HV Tab Attached")).toBeInTheDocument();
    expect(sheet.getByText("Glued")).toBeInTheDocument();
    expect(sheet.getByText("Tested")).toBeInTheDocument();
    expect(sheet.getByText(t.worksheet.additionalGroup)).toBeInTheDocument();
    expect(sheet.queryByText("Stitch Bonding")).not.toBeInTheDocument();
    // Exactly the one non-empty group beyond the component's current stage.
    expect(sheet.getAllByText(t.worksheet.futureStage)).toHaveLength(1);

    const ivRow = within(worksheetRow("MODULE_IV_PS_V1"));
    expect(ivRow.getByText("Humidity [%]")).toBeInTheDocument();
    expect(ivRow.getByText("31.4")).toBeInTheDocument();
    expect(ivRow.getByText("Temperature [C]")).toBeInTheDocument();
    expect(ivRow.getByText("21.5")).toBeInTheDocument();
    expect(ivRow.getByText("stable")).toBeInTheDocument();
    // Scalars 4 and 5 collapse into one chip and are only reachable on hover.
    expect(ivRow.queryByText("Setup id")).not.toBeInTheDocument();
    expect(ivRow.getByText(t.worksheet.moreValues(2))).toHaveAttribute(
      "title",
      "Cycles 3, Setup id IV-BOX-2",
    );
    // Both sweeps are point counts, never samples.
    expect(ivRow.getAllByText(t.worksheet.arrayPoints(4))).toHaveLength(2);
    expect(ivRow.getByText(t.worksheet.statusPassed)).toBeInTheDocument();

    // A dict-valued metrology result is an entry count, not "3 pts" and not a dump.
    const metrologyRow = within(worksheetRow("MODULE_METROLOGY"));
    expect(metrologyRow.getByText(t.worksheet.mapEntries(3))).toBeInTheDocument();
    expect(metrologyRow.getByText(t.worksheet.mapEntries(0))).toBeInTheDocument();

    // A row with no mirrored run shows no values and offers no expander.
    const glueRow = within(worksheetRow("GLUE_WEIGHT"));
    expect(glueRow.getByText(t.worksheet.statusMissing)).toBeInTheDocument();
    expect(
      glueRow.queryByRole("button", { name: t.worksheet.expandRow("GLUE_WEIGHT") }),
    ).not.toBeInTheDocument();

    // The contract itself: no raw curve sample and no per-position map key or
    // value anywhere on the page — text, title or aria-label.
    expect(leaked([...MAP_TOKENS, ...ARRAY_TOKENS])).toEqual([]);
    // …and the heavy mirrored-runs payload was never even requested.
    expect(getComponentTests).not.toHaveBeenCalled();
  });
});

// ---- 2. Lazy expansion ------------------------------------------------------

describe("expanding a row", () => {
  it("fetches the mirrored runs only on expansion and renders that run's curve, values, conditions and mirrored image", async () => {
    const user = userEvent.setup();
    await openModulePage();

    expect(getComponentTests).not.toHaveBeenCalled();
    expect(screen.queryByRole("img", { name: /Leakage current/u })).not.toBeInTheDocument();
    expect(screen.queryByText("Setup id")).not.toBeInTheDocument();

    await user.click(
      within(worksheetRow("MODULE_IV_PS_V1")).getByRole("button", {
        name: t.worksheet.expandRow("MODULE_IV_PS_V1"),
      }),
    );

    await waitFor(() => expect(getComponentTests).toHaveBeenCalledTimes(1));
    expect(vi.mocked(getComponentTests).mock.calls[0]?.[0]).toBe(MODULE_SN);

    // The curve is paired VOLTAGE/CURRENT and labelled from result_meta.
    await screen.findByRole("img", {
      name: "Leakage current [uA] over Bias voltage [V]",
    });
    expect(
      screen.getByText(`Leakage current [uA] / Bias voltage [V] · ${t.testResults.curvePoints(4)}`),
    ).toBeInTheDocument();
    // Scalars that the compact row hid are now spelled out.
    expect(screen.getByText("Setup id")).toBeInTheDocument();
    expect(screen.getByText("IV-BOX-2")).toBeInTheDocument();
    // Conditions come from the run's properties.
    expect(screen.getByText(t.testResults.conditions)).toBeInTheDocument();
    expect(screen.getByText("Anna Abel")).toBeInTheDocument();
    // Attachments are read from the local mirror route, never from the PDB.
    expect(screen.getByAltText("IV sweep plot")).toHaveAttribute(
      "src",
      `/api/components/${MODULE_SN}/attachments/att-iv-3`,
    );

    // Proof that the collapsed-state sweep above is capable of failing: the
    // sweep's own tokens do show up once the raw run is on screen.
    expect(leaked([String(IV_CURRENTS[0]), String(IV_CURRENTS[3])])).toEqual([
      String(IV_CURRENTS[0]),
      String(IV_CURRENTS[3]),
    ]);
    // The expansion is scoped to this row's test type: the metrology run that
    // came back in the same response stays unrendered.
    expect(leaked(MAP_TOKENS)).toEqual([]);
  });
});

// ---- 3. The staging chain ---------------------------------------------------

describe("staging an in-row edit", () => {
  async function openIvEditStrip() {
    const user = userEvent.setup();
    await openModulePage();
    await user.click(
      within(worksheetRow("MODULE_IV_PS_V1")).getByRole("button", {
        name: t.worksheet.editFor("MODULE_IV_PS_V1"),
      }),
    );
    // Prefill waits for the mirrored run behind this row.
    await screen.findByLabelText(/Bias voltage/u);
    return user;
  }

  function fillRunHeader() {
    fireEvent.change(screen.getByLabelText(/Run number/u), { target: { value: "4" } });
    fireEvent.change(screen.getByLabelText(/Measurement date/u), {
      target: { value: "2026-08-26T10:00" },
    });
  }

  it("prefills from the mirrored run, then runs ingest → dry-run → propose-outbox in order and shows the ghost row", async () => {
    // The server's own view after propose-outbox: the staged upload now hangs
    // off the worksheet row, which is what must survive the parent's refresh.
    vi.mocked(getComponentPreview)
      .mockResolvedValueOnce(previewPayload())
      .mockResolvedValue(
        previewPayload({
          stagedByRow: { MODULE_IV_PS_V1: [{ outbox_action_id: 92, status: "draft" }] },
          stagedActions: [stagedActionMetadata],
        }),
      );
    vi.mocked(getComponentStaged).mockResolvedValueOnce([]).mockResolvedValue([stagedAction]);

    const user = await openIvEditStrip();

    // Prefill crosses all three files: worksheet row → mirrored run → schema
    // field → generated control.
    expect(screen.getByLabelText(/Bias voltage/u)).toHaveValue(IV_VOLTAGES.join("\n"));
    expect(screen.getByLabelText(/Leakage current/u)).toHaveValue(IV_CURRENTS.join("\n"));
    // Floats render as text inputs on purpose (see TestForm): a numeric
    // input would swallow the comma decimal separator this lab types.
    expect(screen.getByLabelText(/Humidity/u)).toHaveValue("31.4");
    expect(screen.getByLabelText(/Assembly jig/u)).toHaveValue("JIG-07");

    fillRunHeader();
    await user.click(screen.getByRole("button", { name: t.worksheet.testForm.submit }));

    await waitFor(() => expect(postIngestOutboxProposal).toHaveBeenCalledTimes(1));
    expect(pipeline).toEqual([
      `ingest:${t.worksheet.manualFilename("MODULE_IV_PS_V1")}`,
      `dry-run:${ingestFile.id}`,
      `propose:${ingestFile.id}`,
    ]);

    const body = vi.mocked(postIngestFile).mock.calls[0]?.[0];
    expect(body).toEqual(
      expect.objectContaining({
        filename: "MODULE_IV_PS_V1-manual.json",
        component_sn: MODULE_SN,
        test_type: "MODULE_IV_PS_V1",
        parser: "manual-entry",
      }),
    );
    // The values survive the round trip as typed data, not joined strings.
    expect(body?.payload.results).toEqual({
      VOLTAGE: IV_VOLTAGES,
      CURRENT: IV_CURRENTS,
      HUMIDITY: 31.4,
    });
    expect(body?.payload.properties).toEqual({ JIG: "JIG-07" });
    expect(body?.payload.component).toBe(MODULE_SN);
    expect(body?.payload.runNumber).toBe("4");
    // Attribution stays server-side (no client actor on the ingest contract).
    expect(body).not.toHaveProperty("created_by");
    expect(body).not.toHaveProperty("actor");

    expect(postIngestOutboxProposal).toHaveBeenCalledWith(ingestFile.id, {
      institute_code: INSTITUTE_CODE,
    });

    // The strip closes and the operator is told what was staged.
    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: t.worksheet.testForm.submit }),
      ).not.toBeInTheDocument(),
    );
    expect(await screen.findByText(t.addTest.stagedToast(stagedAction.id))).toBeInTheDocument();

    // Ghost row appears — and is still there once the parent's preview refresh
    // has landed, i.e. the optimistic row hands over to the server's own view.
    expect(within(worksheet()).getByText(t.worksheet.stagedUpload(stagedAction.id))).toBeInTheDocument();
    await waitFor(() => expect(getComponentPreview).toHaveBeenCalledTimes(2));
    await waitFor(() =>
      expect(
        within(worksheet()).getByText(t.worksheet.stagedUpload(stagedAction.id)),
      ).toBeInTheDocument(),
    );
  });

  it("stops at a dry-run with blocking issues: no propose-outbox, no ghost, issues on screen", async () => {
    vi.mocked(getIngestPreview).mockImplementation(async (id: number) => {
      pipeline.push(`dry-run:${id}`);
      return blockedDryRun;
    });

    const user = await openIvEditStrip();
    fillRunHeader();
    await user.click(screen.getByRole("button", { name: t.worksheet.testForm.submit }));

    expect(await screen.findByText(IV_LENGTH_ISSUE)).toBeInTheDocument();
    expect(screen.getByText(t.worksheet.issuesTitle)).toBeInTheDocument();
    expect(postIngestOutboxProposal).not.toHaveBeenCalled();
    expect(pipeline).toEqual([
      `ingest:${t.worksheet.manualFilename("MODULE_IV_PS_V1")}`,
      `dry-run:${ingestFile.id}`,
    ]);
    // Nothing was staged: no ghost row, and the parent never refreshed.
    expect(
      within(worksheet()).queryByText(t.worksheet.stagedUpload(stagedAction.id)),
    ).not.toBeInTheDocument();
    expect(getComponentPreview).toHaveBeenCalledTimes(1);
    // The strip stays open so the operator can correct and retry.
    expect(screen.getByRole("button", { name: t.worksheet.testForm.submit })).toBeInTheDocument();
  });
});

// ---- 4. The schema-shape coupling the mocks hid -----------------------------

describe("schema resolution across the screen/worksheet boundary", () => {
  it("matches a row's schema from the exact prop shape ComponentsScreen passes", async () => {
    const user = userEvent.setup();
    await openModulePage();

    await user.click(
      within(worksheetRow("GLUE_WEIGHT")).getByRole("button", {
        name: t.worksheet.editFor("GLUE_WEIGHT"),
      }),
    );

    // Regression guard. The row is matched on the mirrored row's own
    // `test_code` + `component_type`; the nested PDB JSON in the fixture
    // carries neither (the mirror tolerates both being null), and the
    // component's `type_code` ("R5M0") differs from its `component_type`
    // ("MODULE"). So this only renders if the screen hands over the full
    // schema rows *and* the component type — the two facts the mutually
    // mocked unit tests could not observe.
    expect(await screen.findByLabelText(/Weight of glue under hybrid 1/u)).toBeInTheDocument();
    expect(screen.queryByText(t.worksheet.noSchema("GLUE_WEIGHT"))).not.toBeInTheDocument();
    expect(getTestTypeSchemas).toHaveBeenCalledWith(
      moduleDetail.component_type,
      expect.anything(),
    );
    // Only this row's schema is rendered, not the other mirrored one.
    expect(screen.queryByLabelText(/Bias voltage/u)).not.toBeInTheDocument();
    // Premise guard: the assertion above is only a regression test while the
    // nested PDB JSON stays identity-free.
    expect(glueWeightSchema.schema.code).toBeUndefined();
  });

  it("says so when no mirrored schema matches the row, instead of an empty strip", async () => {
    // Counter-case for the test above: same code path, no match. Without it,
    // "the field rendered" could pass for reasons unrelated to matching.
    vi.mocked(getTestTypeSchemas).mockResolvedValue([ivSchema]);
    const user = userEvent.setup();
    await openModulePage();

    await user.click(
      within(worksheetRow("GLUE_WEIGHT")).getByRole("button", {
        name: t.worksheet.editFor("GLUE_WEIGHT"),
      }),
    );

    expect(await screen.findByText(t.worksheet.noSchema("GLUE_WEIGHT"))).toBeInTheDocument();
    expect(screen.queryByLabelText(/Weight of glue under hybrid 1/u)).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: t.worksheet.testForm.submit }),
    ).not.toBeInTheDocument();
  });
});

// ---- 5. Requirements ghost pencil → worksheet edit strip --------------------

describe("required-tests ghost pencil", () => {
  it("opens the worksheet edit strip for that test type, and reopens it on a second click", async () => {
    const user = userEvent.setup();
    await openModulePage();

    const requirementsPencil = screen.getByRole("button", {
      name: t.components.recordTestFor("GLUE_WEIGHT"),
    });
    await user.click(requirementsPencil);

    expect(await screen.findByLabelText(/Weight of glue under hybrid 1/u)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: t.worksheet.testForm.submit })).toBeInTheDocument();
    // The intent went to the worksheet, not back to the file-drop card.
    expect(screen.getByRole("button", { name: t.addTest.recordTest })).toHaveAttribute(
      "aria-expanded",
      "false",
    );

    // Close it again from the row's own pencil.
    await user.click(
      within(worksheetRow("GLUE_WEIGHT")).getByRole("button", {
        name: t.worksheet.editFor("GLUE_WEIGHT"),
      }),
    );
    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: t.worksheet.testForm.submit }),
      ).not.toBeInTheDocument(),
    );

    // A second click carries the same test type — only the bumped token can
    // reopen the strip.
    await user.click(requirementsPencil);
    expect(await screen.findByLabelText(/Weight of glue under hybrid 1/u)).toBeInTheDocument();
  });
});

// ---- Finding: dict-valued results in the expanded run detail ----------------

describe("expanded run detail for a dict-valued (map) result — known gap", () => {
  /**
   * FINDING (not fixed here: `TestResults.tsx` is owned by another agent).
   *
   * `TestResults.RunScalars` treats every non-numeric-array result as a scalar
   * and formats it with `formatScalar`, which falls through to `String(value)`
   * for a dict. A real MODULE_METROLOGY run — whose per-position results are
   * dicts, see `app/preview.py::_worksheet_latest_run` and
   * `backend/tests/test_preview_worksheet.py::
   * test_dict_valued_results_are_summarised_as_a_map_not_a_scalar` — therefore
   * renders as the literal text "[object Object]" once the row is expanded.
   * The compact worksheet row is correct ("⌁ 3 entries"); only the expanded
   * detail loses the data.
   *
   * This test pins the expected behaviour: the operator must see the measured
   * per-position values (or at least an honest summary), never "[object Object]".
   */
  it("shows the per-position values instead of [object Object]", async () => {
    const user = userEvent.setup();
    await openModulePage();

    await user.click(
      within(worksheetRow("MODULE_METROLOGY")).getByRole("button", {
        name: t.worksheet.expandRow("MODULE_METROLOGY"),
      }),
    );

    await screen.findByText("Hybrid glue thickness [um]");
    // Verified 2026-08-26 by running this block unskipped: it currently finds
    // TWO "[object Object]" nodes (the filled map and the empty one).
    expect(screen.queryAllByText("[object Object]")).toEqual([]);
    expect(screen.getByText(/ABC_R5H1_0/u)).toBeInTheDocument();
  });
});
