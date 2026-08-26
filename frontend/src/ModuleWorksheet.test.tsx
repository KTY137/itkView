import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  ComponentPreviewWorksheet,
  IngestFile,
  IngestPreview,
  OutboxAction,
  TestRunDetail,
  TestTypeSchema,
} from "./api";
import {
  ApiError,
  getComponentTests,
  getIngestPreview,
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
  });

  it("stages an in-row edit through ingest -> dry-run -> propose-outbox, prefilled from the latest run", async () => {
    const user = userEvent.setup();
    const onStaged = vi.fn();
    renderWorksheet({ onStaged });

    await user.click(screen.getByRole("button", { name: "Record GLUE_WEIGHT" }));

    // Waits for the mirrored run (run_count > 0) and prefills the schema field.
    const gwInput = await screen.findByLabelText(/GW1/);
    expect(gwInput).toHaveValue(0.1664);

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
      expect(await screen.findByLabelText("SCALAR_X")).toHaveValue(5);
      // The dict-valued field is never silently filled — the raw map would
      // otherwise reach TestForm's single-line control as "[object Object]".
      const glueField = screen.getByLabelText("HYBRID_GLUE_THICKNESS");
      expect(glueField).toHaveValue(null);
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

      expect(await screen.findByLabelText(/GW1/)).toHaveValue(0.1664);
      // Never joined into "1\n2\n3" (which would itself fail float validation)
      // nor into any other string — the field is simply left blank.
      const currentField = screen.getByLabelText("Current");
      expect(currentField).toHaveValue(null);
      expect(
        screen.getByText(t.worksheet.prefillDropped("Current")),
      ).toBeInTheDocument();
    });

    it("blocks the strip instead of a silent dead end when a non-round-trippable field is required", async () => {
      const user = userEvent.setup();
      vi.mocked(getComponentTests).mockResolvedValue([metrologyRunWithMap]);
      renderWorksheet({
        worksheet: metrologyWorksheet,
        schemas: [metrologySchemaRequired],
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
});
