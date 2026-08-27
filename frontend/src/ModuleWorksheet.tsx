/**
 * Module worksheet (spec §H2) — the spreadsheet-model primary view of a
 * component: one compact table per stage group (row = a test type), values
 * inline, rows expandable to the full mirrored run, and an in-row edit strip
 * that stages a manual test upload through the shared ingest -> dry-run ->
 * propose-outbox pipeline (`testStaging.ts`). Arrays never render as raw
 * numbers here — the payload contract (spec §H1) only ever carries a point
 * count, the full curve is fetched lazily once a row is expanded or edited.
 *
 * Row state (expansion, the open edit strip, optimistic ghosts) is keyed by
 * `${stage}:${test_type}`, not the bare test type: the server emits one row
 * per (stage, test type) and an ordinary institute profile can require the
 * same test type at two stages (review finding I2) — a bare-test-type key
 * would make the two rows share state and expand/edit together.
 *
 * The edit strip only ever prefills a previous run's value when it provably
 * round-trips through `TestForm`'s generated control (see `valueRoundTrips`)
 * — dict-valued PDB results (per-position measurements) and array/schema
 * mismatches never do, and silently dropping or flattening them corrupts the
 * record on approval (review finding C1). Anything that does not round-trip
 * is named in an explicit notice instead, or blocks the strip outright when
 * the schema marks it required.
 */
import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";

import { ApiError, getComponentTests } from "./api";
import type {
  ComponentPreviewWorksheet,
  TestRunAttachment,
  TestRunDetail,
  TestSchemaDefinition,
  TestSchemaField,
  TestSchemaFieldCollection,
  TestTypeSchema,
  WorksheetArraySummary,
  WorksheetChildGroup,
  WorksheetDerived,
  WorksheetGroup,
  WorksheetLatestRun,
  WorksheetRow,
  WorksheetStagedRef,
} from "./api";
import { useDataEntryProfile } from "./dataEntryProfile";
import { planFieldLayout } from "./fieldLayout";
import { DerivedDetail, DerivedVerdicts } from "./GlueDerivation";
import type { DerivedSource } from "./GlueDerivation";
import ImageLightbox from "./ImageLightbox";
import { t } from "./i18n";
import { manualEntryPayload, useTestStaging } from "./testStaging";
import TestForm, {
  manualEntryBlockerSummary,
  manualEntryCapability,
  measurementCollection,
  requiredCodes,
} from "./TestForm";
import type { TestFormSubmitPayload } from "./TestForm";
import { ToolFieldSection } from "./ToolFieldSelect";
import { formatScalar, RunAttachments, RunConditions, RunCurves, RunScalars } from "./TestResults";
import { describeComponent, outboxStatusChipClass, stageChipClass, stageLabel } from "./ui";

export type ModuleWorksheetProps = {
  componentSn: string;
  componentType: string;
  /** Exact PDB type code (for example R5M0_HALFMODULE), used for formula/tool fits. */
  componentTypeCode?: string;
  instituteCode: string;
  worksheet: ComponentPreviewWorksheet;
  /** Mirrored schemas for the edit strip; null while loading. */
  schemas: TestTypeSchema[] | null;
  /** Write permission for this component's institute, resolved by the caller. */
  canWrite: boolean;
  /** Bumped by the caller to force a reload of expanded run details. */
  refreshKey?: number;
  /** Open the edit strip for this test type (ghost-pencil intent); token distinguishes re-clicks. */
  editIntent?: { testType: string; token: number } | null;
  /** Called after an edit was staged so the caller can refresh the preview. */
  onStaged?: (outboxActionId: number) => void;
  /** Route to the Staged screen (spec §H2 "View in Staged"). Omitted when the
   * caller has no reachable route to it — the label then renders as plain
   * text instead of something that looks clickable and is not (review
   * finding I3). */
  onViewStaged?: () => void;
  /** Move a file-only edit to the component's existing JSON upload entry. */
  onUseFileUpload: (testType: string) => void;
};

const TABLE_COLUMNS = 5;
// The wire exposes the PDB lifecycle state verbatim. Only this exact terminal
// state withdraws a run; `requestedToDelete` still counts as live evidence.
const WITHDRAWN_TEST_RUN_STATE = "deleted";

// ---- Small, self-contained helpers (no imports from ComponentsScreen/TestResults internals) ----

function readString(value: unknown): string | null {
  return typeof value === "string" && value.trim() !== "" ? value.trim() : null;
}

/** A row's state key: the server emits one row per (stage, test type), so the
 * bare test type is not unique enough (review finding I2). */
function rowKey(group: WorksheetGroup, row: WorksheetRow): string {
  return `${group.stage ?? "additional"}:${row.test_type}`;
}

/** Sanitised for use as an HTML id fragment (aria-controls target). */
function sanitizeId(value: string): string {
  return value.replace(/[^a-zA-Z0-9_-]+/gu, "-");
}

function matchWorksheetSchema(
  schemas: readonly TestTypeSchema[] | null,
  testType: string,
  componentType: string,
): TestTypeSchema | null {
  if (schemas === null) return null;
  const targetType = testType.trim().toUpperCase();
  const targetComponent = componentType.trim().toUpperCase();
  return (
    schemas.find(
      (schema) =>
        schema.test_code.trim().toUpperCase() === targetType &&
        schema.component_type.trim().toUpperCase() === targetComponent,
    ) ?? null
  );
}

function collectionEntries(
  collection: TestSchemaFieldCollection | undefined,
): Array<[string | null, TestSchemaField | string | null]> {
  if (collection === undefined) return [];
  return Array.isArray(collection)
    ? collection.map((field) => [null, field] as [string | null, TestSchemaField | string])
    : Object.entries(collection);
}

function candidateCode(
  mapCode: string | null,
  candidate: TestSchemaField | string | null,
): string | null {
  if (typeof candidate === "string") return mapCode ?? readString(candidate);
  if (candidate !== null && typeof candidate === "object") {
    return readString(candidate.code) ?? mapCode;
  }
  return mapCode;
}

function isPlainScalar(value: unknown): value is string | number | boolean {
  return typeof value === "string" || typeof value === "number" || typeof value === "boolean";
}

function fieldDeclaresArray(descriptor: TestSchemaField): boolean {
  const raw = readString(descriptor.valueType) ?? readString(descriptor.value_type) ?? "single";
  return raw.toLowerCase() === "array";
}

/**
 * Whether a previous run's value for one field can pass losslessly through
 * `TestForm`'s generated control and come back out as an equivalent payload
 * value (review finding C1).
 *
 *  - `null`/`undefined` always "round-trips": there is nothing to lose, the
 *    field simply renders blank exactly as it would with no previous run.
 *  - Plain scalars (string/number/boolean) always round-trip: they render
 *    into the matching control (or a one-line textarea, when the schema
 *    declares an array) and `TestForm`'s own parser returns exactly that
 *    value back.
 *  - Arrays round-trip only when the schema itself declares
 *    `valueType: "array"` — otherwise `TestForm`'s default single-value
 *    control would flatten them into one joined string, which is exactly the
 *    corruption this check exists to prevent — and only when every element is
 *    itself a plain, non-null scalar. A `null` element stringifies to the
 *    literal text "null" and fails per-line validation; worse, an operator
 *    "fixing" that by deleting the line would silently reindex every later
 *    sample.
 *  - Dict/map values (PDB per-position measurements, e.g. glue thickness per
 *    channel) never round-trip: `TestForm` has no control for them at all.
 */
function valueRoundTrips(value: unknown, declaredArray: boolean): boolean {
  if (value === null || value === undefined) return true;
  if (Array.isArray(value)) {
    return declaredArray && value.every((entry) => isPlainScalar(entry));
  }
  return isPlainScalar(value);
}

/** A field the edit strip could not prefill from the previous run. */
type PrefillDrop = { code: string; name: string; required: boolean };

/**
 * Re-emit a field collection with each field's `defaultValue` overridden from
 * a previous run's measured values — but only for values that round-trip
 * (`valueRoundTrips`). Anything else is left blank and reported in `drops` so
 * the caller can tell the operator what this staged run will not carry,
 * instead of silently emptying or corrupting it (review finding C1).
 */
function prefillCollection(
  collection: TestSchemaFieldCollection | undefined,
  values: Record<string, unknown>,
  required: Set<string>,
  names: Record<string, string | undefined> = {},
): { fields: TestSchemaField[]; drops: PrefillDrop[] } {
  const fields: TestSchemaField[] = [];
  const drops: PrefillDrop[] = [];
  for (const [mapCode, candidate] of collectionEntries(collection)) {
    const code = candidateCode(mapCode, candidate);
    if (code === null) continue;
    const base: TestSchemaField =
      typeof candidate === "string"
        ? { code, dataType: candidate }
        : candidate !== null && typeof candidate === "object"
          ? { ...candidate, code }
          : { code };

    if (!Object.prototype.hasOwnProperty.call(values, code)) {
      fields.push(base);
      continue;
    }
    const value = values[code];
    if (valueRoundTrips(value, fieldDeclaresArray(base))) {
      fields.push(value === null || value === undefined ? base : { ...base, defaultValue: value });
      continue;
    }
    fields.push(base);
    drops.push({
      code,
      name: names[code] ?? readString(base.name) ?? readString(base.title) ?? code,
      required: base.required === true || required.has(code),
    });
  }
  return { fields, drops };
}

function prefilledDefinition(
  definition: TestSchemaDefinition,
  run: TestRunDetail | null,
): { definition: TestSchemaDefinition; drops: PrefillDrop[] } {
  if (run === null) return { definition, drops: [] };
  const resultNames: Record<string, string | undefined> = {};
  for (const [code, meta] of Object.entries(run.result_meta ?? {})) {
    resultNames[code] = meta?.name;
  }
  const properties = prefillCollection(
    definition.properties,
    run.properties ?? {},
    requiredCodes(definition, "properties"),
  );
  const results = prefillCollection(
    measurementCollection(definition).collection ?? undefined,
    run.results ?? {},
    requiredCodes(definition, "results"),
    resultNames,
  );
  return {
    definition: {
      ...definition,
      properties: properties.fields,
      results: results.fields,
      // Re-emitted under `results`; leaving the source key in place would let
      // the un-prefilled original win back whenever `results` came out empty.
      parameters: undefined,
    },
    drops: [...properties.drops, ...results.drops],
  };
}

function runTimestamp(run: TestRunDetail): number {
  if (run.measured_at === null) return -Infinity;
  const parsed = new Date(run.measured_at).getTime();
  return Number.isNaN(parsed) ? -Infinity : parsed;
}

function newestFirst(runs: TestRunDetail[]): TestRunDetail[] {
  return runs.slice().sort((a, b) => runTimestamp(b) - runTimestamp(a));
}

/** A dict-valued result (e.g. per-channel glue thickness) is summarised the
 * same way an array is — a count chip, never the raw map — but reads
 * "entries" rather than "pts" since the number is a key count, not a sample
 * count. */
function arraySummaryLabel(array: WorksheetArraySummary): string {
  return array.kind === "map"
    ? t.worksheet.mapEntries(array.points)
    : t.worksheet.arrayPoints(array.points);
}

function formatMeasuredAt(value: string | null): string {
  if (value === null) return t.common.none;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

const STATUS_CHIP_CLASS: Record<WorksheetRow["status"], string> = {
  passed: "chip green",
  failed: "chip red",
  missing: "chip amber",
  pending: "chip queued",
};

function statusLabel(status: WorksheetRow["status"]): string {
  switch (status) {
    case "passed":
      return t.worksheet.statusPassed;
    case "failed":
      return t.worksheet.statusFailed;
    case "missing":
      return t.worksheet.statusMissing;
    case "pending":
      return t.worksheet.statusPending;
  }
}

function mergedStaged(
  key: string,
  row: WorksheetRow,
  optimistic: Record<string, WorksheetStagedRef[]>,
): WorksheetStagedRef[] {
  const extra = optimistic[key] ?? [];
  if (extra.length === 0) return row.staged;
  const existingIds = new Set(row.staged.map((ref) => ref.outbox_action_id));
  return [...row.staged, ...extra.filter((ref) => !existingIds.has(ref.outbox_action_id))];
}

function ValuesCell({ latest }: { latest: WorksheetLatestRun | null }) {
  if (latest === null) {
    return <span className="muted">{t.common.none}</span>;
  }
  const visibleScalars = latest.scalars.slice(0, 3);
  const restScalars = latest.scalars.slice(3);
  return (
    <span className="ws-values">
      {visibleScalars.map((scalar) => (
        <span className="ws-val" key={scalar.code} title={scalar.code}>
          <span className="ws-val-name">{scalar.name}</span>{" "}
          <span className="mono">{formatScalar(scalar.value)}</span>
        </span>
      ))}
      {restScalars.length > 0 && (
        <span
          className="chip neutral"
          title={restScalars.map((s) => `${s.name} ${formatScalar(s.value)}`).join(", ")}
        >
          {t.worksheet.moreValues(restScalars.length)}
        </span>
      )}
      {latest.arrays.map((array) => (
        <span className="chip neutral mono" key={array.code} title={array.name}>
          {arraySummaryLabel(array)}
        </span>
      ))}
    </span>
  );
}

/**
 * The evidence measured on the component's children, one read-only table per
 * child. On real data this is where nearly all of a module's history lives —
 * only 720 of 14 759 mirrored runs hang on MODULE components; the rest sit on
 * sensors, hybrids, powerboards, and for an R5 ring module on the two
 * half-modules that carry its metrology, glue weight and PS IV.
 *
 * Kept visibly separate from the stage groups above, and deliberately without
 * a Status column or an edit affordance: a requirement check is a statement
 * about *this* component, and recording a result belongs on the child's own
 * page where the serial in the payload would be right.
 */
function ChildEvidence({ groups }: { groups: readonly WorksheetChildGroup[] }) {
  if (groups.length === 0) return null;
  return (
    <section className="ws-children">
      <h3 className="section-title">{t.worksheet.childrenTitle}</h3>
      <p className="state-note">{t.worksheet.childrenIntro}</p>
      {groups.map((child) => (
        <div className="panel ws-group-panel" key={child.sn}>
          <div className="ws-group-head">
            <span className="chip neutral">
              {describeComponent({
                component_type: child.component_type,
                type_code: child.type_code,
              })}
            </span>
            <span className="mono">{child.sn}</span>
            {child.local_name !== null && <span className="muted">{child.local_name}</span>}
          </div>
          {child.rows.length === 0 ? (
            <p className="state-note">{t.worksheet.childrenEmpty}</p>
          ) : (
            <table className="data-table ws-table">
              <thead>
                <tr>
                  <th scope="col">{t.worksheet.colTest}</th>
                  <th scope="col">{t.worksheet.colValues}</th>
                  <th scope="col">{t.worksheet.colResult}</th>
                  <th scope="col">{t.worksheet.colDate}</th>
                </tr>
              </thead>
              <tbody>
                {child.rows.map((row) => (
                  <tr className="ws-row" key={row.test_type}>
                    <td className="mono">{row.test_type}</td>
                    <td>
                      <ValuesCell latest={row.latest} />
                    </td>
                    <td>
                      {row.latest === null ? (
                        <span className="muted">{t.common.none}</span>
                      ) : (
                        <span className={row.latest.passed === true ? "chip green" : "chip red"}>
                          {row.latest.passed === true
                            ? t.worksheet.statusPassed
                            : t.worksheet.statusFailed}
                        </span>
                      )}
                      <span className="muted"> {t.worksheet.childRunCount(row.run_count)}</span>
                      {row.withdrawn_count > 0 && (
                        <span className="chip amber">
                          {t.worksheet.childWithdrawn(row.withdrawn_count)}
                        </span>
                      )}
                    </td>
                    <td className={row.latest?.measured_at ? undefined : "muted"}>
                      {formatMeasuredAt(row.latest?.measured_at ?? null)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      ))}
    </section>
  );
}

function RunDetailContent({
  sn,
  testType,
  runs,
  runsError,
  onRetry,
  onOpenImage,
}: {
  sn: string;
  testType: string;
  runs: TestRunDetail[] | null;
  runsError: string | null;
  onRetry: () => void;
  onOpenImage: (attachment: TestRunAttachment) => void;
}): ReactNode {
  if (runs === null) {
    return <p className="state-note">{t.common.loading}</p>;
  }
  if (runsError !== null) {
    return (
      <div className="error-banner" role="alert">
        <span>{runsError}</span>
        <button type="button" className="btn" onClick={onRetry}>
          {t.common.retry}
        </button>
      </div>
    );
  }
  const matching = newestFirst(runs.filter((run) => run.test_type === testType));
  if (matching.length === 0) {
    return <p className="state-note">{t.worksheet.noMirroredRuns}</p>;
  }
  return (
    <ul className="run-list">
      {matching.map((run, index) => (
        <li className="run" key={run.external_ref ?? `${testType}-${index}`}>
          <div className="run-head">
            <strong className="run-type">{run.test_type}</strong>
            {run.run_state === WITHDRAWN_TEST_RUN_STATE ? (
              <span className="chip amber" title={t.worksheet.withdrawnHint}>
                {t.worksheet.statusWithdrawn}
              </span>
            ) : (
              <span className={run.passed ? "chip green" : "chip red"}>
                {run.passed ? t.worksheet.statusPassed : t.worksheet.statusFailed}
              </span>
            )}
            {run.run_number !== null && (
              <span className="chip muted">{t.worksheet.runNumber(String(run.run_number))}</span>
            )}
            <span className="muted run-date">{formatMeasuredAt(run.measured_at)}</span>
          </div>
          <RunCurves run={run} />
          <RunScalars run={run} />
          <RunAttachments sn={sn} attachments={run.attachments} onOpen={onOpenImage} />
          <RunConditions run={run} />
        </li>
      ))}
    </ul>
  );
}

export default function ModuleWorksheet({
  componentSn,
  componentType,
  componentTypeCode,
  instituteCode,
  worksheet,
  schemas,
  canWrite,
  refreshKey = 0,
  editIntent = null,
  onStaged,
  onViewStaged,
  onUseFileUpload,
}: ModuleWorksheetProps) {
  const visibleGroups = useMemo(
    () => worksheet.groups.filter((group) => group.rows.length > 0),
    [worksheet],
  );
  const childGroups = useMemo(() => worksheet.children ?? [], [worksheet]);

  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [runsRequested, setRunsRequested] = useState(false);
  const [runs, setRuns] = useState<TestRunDetail[] | null>(null);
  const [runsError, setRunsError] = useState<string | null>(null);
  const [lightbox, setLightbox] = useState<TestRunAttachment | null>(null);
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [optimisticStaged, setOptimisticStaged] = useState<Record<string, WorksheetStagedRef[]>>(
    {},
  );
  const [focusToken, setFocusToken] = useState(0);
  // A test type from an editIntent with no matching worksheet row (review
  // finding M5) — surfaced instead of firing a run fetch for nothing.
  const [missingEditIntent, setMissingEditIntent] = useState<string | null>(null);
  const rowRefs = useRef<Record<string, HTMLTableRowElement | null>>({});
  const stripRefs = useRef<Record<string, HTMLDivElement | null>>({});
  const lastAppliedEditToken = useRef(0);
  const focusedTokenRef = useRef(0);

  const {
    preview: stagingPreview,
    busy: stagingBusy,
    entryError: stagingEntryError,
    previewError: stagingPreviewError,
    stageError: stagingStageError,
    ingestPayload: stagingIngestPayload,
    stageUpload: stagingStageUpload,
    reset: resetStaging,
  } = useTestStaging({
    labels: {
      ingestFailed: t.worksheet.ingestFailed,
      previewFailed: t.worksheet.previewFailed,
      stageFailed: t.worksheet.stageFailed,
    },
  });

  useEffect(() => {
    setRuns(null);
    setRunsError(null);
  }, [componentSn, refreshKey]);

  // Review finding I1: the previous implementation cleared optimistic ghosts
  // only on `componentSn` change, which never fires — the parent keys the
  // whole detail panel by `sn` and remounts instead of updating it in place.
  // The `worksheet` prop, by contrast, changes on every preview refresh
  // (evidence sync, a Push/Discard in the Staged-actions panel above, this
  // strip's own successful stage) — and by the time it does, the server's
  // view already includes whatever really happened, so the optimistic copy
  // has served its purpose and can be dropped unconditionally.
  useEffect(() => {
    setOptimisticStaged({});
  }, [worksheet]);

  useEffect(() => {
    if (!runsRequested || runs !== null) return;
    let cancelled = false;
    const ctrl = new AbortController();
    getComponentTests(componentSn, ctrl.signal)
      .then((data) => {
        if (cancelled) return;
        setRuns(data);
        setRunsError(null);
      })
      .catch((error: unknown) => {
        if (cancelled || ctrl.signal.aborted) return;
        setRuns([]);
        setRunsError(error instanceof ApiError ? error.message : t.worksheet.runsLoadError);
      });
    return () => {
      cancelled = true;
      ctrl.abort();
    };
  }, [runsRequested, runs, componentSn, refreshKey]);

  // Review finding M3: once every row is collapsed and no edit strip is open,
  // stop asking for the (potentially ~242 kB) mirrored-runs payload on every
  // refreshKey bump — the very cost the worksheet exists to avoid.
  useEffect(() => {
    const anythingOpen = editingKey !== null || Object.values(expanded).some(Boolean);
    if (!anythingOpen) setRunsRequested(false);
  }, [expanded, editingKey]);

  function toggleExpand(key: string) {
    setExpanded((current) => ({ ...current, [key]: !current[key] }));
    setRunsRequested(true);
  }

  function closeEdit() {
    setEditingKey(null);
    resetStaging();
  }

  function openEdit(key: string) {
    if (editingKey !== key) {
      resetStaging();
    }
    setEditingKey(key);
    setRunsRequested(true);
    setMissingEditIntent(null);
  }

  function handlePencilClick(key: string) {
    if (editingKey === key) {
      closeEdit();
    } else {
      openEdit(key);
    }
  }

  useEffect(() => {
    if (
      editIntent === null ||
      editIntent.token === 0 ||
      editIntent.token === lastAppliedEditToken.current
    ) {
      return;
    }
    lastAppliedEditToken.current = editIntent.token;
    const target = editIntent.testType.trim().toUpperCase();
    let match: { group: WorksheetGroup; row: WorksheetRow } | null = null;
    for (const group of worksheet.groups) {
      const row = group.rows.find((candidate) => candidate.test_type.toUpperCase() === target);
      if (row !== undefined) {
        match = { group, row };
        break;
      }
    }
    if (match === null) {
      // Review finding M5: a dead intent must not fetch anything, and the
      // operator should see why the pencil click did nothing.
      setMissingEditIntent(editIntent.testType);
      return;
    }
    setMissingEditIntent(null);
    const key = rowKey(match.group, match.row);
    setEditingKey((current) => {
      if (current !== key) resetStaging();
      return key;
    });
    setRunsRequested(true);
    setFocusToken((value) => value + 1);
    // Deliberately only reacting to `editIntent` itself (mirrors
    // AddTestResult's pinned-intent effect): the token is the only signal a
    // re-click of the same row needs, and `resetStaging`/`editingKey` are
    // read through the functional updater above instead.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editIntent]);

  const editingRowInfo = useMemo(() => {
    if (editingKey === null) return null;
    for (const group of worksheet.groups) {
      for (const row of group.rows) {
        if (rowKey(group, row) === editingKey) return { group, row };
      }
    }
    return null;
  }, [editingKey, worksheet]);
  const editingTestType = editingRowInfo?.row.test_type ?? null;
  const needsRunsForEdit = (editingRowInfo?.row.run_count ?? 0) > 0;

  // Review finding M1: scrolling the row into view can happen immediately,
  // but focusing a control must wait until the strip actually has one — right
  // after opening it, the strip still reads "Loading previous values…".
  useEffect(() => {
    if (focusToken === 0 || editingKey === null) return;
    rowRefs.current[editingKey]?.scrollIntoView?.({ block: "nearest" });
  }, [focusToken, editingKey]);

  const matchedSchema = useMemo(
    () =>
      editingTestType === null
        ? null
        : matchWorksheetSchema(schemas, editingTestType, componentType),
    [schemas, editingTestType, componentType],
  );
  const latestFullRun = useMemo(() => {
    if (editingTestType === null || runs === null) return null;
    // A withdrawn run remains visible in the expanded audit history, but it
    // is no longer valid input for a new measurement. Keep the edit strip on
    // the newest live run, matching the backend worksheet/stage-gate contract.
    const candidates = runs.filter(
      (run) =>
        run.test_type === editingTestType &&
        run.run_state !== WITHDRAWN_TEST_RUN_STATE,
    );
    return candidates.length === 0 ? null : newestFirst(candidates)[0];
  }, [runs, editingTestType]);
  const prefilled = useMemo(
    () =>
      matchedSchema === null ? null : prefilledDefinition(matchedSchema.schema, latestFullRun ?? null),
    [matchedSchema, latestFullRun],
  );
  // Sheet layout + tool registry, fetched only while a strip is open.
  const { layout, tools, loading: profileLoading, toolsError } = useDataEntryProfile({
    instituteCode,
    componentTypeCode,
    enabled: editingKey !== null,
  });
  const plan = useMemo(
    () =>
      matchedSchema === null || prefilled === null || profileLoading
        ? null
        : planFieldLayout(
            prefilled.definition,
            matchedSchema.test_code,
            layout,
            componentTypeCode,
          ),
    [matchedSchema, prefilled, layout, profileLoading, componentTypeCode],
  );
  const effectiveSchema = useMemo<TestTypeSchema | null>(() => {
    if (matchedSchema === null || plan === null) return null;
    return { ...matchedSchema, schema: plan.definition };
  }, [matchedSchema, plan]);
  const manualCapability = useMemo(
    () =>
      effectiveSchema === null ? null : manualEntryCapability(effectiveSchema.schema),
    [effectiveSchema],
  );

  // A tool field's previous value comes from the same prefill pass as every
  // other field — the strip must reopen showing the jig that was actually
  // used, including a value the registry does not know (see ToolFieldSelect).
  const [toolValues, setToolValues] = useState<Record<string, string>>({});
  const [missingToolCodes, setMissingToolCodes] = useState<ReadonlySet<string>>(new Set());
  const prefilledToolValues = useMemo(() => {
    const values: Record<string, string> = {};
    for (const field of plan?.toolFields ?? []) {
      if (typeof field.defaultValue === "string" || typeof field.defaultValue === "number") {
        values[field.code] = String(field.defaultValue);
      }
    }
    return values;
  }, [plan]);
  useEffect(() => {
    setToolValues(prefilledToolValues);
    setMissingToolCodes(new Set());
  }, [editingKey, prefilledToolValues]);
  const prefillDrops = prefilled?.drops ?? [];
  const requiredPrefillDrops = prefillDrops.filter((drop) => drop.required);
  const optionalPrefillDrops = prefillDrops.filter((drop) => !drop.required);
  const canRenderTestForm =
    schemas !== null &&
    effectiveSchema !== null &&
    !(needsRunsForEdit && runs === null) &&
    !(needsRunsForEdit && runsError !== null) &&
    manualCapability?.canEnter === true &&
    requiredPrefillDrops.length === 0;

  useEffect(() => {
    if (focusToken === 0 || focusToken === focusedTokenRef.current || editingKey === null) return;
    if (!canRenderTestForm) return; // strip has no control to focus yet; retry once it does
    const input = stripRefs.current[editingKey]?.querySelector<HTMLElement>(
      "input, select, textarea",
    );
    if (input === null || input === undefined) return;
    focusedTokenRef.current = focusToken;
    input.focus();
  }, [focusToken, editingKey, canRenderTestForm]);

  /** See `AddTestResult.withToolValues` — same contract, same reason. */
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

  async function handleEditSubmit(payload: TestFormSubmitPayload) {
    const testType = editingTestType;
    const key = editingKey;
    if (testType === null || key === null) return;
    const merged = withToolValues(payload);
    if (merged === null) return;
    // Same manual-entry pipeline as the Add-test-result form (spec §C/§H2):
    // the parser pin marks the payload as operator-entered canonical JSON.
    const created = await stagingIngestPayload(
      t.worksheet.manualFilename(merged.testType),
      manualEntryPayload(merged),
      { componentSn, testType, parser: "manual-entry" },
    );
    if (created === null) return;
    const result = await stagingStageUpload(instituteCode === undefined ? {} : { instituteCode });
    if (result === null) return;
    setOptimisticStaged((current) => ({
      ...current,
      [key]: [
        ...(current[key] ?? []),
        { outbox_action_id: result.action.id, status: result.action.status },
      ],
    }));
    closeEdit();
    onStaged?.(result.action.id);
  }

  if (visibleGroups.length === 0) {
    // A component can legitimately have nothing of its own and still have all
    // of its evidence on the children (39 of the owner's 265 modules), so the
    // empty note must not swallow the child section.
    return (
      <div className="module-worksheet">
        <div className="panel">
          <p className="state-note">{t.worksheet.empty}</p>
        </div>
        <ChildEvidence groups={childGroups} />
      </div>
    );
  }

  return (
    <div className="module-worksheet">
      <h3 className="section-title">{t.worksheet.title}</h3>
      {missingEditIntent !== null && (
        <p className="state-note" role="status">
          {t.worksheet.editIntentMissing(missingEditIntent)}
        </p>
      )}
      {visibleGroups.map((group) => (
        <section className="ws-group" key={group.stage ?? "additional"}>
          <div className="panel ws-group-panel">
            <div className={group.reached ? "ws-group-head" : "ws-group-head ws-group-future"}>
              {group.stage === null ? (
                <span className="ws-group-label">{t.worksheet.additionalGroup}</span>
              ) : (
                <span className={stageChipClass(group.stage)} title={group.stage}>
                  {stageLabel(group.stage)}
                </span>
              )}
              {group.stage !== null && !group.reached && (
                <span className="chip muted">{t.worksheet.futureStage}</span>
              )}
            </div>
            <table className="data-table ws-table">
              <thead>
                <tr>
                  <th scope="col">{t.worksheet.colTest}</th>
                  <th scope="col">{t.worksheet.colValues}</th>
                  <th scope="col">{t.worksheet.colStatus}</th>
                  <th scope="col">{t.worksheet.colDate}</th>
                  <th scope="col">
                    <span className="sr-only">{t.worksheet.colActions}</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {group.rows.map((row) => {
                  const key = rowKey(group, row);
                  const detailId = `ws-detail-${sanitizeId(key)}`;
                  const isExpanded = expanded[key] === true;
                  const isEditing = editingKey === key;
                  const staged = mergedStaged(key, row, optimisticStaged);
                  const rowDerived = row.derived ?? null;
                  // The dry-run's own derivation wins while the strip is open;
                  // until the server sends one, the strip falls back to the
                  // last recorded run's and labels it as such. Either way the
                  // browser computes nothing.
                  const previewDerived = stagingPreview?.derived ?? null;
                  const stripDerived: { derived: WorksheetDerived; source: DerivedSource } | null =
                    !isEditing
                      ? null
                      : previewDerived !== null
                        ? { derived: previewDerived, source: "preview" }
                        : rowDerived !== null
                          ? { derived: rowDerived, source: "latest_run" }
                          : null;
                  return (
                    <Fragment key={key}>
                      <tr
                        className="ws-row"
                        ref={(el) => {
                          rowRefs.current[key] = el;
                        }}
                      >
                        <td className="mono">{row.test_type}</td>
                        <td>
                          {/* The judgement first, the readings that produced
                              it below: the operator reads the sheet for the
                              verdict, not for the scale values. Rows the
                              profile configures no derivation for are
                              untouched. */}
                          {rowDerived !== null && <DerivedVerdicts derived={rowDerived} />}
                          <ValuesCell latest={row.latest} />
                        </td>
                        <td>
                          <span className={STATUS_CHIP_CLASS[row.status]}>
                            {statusLabel(row.status)}
                          </span>
                        </td>
                        <td className={row.latest?.measured_at ? undefined : "muted"}>
                          {formatMeasuredAt(row.latest?.measured_at ?? null)}
                        </td>
                        <td>
                          <span className="ws-actions">
                            {row.run_count > 0 && (
                              <button
                                type="button"
                                className="ws-toggle"
                                aria-expanded={isExpanded}
                                aria-controls={detailId}
                                aria-label={
                                  isExpanded
                                    ? t.worksheet.collapseRow(row.test_type)
                                    : t.worksheet.expandRow(row.test_type)
                                }
                                onClick={() => toggleExpand(key)}
                              >
                                <span aria-hidden="true">{isExpanded ? "▾" : "▸"}</span>
                              </button>
                            )}
                            {canWrite && (
                              <button
                                type="button"
                                className="req-edit-ghost"
                                aria-expanded={isEditing}
                                disabled={stagingBusy !== null}
                                title={t.worksheet.editFor(row.test_type)}
                                aria-label={t.worksheet.editFor(row.test_type)}
                                onClick={() => handlePencilClick(key)}
                              >
                                <span aria-hidden="true" className="req-edit-ghost-glyph">
                                  ✎
                                </span>
                              </button>
                            )}
                          </span>
                        </td>
                      </tr>
                      {staged.map((ref) => (
                        <tr className="ws-ghost-row" key={ref.outbox_action_id}>
                          <td colSpan={TABLE_COLUMNS}>
                            <div className="ghost-row">
                              <span className="ghost-summary">
                                {t.worksheet.stagedUpload(ref.outbox_action_id)}
                              </span>
                              <span className={outboxStatusChipClass(ref.status)}>
                                {t.components.previewStatuses[ref.status]}
                              </span>
                              {onViewStaged !== undefined ? (
                                <button
                                  type="button"
                                  className="link-btn mono"
                                  onClick={onViewStaged}
                                >
                                  {t.worksheet.viewInStaged}
                                </button>
                              ) : (
                                <span className="mono muted">{t.worksheet.viewInStaged}</span>
                              )}
                            </div>
                          </td>
                        </tr>
                      ))}
                      {isEditing && (
                        <tr className="ws-edit-row">
                          <td colSpan={TABLE_COLUMNS}>
                            <div
                              className="ws-edit-strip"
                              ref={(el) => {
                                stripRefs.current[key] = el;
                              }}
                              aria-busy={stagingBusy !== null}
                            >
                              <div className="field-label">{t.worksheet.editFor(row.test_type)}</div>
                              {schemas === null || profileLoading ? (
                                <p className="state-note">
                                  {schemas === null ? t.worksheet.schemasLoading : t.common.loading}
                                </p>
                              ) : effectiveSchema === null ? (
                                <p className="state-note">{t.worksheet.noSchema(row.test_type)}</p>
                              ) : needsRunsForEdit && runs === null ? (
                                <p className="state-note">{t.worksheet.loadingPreviousValues}</p>
                              ) : needsRunsForEdit && runsError !== null ? (
                                // Review finding I6: a transient mirror-fetch
                                // failure must not read as "nothing to
                                // prefill" — block the strip and say so.
                                <div className="error-banner" role="alert">
                                  <span>{t.worksheet.previousValuesError(runsError)}</span>
                                  <button
                                    type="button"
                                    className="btn"
                                    onClick={() => setRuns(null)}
                                  >
                                    {t.common.retry}
                                  </button>
                                </div>
                              ) : manualCapability?.canEnter === false ? (
                                <div className="info-banner" role="status">
                                  <span>
                                    {t.worksheet.manualEntryBlocked(
                                      row.test_type,
                                      manualEntryBlockerSummary(manualCapability),
                                    )}
                                  </span>
                                  <button
                                    type="button"
                                    className="btn"
                                    onClick={() => {
                                      closeEdit();
                                      onUseFileUpload(row.test_type);
                                    }}
                                  >
                                    {t.worksheet.useFileUpload}
                                  </button>
                                </div>
                              ) : requiredPrefillDrops.length > 0 ? (
                                // Review finding C1: a required field that
                                // cannot be reproduced in this form must not
                                // become a silent dead end — block the strip
                                // and point at the file-drop path instead.
                                <div className="info-banner" role="status">
                                  <span>
                                    {t.worksheet.prefillBlockedRequired(
                                      requiredPrefillDrops.map((drop) => drop.name).join(", "),
                                    )}
                                  </span>
                                  <button
                                    type="button"
                                    className="btn"
                                    onClick={() => {
                                      closeEdit();
                                      onUseFileUpload(row.test_type);
                                    }}
                                  >
                                    {t.worksheet.useFileUpload}
                                  </button>
                                </div>
                              ) : (
                                <>
                                  {optionalPrefillDrops.length > 0 && (
                                    <div className="info-banner" role="status">
                                      <span>
                                        {t.worksheet.prefillDropped(
                                          optionalPrefillDrops.map((drop) => drop.name).join(", "),
                                        )}
                                      </span>
                                    </div>
                                  )}
                                  {plan !== null && (
                                    <ToolFieldSection
                                      fields={plan.toolFields}
                                      tools={tools}
                                      componentTypeCode={componentTypeCode}
                                      values={toolValues}
                                      onChange={(code, value) => {
                                        setToolValues((current) => ({
                                          ...current,
                                          [code]: value,
                                        }));
                                        setMissingToolCodes((current) => {
                                          if (!current.has(code)) return current;
                                          const next = new Set(current);
                                          next.delete(code);
                                          return next;
                                        });
                                      }}
                                      invalidCodes={missingToolCodes}
                                      labels={t.worksheet.toolField}
                                      title={t.worksheet.toolSectionTitle}
                                      toolsError={toolsError}
                                      disabled={stagingBusy !== null}
                                    />
                                  )}
                                  <TestForm
                                    key={key}
                                    component={componentSn}
                                    schema={effectiveSchema}
                                    labels={t.worksheet.testForm}
                                    disabled={stagingBusy !== null}
                                    variant="worksheet"
                                    cancelLabel={t.worksheet.cancelEdit}
                                    onCancel={closeEdit}
                                    onSubmit={handleEditSubmit}
                                  />
                                </>
                              )}
                              {stripDerived !== null && (
                                // Below the raw scale readings: what the
                                // server made of them. Read-only on purpose —
                                // the formula exists once, on the server.
                                <DerivedDetail
                                  derived={stripDerived.derived}
                                  source={stripDerived.source}
                                />
                              )}
                              {stagingEntryError !== null && (
                                <p className="error-text" role="alert">
                                  {stagingEntryError}
                                </p>
                              )}
                              {stagingPreview !== null && stagingPreview.issues.length > 0 && (
                                <div>
                                  <div className="field-label">{t.worksheet.issuesTitle}</div>
                                  <ul className="preview-list error-text">
                                    {stagingPreview.issues.map((issue) => (
                                      <li key={issue}>{issue}</li>
                                    ))}
                                  </ul>
                                </div>
                              )}
                              {stagingPreview !== null &&
                                !stagingPreview.upload_ready &&
                                stagingPreview.issues.length === 0 && (
                                  // Review finding I5: `upload_ready=false`
                                  // with no issues is a legitimate server
                                  // response; without this the strip fell
                                  // silent and "Stage" looked like a no-op.
                                  <p className="error-text" role="alert">
                                    {t.worksheet.previewBlocked}
                                  </p>
                                )}
                              {stagingPreview !== null && stagingPreview.warnings.length > 0 && (
                                <div>
                                  <div className="field-label">{t.worksheet.warningsTitle}</div>
                                  <ul className="preview-list muted">
                                    {stagingPreview.warnings.map((warning) => (
                                      <li key={warning}>{warning}</li>
                                    ))}
                                  </ul>
                                </div>
                              )}
                              {stagingPreviewError !== null && (
                                <p className="error-text" role="alert">
                                  {stagingPreviewError}
                                </p>
                              )}
                              {stagingStageError !== null && (
                                <p className="error-text" role="alert">
                                  {stagingStageError}
                                </p>
                              )}
                            </div>
                          </td>
                        </tr>
                      )}
                      {isExpanded && (
                        <tr className="ws-detail-row" id={detailId}>
                          <td colSpan={TABLE_COLUMNS}>
                            <RunDetailContent
                              sn={componentSn}
                              testType={row.test_type}
                              runs={runs}
                              runsError={runsError}
                              onRetry={() => setRuns(null)}
                              onOpenImage={setLightbox}
                            />
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      ))}
      <ChildEvidence groups={childGroups} />
      {lightbox !== null && (
        <ImageLightbox sn={componentSn} attachment={lightbox} onClose={() => setLightbox(null)} />
      )}
    </div>
  );
}
