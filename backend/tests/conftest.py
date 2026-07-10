import pytest
from authutil import authenticate
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.main import create_app


@pytest.fixture()
def client() -> TestClient:
    settings = Settings(database_url="sqlite:///:memory:", _env_file=None)
    app = create_app(settings)
    return TestClient(app)


@pytest.fixture()
def session_factory(client: TestClient) -> sessionmaker[Session]:
    """Sessions on the same in-memory database the client's app uses."""
    return client.app.state.session_factory


@pytest.fixture()
def tudo(client: TestClient) -> dict:
    response = client.post(
        "/api/institutes",
        json={"code": "TUDO", "name": "TU Dortmund", "local_name_prefix": "TUDO-"},
    )
    assert response.status_code == 201, response.text
    return response.json()


# Role-scoped clients: each signs the shared `client` in and pins its CSRF token
# so gated writes work. Institute-agnostic (institute_id=None) — tests that need
# an institute still request the `tudo` fixture (docs/06).


@pytest.fixture()
def as_operator(client: TestClient, session_factory) -> TestClient:
    authenticate(client, session_factory, role="operator")
    return client


@pytest.fixture()
def as_admin(client: TestClient, session_factory) -> TestClient:
    authenticate(client, session_factory, role="admin")
    return client


@pytest.fixture()
def as_viewer(client: TestClient, session_factory) -> TestClient:
    authenticate(client, session_factory, role="viewer")
    return client
