# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-FileComment: itkflow-77bd16a6212c
import json
from datetime import datetime, timezone
from io import BytesIO
from zipfile import ZipFile

from authutil import authenticate

from app.diagnostics import LOG_TAIL_BYTES, build_diagnostics_bundle
from app.models import SyncJob, utcnow


def _bundle_entries(content: bytes):
    with ZipFile(BytesIO(content)) as archive:
        names = archive.namelist()
        metadata = json.loads(
            archive.read("itkflow-diagnostics/metadata.json").decode()
        )
        payloads = {name: archive.read(name) for name in names}
    return names, metadata, payloads


def test_bundle_is_allowlisted_bounded_and_excludes_secret_job_fields(
    session_factory, tmp_path
):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    server_tail = b"x" * (LOG_TAIL_BYTES + 37)
    (log_dir / "server.log").write_bytes(server_tail)
    (log_dir / "desktop.log.1").write_text("desktop lifecycle", encoding="utf-8")
    (log_dir / "database.sqlite").write_text("must not ship", encoding="utf-8")
    (log_dir / "unexpected.log").write_text("must not ship", encoding="utf-8")
    now = utcnow()
    with session_factory() as session:
        session.add(
            SyncJob(
                kind="evidence",
                institute_code="SAFE",
                status="failed",
                phase="fetching",
                current=2,
                total=5,
                percent=40.0,
                message="message-secret",
                error="error-secret",
                result={"secret": "result-secret"},
                requested_by="person@example.test",
                active_key="lease-secret",
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()
        bundle = build_diagnostics_bundle(
            session,
            log_dir=log_dir,
            app_version="test-version",
            generated_at=datetime(2026, 8, 27, tzinfo=timezone.utc),
        )

    names, metadata, payloads = _bundle_entries(bundle)
    assert names == [
        "itkflow-diagnostics/metadata.json",
        "itkflow-diagnostics/logs/server.log",
        "itkflow-diagnostics/logs/desktop.log.1",
    ]
    assert len(payloads["itkflow-diagnostics/logs/server.log"]) == LOG_TAIL_BYTES
    assert metadata["logs"][0]["truncated_to_tail"] is True
    serialized = json.dumps(metadata)
    for secret in (
        "person@example.test",
        "message-secret",
        "error-secret",
        "result-secret",
        "lease-secret",
        "requested_by",
        "user_id",
        "active_key",
    ):
        assert secret not in serialized


def test_global_admin_can_download_desktop_diagnostics(as_admin, tmp_path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "server.log").write_text("safe server line", encoding="utf-8")
    as_admin.app.state.desktop_log_dir = log_dir

    health = as_admin.get("/api/ops/health")
    response = as_admin.get("/api/ops/diagnostics")

    assert health.status_code == 200
    assert health.json()["diagnostics_available"] is True
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "itkFlow-diagnostics-" in response.headers["content-disposition"]
    names, _, _ = _bundle_entries(response.content)
    assert "itkflow-diagnostics/logs/server.log" in names


def test_diagnostics_are_unavailable_on_web(as_admin):
    assert as_admin.get("/api/ops/health").json()["diagnostics_available"] is False
    assert as_admin.get("/api/ops/diagnostics").status_code == 404


def test_diagnostics_are_forbidden_for_scoped_admins(
    client, session_factory, tudo, tmp_path
):
    authenticate(
        client,
        session_factory,
        role="admin",
        institute_id=tudo["id"],
        email="scoped-diagnostics@example.test",
    )
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "server.log").write_text("safe server line", encoding="utf-8")
    client.app.state.desktop_log_dir = log_dir

    assert client.get("/api/ops/health").json()["diagnostics_available"] is False
    assert client.get("/api/ops/diagnostics").status_code == 403
