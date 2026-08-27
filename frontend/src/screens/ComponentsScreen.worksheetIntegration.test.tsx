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
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { IngestFileCreate, OutboxAction, TestTypeSchema } from "../api";
import {
  getComponent,
  getComponentAttachments,
  getComponentPreview,
  getComponentStaged,
  getComponentTests,
  getIngestPreview,
  getMe,
  getOutboxAction,
  getStageSuggestion,
  getTestTypeSchemas,
  postIngestFile,
  postIngestOutboxProposal,
  postOutboxAction,
  postOutboxTransition,
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
  getOutboxAction: vi.fn(),
  getStageSuggestion: vi.fn(),
  getTestTypeSchemas: vi.fn(),
  postIngestFile: vi.fn(),
  postIngestOutboxProposal: vi.fn(),
  postOutboxAction: vi.fn(),
  postOutboxTransition: vi.fn(),
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
  vi.mocked(getOutboxAction).mockResolvedValue({ ...stagedAction, status: "confirmed" });
  vi.mocked(postOutboxAction).mockResolvedValue({
    ...stagedAction,
    id: 93,
    kind: "stage_move",
  });
  vi.mocked(postOutboxTransition).mockImplementation(async (id, body) => ({
    ...stagedAction,
    id,
    status: body.to,
  }));
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
      `/api/components/${MODULE_SN}/attachments/att-iv-3?source=pdb`,
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
    // Two bootstrap reads close the initial Preview/Staged/Suggestion race;
    // the successful draft adds the third refresh.
    await waitFor(() => expect(getComponentPreview).toHaveBeenCalledTimes(3));
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
    expect(getComponentPreview).toHaveBeenCalledTimes(2);
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

  it("moves a file-only worksheet edit to the existing JSON drop and focuses it", async () => {
    const fileOnlyMetrologySchema: TestTypeSchema = {
      id: 19,
      component_type: "MODULE",
      test_code: "MODULE_METROLOGY",
      name: "Module metrology",
      synced_at: "2026-08-27T12:00:00Z",
      schema: {
        properties: [],
        parameters: [
          {
            code: "HYBRID_GLUE_THICKNESS",
            name: "Hybrid glue thickness [um]",
            dataType: "object",
            required: true,
          },
          { code: "SHIELDBOX_HEIGHT", name: "Shield box height [um]", dataType: "float" },
        ],
      },
    };
    vi.mocked(getTestTypeSchemas).mockResolvedValue([...testTypeSchemas, fileOnlyMetrologySchema]);
    const scrollIntoView = vi.fn();
    Element.prototype.scrollIntoView = scrollIntoView;
    const user = userEvent.setup();
    await openModulePage();

    const fileEntry = screen.getByLabelText(t.addTest.chooseFile);
    await user.click(
      within(worksheetRow("MODULE_METROLOGY")).getByRole("button", {
        name: t.worksheet.editFor("MODULE_METROLOGY"),
      }),
    );

    expect(await screen.findByText(/Hybrid glue thickness \[um\] \(HYBRID_GLUE_THICKNESS\)/u))
      .toBeInTheDocument();
    expect(screen.queryByRole("button", { name: t.worksheet.testForm.submit }))
      .not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: t.worksheet.useFileUpload }));

    await waitFor(() => expect(document.activeElement).toBe(fileEntry));
    expect(scrollIntoView).toHaveBeenCalledWith({ behavior: "smooth", block: "center" });
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

  it("rechecks the suggestion after the initial staged snapshot closes a worker-confirmation race", async () => {
    const readySuggestion = {
      ...stageSuggestion,
      move_suggested: true,
      suggested_stage: "STITCH_BONDING",
      checks: stageSuggestion.checks.map((check) =>
        check.test_type === "GLUE_WEIGHT" ? { ...check, status: "passed" as const } : check,
      ),
      blocking: [],
    };
    const confirmedPreview = previewPayload();
    const glueRow = confirmedPreview.worksheet.groups
      .flatMap((group) => group.rows)
      .find((row) => row.test_type === "GLUE_WEIGHT");
    if (glueRow === undefined) throw new Error("GLUE_WEIGHT fixture row missing");
    glueRow.status = "passed";
    vi.mocked(getComponentPreview)
      .mockResolvedValueOnce(previewPayload())
      .mockResolvedValue(confirmedPreview);
    vi.mocked(getComponentStaged).mockResolvedValue([]);
    // The first request represents a read begun just before confirmation. The
    // staged snapshot already sees the terminal action gone, so the detail
    // panel must make a second, sequenced suggestion read.
    vi.mocked(getStageSuggestion)
      .mockResolvedValueOnce(stageSuggestion)
      .mockResolvedValue(readySuggestion);

    await openModulePage();

    expect(await screen.findByRole("button", {
      name: t.components.stageProposeMove("Stitch Bonding"),
    })).toBeInTheDocument();
    expect(getStageSuggestion).toHaveBeenCalledTimes(2);
    expect(getComponentPreview).toHaveBeenCalledTimes(2);
    await waitFor(() =>
      expect(within(worksheetRow("GLUE_WEIGHT")).getByText(t.worksheet.statusPassed))
        .toBeInTheDocument(),
    );
  });

  it("resumes a failed worker action after reload and follows its retry to confirmation", async () => {
    let workerStatus: OutboxAction["status"] = "failed";
    let statusPolls = 0;
    const failedAction: OutboxAction = {
      ...stagedAction,
      status: "failed",
      error: "PDB unavailable: temporary test outage",
      payload: {
        ...stagedAction.payload,
        component_sn: MODULE_SN,
        test_type: "GLUE_WEIGHT",
        passed: true,
      },
    };
    const readySuggestion = {
      ...stageSuggestion,
      move_suggested: true,
      suggested_stage: "STITCH_BONDING",
      checks: stageSuggestion.checks.map((check) =>
        check.test_type === "GLUE_WEIGHT" ? { ...check, status: "passed" as const } : check,
      ),
      blocking: [],
    };
    const confirmedPreview = previewPayload();
    const glueRow = confirmedPreview.worksheet.groups
      .flatMap((group) => group.rows)
      .find((row) => row.test_type === "GLUE_WEIGHT");
    if (glueRow === undefined) throw new Error("GLUE_WEIGHT fixture row missing");
    glueRow.status = "passed";

    vi.mocked(getComponentPreview).mockImplementation(async () =>
      workerStatus === "confirmed"
        ? confirmedPreview
        : previewPayload({
            stagedByRow: {
              GLUE_WEIGHT: [{ outbox_action_id: failedAction.id, status: workerStatus }],
            },
            stagedActions: [{
              ...stagedActionMetadata,
              status: workerStatus,
              summary: "Upload GLUE_WEIGHT",
              test_type: "GLUE_WEIGHT",
            }],
          }),
    );
    vi.mocked(getComponentStaged).mockImplementation(async () =>
      workerStatus === "confirmed" ? [] : [{ ...failedAction, status: workerStatus }],
    );
    vi.mocked(getStageSuggestion).mockImplementation(async () =>
      workerStatus === "confirmed" ? readySuggestion : stageSuggestion,
    );
    vi.mocked(getOutboxAction).mockImplementation(async () => {
      statusPolls += 1;
      workerStatus = statusPolls === 1 ? "submitted" : "confirmed";
      return {
        ...failedAction,
        status: workerStatus,
        error: null,
        external_ref: workerStatus === "confirmed" ? "PDB-RUN-GLUE-RETRY" : null,
      };
    });

    await openModulePage();

    expect(await screen.findByRole(
      "button",
      { name: t.components.stageProposeMove("Stitch Bonding") },
      { timeout: 4_000 },
    )).toBeInTheDocument();
    expect(getOutboxAction).toHaveBeenCalledTimes(2);
    expect(within(worksheetRow("GLUE_WEIGHT")).getByText(t.worksheet.statusPassed))
      .toBeInTheDocument();
  });

  it("refreshes a stale draft immediately when a lost Push response is worker-active", async () => {
    const user = userEvent.setup();
    let workerStatus: OutboxAction["status"] = "draft";
    let statusReads = 0;
    let confirmWorker: (() => void) | undefined;
    const glueDraft: OutboxAction = {
      ...stagedAction,
      payload: {
        ...stagedAction.payload,
        component_sn: MODULE_SN,
        test_type: "GLUE_WEIGHT",
        passed: true,
      },
    };
    const readySuggestion = {
      ...stageSuggestion,
      move_suggested: true,
      suggested_stage: "STITCH_BONDING",
      checks: stageSuggestion.checks.map((check) =>
        check.test_type === "GLUE_WEIGHT" ? { ...check, status: "passed" as const } : check,
      ),
      blocking: [],
    };
    const confirmedPreview = previewPayload();
    const glueRow = confirmedPreview.worksheet.groups
      .flatMap((group) => group.rows)
      .find((row) => row.test_type === "GLUE_WEIGHT");
    if (glueRow === undefined) throw new Error("GLUE_WEIGHT fixture row missing");
    glueRow.status = "passed";

    vi.mocked(getComponentPreview).mockImplementation(async () =>
      workerStatus === "confirmed"
        ? confirmedPreview
        : previewPayload({
            stagedByRow: {
              GLUE_WEIGHT: [{ outbox_action_id: glueDraft.id, status: workerStatus }],
            },
            stagedActions: [{
              ...stagedActionMetadata,
              status: workerStatus,
              summary: "Upload GLUE_WEIGHT",
              test_type: "GLUE_WEIGHT",
            }],
          }),
    );
    vi.mocked(getComponentStaged).mockImplementation(async () =>
      workerStatus === "confirmed" ? [] : [{ ...glueDraft, status: workerStatus }],
    );
    vi.mocked(getStageSuggestion).mockImplementation(async () =>
      workerStatus === "confirmed" ? readySuggestion : stageSuggestion,
    );
    vi.mocked(postOutboxTransition).mockImplementation(async (id, body) => {
      if (body.to === "submitted") {
        // The server accepted the transition, but the response never reached
        // the browser. The authoritative recovery read sees it as active.
        workerStatus = "submitted";
        throw new Error("submitted transition response lost");
      }
      workerStatus = body.to;
      return { ...glueDraft, id, status: body.to };
    });
    vi.mocked(getOutboxAction).mockImplementation(async () => {
      statusReads += 1;
      if (statusReads === 1) return { ...glueDraft, status: "submitted" };
      return new Promise<OutboxAction>((resolve) => {
        confirmWorker = () => {
          workerStatus = "confirmed";
          resolve({
            ...glueDraft,
            status: "confirmed",
            external_ref: "PDB-RUN-GLUE-LOST-RESPONSE",
          });
        };
      });
    });

    await openModulePage();
    await user.click(await screen.findByRole("button", {
      name: t.components.previewStaged(1),
    }));
    await user.click(screen.getByRole("button", { name: t.components.previewPush }));

    // The recovery read returns the same status used to seed the watcher, so
    // polling alone would not refresh until another transition. The explicit
    // active-branch refresh must replace the stale Draft immediately.
    expect((await screen.findAllByText(t.components.previewStatuses.submitted)).length)
      .toBeGreaterThan(0);
    await waitFor(() => expect(getOutboxAction).toHaveBeenCalledTimes(2));
    await act(async () => confirmWorker?.());

    expect(await screen.findByRole(
      "button",
      { name: t.components.stageProposeMove("Stitch Bonding") },
      { timeout: 3_000 },
    )).toBeInTheDocument();
    expect(postOutboxTransition).toHaveBeenCalledTimes(3);
    expect(getOutboxAction).toHaveBeenCalledTimes(2);
    expect(within(worksheetRow("GLUE_WEIGHT")).getByText(t.worksheet.statusPassed))
      .toBeInTheDocument();
  });

  it("stages the required run, waits for worker confirmation, re-evaluates the open page, and proposes the now-valid stage move", async () => {
    const user = userEvent.setup();
    let draftCreated = false;
    let workerStatus: OutboxAction["status"] = "draft";
    let statusPolls = 0;
    const glueDraft: OutboxAction = {
      ...stagedAction,
      payload: {
        ingest_file_id: ingestFile.id,
        component_sn: MODULE_SN,
        test_type: "GLUE_WEIGHT",
        passed: true,
      },
    };
    const readySuggestion = {
      ...stageSuggestion,
      move_suggested: true,
      suggested_stage: "STITCH_BONDING",
      checks: stageSuggestion.checks.map((check) =>
        check.test_type === "GLUE_WEIGHT" ? { ...check, status: "passed" as const } : check,
      ),
      blocking: [],
    };
    const confirmedPreview = previewPayload();
    const confirmedGlueRow = confirmedPreview.worksheet.groups
      .flatMap((group) => group.rows)
      .find((row) => row.test_type === "GLUE_WEIGHT");
    if (confirmedGlueRow === undefined) throw new Error("GLUE_WEIGHT fixture row missing");
    // A freshly confirmed local upload is valid stage evidence before the
    // next mirror sync, but it is not yet a mirrored `latest` run.
    confirmedGlueRow.status = "passed";

    vi.mocked(postIngestFile).mockImplementation(async (body: IngestFileCreate) => {
      pipeline.push(`ingest:${body.filename}`);
      return { ...ingestFile, filename: body.filename, test_type: "GLUE_WEIGHT" };
    });
    vi.mocked(getIngestPreview).mockImplementation(async (id: number) => {
      pipeline.push(`dry-run:${id}`);
      return {
        ...cleanDryRun,
        test_type: "GLUE_WEIGHT",
        n_properties: 0,
        results: [{ name: "GW_GLUE_H1", kind: "scalar", value: "0.245" }],
      };
    });
    vi.mocked(postIngestOutboxProposal).mockImplementation(async (id: number) => {
      pipeline.push(`propose:${id}`);
      draftCreated = true;
      return glueDraft;
    });
    vi.mocked(getComponentPreview).mockImplementation(async () => {
      if (!draftCreated) return previewPayload();
      if (workerStatus === "confirmed") return confirmedPreview;
      return previewPayload({
        stagedByRow: {
          GLUE_WEIGHT: [{ outbox_action_id: glueDraft.id, status: workerStatus }],
        },
        stagedActions: [
          {
            ...stagedActionMetadata,
            status: workerStatus,
            summary: "Upload GLUE_WEIGHT",
            test_type: "GLUE_WEIGHT",
          },
        ],
      });
    });
    vi.mocked(getComponentStaged).mockImplementation(async () =>
      !draftCreated || workerStatus === "confirmed"
        ? []
        : [{ ...glueDraft, status: workerStatus }],
    );
    vi.mocked(getStageSuggestion).mockImplementation(async () =>
      workerStatus === "confirmed" ? readySuggestion : stageSuggestion,
    );
    vi.mocked(postOutboxTransition).mockImplementation(async (id, body) => {
      workerStatus = body.to;
      return { ...glueDraft, id, status: body.to };
    });
    vi.mocked(getOutboxAction).mockImplementation(async () => {
      statusPolls += 1;
      if (statusPolls === 1) {
        workerStatus = "failed";
        return {
          ...glueDraft,
          status: "failed",
          error: "PDB unavailable: temporary test outage",
        };
      }
      if (statusPolls === 2) {
        workerStatus = "submitted";
        return { ...glueDraft, status: "submitted", attempts: 2 };
      }
      workerStatus = "confirmed";
      return {
        ...glueDraft,
        status: "confirmed",
        external_ref: "PDB-RUN-GLUE-1",
      };
    });
    vi.mocked(postOutboxAction).mockImplementation(async (body) => ({
      ...glueDraft,
      id: 93,
      kind: body.kind,
      payload: body.payload,
      status: "draft",
    }));

    await openModulePage();
    await user.click(
      screen.getByRole("button", { name: t.components.recordTestFor("GLUE_WEIGHT") }),
    );
    fireEvent.change(await screen.findByLabelText(/Weight of glue under hybrid 1/u), {
      target: { value: "0.245" },
    });
    fireEvent.change(screen.getByLabelText(/Run number/u), { target: { value: "4" } });
    fireEvent.change(screen.getByLabelText(/Measurement date/u), {
      target: { value: "2026-08-26T10:00" },
    });
    await user.click(screen.getByRole("button", { name: t.worksheet.testForm.submit }));

    await waitFor(() => expect(postIngestOutboxProposal).toHaveBeenCalledTimes(1));
    expect(pipeline).toEqual([
      `ingest:${t.worksheet.manualFilename("GLUE_WEIGHT")}`,
      `dry-run:${ingestFile.id}`,
      `propose:${ingestFile.id}`,
    ]);
    expect(postIngestFile).toHaveBeenCalledWith(
      expect.objectContaining({
        filename: "GLUE_WEIGHT-manual.json",
        component_sn: MODULE_SN,
        test_type: "GLUE_WEIGHT",
        parser: "manual-entry",
        payload: expect.objectContaining({
          component: MODULE_SN,
          testType: "GLUE_WEIGHT",
          results: { GW_GLUE_H1: 0.245 },
        }),
      }),
    );

    // A draft is a preview only: it must not unlock the real stage gate.
    expect(screen.queryByRole("button", {
      name: t.components.stageProposeMove("Stitch Bonding"),
    })).not.toBeInTheDocument();
    expect(await screen.findByText(t.components.stageBlocked)).toBeInTheDocument();

    await user.click(await screen.findByRole("button", {
      name: t.components.previewStaged(1),
    }));
    await user.click(screen.getByRole("button", { name: t.components.previewPush }));
    await waitFor(() => expect(postOutboxTransition).toHaveBeenCalledTimes(3));
    expect(vi.mocked(postOutboxTransition).mock.calls.map(([, body]) => body.to)).toEqual([
      "validated",
      "approved",
      "submitted",
    ]);

    const proposeMove = await screen.findByRole(
      "button",
      { name: t.components.stageProposeMove("Stitch Bonding") },
      { timeout: 9_000 },
    );
    // `failed` is deliberately non-terminal: the worker retries it through
    // `submitted`, and the open detail page must keep watching to confirmation.
    expect(getOutboxAction).toHaveBeenCalledTimes(3);
    expect(within(worksheetRow("GLUE_WEIGHT")).getByText(t.worksheet.statusPassed))
      .toBeInTheDocument();
    expect(within(worksheet()).queryByText(t.worksheet.stagedUpload(glueDraft.id)))
      .not.toBeInTheDocument();

    await user.click(proposeMove);
    await waitFor(() => expect(postOutboxAction).toHaveBeenCalledWith({
      institute_code: INSTITUTE_CODE,
      kind: "stage_move",
      payload: {
        sn: MODULE_SN,
        from_stage: "GLUED",
        to_stage: "STITCH_BONDING",
      },
      created_by: operatorMe.email,
    }));
  }, 15_000);
});

// ---- Dict-valued results in the expanded run detail -------------------------

describe("expanded run detail for a dict-valued (map) result", () => {
  /**
   * A real MODULE_METROLOGY result is a per-position map. The expanded detail
   * keeps its complete position/value table and adds a generated plot only
   * because every value in this fixture is finite and numeric.
   */
  it("shows every position and the generated categorical plot", async () => {
    const user = userEvent.setup();
    await openModulePage();

    await user.click(
      within(worksheetRow("MODULE_METROLOGY")).getByRole("button", {
        name: t.worksheet.expandRow("MODULE_METROLOGY"),
      }),
    );

    await screen.findByText("Hybrid glue thickness [um]");
    expect(screen.queryAllByText("[object Object]")).toEqual([]);
    expect(screen.getAllByText(/ABC_R5H1_0/u).length).toBeGreaterThan(0);
    expect(
      screen.getByRole("img", {
        name: t.testResults.categoryPlotAria(
          "Hybrid glue thickness [um]",
          Object.keys(METROLOGY_THICKNESS).length,
        ),
      }),
    ).toBeInTheDocument();
  });
});
