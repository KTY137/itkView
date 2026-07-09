from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.ingestion import ResultSummary
from app.outbox import OutboxStatus


class InstituteCreate(BaseModel):
    code: str = Field(min_length=2, max_length=16, pattern=r"^[A-Z0-9_]+$")
    name: str = Field(min_length=1, max_length=120)
    local_name_prefix: str = Field(default="", max_length=32)
    settings: dict = Field(default_factory=dict)


class InstituteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    local_name_prefix: str
    settings: dict
    created_at: datetime


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
    institute_code: str
    kind: str = Field(min_length=1, max_length=48)
    payload: dict = Field(default_factory=dict)
    created_by: str = Field(min_length=1, max_length=120)


class OutboxTransition(BaseModel):
    to: OutboxStatus
    actor: str = Field(min_length=1, max_length=120)
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
    created_at: datetime
    updated_at: datetime


class OutboxContractOut(BaseModel):
    statuses: list[str]
    transitions: dict[str, list[str]]
    terminal: list[str]


class IngestFileCreate(BaseModel):
    filename: str = Field(min_length=1, max_length=240)
    payload: dict = Field(default_factory=dict)
    uploaded_by: str = Field(min_length=1, max_length=120)


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
    created_by: str = Field(min_length=1, max_length=120)
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


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ts: datetime
    actor: str
    action: str
    subject: str
    detail: dict
    outbox_action_id: int | None


class HealthOut(BaseModel):
    status: str
    app: str
    version: str
    pdb_instance: str
    pdb_write_scope: str


# --- Auth / users (docs/06) ------------------------------------------------

Role = Literal["viewer", "operator", "admin"]


class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=1, max_length=200)


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


# --- Tools / jigs (docs/07) ------------------------------------------------

ToolStatus = Literal["active", "flagged", "blacklisted"]


class ToolCreate(BaseModel):
    kind: str = Field(min_length=1, max_length=24)
    code: str = Field(min_length=1, max_length=64)
    label: str | None = Field(default=None, max_length=120)
    rfid: str | None = Field(default=None, max_length=64)
    compatible_types: list[str] = Field(default_factory=list)
    status: ToolStatus = "active"


class ToolUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=64)
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


class StatsDimensionsOut(BaseModel):
    component_types: list[str]
    type_codes: list[str]
    institutes: list[str]
