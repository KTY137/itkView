// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
// SPDX-FileComment: itkflow-cf8c8aa94f06
/**
 * Realistically shaped payloads for the module-worksheet integration suite
 * (`screens/ComponentsScreen.worksheetIntegration.test.tsx`).
 *
 * Shapes are taken from what the backend actually emits — `app/preview.py`
 * (`_worksheet_latest_run`, `_build_worksheet`) and the values used in
 * `backend/tests/test_preview_worksheet.py`:
 *
 *  - the worksheet payload carries ONLY scalars plus array/map *counts*; raw
 *    lists and dicts never leave the server (spec §H1),
 *  - a real MODULE_METROLOGY run carries dict-valued results keyed per
 *    position (`{"ABC_R5H1_0": 2.1, …}`), which the worksheet summarises as
 *    `kind: "map"`,
 *  - `GET /api/components/{sn}/tests` (the mirrored-runs fetch) is where the
 *    raw arrays and dicts live, and it is the only place they may appear.
 *
 * Every person-like value is anonymised per CLAUDE.md rule 3.
 */
import type {
  ComponentDetail,
  ComponentPreview,
  ComponentPreviewAction,
  IngestFile,
  IngestPreview,
  MeOut,
  OutboxAction,
  StageSuggestion,
  TestRunAttachment,
  TestRunDetail,
  TestTypeSchema,
  WorksheetLatestRun,
} from "../api";

export const MODULE_SN = "20USEM00000001";
export const INSTITUTE_CODE = "EXAMPLE";

export const operatorMe: MeOut = {
  id: 4,
  email: "anna.abel@example.org",
  display_name: "Anna Abel",
  role: "operator",
  institute_id: 1,
  institute_code: INSTITUTE_CODE,
  csrf_token: "csrf-token-for-tests",
};

export const moduleDetail: ComponentDetail = {
  sn: MODULE_SN,
  local_name: "EXA-M-014",
  component_type: "MODULE",
  // Deliberately different from `component_type`: a caller that hands the
  // worksheet the encoded PDB type code instead of the component type would
  // never match a mirrored schema again.
  type_code: "R5M0",
  stage: "GLUED",
  location: INSTITUTE_CODE,
  institute_code: INSTITUTE_CODE,
  parent_sn: null,
  is_dummy: true,
  trashed: false,
  stale: false,
  synced_at: "2026-08-26T08:00:00Z",
  children: [],
};

// ---- Raw measured data (only ever served by getComponentTests) --------------

/** Bias sweep, four points; the worksheet may only ever show "⌁ 4 pts". */
export const IV_VOLTAGES = [0, -100, -300, -500];
export const IV_CURRENTS = [0.0821, 0.2145, 0.4372, 1.0518];

/** Per-position metrology dict, exactly the shape the PDB returns. */
export const METROLOGY_THICKNESS: Record<string, number> = {
  ABC_R5H1_0: 2.1064,
  ABC_R5H1_1: 2.4183,
  ABC_R5H1_2: 1.9077,
};

const ivAttachment: TestRunAttachment = {
  source: "pdb",
  code: "att-iv-3",
  test_type: "MODULE_IV_PS_V1",
  test_run_ref: "RUN-IV-3",
  filename: "iv-sweep.png",
  content_type: "image/png",
  title: "IV sweep plot",
  size_bytes: 20_480,
  stored: true,
  is_image: true,
};

export const ivRun: TestRunDetail = {
  test_type: "MODULE_IV_PS_V1",
  passed: true,
  external_ref: "RUN-IV-3",
  measured_at: "2026-08-24T09:12:00Z",
  run_number: "3",
  run_state: null,
  results: {
    VOLTAGE: IV_VOLTAGES,
    CURRENT: IV_CURRENTS,
    HUMIDITY: 31.4,
    TEMPERATURE: 21.5,
    COMMENT: "stable",
    N_CYCLES: 3,
    SETUP_ID: "IV-BOX-2",
  },
  result_meta: {
    VOLTAGE: { name: "Bias voltage [V]", value_type: "array" },
    CURRENT: { name: "Leakage current [uA]", value_type: "array" },
    HUMIDITY: { name: "Humidity [%]" },
    TEMPERATURE: { name: "Temperature [C]" },
    COMMENT: { name: "Comment" },
    N_CYCLES: { name: "Cycles" },
    SETUP_ID: { name: "Setup id" },
  },
  properties: { JIG: "JIG-07", OPERATOR: "Anna Abel" },
  attachments: [ivAttachment],
};

export const metrologyRun: TestRunDetail = {
  test_type: "MODULE_METROLOGY",
  passed: true,
  external_ref: "RUN-METRO-1",
  measured_at: "2026-08-25T14:05:00Z",
  run_number: "1",
  run_state: null,
  results: {
    "Hybrid glue thickness [um]": METROLOGY_THICKNESS,
    "Capacitor heights [um]": {},
    "Sensor bow [um]": 24.6,
  },
  result_meta: {
    "Hybrid glue thickness [um]": { name: "Hybrid glue thickness [um]" },
    "Capacitor heights [um]": { name: "Capacitor heights [um]" },
    "Sensor bow [um]": { name: "Sensor bow [um]" },
  },
  properties: {},
  attachments: [],
};

export const mirroredRuns: TestRunDetail[] = [ivRun, metrologyRun];

// ---- Worksheet projection of exactly those runs ------------------------------

const ivLatest: WorksheetLatestRun = {
  external_ref: "RUN-IV-3",
  measured_at: "2026-08-24T09:12:00Z",
  run_number: "3",
  passed: true,
  // Server order: filled scalars first, insertion order preserved.
  scalars: [
    { code: "HUMIDITY", name: "Humidity [%]", value: 31.4 },
    { code: "TEMPERATURE", name: "Temperature [C]", value: 21.5 },
    { code: "COMMENT", name: "Comment", value: "stable" },
    { code: "N_CYCLES", name: "Cycles", value: 3 },
    { code: "SETUP_ID", name: "Setup id", value: "IV-BOX-2" },
  ],
  arrays: [
    { code: "VOLTAGE", name: "Bias voltage [V]", points: IV_VOLTAGES.length, kind: "array" },
    { code: "CURRENT", name: "Leakage current [uA]", points: IV_CURRENTS.length, kind: "array" },
  ],
  attachment_count: 1,
};

const metrologyLatest: WorksheetLatestRun = {
  external_ref: "RUN-METRO-1",
  measured_at: "2026-08-25T14:05:00Z",
  run_number: "1",
  passed: true,
  scalars: [{ code: "Sensor bow [um]", name: "Sensor bow [um]", value: 24.6 }],
  arrays: [
    {
      code: "Hybrid glue thickness [um]",
      name: "Hybrid glue thickness [um]",
      points: Object.keys(METROLOGY_THICKNESS).length,
      kind: "map",
    },
    { code: "Capacitor heights [um]", name: "Capacitor heights [um]", points: 0, kind: "map" },
  ],
  attachment_count: 0,
};

/** One group per stage of the seed model, future stages included (spec §H1). */
export function worksheetPayload(
  stagedByRow: Record<string, Array<{ outbox_action_id: number; status: OutboxAction["status"] }>> = {},
): ComponentPreview["worksheet"] {
  const staged = (testType: string) => stagedByRow[testType] ?? [];
  return {
    groups: [
      {
        stage: "HV_TAB_ATTACHED",
        reached: true,
        rows: [
          {
            test_type: "VISUAL_INSPECTION",
            status: "passed",
            latest: {
              external_ref: "RUN-VI-1",
              measured_at: "2026-08-23T08:30:00Z",
              run_number: "1",
              passed: true,
              scalars: [{ code: "VI_RESULT", name: "Visual inspection result", value: "pass" }],
              arrays: [],
              attachment_count: 0,
            },
            staged: staged("VISUAL_INSPECTION"),
            run_count: 1,
          },
          {
            test_type: "MODULE_IV_PS_V1",
            status: "passed",
            latest: ivLatest,
            staged: staged("MODULE_IV_PS_V1"),
            run_count: 3,
          },
        ],
      },
      {
        stage: "GLUED",
        reached: true,
        rows: [
          {
            test_type: "GLUE_WEIGHT",
            status: "missing",
            latest: null,
            staged: staged("GLUE_WEIGHT"),
            run_count: 0,
          },
          {
            test_type: "MODULE_METROLOGY",
            status: "passed",
            latest: metrologyLatest,
            staged: staged("MODULE_METROLOGY"),
            run_count: 1,
          },
        ],
      },
      // Required-test-free stage: the worksheet must not render an empty table.
      { stage: "STITCH_BONDING", reached: true, rows: [] },
      {
        stage: "TESTED",
        reached: false,
        rows: [
          {
            test_type: "MODULE_IV_AMAC_TC",
            status: "missing",
            latest: null,
            staged: staged("MODULE_IV_AMAC_TC"),
            run_count: 0,
          },
        ],
      },
      {
        // "Additional": mirrored test types outside the stage model.
        stage: null,
        reached: true,
        rows: [
          {
            test_type: "MODULE_IV_AMAC",
            status: "pending",
            latest: null,
            staged: staged("MODULE_IV_AMAC"),
            run_count: 28,
          },
        ],
      },
    ],
  };
}

export function previewPayload(
  options: {
    stagedByRow?: Record<
      string,
      Array<{ outbox_action_id: number; status: OutboxAction["status"] }>
    >;
    stagedActions?: ComponentPreviewAction[];
  } = {},
): ComponentPreview {
  return {
    current: { stage: "GLUED", checks: [] },
    staged_actions: options.stagedActions ?? [],
    projected: { stage: "GLUED", checks: [], ghost_tests: [] },
    worksheet: worksheetPayload(options.stagedByRow ?? {}),
  };
}

export const stageSuggestion: StageSuggestion = {
  sn: MODULE_SN,
  current_stage: "GLUED",
  next_stage: "STITCH_BONDING",
  move_suggested: false,
  suggested_stage: null,
  checks: [
    { stage: "HV_TAB_ATTACHED", test_type: "VISUAL_INSPECTION", status: "passed" },
    { stage: "GLUED", test_type: "GLUE_WEIGHT", status: "missing" },
  ],
  blocking: [{ stage: "GLUED", test_type: "GLUE_WEIGHT", status: "missing" }],
};

// ---- Mirrored test-type schemas ---------------------------------------------
//
// The nested PDB JSON deliberately carries NO `code`/`testType` of its own —
// the mirror tolerates both being null (`app/pdb_test_types.py`), so the only
// reliable identity is the row's own `test_code` + `component_type`.

export const ivSchema: TestTypeSchema = {
  id: 21,
  component_type: "MODULE",
  test_code: "MODULE_IV_PS_V1",
  name: "Module IV (power supply)",
  synced_at: "2026-08-26T07:00:00Z",
  schema: {
    properties: [{ code: "JIG", name: "Assembly jig", dataType: "string" }],
    results: [
      { code: "VOLTAGE", name: "Bias voltage [V]", dataType: "float", valueType: "array" },
      { code: "CURRENT", name: "Leakage current [uA]", dataType: "float", valueType: "array" },
      { code: "HUMIDITY", name: "Humidity [%]", dataType: "float" },
    ],
  },
};

export const glueWeightSchema: TestTypeSchema = {
  id: 22,
  component_type: "MODULE",
  test_code: "GLUE_WEIGHT",
  name: "Glue weight",
  synced_at: "2026-08-26T07:00:00Z",
  schema: {
    results: [
      { code: "GW_GLUE_H1", name: "Weight of glue under hybrid 1 [g]", dataType: "float" },
    ],
  },
};

export const testTypeSchemas: TestTypeSchema[] = [ivSchema, glueWeightSchema];

// ---- Staging pipeline responses ---------------------------------------------

export const ingestFile: IngestFile = {
  id: 71,
  filename: "MODULE_IV_PS_V1-manual.json",
  sha256: "b".repeat(64),
  size_bytes: 412,
  status: "processed",
  component_sn: MODULE_SN,
  test_type: "MODULE_IV_PS_V1",
  parser: "manual-entry",
  error: null,
  outbox_action_id: null,
  uploaded_by: "anna.abel@example.org",
  created_at: "2026-08-26T10:00:00Z",
  updated_at: "2026-08-26T10:00:00Z",
};

export const cleanDryRun: IngestPreview = {
  file_id: ingestFile.id,
  parser: "manual-entry",
  upload_ready: true,
  component_sn: MODULE_SN,
  local_name: moduleDetail.local_name,
  component_mirrored: true,
  component_stage: "GLUED",
  institute_code: INSTITUTE_CODE,
  test_type: "MODULE_IV_PS_V1",
  run_number: "4",
  institution: INSTITUTE_CODE,
  measured_at: "2026-08-26T09:55:00Z",
  passed: true,
  problems: false,
  n_properties: 1,
  results: [
    { name: "VOLTAGE", kind: "array", value: "4 points" },
    { name: "CURRENT", kind: "array", value: "4 points" },
    { name: "HUMIDITY", kind: "scalar", value: "31.4" },
  ],
  issues: [],
  warnings: [],
};

/** The real message `app/ingestion.py` emits for a truncated IV instrument file. */
export const IV_LENGTH_ISSUE =
  "IV curve arrays differ in length: VOLTAGE has 4, CURRENT has 3 points";

export const blockedDryRun: IngestPreview = {
  ...cleanDryRun,
  upload_ready: false,
  issues: [IV_LENGTH_ISSUE],
};

export const stagedAction: OutboxAction = {
  id: 92,
  institute_id: 1,
  kind: "upload_test_run",
  payload: { ingest_file_id: ingestFile.id, component_sn: MODULE_SN },
  status: "draft",
  error: null,
  attempts: 0,
  external_ref: null,
  created_by: "anna.abel@example.org",
  created_at: "2026-08-26T10:01:00Z",
  updated_at: "2026-08-26T10:01:00Z",
};

export const stagedActionMetadata: ComponentPreviewAction = {
  id: stagedAction.id,
  kind: "upload_test_run",
  status: "draft",
  summary: "Upload MODULE_IV_PS_V1",
  to_stage: null,
  test_type: "MODULE_IV_PS_V1",
  created_by: "anna.abel@example.org",
  created_at: "2026-08-26T10:01:00Z",
  submittable: true,
  submittable_reason: null,
};
