# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-FileComment: itkflow-c77158fe0515
"""Bounded, local diagnostics bundle for the packaged desktop application."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import SyncJob

LOG_TAIL_BYTES = 2 * 1024 * 1024
LOG_FILES = tuple(
    f"{base}{suffix}"
    for base in ("server.log", "desktop.log")
    for suffix in ("", ".1", ".2", ".3")
)


class DiagnosticsUnavailableError(RuntimeError):
    """The process is not a packaged desktop server with a safe log root."""


@dataclass(frozen=True, slots=True)
class DiagnosticLog:
    name: str
    content: bytes
    original_size: int

    @property
    def truncated(self) -> bool:
        return self.original_size > len(self.content)


def diagnostics_available(log_dir: object) -> bool:
    if not isinstance(log_dir, Path):
        return False
    try:
        return log_dir.exists() and log_dir.is_dir() and not log_dir.is_symlink()
    except OSError:
        return False


def _safe_logs(log_dir: Path) -> list[DiagnosticLog]:
    if not diagnostics_available(log_dir):
        raise DiagnosticsUnavailableError("Desktop diagnostics are not available.")
    root = log_dir.resolve(strict=True)
    logs: list[DiagnosticLog] = []
    for name in LOG_FILES:
        candidate = root / name
        try:
            if not candidate.exists() or not candidate.is_file() or candidate.is_symlink():
                continue
            resolved = candidate.resolve(strict=True)
            if resolved.parent != root:
                continue
            size = resolved.stat().st_size
            with resolved.open("rb") as handle:
                if size > LOG_TAIL_BYTES:
                    handle.seek(-LOG_TAIL_BYTES, 2)
                content = handle.read(LOG_TAIL_BYTES)
        except OSError:
            continue
        logs.append(DiagnosticLog(name=name, content=content, original_size=size))
    return logs


def _sync_job_metadata(session: Session) -> list[dict]:
    rows = session.scalars(select(SyncJob).order_by(SyncJob.id.desc()).limit(20))
    return [
        {
            "id": row.id,
            "kind": row.kind,
            "institute_code": row.institute_code,
            "status": row.status,
            "phase": row.phase,
            "current": row.current,
            "total": row.total,
            "percent": row.percent,
            "created_at": row.created_at.isoformat(),
            "started_at": row.started_at.isoformat() if row.started_at else None,
            "updated_at": row.updated_at.isoformat(),
            "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        }
        for row in rows
    ]


def build_diagnostics_bundle(
    session: Session,
    *,
    log_dir: Path,
    app_version: str,
    generated_at: datetime | None = None,
) -> bytes:
    """Create one in-memory ZIP from a fixed log allowlist and safe metadata."""

    logs = _safe_logs(log_dir)
    created = (generated_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    metadata = {
        "format": "itkflow-desktop-diagnostics-v1",
        "app_version": app_version,
        "generated_at": created.isoformat(),
        "logs": [
            {
                "name": item.name,
                "included_bytes": len(item.content),
                "original_bytes": item.original_size,
                "truncated_to_tail": item.truncated,
            }
            for item in logs
        ],
        "recent_sync_jobs": _sync_job_metadata(session),
    }
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED, compresslevel=6) as archive:
        archive.writestr(
            "itkflow-diagnostics/metadata.json",
            json.dumps(metadata, indent=2, sort_keys=True).encode(),
        )
        for item in logs:
            archive.writestr(f"itkflow-diagnostics/logs/{item.name}", item.content)
    return output.getvalue()


__all__ = [
    "DiagnosticsUnavailableError",
    "LOG_FILES",
    "LOG_TAIL_BYTES",
    "build_diagnostics_bundle",
    "diagnostics_available",
]
