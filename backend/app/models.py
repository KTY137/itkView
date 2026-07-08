from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
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
    location: Mapped[str] = mapped_column(String(16))  # institute code of the current location
    institute_code: Mapped[str] = mapped_column(String(16), index=True)  # owning institute
    local_name: Mapped[str | None] = mapped_column(String(64), default=None, index=True)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("component.id"), default=None, index=True
    )
    is_dummy: Mapped[bool] = mapped_column(Boolean, default=False)
    trashed: Mapped[bool] = mapped_column(Boolean, default=False)
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
    code: Mapped[str] = mapped_column(String(16), unique=True, index=True)  # PDB code, e.g. TUDO
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
    created_by: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    institute: Mapped[InstituteProfile] = relationship(back_populates="outbox_actions")
    audit_events: Mapped[list["AuditEvent"]] = relationship(back_populates="outbox_action")


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


class AuditEvent(Base):
    """Append-only trail: who did what, when, to which subject."""

    __tablename__ = "audit_event"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    actor: Mapped[str] = mapped_column(String(120))
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


class Tool(Base):
    """A jig/tool/panel in the local registry, tagged with the module types it
    fits — so the assembly wizard can offer a type-filtered quick-select instead
    of free text (docs/07). Institute-scoped; no type mapping hardcoded in code.
    """

    __tablename__ = "tool"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(24), index=True)  # jig | pickup_tool | panel | …
    code: Mapped[str] = mapped_column(String(64))  # local/institute identifier
    rfid: Mapped[str | None] = mapped_column(String(64), default=None, index=True)
    # Module types / R-types this tool fits, e.g. ["R5M0", "R5M1"].
    compatible_types: Mapped[list] = mapped_column(JSON, default=list)
    institute_id: Mapped[int | None] = mapped_column(
        ForeignKey("institute_profile.id"), default=None, index=True
    )
    status: Mapped[str] = mapped_column(String(16), default="active")  # active|flagged|blacklisted
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    institute: Mapped[InstituteProfile | None] = relationship()


class UserSession(Base):
    """Server-side session: an opaque cookie token bound to a user."""

    __tablename__ = "user_session"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship()
