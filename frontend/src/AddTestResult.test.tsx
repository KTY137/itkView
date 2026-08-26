import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { IngestFile, IngestPreview, OutboxAction } from "./api";
import {
  getIngestPreview,
  postIngestFile,
  postIngestOutboxProposal,
} from "./api";
import AddTestResult from "./AddTestResult";
import type { AddTestResultLabels } from "./AddTestResult";

vi.mock("./api", () => ({
  getIngestPreview: vi.fn(),
  postIngestFile: vi.fn(),
  postIngestOutboxProposal: vi.fn(),
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
});
