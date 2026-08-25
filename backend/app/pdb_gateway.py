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

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.config import ProductionAccessError, Settings

if TYPE_CHECKING:
    from app.pdb_credentials import PdbAccessCodes

PDB_REQUEST_TIMEOUT = (10, 60)  # connect seconds, read seconds


class PdbClientUnavailable(RuntimeError):
    """The server-side itkdb client is missing or cannot be initialized."""


def _http_adapter_class(adapter_base: type | None = None) -> type:
    """The adapter class to mount where a session has none.

    The import stays local so the offline/base install still need not provide
    the optional itkdb/requests dependency.
    """

    if adapter_base is not None:
        return adapter_base
    try:
        from requests.adapters import HTTPAdapter
    except ImportError:  # pragma: no cover - itkdb itself requires requests
        raise PdbClientUnavailable(
            "ITKDB client support is incomplete on this server."
        ) from None
    return HTTPAdapter


def _wrap_adapter_send(adapter: Any) -> None:
    """Make one already-mounted adapter apply the default timeout.

    Wrapping the instance rather than replacing it matters: itkdb mounts a
    configured `CacheControlAdapter` for the PDB base URL, and re-creating that
    adapter would throw its cache away.
    """
    if getattr(adapter, "_itkflow_timeout_bound", False):
        return
    original_send = adapter.send

    def send(request, **kwargs):
        if kwargs.get("timeout") is None:
            kwargs["timeout"] = PDB_REQUEST_TIMEOUT
        return original_send(request, **kwargs)

    adapter.send = send
    adapter._itkflow_timeout_bound = True


def _bind_default_timeout(session: Any, adapter_base: type | None = None) -> None:
    """Bound every route this session can take, not just the generic ones.

    `requests` picks the adapter with the *longest* matching prefix. itkdb
    mounts one for the PDB base URL specifically, so a plain
    ``mount("https://", ...)`` is silently shadowed for exactly the requests we
    care about — the API calls — and leaves them unbounded. Every existing
    adapter is therefore wrapped in place, and the generic prefixes are only
    added when the session has none.
    """
    adapters = getattr(session, "adapters", None)
    if adapters is None:
        raise PdbClientUnavailable(
            "The installed ITKDB client has no configurable request session."
        )

    # Fill the generic routes first, then bind every adapter through the one
    # mechanism. Mounting a pre-bounded subclass instead would leave two ways
    # for an adapter to be "bounded" and only one of them observable.
    missing = [prefix for prefix in ("http://", "https://") if prefix not in adapters]
    if missing:
        adapter_cls = _http_adapter_class(adapter_base)
        for prefix in missing:
            session.mount(prefix, adapter_cls())

    for adapter in list(session.adapters.values()):
        _wrap_adapter_send(adapter)


def _bound_user_auth_requests(user: Any, adapter_base: type | None = None) -> None:
    """Apply the PDB timeout to itkdb's private auth/JWKS session.

    ``Client.get(..., timeout=...)`` does not cover ``User.authenticate()``:
    itkdb 0.6.20 performs its grant-token POST and JWKS GET through a separate
    requests Session. Replacing that Session's default adapters keeps both
    internal calls bounded without changing explicit per-request timeouts.
    """

    auth_session = getattr(user, "_session", None)
    if auth_session is None or not hasattr(auth_session, "mount"):
        raise PdbClientUnavailable(
            "The installed ITKDB client has no configurable authentication session."
        )
    _bind_default_timeout(auth_session, adapter_base)


def _bound_client_requests(client: Any, adapter_base: type | None = None) -> None:
    """Apply the PDB timeout to the API client's own session.

    `itkdb.Client` subclasses `requests.Session` and forwards call kwargs
    unchanged, so a `client.get(...)` without an explicit timeout blocks
    forever. A single stalled read is enough to freeze a bulk sync mid-run.
    Callers that do pass a timeout keep theirs.
    """

    _bind_default_timeout(client, adapter_base)


class PdbGateway:
    def __init__(
        self,
        settings: Settings,
        *,
        access_codes: PdbAccessCodes | None = None,
    ) -> None:
        if settings.pdb_instance == "production" and not settings.allow_production:
            raise ProductionAccessError(
                "PdbGateway refuses production PDB access without explicit opt-in."
            )
        self._settings = settings
        # Credentials are deliberately supplied by the authenticated operation.
        # Never fall back to deployment-wide Settings values: doing so would make
        # a request or worker action run as whichever person owns the server env.
        self._access_codes = access_codes
        self._client: Any = None

    @property
    def instance(self) -> str:
        return self._settings.pdb_instance

    @property
    def is_configured(self) -> bool:
        """True when this operation received a complete personal credential."""
        return bool(
            self._access_codes is not None
            and self._access_codes.access_code1
            and self._access_codes.access_code2
        )

    def client(self) -> Any:
        """Build (lazily) an itkdb client for the configured instance."""
        if not self.is_configured:
            raise ProductionAccessError(
                "No personal ITKDB access codes are connected for this account."
            )
        if self._settings.pdb_instance == "production" and not self._settings.allow_production:
            # Settings already refuses this combination; re-checked defensively.
            raise ProductionAccessError(
                "PdbGateway refuses production PDB access without explicit opt-in."
            )
        if self._client is None:
            try:
                import itkdb
            except ImportError:
                # ImportError can also mean that itkdb itself is present but one
                # of its transitive dependencies is missing. Keep that local
                # deployment problem distinct from a remote PDB outage.
                raise PdbClientUnavailable(
                    "ITKDB client support is unavailable on this server. "
                    "Install the backend with its 'pdb' extra."
                ) from None
            user = itkdb.core.User(
                access_code1=self._access_codes.access_code1,
                access_code2=self._access_codes.access_code2,
            )
            _bound_user_auth_requests(user)
            if self._settings.pdb_instance == "production":
                # itkdb's own defaults point at the production PDB.
                client = itkdb.Client(user=user)
            else:
                # Pin the client to the test URL; never fall back to itkdb's
                # production default from a "test" configuration.
                client = itkdb.Client(user=user, prefix_url=self._settings.pdb_test_api_url)
            _bound_client_requests(client)
            self._client = client
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
