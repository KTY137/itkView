import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { Institute } from "../api";
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
  evidenceTitle: "Evidence mirror",
  evidenceHint: "Mirrored component types.",
  evidenceEmpty: "No evidence types.",
  addEvidenceType: "Add evidence type",
  evidenceTypeLabel: (index) => `Evidence type ${index}`,
  evidenceTypePlaceholder: "MODULE",
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
