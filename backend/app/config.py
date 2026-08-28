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

    product_variant: Literal["flow", "view"] = "view"
    app_name: str = "itkView"
    database_url: str = "sqlite:///./itkview.db"

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
    # "disabled": no PDB mutation path is available (forced by itkView).
    # "dummy_only": writes (test-run uploads, stage moves) are refused unless
    # the target is a component itkFlow itself registered into a DUMMY batch
    # (mirror flag `is_dummy=True`). "unrestricted" is accepted as a value but
    # deliberately not implemented — real production writes need their own,
    # conscious release step.
    pdb_write_scope: Literal["disabled", "dummy_only", "unrestricted"] = "dummy_only"
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
    # Concurrent per-component evidence fetches (getComponent plus per-run
    # getTestRun) during the institute evidence sweep. These are independent
    # network reads; every fetch worker builds its own PDB client (itkdb
    # clients subclass requests.Session and are not thread-safe) and all
    # database writes stay on the job thread. 1 restores the fully serial
    # sweep; the small default keeps the load on the production PDB modest
    # while cutting a multi-hour sweep down by roughly that factor.
    sync_fetch_concurrency: int = Field(default=4, ge=1, le=16)
    # How often the unattended-refresh scheduler WAKES UP to evaluate the
    # institute profiles. This is a database query, not PDB traffic: whether a
    # sweep actually runs is decided per institute by
    # `settings["auto_sync"]` (Admin Settings), which is absent by default.
    # `0` switches the scheduler off entirely as a deployment escape hatch.
    auto_sync_poll_minutes: int = Field(default=5, ge=0, le=1440)
    # How the institute evidence sweep learns which test runs exist.
    #   "index_bulk"     — ask `listTestRunsByComponent` for a whole batch of
    #                      serial numbers at once, then pull the detail of the
    #                      new/changed runs through `getTestRunBulk`. Roughly
    #                      one request per 300 runs instead of one per
    #                      component. Anything the batched answer cannot prove
    #                      complete is re-read through the per-component path,
    #                      so this can be slower than expected but never
    #                      mirrors less (docs/09).
    #   "per_component"  — the proven `getComponent`-per-component sweep, kept
    #                      as a one-setting escape hatch because the batched
    #                      endpoints could not be validated against a live PDB.
    sync_evidence_strategy: Literal["index_bulk", "per_component"] = "index_bulk"
    # Serial numbers per `listTestRunsByComponent` request. Bounded because the
    # filter travels in the request body and an unbounded IN-list is exactly
    # the shape a server silently truncates.
    sync_evidence_index_batch_size: int = Field(default=50, ge=1, le=500)
    # Page size for the paginated test-run index. A batch whose answer arrives
    # without pagination metadata is only trusted when it does not exactly fill
    # this page, so raising it also widens that safety margin.
    sync_evidence_index_page_size: int = Field(default=100, ge=10, le=500)
    # Test-run ids per `getTestRunBulk` request. Ids the bulk answer omits fall
    # back to one `getTestRun` each, so a modest batch keeps that repair cheap.
    sync_evidence_bulk_batch_size: int = Field(default=50, ge=1, le=200)

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
        if self.product_variant == "view":
            if self.app_name == "itkFlow":
                self.app_name = "itkView"
            self.outbox_processor = "off"
            self.reminder_scheduler = "off"
            self.allow_pdb_writes = False
            self.pdb_write_scope = "disabled"
        else:
            # The dedicated itkView repository defaults above must not leak
            # into an explicitly requested shared-core Flow regression build.
            if self.app_name == "itkView":
                self.app_name = "itkFlow"
            if self.database_url == "sqlite:///./itkview.db":
                # An explicit local Flow regression must not open View's
                # mirror or inherit its accounts/outbox by accident.
                self.database_url = "sqlite:///./itkflow.db"
        return self

    @property
    def pdb_writes_enabled(self) -> bool:
        """Whether this product may ever open a PDB mutation sink."""

        return self.product_variant == "flow"


@lru_cache
def get_settings() -> Settings:
    return Settings()
