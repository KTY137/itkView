import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ChangeEvent, DragEvent } from "react";
import type {
  IngestFile,
  IngestPreview,
  OutboxAction,
  TestTypeSchema,
} from "./api";
import { useDataEntryProfile } from "./dataEntryProfile";
import { planFieldLayout } from "./fieldLayout";
import { DerivedDetail } from "./GlueDerivation";
import TestForm, { manualEntryBlockerSummary, manualEntryCapability } from "./TestForm";
import type {
  TestFormLabels,
  TestFormSubmitPayload,
} from "./TestForm";
import { ToolFieldSection } from "./ToolFieldSelect";
import type { ToolFieldLabels } from "./ToolFieldSelect";
import {
  fetchDryRun,
  ingestTestPayload,
  manualEntryPayload,
  proposeStagedUpload,
  stageBlockReason,
} from "./testStaging";

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
  manualEntryBlocked: (testType: string, fields: string) => string;
  useFileUpload: string;
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
  /** Heading over the fields that hold a tool rather than a measurement. */
  toolSectionTitle: string;
  toolField: ToolFieldLabels;
  testForm: TestFormLabels;
};

export type AddTestResultProps = {
  componentSn: string;
  componentType: string;
  /** Exact PDB type code (for example R5M0_HALFMODULE), used for formula/tool fits. */
  componentTypeCode?: string;
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
  /**
   * Preselects the test-type dropdown once schemas are loaded (e.g. a click
   * on a "missing"/"failed" row in the required-tests table). Unlike
   * `pinnedTestType`, the select stays enabled and the full schema list
   * stays choosable; a type with no local schema simply leaves the
   * selection empty instead of blocking entry.
   *
   * `token` must be bumped on every click, even re-clicks of the same row:
   * a plain string prop would not change value (and thus would not re-fire
   * the effect that applies it) on a repeated click for the same test type,
   * leaving the form dead on a second click. Mirrors the `intentToken`
   * pattern used by `pinnedTestType` above, folded into one prop object so
   * this remains a single new prop.
   */
  initialTestType?: RecordTestIntent;
  /** Focus the existing JSON file entry from another surface, such as the worksheet. */
  fileUploadIntent?: RecordTestIntent;
};

/** See `AddTestResultProps.initialTestType`. */
export type RecordTestIntent = {
  testType: string;
  token: number;
};

function isJsonObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export default function AddTestResult({
  componentSn,
  componentType,
  componentTypeCode,
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
  initialTestType,
  fileUploadIntent,
}: AddTestResultProps) {
  const rootRef = useRef<HTMLElement>(null);
  const fileEntryRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
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
  const fileUploadIntentToken = fileUploadIntent?.token ?? 0;

  const focusFileUpload = useCallback(() => {
    setFormOpen(false);
    fileEntryRef.current?.scrollIntoView?.({ behavior: "smooth", block: "center" });
    // Focus the actual file chooser, not merely its surrounding card. A
    // visually hidden (but not HTML-hidden) input remains keyboard-operable
    // and lets Enter/Space open the native picker after a file-only redirect.
    fileInputRef.current?.focus({ preventScroll: true });
  }, []);

  const availableSchemas = useMemo(
    () =>
      schemas.filter(
        (schema) => schema.component_type.toUpperCase() === componentType.toUpperCase(),
      ),
    [componentType, schemas],
  );
  // Read by the row-click effect below without being a dependency of it: a
  // schema reload (e.g. "Sync schemas", or the parent's background refetch)
  // must not re-open a form the user already closed, nor steal their scroll
  // position, for an intent that was already applied (review IMPORTANT #3).
  const availableSchemasRef = useRef(availableSchemas);
  availableSchemasRef.current = availableSchemas;
  const normalizedPinnedTestType = pinnedTestType?.trim().toUpperCase() || null;
  const initialTestTypeToken = initialTestType?.token ?? 0;
  const normalizedInitialTestType = initialTestType?.testType.trim().toUpperCase() || null;
  // NOTE (review IMPORTANT #17): initialTestTypeToken is deliberately NOT
  // part of contextIdentity below. Only a genuine test-TYPE change resets
  // ingest/preview state; re-clicking the same "missing"/"failed" row again
  // (same type, bumped token — see the dedicated effect further down) must
  // not silently discard an in-progress file-drop dry-run for that type.
  const contextIdentity = [
    componentSn,
    componentType,
    componentTypeCode ?? "",
    instituteCode ?? "",
    normalizedPinnedTestType ?? "",
    String(intentToken),
    normalizedInitialTestType ?? "",
  ].join("\u0000");
  const operationGeneration = useRef(0);
  const contextIdentityRef = useRef(contextIdentity);
  if (contextIdentityRef.current !== contextIdentity) {
    contextIdentityRef.current = contextIdentity;
    operationGeneration.current += 1;
  }
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

  // Sheet layout: field order, band grouping and which fields hold a tool.
  // Fetched only once a form is actually open — an operator who only uploads
  // instrument files never pays for it.
  const { layout, tools, loading: profileLoading, toolsError } = useDataEntryProfile({
    instituteCode,
    componentTypeCode,
    enabled: formOpen && selectedSchema !== null,
  });
  const plan = useMemo(
    () =>
      selectedSchema === null || profileLoading
        ? null
        : planFieldLayout(
            selectedSchema.schema,
            selectedSchema.test_code,
            layout,
            componentTypeCode,
          ),
    [selectedSchema, layout, profileLoading, componentTypeCode],
  );
  const laidOutSchema = useMemo(
    () =>
      selectedSchema === null || plan === null
        ? null
        : { ...selectedSchema, schema: plan.definition },
    [selectedSchema, plan],
  );
  const manualCapability = useMemo(
    () =>
      laidOutSchema === null ? null : manualEntryCapability(laidOutSchema.schema),
    [laidOutSchema],
  );
  const [toolValues, setToolValues] = useState<Record<string, string>>({});
  const [missingToolCodes, setMissingToolCodes] = useState<ReadonlySet<string>>(new Set());
  useEffect(() => {
    setToolValues({});
    setMissingToolCodes(new Set());
  }, [selectedSchemaId]);

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
    return () => {
      operationGeneration.current += 1;
    };
  }, [contextIdentity]);

  useEffect(() => {
    if (normalizedPinnedTestType === null || intentToken === 0) return;
    setFormOpen(true);
    const match = selectableSchemas[0];
    setSelectedSchemaId(match?.id ?? null);
    rootRef.current?.scrollIntoView?.({ behavior: "smooth", block: "start" });
  }, [intentToken, normalizedPinnedTestType, selectableSchemas]);

  // A row-level "record this test" shortcut (e.g. from the required-tests
  // table): open the manual-entry form and preselect the matching schema,
  // but — unlike the pinned/locked flow above — leave the dropdown enabled
  // and the full schema list choosable. A type without a local schema just
  // leaves the selection empty; it never blocks or throws.
  //
  // Deps are deliberately `initialTestTypeToken` (not `normalizedInitialTestType`
  // alone, and not `availableSchemas`/`selectableSchemas`):
  //  - review IMPORTANT #2: a re-click of the same row carries the same test
  //    type string, so a string-only dependency would never re-fire this
  //    effect on the second click (React bails out — no value change, no
  //    render). The token increments on every click, same type or not.
  //  - review IMPORTANT #3: `availableSchemas` is intentionally read through
  //    `availableSchemasRef` and left out of the dependency list, so an
  //    unrelated schema reload after the intent was applied cannot reopen the
  //    form or steal the user's scroll position again.
  useEffect(() => {
    if (normalizedPinnedTestType !== null) return;
    if (initialTestTypeToken === 0 || normalizedInitialTestType === null) return;
    setFormOpen(true);
    const match = availableSchemasRef.current.find(
      (schema) => schema.test_code.toUpperCase() === normalizedInitialTestType,
    );
    setSelectedSchemaId(match?.id ?? null);
    rootRef.current?.scrollIntoView?.({ behavior: "smooth", block: "start" });
  }, [normalizedPinnedTestType, initialTestTypeToken, normalizedInitialTestType]);

  useEffect(() => {
    if (fileUploadIntentToken === 0) return;
    focusFileUpload();
  }, [fileUploadIntentToken, focusFileUpload]);

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

  function beginOperation(): number {
    operationGeneration.current += 1;
    return operationGeneration.current;
  }

  function operationIsCurrent(generation: number): boolean {
    return generation === operationGeneration.current;
  }

  async function ingestPayload(
    filename: string,
    payload: Record<string, unknown>,
    parser?: "manual-entry",
    existingGeneration?: number,
  ) {
    const generation = existingGeneration ?? beginOperation();
    setBusy("ingest");
    setEntryError(null);
    setPreviewError(null);
    setStageError(null);
    setIngest(null);
    setPreview(null);
    setStagedActionId(null);

    let created: IngestFile | null = null;
    try {
      created = await ingestTestPayload({
        filename,
        payload,
        componentSn,
        ...(normalizedPinnedTestType === null
          ? {}
          : { testType: normalizedPinnedTestType }),
        ...(parser === undefined ? {} : { parser }),
      });
      if (!operationIsCurrent(generation)) return;
      setIngest(created);
      const nextPreview = await fetchDryRun(created.id);
      if (!operationIsCurrent(generation)) return;
      setPreview(nextPreview);
      setStagedActionId(created.outbox_action_id);
      await notifyPreviewReady(created, nextPreview);
    } catch (error) {
      if (!operationIsCurrent(generation)) return;
      if (created === null) {
        setEntryError(labels.ingestFailed(errorMessage(error)));
      } else {
        setPreviewError(labels.previewFailed(errorMessage(error)));
      }
    } finally {
      if (operationIsCurrent(generation)) setBusy(null);
    }
  }

  async function handleFile(file: File) {
    const generation = beginOperation();
    setEntryError(null);
    if (file.size > maxFileBytes) {
      setEntryError(labels.fileTooLarge(file.name, maxFileBytes));
      return;
    }

    setBusy("ingest");
    let parsed: unknown;
    try {
      const text = await file.text();
      if (!operationIsCurrent(generation)) return;
      parsed = JSON.parse(text) as unknown;
    } catch (error) {
      if (!operationIsCurrent(generation)) return;
      setEntryError(
        error instanceof SyntaxError
          ? labels.invalidJson(file.name)
          : labels.readFailed(file.name, errorMessage(error)),
      );
      setBusy(null);
      return;
    }
    if (!operationIsCurrent(generation)) return;
    if (!isJsonObject(parsed)) {
      setEntryError(labels.jsonObjectRequired(file.name));
      setBusy(null);
      return;
    }
    await ingestPayload(file.name, parsed, undefined, generation);
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

  /**
   * Fold the chosen tools back into the payload the form produced.
   *
   * A tool field never reaches `TestForm` (it is removed from the definition
   * the form renders), so its value has to be merged here — under the same
   * section and code the PDB definition declared it in, so the staged payload
   * is indistinguishable from one typed into the old free-text field.
   *
   * Returns `null` when a required tool field is empty: `TestForm` cannot
   * enforce a field it never saw, so the requirement is enforced at the one
   * place that knows about it, rather than silently staging a run missing a
   * value the schema calls required.
   */
  function withToolValues(payload: TestFormSubmitPayload): TestFormSubmitPayload | null {
    const toolFields = plan?.toolFields ?? [];
    if (toolFields.length === 0) return payload;
    const missing = new Set<string>();
    const merged: TestFormSubmitPayload = {
      ...payload,
      properties: { ...payload.properties },
      results: { ...payload.results },
    };
    for (const field of toolFields) {
      const value = (toolValues[field.code] ?? "").trim();
      if (value === "") {
        if (field.required) missing.add(field.code);
        continue;
      }
      merged[field.section][field.code] = value;
    }
    setMissingToolCodes(missing);
    return missing.size === 0 ? merged : null;
  }

  async function handleManualSubmit(payload: TestFormSubmitPayload) {
    const merged = withToolValues(payload);
    if (merged === null) return;
    await ingestPayload(
      labels.manualFilename(merged.testType),
      manualEntryPayload(merged),
      "manual-entry",
    );
  }

  async function handleSchemaSync() {
    if (onSyncSchemas === undefined) return;
    const generation = beginOperation();
    setSchemaError(null);
    setSyncBusy(true);
    try {
      await onSyncSchemas(componentType);
    } catch (error) {
      if (operationIsCurrent(generation)) {
        setSchemaError(labels.schemaSyncFailed(errorMessage(error)));
      }
    } finally {
      if (operationIsCurrent(generation)) setSyncBusy(false);
    }
  }

  async function refreshPreview() {
    if (ingest === null) return;
    const generation = beginOperation();
    const currentIngest = ingest;
    setBusy("preview");
    setPreviewError(null);
    try {
      const nextPreview = await fetchDryRun(currentIngest.id);
      if (!operationIsCurrent(generation)) return;
      setPreview(nextPreview);
      await notifyPreviewReady(currentIngest, nextPreview);
    } catch (error) {
      if (operationIsCurrent(generation)) {
        setPreviewError(labels.previewFailed(errorMessage(error)));
      }
    } finally {
      if (operationIsCurrent(generation)) setBusy(null);
    }
  }

  async function handleStageUpload() {
    if (
      ingest === null ||
      stageBlockReason(preview, stagedActionId ?? ingest.outbox_action_id) !== null ||
      preview === null
    ) {
      return;
    }

    const generation = beginOperation();
    const currentIngest = ingest;
    const currentPreview = preview;
    setBusy("stage");
    setStageError(null);
    try {
      const action = await proposeStagedUpload(currentIngest.id, instituteCode);
      if (!operationIsCurrent(generation)) return;
      const nextIngest = {
        ...currentIngest,
        status: "proposed",
        outbox_action_id: action.id,
      };
      setIngest(nextIngest);
      setStagedActionId(action.id);
      try {
        await onStaged?.(action, nextIngest, currentPreview);
        if (!operationIsCurrent(generation)) return;
        await onRefresh?.();
      } catch {
        // The action is already staged; callback failures must not contradict that fact.
      }
    } catch (error) {
      if (operationIsCurrent(generation)) {
        setStageError(labels.stageFailed(errorMessage(error)));
      }
    } finally {
      if (operationIsCurrent(generation)) setBusy(null);
    }
  }

  function resetResult() {
    beginOperation();
    setEntryError(null);
    setPreviewError(null);
    setStageError(null);
    setIngest(null);
    setPreview(null);
    setStagedActionId(null);
  }

  const existingActionId = stagedActionId ?? ingest?.outbox_action_id ?? null;
  const stageDisabled =
    disabled || busy !== null || stageBlockReason(preview, existingActionId) !== null;

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
        <div
          ref={fileEntryRef}
          className="add-test-result-entry"
        >
          <h4 className="section-title">{labels.fileEntryTitle}</h4>
          <div
            className={`add-test-dropzone${dragActive ? " is-dragging" : ""}`}
            onDragEnter={handleDrag}
            onDragOver={handleDrag}
            onDragLeave={handleDrag}
            onDrop={handleDrop}
          >
            <span>{busy === "ingest" ? labels.processing : labels.dropFile}</span>
            <label className="btn file-choose-btn" aria-disabled={interactionDisabled}>
              {labels.chooseFile}
              <input
                ref={fileInputRef}
                className="add-test-file-input"
                type="file"
                accept="application/json,.json"
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
          {plan !== null && manualCapability?.canEnter === true && (
            // Tooling first, as on the sheet: what the module was built in is
            // decided before the scale is read, and it is chosen, not typed.
            <ToolFieldSection
              fields={plan.toolFields}
              tools={tools}
              componentTypeCode={componentTypeCode}
              values={toolValues}
              onChange={(code, value) => {
                setToolValues((current) => ({ ...current, [code]: value }));
                setMissingToolCodes((current) => {
                  if (!current.has(code)) return current;
                  const next = new Set(current);
                  next.delete(code);
                  return next;
                });
              }}
              invalidCodes={missingToolCodes}
              labels={labels.toolField}
              title={labels.toolSectionTitle}
              toolsError={toolsError}
              disabled={schemaInteractionDisabled}
            />
          )}
          {laidOutSchema !== null && manualCapability?.canEnter === false && (
            <div className="info-banner" role="status">
              <span>
                {labels.manualEntryBlocked(
                  laidOutSchema.test_code,
                  manualEntryBlockerSummary(manualCapability),
                )}
              </span>
              <button
                type="button"
                className="btn"
                disabled={schemaInteractionDisabled}
                onClick={focusFileUpload}
              >
                {labels.useFileUpload}
              </button>
            </div>
          )}
          {laidOutSchema !== null && manualCapability?.canEnter === true && (
            <TestForm
              component={componentSn}
              schema={laidOutSchema}
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

              {preview.derived != null && (
                <DerivedDetail derived={preview.derived} source="preview" />
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
