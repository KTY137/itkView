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
  uploaded_by: string;
};

export type IngestProposalCreate = {
  created_by: string;
  institute_code?: string;
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
  status: string;
  created_at: string;
};

export type ToolQuery = { kind?: string; fits?: string; status?: string };

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

export type ComponentImage = {
  id: string;
  title: string;
  test_type: string | null;
  filename: string | null;
  content_type: string | null;
};

export function getComponentImages(sn: string, signal?: AbortSignal): Promise<ComponentImage[]> {
  return request<ComponentImage[]>(`/api/components/${encodeURIComponent(sn)}/images`, { signal });
}

/** URL of one image's binary (streamed by the backend from the PDB). */
export function componentImageUrl(sn: string, id: string): string {
  return `/api/components/${encodeURIComponent(sn)}/images/${encodeURIComponent(id)}`;
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
};

/** Mirror this component's PDB test-run results into local evidence. */
export function postComponentSyncEvidence(sn: string): Promise<EvidenceSyncResult> {
  return request<EvidenceSyncResult>(
    `/api/components/${encodeURIComponent(sn)}/sync-evidence`,
    { method: "POST" },
  );
}

export type InstituteEvidenceSyncResult = {
  institute_code: string;
  components_processed: number;
  created: number;
  updated: number;
  unchanged: number;
  total: number;
};

/** Mirror PDB test-run evidence for every live component of an institute. */
export function postInstituteEvidenceSync(code: string): Promise<InstituteEvidenceSyncResult> {
  return request<InstituteEvidenceSyncResult>(
    `/api/sync/evidence/${encodeURIComponent(code)}`,
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

export function getProductionStats(
  query: ProductionStatsQuery = {},
  signal?: AbortSignal,
): Promise<ProductionStats> {
  return request<ProductionStats>(`/api/stats/production${queryString(query)}`, { signal });
}

export function getStatsDimensions(signal?: AbortSignal): Promise<StatsDimensions> {
  return request<StatsDimensions>("/api/stats/dimensions", { signal });
}

export function getTools(query: ToolQuery = {}, signal?: AbortSignal): Promise<Tool[]> {
  return request<Tool[]>(`/api/tools${queryString(query)}`, { signal });
}

/** Resolve a scanned RFID or printed code to a single tool (404 if unknown). */
export function scanTool(code: string, signal?: AbortSignal): Promise<Tool> {
  return request<Tool>(`/api/tools/scan${queryString({ code })}`, { signal });
}

export function postToolSync(instituteCode: string): Promise<ToolSyncResult> {
  return request<ToolSyncResult>(`/api/sync/tools/${encodeURIComponent(instituteCode)}`, {
    method: "POST",
  });
}

export function getOutboxContract(signal?: AbortSignal): Promise<OutboxContract> {
  return request<OutboxContract>("/api/outbox/contract", { signal });
}

export function getOutbox(status?: string, signal?: AbortSignal): Promise<OutboxAction[]> {
  return request<OutboxAction[]>(`/api/outbox${queryString({ status })}`, { signal });
}

export function getIngestFiles(status?: string, signal?: AbortSignal): Promise<IngestFile[]> {
  return request<IngestFile[]>(`/api/ingest/files${queryString({ status })}`, { signal });
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

/** End the current session (204). */
export function postLogout(): Promise<void> {
  return requestVoid("/api/auth/logout", { method: "POST" });
}
