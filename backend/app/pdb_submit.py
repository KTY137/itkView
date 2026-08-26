"""Real PDB submitter — writes reviewed outbox actions to the PDB.

Dispatches by action kind:

- `upload_test_run` -> `uploadTestRunResults`
- `stage_move`      -> `setComponentStage`
- `register_component` -> `registerComponent` (DUMMY parts only)
- `assemble_component` -> `assembleComponent` (DUMMY modules/hybrids only)

Write scope (docs/09, ADR 003): with `pdb_write_scope="dummy_only"` (the
default) every write is refused unless its target component is an
itkFlow-registered DUMMY test component (`app.pdb_scope.is_dummy_target`).
"unrestricted" is deliberately not implemented. `register_dummy_component`
is the only way a new PDB component comes into existence through itkFlow —
hybrids/modules only, always in the institute's DUMMY batch.

This is the default `Submitter` wired into the standalone worker. Every
approved action carries an immutable ``OutboxPdbPrincipal`` binding. The
worker resolves that account's currently verified, encrypted credentials for
each attempt and never falls back to deployment-wide access codes. A missing
or unusable personal connection surfaces as ``PdbSubmitUnavailable``.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assembly import (
    ASSEMBLY_ACTION_KIND,
    SAFE_ASSEMBLY_COMPONENT_TYPES,
    revalidate_assembly_action,
)
from app.config import Settings
from app.models import (
    Component,
    IngestFile,
    InstituteProfile,
    OutboxAction,
    OutboxPdbPrincipal,
    PdbCredential,
    utcnow,
)
from app.outbox_worker import PdbSubmitUnavailable, SubmitOutcome, Submitter
from app.pdb_credentials import PdbAccessCodes, PdbCredentialError, load_pdb_credentials
from app.pdb_gateway import PdbGateway
from app.pdb_scope import dummy_batch_name, is_dummy_target, is_registrable_type
from app.pdb_upload import UploadPayloadError, build_upload_test_run_payload


def _extract_run_ref(response: Any) -> str:
    """Best-effort test-run id from an uploadTestRunResults response."""
    if isinstance(response, dict):
        run = response.get("testRun")
        if isinstance(run, dict) and run.get("id"):
            return str(run["id"])
        for key in ("id", "testRunId", "code"):
            if response.get(key):
                return str(response[key])
    return "uploaded"


def _scope_rejection(sn: Any) -> SubmitOutcome:
    return SubmitOutcome.rejected(
        f"Write refused: '{sn}' is not an itkFlow-registered DUMMY test component "
        "(pdb_write_scope=dummy_only). Only self-registered DUMMY-batch parts may "
        "be written to."
    )


class _PdbRequestRejected(RuntimeError):
    """A safe, secret-free marker for a non-transient PDB HTTP response."""


def _response_status(error: Exception) -> int | None:
    """Extract an HTTP status without rendering a potentially secret exception."""
    response = getattr(error, "response", None)
    status = getattr(response, "status_code", None)
    if status is None:
        status = getattr(error, "status_code", None)
    return status if isinstance(status, int) else None


def _call_pdb(method, *args, unavailable_message: str, **kwargs):
    """Call itkdb while replacing every upstream exception with safe text.

    ``itkdb.ResponseException.__str__`` includes a pretty-printed request and
    can therefore expose authentication material. This boundary deliberately
    never renders the exception. Known 4xx responses are data/permission
    rejections; timeouts, 408/429 and 5xx/unknown failures remain retryable.
    """
    try:
        return method(*args, **kwargs)
    except Exception as exc:
        status = _response_status(exc)
        if status is not None and 400 <= status < 500 and status not in {408, 425, 429}:
            raise _PdbRequestRejected("The PDB rejected the request.") from None
        raise PdbSubmitUnavailable(unavailable_message) from None


def make_pdb_submitter(
    settings: Settings,
    *,
    service_access_codes: PdbAccessCodes | None = None,
) -> Submitter:
    """Build the real worker submitter.

    Production calls leave ``service_access_codes`` unset and resolve the
    immutable principal attached at approval time. The explicit override only
    exists for the separately opted-in ``pdb_write`` integration test; it is
    never populated by :mod:`app.run_worker`.
    """
    if service_access_codes is not None and not settings.allow_pdb_writes:
        raise PdbSubmitUnavailable(
            "Explicit service credentials are reserved for opted-in PDB write tests."
        )

    def _client(session: Session, action: OutboxAction):
        if settings.pdb_write_scope != "dummy_only":
            # "unrestricted" is a recognised value but real production writes
            # are deliberately not implemented (docs/09).
            raise PdbSubmitUnavailable(
                "pdb_write_scope='unrestricted' is deliberately not implemented; "
                "PDB writes are confined to DUMMY test components."
            )

        access_codes = service_access_codes
        if access_codes is None:
            action_id = getattr(action, "id", None)
            principal = (
                session.get(OutboxPdbPrincipal, action_id) if isinstance(action_id, int) else None
            )
            if principal is None:
                raise PdbSubmitUnavailable(
                    "No personal PDB identity is bound to this approved action."
                )
            credential = session.get(PdbCredential, principal.user_id)
            if (
                credential is None
                or credential.status != "verified"
                or credential.pdb_identity != principal.pdb_identity
            ):
                raise PdbSubmitUnavailable(
                    "The personal PDB connection bound to this action is unavailable."
                )
            try:
                access_codes = load_pdb_credentials(
                    session,
                    user_id=principal.user_id,
                    encryption_key=settings.pdb_credential_encryption_key,
                )
            except PdbCredentialError:
                raise PdbSubmitUnavailable(
                    "The personal PDB connection bound to this action is unavailable."
                ) from None

        try:
            gateway = PdbGateway(settings, access_codes=access_codes)
            return gateway.client()
        except Exception:
            # Never render the upstream error. itkdb authentication failures
            # may embed the access-code request in their message.
            raise PdbSubmitUnavailable(
                "The personal PDB connection for this action could not be opened."
            ) from None

    def _submit_upload(session, action: OutboxAction) -> SubmitOutcome:
        ingest_id = action.payload.get("ingest_file_id")
        ingest = session.get(IngestFile, ingest_id) if ingest_id is not None else None
        if ingest is None:
            return SubmitOutcome.rejected("The ingest file backing this action no longer exists.")
        component = (
            session.scalar(select(Component).where(Component.sn == ingest.component_sn))
            if ingest.component_sn
            else None
        )
        action_institute_id = getattr(action, "institute_id", None)
        institute = (
            session.get(InstituteProfile, action_institute_id)
            if action_institute_id is not None
            else None
        )
        institute_code = component.institute_code if component is not None else None
        if institute_code is None and institute is not None:
            institute_code = institute.code
        try:
            upload_payload = build_upload_test_run_payload(
                ingest.payload,
                component_sn=ingest.component_sn,
                institute_code=institute_code,
            )
        except UploadPayloadError as exc:
            return SubmitOutcome.rejected(f"Upload payload is not PDB-ready: {exc}")
        sn = upload_payload["component"]
        if not is_dummy_target(session, sn):
            return _scope_rejection(sn)
        client = _client(session, action)
        try:
            response = _call_pdb(
                client.post,
                "uploadTestRunResults",
                json=upload_payload,
                unavailable_message="The PDB upload request is temporarily unavailable.",
            )
        except _PdbRequestRejected:
            return SubmitOutcome.rejected("PDB rejected the upload.")
        return SubmitOutcome.confirmed(_extract_run_ref(response))

    def _submit_stage_move(session, action: OutboxAction) -> SubmitOutcome:
        payload = action.payload or {}
        sn = payload.get("sn")
        to_stage = payload.get("to_stage")
        if not sn or not to_stage:
            return SubmitOutcome.rejected("stage_move payload is missing 'sn' or 'to_stage'.")
        if not is_dummy_target(session, sn):
            return _scope_rejection(sn)
        client = _client(session, action)
        try:
            _call_pdb(
                client.post,
                "setComponentStage",
                json={"component": sn, "stage": to_stage, "rework": bool(payload.get("rework"))},
                unavailable_message="The PDB stage-move request is temporarily unavailable.",
            )
        except _PdbRequestRejected:
            return SubmitOutcome.rejected("PDB rejected the stage move.")
        return SubmitOutcome.confirmed(to_stage)

    def _submit_register(session, action: OutboxAction) -> SubmitOutcome:
        p = action.payload or {}
        ct, tc, inst = p.get("component_type"), p.get("type_code"), p.get("institute_code")
        if not ct or not tc or not inst:
            return SubmitOutcome.rejected(
                "register_component payload is missing component_type / type_code / institute_code."
            )
        if not is_registrable_type(ct, settings):
            return SubmitOutcome.rejected(
                f"Refusing to register component type '{ct}': only "
                f"{settings.pdb_dummy_component_types} may be registered as DUMMY test parts. "
                "Sensors and ASICs must never be registered by itkFlow."
            )
        client = _client(session, action)
        try:
            component = register_dummy_component(
                session,
                settings,
                component_type=ct,
                type_code=tc,
                institute_code=inst,
                subproject=p.get("subproject") or "SE",
                local_name=p.get("local_name"),
                client=client,
            )
        except PdbSubmitUnavailable:
            raise  # scope/codes unavailable -> transient; the worker retries with backoff
        except _PdbRequestRejected:
            return SubmitOutcome.rejected("PDB rejected the registration.")
        return SubmitOutcome.confirmed(component.sn)

    def _submit_assembly(session, action: OutboxAction) -> SubmitOutcome:
        payload = action.payload or {}
        parent_sn = payload.get("parent_sn")
        child_sn = payload.get("child_sn")
        if not isinstance(parent_sn, str) or not isinstance(child_sn, str):
            return SubmitOutcome.rejected(
                "assemble_component payload is missing parent_sn or child_sn."
            )

        # ADR 003 gate: inspect both participants and their component types
        # before an authenticated PDB client is even constructed.  Assembly
        # changes the relationship of both rows, so checking only the parent
        # would allow a real sensor/ASIC to be mutated through a DUMMY module.
        parent = session.scalar(select(Component).where(Component.sn == parent_sn))
        child = session.scalar(select(Component).where(Component.sn == child_sn))
        if parent is None or child is None:
            return SubmitOutcome.rejected(
                "Assembly participants are no longer present in the local mirror."
            )
        if (
            parent.component_type not in SAFE_ASSEMBLY_COMPONENT_TYPES
            or child.component_type not in SAFE_ASSEMBLY_COMPONENT_TYPES
            or not is_registrable_type(parent.component_type, settings)
            or not is_registrable_type(child.component_type, settings)
        ):
            return SubmitOutcome.rejected(
                "Write refused: assembly is limited to DUMMY modules/hybrids; "
                "sensors and ASICs are never written by itkFlow."
            )
        if not is_dummy_target(session, parent_sn) or not is_dummy_target(session, child_sn):
            return SubmitOutcome.rejected(
                "Write refused: both assembly participants must be itkFlow-registered "
                "DUMMY test components (pdb_write_scope=dummy_only)."
            )
        issues = revalidate_assembly_action(session, payload, settings)
        if issues:
            return SubmitOutcome.rejected("Assembly dry-run failed: " + "; ".join(issues))

        properties = payload.get("pdb_properties")
        properties = properties if isinstance(properties, dict) else {}
        client = _client(session, action)
        try:
            response = _call_pdb(
                client.post,
                "assembleComponent",
                json={
                    "parent": parent_sn,
                    "children": [{"sn": child_sn, "properties": properties}],
                    # Never auto-disassemble another relationship.  A child
                    # with a current parent is blocked by the shared dry-run.
                    "disassemble": [],
                },
                unavailable_message="The PDB assembly request is temporarily unavailable.",
            )
        except _PdbRequestRejected:
            return SubmitOutcome.rejected("PDB rejected the assembly.")
        external_ref = None
        if isinstance(response, dict):
            for key in ("id", "code", "assemblyId"):
                if response.get(key):
                    external_ref = str(response[key])
                    break
        return SubmitOutcome.confirmed(external_ref or f"{parent_sn}:{child_sn}")

    def submit(session, action: OutboxAction) -> SubmitOutcome:
        if action.kind == "upload_test_run":
            return _submit_upload(session, action)
        if action.kind == "stage_move":
            return _submit_stage_move(session, action)
        if action.kind == "register_component":
            return _submit_register(session, action)
        if action.kind == ASSEMBLY_ACTION_KIND:
            return _submit_assembly(session, action)
        # No PDB write path for this kind yet; refuse rather than guess.
        # Transient so it is not recorded as a data rejection.
        raise PdbSubmitUnavailable(f"No PDB submitter for action kind '{action.kind}'.")

    return submit


# Batch type code per registrable component type (zeuthenflow reference:
# DBInstituteBatches uses MODULE_BATCH; hybrids analogously).
_BATCH_TYPE_BY_COMPONENT = {"MODULE": "MODULE_BATCH", "HYBRID": "HYBRID_BATCH"}


def _ensure_dummy_batch(client: Any, institute_code: str, component_type: str) -> str | None:
    """Find (or create) the institute's DUMMY batch; return its mongo id.

    Follows the zeuthenflow pattern: `listBatches` by number/owner/type,
    `createBatch` if absent. Returns None when the component type has no
    known batch type — the caller then skips batch assignment.
    """
    batch_type = _BATCH_TYPE_BY_COMPONENT.get(component_type)
    if batch_type is None:
        return None
    number = dummy_batch_name(institute_code)
    listing = _call_pdb(
        client.get,
        "listBatches",
        json={
            "filterMap": {
                "project": "S",
                "number": number,
                "ownerInstitute": [institute_code],
                "batchType": [batch_type],
            }
        },
        unavailable_message="The PDB batch lookup is temporarily unavailable.",
    )
    items = listing.get("itemList", []) if isinstance(listing, dict) else list(listing)
    if items:
        return items[0]["id"]
    created = _call_pdb(
        client.post,
        "createBatch",
        json={
            "number": number,
            "batchType": batch_type,
            "ownerInstituteList": [institute_code],
            "project": "S",
        },
        unavailable_message="The PDB batch creation request is temporarily unavailable.",
    )
    if isinstance(created, dict):
        return created.get("id") or (created.get("batch") or {}).get("id")
    return None


def register_dummy_component(
    session: Session,
    settings: Settings,
    *,
    component_type: str,
    type_code: str,
    institute_code: str,
    subproject: str = "SE",
    local_name: str | None = None,
    properties: dict[str, Any] | None = None,
    access_codes: PdbAccessCodes | None = None,
    client: Any | None = None,
) -> Component:
    """Register a DUMMY test component in the PDB and mirror it locally.

    The only component-creating write itkFlow performs. Guarded twice: the
    component type must be on the configured allowlist (hybrids/modules —
    never sensors or ASICs), and the part is placed in the institute's DUMMY
    batch (`DUMMY_<code>`, created on demand) so collaboration reporting can
    separate it from production. The mirror row carries `is_dummy=True`,
    which is what later entitles the part to receive uploads and stage moves.

    Payload shape follows the zeuthenflow reference (`dbModule.registerModule`
    / `dbComponent.registerComponent`).
    """
    if settings.pdb_write_scope != "dummy_only":
        raise PdbSubmitUnavailable(
            "Component registration is only available in the dummy_only write scope."
        )
    if not is_registrable_type(component_type, settings):
        raise PdbSubmitUnavailable(
            f"Refusing to register component type '{component_type}': only "
            f"{settings.pdb_dummy_component_types} may be registered as DUMMY test "
            "parts. Sensors and ASICs must never be registered by itkFlow."
        )
    institute = session.scalar(
        select(InstituteProfile).where(InstituteProfile.code == institute_code)
    )
    if institute is None:
        raise PdbSubmitUnavailable(f"Institute '{institute_code}' is not configured locally.")

    if client is not None and access_codes is not None:
        raise PdbSubmitUnavailable(
            "Provide either an authenticated PDB client or explicit access codes, not both."
        )
    if access_codes is not None and not settings.allow_pdb_writes:
        raise PdbSubmitUnavailable(
            "Explicit service credentials are reserved for opted-in PDB write tests."
        )
    if client is None:
        try:
            client = PdbGateway(settings, access_codes=access_codes).client()
        except Exception:
            raise PdbSubmitUnavailable(
                "The explicit PDB connection for DUMMY registration could not be opened."
            ) from None

    props = dict(properties or {})
    if local_name is not None:
        props.setdefault("LOCALNAME", local_name)
    response = _call_pdb(
        client.post,
        "registerComponent",
        json={
            "project": "S",
            "subproject": subproject,
            "institution": institute_code,
            "componentType": component_type,
            "type": type_code,
            "properties": props,
        },
        unavailable_message="The PDB component-registration request is temporarily unavailable.",
    )
    component = response.get("component", {}) if isinstance(response, dict) else {}
    sn = component.get("serialNumber")
    if not sn:
        raise PdbSubmitUnavailable(
            f"registerComponent returned no serial number (response keys: "
            f"{sorted(response) if isinstance(response, dict) else type(response).__name__})."
        )

    # Batch assignment (best effort — the local is_dummy flag is the actual
    # write gate; the PDB batch is for collaboration reporting hygiene).
    batch_id = _ensure_dummy_batch(client, institute_code, component_type)
    if batch_id:
        _call_pdb(
            client.post,
            "addBatchComponent",
            json={"component": sn, "id": batch_id},
            unavailable_message="The PDB batch-assignment request is temporarily unavailable.",
        )

    stage = component.get("currentStage") or {}
    stage_code = stage.get("code") if isinstance(stage, dict) else stage
    mirrored = Component(
        sn=sn,
        component_type=component_type,
        type_code=type_code,
        stage=stage_code or "UNKNOWN",
        location=institute_code,
        institute_code=institute_code,
        local_name=local_name,
        is_dummy=True,
        trashed=False,
        synced_at=utcnow(),
    )
    session.add(mirrored)
    session.commit()
    return mirrored
