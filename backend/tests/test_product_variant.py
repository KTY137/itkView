"""Server-enforced itkFlow/itkView product boundary."""

import re

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app import run_worker
from app.api import router
from app.config import Settings
from app.main import create_app
from app.outbox_worker import PdbSubmitUnavailable
from app.pdb_credentials import generate_pdb_credential_encryption_key
from app.pdb_submit import make_pdb_submitter, register_dummy_component
from app.product_policy import (
    ROUTE_CAPABILITIES,
    UNSAFE_METHODS,
    VIEW_ALLOWED_CAPABILITIES,
    RouteCapability,
    request_capability,
    route_capability,
)

CONTROL_PLANE_ROUTES = {
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/logout"),
    ("POST", "/api/setup/admin"),
    ("PUT", "/api/account/pdb-connection"),
    ("POST", "/api/account/pdb-connection/test"),
    ("DELETE", "/api/account/pdb-connection"),
    ("PUT", "/api/account/share-credentials"),
    ("DELETE", "/api/account/share-credentials/{credential_id}"),
    ("POST", "/api/users"),
    ("PATCH", "/api/users/{user_id}"),
    ("POST", "/api/institutes"),
    ("PATCH", "/api/institutes/{code}"),
}

MIRROR_REFRESH_ROUTES = {
    ("POST", "/api/sync/jobs/components/{institute_code}"),
    ("POST", "/api/sync/jobs/evidence/{institute_code}"),
    ("POST", "/api/sync/components/{institute_code}"),
    ("POST", "/api/sync/tools/{institute_code}"),
    ("POST", "/api/test-types/sync"),
    ("POST", "/api/components/{sn}/attachments/sync"),
    ("POST", "/api/components/{sn}/sync-evidence"),
    ("POST", "/api/sync/evidence/{institute_code}"),
    ("POST", "/api/sync/shipments/{institute_code}"),
}


def _settings(variant: str = "view", **overrides) -> Settings:
    values = {
        "product_variant": variant,
        "database_url": "sqlite:///:memory:",
        "pdb_credential_encryption_key": generate_pdb_credential_encryption_key(),
        "auto_sync_poll_minutes": 0,
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


def _client(variant: str = "view") -> TestClient:
    return TestClient(create_app(_settings(variant)))


def _concrete_path(route_path: str) -> str:
    return re.sub(r"\{[^}]+\}", "1", route_path)


def test_view_is_the_dedicated_repository_default(monkeypatch) -> None:
    monkeypatch.delenv("ITKFLOW_PRODUCT_VARIANT", raising=False)
    settings = Settings(_env_file=None)

    assert settings.product_variant == "view"
    assert settings.app_name == "itkView"
    assert settings.database_url == "sqlite:///./itkview.db"
    assert settings.pdb_write_scope == "disabled"
    assert settings.pdb_writes_enabled is False
    assert settings.outbox_processor == "off"
    assert settings.reminder_scheduler == "off"


def test_flow_remains_available_only_when_explicitly_selected() -> None:
    settings = Settings(product_variant="flow", _env_file=None)

    assert settings.product_variant == "flow"
    assert settings.app_name == "itkFlow"
    assert settings.database_url == "sqlite:///./itkflow.db"
    assert settings.pdb_write_scope == "dummy_only"
    assert settings.pdb_writes_enabled is True
    assert settings.outbox_processor == "worker"
    assert settings.reminder_scheduler == "worker"


def test_explicit_flow_never_inherits_the_view_database_default() -> None:
    settings = Settings(
        product_variant="flow",
        app_name="Shared core regression",
        _env_file=None,
    )

    assert settings.app_name == "Shared core regression"
    assert settings.database_url == "sqlite:///./itkflow.db"


def test_view_forces_every_background_and_pdb_write_switch_off() -> None:
    settings = _settings(
        outbox_processor="app",
        reminder_scheduler="app",
        allow_pdb_writes=True,
        pdb_write_scope="unrestricted",
    )

    assert settings.app_name == "itkView"
    assert settings.outbox_processor == "off"
    assert settings.reminder_scheduler == "off"
    assert settings.allow_pdb_writes is False
    assert settings.pdb_write_scope == "disabled"
    assert settings.pdb_writes_enabled is False


def test_every_unsafe_api_route_has_an_explicit_policy_classification() -> None:
    actual = {
        (method, route.path)
        for route in router.routes
        if isinstance(route, APIRoute)
        for method in route.methods.intersection(UNSAFE_METHODS)
    }

    assert set(ROUTE_CAPABILITIES) == actual


def test_view_allowlist_is_only_control_plane_and_exact_read_sync_posts() -> None:
    control = {
        route
        for route, capability in ROUTE_CAPABILITIES.items()
        if capability is RouteCapability.CONTROL_PLANE
    }
    mirror = {
        route
        for route, capability in ROUTE_CAPABILITIES.items()
        if capability is RouteCapability.MIRROR_REFRESH
    }

    assert control == CONTROL_PLANE_ROUTES
    assert mirror == MIRROR_REFRESH_ROUTES
    assert VIEW_ALLOWED_CAPABILITIES == {
        RouteCapability.CONTROL_PLANE,
        RouteCapability.MIRROR_REFRESH,
    }


def test_view_blocks_every_reviewed_workflow_registry_and_reminder_mutation() -> None:
    client = _client()
    blocked = {
        route: capability
        for route, capability in ROUTE_CAPABILITIES.items()
        if capability not in VIEW_ALLOWED_CAPABILITIES
    }

    for (method, route_path), capability in blocked.items():
        response = client.request(method, _concrete_path(route_path), json={})
        assert response.status_code == 403, (method, route_path, capability, response.text)
        assert response.json()["detail"]["code"] == "itkview_read_only"


@pytest.mark.parametrize("method", sorted(UNSAFE_METHODS))
def test_view_fail_closes_unknown_future_mutation_routes(method: str) -> None:
    response = _client().request(method, "/api/future-write", json={})

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "itkview_read_only"


def test_view_passes_control_plane_requests_to_the_real_handlers() -> None:
    client = _client()

    for method, route_path in sorted(CONTROL_PLANE_ROUTES):
        response = client.request(method, _concrete_path(route_path), json={})
        assert response.status_code != 403, (method, route_path, response.text)


def test_view_passes_only_the_reviewed_read_sync_posts_to_real_handlers() -> None:
    client = _client()

    for method, route_path in sorted(MIRROR_REFRESH_ROUTES):
        concrete = _concrete_path(route_path).replace("/1", "/TUDO")
        response = client.request(method, concrete, json={})
        assert response.status_code != 403, (method, route_path, response.text)
        assert request_capability(method, concrete) is RouteCapability.MIRROR_REFRESH

    assert request_capability("POST", "/api/sync/future/TUDO") is None
    assert _client().post("/api/sync/future/TUDO").status_code == 403


def test_route_capability_uses_canonical_paths_only() -> None:
    assert (
        route_capability("POST", "/api/components/{sn}/attachments/sync")
        is RouteCapability.MIRROR_REFRESH
    )
    assert route_capability("POST", "/api/components/20ABC/attachments/sync") is None


def test_view_health_declares_product_and_server_capabilities() -> None:
    body = _client().get("/health").json()

    assert body["app"] == "itkView"
    assert body["product_variant"] == "view"
    assert body["write_features_enabled"] is False
    assert body["pdb_write_scope"] == "disabled"
    assert body["capabilities"] == {
        "account_management": True,
        "mirror_sync": True,
        "test_uploads": False,
        "workflow_writes": False,
        "operations_writes": False,
        "pdb_writes": False,
        "outbound_notifications": False,
    }


def test_flow_health_keeps_all_product_features_available() -> None:
    body = _client("flow").get("/health").json()

    assert body["app"] == "itkFlow"
    assert body["product_variant"] == "flow"
    assert body["write_features_enabled"] is True
    assert all(body["capabilities"].values())


def test_view_never_constructs_in_app_write_workers() -> None:
    app = create_app(
        _settings(
            outbox_processor="app",
            reminder_scheduler="app",
        )
    )

    assert app.state.outbox_processor is None
    assert app.state.reminder_scheduler is None


def test_view_cookie_names_are_isolated_from_flow() -> None:
    body = {
        "email": "admin@example.test",
        "display_name": "Admin",
        "password": "valid-password",
    }
    flow_response = _client("flow").post("/api/setup/admin", json=body)
    view_response = _client("view").post("/api/setup/admin", json=body)

    assert flow_response.status_code == 201
    assert "itkflow_session" in flow_response.cookies
    assert "itkflow_csrf" in flow_response.cookies
    assert "itkview_session" not in flow_response.cookies
    assert view_response.status_code == 201
    assert "itkview_session" in view_response.cookies
    assert "itkview_csrf" in view_response.cookies
    assert "itkflow_session" not in view_response.cookies


def test_pdb_submitter_and_registration_sink_fail_closed_in_view() -> None:
    settings = _settings()

    with pytest.raises(PdbSubmitUnavailable, match="disabled in itkView"):
        make_pdb_submitter(settings)
    with pytest.raises(PdbSubmitUnavailable, match="disabled in itkView"):
        register_dummy_component(
            None,  # type: ignore[arg-type]
            settings,
            component_type="MODULE",
            type_code="DUMMY",
            institute_code="TUDO",
        )


def test_standalone_worker_exits_before_opening_the_database_in_view(monkeypatch) -> None:
    opened_database = False

    def fail_if_opened(_database_url):
        nonlocal opened_database
        opened_database = True
        raise AssertionError("view worker must not open its database")

    monkeypatch.setattr(run_worker, "make_engine", fail_if_opened)

    with pytest.raises(SystemExit, match="disabled in itkView"):
        run_worker.main(["--once"], settings=_settings())
    assert opened_database is False
