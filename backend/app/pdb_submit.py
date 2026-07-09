"""Real PDB submitter — writes reviewed outbox actions to the PDB.

Dispatches by action kind:

- `upload_test_run` -> `uploadTestRunResults`
- `stage_move`      -> `setComponentStage`

Write scope (docs/09, ADR 003): with `pdb_write_scope="dummy_only"` (the
default) every write is refused unless its target component is an
itkFlow-registered DUMMY test component (`app.pdb_scope.is_dummy_target`).
"unrestricted" is deliberately not implemented. `register_dummy_component`
is the only way a new PDB component comes into existence through itkFlow —
hybrids/modules only, always in the institute's DUMMY batch.

This is the default `Submitter` wired into the standalone worker; the offline
test suite injects a fake instead, so this module is never exercised without
configured access codes. A missing/unusable configuration surfaces as
`PdbSubmitUnavailable` (nothing is written).
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Component, IngestFile, InstituteProfile, OutboxAction, utcnow
from app.outbox_worker import PdbSubmitUnavailable, SubmitOutcome, Submitter
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


def make_pdb_submitter(settings: Settings) -> Submitter:
    """Build a `Submitter` bound to these settings (used by the worker loop)."""

    def _client():
        if settings.pdb_write_scope != "dummy_only":
            # "unrestricted" is a recognised value but real production writes
            # are deliberately not implemented (docs/09).
            raise PdbSubmitUnavailable(
                "pdb_write_scope='unrestricted' is deliberately not implemented; "
                "PDB writes are confined to DUMMY test components."
            )
        gateway = PdbGateway(settings)
        if not gateway.is_configured:
            raise PdbSubmitUnavailable(
                "No ITKDB access codes configured. "
                "Set ITKFLOW_ITKDB_ACCESS_CODE1/2 to enable writes."
            )
        try:
            return gateway.client()
        except RuntimeError as exc:  # ProductionAccessError or missing itkdb
            raise PdbSubmitUnavailable(str(exc)) from exc

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
        client = _client()
        try:
            response = client.post("uploadTestRunResults", json=upload_payload)
        except Exception as exc:
            # Reachable but refused (validation/stage/permissions) — a rejection.
            return SubmitOutcome.rejected(f"PDB rejected the upload: {exc}")
        return SubmitOutcome.confirmed(_extract_run_ref(response))

    def _submit_stage_move(session, action: OutboxAction) -> SubmitOutcome:
        payload = action.payload or {}
        sn = payload.get("sn")
        to_stage = payload.get("to_stage")
        if not sn or not to_stage:
            return SubmitOutcome.rejected("stage_move payload is missing 'sn' or 'to_stage'.")
        if not is_dummy_target(session, sn):
            return _scope_rejection(sn)
        client = _client()
        try:
            client.post(
                "setComponentStage",
                json={"component": sn, "stage": to_stage, "rework": bool(payload.get("rework"))},
            )
        except Exception as exc:
            return SubmitOutcome.rejected(f"PDB rejected the stage move: {exc}")
        return SubmitOutcome.confirmed(to_stage)

    def submit(session, action: OutboxAction) -> SubmitOutcome:
        if action.kind == "upload_test_run":
            return _submit_upload(session, action)
        if action.kind == "stage_move":
            return _submit_stage_move(session, action)
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
    listing = client.get(
        "listBatches",
        json={
            "filterMap": {
                "project": "S",
                "number": number,
                "ownerInstitute": [institute_code],
                "batchType": [batch_type],
            }
        },
    )
    items = listing.get("itemList", []) if isinstance(listing, dict) else list(listing)
    if items:
        return items[0]["id"]
    created = client.post(
        "createBatch",
        json={
            "number": number,
            "batchType": batch_type,
            "ownerInstituteList": [institute_code],
            "project": "S",
        },
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

    gateway = PdbGateway(settings)
    if not gateway.is_configured:
        raise PdbSubmitUnavailable("No ITKDB access codes configured.")
    client = gateway.client()

    props = dict(properties or {})
    if local_name is not None:
        props.setdefault("LOCALNAME", local_name)
    response = client.post(
        "registerComponent",
        json={
            "project": "S",
            "subproject": subproject,
            "institution": institute_code,
            "componentType": component_type,
            "type": type_code,
            "properties": props,
        },
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
        client.post("addBatchComponent", json={"component": sn, "id": batch_id})

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
