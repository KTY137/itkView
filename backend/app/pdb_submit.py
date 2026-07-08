"""Real PDB submitter — performs `uploadTestRunResults` against the PDB *test*
instance for an `upload_test_run` outbox action.

This is the default `Submitter` wired into the standalone worker; the offline
test suite injects a fake instead, so this module is never exercised without
configured access codes. It mirrors `app.pdb_sync`: the itkdb client is built
lazily and pinned to the test instance by `PdbGateway`, and a missing/unusable
configuration surfaces as `PdbSubmitUnavailable` (nothing is written).
"""

from typing import Any

from app.config import Settings
from app.models import IngestFile, OutboxAction
from app.outbox_worker import PdbSubmitUnavailable, SubmitOutcome, Submitter
from app.pdb_gateway import PdbGateway


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


def make_pdb_submitter(settings: Settings) -> Submitter:
    """Build a `Submitter` bound to these settings (used by the worker loop)."""

    def submit(session, action: OutboxAction) -> SubmitOutcome:
        if action.kind != "upload_test_run":
            # No PDB write path defined for this kind yet; refuse rather than
            # guess. Transient so it is not marked as a data rejection.
            raise PdbSubmitUnavailable(f"No PDB submitter for action kind '{action.kind}'.")

        ingest_id = action.payload.get("ingest_file_id")
        ingest = session.get(IngestFile, ingest_id) if ingest_id is not None else None
        if ingest is None:
            return SubmitOutcome.rejected("The ingest file backing this action no longer exists.")

        gateway = PdbGateway(settings)
        if not gateway.is_configured:
            raise PdbSubmitUnavailable(
                "No ITKDB access codes configured for the PDB test instance. "
                "Set ITKFLOW_ITKDB_ACCESS_CODE1/2 to enable uploads."
            )
        try:
            client = gateway.client()
        except RuntimeError as exc:  # ProductionAccessError or missing itkdb
            raise PdbSubmitUnavailable(str(exc)) from exc

        try:
            response = client.post("uploadTestRunResults", json=ingest.payload)
        except Exception as exc:
            # The PDB was reachable but refused the payload (validation, stage,
            # permissions). A data rejection, not a transient outage.
            return SubmitOutcome.rejected(f"PDB rejected the upload: {exc}")

        return SubmitOutcome.confirmed(_extract_run_ref(response))

    return submit
