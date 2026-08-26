import { OUTBOX_STATUSES } from "./api";
import type {
  AssemblyDraft,
  AssemblyPreview,
  ComponentDetail,
  ComponentOut,
  CountBucket,
  DashboardSummary,
  GlueBatch,
  GlueUsage,
  IngestFile,
  NotificationChannel,
  OutboxAction,
  ProductionStats,
  Reminder,
  Shipment,
  StatsDimensions,
  Tool,
} from "./api";

/**
 * Built-in demo dataset, used only when the backend is not reachable.
 * All serial numbers, names and people are fictional (anonymized scheme),
 * but shaped like real ITk strip barrel components at a module site.
 */

const SYNCED = "2026-07-08T05:30:00Z";

export const DEMO_COMPONENTS: ComponentOut[] = [
  {
    sn: "20USBML0000101",
    local_name: "TUDO-LS-M-0101",
    component_type: "MODULE",
    type_code: "BML",
    stage: "BONDED",
    location: "TUDO",
    institute_code: "TUDO",
    parent_sn: null,
    is_dummy: false,
    trashed: false,
    stale: false,
    synced_at: SYNCED,
  },
  {
    sn: "20USBSL0000201",
    local_name: "TUDO-SEN-0201",
    component_type: "SENSOR",
    type_code: "SL",
    stage: "AT_MODULE_SITE",
    location: "TUDO",
    institute_code: "TUDO",
    parent_sn: "20USBML0000101",
    is_dummy: false,
    trashed: false,
    stale: false,
    synced_at: SYNCED,
  },
  {
    sn: "20USBHL0000301",
    local_name: "TUDO-HYB-0301",
    component_type: "HYBRID_ASSEMBLY",
    type_code: "HL",
    stage: "BONDED",
    location: "TUDO",
    institute_code: "TUDO",
    parent_sn: "20USBML0000101",
    is_dummy: false,
    trashed: false,
    stale: false,
    synced_at: SYNCED,
  },
  {
    sn: "20USBPB0000401",
    local_name: "TUDO-PB-0401",
    component_type: "POWERBOARD",
    type_code: "PB",
    stage: "LOADED",
    location: "TUDO",
    institute_code: "TUDO",
    parent_sn: "20USBML0000101",
    is_dummy: false,
    trashed: false,
    stale: false,
    synced_at: SYNCED,
  },
  {
    sn: "20USBML0000102",
    local_name: "TUDO-LS-M-0102",
    component_type: "MODULE",
    type_code: "BML",
    stage: "GLUED",
    location: "TUDO",
    institute_code: "TUDO",
    parent_sn: null,
    is_dummy: false,
    trashed: false,
    stale: false,
    synced_at: SYNCED,
  },
  {
    sn: "20USBSL0000202",
    local_name: "TUDO-SEN-0202",
    component_type: "SENSOR",
    type_code: "SL",
    stage: "AT_MODULE_SITE",
    location: "TUDO",
    institute_code: "TUDO",
    parent_sn: "20USBML0000102",
    is_dummy: false,
    trashed: false,
    stale: false,
    synced_at: SYNCED,
  },
  {
    sn: "20USBHL0000302",
    local_name: "TUDO-HYB-0302",
    component_type: "HYBRID_ASSEMBLY",
    type_code: "HL",
    stage: "BONDED",
    location: "TUDO",
    institute_code: "TUDO",
    parent_sn: "20USBML0000102",
    is_dummy: false,
    trashed: false,
    stale: false,
    synced_at: SYNCED,
  },
  {
    sn: "20USBPB0000402",
    local_name: "TUDO-PB-0402",
    component_type: "POWERBOARD",
    type_code: "PB",
    stage: "AT_MODULE_SITE",
    location: "TUDO",
    institute_code: "TUDO",
    parent_sn: null,
    is_dummy: false,
    trashed: false,
    stale: false,
    synced_at: SYNCED,
  },
  {
    sn: "20USBML9990001",
    local_name: "TUDO-DUMMY-M-01",
    component_type: "MODULE",
    type_code: "R5M0",
    stage: "GLUED",
    location: "TUDO",
    institute_code: "TUDO",
    parent_sn: null,
    is_dummy: true,
    trashed: false,
    stale: false,
    synced_at: SYNCED,
  },
  {
    sn: "20USBHL9990002",
    local_name: "TUDO-DUMMY-H-02",
    component_type: "HYBRID",
    type_code: "R5H0",
    stage: "READY",
    location: "TUDO",
    institute_code: "TUDO",
    parent_sn: null,
    is_dummy: true,
    trashed: false,
    stale: false,
    synced_at: SYNCED,
  },
  {
    sn: "20USBSL0000203",
    local_name: "TUDO-SEN-0203",
    component_type: "SENSOR",
    type_code: "SL",
    stage: "AT_MODULE_SITE",
    location: "TUDO",
    institute_code: "TUDO",
    parent_sn: null,
    is_dummy: false,
    trashed: true,
    stale: false,
    synced_at: SYNCED,
  },
];

/** Client-side equivalent of GET /api/components?q=&stage=&institute= for the demo set. */
export function filterDemoComponents(q: string, stage: string, institute = ""): ComponentOut[] {
  const needle = q.trim().toUpperCase();
  return DEMO_COMPONENTS.filter((c) => {
    if (stage !== "" && c.stage !== stage) return false;
    if (institute !== "" && c.institute_code !== institute) return false;
    if (needle === "") return true;
    return (
      c.sn.toUpperCase().includes(needle) ||
      (c.local_name ?? "").toUpperCase().includes(needle)
    );
  });
}

/** Client-side equivalent of GET /api/components/{sn} for the demo set. */
export function getDemoComponent(sn: string): ComponentDetail | null {
  const upper = sn.trim().toUpperCase();
  const found = DEMO_COMPONENTS.find((c) => c.sn.toUpperCase() === upper);
  if (found === undefined) return null;
  return {
    ...found,
    children: DEMO_COMPONENTS.filter((c) => c.parent_sn === found.sn),
  };
}

const DEMO_STAGED_ASSEMBLIES: OutboxAction[] = [];

export function stageDemoAssemblyAction(
  draft: AssemblyDraft,
  preview: AssemblyPreview,
): OutboxAction {
  const timestamp = new Date().toISOString();
  const action: OutboxAction = {
    id: 8_000 + DEMO_STAGED_ASSEMBLIES.length,
    institute_id: 1,
    kind: "assemble_component",
    payload: {
      ...draft,
      expected_parent_component_type: preview.parent?.component_type,
      expected_parent_type_code: preview.parent?.type_code,
      expected_parent_stage: preview.parent?.stage,
      expected_parent_location: preview.parent?.location,
      expected_parent_institute_code: preview.parent?.institute_code,
      expected_child_component_type: preview.child?.component_type,
      expected_child_type_code: preview.child?.type_code,
      expected_child_parent_sn: preview.child?.parent_sn,
      expected_child_location: preview.child?.location,
      expected_child_institute_code: preview.child?.institute_code,
      expected_tool_code: preview.tool?.code,
      expected_glue_batch_no: preview.glue_batch?.batch_no,
      pdb_properties: preview.pdb_properties,
      dry_run_required: true,
    },
    status: "draft",
    error: null,
    attempts: 0,
    created_by: "demo.operator@example.org",
    external_ref: null,
    created_at: timestamp,
    updated_at: timestamp,
  };
  DEMO_STAGED_ASSEMBLIES.push(action);
  return { ...action, payload: { ...action.payload } };
}

/** Fresh copy of the demo outbox so local (demo) transitions can mutate it. */
export function makeDemoOutbox(): OutboxAction[] {
  return [
    {
      id: 101,
      institute_id: 1,
      kind: "assembleModule",
      payload: { parent: "20USBML0000102", child: "20USBPB0000402", slot: "PB" },
      status: "draft",
      error: null,
      attempts: 0,
      created_by: "anna.abel",
      external_ref: null,
      created_at: "2026-07-08T06:02:00Z",
      updated_at: "2026-07-08T06:02:00Z",
    },
    {
      id: 102,
      institute_id: 1,
      kind: "uploadTestRun",
      payload: { sn: "20USBHL0000301", testType: "PEDESTAL_TRIM" },
      status: "validated",
      error: null,
      attempts: 0,
      created_by: "bruno.becker",
      external_ref: null,
      created_at: "2026-07-08T06:05:00Z",
      updated_at: "2026-07-08T06:10:00Z",
    },
    {
      id: 103,
      institute_id: 1,
      kind: "setStage",
      payload: { sn: "20USBML0000101", stage: "BONDED" },
      status: "approved",
      error: null,
      attempts: 0,
      created_by: "anna.abel",
      external_ref: null,
      created_at: "2026-07-08T06:12:00Z",
      updated_at: "2026-07-08T06:20:00Z",
    },
    {
      id: 104,
      institute_id: 1,
      kind: "uploadTestRun",
      payload: { sn: "20USBML0000101", testType: "MODULE_METROLOGY" },
      status: "submitted",
      error: null,
      attempts: 1,
      created_by: "carla.curie",
      external_ref: null,
      created_at: "2026-07-08T06:25:00Z",
      updated_at: "2026-07-08T06:30:00Z",
    },
    {
      id: 105,
      institute_id: 1,
      kind: "createShipment",
      payload: { recipient: "DESYZ", items: ["20USBSL0000203"] },
      status: "failed",
      error: "PDB rejected shipment: component is trashed",
      attempts: 3,
      created_by: "bruno.becker",
      external_ref: null,
      created_at: "2026-07-07T15:40:00Z",
      updated_at: "2026-07-08T05:55:00Z",
    },
    {
      id: 106,
      institute_id: 1,
      kind: "assembleModule",
      payload: { parent: "20USBML0000101", child: "20USBHL0000301", slot: "H0" },
      status: "confirmed",
      error: null,
      attempts: 1,
      created_by: "anna.abel",
      external_ref: "PDB-RUN-2041",
      created_at: "2026-07-07T14:00:00Z",
      updated_at: "2026-07-07T14:05:00Z",
    },
    {
      id: 107,
      institute_id: 1,
      kind: "setStage",
      payload: { sn: "20USBML9990001", stage: "FINISHED" },
      status: "cancelled",
      error: null,
      attempts: 0,
      created_by: "carla.curie",
      external_ref: null,
      created_at: "2026-07-07T13:10:00Z",
      updated_at: "2026-07-07T13:15:00Z",
    },
    {
      id: 108,
      institute_id: 1,
      kind: "stage_move",
      payload: { sn: "20USBML9990001", to_stage: "FINISHED" },
      status: "draft",
      error: null,
      attempts: 0,
      created_by: "anna.abel",
      external_ref: null,
      created_at: "2026-07-08T07:20:00Z",
      updated_at: "2026-07-08T07:20:00Z",
    },
    ...DEMO_STAGED_ASSEMBLIES.map((action) => ({
      ...action,
      payload: { ...action.payload },
    })),
  ];
}

export function makeDemoIngestFiles(): IngestFile[] {
  return [
    {
      id: 201,
      filename: "module-metrology-demo.json",
      sha256: "0".repeat(64),
      size_bytes: 2140,
      status: "received",
      component_sn: "20USBML0000101",
      test_type: "MODULE_METROLOGY",
      parser: "generic-json-v0",
      error: null,
      outbox_action_id: null,
      uploaded_by: "anna.abel",
      created_at: "2026-07-08T07:05:00Z",
      updated_at: "2026-07-08T07:05:00Z",
    },
    {
      id: 202,
      filename: "unknown-instrument-output.json",
      sha256: "1".repeat(64),
      size_bytes: 986,
      status: "triage",
      component_sn: null,
      test_type: null,
      parser: "generic-json-v0",
      error: "Missing component serial number, test type.",
      outbox_action_id: null,
      uploaded_by: "bruno.becker",
      created_at: "2026-07-08T07:10:00Z",
      updated_at: "2026-07-08T07:10:00Z",
    },
  ];
}

const DEMO_TOOLS: Tool[] = [
  { kind: "jig", code: "HV-TAB-JIG-R5", label: "HV tab jig R5", rfid: "E28011700000000000000001", compatible_types: ["R5M0", "R5M1"] },
  { kind: "jig", code: "HV-TAB-JIG-R2", label: "HV tab jig R2", rfid: "E28011700000000000000002", compatible_types: ["R2"] },
  { kind: "pickup_tool", code: "PICKUP-R5", label: "Pickup R5", rfid: "E28011700000000000000003", compatible_types: ["R5M0", "R5M1"] },
  { kind: "pickup_tool", code: "PICKUP-R2", label: "Pickup R2", rfid: "E28011700000000000000004", compatible_types: ["R2"] },
  { kind: "panel", code: "GLUE-PANEL-R5-01", label: "Glue panel R5", rfid: null, compatible_types: ["R5M0", "R5M1"] },
].map((spec, index) => ({
  id: 900 + index,
  institute_id: 1,
  status: "active",
  created_at: SYNCED,
  ...spec,
}));

export function makeDemoTools(): Tool[] {
  return DEMO_TOOLS.map((tool) => ({
    ...tool,
    compatible_types: [...tool.compatible_types],
  }));
}

export function filterDemoTools(kind: string, fits: string): Tool[] {
  return makeDemoTools().filter(
    (tool) =>
      (kind === "" || tool.kind === kind) &&
      (fits === "" || tool.compatible_types.includes(fits)),
  );
}

/** Offline equivalent of GET /api/tools/scan — match by code or RFID. */
export function scanDemoTool(code: string): Tool | null {
  const needle = code.trim().toUpperCase();
  return (
    makeDemoTools().find(
      (tool) =>
        tool.code.toUpperCase() === needle || (tool.rfid ?? "").toUpperCase() === needle,
    ) ?? null
  );
}

export function scanDemoComponent(code: string): ComponentOut | null {
  const needle = code.trim().toUpperCase();
  return (
    DEMO_COMPONENTS.find(
      (component) =>
        component.sn.toUpperCase() === needle ||
        (component.local_name ?? "").toUpperCase() === needle,
    ) ?? null
  );
}

export function makeDemoAssemblyPreview(
  parent: ComponentOut,
  child: ComponentOut,
  tool: Tool,
  glue: GlueBatch | null,
  slot: string,
): AssemblyPreview {
  const issues: AssemblyPreview["issues"] = [];
  const safeTypes = new Set(["MODULE", "HYBRID"]);
  if (!safeTypes.has(parent.component_type)) {
    issues.push({ code: "parent_type_not_allowed", message: "Parent must be a module or hybrid." });
  }
  if (!safeTypes.has(child.component_type)) {
    issues.push({
      code: "child_type_not_allowed",
      message: "Child must be a module or hybrid; sensors and ASICs are never written.",
    });
  }
  if (parent.sn === child.sn) {
    issues.push({ code: "same_component", message: "A component cannot contain itself." });
  }
  if (child.parent_sn !== null) {
    issues.push({ code: "child_has_parent", message: `Child is already in ${child.parent_sn}.` });
  }
  if (tool.status !== "active") {
    issues.push({ code: "tool_not_active", message: "Only an active tool may be used." });
  }
  if (!tool.compatible_types.includes(parent.type_code)) {
    issues.push({ code: "tool_incompatible", message: `Tool does not fit ${parent.type_code}.` });
  }
  if (glue !== null && (glue.status !== "in_use" || glue.pot_life_expired)) {
    issues.push({ code: "glue_unavailable", message: "Glue batch is not usable." });
  }
  const valid = issues.length === 0 && slot.trim() !== "";
  const submittable = valid && parent.is_dummy && child.is_dummy;
  return {
    valid,
    submittable,
    submittable_reason: valid && !submittable ? "not_dummy" : valid ? null : "validation_failed",
    summary: `Assemble ${child.sn} into ${parent.sn} at ${slot}`,
    slot,
    parent,
    child,
    tool,
    glue_batch:
      glue === null
        ? null
        : {
            id: glue.id,
            glue_type: glue.glue_type,
            batch_no: glue.batch_no,
            pdb_sn: glue.pdb_sn,
            status: glue.status,
            mixed_at: glue.mixed_at,
            pot_life_minutes: glue.pot_life_minutes,
            pot_life_remaining_seconds: glue.pot_life_remaining_seconds,
            pot_life_expired: glue.pot_life_expired,
          },
    pdb_properties: {},
    issues,
    warnings: [],
  };
}

function buckets(values: string[]): CountBucket[] {
  const counts = new Map<string, number>();
  for (const value of values) counts.set(value, (counts.get(value) ?? 0) + 1);
  return [...counts.entries()]
    .map(([label, count]) => ({ label, count }))
    .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label));
}

// Production stage order, so the demo dashboard's stage histogram reads
// left-to-right in flow order (…→ TESTED → FINISHED), matching the backend.
const DEMO_STAGE_ORDER = [
  "HV_TAB_ATTACHED",
  "GLUED",
  "STITCH_BONDING",
  "BONDED",
  "TESTED",
  "FINISHED",
];

function orderBuckets(items: CountBucket[], order: string[]): CountBucket[] {
  const rank = (label: string) => {
    const i = order.indexOf(label);
    return i === -1 ? order.length : i;
  };
  return [...items].sort((a, b) => rank(a.label) - rank(b.label) || a.label.localeCompare(b.label));
}

export function makeDemoStatsDimensions(): StatsDimensions {
  return {
    component_types: ["MODULE", "HYBRID", "SENSOR"],
    type_codes: ["R0", "R2", "R5"],
    institutes: ["TUDO"],
  };
}

/** Plausible offline statistics, shaped like a real reconstructed history. */
export function makeDemoProductionStats(): ProductionStats {
  return {
    component_type: "MODULE",
    type_code: null,
    institute: "TUDO",
    target_stage: "FINISHED",
    bucket: "month",
    components_tracked: 42,
    stage_order: DEMO_STAGE_ORDER,
    throughput: [
      { period: "2026-02", count: 2 },
      { period: "2026-03", count: 5 },
      { period: "2026-04", count: 4 },
      { period: "2026-05", count: 9 },
      { period: "2026-06", count: 6 },
      { period: "2026-07", count: 3 },
    ],
    lead_time: { count: 29, median_days: 41.5, p25_days: 22.0, p75_days: 88.0 },
    stage_dwell: [
      { stage: "HV_TAB_ATTACHED", median_days: 6.2, count: 40 },
      { stage: "GLUED", median_days: 3.1, count: 38 },
      { stage: "STITCH_BONDING", median_days: 1.4, count: 33 },
      { stage: "BONDED", median_days: 2.8, count: 31 },
      { stage: "TESTED", median_days: 5.0, count: 29 },
      { stage: "FINISHED", median_days: 12.0, count: 20 },
    ],
    rework: {
      rate: 0.12,
      reworked_components: 5,
      total_components: 42,
      by_stage: [
        { stage: "GLUED", count: 3 },
        { stage: "BONDED", count: 2 },
        { stage: "TESTED", count: 1 },
      ],
    },
    yield_: { good: 29, failed: 4, concluded: 33, in_progress: 9, rate: 0.879 },
  };
}

export function makeDemoDashboardSummary(): DashboardSummary {
  const outbox = makeDemoOutbox();
  return {
    total_components: DEMO_COMPONENTS.length,
    last_synced_at: SYNCED,
    oldest_synced_at: "2026-07-08T05:22:00Z",
    stale_components: DEMO_COMPONENTS.filter((c) => c.stale).length,
    trashed_components: DEMO_COMPONENTS.filter((c) => c.trashed).length,
    required_test_gaps: 8,
    components_with_test_gaps: 3,
    submitted_outbox: outbox.filter((a) => a.status === "submitted").length,
    approved_outbox: outbox.filter((a) => a.status === "approved").length,
    review_outbox: outbox.filter((a) => a.status === "draft" || a.status === "validated").length,
    failed_outbox: outbox.filter((a) => a.status === "failed").length,
    by_stage: orderBuckets(buckets(DEMO_COMPONENTS.map((c) => c.stage)), DEMO_STAGE_ORDER),
    by_component_type: buckets(DEMO_COMPONENTS.map((c) => c.component_type)),
    by_institute: buckets(DEMO_COMPONENTS.map((c) => c.institute_code)),
    outbox_by_status: orderBuckets(buckets(outbox.map((a) => a.status)), [...OUTBOX_STATUSES]),
  };
}

// ---- Glue batches / shipments / reminders (Phase 4 demo fallback) ------------

export function makeDemoGlueBatches(): GlueBatch[] {
  const now = Date.now();
  return [
    {
      id: 1,
      glue_type: "POLARIS_EPOXY",
      batch_no: "PX41A9F2K0",
      pdb_sn: "20USEGT0000098",
      status: "in_use",
      manufacturing_date: "2026-05-02T00:00:00Z",
      expiry_date: "2027-05-02T00:00:00Z",
      opening_date: "2026-08-20T08:00:00Z",
      bipack_count: 12,
      note: null,
      mixed_at: new Date(now - 10 * 60_000).toISOString(),
      pot_life_minutes: 45,
      institute_id: 1,
      created_at: "2026-08-20T08:00:00Z",
      pot_life_remaining_seconds: 35 * 60,
      pot_life_expired: false,
      usage_count: 3,
    },
    {
      id: 2,
      glue_type: "TRUE_BLUE",
      batch_no: "TB77C1D4M8",
      pdb_sn: null,
      status: "new",
      manufacturing_date: "2026-06-15T00:00:00Z",
      expiry_date: "2026-12-15T00:00:00Z",
      opening_date: null,
      bipack_count: 6,
      note: "Reserve for R5 modules",
      mixed_at: null,
      pot_life_minutes: null,
      institute_id: 1,
      created_at: "2026-08-22T09:30:00Z",
      pot_life_remaining_seconds: null,
      pot_life_expired: false,
      usage_count: 0,
    },
    {
      id: 3,
      glue_type: "LOCTITE_3525",
      batch_no: "LC90B2E1Q5",
      pdb_sn: null,
      status: "empty",
      manufacturing_date: "2026-02-01T00:00:00Z",
      expiry_date: "2026-08-01T00:00:00Z",
      opening_date: "2026-03-12T00:00:00Z",
      bipack_count: 0,
      note: null,
      mixed_at: "2026-07-30T10:00:00Z",
      pot_life_minutes: 30,
      institute_id: 1,
      created_at: "2026-02-05T10:00:00Z",
      pot_life_remaining_seconds: 0,
      pot_life_expired: true,
      usage_count: 18,
    },
  ];
}

export function filterDemoGlueBatches(status: string, glueType: string, q: string): GlueBatch[] {
  const needle = q.trim().toLowerCase();
  return makeDemoGlueBatches().filter(
    (b) =>
      (status === "" || b.status === status) &&
      (glueType === "" || b.glue_type === glueType) &&
      (needle === "" ||
        b.batch_no.toLowerCase().includes(needle) ||
        (b.pdb_sn ?? "").toLowerCase().includes(needle) ||
        b.glue_type.toLowerCase().includes(needle)),
  );
}

export function makeDemoGlueUsage(batchId: number): GlueUsage[] {
  if (batchId !== 1) return [];
  return [
    {
      id: 1,
      glue_batch_id: 1,
      component_sn: "20USEM00000435",
      amount_mg: 135.2,
      note: null,
      used_by: "anna.abel@example.org",
      used_at: "2026-08-24T09:12:00Z",
    },
    {
      id: 2,
      glue_batch_id: 1,
      component_sn: "20USEM00000436",
      amount_mg: 128.7,
      note: "Rework",
      used_by: "anna.abel@example.org",
      used_at: "2026-08-24T11:40:00Z",
    },
  ];
}

export function makeDemoShipments(): Shipment[] {
  return [
    {
      id: 1,
      pdb_id: "68a1demo01",
      name: "Hybrid panel delivery",
      sender_code: "DESYZ",
      recipient_code: "TUDO",
      status: "inTransit",
      direction: "incoming",
      sent_at: "2026-08-21T14:00:00Z",
      items: [
        {
          sn: "20USEH00000101",
          component_type: "HYBRID",
          component_mirrored: true,
          is_dummy: true,
          submittable: true,
          submittable_reason: null,
          reception_tests_configured: true,
          reception_test_status: "missing",
          reception_tests: [{ test_type: "HYBRID_RECEPTION", status: "missing" }],
        },
        {
          sn: "20USEH00000102",
          component_type: "HYBRID",
          component_mirrored: true,
          is_dummy: false,
          submittable: false,
          submittable_reason: "not_dummy",
          reception_tests_configured: true,
          reception_test_status: "pending",
          reception_tests: [{ test_type: "HYBRID_RECEPTION", status: "pending" }],
        },
      ],
      institute_id: 1,
      synced_at: "2026-08-25T07:00:00Z",
      reception_status: "pending",
      reception_checklist: [
        { label: "Packaging intact", done: false },
        { label: "Contents match the shipment list", done: false },
        { label: "No visible damage", done: false },
      ],
      reception_items: [],
      reception_note: null,
      reception_by: null,
      reception_updated_at: null,
      reception_tests_configured: true,
      reception_test_status: "pending",
    },
    {
      id: 2,
      pdb_id: "68a1demo02",
      name: "Finished modules to loading site",
      sender_code: "TUDO",
      recipient_code: "AVS",
      status: "delivered",
      direction: "outgoing",
      sent_at: "2026-08-10T09:00:00Z",
      items: [
        {
          sn: "20USEM00000399",
          component_type: "MODULE",
          component_mirrored: true,
          is_dummy: false,
          submittable: false,
          submittable_reason: "not_dummy",
          reception_tests_configured: false,
          reception_test_status: "passed",
          reception_tests: [],
        },
      ],
      institute_id: 1,
      synced_at: "2026-08-25T07:00:00Z",
      reception_status: "done",
      reception_checklist: [
        { label: "Packaging intact", done: true },
        { label: "Contents match the shipment list", done: true },
        { label: "No visible damage", done: true },
      ],
      reception_items: [{ sn: "20USEM00000399", received: true }],
      reception_note: "Confirmed by recipient.",
      reception_by: "anna.abel@example.org",
      reception_updated_at: "2026-08-12T10:00:00Z",
      reception_tests_configured: false,
      reception_test_status: "passed",
    },
  ];
}

export function filterDemoShipments(
  direction: string,
  reception: string,
  q: string,
): Shipment[] {
  const needle = q.trim().toLowerCase();
  return makeDemoShipments().filter(
    (s) =>
      (direction === "" || s.direction === direction) &&
      (reception === "" || s.reception_status === reception) &&
      (needle === "" ||
        (s.name ?? "").toLowerCase().includes(needle) ||
        s.pdb_id.toLowerCase().includes(needle) ||
        s.sender_code.toLowerCase().includes(needle) ||
        s.recipient_code.toLowerCase().includes(needle)),
  );
}

export function makeDemoReminders(): Reminder[] {
  return [
    {
      id: 1,
      title: "Clean the flow bench",
      note: "Weekly cleanroom duty.",
      channel: "lab",
      schedule_kind: "weekly",
      next_due_at: "2026-09-01T06:00:00Z",
      active: true,
      last_fired_at: "2026-08-25T06:00:00Z",
      last_error: null,
      created_by: "anna.abel@example.org",
      institute_id: 1,
      created_at: "2026-07-01T12:00:00Z",
      updated_at: "2026-08-25T06:00:00Z",
    },
    {
      id: 2,
      title: "Check dry-air supply",
      note: null,
      channel: null,
      schedule_kind: "daily",
      next_due_at: "2026-08-26T05:30:00Z",
      active: true,
      last_fired_at: "2026-08-25T05:30:00Z",
      last_error: null,
      created_by: "anna.abel@example.org",
      institute_id: 1,
      created_at: "2026-07-15T09:00:00Z",
      updated_at: "2026-08-25T05:30:00Z",
    },
  ];
}

export function makeDemoNotificationChannels(): NotificationChannel[] {
  return [
    { name: "lab", kind: "mattermost" },
    { name: "ops", kind: "webhook" },
  ];
}
