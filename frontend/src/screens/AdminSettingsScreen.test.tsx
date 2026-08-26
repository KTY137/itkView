import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { Institute } from "../api";
import AdminSettingsScreen from "./AdminSettingsScreen";
import type { AdminSettingsLabels } from "./AdminSettingsScreen";

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
