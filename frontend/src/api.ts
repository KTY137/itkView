/**
 * Typed fetch layer for the itkFlow backend API.
 *
 * NOTE: the backend is being built in parallel; these types mirror the agreed
 * API contract 1:1. As soon as the backend serves its OpenAPI schema, replace
 * the hand-written types with generated ones (e.g. via openapi-typescript) —
 * kept dependency-free for now on purpose.
 */

// ---- Component shapes -------------------------------------------------------

export type ComponentOut = {
  sn: string;
  local_name: string | null;
  component_type: string;
  type_code: string;
  stage: string;
  location: string;
  institute_code: string;
  parent_sn: string | null;
  is_dummy: boolean;
  trashed: boolean;
  stale: boolean;
  synced_at: string;
};

export type ComponentDetail = ComponentOut & {
  children: ComponentOut[];
};

export type RequirementCheck = {
  stage: string;
  test_type: string;
  status: "passed" | "failed" | "missing";
};

export type StageSuggestion = {
  sn: string;
  current_stage: string;
  next_stage: string | null;
  move_suggested: boolean;
  suggested_stage: string | null;
  checks: RequirementCheck[];
  blocking: RequirementCheck[];
};

export type PreviewRequirementCheck = {
  stage: string;
  test_type: string;
  status: "passed" | "failed" | "missing" | "pending";
};

export type ComponentPreviewState = {
  stage: string;
  checks: PreviewRequirementCheck[];
};

export type ComponentPreviewAction = {
  id: number;
  kind: string;
  status: OutboxStatus;
  summary: string;
  to_stage: string | null;
  test_type: string | null;
  created_by: string;
  created_at: string;
  submittable: boolean;
  submittable_reason: string | null;
};

/**
 * A staged, not-yet-pushed test upload ("ghost run").
 *
 * Shaped like a mirrored run so both render through the same components;
 * `ghost` is always true and `attachments` always empty, because the run does
 * not exist in the PDB yet.
 */
export type ComponentPreviewTest = {
  test_type: string;
  passed: boolean | null;
  external_ref: string | null;
  measured_at: string | null;
  synced_at: string | null;
  source: string;
  run_number: string | number | null;
  properties: Record<string, unknown>;
  results: Record<string, unknown>;
  result_meta: Record<string, { name?: string; data_type?: string; value_type?: string }>;
  attachments: TestRunAttachment[];
  ghost: boolean;
  outbox_action_id: number | null;
};

export type WorksheetScalar = { code: string; name: string; value: unknown };

export type WorksheetArraySummary = {
  code: string;
  name: string;
  /** Sample count for arrays, key count for map-valued results. */
  points: number;
  /** Absent on older payloads; treat as "array". */
  kind?: "array" | "map";
};

export type WorksheetLatestRun = {
  external_ref: string | null;
  measured_at: string | null;
  run_number: string | number | null;
  passed: boolean | null;
  scalars: WorksheetScalar[];
  arrays: WorksheetArraySummary[];
  attachment_count: number;
};

export type WorksheetStagedRef = { outbox_action_id: number; status: OutboxStatus };

/**
 * One raw reading that fed a derived step, so the arithmetic stays retraceable
 * (`plan §9.3`). PDB carries every `GW_` code in grams; the mg conversion is
 * part of the server-side contract, so these values are shown verbatim and
 * never re-scaled here.
 */
export type WorksheetDerivedInput = {
  code: string;
  name: string;
  value: number | null;
};

/**
 * `unknown` is deliberate and always carries a `reason`: on the sheet this
 * replaces, an absent input silently produced a number that looked like a
 * result (8 of 13 powerboard verdicts were arithmetic on empty cells).
 */
export type WorksheetDerivedVerdict = "ok" | "too_little" | "too_much" | "unknown";

/** One judged step of a derivation — e.g. the hybrids glueing, the powerboard
 * glueing. `key` and `label` come from the institute profile, never from code. */
export type WorksheetDerivedStep = {
  key: string;
  label: string;
  measured_mg: number | null;
  target_mg: number | null;
  tolerance_mg: number | null;
  verdict: WorksheetDerivedVerdict;
  /** Why there is no verdict: `no_target`, `missing_inputs`, `no_run`. Typed
   * as a plain string so a reason this build does not know yet renders as an
   * explicit unknown reason instead of an empty cell. */
  reason: string | null;
  /** The PDB code the derived value is uploaded under; absent when the step is
   * judged locally but never written back. Beyond the plan §9.3 field list,
   * and not rendered — declared so the wire shape stays described in one
   * place. */
  result_code?: string | null;
  inputs: WorksheetDerivedInput[];
};

/**
 * The server's judgement over a row's measured values (plan §9.3).
 *
 * itkFlow computes this in exactly one place — the backend adapter. The
 * browser only formats and colours it: the sheet this replaces and the
 * reference implementation drifted apart precisely because the same formula
 * existed twice.
 */
export type WorksheetDerived = {
  kind: "glue_weight";
  /** The glue process the rule set was selected for; null when unresolved. */
  process: string | null;
  process_source: "run" | "profile_default" | "unknown";
  steps: WorksheetDerivedStep[];
};

export type WorksheetRow = {
  test_type: string;
  status: "passed" | "failed" | "missing" | "pending";
  latest: WorksheetLatestRun | null;
  staged: WorksheetStagedRef[];
  run_count: number;
  /**
   * Optional on the wire: a test type the institute profile configures no
   * derivation for — and any server built before this block existed — simply
   * carries none, and the row renders exactly as it did before.
   */
  derived?: WorksheetDerived | null;
};

export type WorksheetGroup = {
  /** null = "Additional" group: mirrored test types outside the stage model. */
  stage: string | null;
  reached: boolean;
  rows: WorksheetRow[];
};

/**
 * A child component's evidence for one test type. Deliberately without a
 * requirement `status`: a requirement is a statement about the component whose
 * page this is, and showing a child's evidence does not change what gates its
 * parent's stage move. `latest.passed` carries the run's own verdict.
 */
export type WorksheetChildRow = {
  test_type: string;
  latest: WorksheetLatestRun | null;
  run_count: number;
  /** Runs the PDB has retracted; excluded from `latest` and `run_count`. */
  withdrawn_count: number;
};

/** Evidence that lives on one direct child (sensor, hybrid, powerboard, or —
 * for an R5 ring module — a half-module). */
export type WorksheetChildGroup = {
  sn: string;
  component_type: string;
  type_code: string;
  local_name: string | null;
  rows: WorksheetChildRow[];
};

export type ComponentPreviewWorksheet = {
  groups: WorksheetGroup[];
  /**
   * Optional on the wire so an older server (or a fixture written before this
   * block existed) simply renders no child section instead of crashing the
   * page. The current backend always sends it.
   */
  children?: WorksheetChildGroup[];
};

export type ComponentPreview = {
  current: ComponentPreviewState;
  staged_actions: ComponentPreviewAction[];
  projected: ComponentPreviewState & {
    /**
     * Staged uploads only — never the mirrored runs.
     *
     * Those carry raw measured values (one IV sweep outweighs everything else
     * on this page) and are fetched on demand via `getComponentTests` when the
     * collapsed run list is opened.
     *
     */
    ghost_tests: ComponentPreviewTest[];
  };
  worksheet: ComponentPreviewWorksheet;
};

export type ComponentSyncResult = {
  institute_code: string;
  fetched: number;
  skipped: number;
  created: number;
  updated: number;
  unchanged: number;
  stale: number;
  total: number;
};

export type EvidenceSyncJobResult = {
  institute_code: string;
  component_types: string[];
  components_processed: number;
  created: number;
  updated: number;
  unchanged: number;
  total: number;
  attachments_downloaded: number;
  attachments_reused: number;
  attachments_failed: number;
  attachments_skipped?: number;
  attachments_authentication_required?: number;
  attachments_total: number;
};

export type SyncJobStatus =
  | "queued"
  | "running"
  | "succeeded"
  | "failed"
  | "interrupted";

export type ComponentSyncPhase =
  | "queued"
  | "fetching"
  | "mapping"
  | "upserting"
  | "stage_events"
  | "tools"
  | "committing"
  | "complete";

export type EvidenceSyncPhase =
  | "queued"
  | "fetching"
  | "attachments"
  | "committing"
  | "complete";

export type SyncJobPhase = ComponentSyncPhase | EvidenceSyncPhase;

/** Persisted progress for the read-only PDB -> local component-mirror job. */
export type ComponentSyncJob = {
  id: number;
  kind: "components";
  institute_code: string;
  status: SyncJobStatus;
  phase: ComponentSyncPhase;
  current: number;
  total: number | null;
  percent: number | null;
  message: string;
  result: ComponentSyncResult | null;
  error: string | null;
  created_at: string;
  started_at: string | null;
  updated_at: string;
  finished_at: string | null;
  heartbeat_stale?: boolean;
  stale_after_seconds?: number;
};

/** Persisted progress for the detailed test-evidence and attachment mirror. */
export type EvidenceSyncJob = {
  id: number;
  kind: "evidence";
  institute_code: string;
  status: SyncJobStatus;
  phase: EvidenceSyncPhase;
  current: number;
  total: number | null;
  percent: number | null;
  message: string;
  result: EvidenceSyncJobResult | null;
  error: string | null;
  created_at: string;
  started_at: string | null;
  updated_at: string;
  finished_at: string | null;
  heartbeat_stale?: boolean;
  stale_after_seconds?: number;
};

export type SyncJob = ComponentSyncJob | EvidenceSyncJob;
export type SyncJobKind = SyncJob["kind"];

// ---- Local operations health -----------------------------------------------

export type OpsHeartbeat = {
  service: "outbox-worker" | "reminder-scheduler";
  status: "healthy" | "stale" | "missing" | "error" | "disabled";
  last_seen_at: string | null;
  age_seconds: number | null;
  stale_after_seconds: number;
  detail: Record<string, unknown>;
};

export type OpsHealth = {
  status: "healthy" | "warning" | "critical";
  generated_at: string;
  institute_code: string | null;
  diagnostics_available?: boolean;
  heartbeats: OpsHeartbeat[];
  sync: { active: SyncJob[]; latest: SyncJob[]; stale_active: number };
  outbox: {
    backlog: number;
    failed: number;
    at_attempt_limit: number;
    oldest_open_at: string | null;
    oldest_open_age_seconds: number | null;
  };
  reminders: {
    active: number;
    open_occurrences: number;
    failed_occurrences: number;
    escalated_open: number;
    overdue: number;
  };
  ingest: {
    total: number;
    triage: number;
    failed: number;
    parser_issues: number;
    unassigned: number;
  };
};

// ---- Institute shapes -------------------------------------------------------

export type Institute = {
  id: number;
  code: string;
  name: string;
  local_name_prefix: string;
  settings: Record<string, unknown>;
  created_at: string;
};

export type InstituteCreate = {
  code: string;
  name: string;
  local_name_prefix?: string;
  settings?: Record<string, unknown>;
};

export type InstituteUpdate = {
  name?: string;
  local_name_prefix?: string;
  /** Top-level keys are shallow-merged by the backend. */
  settings?: Record<string, unknown>;
};

// ---- Dashboard shapes -------------------------------------------------------

export type CountBucket = {
  label: string;
  count: number;
};

export type DashboardSummary = {
  total_components: number;
  last_synced_at: string | null;
  oldest_synced_at: string | null;
  stale_components: number;
  trashed_components: number;
  required_test_gaps: number;
  components_with_test_gaps: number;
  submitted_outbox: number;
  approved_outbox: number;
  review_outbox: number;
  failed_outbox: number;
  by_stage: CountBucket[];
  by_component_type: CountBucket[];
  by_institute: CountBucket[];
  outbox_by_status: CountBucket[];
};

// ---- Statistics shapes ------------------------------------------------------

export type ThroughputPoint = { period: string; count: number };

export type LeadTime = {
  count: number;
  median_days: number | null;
  p25_days: number | null;
  p75_days: number | null;
};

export type StageDwell = { stage: string; median_days: number; count: number };

export type Rework = {
  rate: number;
  reworked_components: number;
  total_components: number;
  by_stage: { stage: string; count: number }[];
};

export type Yield = {
  good: number;
  failed: number;
  concluded: number;
  in_progress: number;
  rate: number | null;
};

export type ProductionStats = {
  component_type: string | null;
  type_code: string | null;
  institute: string | null;
  target_stage: string;
  bucket: string;
  components_tracked: number;
  stage_order: string[];
  throughput: ThroughputPoint[];
  lead_time: LeadTime;
  stage_dwell: StageDwell[];
  rework: Rework;
  yield_: Yield;
};

export type RequiredTestStageRow = {
  stage: string;
  test_type: string;
  component_total: number;
  passed: number;
  failed: number;
  missing: number;
};

export type RequiredTestStats = {
  institute: string;
  denominator: "at_or_beyond_stage";
  stage_order: string[];
  rows: RequiredTestStageRow[];
};

export type MeasurementResultDimension = {
  code: string;
  name: string | null;
  kind: "array" | "scalar";
  runs: number;
};

export type MeasurementTestType = {
  test_type: string;
  results: MeasurementResultDimension[];
};

export type MeasurementDimensions = { test_types: MeasurementTestType[] };

export type MeasurementCurve = {
  component_sn: string;
  local_name: string | null;
  external_ref: string | null;
  measured_at: string | null;
  passed: boolean;
  /** null when no matching x array exists — plot against the sample index. */
  x: number[] | null;
  y: number[];
};

export type MeasurementValue = {
  component_sn: string;
  local_name: string | null;
  external_ref: string | null;
  measured_at: string | null;
  passed: boolean;
  value: number;
};

export type MeasurementSeries = {
  test_type: string;
  result_code: string;
  kind: "array" | "scalar";
  result_name: string | null;
  x_result: string | null;
  x_name: string | null;
  curves: MeasurementCurve[];
  values: MeasurementValue[];
  summary: Record<string, number> | null;
  truncated: boolean;
};

export type StatsDimensions = {
  component_types: string[];
  type_codes: string[];
  institutes: string[];
};

export type ProductionStatsQuery = {
  component_type?: string;
  type_code?: string;
  institute?: string;
  target_stage?: string;
  bucket?: string;
};

// ---- Outbox shapes -----------------------------------------------------------

export const OUTBOX_STATUSES = [
  "draft",
  "validated",
  "approved",
  "submitted",
  "confirmed",
  "failed",
  "cancelled",
] as const;

export type OutboxStatus = (typeof OUTBOX_STATUSES)[number];

export type OutboxContract = {
  statuses: OutboxStatus[];
  transitions: Record<OutboxStatus, OutboxStatus[]>;
  terminal: OutboxStatus[];
};

export type OutboxAction = {
  id: number;
  institute_id: number;
  kind: string;
  payload: Record<string, unknown>;
  status: OutboxStatus;
  error: string | null;
  attempts: number;
  external_ref: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
};

// ---- Ingestion shapes -------------------------------------------------------

export type IngestFile = {
  id: number;
  filename: string;
  sha256: string;
  size_bytes: number;
  status: string;
  component_sn: string | null;
  test_type: string | null;
  parser: string | null;
  error: string | null;
  outbox_action_id: number | null;
  uploaded_by: string;
  created_at: string;
  updated_at: string;
};

export type IngestFileCreate = {
  filename: string;
  payload: Record<string, unknown>;
  component_sn?: string;
  test_type?: string;
  parser?: "manual-entry";
};

export type IngestProposalCreate = {
  institute_code?: string;
};

export type TestSchemaField = {
  code?: string;
  name?: string;
  title?: string;
  description?: string;
  dataType?: unknown;
  data_type?: unknown;
  type?: unknown;
  valueType?: unknown;
  value_type?: unknown;
  required?: boolean;
  default?: unknown;
  defaultValue?: unknown;
  [key: string]: unknown;
};

export type TestSchemaFieldCollection =
  | Array<TestSchemaField | string>
  | Record<string, TestSchemaField | string | null>;

/**
 * One PDB test-type definition, mirrored raw (`getTestTypeByCode` is stored
 * unmodified, so this describes the PDB's own vocabulary, not itkFlow's).
 *
 * The measurement fields arrive under `parameters`: every mirrored MODULE
 * definition carries no `results` key at all. `results` stays declared because
 * it is itkFlow's own name for the same block — the `uploadTestRunResults`
 * payload key, and the shape callers produce when they rewrite a definition
 * before rendering it. `TestForm.measurementFields()` owns the precedence
 * between the two.
 */
export type TestSchemaDefinition = {
  properties?: TestSchemaFieldCollection;
  results?: TestSchemaFieldCollection;
  parameters?: TestSchemaFieldCollection;
  required?:
    | string[]
    | Record<string, string[] | Record<string, boolean> | boolean | undefined>;
  [key: string]: unknown;
};

/** Local read-only snapshot of one PDB test-type definition. */
export type TestTypeSchema = {
  id: number;
  component_type: string;
  test_code: string;
  name: string;
  schema: TestSchemaDefinition;
  synced_at: string;
};

export type TestTypeSchemaSyncResult = {
  component_type: string;
  created: number;
  updated: number;
  unchanged: number;
  total: number;
};

export type IngestResultSummary = {
  name: string;
  kind: string;
  value: string;
};

export type IngestPreview = {
  file_id: number;
  parser: string;
  upload_ready: boolean;
  component_sn: string | null;
  local_name: string | null;
  component_mirrored: boolean;
  component_stage: string | null;
  institute_code: string | null;
  test_type: string | null;
  run_number: string | null;
  institution: string | null;
  measured_at: string | null;
  passed: boolean | null;
  problems: boolean | null;
  n_properties: number;
  results: IngestResultSummary[];
  issues: string[];
  warnings: string[];
  /**
   * The same server-side derivation as `WorksheetRow.derived`, but computed
   * over the values *this* dry-run just inspected — the only way the edit
   * strip can show a judgement for freshly entered readings without a second
   * copy of the formula in the browser (plan §2.3).
   *
   * Beyond the plan §9.3 contract, which names `derived` only on the
   * worksheet row, and therefore optional: while the server omits it, the
   * strip falls back to the last recorded run's derivation and says so.
   */
  derived?: WorksheetDerived | null;
};

export type OutboxTransitionBody = {
  to: OutboxStatus;
  actor: string;
  error?: string;
};

/** Offline fallback for the backend-published outbox state machine contract. */
export const DEFAULT_OUTBOX_CONTRACT: OutboxContract = {
  statuses: [...OUTBOX_STATUSES],
  terminal: ["confirmed", "cancelled"],
  transitions: {
  draft: ["validated", "cancelled"],
  validated: ["approved", "draft", "cancelled"],
  approved: ["submitted", "cancelled"],
  submitted: ["confirmed", "failed"],
  failed: ["submitted", "cancelled"],
  confirmed: [],
  cancelled: [],
  },
};

// ---- Tools / jigs -----------------------------------------------------------

export type Tool = {
  id: number;
  kind: string;
  code: string;
  label: string | null;
  rfid: string | null;
  compatible_types: string[];
  institute_id: number | null;
  status: ToolStatus;
  created_at: string;
};

export type ToolStatus = "active" | "flagged" | "blacklisted";

export type ToolQuery = {
  kind?: string;
  fits?: string;
  status?: ToolStatus;
  institute?: string;
};

export type ToolCreateBody = {
  institute_code?: string;
  kind: string;
  code: string;
  label?: string | null;
  rfid?: string | null;
  compatible_types: string[];
  status?: ToolStatus;
};

export type ToolUpdateBody = Partial<Omit<ToolCreateBody, "institute_code">>;

export type ToolSyncResult = {
  institute_code: string;
  created: number;
  updated: number;
  unchanged: number;
  skipped: number;
  total: number;
};

// ---- Auth shapes ------------------------------------------------------------

export type Role = "viewer" | "operator" | "admin";

/** The signed-in user, as returned by `/api/auth/login` and `/api/auth/me`.
 * `institute_*` are nullable: a global admin (docs/06) has no home institute. */
export type MeOut = {
  id: number;
  email: string;
  display_name: string;
  role: Role;
  institute_id: number | null;
  institute_code: string | null;
  csrf_token: string;
};

export type LoginBody = { email: string; password: string };

export type UserOut = {
  id: number;
  email: string;
  display_name: string;
  role: Role;
  is_active: boolean;
  institute_id: number | null;
  created_at: string;
};

export type UserCreateBody = {
  email: string;
  display_name: string;
  role: Role;
  password: string;
};

export type UserUpdateBody = {
  display_name?: string;
  role?: Role;
  is_active?: boolean;
  password?: string;
};

// ---- Personal PDB connection -----------------------------------------------

export type PdbConnectionState =
  | "not_configured"
  | "verified"
  | "invalid"
  | "unreachable";

/** Non-secret status for the signed-in user's personal PDB access codes. */
export type PdbConnectionOut = {
  configured: boolean;
  state: PdbConnectionState;
  instance: string;
  identity: string | null;
  institutions: string[];
  last_checked_at: string | null;
  verified_at: string | null;
};

/** Write-only credential pair. The backend never echoes either value. */
export type PdbCredentialsPut = {
  access_code1: string;
  access_code2: string;
};

/** Non-secret metadata for one account-owned public-share password. */
export type ShareCredentialOut = {
  id: number;
  provider_host: string;
  token_hint: string;
  updated_at: string;
};

/** Write-only public-share URL/password pair. Neither value is echoed. */
export type ShareCredentialPut = {
  url: string;
  password: string;
};

// ---- Error handling ----------------------------------------------------------

export class ApiError extends Error {
  /** HTTP status; 0 means the backend was not reachable (network error). */
  readonly status: number;
  /** Parsed `detail` field of a FastAPI error body, if present. */
  readonly detail: string | null;

  constructor(message: string, status: number, detail: string | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }

  get isNetwork(): boolean {
    return this.status === 0;
  }
}

// ---- Auth / session plumbing -------------------------------------------------
//
// The whole app is cookie-authenticated: every call sends the httpOnly session
// cookie (`credentials: "include"`), and every state-changing call carries the
// CSRF token in the `X-CSRF-Token` header. The token is populated from
// `MeOut.csrf_token` after login/session-probe (`setCsrfToken`) and, as a
// belt-and-suspenders fallback, read from the readable `itkflow_csrf` cookie.
//
// Two cross-cutting signals are dispatched to the auth layer so a dead session
// or a role violation is handled once, centrally: a non-auth `401` drops the
// user to the login screen, a non-auth `403` raises a toast. Auth endpoints
// (`/api/auth/*`) are exempt — their 401 is the normal "not signed in" answer
// and is handled inline by the caller.

const AUTH_PATH_PREFIX = "/api/auth/";

let csrfToken: string | null = null;
let unauthorizedHandler: (() => void) | null = null;
let forbiddenHandler: (() => void) | null = null;

/** Keep the CSRF token the fetch layer attaches to writes in sync with the
 * signed-in session (call with the token from `MeOut`, or null on logout). */
export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

/** Register a handler fired on a non-auth `401` (session gone → login screen). */
export function setUnauthorizedHandler(handler: (() => void) | null): void {
  unauthorizedHandler = handler;
}

/** Register a handler fired on a non-auth `403` (wrong role → toast). */
export function setForbiddenHandler(handler: (() => void) | null): void {
  forbiddenHandler = handler;
}

function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const prefix = `${name}=`;
  for (const part of document.cookie.split(";")) {
    const entry = part.trim();
    if (entry.startsWith(prefix)) return decodeURIComponent(entry.slice(prefix.length));
  }
  return null;
}

function currentCsrfToken(): string | null {
  return csrfToken ?? readCookie("itkflow_csrf");
}

/** Shared fetch: cookies always, CSRF header on writes, and central dispatch of
 * the auth signals. Returns the raw `Response` for the JSON/void wrappers. */
async function rawFetch(path: string, init?: RequestInit): Promise<Response> {
  const method = (init?.method ?? "GET").toUpperCase();
  const headers = new Headers(init?.headers);
  if (method !== "GET" && method !== "HEAD") {
    const token = currentCsrfToken();
    if (token !== null && !headers.has("X-CSRF-Token")) headers.set("X-CSRF-Token", token);
  }

  let res: Response;
  try {
    res = await fetch(path, { ...init, credentials: "include", headers });
  } catch (err) {
    // Keep aborts distinguishable from real network failures.
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new ApiError("Backend not reachable", 0);
  }

  if (!res.ok) {
    if (!path.startsWith(AUTH_PATH_PREFIX)) {
      if (res.status === 401) unauthorizedHandler?.();
      else if (res.status === 403) forbiddenHandler?.();
    }
    let detail: string | null = null;
    try {
      const body: unknown = await res.json();
      if (body !== null && typeof body === "object" && "detail" in body) {
        const raw = (body as { detail: unknown }).detail;
        detail = typeof raw === "string" ? raw : JSON.stringify(raw);
      }
    } catch {
      // Error body was not JSON — fall back to the HTTP status line.
    }
    throw new ApiError(detail ?? `${res.status} ${res.statusText}`, res.status, detail);
  }
  return res;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await rawFetch(path, init);
  return (await res.json()) as T;
}

/** Like `request`, but for endpoints that answer `204 No Content` (e.g. logout). */
async function requestVoid(path: string, init?: RequestInit): Promise<void> {
  await rawFetch(path, init);
}

function queryString(params: Record<string, string | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") search.set(key, value);
  }
  const s = search.toString();
  return s === "" ? "" : `?${s}`;
}

// ---- Endpoints ---------------------------------------------------------------

export type ComponentQuery = {
  q?: string;
  stage?: string;
  component_type?: string;
  institute?: string;
};

export function getComponents(
  query: ComponentQuery = {},
  signal?: AbortSignal,
): Promise<ComponentOut[]> {
  return request<ComponentOut[]>(`/api/components${queryString(query)}`, { signal });
}

export function getComponent(sn: string, signal?: AbortSignal): Promise<ComponentDetail> {
  return request<ComponentDetail>(`/api/components/${encodeURIComponent(sn)}`, { signal });
}

/** Local-only projection of open outbox actions over the component mirror. */
export function getComponentPreview(
  sn: string,
  signal?: AbortSignal,
): Promise<ComponentPreview> {
  return request<ComponentPreview>(`/api/components/${encodeURIComponent(sn)}/preview`, {
    signal,
  });
}

export type TestRunAttachment = {
  /** Storage namespace; attachment codes are unique only within one source. */
  source: string;
  code: string;
  test_type: string;
  test_run_ref: string | null;
  filename: string | null;
  content_type: string | null;
  title: string | null;
  size_bytes: number | null;
  /** False when the PDB knows the file but it has not been mirrored yet. */
  stored: boolean;
  is_image: boolean;
};

export type TestRunDetail = {
  test_type: string;
  passed: boolean;
  external_ref: string | null;
  measured_at: string | null;
  run_number: string | null;
  /** PDB lifecycle state. Exactly `deleted` means the run was withdrawn. */
  run_state: string | null;
  /** Measured values keyed by PDB code; arrays for curves (IV), scalars otherwise. */
  results: Record<string, unknown>;
  /** Descriptions per code — this is where the unit lives. */
  result_meta: Record<string, { name?: string; data_type?: string; value_type?: string }>;
  properties: Record<string, unknown>;
  attachments: TestRunAttachment[];
};

export type ComponentThumbnail = {
  source: string;
  code: string;
};

/** Serial number -> source-qualified attachment, one stored image per component.
 *
 * One request for a whole list: a per-row lookup would open a connection per
 * module only to learn that most have no picture. The server's `limit`
 * (default 2000) bounds *components*, not attachment rows, so the default
 * covers every mirrored component; no caller needs to pass one. */
export function getComponentThumbnails(
  instituteCode?: string,
  signal?: AbortSignal,
): Promise<Record<string, ComponentThumbnail>> {
  const query = instituteCode
    ? `?institute_code=${encodeURIComponent(instituteCode)}`
    : "";
  return request<Record<string, ComponentThumbnail>>(`/api/components/thumbnails${query}`, {
    signal,
  });
}

/** Mirrored test runs with their measured values. Local only — never hits the PDB. */
export function getComponentTests(sn: string, signal?: AbortSignal): Promise<TestRunDetail[]> {
  return request<TestRunDetail[]>(`/api/components/${encodeURIComponent(sn)}/tests`, { signal });
}

/** One direct child's locally stored images, tagged with whose they are. */
export type ChildAttachments = {
  sn: string;
  component_type: string;
  type_code: string;
  local_name: string | null;
  attachments: TestRunAttachment[];
};

/** A component's own mirrored attachment index plus its children's images.
 *
 * The children arrive in their own groups rather than folded into
 * `attachments`: on the owner's mirror 241 of 432 mirrored images hang on a
 * sensor that is a module's direct child and 3 on modules themselves, and a
 * photograph of a sensor is a statement about that sensor. Each group carries
 * the child's serial, so its bytes are fetched under the child's own URL. */
export type ComponentAttachments = {
  component_sn: string;
  attachments: TestRunAttachment[];
  children: ChildAttachments[];
};

export function getComponentAttachments(
  sn: string,
  signal?: AbortSignal,
): Promise<ComponentAttachments> {
  return request<ComponentAttachments>(
    `/api/components/${encodeURIComponent(sn)}/attachments`,
    { signal },
  );
}

/** URL of one locally mirrored attachment. 404 until it has been synced. */
export function componentAttachmentUrl(sn: string, code: string, source: string): string {
  return `/api/components/${encodeURIComponent(sn)}/attachments/${encodeURIComponent(code)}?source=${encodeURIComponent(source)}`;
}

/** Open (not yet confirmed/cancelled) outbox actions targeting this component. */
export function getComponentStaged(sn: string, signal?: AbortSignal): Promise<OutboxAction[]> {
  return request<OutboxAction[]>(`/api/components/${encodeURIComponent(sn)}/staged`, { signal });
}

export type EvidenceSyncResult = {
  component_sn: string;
  created: number;
  updated: number;
  unchanged: number;
  total: number;
  attachments_downloaded: number;
  attachments_reused: number;
  attachments_failed: number;
  attachments_skipped?: number;
  attachments_authentication_required?: number;
  attachments_total: number;
};

export type AssemblyDraft = {
  parent_sn: string;
  child_sn: string;
  slot: string;
  /** Legacy single-tool contract. Sent only when the institute profile has
   * no configured `assembly_tool_slots` layout (docs/05 §8). */
  tool_id?: number;
  /** Tool IDs keyed by `assembly_tool_slots[].key`. Sent instead of
   * `tool_id` once the institute profile defines a slot layout. */
  tools?: Record<string, number[]>;
  glue_batch_id?: number | null;
};

/** One configured tool slot from `Institute.settings.assembly_tool_slots`
 * (docs/05 §8, docs/07). A missing or invalid setting means the wizard falls
 * back to a single legacy tool slot instead. `label` is institute data and
 * must never be translated or hardcoded. */
export type AssemblyToolSlot = {
  key: string;
  label: string;
  kinds?: string[];
  multiple?: boolean;
  /** PDB property code the resolved tool(s) map to. The wizard never reads
   * this itself — it is applied server-side (mirrors `assembly_property_keys`,
   * docs/07) when deriving `AssemblyPreview.pdb_properties`. Kept on this
   * type only so it stays symmetric with the profile contract it renders. */
  property_key?: string;
};

export type AssemblyIssue = { code: string; message: string };

export type AssemblyComponent = Pick<
  ComponentOut,
  | "sn"
  | "local_name"
  | "component_type"
  | "type_code"
  | "stage"
  | "location"
  | "institute_code"
  | "parent_sn"
  | "is_dummy"
  | "stale"
  | "trashed"
>;

export type AssemblyTool = Pick<
  Tool,
  "id" | "kind" | "code" | "label" | "rfid" | "compatible_types" | "status"
>;

export type AssemblyGlueBatch = {
  id: number;
  glue_type: string;
  batch_no: string;
  pdb_sn: string | null;
  status: string;
  mixed_at: string | null;
  pot_life_minutes: number | null;
  pot_life_remaining_seconds: number | null;
  pot_life_expired: boolean;
};

export type AssemblyPreview = {
  valid: boolean;
  submittable: boolean;
  submittable_reason: string | null;
  summary: string;
  slot: string;
  parent: AssemblyComponent | null;
  child: AssemblyComponent | null;
  tool: AssemblyTool | null;
  /** Resolved tools per `assembly_tool_slots[].key`, in selection order —
   * the server's `AssemblyPreviewOut.tools` (schemas.py), defaulting to `{}`
   * once only the legacy single `tool` is in play. This is the source of
   * truth for the Review step: never re-derive it from locally selected
   * tools, the server already revalidated everything. Optional here only so
   * the offline demo preview (which never uses a slot layout) still
   * type-checks without it. */
  tools?: Record<string, AssemblyTool[]>;
  glue_batch: AssemblyGlueBatch | null;
  pdb_properties: Record<string, string>;
  issues: AssemblyIssue[];
  warnings: AssemblyIssue[];
};

export type AssemblyStageResult = {
  preview: AssemblyPreview;
  action: OutboxAction;
};

/** Mirror this component's PDB test-run results into local evidence. */
export function postComponentSyncEvidence(sn: string): Promise<EvidenceSyncResult> {
  return request<EvidenceSyncResult>(
    `/api/components/${encodeURIComponent(sn)}/sync-evidence`,
    { method: "POST" },
  );
}

export function getStageSuggestion(sn: string, signal?: AbortSignal): Promise<StageSuggestion> {
  return request<StageSuggestion>(
    `/api/components/${encodeURIComponent(sn)}/stage-suggestion`,
    { signal },
  );
}

export type OutboxCreateBody = {
  institute_code: string;
  kind: string;
  payload: Record<string, unknown>;
  created_by: string;
};

export function postOutboxAction(body: OutboxCreateBody): Promise<OutboxAction> {
  return request<OutboxAction>("/api/outbox", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export type ComponentRegisterBody = {
  component_type: string;
  type_code: string;
  institute_code: string;
  local_name?: string;
  subproject?: string;
};

/** Queue a DUMMY module/hybrid registration as an outbox draft (docs/10).
 * The backend refuses any type outside the registrable allowlist. */
export function postComponentRegister(body: ComponentRegisterBody): Promise<OutboxAction> {
  return request<OutboxAction>("/api/components/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function postComponentSync(instituteCode: string): Promise<ComponentSyncResult> {
  return request<ComponentSyncResult>(
    `/api/sync/components/${encodeURIComponent(instituteCode)}`,
    { method: "POST" },
  );
}

/** Start (or join) the single-flight background component sync. */
export function startComponentSyncJob(instituteCode: string): Promise<ComponentSyncJob> {
  return request<ComponentSyncJob>(
    `/api/sync/jobs/components/${encodeURIComponent(instituteCode)}`,
    { method: "POST" },
  );
}

/** Start (or join) the single-flight background evidence/attachment sync. */
export function startEvidenceSyncJob(instituteCode: string): Promise<EvidenceSyncJob> {
  return request<EvidenceSyncJob>(
    `/api/sync/jobs/evidence/${encodeURIComponent(instituteCode)}`,
    { method: "POST" },
  );
}

/** Poll one persisted sync job. */
export function getSyncJob(id: number, signal?: AbortSignal): Promise<SyncJob> {
  return request<SyncJob>(`/api/sync/jobs/${id}`, { signal });
}

/** Recover a sync after navigation/reload. No active job is a 204. */
export async function getActiveSyncJob(
  kind: SyncJobKind,
  instituteCode?: string,
  signal?: AbortSignal,
): Promise<SyncJob | null> {
  const query = new URLSearchParams({ kind });
  if (instituteCode !== undefined) query.set("institute_code", instituteCode);
  const response = await rawFetch(
    `/api/sync/jobs/active?${query.toString()}`,
    { signal },
  );
  if (response.status === 204) return null;
  return (await response.json()) as SyncJob;
}

/** Recover the newest persisted job, including terminal success or failure. */
export async function getLatestSyncJob(
  kind: SyncJobKind,
  instituteCode?: string,
  signal?: AbortSignal,
): Promise<SyncJob | null> {
  const query = new URLSearchParams({ kind });
  if (instituteCode !== undefined) query.set("institute_code", instituteCode);
  const response = await rawFetch(`/api/sync/jobs/latest?${query.toString()}`, { signal });
  if (response.status === 204) return null;
  return (await response.json()) as SyncJob;
}

export async function getActiveComponentSyncJob(
  signal?: AbortSignal,
): Promise<ComponentSyncJob | null> {
  const job = await getActiveSyncJob("components", undefined, signal);
  return job === null || job.kind === "components" ? job : null;
}

export async function getActiveEvidenceSyncJob(
  signal?: AbortSignal,
): Promise<EvidenceSyncJob | null> {
  const job = await getActiveSyncJob("evidence", undefined, signal);
  return job === null || job.kind === "evidence" ? job : null;
}

export function getInstitutes(signal?: AbortSignal): Promise<Institute[]> {
  return request<Institute[]>("/api/institutes", { signal });
}

export function postInstitute(body: InstituteCreate): Promise<Institute> {
  return request<Institute>("/api/institutes", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** Admin-only user management (docs/06). The backend scopes every call to the
 * signed-in admin's institute; new users join it automatically. */
export function getUsers(signal?: AbortSignal): Promise<UserOut[]> {
  return request<UserOut[]>("/api/users", { signal });
}

export function postUser(body: UserCreateBody): Promise<UserOut> {
  return request<UserOut>("/api/users", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function patchUser(id: number, body: UserUpdateBody): Promise<UserOut> {
  return request<UserOut>(`/api/users/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function getDashboardSummary(signal?: AbortSignal): Promise<DashboardSummary> {
  return request<DashboardSummary>("/api/dashboard/summary", { signal });
}

/** Admin-only local telemetry. Reading it never contacts the PDB. */
export function getOpsHealth(
  instituteCode?: string,
  signal?: AbortSignal,
): Promise<OpsHealth> {
  return request<OpsHealth>(
    `/api/ops/health${queryString({ institute_code: instituteCode })}`,
    { signal },
  );
}

export function getProductionStats(
  query: ProductionStatsQuery = {},
  signal?: AbortSignal,
): Promise<ProductionStats> {
  return request<ProductionStats>(`/api/stats/production${queryString(query)}`, { signal });
}

export function getStatsDimensions(signal?: AbortSignal): Promise<StatsDimensions> {
  return request<StatsDimensions>("/api/stats/dimensions", { signal });
}

export function getRequiredTestStats(
  institute?: string,
  signal?: AbortSignal,
): Promise<RequiredTestStats> {
  return request<RequiredTestStats>(
    `/api/stats/required-tests${queryString({ institute })}`,
    { signal },
  );
}

export function getMeasurementDimensions(
  signal?: AbortSignal,
): Promise<MeasurementDimensions> {
  return request<MeasurementDimensions>("/api/stats/measurements/dimensions", { signal });
}

export function getMeasurementSeries(
  query: { test_type: string; result: string; x_result?: string },
  signal?: AbortSignal,
): Promise<MeasurementSeries> {
  const params = queryString({
    test_type: query.test_type,
    result: query.result,
    x_result: query.x_result,
  });
  return request<MeasurementSeries>(`/api/stats/measurements${params}`, { signal });
}

export function getTools(query: ToolQuery = {}, signal?: AbortSignal): Promise<Tool[]> {
  return request<Tool[]>(`/api/tools${queryString(query)}`, { signal });
}

/** Resolve a scanned RFID or printed code to a single tool (404 if unknown). */
export function scanTool(
  code: string,
  institute?: string,
  signal?: AbortSignal,
): Promise<Tool> {
  return request<Tool>(`/api/tools/scan${queryString({ code, institute })}`, { signal });
}

export function postTool(body: ToolCreateBody): Promise<Tool> {
  return request<Tool>("/api/tools", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function patchTool(id: number, body: ToolUpdateBody): Promise<Tool> {
  return request<Tool>(`/api/tools/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function deleteTool(id: number): Promise<void> {
  return requestVoid(`/api/tools/${id}`, { method: "DELETE" });
}

export function postToolSync(instituteCode: string): Promise<ToolSyncResult> {
  return request<ToolSyncResult>(`/api/sync/tools/${encodeURIComponent(instituteCode)}`, {
    method: "POST",
  });
}

export function getOutboxContract(signal?: AbortSignal): Promise<OutboxContract> {
  return request<OutboxContract>("/api/outbox/contract", { signal });
}

export function scanAssemblyComponent(
  code: string,
  signal?: AbortSignal,
): Promise<ComponentOut> {
  return request<ComponentOut>(`/api/assembly/scan-component${queryString({ code })}`, {
    signal,
  });
}

export function postAssemblyPreview(body: AssemblyDraft): Promise<AssemblyPreview> {
  return request<AssemblyPreview>("/api/assembly/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function postAssemblyAction(body: AssemblyDraft): Promise<AssemblyStageResult> {
  return request<AssemblyStageResult>("/api/assembly/actions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function getOutbox(status?: string, signal?: AbortSignal): Promise<OutboxAction[]> {
  return request<OutboxAction[]>(`/api/outbox${queryString({ status })}`, { signal });
}

/** Read one action including terminal worker states such as `confirmed`.
 * Component-scoped staged endpoints intentionally omit terminal actions, so
 * this is the authoritative status record for bounded confirmation polling. */
export function getOutboxAction(id: number, signal?: AbortSignal): Promise<OutboxAction> {
  return request<OutboxAction>(`/api/outbox/${id}`, { signal });
}

export function getAudit(limit = 100, signal?: AbortSignal): Promise<AuditEvent[]> {
  return request<AuditEvent[]>(`/api/audit?limit=${encodeURIComponent(String(limit))}`, { signal });
}

/** Complete, chronologically ordered audit trail for one staged action. */
export function getOutboxAudit(
  actionId: number,
  signal?: AbortSignal,
): Promise<AuditEvent[]> {
  return request<AuditEvent[]>(`/api/outbox/${actionId}/audit`, { signal });
}

export function getIngestFiles(status?: string, signal?: AbortSignal): Promise<IngestFile[]> {
  return request<IngestFile[]>(`/api/ingest/files${queryString({ status })}`, { signal });
}

/** Read the locally mirrored form schemas for one component type. */
export function getTestTypeSchemas(
  componentType: string,
  signal?: AbortSignal,
): Promise<TestTypeSchema[]> {
  return request<TestTypeSchema[]>(
    `/api/test-types${queryString({ component_type: componentType })}`,
    { signal },
  );
}

/** Refresh one component type's schema snapshot through the signed-in user's PDB account. */
export function postTestTypeSchemaSync(
  componentType: string,
): Promise<TestTypeSchemaSyncResult> {
  return request<TestTypeSchemaSyncResult>(
    `/api/test-types/sync${queryString({ component_type: componentType })}`,
    { method: "POST" },
  );
}

export function postIngestFile(body: IngestFileCreate): Promise<IngestFile> {
  return request<IngestFile>("/api/ingest/files", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function getIngestPreview(id: number, signal?: AbortSignal): Promise<IngestPreview> {
  return request<IngestPreview>(`/api/ingest/files/${id}/preview`, { signal });
}

export function postIngestOutboxProposal(
  id: number,
  body: IngestProposalCreate,
): Promise<OutboxAction> {
  return request<OutboxAction>(`/api/ingest/files/${id}/propose-outbox`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function postOutboxTransition(
  id: number,
  body: OutboxTransitionBody,
): Promise<OutboxAction> {
  return request<OutboxAction>(`/api/outbox/${id}/transition`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

// ---- Auth endpoints ---------------------------------------------------------

/** Sign in with email + password. 200 sets the session + `itkflow_csrf`
 * cookies and returns the user; 401 on bad or inactive credentials. */
export function postLogin(body: LoginBody): Promise<MeOut> {
  return request<MeOut>("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** Current session's user, or a thrown `ApiError(401)` when not signed in. */
export function getMe(signal?: AbortSignal): Promise<MeOut> {
  return request<MeOut>("/api/auth/me", { signal });
}

export type SetupStatus = { needs_admin: boolean };

export type SetupAdminBody = { email: string; display_name: string; password: string };

/** First-run probe: `needs_admin` is true while no user account exists yet. */
export function getSetupStatus(signal?: AbortSignal): Promise<SetupStatus> {
  return request<SetupStatus>("/api/setup", { signal });
}

/** Create the very first admin account and sign it in. 409 once any user exists. */
export function postSetupAdmin(body: SetupAdminBody): Promise<MeOut> {
  return request<MeOut>("/api/setup/admin", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** End the current session (204). */
export function postLogout(): Promise<void> {
  return requestVoid("/api/auth/logout", { method: "POST" });
}

// ---- Personal PDB connection endpoints ------------------------------------

/** Read only non-secret connection metadata for the signed-in user. */
export function getPdbConnection(signal?: AbortSignal): Promise<PdbConnectionOut> {
  return request<PdbConnectionOut>("/api/account/pdb-connection", { signal });
}

/** Replace the signed-in user's PDB access codes and verify the new pair. */
export function putPdbConnection(body: PdbCredentialsPut): Promise<PdbConnectionOut> {
  return request<PdbConnectionOut>("/api/account/pdb-connection", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** Re-test the saved pair without returning it to the browser. */
export function testPdbConnection(): Promise<PdbConnectionOut> {
  return request<PdbConnectionOut>("/api/account/pdb-connection/test", {
    method: "POST",
  });
}

/** Remove only the signed-in user's saved PDB connection (204). */
export function deletePdbConnection(): Promise<void> {
  return requestVoid("/api/account/pdb-connection", { method: "DELETE" });
}

/** List only non-secret metadata for saved public-share passwords. */
export function getShareCredentials(signal?: AbortSignal): Promise<ShareCredentialOut[]> {
  return request<ShareCredentialOut[]>("/api/account/share-credentials", { signal });
}

/** Validate the link shape and locally save one encrypted public-share password. */
export function putShareCredential(body: ShareCredentialPut): Promise<ShareCredentialOut> {
  return request<ShareCredentialOut>("/api/account/share-credentials", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** Remove one account-owned saved public-share password. */
export function deleteShareCredential(id: number): Promise<void> {
  return requestVoid(`/api/account/share-credentials/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}


// ---- Glue batches (Phase 4, docs/11) -----------------------------------------

export type GlueBatchStatus = "new" | "in_use" | "expired" | "empty";

export type GlueBatch = {
  id: number;
  glue_type: string;
  batch_no: string;
  pdb_sn: string | null;
  status: GlueBatchStatus;
  manufacturing_date: string | null;
  expiry_date: string | null;
  opening_date: string | null;
  bipack_count: number | null;
  note: string | null;
  mixed_at: string | null;
  pot_life_minutes: number | null;
  institute_id: number | null;
  created_at: string;
  /** Server-computed snapshot; the screen ticks it down locally between loads. */
  pot_life_remaining_seconds: number | null;
  pot_life_expired: boolean;
  usage_count: number;
};

export type GlueUsage = {
  id: number;
  glue_batch_id: number;
  component_sn: string;
  amount_mg: number | null;
  note: string | null;
  used_by: string;
  used_at: string;
};

export type GlueBatchQuery = {
  status?: string;
  glue_type?: string;
  q?: string;
  institute?: string;
};

export type GlueBatchCreateBody = {
  glue_type: string;
  batch_no: string;
  pdb_sn?: string;
  status?: GlueBatchStatus;
  manufacturing_date?: string;
  expiry_date?: string;
  opening_date?: string;
  bipack_count?: number;
  note?: string;
};

export type GlueBatchUpdateBody = Partial<Omit<GlueBatchCreateBody, "glue_type">>;

export function getGlueBatches(
  query: GlueBatchQuery = {},
  signal?: AbortSignal,
): Promise<GlueBatch[]> {
  return request<GlueBatch[]>(`/api/glue-batches${queryString(query)}`, { signal });
}

export function scanGlueBatch(
  code: string,
  institute?: string,
  signal?: AbortSignal,
): Promise<GlueBatch> {
  return request<GlueBatch>(`/api/glue-batches/scan${queryString({ code, institute })}`, {
    signal,
  });
}

export function postGlueBatch(body: GlueBatchCreateBody): Promise<GlueBatch> {
  return request<GlueBatch>("/api/glue-batches", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** Admin-only institute profile update. Operational settings are validated server-side. */
export function patchInstitute(code: string, body: InstituteUpdate): Promise<Institute> {
  return request<Institute>(`/api/institutes/${encodeURIComponent(code)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function patchGlueBatch(id: number, body: GlueBatchUpdateBody): Promise<GlueBatch> {
  return request<GlueBatch>(`/api/glue-batches/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** Start the pot-life timer ("just mixed"); pot life falls back to the
 * institute profile's per-type default when omitted. */
export function postGlueBatchMix(
  id: number,
  potLifeMinutes?: number,
): Promise<GlueBatch> {
  return request<GlueBatch>(`/api/glue-batches/${id}/mix`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(potLifeMinutes ? { pot_life_minutes: potLifeMinutes } : {}),
  });
}

export function getGlueUsage(id: number, signal?: AbortSignal): Promise<GlueUsage[]> {
  return request<GlueUsage[]>(`/api/glue-batches/${id}/usage`, { signal });
}

export type GlueUsageCreateBody = { component_sn: string; amount_mg?: number; note?: string };

export function postGlueUsage(id: number, body: GlueUsageCreateBody): Promise<GlueUsage> {
  return request<GlueUsage>(`/api/glue-batches/${id}/usage`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

// ---- Shipments (Phase 4, docs/11) --------------------------------------------

export type ShipmentDirection = "incoming" | "outgoing" | "internal" | "unknown";

export type ShipmentReceptionTestStatus = "missing" | "pending" | "passed" | "failed";

export type ShipmentReceptionTest = {
  test_type: string;
  status: ShipmentReceptionTestStatus;
};

export type ShipmentItem = {
  sn: string;
  component_type?: string | null;
  component_mirrored: boolean;
  is_dummy: boolean;
  submittable: boolean;
  submittable_reason: string | null;
  reception_tests_configured: boolean;
  reception_test_status: ShipmentReceptionTestStatus;
  reception_tests: ShipmentReceptionTest[];
};

export type ShipmentChecklistItem = { label: string; done: boolean };

export type ShipmentReceptionItem = { sn: string; received: boolean; note?: string | null };

export type Shipment = {
  id: number;
  pdb_id: string;
  name: string | null;
  sender_code: string;
  recipient_code: string;
  status: string;
  direction: ShipmentDirection;
  sent_at: string | null;
  items: ShipmentItem[];
  institute_id: number | null;
  synced_at: string;
  reception_status: "pending" | "in_progress" | "done";
  reception_checklist: ShipmentChecklistItem[];
  reception_items: ShipmentReceptionItem[];
  reception_note: string | null;
  reception_by: string | null;
  reception_updated_at: string | null;
  reception_tests_configured: boolean;
  reception_test_status: ShipmentReceptionTestStatus;
};

export type ShipmentQuery = {
  direction?: string;
  status?: string;
  reception?: string;
  q?: string;
};

export function getShipments(
  query: ShipmentQuery = {},
  signal?: AbortSignal,
): Promise<Shipment[]> {
  return request<Shipment[]>(`/api/shipments${queryString(query)}`, { signal });
}

export function getShipment(id: number, signal?: AbortSignal): Promise<Shipment> {
  return request<Shipment>(`/api/shipments/${id}`, { signal });
}

export type ShipmentSyncResult = {
  institute_code: string;
  created: number;
  updated: number;
  unchanged: number;
  total: number;
};

export function postShipmentSync(instituteCode: string): Promise<ShipmentSyncResult> {
  return request<ShipmentSyncResult>(
    `/api/sync/shipments/${encodeURIComponent(instituteCode)}`,
    { method: "POST" },
  );
}

export type ShipmentReceptionBody = {
  status?: "pending" | "in_progress" | "done";
  checklist?: ShipmentChecklistItem[];
  items?: ShipmentReceptionItem[];
  note?: string;
  test_override?: boolean;
  test_override_reason?: string;
};

export function postShipmentReception(
  id: number,
  body: ShipmentReceptionBody,
): Promise<Shipment> {
  return request<Shipment>(`/api/shipments/${id}/reception`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

// ---- Reminders & notification channels (Phase 4, docs/11) --------------------

export type ReminderScheduleKind = "once" | "daily" | "weekly" | "monthly";

export type Reminder = {
  id: number;
  title: string;
  note: string | null;
  channel: string | null;
  schedule_kind: ReminderScheduleKind;
  next_due_at: string;
  active: boolean;
  last_fired_at: string | null;
  last_error: string | null;
  created_by: string;
  institute_id: number | null;
  created_at: string;
  updated_at: string;
};

export type AuditEvent = {
  id: number;
  ts: string;
  actor: string;
  user_id: number | null;
  action: string;
  subject: string;
  detail: Record<string, unknown>;
  outbox_action_id: number | null;
};

export function getReminders(active?: boolean, signal?: AbortSignal): Promise<Reminder[]> {
  return request<Reminder[]>(
    `/api/reminders${queryString({ active: active === undefined ? undefined : String(active) })}`,
    { signal },
  );
}

export type ReminderCreateBody = {
  title: string;
  note?: string;
  channel?: string;
  schedule_kind: ReminderScheduleKind;
  next_due_at: string;
};

export function postReminder(body: ReminderCreateBody): Promise<Reminder> {
  return request<Reminder>("/api/reminders", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export type ReminderUpdateBody = {
  title?: string;
  note?: string;
  /** An empty string clears the channel. */
  channel?: string;
  schedule_kind?: ReminderScheduleKind;
  next_due_at?: string;
  active?: boolean;
};

export function patchReminder(id: number, body: ReminderUpdateBody): Promise<Reminder> {
  return request<Reminder>(`/api/reminders/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function deleteReminder(id: number): Promise<void> {
  return requestVoid(`/api/reminders/${id}`, { method: "DELETE" });
}

export type ReminderOccurrence = {
  id: number;
  reminder_id: number;
  institute_id: number | null;
  due_at: string;
  fired_at: string;
  delivery_status: "sent" | "audit_only" | "failed";
  delivery_error: string | null;
  escalation_due_at: string | null;
  escalation_channel: string | null;
  escalated_at: string | null;
  escalation_error: string | null;
  acknowledged_at: string | null;
  acknowledged_by: string | null;
};

export function getReminderOccurrences(
  openOnly = false,
  reminderId?: number,
  signal?: AbortSignal,
): Promise<ReminderOccurrence[]> {
  return request<ReminderOccurrence[]>(
    `/api/reminder-occurrences${queryString({
      open_only: String(openOnly),
      reminder_id: reminderId === undefined ? undefined : String(reminderId),
    })}`,
    { signal },
  );
}

export function acknowledgeReminderOccurrence(id: number): Promise<ReminderOccurrence> {
  return request<ReminderOccurrence>(`/api/reminder-occurrences/${id}/ack`, {
    method: "POST",
  });
}

/** Names and kinds only — webhook URLs never reach the browser. */
export type NotificationChannel = { name: string; kind: string };

export function getNotificationChannels(signal?: AbortSignal): Promise<NotificationChannel[]> {
  return request<NotificationChannel[]>("/api/notifications/channels", { signal });
}

export type NotificationTestResult = { channel: string; sent: boolean };

export function postNotificationTest(
  channel: string,
  instituteCode?: string,
): Promise<NotificationTestResult> {
  return request<NotificationTestResult>("/api/notifications/test", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      channel,
      ...(instituteCode === undefined ? {} : { institute_code: instituteCode }),
    }),
  });
}
