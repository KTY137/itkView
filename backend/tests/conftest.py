import pytest
from authutil import authenticate, create_institute_profile
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.main import create_app
from app.pdb_credentials import (
    PdbAccessCodes,
    generate_pdb_credential_encryption_key,
    save_pdb_credentials,
)


@pytest.fixture(autouse=True)
def shared_core_tests_use_explicit_flow(monkeypatch):
    """Keep legacy writer tests explicit while the shipped repo defaults View."""

    monkeypatch.setenv("ITKFLOW_PRODUCT_VARIANT", "flow")


@pytest.fixture()
def client() -> TestClient:
    settings = Settings(
        database_url="sqlite:///:memory:",
        pdb_credential_encryption_key=generate_pdb_credential_encryption_key(),
        _env_file=None,
    )
    app = create_app(settings)
    return TestClient(app)


@pytest.fixture()
def session_factory(client: TestClient) -> sessionmaker[Session]:
    """Sessions on the same in-memory database the client's app uses."""
    return client.app.state.session_factory


@pytest.fixture()
def tudo(session_factory: sessionmaker[Session]) -> dict:
    return create_institute_profile(
        session_factory,
        code="TUDO",
        name="TU Dortmund",
        local_name_prefix="TUDO-",
    )


# Role-scoped clients: each signs the shared `client` in and pins its CSRF token
# so gated writes work. Institute-agnostic (institute_id=None) — tests that need
# an institute still request the `tudo` fixture (docs/06).


def _connect_test_pdb_account(
    client: TestClient,
    session_factory: sessionmaker[Session],
    user_id: int,
) -> None:
    """Give role fixtures an isolated fake connection for offline PDB-path tests."""
    with session_factory() as session:
        save_pdb_credentials(
            session,
            user_id=user_id,
            access_codes=PdbAccessCodes(
                f"offline-code-1-user-{user_id}",
                f"offline-code-2-user-{user_id}",
            ),
            pdb_identity=f"offline-pdb-user-{user_id}",
            institutions=(),
            encryption_key=client.app.state.settings.pdb_credential_encryption_key,
        )
        session.commit()


@pytest.fixture()
def as_operator(client: TestClient, session_factory) -> TestClient:
    me = authenticate(client, session_factory, role="operator")
    _connect_test_pdb_account(client, session_factory, me["id"])
    return client


@pytest.fixture()
def as_admin(client: TestClient, session_factory) -> TestClient:
    me = authenticate(client, session_factory, role="admin")
    _connect_test_pdb_account(client, session_factory, me["id"])
    return client


@pytest.fixture()
def as_viewer(client: TestClient, session_factory) -> TestClient:
    authenticate(client, session_factory, role="viewer")
    return client
