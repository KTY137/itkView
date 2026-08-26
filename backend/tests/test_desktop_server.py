"""Desktop packaging entry point: state locations, key stability, ports."""

import json

import pytest

from app import desktop_server
from app.pdb_credentials import PdbAccessCodes, decrypt_access_codes, encrypt_access_codes


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    target = tmp_path / "appdata"
    monkeypatch.setenv("ITKFLOW_DATA_DIR", str(target))
    return desktop_server.application_data_dir()


def test_data_dir_is_created(data_dir):
    assert data_dir.is_dir()


def test_encryption_key_is_generated_once(data_dir):
    first = desktop_server.ensure_encryption_key(data_dir)
    second = desktop_server.ensure_encryption_key(data_dir)
    # Regenerating would silently orphan every saved PDB connection.
    assert first == second
    assert (data_dir / "pdb-credential.key").is_file()


def test_existing_key_file_wins(data_dir):
    """A key written by the dev launcher must keep working in the desktop app."""
    from app.pdb_credentials import generate_pdb_credential_encryption_key

    launcher_key = generate_pdb_credential_encryption_key()
    (data_dir / "pdb-credential.key").write_text(launcher_key + "\n", encoding="ascii")

    assert desktop_server.ensure_encryption_key(data_dir) == launcher_key

    # And it really decrypts a payload sealed with the pre-existing key.
    payload = encrypt_access_codes(PdbAccessCodes("a", "b"), launcher_key, user_id=1)
    restored = decrypt_access_codes(payload, launcher_key, user_id=1)
    assert restored.access_code1 == "a"


def test_settings_default_to_a_database_in_the_data_dir(data_dir, monkeypatch):
    monkeypatch.delenv("ITKFLOW_DATABASE_URL", raising=False)
    settings = desktop_server.build_settings(data_dir, None)
    assert settings.database_url.startswith("sqlite:///")
    assert "itkflow.db" in settings.database_url
    assert settings.pdb_credential_encryption_key is not None


def test_settings_enable_production_reads_by_default(data_dir, monkeypatch):
    for name in ("ITKFLOW_PDB_INSTANCE", "ITKFLOW_ALLOW_PRODUCTION"):
        monkeypatch.delenv(name, raising=False)
    settings = desktop_server.build_settings(data_dir, None)
    # The desktop bundle is an end-user artifact: production reads work out of
    # the box (owner decision, docs/09). Nothing contacts the PDB until a
    # person connects their own access codes, and writes stay dummy_only.
    assert settings.pdb_instance == "production"
    assert settings.allow_production is True
    assert settings.pdb_write_scope == "dummy_only"


def test_settings_respect_an_explicit_pdb_environment(data_dir, monkeypatch):
    # A deliberately-set environment always wins over the bundle default.
    monkeypatch.setenv("ITKFLOW_PDB_INSTANCE", "offline")
    monkeypatch.delenv("ITKFLOW_ALLOW_PRODUCTION", raising=False)
    settings = desktop_server.build_settings(data_dir, None)
    assert settings.pdb_instance == "offline"
    assert settings.allow_production is False


def test_settings_let_the_bundle_fire_its_own_reminders(data_dir, monkeypatch):
    """The bundle ships one process, so the API must be the reminder scheduler.

    With the `worker` default a packaged install has no ticker at all and every
    scheduled reminder silently never fires (docs/11).
    """
    monkeypatch.delenv("ITKFLOW_REMINDER_SCHEDULER", raising=False)
    settings = desktop_server.build_settings(data_dir, None)
    assert settings.reminder_scheduler == "app"

    monkeypatch.setenv("ITKFLOW_REMINDER_SCHEDULER", "off")
    assert desktop_server.build_settings(data_dir, None).reminder_scheduler == "off"


def test_reserve_port_zero_picks_a_free_port():
    sock = desktop_server.reserve_port("127.0.0.1", 0)
    try:
        host, port = sock.getsockname()[:2]
        assert host == "127.0.0.1"
        assert port > 0
    finally:
        sock.close()


def test_reserve_port_refuses_a_taken_port():
    taken = desktop_server.reserve_port("127.0.0.1", 0)
    try:
        port = taken.getsockname()[1]
        # Must raise rather than silently share the port: two servers on one
        # port would split requests between them.
        with pytest.raises(OSError):
            desktop_server.reserve_port("127.0.0.1", port).close()
    finally:
        taken.close()


def test_main_reports_a_bind_failure_instead_of_hanging(data_dir, capsys):
    taken = desktop_server.reserve_port("127.0.0.1", 0)
    try:
        port = taken.getsockname()[1]
        assert desktop_server.main(["--port", str(port)]) == 2
        assert "cannot bind" in capsys.readouterr().out
    finally:
        taken.close()


def test_ready_line_is_machine_readable():
    # The host parses this; keep it one line of JSON behind a stable prefix.
    line = f'{desktop_server.READY_PREFIX} {json.dumps({"port": 1})}'
    prefix, _, payload = line.partition(" ")
    assert prefix == "ITKFLOW_READY"
    assert json.loads(payload)["port"] == 1


def test_bundled_static_dir_is_none_outside_a_bundle():
    assert not hasattr(__import__("sys"), "_MEIPASS")
    assert desktop_server.bundled_static_dir() is None


def test_frozen_build_always_writes_a_log(data_dir, monkeypatch):
    """A windowed bundle discards stdout, so the crash trail must be a file."""
    monkeypatch.setattr(desktop_server, "is_frozen", lambda: True)
    real_stdout, real_stderr = __import__("sys").stdout, __import__("sys").stderr
    try:
        log_file = desktop_server.redirect_output_to_log(data_dir)
        assert log_file is not None and log_file.is_file()
        print("hello from the bundle")
    finally:
        import sys as _sys

        _sys.stdout.close()
        _sys.stdout, _sys.stderr = real_stdout, real_stderr
    assert "hello from the bundle" in log_file.read_text(encoding="utf-8")


def test_unfrozen_run_keeps_the_terminal(data_dir, monkeypatch):
    monkeypatch.setattr(desktop_server, "is_frozen", lambda: False)
    assert desktop_server.redirect_output_to_log(data_dir) is None
