import hashlib
import json
from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app import __version__
from app.ingestion import ParsedTestRun, parse_payload
from app.models import AuditEvent, Component, IngestFile, InstituteProfile, OutboxAction
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
    ComponentOut,
    ComponentSyncOut,
    CountBucket,
    DashboardSummaryOut,
    HealthOut,
    IngestFileCreate,
    IngestFileOut,
    IngestPreviewOut,
    IngestProposalCreate,
    InstituteCreate,
    InstituteOut,
    OutboxContractOut,
    OutboxCreate,
    OutboxOut,
    OutboxTransition,
    RequirementCheckOut,
    StageSuggestionOut,
)
from app.stage_service import evaluate_for_component
from app.sync import UnknownParentError, sync_components


def get_db(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        yield session


router = APIRouter()


def count_buckets(db: Session, column) -> list[CountBucket]:
    rows = db.execute(
        select(column, func.count()).group_by(column).order_by(func.count().desc(), column)
    )
    return [CountBucket(label=str(label), count=count) for label, count in rows]


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
        status="ok", app=settings.app_name, version=__version__, pdb_instance=settings.pdb_instance
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
# Components (PDB mirror, read-only — writes go through sync/outbox)
# --------------------------------------------------------------------------


@router.get("/api/components", response_model=list[ComponentOut], tags=["components"])
def list_components(
    q: str | None = None,
    stage: str | None = None,
    component_type: str | None = None,
    institute: str | None = None,
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
        stats = sync_components(db, fetched.records)
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
        total=stats.total,
    )


# --------------------------------------------------------------------------
# Dashboard
# --------------------------------------------------------------------------


@router.get("/api/dashboard/summary", response_model=DashboardSummaryOut, tags=["dashboard"])
def dashboard_summary(db: Session = Depends(get_db)) -> DashboardSummaryOut:
    total_components = db.scalar(select(func.count(Component.id))) or 0
    last_synced_at = db.scalar(select(func.max(Component.synced_at)))
    submitted_outbox = (
        db.scalar(
            select(func.count(OutboxAction.id)).where(
                OutboxAction.status == OutboxStatus.SUBMITTED.value
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
        submitted_outbox=submitted_outbox,
        failed_outbox=failed_outbox,
        by_stage=count_buckets(db, Component.stage),
        by_component_type=count_buckets(db, Component.component_type),
        by_institute=count_buckets(db, Component.institute_code),
        outbox_by_status=count_buckets(db, OutboxAction.status),
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
