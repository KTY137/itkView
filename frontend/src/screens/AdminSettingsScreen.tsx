// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
// SPDX-FileComment: itkflow-9950233ec3a9
import { useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { getMeasurementDimensions, getStatsDimensions, getTestTypeSchemas } from "../api";
import type { Institute } from "../api";

const MASKED_SECRET = "***";
const MAX_GLUE_POT_LIFE_MINUTES = 1_440;
const STAGE_NAME_PATTERN = /^[A-Z][A-Z0-9_]{0,63}$/u;
const TEST_TYPE_PATTERN = /^[A-Z][A-Z0-9_]{0,63}$/u;
const TEST_TYPE_LIST_ID = "admin-stage-test-types";
/** A PDB result code, e.g. the code a scale reading is stored under. */
const RESULT_CODE_PATTERN = /^[A-Z][A-Z0-9_]{0,63}$/u;
/** A derivation step key (plan §9.2/§9.3) — profile-defined, case as typed. */
const GLUE_STEP_KEY_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$/u;
const GLUE_PROCESS_PATTERN = /^[A-Z][A-Z0-9_]{0,31}$/u;
const GLUE_TYPE_CODE_PATTERN = /^[A-Z][A-Z0-9_]{0,31}$/u;
const ISO_DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/u;
const GLUE_STEP_LIST_ID = "admin-glue-step-keys";
/** A glue target/tolerance in mg; generous, but rules out a stray gram value. */
const MAX_GLUE_TARGET_MG = 100_000;
/** Guard against a pathological mirror; a real profile has a handful of types. */
const MAX_SCHEMA_COMPONENT_TYPES = 8;

/**
 * The unattended sync schedule (`auto_sync`, backend/app/auto_sync.py). The
 * floor mirrors MIN_INTERVAL_MINUTES there: the backend refuses anything
 * below it instead of quietly speeding a profile up, so the editor has to
 * refuse it too rather than send a number that would come back rejected.
 */
const AUTO_SYNC_MIN_INTERVAL_MINUTES = 15;
const AUTO_SYNC_MAX_INTERVAL_MINUTES = 7 * 24 * 60;
/** What an institute that never configured a schedule shows before it is on. */
const AUTO_SYNC_DEFAULT_INTERVAL_MINUTES = 60;
/** ISO weekdays, 1 = Monday through 7 = Sunday; all seven means every day. */
const ISO_WEEKDAYS: readonly number[] = [1, 2, 3, 4, 5, 6, 7];
const HHMM_PATTERN = /^(?:[01]\d|2[0-3]):[0-5]\d$/u;

// Mirror of the institute-agnostic seed model in
// `backend/app/domain/stages.py` (DEFAULT_STAGE_ORDER /
// DEFAULT_STAGE_REQUIREMENTS). It is *not* institute configuration — an
// institute's own values always live in its profile — but the editor cannot
// show what a profile without an override currently evaluates against without
// knowing the seed, and no endpoint exposes the merged model. Keep in sync
// with the backend seed; anything institute-specific belongs in the profile.
const SEED_STAGE_ORDER: readonly string[] = [
  "HV_TAB_ATTACHED",
  "GLUED",
  "STITCH_BONDING",
  "BONDED",
  "TESTED",
  "FINISHED",
];

const SEED_STAGE_REQUIREMENTS: Readonly<Record<string, readonly string[]>> = {
  HV_TAB_ATTACHED: ["VISUAL_INSPECTION", "MODULE_IV_PS_V1"],
  GLUED: ["GLUE_WEIGHT", "MODULE_BOW", "MODULE_METROLOGY"],
  STITCH_BONDING: [],
  BONDED: ["MODULE_WIRE_BONDING"],
  TESTED: ["MODULE_IV_AMAC_TC"],
  FINISHED: [],
};

let nextRowId = 0;

function rowId(prefix: string): string {
  nextRowId += 1;
  return `${prefix}-${nextRowId}`;
}

type NotificationChannelKind = "mattermost" | "telegram" | "webhook" | "email";

type ChannelDraft = {
  key: string;
  originalName: string | null;
  originalKind: NotificationChannelKind | null;
  originalSmtpHost: string | null;
  originalSmtpPort: string | null;
  originalSmtpSecurity: "ssl" | "starttls" | null;
  originalSmtpUsername: string | null;
  name: string;
  kind: NotificationChannelKind;
  url: string;
  hasStoredSecret: boolean;
  channel: string;
  chatId: string;
  smtpHost: string;
  smtpPort: string;
  smtpSecurity: "ssl" | "starttls";
  smtpUsername: string;
  smtpPassword: string;
  hasStoredSmtpPassword: boolean;
  fromAddress: string;
  toAddress: string;
};

type TextRow = {
  key: string;
  value: string;
};

type GluePotLifeRow = {
  key: string;
  glueType: string;
  minutes: string;
};

type ReceptionTestRow = {
  key: string;
  componentType: string;
  testType: string;
};

/**
 * One derivation step of the glue-weight formula, expressed as data
 * (plan §9.2): "which measurement, minus which measurements, stored under
 * which result code". Which PDB codes those are is institute and schema
 * business, never code — the editor only knows the shape.
 */
type GlueInputRow = {
  key: string;
  /** Profile-defined step key; the glue targets below refer to it. */
  stepKey: string;
  /** What the operator reads as the step's name in the worksheet verdict. */
  label: string;
  /** Which test type carries this step's readings; blank = the profile default. */
  testType: string;
  measured: string;
  subtract: TextRow[];
  /** Optional: without it the step is judged but never uploaded. */
  resultCode: string;
  /** Exact component-type formula overrides; retained without a raw-JSON editor. */
  byTypeCode: Record<string, GlueWeightInputOverride>;
};

/** One target/tolerance cell: module type × step, inside one rule set. */
type GlueTargetCellRow = {
  key: string;
  moduleType: string;
  stepKey: string;
  targetMg: string;
  toleranceMg: string;
};

/**
 * One glue-target rule set (plan §9.1). `validFrom` is what makes historical
 * runs judgeable: the live production sheet really does run two generations
 * of the same rule side by side, and a profile that knows only one set of
 * constants misjudges every run recorded under the other.
 */
type GlueRuleSetRow = {
  key: string;
  process: string;
  label: string;
  /** ISO date, or "" for the always-valid fallback (`valid_from: null`). */
  validFrom: string;
  targets: GlueTargetCellRow[];
};

type StageRow = {
  key: string;
  name: string;
  /** The stage exists in the seed model, so the engine always evaluates it. */
  fromSeed: boolean;
  /** Loaded from a `stage_requirements` entry the saved order did not list. */
  appended: boolean;
  tests: TextRow[];
};

type SettingsDraft = {
  name: string;
  localNamePrefix: string;
  logoUrl: string;
  pdbProject: string;
  stages: StageRow[];
  /**
   * Explicit owner approval for using this institute's stage model in
   * production-status decisions. Any edit to the stage order or requirements
   * clears it; only the separate checkbox below may set it again.
   */
  stagePolicyApproved: boolean;
  channels: ChannelDraft[];
  receptionChecklist: TextRow[];
  receptionTests: ReceptionTestRow[];
  gluePotLife: GluePotLifeRow[];
  glueInputs: GlueInputRow[];
  glueRuleSets: GlueRuleSetRow[];
  glueDefaultProcess: string;
  glueProcessProperty: string;
  /**
   * Whether the loaded profile already carried the key. An institute that has
   * never configured a glue derivation must not have one silently written as
   * "explicitly empty" by an unrelated save — that would switch the judgement
   * off for every module without anybody asking for it.
   */
  hadGlueInputs: boolean;
  hadGlueTargets: boolean;
  hadGlueDefaultProcess: boolean;
  hadGlueProcessProperty: boolean;
  evidenceComponentTypes: TextRow[];
  autoSyncEnabled: boolean;
  autoSyncIntervalMinutes: string;
  autoSyncWindowStart: string;
  autoSyncWindowEnd: string;
  /** ISO weekdays the window may open on; all seven means every day. */
  autoSyncWeekdays: number[];
  /** Stored block exists but the backend scheduler must read it as off. */
  autoSyncMalformed: boolean;
  /**
   * Whether the loaded profile already carried `auto_sync`. An institute that
   * never configured a schedule must not have one written by an unrelated
   * save — not even a disabled one, which would record a decision nobody made.
   */
  hadAutoSync: boolean;
  escalationAfterMinutes: string;
  escalationChannel: string;
};

export type AdminOperationalSettings = {
  logo_url: string;
  pdb_project: string;
  notification_channels: Record<
    string,
    {
      kind: NotificationChannelKind;
      url?: string;
      channel?: string;
      chat_id?: string;
      smtp_host?: string;
      smtp_port?: number;
      smtp_security?: "ssl" | "starttls";
      smtp_username?: string;
      smtp_password?: string;
      from_address?: string;
      to_address?: string;
    }
  >;
  shipment_reception_checklist: string[];
  shipment_reception_tests: Record<string, string[]>;
  glue_pot_life_minutes: Record<string, number>;
  /**
   * The glue-weight formula as data (plan §9.2), keyed by derivation step:
   * `measured − Σ subtract`, stored under `result_code`. Omitted entirely
   * while the institute has never configured one, so an unrelated save never
   * turns "not configured" into "explicitly none"; `null` when the admin
   * empties a configured one, which disables input-based derivation. An empty
   * object is rejected there on purpose.
   */
  glue_weight_inputs?: Record<string, GlueWeightInputMapping> | null;
  /**
   * Glue targets per process × module type × step, with a validity date
   * (plan §9.1). A list, not a map: several generations of the same process
   * coexist and the run's measurement date picks the rule set. Same
   * omitted / `null` contract as above.
   */
  glue_targets?: GlueTargetRuleSet[] | null;
  /** Explicit fallback when a run does not carry a process property. */
  glue_default_process?: string | null;
  /** Optional PDB property/result code that identifies the process per run. */
  glue_process_property?: string | null;
  evidence_component_types: string[];
  /**
   * The unattended sync schedule. Omitted while the institute has never
   * configured one, so an unrelated save can never switch on the only thing
   * in itkFlow that contacts the PDB without a person asking for it; `null`
   * clears a configured one back to off.
   */
  auto_sync?: AutoSyncSchedule | null;
  reminder_escalation: { after_minutes: number; channel: string } | null;
  /** Complete ordered stage list; written together with `stage_requirements`. */
  stage_order: string[];
  /** One entry per listed stage, so the saved profile is fully explicit. */
  stage_requirements: Record<string, string[]>;
  /** Explicit admin acknowledgement of the exact order and requirements. */
  stage_policy_approved: boolean;
};

export type GlueWeightInputMapping = {
  measured: string;
  subtract: string[];
  /** Absent when the step is judged locally but never uploaded. */
  result_code?: string;
  label?: string;
  test_type?: string;
  by_type_code?: Record<string, GlueWeightInputOverride>;
};

export type GlueWeightInputOverride = {
  measured: string;
  subtract: string[];
  /** Absent inherits the base output code; null explicitly disables it. */
  result_code?: string | null;
};

export type GlueTargetRuleSet = {
  process: string;
  label: string;
  /** null = always valid; the fallback when no dated rule set matches. */
  valid_from: string | null;
  module_types: Record<string, Record<string, { target_mg: number; tolerance_mg: number }>>;
};

/**
 * The schedule an unattended refresh follows, exactly as the backend stores
 * it. `window_start`/`window_end` are wall-clock times in the server's own
 * local time and may cross midnight (22:00–06:00 is an overnight window);
 * `weekdays` are ISO numbers, and `null` means every day.
 */
export type AutoSyncSchedule = {
  enabled: boolean;
  interval_minutes: number;
  window_start: string | null;
  window_end: string | null;
  weekdays: number[] | null;
};

export type AdminSettingsUpdate = {
  name: string;
  local_name_prefix: string;
  settings: AdminOperationalSettings;
};

export type AdminSettingsLabels = {
  title: string;
  subtitle: string;
  instituteLabel: string;
  noInstitute: string;
  generalTitle: string;
  generalHint: string;
  nameLabel: string;
  localNamePrefixLabel: string;
  logoUrlLabel: string;
  logoUrlPlaceholder: string;
  pdbProjectLabel: string;
  pdbProjectPlaceholder: string;
  notificationsTitle: string;
  notificationsHint: string;
  notificationsEmpty: string;
  addChannel: string;
  channelRowLabel: (index: number) => string;
  channelNameLabel: string;
  channelNamePlaceholder: string;
  channelKindLabel: string;
  channelKindMattermost: string;
  channelKindWebhook: string;
  channelKindTelegram: string;
  channelKindEmail: string;
  channelUrlLabel: string;
  channelUrlPlaceholder: string;
  channelStoredSecretHint: string;
  mattermostChannelLabel: string;
  mattermostChannelPlaceholder: string;
  telegramChatIdLabel: string;
  telegramChatIdPlaceholder: string;
  smtpHostLabel: string;
  smtpPortLabel: string;
  smtpSecurityLabel: string;
  smtpSecuritySsl: string;
  smtpSecurityStarttls: string;
  smtpUsernameLabel: string;
  smtpPasswordLabel: string;
  smtpFromLabel: string;
  smtpToLabel: string;
  escalationTitle: string;
  escalationHint: string;
  escalationAfterLabel: string;
  escalationChannelLabel: string;
  escalationDisabled: string;
  testChannel: string;
  testingChannel: string;
  shipmentsTitle: string;
  shipmentsHint: string;
  shipmentsEmpty: string;
  addChecklistItem: string;
  checklistItemLabel: (index: number) => string;
  checklistItemPlaceholder: string;
  receptionTestsTitle: string;
  receptionTestsHint: string;
  receptionTestsEmpty: string;
  addReceptionTest: string;
  receptionTestRowLabel: (index: number) => string;
  receptionComponentTypeLabel: string;
  receptionComponentTypePlaceholder: string;
  receptionTestTypeLabel: string;
  receptionTestTypePlaceholder: string;
  stagesTitle: string;
  stagesHint: string;
  stagesImpact: string;
  stagesDirtyWarning: string;
  stagePolicyApprovedLabel: string;
  stagePolicyApprovedHint: string;
  stagePolicyUnapprovedLabel: string;
  stagePolicyUnapprovedWarning: string;
  addStage: string;
  stageRowLabel: (index: number) => string;
  stageNameLabel: string;
  stageNamePlaceholder: string;
  stageOriginSeed: string;
  stageOriginCustom: string;
  stageOriginAppended: string;
  stageSeedLockedHint: string;
  stageMoveUp: string;
  stageMoveDown: string;
  stageRemove: string;
  stageTestsLabel: string;
  stageTestsEmpty: string;
  addStageTest: string;
  stageTestLabel: (index: number) => string;
  stageTestPlaceholder: string;
  stageRemoveTest: (index: number) => string;
  stageTestUnknown: string;
  stageTestUnknownHint: string;
  glueTitle: string;
  glueHint: string;
  glueEmpty: string;
  addGlueType: string;
  glueRowLabel: (index: number) => string;
  glueTypeLabel: string;
  glueTypePlaceholder: string;
  potLifeLabel: string;
  minutesUnit: string;
  glueInputsTitle: string;
  glueInputsHint: string;
  glueInputsImpact: string;
  glueInputsEmpty: string;
  addGlueInput: string;
  glueInputRowLabel: (index: number) => string;
  glueStepKeyLabel: string;
  glueStepKeyPlaceholder: string;
  glueStepLabelLabel: string;
  glueStepLabelPlaceholder: string;
  glueStepTestTypeLabel: string;
  glueStepTestTypePlaceholder: string;
  glueMeasuredLabel: string;
  glueMeasuredPlaceholder: string;
  glueSubtractLabel: string;
  glueSubtractEmpty: string;
  addGlueSubtract: string;
  glueSubtractItemLabel: (index: number) => string;
  glueSubtractPlaceholder: string;
  removeGlueSubtract: (index: number) => string;
  glueResultCodeLabel: string;
  glueResultCodePlaceholder: string;
  /** `result` is "" when the step is judged locally but never uploaded. */
  glueFormulaPreview: (measured: string, subtract: string[], result: string) => string;
  glueFormulaIncomplete: string;
  glueTargetsTitle: string;
  glueTargetsHint: string;
  glueTargetsImpact: string;
  glueTargetsEmpty: string;
  glueJudgementDirtyWarning: string;
  glueProcessResolutionTitle: string;
  glueProcessResolutionHint: string;
  glueDefaultProcessLabel: string;
  glueDefaultProcessUnset: string;
  glueDefaultProcessMissing: string;
  glueProcessPropertyLabel: string;
  glueProcessPropertyPlaceholder: string;
  addGlueRuleSet: string;
  glueRuleSetRowLabel: (index: number) => string;
  glueProcessLabel: string;
  glueProcessPlaceholder: string;
  glueProcessDisplayLabel: string;
  glueProcessDisplayPlaceholder: string;
  glueValidFromLabel: string;
  glueValidFromAlways: string;
  removeGlueRuleSet: string;
  glueTargetRowsLabel: string;
  glueTargetRowsEmpty: string;
  addGlueTargetRow: string;
  glueTargetRowLabel: (index: number) => string;
  glueModuleTypeLabel: string;
  glueModuleTypePlaceholder: string;
  glueTargetMgLabel: string;
  glueToleranceMgLabel: string;
  milligramsUnit: string;
  removeGlueTargetRow: (index: number) => string;
  glueStepUnknown: string;
  glueStepUnknownHint: string;
  glueNumberRequired: (fieldLabel: string, maximum: number) => string;
  glueDateRequired: (fieldLabel: string) => string;
  evidenceTitle: string;
  evidenceHint: string;
  evidenceEmpty: string;
  addEvidenceType: string;
  evidenceTypeLabel: (index: number) => string;
  evidenceTypePlaceholder: string;
  autoSyncTitle: string;
  autoSyncHint: string;
  autoSyncIdentityHint: string;
  autoSyncIdentityDetail: string;
  autoSyncClockHint: string;
  autoSyncEnabledLabel: string;
  autoSyncEnabledNote: string;
  autoSyncDisabledNote: string;
  autoSyncIntervalLabel: string;
  autoSyncIntervalHint: string;
  autoSyncWindowStartLabel: string;
  autoSyncWindowEndLabel: string;
  autoSyncWindowAnyTime: string;
  autoSyncWindowDaytime: (start: string, end: string) => string;
  autoSyncWindowOvernight: (start: string, end: string) => string;
  autoSyncWeekdaysLabel: string;
  autoSyncWeekdaysHint: string;
  autoSyncWeekdayName: (isoWeekday: number) => string;
  autoSyncWeekdayShortName: (isoWeekday: number) => string;
  autoSyncDirtyWarning: string;
  autoSyncWindowPairRequired: string;
  autoSyncWindowFormat: string;
  autoSyncWindowIdentical: string;
  autoSyncWeekdaysRequired: string;
  autoSyncMalformedWarning: string;
  remove: string;
  reset: string;
  save: string;
  saving: string;
  saveSucceeded: (instituteCode: string) => string;
  saveFailed: (message: string) => string;
  testSucceeded: (channelName: string) => string;
  testFailed: (message: string) => string;
  unknownError: string;
  required: (fieldLabel: string) => string;
  tooLong: (fieldLabel: string, maxLength: number) => string;
  duplicate: (fieldLabel: string, value: string) => string;
  safeImageUrlRequired: (fieldLabel: string) => string;
  httpsUrlRequired: (fieldLabel: string) => string;
  integerRangeRequired: (fieldLabel: string, minimum: number, maximum: number) => string;
};

export type AdminSettingsScreenProps = {
  institutes: Institute[];
  selectedCode: string;
  onSelectedCodeChange: (instituteCode: string) => void;
  onSave: (
    instituteCode: string,
    update: AdminSettingsUpdate,
  ) => Promise<Institute | void>;
  onTestChannel?: (instituteCode: string, channelName: string) => Promise<void>;
  /**
   * Test types the local mirror already knows, offered as suggestions for a
   * stage requirement. Injectable so tests stay offline; production uses the
   * mirrored schemas plus the evidence that has actually been recorded.
   */
  loadKnownTestTypes?: (signal?: AbortSignal) => Promise<string[]>;
  labels: AdminSettingsLabels;
};

function normalizedTestType(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const cleaned = value.trim().toUpperCase();
  return cleaned === "" ? null : cleaned;
}

/**
 * Collect the test types the frontend can already reach: the locally mirrored
 * PDB test-type schemas (per component type present in the stage history) and
 * every test type that appears in mirrored measurement evidence. Both are
 * discovery sources, never a whitelist — a stage may require a test nobody has
 * recorded yet, so a failure here only removes the suggestions.
 */
async function loadMirroredTestTypes(signal?: AbortSignal): Promise<string[]> {
  const found = new Set<string>();
  const [dimensions, measurements] = await Promise.allSettled([
    getStatsDimensions(signal),
    getMeasurementDimensions(signal),
  ]);
  if (measurements.status === "fulfilled") {
    for (const entry of measurements.value.test_types) {
      const testType = normalizedTestType(entry.test_type);
      if (testType !== null) found.add(testType);
    }
  }
  const componentTypes =
    dimensions.status === "fulfilled"
      ? dimensions.value.component_types.slice(0, MAX_SCHEMA_COMPONENT_TYPES)
      : [];
  const schemas = await Promise.allSettled(
    componentTypes.map((componentType) => getTestTypeSchemas(componentType, signal)),
  );
  for (const result of schemas) {
    if (result.status !== "fulfilled") continue;
    for (const row of result.value) {
      const testType = normalizedTestType(row.test_code);
      if (testType !== null) found.add(testType);
    }
  }
  return [...found].sort((left, right) => left.localeCompare(right));
}

function asObject(value: unknown): Record<string, unknown> | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

function stringSetting(settings: Record<string, unknown>, key: string): string {
  const value = settings[key];
  return typeof value === "string" ? value : "";
}

function optionalStringSetting(
  settings: Record<string, unknown>,
  key: string,
  legacyKey?: string,
): { value: string; configured: boolean } {
  if (Object.prototype.hasOwnProperty.call(settings, key)) {
    return { value: stringSetting(settings, key), configured: true };
  }
  if (legacyKey !== undefined && Object.prototype.hasOwnProperty.call(settings, legacyKey)) {
    return { value: stringSetting(settings, legacyKey), configured: true };
  }
  return { value: "", configured: false };
}

function stringList(value: unknown, prefix: string): TextRow[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter((item): item is string => typeof item === "string")
    .map((item) => ({ key: rowId(prefix), value: item }));
}

function channelRows(value: unknown): ChannelDraft[] {
  const channels = asObject(value);
  if (channels === null) return [];

  return Object.entries(channels).flatMap(([name, rawConfig]) => {
    const config = asObject(rawConfig);
    if (config === null) return [];
    const rawKind = config.kind;
    if (
      rawKind !== "mattermost" &&
      rawKind !== "telegram" &&
      rawKind !== "webhook" &&
      rawKind !== "email"
    ) return [];
    const rawUrl = config.url;
    const channel = typeof config.channel === "string" ? config.channel : "";
    const smtpHost = typeof config.smtp_host === "string" ? config.smtp_host : "";
    const smtpPort =
      typeof config.smtp_port === "number" || typeof config.smtp_port === "string"
        ? String(config.smtp_port)
        : "587";
    const smtpSecurity = config.smtp_security === "ssl" ? "ssl" : "starttls";
    const smtpUsername =
      typeof config.smtp_username === "string" ? config.smtp_username : "";
    return [
      {
        key: rowId("admin-channel"),
        originalName: name,
        originalKind: rawKind,
        originalSmtpHost: rawKind === "email" ? smtpHost : null,
        originalSmtpPort: rawKind === "email" ? smtpPort : null,
        originalSmtpSecurity: rawKind === "email" ? smtpSecurity : null,
        originalSmtpUsername: rawKind === "email" ? smtpUsername : null,
        name,
        kind: rawKind,
        // The API promises a masked value. Be defensive if an older API ever
        // returns a real URL: never copy an existing bearer secret into a form.
        url: "",
        hasStoredSecret: typeof rawUrl === "string" && rawUrl.trim() !== "",
        channel,
        chatId: typeof config.chat_id === "string" ? config.chat_id : "",
        smtpHost,
        smtpPort,
        smtpSecurity,
        smtpUsername,
        smtpPassword: "",
        hasStoredSmtpPassword:
          typeof config.smtp_password === "string" && config.smtp_password.trim() !== "",
        fromAddress: typeof config.from_address === "string" ? config.from_address : "",
        toAddress: typeof config.to_address === "string" ? config.to_address : "",
      },
    ];
  });
}

function glueRows(value: unknown): GluePotLifeRow[] {
  const potLife = asObject(value);
  if (potLife === null) return [];
  return Object.entries(potLife).flatMap(([glueType, minutes]) => {
    if (typeof minutes !== "number" && typeof minutes !== "string") return [];
    return [
      {
        key: rowId("admin-glue"),
        glueType,
        minutes: String(minutes),
      },
    ];
  });
}

function receptionTestRows(value: unknown): ReceptionTestRow[] {
  const mapping = asObject(value);
  if (mapping === null) return [];
  return Object.entries(mapping).flatMap(([componentType, rawTests]) => {
    if (!Array.isArray(rawTests)) return [];
    return rawTests.flatMap((rawTestType) =>
      typeof rawTestType === "string"
        ? [
            {
              key: rowId("admin-reception-test"),
              componentType,
              testType: rawTestType,
            },
          ]
        : [],
    );
  });
}

/** Numbers survive a round-trip through the form as text; keep them verbatim
 * so a saved `151` never comes back as `151.00000000000003`. */
function numberText(value: unknown): string {
  return typeof value === "number" || typeof value === "string" ? String(value) : "";
}

function glueInputOverrides(value: unknown): Record<string, GlueWeightInputOverride> {
  const mapping = asObject(value);
  const overrides = Object.create(null) as Record<string, GlueWeightInputOverride>;
  if (mapping === null) return overrides;

  for (const [rawTypeCode, rawOverride] of Object.entries(mapping)) {
    const typeCode = rawTypeCode.trim().toUpperCase();
    const override = asObject(rawOverride);
    if (!GLUE_TYPE_CODE_PATTERN.test(typeCode) || override === null) continue;

    const measured =
      typeof override.measured === "string" ? override.measured.trim().toUpperCase() : "";
    if (!RESULT_CODE_PATTERN.test(measured) || !Array.isArray(override.subtract)) continue;
    const subtract = override.subtract.flatMap((rawCode) => {
      if (typeof rawCode !== "string") return [];
      const code = rawCode.trim().toUpperCase();
      return RESULT_CODE_PATTERN.test(code) ? [code] : [];
    });
    if (subtract.length !== override.subtract.length) continue;

    let resultCode: string | null | undefined;
    if (Object.prototype.hasOwnProperty.call(override, "result_code")) {
      if (override.result_code === null) {
        resultCode = null;
      } else if (typeof override.result_code === "string") {
        const code = override.result_code.trim().toUpperCase();
        if (!RESULT_CODE_PATTERN.test(code)) continue;
        resultCode = code;
      } else {
        continue;
      }
    }
    overrides[typeCode] = {
      measured,
      subtract,
      ...(resultCode === undefined ? {} : { result_code: resultCode }),
    };
  }
  return overrides;
}

function cloneGlueInputOverrides(
  overrides: Record<string, GlueWeightInputOverride>,
): Record<string, GlueWeightInputOverride> {
  return Object.fromEntries(
    Object.entries(overrides).map(([typeCode, override]) => [
      typeCode,
      { ...override, subtract: [...override.subtract] },
    ]),
  );
}

/** `glue_weight_inputs` (plan §9.2) → editor rows. Anything unreadable is
 * dropped rather than guessed: a half-understood formula is worse than none. */
function glueInputRows(value: unknown): GlueInputRow[] {
  const mapping = asObject(value);
  if (mapping === null) return [];
  return Object.entries(mapping).flatMap(([stepKey, rawStep]) => {
    const step = asObject(rawStep);
    if (step === null) return [];
    const subtract = Array.isArray(step.subtract)
      ? step.subtract.filter((item): item is string => typeof item === "string")
      : [];
    return [
      {
        key: rowId("admin-glue-input"),
        stepKey,
        label: typeof step.label === "string" ? step.label : "",
        testType: typeof step.test_type === "string" ? step.test_type : "",
        measured: typeof step.measured === "string" ? step.measured : "",
        subtract: subtract.map((code) => ({ key: rowId("admin-glue-subtract"), value: code })),
        resultCode: typeof step.result_code === "string" ? step.result_code : "",
        byTypeCode: glueInputOverrides(step.by_type_code),
      },
    ];
  });
}

/**
 * The date part of a stored `valid_from`. The API normalises it to a full UTC
 * timestamp (`2023-10-24T00:00:00+00:00`), which a `<input type="date">` would
 * silently refuse and render as blank — the rule would then look undated and
 * be saved as the always-valid fallback, quietly re-judging every historical
 * run against it.
 */
function validFromDate(value: unknown): string {
  if (typeof value !== "string") return "";
  const trimmed = value.trim();
  return ISO_DATE_PATTERN.test(trimmed.slice(0, 10)) ? trimmed.slice(0, 10) : "";
}

/**
 * `glue_targets` (plan §9.1) → editor rows. The stored shape nests
 * process → module type → step → {target, tolerance}; the editor flattens the
 * inner two levels into one row per cell, which is how an operator reads the
 * table on the sheet and keeps every field reachable with the keyboard.
 */
function glueRuleSetRows(value: unknown): GlueRuleSetRow[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((rawRuleSet) => {
    const ruleSet = asObject(rawRuleSet);
    if (ruleSet === null) return [];
    const process = typeof ruleSet.process === "string" ? ruleSet.process : "";
    const moduleTypes = asObject(ruleSet.module_types) ?? {};
    const targets: GlueTargetCellRow[] = [];
    for (const [moduleType, rawSteps] of Object.entries(moduleTypes)) {
      const steps = asObject(rawSteps);
      if (steps === null) continue;
      for (const [stepKey, rawCell] of Object.entries(steps)) {
        const cell = asObject(rawCell);
        if (cell === null) continue;
        targets.push({
          key: rowId("admin-glue-target"),
          moduleType,
          stepKey,
          targetMg: numberText(cell.target_mg),
          toleranceMg: numberText(cell.tolerance_mg),
        });
      }
    }
    return [
      {
        key: rowId("admin-glue-ruleset"),
        process,
        label: typeof ruleSet.label === "string" ? ruleSet.label : "",
        validFrom: validFromDate(ruleSet.valid_from),
        targets,
      },
    ];
  });
}

function stringArray(value: unknown): string[] | null {
  if (!Array.isArray(value)) return null;
  return value.every((item) => typeof item === "string" && item !== "")
    ? (value as string[])
    : null;
}

/**
 * Project the saved profile exactly the way `stage_model_from_settings`
 * (backend/app/domain/stages.py) does, so the editor shows what the engine
 * will actually evaluate:
 *
 *  - `stage_order` replaces the seed order wholesale; any other shape (absent,
 *    null, a non-list, a list holding a non-string or an empty string) keeps
 *    the seed order.
 *  - `stage_requirements` replaces the seed requirements *per stage*; stages
 *    the override does not mention keep their seed requirements. Because the
 *    seed keys therefore always survive the merge, a seed stage that is left
 *    out of the order is not dropped — it is appended after the ordered
 *    stages. That is why seed stages cannot be removed or renamed here.
 */
function stageRowsFromSettings(settings: Record<string, unknown>): StageRow[] {
  const order = stringArray(settings.stage_order) ?? [...SEED_STAGE_ORDER];
  const requirements = new Map<string, string[]>();
  for (const [stage, tests] of Object.entries(SEED_STAGE_REQUIREMENTS)) {
    requirements.set(stage, [...tests]);
  }
  const override = asObject(settings.stage_requirements);
  if (override !== null) {
    for (const [stage, tests] of Object.entries(override)) {
      if (!Array.isArray(tests)) continue;
      const list = tests.filter((item): item is string => typeof item === "string");
      // A single non-string entry makes the backend ignore the whole override
      // for this stage, which then keeps its seed requirements.
      if (list.length === tests.length) requirements.set(stage, list);
    }
  }
  const effectiveOrder = [
    ...order,
    ...[...requirements.keys()].filter((stage) => !order.includes(stage)),
  ];
  return effectiveOrder.map((stage) => ({
    key: rowId("admin-stage"),
    name: stage,
    fromSeed: SEED_STAGE_ORDER.includes(stage) || stage in SEED_STAGE_REQUIREMENTS,
    appended: !order.includes(stage),
    tests: (requirements.get(stage) ?? []).map((testType) => ({
      key: rowId("admin-stage-test"),
      value: testType,
    })),
  }));
}

/**
 * Match the backend's fail-closed definition of an explicit stage policy.
 * A raw approval bit is ineffective when the stored model still inherits any
 * seed order/requirement entry, so the UI must not present that state as
 * approved either.
 */
function hasExplicitStagePolicy(settings: Record<string, unknown>): boolean {
  const order = stringArray(settings.stage_order);
  const requirements = asObject(settings.stage_requirements);
  if (order === null || requirements === null) return false;
  if (
    Object.values(requirements).some(
      (tests) =>
        !Array.isArray(tests) ||
        tests.some((test) => typeof test !== "string" || test.length === 0),
    )
  ) {
    return false;
  }

  const effectiveRequirementStages = [
    ...Object.keys(SEED_STAGE_REQUIREMENTS),
    ...Object.keys(requirements).filter(
      (stage) => !(stage in SEED_STAGE_REQUIREMENTS),
    ),
  ];
  const effectiveOrder = [
    ...order,
    ...effectiveRequirementStages.filter((stage) => !order.includes(stage)),
  ];
  return (
    effectiveOrder.length === order.length &&
    effectiveOrder.every((stage, index) => stage === order[index]) &&
    effectiveOrder.every((stage) => Object.hasOwn(requirements, stage))
  );
}

type AutoSyncDraft = Pick<
  SettingsDraft,
  | "autoSyncEnabled"
  | "autoSyncIntervalMinutes"
  | "autoSyncWindowStart"
  | "autoSyncWindowEnd"
  | "autoSyncWeekdays"
  | "autoSyncMalformed"
  | "hadAutoSync"
>;

/**
 * Project the stored schedule the way `read_auto_sync_schedule`
 * (backend/app/auto_sync.py) does, so the editor shows what the scheduler
 * will actually do. That reader fails closed — anything it cannot act on
 * reads as "off" rather than being repaired into a guess — and a profile
 * without the key shows the default: off, every day allowed, nothing written
 * back until somebody changes something here.
 */
function autoSyncFromSettings(settings: Record<string, unknown>): AutoSyncDraft {
  const configured = Object.prototype.hasOwnProperty.call(settings, "auto_sync");
  const rawBlock = settings.auto_sync;
  const block = asObject(rawBlock);
  const supportedFields = new Set([
    "enabled",
    "interval_minutes",
    "window_start",
    "window_end",
    "weekdays",
  ]);
  const interval = block?.interval_minutes;
  const windowStart = block?.window_start;
  const windowEnd = block?.window_end;
  const rawWeekdays = block?.weekdays;
  const weekdayList =
    rawWeekdays === null || rawWeekdays === undefined
      ? [...ISO_WEEKDAYS]
      : Array.isArray(rawWeekdays)
        ? rawWeekdays
        : [];
  const weekdaysValid =
    (rawWeekdays === null || rawWeekdays === undefined) ||
    (Array.isArray(rawWeekdays) &&
      rawWeekdays.length > 0 &&
      rawWeekdays.every(
        (day) =>
          typeof day === "number" && Number.isInteger(day) && day >= 1 && day <= 7,
      ) &&
      new Set(rawWeekdays).size === rawWeekdays.length);
  const windowValid =
    (windowStart === null || windowStart === undefined) &&
    (windowEnd === null || windowEnd === undefined)
      ? true
      : typeof windowStart === "string" &&
        typeof windowEnd === "string" &&
        HHMM_PATTERN.test(windowStart) &&
        HHMM_PATTERN.test(windowEnd) &&
        windowStart !== windowEnd;
  const blockValid =
    block !== null &&
    Object.keys(block).every((key) => supportedFields.has(key)) &&
    typeof block.enabled === "boolean" &&
    typeof interval === "number" &&
    Number.isInteger(interval) &&
    interval >= AUTO_SYNC_MIN_INTERVAL_MINUTES &&
    interval <= AUTO_SYNC_MAX_INTERVAL_MINUTES &&
    weekdaysValid &&
    windowValid;

  if (!blockValid) {
    return {
      autoSyncEnabled: false,
      autoSyncIntervalMinutes: String(AUTO_SYNC_DEFAULT_INTERVAL_MINUTES),
      autoSyncWindowStart: "",
      autoSyncWindowEnd: "",
      autoSyncWeekdays: [...ISO_WEEKDAYS],
      // A malformed stored value remains untouched by an unrelated save. It
      // is visibly off and is replaced only when an admin edits this section.
      hadAutoSync: false,
      autoSyncMalformed: configured && rawBlock !== null,
    };
  }

  return {
    autoSyncEnabled: block.enabled === true,
    autoSyncIntervalMinutes: String(interval),
    autoSyncWindowStart: typeof windowStart === "string" ? windowStart : "",
    autoSyncWindowEnd: typeof windowEnd === "string" ? windowEnd : "",
    autoSyncWeekdays: [...weekdayList].sort((left, right) => left - right),
    hadAutoSync: configured,
    autoSyncMalformed: false,
  };
}

/**
 * Whether this institute has anything of its own to say about the schedule.
 * An unrelated save must not write an `auto_sync` block into a profile that
 * never had one: absence is how "never syncs unattended" is stored, and even
 * a disabled block would record a decision nobody made.
 */
function autoSyncConfigured(draft: SettingsDraft): boolean {
  return (
    draft.hadAutoSync ||
    draft.autoSyncEnabled ||
    draft.autoSyncWindowStart !== "" ||
    draft.autoSyncWindowEnd !== "" ||
    draft.autoSyncIntervalMinutes.trim() !== String(AUTO_SYNC_DEFAULT_INTERVAL_MINUTES) ||
    draft.autoSyncWeekdays.length !== ISO_WEEKDAYS.length
  );
}

/** Everything that decides when unattended PDB traffic happens. */
function comparableAutoSync(draft: SettingsDraft): unknown {
  return {
    enabled: draft.autoSyncEnabled,
    intervalMinutes: draft.autoSyncIntervalMinutes,
    windowStart: draft.autoSyncWindowStart,
    windowEnd: draft.autoSyncWindowEnd,
    weekdays: draft.autoSyncWeekdays,
  };
}

function draftFromInstitute(institute: Institute): SettingsDraft {
  const settings = asObject(institute.settings) ?? {};
  const escalation = asObject(settings.reminder_escalation);
  const glueDefaultProcess = optionalStringSetting(
    settings,
    "glue_default_process",
    "glue_process_default",
  );
  const glueProcessProperty = optionalStringSetting(settings, "glue_process_property");
  return {
    name: institute.name,
    localNamePrefix: institute.local_name_prefix,
    logoUrl: stringSetting(settings, "logo_url"),
    pdbProject: stringSetting(settings, "pdb_project"),
    stages: stageRowsFromSettings(settings),
    stagePolicyApproved:
      settings.stage_policy_approved === true && hasExplicitStagePolicy(settings),
    channels: channelRows(settings.notification_channels),
    receptionChecklist: stringList(
      settings.shipment_reception_checklist,
      "admin-checklist",
    ),
    receptionTests: receptionTestRows(settings.shipment_reception_tests),
    gluePotLife: glueRows(settings.glue_pot_life_minutes),
    glueInputs: glueInputRows(settings.glue_weight_inputs),
    glueRuleSets: glueRuleSetRows(settings.glue_targets),
    glueDefaultProcess: glueDefaultProcess.value.trim().toUpperCase(),
    glueProcessProperty: glueProcessProperty.value.trim().toUpperCase(),
    hadGlueInputs: Object.prototype.hasOwnProperty.call(settings, "glue_weight_inputs"),
    hadGlueTargets: Object.prototype.hasOwnProperty.call(settings, "glue_targets"),
    hadGlueDefaultProcess: glueDefaultProcess.configured,
    hadGlueProcessProperty: glueProcessProperty.configured,
    evidenceComponentTypes: stringList(
      settings.evidence_component_types,
      "admin-evidence",
    ),
    ...autoSyncFromSettings(settings),
    escalationAfterMinutes:
      typeof escalation?.after_minutes === "number"
        ? String(escalation.after_minutes)
        : "",
    escalationChannel:
      typeof escalation?.channel === "string" ? escalation.channel : "",
  };
}

function emptyDraft(): SettingsDraft {
  return {
    name: "",
    localNamePrefix: "",
    logoUrl: "",
    pdbProject: "",
    stages: [],
    stagePolicyApproved: false,
    channels: [],
    receptionChecklist: [],
    receptionTests: [],
    gluePotLife: [],
    glueInputs: [],
    glueRuleSets: [],
    glueDefaultProcess: "",
    glueProcessProperty: "",
    hadGlueInputs: false,
    hadGlueTargets: false,
    hadGlueDefaultProcess: false,
    hadGlueProcessProperty: false,
    evidenceComponentTypes: [],
    autoSyncEnabled: false,
    autoSyncIntervalMinutes: String(AUTO_SYNC_DEFAULT_INTERVAL_MINUTES),
    autoSyncWindowStart: "",
    autoSyncWindowEnd: "",
    autoSyncWeekdays: [...ISO_WEEKDAYS],
    autoSyncMalformed: false,
    hadAutoSync: false,
    escalationAfterMinutes: "",
    escalationChannel: "",
  };
}

function cloneDraft(draft: SettingsDraft): SettingsDraft {
  return {
    ...draft,
    stages: draft.stages.map((row) => ({
      ...row,
      tests: row.tests.map((test) => ({ ...test })),
    })),
    channels: draft.channels.map((row) => ({ ...row })),
    receptionChecklist: draft.receptionChecklist.map((row) => ({ ...row })),
    receptionTests: draft.receptionTests.map((row) => ({ ...row })),
    gluePotLife: draft.gluePotLife.map((row) => ({ ...row })),
    glueInputs: draft.glueInputs.map((row) => ({
      ...row,
      subtract: row.subtract.map((item) => ({ ...item })),
      byTypeCode: cloneGlueInputOverrides(row.byTypeCode),
    })),
    glueRuleSets: draft.glueRuleSets.map((row) => ({
      ...row,
      targets: row.targets.map((target) => ({ ...target })),
    })),
    evidenceComponentTypes: draft.evidenceComponentTypes.map((row) => ({ ...row })),
    autoSyncWeekdays: [...draft.autoSyncWeekdays],
  };
}

function comparableStages(draft: SettingsDraft): { stage: string; tests: string[] }[] {
  return draft.stages.map((row) => ({
    stage: row.name,
    tests: row.tests.map((test) => test.value),
  }));
}

/** Everything that decides how a glue result is judged, in one comparable
 * shape — the dirty warning has to fire for the formula *and* the targets. */
function comparableGlueJudgement(draft: SettingsDraft): unknown {
  return {
    defaultProcess: draft.glueDefaultProcess,
    processProperty: draft.glueProcessProperty,
    inputs: draft.glueInputs.map((row) => ({
      stepKey: row.stepKey,
      label: row.label,
      testType: row.testType,
      measured: row.measured,
      subtract: row.subtract.map((item) => item.value),
      resultCode: row.resultCode,
      byTypeCode: cloneGlueInputOverrides(row.byTypeCode),
    })),
    ruleSets: draft.glueRuleSets.map((row) => ({
      process: row.process,
      label: row.label,
      validFrom: row.validFrom,
      targets: row.targets.map(({ key: _key, ...target }) => target),
    })),
  };
}

function comparableDraft(draft: SettingsDraft): string {
  return JSON.stringify({
    name: draft.name,
    localNamePrefix: draft.localNamePrefix,
    logoUrl: draft.logoUrl,
    pdbProject: draft.pdbProject,
    stages: comparableStages(draft),
    stagePolicyApproved: draft.stagePolicyApproved,
    channels: draft.channels.map(({ key: _key, ...row }) => row),
    receptionChecklist: draft.receptionChecklist.map((row) => row.value),
    receptionTests: draft.receptionTests.map((row) => ({
      componentType: row.componentType,
      testType: row.testType,
    })),
    gluePotLife: draft.gluePotLife.map((row) => ({
      glueType: row.glueType,
      minutes: row.minutes,
    })),
    glueJudgement: comparableGlueJudgement(draft),
    evidenceComponentTypes: draft.evidenceComponentTypes.map((row) => row.value),
    autoSync: comparableAutoSync(draft),
    escalationAfterMinutes: draft.escalationAfterMinutes,
    escalationChannel: draft.escalationChannel,
  });
}

function validHttpsUrl(value: string): boolean {
  if (/\s/.test(value) || value.includes("\\")) return false;
  try {
    const parsed = new URL(value);
    return (
      parsed.protocol === "https:" &&
      parsed.hostname !== "" &&
      parsed.username === "" &&
      parsed.password === ""
    );
  } catch {
    return false;
  }
}

function validEmail(value: string): boolean {
  return /^[^@\s]+@[^@\s]+\.[^@\s]+$/u.test(value) && value.length <= 254;
}

function validSmtpHost(value: string): boolean {
  return (
    value !== "" &&
    value.length <= 253 &&
    !/[\s/@\\]/u.test(value) &&
    !Array.from(value).some((character) => character.charCodeAt(0) < 32)
  );
}

function validImageUrl(value: string): boolean {
  if (/\s/.test(value) || value.includes("\\") || value.startsWith("//")) return false;
  // Explicit schemes are accepted only through the strict remote-HTTPS gate.
  // Everything else must resolve to the same origin, which keeps existing
  // values such as `logo.svg`, `./logo.svg`, and `/assets/logo.svg` valid.
  if (/^[a-z][a-z\d+.-]*:/i.test(value)) return validHttpsUrl(value);
  try {
    const localOrigin = "https://itkflow.invalid";
    return new URL(value, `${localOrigin}/`).origin === localOrigin;
  } catch {
    return false;
  }
}

function unknownError(error: unknown, fallback: string): string {
  return error instanceof Error && error.message !== "" ? error.message : fallback;
}

function updateTextRow(rows: TextRow[], key: string, value: string): TextRow[] {
  return rows.map((row) => (row.key === key ? { ...row, value } : row));
}

function validateAndBuildUpdate(
  draft: SettingsDraft,
  labels: AdminSettingsLabels,
): { update: AdminSettingsUpdate } | { error: string } {
  const name = draft.name.trim();
  const prefix = draft.localNamePrefix.trim();
  const logoUrl = draft.logoUrl.trim();
  const pdbProject = draft.pdbProject.trim();

  if (name === "") return { error: labels.required(labels.nameLabel) };
  if (name.length > 120) return { error: labels.tooLong(labels.nameLabel, 120) };
  if (prefix.length > 32) {
    return { error: labels.tooLong(labels.localNamePrefixLabel, 32) };
  }
  if (logoUrl !== "" && !validImageUrl(logoUrl)) {
    return { error: labels.safeImageUrlRequired(labels.logoUrlLabel) };
  }

  const notificationChannels = Object.create(null) as AdminOperationalSettings["notification_channels"];
  const channelNames = new Set<string>();
  for (const row of draft.channels) {
    const channelName = row.name.trim();
    if (channelName === "") {
      return { error: labels.required(labels.channelNameLabel) };
    }
    if (channelName.length > 64) {
      return { error: labels.tooLong(labels.channelNameLabel, 64) };
    }
    if (channelNames.has(channelName)) {
      return { error: labels.duplicate(labels.channelNameLabel, channelName) };
    }
    channelNames.add(channelName);

    if (row.kind === "email") {
      const host = row.smtpHost.trim();
      const port = Number(row.smtpPort);
      const username = row.smtpUsername.trim();
      const enteredPassword = row.smtpPassword;
      const fromAddress = row.fromAddress.trim();
      const toAddress = row.toAddress.trim();
      if (!validSmtpHost(host)) return { error: labels.required(labels.smtpHostLabel) };
      if (!Number.isInteger(port) || port < 1 || port > 65_535) {
        return { error: labels.integerRangeRequired(labels.smtpPortLabel, 1, 65_535) };
      }
      if (!validEmail(fromAddress)) return { error: labels.required(labels.smtpFromLabel) };
      if (!validEmail(toAddress)) return { error: labels.required(labels.smtpToLabel) };
      let password: string | undefined;
      if (enteredPassword !== "") {
        password = enteredPassword;
      } else if (
        row.hasStoredSmtpPassword &&
        row.originalName === channelName &&
        row.originalKind === "email" &&
        username !== "" &&
        row.originalSmtpHost === host &&
        row.originalSmtpPort === String(port) &&
        row.originalSmtpSecurity === row.smtpSecurity &&
        row.originalSmtpUsername === username
      ) {
        password = MASKED_SECRET;
      }
      if ((username === "") !== (password === undefined)) {
        return {
          error: labels.required(
            username === "" ? labels.smtpUsernameLabel : labels.smtpPasswordLabel,
          ),
        };
      }
      notificationChannels[channelName] = {
        kind: "email",
        smtp_host: host,
        smtp_port: port,
        smtp_security: row.smtpSecurity,
        from_address: fromAddress,
        to_address: toAddress,
        ...(username === ""
          ? {}
          : { smtp_username: username, smtp_password: password as string }),
      };
      continue;
    }

    const enteredUrl = row.url.trim();
    let url: string;
    if (enteredUrl !== "") {
      if (!validHttpsUrl(enteredUrl)) {
        return { error: labels.httpsUrlRequired(labels.channelUrlLabel) };
      }
      url = enteredUrl;
    } else if (
      row.hasStoredSecret &&
      row.originalName === channelName &&
      row.originalKind === row.kind
    ) {
      url = MASKED_SECRET;
    } else {
      return { error: labels.required(labels.channelUrlLabel) };
    }

    const channel = row.channel.trim();
    if (channel.length > 120) {
      return { error: labels.tooLong(labels.mattermostChannelLabel, 120) };
    }
    const chatId = row.chatId.trim();
    if (
      row.kind === "telegram" &&
      !/^(?:-?[0-9]{1,32}|@[A-Za-z0-9_]{1,64})$/u.test(chatId)
    ) {
      return { error: labels.required(labels.telegramChatIdLabel) };
    }
    notificationChannels[channelName] = {
      kind: row.kind,
      url,
      ...(row.kind === "mattermost" && channel !== "" ? { channel } : {}),
      ...(row.kind === "telegram" ? { chat_id: chatId } : {}),
    };
  }

  const receptionChecklist: string[] = [];
  const checklistItems = new Set<string>();
  for (const row of draft.receptionChecklist) {
    const item = row.value.trim();
    if (item === "") {
      return { error: labels.required(labels.checklistItemLabel(1)) };
    }
    if (item.length > 200) {
      return { error: labels.tooLong(labels.checklistItemLabel(1), 200) };
    }
    if (checklistItems.has(item)) {
      return { error: labels.duplicate(labels.checklistItemLabel(1), item) };
    }
    checklistItems.add(item);
    receptionChecklist.push(item);
  }

  const receptionTests = Object.create(null) as Record<string, string[]>;
  const receptionTestPairs = new Set<string>();
  for (const row of draft.receptionTests) {
    const componentType = row.componentType.trim().toUpperCase();
    const testType = row.testType.trim().toUpperCase();
    if (componentType === "") {
      return { error: labels.required(labels.receptionComponentTypeLabel) };
    }
    if (testType === "") {
      return { error: labels.required(labels.receptionTestTypeLabel) };
    }
    if (componentType.length > 32) {
      return { error: labels.tooLong(labels.receptionComponentTypeLabel, 32) };
    }
    if (testType.length > 64) {
      return { error: labels.tooLong(labels.receptionTestTypeLabel, 64) };
    }
    const pair = `${componentType}\u0000${testType}`;
    if (receptionTestPairs.has(pair)) {
      return {
        error: labels.duplicate(
          labels.receptionTestTypeLabel,
          `${componentType} / ${testType}`,
        ),
      };
    }
    receptionTestPairs.add(pair);
    (receptionTests[componentType] ??= []).push(testType);
  }

  const gluePotLifeMinutes = Object.create(null) as Record<string, number>;
  const glueTypes = new Set<string>();
  for (const row of draft.gluePotLife) {
    const glueType = row.glueType.trim();
    if (glueType === "") return { error: labels.required(labels.glueTypeLabel) };
    if (glueType.length > 48) {
      return { error: labels.tooLong(labels.glueTypeLabel, 48) };
    }
    if (glueTypes.has(glueType)) {
      return { error: labels.duplicate(labels.glueTypeLabel, glueType) };
    }
    glueTypes.add(glueType);
    const minutes = Number(row.minutes);
    if (
      !Number.isInteger(minutes) ||
      minutes < 1 ||
      minutes > MAX_GLUE_POT_LIFE_MINUTES
    ) {
      return {
        error: labels.integerRangeRequired(
          labels.potLifeLabel,
          1,
          MAX_GLUE_POT_LIFE_MINUTES,
        ),
      };
    }
    gluePotLifeMinutes[glueType] = minutes;
  }

  // ---- Glue-weight judgement (plan §9.1/§9.2) -------------------------------
  // The formula and the targets are profile data. Nothing here knows a module
  // type, a glue process or a PDB result code: every one of them is typed by
  // the admin and travels in the payload.
  const glueWeightInputs = Object.create(null) as Record<string, GlueWeightInputMapping>;
  const glueStepKeys = new Set<string>();
  for (const row of draft.glueInputs) {
    const stepKey = row.stepKey.trim();
    if (stepKey === "" || !GLUE_STEP_KEY_PATTERN.test(stepKey)) {
      return { error: labels.required(labels.glueStepKeyLabel) };
    }
    if (glueStepKeys.has(stepKey)) {
      return { error: labels.duplicate(labels.glueStepKeyLabel, stepKey) };
    }
    glueStepKeys.add(stepKey);
    const measured = row.measured.trim().toUpperCase();
    if (!RESULT_CODE_PATTERN.test(measured)) {
      return { error: labels.required(labels.glueMeasuredLabel) };
    }
    const subtract: string[] = [];
    for (const item of row.subtract) {
      const code = item.value.trim().toUpperCase();
      if (!RESULT_CODE_PATTERN.test(code)) {
        return { error: labels.required(labels.glueSubtractLabel) };
      }
      // Subtracting the measured weight from itself, or the same code twice,
      // silently produces a glue weight nobody meant.
      if (code === measured || subtract.includes(code)) {
        return { error: labels.duplicate(labels.glueSubtractLabel, code) };
      }
      subtract.push(code);
    }
    // Optional: a step without a result code is still judged, it is just
    // never part of the uploaded run.
    const resultCode = row.resultCode.trim().toUpperCase();
    if (resultCode !== "" && !RESULT_CODE_PATTERN.test(resultCode)) {
      return { error: labels.required(labels.glueResultCodeLabel) };
    }
    // Writing the result into one of its own inputs makes the next derivation
    // read its own output.
    if (resultCode !== "" && (resultCode === measured || subtract.includes(resultCode))) {
      return { error: labels.duplicate(labels.glueResultCodeLabel, resultCode) };
    }
    const stepLabel = row.label.trim();
    if (stepLabel.length > 60) {
      return { error: labels.tooLong(labels.glueStepLabelLabel, 60) };
    }
    const testType = row.testType.trim().toUpperCase();
    if (testType !== "" && !TEST_TYPE_PATTERN.test(testType)) {
      return { error: labels.required(labels.glueStepTestTypeLabel) };
    }
    const byTypeCode = cloneGlueInputOverrides(row.byTypeCode);
    glueWeightInputs[stepKey] = {
      measured,
      subtract,
      ...(resultCode === "" ? {} : { result_code: resultCode }),
      ...(stepLabel === "" ? {} : { label: stepLabel }),
      ...(testType === "" ? {} : { test_type: testType }),
      ...(Object.keys(byTypeCode).length === 0 ? {} : { by_type_code: byTypeCode }),
    };
  }

  const glueTargets: GlueTargetRuleSet[] = [];
  const ruleSetKeys = new Set<string>();
  for (const row of draft.glueRuleSets) {
    const process = row.process.trim().toUpperCase();
    if (process === "" || !GLUE_PROCESS_PATTERN.test(process)) {
      return { error: labels.required(labels.glueProcessLabel) };
    }
    const label = row.label.trim();
    if (label.length > 120) {
      return { error: labels.tooLong(labels.glueProcessDisplayLabel, 120) };
    }
    const validFromText = row.validFrom.trim();
    let validFrom: string | null = null;
    if (validFromText !== "") {
      if (
        !ISO_DATE_PATTERN.test(validFromText) ||
        Number.isNaN(new Date(`${validFromText}T00:00:00Z`).getTime())
      ) {
        return { error: labels.glueDateRequired(labels.glueValidFromLabel) };
      }
      validFrom = validFromText;
    }
    // Two rule sets of the same process starting on the same day would make
    // the "newest valid_from wins" selection arbitrary.
    const ruleSetKey = `${process}\u0000${validFrom ?? ""}`;
    if (ruleSetKeys.has(ruleSetKey)) {
      return { error: labels.duplicate(labels.glueProcessLabel, process) };
    }
    ruleSetKeys.add(ruleSetKey);

    const moduleTypes = Object.create(null) as GlueTargetRuleSet["module_types"];
    const targetKeys = new Set<string>();
    for (const target of row.targets) {
      const moduleType = target.moduleType.trim().toUpperCase();
      if (moduleType === "") {
        return { error: labels.required(labels.glueModuleTypeLabel) };
      }
      if (moduleType.length > 32) {
        return { error: labels.tooLong(labels.glueModuleTypeLabel, 32) };
      }
      const stepKey = target.stepKey.trim();
      if (stepKey === "" || !GLUE_STEP_KEY_PATTERN.test(stepKey)) {
        return { error: labels.required(labels.glueStepKeyLabel) };
      }
      const pair = `${moduleType}\u0000${stepKey}`;
      if (targetKeys.has(pair)) {
        return {
          error: labels.duplicate(labels.glueModuleTypeLabel, `${moduleType} / ${stepKey}`),
        };
      }
      targetKeys.add(pair);
      const targetMg = Number(target.targetMg.trim());
      if (
        target.targetMg.trim() === "" ||
        !Number.isFinite(targetMg) ||
        targetMg < 0 ||
        targetMg > MAX_GLUE_TARGET_MG
      ) {
        return { error: labels.glueNumberRequired(labels.glueTargetMgLabel, MAX_GLUE_TARGET_MG) };
      }
      const toleranceMg = Number(target.toleranceMg.trim());
      if (
        target.toleranceMg.trim() === "" ||
        !Number.isFinite(toleranceMg) ||
        toleranceMg < 0 ||
        toleranceMg > MAX_GLUE_TARGET_MG
      ) {
        return {
          error: labels.glueNumberRequired(labels.glueToleranceMgLabel, MAX_GLUE_TARGET_MG),
        };
      }
      (moduleTypes[moduleType] ??= Object.create(null) as Record<
        string,
        { target_mg: number; tolerance_mg: number }
      >)[stepKey] = { target_mg: targetMg, tolerance_mg: toleranceMg };
    }
    glueTargets.push({ process, label, valid_from: validFrom, module_types: moduleTypes });
  }

  const glueDefaultProcess = draft.glueDefaultProcess.trim().toUpperCase();
  if (glueDefaultProcess !== "" && !GLUE_PROCESS_PATTERN.test(glueDefaultProcess)) {
    return { error: labels.required(labels.glueDefaultProcessLabel) };
  }
  if (
    glueDefaultProcess !== "" &&
    !glueTargets.some((ruleSet) => ruleSet.process === glueDefaultProcess)
  ) {
    return { error: labels.glueDefaultProcessMissing };
  }
  const glueProcessProperty = draft.glueProcessProperty.trim().toUpperCase();
  if (glueProcessProperty !== "" && !RESULT_CODE_PATTERN.test(glueProcessProperty)) {
    return { error: labels.required(labels.glueProcessPropertyLabel) };
  }

  // One entry per listed stage — including empty ones. Writing the map in full
  // keeps the saved profile self-explanatory: no stage silently keeps a seed
  // requirement that the editor is no longer showing.
  const stageOrder: string[] = [];
  const stageRequirements = Object.create(null) as Record<string, string[]>;
  for (const row of draft.stages) {
    const stage = row.name.trim().toUpperCase();
    if (stage === "") return { error: labels.required(labels.stageNameLabel) };
    if (stage.length > 64) return { error: labels.tooLong(labels.stageNameLabel, 64) };
    if (!STAGE_NAME_PATTERN.test(stage)) {
      return { error: labels.required(labels.stageNameLabel) };
    }
    if (stageOrder.includes(stage)) {
      return { error: labels.duplicate(labels.stageNameLabel, stage) };
    }
    const tests: string[] = [];
    for (const test of row.tests) {
      const testType = test.value.trim().toUpperCase();
      if (testType === "") return { error: labels.required(labels.stageTestsLabel) };
      if (testType.length > 64) {
        return { error: labels.tooLong(labels.stageTestsLabel, 64) };
      }
      if (!TEST_TYPE_PATTERN.test(testType)) {
        return { error: labels.required(labels.stageTestsLabel) };
      }
      if (tests.includes(testType)) {
        return { error: labels.duplicate(labels.stageTestsLabel, testType) };
      }
      tests.push(testType);
    }
    stageOrder.push(stage);
    stageRequirements[stage] = tests;
  }
  if (stageOrder.length === 0) {
    return { error: labels.required(labels.stagesTitle) };
  }

  const evidenceComponentTypes: string[] = [];
  const evidenceTypes = new Set<string>();
  for (const row of draft.evidenceComponentTypes) {
    const componentType = row.value.trim().toUpperCase();
    if (componentType === "") {
      return { error: labels.required(labels.evidenceTypeLabel(1)) };
    }
    if (componentType.length > 32) {
      return { error: labels.tooLong(labels.evidenceTypeLabel(1), 32) };
    }
    if (evidenceTypes.has(componentType)) {
      return { error: labels.duplicate(labels.evidenceTypeLabel(1), componentType) };
    }
    evidenceTypes.add(componentType);
    evidenceComponentTypes.push(componentType);
  }

  // The unattended schedule. Refused rather than corrected: the backend
  // refuses the same input, and its reader would then read a rejected profile
  // as "off" while this screen still showed a schedule that never fires.
  let autoSync: AutoSyncSchedule | undefined;
  if (autoSyncConfigured(draft)) {
    const intervalMinutes = Number(draft.autoSyncIntervalMinutes.trim());
    if (
      draft.autoSyncIntervalMinutes.trim() === "" ||
      !Number.isInteger(intervalMinutes) ||
      intervalMinutes < AUTO_SYNC_MIN_INTERVAL_MINUTES ||
      intervalMinutes > AUTO_SYNC_MAX_INTERVAL_MINUTES
    ) {
      return {
        error: labels.integerRangeRequired(
          labels.autoSyncIntervalLabel,
          AUTO_SYNC_MIN_INTERVAL_MINUTES,
          AUTO_SYNC_MAX_INTERVAL_MINUTES,
        ),
      };
    }
    const windowStart = draft.autoSyncWindowStart.trim();
    const windowEnd = draft.autoSyncWindowEnd.trim();
    if ((windowStart === "") !== (windowEnd === "")) {
      return { error: labels.autoSyncWindowPairRequired };
    }
    if (
      windowStart !== "" &&
      (!HHMM_PATTERN.test(windowStart) || !HHMM_PATTERN.test(windowEnd))
    ) {
      return { error: labels.autoSyncWindowFormat };
    }
    // Deliberately no start-before-end check: 22:00 to 06:00 is an overnight
    // window, which is the most considerate schedule there is. Only an
    // identical pair is meaningless, and the backend rejects it too.
    if (windowStart !== "" && windowStart === windowEnd) {
      return { error: labels.autoSyncWindowIdentical };
    }
    if (draft.autoSyncWeekdays.length === 0) {
      return { error: labels.autoSyncWeekdaysRequired };
    }
    autoSync = {
      enabled: draft.autoSyncEnabled,
      interval_minutes: intervalMinutes,
      window_start: windowStart === "" ? null : windowStart,
      window_end: windowEnd === "" ? null : windowEnd,
      // All seven selected is "every day", which the profile states as null.
      weekdays:
        draft.autoSyncWeekdays.length === ISO_WEEKDAYS.length
          ? null
          : [...draft.autoSyncWeekdays].sort((left, right) => left - right),
    };
  }

  const escalationAfter = draft.escalationAfterMinutes.trim();
  const escalationChannel = draft.escalationChannel.trim();
  let reminderEscalation: { after_minutes: number; channel: string } | null = null;
  if (escalationAfter !== "" || escalationChannel !== "") {
    const minutes = Number(escalationAfter);
    if (!Number.isInteger(minutes) || minutes < 1 || minutes > 10_080) {
      return {
        error: labels.integerRangeRequired(labels.escalationAfterLabel, 1, 10_080),
      };
    }
    if (escalationChannel === "" || !channelNames.has(escalationChannel)) {
      return { error: labels.required(labels.escalationChannelLabel) };
    }
    reminderEscalation = { after_minutes: minutes, channel: escalationChannel };
  }

  return {
    update: {
      name,
      local_name_prefix: prefix,
      settings: {
        logo_url: logoUrl,
        pdb_project: pdbProject,
        notification_channels: notificationChannels,
        shipment_reception_checklist: receptionChecklist,
        shipment_reception_tests: receptionTests,
        glue_pot_life_minutes: gluePotLifeMinutes,
        // Written only once the institute has something to say about the glue
        // judgement, or already had the key: emitting anything on an unrelated
        // save would change how every module's glue result is judged without
        // anybody asking. When the admin empties a configured block the value
        // is `null`, which disables that profile-backed derivation or target
        // block; an empty object or list is rejected outright.
        ...(draft.hadGlueInputs || draft.glueInputs.length > 0
          ? { glue_weight_inputs: draft.glueInputs.length === 0 ? null : glueWeightInputs }
          : {}),
        ...(draft.hadGlueTargets || draft.glueRuleSets.length > 0
          ? { glue_targets: draft.glueRuleSets.length === 0 ? null : glueTargets }
          : {}),
        ...(draft.hadGlueDefaultProcess || glueDefaultProcess !== ""
          ? { glue_default_process: glueDefaultProcess === "" ? null : glueDefaultProcess }
          : {}),
        ...(draft.hadGlueProcessProperty || glueProcessProperty !== ""
          ? { glue_process_property: glueProcessProperty === "" ? null : glueProcessProperty }
          : {}),
        evidence_component_types: evidenceComponentTypes,
        // Written only once this institute has said something about the
        // schedule, or already had the key: an unrelated save must never be
        // able to switch unattended PDB traffic on.
        ...(autoSync === undefined ? {} : { auto_sync: autoSync }),
        reminder_escalation: reminderEscalation,
        stage_order: stageOrder,
        stage_requirements: stageRequirements,
        stage_policy_approved: draft.stagePolicyApproved,
      },
    },
  };
}

function maskedInstituteAfterSave(
  institute: Institute,
  update: AdminSettingsUpdate,
): Institute {
  const maskedChannels = Object.fromEntries(
    Object.entries(update.settings.notification_channels).map(([name, config]) => [
      name,
      {
        ...config,
        ...(config.url === undefined ? {} : { url: MASKED_SECRET }),
        ...(config.smtp_password === undefined
          ? {}
          : { smtp_password: MASKED_SECRET }),
      },
    ]),
  );
  return {
    ...institute,
    name: update.name,
    local_name_prefix: update.local_name_prefix,
    settings: {
      ...institute.settings,
      ...update.settings,
      notification_channels: maskedChannels,
    },
  };
}

/**
 * Structured editor for the institute-owned operational profile. It never
 * exposes a raw JSON editor and never stores an existing webhook secret in
 * component state: the API's `***` marker is sent back only to preserve an
 * unchanged, same-name channel.
 */
export default function AdminSettingsScreen({
  institutes,
  selectedCode,
  onSelectedCodeChange,
  onSave,
  onTestChannel,
  loadKnownTestTypes = loadMirroredTestTypes,
  labels,
}: AdminSettingsScreenProps) {
  const selectedInstitute = useMemo(
    () => institutes.find((institute) => institute.code === selectedCode) ?? null,
    [institutes, selectedCode],
  );
  const [loadedCode, setLoadedCode] = useState<string | null>(null);
  const [draft, setDraft] = useState<SettingsDraft>(emptyDraft);
  const [savedDraft, setSavedDraft] = useState<SettingsDraft>(emptyDraft);
  const [saving, setSaving] = useState(false);
  const [testingKey, setTestingKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [knownTestTypes, setKnownTestTypes] = useState<readonly string[]>([]);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    loadKnownTestTypes(controller.signal)
      .then((types) => {
        // Suggestions only: a lookup failure must never stop the admin from
        // entering a test type the mirror has not seen yet.
        if (active) setKnownTestTypes(types);
      })
      .catch(() => undefined);
    return () => {
      active = false;
      controller.abort();
    };
  }, [loadKnownTestTypes]);

  useEffect(() => {
    const next = selectedInstitute === null ? emptyDraft() : draftFromInstitute(selectedInstitute);
    setDraft(next);
    setSavedDraft(cloneDraft(next));
    setLoadedCode(selectedInstitute?.code ?? null);
    setError(null);
    setNotice(null);
  }, [selectedCode, selectedInstitute?.id]);

  const dirty = comparableDraft(draft) !== comparableDraft(savedDraft);
  const busy = saving || testingKey !== null;

  function changeDraft(updater: (current: SettingsDraft) => SettingsDraft) {
    setDraft(updater);
    setError(null);
    setNotice(null);
  }

  function reset() {
    setDraft(cloneDraft(savedDraft));
    setError(null);
    setNotice(null);
  }

  function changeStages(updater: (rows: StageRow[]) => StageRow[]) {
    changeDraft((current) => {
      const stages = updater(current.stages);
      if (stages === current.stages) return current;
      return {
        ...current,
        stages,
        // Approval belongs to the exact stage order and requirement set that
        // was reviewed. A changed policy must be consciously approved again.
        stagePolicyApproved: false,
      };
    });
  }

  function updateStage(key: string, updater: (row: StageRow) => StageRow) {
    changeStages((rows) => rows.map((row) => (row.key === key ? updater(row) : row)));
  }

  /** Keyboard-operable reorder: the buttons are the primary control, so this
   * only has to move one row; React keeps focus on the button that moved. */
  function moveStage(key: string, offset: number) {
    changeStages((rows) => {
      const index = rows.findIndex((row) => row.key === key);
      const target = index + offset;
      if (index < 0 || target < 0 || target >= rows.length) return rows;
      const reordered = [...rows];
      const [moved] = reordered.splice(index, 1);
      reordered.splice(target, 0, moved);
      return reordered;
    });
  }

  function isKnownTestType(value: string): boolean {
    return knownTestTypes.includes(value.trim().toUpperCase());
  }

  function changeGlueInputs(updater: (rows: GlueInputRow[]) => GlueInputRow[]) {
    changeDraft((current) => ({ ...current, glueInputs: updater(current.glueInputs) }));
  }

  function updateGlueInput(key: string, updater: (row: GlueInputRow) => GlueInputRow) {
    changeGlueInputs((rows) => rows.map((row) => (row.key === key ? updater(row) : row)));
  }

  function changeGlueRuleSets(updater: (rows: GlueRuleSetRow[]) => GlueRuleSetRow[]) {
    changeDraft((current) => ({ ...current, glueRuleSets: updater(current.glueRuleSets) }));
  }

  function updateGlueRuleSet(key: string, updater: (row: GlueRuleSetRow) => GlueRuleSetRow) {
    changeGlueRuleSets((rows) => rows.map((row) => (row.key === key ? updater(row) : row)));
  }

  /** The step keys the formula defines; the targets below refer to them. */
  const glueStepKeys = useMemo(
    () =>
      [
        ...new Set(
          draft.glueInputs.map((row) => row.stepKey.trim()).filter((stepKey) => stepKey !== ""),
        ),
      ].sort((left, right) => left.localeCompare(right)),
    [draft.glueInputs],
  );
  const glueProcesses = useMemo(
    () =>
      [
        ...new Set(
          draft.glueRuleSets
            .map((row) => row.process.trim().toUpperCase())
            .filter((process) => process !== ""),
        ),
      ].sort((left, right) => left.localeCompare(right)),
    [draft.glueRuleSets],
  );

  const stageModelDirty =
    JSON.stringify(comparableStages(draft)) !== JSON.stringify(comparableStages(savedDraft));
  const glueJudgementDirty =
    JSON.stringify(comparableGlueJudgement(draft)) !==
    JSON.stringify(comparableGlueJudgement(savedDraft));
  const autoSyncDirty =
    JSON.stringify(comparableAutoSync(draft)) !==
    JSON.stringify(comparableAutoSync(savedDraft));
  const autoSyncWindowNote = ((): string => {
    const start = draft.autoSyncWindowStart.trim();
    const end = draft.autoSyncWindowEnd.trim();
    if (start === "" && end === "") return labels.autoSyncWindowAnyTime;
    if (start === "" || end === "") return labels.autoSyncWindowPairRequired;
    if (start === end) return labels.autoSyncWindowIdentical;
    // Zero-padded HH:MM sorts chronologically, so a start after the end is
    // precisely a window that runs over midnight.
    return start < end
      ? labels.autoSyncWindowDaytime(start, end)
      : labels.autoSyncWindowOvernight(start, end);
  })();

  function toggleAutoSyncWeekday(isoWeekday: number) {
    changeDraft((current) => ({
      ...current,
      autoSyncWeekdays: current.autoSyncWeekdays.includes(isoWeekday)
        ? current.autoSyncWeekdays.filter((day) => day !== isoWeekday)
        : [...current.autoSyncWeekdays, isoWeekday].sort((left, right) => left - right),
    }));
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (selectedInstitute === null) return;
    const result = validateAndBuildUpdate(draft, labels);
    if ("error" in result) {
      setError(result.error);
      setNotice(null);
      return;
    }

    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const response = await onSave(selectedInstitute.code, result.update);
      const updated =
        response !== undefined
          ? response
          : maskedInstituteAfterSave(selectedInstitute, result.update);
      const next = draftFromInstitute(updated);
      setDraft(next);
      setSavedDraft(cloneDraft(next));
      setLoadedCode(updated.code);
      setNotice(labels.saveSucceeded(updated.code));
    } catch (caught: unknown) {
      setError(labels.saveFailed(unknownError(caught, labels.unknownError)));
    } finally {
      setSaving(false);
    }
  }

  async function testChannel(row: ChannelDraft) {
    if (selectedInstitute === null || row.originalName === null || onTestChannel === undefined) {
      return;
    }
    setTestingKey(row.key);
    setError(null);
    setNotice(null);
    try {
      await onTestChannel(selectedInstitute.code, row.originalName);
      setNotice(labels.testSucceeded(row.originalName));
    } catch (caught: unknown) {
      setError(labels.testFailed(unknownError(caught, labels.unknownError)));
    } finally {
      setTestingKey(null);
    }
  }

  function savedChannelMatches(row: ChannelDraft): boolean {
    if (row.originalName === null) return false;
    const secretReady =
      row.kind === "email"
        ? row.smtpPassword === "" &&
          (row.smtpUsername === "" || row.hasStoredSmtpPassword)
        : row.url === "" && row.hasStoredSecret;
    if (!secretReady) return false;
    const saved = savedDraft.channels.find(
      (candidate) => candidate.originalName === row.originalName,
    );
    return (
      saved !== undefined &&
      row.name === saved.name &&
      row.kind === saved.kind &&
      row.channel === saved.channel &&
      row.chatId === saved.chatId &&
      row.smtpHost === saved.smtpHost &&
      row.smtpPort === saved.smtpPort &&
      row.smtpSecurity === saved.smtpSecurity &&
      row.smtpUsername === saved.smtpUsername &&
      row.fromAddress === saved.fromAddress &&
      row.toAddress === saved.toAddress
    );
  }

  return (
    <div className="screen admin-settings-screen">
      <div className="sc-head admin-settings-head">
        <div>
          <h1>{labels.title}</h1>
          <span className="sub">{labels.subtitle}</span>
        </div>
        <label className="admin-settings-institute-picker">
          <span className="field-label">{labels.instituteLabel}</span>
          <select
            className="select-input"
            value={selectedCode}
            disabled={busy || dirty || institutes.length < 2}
            onChange={(event) => onSelectedCodeChange(event.target.value)}
          >
            {institutes.length === 0 && <option value="">{labels.noInstitute}</option>}
            {institutes.map((institute) => (
              <option value={institute.code} key={institute.id}>
                {institute.code} · {institute.name}
              </option>
            ))}
          </select>
        </label>
      </div>

      {selectedInstitute === null || loadedCode !== selectedInstitute.code ? (
        <p className="state-note">{labels.noInstitute}</p>
      ) : (
        <form className="admin-settings-form" noValidate onSubmit={(event) => void submit(event)}>
          <section className="panel admin-settings-section" aria-labelledby="admin-general-title">
            <div className="admin-settings-section-head">
              <div>
                <h2 className="section-title" id="admin-general-title">
                  {labels.generalTitle}
                </h2>
                <p className="muted admin-settings-copy">{labels.generalHint}</p>
              </div>
              <span className="chip neutral mono">{selectedInstitute.code}</span>
            </div>
            <div className="admin-settings-grid">
              <label className="admin-settings-field">
                <span className="field-label">{labels.nameLabel}</span>
                <input
                  className="text-input"
                  value={draft.name}
                  maxLength={120}
                  disabled={busy}
                  onChange={(event) =>
                    changeDraft((current) => ({ ...current, name: event.target.value }))
                  }
                />
              </label>
              <label className="admin-settings-field">
                <span className="field-label">{labels.localNamePrefixLabel}</span>
                <input
                  className="text-input mono"
                  value={draft.localNamePrefix}
                  maxLength={32}
                  disabled={busy}
                  onChange={(event) =>
                    changeDraft((current) => ({
                      ...current,
                      localNamePrefix: event.target.value,
                    }))
                  }
                />
              </label>
              <label className="admin-settings-field admin-settings-field-wide">
                <span className="field-label">{labels.logoUrlLabel}</span>
                <input
                  className="text-input mono"
                  type="url"
                  value={draft.logoUrl}
                  placeholder={labels.logoUrlPlaceholder}
                  disabled={busy}
                  onChange={(event) =>
                    changeDraft((current) => ({ ...current, logoUrl: event.target.value }))
                  }
                />
              </label>
              <label className="admin-settings-field">
                <span className="field-label">{labels.pdbProjectLabel}</span>
                <input
                  className="text-input mono"
                  value={draft.pdbProject}
                  placeholder={labels.pdbProjectPlaceholder}
                  disabled={busy}
                  onChange={(event) =>
                    changeDraft((current) => ({
                      ...current,
                      pdbProject: event.target.value,
                    }))
                  }
                />
              </label>
            </div>
          </section>

          <section className="panel admin-settings-section" aria-labelledby="admin-stages-title">
            <div className="admin-settings-section-head">
              <div>
                <h2 className="section-title" id="admin-stages-title">
                  {labels.stagesTitle}
                </h2>
                <p className="muted admin-settings-copy">{labels.stagesHint}</p>
                <p className="muted admin-settings-copy">{labels.stagesImpact}</p>
                <p className="muted admin-settings-copy" id="admin-stage-seed-hint">
                  {labels.stageSeedLockedHint}
                </p>
              </div>
              <button
                type="button"
                className="btn"
                disabled={busy}
                onClick={() =>
                  changeStages((rows) => [
                    ...rows,
                    {
                      key: rowId("admin-stage"),
                      name: "",
                      fromSeed: false,
                      appended: false,
                      tests: [],
                    },
                  ])
                }
              >
                {labels.addStage}
              </button>
            </div>
            {stageModelDirty && (
              <div className="info-banner admin-settings-message" role="status">
                <span>{labels.stagesDirtyWarning}</span>
              </div>
            )}
            <div className="admin-settings-row">
              <label className="admin-settings-toggle" htmlFor="admin-stage-policy-approved">
                <input
                  id="admin-stage-policy-approved"
                  type="checkbox"
                  checked={draft.stagePolicyApproved}
                  disabled={busy}
                  aria-describedby="admin-stage-policy-approved-hint"
                  onChange={(event) =>
                    changeDraft((current) => ({
                      ...current,
                      stagePolicyApproved: event.target.checked,
                    }))
                  }
                />
                <span>{labels.stagePolicyApprovedLabel}</span>
              </label>
              <p
                className="muted admin-settings-copy"
                id="admin-stage-policy-approved-hint"
              >
                {labels.stagePolicyApprovedHint}
              </p>
            </div>
            {!draft.stagePolicyApproved && (
              <div className="info-banner admin-settings-message" role="status">
                <span className="chip amber">{labels.stagePolicyUnapprovedLabel}</span>
                <span>{labels.stagePolicyUnapprovedWarning}</span>
              </div>
            )}
            <datalist id={TEST_TYPE_LIST_ID}>
              {knownTestTypes.map((testType) => (
                <option value={testType} key={testType} />
              ))}
            </datalist>
            <div className="admin-settings-list">
              {draft.stages.map((row, index) => (
                <div
                  className="admin-settings-row"
                  role="group"
                  aria-label={labels.stageRowLabel(index + 1)}
                  key={row.key}
                >
                  <div className="admin-settings-channel-row">
                    <label className="admin-settings-field">
                      <span className="field-label">{labels.stageNameLabel}</span>
                      <input
                        className="text-input mono"
                        value={row.name}
                        maxLength={64}
                        placeholder={labels.stageNamePlaceholder}
                        disabled={busy}
                        readOnly={row.fromSeed}
                        aria-describedby={row.fromSeed ? "admin-stage-seed-hint" : undefined}
                        onChange={(event) =>
                          updateStage(row.key, (current) => ({
                            ...current,
                            name: event.target.value.toUpperCase(),
                          }))
                        }
                      />
                    </label>
                    <div className="chip-row">
                      <span className="chip neutral mono">{index + 1}</span>
                      <span className="chip neutral">
                        {row.fromSeed ? labels.stageOriginSeed : labels.stageOriginCustom}
                      </span>
                      {row.appended && (
                        <span className="chip amber">{labels.stageOriginAppended}</span>
                      )}
                    </div>
                    <div className="admin-settings-row-actions">
                      <button
                        type="button"
                        className="btn"
                        disabled={busy || index === 0}
                        onClick={() => moveStage(row.key, -1)}
                      >
                        {labels.stageMoveUp}
                      </button>
                      <button
                        type="button"
                        className="btn"
                        disabled={busy || index === draft.stages.length - 1}
                        onClick={() => moveStage(row.key, 1)}
                      >
                        {labels.stageMoveDown}
                      </button>
                      <button
                        type="button"
                        className="btn danger"
                        disabled={busy || row.fromSeed}
                        aria-describedby={row.fromSeed ? "admin-stage-seed-hint" : undefined}
                        onClick={() =>
                          changeStages((rows) =>
                            rows.filter((candidate) => candidate.key !== row.key),
                          )
                        }
                      >
                        {labels.stageRemove}
                      </button>
                    </div>
                  </div>
                  <span className="field-label">{labels.stageTestsLabel}</span>
                  {row.tests.length === 0 ? (
                    <p className="state-note admin-settings-empty">{labels.stageTestsEmpty}</p>
                  ) : (
                    <div className="admin-settings-list">
                      {row.tests.map((test, testIndex) => {
                        const value = test.value.trim();
                        const unrecognized =
                          knownTestTypes.length > 0 && value !== "" && !isKnownTestType(value);
                        return (
                          <div className="admin-settings-simple-row" key={test.key}>
                            <div className="admin-settings-field admin-settings-field-wide">
                              <label className="field-label" htmlFor={test.key}>
                                {labels.stageTestLabel(testIndex + 1)}
                              </label>
                              <input
                                id={test.key}
                                className="text-input mono"
                                list={TEST_TYPE_LIST_ID}
                                value={test.value}
                                maxLength={64}
                                placeholder={labels.stageTestPlaceholder}
                                disabled={busy}
                                aria-describedby={
                                  unrecognized ? `${test.key}-unrecognized` : undefined
                                }
                                onChange={(event) =>
                                  updateStage(row.key, (current) => ({
                                    ...current,
                                    tests: updateTextRow(
                                      current.tests,
                                      test.key,
                                      event.target.value.toUpperCase(),
                                    ),
                                  }))
                                }
                              />
                              {unrecognized && (
                                <span
                                  className="muted admin-settings-secret-hint"
                                  id={`${test.key}-unrecognized`}
                                >
                                  <span className="chip amber">{labels.stageTestUnknown}</span>{" "}
                                  {labels.stageTestUnknownHint}
                                </span>
                              )}
                            </div>
                            <button
                              type="button"
                              className="btn danger"
                              disabled={busy}
                              onClick={() =>
                                updateStage(row.key, (current) => ({
                                  ...current,
                                  tests: current.tests.filter(
                                    (candidate) => candidate.key !== test.key,
                                  ),
                                }))
                              }
                            >
                              {labels.stageRemoveTest(testIndex + 1)}
                            </button>
                          </div>
                        );
                      })}
                    </div>
                  )}
                  <div className="admin-settings-row-actions">
                    <button
                      type="button"
                      className="btn"
                      disabled={busy}
                      onClick={() =>
                        updateStage(row.key, (current) => ({
                          ...current,
                          tests: [
                            ...current.tests,
                            { key: rowId("admin-stage-test"), value: "" },
                          ],
                        }))
                      }
                    >
                      {labels.addStageTest}
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </section>

          <section
            className="panel admin-settings-section"
            aria-labelledby="admin-notifications-title"
          >
            <div className="admin-settings-section-head">
              <div>
                <h2 className="section-title" id="admin-notifications-title">
                  {labels.notificationsTitle}
                </h2>
                <p className="muted admin-settings-copy">{labels.notificationsHint}</p>
              </div>
              <button
                type="button"
                className="btn"
                disabled={busy}
                onClick={() =>
                  changeDraft((current) => ({
                    ...current,
                    channels: [
                      ...current.channels,
                      {
                        key: rowId("admin-channel"),
                        originalName: null,
                        originalKind: null,
                        originalSmtpHost: null,
                        originalSmtpPort: null,
                        originalSmtpSecurity: null,
                        originalSmtpUsername: null,
                        name: "",
                        kind: "mattermost",
                        url: "",
                        hasStoredSecret: false,
                        channel: "",
                        chatId: "",
                        smtpHost: "",
                        smtpPort: "587",
                        smtpSecurity: "starttls",
                        smtpUsername: "",
                        smtpPassword: "",
                        hasStoredSmtpPassword: false,
                        fromAddress: "",
                        toAddress: "",
                      },
                    ],
                  }))
                }
              >
                {labels.addChannel}
              </button>
            </div>
            {draft.channels.length === 0 ? (
              <p className="state-note admin-settings-empty">{labels.notificationsEmpty}</p>
            ) : (
              <div className="admin-settings-list">
                {draft.channels.map((row, index) => (
                  <div
                    className="admin-settings-row admin-settings-channel-row"
                    role="group"
                    aria-label={labels.channelRowLabel(index + 1)}
                    key={row.key}
                  >
                    <label className="admin-settings-field">
                      <span className="field-label">{labels.channelNameLabel}</span>
                      <input
                        className="text-input mono"
                        value={row.name}
                        maxLength={64}
                        placeholder={labels.channelNamePlaceholder}
                        disabled={busy}
                        onChange={(event) =>
                          changeDraft((current) => ({
                            ...current,
                            channels: current.channels.map((candidate) =>
                              candidate.key === row.key
                                ? { ...candidate, name: event.target.value }
                                : candidate,
                            ),
                          }))
                        }
                      />
                    </label>
                    <label className="admin-settings-field">
                      <span className="field-label">{labels.channelKindLabel}</span>
                      <select
                        className="select-input"
                        value={row.kind}
                        disabled={busy}
                        onChange={(event) =>
                          changeDraft((current) => ({
                            ...current,
                            channels: current.channels.map((candidate) =>
                              candidate.key === row.key
                                ? {
                                    ...candidate,
                                    kind: event.target.value as NotificationChannelKind,
                                  }
                                : candidate,
                            ),
                          }))
                        }
                      >
                        <option value="mattermost">{labels.channelKindMattermost}</option>
                        <option value="webhook">{labels.channelKindWebhook}</option>
                        <option value="telegram">{labels.channelKindTelegram}</option>
                        <option value="email">{labels.channelKindEmail}</option>
                      </select>
                    </label>
                    {row.kind !== "email" && (
                      <label className="admin-settings-field admin-settings-secret-field">
                        <span className="field-label">{labels.channelUrlLabel}</span>
                        <input
                          className="text-input mono"
                          type="password"
                          autoComplete="new-password"
                          spellCheck={false}
                          value={row.url}
                          placeholder={labels.channelUrlPlaceholder}
                          disabled={busy}
                          onChange={(event) =>
                            changeDraft((current) => ({
                              ...current,
                              channels: current.channels.map((candidate) =>
                                candidate.key === row.key
                                  ? { ...candidate, url: event.target.value }
                                  : candidate,
                              ),
                            }))
                          }
                        />
                        {row.hasStoredSecret &&
                          row.originalKind === row.kind &&
                          row.url === "" && (
                          <span className="muted admin-settings-secret-hint">
                            {labels.channelStoredSecretHint}
                          </span>
                        )}
                      </label>
                    )}
                    {row.kind === "mattermost" && (
                      <label className="admin-settings-field">
                        <span className="field-label">{labels.mattermostChannelLabel}</span>
                        <input
                          className="text-input mono"
                          value={row.channel}
                          maxLength={120}
                          placeholder={labels.mattermostChannelPlaceholder}
                          disabled={busy}
                          onChange={(event) =>
                            changeDraft((current) => ({
                              ...current,
                              channels: current.channels.map((candidate) =>
                                candidate.key === row.key
                                  ? { ...candidate, channel: event.target.value }
                                  : candidate,
                              ),
                            }))
                          }
                        />
                      </label>
                    )}
                    {row.kind === "telegram" && (
                      <label className="admin-settings-field">
                        <span className="field-label">{labels.telegramChatIdLabel}</span>
                        <input
                          className="text-input mono"
                          value={row.chatId}
                          maxLength={65}
                          placeholder={labels.telegramChatIdPlaceholder}
                          disabled={busy}
                          onChange={(event) =>
                            changeDraft((current) => ({
                              ...current,
                              channels: current.channels.map((candidate) =>
                                candidate.key === row.key
                                  ? { ...candidate, chatId: event.target.value }
                                  : candidate,
                              ),
                            }))
                          }
                        />
                      </label>
                    )}
                    {row.kind === "email" && (
                      <>
                        <label className="admin-settings-field">
                          <span className="field-label">{labels.smtpHostLabel}</span>
                          <input
                            className="text-input mono"
                            value={row.smtpHost}
                            disabled={busy}
                            onChange={(event) =>
                              changeDraft((current) => ({
                                ...current,
                                channels: current.channels.map((candidate) =>
                                  candidate.key === row.key
                                    ? { ...candidate, smtpHost: event.target.value }
                                    : candidate,
                                ),
                              }))
                            }
                          />
                        </label>
                        <label className="admin-settings-field">
                          <span className="field-label">{labels.smtpPortLabel}</span>
                          <input
                            className="short-input mono"
                            type="number"
                            min={1}
                            max={65_535}
                            value={row.smtpPort}
                            disabled={busy}
                            onChange={(event) =>
                              changeDraft((current) => ({
                                ...current,
                                channels: current.channels.map((candidate) =>
                                  candidate.key === row.key
                                    ? { ...candidate, smtpPort: event.target.value }
                                    : candidate,
                                ),
                              }))
                            }
                          />
                        </label>
                        <label className="admin-settings-field">
                          <span className="field-label">{labels.smtpSecurityLabel}</span>
                          <select
                            className="select-input"
                            value={row.smtpSecurity}
                            disabled={busy}
                            onChange={(event) =>
                              changeDraft((current) => ({
                                ...current,
                                channels: current.channels.map((candidate) =>
                                  candidate.key === row.key
                                    ? {
                                        ...candidate,
                                        smtpSecurity: event.target.value as "ssl" | "starttls",
                                      }
                                    : candidate,
                                ),
                              }))
                            }
                          >
                            <option value="starttls">{labels.smtpSecurityStarttls}</option>
                            <option value="ssl">{labels.smtpSecuritySsl}</option>
                          </select>
                        </label>
                        <label className="admin-settings-field">
                          <span className="field-label">{labels.smtpUsernameLabel}</span>
                          <input
                            className="text-input mono"
                            value={row.smtpUsername}
                            disabled={busy}
                            autoComplete="username"
                            onChange={(event) =>
                              changeDraft((current) => ({
                                ...current,
                                channels: current.channels.map((candidate) =>
                                  candidate.key === row.key
                                    ? { ...candidate, smtpUsername: event.target.value }
                                    : candidate,
                                ),
                              }))
                            }
                          />
                        </label>
                        <label className="admin-settings-field admin-settings-secret-field">
                          <span className="field-label">{labels.smtpPasswordLabel}</span>
                          <input
                            className="text-input mono"
                            type="password"
                            autoComplete="new-password"
                            value={row.smtpPassword}
                            disabled={busy}
                            onChange={(event) =>
                              changeDraft((current) => ({
                                ...current,
                                channels: current.channels.map((candidate) =>
                                  candidate.key === row.key
                                    ? { ...candidate, smtpPassword: event.target.value }
                                    : candidate,
                                ),
                              }))
                            }
                          />
                          {row.hasStoredSmtpPassword &&
                            row.originalKind === "email" &&
                            row.smtpUsername.trim() !== "" &&
                            row.originalSmtpHost === row.smtpHost.trim() &&
                            row.originalSmtpPort === String(Number(row.smtpPort)) &&
                            row.originalSmtpSecurity === row.smtpSecurity &&
                            row.originalSmtpUsername === row.smtpUsername.trim() &&
                            row.smtpPassword === "" && (
                            <span className="muted admin-settings-secret-hint">
                              {labels.channelStoredSecretHint}
                            </span>
                          )}
                        </label>
                        <label className="admin-settings-field">
                          <span className="field-label">{labels.smtpFromLabel}</span>
                          <input
                            className="text-input mono"
                            type="email"
                            value={row.fromAddress}
                            disabled={busy}
                            onChange={(event) =>
                              changeDraft((current) => ({
                                ...current,
                                channels: current.channels.map((candidate) =>
                                  candidate.key === row.key
                                    ? { ...candidate, fromAddress: event.target.value }
                                    : candidate,
                                ),
                              }))
                            }
                          />
                        </label>
                        <label className="admin-settings-field">
                          <span className="field-label">{labels.smtpToLabel}</span>
                          <input
                            className="text-input mono"
                            type="email"
                            value={row.toAddress}
                            disabled={busy}
                            onChange={(event) =>
                              changeDraft((current) => ({
                                ...current,
                                channels: current.channels.map((candidate) =>
                                  candidate.key === row.key
                                    ? { ...candidate, toAddress: event.target.value }
                                    : candidate,
                                ),
                              }))
                            }
                          />
                        </label>
                      </>
                    )}
                    <div className="admin-settings-row-actions">
                      {row.originalName !== null && onTestChannel !== undefined && (
                        <button
                          type="button"
                          className="btn"
                          disabled={busy || !savedChannelMatches(row)}
                          onClick={() => void testChannel(row)}
                        >
                          {testingKey === row.key
                            ? labels.testingChannel
                            : labels.testChannel}
                        </button>
                      )}
                      <button
                        type="button"
                        className="btn danger"
                        disabled={busy}
                        onClick={() =>
                          changeDraft((current) => ({
                            ...current,
                            channels: current.channels.filter(
                              (candidate) => candidate.key !== row.key,
                            ),
                          }))
                        }
                      >
                        {labels.remove}
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
            <div className="admin-settings-section-head admin-settings-subsection">
              <div>
                <h3 className="section-title">{labels.escalationTitle}</h3>
                <p className="muted admin-settings-copy">{labels.escalationHint}</p>
              </div>
            </div>
            <div className="admin-settings-grid">
              <label className="admin-settings-field">
                <span className="field-label">{labels.escalationAfterLabel}</span>
                <input
                  className="short-input mono"
                  type="number"
                  min={1}
                  max={10_080}
                  value={draft.escalationAfterMinutes}
                  disabled={busy}
                  placeholder={labels.escalationDisabled}
                  onChange={(event) =>
                    changeDraft((current) => ({
                      ...current,
                      escalationAfterMinutes: event.target.value,
                    }))
                  }
                />
              </label>
              <label className="admin-settings-field">
                <span className="field-label">{labels.escalationChannelLabel}</span>
                <select
                  className="select-input"
                  value={draft.escalationChannel}
                  disabled={busy}
                  onChange={(event) =>
                    changeDraft((current) => ({
                      ...current,
                      escalationChannel: event.target.value,
                    }))
                  }
                >
                  <option value="">{labels.escalationDisabled}</option>
                  {draft.channels
                    .filter((channel) => channel.name.trim() !== "")
                    .map((channel) => (
                      <option key={channel.key} value={channel.name.trim()}>
                        {channel.name.trim()}
                      </option>
                    ))}
                </select>
              </label>
            </div>
          </section>

          <section
            className="panel admin-settings-section"
            aria-labelledby="admin-shipments-title"
          >
            <div className="admin-settings-section-head">
              <div>
                <h2 className="section-title" id="admin-shipments-title">
                  {labels.shipmentsTitle}
                </h2>
                <p className="muted admin-settings-copy">{labels.shipmentsHint}</p>
              </div>
              <button
                type="button"
                className="btn"
                disabled={busy}
                onClick={() =>
                  changeDraft((current) => ({
                    ...current,
                    receptionChecklist: [
                      ...current.receptionChecklist,
                      { key: rowId("admin-checklist"), value: "" },
                    ],
                  }))
                }
              >
                {labels.addChecklistItem}
              </button>
            </div>
            {draft.receptionChecklist.length === 0 ? (
              <p className="state-note admin-settings-empty">{labels.shipmentsEmpty}</p>
            ) : (
              <div className="admin-settings-list">
                {draft.receptionChecklist.map((row, index) => (
                  <div
                    className="admin-settings-row admin-settings-simple-row"
                    role="group"
                    aria-label={labels.checklistItemLabel(index + 1)}
                    key={row.key}
                  >
                    <label className="admin-settings-field admin-settings-field-wide">
                      <span className="field-label">
                        {labels.checklistItemLabel(index + 1)}
                      </span>
                      <input
                        className="text-input"
                        value={row.value}
                        maxLength={200}
                        placeholder={labels.checklistItemPlaceholder}
                        disabled={busy}
                        onChange={(event) =>
                          changeDraft((current) => ({
                            ...current,
                            receptionChecklist: updateTextRow(
                              current.receptionChecklist,
                              row.key,
                              event.target.value,
                            ),
                          }))
                        }
                      />
                    </label>
                    <button
                      type="button"
                      className="btn danger"
                      disabled={busy}
                      onClick={() =>
                        changeDraft((current) => ({
                          ...current,
                          receptionChecklist: current.receptionChecklist.filter(
                            (candidate) => candidate.key !== row.key,
                          ),
                        }))
                      }
                    >
                      {labels.remove}
                    </button>
                  </div>
                ))}
              </div>
            )}
          </section>

          <section
            className="panel admin-settings-section"
            aria-labelledby="admin-reception-tests-title"
          >
            <div className="admin-settings-section-head">
              <div>
                <h2 className="section-title" id="admin-reception-tests-title">
                  {labels.receptionTestsTitle}
                </h2>
                <p className="muted admin-settings-copy">{labels.receptionTestsHint}</p>
              </div>
              <button
                type="button"
                className="btn"
                disabled={busy}
                onClick={() =>
                  changeDraft((current) => ({
                    ...current,
                    receptionTests: [
                      ...current.receptionTests,
                      {
                        key: rowId("admin-reception-test"),
                        componentType: "",
                        testType: "",
                      },
                    ],
                  }))
                }
              >
                {labels.addReceptionTest}
              </button>
            </div>
            {draft.receptionTests.length === 0 ? (
              <p className="state-note admin-settings-empty">
                {labels.receptionTestsEmpty}
              </p>
            ) : (
              <div className="admin-settings-list">
                {draft.receptionTests.map((row, index) => (
                  <div
                    className="admin-settings-row admin-settings-reception-test-row"
                    role="group"
                    aria-label={labels.receptionTestRowLabel(index + 1)}
                    key={row.key}
                  >
                    <label className="admin-settings-field">
                      <span className="field-label">
                        {labels.receptionComponentTypeLabel}
                      </span>
                      <input
                        className="text-input mono"
                        value={row.componentType}
                        maxLength={32}
                        placeholder={labels.receptionComponentTypePlaceholder}
                        disabled={busy}
                        onChange={(event) =>
                          changeDraft((current) => ({
                            ...current,
                            receptionTests: current.receptionTests.map((candidate) =>
                              candidate.key === row.key
                                ? {
                                    ...candidate,
                                    componentType: event.target.value.toUpperCase(),
                                  }
                                : candidate,
                            ),
                          }))
                        }
                      />
                    </label>
                    <label className="admin-settings-field">
                      <span className="field-label">{labels.receptionTestTypeLabel}</span>
                      <input
                        className="text-input mono"
                        value={row.testType}
                        maxLength={64}
                        placeholder={labels.receptionTestTypePlaceholder}
                        disabled={busy}
                        onChange={(event) =>
                          changeDraft((current) => ({
                            ...current,
                            receptionTests: current.receptionTests.map((candidate) =>
                              candidate.key === row.key
                                ? {
                                    ...candidate,
                                    testType: event.target.value.toUpperCase(),
                                  }
                                : candidate,
                            ),
                          }))
                        }
                      />
                    </label>
                    <button
                      type="button"
                      className="btn danger"
                      disabled={busy}
                      onClick={() =>
                        changeDraft((current) => ({
                          ...current,
                          receptionTests: current.receptionTests.filter(
                            (candidate) => candidate.key !== row.key,
                          ),
                        }))
                      }
                    >
                      {labels.remove}
                    </button>
                  </div>
                ))}
              </div>
            )}
          </section>

          <section className="panel admin-settings-section" aria-labelledby="admin-glue-title">
            <div className="admin-settings-section-head">
              <div>
                <h2 className="section-title" id="admin-glue-title">
                  {labels.glueTitle}
                </h2>
                <p className="muted admin-settings-copy">{labels.glueHint}</p>
              </div>
              <button
                type="button"
                className="btn"
                disabled={busy}
                onClick={() =>
                  changeDraft((current) => ({
                    ...current,
                    gluePotLife: [
                      ...current.gluePotLife,
                      { key: rowId("admin-glue"), glueType: "", minutes: "" },
                    ],
                  }))
                }
              >
                {labels.addGlueType}
              </button>
            </div>
            {draft.gluePotLife.length === 0 ? (
              <p className="state-note admin-settings-empty">{labels.glueEmpty}</p>
            ) : (
              <div className="admin-settings-list">
                {draft.gluePotLife.map((row, index) => (
                  <div
                    className="admin-settings-row admin-settings-glue-row"
                    role="group"
                    aria-label={labels.glueRowLabel(index + 1)}
                    key={row.key}
                  >
                    <label className="admin-settings-field">
                      <span className="field-label">{labels.glueTypeLabel}</span>
                      <input
                        className="text-input mono"
                        value={row.glueType}
                        maxLength={48}
                        placeholder={labels.glueTypePlaceholder}
                        disabled={busy}
                        onChange={(event) =>
                          changeDraft((current) => ({
                            ...current,
                            gluePotLife: current.gluePotLife.map((candidate) =>
                              candidate.key === row.key
                                ? { ...candidate, glueType: event.target.value }
                                : candidate,
                            ),
                          }))
                        }
                      />
                    </label>
                    <label className="admin-settings-field">
                      <span className="field-label">{labels.potLifeLabel}</span>
                      <span className="admin-settings-input-unit">
                        <input
                          className="short-input mono"
                          type="number"
                          min={1}
                          max={MAX_GLUE_POT_LIFE_MINUTES}
                          step={1}
                          value={row.minutes}
                          disabled={busy}
                          onChange={(event) =>
                            changeDraft((current) => ({
                              ...current,
                              gluePotLife: current.gluePotLife.map((candidate) =>
                                candidate.key === row.key
                                  ? { ...candidate, minutes: event.target.value }
                                  : candidate,
                              ),
                            }))
                          }
                        />
                        <span className="muted">{labels.minutesUnit}</span>
                      </span>
                    </label>
                    <button
                      type="button"
                      className="btn danger"
                      disabled={busy}
                      onClick={() =>
                        changeDraft((current) => ({
                          ...current,
                          gluePotLife: current.gluePotLife.filter(
                            (candidate) => candidate.key !== row.key,
                          ),
                        }))
                      }
                    >
                      {labels.remove}
                    </button>
                  </div>
                ))}
              </div>
            )}
          </section>

          {/* The glue-weight judgement (plan §9.1/§9.2): the formula as data
              and the targets it is judged against. Together these are the
              only reason a module's glue result can be called good or bad —
              the PDB grades nothing (automaticGrading is false on every
              module schema), so switching the production sheet off without
              porting these tables loses the verdict outright. */}
          <section
            className="panel admin-settings-section"
            aria-labelledby="admin-glue-inputs-title"
          >
            <div className="admin-settings-section-head">
              <div>
                <h2 className="section-title" id="admin-glue-inputs-title">
                  {labels.glueInputsTitle}
                </h2>
                <p className="muted admin-settings-copy">{labels.glueInputsHint}</p>
                <p className="muted admin-settings-copy">{labels.glueInputsImpact}</p>
              </div>
              <button
                type="button"
                className="btn"
                disabled={busy}
                onClick={() =>
                  changeGlueInputs((rows) => [
                    ...rows,
                    {
                      key: rowId("admin-glue-input"),
                      stepKey: "",
                      label: "",
                      testType: "",
                      measured: "",
                      subtract: [],
                      resultCode: "",
                      byTypeCode: {},
                    },
                  ])
                }
              >
                {labels.addGlueInput}
              </button>
            </div>
            {glueJudgementDirty && (
              <div className="info-banner admin-settings-message" role="status">
                <span>{labels.glueJudgementDirtyWarning}</span>
              </div>
            )}
            {draft.glueInputs.length === 0 ? (
              <p className="state-note admin-settings-empty">{labels.glueInputsEmpty}</p>
            ) : (
              <div className="admin-settings-list">
                {draft.glueInputs.map((row, index) => {
                  const measured = row.measured.trim().toUpperCase();
                  const resultCode = row.resultCode.trim().toUpperCase();
                  const subtract = row.subtract
                    .map((item) => item.value.trim().toUpperCase())
                    .filter((code) => code !== "");
                  return (
                    <div
                      className="admin-settings-row"
                      role="group"
                      aria-label={labels.glueInputRowLabel(index + 1)}
                      key={row.key}
                    >
                      <div className="admin-settings-channel-row">
                        <label className="admin-settings-field">
                          <span className="field-label">{labels.glueStepKeyLabel}</span>
                          <input
                            className="text-input mono"
                            value={row.stepKey}
                            maxLength={32}
                            placeholder={labels.glueStepKeyPlaceholder}
                            disabled={busy}
                            onChange={(event) =>
                              updateGlueInput(row.key, (current) => ({
                                ...current,
                                stepKey: event.target.value,
                              }))
                            }
                          />
                        </label>
                        <label className="admin-settings-field">
                          <span className="field-label">{labels.glueStepLabelLabel}</span>
                          <input
                            className="text-input"
                            value={row.label}
                            maxLength={60}
                            placeholder={labels.glueStepLabelPlaceholder}
                            disabled={busy}
                            onChange={(event) =>
                              updateGlueInput(row.key, (current) => ({
                                ...current,
                                label: event.target.value,
                              }))
                            }
                          />
                        </label>
                        <label className="admin-settings-field">
                          <span className="field-label">{labels.glueStepTestTypeLabel}</span>
                          <input
                            className="text-input mono"
                            list={TEST_TYPE_LIST_ID}
                            value={row.testType}
                            maxLength={64}
                            placeholder={labels.glueStepTestTypePlaceholder}
                            disabled={busy}
                            onChange={(event) =>
                              updateGlueInput(row.key, (current) => ({
                                ...current,
                                testType: event.target.value.toUpperCase(),
                              }))
                            }
                          />
                        </label>
                        <label className="admin-settings-field">
                          <span className="field-label">{labels.glueMeasuredLabel}</span>
                          <input
                            className="text-input mono"
                            value={row.measured}
                            maxLength={64}
                            placeholder={labels.glueMeasuredPlaceholder}
                            disabled={busy}
                            onChange={(event) =>
                              updateGlueInput(row.key, (current) => ({
                                ...current,
                                measured: event.target.value.toUpperCase(),
                              }))
                            }
                          />
                        </label>
                        <label className="admin-settings-field">
                          <span className="field-label">{labels.glueResultCodeLabel}</span>
                          <input
                            className="text-input mono"
                            value={row.resultCode}
                            maxLength={64}
                            placeholder={labels.glueResultCodePlaceholder}
                            disabled={busy}
                            onChange={(event) =>
                              updateGlueInput(row.key, (current) => ({
                                ...current,
                                resultCode: event.target.value.toUpperCase(),
                              }))
                            }
                          />
                        </label>
                        <div className="admin-settings-row-actions">
                          <button
                            type="button"
                            className="btn danger"
                            disabled={busy}
                            onClick={() =>
                              changeGlueInputs((rows) =>
                                rows.filter((candidate) => candidate.key !== row.key),
                              )
                            }
                          >
                            {labels.remove}
                          </button>
                        </div>
                      </div>
                      <span className="field-label">{labels.glueSubtractLabel}</span>
                      {row.subtract.length === 0 ? (
                        <p className="state-note admin-settings-empty">
                          {labels.glueSubtractEmpty}
                        </p>
                      ) : (
                        <div className="admin-settings-list">
                          {row.subtract.map((item, itemIndex) => (
                            <div className="admin-settings-simple-row" key={item.key}>
                              <div className="admin-settings-field admin-settings-field-wide">
                                <label className="field-label" htmlFor={item.key}>
                                  {labels.glueSubtractItemLabel(itemIndex + 1)}
                                </label>
                                <input
                                  id={item.key}
                                  className="text-input mono"
                                  value={item.value}
                                  maxLength={64}
                                  placeholder={labels.glueSubtractPlaceholder}
                                  disabled={busy}
                                  onChange={(event) =>
                                    updateGlueInput(row.key, (current) => ({
                                      ...current,
                                      subtract: updateTextRow(
                                        current.subtract,
                                        item.key,
                                        event.target.value.toUpperCase(),
                                      ),
                                    }))
                                  }
                                />
                              </div>
                              <button
                                type="button"
                                className="btn danger"
                                disabled={busy}
                                onClick={() =>
                                  updateGlueInput(row.key, (current) => ({
                                    ...current,
                                    subtract: current.subtract.filter(
                                      (candidate) => candidate.key !== item.key,
                                    ),
                                  }))
                                }
                              >
                                {labels.removeGlueSubtract(itemIndex + 1)}
                              </button>
                            </div>
                          ))}
                        </div>
                      )}
                      <div className="admin-settings-row-actions">
                        <button
                          type="button"
                          className="btn"
                          disabled={busy}
                          onClick={() =>
                            updateGlueInput(row.key, (current) => ({
                              ...current,
                              subtract: [
                                ...current.subtract,
                                { key: rowId("admin-glue-subtract"), value: "" },
                              ],
                            }))
                          }
                        >
                          {labels.addGlueSubtract}
                        </button>
                      </div>
                      {/* The formula the admin just described, read back in
                          one line — "which measurement minus which
                          measurements", never raw JSON. */}
                      <p className="mono admin-settings-formula">
                        {measured === ""
                          ? labels.glueFormulaIncomplete
                          : labels.glueFormulaPreview(measured, subtract, resultCode)}
                      </p>
                    </div>
                  );
                })}
              </div>
            )}
          </section>

          <section
            className="panel admin-settings-section"
            aria-labelledby="admin-glue-targets-title"
          >
            <div className="admin-settings-section-head">
              <div>
                <h2 className="section-title" id="admin-glue-targets-title">
                  {labels.glueTargetsTitle}
                </h2>
                <p className="muted admin-settings-copy">{labels.glueTargetsHint}</p>
                <p className="muted admin-settings-copy">{labels.glueTargetsImpact}</p>
              </div>
              <button
                type="button"
                className="btn"
                disabled={busy}
                onClick={() =>
                  changeGlueRuleSets((rows) => [
                    ...rows,
                    {
                      key: rowId("admin-glue-ruleset"),
                      process: "",
                      label: "",
                      validFrom: "",
                      targets: [],
                    },
                  ])
                }
              >
                {labels.addGlueRuleSet}
              </button>
            </div>
            <div
              className="admin-settings-row"
              role="group"
              aria-label={labels.glueProcessResolutionTitle}
            >
              <span className="field-label">{labels.glueProcessResolutionTitle}</span>
              <p className="muted admin-settings-copy">{labels.glueProcessResolutionHint}</p>
              <div className="admin-settings-channel-row">
                <label className="admin-settings-field">
                  <span className="field-label">{labels.glueDefaultProcessLabel}</span>
                  <select
                    className="select-input mono"
                    value={draft.glueDefaultProcess}
                    disabled={busy}
                    onChange={(event) =>
                      changeDraft((current) => ({
                        ...current,
                        glueDefaultProcess: event.target.value,
                      }))
                    }
                  >
                    <option value="">{labels.glueDefaultProcessUnset}</option>
                    {glueProcesses.map((process) => (
                      <option value={process} key={process}>
                        {process}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="admin-settings-field">
                  <span className="field-label">{labels.glueProcessPropertyLabel}</span>
                  <input
                    className="text-input mono"
                    value={draft.glueProcessProperty}
                    maxLength={64}
                    placeholder={labels.glueProcessPropertyPlaceholder}
                    disabled={busy}
                    onChange={(event) =>
                      changeDraft((current) => ({
                        ...current,
                        glueProcessProperty: event.target.value.toUpperCase(),
                      }))
                    }
                  />
                </label>
              </div>
            </div>
            <datalist id={GLUE_STEP_LIST_ID}>
              {glueStepKeys.map((stepKey) => (
                <option value={stepKey} key={stepKey} />
              ))}
            </datalist>
            {draft.glueRuleSets.length === 0 ? (
              <p className="state-note admin-settings-empty">{labels.glueTargetsEmpty}</p>
            ) : (
              <div className="admin-settings-list">
                {draft.glueRuleSets.map((row, index) => (
                  <div
                    className="admin-settings-row"
                    role="group"
                    aria-label={labels.glueRuleSetRowLabel(index + 1)}
                    key={row.key}
                  >
                    <div className="admin-settings-channel-row">
                      <label className="admin-settings-field">
                        <span className="field-label">{labels.glueProcessLabel}</span>
                        <input
                          className="text-input mono"
                          value={row.process}
                          maxLength={32}
                          placeholder={labels.glueProcessPlaceholder}
                          disabled={busy}
                          onChange={(event) =>
                            updateGlueRuleSet(row.key, (current) => ({
                              ...current,
                              process: event.target.value.toUpperCase(),
                            }))
                          }
                        />
                      </label>
                      <label className="admin-settings-field">
                        <span className="field-label">{labels.glueProcessDisplayLabel}</span>
                        <input
                          className="text-input"
                          value={row.label}
                          maxLength={120}
                          placeholder={labels.glueProcessDisplayPlaceholder}
                          disabled={busy}
                          onChange={(event) =>
                            updateGlueRuleSet(row.key, (current) => ({
                              ...current,
                              label: event.target.value,
                            }))
                          }
                        />
                      </label>
                      <label className="admin-settings-field">
                        <span className="field-label">{labels.glueValidFromLabel}</span>
                        <input
                          className="text-input mono"
                          type="date"
                          value={row.validFrom}
                          disabled={busy}
                          onChange={(event) =>
                            updateGlueRuleSet(row.key, (current) => ({
                              ...current,
                              validFrom: event.target.value,
                            }))
                          }
                        />
                      </label>
                      <div className="chip-row">
                        {row.validFrom.trim() === "" && (
                          <span className="chip neutral">{labels.glueValidFromAlways}</span>
                        )}
                      </div>
                      <div className="admin-settings-row-actions">
                        <button
                          type="button"
                          className="btn danger"
                          disabled={busy}
                          onClick={() =>
                            changeGlueRuleSets((rows) =>
                              rows.filter((candidate) => candidate.key !== row.key),
                            )
                          }
                        >
                          {labels.removeGlueRuleSet}
                        </button>
                      </div>
                    </div>
                    <span className="field-label">{labels.glueTargetRowsLabel}</span>
                    {row.targets.length === 0 ? (
                      <p className="state-note admin-settings-empty">
                        {labels.glueTargetRowsEmpty}
                      </p>
                    ) : (
                      <div className="admin-settings-list">
                        {row.targets.map((target, targetIndex) => {
                          const stepKey = target.stepKey.trim();
                          const unknownStep =
                            stepKey !== "" && !glueStepKeys.includes(stepKey);
                          return (
                            <div
                              className="admin-settings-row admin-settings-glue-target-row"
                              role="group"
                              aria-label={labels.glueTargetRowLabel(targetIndex + 1)}
                              key={target.key}
                            >
                              <label className="admin-settings-field">
                                <span className="field-label">{labels.glueModuleTypeLabel}</span>
                                <input
                                  className="text-input mono"
                                  value={target.moduleType}
                                  maxLength={32}
                                  placeholder={labels.glueModuleTypePlaceholder}
                                  disabled={busy}
                                  onChange={(event) =>
                                    updateGlueRuleSet(row.key, (current) => ({
                                      ...current,
                                      targets: current.targets.map((candidate) =>
                                        candidate.key === target.key
                                          ? {
                                              ...candidate,
                                              moduleType: event.target.value.toUpperCase(),
                                            }
                                          : candidate,
                                      ),
                                    }))
                                  }
                                />
                              </label>
                              <div className="admin-settings-field">
                                <label className="field-label" htmlFor={target.key}>
                                  {labels.glueStepKeyLabel}
                                </label>
                                <input
                                  id={target.key}
                                  className="text-input mono"
                                  list={GLUE_STEP_LIST_ID}
                                  value={target.stepKey}
                                  maxLength={32}
                                  placeholder={labels.glueStepKeyPlaceholder}
                                  disabled={busy}
                                  aria-describedby={
                                    unknownStep ? `${target.key}-unknown-step` : undefined
                                  }
                                  onChange={(event) =>
                                    updateGlueRuleSet(row.key, (current) => ({
                                      ...current,
                                      targets: current.targets.map((candidate) =>
                                        candidate.key === target.key
                                          ? { ...candidate, stepKey: event.target.value }
                                          : candidate,
                                      ),
                                    }))
                                  }
                                />
                                {unknownStep && (
                                  <span
                                    className="muted admin-settings-secret-hint"
                                    id={`${target.key}-unknown-step`}
                                  >
                                    <span className="chip amber">{labels.glueStepUnknown}</span>{" "}
                                    {labels.glueStepUnknownHint}
                                  </span>
                                )}
                              </div>
                              {/* The unit sits beside the control rather than
                                  inside the label, so the accessible name
                                  stays "Target" and not "Target mg". */}
                              <div className="admin-settings-field">
                                <label
                                  className="field-label"
                                  htmlFor={`${target.key}-target`}
                                >
                                  {labels.glueTargetMgLabel}
                                </label>
                                <span className="admin-settings-input-unit">
                                  <input
                                    id={`${target.key}-target`}
                                    className="short-input mono"
                                    type="number"
                                    min={0}
                                    max={MAX_GLUE_TARGET_MG}
                                    step="any"
                                    value={target.targetMg}
                                    disabled={busy}
                                    onChange={(event) =>
                                      updateGlueRuleSet(row.key, (current) => ({
                                        ...current,
                                        targets: current.targets.map((candidate) =>
                                          candidate.key === target.key
                                            ? { ...candidate, targetMg: event.target.value }
                                            : candidate,
                                        ),
                                      }))
                                    }
                                  />
                                  <span className="muted">{labels.milligramsUnit}</span>
                                </span>
                              </div>
                              <div className="admin-settings-field">
                                <label
                                  className="field-label"
                                  htmlFor={`${target.key}-tolerance`}
                                >
                                  {labels.glueToleranceMgLabel}
                                </label>
                                <span className="admin-settings-input-unit">
                                  <input
                                    id={`${target.key}-tolerance`}
                                    className="short-input mono"
                                    type="number"
                                    min={0}
                                    max={MAX_GLUE_TARGET_MG}
                                    step="any"
                                    value={target.toleranceMg}
                                    disabled={busy}
                                    onChange={(event) =>
                                      updateGlueRuleSet(row.key, (current) => ({
                                        ...current,
                                        targets: current.targets.map((candidate) =>
                                          candidate.key === target.key
                                            ? { ...candidate, toleranceMg: event.target.value }
                                            : candidate,
                                        ),
                                      }))
                                    }
                                  />
                                  <span className="muted">{labels.milligramsUnit}</span>
                                </span>
                              </div>
                              <button
                                type="button"
                                className="btn danger"
                                disabled={busy}
                                onClick={() =>
                                  updateGlueRuleSet(row.key, (current) => ({
                                    ...current,
                                    targets: current.targets.filter(
                                      (candidate) => candidate.key !== target.key,
                                    ),
                                  }))
                                }
                              >
                                {labels.removeGlueTargetRow(targetIndex + 1)}
                              </button>
                            </div>
                          );
                        })}
                      </div>
                    )}
                    <div className="admin-settings-row-actions">
                      <button
                        type="button"
                        className="btn"
                        disabled={busy}
                        onClick={() =>
                          updateGlueRuleSet(row.key, (current) => ({
                            ...current,
                            targets: [
                              ...current.targets,
                              {
                                key: rowId("admin-glue-target"),
                                moduleType: "",
                                stepKey: "",
                                targetMg: "",
                                toleranceMg: "",
                              },
                            ],
                          }))
                        }
                      >
                        {labels.addGlueTargetRow}
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>

          <section
            className="panel admin-settings-section"
            aria-labelledby="admin-evidence-title"
          >
            <div className="admin-settings-section-head">
              <div>
                <h2 className="section-title" id="admin-evidence-title">
                  {labels.evidenceTitle}
                </h2>
                <p className="muted admin-settings-copy">{labels.evidenceHint}</p>
              </div>
              <button
                type="button"
                className="btn"
                disabled={busy}
                onClick={() =>
                  changeDraft((current) => ({
                    ...current,
                    evidenceComponentTypes: [
                      ...current.evidenceComponentTypes,
                      { key: rowId("admin-evidence"), value: "" },
                    ],
                  }))
                }
              >
                {labels.addEvidenceType}
              </button>
            </div>
            {draft.evidenceComponentTypes.length === 0 ? (
              <p className="state-note admin-settings-empty">{labels.evidenceEmpty}</p>
            ) : (
              <div className="admin-settings-list">
                {draft.evidenceComponentTypes.map((row, index) => (
                  <div
                    className="admin-settings-row admin-settings-simple-row"
                    role="group"
                    aria-label={labels.evidenceTypeLabel(index + 1)}
                    key={row.key}
                  >
                    <label className="admin-settings-field admin-settings-field-wide">
                      <span className="field-label">{labels.evidenceTypeLabel(index + 1)}</span>
                      <input
                        className="text-input mono"
                        value={row.value}
                        maxLength={32}
                        placeholder={labels.evidenceTypePlaceholder}
                        disabled={busy}
                        onChange={(event) =>
                          changeDraft((current) => ({
                            ...current,
                            evidenceComponentTypes: updateTextRow(
                              current.evidenceComponentTypes,
                              row.key,
                              event.target.value.toUpperCase(),
                            ),
                          }))
                        }
                      />
                    </label>
                    <button
                      type="button"
                      className="btn danger"
                      disabled={busy}
                      onClick={() =>
                        changeDraft((current) => ({
                          ...current,
                          evidenceComponentTypes: current.evidenceComponentTypes.filter(
                            (candidate) => candidate.key !== row.key,
                          ),
                        }))
                      }
                    >
                      {labels.remove}
                    </button>
                  </div>
                ))}
              </div>
            )}
          </section>

          <section
            className="panel admin-settings-section"
            aria-labelledby="admin-auto-sync-title"
          >
            <div className="admin-settings-section-head">
              <div>
                <h2 className="section-title" id="admin-auto-sync-title">
                  {labels.autoSyncTitle}
                </h2>
                <p className="muted admin-settings-copy">{labels.autoSyncHint}</p>
                <p className="muted admin-settings-copy">{labels.autoSyncIdentityHint}</p>
                <p className="muted admin-settings-copy">{labels.autoSyncIdentityDetail}</p>
                <p className="muted admin-settings-copy">{labels.autoSyncClockHint}</p>
              </div>
            </div>
            {autoSyncDirty && (
              <div className="info-banner admin-settings-message" role="status">
                <span>{labels.autoSyncDirtyWarning}</span>
              </div>
            )}
            {draft.autoSyncMalformed && (
              <div className="error-banner admin-settings-message" role="alert">
                <span>{labels.autoSyncMalformedWarning}</span>
              </div>
            )}
            <label className="admin-settings-toggle">
              <input
                type="checkbox"
                checked={draft.autoSyncEnabled}
                disabled={busy}
                onChange={(event) =>
                  changeDraft((current) => ({
                    ...current,
                    autoSyncEnabled: event.target.checked,
                  }))
                }
              />
              <span>{labels.autoSyncEnabledLabel}</span>
            </label>
            <p className="state-note admin-settings-empty">
              {draft.autoSyncEnabled
                ? labels.autoSyncEnabledNote
                : labels.autoSyncDisabledNote}
            </p>
            <div className="admin-settings-grid">
              <label className="admin-settings-field">
                <span className="field-label">{labels.autoSyncIntervalLabel}</span>
                <span className="admin-settings-input-unit">
                  <input
                    className="short-input mono"
                    type="number"
                    min={AUTO_SYNC_MIN_INTERVAL_MINUTES}
                    max={AUTO_SYNC_MAX_INTERVAL_MINUTES}
                    step={5}
                    value={draft.autoSyncIntervalMinutes}
                    disabled={busy}
                    onChange={(event) =>
                      changeDraft((current) => ({
                        ...current,
                        autoSyncIntervalMinutes: event.target.value,
                      }))
                    }
                  />
                  <span className="muted">{labels.minutesUnit}</span>
                </span>
              </label>
              <p className="muted admin-settings-copy">{labels.autoSyncIntervalHint}</p>
              <label className="admin-settings-field">
                <span className="field-label">{labels.autoSyncWindowStartLabel}</span>
                <input
                  className="short-input mono"
                  type="time"
                  value={draft.autoSyncWindowStart}
                  disabled={busy}
                  onChange={(event) =>
                    changeDraft((current) => ({
                      ...current,
                      autoSyncWindowStart: event.target.value,
                    }))
                  }
                />
              </label>
              <label className="admin-settings-field">
                <span className="field-label">{labels.autoSyncWindowEndLabel}</span>
                <input
                  className="short-input mono"
                  type="time"
                  value={draft.autoSyncWindowEnd}
                  disabled={busy}
                  onChange={(event) =>
                    changeDraft((current) => ({
                      ...current,
                      autoSyncWindowEnd: event.target.value,
                    }))
                  }
                />
              </label>
            </div>
            <p className="state-note admin-settings-empty">{autoSyncWindowNote}</p>
            <div className="admin-settings-field admin-settings-field-wide">
              <span className="field-label" id="admin-auto-sync-weekdays">
                {labels.autoSyncWeekdaysLabel}
              </span>
              <div
                className="admin-settings-weekdays"
                role="group"
                aria-labelledby="admin-auto-sync-weekdays"
              >
                {ISO_WEEKDAYS.map((isoWeekday) => {
                  const selected = draft.autoSyncWeekdays.includes(isoWeekday);
                  return (
                    <button
                      key={isoWeekday}
                      type="button"
                      className={`btn admin-settings-weekday${selected ? " primary" : ""}`}
                      aria-pressed={selected}
                      aria-label={labels.autoSyncWeekdayName(isoWeekday)}
                      disabled={busy}
                      onClick={() => toggleAutoSyncWeekday(isoWeekday)}
                    >
                      {labels.autoSyncWeekdayShortName(isoWeekday)}
                    </button>
                  );
                })}
              </div>
              <p className="muted admin-settings-copy">{labels.autoSyncWeekdaysHint}</p>
            </div>
          </section>

          {error !== null && (
            <div className="error-banner admin-settings-message" role="alert">
              <span>{error}</span>
            </div>
          )}
          {notice !== null && (
            <div className="info-banner admin-settings-message" role="status">
              <span>{notice}</span>
            </div>
          )}

          <div className="admin-settings-actions">
            <button type="button" className="btn" disabled={busy || !dirty} onClick={reset}>
              {labels.reset}
            </button>
            <button type="submit" className="btn primary" disabled={busy || !dirty}>
              {saving ? labels.saving : labels.save}
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
