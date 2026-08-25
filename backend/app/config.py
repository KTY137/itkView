"""Application settings.

Safety design: the PDB production instance is never reachable by default.
`pdb_instance` defaults to "test" (inert — that historical instance no longer
exists, so the default configuration cannot reach any PDB at all). Switching to
"production" is refused unless `allow_production` is also set — two deliberate
steps, both via environment variables, neither of which exists in any committed
file. Writes against production are additionally scoped by `pdb_write_scope`
(default `dummy_only`): only components itkFlow itself registered into a
DUMMY batch may ever be written to (see docs/09).
"""

from functools import lru_cache
from typing import Literal
from urllib.parse import urlparse

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# UI base URL of the PDB test instance (links shown to users).
PDB_TEST_UI_URL = "https://itkpd-test.unicorncollege.cz"
# Historically documented API base URL of the PDB test instance. As of 2026-07
# this hostname no longer resolves (the instance moved); override via
# ITKFLOW_PDB_TEST_API_URL once the current URL is known. itkdb's own default
# points at production, so we always pass an explicit prefix_url.
PDB_TEST_API_URL_DEFAULT = "https://itkpd-test.unicorncollege.cz/"

# Hosts that are (or front) the production PDB. A "test" URL pointing at any
# of these is refused outright — that is exactly the accident we guard against.
PDB_PRODUCTION_HOSTS = frozenset({"itkpd.unicornuniversity.net"})


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

    # --- PDB access -------------------------------------------------------
    pdb_instance: Literal["test", "production"] = "test"
    # Second, deliberate switch. Both must be set to reach production.
    allow_production: bool = False
    # API base URL of the PDB *test* instance (itkdb prefix_url).
    pdb_test_api_url: str = PDB_TEST_API_URL_DEFAULT
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

    # --- Outbox worker ----------------------------------------------------
    # Seconds the async submission worker sleeps between polling cycles.
    worker_poll_seconds: int = 5
    # Give up auto-processing an action after this many attempts (safety cap).
    worker_max_attempts: int = 5
    # Base retry delay for transient PDB outages; the worker doubles it after
    # each unavailable attempt until worker_max_attempts is reached.
    worker_retry_backoff_seconds: int = 60

    @model_validator(mode="after")
    def _guard_production(self) -> "Settings":
        if self.pdb_instance == "production" and not self.allow_production:
            raise ProductionAccessError(
                "Refusing to configure the production PDB: set ITKFLOW_PDB_INSTANCE=test, "
                "or additionally set ITKFLOW_ALLOW_PRODUCTION=true if this deployment is "
                "deliberately meant to write to production."
            )
        host = urlparse(self.pdb_test_api_url).hostname or ""
        if not self.pdb_test_api_url.startswith("https://"):
            raise ProductionAccessError("The PDB test API URL must use https.")
        if host in PDB_PRODUCTION_HOSTS:
            raise ProductionAccessError(
                f"ITKFLOW_PDB_TEST_API_URL points at the production host '{host}'. "
                "The test URL must never be a production endpoint."
            )
        return self

    @property
    def pdb_ui_url(self) -> str:
        if self.pdb_instance == "test":
            return PDB_TEST_UI_URL
        # Intentionally not preconfigured; a production deployment must supply it.
        raise ProductionAccessError("Production PDB UI URL is not preconfigured.")


@lru_cache
def get_settings() -> Settings:
    return Settings()
