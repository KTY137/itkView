import hashlib
import hmac
import json
from collections.abc import Iterator
from datetime import timezone
from functools import lru_cache
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app import __version__
from app.assembly import (
    ASSEMBLY_ACTION_KIND,
    canonical_action_payload,
    evaluate_assembly,
)
from app.auth import (
    CSRF_HEADER,
    SESSION_TTL,
    csrf_cookie_name,
    hash_password,
    new_csrf_token,
    new_session_token,
    session_cookie_name,
    session_expiry,
    verify_password,
)
from app.config import ProductionAccessError, Settings
from app.domain.glue import pot_life_state
from app.domain.stages import DEFAULT_STAGE_ORDER
from app.glue_service import derivation_payload, derived_result_codes, derived_result_grams
from app.ingestion import (
    ParsedTestRun,
    derive_glue_results,
    missing_required_properties,
    parse_payload,
)
from app.institute_settings import (
    InstituteSettingsValidationError,
    normalize_institute_settings_update,
)
from app.measurement_stats import measurement_dimensions, measurement_series
from app.models import (
    AuditEvent,
    Component,
    GlueBatch,
    GlueUsage,
    IngestFile,
    InstituteProfile,
    OutboxAction,
    OutboxPdbPrincipal,
    PdbCredential,
    Reminder,
    ReminderOccurrence,
    Shipment,
    StageEvent,
    SyncJob,
    TestRunEvidence,
    TestTypeSchema,
    Tool,
    User,
    UserSession,
    utcnow,
)
from app.notifications import (
    NotificationError,
    channel_configs,
    redact_channel_urls,
)
from app.ops_health import collect_ops_health
from app.outbox import (
    TERMINAL,
    InvalidTransition,
    OutboxStatus,
    assert_transition,
    transition_contract,
)
from app.pdb_credentials import (
    CredentialDecryptionError,
    CredentialIdentityConflictError,
    CredentialKeyInvalidError,
    CredentialKeyMissingError,
    CredentialNotFoundError,
    PdbAccessCodes,
    delete_pdb_credentials,
    get_pdb_credential_status,
    load_pdb_credentials,
    save_pdb_credentials,
    update_pdb_credential_status,
)
from app.pdb_gateway import PdbClientUnavailable
from app.pdb_scope import is_registrable_type
from app.pdb_sync import PdbSyncUnavailable
from app.required_test_stats import required_test_stats
from app.schemas import (
    AssemblyDraftIn,
    AssemblyPreviewOut,
    AssemblyStageOut,
    AttachmentLocatorOut,
    ThumbnailPartOut,
    AttachmentSyncOut,
    AuditOut,
    ChildAttachmentsOut,
    ComponentAttachmentsOut,
    ComponentDetailOut,
    ComponentImageOut,
    ComponentOut,
    ComponentPreviewOut,
    ComponentRegisterIn,
    ComponentSyncOut,
    CountBucket,
    DashboardSummaryOut,
    EvidenceSyncOut,
    GlueBatchCreate,
    GlueBatchMixIn,
    GlueBatchOut,
    GlueBatchUpdate,
    GlueUsageCreate,
    GlueUsageOut,
    HealthOut,
    IngestFileCreate,
    IngestFileOut,
    IngestPreviewOut,
    IngestProposalCreate,
    InstituteCreate,
    InstituteEvidenceSyncOut,
    InstituteOut,
    InstituteUpdate,
    LoginIn,
    MeasurementDimensionsOut,
    MeasurementSeriesOut,
    MeOut,
    NotificationChannelOut,
    NotificationTestIn,
    NotificationTestOut,
    OpsHealthOut,
    OutboxContractOut,
    OutboxCreate,
    OutboxOut,
    OutboxTransition,
    PdbConnectionOut,
    PdbCredentialsPut,
    ProductCapabilitiesOut,
    ProductionStatsOut,
    ReminderCreate,
    ReminderOccurrenceOut,
    ReminderOut,
    ReminderUpdate,
    RequiredTestStatsOut,
    RequirementCheckOut,
    SetupAdminIn,
    SetupStatusOut,
    ShareCredentialOut,
    ShareCredentialPut,
    ShipmentItemOut,
    ShipmentOut,
    ShipmentReceptionUpdate,
    ShipmentSyncOut,
    StageSuggestionOut,
    StatsDimensionsOut,
    SyncJobOut,
    TestRunAttachmentOut,
    TestRunDetailOut,
    TestTypeSchemaOut,
    TestTypeSchemaSyncOut,
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
from app.sync import UnknownParentError
from app.sync_jobs import (
    ACTIVE_SYNC_STATUSES,
    COMPONENT_SYNC_KIND,
    EvidenceSyncModeConflict,
    SYNC_HEARTBEAT_GRACE,
    SyncLeaseBusy,
    SyncLeaseLost,
    _job_heartbeat_stale,
    acquire_component_sync_lease,
    acquire_evidence_sync_lease,
    fail_sync_job,
    run_inline_component_sync,
)
from app.tool_sync import sync_tools_from_components


def get_db(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        yield session


def _sync_job_out(job: SyncJob) -> SyncJobOut:
    """Serialize heartbeat state with the server's canonical stale clock."""

    # Queued evidence jobs keep their requested scope in a private result key
    # so a process restart cannot silently turn lightweight into standard.
    # The public contract still exposes no result until the worker completes.
    raw_result = job.result
    public_result = (
        None
        if isinstance(raw_result, dict) and "institute_code" not in raw_result
        else raw_result
    )
    payload = {
        name: getattr(job, name)
        for name in SyncJobOut.model_fields
        if hasattr(job, name)
    }
    payload["result"] = public_result
    return SyncJobOut.model_validate(payload).model_copy(
        update={
            "heartbeat_stale": _job_heartbeat_stale(job),
            "stale_after_seconds": int(SYNC_HEARTBEAT_GRACE.total_seconds()),
        }
    )


def current_session(request: Request, db: Session = Depends(get_db)) -> UserSession | None:
    """Resolve the live (unexpired) session from the cookie, or None."""
    cookie_name = session_cookie_name(request.app.state.settings.product_variant)
    token = request.cookies.get(cookie_name)
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
    return session


def current_user(
    session: UserSession | None = Depends(current_session),
    db: Session = Depends(get_db),
) -> User | None:
    """Resolve the signed-in user from the session cookie, or None. Optional —
    endpoints stay usable while auth is being rolled out (docs/06)."""
    if session is None:
        return None
    user = db.get(User, session.user_id)
    return user if (user is not None and user.is_active) else None


def require_user(user: User | None = Depends(current_user)) -> User:
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return user


_CSRF_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def csrf_protect(
    request: Request, session: UserSession | None = Depends(current_session)
) -> None:
    """Double-submit CSRF guard, bound to the server-side session (docs/06).

    Applied to every route (router-level dependency) but only enforced on
    state-changing requests that carry a valid session: safe methods are exempt,
    and an unauthenticated request has no ambient cookie authority to forge (it
    is still stopped by the auth dependency where a role is required). When a
    session is present, the `X-CSRF-Token` header must equal the token bound to
    that session row; login itself is exempt because no session exists yet.
    """
    if request.method in _CSRF_SAFE_METHODS:
        return
    # Login must not be blocked by a stale/leftover session cookie — it
    # establishes a fresh session. Everything else needs a matching token.
    if request.url.path == "/api/auth/login":
        return
    # No session, or a legacy session created before CSRF tokens existed (no
    # token to match yet) — `whoami` mints one on the next /me call.
    if session is None or not session.csrf_token:
        return
    header = request.headers.get(CSRF_HEADER) or ""
    if not hmac.compare_digest(header, session.csrf_token):
        raise HTTPException(status_code=403, detail="Missing or invalid CSRF token.")


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


def _require_institute_scope(user: User, institute: InstituteProfile) -> None:
    """Reject an institute-bound user targeting another institute's writes."""

    if user.institute_id is not None and user.institute_id != institute.id:
        raise HTTPException(
            status_code=403,
            detail="You can only modify data for your own institute.",
        )


def _me(user: User, csrf_token: str) -> MeOut:
    code = user.institute.code if user.institute is not None else None
    return MeOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=user.role,
        institute_id=user.institute_id,
        institute_code=code,
        csrf_token=csrf_token,
    )


def _set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        session_cookie_name(settings.product_variant),
        token,
        httponly=True,
        samesite="lax",
        secure=settings.session_cookie_secure,
        max_age=int(SESSION_TTL.total_seconds()),
    )


def _set_csrf_cookie(response: Response, csrf_token: str, settings: Settings) -> None:
    # Readable by the frontend (NOT httpOnly) so it can echo the token back in
    # the X-CSRF-Token header (double-submit, docs/06).
    response.set_cookie(
        csrf_cookie_name(settings.product_variant),
        csrf_token,
        httponly=False,
        samesite="lax",
        secure=settings.session_cookie_secure,
        max_age=int(SESSION_TTL.total_seconds()),
    )


# Every route carries the CSRF guard; it is a no-op for safe methods and for
# unauthenticated requests (see `csrf_protect`).
router = APIRouter(dependencies=[Depends(csrf_protect)])


# --------------------------------------------------------------------------
# Auth & users (docs/06). Additive: existing endpoints remain open for now.
# --------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _dummy_password_hash() -> str:
    """One process-constant hash so an unknown email still pays for a full
    PBKDF2 verification instead of returning immediately — otherwise "no such
    account" would answer measurably faster than "wrong password" and let an
    attacker enumerate registered emails purely from login latency. Lazy
    (first login) rather than import-time: 200k PBKDF2 rounds cost ~0.4s,
    which must not tax every app start and test run (review M3). The password
    behind it is discarded; it is never compared against anything real.
    """
    return hash_password("itkflow-constant-time-login-placeholder")


@router.post("/api/auth/login", response_model=MeOut, tags=["auth"])
def login(
    body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)
) -> MeOut:
    user = db.scalar(select(User).where(User.email == body.email.strip().lower()))
    # Always run exactly one verification, against the real hash when the
    # account exists (even if inactive) or the dummy hash otherwise, so the
    # branch taken cannot be inferred from response timing. A password-less
    # account (future SSO shape) also takes the dummy path: verify_password
    # short-circuits on a falsy hash, which would answer faster (review M4).
    stored_hash = (
        user.password_hash
        if user is not None and user.password_hash
        else _dummy_password_hash()
    )
    password_ok = verify_password(body.password, stored_hash)
    if user is None or not user.is_active or not password_ok:
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    token = new_session_token()
    csrf_token = new_csrf_token()
    db.add(
        UserSession(
            token=token, user_id=user.id, csrf_token=csrf_token, expires_at=session_expiry()
        )
    )
    db.commit()
    settings = request.app.state.settings
    _set_session_cookie(response, token, settings)
    _set_csrf_cookie(response, csrf_token, settings)
    return _me(user, csrf_token)


@router.post("/api/auth/logout", status_code=204, tags=["auth"])
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> None:
    settings = request.app.state.settings
    session_cookie = session_cookie_name(settings.product_variant)
    csrf_cookie = csrf_cookie_name(settings.product_variant)
    token = request.cookies.get(session_cookie)
    if token:
        session = db.scalar(select(UserSession).where(UserSession.token == token))
        if session is not None:
            db.delete(session)
            db.commit()
    response.delete_cookie(session_cookie)
    response.delete_cookie(csrf_cookie)


@router.get("/api/auth/me", response_model=MeOut, tags=["auth"])
def whoami(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
    session: UserSession | None = Depends(current_session),
) -> MeOut:
    # `require_user` guarantees a live session here. Legacy sessions created
    # before CSRF tokens existed carry none — mint and persist one so the token
    # is always a valid string the frontend can echo back on writes.
    csrf_token = session.csrf_token if session is not None else ""
    if session is not None and not csrf_token:
        csrf_token = new_csrf_token()
        session.csrf_token = csrf_token
        db.commit()
    _set_csrf_cookie(response, csrf_token, request.app.state.settings)
    return _me(user, csrf_token)


# --------------------------------------------------------------------------
# First-run setup: create the initial admin from the UI, never the CLI
# --------------------------------------------------------------------------


@router.get("/api/setup", response_model=SetupStatusOut, tags=["auth"])
def setup_status(db: Session = Depends(get_db)) -> SetupStatusOut:
    return SetupStatusOut(needs_admin=db.scalar(select(User.id).limit(1)) is None)


@router.post("/api/setup/admin", response_model=MeOut, status_code=201, tags=["auth"])
def bootstrap_admin(
    body: SetupAdminIn, request: Request, response: Response, db: Session = Depends(get_db)
) -> MeOut:
    """Create the very first admin account and sign it in.

    Open only while the user table is empty, so a fresh deployment needs no
    shell access; from the first user on, account management is admin-gated
    (`/api/users`, docs/06).
    """
    # Two concurrent bootstrap calls could both see an empty table under READ
    # COMMITTED and both create a "first" admin. A transaction-scoped advisory
    # lock serialises them on PostgreSQL; single-writer SQLite needs none.
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(715001)"))
    if db.scalar(select(User.id).limit(1)) is not None:
        raise HTTPException(status_code=409, detail="Setup is already complete.")
    user = User(
        email=body.email.strip().lower(),
        display_name=body.display_name,
        role="admin",
        password_hash=hash_password(body.password),
    )
    db.add(user)
    db.flush()
    db.add(
        AuditEvent(
            actor=user.email,
            user_id=user.id,
            action="setup.admin_created",
            subject=f"user:{user.id}",
            detail={"email": user.email},
        )
    )
    token = new_session_token()
    csrf_token = new_csrf_token()
    db.add(
        UserSession(
            token=token, user_id=user.id, csrf_token=csrf_token, expires_at=session_expiry()
        )
    )
    db.commit()
    settings = request.app.state.settings
    _set_session_cookie(response, token, settings)
    _set_csrf_cookie(response, csrf_token, settings)
    return _me(user, csrf_token)


# --------------------------------------------------------------------------
# Personal Plus4U / PDB connection
# --------------------------------------------------------------------------


def _pdb_connection_out(db: Session, user: User, settings: Settings) -> PdbConnectionOut:
    status = get_pdb_credential_status(db, user_id=user.id)
    return PdbConnectionOut(
        configured=status.configured,
        state=status.status,
        instance=settings.pdb_instance,
        identity=status.pdb_identity,
        institutions=list(status.institutions),
        last_checked_at=status.last_checked_at,
        verified_at=status.verified_at,
    )


def _personal_pdb_gateway(request: Request, access_codes: PdbAccessCodes):
    """Create an operation-local gateway; tests may inject a credential-aware factory."""
    from app.pdb_gateway import PdbGateway

    factory = getattr(request.app.state, "pdb_gateway_factory", None)
    if factory is not None:
        return factory(request.app.state.settings, access_codes)
    return PdbGateway(request.app.state.settings, access_codes=access_codes)


def _pdb_failure_state(error: Exception) -> Literal["invalid", "unreachable"]:
    """Classify without formatting the exception, whose request may contain codes."""
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        response = getattr(current, "response", None)
        status_code = getattr(response, "status_code", None)
        if status_code in {400, 401, 403}:
            return "invalid"
        current = current.__cause__ or current.__context__
    return "unreachable"


def _verified_pdb_metadata(request: Request, access_codes: PdbAccessCodes) -> dict:
    try:
        raw = _personal_pdb_gateway(request, access_codes).verify_connection()
    except ProductionAccessError as exc:
        # Configuration, not weather: an offline instance (or a refused opt-in)
        # must not masquerade as a network outage — that confusion is exactly
        # what the retired test-instance default used to produce.
        raise HTTPException(status_code=503, detail=str(exc)) from None
    except PdbClientUnavailable:
        product_name = request.app.state.settings.app_name
        raise HTTPException(
            status_code=500,
            detail=f"PDB client support is unavailable on this {product_name} server.",
        ) from None
    except Exception as exc:
        state = _pdb_failure_state(exc)
        status_code = 422 if state == "invalid" else 503
        detail = (
            "The PDB rejected these access codes."
            if state == "invalid"
            else "The PDB could not be reached. Try again later."
        )
        # itkdb's ResponseException can embed the complete grantToken body.
        # Never stringify it and suppress the exception chain at the API edge.
        raise HTTPException(status_code=status_code, detail=detail) from None

    if not isinstance(raw, dict) or not isinstance(raw.get("identity"), str):
        raise HTTPException(
            status_code=503,
            detail="The PDB returned an invalid account response. Try again later.",
        )
    identity = raw["identity"].strip()
    if not identity:
        raise HTTPException(
            status_code=422,
            detail="The PDB access codes did not resolve to a user identity.",
        )
    institutions = sorted(
        {
            code.strip()
            for code in (raw.get("institutions") or [])
            if isinstance(code, str) and code.strip()
        }
    )
    name_parts = [raw.get("first_name"), raw.get("last_name")]
    display_name = " ".join(
        part.strip() for part in name_parts if isinstance(part, str) and part.strip()
    )
    return {
        "identity": identity,
        "institutions": institutions,
        "display_name": display_name or None,
    }


def _require_pdb_institute(user: User, institutions: list[str]) -> None:
    if user.institute is not None and user.institute.code not in institutions:
        raise HTTPException(
            status_code=422,
            detail=(
                f"This PDB account is not a member of the local institute "
                f"'{user.institute.code}'."
            ),
        )


def _load_personal_pdb_access(
    request: Request,
    db: Session,
    user: User,
) -> PdbAccessCodes:
    """Resolve one verified credential for this request, with no global fallback."""
    credential = db.get(PdbCredential, user.id)
    if credential is None:
        raise HTTPException(
            status_code=409,
            detail="Connect your personal PDB account in Account settings first.",
        )
    if credential.status != "verified":
        raise HTTPException(
            status_code=409,
            detail="Test and verify your personal PDB connection in Account settings first.",
        )
    _require_pdb_institute(user, list(credential.institutions or []))
    try:
        return load_pdb_credentials(
            db,
            user_id=user.id,
            encryption_key=request.app.state.settings.pdb_credential_encryption_key,
        )
    except CredentialNotFoundError:
        raise HTTPException(
            status_code=409,
            detail="Connect your personal PDB account in Account settings first.",
        ) from None
    except (CredentialDecryptionError, CredentialKeyMissingError, CredentialKeyInvalidError):
        raise HTTPException(
            status_code=503,
            detail="The saved PDB connection cannot be opened by this server.",
        ) from None


def _audit_pdb_connection(
    db: Session,
    user: User,
    action: str,
    *,
    result: str,
    instance: str,
) -> None:
    db.add(
        AuditEvent(
            actor=user.email,
            user_id=user.id,
            action=action,
            subject=f"user:{user.id}:pdb-connection",
            detail={"result": result, "instance": instance},
        )
    )


@router.get(
    "/api/account/pdb-connection",
    response_model=PdbConnectionOut,
    tags=["account", "pdb"],
)
def get_personal_pdb_connection(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> PdbConnectionOut:
    return _pdb_connection_out(db, user, request.app.state.settings)


@router.put(
    "/api/account/pdb-connection",
    response_model=PdbConnectionOut,
    tags=["account", "pdb"],
)
def put_personal_pdb_connection(
    body: PdbCredentialsPut,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> PdbConnectionOut:
    settings = request.app.state.settings
    code1 = body.access_code1.get_secret_value().strip()
    code2 = body.access_code2.get_secret_value().strip()
    if not code1 or not code2:
        raise HTTPException(status_code=422, detail="Both PDB access codes are required.")
    access_codes = PdbAccessCodes(
        code1,
        code2,
    )
    metadata = _verified_pdb_metadata(request, access_codes)
    _require_pdb_institute(user, metadata["institutions"])

    try:
        save_pdb_credentials(
            db,
            user_id=user.id,
            access_codes=access_codes,
            pdb_identity=metadata["identity"],
            pdb_display_name=metadata["display_name"],
            institutions=metadata["institutions"],
            encryption_key=settings.pdb_credential_encryption_key,
        )
        _audit_pdb_connection(
            db,
            user,
            "pdb.connection_connected",
            result="verified",
            instance=settings.pdb_instance,
        )
        db.commit()
    except CredentialIdentityConflictError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=(
                f"This PDB identity is already connected to another "
                f"{settings.app_name} account."
            ),
        ) from None
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=(
                f"This PDB identity is already connected to another "
                f"{settings.app_name} account."
            ),
        ) from None
    except (CredentialKeyMissingError, CredentialKeyInvalidError):
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail="Personal PDB credential storage is not configured on this server.",
        ) from None
    return _pdb_connection_out(db, user, settings)


@router.post(
    "/api/account/pdb-connection/test",
    response_model=PdbConnectionOut,
    tags=["account", "pdb"],
)
def test_personal_pdb_connection(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> PdbConnectionOut:
    settings = request.app.state.settings
    try:
        access_codes = load_pdb_credentials(
            db,
            user_id=user.id,
            encryption_key=settings.pdb_credential_encryption_key,
        )
    except CredentialNotFoundError:
        raise HTTPException(
            status_code=409,
            detail="No personal PDB connection is configured for this account.",
        ) from None
    except (CredentialDecryptionError, CredentialKeyMissingError, CredentialKeyInvalidError):
        raise HTTPException(
            status_code=503,
            detail="The saved PDB connection cannot be opened by this server.",
        ) from None

    try:
        metadata = _verified_pdb_metadata(request, access_codes)
        _require_pdb_institute(user, metadata["institutions"])
        credential = db.get(PdbCredential, user.id)
        if credential is None:
            raise HTTPException(
                status_code=409,
                detail="No personal PDB connection is configured for this account.",
            )
        if metadata["identity"] != credential.pdb_identity:
            raise HTTPException(
                status_code=422,
                detail="The saved access codes no longer match the connected PDB identity.",
            )
        credential.pdb_display_name = metadata["display_name"]
        credential.institutions = metadata["institutions"]
        update_pdb_credential_status(db, user_id=user.id, status="verified")
        _audit_pdb_connection(
            db,
            user,
            "pdb.connection_tested",
            result="verified",
            instance=settings.pdb_instance,
        )
        db.commit()
        return _pdb_connection_out(db, user, settings)
    except HTTPException as exc:
        if exc.status_code == 500:
            # A local deployment problem says nothing about whether the saved
            # personal codes remain valid. Preserve the last known status.
            raise exc from None
        state: Literal["invalid", "unreachable"] = (
            "invalid" if exc.status_code == 422 else "unreachable"
        )
        update_pdb_credential_status(db, user_id=user.id, status=state)
        _audit_pdb_connection(
            db,
            user,
            "pdb.connection_tested",
            result=state,
            instance=settings.pdb_instance,
        )
        db.commit()
        raise exc from None


@router.delete(
    "/api/account/pdb-connection",
    status_code=204,
    tags=["account", "pdb"],
)
def delete_personal_pdb_connection(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> None:
    settings = request.app.state.settings
    removed = delete_pdb_credentials(db, user_id=user.id)
    _audit_pdb_connection(
        db,
        user,
        "pdb.connection_disconnected",
        result="removed" if removed else "not_configured",
        instance=settings.pdb_instance,
    )
    db.commit()


def _share_credential_out(status) -> ShareCredentialOut:
    return ShareCredentialOut(
        id=status.id,
        provider_host=status.provider_host,
        token_hint=status.token_hint,
        updated_at=status.updated_at,
    )


@router.get(
    "/api/account/share-credentials",
    response_model=list[ShareCredentialOut],
    tags=["account", "attachments"],
)
def get_share_credentials(
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> list[ShareCredentialOut]:
    """List only non-secret metadata for this user's public-share passwords."""

    from app.share_credentials import list_share_credentials

    return [
        _share_credential_out(status)
        for status in list_share_credentials(db, user_id=user.id)
    ]


@router.put(
    "/api/account/share-credentials",
    response_model=ShareCredentialOut,
    tags=["account", "attachments"],
)
def put_share_credential(
    body: ShareCredentialPut,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> ShareCredentialOut:
    """Validate and locally save a password for one HTTPS public share.

    Private CERNBox account URLs are intentionally rejected: supporting them
    requires CERN OAuth, never collection of a person's CERN password.
    Share access is checked only when an evidence-bound sync needs the URL;
    this user-controlled settings endpoint never makes an outbound request.
    """

    from app.share_credentials import (
        ShareLinkValidationError,
        SharePasswordValidationError,
        public_share_identity,
        save_share_password,
    )

    settings = request.app.state.settings
    url = body.url.strip()
    password = body.password.get_secret_value()
    try:
        identity = public_share_identity(url)
    except (ShareLinkValidationError, SharePasswordValidationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None

    try:
        row = save_share_password(
            db,
            user_id=user.id,
            url=url,
            password=password,
            encryption_key=settings.pdb_credential_encryption_key,
        )
        db.add(
            AuditEvent(
                actor=user.email,
                user_id=user.id,
                action="share_credential.saved",
                subject=f"user:{user.id}:share-credential",
                detail={"provider_host": identity.host, "result": "saved"},
            )
        )
        db.commit()
        db.refresh(row)
    except SharePasswordValidationError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except (CredentialKeyMissingError, CredentialKeyInvalidError):
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail="Encrypted public-share credential storage is not configured.",
        ) from None
    return _share_credential_out(row)


@router.delete(
    "/api/account/share-credentials/{credential_id}",
    status_code=204,
    tags=["account", "attachments"],
)
def delete_share_password(
    credential_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> None:
    from app.share_credentials import delete_share_credential

    removed = delete_share_credential(
        db,
        user_id=user.id,
        credential_id=credential_id,
    )
    if not removed:
        raise HTTPException(status_code=404, detail="Saved public share not found.")
    db.add(
        AuditEvent(
            actor=user.email,
            user_id=user.id,
            action="share_credential.removed",
            subject=f"user:{user.id}:share-credential:{credential_id}",
            detail={"result": "removed"},
        )
    )
    db.commit()


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
        # A new password invalidates every existing session for this user —
        # otherwise a stolen/leaked session would survive the very reset meant
        # to shut it out.
        db.execute(delete(UserSession).where(UserSession.user_id == user.id))
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

    Gaps are computed by the same stage engine as the detail view, which counts
    both mirrored PDB test-run evidence (`app.pdb_test_evidence`) and confirmed
    itkFlow uploads as satisfied; everything else remains missing.
    Terminal/trashed/stale modules are excluded so old production history does
    not dominate the daily dashboard.
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
    flow_enabled = settings.product_variant == "flow"
    return HealthOut(
        status="ok",
        app=settings.app_name,
        version=__version__,
        product_variant=settings.product_variant,
        write_features_enabled=flow_enabled,
        capabilities=ProductCapabilitiesOut(
            account_management=True,
            mirror_sync=True,
            test_uploads=flow_enabled,
            workflow_writes=flow_enabled,
            operations_writes=flow_enabled,
            pdb_writes=flow_enabled,
            outbound_notifications=flow_enabled,
        ),
        pdb_instance=settings.pdb_instance,
        pdb_write_scope=settings.pdb_write_scope,
    )


# --------------------------------------------------------------------------
# Institutes
# --------------------------------------------------------------------------


def _institute_out(institute: InstituteProfile) -> InstituteOut:
    """Serialize a profile with notification webhook URLs masked.

    The profile is readable by every role, but channel URLs are effectively
    write tokens for the channel they point at. Admins re-enter the URL when
    editing; the API never returns it (same stance as PDB access codes)."""
    out = InstituteOut.model_validate(institute)
    out.settings = redact_channel_urls(out.settings)
    return out


@router.get("/api/institutes", response_model=list[InstituteOut], tags=["institutes"])
def list_institutes(db: Session = Depends(get_db)) -> list[InstituteOut]:
    institutes = db.scalars(select(InstituteProfile).order_by(InstituteProfile.code))
    return [_institute_out(institute) for institute in institutes]


@router.post("/api/institutes", response_model=InstituteOut, status_code=201, tags=["institutes"])
def create_institute(
    body: InstituteCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> InstituteOut:
    """Create a tenant profile.

    Only a global admin may create a new tenant. An institute-bound admin is
    deliberately unable to widen their own scope by minting another profile.
    """
    if admin.institute_id is not None:
        raise HTTPException(
            status_code=403,
            detail="Only a global admin can create an institute.",
        )
    exists = db.scalar(select(InstituteProfile).where(InstituteProfile.code == body.code))
    if exists:
        raise HTTPException(status_code=409, detail=f"Institute '{body.code}' already exists.")
    try:
        normalized_settings = normalize_institute_settings_update({}, body.settings)
    except InstituteSettingsValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    institute = InstituteProfile(
        **body.model_dump(exclude={"settings"}),
        settings=normalized_settings,
    )
    db.add(institute)
    db.flush()
    db.add(
        AuditEvent(
            actor=admin.email,
            user_id=admin.id,
            action="institute.created",
            subject=f"institute:{institute.code}",
            detail={"institute_id": institute.id},
        )
    )
    db.commit()
    db.refresh(institute)
    return _institute_out(institute)


@router.get("/api/ops/health", response_model=OpsHealthOut, tags=["operations"])
def operations_health(
    request: Request,
    institute_code: str | None = None,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict:
    """Return local operational telemetry without contacting the PDB.

    Institute-bound admins always see their own tenant.  A global admin may
    select one institute or omit ``institute_code`` for an installation-wide
    aggregate.
    """

    institute: InstituteProfile | None
    if admin.institute_id is not None:
        institute = db.get(InstituteProfile, admin.institute_id)
        if institute is None:
            raise HTTPException(status_code=409, detail="Admin institute is not configured.")
        if institute_code is not None and institute_code != institute.code:
            raise HTTPException(
                status_code=403,
                detail="You can only view operations for your own institute.",
            )
    elif institute_code is not None:
        institute = db.scalar(
            select(InstituteProfile).where(InstituteProfile.code == institute_code)
        )
        if institute is None:
            raise HTTPException(
                status_code=404,
                detail=f"Institute '{institute_code}' not found.",
            )
    else:
        institute = None
    snapshot = collect_ops_health(
        db,
        request.app.state.settings,
        institute=institute,
    )
    from app.diagnostics import diagnostics_available

    snapshot["diagnostics_available"] = (
        admin.institute_id is None
        and diagnostics_available(getattr(request.app.state, "desktop_log_dir", None))
    )
    return snapshot


@router.get("/api/ops/diagnostics", tags=["operations"])
def operations_diagnostics(
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> Response:
    """Download a bounded local desktop log bundle for global admins only."""

    if admin.institute_id is not None:
        raise HTTPException(
            status_code=403,
            detail="Installation diagnostics require a global administrator.",
        )
    from app.diagnostics import DiagnosticsUnavailableError, build_diagnostics_bundle

    log_dir = getattr(request.app.state, "desktop_log_dir", None)
    try:
        bundle = build_diagnostics_bundle(
            db,
            log_dir=log_dir,
            app_version=__version__,
        )
    except (DiagnosticsUnavailableError, OSError, TypeError):
        raise HTTPException(
            status_code=404,
            detail="Desktop diagnostics are not available on this server.",
        ) from None
    stamp = utcnow().strftime("%Y%m%d-%H%M%S")
    product_name = (
        "itkView"
        if request.app.state.settings.product_variant == "view"
        else "itkFlow"
    )
    return Response(
        content=bundle,
        media_type="application/zip",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": (
                f'attachment; filename="{product_name}-diagnostics-{stamp}.zip"'
            ),
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.patch("/api/institutes/{code}", response_model=InstituteOut, tags=["institutes"])
def update_institute(
    code: str,
    body: InstituteUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> InstituteOut:
    """Update an institute profile's config — branding, `stage_requirements`,
    `required_properties` (docs/07), `notification_channels` (docs/11), etc.
    Admin-only: a per-institute admin may edit only their own institute, a
    global admin any. `settings` is shallow-merged so unrelated config
    survives."""
    institute = db.scalar(select(InstituteProfile).where(InstituteProfile.code == code))
    if institute is None:
        raise HTTPException(status_code=404, detail=f"Institute '{code}' not found.")
    if admin.institute_id is not None and admin.institute_id != institute.id:
        raise HTTPException(status_code=403, detail="You can only edit your own institute.")

    changed_fields: list[str] = []
    changed_settings_keys: list[str] = []
    changed_channel_names: list[str] = []
    if body.name is not None and body.name != institute.name:
        institute.name = body.name
        changed_fields.append("name")
    if (
        body.local_name_prefix is not None
        and body.local_name_prefix != institute.local_name_prefix
    ):
        institute.local_name_prefix = body.local_name_prefix
        changed_fields.append("local_name_prefix")
    if body.settings is not None:
        current_settings = institute.settings if isinstance(institute.settings, dict) else {}
        try:
            settings_patch = normalize_institute_settings_update(
                current_settings,
                body.settings,
            )
        except InstituteSettingsValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None

        next_settings = {**current_settings, **settings_patch}
        # The short-lived legacy name is accepted at the request boundary but
        # must disappear from storage as soon as a canonical default is saved.
        # A plain shallow merge cannot express that deletion on its own.
        if "glue_default_process" in settings_patch:
            next_settings.pop("glue_process_default", None)
        missing = object()
        changed_settings_keys = sorted(
            key
            for key in set(current_settings) | set(next_settings)
            if current_settings.get(key, missing) != next_settings.get(key, missing)
        )
        if "notification_channels" in changed_settings_keys:
            previous_channels = current_settings.get("notification_channels")
            next_channels = settings_patch["notification_channels"]
            previous_channels = previous_channels if isinstance(previous_channels, dict) else {}
            changed_channel_names = sorted(
                name
                for name in set(previous_channels) | set(next_channels)
                if previous_channels.get(name) != next_channels.get(name)
            )
        if changed_settings_keys:
            institute.settings = next_settings

    if changed_fields or changed_settings_keys:
        detail: dict[str, list[str]] = {}
        if changed_fields:
            detail["profile_fields"] = sorted(changed_fields)
        if changed_settings_keys:
            detail["settings_keys"] = changed_settings_keys
        if changed_channel_names:
            detail["notification_channels"] = changed_channel_names
        db.add(
            AuditEvent(
                actor=admin.email,
                user_id=admin.id,
                action="institute.updated",
                subject=f"institute:{institute.code}",
                detail=detail,
            )
        )
    db.commit()
    db.refresh(institute)
    return _institute_out(institute)


# --------------------------------------------------------------------------
# Tools / jigs registry (docs/07). Reads open; writes require operator/admin.
# --------------------------------------------------------------------------


@router.get("/api/tools", response_model=list[ToolOut], tags=["tools"])
def list_tools(
    kind: str | None = None,
    fits: str | None = None,
    status: str | None = None,
    institute: str | None = None,
    db: Session = Depends(get_db),
) -> list[Tool]:
    stmt = select(Tool).order_by(Tool.kind, Tool.code)
    if kind:
        stmt = stmt.where(Tool.kind == kind)
    if status:
        stmt = stmt.where(Tool.status == status)
    if institute:
        profile = db.scalar(
            select(InstituteProfile).where(
                func.lower(InstituteProfile.code) == institute.strip().lower()
            )
        )
        if profile is None:
            return []
        stmt = stmt.where(Tool.institute_id == profile.id)
    tools = list(db.scalars(stmt))
    if fits:  # keep only tools compatible with this component/module type
        fits_code = fits.strip().upper()
        tools = [tool for tool in tools if fits_code in (tool.compatible_types or [])]
    return tools


@router.get("/api/tools/by-rfid/{rfid}", response_model=ToolOut, tags=["tools"])
def get_tool_by_rfid(
    rfid: str,
    institute: str | None = None,
    db: Session = Depends(get_db),
) -> Tool:
    stmt = select(Tool).where(func.lower(Tool.rfid) == rfid.strip().lower())
    if institute:
        stmt = stmt.join(InstituteProfile).where(
            func.lower(InstituteProfile.code) == institute.strip().lower()
        )
    tool = db.scalar(stmt)
    if tool is None:
        raise HTTPException(status_code=404, detail=f"No tool with RFID '{rfid}'.")
    return tool


@router.get("/api/tools/scan", response_model=ToolOut, tags=["tools"])
def scan_tool(
    code: str,
    institute: str | None = None,
    db: Session = Depends(get_db),
) -> Tool:
    """Resolve a scanned value to a tool by RFID *or* printed code.

    Scanner-first: a wedge scanner emits either the RFID tag or the label code,
    so match both, case-insensitively. This is the auto-pull the Tools screen
    uses to surface a jig the moment it is scanned.
    """
    needle = code.strip()
    if needle == "":
        raise HTTPException(status_code=422, detail="Empty scan value.")
    stmt = select(Tool).where(
        or_(
            func.lower(Tool.rfid) == needle.lower(),
            func.lower(Tool.code) == needle.lower(),
            func.lower(Tool.label) == needle.lower(),
        )
    )
    if institute:
        stmt = stmt.join(InstituteProfile).where(
            func.lower(InstituteProfile.code) == institute.strip().lower()
        )
    tool = db.scalar(stmt)
    if tool is None:
        raise HTTPException(status_code=404, detail=f"No tool matches scan '{code}'.")
    return tool


@router.post("/api/tools", response_model=ToolOut, status_code=201, tags=["tools"])
def create_tool(
    body: ToolCreate, db: Session = Depends(get_db), user: User = Depends(require_operator)
) -> Tool:
    institute = _tool_institute(db, user, body.institute_code)
    values = _normalized_tool_values(
        kind=body.kind,
        code=body.code,
        label=body.label,
        rfid=body.rfid,
        compatible_types=body.compatible_types,
    )
    _ensure_tool_identifiers_available(
        db,
        institute_id=institute.id,
        code=values["code"],
        rfid=values["rfid"],
    )
    tool = Tool(
        **values,
        status=body.status,
        institute_id=institute.id,
    )
    db.add(tool)
    db.flush()
    db.add(
        AuditEvent(
            actor=user.email,
            user_id=user.id,
            action="tool.created",
            subject=f"tool:{tool.id}",
            detail={
                "institute": institute.code,
                "kind": tool.kind,
                "code": tool.code,
                "status": tool.status,
                "compatible_types": list(tool.compatible_types or []),
            },
        )
    )
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
    if tool.institute_id is not None:
        institute = db.get(InstituteProfile, tool.institute_id)
        if institute is not None:
            _require_institute_scope(user, institute)
    target_institute_id = tool.institute_id or user.institute_id
    if target_institute_id is None:
        raise HTTPException(
            status_code=422,
            detail="The tool must belong to an institute before it can be edited.",
        )

    fields_set = body.model_fields_set
    if "kind" in fields_set and body.kind is None:
        raise HTTPException(status_code=422, detail="Tool kind cannot be cleared.")
    if "code" in fields_set and body.code is None:
        raise HTTPException(status_code=422, detail="Tool code cannot be cleared.")
    if "compatible_types" in fields_set and body.compatible_types is None:
        raise HTTPException(
            status_code=422,
            detail="Tool compatible_types must be a list; use [] to clear it.",
        )
    values = _normalized_tool_values(
        kind=body.kind if "kind" in fields_set else tool.kind,
        code=body.code if "code" in fields_set else tool.code,
        label=body.label if "label" in fields_set else tool.label,
        rfid=body.rfid if "rfid" in fields_set else tool.rfid,
        compatible_types=(
            body.compatible_types
            if "compatible_types" in fields_set
            else list(tool.compatible_types or [])
        ),
    )
    _ensure_tool_identifiers_available(
        db,
        institute_id=target_institute_id,
        code=values["code"],
        rfid=values["rfid"],
        exclude_id=tool.id,
    )
    changed_fields: list[str] = []
    for field, value in values.items():
        if value != getattr(tool, field):
            setattr(tool, field, value)
            changed_fields.append(field)
    if body.status is not None and body.status != tool.status:
        tool.status = body.status
        changed_fields.append("status")
    if tool.institute_id is None:
        tool.institute_id = target_institute_id
        changed_fields.append("institute_id")
    if changed_fields:
        db.add(
            AuditEvent(
                actor=user.email,
                user_id=user.id,
                action="tool.updated",
                subject=f"tool:{tool.id}",
                detail={
                    "changed_fields": sorted(changed_fields),
                    "status": tool.status,
                },
            )
        )
    db.commit()
    db.refresh(tool)
    return tool


@router.delete("/api/tools/{tool_id}", status_code=204, tags=["tools"])
def delete_tool(
    tool_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> Response:
    tool = db.get(Tool, tool_id)
    if tool is None:
        raise HTTPException(status_code=404, detail=f"Tool {tool_id} not found.")
    institute = db.get(InstituteProfile, tool.institute_id) if tool.institute_id else None
    if institute is not None:
        _require_institute_scope(user, institute)
    db.add(
        AuditEvent(
            actor=user.email,
            user_id=user.id,
            action="tool.deleted",
            subject=f"tool:{tool.id}",
            detail={
                "institute": institute.code if institute is not None else None,
                "kind": tool.kind,
                "code": tool.code,
            },
        )
    )
    db.delete(tool)
    db.commit()
    return Response(status_code=204)


def _tool_institute(
    db: Session,
    user: User,
    requested_code: str | None,
) -> InstituteProfile:
    if requested_code is not None:
        institute = db.scalar(
            select(InstituteProfile).where(
                func.lower(InstituteProfile.code) == requested_code.strip().lower()
            )
        )
        if institute is None:
            raise HTTPException(
                status_code=404,
                detail=f"Institute '{requested_code}' not found.",
            )
        _require_institute_scope(user, institute)
        return institute
    if user.institute_id is None:
        raise HTTPException(
            status_code=422,
            detail="Select an institute for the new tool.",
        )
    institute = db.get(InstituteProfile, user.institute_id)
    if institute is None:
        raise HTTPException(status_code=422, detail="The user's institute is unavailable.")
    return institute


def _normalized_tool_values(
    *,
    kind: str,
    code: str,
    label: str | None,
    rfid: str | None,
    compatible_types: list[str],
) -> dict[str, object]:
    normalized_kind = kind.strip().lower()
    normalized_code = code.strip()
    normalized_label = label.strip() if isinstance(label, str) else None
    normalized_rfid = rfid.strip() if isinstance(rfid, str) else None
    if not normalized_kind or not normalized_code:
        raise HTTPException(status_code=422, detail="Tool kind and code are required.")
    normalized_types: list[str] = []
    for raw in compatible_types:
        if not isinstance(raw, str):
            raise HTTPException(
                status_code=422,
                detail="Compatible component types must be strings.",
            )
        value = raw.strip().upper()
        if not value:
            continue
        if len(value) > 32:
            raise HTTPException(
                status_code=422,
                detail="Compatible component types must be at most 32 characters.",
            )
        if value not in normalized_types:
            normalized_types.append(value)
    if len(normalized_types) > 100:
        raise HTTPException(status_code=422, detail="A tool may list at most 100 types.")
    return {
        "kind": normalized_kind,
        "code": normalized_code,
        "label": normalized_label or None,
        "rfid": normalized_rfid or None,
        "compatible_types": normalized_types,
    }


def _ensure_tool_identifiers_available(
    db: Session,
    *,
    institute_id: int,
    code: str,
    rfid: str | None,
    exclude_id: int | None = None,
) -> None:
    stmt = select(Tool).where(
        Tool.institute_id == institute_id,
        func.lower(Tool.code) == code.lower(),
    )
    if exclude_id is not None:
        stmt = stmt.where(Tool.id != exclude_id)
    if db.scalar(stmt) is not None:
        raise HTTPException(status_code=409, detail=f"Tool code '{code}' already exists.")
    if rfid is None:
        return
    stmt = select(Tool).where(
        Tool.institute_id == institute_id,
        func.lower(Tool.rfid) == rfid.lower(),
    )
    if exclude_id is not None:
        stmt = stmt.where(Tool.id != exclude_id)
    if db.scalar(stmt) is not None:
        raise HTTPException(status_code=409, detail=f"Tool RFID '{rfid}' already exists.")


# --------------------------------------------------------------------------
# Scanner-first assembly wizard.  Preview is local; staging creates an outbox
# intent only.  No route in this section opens a PDB client.
# --------------------------------------------------------------------------


@router.get("/api/assembly/scan-component", response_model=ComponentOut, tags=["assembly"])
def scan_assembly_component(
    code: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> Component:
    needle = code.strip()
    if not needle:
        raise HTTPException(status_code=422, detail="Empty scan value.")
    matches = list(
        db.scalars(
            select(Component)
            .where(
                or_(
                    func.lower(Component.sn) == needle.lower(),
                    func.lower(Component.local_name) == needle.lower(),
                )
            )
            .order_by(Component.id)
            .limit(2)
        )
    )
    if not matches:
        raise HTTPException(status_code=404, detail=f"No component matches scan '{code}'.")
    if len(matches) > 1:
        raise HTTPException(
            status_code=409,
            detail="The scanned local name is ambiguous; scan the PDB serial number.",
        )
    component = matches[0]
    if user.institute is not None and component.institute_code != user.institute.code:
        raise HTTPException(
            status_code=403,
            detail="You can only assemble components for your own institute.",
        )
    return component


@router.post(
    "/api/assembly/preview",
    response_model=AssemblyPreviewOut,
    tags=["assembly"],
)
def preview_assembly(
    body: AssemblyDraftIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    evaluation = evaluate_assembly(
        db,
        request.app.state.settings,
        parent_sn=body.parent_sn,
        child_sn=body.child_sn,
        slot=body.slot,
        tool_id=body.tool_id,
        tools=body.tools,
        glue_batch_id=body.glue_batch_id,
    )
    if evaluation.institute is not None:
        _require_institute_scope(user, evaluation.institute)
    return evaluation.as_dict()


@router.post(
    "/api/assembly/actions",
    response_model=AssemblyStageOut,
    status_code=201,
    tags=["assembly"],
)
def stage_assembly(
    body: AssemblyDraftIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_operator),
) -> dict:
    evaluation = evaluate_assembly(
        db,
        request.app.state.settings,
        parent_sn=body.parent_sn,
        child_sn=body.child_sn,
        slot=body.slot,
        tool_id=body.tool_id,
        tools=body.tools,
        glue_batch_id=body.glue_batch_id,
    )
    if evaluation.institute is not None:
        _require_institute_scope(user, evaluation.institute)
    if not evaluation.valid:
        detail = "; ".join(issue.message for issue in evaluation.issues)
        raise HTTPException(status_code=409, detail=f"Assembly dry-run blocked: {detail}")
    if evaluation.institute is None:
        raise HTTPException(
            status_code=409,
            detail="Assembly dry-run blocked: parent institute is not configured.",
        )
    payload = canonical_action_payload(evaluation)
    action = OutboxAction(
        institute_id=evaluation.institute.id,
        kind=ASSEMBLY_ACTION_KIND,
        payload=payload,
        status=OutboxStatus.DRAFT.value,
        created_by=user.email,
        user_id=user.id,
    )
    db.add(action)
    db.flush()
    db.add(
        AuditEvent(
            actor=user.email,
            user_id=user.id,
            action="outbox.created",
            subject=f"outbox:{action.id}",
            detail={
                "kind": ASSEMBLY_ACTION_KIND,
                "institute": evaluation.institute.code,
                "parent_sn": evaluation.parent.sn if evaluation.parent is not None else None,
                "child_sn": evaluation.child.sn if evaluation.child is not None else None,
                "tool_code": evaluation.tool.code if evaluation.tool is not None else None,
                "glue_batch": (
                    evaluation.glue_batch.batch_no
                    if evaluation.glue_batch is not None
                    else None
                ),
                "dry_run": "passed",
                "submittable": evaluation.submittable,
            },
            outbox_action_id=action.id,
        )
    )
    db.commit()
    db.refresh(action)
    return {"preview": evaluation.as_dict(), "action": action}


# --------------------------------------------------------------------------
# Glue batches (Phase 4, docs/11). Reads open; writes require operator/admin.
# --------------------------------------------------------------------------


def _default_pot_life_minutes(institute: InstituteProfile | None, glue_type: str) -> int | None:
    """Per-type pot-life default from the institute profile — never from code."""
    if institute is None:
        return None
    raw = (institute.settings or {}).get("glue_pot_life_minutes")
    if not isinstance(raw, dict):
        return None
    value = raw.get(glue_type)
    if isinstance(value, (int, float)) and value > 0:
        return int(value)
    return None


def _glue_batch_out(batch: GlueBatch, usage_count: int) -> GlueBatchOut:
    out = GlueBatchOut.model_validate(batch)
    out.usage_count = usage_count
    state = pot_life_state(batch.mixed_at, batch.pot_life_minutes)
    if state is not None:
        out.pot_life_remaining_seconds = state.remaining_seconds
        out.pot_life_expired = state.expired
    return out


def _glue_usage_counts(db: Session, batch_ids: list[int]) -> dict[int, int]:
    if not batch_ids:
        return {}
    rows = db.execute(
        select(GlueUsage.glue_batch_id, func.count())
        .where(GlueUsage.glue_batch_id.in_(batch_ids))
        .group_by(GlueUsage.glue_batch_id)
    )
    return {batch_id: count for batch_id, count in rows}


def _require_glue_batch_scope(db: Session, user: User, batch: GlueBatch) -> None:
    """Keep every glue mutation inside the signed-in user's institute.

    Legacy institute-less rows remain manageable by an unbound administrator,
    but an institute-bound operator may never claim or mutate them implicitly.
    """

    if batch.institute_id is None:
        if user.institute_id is not None:
            raise HTTPException(
                status_code=403,
                detail="You can only modify data for your own institute.",
            )
        return
    institute = db.get(InstituteProfile, batch.institute_id)
    if institute is None:
        raise HTTPException(status_code=409, detail="The glue batch has no valid institute.")
    _require_institute_scope(user, institute)


@router.get("/api/glue-batches", response_model=list[GlueBatchOut], tags=["glue"])
def list_glue_batches(
    status: str | None = None,
    glue_type: str | None = None,
    q: str | None = None,
    institute: str | None = None,
    db: Session = Depends(get_db),
) -> list[GlueBatchOut]:
    stmt = select(GlueBatch).order_by(GlueBatch.status, GlueBatch.glue_type, GlueBatch.batch_no)
    if status:
        stmt = stmt.where(GlueBatch.status == status)
    if glue_type:
        stmt = stmt.where(GlueBatch.glue_type == glue_type)
    if q:
        needle = f"%{q.strip().lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(GlueBatch.batch_no).like(needle),
                func.lower(GlueBatch.pdb_sn).like(needle),
                func.lower(GlueBatch.glue_type).like(needle),
            )
        )
    if institute:
        profile = db.scalar(
            select(InstituteProfile).where(
                func.lower(InstituteProfile.code) == institute.strip().lower()
            )
        )
        if profile is None:
            return []
        stmt = stmt.where(GlueBatch.institute_id == profile.id)
    batches = list(db.scalars(stmt))
    counts = _glue_usage_counts(db, [batch.id for batch in batches])
    return [_glue_batch_out(batch, counts.get(batch.id, 0)) for batch in batches]


@router.get("/api/glue-batches/scan", response_model=GlueBatchOut, tags=["glue"])
def scan_glue_batch(
    code: str,
    institute: str | None = None,
    db: Session = Depends(get_db),
) -> GlueBatchOut:
    """Resolve a scanned value to a batch by PDB serial or batch number,
    case-insensitively (scanner-first, same contract as the tool scan)."""
    needle = code.strip()
    if needle == "":
        raise HTTPException(status_code=422, detail="Empty scan value.")
    stmt = select(GlueBatch).where(
        or_(
            func.lower(GlueBatch.pdb_sn) == needle.lower(),
            func.lower(GlueBatch.batch_no) == needle.lower(),
        )
    )
    if institute:
        stmt = stmt.join(InstituteProfile).where(
            func.lower(InstituteProfile.code) == institute.strip().lower()
        )
    batch = db.scalar(stmt)
    if batch is None:
        raise HTTPException(status_code=404, detail=f"No glue batch matches scan '{code}'.")
    counts = _glue_usage_counts(db, [batch.id])
    return _glue_batch_out(batch, counts.get(batch.id, 0))


@router.post("/api/glue-batches", response_model=GlueBatchOut, status_code=201, tags=["glue"])
def create_glue_batch(
    body: GlueBatchCreate, db: Session = Depends(get_db), user: User = Depends(require_operator)
) -> GlueBatchOut:
    batch = GlueBatch(
        glue_type=body.glue_type,
        batch_no=body.batch_no,
        pdb_sn=body.pdb_sn,
        status=body.status,
        manufacturing_date=body.manufacturing_date,
        expiry_date=body.expiry_date,
        opening_date=body.opening_date,
        bipack_count=body.bipack_count,
        note=body.note,
        institute_id=user.institute_id,
    )
    db.add(batch)
    db.flush()
    db.add(
        AuditEvent(
            actor=user.email,
            user_id=user.id,
            action="glue_batch.created",
            subject=f"glue_batch:{batch.id}",
            detail={"glue_type": batch.glue_type, "batch_no": batch.batch_no},
        )
    )
    db.commit()
    db.refresh(batch)
    return _glue_batch_out(batch, 0)


@router.patch("/api/glue-batches/{batch_id}", response_model=GlueBatchOut, tags=["glue"])
def update_glue_batch(
    batch_id: int,
    body: GlueBatchUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_operator),
) -> GlueBatchOut:
    batch = db.get(GlueBatch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail=f"Glue batch {batch_id} not found.")
    _require_glue_batch_scope(db, user, batch)
    changed: dict[str, object] = {}
    for field in (
        "batch_no",
        "pdb_sn",
        "status",
        "manufacturing_date",
        "expiry_date",
        "opening_date",
        "bipack_count",
        "note",
    ):
        value = getattr(body, field)
        if value is not None and value != getattr(batch, field):
            setattr(batch, field, value)
            changed[field] = str(value)
    if changed:
        db.add(
            AuditEvent(
                actor=user.email,
                user_id=user.id,
                action="glue_batch.updated",
                subject=f"glue_batch:{batch.id}",
                detail={"changed": changed},
            )
        )
    db.commit()
    db.refresh(batch)
    counts = _glue_usage_counts(db, [batch.id])
    return _glue_batch_out(batch, counts.get(batch.id, 0))


@router.post("/api/glue-batches/{batch_id}/mix", response_model=GlueBatchOut, tags=["glue"])
def mix_glue_batch(
    batch_id: int,
    body: GlueBatchMixIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_operator),
) -> GlueBatchOut:
    """Start the pot-life timer: the batch was just mixed at the bench.

    The pot life comes from the request, else from the institute profile's
    `glue_pot_life_minutes[glue_type]`; without either the batch is marked
    mixed but untimed (expiry warnings then rely on `expiry_date` alone)."""
    batch = db.get(GlueBatch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail=f"Glue batch {batch_id} not found.")
    _require_glue_batch_scope(db, user, batch)
    if batch.status in ("expired", "empty"):
        raise HTTPException(
            status_code=409, detail=f"Glue batch {batch_id} is {batch.status} — mix a fresh one."
        )
    institute = db.get(InstituteProfile, batch.institute_id) if batch.institute_id else None
    batch.mixed_at = utcnow()
    batch.pot_life_minutes = body.pot_life_minutes or _default_pot_life_minutes(
        institute, batch.glue_type
    )
    if batch.status == "new":
        batch.status = "in_use"
    if batch.opening_date is None:
        batch.opening_date = batch.mixed_at
    db.add(
        AuditEvent(
            actor=user.email,
            user_id=user.id,
            action="glue_batch.mixed",
            subject=f"glue_batch:{batch.id}",
            detail={
                "glue_type": batch.glue_type,
                "batch_no": batch.batch_no,
                "pot_life_minutes": batch.pot_life_minutes,
            },
        )
    )
    db.commit()
    db.refresh(batch)
    counts = _glue_usage_counts(db, [batch.id])
    return _glue_batch_out(batch, counts.get(batch.id, 0))


@router.get(
    "/api/glue-batches/{batch_id}/usage", response_model=list[GlueUsageOut], tags=["glue"]
)
def list_glue_usage(batch_id: int, db: Session = Depends(get_db)) -> list[GlueUsage]:
    if db.get(GlueBatch, batch_id) is None:
        raise HTTPException(status_code=404, detail=f"Glue batch {batch_id} not found.")
    return list(
        db.scalars(
            select(GlueUsage)
            .where(GlueUsage.glue_batch_id == batch_id)
            .order_by(GlueUsage.used_at.desc(), GlueUsage.id.desc())
        )
    )


@router.post(
    "/api/glue-batches/{batch_id}/usage",
    response_model=GlueUsageOut,
    status_code=201,
    tags=["glue"],
)
def record_glue_usage(
    batch_id: int,
    body: GlueUsageCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_operator),
) -> GlueUsage:
    """Record consumption for a component (roadmap: glue data joinable with
    production). The SN is accepted as scanned — the component may not be
    mirrored yet when glue is logged at the bench."""
    batch = db.get(GlueBatch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail=f"Glue batch {batch_id} not found.")
    _require_glue_batch_scope(db, user, batch)
    if batch.status in ("expired", "empty"):
        raise HTTPException(
            status_code=409,
            detail=f"Glue batch {batch_id} is {batch.status} and must not be used.",
        )
    usage = GlueUsage(
        glue_batch_id=batch.id,
        component_sn=body.component_sn.strip(),
        amount_mg=body.amount_mg,
        note=body.note,
        used_by=user.email,
        user_id=user.id,
    )
    if batch.status == "new":
        batch.status = "in_use"
    db.add(usage)
    db.flush()
    db.add(
        AuditEvent(
            actor=user.email,
            user_id=user.id,
            action="glue_batch.usage_recorded",
            subject=f"glue_batch:{batch.id}",
            detail={"component_sn": usage.component_sn, "amount_mg": usage.amount_mg},
        )
    )
    db.commit()
    db.refresh(usage)
    return usage


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
    components = list(db.scalars(stmt))
    from app.production_status import annotate_production_status

    annotate_production_status(db, components)
    return components


# Registered before /api/components/{sn}: FastAPI matches routes in
# registration order, and a literal segment that sits beside a path parameter
# is otherwise swallowed by it.
@router.get(
    "/api/components/thumbnails",
    response_model=dict[str, AttachmentLocatorOut],
    tags=["components"],
)
def component_thumbnails(
    request: Request,
    institute_code: str | None = None,
    limit: int = 2000,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict[str, AttachmentLocatorOut]:
    """Map of serial number to one locally stored image locator.

    One request for a whole list rather than one per row: a grid of a few
    hundred modules would otherwise open a few hundred connections just to
    discover that most have no picture.

    Only attachments whose bytes are on disk and whose MIME type browsers can
    paint are returned, so the caller can render every entry it receives
    without a fallback state. Stored TIFFs remain truthful gallery
    placeholders but never become broken list thumbnails.

    `limit` bounds *components*, which is what a caller asking for a list of
    components means by it. The helper unites authoritative associations with
    legacy blob-row ownership, groups that candidate set and applies the limit
    in SQL before rows reach Python. Repeated run associations therefore
    cannot turn the bounded endpoint into an unbounded read. If the selected
    blob has meanwhile disappeared from disk, the component simply has no tile
    this time."""
    from app.attachment_store import resolve_path, thumbnail_attachments

    settings = request.app.state.settings
    thumbnails: dict[str, AttachmentLocatorOut] = {}
    for component_sn, row, part in thumbnail_attachments(
        db, institute_code=institute_code, limit=limit
    ):
        if resolve_path(settings, row) is None:
            continue
        thumbnails[component_sn] = AttachmentLocatorOut(
            source=row.source,
            code=row.pdb_code,
            # The bytes live under the part's serial when the tile is borrowed;
            # calling the binary route with the listed component would 404.
            sn=part.sn if part is not None else component_sn,
            part=(
                ThumbnailPartOut(
                    sn=part.sn,
                    component_type=part.component_type,
                    type_code=part.type_code,
                    local_name=part.local_name,
                )
                if part is not None
                else None
            ),
        )
    return thumbnails


@router.get("/api/components/{sn}", response_model=ComponentDetailOut, tags=["components"])
def get_component(sn: str, db: Session = Depends(get_db)) -> Component:
    component = db.scalar(
        select(Component)
        .options(selectinload(Component.parent), selectinload(Component.children))
        .where(Component.sn == sn)
    )
    if component is None:
        raise HTTPException(status_code=404, detail=f"Component '{sn}' not found.")
    from app.production_status import annotate_production_status

    annotate_production_status(db, [component, *component.children])
    return component


@router.get(
    "/api/components/{sn}/preview",
    response_model=ComponentPreviewOut,
    tags=["components", "outbox"],
)
def component_preview(
    sn: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> ComponentPreviewOut:
    """Project staged work over the local mirror without contacting the PDB.

    Intentionally light: `projected.ghost_tests` holds only staged, not-yet-
    pushed uploads. Mirrored runs appear here as worksheet summaries; their raw
    values are served by `GET /api/components/{sn}/tests`, which the module page
    calls only when the operator opens the full run list.
    """
    from app.preview import build_component_preview

    component = db.scalar(select(Component).where(Component.sn == sn))
    if component is None:
        raise HTTPException(status_code=404, detail=f"Component '{sn}' not found.")
    return ComponentPreviewOut.model_validate(
        build_component_preview(db, component, request.app.state.settings)
    )


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


@router.get(
    "/api/sync/jobs/active",
    response_model=SyncJobOut,
    responses={204: {"description": "No component sync is active."}},
    tags=["components", "sync"],
)
def active_sync_job(
    kind: Literal["components", "evidence"] = COMPONENT_SYNC_KIND,
    institute_code: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> SyncJobOut | Response:
    """Discover a live job after navigation, refresh or another tab."""

    statement = select(SyncJob).where(
        SyncJob.kind == kind,
        SyncJob.status.in_(ACTIVE_SYNC_STATUSES),
    )
    if institute_code is not None:
        statement = statement.where(SyncJob.institute_code == institute_code)
    job = db.scalar(
        statement.order_by(
            (SyncJob.status == "running").desc(),
            SyncJob.updated_at.desc(),
            SyncJob.id.desc(),
        )
    )
    return _sync_job_out(job) if job is not None else Response(status_code=204)


@router.get(
    "/api/sync/jobs/latest",
    response_model=SyncJobOut,
    responses={204: {"description": "No matching sync job exists."}},
    tags=["components", "sync"],
)
def latest_sync_job(
    kind: Literal["components", "evidence"] = COMPONENT_SYNC_KIND,
    institute_code: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> SyncJobOut | Response:
    """Recover the newest persisted job, including terminal success/errors."""

    statement = select(SyncJob).where(SyncJob.kind == kind)
    if institute_code is not None:
        statement = statement.where(SyncJob.institute_code == institute_code)
    job = db.scalar(statement.order_by(SyncJob.id.desc()))
    return _sync_job_out(job) if job is not None else Response(status_code=204)


@router.get(
    "/api/sync/jobs/{job_id}",
    response_model=SyncJobOut,
    tags=["components", "sync"],
)
def get_sync_job(
    job_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> SyncJobOut:
    job = db.get(SyncJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Sync job '{job_id}' not found.")
    return _sync_job_out(job)


@router.post(
    "/api/sync/jobs/components/{institute_code}",
    response_model=SyncJobOut,
    status_code=202,
    tags=["components", "sync"],
)
def start_component_sync_job(
    institute_code: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_operator),
) -> SyncJobOut:
    """Start a pollable sync, or converge on the already-active global job."""

    institute = db.scalar(
        select(InstituteProfile).where(InstituteProfile.code == institute_code)
    )
    if institute is None:
        raise HTTPException(status_code=404, detail=f"Institute '{institute_code}' not found.")
    _require_institute_scope(user, institute)

    # Fail before acquiring the global lease. The worker resolves this same
    # user's codes again in its own short-lived session; no secret enters the
    # durable job row or executor queue.
    _load_personal_pdb_access(request, db, user)

    try:
        lease = acquire_component_sync_lease(
            db,
            institute_code=institute.code,
            requested_by=user.email,
            user_id=user.id,
        )
    except SyncLeaseBusy as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not lease.created:
        return _sync_job_out(lease.job)

    try:
        request.app.state.sync_job_manager.start(
            lease.job.id,
            request.app.state.component_fetcher,
            follow_with_evidence=False,
        )
    except Exception as exc:
        fail_sync_job(request.app.state.session_factory, lease.job.id, exc)
        raise HTTPException(status_code=503, detail="Could not schedule component sync.") from exc
    return _sync_job_out(lease.job)


@router.post(
    "/api/sync/jobs/evidence/{institute_code}",
    response_model=SyncJobOut,
    status_code=202,
    tags=["components", "sync"],
)
def start_evidence_sync_job(
    institute_code: str,
    request: Request,
    mode: Literal["standard", "lightweight"] = Query(default="standard"),
    db: Session = Depends(get_db),
    user: User = Depends(require_operator),
) -> SyncJobOut:
    """Start the detailed evidence/attachment mirror, or return its live job."""

    institute = db.scalar(
        select(InstituteProfile).where(InstituteProfile.code == institute_code)
    )
    if institute is None:
        raise HTTPException(status_code=404, detail=f"Institute '{institute_code}' not found.")
    _require_institute_scope(user, institute)
    _load_personal_pdb_access(request, db, user)
    try:
        lease = acquire_evidence_sync_lease(
            db,
            institute_code=institute.code,
            requested_by=user.email,
            user_id=user.id,
            sync_mode=mode,
        )
    except EvidenceSyncModeConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SyncLeaseBusy as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not lease.created:
        return _sync_job_out(lease.job)
    try:
        request.app.state.sync_job_manager.start_evidence(lease.job.id)
    except Exception as exc:
        fail_sync_job(request.app.state.session_factory, lease.job.id, exc)
        raise HTTPException(status_code=503, detail="Could not schedule evidence sync.") from exc
    return _sync_job_out(lease.job)


@router.post(
    "/api/sync/components/{institute_code}",
    response_model=ComponentSyncOut,
    tags=["components", "sync"],
)
def sync_components_for_institute(
    institute_code: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_operator),
) -> ComponentSyncOut:
    institute = db.scalar(select(InstituteProfile).where(InstituteProfile.code == institute_code))
    if institute is None:
        raise HTTPException(status_code=404, detail=f"Institute '{institute_code}' not found.")
    _require_institute_scope(user, institute)

    access_codes = _load_personal_pdb_access(request, db, user)

    try:
        lease = acquire_component_sync_lease(
            db,
            institute_code=institute.code,
            requested_by=user.email,
            user_id=user.id,
            initial_status="running",
        )
    except SyncLeaseBusy as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not lease.created:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Component sync job '{lease.job.id}' for institute "
                f"'{lease.job.institute_code}' is already active."
            ),
        )

    job_id = lease.job.id
    try:
        result = run_inline_component_sync(
            request.app.state.session_factory,
            request.app.state.settings,
            request.app.state.component_fetcher,
            job_id,
            access_codes,
        )
    except SyncLeaseLost:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="The component sync lease was replaced; its results were discarded.",
        ) from None
    except PdbSyncUnavailable as exc:
        db.rollback()
        fail_sync_job(request.app.state.session_factory, job_id, exc)
        raise HTTPException(status_code=503, detail=str(exc)) from None
    except UnknownParentError as exc:
        db.rollback()
        fail_sync_job(request.app.state.session_factory, job_id, exc)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        db.rollback()
        fail_sync_job(request.app.state.session_factory, job_id, exc)
        raise

    return ComponentSyncOut(**result)


@router.post(
    "/api/sync/tools/{institute_code}",
    response_model=ToolSyncOut,
    tags=["tools", "sync"],
)
def sync_tools_for_institute(
    institute_code: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_operator),
) -> ToolSyncOut:
    """Rebuild the local tool registry from already mirrored PDB tool components."""

    institute = db.scalar(select(InstituteProfile).where(InstituteProfile.code == institute_code))
    if institute is None:
        raise HTTPException(status_code=404, detail=f"Institute '{institute_code}' not found.")
    _require_institute_scope(user, institute)

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


@router.get(
    "/api/stats/measurements/dimensions",
    response_model=MeasurementDimensionsOut,
    tags=["stats"],
)
def stats_measurement_dimensions(
    institute: str | None = None, db: Session = Depends(get_db)
) -> MeasurementDimensionsOut:
    """Test types and result codes present in the mirrored evidence.

    Discovered from the data (hard rule #4: which codes exist is never
    hardcoded); the UI builds its measurement pickers from this.
    """
    return MeasurementDimensionsOut(
        test_types=measurement_dimensions(db, institute_code=institute)
    )


@router.get("/api/stats/measurements", response_model=MeasurementSeriesOut, tags=["stats"])
def stats_measurements(
    test_type: str,
    result: str,
    x_result: str | None = None,
    institute: str | None = None,
    limit: int = Query(default=300, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> MeasurementSeriesOut:
    """One measurement series across the institute's mirrored runs.

    Array results become overlaid curves (all IV curves in one chart, paired
    against `x_result` when its array length matches); scalar results become a
    distribution with summary statistics. Newest runs first, capped by `limit`.
    """
    series = measurement_series(
        db,
        test_type=test_type,
        result_code=result,
        x_result=x_result,
        institute_code=institute,
        limit=limit,
    )
    return MeasurementSeriesOut(
        test_type=series.test_type,
        result_code=series.result_code,
        kind=series.kind,
        result_name=series.result_name,
        x_result=series.x_result,
        x_name=series.x_name,
        curves=[vars(curve) for curve in series.curves],
        values=[vars(value) for value in series.values],
        summary=series.summary,
        truncated=series.truncated,
    )


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


@router.get(
    "/api/stats/required-tests",
    response_model=RequiredTestStatsOut,
    tags=["stats"],
)
def get_required_test_stats(
    institute: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> RequiredTestStatsOut:
    """Confirmed REQUIRED-test coverage from the local mirror only.

    Institute-bound viewers read their own profile by default. An unbound user
    may omit the query only when exactly one institute profile exists; with
    several profiles the scope must be explicit because each has its own stage
    model. No PDB client is constructed by this route.
    """
    code = institute.strip().upper() if institute is not None else None
    if not code and user.institute is not None:
        code = user.institute.code
    if not code:
        profiles = list(
            db.scalars(select(InstituteProfile).order_by(InstituteProfile.code).limit(2))
        )
        if len(profiles) != 1:
            raise HTTPException(
                status_code=422,
                detail="institute is required when more than one profile is configured.",
            )
        profile = profiles[0]
    else:
        profile = db.scalar(select(InstituteProfile).where(InstituteProfile.code == code))
        if profile is None:
            raise HTTPException(status_code=404, detail=f"Institute '{code}' not found.")
    if user.institute_id is not None and user.institute_id != profile.id:
        raise HTTPException(
            status_code=403,
            detail="You can only read REQUIRED-test statistics for your own institute.",
        )

    stats = required_test_stats(db, profile)
    return RequiredTestStatsOut(
        institute=stats.institute,
        denominator="at_or_beyond_stage",
        stage_order=stats.stage_order,
        rows=[vars(row) for row in stats.rows],
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
        worker_owned_targets=[OutboxStatus.CONFIRMED.value, OutboxStatus.FAILED.value],
    )


@router.get("/api/outbox", response_model=list[OutboxOut], tags=["outbox"])
def list_outbox(
    status: OutboxStatus | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> list[OutboxAction]:
    stmt = select(OutboxAction).order_by(OutboxAction.created_at.desc())
    if status is not None:
        stmt = stmt.where(OutboxAction.status == status.value)
    return list(db.scalars(stmt))


@router.get("/api/outbox/{action_id}", response_model=OutboxOut, tags=["outbox"])
def get_outbox_action(
    action_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> OutboxAction:
    action = db.get(OutboxAction, action_id)
    if action is None:
        raise HTTPException(status_code=404, detail=f"Outbox action {action_id} not found.")
    return action


@router.post(
    "/api/components/register", response_model=OutboxOut, status_code=201, tags=["components"]
)
def register_component_draft(
    body: ComponentRegisterIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_operator),
) -> OutboxAction:
    """Queue a DUMMY component registration as a reviewed outbox draft (docs/10).

    Registration is the only component-creating PDB write itkFlow does, so the
    type allowlist is enforced up front here (MODULE/HYBRID only) and again at
    submit time by `register_dummy_component`. Nothing is written to the PDB
    until the draft is approved and the worker runs with access codes.
    """
    settings = request.app.state.settings
    if not is_registrable_type(body.component_type, settings):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Refusing to register component type '{body.component_type}': only "
                f"{settings.pdb_dummy_component_types} may be registered as DUMMY test parts. "
                "Sensors and ASICs must never be registered by itkFlow."
            ),
        )
    institute = db.scalar(
        select(InstituteProfile).where(InstituteProfile.code == body.institute_code)
    )
    if institute is None:
        raise HTTPException(status_code=404, detail=f"Institute '{body.institute_code}' not found.")
    _require_institute_scope(user, institute)
    payload: dict = {
        "component_type": body.component_type,
        "type_code": body.type_code,
        "institute_code": body.institute_code,
        "subproject": body.subproject,
    }
    if body.local_name:
        payload["local_name"] = body.local_name
    action = OutboxAction(
        institute_id=institute.id,
        kind="register_component",
        payload=payload,
        status=OutboxStatus.DRAFT.value,
        created_by=user.email,
        user_id=user.id,
    )
    db.add(action)
    db.flush()
    db.add(
        AuditEvent(
            actor=user.email,
            user_id=user.id,
            action="outbox.created",
            subject=f"outbox:{action.id}",
            detail={
                "kind": "register_component",
                "institute": institute.code,
                "component_type": body.component_type,
            },
            outbox_action_id=action.id,
        )
    )
    db.commit()
    db.refresh(action)
    return action


@router.post("/api/outbox", response_model=OutboxOut, status_code=201, tags=["outbox"])
def create_outbox_action(
    body: OutboxCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_operator),
) -> OutboxAction:
    institute = db.scalar(
        select(InstituteProfile).where(InstituteProfile.code == body.institute_code)
    )
    if institute is None:
        raise HTTPException(status_code=404, detail=f"Institute '{body.institute_code}' not found.")
    _require_institute_scope(user, institute)
    action = OutboxAction(
        institute_id=institute.id,
        kind=body.kind,
        payload=body.payload,
        status=OutboxStatus.DRAFT.value,
        created_by=user.email,
        user_id=user.id,
    )
    db.add(action)
    db.flush()
    db.add(
        AuditEvent(
            actor=user.email,
            user_id=user.id,
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
    action_id: int,
    body: OutboxTransition,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_operator),
) -> OutboxAction:
    action = db.get(OutboxAction, action_id)
    if action is None:
        raise HTTPException(status_code=404, detail=f"Outbox action {action_id} not found.")
    if user.institute_id is not None and user.institute_id != action.institute_id:
        raise HTTPException(
            status_code=403,
            detail="You can only modify PDB actions for your own institute.",
        )
    current = OutboxStatus(action.status)
    try:
        assert_transition(current, body.to)
    except InvalidTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if body.to in {OutboxStatus.CONFIRMED, OutboxStatus.FAILED}:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Status '{body.to.value}' is worker-owned and cannot be set "
                "through the operator API."
            ),
        )

    if body.to is OutboxStatus.APPROVED:
        # Decryption here proves that the bound identity is usable by this
        # deployment. The codes themselves are discarded; the worker reloads
        # them for this exact user when it later submits or retries.
        _load_personal_pdb_access(request, db, user)
        credential = db.get(PdbCredential, user.id)
        if credential is None:  # guarded above; defensive against future refactors
            raise HTTPException(status_code=409, detail="Personal PDB connection required.")
        principal = db.get(OutboxPdbPrincipal, action.id)
        if principal is not None and (
            principal.user_id != user.id
            or principal.pdb_identity != credential.pdb_identity
        ):
            raise HTTPException(
                status_code=409,
                detail="This action is already bound to a different PDB identity.",
            )
        if principal is None:
            db.add(
                OutboxPdbPrincipal(
                    outbox_action_id=action.id,
                    user_id=user.id,
                    pdb_identity=credential.pdb_identity,
                )
            )

    action.status = body.to.value
    if body.to is OutboxStatus.SUBMITTED:
        action.attempts += 1
        action.error = None
    if body.to is OutboxStatus.FAILED:
        action.error = body.error or "Unknown error."

    db.add(
        AuditEvent(
            actor=user.email,
            user_id=user.id,
            action="outbox.transition",
            subject=f"outbox:{action.id}",
            detail={
                "from": current.value,
                "to": body.to.value,
                "error": body.error,
                **(
                    {"pdb_principal_user_id": user.id}
                    if body.to is OutboxStatus.APPROVED
                    else {}
                ),
            },
            outbox_action_id=action.id,
        )
    )
    db.commit()
    db.refresh(action)
    return action


# --------------------------------------------------------------------------
# Test-type schema mirror (read-only PDB catalogue for manual-entry forms)
# --------------------------------------------------------------------------


@router.get(
    "/api/test-types",
    response_model=list[TestTypeSchemaOut],
    tags=["ingestion"],
)
def list_test_type_schemas(
    component_type: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> list[TestTypeSchemaOut]:
    del user
    normalized = component_type.strip()
    if not normalized or len(normalized) > 32:
        raise HTTPException(status_code=422, detail="A valid component_type is required.")
    rows = db.scalars(
        select(TestTypeSchema)
        .where(TestTypeSchema.component_type == normalized)
        .order_by(TestTypeSchema.name, TestTypeSchema.test_code)
    )
    return [
        TestTypeSchemaOut(
            id=row.id,
            component_type=row.component_type,
            test_code=row.test_code,
            name=row.name,
            schema=row.schema_data,
            synced_at=row.synced_at,
        )
        for row in rows
    ]


@router.post(
    "/api/test-types/sync",
    response_model=TestTypeSchemaSyncOut,
    tags=["ingestion"],
)
def sync_test_type_schemas(
    component_type: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_operator),
) -> TestTypeSchemaSyncOut:
    from app.pdb_test_types import (
        DEFAULT_PDB_PROJECT,
        PdbTestTypesUnavailable,
        fetch_test_type_schemas,
    )
    from app.test_type_schemas import upsert_test_type_schemas

    normalized = component_type.strip()
    if not normalized or len(normalized) > 32:
        raise HTTPException(status_code=422, detail="A valid component_type is required.")

    profile = db.get(InstituteProfile, user.institute_id) if user.institute_id else None
    configured_project = (profile.settings or {}).get("pdb_project") if profile else None
    project = (
        configured_project.strip()
        if isinstance(configured_project, str) and configured_project.strip()
        else DEFAULT_PDB_PROJECT
    )
    fetcher = getattr(request.app.state, "test_type_schema_fetcher", fetch_test_type_schemas)
    try:
        records = fetcher(
            _pdb_gateway(request, db, user),
            normalized,
            project=project,
        )
    except PdbTestTypesUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None

    stats = upsert_test_type_schemas(db, records, component_type=normalized)
    db.commit()
    return TestTypeSchemaSyncOut(
        component_type=normalized,
        created=stats.created,
        updated=stats.updated,
        unchanged=stats.unchanged,
        total=stats.total,
    )


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
def create_ingest_file(
    body: IngestFileCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_operator),
) -> IngestFile:
    raw = canonical_json_bytes(body.payload)
    parsed = parse_payload(body.payload)
    pinned_sn = body.component_sn.strip() if body.component_sn is not None else None
    pinned_test_type = (
        body.test_type.strip().upper() if body.test_type is not None else None
    )
    if body.component_sn is not None and not pinned_sn:
        raise HTTPException(status_code=422, detail="component_sn must not be blank.")
    if body.test_type is not None and not pinned_test_type:
        raise HTTPException(status_code=422, detail="test_type must not be blank.")
    pinned_component = (
        db.scalar(select(Component).where(Component.sn == pinned_sn)) if pinned_sn else None
    )
    if pinned_sn and pinned_component is None:
        raise HTTPException(status_code=404, detail=f"Component '{pinned_sn}' not found.")
    component = pinned_component or resolve_component(db, parsed)
    if component is not None:
        institute = db.scalar(
            select(InstituteProfile).where(
                InstituteProfile.code == component.institute_code
            )
        )
        if institute is None:
            raise HTTPException(
                status_code=409,
                detail=f"Component institute '{component.institute_code}' is not configured.",
            )
        _require_institute_scope(user, institute)
    component_sn = pinned_sn or parsed.component_sn or (
        component.sn if component is not None else None
    )

    notes = list(parsed.issues)
    if pinned_sn and parsed.component_sn and parsed.component_sn != pinned_sn:
        notes.append(
            f"Payload component '{parsed.component_sn}' does not match pinned component "
            f"'{pinned_sn}'"
        )
    parsed_test_type = parsed.test_type.upper() if parsed.test_type is not None else None
    if pinned_test_type and parsed_test_type != pinned_test_type:
        embedded = parsed.test_type if parsed.test_type is not None else "missing"
        notes.append(
            f"Payload test type '{embedded}' does not match pinned test type "
            f"'{pinned_test_type}'"
        )
    if component_sn is None and parsed.local_name is not None:
        notes.append(f"Local name '{parsed.local_name}' does not match any mirrored component")

    ingest = IngestFile(
        filename=body.filename,
        sha256=hashlib.sha256(raw).hexdigest(),
        size_bytes=len(raw),
        status="triage" if notes else "received",
        component_sn=component_sn,
        test_type=pinned_test_type or parsed.test_type,
        parser=body.parser or parsed.parser,
        error="; ".join(notes) if notes else None,
        payload=body.payload,
        uploaded_by=user.email,
    )
    db.add(ingest)
    db.flush()
    db.add(
        AuditEvent(
            actor=user.email,
            user_id=user.id,
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


def _ingest_target_issues(ingest: IngestFile, parsed: ParsedTestRun) -> list[str]:
    """Detect a pinned/assigned target that conflicts with the untouched payload."""
    issues: list[str] = []
    if (
        ingest.component_sn is not None
        and parsed.component_sn is not None
        and ingest.component_sn != parsed.component_sn
    ):
        issues.append(
            f"Payload component '{parsed.component_sn}' does not match pinned component "
            f"'{ingest.component_sn}'"
        )
    if ingest.test_type is not None and (
        parsed.test_type is None
        or ingest.test_type.upper() != parsed.test_type.upper()
    ):
        embedded = parsed.test_type if parsed.test_type is not None else "missing"
        issues.append(
            f"Payload test type '{embedded}' does not match pinned test type "
            f"'{ingest.test_type}'"
        )
    return issues


def _ingest_institute(
    db: Session,
    parsed: ParsedTestRun,
    component: Component | None,
    *,
    institute_code: str | None = None,
) -> InstituteProfile | None:
    """The profile whose rules govern one ingest file.

    The mirrored component owns the answer. For an unmirrored component an
    explicit preview/proposal selection wins, then the institution named by
    the payload is the fallback. Everything institute-specific about an upload
    — required properties, glue targets — resolves through this one lookup.
    """
    resolved_code = (
        component.institute_code
        if component is not None
        else institute_code or parsed.institution
    )
    if resolved_code is None:
        return None
    return db.scalar(select(InstituteProfile).where(InstituteProfile.code == resolved_code))


def _require_matching_unmirrored_institute(
    parsed: ParsedTestRun,
    component: Component | None,
    institute_code: str | None,
) -> None:
    """Do not let an explicit tenant silently reinterpret an unmirrored file."""
    if (
        component is None
        and institute_code is not None
        and parsed.institution is not None
        and institute_code != parsed.institution
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                f"Payload institution '{parsed.institution}' does not match selected "
                f"institute '{institute_code}'."
            ),
        )


def _ingest_derivation(
    ingest: IngestFile,
    parsed: ParsedTestRun,
    component: Component | None,
    profile: InstituteProfile | None,
):
    """Server-side derived values for one ingest file (spec 2026-08-27 §9.3).

    Computed in the dry-run, before anything is staged, so the operator sees
    the verdict while the file can still be rejected — and so the value that is
    uploaded is the value they approved. None where the institute configures no
    derivation for this test type.
    """
    return derive_glue_results(
        ingest.payload,
        profile.settings if profile is not None else None,
        parsed.test_type or ingest.test_type,
        component.type_code if component is not None else None,
        measured_at=parsed.measured_at,
    )


def _required_property_issues(
    ingest: IngestFile,
    parsed: ParsedTestRun,
    profile: InstituteProfile | None,
) -> list[str]:
    """Institute-configured mandatory upload properties (e.g. the used jig) that
    are missing from this ingest file (docs/07). Data-driven and empty by default
    — a no-op until an institute sets `settings['required_properties']`."""
    test_type = parsed.test_type or ingest.test_type
    if test_type is None or profile is None:
        return []
    missing = missing_required_properties(
        ingest.payload.get("properties"), profile.settings, test_type
    )
    if not missing:
        return []
    label = "property" if len(missing) == 1 else "properties"
    return [f"Missing required {label} for {test_type}: {', '.join(missing)}."]


@router.get(
    "/api/ingest/files/{file_id}/preview",
    response_model=IngestPreviewOut,
    tags=["ingestion"],
)
def preview_ingest_file(
    file_id: int,
    institute_code: str | None = None,
    db: Session = Depends(get_db),
) -> IngestPreviewOut:
    """Dry-run parse of a stored payload — no state change, no PDB access."""
    ingest = db.get(IngestFile, file_id)
    if ingest is None:
        raise HTTPException(status_code=404, detail=f"Ingest file {file_id} not found.")

    parsed = parse_payload(ingest.payload)
    component = (
        db.scalar(select(Component).where(Component.sn == ingest.component_sn))
        if ingest.component_sn is not None
        else resolve_component(db, parsed)
    )
    component_sn = ingest.component_sn or parsed.component_sn or (
        component.sn if component is not None else None
    )
    _require_matching_unmirrored_institute(parsed, component, institute_code)
    profile = _ingest_institute(
        db,
        parsed,
        component,
        institute_code=institute_code,
    )
    if component is None and institute_code is not None and profile is None:
        raise HTTPException(
            status_code=404,
            detail=f"Institute '{institute_code}' not found.",
        )
    issues = (
        parsed.issues
        + _ingest_target_issues(ingest, parsed)
        + _required_property_issues(ingest, parsed, profile)
    )
    return IngestPreviewOut(
        file_id=ingest.id,
        parser=ingest.parser or parsed.parser,
        upload_ready=(
            not issues and component_sn is not None and parsed.test_type is not None
        ),
        component_sn=component_sn,
        local_name=parsed.local_name,
        component_mirrored=component is not None,
        component_stage=component.stage if component is not None else None,
        institute_code=profile.code if profile is not None else None,
        test_type=parsed.test_type,
        run_number=parsed.run_number,
        institution=parsed.institution,
        measured_at=parsed.measured_at,
        passed=parsed.passed,
        problems=parsed.problems,
        n_properties=parsed.n_properties,
        results=parsed.results,
        issues=issues,
        warnings=parsed.warnings,
        derived=derivation_payload(_ingest_derivation(ingest, parsed, component, profile)),
    )


@router.post(
    "/api/ingest/files/{file_id}/propose-outbox",
    response_model=OutboxOut,
    status_code=201,
    tags=["ingestion", "outbox"],
)
def propose_ingest_outbox_action(
    file_id: int,
    body: IngestProposalCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_operator),
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
    component = db.scalar(select(Component).where(Component.sn == ingest.component_sn))
    _require_matching_unmirrored_institute(parsed, component, body.institute_code)
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
    _require_institute_scope(user, institute)

    issues = (
        parsed.issues
        + _ingest_target_issues(ingest, parsed)
        + _required_property_issues(ingest, parsed, institute)
    )
    if issues:
        raise HTTPException(
            status_code=409,
            detail=f"Dry-run validation failed: {'; '.join(issues)}.",
        )

    derivation = _ingest_derivation(ingest, parsed, component, institute)

    action = OutboxAction(
        institute_id=institute.id,
        kind="upload_test_run",
        status=OutboxStatus.DRAFT.value,
        created_by=user.email,
        user_id=user.id,
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
            # What the dry-run computed, in the grams the PDB stores. Staged
            # with the action rather than written back into the ingest file, so
            # the uploaded document keeps matching the sha256 it was received
            # under while the write intent still carries the derived values.
            "derived_results": derived_result_grams(derivation),
            # Includes output codes whose value is absent because an input is
            # missing. Those codes are still server-owned and must be removed
            # from raw results rather than allowing a stale formula value to
            # pass through unchanged.
            "derived_result_codes": derived_result_codes(derivation),
            # The complete reviewed server decision is part of the immutable
            # write intent too. The worker recomputes it immediately before
            # submission, so a later target/tolerance change requires a fresh
            # operator review even when the numeric upload values are equal.
            "derived": derivation_payload(derivation),
        },
    )
    db.add(action)
    db.flush()
    ingest.outbox_action_id = action.id
    ingest.status = "proposed"
    ingest.error = None
    db.add(
        AuditEvent(
            actor=user.email,
            user_id=user.id,
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
def list_audit(
    limit: int = 100,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> list[AuditEvent]:
    stmt = (
        select(AuditEvent)
        .order_by(AuditEvent.ts.desc(), AuditEvent.id.desc())
        .limit(min(limit, 500))
    )
    return list(db.scalars(stmt))


@router.get(
    "/api/outbox/{action_id}/audit",
    response_model=list[AuditOut],
    tags=["audit"],
)
def list_outbox_audit(
    action_id: int,
    db: Session = Depends(get_db),
) -> list[AuditEvent]:
    """Return the complete audit trail for one staged action.

    This targeted route avoids deriving an action's history from a capped
    instance-wide audit page. Outbox actions have a bounded state machine, so
    their complete trail is safe to return without a global pagination cap.
    """
    if db.get(OutboxAction, action_id) is None:
        raise HTTPException(status_code=404, detail=f"Outbox action {action_id} not found.")
    stmt = (
        select(AuditEvent)
        .where(AuditEvent.outbox_action_id == action_id)
        .order_by(AuditEvent.ts.asc(), AuditEvent.id.asc())
    )
    return list(db.scalars(stmt))


# --------------------------------------------------------------------------
# Component images (metrology / VI attachments, read-only PDB fetch)
# --------------------------------------------------------------------------


def _pdb_gateway(request: Request, db: Session, user: User):
    """Personal PDB gateway for direct reads; tests may inject a fake."""
    from app.pdb_gateway import PdbGateway

    injected = getattr(request.app.state, "pdb_gateway", None)
    if injected is not None:
        return injected
    access_codes = _load_personal_pdb_access(request, db, user)
    return PdbGateway(request.app.state.settings, access_codes=access_codes)


@router.get(
    "/api/components/{sn}/images",
    response_model=list[ComponentImageOut],
    tags=["components"],
)
def component_images(
    sn: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> list[dict]:
    """List a component's metrology/VI image attachments (empty when offline)."""
    from app.pdb_attachments import list_component_images

    return list_component_images(_pdb_gateway(request, db, user), sn)


@router.get("/api/components/{sn}/images/{attachment_id}", tags=["components"])
def component_image_binary(
    sn: str,
    attachment_id: str,
    request: Request,
    test_run_ref: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> Response:
    """Stream one image attachment's bytes from the PDB.

    `test_run_ref` comes from the listing and is what makes the working
    download route usable; without it only the fallback remains."""
    from app.pdb_attachments import fetch_image_binary

    result = fetch_image_binary(
        _pdb_gateway(request, db, user), sn, attachment_id, test_run_ref
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Image not available.")
    content_type, data = result
    return Response(content=data, media_type=content_type)


def _attachment_rows_by_run(
    db: Session, sn: str
) -> dict[tuple[str, str | None], list]:
    """Local attachment index grouped by test type and run.

    A real PDB run reference is unique, but custom/legacy evidence may have no
    reference. Including the test type keeps those valid empty-reference
    associations from appearing on every no-run test card.
    """
    from app.attachment_store import attachment_references

    grouped: dict[tuple[str, str | None], list] = {}
    for row in attachment_references(db, sn):
        grouped.setdefault((row.test_type, row.test_run_ref), []).append(row)
    return grouped


def _attachment_out(settings: Settings, row) -> TestRunAttachmentOut:
    from app.attachment_store import attachment_read_model

    return TestRunAttachmentOut.model_validate(attachment_read_model(settings, row))


@router.get(
    "/api/components/{sn}/tests",
    response_model=list[TestRunDetailOut],
    tags=["components", "workflow"],
)
def component_test_details(
    sn: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> list[TestRunDetailOut]:
    """Mirrored test runs with their measured values, newest first.

    Purely local: this reads the mirror written by `/sync-evidence` and never
    touches the PDB, so the detail page stays fast and works offline. An empty
    list means nothing has been mirrored yet, not that no tests exist."""
    settings = request.app.state.settings
    grouped = _attachment_rows_by_run(db, sn)

    rows = db.scalars(
        select(TestRunEvidence)
        .where(TestRunEvidence.component_sn == sn)
        .order_by(TestRunEvidence.measured_at.desc().nullslast(), TestRunEvidence.id.desc())
    )

    details: list[TestRunDetailOut] = []
    for evidence in rows:
        payload = evidence.payload or {}
        run_number = payload.get("run_number")
        details.append(
            TestRunDetailOut(
                test_type=evidence.test_type,
                passed=evidence.passed,
                external_ref=evidence.external_ref,
                measured_at=evidence.measured_at,
                run_number=str(run_number) if run_number is not None else None,
                # Withdrawn runs stay in this list; the state is what tells a
                # reader not to treat them as evidence (see TestRunDetailOut).
                run_state=evidence.run_state,
                results=payload.get("results") or {},
                result_meta=payload.get("result_meta") or {},
                properties=payload.get("properties") or {},
                attachments=[
                    _attachment_out(settings, row)
                    for row in grouped.get(
                        (evidence.test_type, evidence.external_ref), []
                    )
                ],
            )
        )
    return details


@router.get(
    "/api/components/{sn}/attachments",
    response_model=ComponentAttachmentsOut,
    tags=["components"],
)
def component_attachments(
    sn: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> ComponentAttachmentsOut:
    """This component's mirrored attachment index, plus its parts' images.

    The operator works on a module; the photographs hang on the parts bonded
    into it. On the owner's mirror 3 of 432 mirrored images sit on a module and
    241 on sensors that are a module's direct child — filtered by serial number
    alone, a module page can never show them. For a stitched R3-R5 module the
    parts hang one hop further down, below its half modules, so the walk takes
    a second hop through a child that is itself a module (see
    `attachment_store.child_image_attachments`).

    They arrive in their own per-part group, tagged with that part's serial
    and component type, never merged into `attachments`: a photograph of a
    sensor is a statement about that sensor. This follows the worksheet's child
    evidence groups (`preview._child_evidence_groups`), including their cost
    rule — a constant query set for the whole family, never one per child.

    The per-run attachment lists in `GET /api/components/{sn}/tests` are
    untouched: a run belongs to exactly one component."""
    from app.attachment_store import child_image_attachments, known_attachments

    settings = request.app.state.settings
    return ComponentAttachmentsOut(
        component_sn=sn,
        attachments=[_attachment_out(settings, row) for row in known_attachments(db, sn)],
        children=[
            ChildAttachmentsOut(
                sn=child.sn,
                component_type=child.component_type,
                type_code=child.type_code,
                local_name=child.local_name,
                attachments=[_attachment_out(settings, row) for row in rows],
            )
            for child, rows in child_image_attachments(db, sn)
        ],
    )


@router.post(
    "/api/components/{sn}/attachments/sync",
    response_model=AttachmentSyncOut,
    tags=["components"],
)
def component_attachments_sync(
    sn: str,
    request: Request,
    force: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(require_operator),
) -> AttachmentSyncOut:
    """Mirror this component's attachment bytes into the local folder.

    Read-only against the PDB. Requires the detailed evidence sync to have run
    first, which is what records *which* attachments exist."""
    from app.attachment_store import download_attachments
    from app.share_credentials import load_share_passwords

    settings = request.app.state.settings
    try:
        share_passwords = load_share_passwords(
            db,
            user_id=user.id,
            encryption_key=settings.pdb_credential_encryption_key,
        )
    except (CredentialKeyMissingError, CredentialKeyInvalidError):
        raise HTTPException(
            status_code=503,
            detail="Saved public-share passwords cannot be opened by this server.",
        ) from None

    stats = download_attachments(
        db,
        _pdb_gateway(request, db, user),
        settings,
        sn,
        force=force,
        share_passwords=share_passwords,
    )
    db.commit()
    return AttachmentSyncOut(
        component_sn=sn,
        downloaded=stats.downloaded,
        reused=stats.reused,
        failed=stats.failed,
        skipped=stats.skipped,
        authentication_required=stats.authentication_required,
        total=stats.total,
    )


@router.get("/api/components/{sn}/attachments/{code}", tags=["components"])
def component_attachment_binary(
    sn: str,
    code: str,
    request: Request,
    source: str | None = Query(default=None, min_length=1, max_length=24),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> Response:
    """Serve one locally mirrored attachment.

    Local only: a file that was never downloaded is a 404 rather than a silent
    fetch, so the UI can offer the sync instead of hiding a slow PDB call
    behind an image tag. New clients pass ``source`` to address the complete
    ``(source, code)`` blob identity. Omitting it retains deterministic legacy
    bookmark compatibility."""
    from app.attachment_store import attachment_for_component, resolve_path

    row = attachment_for_component(db, sn, code, source=source)
    if row is None:
        raise HTTPException(status_code=404, detail="Unknown attachment.")

    path = resolve_path(request.app.state.settings, row)
    if path is None:
        raise HTTPException(
            status_code=404,
            detail="This attachment is not mirrored locally yet. Sync attachments first.",
        )
    return FileResponse(
        path,
        media_type=row.content_type or "application/octet-stream",
        filename=row.filename or row.pdb_code,
    )


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
    sn: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_operator),
) -> EvidenceSyncOut:
    """Mirror this component's PDB test-run results into local evidence, so the
    stage engine knows which required tests really passed (not just itkFlow
    uploads). Read-only against the PDB, and detailed: measured values,
    properties and attachment metadata come along, which is what the
    glue-weight, metrology and IV views read.

    Answers 503 when the PDB cannot be read. Reporting a successful zero there
    would be indistinguishable from a module that has no test runs at all."""
    from app.attachment_store import download_attachments
    from app.pdb_test_evidence import PdbEvidenceUnavailable, fetch_test_run_evidence
    from app.share_credentials import load_share_passwords
    from app.test_run_evidence import upsert_test_run_evidence

    component = db.scalar(select(Component).where(Component.sn == sn))
    if component is None:
        raise HTTPException(status_code=404, detail=f"Component '{sn}' not found.")
    institute = db.scalar(
        select(InstituteProfile).where(
            InstituteProfile.code == component.institute_code
        )
    )
    if institute is None:
        raise HTTPException(
            status_code=409,
            detail=f"Component institute '{component.institute_code}' is not configured.",
        )
    _require_institute_scope(user, institute)

    # One opened component is worth the extra request per run: this is what
    # fills the glue-weight, metrology and IV views.
    gateway = _pdb_gateway(request, db, user)
    settings = request.app.state.settings
    try:
        share_passwords = load_share_passwords(
            db,
            user_id=user.id,
            encryption_key=settings.pdb_credential_encryption_key,
        )
    except (CredentialKeyMissingError, CredentialKeyInvalidError):
        raise HTTPException(
            status_code=503,
            detail="Saved public-share passwords cannot be opened by this server.",
        ) from None
    try:
        records = fetch_test_run_evidence(
            gateway, sn, with_detail=True, strict=True
        )
    except PdbEvidenceUnavailable as exc:
        # Reporting "0 mirrored" here would be a lie that looks like a fact.
        raise HTTPException(status_code=503, detail=str(exc)) from None
    stats = upsert_test_run_evidence(db, records)
    # Commit the evidence BEFORE the download phase: holding the write
    # transaction across network I/O blocked every other writer for the whole
    # fetch — the exact "database is locked" incident. The attachment index is
    # idempotent and re-derivable, so it does not need to share the commit.
    db.commit()
    attachment_stats = download_attachments(
        db,
        gateway,
        settings,
        sn,
        share_passwords=share_passwords,
    )
    db.commit()
    return EvidenceSyncOut(
        component_sn=sn,
        created=stats.created,
        updated=stats.updated,
        unchanged=stats.unchanged,
        total=stats.total,
        attachments_downloaded=attachment_stats.downloaded,
        attachments_reused=attachment_stats.reused,
        attachments_failed=attachment_stats.failed,
        attachments_skipped=attachment_stats.skipped,
        attachments_authentication_required=(
            attachment_stats.authentication_required
        ),
        attachments_total=attachment_stats.total,
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
    user: User = Depends(require_operator),
) -> InstituteEvidenceSyncOut:
    """Mirror PDB test-run evidence for every live component of one type at an
    institute, so the dashboard's required-test gaps and stage suggestions
    reflect real PDB results. One PDB read per component; a no-op when the
    gateway is not configured."""
    from app.attachment_store import AttachmentSyncStats, download_attachments
    from app.pdb_test_evidence import fetch_test_run_evidence
    from app.share_credentials import load_share_passwords
    from app.test_run_evidence import upsert_test_run_evidence

    institute = db.scalar(
        select(InstituteProfile).where(InstituteProfile.code == institute_code)
    )
    if institute is None:
        raise HTTPException(status_code=404, detail=f"Institute '{institute_code}' not found.")
    _require_institute_scope(user, institute)

    gateway = _pdb_gateway(request, db, user)
    settings = request.app.state.settings
    try:
        share_passwords = load_share_passwords(
            db,
            user_id=user.id,
            encryption_key=settings.pdb_credential_encryption_key,
        )
    except (CredentialKeyMissingError, CredentialKeyInvalidError):
        raise HTTPException(
            status_code=503,
            detail="Saved public-share passwords cannot be opened by this server.",
        ) from None
    components = list(
        db.scalars(
            select(Component).where(
                Component.institute_code == institute_code,
                Component.component_type == component_type,
                Component.trashed.is_(False),
                Component.stale.is_(False),
            )
        )
    )
    records = []
    for component in components:
        records.extend(fetch_test_run_evidence(gateway, component.sn, with_detail=True))
    stats = upsert_test_run_evidence(db, records)
    # Evidence becomes durable before any network download, and each
    # component's attachment index commits on its own: the write lock is never
    # held across network I/O (the "database is locked" incident), and an
    # interrupted sweep keeps everything mirrored so far.
    db.commit()
    attachment_stats = AttachmentSyncStats()
    for component in components:
        current = download_attachments(
            db,
            gateway,
            settings,
            component.sn,
            share_passwords=share_passwords,
        )
        db.commit()
        attachment_stats = AttachmentSyncStats(
            downloaded=attachment_stats.downloaded + current.downloaded,
            reused=attachment_stats.reused + current.reused,
            failed=attachment_stats.failed + current.failed,
            skipped=attachment_stats.skipped + current.skipped,
            authentication_required=(
                attachment_stats.authentication_required
                + current.authentication_required
            ),
        )
    return InstituteEvidenceSyncOut(
        institute_code=institute_code,
        component_types=[component_type],
        components_processed=len(components),
        created=stats.created,
        updated=stats.updated,
        unchanged=stats.unchanged,
        total=stats.total,
        attachments_downloaded=attachment_stats.downloaded,
        attachments_reused=attachment_stats.reused,
        attachments_failed=attachment_stats.failed,
        attachments_skipped=attachment_stats.skipped,
        attachments_authentication_required=(
            attachment_stats.authentication_required
        ),
        attachments_total=attachment_stats.total,
    )


# --------------------------------------------------------------------------
# Shipments (Phase 4, docs/11): PDB mirror + local receiving check
# --------------------------------------------------------------------------


def _shipment_direction(shipment: Shipment, institute_code: str | None) -> str:
    if not institute_code:
        return "unknown"
    incoming = shipment.recipient_code == institute_code
    outgoing = shipment.sender_code == institute_code
    if incoming and outgoing:
        return "internal"
    if incoming:
        return "incoming"
    if outgoing:
        return "outgoing"
    return "unknown"


def _shipment_out(
    shipment: Shipment,
    institute_codes: dict[int, str],
    projection: dict | None = None,
) -> ShipmentOut:
    out = ShipmentOut.model_validate(shipment)
    code = institute_codes.get(shipment.institute_id) if shipment.institute_id else None
    out.direction = _shipment_direction(shipment, code)
    if projection is not None:
        out.items = [ShipmentItemOut.model_validate(item) for item in projection["items"]]
        out.reception_tests_configured = projection["reception_tests_configured"]
        out.reception_test_status = projection["reception_test_status"]
    return out


def _institute_codes(db: Session) -> dict[int, str]:
    rows = db.execute(select(InstituteProfile.id, InstituteProfile.code))
    return {institute_id: code for institute_id, code in rows}


@router.get("/api/shipments", response_model=list[ShipmentOut], tags=["shipments"])
def list_shipments(
    direction: str | None = None,
    status: str | None = None,
    reception: str | None = None,
    q: str | None = None,
    db: Session = Depends(get_db),
) -> list[ShipmentOut]:
    stmt = select(Shipment).order_by(Shipment.sent_at.desc().nulls_last(), Shipment.id.desc())
    if status:
        stmt = stmt.where(Shipment.status == status)
    if reception:
        stmt = stmt.where(Shipment.reception_status == reception)
    if q:
        needle = f"%{q.strip().lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Shipment.name).like(needle),
                func.lower(Shipment.pdb_id).like(needle),
                func.lower(Shipment.sender_code).like(needle),
                func.lower(Shipment.recipient_code).like(needle),
            )
        )
    codes = _institute_codes(db)
    shipment_rows = list(db.scalars(stmt))
    from app.shipment_reception import project_shipment_reception_tests

    projections = project_shipment_reception_tests(db, shipment_rows)
    shipments = [
        _shipment_out(shipment, codes, projections.get(shipment.id))
        for shipment in shipment_rows
    ]
    if direction:
        shipments = [shipment for shipment in shipments if shipment.direction == direction]
    return shipments


@router.get("/api/shipments/{shipment_id}", response_model=ShipmentOut, tags=["shipments"])
def get_shipment(shipment_id: int, db: Session = Depends(get_db)) -> ShipmentOut:
    shipment = db.get(Shipment, shipment_id)
    if shipment is None:
        raise HTTPException(status_code=404, detail=f"Shipment {shipment_id} not found.")
    from app.shipment_reception import project_shipment_reception_tests

    projection = project_shipment_reception_tests(db, [shipment])[shipment.id]
    return _shipment_out(shipment, _institute_codes(db), projection)


@router.post(
    "/api/sync/shipments/{institute_code}", response_model=ShipmentSyncOut, tags=["shipments"]
)
def sync_institute_shipments(
    institute_code: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_operator),
) -> ShipmentSyncOut:
    """Mirror the institute's PDB shipments (both directions, read-only).

    Small lists, so this runs synchronously like the evidence sync. Answers 503
    when the PDB cannot be read — a successful zero would be a lie."""
    from app.pdb_shipments import PdbShipmentsUnavailable, fetch_shipments_for_institute
    from app.shipment_sync import delivered_pdb_ids, sync_shipments

    institute = db.scalar(
        select(InstituteProfile).where(InstituteProfile.code == institute_code)
    )
    if institute is None:
        raise HTTPException(status_code=404, detail=f"Institute '{institute_code}' not found.")
    _require_institute_scope(user, institute)
    gateway = _pdb_gateway(request, db, user)
    try:
        records = fetch_shipments_for_institute(
            gateway, institute_code, skip_items_for=delivered_pdb_ids(db)
        )
    except PdbShipmentsUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    stats = sync_shipments(db, institute, records)
    db.commit()
    return ShipmentSyncOut(
        institute_code=institute_code,
        created=stats.created,
        updated=stats.updated,
        unchanged=stats.unchanged,
        total=stats.total,
    )


@router.post(
    "/api/shipments/{shipment_id}/reception", response_model=ShipmentOut, tags=["shipments"]
)
def update_shipment_reception(
    shipment_id: int,
    body: ShipmentReceptionUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_operator),
) -> ShipmentOut:
    """Record the local receiving check. Partial: omitted fields are kept.

    These fields are locally leading — a later PDB sync never overwrites them."""
    shipment = db.get(Shipment, shipment_id)
    if shipment is None:
        raise HTTPException(status_code=404, detail=f"Shipment {shipment_id} not found.")
    institute = (
        db.get(InstituteProfile, shipment.institute_id)
        if shipment.institute_id is not None
        else None
    )
    if institute is None:
        raise HTTPException(
            status_code=409,
            detail="The shipment is not linked to an institute profile.",
        )
    _require_institute_scope(user, institute)

    override_reason = (body.test_override_reason or "").strip()
    if body.test_override and body.status != "done":
        raise HTTPException(
            status_code=422,
            detail="A reception-test override is only valid when marking reception done.",
        )
    if body.test_override and not override_reason:
        raise HTTPException(
            status_code=422,
            detail="A reception-test override requires a reason.",
        )
    if body.test_override and user.role != "admin":
        raise HTTPException(
            status_code=403,
            detail="Only an admin may override incomplete reception tests.",
        )
    if body.test_override_reason is not None and not body.test_override:
        raise HTTPException(
            status_code=422,
            detail="Set test_override when supplying an override reason.",
        )

    from app.shipment_reception import project_shipment_reception_tests

    projection = project_shipment_reception_tests(db, [shipment])[shipment.id]
    tests_block_done = (
        projection["reception_tests_configured"]
        and projection["reception_test_status"] != "passed"
    )
    if body.status == "done" and tests_block_done:
        if not body.test_override:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": (
                        "Reception cannot be marked done until every configured "
                        "reception test has passed."
                    ),
                    "reception_test_status": projection["reception_test_status"],
                },
            )
        db.add(
            AuditEvent(
                actor=user.email,
                user_id=user.id,
                action="shipment.reception_test_override",
                subject=f"shipment:{shipment.id}",
                detail={
                    "pdb_id": shipment.pdb_id,
                    "reception_test_status": projection["reception_test_status"],
                    "reason": override_reason,
                },
            )
        )
    elif body.test_override:
        raise HTTPException(
            status_code=409,
            detail="Reception tests already pass; an override is not applicable.",
        )
    if body.checklist is not None:
        shipment.reception_checklist = [item.model_dump() for item in body.checklist]
    if body.items is not None:
        shipment.reception_items = [item.model_dump() for item in body.items]
    if body.note is not None:
        shipment.reception_note = body.note
    if body.status is not None:
        shipment.reception_status = body.status
    elif shipment.reception_status == "pending":
        shipment.reception_status = "in_progress"
    shipment.reception_by = user.email
    shipment.reception_user_id = user.id
    shipment.reception_updated_at = utcnow()
    db.add(
        AuditEvent(
            actor=user.email,
            user_id=user.id,
            action="shipment.reception_updated",
            subject=f"shipment:{shipment.id}",
            detail={
                "pdb_id": shipment.pdb_id,
                "reception_status": shipment.reception_status,
            },
        )
    )
    db.commit()
    db.refresh(shipment)
    refreshed = project_shipment_reception_tests(db, [shipment])[shipment.id]
    return _shipment_out(shipment, _institute_codes(db), refreshed)


# --------------------------------------------------------------------------
# Reminders & notification channels (Phase 4, docs/11)
# --------------------------------------------------------------------------


def _validate_reminder_channel(db: Session, user: User, channel: str | None) -> None:
    """A named channel must exist in the user's institute profile."""
    if not channel:
        return
    institute = db.get(InstituteProfile, user.institute_id) if user.institute_id else None
    if institute is None or channel not in channel_configs(institute.settings):
        raise HTTPException(
            status_code=422,
            detail=f"Notification channel '{channel}' is not configured for your institute.",
        )


@router.get("/api/reminders", response_model=list[ReminderOut], tags=["reminders"])
def list_reminders(
    active: bool | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> list[Reminder]:
    stmt = (
        select(Reminder)
        .where(Reminder.deleted_at.is_(None))
        .order_by(Reminder.active.desc(), Reminder.next_due_at)
    )
    if user.institute_id is not None:
        stmt = stmt.where(Reminder.institute_id == user.institute_id)
    if active is not None:
        stmt = stmt.where(Reminder.active.is_(active))
    return list(db.scalars(stmt))


@router.post("/api/reminders", response_model=ReminderOut, status_code=201, tags=["reminders"])
def create_reminder(
    body: ReminderCreate, db: Session = Depends(get_db), user: User = Depends(require_operator)
) -> Reminder:
    _validate_reminder_channel(db, user, body.channel)
    reminder = Reminder(
        title=body.title,
        note=body.note,
        channel=body.channel or None,
        schedule_kind=body.schedule_kind,
        next_due_at=body.next_due_at,
        created_by=user.email,
        user_id=user.id,
        institute_id=user.institute_id,
    )
    db.add(reminder)
    db.flush()
    db.add(
        AuditEvent(
            actor=user.email,
            user_id=user.id,
            action="reminder.created",
            subject=f"reminder:{reminder.id}",
            detail={"title": reminder.title, "schedule_kind": reminder.schedule_kind},
        )
    )
    db.commit()
    db.refresh(reminder)
    return reminder


@router.patch("/api/reminders/{reminder_id}", response_model=ReminderOut, tags=["reminders"])
def update_reminder(
    reminder_id: int,
    body: ReminderUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_operator),
) -> Reminder:
    reminder = db.get(Reminder, reminder_id)
    if reminder is None or reminder.deleted_at is not None:
        raise HTTPException(status_code=404, detail=f"Reminder {reminder_id} not found.")
    if user.institute_id is not None and reminder.institute_id != user.institute_id:
        raise HTTPException(status_code=403, detail="You can only edit your own reminders.")
    if body.channel is not None:
        # Empty string clears the channel; a non-empty name must be configured.
        channel = body.channel.strip() or None
        _validate_reminder_channel(db, user, channel)
        reminder.channel = channel
    if body.title is not None:
        reminder.title = body.title
    if body.note is not None:
        reminder.note = body.note
    if body.schedule_kind is not None:
        reminder.schedule_kind = body.schedule_kind
    if body.next_due_at is not None:
        reminder.next_due_at = body.next_due_at
    if body.active is not None:
        reminder.active = body.active
    db.add(
        AuditEvent(
            actor=user.email,
            user_id=user.id,
            action="reminder.updated",
            subject=f"reminder:{reminder.id}",
            detail={"title": reminder.title, "active": reminder.active},
        )
    )
    db.commit()
    db.refresh(reminder)
    return reminder


@router.delete("/api/reminders/{reminder_id}", status_code=204, tags=["reminders"])
def delete_reminder(
    reminder_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_operator),
) -> Response:
    reminder = db.get(Reminder, reminder_id)
    if reminder is None or reminder.deleted_at is not None:
        raise HTTPException(status_code=404, detail=f"Reminder {reminder_id} not found.")
    if user.institute_id is not None and reminder.institute_id != user.institute_id:
        raise HTTPException(status_code=403, detail="You can only delete your own reminders.")
    db.add(
        AuditEvent(
            actor=user.email,
            user_id=user.id,
            action="reminder.deleted",
            subject=f"reminder:{reminder.id}",
            detail={"title": reminder.title},
        )
    )
    # A fired occurrence is a durable acknowledgement task. Hiding the
    # schedule must not orphan or erase that operational history, and an open
    # occurrence must still be able to escalate with its original title.
    reminder.active = False
    reminder.deleted_at = utcnow()
    db.commit()
    return Response(status_code=204)


@router.get(
    "/api/reminder-occurrences",
    response_model=list[ReminderOccurrenceOut],
    tags=["reminders"],
)
def list_reminder_occurrences(
    reminder_id: int | None = None,
    open_only: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> list[ReminderOccurrence]:
    """List durable reminder tasks; institute-bound users see only their own."""

    stmt = select(ReminderOccurrence).order_by(
        ReminderOccurrence.acknowledged_at.is_(None).desc(),
        ReminderOccurrence.fired_at.desc(),
        ReminderOccurrence.id.desc(),
    )
    if user.institute_id is not None:
        stmt = stmt.where(ReminderOccurrence.institute_id == user.institute_id)
    if reminder_id is not None:
        stmt = stmt.where(ReminderOccurrence.reminder_id == reminder_id)
    if open_only:
        stmt = stmt.where(ReminderOccurrence.acknowledged_at.is_(None))
    return list(db.scalars(stmt))


@router.post(
    "/api/reminder-occurrences/{occurrence_id}/ack",
    response_model=ReminderOccurrenceOut,
    tags=["reminders"],
)
def acknowledge_reminder_occurrence(
    occurrence_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_operator),
) -> ReminderOccurrence:
    occurrence = db.get(ReminderOccurrence, occurrence_id)
    if occurrence is None:
        raise HTTPException(
            status_code=404,
            detail=f"Reminder occurrence {occurrence_id} not found.",
        )
    if user.institute_id is not None and occurrence.institute_id != user.institute_id:
        raise HTTPException(
            status_code=403,
            detail="You can only acknowledge reminders for your own institute.",
        )
    if occurrence.acknowledged_at is None:
        occurrence.acknowledged_at = utcnow()
        occurrence.acknowledged_by = user.email
        occurrence.acknowledged_user_id = user.id
        db.add(
            AuditEvent(
                actor=user.email,
                user_id=user.id,
                action="reminder.acknowledged",
                subject=f"reminder:{occurrence.reminder_id}",
                detail={"occurrence_id": occurrence.id},
            )
        )
        db.commit()
        db.refresh(occurrence)
    return occurrence


@router.get(
    "/api/notifications/channels",
    response_model=list[NotificationChannelOut],
    tags=["reminders"],
)
def list_notification_channels(
    db: Session = Depends(get_db), user: User = Depends(require_user)
) -> list[NotificationChannelOut]:
    """Channel names and kinds for the user's institute — URLs stay server-side."""
    institute = db.get(InstituteProfile, user.institute_id) if user.institute_id else None
    if institute is None:
        return []
    return [
        NotificationChannelOut(name=name, kind=config.get("kind", "webhook"))
        for name, config in sorted(channel_configs(institute.settings).items())
    ]


@router.post("/api/notifications/test", response_model=NotificationTestOut, tags=["reminders"])
def send_test_notification(
    body: NotificationTestIn,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> NotificationTestOut:
    """Send a test message through one configured channel (admin-only).

    An institute-bound admin is always confined to their own profile.  A
    global admin has no implicit tenant and must select one explicitly.
    """
    if admin.institute_id is not None:
        institute = db.get(InstituteProfile, admin.institute_id)
        if body.institute_code is not None and (
            institute is None or body.institute_code != institute.code
        ):
            raise HTTPException(
                status_code=403,
                detail="You can only test channels for your own institute.",
            )
    elif body.institute_code is not None:
        institute = db.scalar(
            select(InstituteProfile).where(InstituteProfile.code == body.institute_code)
        )
        if institute is None:
            raise HTTPException(
                status_code=404,
                detail=f"Institute '{body.institute_code}' not found.",
            )
    else:
        institute = None
    if institute is None:
        raise HTTPException(
            status_code=400,
            detail="Select an institute before testing a notification channel.",
        )
    channel = channel_configs(institute.settings).get(body.channel)
    if channel is None:
        raise HTTPException(
            status_code=422,
            detail=f"Notification channel '{body.channel}' is not configured.",
        )
    notifier = getattr(request.app.state, "notifier", None)
    if notifier is None:
        from app.notifications import make_notifier

        notifier = make_notifier(request.app.state.settings)
    try:
        notifier(channel, "itkFlow test notification", "Channel configuration works.")
    except NotificationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    db.add(
        AuditEvent(
            actor=admin.email,
            user_id=admin.id,
            action="notification.test_sent",
            subject=f"channel:{body.channel}",
            detail={"institute": institute.code},
        )
    )
    db.commit()
    return NotificationTestOut(channel=body.channel, sent=True)
