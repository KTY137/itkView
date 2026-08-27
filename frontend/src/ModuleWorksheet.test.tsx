import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  ComponentPreviewWorksheet,
  IngestFile,
  IngestPreview,
  Institute,
  OutboxAction,
  TestRunDetail,
  TestTypeSchema,
  Tool,
  WorksheetDerivedStep,
} from "./api";
import {
  ApiError,
  getComponentTests,
  getIngestPreview,
  getInstitutes,
  getTools,
  postIngestFile,
  postIngestOutboxProposal,
} from "./api";
import { t } from "./i18n";
import ModuleWorksheet from "./ModuleWorksheet";

vi.mock("./api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api")>()),
  getComponentTests: vi.fn(),
  getIngestPreview: vi.fn(),
  postIngestFile: vi.fn(),
  postIngestOutboxProposal: vi.fn(),
  // Read by the edit strip's data-entry layout (field order + tool registry).
  getInstitutes: vi.fn(),
  getTools: vi.fn(),
}));

// TestResults.tsx is owned by a parallel agent; mock its renderers so this
// suite only depends on the fixed export names/shapes from spec §H2. Its
// `formatScalar` helper is kept real (imported via `importOriginal`) since
// the worksheet now shares it instead of keeping its own copy (M4).
vi.mock("./TestResults", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./TestResults")>()),
  RunCurves: ({ run }: { run: TestRunDetail }) => (
    <div data-testid="run-curves">{run.test_type}</div>
  ),
  RunScalars: ({ run }: { run: TestRunDetail }) => (
    <div data-testid="run-scalars">{String(run.results.GW1)}</div>
  ),
  RunConditions: () => <div data-testid="run-conditions" />,
  RunAttachments: () => <div data-testid="run-attachments" />,
}));

const worksheet: ComponentPreviewWorksheet = {
  groups: [
    {
      stage: "GLUED",
      reached: true,
      rows: [
        {
          test_type: "GLUE_WEIGHT",
          status: "passed",
          latest: {
            external_ref: "run-glue-1",
            measured_at: "2026-08-20T10:00:00Z",
            run_number: "3",
            passed: true,
            scalars: [
              { code: "GW1", name: "Glue weight H1", value: 0.1664 },
              { code: "GW2", name: "Glue weight H2", value: 0.17 },
              { code: "GW3", name: "Glue weight H3", value: 0.18 },
              { code: "GW4", name: "Glue weight H4", value: 0.19 },
              { code: "GW5", name: "Glue weight H5", value: 0.2 },
            ],
            arrays: [{ code: "CURRENT", name: "Current", points: 40 }],
            attachment_count: 0,
          },
          staged: [{ outbox_action_id: 55, status: "draft" }],
          run_count: 3,
        },
      ],
    },
    {
      stage: "TESTED",
      reached: false,
      rows: [
        {
          test_type: "MODULE_IV",
          status: "missing",
          latest: null,
          staged: [],
          run_count: 0,
        },
      ],
    },
    {
      stage: null,
      reached: true,
      rows: [
        {
          test_type: "EXTRA_CHECK",
          status: "pending",
          latest: null,
          staged: [],
          run_count: 0,
        },
      ],
    },
  ],
};

const mirroredRun: TestRunDetail = {
  test_type: "GLUE_WEIGHT",
  passed: true,
  external_ref: "run-glue-1",
  measured_at: "2026-08-20T10:00:00Z",
  run_number: "3",
  run_state: null,
  results: { GW1: 0.1664, GW2: 0.17 },
  result_meta: {},
  properties: { OPERATOR: "Anna Abel" },
  attachments: [],
};

/** The full mirrored schema row, exactly as the integrating screen passes it
 * (`ComponentsScreen.tsx`: `schemas={testSchemas}`, review finding I7) — the
 * local DB's `test_code`/`component_type`/`id` columns plus the nested PDB
 * schema JSON under `.schema`. */
const glueSchema: TestTypeSchema = {
  id: 7,
  component_type: "MODULE",
  test_code: "GLUE_WEIGHT",
  name: "Glue weight",
  synced_at: "2026-08-26T00:00:00Z",
  schema: {
    properties: [],
    results: [{ code: "GW1", dataType: "float" }],
  },
};

const ingestFile: IngestFile = {
  id: 71,
  filename: "GLUE_WEIGHT-manual.json",
  sha256: "a".repeat(64),
  size_bytes: 180,
  status: "processed",
  component_sn: "20USEM00000001",
  test_type: "GLUE_WEIGHT",
  parser: "manual-entry",
  error: null,
  outbox_action_id: null,
  uploaded_by: "server-attributed@example.org",
  created_at: "2026-08-26T10:00:00Z",
  updated_at: "2026-08-26T10:00:00Z",
};

const dryRun: IngestPreview = {
  file_id: 71,
  parser: "manual-entry",
  upload_ready: true,
  component_sn: "20USEM00000001",
  local_name: "Example module",
  component_mirrored: true,
  component_stage: "GLUED",
  institute_code: "EXAMPLE",
  test_type: "GLUE_WEIGHT",
  run_number: "7",
  institution: "EXAMPLE",
  measured_at: "2026-08-26T09:55:00Z",
  passed: true,
  problems: false,
  n_properties: 0,
  results: [{ name: "GW1", kind: "scalar", value: "0.2" }],
  issues: [],
  warnings: [],
};

const action: OutboxAction = {
  id: 92,
  institute_id: 3,
  kind: "upload_test_run",
  payload: { ingest_file_id: 71 },
  status: "draft",
  error: null,
  attempts: 0,
  external_ref: null,
  created_by: "server-attributed@example.org",
  created_at: "2026-08-26T10:01:00Z",
  updated_at: "2026-08-26T10:01:00Z",
};

// ---- Fixtures for the C1 prefill round-trip guard --------------------------
//
// Modelled on the spec §H1 real-data note: MODULE_METROLOGY carries a
// dict-valued result (per-position glue thickness) alongside plain scalars.

const metrologyWorksheet: ComponentPreviewWorksheet = {
  groups: [
    {
      stage: "GLUED",
      reached: true,
      rows: [
        {
          test_type: "MODULE_METROLOGY",
          status: "passed",
          latest: {
            external_ref: "run-metrology-1",
            measured_at: "2026-08-20T10:00:00Z",
            run_number: "1",
            passed: true,
            scalars: [{ code: "SCALAR_X", name: "Scalar X", value: 5 }],
            arrays: [
              {
                code: "HYBRID_GLUE_THICKNESS",
                name: "Hybrid glue thickness [um]",
                points: 2,
                kind: "map",
              },
            ],
            attachment_count: 0,
          },
          staged: [],
          run_count: 1,
        },
      ],
    },
  ],
};

const metrologyRunWithMap: TestRunDetail = {
  test_type: "MODULE_METROLOGY",
  passed: true,
  external_ref: "run-metrology-1",
  measured_at: "2026-08-20T10:00:00Z",
  run_number: "1",
  run_state: null,
  results: {
    HYBRID_GLUE_THICKNESS: { ABC_R5H1_0: 12.3, ABC_R5H1_1: 11.9 },
    SCALAR_X: 5,
  },
  result_meta: {
    HYBRID_GLUE_THICKNESS: { name: "Hybrid glue thickness [um]" },
    SCALAR_X: { name: "Scalar X" },
  },
  properties: {},
  attachments: [],
};

const metrologySchemaOptional: TestTypeSchema = {
  id: 9,
  component_type: "MODULE",
  test_code: "MODULE_METROLOGY",
  name: "Module metrology",
  synced_at: "2026-08-26T00:00:00Z",
  schema: {
    properties: [],
    results: [
      { code: "HYBRID_GLUE_THICKNESS", dataType: "float" },
      { code: "SCALAR_X", dataType: "float" },
    ],
  },
};

const metrologySchemaRequired: TestTypeSchema = {
  ...metrologySchemaOptional,
  schema: {
    properties: [],
    results: [{ code: "HYBRID_GLUE_THICKNESS", dataType: "float" }],
    required: ["HYBRID_GLUE_THICKNESS"],
  },
};

// A schema field the mirror declares as a plain (non-array) value, while the
// previous run actually recorded a list for it — the "declared single, got a
// list" half of C1.
const glueSchemaWithMismatchedCurrent: TestTypeSchema = {
  ...glueSchema,
  schema: {
    properties: [],
    results: [
      { code: "GW1", dataType: "float" },
      { code: "CURRENT", name: "Current", dataType: "float" },
    ],
  },
};

const mirroredRunWithMismatchedArray: TestRunDetail = {
  ...mirroredRun,
  results: { ...mirroredRun.results, CURRENT: [1, 2, 3] },
};

function renderWorksheet(overrides: Partial<ComponentProps<typeof ModuleWorksheet>> = {}) {
  return render(
    <ModuleWorksheet
      componentSn="20USEM00000001"
      componentType="MODULE"
      instituteCode="EXAMPLE"
      worksheet={worksheet}
      schemas={[glueSchema]}
      canWrite
      onUseFileUpload={vi.fn()}
      {...overrides}
    />,
  );
}

describe("ModuleWorksheet", () => {
  beforeEach(() => {
    vi.mocked(getComponentTests).mockResolvedValue([mirroredRun]);
    vi.mocked(postIngestFile).mockResolvedValue(ingestFile);
    vi.mocked(getIngestPreview).mockResolvedValue(dryRun);
    vi.mocked(postIngestOutboxProposal).mockResolvedValue(action);
    vi.mocked(getInstitutes).mockResolvedValue([]);
    vi.mocked(getTools).mockResolvedValue([]);
  });

  it("compacts the values cell: three scalars inline, the rest as +n, arrays as a point-count chip", () => {
    renderWorksheet();

    // Group headings, humanised (raw SNAKE_CASE stays only in the title attr).
    expect(screen.getByText("Glued")).toBeInTheDocument();
    expect(screen.getByText("Tested")).toBeInTheDocument();
    expect(screen.getByText("Additional")).toBeInTheDocument();

    // First three scalars inline as "Label" + mono value.
    expect(screen.getByText("Glue weight H1")).toBeInTheDocument();
    expect(screen.getByText("0.1664")).toBeInTheDocument();
    expect(screen.getByText("Glue weight H3")).toBeInTheDocument();
    // Remainder collapses to "+n"; hidden scalars never appear as text nodes.
    expect(screen.getByText("+2")).toBeInTheDocument();
    expect(screen.queryByText("Glue weight H4")).not.toBeInTheDocument();
    expect(screen.queryByText("0.19")).not.toBeInTheDocument();
    // Arrays are only ever a point-count chip, never raw data.
    expect(screen.getByText("⌁ 40 pts")).toBeInTheDocument();
    expect(screen.getByText("passed")).toBeInTheDocument();
  });

  it("shows a dashed ghost sub-row for each open staged action; 'View in Staged' is plain text unless a route is wired (I3)", () => {
    renderWorksheet();

    expect(screen.getByText("Staged upload · action #55")).toBeInTheDocument();
    expect(screen.getByText("Draft")).toBeInTheDocument();
    // No `onViewStaged`: the label must not look clickable when it is not.
    expect(screen.queryByRole("button", { name: "View in Staged" })).not.toBeInTheDocument();
    expect(screen.getByText("View in Staged")).toBeInTheDocument();
  });

  it("routes 'View in Staged' through the caller's callback when one is wired (I3)", async () => {
    const user = userEvent.setup();
    const onViewStaged = vi.fn();
    renderWorksheet({ onViewStaged });

    await user.click(screen.getByRole("button", { name: "View in Staged" }));
    expect(onViewStaged).toHaveBeenCalledTimes(1);
  });

  it("keys row state by stage+test_type: the same test type at two stages does not share expand/edit state (I2)", async () => {
    const user = userEvent.setup();
    const twoStageWorksheet: ComponentPreviewWorksheet = {
      groups: [
        {
          stage: "GLUED",
          reached: true,
          rows: [
            { test_type: "VISUAL_INSPECTION", status: "passed", latest: null, staged: [], run_count: 0 },
          ],
        },
        {
          stage: "TESTED",
          reached: true,
          rows: [
            { test_type: "VISUAL_INSPECTION", status: "missing", latest: null, staged: [], run_count: 0 },
          ],
        },
      ],
    };
    const { container } = renderWorksheet({ worksheet: twoStageWorksheet });

    const pencils = screen.getAllByRole("button", { name: "Record VISUAL_INSPECTION" });
    expect(pencils).toHaveLength(2);

    await user.click(pencils[0]);
    expect(container.querySelectorAll(".ws-edit-strip")).toHaveLength(1);

    // Before the fix, both rows shared one `editingTestType` string, so this
    // second row's pencil compared equal to the first and just closed it.
    await user.click(pencils[1]);
    expect(container.querySelectorAll(".ws-edit-strip")).toHaveLength(1);
  });

  it("surfaces a mismatched editIntent instead of firing a run fetch for nothing (M5)", () => {
    renderWorksheet({ editIntent: { testType: "DOES_NOT_EXIST", token: 1 } });

    expect(screen.getByText("No worksheet row for DOES_NOT_EXIST yet.")).toBeInTheDocument();
    expect(getComponentTests).not.toHaveBeenCalled();
  });

  it("renders map-valued arrays as an entry-count chip, and treats an absent kind as an array (M7)", () => {
    const mixedWorksheet: ComponentPreviewWorksheet = {
      groups: [
        {
          stage: "GLUED",
          reached: true,
          rows: [
            {
              test_type: "MODULE_METROLOGY",
              status: "passed",
              latest: {
                external_ref: "run-1",
                measured_at: null,
                run_number: null,
                passed: true,
                scalars: [],
                arrays: [
                  { code: "MAP1", name: "Map field", points: 3, kind: "map" },
                  { code: "ARR1", name: "Array field (legacy)", points: 12 },
                ],
                attachment_count: 0,
              },
              staged: [],
              run_count: 1,
            },
          ],
        },
      ],
    };
    renderWorksheet({ worksheet: mixedWorksheet });

    expect(screen.getByText("⌁ 3 entries")).toBeInTheDocument();
    expect(screen.getByText("⌁ 12 pts")).toBeInTheDocument();
  });

  it("hides the edit pencil without write permission", () => {
    renderWorksheet({ canWrite: false });
    expect(screen.queryByRole("button", { name: "Record GLUE_WEIGHT" })).not.toBeInTheDocument();
  });

  it("opens the edit strip for the right row on an editIntent token", async () => {
    renderWorksheet({ editIntent: { testType: "GLUE_WEIGHT", token: 1 } });

    expect(await screen.findByText("Record GLUE_WEIGHT")).toBeInTheDocument();
    // Only the intended row's strip opens.
    expect(screen.queryByText("Record MODULE_IV")).not.toBeInTheDocument();
  });

  it("expands a row into the full mirrored run via the TestResults renderers", async () => {
    const user = userEvent.setup();
    renderWorksheet();

    await user.click(screen.getByRole("button", { name: "Show GLUE_WEIGHT runs" }));

    await waitFor(() => expect(getComponentTests).toHaveBeenCalledTimes(1));
    expect(vi.mocked(getComponentTests).mock.calls[0]?.[0]).toBe("20USEM00000001");
    expect(await screen.findByTestId("run-curves")).toHaveTextContent("GLUE_WEIGHT");
    expect(screen.getByTestId("run-scalars")).toHaveTextContent("0.1664");
    expect(screen.getByTestId("run-conditions")).toBeInTheDocument();
    expect(
      screen.getByTestId("run-attachments").compareDocumentPosition(
        screen.getByTestId("run-curves"),
      ),
    ).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
  });

  it("labels only the terminal deleted state as withdrawn instead of presenting its old verdict as valid", async () => {
    const user = userEvent.setup();
    vi.mocked(getComponentTests).mockResolvedValue([
      { ...mirroredRun, external_ref: "run-withdrawn", run_state: "deleted" },
      { ...mirroredRun, external_ref: "run-requested", run_state: "requestedToDelete" },
    ]);
    const { container } = renderWorksheet();

    await user.click(screen.getByRole("button", { name: "Show GLUE_WEIGHT runs" }));

    expect(await screen.findByText(t.worksheet.statusWithdrawn)).toHaveAttribute(
      "title",
      t.worksheet.withdrawnHint,
    );
    // A pending deletion request is deliberately still a live run.
    const runList = container.querySelector(".run-list");
    expect(runList).not.toBeNull();
    expect(within(runList as HTMLElement).getByText(t.worksheet.statusPassed)).toBeInTheDocument();
  });

  it("prefills from the newest live run and never from a newer withdrawn run", async () => {
    const user = userEvent.setup();
    vi.mocked(getComponentTests).mockResolvedValue([
      {
        ...mirroredRun,
        external_ref: "run-withdrawn-newer",
        measured_at: "2026-08-25T10:00:00Z",
        run_number: "9",
        run_state: "deleted",
        results: { GW1: 9.99 },
      },
      {
        ...mirroredRun,
        external_ref: "run-live-older",
        measured_at: "2026-08-20T10:00:00Z",
        run_number: "3",
        run_state: null,
        results: { GW1: 0.1664 },
      },
    ]);
    renderWorksheet();

    await user.click(screen.getByRole("button", { name: "Record GLUE_WEIGHT" }));

    expect(await screen.findByLabelText(/GW1/)).toHaveValue("0.1664");
    expect(screen.getByLabelText(/GW1/)).not.toHaveValue("9.99");
  });

  it("does not load a withdrawn-only run into an already open empty strip", async () => {
    const user = userEvent.setup();
    let resolveRuns: ((runs: TestRunDetail[]) => void) | undefined;
    vi.mocked(getComponentTests).mockReturnValue(
      new Promise<TestRunDetail[]>((resolve) => {
        resolveRuns = resolve;
      }),
    );
    const noLiveGlueRuns: ComponentPreviewWorksheet = {
      ...worksheet,
      groups: worksheet.groups.map((group) => ({
        ...group,
        rows: group.rows.map((row) =>
          row.test_type === "GLUE_WEIGHT"
            ? { ...row, status: "missing", latest: null, run_count: 0 }
            : row,
        ),
      })),
    };
    renderWorksheet({ worksheet: noLiveGlueRuns });

    await user.click(screen.getByRole("button", { name: "Record GLUE_WEIGHT" }));
    const input = await screen.findByLabelText(/GW1/);
    expect(input).toHaveValue("");
    await user.type(input, "0.245");
    await waitFor(() => expect(getComponentTests).toHaveBeenCalledTimes(1));

    await act(async () => {
      resolveRuns?.([
        {
          ...mirroredRun,
          external_ref: "run-withdrawn-only",
          measured_at: "2026-08-25T10:00:00Z",
          run_number: "9",
          run_state: "deleted",
          results: { GW1: 9.99 },
        },
      ]);
    });

    expect(input).toHaveValue("0.245");
  });

  it("stages an in-row edit through ingest -> dry-run -> propose-outbox, prefilled from the latest run", async () => {
    const user = userEvent.setup();
    const onStaged = vi.fn();
    renderWorksheet({ onStaged });

    await user.click(screen.getByRole("button", { name: "Record GLUE_WEIGHT" }));

    // Waits for the mirrored run (run_count > 0) and prefills the schema field.
    const gwInput = await screen.findByLabelText(/GW1/);
    expect(gwInput).toHaveValue("0.1664");

    // Run number and measurement date are required by the form contract.
    fireEvent.change(screen.getByLabelText(/Run number/), {
      target: { value: "7" },
    });
    fireEvent.change(screen.getByLabelText(/Measurement date/), {
      target: { value: "2026-08-26T10:00" },
    });
    await user.click(screen.getByRole("button", { name: "Stage test result" }));

    await waitFor(() => expect(postIngestFile).toHaveBeenCalledTimes(1));
    const body = vi.mocked(postIngestFile).mock.calls[0]?.[0];
    expect(body).toEqual(
      expect.objectContaining({
        component_sn: "20USEM00000001",
        test_type: "GLUE_WEIGHT",
        parser: "manual-entry",
      }),
    );
    expect(body?.payload).toEqual(
      expect.objectContaining({
        component: "20USEM00000001",
        testType: "GLUE_WEIGHT",
        results: { GW1: 0.1664 },
      }),
    );
    expect(body).not.toHaveProperty("actor");
    expect(body).not.toHaveProperty("created_by");

    await waitFor(() => expect(postIngestOutboxProposal).toHaveBeenCalledTimes(1));
    expect(postIngestOutboxProposal).toHaveBeenCalledWith(71, { institute_code: "EXAMPLE" });
    await waitFor(() => expect(onStaged).toHaveBeenCalledWith(92));
    // The strip collapses and a ghost sub-row appears for the new action.
    expect(screen.queryByText("Record GLUE_WEIGHT")).not.toBeInTheDocument();
    expect(screen.getByText("Staged upload · action #92")).toBeInTheDocument();
  });

  describe("C1: prefill only round-trippable values", () => {
    it("does not silently drop a dict-valued (map) result — it is left blank and named in a notice", async () => {
      const user = userEvent.setup();
      vi.mocked(getComponentTests).mockResolvedValue([metrologyRunWithMap]);
      renderWorksheet({
        worksheet: metrologyWorksheet,
        schemas: [metrologySchemaOptional],
      });

      await user.click(screen.getByRole("button", { name: "Record MODULE_METROLOGY" }));

      // The round-trippable scalar still prefills.
      expect(await screen.findByLabelText("SCALAR_X")).toHaveValue("5");
      // The dict-valued field is never silently filled — the raw map would
      // otherwise reach TestForm's single-line control as "[object Object]".
      const glueField = screen.getByLabelText("HYBRID_GLUE_THICKNESS");
      expect(glueField).toHaveValue("");
      // Explicit, non-dismissable notice naming the dropped field.
      expect(
        screen.getByText(t.worksheet.prefillDropped("Hybrid glue thickness [um]")),
      ).toBeInTheDocument();
    });

    it("does not flatten a list-valued result into a single-line control when the schema declares it a scalar", async () => {
      const user = userEvent.setup();
      vi.mocked(getComponentTests).mockResolvedValue([mirroredRunWithMismatchedArray]);
      renderWorksheet({ schemas: [glueSchemaWithMismatchedCurrent] });

      await user.click(screen.getByRole("button", { name: "Record GLUE_WEIGHT" }));

      expect(await screen.findByLabelText(/GW1/)).toHaveValue("0.1664");
      // Never joined into "1\n2\n3" (which would itself fail float validation)
      // nor into any other string — the field is simply left blank.
      const currentField = screen.getByLabelText("Current");
      expect(currentField).toHaveValue("");
      expect(
        screen.getByText(t.worksheet.prefillDropped("Current")),
      ).toBeInTheDocument();
    });

    it("blocks the strip instead of a silent dead end when a non-round-trippable field is required", async () => {
      const user = userEvent.setup();
      const onUseFileUpload = vi.fn();
      vi.mocked(getComponentTests).mockResolvedValue([metrologyRunWithMap]);
      renderWorksheet({
        worksheet: metrologyWorksheet,
        schemas: [metrologySchemaRequired],
        onUseFileUpload,
      });

      await user.click(screen.getByRole("button", { name: "Record MODULE_METROLOGY" }));

      // Chosen behaviour (documented in ModuleWorksheet.tsx): block the strip
      // and point at the file-drop path, rather than rendering a form that
      // can never validate.
      expect(
        await screen.findByText(t.worksheet.prefillBlockedRequired("Hybrid glue thickness [um]")),
      ).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Stage test result" })).not.toBeInTheDocument();
      // TestForm itself must not render at all — a half-usable form here
      // would still let the operator submit a payload missing this field.
      expect(screen.queryByLabelText("HYBRID_GLUE_THICKNESS")).not.toBeInTheDocument();

      await user.click(screen.getByRole("button", { name: t.worksheet.useFileUpload }));
      expect(onUseFileUpload).toHaveBeenCalledWith("MODULE_METROLOGY");
    });
  });

  describe("manual-entry capability", () => {
    const missingWorksheet = (testType: string): ComponentPreviewWorksheet => ({
      groups: [
        {
          stage: "TESTED",
          reached: true,
          rows: [
            {
              test_type: testType,
              status: "missing",
              latest: null,
              staged: [],
              run_count: 0,
            },
          ],
        },
      ],
    });

    it("names required object fields and routes the file-only test to JSON upload", async () => {
      const user = userEvent.setup();
      const onUseFileUpload = vi.fn();
      renderWorksheet({
        worksheet: missingWorksheet("MODULE_IV_AMAC_TC"),
        schemas: [
          {
            id: 21,
            component_type: "MODULE",
            test_code: "MODULE_IV_AMAC_TC",
            name: "Module IV AMAC thermal cycle",
            synced_at: "2026-08-27T12:00:00Z",
            schema: {
              properties: [
                { code: "DCS", name: "DCS settings", dataType: "object", required: true },
                {
                  code: "SCAN_INFO",
                  name: "Scan information",
                  dataType: "object",
                  required: true,
                },
              ],
              parameters: [{ code: "SUMMARY", name: "Summary", dataType: "float" }],
            },
          },
        ],
        onUseFileUpload,
      });

      await user.click(screen.getByRole("button", { name: "Record MODULE_IV_AMAC_TC" }));

      expect(await screen.findByText(/DCS settings \(DCS\)/u)).toHaveTextContent(
        "Scan information (SCAN_INFO)",
      );
      expect(screen.queryByLabelText(/Run number/u)).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Stage test result" })).not.toBeInTheDocument();

      await user.click(screen.getByRole("button", { name: t.worksheet.useFileUpload }));
      expect(onUseFileUpload).toHaveBeenCalledWith("MODULE_IV_AMAC_TC");
    });

    it("does not render a flattening textarea for a 2-D primitive curve", async () => {
      const user = userEvent.setup();
      const onUseFileUpload = vi.fn();
      const { container } = renderWorksheet({
        worksheet: missingWorksheet("MODULE_TC"),
        schemas: [
          {
            id: 22,
            component_type: "MODULE",
            test_code: "MODULE_TC",
            name: "Module thermal cycle",
            synced_at: "2026-08-27T12:00:00Z",
            schema: {
              parameters: [
                { code: "SUMMARY", name: "Summary", dataType: "float" },
                {
                  code: "CURRENT",
                  name: "Current",
                  dataType: "float",
                  valueType: "array",
                  arrayDimensions: 2,
                },
              ],
            },
          },
        ],
        onUseFileUpload,
      });

      await user.click(screen.getByRole("button", { name: "Record MODULE_TC" }));

      expect(await screen.findByText(/Current \(CURRENT\)/u)).toBeInTheDocument();
      expect(container.querySelector('textarea[name="results.CURRENT"]')).toBeNull();
      expect(screen.queryByLabelText(/Run number/u)).not.toBeInTheDocument();
    });
  });

  describe("I5/I6/M7: strip feedback for blocked and failed states", () => {
    it("renders dry-run issues and does not auto-propose (M7)", async () => {
      const user = userEvent.setup();
      vi.mocked(getIngestPreview).mockResolvedValueOnce({
        ...dryRun,
        upload_ready: false,
        issues: ["Component stage mismatch"],
      });
      renderWorksheet();

      await user.click(screen.getByRole("button", { name: "Record GLUE_WEIGHT" }));
      await screen.findByLabelText(/GW1/);
      fireEvent.change(screen.getByLabelText(/Run number/), { target: { value: "7" } });
      fireEvent.change(screen.getByLabelText(/Measurement date/), {
        target: { value: "2026-08-26T10:00" },
      });
      await user.click(screen.getByRole("button", { name: "Stage test result" }));

      expect(await screen.findByText("Component stage mismatch")).toBeInTheDocument();
      expect(postIngestOutboxProposal).not.toHaveBeenCalled();
    });

    it("surfaces upload_ready=false even with no issues instead of a silent no-op (I5)", async () => {
      const user = userEvent.setup();
      vi.mocked(getIngestPreview).mockResolvedValueOnce({
        ...dryRun,
        upload_ready: false,
        issues: [],
      });
      renderWorksheet();

      await user.click(screen.getByRole("button", { name: "Record GLUE_WEIGHT" }));
      await screen.findByLabelText(/GW1/);
      fireEvent.change(screen.getByLabelText(/Run number/), { target: { value: "7" } });
      fireEvent.change(screen.getByLabelText(/Measurement date/), {
        target: { value: "2026-08-26T10:00" },
      });
      await user.click(screen.getByRole("button", { name: "Stage test result" }));

      expect(await screen.findByText(t.worksheet.previewBlocked)).toBeInTheDocument();
      expect(postIngestOutboxProposal).not.toHaveBeenCalled();
    });

    it("blocks the strip and surfaces the error when the previous-run fetch fails, instead of rendering unprefilled (I6)", async () => {
      vi.mocked(getComponentTests).mockRejectedValueOnce(new ApiError("network blip", 500));
      const user = userEvent.setup();
      renderWorksheet();

      await user.click(screen.getByRole("button", { name: "Record GLUE_WEIGHT" }));

      expect(
        await screen.findByText(t.worksheet.previousValuesError("network blip")),
      ).toBeInTheDocument();
      expect(screen.queryByLabelText(/GW1/)).not.toBeInTheDocument();
    });
  });

  describe("child-component evidence", () => {
    // Only 720 of 14 759 mirrored runs hang on MODULE components; the rest sit
    // on the children, and for an R5 ring module the metrology / glue weight /
    // PS IV live on its two half-modules. The page shows that evidence — as
    // the child's, never folded into the module's own rows.
    const withChildren: ComponentPreviewWorksheet = {
      ...worksheet,
      children: [
        {
          sn: "20USE5L0000031",
          component_type: "MODULE",
          type_code: "R5M1",
          local_name: "EXA-R5M1-0002",
          rows: [
            {
              test_type: "MODULE_METROLOGY",
              latest: {
                external_ref: "run-child-metro",
                measured_at: "2026-08-21T09:00:00Z",
                run_number: "2",
                passed: false,
                scalars: [{ code: "SHIELDBOX_HEIGHT", name: "Shield box height [um]", value: 88 }],
                arrays: [
                  {
                    code: "HYBRID_GLUE_THICKNESS",
                    name: "Hybrid glue thickness [um]",
                    points: 14,
                    kind: "map",
                  },
                ],
                attachment_count: 1,
              },
              run_count: 2,
              withdrawn_count: 3,
            },
          ],
        },
        {
          sn: "20USES40000771",
          component_type: "SENSOR",
          type_code: "ATLAS18R5",
          local_name: null,
          rows: [],
        },
      ],
    };

    it("renders one group per child with its serial, decoded type and local name", () => {
      renderWorksheet({ worksheet: withChildren });

      expect(screen.getByText(t.worksheet.childrenTitle)).toBeInTheDocument();
      expect(screen.getByText("20USE5L0000031")).toBeInTheDocument();
      expect(screen.getByText("Module · Endcap R5, pos 1")).toBeInTheDocument();
      expect(screen.getByText("EXA-R5M1-0002")).toBeInTheDocument();
      expect(screen.getByText("MODULE_METROLOGY")).toBeInTheDocument();
      // A child with nothing mirrored still gets a group and says so.
      expect(screen.getByText("20USES40000771")).toBeInTheDocument();
      expect(screen.getByText(t.worksheet.childrenEmpty)).toBeInTheDocument();
    });

    it("keeps the compactness contract: scalars inline, maps as a count chip, run and withdrawn counts", () => {
      renderWorksheet({ worksheet: withChildren });

      expect(screen.getByText("Shield box height [um]")).toBeInTheDocument();
      expect(screen.getByText("88")).toBeInTheDocument();
      expect(screen.getByText("⌁ 14 entries")).toBeInTheDocument();
      expect(screen.getByText(t.worksheet.childRunCount(2))).toBeInTheDocument();
      expect(screen.getByText(t.worksheet.childWithdrawn(3))).toBeInTheDocument();
    });

    it("makes no requirement claim for the parent while giving child plots a visible read-only affordance", () => {
      renderWorksheet({ worksheet: withChildren });

      const childSection = screen.getByText(t.worksheet.childrenTitle).closest("section");
      expect(childSection).not.toBeNull();
      // The child's own pass/fail, not a "missing"/"pending" requirement state.
      expect(childSection).toHaveTextContent(t.worksheet.statusFailed);
      expect(childSection).not.toHaveTextContent(t.worksheet.statusMissing);
      expect(
        screen.queryByRole("button", { name: "Record MODULE_METROLOGY" }),
      ).not.toBeInTheDocument();
      expect(
        within(childSection as HTMLElement).getByRole("button", {
          name: "Show MODULE_METROLOGY runs",
        }),
      ).toHaveTextContent(t.worksheet.runsAndPlots);
    });

    it("loads and renders a child's full run detail under the child's serial", async () => {
      const user = userEvent.setup();
      vi.mocked(getComponentTests).mockResolvedValue([metrologyRunWithMap]);
      renderWorksheet({ worksheet: withChildren });

      await user.click(
        screen.getByRole("button", { name: "Show MODULE_METROLOGY runs" }),
      );

      await waitFor(() =>
        expect(getComponentTests).toHaveBeenCalledWith(
          "20USE5L0000031",
          expect.any(AbortSignal),
        ),
      );
      expect(await screen.findByTestId("run-curves")).toHaveTextContent("MODULE_METROLOGY");
    });

    it("renders nothing extra when the server sends no children block at all", () => {
      renderWorksheet();
      expect(screen.queryByText(t.worksheet.childrenTitle)).not.toBeInTheDocument();
    });
  });
});

// ---- The server-derived glue judgement (plan §9.3) --------------------------
//
// On the owner's production sheet a row of scale readings becomes a glue
// weight, a target, a tolerance and a verdict. That judgement exists nowhere
// in itkFlow today, and nowhere in the PDB either (automatic grading is off on
// every module schema). These tests pin two things: that the verdict is
// visible without opening the row, and that every number on screen came out of
// the payload — the browser must never re-derive any of it.

function derivedStep(overrides: Partial<WorksheetDerivedStep> = {}): WorksheetDerivedStep {
  return {
    key: "hybrids",
    label: "Hybrids",
    measured_mg: 151.2,
    target_mg: 151,
    tolerance_mg: 22,
    verdict: "ok",
    reason: null,
    inputs: [
      { code: "GW_MODULE_H1H2", name: "Module after hybrid glueing", value: 9.3819 },
      { code: "GW_SENSOR", name: "Sensor with tab", value: 7.0162 },
    ],
    ...overrides,
  };
}

function derivedWorksheet(steps: WorksheetDerivedStep[]): ComponentPreviewWorksheet {
  return {
    groups: [
      {
        stage: "GLUED",
        reached: true,
        rows: [
          {
            test_type: "GLUE_WEIGHT",
            status: "passed",
            latest: {
              external_ref: "run-glue-1",
              measured_at: "2026-08-20T10:00:00Z",
              run_number: "3",
              passed: true,
              scalars: [{ code: "GW_SENSOR", name: "Sensor with tab", value: 7.0162 }],
              arrays: [],
              attachment_count: 0,
            },
            staged: [],
            run_count: 1,
            derived: {
              kind: "glue_weight",
              process: "TRUEBLUE",
              process_source: "profile_default",
              steps,
            },
          },
        ],
      },
    ],
  };
}

describe("ModuleWorksheet derived glue judgement", () => {
  beforeEach(() => {
    vi.mocked(getComponentTests).mockResolvedValue([mirroredRun]);
    vi.mocked(postIngestFile).mockResolvedValue(ingestFile);
    vi.mocked(getIngestPreview).mockResolvedValue(dryRun);
    vi.mocked(postIngestOutboxProposal).mockResolvedValue(action);
    vi.mocked(getInstitutes).mockResolvedValue([]);
    vi.mocked(getTools).mockResolvedValue([]);
  });

  it("shows the verdict as a word in the collapsed row, with the measured-versus-target figure", () => {
    renderWorksheet({ worksheet: derivedWorksheet([derivedStep()]) });

    // No row expanded, no edit strip open: the judgement is readable at a glance.
    expect(screen.queryByRole("button", { name: "Hide GLUE_WEIGHT runs" })).not.toBeInTheDocument();
    expect(screen.getByText(t.worksheet.verdictOk)).toBeInTheDocument();
    expect(screen.getByText("Hybrids")).toBeInTheDocument();
    expect(screen.getByText(t.worksheet.derivedFigure("151.2", "151", "22"))).toBeInTheDocument();
    // The requirement status is a different statement and keeps its own chip.
    expect(screen.getByText(t.worksheet.statusPassed)).toBeInTheDocument();
  });

  it("names each bad verdict, and never resolves the tolerance into a band", () => {
    const { unmount } = renderWorksheet({
      worksheet: derivedWorksheet([derivedStep({ measured_mg: 112, verdict: "too_little" })]),
    });
    expect(screen.getByText(t.worksheet.verdictTooLittle)).toHaveClass("chip", "red");
    // `151 - 22 = 129` on screen would mean the browser had done arithmetic.
    expect(screen.queryByText(/129/u)).not.toBeInTheDocument();
    unmount();

    renderWorksheet({
      worksheet: derivedWorksheet([derivedStep({ measured_mg: 200, verdict: "too_much" })]),
    });
    expect(screen.getByText(t.worksheet.verdictTooMuch)).toHaveClass("chip", "red");
    expect(screen.queryByText(/173/u)).not.toBeInTheDocument();
  });

  it("puts the reason in words when there is no verdict, never a chip that could read as fine", () => {
    const reasons: Array<[string | null, string]> = [
      ["missing_inputs", t.worksheet.verdictMissingInputs],
      ["no_target", t.worksheet.verdictNoTarget],
      ["no_run", t.worksheet.verdictNoRun],
      [null, t.worksheet.verdictUnknown],
      ["profile_conflict", t.worksheet.verdictUnknownReason("profile_conflict")],
    ];
    for (const [reason, expected] of reasons) {
      const { unmount } = renderWorksheet({
        worksheet: derivedWorksheet([
          derivedStep({ measured_mg: null, verdict: "unknown", reason }),
        ]),
      });
      const chip = screen.getByText(expected);
      // Amber, never green: on the sheet this replaces, 8 of 13 powerboard
      // verdicts are arithmetic on blank cells and look exactly like results.
      expect(chip).toHaveClass("chip", "amber");
      expect(chip).not.toHaveClass("green");
      // The target still shows; the missing measurement reads as an em dash.
      expect(
        screen.getByText(t.worksheet.derivedFigure(t.common.none, "151", "22")),
      ).toBeInTheDocument();
      unmount();
    }
  });

  it("keeps two steps as two verdicts on one row instead of collapsing them", () => {
    renderWorksheet({
      worksheet: derivedWorksheet([
        derivedStep(),
        derivedStep({
          key: "powerboard",
          label: "Powerboard",
          measured_mg: 96,
          target_mg: 70,
          tolerance_mg: 11,
          verdict: "too_much",
        }),
      ]),
    });

    expect(screen.getAllByRole("row")).toHaveLength(2); // header + the one test row
    expect(screen.getByText("Hybrids")).toBeInTheDocument();
    expect(screen.getByText("Powerboard")).toBeInTheDocument();
    expect(screen.getByText(t.worksheet.verdictOk)).toBeInTheDocument();
    expect(screen.getByText(t.worksheet.verdictTooMuch)).toBeInTheDocument();
    expect(screen.getByText(t.worksheet.derivedFigure("151.2", "151", "22"))).toBeInTheDocument();
    expect(screen.getByText(t.worksheet.derivedFigure("96", "70", "11"))).toBeInTheDocument();
  });

  it("renders only what the payload says: a verdict that contradicts the numbers still shows", () => {
    // The point of the assertion. If any of this were computed in the browser,
    // 9999 against 42 ± 1 could not possibly render as "OK" — the display
    // follows the server, the only place the formula lives.
    const { unmount } = renderWorksheet({ worksheet: derivedWorksheet([derivedStep()]) });
    expect(screen.getByText(t.worksheet.derivedFigure("151.2", "151", "22"))).toBeInTheDocument();
    unmount();

    renderWorksheet({
      worksheet: derivedWorksheet([
        derivedStep({ measured_mg: 9999, target_mg: 42, tolerance_mg: 1, verdict: "ok" }),
      ]),
    });
    expect(screen.getByText(t.worksheet.derivedFigure("9999", "42", "1"))).toBeInTheDocument();
    expect(screen.getByText(t.worksheet.verdictOk)).toBeInTheDocument();
    expect(screen.queryByText(t.worksheet.verdictTooMuch)).not.toBeInTheDocument();
  });

  it("leaves a row without a derivation exactly as it was", () => {
    renderWorksheet();

    expect(screen.getByText("Glue weight H1")).toBeInTheDocument();
    expect(screen.getByText("0.1664")).toBeInTheDocument();
    expect(screen.queryByText(t.worksheet.verdictOk)).not.toBeInTheDocument();
    expect(screen.queryByText(t.worksheet.verdictNoRun)).not.toBeInTheDocument();
    expect(screen.queryByText(t.worksheet.derivedTitle)).not.toBeInTheDocument();
  });

  it("shows the last run's derivation read-only in the edit strip, and says where it came from", async () => {
    const user = userEvent.setup();
    renderWorksheet({ worksheet: derivedWorksheet([derivedStep()]) });

    await user.click(screen.getByRole("button", { name: "Record GLUE_WEIGHT" }));

    expect(await screen.findByText(t.worksheet.derivedTitle)).toBeInTheDocument();
    expect(screen.getByText(t.worksheet.derivedFromLatestRun)).toBeInTheDocument();
    expect(screen.getByText(t.worksheet.derivedMg("151.2"))).toBeInTheDocument();
    expect(screen.getByText(t.worksheet.derivedMg("151"))).toBeInTheDocument();
    expect(screen.getByText(t.worksheet.derivedToleranceMg("22"))).toBeInTheDocument();
    // The readings the server actually used, so the arithmetic is retraceable.
    expect(screen.getByText("Module after hybrid glueing")).toBeInTheDocument();
    expect(screen.getByText("9.3819")).toBeInTheDocument();
    // Read-only: the derived figures are never editable form controls.
    expect(screen.queryByLabelText(t.worksheet.derivedWeightLabel)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(t.worksheet.derivedTargetLabel)).not.toBeInTheDocument();
  });

  it("replaces it with the dry-run's own derivation once the server has judged the entered values", async () => {
    const user = userEvent.setup();
    vi.mocked(getIngestPreview).mockResolvedValue({
      ...dryRun,
      upload_ready: false,
      issues: ["Component stage mismatch"],
      derived: {
        kind: "glue_weight",
        process: "TRUEBLUE",
        process_source: "run",
        steps: [derivedStep({ measured_mg: 118, verdict: "too_little" })],
      },
    });
    renderWorksheet({ worksheet: derivedWorksheet([derivedStep()]) });

    await user.click(screen.getByRole("button", { name: "Record GLUE_WEIGHT" }));
    await screen.findByLabelText(/GW1/);
    fireEvent.change(screen.getByLabelText(/Run number/), { target: { value: "7" } });
    fireEvent.change(screen.getByLabelText(/Measurement date/), {
      target: { value: "2026-08-26T10:00" },
    });
    await user.click(screen.getByRole("button", { name: "Stage test result" }));

    expect(await screen.findByText(t.worksheet.derivedFromPreview)).toBeInTheDocument();
    expect(screen.getByText(t.worksheet.derivedMg("118"))).toBeInTheDocument();
    expect(screen.getByText(t.worksheet.verdictTooLittle)).toBeInTheDocument();
    // The stale judgement from the last run is gone, and so is its label.
    expect(screen.queryByText(t.worksheet.derivedFromLatestRun)).not.toBeInTheDocument();
    expect(screen.queryByText(t.worksheet.derivedMg("151.2"))).not.toBeInTheDocument();
  });
});

/**
 * The edit strip, reshaped to the production sheet.
 *
 * Two things the old strip got wrong for a real definition. (1) It ordered
 * fields the way the PDB happens to list them — for GLUE_WEIGHT that is every
 * derived glue weight interleaved with the readings it comes from, with every
 * `order` set to 1, so there was nothing to sort by. (2) It prefilled
 * `definition.results`, and no mirrored MODULE definition has that key: the
 * measurements are under `parameters`, so the strip re-opened blank over a
 * recorded run without saying so.
 */
describe("ModuleWorksheet edit strip layout", () => {
  const layoutSettings = {
    glue_weight_inputs: {
      hybrids: {
        label: "Gluing hybrids",
        test_type: "GLUE_WEIGHT",
        measured: "GW_MODULE_H1",
        subtract: ["GW_SENSOR", "GW_HYBRID1"],
        result_code: "GW_GLUE_H1",
      },
    },
    test_tool_fields: {
      // GLUE_WEIGHT deliberately has no entry: GW_METHOD is the application
      // method, not a tool slot. MODULE_BOW.JIG is a real PDB tool property.
      MODULE_BOW: [{ code: "JIG", kinds: ["jig"] }],
    },
  };

  const institute: Institute = {
    id: 3,
    code: "EXAMPLE",
    name: "Example Institute",
    local_name_prefix: "EX",
    settings: layoutSettings,
    created_at: "2026-08-01T00:00:00Z",
  };

  const assemblyJig: Tool = {
    id: 21,
    kind: "jig",
    code: "20USERT0605010",
    label: "Module assembly jig 5010",
    rfid: null,
    compatible_types: [],
    institute_id: 3,
    status: "active",
    created_at: "2026-08-01T00:00:00Z",
  };

  /** The definition as the mirror holds it: measurements under `parameters`. */
  const mirroredGlueSchema: TestTypeSchema = {
    ...glueSchema,
    schema: {
      code: "GLUE_WEIGHT",
      properties: [],
      parameters: [
        { code: "GW_GLUE_H1", name: "Glue under hybrid 1", dataType: "float" },
        { code: "GW_MODULE_H1", name: "Module after hybrid", dataType: "float" },
        { code: "GW_SENSOR", name: "Sensor weight", dataType: "float" },
        { code: "GW_HYBRID1", name: "Hybrid 1 weight", dataType: "float" },
      ],
    },
  };

  const glueRun: TestRunDetail = {
    ...mirroredRun,
    results: {
      GW_SENSOR: 7.0162,
      GW_HYBRID1: 2.233,
      GW_MODULE_H1: 9.3819,
      GW_GLUE_H1: 0.133,
    },
    properties: {},
  };

  const moduleBowWorksheet: ComponentPreviewWorksheet = {
    groups: [
      {
        stage: "TESTED",
        reached: true,
        rows: [
          {
            test_type: "MODULE_BOW",
            status: "passed",
            latest: {
              external_ref: "run-bow-1",
              measured_at: "2026-08-20T10:00:00Z",
              run_number: "3",
              passed: true,
              scalars: [{ code: "BOW", name: "Module bow", value: 42.1 }],
              arrays: [],
              attachment_count: 0,
            },
            staged: [],
            run_count: 1,
          },
        ],
      },
    ],
  };

  const mirroredBowSchema: TestTypeSchema = {
    id: 8,
    component_type: "MODULE",
    test_code: "MODULE_BOW",
    name: "Module bow",
    synced_at: "2026-08-26T00:00:00Z",
    schema: {
      code: "MODULE_BOW",
      properties: [{ code: "JIG", name: "Module assembly jig", dataType: "string" }],
      parameters: [{ code: "BOW", name: "Module bow", dataType: "float" }],
    },
  };

  const moduleBowRun: TestRunDetail = {
    ...mirroredRun,
    test_type: "MODULE_BOW",
    external_ref: "run-bow-1",
    results: { BOW: 42.1 },
    properties: { JIG: "20USERT0605010" },
  };

  const renderBowWorksheet = () =>
    renderWorksheet({
      worksheet: moduleBowWorksheet,
      schemas: [mirroredBowSchema],
      editIntent: { testType: "MODULE_BOW", token: 1 },
    });

  beforeEach(() => {
    vi.mocked(getComponentTests).mockResolvedValue([glueRun]);
    vi.mocked(postIngestFile).mockResolvedValue(ingestFile);
    vi.mocked(getIngestPreview).mockResolvedValue(dryRun);
    vi.mocked(postIngestOutboxProposal).mockResolvedValue(action);
    vi.mocked(getInstitutes).mockResolvedValue([institute]);
    vi.mocked(getTools).mockResolvedValue([assemblyJig]);
  });

  it("runs the fields in the sheet's order and keeps the derived result read-only", async () => {
    const { container } = renderWorksheet({
      schemas: [mirroredGlueSchema],
      editIntent: { testType: "GLUE_WEIGHT", token: 1 },
    });

    await screen.findByLabelText(/Sensor weight/u);
    const order = Array.from(container.querySelectorAll<HTMLInputElement>("input[name]"))
      .map((input) => input.name)
      .filter((name) => name.startsWith("results."));
    // Sheet rows 10 / 17 / 21 are raw readings. Formula row 24 is rendered by
    // DerivedDetail, never as the definition's editable GW_GLUE_H1 field.
    expect(order).toEqual([
      "results.GW_SENSOR",
      "results.GW_HYBRID1",
      "results.GW_MODULE_H1",
    ]);
    expect(screen.queryByLabelText(/Glue under hybrid 1/u)).not.toBeInTheDocument();
    // The glue profile has no fake tool slot for GW_METHOD.
    expect(screen.queryByText("Tooling")).not.toBeInTheDocument();
  });

  it("prefills from a parameters-only definition instead of opening blank over a recorded run", async () => {
    renderWorksheet({
      schemas: [mirroredGlueSchema],
      editIntent: { testType: "GLUE_WEIGHT", token: 1 },
    });

    expect(await screen.findByLabelText(/Sensor weight/u)).toHaveValue("7.0162");
    expect(screen.getByLabelText(/Module after hybrid/u)).toHaveValue("9.3819");
  });

  it("prefills a tool field as a selected registry entry, not as free text", async () => {
    vi.mocked(getComponentTests).mockResolvedValue([moduleBowRun]);
    renderBowWorksheet();

    const select = (await screen.findByLabelText("Module assembly jig")) as HTMLSelectElement;
    expect(select.tagName).toBe("SELECT");
    // The registry and the previous run arrive in separate responses; the
    // selection is only correct once both have.
    await waitFor(() => expect(select.value).toBe("20USERT0605010"));
    expect(
      within(select).getByRole("option", { name: "Module assembly jig 5010 · 20USERT0605010" }),
    ).toBeInTheDocument();
    // Still scannable: adding the dropdown must not remove the faster path.
    expect(
      screen.getByLabelText("Scan a tool for Module assembly jig"),
    ).toBeInTheDocument();
  });

  it("keeps a stored value the registry does not know rather than silently blanking it", async () => {
    // Real mirrored data: the same jig recorded as free text across runs.
    vi.mocked(getComponentTests).mockResolvedValue([
      { ...moduleBowRun, properties: { JIG: "Module Assembly Jig" } },
    ]);
    renderBowWorksheet();

    const select = (await screen.findByLabelText("Module assembly jig")) as HTMLSelectElement;
    await waitFor(() => expect(select.value).toBe("Module Assembly Jig"));
    expect(
      within(select).getByRole("option", {
        name: "Module Assembly Jig — not in the tool registry",
      }),
    ).toBeInTheDocument();
  });

  it("stages the chosen tool under the schema's own code", async () => {
    const user = userEvent.setup();
    vi.mocked(getComponentTests).mockResolvedValue([moduleBowRun]);
    renderBowWorksheet();

    await screen.findByLabelText(/Module bow/u);
    await waitFor(() =>
      expect(
        (screen.getByLabelText("Module assembly jig") as HTMLSelectElement).value,
      ).toBe("20USERT0605010"),
    );
    fireEvent.change(screen.getByLabelText(/Run number/u), { target: { value: "7" } });
    fireEvent.change(screen.getByLabelText(/Measurement date/u), {
      target: { value: "2026-08-26T10:00" },
    });
    await user.click(screen.getByRole("button", { name: "Stage test result" }));

    await waitFor(() => expect(postIngestFile).toHaveBeenCalledTimes(1));
    const payload = vi.mocked(postIngestFile).mock.calls[0]?.[0]?.payload as Record<
      string,
      unknown
    >;
    expect((payload.properties as Record<string, unknown>).JIG).toBe("20USERT0605010");
  });
});
