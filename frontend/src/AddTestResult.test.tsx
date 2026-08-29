// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
// SPDX-FileComment: itkflow-7918eedd6986
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type {
  IngestFile,
  IngestPreview,
  Institute,
  OutboxAction,
  TestTypeSchema,
  Tool,
  WorksheetDerived,
} from "./api";
import {
  getIngestPreview,
  getInstitutes,
  getTools,
  postIngestFile,
  postIngestOutboxProposal,
} from "./api";
import AddTestResult from "./AddTestResult";
import type { AddTestResultLabels } from "./AddTestResult";

vi.mock("./api", () => ({
  getIngestPreview: vi.fn(),
  postIngestFile: vi.fn(),
  postIngestOutboxProposal: vi.fn(),
  getInstitutes: vi.fn(async () => []),
  getTools: vi.fn(async () => []),
}));

const labels: AddTestResultLabels = {
  title: "Add test result",
  subtitle: "Upload or record a result.",
  fileEntryTitle: "Instrument file",
  dropFile: "Drop JSON here",
  chooseFile: "Choose JSON file",
  fileHint: (maxBytes) => `Maximum ${maxBytes} bytes.`,
  recordEntryTitle: "Manual entry",
  recordTest: "Record test",
  closeRecordTest: "Close form",
  testTypeLabel: "Test type",
  chooseTestType: "Choose a test type",
  pinnedTestType: (testType) => `Pinned test: ${testType}`,
  pinnedSchemaMissing: (testType) => `No schema for ${testType}.`,
  manualEntryBlocked: (testType, fields) => `${testType} is file-only: ${fields}`,
  useFileUpload: "Use JSON file upload",
  noSchemas: "No schemas available.",
  syncSchemas: "Sync schemas",
  syncingSchemas: "Syncing schemas",
  schemasLoading: "Loading schemas",
  processing: "Processing",
  manualFilename: (testType) => `${testType}.manual.json`,
  fileTooLarge: (filename) => `${filename} is too large.`,
  invalidJson: (filename) => `${filename} is not valid JSON.`,
  jsonObjectRequired: (filename) => `${filename} must contain an object.`,
  readFailed: (filename, error) => `${filename} could not be read: ${error}`,
  ingestFailed: (error) => `Ingest failed: ${error}`,
  schemaSyncFailed: (error) => `Schema sync failed: ${error}`,
  dryRunTitle: "Server dry-run",
  previewLoading: "Loading dry-run",
  previewFailed: (error) => `Dry-run failed: ${error}`,
  retryPreview: "Retry dry-run",
  previewReady: "Ready to stage",
  previewBlocked: "Blocked",
  fileLabel: "File",
  parserLabel: "Parser",
  componentLabel: "Component",
  stageLabel: "Current stage",
  previewTestTypeLabel: "Test type",
  runLabel: "Run",
  measuredLabel: "Measured",
  passedLabel: "Passed",
  problemsLabel: "Problems",
  propertiesLabel: "Properties",
  yes: "Yes",
  no: "No",
  none: "None",
  issuesTitle: "Issues",
  warningsTitle: "Warnings",
  resultsTitle: "Results",
  stageUpload: "Stage upload",
  stagingUpload: "Staging upload",
  alreadyStaged: (id) => `Already staged as ${id}`,
  staged: (id) => `Staged as ${id}`,
  stageFailed: (error) => `Stage failed: ${error}`,
  reset: "Reset result",
  toolSectionTitle: "Tooling",
  toolField: {
    choose: "Choose a tool",
    unknownValue: (value) => `${value} — not in the tool registry`,
    scanLabel: (field) => `Scan a tool for ${field}`,
    scanPlaceholder: "Scan tool barcode or RFID",
    scan: "Scan",
    scanNoMatch: (value) => `No tool offered for this field matches ${value}.`,
    noCandidates: "No registered tool fits this component type and field yet.",
    registryError: (error) => `Could not load the tool registry: ${error}`,
    required: "Choose a tool for this field.",
  },
  testForm: {
    runNumber: "Run number",
    date: "Measured at",
    passed: "Passed",
    problems: "Problems",
    properties: "Properties",
    results: "Results",
    submit: "Dry-run manual result",
    booleanUnset: "Not set",
    booleanTrue: "Yes",
    booleanFalse: "No",
    arrayHint: "One value per line.",
    requiredField: (field) => `${field} is required.`,
    invalidNumber: (field) => `${field} must be numeric.`,
    invalidInteger: (field) => `${field} must be an integer.`,
    invalidBoolean: (field) => `${field} must be a boolean.`,
    unsupportedType: (field, type) => `${field} has unsupported type ${type}.`,
  },
};

const ingestFile: IngestFile = {
  id: 71,
  filename: "metrology.json",
  sha256: "a".repeat(64),
  size_bytes: 180,
  status: "processed",
  component_sn: "20USEM00000001",
  test_type: "MODULE_METROLOGY",
  parser: "pdb-test-run-v1",
  error: null,
  outbox_action_id: null,
  uploaded_by: "server-attributed@example.org",
  created_at: "2026-08-26T10:00:00Z",
  updated_at: "2026-08-26T10:00:00Z",
};

const preview: IngestPreview = {
  file_id: 71,
  parser: "pdb-test-run-v1",
  upload_ready: true,
  component_sn: "20USEM00000001",
  local_name: "Example module",
  component_mirrored: true,
  component_stage: "GLUED",
  institute_code: "EXAMPLE",
  test_type: "MODULE_METROLOGY",
  run_number: "4",
  institution: "EXAMPLE",
  measured_at: "2026-08-26T09:55:00Z",
  passed: true,
  problems: false,
  n_properties: 1,
  results: [{ name: "BOW", kind: "scalar", value: "0.12" }],
  issues: [],
  warnings: ["Review the fixture identifier."],
};

const glueDerivation: WorksheetDerived = {
  kind: "glue_weight",
  process: "TRUE_BLUE",
  process_source: "profile_default",
  steps: [
    {
      key: "hybrids",
      label: "Hybrid glue",
      measured_mg: 137.4,
      target_mg: 151,
      tolerance_mg: 22,
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

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => {
    resolve = next;
  });
  return { promise, resolve };
}

describe("AddTestResult", () => {
  beforeEach(() => {
    vi.mocked(postIngestFile).mockResolvedValue(ingestFile);
    vi.mocked(getIngestPreview).mockResolvedValue(preview);
    vi.mocked(postIngestOutboxProposal).mockResolvedValue(action);
  });

  it("pins a chosen JSON file, runs the server preview, and stages without client actor fields", async () => {
    const user = userEvent.setup();
    const onStaged = vi.fn();
    const rawOnlyMarker = "RAW_PAYLOAD_MUST_NOT_BE_RENDERED";
    const { container } = render(
      <AddTestResult
        componentSn="20USEM00000001"
        componentType="MODULE"
        labels={labels}
        schemas={[]}
        instituteCode="EXAMPLE"
        onStaged={onStaged}
      />,
    );
    const file = new File(
      [
        JSON.stringify({
          component: "20USEM00000001",
          testType: "MODULE_METROLOGY",
          results: [{ name: "BOW", value: 0.12 }],
          internal_marker: rawOnlyMarker,
        }),
      ],
      "metrology.json",
      { type: "application/json" },
    );
    const input = container.querySelector<HTMLInputElement>('input[type="file"]');
    expect(input).not.toBeNull();
    await user.upload(input as HTMLInputElement, file);

    await waitFor(() => expect(postIngestFile).toHaveBeenCalledTimes(1));
    const ingestBody = vi.mocked(postIngestFile).mock.calls[0]?.[0];
    expect(ingestBody).toEqual({
      filename: "metrology.json",
      payload: {
        component: "20USEM00000001",
        testType: "MODULE_METROLOGY",
        results: [{ name: "BOW", value: 0.12 }],
        internal_marker: rawOnlyMarker,
      },
      component_sn: "20USEM00000001",
    });
    expect(ingestBody).not.toHaveProperty("actor");
    expect(ingestBody).not.toHaveProperty("uploaded_by");
    expect(ingestBody).not.toHaveProperty("created_by");
    expect(getIngestPreview).toHaveBeenCalledWith(71);
    expect(await screen.findByText("Ready to stage")).toBeInTheDocument();
    expect(screen.queryByText(rawOnlyMarker)).not.toBeInTheDocument();
    expect(container.querySelector("textarea")).toBeNull();

    await user.click(screen.getByRole("button", { name: "Stage upload" }));
    await waitFor(() => expect(postIngestOutboxProposal).toHaveBeenCalledTimes(1));
    const proposalBody = vi.mocked(postIngestOutboxProposal).mock.calls[0]?.[1];
    expect(postIngestOutboxProposal).toHaveBeenCalledWith(71, {
      institute_code: "EXAMPLE",
    });
    expect(proposalBody).not.toHaveProperty("actor");
    expect(proposalBody).not.toHaveProperty("uploaded_by");
    expect(proposalBody).not.toHaveProperty("created_by");
    await waitFor(() => expect(onStaged).toHaveBeenCalledWith(action, {
      ...ingestFile,
      status: "proposed",
      outbox_action_id: 92,
    }, preview));
  });

  it("shows the server-derived glue judgement in the dry-run before staging", async () => {
    vi.mocked(getIngestPreview).mockResolvedValueOnce({
      ...preview,
      test_type: "GLUE_WEIGHT",
      derived: glueDerivation,
    });
    const user = userEvent.setup();
    const { container } = render(
      <AddTestResult
        componentSn="20USEM00000001"
        componentType="MODULE"
        labels={labels}
        schemas={[]}
        instituteCode="EXAMPLE"
      />,
    );
    await user.upload(
      container.querySelector<HTMLInputElement>('input[type="file"]') as HTMLInputElement,
      new File(
        [JSON.stringify({ component: "20USEM00000001", testType: "GLUE_WEIGHT" })],
        "glue.json",
        { type: "application/json" },
      ),
    );

    expect(await screen.findByText("Derived by the server")).toBeInTheDocument();
    expect(screen.getByText("Hybrid glue")).toBeInTheDocument();
    expect(screen.getByText("137.4 mg")).toBeInTheDocument();
    expect(screen.getByText("151 mg")).toBeInTheDocument();
    expect(screen.getByText("± 22 mg")).toBeInTheDocument();
    expect(screen.getByText(/values checked just now/i)).toBeInTheDocument();
  });

  it("opens on the pinned reception test and sends both server-side pins", async () => {
    const user = userEvent.setup();
    const { container } = render(
      <AddTestResult
        componentSn="20USEM00000001"
        componentType="MODULE"
        labels={labels}
        schemas={[
          {
            id: 1,
            component_type: "MODULE",
            test_code: "MODULE_METROLOGY",
            name: "Module metrology",
            schema: {},
            synced_at: "2026-08-26T10:00:00Z",
          },
          {
            id: 2,
            component_type: "MODULE",
            test_code: "OTHER_TEST",
            name: "Other",
            schema: {},
            synced_at: "2026-08-26T10:00:00Z",
          },
        ]}
        pinnedTestType="MODULE_METROLOGY"
        intentToken={11}
      />,
    );

    expect(await screen.findByText("Pinned test: MODULE_METROLOGY")).toBeInTheDocument();
    const select = screen.getByLabelText("Test type");
    expect(select).toBeDisabled();
    expect(select).toHaveValue("1");
    expect(screen.queryByRole("option", { name: /Other/ })).not.toBeInTheDocument();

    const file = new File(
      [JSON.stringify({ component: "20USEM00000001", testType: "MODULE_METROLOGY" })],
      "reception.json",
      { type: "application/json" },
    );
    const input = container.querySelector<HTMLInputElement>('input[type="file"]');
    await user.upload(input as HTMLInputElement, file);
    await waitFor(() => expect(postIngestFile).toHaveBeenCalledTimes(1));
    expect(vi.mocked(postIngestFile).mock.calls[0]?.[0]).toEqual(
      expect.objectContaining({
        component_sn: "20USEM00000001",
        test_type: "MODULE_METROLOGY",
      }),
    );
  });

  it("drops an old ingest response when the same component receives a new pinned intent", async () => {
    const user = userEvent.setup();
    const pendingIngest = deferred<IngestFile>();
    vi.mocked(postIngestFile).mockReturnValueOnce(pendingIngest.promise);
    const { container, rerender } = render(
      <AddTestResult
        componentSn="20USEM00000001"
        componentType="MODULE"
        labels={labels}
        schemas={[]}
        pinnedTestType="MODULE_METROLOGY"
        intentToken={1}
      />,
    );
    const file = new File(
      [JSON.stringify({ component: "20USEM00000001", testType: "MODULE_METROLOGY" })],
      "old-intent.json",
      { type: "application/json" },
    );
    await user.upload(
      container.querySelector<HTMLInputElement>('input[type="file"]') as HTMLInputElement,
      file,
    );
    await waitFor(() => expect(postIngestFile).toHaveBeenCalledTimes(1));

    rerender(
      <AddTestResult
        componentSn="20USEM00000001"
        componentType="MODULE"
        labels={labels}
        schemas={[]}
        pinnedTestType="RECEPTION_IV"
        intentToken={2}
      />,
    );
    pendingIngest.resolve(ingestFile);

    await waitFor(() =>
      expect(screen.getByText("Pinned test: RECEPTION_IV")).toBeInTheDocument(),
    );
    expect(getIngestPreview).not.toHaveBeenCalled();
    expect(screen.queryByText("Ready to stage")).not.toBeInTheDocument();
    expect(screen.queryByText(/old-intent\.json/)).not.toBeInTheDocument();
  });

  it("preselects initialTestType once schemas are loaded without locking the dropdown", async () => {
    render(
      <AddTestResult
        componentSn="20USEM00000001"
        componentType="MODULE"
        labels={labels}
        schemas={[
          {
            id: 1,
            component_type: "MODULE",
            test_code: "MODULE_METROLOGY",
            name: "Module metrology",
            schema: {},
            synced_at: "2026-08-26T10:00:00Z",
          },
          {
            id: 2,
            component_type: "MODULE",
            test_code: "OTHER_TEST",
            name: "Other",
            schema: {},
            synced_at: "2026-08-26T10:00:00Z",
          },
        ]}
        // Lower-case on purpose: matching against the schema's test_code must
        // be case-insensitive, same as the pinned flow.
        initialTestType={{ testType: "module_metrology", token: 1 }}
      />,
    );

    await waitFor(() => expect(screen.getByLabelText("Test type")).toHaveValue("1"));
    const select = screen.getByLabelText("Test type");
    expect(select).not.toBeDisabled();
    // Unlike pinnedTestType, the full schema list stays choosable.
    expect(screen.getByRole("option", { name: /Other/ })).toBeInTheDocument();
    expect(screen.queryByText(/Pinned test:/)).not.toBeInTheDocument();
  });

  it("opens the record-test form but leaves the selection empty for an unknown initialTestType", async () => {
    render(
      <AddTestResult
        componentSn="20USEM00000001"
        componentType="MODULE"
        labels={labels}
        schemas={[
          {
            id: 1,
            component_type: "MODULE",
            test_code: "MODULE_METROLOGY",
            name: "Module metrology",
            schema: {},
            synced_at: "2026-08-26T10:00:00Z",
          },
        ]}
        initialTestType={{ testType: "MODULE_BOW", token: 1 }}
      />,
    );

    const select = await screen.findByLabelText("Test type");
    expect(select).toHaveValue("");
    expect(select).not.toBeDisabled();
    expect(screen.queryByText(/pinnedSchemaMissing|No schema for/)).not.toBeInTheDocument();
  });

  it("reopens the form on a second click of the same row (token bump) even though the test type string is unchanged", async () => {
    const schema = {
      id: 1,
      component_type: "MODULE",
      test_code: "MODULE_METROLOGY",
      name: "Module metrology",
      schema: {},
      synced_at: "2026-08-26T10:00:00Z",
    };
    const { rerender } = render(
      <AddTestResult
        componentSn="20USEM00000001"
        componentType="MODULE"
        labels={labels}
        schemas={[schema]}
        initialTestType={{ testType: "MODULE_METROLOGY", token: 1 }}
      />,
    );

    await waitFor(() => expect(screen.getByLabelText("Test type")).toHaveValue("1"));
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Close form" }));
    expect(screen.queryByLabelText("Test type")).not.toBeInTheDocument();

    // Same row clicked again: the test-type string alone did not change, but
    // the token did — a naive string-keyed effect would never re-fire here
    // and the form would stay dead on every repeat click (review IMPORTANT #2).
    rerender(
      <AddTestResult
        componentSn="20USEM00000001"
        componentType="MODULE"
        labels={labels}
        schemas={[schema]}
        initialTestType={{ testType: "MODULE_METROLOGY", token: 2 }}
      />,
    );

    await waitFor(() => expect(screen.getByLabelText("Test type")).toHaveValue("1"));
  });

  it("does not reopen a manually closed form or scroll again when only the schemas array changes for an already-applied intent", async () => {
    const scrollIntoView = vi.fn();
    Element.prototype.scrollIntoView = scrollIntoView;
    const schemaA = {
      id: 1,
      component_type: "MODULE",
      test_code: "MODULE_METROLOGY",
      name: "Module metrology",
      schema: {},
      synced_at: "2026-08-26T10:00:00Z",
    };
    const { rerender } = render(
      <AddTestResult
        componentSn="20USEM00000001"
        componentType="MODULE"
        labels={labels}
        schemas={[schemaA]}
        initialTestType={{ testType: "MODULE_METROLOGY", token: 1 }}
      />,
    );

    await waitFor(() => expect(screen.getByLabelText("Test type")).toHaveValue("1"));
    expect(scrollIntoView).toHaveBeenCalledTimes(1);

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Close form" }));
    expect(screen.queryByLabelText("Test type")).not.toBeInTheDocument();

    // A schema reload (new array reference, e.g. from "Sync schemas" or a
    // background refetch) with the SAME intent token must not reopen the
    // form the user just closed, nor scroll again (review IMPORTANT #3).
    const schemaB = {
      id: 2,
      component_type: "MODULE",
      test_code: "OTHER_TEST",
      name: "Other",
      schema: {},
      synced_at: "2026-08-26T10:00:00Z",
    };
    rerender(
      <AddTestResult
        componentSn="20USEM00000001"
        componentType="MODULE"
        labels={labels}
        schemas={[schemaA, schemaB]}
        initialTestType={{ testType: "MODULE_METROLOGY", token: 1 }}
      />,
    );

    expect(screen.queryByLabelText("Test type")).not.toBeInTheDocument();
    expect(scrollIntoView).toHaveBeenCalledTimes(1);
  });

  it("replaces a form with named blockers and focuses the existing JSON upload", async () => {
    const scrollIntoView = vi.fn();
    Element.prototype.scrollIntoView = scrollIntoView;
    const user = userEvent.setup();
    render(
      <AddTestResult
        componentSn="20USEM00000001"
        componentType="MODULE"
        labels={labels}
        schemas={[
          {
            id: 31,
            component_type: "MODULE",
            test_code: "OBJECT_TEST",
            name: "Object test",
            synced_at: "2026-08-27T12:00:00Z",
            schema: {
              properties: [
                { code: "DCS", name: "DCS settings", dataType: "object", required: true },
              ],
              parameters: [{ code: "VALUE", name: "Value", dataType: "float" }],
            },
          },
        ]}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Record test" }));
    await user.selectOptions(screen.getByLabelText("Test type"), "31");

    expect(await screen.findByText(/OBJECT_TEST is file-only/)).toHaveTextContent(
      "DCS settings (DCS)",
    );
    expect(screen.queryByLabelText(/^Run number/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Dry-run manual result" })).not.toBeInTheDocument();

    const fileInput = screen.getByLabelText("Choose JSON file");
    expect(fileInput).not.toHaveAttribute("hidden");
    await user.click(screen.getByRole("button", { name: "Use JSON file upload" }));

    expect(screen.queryByLabelText("Test type")).not.toBeInTheDocument();
    expect(scrollIntoView).toHaveBeenCalledWith({ behavior: "smooth", block: "center" });
    expect(document.activeElement).toBe(fileInput);
  });

  it("keeps a 2-D primitive array file-only instead of flattening it into a textarea", async () => {
    const user = userEvent.setup();
    const { container } = render(
      <AddTestResult
        componentSn="20USEM00000001"
        componentType="MODULE"
        labels={labels}
        schemas={[
          {
            id: 32,
            component_type: "MODULE",
            test_code: "TWO_DIMENSIONAL_TEST",
            name: "Two-dimensional test",
            synced_at: "2026-08-27T12:00:00Z",
            schema: {
              parameters: [
                { code: "VALUE", name: "Value", dataType: "float" },
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
        ]}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Record test" }));
    await user.selectOptions(screen.getByLabelText("Test type"), "32");

    expect(await screen.findByText(/TWO_DIMENSIONAL_TEST is file-only/)).toHaveTextContent(
      "Current (CURRENT)",
    );
    expect(container.querySelector('textarea[name="results.CURRENT"]')).toBeNull();
    expect(screen.queryByLabelText(/^Run number/)).not.toBeInTheDocument();
  });

  it("disables a file-only redirect whenever its target chooser is disabled", async () => {
    const user = userEvent.setup();
    const fileOnlySchema: TestTypeSchema = {
      id: 33,
      component_type: "MODULE",
      test_code: "OBJECT_TEST",
      name: "Object test",
      synced_at: "2026-08-27T12:00:00Z",
      schema: {
        properties: [{ code: "DCS", name: "DCS settings", dataType: "object", required: true }],
        parameters: [{ code: "VALUE", name: "Value", dataType: "float" }],
      },
    };
    const { rerender } = render(
      <AddTestResult
        componentSn="20USEM00000001"
        componentType="MODULE"
        labels={labels}
        schemas={[fileOnlySchema]}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Record test" }));
    await user.selectOptions(screen.getByLabelText("Test type"), "33");
    expect(await screen.findByRole("button", { name: "Use JSON file upload" })).toBeEnabled();

    rerender(
      <AddTestResult
        componentSn="20USEM00000001"
        componentType="MODULE"
        labels={labels}
        schemas={[fileOnlySchema]}
        disabled
      />,
    );

    expect(screen.getByRole("button", { name: "Use JSON file upload" })).toBeDisabled();
    expect(screen.getByLabelText("Choose JSON file")).toBeDisabled();
  });

  it("applies each external file-upload intent once and focuses the real drop target", async () => {
    const scrollIntoView = vi.fn();
    Element.prototype.scrollIntoView = scrollIntoView;
    const { rerender } = render(
      <AddTestResult
        componentSn="20USEM00000001"
        componentType="MODULE"
        labels={labels}
        schemas={[]}
        fileUploadIntent={{ testType: "OBJECT_TEST", token: 1 }}
      />,
    );

    const fileInput = screen.getByLabelText("Choose JSON file");
    await waitFor(() => expect(scrollIntoView).toHaveBeenCalledTimes(1));
    expect(document.activeElement).toBe(fileInput);

    rerender(
      <AddTestResult
        componentSn="20USEM00000001"
        componentType="MODULE"
        labels={labels}
        schemas={[]}
        fileUploadIntent={{ testType: "OBJECT_TEST", token: 1 }}
      />,
    );
    expect(scrollIntoView).toHaveBeenCalledTimes(1);

    rerender(
      <AddTestResult
        componentSn="20USEM00000001"
        componentType="MODULE"
        labels={labels}
        schemas={[]}
        fileUploadIntent={{ testType: "OBJECT_TEST", token: 2 }}
      />,
    );
    await waitFor(() => expect(scrollIntoView).toHaveBeenCalledTimes(2));
    expect(document.activeElement).toBe(fileInput);
  });

  it("keeps the JSON chooser in the keyboard tab order", async () => {
    const user = userEvent.setup();
    render(
      <AddTestResult
        componentSn="20USEM00000001"
        componentType="MODULE"
        labels={labels}
        schemas={[]}
      />,
    );

    const fileInput = screen.getByLabelText("Choose JSON file");
    await user.tab();

    expect(fileInput).toHaveFocus();
    expect(fileInput).toHaveAttribute("type", "file");
  });
});

/**
 * Tool fields (the sheet's data-validation dropdowns).
 *
 * The production sheet never lets an operator type a jig serial: every
 * tooling row is a dropdown. Where itkFlow left one as free text, the mirror
 * shows the result — the same jig recorded under three spellings across 28
 * MODULE_BOW runs. These cover the picker itself: the registry populates it,
 * the kind filter narrows it, the keyboard reaches it, and the scanner-first
 * path is still there for the operator holding the tool.
 */
describe("AddTestResult tool fields", () => {
  const bowSchema: TestTypeSchema = {
    id: 9,
    component_type: "MODULE",
    test_code: "MODULE_BOW",
    name: "Module bow",
    synced_at: "2026-08-27T09:00:00Z",
    schema: {
      code: "MODULE_BOW",
      parameters: [
        { code: "BOW", name: "Bow [mm]", dataType: "float", valueType: "single" },
      ],
      properties: [
        { code: "JIG", name: "Jig", dataType: "string", valueType: "single", required: true },
        {
          code: "SCRIPT_VERSION",
          name: "Script version",
          dataType: "string",
          valueType: "single",
        },
      ],
    },
  };

  const institute: Institute = {
    id: 3,
    code: "EXAMPLE",
    name: "Example Institute",
    local_name_prefix: "EX",
    settings: { test_tool_fields: { MODULE_BOW: [{ code: "JIG", kinds: ["jig"] }] } },
    created_at: "2026-08-01T00:00:00Z",
  };

  function registryTool(overrides: Partial<Tool> & Pick<Tool, "id" | "code">): Tool {
    return {
      kind: "jig",
      label: null,
      rfid: null,
      compatible_types: [],
      institute_id: 3,
      status: "active",
      created_at: "2026-08-01T00:00:00Z",
      ...overrides,
    } as Tool;
  }

  const moduleJig = registryTool({
    id: 11,
    code: "20USERT0510703",
    label: "Module jig 3",
    rfid: "E2801160600002111C6B8584",
  });
  const pickupTool = registryTool({
    id: 12,
    code: "20USERT0510203",
    label: "Pickup tool 3",
    kind: "pickup_tool",
  });
  const wrongModuleJig = registryTool({
    id: 13,
    code: "20USERT0510799",
    label: "R2-only module jig",
    compatible_types: ["R2"],
  });

  beforeEach(() => {
    vi.mocked(postIngestFile).mockResolvedValue(ingestFile);
    vi.mocked(getIngestPreview).mockResolvedValue(preview);
    vi.mocked(postIngestOutboxProposal).mockResolvedValue(action);
    vi.mocked(getInstitutes).mockResolvedValue([institute]);
    vi.mocked(getTools).mockResolvedValue([moduleJig, pickupTool, wrongModuleJig]);
  });

  async function openBowForm() {
    const user = userEvent.setup();
    render(
      <AddTestResult
        componentSn="20USEM00000001"
        componentType="MODULE"
        componentTypeCode="R5M0_HALFMODULE"
        labels={labels}
        schemas={[bowSchema]}
        instituteCode="EXAMPLE"
      />,
    );
    await user.click(screen.getByRole("button", { name: "Record test" }));
    await user.selectOptions(screen.getByLabelText("Test type"), "9");
    return user;
  }

  it("offers the registry — human label first, serial second — and only the configured kind", async () => {
    await openBowForm();

    const select = await screen.findByLabelText("Jig *");
    expect(getTools).toHaveBeenCalledWith(
      {
        status: "active",
        institute: "EXAMPLE",
      },
      expect.any(AbortSignal),
    );
    expect(select.tagName).toBe("SELECT");
    const options = within(select as HTMLSelectElement)
      .getAllByRole("option")
      .map((option) => option.textContent);
    expect(options).toEqual(["Choose a tool", "Module jig 3 · 20USERT0510703"]);
    expect(options.join(" ")).not.toContain("R2-only module jig");
    // A pickup tool is a tool, but not a jig: the kind filter is the whole
    // point of naming `kinds` in the profile.
    expect(options.join(" ")).not.toContain("Pickup tool 3");

    // The field is gone from the generated form, so there is no second,
    // free-text way to record the same jig.
    expect(screen.queryByRole("textbox", { name: /^Jig/u })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Script version")).toBeInTheDocument();
  });

  it("does not expose a configured tool as free text while its profile is loading", async () => {
    const pendingInstitutes = deferred<Institute[]>();
    vi.mocked(getInstitutes).mockReturnValueOnce(pendingInstitutes.promise);
    const user = userEvent.setup();
    render(
      <AddTestResult
        componentSn="20USEM00000001"
        componentType="MODULE"
        componentTypeCode="R5M0_HALFMODULE"
        labels={labels}
        schemas={[bowSchema]}
        instituteCode="EXAMPLE"
      />,
    );

    await user.click(screen.getByRole("button", { name: "Record test" }));
    await user.selectOptions(screen.getByLabelText("Test type"), "9");
    expect(screen.queryByLabelText("Jig *")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Script version")).not.toBeInTheDocument();

    pendingInstitutes.resolve([institute]);
    expect((await screen.findByLabelText("Jig *")).tagName).toBe("SELECT");
  });

  it("is reachable and operable from the keyboard alone", async () => {
    const user = await openBowForm();
    const select = (await screen.findByLabelText("Jig *")) as HTMLSelectElement;

    select.focus();
    expect(document.activeElement).toBe(select);
    await user.selectOptions(select, "20USERT0510703");
    expect(select.value).toBe("20USERT0510703");

    // Tab reaches the scan box next to it — the dropdown never becomes a
    // mouse-only trap in front of the scanner path.
    await user.tab();
    expect(document.activeElement).toBe(screen.getByLabelText("Scan a tool for Jig"));
  });

  it("still accepts a scan: a wedge read plus Enter selects the tool", async () => {
    const user = await openBowForm();
    const scan = await screen.findByLabelText("Scan a tool for Jig");

    // RFID, as a keyboard-wedge reader delivers it: characters then Enter.
    await user.type(scan, "E2801160600002111C6B8584{Enter}");

    const select = screen.getByLabelText("Jig *") as HTMLSelectElement;
    expect(select.value).toBe("20USERT0510703");
    expect((scan as HTMLInputElement).value).toBe("");
  });

  it("says so when a scan matches nothing, instead of silently doing nothing", async () => {
    const user = await openBowForm();
    const scan = await screen.findByLabelText("Scan a tool for Jig");

    await user.type(scan, "20USERT9999999{Enter}");

    expect(
      await screen.findByText("No tool offered for this field matches 20USERT9999999."),
    ).toBeInTheDocument();
    expect((screen.getByLabelText("Jig *") as HTMLSelectElement).value).toBe("");
  });

  it("submits the chosen serial under the schema's own property code", async () => {
    const user = await openBowForm();

    await user.selectOptions(await screen.findByLabelText("Jig *"), "20USERT0510703");
    await user.type(screen.getByLabelText(/^Run number/u), "1");
    await user.type(screen.getByLabelText(/^Measured at/u), "2026-08-27T09:30");
    await user.type(screen.getByLabelText(/^Bow/u), "0.12");
    await user.click(screen.getByRole("button", { name: "Dry-run manual result" }));

    await waitFor(() => expect(postIngestFile).toHaveBeenCalledTimes(1));
    const payload = vi.mocked(postIngestFile).mock.calls[0]?.[0]?.payload as Record<
      string,
      unknown
    >;
    expect((payload.properties as Record<string, unknown>).JIG).toBe("20USERT0510703");
  });

  it("blocks a required tool field instead of staging a run without it", async () => {
    const user = await openBowForm();

    await screen.findByLabelText("Jig *");
    await user.type(screen.getByLabelText(/^Run number/u), "1");
    await user.type(screen.getByLabelText(/^Measured at/u), "2026-08-27T09:30");
    await user.type(screen.getByLabelText(/^Bow/u), "0.12");
    await user.click(screen.getByRole("button", { name: "Dry-run manual result" }));

    // TestForm cannot enforce a field it never saw, so the panel does.
    expect(await screen.findByText("Choose a tool for this field.")).toBeInTheDocument();
    expect(postIngestFile).not.toHaveBeenCalled();
  });
});
