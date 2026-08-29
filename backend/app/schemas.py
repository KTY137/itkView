# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-FileComment: itkflow-468e6c923647
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    StringConstraints,
    model_validator,
)

from app.ingestion import ResultSummary
from app.outbox import OutboxStatus


class InstituteCreate(BaseModel):
    code: str = Field(min_length=2, max_length=16, pattern=r"^[A-Z0-9_]+$")
    name: str = Field(min_length=1, max_length=120)
    local_name_prefix: str = Field(default="", max_length=32)
    settings: dict = Field(default_factory=dict)


class InstituteUpdate(BaseModel):
    # Edit an institute profile's config (branding, stage_requirements,
    # required_properties, …). `settings` is shallow-merged at the top level.
    name: str | None = Field(default=None, min_length=1, max_length=120)
    local_name_prefix: str | None = Field(default=None, max_length=32)
    settings: dict | None = None


class InstituteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    local_name_prefix: str
    settings: dict
    created_at: datetime


class ProductionStatusReasonOut(BaseModel):
    """One fail-closed reason attached to a component production marker."""

    code: Literal[
        "required_test_failed",
        "required_test_missing",
        "unknown_stage",
        "missing_profile",
        "stale_mirror",
        "trashed",
        "provisional_profile",
    ]
    stage: str | None = None
    test_type: str | None = None


class ComponentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sn: str
    local_name: str | None
    component_type: str
    type_code: str
    stage: str
    location: str
    institute_code: str
    parent_sn: str | None
    is_dummy: bool
    trashed: bool
    stale: bool
    synced_at: datetime
    # Calculated from the institute stage model and the local evidence mirror
    # by component read endpoints. Optional defaults keep non-overview helper
    # endpoints backwards compatible until they opt into the projection.
    production_status: Literal[
        "clear", "hold", "incomplete", "unknown", "not_applicable"
    ] | None = None
    production_policy_source: Literal[
        "profile_override", "seed_default", "missing_profile"
    ] | None = None
    production_policy_approved: bool | None = None
    production_status_reasons: list[ProductionStatusReasonOut] = Field(default_factory=list)


class ComponentDetailOut(ComponentOut):
    children: list[ComponentOut]


class ComponentSyncOut(BaseModel):
    institute_code: str
    fetched: int
    skipped: int
    created: int
    updated: int
    unchanged: int
    stale: int
    total: int


class EvidenceSyncJobResultOut(BaseModel):
    institute_code: str
    sync_mode: Literal["standard", "lightweight"] = "standard"
    component_types: list[str]
    components_processed: int
    created: int
    updated: int
    unchanged: int
    total: int
    attachments_downloaded: int
    attachments_reused: int
    attachments_failed: int
    attachments_skipped: int = 0
    attachments_authentication_required: int = 0
    attachments_total: int


SyncJobStatus = Literal["queued", "running", "succeeded", "failed", "interrupted"]
SyncJobPhase = Literal[
    "queued",
    "fetching",
    "mapping",
    "upserting",
    "stage_events",
    "tools",
    "attachments",
    "committing",
    "complete",
]


class SyncJobOut(BaseModel):
    """Pollable state of a background component-mirror sync."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: Literal["components", "evidence"]
    institute_code: str
    status: SyncJobStatus
    phase: SyncJobPhase
    current: int
    total: int | None
    percent: float | None
    message: str
    result: ComponentSyncOut | EvidenceSyncJobResultOut | None
    error: str | None
    created_at: datetime
    started_at: datetime | None
    updated_at: datetime
    finished_at: datetime | None
    # Calculated by the server from the same heartbeat contract that governs
    # stale takeover. Clients must not guess from their own wall clock.
    heartbeat_stale: bool = False
    stale_after_seconds: int = 180


class ToolSyncOut(BaseModel):
    institute_code: str
    created: int
    updated: int
    unchanged: int
    skipped: int
    total: int


class RequirementCheckOut(BaseModel):
    stage: str
    test_type: str
    status: str  # passed | failed | missing


class StageSuggestionOut(BaseModel):
    sn: str
    current_stage: str
    next_stage: str | None
    move_suggested: bool
    suggested_stage: str | None
    checks: list[RequirementCheckOut]
    blocking: list[RequirementCheckOut]


class PreviewRequirementCheckOut(BaseModel):
    stage: str
    test_type: str
    status: Literal["passed", "failed", "missing", "pending"]


class ComponentPreviewStateOut(BaseModel):
    stage: str
    checks: list[PreviewRequirementCheckOut]


class ComponentPreviewActionOut(BaseModel):
    id: int
    kind: str
    status: str
    summary: str
    to_stage: str | None
    test_type: str | None
    created_by: str
    created_at: datetime
    submittable: bool
    submittable_reason: str | None


class TestRunAttachmentOut(BaseModel):
    """One mirrored attachment. `stored` distinguishes "known" from "on disk"."""

    source: str
    code: str
    test_type: str
    test_run_ref: str | None
    filename: str | None
    content_type: str | None
    title: str | None
    size_bytes: int | None
    stored: bool
    is_image: bool


class ComponentHistoryEventOut(BaseModel):
    """One dated fact from a component's record.

    `kind` says which fact it is; the fields that do not apply stay null rather
    than being folded into a formatted string, so a caller can group, filter or
    translate without parsing prose.
    """

    kind: Literal["stage", "test", "location"]
    # Null for a legacy run whose instrument time was never mirrored. The row
    # is still shown, marked undated, because dropping it would hide real work.
    at: datetime | None
    stage: str | None = None
    # The site a relocation moved the component to. Named, never a raw PDB
    # object id: an unresolvable entry is dropped by the sync instead.
    location: str | None = None
    rework: bool | None = None
    test_type: str | None = None
    passed: bool | None = None
    # A run the PDB has retracted. Not evidence for a gate, but still history.
    withdrawn: bool | None = None
    external_ref: str | None = None


class ComponentHistoryOut(BaseModel):
    component_sn: str
    events: list[ComponentHistoryEventOut]


class ThumbnailPartOut(BaseModel):
    """The assembled part a borrowed list tile was taken from."""

    sn: str
    component_type: str
    type_code: str
    local_name: str | None


class AttachmentLocatorOut(BaseModel):
    """Public identity of one physical attachment blob, and whose it is.

    `sn` is the component whose mirror holds the bytes — the serial the binary
    route must be called with, which is not the listed component when the tile
    was borrowed. `part` is set exactly then, so a caller can mark the tile
    instead of passing a sensor's photograph off as the module's.
    """

    source: str
    code: str
    sn: str
    part: ThumbnailPartOut | None = None


class ChildAttachmentsOut(BaseModel):
    """One direct child's locally stored images, tagged with whose they are."""

    sn: str
    component_type: str
    type_code: str
    local_name: str | None
    attachments: list[TestRunAttachmentOut]


class ComponentAttachmentsOut(BaseModel):
    """A component's own attachment index plus its children's stored images.

    The children stay in their own groups rather than being folded into
    `attachments`: a photograph of a sensor is evidence about that sensor, and
    a gallery that hides which part it shows states something untrue.
    """

    component_sn: str
    attachments: list[TestRunAttachmentOut]
    children: list[ChildAttachmentsOut]


class ComponentPreviewTestOut(BaseModel):
    """One staged, not-yet-pushed test upload ("ghost").

    Same shape as a mirrored run so the frontend can render both through one
    component; ``ghost`` is always ``True`` here and ``attachments`` is always
    empty, because the run does not exist in the PDB yet.
    """

    test_type: str
    passed: bool | None
    external_ref: str | None
    measured_at: datetime | None
    synced_at: datetime | None
    source: str
    run_number: str | int | None
    properties: dict[str, Any]
    results: dict[str, Any]
    result_meta: dict[str, Any]
    attachments: list[TestRunAttachmentOut]
    ghost: bool
    outbox_action_id: int | None


class ComponentProjectedStateOut(ComponentPreviewStateOut):
    """Projected stage and checks, plus the staged uploads only.

    ``ghost_tests`` deliberately does NOT contain mirrored runs: those carry raw
    measured values (a single IV sweep dwarfs the rest of this response) and are
    fetched on demand from ``GET /api/components/{sn}/tests`` when the operator
    opens the collapsed run list. The field is named ``ghost_tests`` rather than
    ``tests`` so nothing can mistake it for the component's full test history.
    """

    ghost_tests: list[ComponentPreviewTestOut]


class WorksheetScalarOut(BaseModel):
    code: str
    name: str
    value: Any


class WorksheetArraySummaryOut(BaseModel):
    """A list or dict result reduced to a count — never the raw values.

    ``kind`` tells the frontend which affordance to render ("40 pts" for an
    array vs "20 entries" for a map); a dict-valued result (e.g. per-position
    metrology) is exactly as spammy inline as a raw array and must be summarised
    the same way, not treated as a scalar.
    """

    code: str
    name: str
    points: int
    kind: Literal["array", "map"]


class WorksheetLatestRunOut(BaseModel):
    external_ref: str | None
    measured_at: datetime | None
    run_number: str | int | None
    passed: bool | None
    scalars: list[WorksheetScalarOut]
    arrays: list[WorksheetArraySummaryOut]
    attachment_count: int


class WorksheetStagedRefOut(BaseModel):
    outbox_action_id: int
    status: str


class DerivedInputOut(BaseModel):
    """One raw reading a derived value was computed from.

    ``value`` is the number exactly as the PDB holds it — grams for every
    ``GW_`` code — so the operator can check the arithmetic against the scale.
    ``None`` means the reading is absent, which is why the step could not be
    judged; it is never shown as a zero.
    """

    code: str
    name: str
    value: float | None


class DerivedStepOut(BaseModel):
    """One derived quantity with the institute's verdict on it.

    Milligrams throughout: the PDB's grams are converted once, server-side, in
    ``app.glue_service``. ``verdict="unknown"`` always carries a ``reason`` —
    no target configured, an input missing, nothing measured yet, or readings
    that imply a physically impossible negative glue weight. The alternative,
    a blank cell that looks like a result, is exactly how 8 of 13 powerboard
    verdicts on the sheet this replaces became arithmetic on empty inputs.
    """

    key: str
    label: str
    measured_mg: float | None
    target_mg: float | None
    tolerance_mg: float | None
    verdict: Literal["ok", "too_little", "too_much", "unknown"]
    reason: Literal[
        "no_target", "missing_inputs", "no_run", "implausible_result"
    ] | None
    result_code: str | None
    inputs: list[DerivedInputOut]


class DerivedValuesOut(BaseModel):
    """Server-computed values for one row, present only where a profile derives them.

    The PDB does not judge glue weights — ``automaticGrading`` is false on every
    module schema with all thresholds null — so target, tolerance and verdict
    come from the institute profile and are computed here, never in the browser.
    ``process_source`` says whether the run named its own glue process, the
    profile's default was applied, or neither could be established.
    """

    kind: Literal["glue_weight"]
    process: str | None
    process_source: Literal["run", "profile_default", "unknown"]
    steps: list[DerivedStepOut]


class WorksheetRowOut(BaseModel):
    """``run_count`` counts only runs the PDB still stands behind.

    ``withdrawn_count`` reports the runs it has retracted (`state='deleted'`).
    They are excluded from ``latest``, from ``run_count`` and from the
    requirement ``status`` — a retracted measurement is not evidence — but they
    are counted rather than erased, because silently hiding data the PDB still
    holds is its own kind of false statement.

    ``derived`` is set only where the institute profile defines a derivation for
    this test type. It is present even on a row with no run at all — the targets
    are worth showing to whoever is about to perform the measurement, and every
    step then states ``reason="no_run"`` instead of leaving a blank.
    """

    test_type: str
    status: Literal["passed", "failed", "missing", "pending"]
    latest: WorksheetLatestRunOut | None
    staged: list[WorksheetStagedRefOut]
    run_count: int
    withdrawn_count: int
    derived: DerivedValuesOut | None = None


class WorksheetGroupOut(BaseModel):
    """``stage=None`` marks the trailing "Additional" group (see preview.py)."""

    stage: str | None
    reached: bool
    rows: list[WorksheetRowOut]


class WorksheetChildRowOut(BaseModel):
    """A child component's evidence for one test type.

    Deliberately without a requirement ``status``: a requirement check is a
    statement about the component whose page this is, and showing a child's
    evidence must not change what gates that component's stage move.
    ``latest.passed`` carries the run's own verdict instead.
    """

    test_type: str
    latest: WorksheetLatestRunOut | None
    run_count: int
    withdrawn_count: int


class WorksheetChildGroupOut(BaseModel):
    """Evidence that lives on one direct child of the component.

    Identity is the child's serial plus its type and local name, because that
    is what an operator recognises on the bench. Groups are emitted for every
    direct child, including one with no mirrored runs at all — "we looked and
    there is nothing" is a different statement from "we did not look".
    """

    sn: str
    component_type: str
    type_code: str
    local_name: str | None
    rows: list[WorksheetChildRowOut]


class ComponentPreviewWorksheetOut(BaseModel):
    groups: list[WorksheetGroupOut]
    children: list[WorksheetChildGroupOut]


class ComponentPreviewOut(BaseModel):
    current: ComponentPreviewStateOut
    staged_actions: list[ComponentPreviewActionOut]
    projected: ComponentProjectedStateOut
    worksheet: ComponentPreviewWorksheetOut


class CountBucket(BaseModel):
    label: str
    count: int


class DashboardSummaryOut(BaseModel):
    total_components: int
    last_synced_at: datetime | None
    oldest_synced_at: datetime | None
    stale_components: int
    trashed_components: int
    required_test_gaps: int
    components_with_test_gaps: int
    submitted_outbox: int
    approved_outbox: int
    review_outbox: int
    failed_outbox: int
    by_stage: list[CountBucket]
    by_component_type: list[CountBucket]
    by_institute: list[CountBucket]
    outbox_by_status: list[CountBucket]


class OutboxCreate(BaseModel):
    # Attribution is server-side now (docs/06): `created_by`/`user_id` are set
    # from the session, never the body. Any client-sent author is ignored.
    institute_code: str
    kind: str = Field(min_length=1, max_length=48)
    payload: dict = Field(default_factory=dict)


class ComponentRegisterIn(BaseModel):
    # Register a new DUMMY test component (docs/10). The server refuses any type
    # outside the registrable allowlist (MODULE/HYBRID) — never sensors/ASICs.
    component_type: str = Field(min_length=1, max_length=32)
    type_code: str = Field(min_length=1, max_length=32)
    institute_code: str
    local_name: str | None = Field(default=None, max_length=64)
    subproject: str = Field(default="SE", min_length=1, max_length=8)


class OutboxTransition(BaseModel):
    to: OutboxStatus
    error: str | None = None


class OutboxOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    institute_id: int
    kind: str
    payload: dict
    status: str
    error: str | None
    attempts: int
    external_ref: str | None
    created_by: str
    user_id: int | None
    created_at: datetime
    updated_at: datetime


class OutboxContractOut(BaseModel):
    statuses: list[str]
    transitions: dict[str, list[str]]
    terminal: list[str]
    worker_owned_targets: list[str]


class IngestFileCreate(BaseModel):
    # `uploaded_by` is set from the session (docs/06), not the body.
    filename: str = Field(min_length=1, max_length=240)
    payload: dict = Field(default_factory=dict)
    # A component-page upload pins the intended target. The payload stays
    # untouched; a conflicting embedded SN becomes a dry-run issue.
    component_sn: str | None = Field(default=None, min_length=1, max_length=20)
    # A workflow deep-link may also pin the expected test type. The raw
    # payload is not rewritten; a conflicting embedded test type is surfaced
    # as a blocking dry-run issue.
    test_type: str | None = Field(default=None, min_length=1, max_length=64)
    parser: Literal["manual-entry"] | None = None


class IngestFileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    sha256: str
    size_bytes: int
    status: str
    component_sn: str | None
    test_type: str | None
    parser: str | None
    error: str | None
    outbox_action_id: int | None
    uploaded_by: str
    created_at: datetime
    updated_at: datetime


class IngestProposalCreate(BaseModel):
    # `created_by`/`user_id` come from the session (docs/06), not the body.
    institute_code: str | None = Field(default=None, min_length=2, max_length=16)


class IngestPreviewOut(BaseModel):
    """Dry-run parse of a stored ingest payload plus mirror resolution."""

    file_id: int
    parser: str
    upload_ready: bool
    component_sn: str | None
    local_name: str | None
    component_mirrored: bool
    component_stage: str | None
    institute_code: str | None
    test_type: str | None
    run_number: str | None
    institution: str | None
    measured_at: str | None
    passed: bool | None
    problems: bool | None
    n_properties: int
    results: list[ResultSummary]
    issues: list[str]
    warnings: list[str]
    # Values the server computes from the payload before anything is staged, so
    # the operator sees the verdict while the file can still be rejected. Null
    # when the resolved institute derives nothing for this test type.
    derived: DerivedValuesOut | None = None


class TestTypeSchemaOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: int
    component_type: str
    test_code: str
    name: str
    schema_data: dict[str, Any] = Field(alias="schema")
    synced_at: datetime


class TestTypeSchemaSyncOut(BaseModel):
    component_type: str
    created: int
    updated: int
    unchanged: int
    total: int


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ts: datetime
    actor: str
    user_id: int | None
    action: str
    subject: str
    detail: dict
    outbox_action_id: int | None


class ProductCapabilitiesOut(BaseModel):
    account_management: bool
    mirror_sync: bool
    test_uploads: bool
    workflow_writes: bool
    operations_writes: bool
    pdb_writes: bool
    outbound_notifications: bool


class HealthOut(BaseModel):
    status: str
    app: str
    version: str
    product_variant: Literal["flow", "view"]
    write_features_enabled: bool
    capabilities: ProductCapabilitiesOut
    pdb_instance: str
    pdb_write_scope: str
    # Names the origin of a running copy. See app/provenance.py.
    provenance: str
    copyright: str


class OpsHeartbeatOut(BaseModel):
    service: Literal["outbox-worker", "reminder-scheduler"]
    status: Literal["healthy", "stale", "missing", "error", "disabled"]
    last_seen_at: datetime | None
    age_seconds: int | None
    stale_after_seconds: int
    detail: dict[str, Any]


class OpsSyncOut(BaseModel):
    active: list[SyncJobOut]
    latest: list[SyncJobOut]
    stale_active: int


class OpsOutboxOut(BaseModel):
    backlog: int
    failed: int
    at_attempt_limit: int
    oldest_open_at: datetime | None
    oldest_open_age_seconds: int | None


class OpsRemindersOut(BaseModel):
    active: int
    open_occurrences: int
    failed_occurrences: int
    escalated_open: int
    overdue: int


class OpsIngestOut(BaseModel):
    total: int
    triage: int
    failed: int
    parser_issues: int
    unassigned: int


class OpsHealthOut(BaseModel):
    status: Literal["healthy", "warning", "critical"]
    generated_at: datetime
    institute_code: str | None
    heartbeats: list[OpsHeartbeatOut]
    sync: OpsSyncOut
    outbox: OpsOutboxOut
    reminders: OpsRemindersOut
    ingest: OpsIngestOut
    diagnostics_available: bool = False


# --- Auth / users (docs/06) ------------------------------------------------

Role = Literal["viewer", "operator", "admin"]


class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=1, max_length=200)


class MeasurementResultDimensionOut(BaseModel):
    code: str
    name: str | None
    kind: Literal["array", "scalar"]
    runs: int


class MeasurementTestTypeOut(BaseModel):
    test_type: str
    results: list[MeasurementResultDimensionOut]


class MeasurementDimensionsOut(BaseModel):
    test_types: list[MeasurementTestTypeOut]


class MeasurementCurveOut(BaseModel):
    component_sn: str
    local_name: str | None
    external_ref: str | None
    measured_at: datetime | None
    passed: bool
    # x is None when no matching x_result array exists; the client plots
    # against the sample index then.
    x: list[float] | None
    y: list[float]


class MeasurementValueOut(BaseModel):
    component_sn: str
    local_name: str | None
    external_ref: str | None
    measured_at: datetime | None
    passed: bool
    value: float


class MeasurementSeriesOut(BaseModel):
    test_type: str
    result_code: str
    kind: Literal["array", "scalar"]
    result_name: str | None
    x_result: str | None
    x_name: str | None
    curves: list[MeasurementCurveOut]
    values: list[MeasurementValueOut]
    summary: dict[str, float] | None
    truncated: bool


class SetupStatusOut(BaseModel):
    # True while the user table is empty; the frontend then offers the
    # first-run "create the first admin account" form instead of the login.
    needs_admin: bool


class SetupAdminIn(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    display_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=8, max_length=200)


class UserCreate(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    display_name: str = Field(min_length=1, max_length=120)
    role: Role = "viewer"
    password: str = Field(min_length=8, max_length=200)


class UserUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    role: Role | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=200)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    display_name: str
    role: str
    is_active: bool
    institute_id: int | None
    created_at: datetime


class MeOut(BaseModel):
    id: int
    email: str
    display_name: str
    role: str
    institute_id: int | None
    institute_code: str | None
    # Double-submit CSRF token, also set as the product's readable CSRF cookie.
    # The frontend echoes it in the X-CSRF-Token header (docs/06).
    csrf_token: str


# --- Personal PDB connection ------------------------------------------------

PdbConnectionState = Literal[
    "not_configured",
    "verified",
    "invalid",
    "unreachable",
]


class PdbCredentialsPut(BaseModel):
    """Write-only Plus4U/PDB access-code pair for the signed-in account."""

    access_code1: SecretStr = Field(min_length=1, max_length=1000)
    access_code2: SecretStr = Field(min_length=1, max_length=1000)


class PdbConnectionOut(BaseModel):
    """Non-secret metadata; stored access codes are never returned by the API."""

    configured: bool
    state: PdbConnectionState
    instance: str
    identity: str | None
    institutions: list[str]
    last_checked_at: datetime | None
    verified_at: datetime | None


class ShareCredentialPut(BaseModel):
    """Write-only public-share URL/password pair."""

    url: str = Field(min_length=1, max_length=2048)
    password: SecretStr = Field(min_length=1, max_length=1024)


class ShareCredentialOut(BaseModel):
    """Non-secret public-share credential status."""

    id: int
    provider_host: str
    token_hint: str
    updated_at: datetime


# --- Tools / jigs (docs/07) ------------------------------------------------

ToolStatus = Literal["active", "flagged", "blacklisted"]


class ToolCreate(BaseModel):
    institute_code: str | None = Field(default=None, min_length=1, max_length=32)
    kind: str = Field(min_length=1, max_length=24)
    code: str = Field(min_length=1, max_length=64)
    label: str | None = Field(default=None, max_length=120)
    rfid: str | None = Field(default=None, max_length=64)
    compatible_types: list[str] = Field(default_factory=list)
    status: ToolStatus = "active"


class ToolUpdate(BaseModel):
    kind: str | None = Field(default=None, min_length=1, max_length=24)
    code: str | None = Field(default=None, min_length=1, max_length=64)
    label: str | None = Field(default=None, max_length=120)
    rfid: str | None = Field(default=None, max_length=64)
    compatible_types: list[str] | None = None
    status: ToolStatus | None = None


class ToolOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    code: str
    label: str | None
    rfid: str | None
    compatible_types: list[str]
    institute_id: int | None
    status: str
    created_at: datetime


# --- Scanner-first assembly dry-run / outbox contract ----------------------


class AssemblyDraftIn(BaseModel):
    parent_sn: str = Field(min_length=1, max_length=20)
    child_sn: str = Field(min_length=1, max_length=20)
    slot: str = Field(min_length=1, max_length=64)
    # Legacy single default-slot tool. Either this or `tools` must name at
    # least one tool; the domain layer enforces that and their consistency.
    tool_id: int | None = Field(default=None, gt=0)
    # Combined tool slots from the institute profile's `assembly_tool_slots`
    # (the production sheets' "jigs top, bottom" columns): slot key → tool ids.
    # Bounded at the wire so an oversized payload never reaches the resolver
    # (the domain cap is MAX_SLOT_TOOLS; 16 slots is far above any real bench).
    tools: (
        dict[
            Annotated[str, StringConstraints(min_length=1, max_length=32)],
            Annotated[list[Annotated[int, Field(gt=0)]], Field(max_length=4)],
        ]
        | None
    ) = Field(default=None)

    @model_validator(mode="after")
    def _bound_tool_slots(self) -> "AssemblyDraftIn":
        if self.tools is not None and len(self.tools) > 16:
            raise ValueError("tools names too many slots (maximum 16).")
        return self
    glue_batch_id: int | None = Field(default=None, gt=0)


class AssemblyIssueOut(BaseModel):
    code: str
    message: str


class AssemblyComponentOut(BaseModel):
    sn: str
    local_name: str | None
    component_type: str
    type_code: str
    stage: str
    location: str
    institute_code: str
    parent_sn: str | None
    is_dummy: bool
    stale: bool
    trashed: bool


class AssemblyToolOut(BaseModel):
    id: int
    kind: str
    code: str
    label: str | None
    rfid: str | None
    compatible_types: list[str]
    status: str


class AssemblyGlueBatchOut(BaseModel):
    id: int
    glue_type: str
    batch_no: str
    pdb_sn: str | None
    status: str
    mixed_at: datetime | None
    pot_life_minutes: int | None
    pot_life_remaining_seconds: int | None
    pot_life_expired: bool


class AssemblyPreviewOut(BaseModel):
    valid: bool
    submittable: bool
    submittable_reason: str | None
    summary: str
    slot: str
    parent: AssemblyComponentOut | None
    child: AssemblyComponentOut | None
    tool: AssemblyToolOut | None
    # Combined tool slots (institute profile `assembly_tool_slots`): slot key
    # → resolved tools, in selection order. Empty when only the legacy single
    # default tool is in play.
    tools: dict[str, list[AssemblyToolOut]] = {}
    glue_batch: AssemblyGlueBatchOut | None
    pdb_properties: dict[str, str]
    issues: list[AssemblyIssueOut]
    warnings: list[AssemblyIssueOut]


class AssemblyStageOut(BaseModel):
    preview: AssemblyPreviewOut
    action: OutboxOut


# --- Production statistics (reconstructed from the stage-event history) ------


class ThroughputPoint(BaseModel):
    period: str
    count: int


class LeadTimeOut(BaseModel):
    count: int
    median_days: float | None
    p25_days: float | None
    p75_days: float | None


class StageDwellOut(BaseModel):
    stage: str
    median_days: float
    count: int


class ReworkStageOut(BaseModel):
    stage: str
    count: int


class ReworkOut(BaseModel):
    rate: float
    reworked_components: int
    total_components: int
    by_stage: list[ReworkStageOut]


class YieldOut(BaseModel):
    good: int
    failed: int
    concluded: int
    in_progress: int
    rate: float | None


class ProductionStatsOut(BaseModel):
    component_type: str | None
    type_code: str | None
    institute: str | None
    target_stage: str
    bucket: str
    components_tracked: int
    stage_order: list[str]
    throughput: list[ThroughputPoint]
    lead_time: LeadTimeOut
    stage_dwell: list[StageDwellOut]
    rework: ReworkOut
    yield_: YieldOut


class RequiredTestStageRowOut(BaseModel):
    stage: str
    test_type: str
    component_total: int
    passed: int
    failed: int
    missing: int


class RequiredTestStatsOut(BaseModel):
    institute: str
    denominator: Literal["at_or_beyond_stage"]
    stage_order: list[str]
    rows: list[RequiredTestStageRowOut]


class StatsDimensionsOut(BaseModel):
    component_types: list[str]
    type_codes: list[str]
    institutes: list[str]


# --- Component image attachments (metrology / VI, read-only) ----------------


class ComponentImageOut(BaseModel):
    id: str
    title: str
    test_type: str | None
    # The download route needs the owning run, so it has to survive the listing.
    test_run_ref: str | None = None
    filename: str | None
    content_type: str | None


class EvidenceSyncOut(BaseModel):
    component_sn: str
    created: int
    updated: int
    unchanged: int
    total: int
    attachments_downloaded: int = 0
    attachments_reused: int = 0
    attachments_failed: int = 0
    attachments_skipped: int = 0
    attachments_authentication_required: int = 0
    attachments_total: int = 0


class InstituteEvidenceSyncOut(EvidenceSyncJobResultOut):
    pass


class TestRunDetailOut(BaseModel):
    """A mirrored test run with its measured values.

    `results` and `properties` are keyed by PDB code; `result_meta` carries the
    human name, which is where the unit lives ("Weight of glue ... [g]").

    `run_state` is the PDB's own state for the run. Withdrawn runs
    (`state='deleted'`) are still listed here — the PDB still holds them and
    hiding them would be its own kind of lie — but they no longer count as
    evidence anywhere a requirement or a statistic is decided, so a reader of
    this list must consult `run_state` before treating a run as valid.
    """

    test_type: str
    passed: bool
    external_ref: str | None
    measured_at: datetime | None
    run_number: str | None
    run_state: str | None = None
    results: dict[str, Any]
    result_meta: dict[str, Any]
    properties: dict[str, Any]
    attachments: list[TestRunAttachmentOut]


class AttachmentSyncOut(BaseModel):
    component_sn: str
    downloaded: int
    reused: int
    failed: int
    skipped: int = 0
    authentication_required: int = 0
    total: int


# --- Glue batches (Phase 4, docs/11) -----------------------------------------

GlueBatchStatus = Literal["new", "in_use", "expired", "empty"]


class GlueBatchCreate(BaseModel):
    glue_type: str = Field(min_length=1, max_length=48)
    batch_no: str = Field(min_length=1, max_length=64)
    pdb_sn: str | None = Field(default=None, max_length=20)
    status: GlueBatchStatus = "new"
    manufacturing_date: datetime | None = None
    expiry_date: datetime | None = None
    opening_date: datetime | None = None
    bipack_count: int | None = Field(default=None, ge=0)
    note: str | None = Field(default=None, max_length=2000)


class GlueBatchUpdate(BaseModel):
    batch_no: str | None = Field(default=None, min_length=1, max_length=64)
    pdb_sn: str | None = Field(default=None, max_length=20)
    status: GlueBatchStatus | None = None
    manufacturing_date: datetime | None = None
    expiry_date: datetime | None = None
    opening_date: datetime | None = None
    bipack_count: int | None = Field(default=None, ge=0)
    note: str | None = Field(default=None, max_length=2000)


class GlueBatchMixIn(BaseModel):
    # Explicit pot life wins; otherwise the institute profile's
    # `glue_pot_life_minutes[glue_type]` default applies.
    pot_life_minutes: int | None = Field(default=None, gt=0, le=24 * 60)


class GlueUsageCreate(BaseModel):
    component_sn: str = Field(min_length=1, max_length=64)
    amount_mg: float | None = Field(default=None, ge=0)
    note: str | None = Field(default=None, max_length=240)


class GlueUsageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    glue_batch_id: int
    component_sn: str
    amount_mg: float | None
    note: str | None
    used_by: str
    used_at: datetime


class GlueBatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    glue_type: str
    batch_no: str
    pdb_sn: str | None
    status: str
    manufacturing_date: datetime | None
    expiry_date: datetime | None
    opening_date: datetime | None
    bipack_count: int | None
    note: str | None
    mixed_at: datetime | None
    pot_life_minutes: int | None
    institute_id: int | None
    created_at: datetime
    # Computed server-side from mixed_at/pot_life_minutes (domain/glue.py).
    pot_life_remaining_seconds: int | None = None
    pot_life_expired: bool = False
    usage_count: int = 0


# --- Shipments (Phase 4, docs/11) --------------------------------------------

ReceptionStatus = Literal["pending", "in_progress", "done"]
ReceptionTestStatus = Literal["missing", "pending", "passed", "failed"]


class ShipmentChecklistItem(BaseModel):
    label: str = Field(min_length=1, max_length=200)
    done: bool = False


class ShipmentReceptionItem(BaseModel):
    sn: str = Field(min_length=1, max_length=64)
    received: bool = False
    note: str | None = Field(default=None, max_length=240)


class ShipmentReceptionUpdate(BaseModel):
    """Partial update of the local receiving check; omitted fields are kept."""

    status: ReceptionStatus | None = None
    checklist: list[ShipmentChecklistItem] | None = None
    items: list[ShipmentReceptionItem] | None = None
    note: str | None = Field(default=None, max_length=2000)
    # Only an admin may use this explicit escape hatch, and only while moving
    # the reception to done. The API additionally requires a non-blank reason
    # and emits a dedicated audit event.
    test_override: bool = False
    test_override_reason: str | None = Field(default=None, max_length=500)


class ShipmentReceptionTestOut(BaseModel):
    test_type: str
    status: ReceptionTestStatus


class ShipmentItemOut(BaseModel):
    sn: str
    component_type: str | None = None
    component_mirrored: bool = False
    is_dummy: bool = False
    submittable: bool = False
    submittable_reason: str | None = None
    reception_tests_configured: bool = False
    reception_test_status: ReceptionTestStatus = "passed"
    reception_tests: list[ShipmentReceptionTestOut] = Field(default_factory=list)


class ShipmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    pdb_id: str
    name: str | None
    sender_code: str
    recipient_code: str
    status: str
    # Relative to the owning institute: incoming | outgoing | internal | unknown.
    direction: str = "unknown"
    sent_at: datetime | None
    items: list[ShipmentItemOut]
    institute_id: int | None
    synced_at: datetime
    reception_status: str
    reception_checklist: list[dict]
    reception_items: list[dict]
    reception_note: str | None
    reception_by: str | None
    reception_updated_at: datetime | None
    reception_tests_configured: bool = False
    reception_test_status: ReceptionTestStatus = "passed"


class ShipmentSyncOut(BaseModel):
    institute_code: str
    created: int
    updated: int
    unchanged: int
    total: int


# --- Reminders / notifications (Phase 4, docs/11) ----------------------------

ReminderScheduleKind = Literal["once", "daily", "weekly", "monthly"]


class ReminderCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    note: str | None = Field(default=None, max_length=2000)
    channel: str | None = Field(default=None, max_length=64)
    schedule_kind: ReminderScheduleKind = "once"
    next_due_at: datetime


class ReminderUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    note: str | None = Field(default=None, max_length=2000)
    channel: str | None = Field(default=None, max_length=64)
    schedule_kind: ReminderScheduleKind | None = None
    next_due_at: datetime | None = None
    active: bool | None = None


class ReminderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    note: str | None
    channel: str | None
    schedule_kind: str
    next_due_at: datetime
    active: bool
    last_fired_at: datetime | None
    last_error: str | None
    created_by: str
    institute_id: int | None
    created_at: datetime
    updated_at: datetime


class ReminderOccurrenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    reminder_id: int
    institute_id: int | None
    due_at: datetime
    fired_at: datetime
    delivery_status: Literal["sent", "audit_only", "failed"]
    delivery_error: str | None
    escalation_due_at: datetime | None
    escalation_channel: str | None
    escalated_at: datetime | None
    escalation_error: str | None
    acknowledged_at: datetime | None
    acknowledged_by: str | None


class NotificationChannelOut(BaseModel):
    """Channel name and kind only — webhook URLs never leave the server."""

    name: str
    kind: str


class NotificationTestIn(BaseModel):
    channel: str = Field(min_length=1, max_length=64)
    # Institute-bound admins may omit this (their own institute is implied).
    # Global admins must select a target explicitly.
    institute_code: str | None = Field(
        default=None,
        min_length=2,
        max_length=16,
        pattern=r"^[A-Z0-9_]+$",
    )


class NotificationTestOut(BaseModel):
    channel: str
    sent: bool
