from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Component(Base):
    """Mirror of a PDB component — read-mostly, maintained by the sync layer.

    The PDB stays the source of truth (revamp plan §2); this table only makes
    it browsable offline and joinable with local entities. Never written by
    request handlers — only by `app.sync.sync_components`.
    """

    __tablename__ = "component"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sn: Mapped[str] = mapped_column(String(20), unique=True, index=True)  # PDB serial number
    component_type: Mapped[str] = mapped_column(String(32))  # e.g. MODULE, SENSOR, HYBRID, PWB
    type_code: Mapped[str] = mapped_column(String(32))  # PDB type code, e.g. R5M0, R5H1
    stage: Mapped[str] = mapped_column(String(48))  # current PDB stage, e.g. GLUED
    # PDB institute codes run longer than a short abbreviation (e.g.
    # UCSC_STRIP_SENSORS, 18 chars), so these hold 32 rather than 16.
    location: Mapped[str] = mapped_column(String(32))  # institute code of the current location
    institute_code: Mapped[str] = mapped_column(String(32), index=True)  # owning institute
    local_name: Mapped[str | None] = mapped_column(String(64), default=None, index=True)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("component.id"), default=None, index=True
    )
    is_dummy: Mapped[bool] = mapped_column(Boolean, default=False)
    trashed: Mapped[bool] = mapped_column(Boolean, default=False)
    # Set by a full institute sync when the PDB stops returning a component we
    # still hold (moved away, deleted). The row is kept for its local links but
    # flagged as no longer live; a later sync that sees it again clears this.
    stale: Mapped[bool] = mapped_column(Boolean, default=False)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    parent: Mapped["Component | None"] = relationship(
        back_populates="children", remote_side="Component.id"
    )
    children: Mapped[list["Component"]] = relationship(
        back_populates="parent", order_by="Component.sn"
    )

    @property
    def parent_sn(self) -> str | None:
        """Serial number of the assembly parent (for API schemas)."""
        return self.parent.sn if self.parent is not None else None


class InstituteProfile(Base):
    """Everything institute-specific lives here — never in code (hard rule #4)."""

    __tablename__ = "institute_profile"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # PDB code (e.g. TUDO); 32 to fit longer codes like UCSC_STRIP_SENSORS.
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    local_name_prefix: Mapped[str] = mapped_column(String(32), default="")
    # Free-form profile: glue targets, stage automation flags, notification channels, …
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    outbox_actions: Mapped[list["OutboxAction"]] = relationship(back_populates="institute")


class OutboxAction(Base):
    """A reviewed, auditable intent to write to the PDB.

    Nothing writes to the PDB except by confirming one of these.
    Status machine: see app/outbox.py.
    """

    __tablename__ = "outbox_action"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    institute_id: Mapped[int] = mapped_column(ForeignKey("institute_profile.id"), index=True)
    kind: Mapped[str] = mapped_column(String(48))  # e.g. register_component, stage_move
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    # PDB-side identifier returned once the write is confirmed (e.g. the test
    # run id). Its presence means "already written" — the worker never
    # re-submits an action that has one (idempotency guard).
    external_ref: Mapped[str | None] = mapped_column(String(64), default=None)
    # Denormalised, human-readable author kept for history/display. New writes
    # set it server-side from the signed-in user; `user_id` is the fraud-proof
    # link (docs/06). Nullable FK so old rows and system/worker writes stay valid.
    created_by: Mapped[str] = mapped_column(String(120))
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("app_user.id"), default=None, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    institute: Mapped[InstituteProfile] = relationship(back_populates="outbox_actions")
    audit_events: Mapped[list["AuditEvent"]] = relationship(back_populates="outbox_action")
    pdb_principal: Mapped["OutboxPdbPrincipal | None"] = relationship(
        back_populates="outbox_action",
        cascade="all, delete-orphan",
        uselist=False,
    )


class IngestFile(Base):
    """Server-side inbox item for an uploaded instrument JSON file.

    Phase 2 parser plugins will turn these into reviewed outbox proposals.
    For now this table only records receipt, raw JSON, lightweight inferred
    metadata and triage status. It never writes to the PDB.
    """

    __tablename__ = "ingest_file"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filename: Mapped[str] = mapped_column(String(240))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    size_bytes: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default="received", index=True)
    component_sn: Mapped[str | None] = mapped_column(String(20), default=None, index=True)
    test_type: Mapped[str | None] = mapped_column(String(64), default=None, index=True)
    parser: Mapped[str | None] = mapped_column(String(64), default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    outbox_action_id: Mapped[int | None] = mapped_column(
        ForeignKey("outbox_action.id"), default=None, index=True
    )
    uploaded_by: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    outbox_action: Mapped[OutboxAction | None] = relationship()


class TestRunEvidence(Base):
    """Mirrored evidence that a component has a test run result.

    This is read-side evidence, not a write intent. It is fed by the PDB
    test-run mirror (`app.pdb_test_evidence.fetch_test_run_evidence`, exposed via
    `/api/components/{sn}/sync-evidence` and `/api/sync/evidence/{institute_code}`),
    and can also come from zFlow reconciliation or a local sync job; it is merged
    with confirmed itkFlow uploads by `app.stage_service`.
    """

    __tablename__ = "test_run_evidence"
    __test__ = False
    __table_args__ = (
        UniqueConstraint("source", "external_ref", name="uq_test_run_evidence_source_ref"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    component_sn: Mapped[str] = mapped_column(String(20), index=True)
    test_type: Mapped[str] = mapped_column(String(64), index=True)
    passed: Mapped[bool] = mapped_column(Boolean)
    source: Mapped[str] = mapped_column(String(24), default="pdb", index=True)
    external_ref: Mapped[str | None] = mapped_column(String(64), default=None)
    # The run's own lifecycle state as the PDB reports it ("ready", "deleted",
    # "requestedToDelete", ...). The PDB keeps serving a withdrawn run, so
    # without this column a retracted measurement is indistinguishable from a
    # valid one and counts as evidence: on the real TUDO mirror that is 102 of
    # 14 759 runs, 13% of all GLUE_WEIGHT and 25% of all MODULE_BOW.
    # `app.test_run_evidence.WITHDRAWN_RUN_STATE` owns the interpretation;
    # NULL means "unknown", which is deliberately treated as still valid so a
    # non-PDB or not-yet-backfilled source never silently loses its evidence.
    run_state: Mapped[str | None] = mapped_column(String(32), default=None)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    measured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TestRunAttachment(Base):
    """A PDB test-run attachment mirrored to a local file.

    The row is the index; the bytes live on disk under the configured
    attachment directory (`app.attachment_store`). Keeping them out of the
    database keeps the mirror small and lets a person open the folder and look
    at the images with any ordinary viewer.

    `pdb_code` is the PDB's own attachment handle and is unique per source, so
    re-running a sync re-uses the file instead of downloading it again.
    """

    __tablename__ = "test_run_attachment"
    __test__ = False
    __table_args__ = (
        UniqueConstraint("source", "pdb_code", name="uq_test_run_attachment_source_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    component_sn: Mapped[str] = mapped_column(String(20), index=True)
    test_type: Mapped[str] = mapped_column(String(64), index=True)
    # The run this belongs to; matches `TestRunEvidence.external_ref`.
    test_run_ref: Mapped[str | None] = mapped_column(String(64), default=None, index=True)
    source: Mapped[str] = mapped_column(String(24), default="pdb", index=True)
    pdb_code: Mapped[str] = mapped_column(String(128))
    filename: Mapped[str | None] = mapped_column(String(255), default=None)
    content_type: Mapped[str | None] = mapped_column(String(128), default=None)
    title: Mapped[str | None] = mapped_column(String(255), default=None)
    size_bytes: Mapped[int | None] = mapped_column(Integer, default=None)
    # Relative to the configured attachment directory, so moving or backing up
    # that directory does not invalidate every row.
    relative_path: Mapped[str | None] = mapped_column(String(400), default=None)
    downloaded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    @property
    def is_image(self) -> bool:
        return bool(self.content_type and self.content_type.startswith("image/"))


class TestTypeSchema(Base):
    """Read-only local mirror of one PDB test-type definition.

    The database column is named ``schema`` to match the public contract;
    ``schema_data`` avoids colliding with framework helpers in Python code.
    """

    __tablename__ = "test_type_schema"
    __test__ = False
    __table_args__ = (
        UniqueConstraint(
            "component_type",
            "test_code",
            name="uq_test_type_schema_component_code",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    component_type: Mapped[str] = mapped_column(String(32), index=True)
    test_code: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(160))
    schema_data: Mapped[dict] = mapped_column("schema", JSON, default=dict)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditEvent(Base):
    """Append-only trail: who did what, when, to which subject."""

    __tablename__ = "audit_event"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    # `actor` is the denormalised author string (kept for history/display);
    # `user_id` is the server-set link to the real account. Nullable so old rows
    # and system/worker events (no signed-in user) remain valid (docs/06).
    actor: Mapped[str] = mapped_column(String(120))
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("app_user.id"), default=None, index=True
    )
    action: Mapped[str] = mapped_column(String(64))
    subject: Mapped[str] = mapped_column(String(200))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    outbox_action_id: Mapped[int | None] = mapped_column(
        ForeignKey("outbox_action.id"), default=None, index=True
    )

    outbox_action: Mapped[OutboxAction | None] = relationship(back_populates="audit_events")


class User(Base):
    """A person who uses the app. Every action is attributed to one (docs/06).

    Local accounts for v1: `password_hash` is set for password login;
    `external_subject` is reserved for a later OIDC/SSO adapter.
    """

    __tablename__ = "app_user"  # "user" is reserved in some databases

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    institute_id: Mapped[int | None] = mapped_column(
        ForeignKey("institute_profile.id"), default=None, index=True
    )
    role: Mapped[str] = mapped_column(String(16), default="viewer")  # viewer|operator|admin
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    password_hash: Mapped[str | None] = mapped_column(String(200), default=None)
    external_subject: Mapped[str | None] = mapped_column(String(200), default=None, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    institute: Mapped[InstituteProfile | None] = relationship()
    pdb_credential: Mapped["PdbCredential | None"] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        uselist=False,
    )


class PdbCredential(Base):
    """Encrypted, account-owned credentials for the external production DB.

    The local user id is both primary key and foreign key, which makes the
    relationship structurally one-to-one. Access codes only ever appear inside
    ``encrypted_payload``; identity and verification metadata are non-secret
    operational state used by the account UI.
    """

    __tablename__ = "pdb_credential"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True
    )
    encrypted_payload: Mapped[str] = mapped_column(Text)
    pdb_identity: Mapped[str] = mapped_column(String(200), unique=True)
    pdb_display_name: Mapped[str | None] = mapped_column(String(200), default=None)
    institutions: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="verified")
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    user: Mapped[User] = relationship(back_populates="pdb_credential")


class OutboxPdbPrincipal(Base):
    """Immutable account identity selected when an outbox write is approved.

    The creator remains recorded on ``OutboxAction.user_id``. This separate
    one-to-one row binds submission and every retry to the approving account's
    personal PDB identity, without copying either access code into the queue.
    """

    __tablename__ = "outbox_pdb_principal"

    outbox_action_id: Mapped[int] = mapped_column(
        ForeignKey("outbox_action.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"), index=True)
    pdb_identity: Mapped[str] = mapped_column(String(200))
    bound_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    outbox_action: Mapped[OutboxAction] = relationship(back_populates="pdb_principal")
    user: Mapped[User] = relationship()


class Tool(Base):
    """A jig/tool/panel in the local registry, tagged with the module types it
    fits — so the assembly wizard can offer a type-filtered quick-select instead
    of free text (docs/07). Institute-scoped; no type mapping hardcoded in code.
    """

    __tablename__ = "tool"
    __table_args__ = (
        UniqueConstraint("institute_id", "code", name="uq_tool_institute_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(24), index=True)  # jig | pickup_tool | panel | …
    code: Mapped[str] = mapped_column(String(64))  # local/institute identifier (scannable)
    # Human-friendly name operators use ("R5M0 Module jig #3 (orange)"); the code
    # stays the scannable serial. Optional.
    label: Mapped[str | None] = mapped_column(String(120), default=None)
    rfid: Mapped[str | None] = mapped_column(String(64), default=None, index=True)
    # Module types / R-types this tool fits, e.g. ["R5M0", "R5M1"].
    compatible_types: Mapped[list] = mapped_column(JSON, default=list)
    institute_id: Mapped[int | None] = mapped_column(
        ForeignKey("institute_profile.id"), default=None, index=True
    )
    status: Mapped[str] = mapped_column(String(16), default="active")  # active|flagged|blacklisted
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    institute: Mapped[InstituteProfile | None] = relationship()


class GlueBatch(Base):
    """A glue/adhesive batch in the local registry (Phase 4, replaces the glue
    sheet). Lifecycle: new → in_use → expired/empty. `pdb_sn` is an optional,
    scannable reference to the GLUE component in the PDB — itkFlow never
    registers GLUE components itself (write scope is dummy modules/hybrids
    only), it only links to them. Pot life starts ticking at `mixed_at`; the
    per-type default minutes come from the institute profile
    (`settings['glue_pot_life_minutes']`), never from code.
    """

    __tablename__ = "glue_batch"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    glue_type: Mapped[str] = mapped_column(String(48), index=True)  # e.g. POLARIS_EPOXY
    batch_no: Mapped[str] = mapped_column(String(64), index=True)
    pdb_sn: Mapped[str | None] = mapped_column(String(20), default=None, index=True)
    status: Mapped[str] = mapped_column(
        String(16), default="new", index=True
    )  # new|in_use|expired|empty
    manufacturing_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    expiry_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    opening_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    bipack_count: Mapped[int | None] = mapped_column(Integer, default=None)
    note: Mapped[str | None] = mapped_column(Text, default=None)
    mixed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    pot_life_minutes: Mapped[int | None] = mapped_column(Integer, default=None)
    institute_id: Mapped[int | None] = mapped_column(
        ForeignKey("institute_profile.id"), default=None, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    institute: Mapped[InstituteProfile | None] = relationship()
    usages: Mapped[list["GlueUsage"]] = relationship(
        back_populates="glue_batch", cascade="all, delete-orphan"
    )


class GlueUsage(Base):
    """One recorded consumption of a glue batch for a component.

    Links consumables to production (roadmap Phase 4 done criterion: glue data
    joinable with components). `component_sn` is a plain string, not an FK —
    the component may not be mirrored yet when glue is logged at the bench.
    """

    __tablename__ = "glue_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    glue_batch_id: Mapped[int] = mapped_column(ForeignKey("glue_batch.id"), index=True)
    component_sn: Mapped[str] = mapped_column(String(64), index=True)
    amount_mg: Mapped[float | None] = mapped_column(Float, default=None)
    note: Mapped[str | None] = mapped_column(String(240), default=None)
    used_by: Mapped[str] = mapped_column(String(120))
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("app_user.id"), default=None, index=True
    )
    used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    glue_batch: Mapped[GlueBatch] = relationship(back_populates="usages")


class Shipment(Base):
    """Mirror of a PDB shipment plus the local receiving check.

    The PDB fields (`pdb_id` … `items`) are read-mostly and owned by
    `app.shipment_sync`; the `reception_*` fields are locally leading and never
    overwritten by a sync (same contract as Tool RFID/blacklist data). The
    receiving checklist template comes from the institute profile
    (`settings['shipment_reception_checklist']`).
    """

    __tablename__ = "shipment"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pdb_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(120), default=None)
    sender_code: Mapped[str] = mapped_column(String(32), index=True)
    recipient_code: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(24), index=True)  # PDB status verbatim
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    # [{"sn": …, "component_type": …}] — small lists; a join table would buy
    # nothing while the PDB owns the truth.
    items: Mapped[list] = mapped_column(JSON, default=list)
    institute_id: Mapped[int | None] = mapped_column(
        ForeignKey("institute_profile.id"), default=None, index=True
    )
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    # Local receiving check (pending|in_progress|done).
    reception_status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    reception_checklist: Mapped[list] = mapped_column(JSON, default=list)  # [{label, done}]
    reception_items: Mapped[list] = mapped_column(JSON, default=list)  # [{sn, received, note?}]
    reception_note: Mapped[str | None] = mapped_column(Text, default=None)
    reception_by: Mapped[str | None] = mapped_column(String(120), default=None)
    reception_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("app_user.id"), default=None
    )
    reception_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    institute: Mapped[InstituteProfile | None] = relationship()


class Reminder(Base):
    """A recurring or one-off operational task that fires a notification.

    The worker process (`run_worker`) polls `next_due_at` and sends the message
    through the notification channel named here — channel definitions live in
    the institute profile (`settings['notification_channels']`), never in code
    (hard rule #4). A reminder without a channel still fires into the audit
    trail, so the module is useful before any webhook is configured.
    """

    __tablename__ = "reminder"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(160))
    note: Mapped[str | None] = mapped_column(Text, default=None)
    channel: Mapped[str | None] = mapped_column(String(64), default=None)
    schedule_kind: Mapped[str] = mapped_column(
        String(16), default="once"
    )  # once|daily|weekly|monthly
    next_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    last_fired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    last_error: Mapped[str | None] = mapped_column(Text, default=None)
    created_by: Mapped[str] = mapped_column(String(120))
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("app_user.id"), default=None, index=True
    )
    institute_id: Mapped[int | None] = mapped_column(
        ForeignKey("institute_profile.id"), default=None, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, index=True
    )

    institute: Mapped[InstituteProfile | None] = relationship()
    occurrences: Mapped[list["ReminderOccurrence"]] = relationship(
        back_populates="reminder",
    )


class ReminderOccurrence(Base):
    """One durable reminder task, optionally acknowledged and escalated."""

    __tablename__ = "reminder_occurrence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reminder_id: Mapped[int] = mapped_column(ForeignKey("reminder.id"), index=True)
    institute_id: Mapped[int | None] = mapped_column(
        ForeignKey("institute_profile.id"), default=None, index=True
    )
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    fired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    delivery_status: Mapped[str] = mapped_column(String(16), default="audit_only")
    delivery_error: Mapped[str | None] = mapped_column(Text, default=None)
    escalation_due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, index=True
    )
    escalation_channel: Mapped[str | None] = mapped_column(String(64), default=None)
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    escalation_error: Mapped[str | None] = mapped_column(Text, default=None)
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, index=True
    )
    acknowledged_by: Mapped[str | None] = mapped_column(String(120), default=None)
    acknowledged_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("app_user.id"), default=None, index=True
    )

    reminder: Mapped[Reminder] = relationship(back_populates="occurrences")


class UserSession(Base):
    """Server-side session: an opaque cookie token bound to a user."""

    __tablename__ = "user_session"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"), index=True)
    # Per-session CSRF token for the double-submit guard; compared against the
    # X-CSRF-Token header on every state-changing request (docs/06).
    csrf_token: Mapped[str] = mapped_column(String(64), default="")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship()


class StageEvent(Base):
    """One timestamped stage transition, reconstructed from the PDB `stages[]`.

    The PDB records the full dated stage log of every component; the sync mirrors
    it here so we can compute throughput, cycle time, rework and WIP over time
    without a separate time-series store. Denormalised component facts
    (type/institute) let the stats queries filter without a join. Rows are owned
    by the sync layer and rebuilt per component on each full sync.
    """

    __tablename__ = "stage_event"
    __table_args__ = (
        # A component enters a given stage at a given instant exactly once;
        # this makes re-sync idempotent.
        UniqueConstraint("component_sn", "stage", "entered_at", name="uq_stage_event"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    component_sn: Mapped[str] = mapped_column(String(20), index=True)
    component_type: Mapped[str] = mapped_column(String(32), index=True)
    type_code: Mapped[str] = mapped_column(String(32))
    institute_code: Mapped[str] = mapped_column(String(32), index=True)
    stage: Mapped[str] = mapped_column(String(48), index=True)
    entered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    rework: Mapped[bool] = mapped_column(Boolean, default=False)


class SyncJob(Base):
    """Persistent status for a long-running read-only mirror sync.

    ``active_key`` is populated only while a job is queued/running. Its unique
    constraint is the cross-request, cross-thread single-flight guard: component
    sync scopes can overlap, so only one component sync may mutate the mirror at
    a time; evidence syncs use one key per institute. Terminal jobs clear the
    key and remain available as history.
    """

    __tablename__ = "sync_job"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    institute_code: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(16), index=True)
    phase: Mapped[str] = mapped_column(String(24))
    current: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int | None] = mapped_column(Integer, default=None)
    percent: Mapped[float | None] = mapped_column(Float, default=None)
    message: Mapped[str] = mapped_column(String(240), default="")
    result: Mapped[dict | None] = mapped_column(JSON, default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    requested_by: Mapped[str] = mapped_column(String(120))
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("app_user.id"), default=None, index=True
    )
    # NULL for terminal rows. SQLite and PostgreSQL both allow multiple NULLs
    # in a UNIQUE column, while rejecting a second live lease for one scope.
    active_key: Mapped[str | None] = mapped_column(String(32), unique=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class ServiceHeartbeat(Base):
    """Latest durable heartbeat for one local background service.

    Heartbeats deliberately describe only itkFlow's own worker processes.  The
    operations view never probes the PDB (or any other remote dependency) as a
    side effect of being opened.
    """

    __tablename__ = "service_heartbeat"

    service: Mapped[str] = mapped_column(String(48), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), default="ok")
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, index=True
    )
