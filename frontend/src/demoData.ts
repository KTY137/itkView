import type {
  ComponentDetail,
  ComponentOut,
  CountBucket,
  DashboardSummary,
  IngestFile,
  OutboxAction,
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
    synced_at: SYNCED,
  },
  {
    sn: "20USBML9990001",
    local_name: "TUDO-DUMMY-M-01",
    component_type: "MODULE",
    type_code: "BML",
    stage: "TESTED",
    location: "TUDO",
    institute_code: "TUDO",
    parent_sn: null,
    is_dummy: true,
    trashed: false,
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

function buckets(values: string[]): CountBucket[] {
  const counts = new Map<string, number>();
  for (const value of values) counts.set(value, (counts.get(value) ?? 0) + 1);
  return [...counts.entries()]
    .map(([label, count]) => ({ label, count }))
    .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label));
}

export function makeDemoDashboardSummary(): DashboardSummary {
  const outbox = makeDemoOutbox();
  return {
    total_components: DEMO_COMPONENTS.length,
    last_synced_at: SYNCED,
    submitted_outbox: outbox.filter((a) => a.status === "submitted").length,
    failed_outbox: outbox.filter((a) => a.status === "failed").length,
    by_stage: buckets(DEMO_COMPONENTS.map((c) => c.stage)),
    by_component_type: buckets(DEMO_COMPONENTS.map((c) => c.component_type)),
    by_institute: buckets(DEMO_COMPONENTS.map((c) => c.institute_code)),
    outbox_by_status: buckets(outbox.map((a) => a.status)),
  };
}
