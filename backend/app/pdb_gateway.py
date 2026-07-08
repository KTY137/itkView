"""PDB gateway — the only module allowed to talk to the ITk Production Database.

There is no PDB test server any more; the collaboration-sanctioned way to test
is against production, with writes confined to self-registered DUMMY-batch
components (docs/09). Safety layers, in order:

1. `Settings` refuses `pdb_instance="production"` without a second opt-in flag.
2. This gateway re-checks that guard at construction time.
3. For `pdb_instance="test"` the client is pinned to the (now defunct)
   test-instance URL — the default configuration therefore reaches nothing.
   For `production` the client uses itkdb's own defaults (which point at
   production) and only exists behind the double opt-in.
4. Writes are scoped separately in `app.pdb_submit` / `app.pdb_scope`:
   `pdb_write_scope="dummy_only"` restricts every write to itkFlow-registered
   DUMMY test components.

`itkdb` is an optional dependency (`pip install -e ".[pdb]"`); the offline
test suite never imports it.
"""

from typing import Any

from app.config import ProductionAccessError, Settings


class PdbGateway:
    def __init__(self, settings: Settings) -> None:
        if settings.pdb_instance == "production" and not settings.allow_production:
            raise ProductionAccessError(
                "PdbGateway refuses production PDB access without explicit opt-in."
            )
        self._settings = settings
        self._client: Any = None

    @property
    def instance(self) -> str:
        return self._settings.pdb_instance

    @property
    def is_configured(self) -> bool:
        """True when access codes for the configured instance are present."""
        return bool(self._settings.itkdb_access_code1 and self._settings.itkdb_access_code2)

    def client(self) -> Any:
        """Build (lazily) an itkdb client for the configured instance."""
        if not self.is_configured:
            raise ProductionAccessError(
                "No ITKDB access codes configured. Set ITKFLOW_ITKDB_ACCESS_CODE1/2."
            )
        if self._settings.pdb_instance == "production" and not self._settings.allow_production:
            # Settings already refuses this combination; re-checked defensively.
            raise ProductionAccessError(
                "PdbGateway refuses production PDB access without explicit opt-in."
            )
        if self._client is None:
            try:
                import itkdb
            except ImportError as exc:
                raise RuntimeError(
                    "itkdb is not installed. Install with: pip install -e '.[pdb]'"
                ) from exc
            user = itkdb.core.User(
                access_code1=self._settings.itkdb_access_code1,
                access_code2=self._settings.itkdb_access_code2,
            )
            if self._settings.pdb_instance == "production":
                # itkdb's own defaults point at the production PDB.
                self._client = itkdb.Client(user=user)
            else:
                # Pin the client to the test URL; never fall back to itkdb's
                # production default from a "test" configuration.
                self._client = itkdb.Client(user=user, prefix_url=self._settings.pdb_test_api_url)
        return self._client

    def verify_connection(self) -> dict:
        """Authenticate and fetch the caller's own user record. Read-only."""
        client = self.client()
        client.user.authenticate()
        identity = client.user.identity
        me = client.get("getUser", json={"userIdentity": identity})
        return {
            "instance": self.instance,
            "identity": identity,
            "first_name": me.get("firstName"),
            "last_name": me.get("lastName"),
            "institutions": [inst.get("code") for inst in me.get("institutions", [])],
        }
