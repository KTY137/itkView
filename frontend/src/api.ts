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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, init);
  } catch (err) {
    // Keep aborts distinguishable from real network failures.
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new ApiError("Backend not reachable", 0);
  }
  if (!res.ok) {
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
  return (await res.json()) as T;
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
