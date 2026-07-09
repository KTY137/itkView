import hashlib
import json
from collections.abc import Iterator
from datetime import timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app import __version__
from app.auth import (
    SESSION_COOKIE,
    SESSION_TTL,
    hash_password,
    new_session_token,
    session_expiry,
    verify_password,
)
from app.domain.stages import DEFAULT_STAGE_ORDER
from app.ingestion import ParsedTestRun, parse_payload
from app.models import (
    AuditEvent,
    Component,
    IngestFile,
    InstituteProfile,
    OutboxAction,
    StageEvent,
    Tool,
    User,
    UserSession,
    utcnow,
)
from app.outbox import (
    TERMINAL,
    InvalidTransition,
    OutboxStatus,
    assert_transition,
    transition_contract,
)
from app.pdb_sync import PdbSyncUnavailable
from app.schemas import (
    AuditOut,
    ComponentDetailOut,
    ComponentImageOut,
    ComponentOut,
    ComponentSyncOut,
    CountBucket,
    DashboardSummaryOut,
    EvidenceSyncOut,
    HealthOut,
    IngestFileCreate,
    IngestFileOut,
    IngestPreviewOut,
    IngestProposalCreate,
    InstituteCreate,
    InstituteEvidenceSyncOut,
    InstituteOut,
    LoginIn,
    MeOut,
    OutboxContractOut,
    OutboxCreate,
    OutboxOut,
    OutboxTransition,
    ProductionStatsOut,
    RequirementCheckOut,
    StageSuggestionOut,
    StatsDimensionsOut,
    ToolCreate,
    ToolOut,
    ToolSyncOut,
    ToolUpdate,
    UserCreate,
    UserOut,
    UserUpdate,
)
from app.stage_service import evaluate_for_component
from app.stats import production_stats
from app.sync import UnknownParentError, sync_components
from app.tool_sync import sync_tools_from_components


def get_db(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        yield session


def current_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    """Resolve the signed-in user from the session cookie, or None. Optional —
    endpoints stay usable while auth is being rolled out (docs/06)."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    session = db.scalar(select(UserSession).where(UserSession.token == token))
    if session is None:
        return None
    # SQLite returns naive datetimes; treat a stored expiry as UTC to compare.
    expires = session.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < utcnow():
        return None
    user = db.get(User, session.user_id)
    return user if (user is not None and user.is_active) else None


def require_user(user: User | None = Depends(current_user)) -> User:
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return user


def require_role(*roles: str):
    """Dependency factory: require an authenticated user with one of `roles`."""

    def dependency(user: User = Depends(require_user)) -> User:
        if user.role not in roles:
            raise HTTPException(
                status_code=403,
                detail=f"This action requires role: {', '.join(roles)}.",
            )
        return user

    return dependency


# Module-level singletons (FastAPI resolves these; avoids calls in arg defaults).
require_admin = require_role("admin")
require_operator = require_role("operator", "admin")


def _me(user: User) -> MeOut:
    code = user.institute.code if user.institute is not None else None
    return MeOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=user.role,
        institute_id=user.institute_id,
        institute_code=code,
    )


router = APIRouter()


# --------------------------------------------------------------------------
# Auth & users (docs/06). Additive: existing endpoints remain open for now.
# --------------------------------------------------------------------------


@router.post("/api/auth/login", response_model=MeOut, tags=["auth"])
def login(body: LoginIn, response: Response, db: Session = Depends(get_db)) -> MeOut:
    user = db.scalar(select(User).where(User.email == body.email.strip().lower()))
    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    token = new_session_token()
    db.add(UserSession(token=token, user_id=user.id, expires_at=session_expiry()))
    db.commit()
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        max_age=int(SESSION_TTL.total_seconds()),
    )
    return _me(user)


@router.post("/api/auth/logout", status_code=204, tags=["auth"])
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> None:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        session = db.scalar(select(UserSession).where(UserSession.token == token))
        if session is not None:
            db.delete(session)
            db.commit()
    response.delete_cookie(SESSION_COOKIE)


@router.get("/api/auth/me", response_model=MeOut, tags=["auth"])
def whoami(user: User = Depends(require_user)) -> MeOut:
    return _me(user)


@router.get("/api/users", response_model=list[UserOut], tags=["users"])
def list_users(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    stmt = select(User).order_by(User.email)
    if admin.institute_id is not None:  # per-institute admins see their own users
        stmt = stmt.where(User.institute_id == admin.institute_id)
    return list(db.scalars(stmt))


@router.post("/api/users", response_model=UserOut, status_code=201, tags=["users"])
def create_user(
    body: UserCreate, db: Session = Depends(get_db), admin: User = Depends(require_admin)
) -> User:
    email = body.email.strip().lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=409, detail=f"A user with email '{email}' already exists.")
    user = User(
        email=email,
        display_name=body.display_name,
        role=body.role,
        institute_id=admin.institute_id,  # new users join the admin's institute
        password_hash=hash_password(body.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.patch("/api/users/{user_id}", response_model=UserOut, tags=["users"])
def update_user(
    user_id: int,
    body: UserUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> User:
    user = db.get(User, user_id)
    if user is None or (
        admin.institute_id is not None and user.institute_id != admin.institute_id
    ):
        raise HTTPException(status_code=404, detail=f"User {user_id} not found.")
    if body.display_name is not None:
        user.display_name = body.display_name
    if body.role is not None:
        user.role = body.role
    if body.is_active is not None:
        user.is_active = body.is_active
    if body.password is not None:
        user.password_hash = hash_password(body.password)
    db.commit()
    db.refresh(user)
    return user


def count_buckets(db: Session, column) -> list[CountBucket]:
    rows = db.execute(
        select(column, func.count()).group_by(column).order_by(func.count().desc(), column)
    )
    return [CountBucket(label=str(label), count=count) for label, count in rows]


def order_buckets(
    buckets: list[CountBucket], order: tuple[str, ...] | list[str]
) -> list[CountBucket]:
    """Reorder buckets to follow a domain sequence (e.g. production stages left
    to right), with any label not in `order` appended alphabetically."""
    rank = {name: index for index, name in enumerate(order)}
    return sorted(buckets, key=lambda b: (rank.get(b.label, len(rank)), b.label))


def active_module_requirement_gaps(db: Session) -> tuple[int, int]:
    """Required-test gaps for active modules, using the same engine as detail.

    Until a PDB test-run mirror exists, this measures local evidence gaps:
    confirmed itkFlow uploads are counted as satisfied, everything else remains
    missing. Terminal/trashed/stale modules are excluded so old production
    history does not dominate the daily dashboard.
    """

    modules = db.scalars(
        select(Component)
        .where(Component.component_type == "MODULE")
        .where(Component.stale.is_(False))
        .where(Component.trashed.is_(False))
        .where(~Component.stage.in_(("FINISHED", "FAILED", "TRASHED", "ABANDONED")))
    )
    components_with_gaps = 0
    total_gaps = 0
    for component in modules:
        gaps = len(evaluate_for_component(db, component).blocking)
        if gaps:
            components_with_gaps += 1
            total_gaps += gaps
    return total_gaps, components_with_gaps


def canonical_json_bytes(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def resolve_component(db: Session, parsed: ParsedTestRun) -> Component | None:
    """Find the mirrored component for a parsed payload — by SN, else local name."""
    if parsed.component_sn is not None:
        return db.scalar(select(Component).where(Component.sn == parsed.component_sn))
    if parsed.local_name is not None:
        return db.scalar(select(Component).where(Component.local_name == parsed.local_name))
    return None


@router.get("/health", response_model=HealthOut, tags=["meta"])
def health(request: Request) -> HealthOut:
    settings = request.app.state.settings
    return HealthOut(
        status="ok",
        app=settings.app_name,
        version=__version__,
        pdb_instance=settings.pdb_instance,
        pdb_write_scope=settings.pdb_write_scope,
    )


# --------------------------------------------------------------------------
# Institutes
# --------------------------------------------------------------------------


@router.get("/api/institutes", response_model=list[InstituteOut], tags=["institutes"])
def list_institutes(db: Session = Depends(get_db)) -> list[InstituteProfile]:
    return list(db.scalars(select(InstituteProfile).order_by(InstituteProfile.code)))


@router.post("/api/institutes", response_model=InstituteOut, status_code=201, tags=["institutes"])
def create_institute(body: InstituteCreate, db: Session = Depends(get_db)) -> InstituteProfile:
    exists = db.scalar(select(InstituteProfile).where(InstituteProfile.code == body.code))
    if exists:
        raise HTTPException(status_code=409, detail=f"Institute '{body.code}' already exists.")
    institute = InstituteProfile(**body.model_dump())
    db.add(institute)
    db.commit()
    db.refresh(institute)
    return institute


# --------------------------------------------------------------------------
# Tools / jigs registry (docs/07). Reads open; writes require operator/admin.
# --------------------------------------------------------------------------


@router.get("/api/tools", response_model=list[ToolOut], tags=["tools"])
def list_tools(
    kind: str | None = None,
    fits: str | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
) -> list[Tool]:
    stmt = select(Tool).order_by(Tool.kind, Tool.code)
    if kind:
        stmt = stmt.where(Tool.kind == kind)
    if status:
        stmt = stmt.where(Tool.status == status)
    tools = list(db.scalars(stmt))
    if fits:  # keep only tools compatible with this component/module type
        tools = [tool for tool in tools if fits in (tool.compatible_types or [])]
    return tools


@router.get("/api/tools/by-rfid/{rfid}", response_model=ToolOut, tags=["tools"])
def get_tool_by_rfid(rfid: str, db: Session = Depends(get_db)) -> Tool:
    tool = db.scalar(select(Tool).where(Tool.rfid == rfid))
    if tool is None:
        raise HTTPException(status_code=404, detail=f"No tool with RFID '{rfid}'.")
    return tool


@router.get("/api/tools/scan", response_model=ToolOut, tags=["tools"])
def scan_tool(code: str, db: Session = Depends(get_db)) -> Tool:
    """Resolve a scanned value to a tool by RFID *or* printed code.

    Scanner-first: a wedge scanner emits either the RFID tag or the label code,
    so match both, case-insensitively. This is the auto-pull the Tools screen
    uses to surface a jig the moment it is scanned.
    """
    needle = code.strip()
    if needle == "":
        raise HTTPException(status_code=422, detail="Empty scan value.")
    tool = db.scalar(
        select(Tool).where(
            or_(
                func.lower(Tool.rfid) == needle.lower(),
                func.lower(Tool.code) == needle.lower(),
                func.lower(Tool.label) == needle.lower(),
            )
        )
    )
    if tool is None:
        raise HTTPException(status_code=404, detail=f"No tool matches scan '{code}'.")
    return tool


@router.post("/api/tools", response_model=ToolOut, status_code=201, tags=["tools"])
def create_tool(
    body: ToolCreate, db: Session = Depends(get_db), user: User = Depends(require_operator)
) -> Tool:
    tool = Tool(
        kind=body.kind,
        code=body.code,
        label=body.label,
        rfid=body.rfid,
        compatible_types=body.compatible_types,
        status=body.status,
        institute_id=user.institute_id,
    )
    db.add(tool)
    db.commit()
    db.refresh(tool)
    return tool


@router.patch("/api/tools/{tool_id}", response_model=ToolOut, tags=["tools"])
def update_tool(
    tool_id: int,
    body: ToolUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_operator),
) -> Tool:
    tool = db.get(Tool, tool_id)
    if tool is None:
        raise HTTPException(status_code=404, detail=f"Tool {tool_id} not found.")
    if body.code is not None:
        tool.code = body.code
    if body.rfid is not None:
        tool.rfid = body.rfid
    if body.compatible_types is not None:
        tool.compatible_types = body.compatible_types
    if body.status is not None:
        tool.status = body.status
    db.commit()
    db.refresh(tool)
    return tool


# --------------------------------------------------------------------------
# Components (PDB mirror, read-only — writes go through sync/outbox)
# --------------------------------------------------------------------------


@router.get("/api/components", response_model=list[ComponentOut], tags=["components"])
def list_components(
    q: str | None = None,
    stage: str | None = None,
    component_type: str | None = None,
    institute: str | None = None,
    stale: bool | None = None,
    db: Session = Depends(get_db),
) -> list[Component]:
    stmt = (
        select(Component)
        .options(selectinload(Component.parent))
        .order_by(Component.local_name.nulls_last(), Component.sn)
    )
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(or_(Component.sn.ilike(pattern), Component.local_name.ilike(pattern)))
    if stage:
        stmt = stmt.where(Component.stage == stage)
    if component_type:
        stmt = stmt.where(Component.component_type == component_type)
    if institute:
        stmt = stmt.where(Component.institute_code == institute)
    if stale is not None:
        stmt = stmt.where(Component.stale.is_(stale))
    return list(db.scalars(stmt))


@router.get("/api/components/{sn}", response_model=ComponentDetailOut, tags=["components"])
def get_component(sn: str, db: Session = Depends(get_db)) -> Component:
    component = db.scalar(
        select(Component)
        .options(selectinload(Component.parent), selectinload(Component.children))
        .where(Component.sn == sn)
    )
    if component is None:
        raise HTTPException(status_code=404, detail=f"Component '{sn}' not found.")
    return component


@router.get(
    "/api/components/{sn}/stage-suggestion",
    response_model=StageSuggestionOut,
    tags=["components", "workflow"],
)
def component_stage_suggestion(sn: str, db: Session = Depends(get_db)) -> StageSuggestionOut:
    component = db.scalar(select(Component).where(Component.sn == sn))
    if component is None:
        raise HTTPException(status_code=404, detail=f"Component '{sn}' not found.")

    evaluation = evaluate_for_component(db, component)

    def out(checks) -> list[RequirementCheckOut]:
        return [
            RequirementCheckOut(stage=c.stage, test_type=c.test_type, status=c.status.value)
            for c in checks
        ]

    return StageSuggestionOut(
        sn=sn,
        current_stage=evaluation.current_stage,
        next_stage=evaluation.next_stage,
        move_suggested=evaluation.move_suggested,
        suggested_stage=evaluation.suggested_stage,
        checks=out(evaluation.checks),
        blocking=out(evaluation.blocking),
    )


@router.post(
    "/api/sync/components/{institute_code}",
    response_model=ComponentSyncOut,
    tags=["components", "sync"],
)
def sync_components_for_institute(
    institute_code: str,
    request: Request,
    db: Session = Depends(get_db),
) -> ComponentSyncOut:
    institute = db.scalar(select(InstituteProfile).where(InstituteProfile.code == institute_code))
    if institute is None:
        raise HTTPException(status_code=404, detail=f"Institute '{institute_code}' not found.")

    fetcher = request.app.state.component_fetcher
    try:
        fetched = fetcher(request.app.state.settings, institute)
        # A full institute fetch is authoritative, so prune rows that vanished.
        stats = sync_components(db, fetched.records, prune_scope=institute.code)
        sync_tools_from_components(db, institute)
    except PdbSyncUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except UnknownParentError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    db.commit()
    return ComponentSyncOut(
        institute_code=institute.code,
        fetched=len(fetched.records) + fetched.skipped,
        skipped=fetched.skipped,
        created=stats.created,
        updated=stats.updated,
        unchanged=stats.unchanged,
        stale=stats.stale,
        total=stats.total,
    )


@router.post(
    "/api/sync/tools/{institute_code}",
    response_model=ToolSyncOut,
    tags=["tools", "sync"],
)
def sync_tools_for_institute(
    institute_code: str,
    db: Session = Depends(get_db),
) -> ToolSyncOut:
    """Rebuild the local tool registry from already mirrored PDB tool components."""

    institute = db.scalar(select(InstituteProfile).where(InstituteProfile.code == institute_code))
    if institute is None:
        raise HTTPException(status_code=404, detail=f"Institute '{institute_code}' not found.")

    stats = sync_tools_from_components(db, institute)
    db.commit()
    return ToolSyncOut(
        institute_code=institute.code,
        created=stats.created,
        updated=stats.updated,
        unchanged=stats.unchanged,
        skipped=stats.skipped,
        total=stats.total,
    )


# --------------------------------------------------------------------------
# Dashboard
# --------------------------------------------------------------------------


@router.get("/api/dashboard/summary", response_model=DashboardSummaryOut, tags=["dashboard"])
def dashboard_summary(db: Session = Depends(get_db)) -> DashboardSummaryOut:
    total_components = db.scalar(select(func.count(Component.id))) or 0
    last_synced_at = db.scalar(select(func.max(Component.synced_at)))
    oldest_synced_at = db.scalar(select(func.min(Component.synced_at)))
    stale_components = (
        db.scalar(select(func.count(Component.id)).where(Component.stale.is_(True))) or 0
    )
    trashed_components = (
        db.scalar(select(func.count(Component.id)).where(Component.trashed.is_(True))) or 0
    )
    required_test_gaps, components_with_test_gaps = active_module_requirement_gaps(db)
    submitted_outbox = (
        db.scalar(
            select(func.count(OutboxAction.id)).where(
                OutboxAction.status == OutboxStatus.SUBMITTED.value
            )
        )
        or 0
    )
    approved_outbox = (
        db.scalar(
            select(func.count(OutboxAction.id)).where(
                OutboxAction.status == OutboxStatus.APPROVED.value
            )
        )
        or 0
    )
    review_outbox = (
        db.scalar(
            select(func.count(OutboxAction.id)).where(
                OutboxAction.status.in_(
                    [OutboxStatus.DRAFT.value, OutboxStatus.VALIDATED.value]
                )
            )
        )
        or 0
    )
    failed_outbox = (
        db.scalar(
            select(func.count(OutboxAction.id)).where(
                OutboxAction.status == OutboxStatus.FAILED.value
            )
        )
        or 0
    )
    return DashboardSummaryOut(
        total_components=total_components,
        last_synced_at=last_synced_at,
        oldest_synced_at=oldest_synced_at,
        stale_components=stale_components,
        trashed_components=trashed_components,
        required_test_gaps=required_test_gaps,
        components_with_test_gaps=components_with_test_gaps,
        submitted_outbox=submitted_outbox,
        approved_outbox=approved_outbox,
        review_outbox=review_outbox,
        failed_outbox=failed_outbox,
        # Stages read left-to-right in production order (…→ TESTED → FINISHED),
        # and outbox statuses in their lifecycle order — not by frequency.
        by_stage=order_buckets(count_buckets(db, Component.stage), DEFAULT_STAGE_ORDER),
        by_component_type=count_buckets(db, Component.component_type),
        by_institute=count_buckets(db, Component.institute_code),
        outbox_by_status=order_buckets(
            count_buckets(db, OutboxAction.status), [s.value for s in OutboxStatus]
        ),
    )


# --------------------------------------------------------------------------
# Statistics (throughput / cycle time / rework, from the stage-event history)
# --------------------------------------------------------------------------


@router.get("/api/stats/dimensions", response_model=StatsDimensionsOut, tags=["stats"])
def stats_dimensions(db: Session = Depends(get_db)) -> StatsDimensionsOut:
    """Distinct filter values present in the stage-event history."""

    def distinct(column) -> list[str]:
        return [v for (v,) in db.execute(select(column).distinct().order_by(column)) if v]

    return StatsDimensionsOut(
        component_types=distinct(StageEvent.component_type),
        type_codes=distinct(StageEvent.type_code),
        institutes=distinct(StageEvent.institute_code),
    )


@router.get("/api/stats/production", response_model=ProductionStatsOut, tags=["stats"])
def get_production_stats(
    component_type: str | None = "MODULE",
    type_code: str | None = None,
    institute: str | None = None,
    target_stage: str = "FINISHED",
    bucket: str = "month",
    db: Session = Depends(get_db),
) -> dict:
    if bucket not in ("week", "month", "year"):
        raise HTTPException(status_code=422, detail="bucket must be week, month or year.")
    return production_stats(
        db,
        component_type=component_type or None,
        type_code=type_code or None,
        institute=institute or None,
        target_stage=target_stage,
        bucket=bucket,
    )


# --------------------------------------------------------------------------
# Outbox
# --------------------------------------------------------------------------


@router.get("/api/outbox/contract", response_model=OutboxContractOut, tags=["outbox"])
def get_outbox_contract() -> OutboxContractOut:
    return OutboxContractOut(
        statuses=[status.value for status in OutboxStatus],
        transitions=transition_contract(),
        terminal=[status.value for status in sorted(TERMINAL, key=lambda item: item.value)],
    )


@router.get("/api/outbox", response_model=list[OutboxOut], tags=["outbox"])
def list_outbox(
    status: OutboxStatus | None = None, db: Session = Depends(get_db)
) -> list[OutboxAction]:
    stmt = select(OutboxAction).order_by(OutboxAction.created_at.desc())
    if status is not None:
        stmt = stmt.where(OutboxAction.status == status.value)
    return list(db.scalars(stmt))


@router.get("/api/outbox/{action_id}", response_model=OutboxOut, tags=["outbox"])
def get_outbox_action(action_id: int, db: Session = Depends(get_db)) -> OutboxAction:
    action = db.get(OutboxAction, action_id)
    if action is None:
        raise HTTPException(status_code=404, detail=f"Outbox action {action_id} not found.")
    return action


@router.post("/api/outbox", response_model=OutboxOut, status_code=201, tags=["outbox"])
def create_outbox_action(body: OutboxCreate, db: Session = Depends(get_db)) -> OutboxAction:
    institute = db.scalar(
        select(InstituteProfile).where(InstituteProfile.code == body.institute_code)
    )
    if institute is None:
        raise HTTPException(status_code=404, detail=f"Institute '{body.institute_code}' not found.")
    action = OutboxAction(
        institute_id=institute.id,
        kind=body.kind,
        payload=body.payload,
        status=OutboxStatus.DRAFT.value,
        created_by=body.created_by,
    )
    db.add(action)
    db.flush()
    db.add(
        AuditEvent(
            actor=body.created_by,
            action="outbox.created",
            subject=f"outbox:{action.id}",
            detail={"kind": body.kind, "institute": institute.code},
            outbox_action_id=action.id,
        )
    )
    db.commit()
    db.refresh(action)
    return action


@router.post("/api/outbox/{action_id}/transition", response_model=OutboxOut, tags=["outbox"])
def transition_outbox_action(
    action_id: int, body: OutboxTransition, db: Session = Depends(get_db)
) -> OutboxAction:
    action = db.get(OutboxAction, action_id)
    if action is None:
        raise HTTPException(status_code=404, detail=f"Outbox action {action_id} not found.")

    current = OutboxStatus(action.status)
    try:
        assert_transition(current, body.to)
    except InvalidTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    action.status = body.to.value
    if body.to is OutboxStatus.SUBMITTED:
        action.attempts += 1
        action.error = None
    if body.to is OutboxStatus.FAILED:
        action.error = body.error or "Unknown error."

    db.add(
        AuditEvent(
            actor=body.actor,
            action="outbox.transition",
            subject=f"outbox:{action.id}",
            detail={"from": current.value, "to": body.to.value, "error": body.error},
            outbox_action_id=action.id,
        )
    )
    db.commit()
    db.refresh(action)
    return action


# --------------------------------------------------------------------------
# Ingestion inbox (local only; PDB uploads are later outbox actions)
# --------------------------------------------------------------------------


@router.get("/api/ingest/files", response_model=list[IngestFileOut], tags=["ingestion"])
def list_ingest_files(
    status: str | None = None, db: Session = Depends(get_db)
) -> list[IngestFile]:
    stmt = select(IngestFile).order_by(IngestFile.created_at.desc(), IngestFile.id.desc())
    if status:
        stmt = stmt.where(IngestFile.status == status)
    return list(db.scalars(stmt))


@router.post(
    "/api/ingest/files",
    response_model=IngestFileOut,
    status_code=201,
    tags=["ingestion"],
)
def create_ingest_file(body: IngestFileCreate, db: Session = Depends(get_db)) -> IngestFile:
    raw = canonical_json_bytes(body.payload)
    parsed = parse_payload(body.payload)
    component = resolve_component(db, parsed)
    component_sn = parsed.component_sn or (component.sn if component is not None else None)

    notes = list(parsed.issues)
    if component_sn is None and parsed.local_name is not None:
        notes.append(f"Local name '{parsed.local_name}' does not match any mirrored component")

    ingest = IngestFile(
        filename=body.filename,
        sha256=hashlib.sha256(raw).hexdigest(),
        size_bytes=len(raw),
        status="triage" if notes else "received",
        component_sn=component_sn,
        test_type=parsed.test_type,
        parser=parsed.parser,
        error="; ".join(notes) if notes else None,
        payload=body.payload,
        uploaded_by=body.uploaded_by,
    )
    db.add(ingest)
    db.flush()
    db.add(
        AuditEvent(
            actor=body.uploaded_by,
            action="ingest.received",
            subject=f"ingest:{ingest.id}",
            detail={
                "filename": ingest.filename,
                "status": ingest.status,
                "component_sn": ingest.component_sn,
                "test_type": ingest.test_type,
            },
        )
    )
    db.commit()
    db.refresh(ingest)
    return ingest


@router.get(
    "/api/ingest/files/{file_id}/preview",
    response_model=IngestPreviewOut,
    tags=["ingestion"],
)
def preview_ingest_file(file_id: int, db: Session = Depends(get_db)) -> IngestPreviewOut:
    """Dry-run parse of a stored payload — no state change, no PDB access."""
    ingest = db.get(IngestFile, file_id)
    if ingest is None:
        raise HTTPException(status_code=404, detail=f"Ingest file {file_id} not found.")

    parsed = parse_payload(ingest.payload)
    component = resolve_component(db, parsed)
    component_sn = parsed.component_sn or (component.sn if component is not None else None)
    return IngestPreviewOut(
        file_id=ingest.id,
        parser=parsed.parser,
        upload_ready=(
            not parsed.issues and component_sn is not None and parsed.test_type is not None
        ),
        component_sn=component_sn,
        local_name=parsed.local_name,
        component_mirrored=component is not None,
        component_stage=component.stage if component is not None else None,
        institute_code=component.institute_code if component is not None else None,
        test_type=parsed.test_type,
        run_number=parsed.run_number,
        institution=parsed.institution,
        measured_at=parsed.measured_at,
        passed=parsed.passed,
        problems=parsed.problems,
        n_properties=parsed.n_properties,
        results=parsed.results,
        issues=parsed.issues,
        warnings=parsed.warnings,
    )


@router.post(
    "/api/ingest/files/{file_id}/propose-outbox",
    response_model=OutboxOut,
    status_code=201,
    tags=["ingestion", "outbox"],
)
def propose_ingest_outbox_action(
    file_id: int, body: IngestProposalCreate, db: Session = Depends(get_db)
) -> OutboxAction:
    ingest = db.get(IngestFile, file_id)
    if ingest is None:
        raise HTTPException(status_code=404, detail=f"Ingest file {file_id} not found.")
    if ingest.outbox_action_id is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Ingest file {file_id} already has outbox action {ingest.outbox_action_id}.",
        )
    if ingest.component_sn is None or ingest.test_type is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "Ingest file needs component serial number and test type "
                "before outbox proposal."
            ),
        )
    parsed = parse_payload(ingest.payload)
    if parsed.issues:
        raise HTTPException(
            status_code=409,
            detail=f"Dry-run validation failed: {'; '.join(parsed.issues)}.",
        )

    component = db.scalar(select(Component).where(Component.sn == ingest.component_sn))
    institute_code = component.institute_code if component is not None else body.institute_code
    if institute_code is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "Component is not mirrored locally; provide institute_code or sync components "
                "before proposing an upload."
            ),
        )
    institute = db.scalar(select(InstituteProfile).where(InstituteProfile.code == institute_code))
    if institute is None:
        raise HTTPException(status_code=404, detail=f"Institute '{institute_code}' not found.")

    action = OutboxAction(
        institute_id=institute.id,
        kind="upload_test_run",
        status=OutboxStatus.DRAFT.value,
        created_by=body.created_by,
        payload={
            "ingest_file_id": ingest.id,
            "filename": ingest.filename,
            "sha256": ingest.sha256,
            "component_sn": ingest.component_sn,
            "test_type": ingest.test_type,
            "parser": ingest.parser,
            "run_number": parsed.run_number,
            "passed": parsed.passed,
            "measured_at": parsed.measured_at,
            "dry_run_required": True,
        },
    )
    db.add(action)
    db.flush()
    ingest.outbox_action_id = action.id
    ingest.status = "proposed"
    ingest.error = None
    db.add(
        AuditEvent(
            actor=body.created_by,
            action="ingest.outbox_proposed",
            subject=f"ingest:{ingest.id}",
            detail={"outbox_action_id": action.id, "institute": institute.code},
            outbox_action_id=action.id,
        )
    )
    db.commit()
    db.refresh(action)
    return action


# --------------------------------------------------------------------------
# Audit
# --------------------------------------------------------------------------


@router.get("/api/audit", response_model=list[AuditOut], tags=["audit"])
def list_audit(limit: int = 100, db: Session = Depends(get_db)) -> list[AuditEvent]:
    stmt = (
        select(AuditEvent)
        .order_by(AuditEvent.ts.desc(), AuditEvent.id.desc())
        .limit(min(limit, 500))
    )
    return list(db.scalars(stmt))


# --------------------------------------------------------------------------
# Component images (metrology / VI attachments, read-only PDB fetch)
# --------------------------------------------------------------------------


def _pdb_gateway(request: Request):
    """The PDB gateway for read-only fetches; tests may inject a fake on app.state."""
    from app.pdb_gateway import PdbGateway

    injected = getattr(request.app.state, "pdb_gateway", None)
    return injected if injected is not None else PdbGateway(request.app.state.settings)


@router.get(
    "/api/components/{sn}/images",
    response_model=list[ComponentImageOut],
    tags=["components"],
)
def component_images(sn: str, request: Request) -> list[dict]:
    """List a component's metrology/VI image attachments (empty when offline)."""
    from app.pdb_attachments import list_component_images

    return list_component_images(_pdb_gateway(request), sn)


@router.get("/api/components/{sn}/images/{attachment_id}", tags=["components"])
def component_image_binary(sn: str, attachment_id: str, request: Request) -> Response:
    """Stream one image attachment's bytes from the PDB binary store."""
    from app.pdb_attachments import fetch_image_binary

    result = fetch_image_binary(_pdb_gateway(request), sn, attachment_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Image not available.")
    content_type, data = result
    return Response(content=data, media_type=content_type)


@router.get(
    "/api/components/{sn}/staged",
    response_model=list[OutboxOut],
    tags=["components", "outbox"],
)
def component_staged_changes(sn: str, db: Session = Depends(get_db)) -> list[OutboxAction]:
    """Outbox actions targeting this component that are not yet confirmed/cancelled.

    This is the 'ghost' layer for a module: everything staged for it but not
    pushed to the PDB, newest first. Actions reference the component by `sn`
    (stage moves) or `component_sn` (test uploads)."""
    open_actions = db.scalars(
        select(OutboxAction)
        .where(OutboxAction.status.not_in([status.value for status in TERMINAL]))
        .order_by(OutboxAction.created_at.desc(), OutboxAction.id.desc())
    )
    result = []
    for action in open_actions:
        payload = action.payload or {}
        if payload.get("sn") == sn or payload.get("component_sn") == sn:
            result.append(action)
    return result


@router.post(
    "/api/components/{sn}/sync-evidence",
    response_model=EvidenceSyncOut,
    tags=["components", "workflow"],
)
def component_sync_evidence(
    sn: str, request: Request, db: Session = Depends(get_db)
) -> EvidenceSyncOut:
    """Mirror this component's PDB test-run results into local evidence, so the
    stage engine knows which required tests really passed (not just itkFlow
    uploads). Read-only against the PDB; no-op counts when not configured."""
    from app.pdb_test_evidence import fetch_test_run_evidence
    from app.test_run_evidence import upsert_test_run_evidence

    records = fetch_test_run_evidence(_pdb_gateway(request), sn)
    stats = upsert_test_run_evidence(db, records)
    db.commit()
    return EvidenceSyncOut(
        component_sn=sn,
        created=stats.created,
        updated=stats.updated,
        unchanged=stats.unchanged,
        total=stats.total,
    )


@router.post(
    "/api/sync/evidence/{institute_code}",
    response_model=InstituteEvidenceSyncOut,
    tags=["components", "workflow"],
)
def sync_institute_evidence(
    institute_code: str,
    request: Request,
    component_type: str = "MODULE",
    db: Session = Depends(get_db),
) -> InstituteEvidenceSyncOut:
    """Mirror PDB test-run evidence for every live component of one type at an
    institute, so the dashboard's required-test gaps and stage suggestions
    reflect real PDB results. One PDB read per component; a no-op when the
    gateway is not configured."""
    from app.pdb_test_evidence import fetch_test_run_evidence
    from app.test_run_evidence import upsert_test_run_evidence

    gateway = _pdb_gateway(request)
    components = db.scalars(
        select(Component).where(
            Component.institute_code == institute_code,
            Component.component_type == component_type,
            Component.trashed.is_(False),
        )
    )
    records = []
    processed = 0
    for component in components:
        records.extend(fetch_test_run_evidence(gateway, component.sn))
        processed += 1
    stats = upsert_test_run_evidence(db, records)
    db.commit()
    return InstituteEvidenceSyncOut(
        institute_code=institute_code,
        components_processed=processed,
        created=stats.created,
        updated=stats.updated,
        unchanged=stats.unchanged,
        total=stats.total,
    )
