import { useEffect, useMemo, useRef, useState } from "react";
import type { ChangeEvent, DragEvent } from "react";
import {
  getIngestPreview,
  postIngestFile,
  postIngestOutboxProposal,
} from "./api";
import type {
  IngestFile,
  IngestPreview,
  OutboxAction,
  TestTypeSchema,
} from "./api";
import TestForm from "./TestForm";
import type {
  TestFormLabels,
  TestFormSubmitPayload,
} from "./TestForm";

const DEFAULT_MAX_FILE_BYTES = 5 * 1024 * 1024;

type BusyOperation = "ingest" | "preview" | "stage" | null;

export type AddTestResultLabels = {
  title: string;
  subtitle: string;
  fileEntryTitle: string;
  dropFile: string;
  chooseFile: string;
  fileHint: (maxBytes: number) => string;
  recordEntryTitle: string;
  recordTest: string;
  closeRecordTest: string;
  testTypeLabel: string;
  chooseTestType: string;
  pinnedTestType: (testType: string) => string;
  pinnedSchemaMissing: (testType: string) => string;
  noSchemas: string;
  syncSchemas: string;
  syncingSchemas: string;
  schemasLoading: string;
  processing: string;
  manualFilename: (testType: string) => string;
  fileTooLarge: (filename: string, maxBytes: number) => string;
  invalidJson: (filename: string) => string;
  jsonObjectRequired: (filename: string) => string;
  readFailed: (filename: string, error: string) => string;
  ingestFailed: (error: string) => string;
  schemaSyncFailed: (error: string) => string;
  dryRunTitle: string;
  previewLoading: string;
  previewFailed: (error: string) => string;
  retryPreview: string;
  previewReady: string;
  previewBlocked: string;
  fileLabel: string;
  parserLabel: string;
  componentLabel: string;
  stageLabel: string;
  previewTestTypeLabel: string;
  runLabel: string;
  measuredLabel: string;
  passedLabel: string;
  problemsLabel: string;
  propertiesLabel: string;
  yes: string;
  no: string;
  none: string;
  issuesTitle: string;
  warningsTitle: string;
  resultsTitle: string;
  stageUpload: string;
  stagingUpload: string;
  alreadyStaged: (actionId: number) => string;
  staged: (actionId: number) => string;
  stageFailed: (error: string) => string;
  reset: string;
  testForm: TestFormLabels;
};

export type AddTestResultProps = {
  componentSn: string;
  componentType: string;
  labels: AddTestResultLabels;
  schemas: readonly TestTypeSchema[];
  schemasLoading?: boolean;
  schemasSyncing?: boolean;
  onSyncSchemas?: (componentType: string) => void | Promise<unknown>;
  onRefresh?: () => void | Promise<unknown>;
  onPreviewReady?: (file: IngestFile, preview: IngestPreview) => void | Promise<unknown>;
  onStaged?: (
    action: OutboxAction,
    file: IngestFile,
    preview: IngestPreview,
  ) => void | Promise<unknown>;
  instituteCode?: string;
  maxFileBytes?: number;
  disabled?: boolean;
  pinnedTestType?: string;
  intentToken?: number;
};

function isJsonObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function manualPayload(payload: TestFormSubmitPayload): Record<string, unknown> {
  return {
    component: payload.component,
    testType: payload.testType,
    runNumber: payload.runNumber,
    date: payload.date,
    passed: payload.passed,
    problems: payload.problems,
    properties: payload.properties,
    results: payload.results,
  };
}

export default function AddTestResult({
  componentSn,
  componentType,
  labels,
  schemas,
  schemasLoading = false,
  schemasSyncing = false,
  onSyncSchemas,
  onRefresh,
  onPreviewReady,
  onStaged,
  instituteCode,
  maxFileBytes = DEFAULT_MAX_FILE_BYTES,
  disabled = false,
  pinnedTestType,
  intentToken = 0,
}: AddTestResultProps) {
  const rootRef = useRef<HTMLElement>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [selectedSchemaId, setSelectedSchemaId] = useState<number | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [busy, setBusy] = useState<BusyOperation>(null);
  const [syncBusy, setSyncBusy] = useState(false);
  const [entryError, setEntryError] = useState<string | null>(null);
  const [schemaError, setSchemaError] = useState<string | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [stageError, setStageError] = useState<string | null>(null);
  const [ingest, setIngest] = useState<IngestFile | null>(null);
  const [preview, setPreview] = useState<IngestPreview | null>(null);
  const [stagedActionId, setStagedActionId] = useState<number | null>(null);

  const availableSchemas = useMemo(
    () =>
      schemas.filter(
        (schema) => schema.component_type.toUpperCase() === componentType.toUpperCase(),
      ),
    [componentType, schemas],
  );
  const normalizedPinnedTestType = pinnedTestType?.trim().toUpperCase() || null;
  const selectableSchemas = useMemo(
    () =>
      normalizedPinnedTestType === null
        ? availableSchemas
        : availableSchemas.filter(
            (schema) => schema.test_code.toUpperCase() === normalizedPinnedTestType,
          ),
    [availableSchemas, normalizedPinnedTestType],
  );
  const selectedSchema =
    selectedSchemaId === null
      ? null
      : (selectableSchemas.find((schema) => schema.id === selectedSchemaId) ?? null);
  const interactionDisabled = disabled || busy !== null || syncBusy;
  const schemaInteractionDisabled =
    interactionDisabled || schemasLoading || schemasSyncing;

  useEffect(() => {
    setFormOpen(false);
    setSelectedSchemaId(null);
    setDragActive(false);
    setBusy(null);
    setEntryError(null);
    setSchemaError(null);
    setPreviewError(null);
    setStageError(null);
    setIngest(null);
    setPreview(null);
    setStagedActionId(null);
  }, [componentSn, componentType]);

  useEffect(() => {
    if (normalizedPinnedTestType === null || intentToken === 0) return;
    setFormOpen(true);
    const match = selectableSchemas[0];
    setSelectedSchemaId(match?.id ?? null);
    rootRef.current?.scrollIntoView?.({ behavior: "smooth", block: "start" });
  }, [intentToken, normalizedPinnedTestType, selectableSchemas]);

  useEffect(() => {
    if (
      selectedSchemaId !== null &&
      !selectableSchemas.some((schema) => schema.id === selectedSchemaId)
    ) {
      setSelectedSchemaId(null);
    }
  }, [selectableSchemas, selectedSchemaId]);

  async function notifyPreviewReady(file: IngestFile, nextPreview: IngestPreview) {
    try {
      await onPreviewReady?.(file, nextPreview);
    } catch {
      // Parent refresh callbacks must not turn a successful ingest into a false failure.
    }
  }

  async function ingestPayload(
    filename: string,
    payload: Record<string, unknown>,
    parser?: "manual-entry",
  ) {
    setBusy("ingest");
    setEntryError(null);
    setPreviewError(null);
    setStageError(null);
    setIngest(null);
    setPreview(null);
    setStagedActionId(null);

    let created: IngestFile | null = null;
    try {
      const body: Parameters<typeof postIngestFile>[0] = {
        filename,
        payload,
        component_sn: componentSn,
        ...(normalizedPinnedTestType === null
          ? {}
          : { test_type: normalizedPinnedTestType }),
        ...(parser === undefined ? {} : { parser }),
      };
      created = await postIngestFile(body);
      setIngest(created);
      const nextPreview = await getIngestPreview(created.id);
      setPreview(nextPreview);
      setStagedActionId(created.outbox_action_id);
      await notifyPreviewReady(created, nextPreview);
    } catch (error) {
      if (created === null) {
        setEntryError(labels.ingestFailed(errorMessage(error)));
      } else {
        setPreviewError(labels.previewFailed(errorMessage(error)));
      }
    } finally {
      setBusy(null);
    }
  }

  async function handleFile(file: File) {
    setEntryError(null);
    if (file.size > maxFileBytes) {
      setEntryError(labels.fileTooLarge(file.name, maxFileBytes));
      return;
    }

    setBusy("ingest");
    let parsed: unknown;
    try {
      const text = await file.text();
      parsed = JSON.parse(text) as unknown;
    } catch (error) {
      setEntryError(
        error instanceof SyntaxError
          ? labels.invalidJson(file.name)
          : labels.readFailed(file.name, errorMessage(error)),
      );
      setBusy(null);
      return;
    }
    if (!isJsonObject(parsed)) {
      setEntryError(labels.jsonObjectRequired(file.name));
      setBusy(null);
      return;
    }
    await ingestPayload(file.name, parsed);
  }

  function handleFileInput(event: ChangeEvent<HTMLInputElement>) {
    const file = event.currentTarget.files?.[0];
    event.currentTarget.value = "";
    if (file !== undefined) void handleFile(file);
  }

  function handleDrag(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    event.stopPropagation();
    if (!interactionDisabled) setDragActive(event.type === "dragenter" || event.type === "dragover");
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    event.stopPropagation();
    setDragActive(false);
    if (interactionDisabled) return;
    const file = event.dataTransfer.files[0];
    if (file !== undefined) void handleFile(file);
  }

  async function handleManualSubmit(payload: TestFormSubmitPayload) {
    await ingestPayload(
      labels.manualFilename(payload.testType),
      manualPayload(payload),
      "manual-entry",
    );
  }

  async function handleSchemaSync() {
    if (onSyncSchemas === undefined) return;
    setSchemaError(null);
    setSyncBusy(true);
    try {
      await onSyncSchemas(componentType);
    } catch (error) {
      setSchemaError(labels.schemaSyncFailed(errorMessage(error)));
    } finally {
      setSyncBusy(false);
    }
  }

  async function refreshPreview() {
    if (ingest === null) return;
    setBusy("preview");
    setPreviewError(null);
    try {
      const nextPreview = await getIngestPreview(ingest.id);
      setPreview(nextPreview);
      await notifyPreviewReady(ingest, nextPreview);
    } catch (error) {
      setPreviewError(labels.previewFailed(errorMessage(error)));
    } finally {
      setBusy(null);
    }
  }

  async function handleStageUpload() {
    if (
      ingest === null ||
      preview === null ||
      !preview.upload_ready ||
      preview.issues.length > 0 ||
      stagedActionId !== null ||
      ingest.outbox_action_id !== null
    ) {
      return;
    }

    setBusy("stage");
    setStageError(null);
    try {
      const body: Parameters<typeof postIngestOutboxProposal>[1] = {
        ...(instituteCode === undefined ? {} : { institute_code: instituteCode }),
      };
      const action = await postIngestOutboxProposal(ingest.id, body);
      const nextIngest = { ...ingest, status: "proposed", outbox_action_id: action.id };
      setIngest(nextIngest);
      setStagedActionId(action.id);
      try {
        await onStaged?.(action, nextIngest, preview);
        await onRefresh?.();
      } catch {
        // The action is already staged; callback failures must not contradict that fact.
      }
    } catch (error) {
      setStageError(labels.stageFailed(errorMessage(error)));
    } finally {
      setBusy(null);
    }
  }

  function resetResult() {
    setEntryError(null);
    setPreviewError(null);
    setStageError(null);
    setIngest(null);
    setPreview(null);
    setStagedActionId(null);
  }

  const existingActionId = stagedActionId ?? ingest?.outbox_action_id ?? null;
  const stageDisabled =
    disabled ||
    busy !== null ||
    preview === null ||
    !preview.upload_ready ||
    preview.issues.length > 0 ||
    existingActionId !== null;

  return (
    <section
      ref={rootRef}
      className="panel phase4-detail add-test-result"
      aria-busy={busy !== null}
    >
      <header className="phase4-panel-head add-test-result-head">
        <div>
          <h3 className="detail-title">{labels.title}</h3>
          <p className="phase4-copy muted">{labels.subtitle}</p>
        </div>
        <span className="chip neutral mono">{componentSn}</span>
        {normalizedPinnedTestType !== null && (
          <span className="chip queued mono">
            {labels.pinnedTestType(normalizedPinnedTestType)}
          </span>
        )}
      </header>

      <div className="phase4-split add-test-result-entries">
        <div className="add-test-result-entry">
          <h4 className="section-title">{labels.fileEntryTitle}</h4>
          <div
            className={`add-test-dropzone${dragActive ? " is-dragging" : ""}`}
            onDragEnter={handleDrag}
            onDragOver={handleDrag}
            onDragLeave={handleDrag}
            onDrop={handleDrop}
          >
            <span>{busy === "ingest" ? labels.processing : labels.dropFile}</span>
            <label className="btn" aria-disabled={interactionDisabled}>
              {labels.chooseFile}
              <input
                className="add-test-file-input"
                type="file"
                accept="application/json,.json"
                hidden
                disabled={interactionDisabled}
                onChange={handleFileInput}
              />
            </label>
            <small className="muted">{labels.fileHint(maxFileBytes)}</small>
          </div>
        </div>

        <div className="add-test-result-entry">
          <h4 className="section-title">{labels.recordEntryTitle}</h4>
          <div className="phase4-action-bar">
            <button
              type="button"
              className="btn"
              disabled={schemaInteractionDisabled}
              aria-expanded={formOpen}
              onClick={() => setFormOpen((open) => !open)}
            >
              {formOpen ? labels.closeRecordTest : labels.recordTest}
            </button>
            {onSyncSchemas !== undefined && (
              <button
                type="button"
                className="btn"
                disabled={schemaInteractionDisabled}
                onClick={() => void handleSchemaSync()}
              >
                {syncBusy || schemasSyncing ? labels.syncingSchemas : labels.syncSchemas}
              </button>
            )}
          </div>
          {schemasLoading && <p className="state-note">{labels.schemasLoading}</p>}
          {!schemasLoading && selectableSchemas.length === 0 && (
            <p className="state-note">
              {normalizedPinnedTestType === null
                ? labels.noSchemas
                : labels.pinnedSchemaMissing(normalizedPinnedTestType)}
            </p>
          )}
          {schemaError !== null && <p className="error-text" role="alert">{schemaError}</p>}
        </div>
      </div>

      {formOpen && selectableSchemas.length > 0 && (
        <div className="phase4-subsection add-test-manual-entry">
          <label className="phase4-field">
            <span className="field-label">{labels.testTypeLabel}</span>
            <select
              className="select-input"
              value={selectedSchemaId ?? ""}
              disabled={schemaInteractionDisabled || normalizedPinnedTestType !== null}
              onChange={(event) => {
                const value = event.target.value;
                setSelectedSchemaId(value === "" ? null : Number(value));
              }}
            >
              <option value="">{labels.chooseTestType}</option>
              {selectableSchemas.map((schema) => (
                <option key={schema.id} value={schema.id}>
                  {schema.name} · {schema.test_code}
                </option>
              ))}
            </select>
          </label>
          {selectedSchema !== null && (
            <TestForm
              component={componentSn}
              schema={selectedSchema}
              labels={labels.testForm}
              disabled={schemaInteractionDisabled}
              onSubmit={handleManualSubmit}
            />
          )}
        </div>
      )}

      {entryError !== null && <p className="error-text" role="alert">{entryError}</p>}

      {ingest !== null && (
        <div className="phase4-subsection preview-panel add-test-dry-run">
          <div className="phase4-panel-head">
            <div>
              <h4 className="section-title">{labels.dryRunTitle}</h4>
              <span className="mono muted">#{ingest.id} · {ingest.filename}</span>
            </div>
            <button type="button" className="btn" disabled={busy !== null} onClick={resetResult}>
              {labels.reset}
            </button>
          </div>

          {busy === "preview" && <p className="state-note">{labels.previewLoading}</p>}
          {previewError !== null && (
            <div className="error-banner" role="alert">
              <span>{previewError}</span>
              <button
                type="button"
                className="btn"
                disabled={busy !== null}
                onClick={() => void refreshPreview()}
              >
                {labels.retryPreview}
              </button>
            </div>
          )}

          {preview !== null && (
            <>
              <div className="phase4-action-bar add-test-preview-summary">
                <span className={preview.upload_ready ? "chip green" : "chip amber"}>
                  {preview.upload_ready ? labels.previewReady : labels.previewBlocked}
                </span>
                <span className="chip neutral">
                  {labels.parserLabel}: <span className="mono">{preview.parser}</span>
                </span>
                {preview.test_type !== null && <span className="chip stage">{preview.test_type}</span>}
              </div>

              <dl className="field-grid add-test-preview-fields">
                <div>
                  <dt className="field-label">{labels.fileLabel}</dt>
                  <dd>{ingest.filename}</dd>
                </div>
                <div>
                  <dt className="field-label">{labels.componentLabel}</dt>
                  <dd className="mono">{preview.component_sn ?? labels.none}</dd>
                </div>
                <div>
                  <dt className="field-label">{labels.stageLabel}</dt>
                  <dd>{preview.component_stage ?? labels.none}</dd>
                </div>
                <div>
                  <dt className="field-label">{labels.previewTestTypeLabel}</dt>
                  <dd className="mono">{preview.test_type ?? labels.none}</dd>
                </div>
                <div>
                  <dt className="field-label">{labels.runLabel}</dt>
                  <dd>{preview.run_number ?? labels.none}</dd>
                </div>
                <div>
                  <dt className="field-label">{labels.measuredLabel}</dt>
                  <dd>{preview.measured_at ?? labels.none}</dd>
                </div>
                <div>
                  <dt className="field-label">{labels.passedLabel}</dt>
                  <dd>
                    {preview.passed === null ? labels.none : preview.passed ? labels.yes : labels.no}
                  </dd>
                </div>
                <div>
                  <dt className="field-label">{labels.problemsLabel}</dt>
                  <dd>
                    {preview.problems === null
                      ? labels.none
                      : preview.problems
                        ? labels.yes
                        : labels.no}
                  </dd>
                </div>
                <div>
                  <dt className="field-label">{labels.propertiesLabel}</dt>
                  <dd>{preview.n_properties}</dd>
                </div>
              </dl>

              {preview.issues.length > 0 && (
                <div>
                  <div className="field-label">{labels.issuesTitle}</div>
                  <ul className="preview-list error-text">
                    {preview.issues.map((issue) => <li key={issue}>{issue}</li>)}
                  </ul>
                </div>
              )}
              {preview.warnings.length > 0 && (
                <div>
                  <div className="field-label">{labels.warningsTitle}</div>
                  <ul className="preview-list muted">
                    {preview.warnings.map((warning) => <li key={warning}>{warning}</li>)}
                  </ul>
                </div>
              )}
              {preview.results.length > 0 && (
                <div className="phase4-table-wrap">
                  <div className="field-label">{labels.resultsTitle}</div>
                  <table className="data-table preview-results">
                    <tbody>
                      {preview.results.map((result) => (
                        <tr key={result.name}>
                          <td className="mono">{result.name}</td>
                          <td className="muted">{result.kind}</td>
                          <td className="mono">{result.value}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              <div className="phase4-action-bar phase4-actions-end">
                {existingActionId !== null && (
                  <span className="chip green">{labels.staged(existingActionId)}</span>
                )}
                <button
                  type="button"
                  className="btn primary"
                  disabled={stageDisabled}
                  onClick={() => void handleStageUpload()}
                >
                  {existingActionId !== null
                    ? labels.alreadyStaged(existingActionId)
                    : busy === "stage"
                      ? labels.stagingUpload
                      : labels.stageUpload}
                </button>
              </div>
              {stageError !== null && <p className="error-text" role="alert">{stageError}</p>}
            </>
          )}
        </div>
      )}
    </section>
  );
}
