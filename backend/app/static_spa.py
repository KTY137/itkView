# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-FileComment: itkflow-65c08adfdcf9
"""Serve the built frontend from the backend process (desktop packaging).

The Compose deployment keeps nginx in front of the SPA. The desktop build has
no reverse proxy, so the packaged backend serves the Vite build itself: the
webview then loads UI and API from one origin, which keeps the existing
session-cookie and CSRF flow working untouched.

Enabled only when `ITKFLOW_STATIC_DIR` points at a directory containing
`index.html`; a server without it behaves exactly as before.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException

# Path prefixes owned by the backend. The SPA fallback must never answer these:
# turning a genuine API 404 into a 200 with index.html produces a page that
# loads but silently does nothing — the worst class of packaging bug.
API_PREFIXES = ("/api", "/health", "/docs", "/redoc", "/openapi.json")


def _is_api_path(path: str) -> bool:
    normalised = "/" + path.lstrip("/")
    return any(
        normalised == prefix or normalised.startswith(prefix + "/")
        for prefix in API_PREFIXES
    )


def mount_spa(app: FastAPI, static_dir: Path) -> bool:
    """Serve `static_dir` as a single-page app. Returns False if there is none.

    Must be called after the API routes are registered: the fallback route is
    a catch-all and Starlette matches in registration order.
    """
    static_root = Path(static_dir).resolve()
    index_file = static_root / "index.html"
    if not index_file.is_file():
        return False

    assets_dir = static_root / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{spa_path:path}", include_in_schema=False)
    def serve_spa(spa_path: str) -> FileResponse:
        if _is_api_path(spa_path):
            # Let a missing API route stay a 404 instead of becoming the shell.
            raise HTTPException(status_code=404, detail="Not Found")

        if spa_path:
            candidate = (static_root / spa_path).resolve()
            # Containment check: a crafted path must not read outside the
            # bundle. `resolve()` first, compare after — string prefixes alone
            # would accept "..%2f" style escapes on some platforms.
            if candidate.is_file() and candidate.is_relative_to(static_root):
                return FileResponse(candidate)

        # Unknown paths belong to the client-side router, which needs the shell.
        return FileResponse(index_file)

    return True
