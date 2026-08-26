"""The single-process deployments must drain the outbox themselves.

Compose runs a standalone worker; the desktop bundle and the dev launcher do
not. Without an in-process drain a reviewed action reaches `submitted` and then
sits there forever — the PDB write silently never happens (docs/11).
"""


from app import desktop_server
from app.config import Settings
from app.main import create_app
from app.outbox_processor import OutboxProcessor


def make_settings(**kwargs) -> Settings:
    return Settings(_env_file=None, **kwargs)


def test_worker_deployments_keep_the_standalone_worker():
    assert make_settings().outbox_processor == "worker"


def test_the_desktop_bundle_drains_the_outbox_itself(tmp_path, monkeypatch):
    for name in ("ITKFLOW_OUTBOX_PROCESSOR", "ITKFLOW_DATABASE_URL"):
        monkeypatch.delenv(name, raising=False)
    settings = desktop_server.build_settings(tmp_path, None)
    assert settings.outbox_processor == "app"


def test_an_app_processor_is_wired_into_the_application(tmp_path):
    settings = make_settings(
        database_url=f"sqlite:///{(tmp_path / 'app.db').as_posix()}",
        outbox_processor="app",
    )
    app = create_app(settings)
    assert isinstance(app.state.outbox_processor, OutboxProcessor)


def test_a_worker_deployment_does_not_start_a_second_drain(tmp_path):
    settings = make_settings(
        database_url=f"sqlite:///{(tmp_path / 'app.db').as_posix()}",
        outbox_processor="worker",
    )
    app = create_app(settings)
    assert app.state.outbox_processor is None


def test_one_tick_processes_the_outbox_and_survives_a_failing_cycle(tmp_path):
    settings = make_settings(
        database_url=f"sqlite:///{(tmp_path / 'app.db').as_posix()}",
        outbox_processor="app",
    )
    app = create_app(settings)
    processor: OutboxProcessor = app.state.outbox_processor

    calls: list[str] = []

    def failing_run_once(*args, **kwargs):
        calls.append("tick")
        raise RuntimeError("PDB unreachable")

    processor._run_once = failing_run_once  # noqa: SLF001 — exercising the guard
    # A bad cycle must be swallowed: the drain has to keep polling, exactly like
    # the reminder scheduler, or one outage stops every later push.
    processor.tick()
    assert calls == ["tick"]


def test_the_processor_never_uses_deployment_wide_service_credentials(tmp_path, monkeypatch):
    """Writes always run as the PDB identity bound at approval time (ADR 004)."""
    settings = make_settings(
        database_url=f"sqlite:///{(tmp_path / 'app.db').as_posix()}",
        outbox_processor="app",
        itkdb_access_code1="deployment-wide-1",
        itkdb_access_code2="deployment-wide-2",
    )
    app = create_app(settings)
    processor: OutboxProcessor = app.state.outbox_processor

    captured: list[dict] = []

    def spy_make_submitter(passed_settings, **kwargs):
        captured.append(kwargs)
        return lambda session, action: None

    monkeypatch.setattr("app.outbox_processor.make_pdb_submitter", spy_make_submitter)
    processor.tick()

    assert captured == [{}], "no service credentials may be handed to the submitter"
