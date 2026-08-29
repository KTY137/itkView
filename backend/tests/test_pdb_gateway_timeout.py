# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-FileComment: itkflow-537009e61cdf
import pytest

from app.pdb_gateway import (
    PDB_REQUEST_TIMEOUT,
    PdbClientUnavailable,
    _bound_client_requests,
    _bound_user_auth_requests,
)


class RecordingAdapter:
    def __init__(self) -> None:
        self.received_timeout = None

    def send(self, request, **kwargs):
        self.received_timeout = kwargs.get("timeout")
        return self.received_timeout


class RecordingSession:
    def __init__(self) -> None:
        self.adapters = {}

    def mount(self, prefix, adapter) -> None:
        self.adapters[prefix] = adapter


class FakeUser:
    def __init__(self) -> None:
        self._session = RecordingSession()


def test_itkdb_auth_and_jwks_session_gets_default_timeout():
    """The separate itkdb auth session cannot wait forever before page 0."""

    user = FakeUser()
    _bound_user_auth_requests(user, adapter_base=RecordingAdapter)

    https_adapter = user._session.adapters["https://"]
    assert https_adapter.send(object()) == PDB_REQUEST_TIMEOUT
    assert https_adapter.send(object(), timeout=7) == 7


def test_api_client_session_gets_default_timeout():
    """A `client.get(...)` without a timeout must not block forever.

    `itkdb.Client` is a requests Session that forwards kwargs unchanged, so an
    unbounded read is the default. One stalled call freezes an entire bulk
    sync mid-run.
    """

    client = RecordingSession()
    _bound_client_requests(client, adapter_base=RecordingAdapter)

    https_adapter = client.adapters["https://"]
    assert https_adapter.send(object()) == PDB_REQUEST_TIMEOUT


def test_api_client_keeps_an_explicit_timeout():
    client = RecordingSession()
    _bound_client_requests(client, adapter_base=RecordingAdapter)

    assert client.adapters["https://"].send(object(), timeout=3) == 3


def test_both_http_and_https_are_bound():
    client = RecordingSession()
    _bound_client_requests(client, adapter_base=RecordingAdapter)

    assert set(client.adapters) == {"http://", "https://"}


def test_a_client_without_mount_is_refused():
    # Better a clear local error than a silently unbounded client.
    with pytest.raises(PdbClientUnavailable):
        _bound_client_requests(object(), adapter_base=RecordingAdapter)


class PrefixSession:
    """A session that already has a route-specific adapter, like itkdb's."""

    def __init__(self, adapters):
        self.adapters = dict(adapters)

    def mount(self, prefix, adapter):
        self.adapters[prefix] = adapter


class ConfiguredAdapter:
    """Stands in for itkdb's CacheControlAdapter: configured, not replaceable."""

    def __init__(self, marker="cache"):
        self.marker = marker
        self.received_timeout = None

    def send(self, request, **kwargs):
        self.received_timeout = kwargs.get("timeout")
        return self.received_timeout


def test_a_route_specific_adapter_is_bounded_too():
    """The bug this guards: requests picks the LONGEST matching prefix.

    itkdb mounts its own adapter for the PDB base URL, so mounting a generic
    "https://" adapter leaves every real API call unbounded — a single stalled
    read then freezes a whole bulk sync, which is exactly what happened.
    """
    pdb_adapter = ConfiguredAdapter()
    session = PrefixSession({"https://itkpd.unicornuniversity.net/": pdb_adapter})

    _bound_client_requests(session, adapter_base=RecordingAdapter)

    assert pdb_adapter.send(object()) == PDB_REQUEST_TIMEOUT


def test_the_configured_adapter_instance_is_kept():
    """Replacing it would throw itkdb's response cache away."""
    pdb_adapter = ConfiguredAdapter(marker="keep-me")
    session = PrefixSession({"https://itkpd.unicornuniversity.net/": pdb_adapter})

    _bound_client_requests(session, adapter_base=RecordingAdapter)

    kept = session.adapters["https://itkpd.unicornuniversity.net/"]
    assert kept is pdb_adapter
    assert kept.marker == "keep-me"


def test_a_route_specific_adapter_keeps_an_explicit_timeout():
    pdb_adapter = ConfiguredAdapter()
    session = PrefixSession({"https://itkpd.unicornuniversity.net/": pdb_adapter})

    _bound_client_requests(session, adapter_base=RecordingAdapter)

    assert pdb_adapter.send(object(), timeout=5) == 5


def test_binding_twice_does_not_stack_wrappers():
    pdb_adapter = ConfiguredAdapter()
    session = PrefixSession({"https://itkpd.unicornuniversity.net/": pdb_adapter})

    _bound_client_requests(session, adapter_base=RecordingAdapter)
    once = pdb_adapter.send
    _bound_client_requests(session, adapter_base=RecordingAdapter)

    assert pdb_adapter.send is once
    assert pdb_adapter.send(object()) == PDB_REQUEST_TIMEOUT


def test_generic_prefixes_are_added_when_absent():
    session = PrefixSession({"https://itkpd.unicornuniversity.net/": ConfiguredAdapter()})

    _bound_client_requests(session, adapter_base=RecordingAdapter)

    # Anything the client reaches outside the PDB base URL stays bounded too.
    assert set(session.adapters) >= {"http://", "https://"}
