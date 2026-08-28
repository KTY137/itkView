import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { Institute } from "../api";
import { t } from "../i18n";
import AdminSettingsScreen from "./AdminSettingsScreen";
import type { AdminSettingsLabels, AdminSettingsScreenProps } from "./AdminSettingsScreen";

const labels: AdminSettingsLabels = {
  title: "Settings",
  subtitle: "Institute profile",
  instituteLabel: "Institute",
  noInstitute: "No institute selected.",
  generalTitle: "General",
  generalHint: "Institute identity.",
  nameLabel: "Institute name",
  localNamePrefixLabel: "Local-name prefix",
  logoUrlLabel: "Logo URL",
  logoUrlPlaceholder: "/assets/logo.svg",
  pdbProjectLabel: "PDB project",
  pdbProjectPlaceholder: "S",
  notificationsTitle: "Notification channels",
  notificationsHint: "Saved URLs remain write-only.",
  notificationsEmpty: "No channels.",
  addChannel: "Add channel",
  channelRowLabel: (index) => `Notification channel ${index}`,
  channelNameLabel: "Channel name",
  channelNamePlaceholder: "operations",
  channelKindLabel: "Channel kind",
  channelKindMattermost: "Mattermost",
  channelKindWebhook: "Webhook",
  channelKindTelegram: "Telegram",
  channelKindEmail: "Email",
  channelUrlLabel: "Webhook URL",
  channelUrlPlaceholder: "https://hooks.example.invalid/secret",
  channelStoredSecretHint: "Saved secret is unchanged.",
  mattermostChannelLabel: "Mattermost channel",
  mattermostChannelPlaceholder: "lab-operations",
  telegramChatIdLabel: "Telegram chat ID",
  telegramChatIdPlaceholder: "-100123",
  smtpHostLabel: "SMTP host",
  smtpPortLabel: "SMTP port",
  smtpSecurityLabel: "SMTP security",
  smtpSecuritySsl: "SSL",
  smtpSecurityStarttls: "STARTTLS",
  smtpUsernameLabel: "SMTP username",
  smtpPasswordLabel: "SMTP password",
  smtpFromLabel: "From address",
  smtpToLabel: "Recipient address",
  escalationTitle: "Escalation",
  escalationHint: "Escalate open tasks.",
  escalationAfterLabel: "Escalate after",
  escalationChannelLabel: "Escalation channel",
  escalationDisabled: "Disabled",
  testChannel: "Test channel",
  testingChannel: "Testing channel",
  shipmentsTitle: "Shipment reception checklist",
  shipmentsHint: "Checklist template.",
  shipmentsEmpty: "No checklist items.",
  addChecklistItem: "Add checklist item",
  checklistItemLabel: (index) => `Checklist item ${index}`,
  checklistItemPlaceholder: "Packaging intact",
  receptionTestsTitle: "Reception tests",
  receptionTestsHint: "Required tests by component type.",
  receptionTestsEmpty: "No reception tests.",
  addReceptionTest: "Add reception test",
  receptionTestRowLabel: (index) => `Reception test ${index}`,
  receptionComponentTypeLabel: "Reception component type",
  receptionComponentTypePlaceholder: "MODULE",
  receptionTestTypeLabel: "Reception test type",
  receptionTestTypePlaceholder: "RECEPTION_IV",
  stagesTitle: "Production stages",
  stagesHint: "Ordered stage flow.",
  stagesImpact: "Saving changes requirement checks.",
  stagesDirtyWarning: "Unsaved stage-model change.",
  stagePolicyApprovedLabel: "Approve this stage workflow for production decisions",
  stagePolicyApprovedHint:
    "Any workflow change clears this approval and requires a deliberate new approval.",
  stagePolicyUnapprovedLabel: "Not approved",
  stagePolicyUnapprovedWarning: "Production status remains provisional.",
  addStage: "Add stage",
  stageRowLabel: (index) => `Production stage ${index}`,
  stageNameLabel: "Stage code",
  stageNamePlaceholder: "MODULE_RECEPTION",
  stageOriginSeed: "Built-in stage",
  stageOriginCustom: "Institute stage",
  stageOriginAppended: "Appended by the engine",
  stageSeedLockedHint: "Built-in stages cannot be renamed or removed.",
  stageMoveUp: "Move up",
  stageMoveDown: "Move down",
  stageRemove: "Remove stage",
  stageTestsLabel: "Required test types",
  stageTestsEmpty: "No test is required at this stage.",
  addStageTest: "Add required test",
  stageTestLabel: (index) => `Required test ${index}`,
  stageTestPlaceholder: "MODULE_IV_AMAC",
  stageRemoveTest: (index) => `Remove required test ${index}`,
  stageTestUnknown: "Not mirrored",
  stageTestUnknownHint: "Check the spelling.",
  glueTitle: "Glue pot life",
  glueHint: "Pot life by glue type.",
  glueEmpty: "No glue types.",
  addGlueType: "Add glue type",
  glueRowLabel: (index) => `Glue type ${index}`,
  glueTypeLabel: "Glue type",
  glueTypePlaceholder: "EPOXY",
  potLifeLabel: "Pot life",
  minutesUnit: "minutes",
  glueInputsTitle: "Glue weight formula",
  glueInputsHint: "Which weighing feeds each glue step.",
  glueInputsImpact: "Result codes must match the schema.",
  glueInputsEmpty: "No glue formula configured.",
  addGlueInput: "Add glue step",
  glueInputRowLabel: (index) => `Glue step ${index}`,
  glueStepKeyLabel: "Step key",
  glueStepKeyPlaceholder: "hybrids",
  glueStepLabelLabel: "Step name",
  glueStepLabelPlaceholder: "Hybrids",
  glueStepTestTypeLabel: "Test type",
  glueStepTestTypePlaceholder: "GLUE_WEIGHT",
  glueMeasuredLabel: "Measured weight",
  glueMeasuredPlaceholder: "GW_MODULE_H1H2",
  glueSubtractLabel: "Minus these weights",
  glueSubtractEmpty: "Nothing is subtracted.",
  addGlueSubtract: "Add subtracted weight",
  glueSubtractItemLabel: (index) => `Subtracted weight ${index}`,
  glueSubtractPlaceholder: "GW_SENSOR",
  removeGlueSubtract: (index) => `Remove subtracted weight ${index}`,
  glueResultCodeLabel: "Store result as",
  glueResultCodePlaceholder: "GW_GLUE_H1H2",
  glueFormulaPreview: (measured, subtract, result) => {
    const expression = subtract.length === 0 ? measured : `${measured} − ${subtract.join(" − ")}`;
    return result === "" ? expression : `${result} = ${expression}`;
  },
  glueFormulaIncomplete: "Formula incomplete.",
  glueTargetsTitle: "Glue targets",
  glueTargetsHint: "Target and tolerance per process, module type and step.",
  glueTargetsImpact: "Saving re-judges past runs.",
  glueTargetsEmpty: "No glue targets configured.",
  glueJudgementDirtyWarning: "Unsaved change to the glue judgement.",
  glueProcessResolutionTitle: "Run process selection",
  glueProcessResolutionHint: "Choose how runs identify their process.",
  glueDefaultProcessLabel: "Default glue process",
  glueDefaultProcessUnset: "No default process",
  glueDefaultProcessMissing: "Default glue process must match a configured rule set.",
  glueProcessPropertyLabel: "Run process property",
  glueProcessPropertyPlaceholder: "GW_PROCESS",
  addGlueRuleSet: "Add rule set",
  glueRuleSetRowLabel: (index) => `Glue rule set ${index}`,
  glueProcessLabel: "Glue process",
  glueProcessPlaceholder: "TRUEBLUE",
  glueProcessDisplayLabel: "Display name",
  glueProcessDisplayPlaceholder: "Shown to operators",
  glueValidFromLabel: "Valid from",
  glueValidFromAlways: "Always valid",
  removeGlueRuleSet: "Remove rule set",
  glueTargetRowsLabel: "Targets",
  glueTargetRowsEmpty: "No target in this rule set.",
  addGlueTargetRow: "Add target",
  glueTargetRowLabel: (index) => `Glue target ${index}`,
  glueModuleTypeLabel: "Module type",
  glueModuleTypePlaceholder: "R5M1",
  glueTargetMgLabel: "Target",
  glueToleranceMgLabel: "Tolerance",
  milligramsUnit: "mg",
  removeGlueTargetRow: (index) => `Remove glue target ${index}`,
  glueStepUnknown: "Not in the formula",
  glueStepUnknownHint: "Check the spelling.",
  glueNumberRequired: (field, max) => `${field} must be 0-${max} mg.`,
  glueDateRequired: (field) => `${field} must be a date.`,
  evidenceTitle: "Evidence mirror",
  evidenceHint: "Mirrored component types.",
  evidenceEmpty: "No evidence types.",
  addEvidenceType: "Add evidence type",
  evidenceTypeLabel: (index) => `Evidence type ${index}`,
  evidenceTypePlaceholder: "MODULE",
  autoSyncTitle: "Scheduled sync",
  autoSyncHint: "Off unless switched on here.",
  autoSyncIdentityHint: "Runs as the last person who synced successfully.",
  autoSyncIdentityDetail: "Skips deactivated accounts and invalid codes.",
  autoSyncClockHint: "Window in server local time; interval in UTC.",
  autoSyncEnabledLabel: "Refresh this institute on a schedule",
  autoSyncEnabledNote: "On: itkFlow contacts the PDB by itself.",
  autoSyncDisabledNote: "Off: only a person starts a sync.",
  autoSyncIntervalLabel: "Refresh when the last sync is older than",
  autoSyncIntervalHint: "At least 15 minutes.",
  autoSyncWindowStartLabel: "Window start",
  autoSyncWindowEndLabel: "Window end",
  autoSyncWindowAnyTime: "No window: any time of day.",
  autoSyncWindowDaytime: (start, end) => `Daytime window ${start} to ${end}.`,
  autoSyncWindowOvernight: (start, end) => `Overnight window ${start} to ${end}.`,
  autoSyncWeekdaysLabel: "Weekdays",
  autoSyncWeekdaysHint: "A night window belongs to the day it opened on.",
  autoSyncWeekdayName: (isoWeekday) =>
    ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"][
      isoWeekday - 1
    ] ?? String(isoWeekday),
  autoSyncWeekdayShortName: (isoWeekday) =>
    ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][isoWeekday - 1] ??
    String(isoWeekday),
  autoSyncDirtyWarning: "Unsaved scheduled-sync change.",
  autoSyncWindowPairRequired: "Set both window times, or neither.",
  autoSyncWindowFormat: "Window times must be HH:MM.",
  autoSyncWindowIdentical: "Window start and end must differ.",
  autoSyncWeekdaysRequired: "Select at least one weekday.",
  autoSyncMalformedWarning: "Stored scheduled-sync settings are invalid and off.",
  remove: "Remove",
  reset: "Reset",
  save: "Save changes",
  saving: "Saving",
  saveSucceeded: (code) => `${code} saved.`,
  saveFailed: (message) => `Save failed: ${message}`,
  testSucceeded: (channel) => `${channel} tested.`,
  testFailed: (message) => `Test failed: ${message}`,
  unknownError: "Unknown error",
  required: (field) => `${field} is required.`,
  tooLong: (field, max) => `${field} must be at most ${max} characters.`,
  duplicate: (field, value) => `${field} duplicates ${value}.`,
  safeImageUrlRequired: (field) => `${field} must be local or HTTPS.`,
  httpsUrlRequired: (field) => `${field} must be HTTPS.`,
  integerRangeRequired: (field, min, max) => `${field} must be ${min}-${max}.`,
};

/** Keeps every test offline: the screen otherwise queries the local mirror. */
const noTestTypes = () => Promise.resolve<string[]>([]);

function institute(code: string, channelName: string): Institute {
  return {
    id: code === "ALPHA" ? 1 : 2,
    code,
    name: `${code} Institute`,
    local_name_prefix: code,
    settings: {
      logo_url: "",
      pdb_project: "S",
      notification_channels: {
        [channelName]: {
          kind: "mattermost",
          url: "***",
          channel: `${code.toLowerCase()}-operations`,
        },
      },
      shipment_reception_checklist: [],
      shipment_reception_tests: {},
      glue_pot_life_minutes: {},
      evidence_component_types: [],
    },
    created_at: "2026-08-26T08:00:00Z",
  };
}

const alpha = institute("ALPHA", "ops-alpha");
const beta = institute("BETA", "ops-beta");

function authenticatedEmailInstitute(): Institute {
  return {
    ...alpha,
    settings: {
      ...alpha.settings,
      notification_channels: {
        emailOps: {
          kind: "email",
          smtp_host: "smtp.example.org",
          smtp_port: 587,
          smtp_security: "starttls",
          smtp_username: "itkflow",
          smtp_password: "***",
          from_address: "itkflow@example.org",
          to_address: "ops@example.org",
        },
      },
    },
  };
}

describe("AdminSettingsScreen notification secrets", () => {
  it("tests the saved channel for the selected institute and preserves its masked secret", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    const onTestChannel = vi.fn().mockResolvedValue(undefined);
    render(
      <AdminSettingsScreen
        institutes={[alpha, beta]}
        selectedCode="BETA"
        onSelectedCodeChange={vi.fn()}
        onSave={onSave}
        onTestChannel={onTestChannel}
        loadKnownTestTypes={noTestTypes}
        labels={labels}
      />,
    );

    const secretInput = await screen.findByLabelText(/^Webhook URL/);
    expect(secretInput).toHaveValue("");
    expect(screen.getByText("Saved secret is unchanged.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Test channel" }));
    await waitFor(() =>
      expect(onTestChannel).toHaveBeenCalledWith("BETA", "ops-beta"),
    );

    const nameInput = screen.getByLabelText("Institute name");
    await user.clear(nameInput);
    await user.type(nameInput, "Beta Updated");
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(onSave).toHaveBeenCalledWith(
      "BETA",
      expect.objectContaining({
        settings: expect.objectContaining({
          notification_channels: {
            "ops-beta": {
              kind: "mattermost",
              url: "***",
              channel: "beta-operations",
            },
          },
        }),
      }),
    );
  });

  it("requires a fresh HTTPS URL when a saved channel is renamed", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(
      <AdminSettingsScreen
        institutes={[alpha]}
        selectedCode="ALPHA"
        onSelectedCodeChange={vi.fn()}
        onSave={onSave}
        onTestChannel={vi.fn().mockResolvedValue(undefined)}
        loadKnownTestTypes={noTestTypes}
        labels={labels}
      />,
    );

    const row = await screen.findByRole("group", { name: "Notification channel 1" });
    const nameInput = within(row).getByLabelText("Channel name");
    await user.clear(nameInput);
    await user.type(nameInput, "ops-renamed");
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Webhook URL is required.");
    expect(onSave).not.toHaveBeenCalled();
    expect(within(row).getByRole("button", { name: "Test channel" })).toBeDisabled();
  });

  it("sends the complete channel map so removing a row deliberately deletes the channel", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(
      <AdminSettingsScreen
        institutes={[alpha]}
        selectedCode="ALPHA"
        onSelectedCodeChange={vi.fn()}
        onSave={onSave}
        onTestChannel={vi.fn().mockResolvedValue(undefined)}
        loadKnownTestTypes={noTestTypes}
        labels={labels}
      />,
    );

    const row = await screen.findByRole("group", { name: "Notification channel 1" });
    await user.click(within(row).getByRole("button", { name: "Remove" }));
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(onSave.mock.calls[0]?.[1].settings.notification_channels).toEqual({});
  });

  it("preserves masked Telegram and SMTP secrets during an unrelated save", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    const adapters: Institute = {
      ...alpha,
      settings: {
        ...alpha.settings,
        notification_channels: {
          telegramAlerts: {
            kind: "telegram",
            url: "***",
            chat_id: "-1001234567890",
          },
          emailOps: {
            kind: "email",
            smtp_host: "smtp.example.org",
            smtp_port: 587,
            smtp_security: "starttls",
            smtp_username: "itkflow",
            smtp_password: "***",
            from_address: "itkflow@example.org",
            to_address: "ops@example.org",
          },
        },
      },
    };
    render(
      <AdminSettingsScreen
        institutes={[adapters]}
        selectedCode="ALPHA"
        onSelectedCodeChange={vi.fn()}
        onSave={onSave}
        onTestChannel={vi.fn().mockResolvedValue(undefined)}
        loadKnownTestTypes={noTestTypes}
        labels={labels}
      />,
    );

    const nameInput = await screen.findByLabelText("Institute name");
    await user.clear(nameInput);
    await user.type(nameInput, "Alpha Updated");
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(onSave.mock.calls[0]?.[1].settings.notification_channels).toEqual({
      telegramAlerts: {
        kind: "telegram",
        url: "***",
        chat_id: "-1001234567890",
      },
      emailOps: {
        kind: "email",
        smtp_host: "smtp.example.org",
        smtp_port: 587,
        smtp_security: "starttls",
        smtp_username: "itkflow",
        smtp_password: "***",
        from_address: "itkflow@example.org",
        to_address: "ops@example.org",
      },
    });
  });

  it("requires a fresh secret when a saved channel changes adapter kind", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(
      <AdminSettingsScreen
        institutes={[alpha]}
        selectedCode="ALPHA"
        onSelectedCodeChange={vi.fn()}
        onSave={onSave}
        onTestChannel={vi.fn().mockResolvedValue(undefined)}
        loadKnownTestTypes={noTestTypes}
        labels={labels}
      />,
    );

    const row = await screen.findByRole("group", { name: "Notification channel 1" });
    await user.selectOptions(within(row).getByLabelText("Channel kind"), "telegram");
    await user.type(within(row).getByLabelText("Telegram chat ID"), "@lab_alerts");
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Webhook URL is required.");
    expect(onSave).not.toHaveBeenCalled();
  });

  it("requires a fresh SMTP password when the saved connection target changes", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(
      <AdminSettingsScreen
        institutes={[authenticatedEmailInstitute()]}
        selectedCode="ALPHA"
        onSelectedCodeChange={vi.fn()}
        onSave={onSave}
        onTestChannel={vi.fn().mockResolvedValue(undefined)}
        loadKnownTestTypes={noTestTypes}
        labels={labels}
      />,
    );

    const host = await screen.findByLabelText("SMTP host");
    await user.clear(host);
    await user.type(host, "attacker.example.org");
    expect(screen.queryByText("Saved secret is unchanged.")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("SMTP password is required.");
    expect(onSave).not.toHaveBeenCalled();
  });

  it("can deliberately remove SMTP authentication without reusing the stored password", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(
      <AdminSettingsScreen
        institutes={[authenticatedEmailInstitute()]}
        selectedCode="ALPHA"
        onSelectedCodeChange={vi.fn()}
        onSave={onSave}
        onTestChannel={vi.fn().mockResolvedValue(undefined)}
        loadKnownTestTypes={noTestTypes}
        labels={labels}
      />,
    );

    const username = await screen.findByLabelText("SMTP username");
    await user.clear(username);
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(onSave.mock.calls[0]?.[1].settings.notification_channels.emailOps).toEqual({
      kind: "email",
      smtp_host: "smtp.example.org",
      smtp_port: 587,
      smtp_security: "starttls",
      from_address: "itkflow@example.org",
      to_address: "ops@example.org",
    });
  });
});

// The seed model these expectations lean on lives in
// backend/app/domain/stages.py and is mirrored by the screen.
const SEED_ORDER = [
  "HV_TAB_ATTACHED",
  "GLUED",
  "STITCH_BONDING",
  "BONDED",
  "TESTED",
  "FINISHED",
];

function approvedStageSettings(): Record<string, unknown> {
  return {
    stage_order: [...SEED_ORDER],
    stage_requirements: {
      HV_TAB_ATTACHED: [],
      GLUED: ["MODULE_METROLOGY"],
      STITCH_BONDING: [],
      BONDED: [],
      TESTED: [],
      FINISHED: [],
    },
    stage_policy_approved: true,
  };
}

function stageInstitute(settings: Record<string, unknown>): Institute {
  return { ...alpha, settings: { ...alpha.settings, ...settings } };
}

function renderStages(
  institutes: Institute[],
  onSave: AdminSettingsScreenProps["onSave"],
  loadKnownTestTypes: (signal?: AbortSignal) => Promise<string[]> = noTestTypes,
) {
  render(
    <AdminSettingsScreen
      institutes={institutes}
      selectedCode="ALPHA"
      onSelectedCodeChange={vi.fn()}
      onSave={onSave}
      onTestChannel={vi.fn().mockResolvedValue(undefined)}
      loadKnownTestTypes={loadKnownTestTypes}
      labels={labels}
    />,
  );
}

function stageGroup(index: number): HTMLElement {
  return screen.getByRole("group", { name: `Production stage ${index}` });
}

describe("AdminSettingsScreen stage model", () => {
  it("loads explicit approval, clears it on a workflow edit, and saves only after deliberate re-approval", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderStages([stageInstitute(approvedStageSettings())], onSave);

    const approval = await screen.findByRole("checkbox", {
      name: "Approve this stage workflow for production decisions",
    });
    expect(approval).toBeChecked();
    expect(screen.queryByText("Production status remains provisional.")).not.toBeInTheDocument();

    await user.click(within(stageGroup(1)).getByRole("button", { name: "Move down" }));
    expect(approval).not.toBeChecked();
    expect(screen.getByText("Production status remains provisional.")).toBeInTheDocument();

    await user.click(approval);
    expect(approval).toBeChecked();
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(onSave.mock.calls[0]?.[1].settings.stage_policy_approved).toBe(true);
  });

  it("persists a cleared approval when requirements change without re-approval", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderStages([stageInstitute(approvedStageSettings())], onSave);

    const glued = await screen.findByRole("group", { name: "Production stage 2" });
    await user.click(
      within(glued).getByRole("button", { name: "Remove required test 1" }),
    );

    expect(
      screen.getByRole("checkbox", {
        name: "Approve this stage workflow for production decisions",
      }),
    ).not.toBeChecked();
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(onSave.mock.calls[0]?.[1].settings.stage_policy_approved).toBe(false);
  });

  it("does not present a raw approval as effective for a partial seed-backed profile", async () => {
    renderStages(
      [
        stageInstitute({
          stage_requirements: { GLUED: ["MODULE_METROLOGY"] },
          stage_policy_approved: true,
        }),
      ],
      vi.fn().mockResolvedValue(undefined),
    );

    expect(
      await screen.findByRole("checkbox", {
        name: "Approve this stage workflow for production decisions",
      }),
    ).not.toBeChecked();
    expect(screen.getByText("Production status remains provisional.")).toBeInTheDocument();
  });

  it("loads an absent approval as provisional and writes an explicit false value", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderStages([stageInstitute({})], onSave);

    expect(
      await screen.findByRole("checkbox", {
        name: "Approve this stage workflow for production decisions",
      }),
    ).not.toBeChecked();
    expect(screen.getByText("Not approved")).toBeInTheDocument();
    expect(screen.getByText("Production status remains provisional.")).toBeInTheDocument();

    await user.type(screen.getByLabelText("Institute name"), " updated");
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(onSave.mock.calls[0]?.[1].settings.stage_policy_approved).toBe(false);
  });

  it("renders the merged model: seed requirements survive an override that omits the stage", async () => {
    renderStages([stageInstitute({ stage_requirements: { TESTED: ["MODULE_IV_AMAC"] } })], vi.fn().mockResolvedValue(undefined));

    await screen.findByRole("group", { name: "Production stage 1" });
    for (const [index, stage] of SEED_ORDER.entries()) {
      expect(within(stageGroup(index + 1)).getByLabelText("Stage code")).toHaveValue(stage);
    }
    // Not overridden: HV_TAB_ATTACHED still shows what the engine evaluates.
    const first = stageGroup(1);
    expect(within(first).getByLabelText("Required test 1")).toHaveValue("VISUAL_INSPECTION");
    expect(within(first).getByLabelText("Required test 2")).toHaveValue("MODULE_IV_PS_V1");
    // Overridden: the institute's value replaces the seed one for that stage.
    expect(within(stageGroup(5)).getByLabelText("Required test 1")).toHaveValue(
      "MODULE_IV_AMAC",
    );
    expect(within(stageGroup(6)).getByText("No test is required at this stage.")).toBeInTheDocument();
    expect(within(first).getByText("Built-in stage")).toBeInTheDocument();
  });

  it("shows a requirements-only stage where the engine appends it instead of dropping it", async () => {
    renderStages(
      [
        stageInstitute({
          stage_order: SEED_ORDER,
          stage_requirements: { MODULE_RECEPTION: ["RECEPTION_IV"] },
        }),
      ],
      vi.fn(),
    );

    const appended = await screen.findByRole("group", { name: "Production stage 7" });
    expect(within(appended).getByLabelText("Stage code")).toHaveValue("MODULE_RECEPTION");
    expect(within(appended).getByText("Appended by the engine")).toBeInTheDocument();
    expect(within(appended).getByText("Institute stage")).toBeInTheDocument();
    expect(within(appended).getByLabelText("Required test 1")).toHaveValue("RECEPTION_IV");
    expect(screen.queryByRole("group", { name: "Production stage 8" })).not.toBeInTheDocument();
  });

  it("reorders with the keyboard and saves a complete, explicit stage model", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderStages([stageInstitute({})], onSave);

    await screen.findByRole("group", { name: "Production stage 1" });
    const moveDown = within(stageGroup(1)).getByRole("button", { name: "Move down" });
    moveDown.focus();
    await user.keyboard("{Enter}");

    expect(within(stageGroup(1)).getByLabelText("Stage code")).toHaveValue("GLUED");
    expect(within(stageGroup(2)).getByLabelText("Stage code")).toHaveValue("HV_TAB_ATTACHED");
    expect(screen.getByText("Unsaved stage-model change.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    const settings = onSave.mock.calls[0]?.[1].settings;
    expect(settings.stage_order).toEqual([
      "GLUED",
      "HV_TAB_ATTACHED",
      "STITCH_BONDING",
      "BONDED",
      "TESTED",
      "FINISHED",
    ]);
    // Every listed stage gets an entry, so nothing silently keeps a seed value.
    expect(settings.stage_requirements).toEqual({
      HV_TAB_ATTACHED: ["VISUAL_INSPECTION", "MODULE_IV_PS_V1"],
      GLUED: ["GLUE_WEIGHT", "MODULE_BOW", "MODULE_METROLOGY"],
      STITCH_BONDING: [],
      BONDED: ["MODULE_WIRE_BONDING"],
      TESTED: ["MODULE_IV_AMAC_TC"],
      FINISHED: [],
    });
  });

  it("adds a stage with a required test and clears an inherited requirement", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderStages([stageInstitute({})], onSave);

    await user.click(await screen.findByRole("button", { name: "Add stage" }));
    const added = stageGroup(7);
    await user.type(within(added).getByLabelText("Stage code"), "module_reception");
    await user.click(within(added).getByRole("button", { name: "Add required test" }));
    await user.type(within(added).getByLabelText("Required test 1"), "reception_iv");

    await user.click(
      within(stageGroup(5)).getByRole("button", { name: "Remove required test 1" }),
    );
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    const settings = onSave.mock.calls[0]?.[1].settings;
    expect(settings.stage_order.at(-1)).toBe("MODULE_RECEPTION");
    expect(settings.stage_requirements.MODULE_RECEPTION).toEqual(["RECEPTION_IV"]);
    expect(settings.stage_requirements.TESTED).toEqual([]);
  });

  it("keeps built-in stages removable only through their requirements", async () => {
    const user = userEvent.setup();
    renderStages([stageInstitute({})], vi.fn().mockResolvedValue(undefined));

    const builtIn = await screen.findByRole("group", { name: "Production stage 1" });
    expect(within(builtIn).getByRole("button", { name: "Remove stage" })).toBeDisabled();
    expect(within(builtIn).getByLabelText("Stage code")).toHaveAttribute("readonly");

    await user.click(screen.getByRole("button", { name: "Add stage" }));
    const added = stageGroup(7);
    expect(within(added).getByRole("button", { name: "Remove stage" })).toBeEnabled();
    await user.click(within(added).getByRole("button", { name: "Remove stage" }));
    expect(screen.queryByRole("group", { name: "Production stage 7" })).not.toBeInTheDocument();
  });

  it("marks a test type the mirror does not know without forbidding it", async () => {
    const onSave = vi.fn();
    renderStages([stageInstitute({})], onSave, () =>
      Promise.resolve(["MODULE_IV_AMAC", "MODULE_WIRE_BONDING"]),
    );

    const bonded = await screen.findByRole("group", { name: "Production stage 4" });
    await waitFor(() =>
      expect(within(stageGroup(5)).getByText("Not mirrored")).toBeInTheDocument(),
    );
    // MODULE_IV_AMAC_TC is a plausible typo of a mirrored type — flag, not block.
    expect(within(stageGroup(5)).getByLabelText("Required test 1")).toHaveAttribute(
      "aria-describedby",
    );
    expect(within(bonded).queryByText("Not mirrored")).not.toBeInTheDocument();
  });

  it("rejects a duplicate stage before it reaches the profile", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderStages([stageInstitute({})], onSave);

    await user.click(await screen.findByRole("button", { name: "Add stage" }));
    await user.type(within(stageGroup(7)).getByLabelText("Stage code"), "glued");
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Stage code duplicates GLUED.",
    );
    expect(onSave).not.toHaveBeenCalled();
  });

  it("rejects a blank required test instead of saving an unsatisfiable stage", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderStages([stageInstitute({})], onSave);

    await user.click(
      within(await screen.findByRole("group", { name: "Production stage 6" })).getByRole(
        "button",
        { name: "Add required test" },
      ),
    );
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Required test types is required.",
    );
    expect(onSave).not.toHaveBeenCalled();
  });
});

describe("AdminSettingsScreen reception test mapping", () => {
  it("saves structured component-type to test-type rows without raw JSON", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(
      <AdminSettingsScreen
        institutes={[alpha]}
        selectedCode="ALPHA"
        onSelectedCodeChange={vi.fn()}
        onSave={onSave}
        onTestChannel={vi.fn().mockResolvedValue(undefined)}
        loadKnownTestTypes={noTestTypes}
        labels={labels}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Add reception test" }));
    const first = screen.getByRole("group", { name: "Reception test 1" });
    await user.type(within(first).getByLabelText("Reception component type"), "module");
    await user.type(within(first).getByLabelText("Reception test type"), "reception_iv");

    await user.click(screen.getByRole("button", { name: "Add reception test" }));
    const second = screen.getByRole("group", { name: "Reception test 2" });
    await user.type(within(second).getByLabelText("Reception component type"), "module");
    await user.type(
      within(second).getByLabelText("Reception test type"),
      "reception_visual",
    );
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(onSave.mock.calls[0]?.[1].settings.shipment_reception_tests).toEqual({
      MODULE: ["RECEPTION_IV", "RECEPTION_VISUAL"],
    });
    expect(screen.queryByRole("textbox", { name: /json/i })).not.toBeInTheDocument();
  });
});
// ---- Glue-weight judgement editor (plan §9.1/§9.2) --------------------------
//
// Target, tolerance and verdict can only come from the institute profile: the
// PDB grades nothing (automatic grading is off on every module schema, every
// threshold null). These tests pin the saved shape, because that shape is the
// contract the backend adapter reads.

function glueGroup(index: number): HTMLElement {
  return screen.getByRole("group", { name: `Glue step ${index}` });
}

function ruleSetGroup(index: number): HTMLElement {
  return screen.getByRole("group", { name: `Glue rule set ${index}` });
}

function targetGroup(ruleSetIndex: number, index: number): HTMLElement {
  return within(ruleSetGroup(ruleSetIndex)).getByRole("group", {
    name: `Glue target ${index}`,
  });
}

const configuredGlue = {
  glue_weight_inputs: {
    hybrids: {
      label: "Hybrids",
      test_type: "GLUE_WEIGHT",
      measured: "GW_MODULE_H1H2",
      subtract: ["GW_SENSOR", "GW_HYBRID1", "GW_HYBRID2"],
      result_code: "GW_GLUE_H1H2",
    },
  },
  glue_targets: [
    {
      process: "TRUEBLUE",
      label: "True Blue / False Blue",
      valid_from: null,
      module_types: { R5M1: { hybrids: { target_mg: 151, tolerance_mg: 22 } } },
    },
  ],
};

describe("AdminSettingsScreen glue judgement", () => {
  it("reads the stored formula back as words, not as JSON", async () => {
    renderStages([stageInstitute(configuredGlue)], vi.fn().mockResolvedValue(undefined));

    const step = await screen.findByRole("group", { name: "Glue step 1" });
    expect(within(step).getByLabelText("Step key")).toHaveValue("hybrids");
    expect(within(step).getByLabelText("Step name")).toHaveValue("Hybrids");
    expect(within(step).getByLabelText("Test type")).toHaveValue("GLUE_WEIGHT");
    expect(within(step).getByLabelText("Measured weight")).toHaveValue("GW_MODULE_H1H2");
    expect(within(step).getByLabelText("Subtracted weight 1")).toHaveValue("GW_SENSOR");
    expect(within(step).getByLabelText("Subtracted weight 3")).toHaveValue("GW_HYBRID2");
    expect(within(step).getByLabelText("Store result as")).toHaveValue("GW_GLUE_H1H2");
    expect(
      within(step).getByText(
        "GW_GLUE_H1H2 = GW_MODULE_H1H2 − GW_SENSOR − GW_HYBRID1 − GW_HYBRID2",
      ),
    ).toBeInTheDocument();

    // The nested target map is flattened into one row per module type × step.
    const ruleSet = ruleSetGroup(1);
    expect(within(ruleSet).getByLabelText("Glue process")).toHaveValue("TRUEBLUE");
    expect(within(ruleSet).getByText("Always valid")).toBeInTheDocument();
    const target = targetGroup(1, 1);
    expect(within(target).getByLabelText("Module type")).toHaveValue("R5M1");
    expect(within(target).getByLabelText("Step key")).toHaveValue("hybrids");
    expect(within(target).getByLabelText("Target")).toHaveValue(151);
    expect(within(target).getByLabelText("Tolerance")).toHaveValue(22);
  });

  it("loads and saves the canonical process controls from configured rule-set options", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderStages(
      [
        stageInstitute({
          ...configuredGlue,
          glue_default_process: "TRUEBLUE",
          glue_process_property: "GW_PROCESS",
          glue_targets: [
            ...configuredGlue.glue_targets,
            {
              ...configuredGlue.glue_targets[0],
              process: "POLARIS",
              label: "Polaris",
            },
          ],
        }),
      ],
      onSave,
    );

    const defaultProcess = await screen.findByLabelText("Default glue process");
    expect(defaultProcess).toHaveValue("TRUEBLUE");
    expect(
      within(defaultProcess).getAllByRole("option").map((option) => option.getAttribute("value")),
    ).toEqual(["", "POLARIS", "TRUEBLUE"]);
    expect(screen.getByLabelText("Run process property")).toHaveValue("GW_PROCESS");

    await user.selectOptions(defaultProcess, "POLARIS");
    const processProperty = screen.getByLabelText("Run process property");
    await user.clear(processProperty);
    await user.type(processProperty, "glue_process");
    expect(screen.getByText("Unsaved change to the glue judgement.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    const settings = onSave.mock.calls[0]?.[1].settings;
    expect(settings.glue_default_process).toBe("POLARIS");
    expect(settings.glue_process_property).toBe("GLUE_PROCESS");
    expect(settings).not.toHaveProperty("glue_process_default");
  });

  it("serializes cleared configured process controls as null", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderStages(
      [
        stageInstitute({
          ...configuredGlue,
          glue_default_process: "TRUEBLUE",
          glue_process_property: "GW_PROCESS",
        }),
      ],
      onSave,
    );

    await user.selectOptions(await screen.findByLabelText("Default glue process"), "");
    await user.clear(screen.getByLabelText("Run process property"));
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    const settings = onSave.mock.calls[0]?.[1].settings;
    expect(settings.glue_default_process).toBeNull();
    expect(settings.glue_process_property).toBeNull();
  });

  it("rejects a default whose last matching rule set was removed", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderStages(
      [stageInstitute({ ...configuredGlue, glue_default_process: "TRUEBLUE" })],
      onSave,
    );

    await user.click(
      within(ruleSetGroup(1)).getByRole("button", { name: "Remove rule set" }),
    );
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    expect(
      await screen.findByText("Default glue process must match a configured rule set."),
    ).toBeInTheDocument();
    expect(onSave).not.toHaveBeenCalled();
  });

  it("reads the legacy default but migrates it to the canonical key on save", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderStages(
      [stageInstitute({ ...configuredGlue, glue_process_default: "trueblue" })],
      onSave,
    );

    expect(await screen.findByLabelText("Default glue process")).toHaveValue("TRUEBLUE");
    const nameInput = screen.getByLabelText("Institute name");
    await user.clear(nameInput);
    await user.type(nameInput, "Alpha Updated");
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    const settings = onSave.mock.calls[0]?.[1].settings;
    expect(settings.glue_default_process).toBe("TRUEBLUE");
    expect(settings).not.toHaveProperty("glue_process_default");
    expect(settings).not.toHaveProperty("glue_process_property");
  });

  it("saves the §9.1/§9.2 shape, with valid_from making a second generation judgeable", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderStages([stageInstitute(configuredGlue)], onSave);

    // A second rule set for the same process, valid from a date: the live
    // production sheet really does run two generations side by side.
    await user.click(await screen.findByRole("button", { name: "Add rule set" }));
    const added = ruleSetGroup(2);
    await user.type(within(added).getByLabelText("Glue process"), "trueblue");
    await user.type(within(added).getByLabelText("Display name"), "True Blue (2023 revision)");
    fireEvent.change(within(added).getByLabelText("Valid from"), {
      target: { value: "2023-10-24" },
    });
    await user.click(within(added).getByRole("button", { name: "Add target" }));
    const newTarget = targetGroup(2, 1);
    await user.type(within(newTarget).getByLabelText("Module type"), "r5m1");
    await user.type(within(newTarget).getByLabelText("Step key"), "hybrids");
    await user.type(within(newTarget).getByLabelText("Target"), "154");
    await user.type(within(newTarget).getByLabelText("Tolerance"), "15.4");

    expect(screen.getByText("Unsaved change to the glue judgement.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    const settings = onSave.mock.calls[0]?.[1].settings;
    expect(settings.glue_weight_inputs).toEqual({
      hybrids: {
        label: "Hybrids",
        test_type: "GLUE_WEIGHT",
        measured: "GW_MODULE_H1H2",
        subtract: ["GW_SENSOR", "GW_HYBRID1", "GW_HYBRID2"],
        result_code: "GW_GLUE_H1H2",
      },
    });
    expect(settings.glue_targets).toEqual([
      {
        process: "TRUEBLUE",
        label: "True Blue / False Blue",
        valid_from: null,
        module_types: { R5M1: { hybrids: { target_mg: 151, tolerance_mg: 22 } } },
      },
      {
        process: "TRUEBLUE",
        label: "True Blue (2023 revision)",
        valid_from: "2023-10-24",
        module_types: { R5M1: { hybrids: { target_mg: 154, tolerance_mg: 15.4 } } },
      },
    ]);
  });

  it("keeps a dated rule dated when the API hands back its canonical timestamp", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    // What the API actually stores after normalising "2023-10-24".
    renderStages(
      [
        stageInstitute({
          ...configuredGlue,
          glue_targets: [
            { ...configuredGlue.glue_targets[0], valid_from: "2023-10-24T00:00:00+00:00" },
          ],
        }),
      ],
      onSave,
    );

    const ruleSet = await screen.findByRole("group", { name: "Glue rule set 1" });
    // A date input silently rejects a full timestamp and renders blank — the
    // rule would then look undated and be saved as the always-valid fallback,
    // re-judging every historical run against it.
    expect(within(ruleSet).getByLabelText("Valid from")).toHaveValue("2023-10-24");
    expect(within(ruleSet).queryByText("Always valid")).not.toBeInTheDocument();

    await user.type(within(ruleSet).getByLabelText("Display name"), " v1");
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(onSave.mock.calls[0]?.[1].settings.glue_targets[0].valid_from).toBe("2023-10-24");
  });

  it("builds a whole formula from scratch and normalises what the admin typed", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderStages([stageInstitute({})], onSave);

    expect(await screen.findByText("No glue formula configured.")).toBeInTheDocument();
    expect(screen.getByText("No glue targets configured.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Add glue step" }));
    const step = glueGroup(1);
    await user.type(within(step).getByLabelText("Step key"), "powerboard");
    await user.type(within(step).getByLabelText("Measured weight"), "gw_module_h1h2pb");
    await user.type(within(step).getByLabelText("Store result as"), "gw_glue_pb");
    await user.click(within(step).getByRole("button", { name: "Add subtracted weight" }));
    await user.type(within(step).getByLabelText("Subtracted weight 1"), "gw_module_h1h2");
    await user.click(within(step).getByRole("button", { name: "Add subtracted weight" }));
    await user.type(within(step).getByLabelText("Subtracted weight 2"), "gw_pb");
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    const settings = onSave.mock.calls[0]?.[1].settings;
    expect(settings.glue_weight_inputs).toEqual({
      powerboard: {
        measured: "GW_MODULE_H1H2PB",
        subtract: ["GW_MODULE_H1H2", "GW_PB"],
        result_code: "GW_GLUE_PB",
      },
    });
    // Nothing was entered under targets, and the profile never had the key —
    // so it stays absent rather than being written as "explicitly none".
    expect(settings).not.toHaveProperty("glue_targets");
  });

  it("does not touch a profile's glue keys during an unrelated save", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderStages([stageInstitute({})], onSave);

    const nameInput = await screen.findByLabelText("Institute name");
    await user.clear(nameInput);
    await user.type(nameInput, "Alpha Updated");
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    const settings = onSave.mock.calls[0]?.[1].settings;
    // Writing anything here would change how every module's glue verdict is
    // reached without anybody asking for it.
    expect(settings).not.toHaveProperty("glue_weight_inputs");
    expect(settings).not.toHaveProperty("glue_targets");
    expect(settings).not.toHaveProperty("glue_default_process");
    expect(settings).not.toHaveProperty("glue_process_default");
    expect(settings).not.toHaveProperty("glue_process_property");
    expect(screen.queryByText("Unsaved change to the glue judgement.")).not.toBeInTheDocument();
  });

  it("preserves and canonicalizes a hidden R2 input override during an unrelated save", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    const sourceOverride = {
      measured: "gw_module_h1",
      subtract: ["gw_sensor", "gw_hybrid1"],
      result_code: null,
    };
    renderStages(
      [
        stageInstitute({
          ...configuredGlue,
          glue_weight_inputs: {
            hybrids: {
              ...configuredGlue.glue_weight_inputs.hybrids,
              by_type_code: { r2: sourceOverride },
            },
          },
        }),
      ],
      onSave,
    );

    const nameInput = await screen.findByLabelText("Institute name");
    await user.clear(nameInput);
    await user.type(nameInput, "Alpha Updated");
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    const settings = onSave.mock.calls[0]?.[1].settings;
    expect(settings.glue_weight_inputs).toEqual({
      hybrids: {
        label: "Hybrids",
        test_type: "GLUE_WEIGHT",
        measured: "GW_MODULE_H1H2",
        subtract: ["GW_SENSOR", "GW_HYBRID1", "GW_HYBRID2"],
        result_code: "GW_GLUE_H1H2",
        by_type_code: {
          R2: {
            measured: "GW_MODULE_H1",
            subtract: ["GW_SENSOR", "GW_HYBRID1"],
            result_code: null,
          },
        },
      },
    });
    const savedOverride = settings.glue_weight_inputs?.hybrids?.by_type_code?.R2;
    expect(savedOverride).not.toBe(sourceOverride);
    expect(savedOverride?.subtract).not.toBe(sourceOverride.subtract);
  });

  it("clears a configured formula with null to disable input-based derivation", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderStages([stageInstitute(configuredGlue)], onSave);

    const step = await screen.findByRole("group", { name: "Glue step 1" });
    await user.click(within(step).getByRole("button", { name: "Remove" }));
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    // An empty object is rejected by the API on purpose; null explicitly
    // disables input-based derivation for this profile.
    expect(onSave.mock.calls[0]?.[1].settings.glue_weight_inputs).toBeNull();
  });

  it("flags a target whose step no formula produces, instead of saving a rule nothing can meet", async () => {
    const user = userEvent.setup();
    renderStages([stageInstitute(configuredGlue)], vi.fn().mockResolvedValue(undefined));

    await screen.findByRole("group", { name: "Glue rule set 1" });
    const target = targetGroup(1, 1);
    const stepKey = within(target).getByLabelText("Step key");
    expect(within(target).queryByText("Not in the formula")).not.toBeInTheDocument();

    await user.clear(stepKey);
    await user.type(stepKey, "powerboard");
    expect(within(target).getByText("Not in the formula")).toBeInTheDocument();
    expect(stepKey).toHaveAttribute("aria-describedby");
  });

  it("refuses a malformed rule set rather than saving an unjudgeable profile", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderStages([stageInstitute(configuredGlue)], onSave);

    await screen.findByRole("group", { name: "Glue rule set 1" });
    await user.clear(within(targetGroup(1, 1)).getByLabelText("Target"));
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Target must be 0-100000 mg.");
    expect(onSave).not.toHaveBeenCalled();
  });

  it("refuses a step that would overwrite one of its own inputs", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderStages([stageInstitute(configuredGlue)], onSave);

    const step = await screen.findByRole("group", { name: "Glue step 1" });
    const resultCode = within(step).getByLabelText("Store result as");
    await user.clear(resultCode);
    await user.type(resultCode, "GW_SENSOR");
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    // Otherwise the derived value lands on a scale reading, and the next
    // derivation reads its own output back as an input.
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Store result as duplicates GW_SENSOR.",
    );
    expect(onSave).not.toHaveBeenCalled();
  });
});


// The one setting that makes itkFlow contact the PDB on its own, without
// anyone asking for it at that moment. Everything here guards the same thing
// from two sides: it must be off unless somebody deliberately switches it on,
// and what it does must be readable on the screen rather than in a doc.
const overnightSchedule = {
  enabled: true,
  interval_minutes: 120,
  window_start: "22:00",
  window_end: "06:00",
  weekdays: [5, 6],
};

function intervalField(): HTMLElement {
  return screen.getByLabelText(/Refresh when the last sync is older than/);
}

describe("AdminSettingsScreen scheduled sync", () => {
  it("shows a malformed enabled block as off and preserves it on an unrelated save", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderStages(
      [stageInstitute({ auto_sync: { enabled: true, interval_minutes: "often" } })],
      onSave,
    );

    expect(
      await screen.findByLabelText("Refresh this institute on a schedule"),
    ).not.toBeChecked();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Stored scheduled-sync settings are invalid and off.",
    );

    const nameInput = screen.getByLabelText("Institute name");
    await user.clear(nameInput);
    await user.type(nameInput, "Alpha Updated");
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(onSave.mock.calls[0]?.[1].settings).not.toHaveProperty("auto_sync");
  });

  it("shows an unconfigured institute as off and saves no schedule at all", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderStages([alpha], onSave);

    const toggle = await screen.findByLabelText("Refresh this institute on a schedule");
    expect(toggle).not.toBeChecked();
    expect(screen.getByText("Off: only a person starts a sync.")).toBeInTheDocument();
    expect(screen.getByText("No window: any time of day.")).toBeInTheDocument();

    const nameInput = screen.getByLabelText("Institute name");
    await user.clear(nameInput);
    await user.type(nameInput, "Alpha Updated");
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    // Not `{enabled: false}` either: a profile nobody configured must not gain
    // a schedule — not even a switched-off one — from an unrelated save.
    expect(onSave.mock.calls[0]?.[1].settings).not.toHaveProperty("auto_sync");
  });

  it("renders a stored overnight schedule as an overnight schedule", async () => {
    renderStages([stageInstitute({ auto_sync: overnightSchedule })], vi.fn());

    expect(
      await screen.findByLabelText("Refresh this institute on a schedule"),
    ).toBeChecked();
    expect(screen.getByText("On: itkFlow contacts the PDB by itself.")).toBeInTheDocument();
    expect(intervalField()).toHaveValue(120);
    expect(screen.getByLabelText("Window start")).toHaveValue("22:00");
    expect(screen.getByLabelText("Window end")).toHaveValue("06:00");
    // 22:00–06:00 is a night shift, not an empty set. If this ever reads as a
    // complaint about the order, somebody has "fixed" a start-before-end rule
    // into the editor.
    expect(screen.getByText("Overnight window 22:00 to 06:00.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Friday" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: "Saturday" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: "Monday" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("saves an overnight schedule with weekdays toggled by keyboard", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderStages([alpha], onSave);

    await user.click(await screen.findByLabelText("Refresh this institute on a schedule"));
    await user.clear(intervalField());
    await user.type(intervalField(), "30");
    fireEvent.change(screen.getByLabelText("Window start"), {
      target: { value: "22:00" },
    });
    fireEvent.change(screen.getByLabelText("Window end"), { target: { value: "06:00" } });
    // No pointer: the toggles have to work for someone whose hands are on the
    // keyboard, like every other control on this screen.
    screen.getByRole("button", { name: "Saturday" }).focus();
    await user.keyboard("{Enter}");
    screen.getByRole("button", { name: "Sunday" }).focus();
    await user.keyboard(" ");
    expect(screen.getByRole("button", { name: "Saturday" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(screen.getByText("Unsaved scheduled-sync change.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(onSave.mock.calls[0]?.[1].settings.auto_sync).toEqual({
      enabled: true,
      interval_minutes: 30,
      window_start: "22:00",
      window_end: "06:00",
      weekdays: [1, 2, 3, 4, 5],
    });
  });

  it("states every day as null rather than as a list of all seven", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderStages([alpha], onSave);

    await user.click(await screen.findByLabelText("Refresh this institute on a schedule"));
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(onSave.mock.calls[0]?.[1].settings.auto_sync).toEqual({
      enabled: true,
      interval_minutes: 60,
      window_start: null,
      window_end: null,
      weekdays: null,
    });
  });

  it("switches a configured schedule off without losing what it says", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderStages([stageInstitute({ auto_sync: overnightSchedule })], onSave);

    await user.click(await screen.findByLabelText("Refresh this institute on a schedule"));
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(onSave.mock.calls[0]?.[1].settings.auto_sync).toEqual({
      ...overnightSchedule,
      enabled: false,
    });
  });

  it("refuses an interval below the floor instead of speeding the profile up", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderStages([alpha], onSave);

    await user.click(await screen.findByLabelText("Refresh this institute on a schedule"));
    await user.clear(intervalField());
    await user.type(intervalField(), "5");
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Refresh when the last sync is older than must be 15-10080.",
    );
    expect(onSave).not.toHaveBeenCalled();
  });

  it("refuses one window time without the other", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderStages([alpha], onSave);

    await user.click(await screen.findByLabelText("Refresh this institute on a schedule"));
    fireEvent.change(screen.getByLabelText("Window start"), {
      target: { value: "07:00" },
    });
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Set both window times, or neither.",
    );
    expect(onSave).not.toHaveBeenCalled();
  });

  it("refuses a window that starts and ends at the same minute", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderStages([alpha], onSave);

    await user.click(await screen.findByLabelText("Refresh this institute on a schedule"));
    fireEvent.change(screen.getByLabelText("Window start"), {
      target: { value: "07:00" },
    });
    fireEvent.change(screen.getByLabelText("Window end"), { target: { value: "07:00" } });
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Window start and end must differ.",
    );
    expect(onSave).not.toHaveBeenCalled();
  });

  it("refuses an empty weekday selection instead of sending it as every day", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderStages([stageInstitute({ auto_sync: overnightSchedule })], onSave);

    await screen.findByLabelText("Refresh this institute on a schedule");
    await user.click(screen.getByRole("button", { name: "Friday" }));
    await user.click(screen.getByRole("button", { name: "Saturday" }));
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    // An empty list reads as "every day" on the server. Unticking everything
    // means the opposite, so it must never reach the API.
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Select at least one weekday.",
    );
    expect(onSave).not.toHaveBeenCalled();
  });

  it("says in the shipped English copy what switching this on actually does", async () => {
    render(
      <AdminSettingsScreen
        institutes={[alpha]}
        selectedCode="ALPHA"
        onSelectedCodeChange={vi.fn()}
        onSave={vi.fn().mockResolvedValue(undefined)}
        onTestChannel={vi.fn().mockResolvedValue(undefined)}
        loadKnownTestTypes={noTestTypes}
        labels={t.adminSettings}
      />,
    );

    // These four statements are the point of the section, not decoration: what
    // it does, whose access it uses, which clock it reads, and that an
    // overnight window is meant to be possible.
    expect(
      await screen.findByText(/without anyone asking for it at that moment/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/succeeded most recently/i)).toBeInTheDocument();
    expect(screen.getByText(/server.s own clock/i)).toBeInTheDocument();
    expect(screen.getByText(/22:00 to 06:00 runs overnight only/i)).toBeInTheDocument();
  });
});
