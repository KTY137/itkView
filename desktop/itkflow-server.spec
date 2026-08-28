# PyInstaller spec shared by the itkFlow and itkView desktop sidecars.
#
# Produces one self-contained server executable that Tauri spawns. The built
# frontend travels inside the bundle (`frontend/`) so the backend can serve UI
# and API from one origin — see backend/app/desktop_server.py.
#
# Build via desktop/build-sidecar.py, which also builds the frontend first and
# renames the result to the target triple Tauri's sidecar mechanism expects.

import os
import re
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

SPEC_DIR = Path(SPECPATH).resolve()
REPO_ROOT = SPEC_DIR.parent
BACKEND_DIR = REPO_ROOT / "backend"
FRONTEND_DIST = Path(
    os.environ.get(
        "ITKFLOW_FRONTEND_DIST", SPEC_DIR / "build" / "view" / "frontend"
    )
).resolve()
SIDECAR_NAME = os.environ.get("ITKFLOW_DESKTOP_SIDECAR_NAME", "itkview-server")

if re.fullmatch(r"[a-z0-9-]+", SIDECAR_NAME) is None:
    raise SystemExit(f"Invalid desktop sidecar name: {SIDECAR_NAME!r}")

if not (FRONTEND_DIST / "index.html").is_file():
    raise SystemExit(
        f"Frontend build missing at {FRONTEND_DIST}. Build the selected desktop variant first."
    )

datas = [(str(FRONTEND_DIST), "frontend")]
binaries = []
hiddenimports = []

# uvicorn resolves its protocol/loop implementations by string at runtime, so
# static analysis finds none of them.
hiddenimports += collect_submodules("uvicorn")
# The app package is imported through app.main; collecting it explicitly keeps
# modules that are only reachable via FastAPI's route table.
hiddenimports += collect_submodules("app")

# itkdb is optional at runtime but must be present for PDB access to work at
# all in the packaged app; it ships data files (certificates, schemas).
for package in ("itkdb", "certifi"):
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
    except Exception:
        continue
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

a = Analysis(
    [str(BACKEND_DIR / "app" / "desktop_server.py")],
    pathex=[str(BACKEND_DIR)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Never bundle the test toolchain into a shipped artifact.
    excludes=["pytest", "_pytest", "PyInstaller"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=SIDECAR_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # No console window: Tauri owns the UI, and a stray terminal looks broken.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
