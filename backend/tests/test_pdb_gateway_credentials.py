import sys
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.pdb_credentials import PdbAccessCodes
from app.pdb_gateway import PdbClientUnavailable, PdbGateway


class RecordingSession:
    def __init__(self) -> None:
        self.adapters = {}

    def mount(self, prefix, adapter) -> None:
        self.adapters[prefix] = adapter


class FakeUser:
    def __init__(self, *, access_code1: str, access_code2: str) -> None:
        self.access_code1 = access_code1
        self.access_code2 = access_code2
        self._session = RecordingSession()


class FakeClient(RecordingSession):
    """`itkdb.Client` really is a requests Session, so the double is one too.

    That is not incidental: the gateway binds its request timeout by walking
    the client's mounted adapters, and a double without them would hide a
    regression there rather than expose it.
    """

    def __init__(self, *, user: FakeUser, prefix_url: str | None = None) -> None:
        super().__init__()
        self.user = user
        self.prefix_url = prefix_url


def test_gateways_keep_two_users_credentials_isolated(monkeypatch):
    """A client is built only from the access codes explicitly bound to it."""

    fake_itkdb = SimpleNamespace(
        core=SimpleNamespace(User=FakeUser),
        Client=FakeClient,
    )
    monkeypatch.setitem(sys.modules, "itkdb", fake_itkdb)
    settings = Settings(
        itkdb_access_code1="legacy-global-1",
        itkdb_access_code2="legacy-global-2",
        # A client only exists for the production instance (offline builds
        # none); the itkdb module is faked, so nothing is reached.
        pdb_instance="production",
        allow_production=True,
        _env_file=None,
    )
    alice = PdbAccessCodes(access_code1="alice-1", access_code2="alice-2")
    bob = PdbAccessCodes(access_code1="bob-1", access_code2="bob-2")

    alice_client = PdbGateway(settings, access_codes=alice).client()
    bob_client = PdbGateway(settings, access_codes=bob).client()

    assert (alice_client.user.access_code1, alice_client.user.access_code2) == (
        "alice-1",
        "alice-2",
    )
    assert (bob_client.user.access_code1, bob_client.user.access_code2) == (
        "bob-1",
        "bob-2",
    )
    assert "legacy-global-1" not in {
        alice_client.user.access_code1,
        bob_client.user.access_code1,
    }


def test_missing_itkdb_dependency_is_a_local_client_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "itkdb", None)
    settings = Settings(pdb_instance="production", allow_production=True, _env_file=None)
    codes = PdbAccessCodes(access_code1="personal-one", access_code2="personal-two")

    with pytest.raises(PdbClientUnavailable, match="unavailable on this server"):
        PdbGateway(settings, access_codes=codes).client()


def test_built_client_has_a_bounded_request_timeout(monkeypatch):
    """Every client the gateway hands out must already be timeout-bounded.

    An unbounded client is not a visible failure: it works until one PDB read
    stalls, and then a whole sync sits there forever.
    """
    from app.pdb_gateway import PDB_REQUEST_TIMEOUT

    fake_itkdb = SimpleNamespace(core=SimpleNamespace(User=FakeUser), Client=FakeClient)
    monkeypatch.setitem(sys.modules, "itkdb", fake_itkdb)
    settings = Settings(pdb_instance="production", allow_production=True, _env_file=None)
    codes = PdbAccessCodes(access_code1="one", access_code2="two")

    client = PdbGateway(settings, access_codes=codes).client()

    assert set(client.adapters) >= {"http://", "https://"}
    for adapter in client.adapters.values():
        assert getattr(adapter, "_itkflow_timeout_bound", False), adapter
    assert PDB_REQUEST_TIMEOUT == (10, 60)
