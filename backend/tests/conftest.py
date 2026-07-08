import pytest
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
