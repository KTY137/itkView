import pytest
from pydantic import ValidationError

from app.config import ProductionAccessError, Settings
from app.pdb_gateway import PdbGateway


def make_settings(**kwargs) -> Settings:
    # _env_file=None: unit tests must not be influenced by a developer's .env
    return Settings(_env_file=None, **kwargs)


def test_default_is_the_pdb_test_instance():
    settings = make_settings()
    assert settings.pdb_instance == "test"
    assert settings.allow_production is False
    assert "itkpd-test" in settings.pdb_ui_url


def test_production_without_explicit_opt_in_is_refused():
    with pytest.raises(ProductionAccessError):
        make_settings(pdb_instance="production")


def test_production_with_double_opt_in_is_possible():
    settings = make_settings(pdb_instance="production", allow_production=True)
    assert settings.pdb_instance == "production"
    # …but even then, no production UI URL is preconfigured anywhere:
    with pytest.raises(ProductionAccessError):
        _ = settings.pdb_ui_url


def test_test_api_url_must_not_be_a_production_host():
    with pytest.raises(ProductionAccessError, match="production host"):
        make_settings(pdb_test_api_url="https://itkpd.unicornuniversity.net/")


def test_test_api_url_must_use_https():
    with pytest.raises(ProductionAccessError, match="https"):
        make_settings(pdb_test_api_url="http://somewhere.example.org/")


def test_gateway_refuses_unconfigured_client():
    gateway = PdbGateway(make_settings())
    assert gateway.instance == "test"
    assert gateway.is_configured is False
    with pytest.raises(ProductionAccessError, match="access codes"):
        gateway.client()


def test_gateway_never_falls_back_to_deployment_access_codes():
    settings = make_settings(
        itkdb_access_code1="legacy-global-code-1",
        itkdb_access_code2="legacy-global-code-2",
    )

    gateway = PdbGateway(settings)

    assert gateway.is_configured is False
    with pytest.raises(ProductionAccessError, match="personal ITKDB access codes"):
        gateway.client()


def test_gateway_double_checks_the_production_guard():
    # Even a hand-built Settings object that bypassed validation is caught.
    settings = make_settings()
    object.__setattr__(settings, "pdb_instance", "production")
    with pytest.raises(ProductionAccessError):
        PdbGateway(settings)


def test_ops_heartbeat_threshold_is_local_and_bounded():
    assert make_settings(ops_heartbeat_stale_seconds=91).ops_heartbeat_stale_seconds == 91
    with pytest.raises(ValidationError):
        make_settings(ops_heartbeat_stale_seconds=0)
