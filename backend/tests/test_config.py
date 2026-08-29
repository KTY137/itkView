# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-FileComment: itkflow-39b03a4f2eb1
import pytest
from pydantic import ValidationError

from app.config import ProductionAccessError, Settings
from app.pdb_credentials import PdbAccessCodes
from app.pdb_gateway import PdbGateway


def make_settings(**kwargs) -> Settings:
    # _env_file=None: unit tests must not be influenced by a developer's .env
    return Settings(_env_file=None, **kwargs)


def test_default_is_offline_and_reaches_no_pdb():
    settings = make_settings()
    assert settings.pdb_instance == "offline"
    assert settings.allow_production is False


def test_the_retired_test_instance_is_gone():
    # The historical PDB test service no longer exists; "test" is not a valid
    # configuration anymore and must fail loudly instead of pretending.
    with pytest.raises(ValidationError):
        make_settings(pdb_instance="test")


def test_production_without_explicit_opt_in_is_refused():
    with pytest.raises(ProductionAccessError):
        make_settings(pdb_instance="production")


def test_production_with_double_opt_in_is_possible():
    settings = make_settings(pdb_instance="production", allow_production=True)
    assert settings.pdb_instance == "production"
    # No production UI URL is preconfigured anywhere in Settings; a deployment
    # that wants to link out to the PDB UI must supply its own configuration —
    # there used to be a `pdb_ui_url` property here that only ever raised.


def test_gateway_refuses_unconfigured_client():
    gateway = PdbGateway(make_settings())
    assert gateway.instance == "offline"
    assert gateway.is_configured is False
    with pytest.raises(ProductionAccessError, match="access codes"):
        gateway.client()


def test_gateway_refuses_a_client_while_offline_even_with_codes():
    gateway = PdbGateway(
        make_settings(),
        access_codes=PdbAccessCodes("offline-code-1", "offline-code-2"),
    )
    assert gateway.is_configured is True
    with pytest.raises(ProductionAccessError, match="[Nn]o PDB"):
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


def test_sync_page_attempts_are_configurable_and_bounded():
    assert make_settings().sync_page_max_attempts == 3
    assert make_settings(sync_page_max_attempts=7).sync_page_max_attempts == 7
    with pytest.raises(ValidationError):
        make_settings(sync_page_max_attempts=0)


def test_sync_fetch_concurrency_is_configurable_and_bounded():
    # Default is a small bounded pool; 1 restores the fully serial sweep.
    assert make_settings().sync_fetch_concurrency == 4
    assert make_settings(sync_fetch_concurrency=1).sync_fetch_concurrency == 1
    with pytest.raises(ValidationError):
        make_settings(sync_fetch_concurrency=0)
    with pytest.raises(ValidationError):
        make_settings(sync_fetch_concurrency=17)


def test_ops_heartbeat_threshold_is_local_and_bounded():
    assert make_settings(ops_heartbeat_stale_seconds=91).ops_heartbeat_stale_seconds == 91
    with pytest.raises(ValidationError):
        make_settings(ops_heartbeat_stale_seconds=0)


def test_evidence_sweep_strategy_is_switchable():
    # Default is the batched index/bulk sweep; the proven per-component sweep
    # stays selectable without a code change.
    assert make_settings().sync_evidence_strategy == "index_bulk"
    assert (
        make_settings(sync_evidence_strategy="per_component").sync_evidence_strategy
        == "per_component"
    )
    with pytest.raises(ValidationError):
        make_settings(sync_evidence_strategy="whatever")


def test_evidence_batch_sizes_are_configurable_and_bounded():
    settings = make_settings()
    assert settings.sync_evidence_index_batch_size == 50
    assert settings.sync_evidence_index_page_size == 100
    assert settings.sync_evidence_bulk_batch_size == 50

    tuned = make_settings(
        sync_evidence_index_batch_size=10,
        sync_evidence_index_page_size=25,
        sync_evidence_bulk_batch_size=20,
    )
    assert tuned.sync_evidence_index_batch_size == 10
    assert tuned.sync_evidence_index_page_size == 25
    assert tuned.sync_evidence_bulk_batch_size == 20

    for field in (
        "sync_evidence_index_batch_size",
        "sync_evidence_index_page_size",
        "sync_evidence_bulk_batch_size",
    ):
        with pytest.raises(ValidationError):
            make_settings(**{field: 0})
        with pytest.raises(ValidationError):
            make_settings(**{field: 100_000})


def test_evidence_batch_sizes_come_from_the_itkflow_env_prefix(monkeypatch):
    monkeypatch.setenv("ITKFLOW_SYNC_EVIDENCE_INDEX_BATCH_SIZE", "7")
    monkeypatch.setenv("ITKFLOW_SYNC_EVIDENCE_BULK_BATCH_SIZE", "9")
    monkeypatch.setenv("ITKFLOW_SYNC_EVIDENCE_STRATEGY", "per_component")
    settings = make_settings()
    assert settings.sync_evidence_index_batch_size == 7
    assert settings.sync_evidence_bulk_batch_size == 9
    assert settings.sync_evidence_strategy == "per_component"
