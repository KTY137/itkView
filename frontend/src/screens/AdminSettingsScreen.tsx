import { useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { getMeasurementDimensions, getStatsDimensions, getTestTypeSchemas } from "../api";
import type { Institute } from "../api";

const MASKED_SECRET = "***";
const MAX_GLUE_POT_LIFE_MINUTES = 1_440;
const STAGE_NAME_PATTERN = /^[A-Z][A-Z0-9_]{0,63}$/u;
const TEST_TYPE_PATTERN = /^[A-Z][A-Z0-9_]{0,63}$/u;
const TEST_TYPE_LIST_ID = "admin-stage-test-types";
/** Guard against a pathological mirror; a real profile has a handful of types. */
const MAX_SCHEMA_COMPONENT_TYPES = 8;

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
  channels: ChannelDraft[];
  receptionChecklist: TextRow[];
  receptionTests: ReceptionTestRow[];
  gluePotLife: GluePotLifeRow[];
  evidenceComponentTypes: TextRow[];
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
  evidence_component_types: string[];
  reminder_escalation: { after_minutes: number; channel: string } | null;
  /** Complete ordered stage list; written together with `stage_requirements`. */
  stage_order: string[];
  /** One entry per listed stage, so the saved profile is fully explicit. */
  stage_requirements: Record<string, string[]>;
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
  evidenceTitle: string;
  evidenceHint: string;
  evidenceEmpty: string;
  addEvidenceType: string;
  evidenceTypeLabel: (index: number) => string;
  evidenceTypePlaceholder: string;
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
  onTestChannel: (instituteCode: string, channelName: string) => Promise<void>;
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

function draftFromInstitute(institute: Institute): SettingsDraft {
  const settings = asObject(institute.settings) ?? {};
  const escalation = asObject(settings.reminder_escalation);
  return {
    name: institute.name,
    localNamePrefix: institute.local_name_prefix,
    logoUrl: stringSetting(settings, "logo_url"),
    pdbProject: stringSetting(settings, "pdb_project"),
    stages: stageRowsFromSettings(settings),
    channels: channelRows(settings.notification_channels),
    receptionChecklist: stringList(
      settings.shipment_reception_checklist,
      "admin-checklist",
    ),
    receptionTests: receptionTestRows(settings.shipment_reception_tests),
    gluePotLife: glueRows(settings.glue_pot_life_minutes),
    evidenceComponentTypes: stringList(
      settings.evidence_component_types,
      "admin-evidence",
    ),
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
    channels: [],
    receptionChecklist: [],
    receptionTests: [],
    gluePotLife: [],
    evidenceComponentTypes: [],
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
    evidenceComponentTypes: draft.evidenceComponentTypes.map((row) => ({ ...row })),
  };
}

function comparableStages(draft: SettingsDraft): { stage: string; tests: string[] }[] {
  return draft.stages.map((row) => ({
    stage: row.name,
    tests: row.tests.map((test) => test.value),
  }));
}

function comparableDraft(draft: SettingsDraft): string {
  return JSON.stringify({
    name: draft.name,
    localNamePrefix: draft.localNamePrefix,
    logoUrl: draft.logoUrl,
    pdbProject: draft.pdbProject,
    stages: comparableStages(draft),
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
    evidenceComponentTypes: draft.evidenceComponentTypes.map((row) => row.value),
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
        evidence_component_types: evidenceComponentTypes,
        reminder_escalation: reminderEscalation,
        stage_order: stageOrder,
        stage_requirements: stageRequirements,
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
    changeDraft((current) => ({ ...current, stages: updater(current.stages) }));
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

  const stageModelDirty =
    JSON.stringify(comparableStages(draft)) !== JSON.stringify(comparableStages(savedDraft));

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
    if (selectedInstitute === null || row.originalName === null) return;
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
                      {row.originalName !== null && (
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
