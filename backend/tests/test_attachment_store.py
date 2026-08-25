"""Local attachment mirror: path safety, idempotency, partial failure."""

import pytest
from sqlalchemy import select

from app import attachment_store
from app.attachment_store import (
    download_attachments,
    pending_attachments,
    resolve_path,
    storage_path,
)
from app.config import Settings
from app.db import Base, make_engine, make_session_factory
from app.models import TestRunAttachment, TestRunEvidence

JPEG = b"\xff\xd8\xff\xe0itkflow-test-image"


@pytest.fixture()
def settings(tmp_path) -> Settings:
    return Settings(
        database_url="sqlite:///:memory:",
        attachment_dir=str(tmp_path / "attachments"),
        _env_file=None,
    )


@pytest.fixture()
def session(settings):
    engine = make_engine(settings.database_url)
    Base.metadata.create_all(engine)
    with make_session_factory(engine)() as active:
        yield active


@pytest.fixture()
def evidence(session):
    session.add(
        TestRunEvidence(
            component_sn="20USEM20000041",
            test_type="VISUAL_INSPECTION",
            passed=True,
            source="pdb",
            external_ref="RUN-1",
            payload={
                "attachments": [
                    {
                        "code": "abc123",
                        "filename": "Untitled.jpg",
                        "content_type": "image/jpeg",
                        "title": None,
                    }
                ]
            },
        )
    )
    session.commit()


class _FakeClient:
    def __init__(self, data=JPEG, fail=False):
        self._data = data
        self._fail = fail
        self.calls = 0

    def get(self, action, json=None):
        self.calls += 1
        if self._fail:
            raise RuntimeError("PDB said no")

        class _BinaryFile:
            content = self._data

        return _BinaryFile()


class _FakeGateway:
    def __init__(self, client=None, configured=True):
        self._client = client or _FakeClient()
        self.is_configured = configured

    def client(self):
        return self._client


# --- path construction -----------------------------------------------------


def test_storage_path_groups_by_serial_number():
    path = storage_path("20USEM20000041", "abc123", "image/jpeg", "x.jpg")
    assert path == "20USEM20000041/abc123.jpg"


def test_storage_path_ignores_the_pdb_filename():
    """A PDB-supplied name must never reach the filesystem."""
    path = storage_path("20USEM1", "code9", "image/png", "../../evil.exe")
    assert path == "20USEM1/code9.png"
    assert ".." not in path and "evil" not in path


def test_storage_path_sanitises_a_hostile_code():
    path = storage_path("20USEM1", "../../../etc/passwd", "image/png", None)
    assert ".." not in path
    assert path.count("/") == 1


def test_unknown_content_type_gets_no_extension():
    # Better a extension-less file than writing an arbitrary one.
    assert storage_path("SN", "c", "application/x-msdownload", "a.exe") == "SN/c"


def test_extension_falls_back_to_a_trusted_suffix():
    assert storage_path("SN", "c", None, "photo.png") == "SN/c.png"


# --- descriptor extraction -------------------------------------------------


def test_pending_attachments_reads_the_evidence_payload(session, evidence):
    descriptors = pending_attachments(session, "20USEM20000041")
    assert len(descriptors) == 1
    assert descriptors[0]["code"] == "abc123"
    assert descriptors[0]["test_run_ref"] == "RUN-1"


def test_pending_attachments_skips_entries_without_a_code(session):
    session.add(
        TestRunEvidence(
            component_sn="SN2",
            test_type="X",
            passed=True,
            source="pdb",
            external_ref="R",
            payload={"attachments": [{"filename": "no-code.jpg"}]},
        )
    )
    session.commit()
    assert pending_attachments(session, "SN2") == []


# --- downloading -----------------------------------------------------------


def test_download_writes_the_file_and_indexes_it(session, settings, evidence):
    stats = download_attachments(session, _FakeGateway(), settings, "20USEM20000041")
    session.commit()

    assert stats.downloaded == 1 and stats.failed == 0
    row = session.scalar(select(TestRunAttachment))
    assert row.relative_path == "20USEM20000041/abc123.jpg"
    assert row.size_bytes == len(JPEG)
    assert row.downloaded_at is not None

    stored = resolve_path(settings, row)
    assert stored is not None and stored.read_bytes() == JPEG


def test_download_is_idempotent(session, settings, evidence):
    client = _FakeClient()
    gateway = _FakeGateway(client)
    download_attachments(session, gateway, settings, "20USEM20000041")
    session.commit()
    second = download_attachments(session, gateway, settings, "20USEM20000041")
    session.commit()

    # Re-running a sync must not re-download what is already on disk.
    assert second.reused == 1 and second.downloaded == 0
    assert client.calls == 1


def test_force_redownloads(session, settings, evidence):
    client = _FakeClient()
    gateway = _FakeGateway(client)
    download_attachments(session, gateway, settings, "20USEM20000041")
    session.commit()
    again = download_attachments(session, gateway, settings, "20USEM20000041", force=True)
    session.commit()

    assert again.downloaded == 1
    assert client.calls == 2


def test_a_pdb_failure_is_counted_not_raised(session, settings, evidence):
    stats = download_attachments(
        session, _FakeGateway(_FakeClient(fail=True)), settings, "20USEM20000041"
    )
    session.commit()

    assert stats.failed == 1 and stats.downloaded == 0
    # The row still exists so the UI can show that an attachment is known but
    # not yet mirrored, rather than pretending it does not exist.
    assert session.scalar(select(TestRunAttachment)) is not None


def test_unconfigured_gateway_downloads_nothing(session, settings, evidence):
    stats = download_attachments(
        session, _FakeGateway(configured=False), settings, "20USEM20000041"
    )
    session.commit()
    assert stats.downloaded == 0 and stats.failed == 1


def test_no_attachments_is_not_an_error(session, settings):
    stats = download_attachments(session, _FakeGateway(), settings, "UNKNOWN-SN")
    assert stats.total == 0


# --- serving ---------------------------------------------------------------


def test_resolve_path_refuses_an_escaping_row(session, settings, evidence, tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("not yours", encoding="utf-8")

    download_attachments(session, _FakeGateway(), settings, "20USEM20000041")
    session.commit()
    row = session.scalar(select(TestRunAttachment))
    # Simulate a hand-edited database row pointing outside the store.
    row.relative_path = "../secret.txt"
    session.flush()

    assert resolve_path(settings, row) is None


def test_resolve_path_is_none_when_the_file_is_gone(session, settings, evidence):
    download_attachments(session, _FakeGateway(), settings, "20USEM20000041")
    session.commit()
    row = session.scalar(select(TestRunAttachment))
    resolve_path(settings, row).unlink()

    assert resolve_path(settings, row) is None


def test_attachment_root_is_created(settings):
    root = attachment_store.attachment_root(settings)
    assert root.is_dir()
