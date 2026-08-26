"""Application settings.

Safety design: the code-level default reaches no PDB at all. `pdb_instance`
defaults to "offline" — there is no PDB test service anymore, so the only real
instance is production, and reaching it takes two deliberate switches
(`pdb_instance=production` plus `allow_production`). Dev environments, tests
and agent sessions therefore stay inert by construction; the shipped end-user
artifacts (desktop bundle, Compose) enable production *reads* explicitly (see
docs/09 — reads still require each person's own access codes, so an instance
without connected accounts contacts nothing). Writes against production are
additionally scoped by `pdb_write_scope` (default `dummy_only`): only
components itkFlow itself registered into a DUMMY batch may ever be written.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ProductionAccessError(RuntimeError):
    """Raised when production PDB access is requested without explicit opt-in."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ITKFLOW_", env_file=".env", extra="ignore")

    app_name: str = "itkFlow"
    database_url: str = "sqlite:///./itkflow.db"

    # --- Auth / sessions --------------------------------------------------
    # Mark the login (and CSRF) cookies `Secure` so browsers only send them over
    # HTTPS. Default False keeps local http dev working; set True behind TLS
    # (remote access, docs/08).
    session_cookie_secure: bool = False

    # --- Desktop / static hosting -----------------------------------------
    # Directory holding the built frontend (Vite `dist`). When set, the backend
    # serves the SPA from its own origin, which is how the packaged desktop
    # build works. Unset in Compose: nginx serves the SPA there.
    static_dir: str | None = None
    # Directory for test-run attachments mirrored from the PDB (images, IV
    # plots, instrument output). Kept on disk rather than in the database so a
    # person can open the folder and look at them directly. Unset falls back to
    # `attachments/` beside the application data.
    attachment_dir: str | None = None
    # Bound unauthenticated share-link downloads and all mirrored payloads.
    # A URL-valued PDB result is untrusted input; neither an endless response
    # nor an unexpectedly large file may occupy the sync worker indefinitely.
    attachment_download_timeout_seconds: int = 60
    attachment_max_bytes: int = 100 * 1024 * 1024

    # --- PDB access -------------------------------------------------------
    # "offline" reaches no PDB (dev/test default). The retired "test" instance
    # is not a valid value anymore — it no longer exists.
    pdb_instance: Literal["offline", "production"] = "offline"
    # Second, deliberate switch. Both must be set to reach production.
    allow_production: bool = False
    # Explicit credentials for manually opted-in PDB integration tests only.
    # Web requests, sync jobs and the production worker never fall back to
    # these deployment-wide values (ADR 004).
    itkdb_access_code1: str | None = None
    itkdb_access_code2: str | None = None
    # Master key for per-user PDB access codes stored in the local database.
    # It must be a URL-safe base64-encoded 32-byte key and is only supplied via
    # ITKFLOW_PDB_CREDENTIAL_ENCRYPTION_KEY. SecretStr keeps settings reprs and
    # validation errors from disclosing the value.
    pdb_credential_encryption_key: SecretStr | None = None

    # --- PDB write scope ----------------------------------------------------
    # "dummy_only": writes (test-run uploads, stage moves) are refused unless
    # the target is a component itkFlow itself registered into a DUMMY batch
    # (mirror flag `is_dummy=True`). "unrestricted" is accepted as a value but
    # deliberately not implemented — real production writes need their own,
    # conscious release step.
    pdb_write_scope: Literal["dummy_only", "unrestricted"] = "dummy_only"
    # Opt-in read by the pdb_write end-to-end test only; nothing writes without it.
    allow_pdb_writes: bool = False
    # Component types itkFlow may register as DUMMY test components. Sensors
    # and ASICs are never allowed here: there is no dummy mechanism for them
    # and registering one corrupts collaboration serial numbering.
    pdb_dummy_component_types: list[str] = ["MODULE", "HYBRID"]

    # --- Sync tuning ------------------------------------------------------
    # Transient-failure retry budget per PDB listing page during component
    # syncs. Raise it on an unreliable connection; each retry backs off
    # exponentially before the page is requested again.
    sync_page_max_attempts: int = Field(default=3, ge=1, le=10)

    # --- Outbox worker ----------------------------------------------------
    # Which process submits approved outbox actions to the PDB:
    #   "worker" — the standalone `app.run_worker` service (Compose runs one).
    #   "app"    — the API process drains the outbox itself. The desktop bundle
    #              and the dev launcher run no worker, so without this a
    #              reviewed action would reach `submitted` and never be pushed.
    #   "off"    — nobody submits (tests).
    # Exactly one process should drain; actions are claimed transactionally, so
    # a misconfiguration cannot submit the same action twice.
    outbox_processor: Literal["worker", "app", "off"] = "worker"
    # Seconds the async submission worker sleeps between polling cycles.
    worker_poll_seconds: int = 5
    # Give up auto-processing an action after this many attempts (safety cap).
    worker_max_attempts: int = 5
    # Base retry delay for transient PDB outages; the worker doubles it after
    # each unavailable attempt until worker_max_attempts is reached.
    worker_retry_backoff_seconds: int = 60

    # --- Local operations telemetry --------------------------------------
    # A worker/scheduler heartbeat remains healthy through this age.  The
    # operations endpoint only reads this local telemetry; it never turns a
    # dashboard refresh into a live PDB probe.
    ops_heartbeat_stale_seconds: int = Field(default=180, ge=1, le=86_400)

    # --- Notifications / reminders -----------------------------------------
    # Timeout for one outbound notification webhook POST (Mattermost etc.).
    # Small on purpose: a slow endpoint must not stall the worker's poll loop.
    notify_timeout_seconds: int = 10
    # Which process fires due reminders (docs/11):
    #   "worker" — the standalone outbox worker ticks them (Compose runs one).
    #   "app"    — the API process ticks them itself. The desktop bundle and the
    #              dev launcher run no worker at all, so without this a
    #              scheduled reminder would simply never fire there.
    #   "off"    — nobody ticks (tests, or reminders managed elsewhere).
    # Exactly one process should tick. A misconfiguration cannot double-send:
    # each occurrence is claimed transactionally before it is delivered.
    reminder_scheduler: Literal["worker", "app", "off"] = "worker"
    # Seconds the in-app scheduler sleeps between reminder ticks. Reminders are
    # due-time based, so this only bounds how late one may fire.
    reminder_poll_seconds: int = 60

    @model_validator(mode="after")
    def _guard_production(self) -> "Settings":
        if self.pdb_instance == "production" and not self.allow_production:
            raise ProductionAccessError(
                "Refusing to configure the production PDB: set "
                "ITKFLOW_PDB_INSTANCE=offline, or additionally set "
                "ITKFLOW_ALLOW_PRODUCTION=true if this deployment is deliberately "
                "meant to reach production."
            )
        return self

    @property
    def pdb_ui_url(self) -> str:
        if self.pdb_instance != "production":
            raise ProductionAccessError("No PDB is configured for this deployment.")
        # Intentionally not preconfigured; a production deployment must supply it.
        raise ProductionAccessError("Production PDB UI URL is not preconfigured.")


@lru_cache
def get_settings() -> Settings:
    return Settings()
