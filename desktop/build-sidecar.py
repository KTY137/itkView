"""Build the itkFlow desktop sidecar: frontend -> PyInstaller -> Tauri binary.

Tauri's `externalBin` looks for a file named `<name>-<target-triple>` next to
the configured path, so the last step is a rename, not a copy into place by
hand. Run this before `npm run build` in desktop/.

    python desktop/build-sidecar.py [--skip-frontend]
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

DESKTOP_DIR = Path(__file__).resolve().parent
REPO_ROOT = DESKTOP_DIR.parent
FRONTEND_DIR = REPO_ROOT / "frontend"
BACKEND_PYTHON = REPO_ROOT / "backend" / ".venv" / "Scripts" / "python.exe"
if not BACKEND_PYTHON.is_file():  # POSIX layout
    BACKEND_PYTHON = REPO_ROOT / "backend" / ".venv" / "bin" / "python"
BINARIES_DIR = DESKTOP_DIR / "src-tauri" / "binaries"
BUILD_DIR = DESKTOP_DIR / "build"


def run(command: list[str], cwd: Path) -> None:
    printable = " ".join(command)
    print(f"\n$ {printable}\n  (in {cwd})", flush=True)
    result = subprocess.run(command, cwd=cwd)
    if result.returncode != 0:
        raise SystemExit(f"failed with exit code {result.returncode}: {printable}")


def target_triple() -> str:
    """The triple Tauri expects in the sidecar file name."""
    output = subprocess.run(
        ["rustc", "-vV"], capture_output=True, text=True, check=True
    ).stdout
    match = re.search(r"^host:\s*(\S+)$", output, re.MULTILINE)
    if not match:
        raise SystemExit("could not read the host target triple from 'rustc -vV'.")
    return match.group(1)


def build_frontend() -> None:
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    if npm is None:
        raise SystemExit("npm was not found on PATH.")
    run([npm, "run", "build"], cwd=FRONTEND_DIR)


def build_sidecar() -> Path:
    if not BACKEND_PYTHON.is_file():
        raise SystemExit(
            f"backend environment not found at {BACKEND_PYTHON}. "
            "Create it as documented in README.md."
        )
    run(
        [
            str(BACKEND_PYTHON),
            "-m",
            "PyInstaller",
            "itkflow-server.spec",
            "--distpath",
            str(BUILD_DIR / "dist"),
            "--workpath",
            str(BUILD_DIR / "work"),
            "--noconfirm",
        ],
        cwd=DESKTOP_DIR,
    )
    suffix = ".exe" if sys.platform == "win32" else ""
    built = BUILD_DIR / "dist" / f"itkflow-server{suffix}"
    if not built.is_file():
        raise SystemExit(f"PyInstaller did not produce {built}.")
    return built


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="build-sidecar")
    parser.add_argument(
        "--skip-frontend",
        action="store_true",
        help="Reuse the existing frontend/dist instead of rebuilding it.",
    )
    args = parser.parse_args(argv)

    if not args.skip_frontend:
        build_frontend()
    elif not (FRONTEND_DIR / "dist" / "index.html").is_file():
        raise SystemExit("--skip-frontend given but frontend/dist/index.html is missing.")

    built = build_sidecar()

    BINARIES_DIR.mkdir(parents=True, exist_ok=True)
    target = BINARIES_DIR / f"itkflow-server-{target_triple()}{built.suffix}"
    shutil.copy2(built, target)
    size_mb = target.stat().st_size / (1024 * 1024)
    print(f"\nsidecar ready: {target.relative_to(REPO_ROOT)} ({size_mb:.0f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
