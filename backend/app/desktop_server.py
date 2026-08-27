"""Entry point for the packaged desktop build (Tauri sidecar).

The desktop bundle has no reverse proxy and no shell environment to configure,
so this module owns what Compose otherwise supplies:

* a writable application-data directory for the database and the credential
  encryption key, outside the read-only bundle;
* a stable encryption key, generated once and then reused — losing it makes
  saved personal PDB connections unreadable, so it is never silently replaced;
* the bundled frontend build, served by the backend itself so UI and API share
  one origin (session cookies, CSRF);
* a free localhost port, chosen by binding the socket here and handing that
  same socket to uvicorn, so the host process cannot race us for it.

Two ways to learn the server is up, because a windowed bundle has no stdout:
the host may pass an explicit ``--port`` and poll ``/health``, and a run with a
console additionally prints one ``ITKFLOW_READY {json}`` line. The end-user
desktop bundle selects the production read target by default, but sends no PDB
traffic until a user connects personal access codes. Writes remain confined to
itkFlow-registered DUMMY-batch test components.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
from pathlib import Path

READY_PREFIX = "ITKFLOW_READY"
_APP_DIR_NAME = "itkflow"
_KEY_FILE_NAME = "pdb-credential.key"
_DB_FILE_NAME = "itkflow.db"


def application_data_dir() -> Path:
    """Per-user, writable directory for desktop state.

    Deliberately the same location the Windows dev launcher uses, so a person
    who used `start-itkflow.ps1` keeps their connected PDB credentials.
    """
    override = os.environ.get("ITKFLOW_DATA_DIR")
    if override:
        directory = Path(override)
    elif sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if not base:
            raise RuntimeError("Windows did not provide LOCALAPPDATA.")
        directory = Path(base) / _APP_DIR_NAME
    elif sys.platform == "darwin":
        directory = Path.home() / "Library" / "Application Support" / _APP_DIR_NAME
    else:
        base = os.environ.get("XDG_DATA_HOME")
        directory = (Path(base) if base else Path.home() / ".local" / "share") / _APP_DIR_NAME
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def ensure_encryption_key(data_dir: Path) -> str:
    """Return the stable credential key, creating it only when absent.

    A regenerated key silently invalidates every saved PDB connection, so an
    existing file always wins — including one written by the dev launcher.
    """
    from app.pdb_credentials import generate_pdb_credential_encryption_key

    key_file = data_dir / _KEY_FILE_NAME
    if key_file.is_file():
        existing = key_file.read_text(encoding="ascii").strip()
        if existing:
            return existing

    key = generate_pdb_credential_encryption_key()
    key_file.write_text(key, encoding="ascii")
    try:
        key_file.chmod(0o600)
    except OSError:
        # Windows ACLs are not POSIX modes; the per-user directory still applies.
        pass
    return key


def is_frozen() -> bool:
    """True inside a PyInstaller bundle."""
    return bool(getattr(sys, "frozen", False))


def redirect_output_to_log(data_dir: Path) -> Path | None:
    """Give a packaged run somewhere to write, and keep a crash trail.

    A windowed bundle has no usable console: PyInstaller replaces stdout with a
    sink that silently discards everything (and older versions use None, where
    an unguarded ``print`` in a dependency raises instead). Either way a crash
    would leave nothing to read, so a frozen build always logs to a file.
    """
    if not is_frozen() and sys.stdout is not None and sys.stderr is not None:
        return None

    log_dir = data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "server.log"
    # Line buffered: a crash must not lose the lines explaining it.
    stream = open(log_file, "a", encoding="utf-8", buffering=1)
    sys.stdout = stream
    sys.stderr = stream
    return log_file


def bundled_static_dir() -> Path | None:
    """The frontend build inside the bundle, if this is a packaged run."""
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root is None:
        return None
    candidate = Path(bundle_root) / "frontend"
    return candidate if (candidate / "index.html").is_file() else None


def reserve_port(host: str, port: int) -> socket.socket:
    """Bind and return a listening socket. Port 0 lets the OS pick a free one."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # No SO_REUSEADDR: on Windows it lets two processes share one port, which
    # would silently split requests between an old and a new server.
    sock.bind((host, port))
    sock.listen(128)
    return sock


def build_settings(data_dir: Path, static_dir: Path | None):
    from app.config import Settings

    database_url = os.environ.get("ITKFLOW_DATABASE_URL")
    if not database_url:
        database_url = f"sqlite:///{(data_dir / _DB_FILE_NAME).as_posix()}"

    overrides: dict[str, object] = {
        "database_url": database_url,
        "pdb_credential_encryption_key": ensure_encryption_key(data_dir),
        # The bundle ships one process, so the API has to fire due reminders
        # itself — the worker default would mean they never fire here (docs/11).
        "reminder_scheduler": os.environ.get("ITKFLOW_REMINDER_SCHEDULER", "app"),
        # …and for the same reason it has to submit approved outbox actions
        # itself; otherwise a pushed change stops at `submitted` forever.
        "outbox_processor": os.environ.get("ITKFLOW_OUTBOX_PROCESSOR", "app"),
    }
    if static_dir is not None:
        overrides["static_dir"] = str(static_dir)
    # The desktop bundle is an end-user artifact: production *reads* are on by
    # default (owner decision, docs/09) — nothing contacts the PDB until a
    # person connects their own access codes, and writes stay `dummy_only`
    # regardless. The environment still wins when either variable is set
    # explicitly (init kwargs would shadow env, hence the guard).
    if "ITKFLOW_PDB_INSTANCE" not in os.environ and "ITKFLOW_ALLOW_PRODUCTION" not in os.environ:
        overrides["pdb_instance"] = "production"
        overrides["allow_production"] = True
    # Everything else (write scope in particular) keeps its documented default.
    return Settings(**overrides)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="itkflow-server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="0 (default) asks the OS for a free port and reports it on stdout.",
    )
    parser.add_argument(
        "--static-dir",
        default=os.environ.get("ITKFLOW_STATIC_DIR"),
        help="Frontend build to serve. Defaults to the bundled one.",
    )
    args = parser.parse_args(argv)

    import uvicorn

    from app.main import create_app

    data_dir = application_data_dir()
    redirect_output_to_log(data_dir)
    static_dir = Path(args.static_dir) if args.static_dir else bundled_static_dir()
    settings = build_settings(data_dir, static_dir)

    try:
        sock = reserve_port(args.host, args.port)
    except OSError as exc:
        # The host picked a port that something else took in the meantime. Exit
        # distinguishably so it can retry with a fresh one instead of hanging.
        print(f"itkflow-server: cannot bind {args.host}:{args.port}: {exc}", flush=True)
        return 2
    bound_host, bound_port = sock.getsockname()[:2]

    app = create_app(settings)
    ready = {
        "port": bound_port,
        "url": f"http://{bound_host}:{bound_port}/",
        "data_dir": str(data_dir),
        "pdb_instance": settings.pdb_instance,
        "spa": bool(getattr(app.state, "spa_mounted", False)),
    }
    # One line, flushed: the host blocks on it before opening a window.
    print(f"{READY_PREFIX} {json.dumps(ready)}", flush=True)

    server = uvicorn.Server(
        uvicorn.Config(app, log_level=os.environ.get("ITKFLOW_LOG_LEVEL", "info"))
    )
    server.run(sockets=[sock])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
