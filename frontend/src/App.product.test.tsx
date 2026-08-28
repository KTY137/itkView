import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ComponentOut, Institute, Shipment } from "./api";

const authState = vi.hoisted(() => ({
  current: {
    status: "authenticated",
    user: {
      id: 1,
      email: "admin@example.org",
      display_name: "View Admin",
      role: "admin",
      institute_id: 1,
      institute_code: "TUDO",
      active: true,
      created_at: "2026-08-28T08:00:00Z",
      csrf_token: "csrf",
    },
    csrfToken: "csrf",
    role: "admin",
    canWrite: true,
    canSync: true,
    isAdmin: true,
    demo: false,
    login: vi.fn(),
    bootstrapAdmin: vi.fn(),
    logout: vi.fn(),
    enterDemo: vi.fn(),
    showToast: vi.fn(),
  },
}));

const componentController = vi.hoisted(() => ({
  kind: "components" as const,
  job: null,
  active: false,
  discovering: false,
  starting: false,
  startError: null,
  pollError: null,
  dataEpoch: 0,
  start: vi.fn().mockResolvedValue(undefined),
  dismiss: vi.fn(),
}));

const evidenceController = vi.hoisted(() => ({
  kind: "evidence" as const,
  job: null,
  active: false,
  discovering: false,
  starting: false,
  startError: null,
  pollError: null,
  dataEpoch: 0,
  start: vi.fn().mockResolvedValue(undefined),
  dismiss: vi.fn(),
}));

vi.mock("./auth", () => ({ useAuth: () => authState.current }));

vi.mock("./componentSync", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./componentSync")>()),
  useComponentSyncJob: () => componentController,
  useEvidenceSyncJob: () => evidenceController,
}));

vi.mock("./api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./api")>();
  return {
    ...actual,
    getInstitutes: vi.fn(),
    getComponents: vi.fn(),
    getComponentThumbnails: vi.fn(),
    getComponent: vi.fn(),
    getComponentPreview: vi.fn(),
    getComponentStaged: vi.fn(),
    getStageSuggestion: vi.fn(),
    getTestTypeSchemas: vi.fn(),
    getComponentAttachments: vi.fn(),
    getComponentTests: vi.fn(),
    getDashboardSummary: vi.fn(),
    getTools: vi.fn(),
    getShipments: vi.fn(),
    getOpsHealth: vi.fn(),
  };
});

const institute: Institute = {
  id: 1,
  code: "TUDO",
  name: "Test institute",
  local_name_prefix: "TUDO-",
  settings: {
    notification_channels: {
      operations: {
        kind: "mattermost",
        url: "***",
        channel: "lab-operations",
      },
    },
  },
  created_at: "2026-08-28T08:00:00Z",
};

const component: ComponentOut = {
  sn: "20USEM00000001",
  local_name: "TUDO-M-001",
  component_type: "MODULE",
  type_code: "BM",
  stage: "GLUED",
  location: "TUDO",
  institute_code: "TUDO",
  parent_sn: null,
  is_dummy: true,
  trashed: false,
  stale: false,
  synced_at: "2026-08-28T08:00:00Z",
  production_status: "clear",
  production_status_reasons: [],
};

const shipment: Shipment = {
  id: 4,
  pdb_id: "shipment-4",
  name: "Incoming modules",
  sender_code: "SENDER",
  recipient_code: "TUDO",
  status: "delivered",
  direction: "incoming",
  sent_at: "2026-08-26T08:00:00Z",
  items: [
    {
      sn: component.sn,
      component_type: "MODULE",
      component_mirrored: true,
      is_dummy: false,
      submittable: false,
      submittable_reason: "not_dummy",
      reception_tests_configured: true,
      reception_test_status: "missing",
      reception_tests: [{ test_type: "RECEPTION_IV", status: "missing" }],
    },
  ],
  institute_id: 1,
  synced_at: "2026-08-26T08:05:00Z",
  reception_status: "in_progress",
  reception_checklist: [{ label: "Packaging intact", done: true }],
  reception_items: [{ sn: component.sn, received: true, note: null }],
  reception_note: null,
  reception_by: "receiver@example.org",
  reception_updated_at: "2026-08-26T08:10:00Z",
  reception_tests_configured: true,
  reception_test_status: "missing",
};

async function loadApp(variant: "flow" | "view") {
  vi.stubEnv("VITE_ITKFLOW_PRODUCT_VARIANT", variant);
  vi.resetModules();

  const api = await import("./api");
  vi.mocked(api.getInstitutes).mockResolvedValue([institute]);
  vi.mocked(api.getComponents).mockResolvedValue([component]);
  vi.mocked(api.getComponentThumbnails).mockResolvedValue({});
  vi.mocked(api.getComponent).mockResolvedValue({ ...component, children: [] });
  vi.mocked(api.getStageSuggestion).mockResolvedValue({
    sn: component.sn,
    current_stage: "GLUED",
    next_stage: "BONDED",
    move_suggested: true,
    suggested_stage: "BONDED",
    checks: [{ stage: "GLUED", test_type: "MODULE_METROLOGY", status: "missing" }],
    blocking: [],
  });
  vi.mocked(api.getComponentPreview).mockResolvedValue({
    current: { stage: "GLUED", checks: [] },
    staged_actions: [
      {
        id: 55,
        kind: "upload_test_run",
        status: "draft",
        summary: "Staged glue weight",
        to_stage: null,
        test_type: "GLUE_WEIGHT",
        created_by: "operator@example.org",
        created_at: "2026-08-28T08:00:00Z",
        submittable: true,
        submittable_reason: null,
      },
    ],
    projected: {
      stage: "GLUED",
      checks: [],
      ghost_tests: [
        {
          test_type: "GLUE_WEIGHT",
          passed: null,
          external_ref: null,
          measured_at: null,
          synced_at: null,
          source: "outbox",
          run_number: null,
          properties: {},
          results: { GLUE_WEIGHT: 12.3 },
          result_meta: {},
          attachments: [],
          ghost: true,
          outbox_action_id: 55,
        },
      ],
    },
    worksheet: {
      groups: [
        {
          stage: "GLUED",
          reached: true,
          rows: [
            {
              test_type: "GLUE_WEIGHT",
              status: "missing",
              latest: null,
              staged: [{ outbox_action_id: 55, status: "draft" }],
              run_count: 0,
            },
          ],
        },
      ],
    },
  });
  vi.mocked(api.getComponentStaged).mockResolvedValue([]);
  vi.mocked(api.getTestTypeSchemas).mockResolvedValue([]);
  vi.mocked(api.getComponentAttachments).mockResolvedValue({
    component_sn: component.sn,
    attachments: [],
    children: [],
  });
  vi.mocked(api.getComponentTests).mockResolvedValue([]);
  vi.mocked(api.getDashboardSummary).mockResolvedValue({
    total_components: 1,
    last_synced_at: component.synced_at,
    oldest_synced_at: component.synced_at,
    stale_components: 0,
    trashed_components: 0,
    required_test_gaps: 1,
    components_with_test_gaps: 1,
    submitted_outbox: 1,
    approved_outbox: 1,
    review_outbox: 1,
    failed_outbox: 1,
    by_stage: [{ label: "GLUED", count: 1 }],
    by_component_type: [{ label: "MODULE", count: 1 }],
    by_institute: [{ label: "TUDO", count: 1 }],
    outbox_by_status: [{ label: "draft", count: 1 }],
  });
  vi.mocked(api.getTools).mockResolvedValue([
    {
      id: 7,
      institute_id: 1,
      kind: "jig",
      code: "JIG-07",
      label: "Assembly jig",
      rfid: "RFID-07",
      compatible_types: ["BM"],
      status: "active",
      created_at: "2026-08-28T08:00:00Z",
    },
  ]);
  vi.mocked(api.getShipments).mockResolvedValue([shipment]);
  vi.mocked(api.getOpsHealth).mockResolvedValue({
    status: "healthy",
    generated_at: "2026-08-28T08:00:00Z",
    institute_code: "TUDO",
    heartbeats: [],
    sync: { active: [], stale_active: 0, latest: [] },
    outbox: {
      backlog: 2,
      failed: 1,
      at_attempt_limit: 0,
      oldest_open_at: null,
      oldest_open_age_seconds: null,
    },
    reminders: {
      active: 0,
      open_occurrences: 0,
      failed_occurrences: 0,
      escalated_open: 0,
      overdue: 0,
    },
    ingest: { total: 2, triage: 1, failed: 0, parser_issues: 1, unassigned: 0 },
  });

  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      statusText: "OK",
      json: vi.fn().mockResolvedValue({
        status: "ok",
        app: variant === "view" ? "itkView" : "itkFlow",
        version: "0.2.8",
        pdb_instance: "production",
      }),
    }),
  );

  const App = (await import("./App")).default;
  return { App, api };
}

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

describe("compile-time product UI", () => {
  it("keeps the existing itkFlow navigation and authoring entry points", async () => {
    authState.current.canWrite = true;
    const { App } = await loadApp("flow");
    const user = userEvent.setup();
    render(<App />);

    expect(document.querySelector(".rail .brand")).toHaveTextContent("itkFlow");
    expect(screen.getByRole("button", { name: "Ingest log" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Staged" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Record assembly step" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Components" }));
    expect(await screen.findByText("TUDO-M-001")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Register module/ })).toBeInTheDocument();
  });

  it("brands itkView, keeps mirror sync/viewing, and removes workflow writers", async () => {
    authState.current.canWrite = false;
    authState.current.canSync = true;
    const { App, api } = await loadApp("view");
    const user = userEvent.setup();
    render(<App />);

    expect(document.querySelector(".rail .brand")).toHaveTextContent("itkView");
    expect(document.querySelector(".rail .brand")).toHaveTextContent("read-only");
    expect(screen.getByText("itkView", { selector: ".crumb b" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Ingest log" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Staged" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Record assembly step" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Components" }));
    expect(await screen.findByText("TUDO-M-001")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sync components & evidence" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Refresh test evidence" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Register module/ })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "TUDO-M-001" }));
    expect(await screen.findByRole("heading", { name: "TUDO-M-001" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Refresh test evidence" })).toBeInTheDocument();
    expect(
      await screen.findByRole("heading", { name: "Metrology & inspection images" }),
    ).toBeInTheDocument();
    expect(screen.getByText("All mirrored runs")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Record MODULE_METROLOGY result/ })).not.toBeInTheDocument();
    expect(screen.queryByText("Staged upload · action #55")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Push to PDB" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Discard" })).not.toBeInTheDocument();
    expect(api.getComponentStaged).not.toHaveBeenCalled();
    expect(api.getTestTypeSchemas).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Dashboard" }));
    expect(await screen.findByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
    expect(screen.queryByText("Needs review")).not.toBeInTheDocument();
    expect(screen.queryByText("Staged actions by status")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Tools & jigs" }));
    const toolRow = (await screen.findByText("JIG-07")).closest("tr") as HTMLTableRowElement;
    expect(screen.getByRole("button", { name: "Sync tools from mirror" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add tool" })).not.toBeInTheDocument();
    expect(within(toolRow).queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Shipments" }));
    expect(await screen.findByText("Incoming modules")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sync from PDB" })).toBeInTheDocument();
    await user.click(screen.getByText("Incoming modules"));
    const shipmentDetail = await screen.findByRole("region", { name: "Shipment detail" });
    expect(screen.queryByRole("button", { name: "Record test" })).not.toBeInTheDocument();
    expect(screen.queryByText(/record and stage this result/i)).not.toBeInTheDocument();
    expect(within(shipmentDetail).queryByRole("checkbox")).not.toBeInTheDocument();
    expect(within(shipmentDetail).queryByRole("textbox")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Operations health" }));
    expect(await screen.findByRole("heading", { name: "Operations health" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Open Staged" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Open Ingest log" })).not.toBeInTheDocument();
    expect(screen.queryByText("Staged backlog")).not.toBeInTheDocument();
    expect(screen.queryByText("Parser issues")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open Reminders" })).toBeInTheDocument();

    await waitFor(() => expect(api.getOpsHealth).toHaveBeenCalled());

    await user.click(screen.getByRole("button", { name: "Settings" }));
    expect(await screen.findByRole("heading", { name: "Settings" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save settings" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Test channel" })).not.toBeInTheDocument();
  });
});
