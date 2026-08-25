"""The packaged desktop build serves the SPA from the backend origin."""

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.pdb_credentials import generate_pdb_credential_encryption_key

INDEX_HTML = "<!doctype html><title>itkFlow</title><div id=root></div>"


@pytest.fixture()
def spa_dir(tmp_path):
    (tmp_path / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "app.js").write_text("console.log('itkflow')", encoding="utf-8")
    (tmp_path / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    return tmp_path


def _client(static_dir=None) -> TestClient:
    settings = Settings(
        database_url="sqlite:///:memory:",
        pdb_credential_encryption_key=generate_pdb_credential_encryption_key(),
        static_dir=str(static_dir) if static_dir else None,
        _env_file=None,
    )
    return TestClient(create_app(settings))


def test_serves_index_at_root(spa_dir):
    response = _client(spa_dir).get("/")
    assert response.status_code == 200
    assert "itkFlow" in response.text


def test_serves_hashed_assets(spa_dir):
    response = _client(spa_dir).get("/assets/app.js")
    assert response.status_code == 200
    assert "itkflow" in response.text


def test_client_side_route_falls_back_to_index(spa_dir):
    # A deep link the user reloads on: no such file exists, the router owns it.
    response = _client(spa_dir).get("/components/20USEM00000435")
    assert response.status_code == 200
    assert "itkFlow" in response.text


def test_real_files_win_over_the_fallback(spa_dir):
    response = _client(spa_dir).get("/favicon.svg")
    assert response.status_code == 200
    assert response.text == "<svg/>"


def test_api_routes_are_not_shadowed(spa_dir):
    response = _client(spa_dir).get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_unknown_api_path_stays_404(spa_dir):
    # Must not become a 200 with the shell: that hides backend errors behind a
    # page that loads and then silently does nothing.
    response = _client(spa_dir).get("/api/does-not-exist")
    assert response.status_code == 404
    assert "<div id=root>" not in response.text


def test_path_traversal_is_refused(spa_dir):
    secret = spa_dir.parent / "outside.txt"
    secret.write_text("must not be served", encoding="utf-8")
    response = _client(spa_dir).get("/../outside.txt")
    assert "must not be served" not in response.text


def test_without_static_dir_root_is_not_served():
    response = _client().get("/")
    assert response.status_code == 404
