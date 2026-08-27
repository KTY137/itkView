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


# --- download route and payload validation ---------------------------------


HTML_ERROR_PAGE = b"<!DOCTYPE html><html><body>Sign in to continue</body></html>"


class _RoutingClient:
    """Records which routes were tried and what each one answers."""

    def __init__(self, answers):
        self.answers = answers
        self.calls: list[str] = []

    def get(self, action, json=None):
        self.calls.append(action)
        answer = self.answers.get(action)
        if answer is None:
            raise RuntimeError(f"no answer configured for {action}")

        class _File:
            content = answer[0]
            mimetype = answer[1]

        return _File()


def test_the_working_route_is_tried_first(session, settings, evidence):
    """getTestRunAttachment is the route that returns the file.

    The binary store answered a 200 with an HTML page during live validation,
    so trying it first would store that page and call it a success.
    """
    client = _RoutingClient(
        {
            "getTestRunAttachment": (JPEG, "image/jpeg"),
            "uu-app-binarystore/getBinaryData": (HTML_ERROR_PAGE, "text/html"),
        }
    )
    stats = download_attachments(session, _FakeGateway(client), settings, "20USEM20000041")
    session.commit()

    assert client.calls == ["getTestRunAttachment"]
    assert stats.downloaded == 1
    assert resolve_path(settings, session.scalar(select(TestRunAttachment))).read_bytes() == JPEG


def test_an_html_answer_is_refused(session, settings, evidence):
    """A 200 carrying an error page is a failure, not a file.

    Stored, it would be the right size with the right name and render as a
    broken image — a failure that looks like a success everywhere but the screen.
    """
    client = _RoutingClient(
        {
            "getTestRunAttachment": (HTML_ERROR_PAGE, "text/html"),
            "uu-app-binarystore/getBinaryData": (HTML_ERROR_PAGE, "text/html"),
        }
    )
    stats = download_attachments(session, _FakeGateway(client), settings, "20USEM20000041")
    session.commit()

    assert stats.downloaded == 0 and stats.failed == 1
    assert resolve_path(settings, session.scalar(select(TestRunAttachment))) is None


def test_the_binary_store_is_used_as_a_fallback(session, settings, evidence):
    client = _RoutingClient(
        {
            "getTestRunAttachment": (b"", None),
            "uu-app-binarystore/getBinaryData": (JPEG, "image/jpeg"),
        }
    )
    stats = download_attachments(session, _FakeGateway(client), settings, "20USEM20000041")
    session.commit()

    assert client.calls == ["getTestRunAttachment", "uu-app-binarystore/getBinaryData"]
    assert stats.downloaded == 1


def test_the_sniffed_content_type_wins_over_the_listing(session, settings, evidence):
    """The listing often says "file"; itkdb sniffs what it actually is."""
    client = _RoutingClient({"getTestRunAttachment": (b"%PDF-1.4 body", "application/pdf")})
    download_attachments(session, _FakeGateway(client), settings, "20USEM20000041")
    session.commit()

    row = session.scalar(select(TestRunAttachment))
    assert row.content_type == "application/pdf"
    # And the stored name follows the real type, not the claimed one.
    assert row.relative_path.endswith(".pdf")


def test_looks_like_html_detects_the_usual_shapes():
    from app.attachment_store import looks_like_html

    for page in (b"<!DOCTYPE html>", b"<html><body>", b"<?xml version"):
        assert looks_like_html(page), page
    assert not looks_like_html(JPEG)
    assert not looks_like_html(b"")


def test_instrument_data_keeps_its_suffix():
    """Instrument output arrives as octet-stream; the name is the only clue."""
    assert storage_path("SN", "c", "application/octet-stream", "iv_002.dat") == "SN/c.dat"
    assert storage_path("SN", "c", "application/octet-stream", "run.log") == "SN/c.log"


def test_an_executable_suffix_is_still_refused():
    for name in ("payload.exe", "script.bat", "lib.dll", "run.ps1", "x.cmd"):
        assert storage_path("SN", "c", "application/octet-stream", name) == "SN/c", name


# --- EOS and public share-link sources -------------------------------------


class _PublicHeaders:
    def __init__(self, content_type: str):
        self._content_type = content_type

    def get_content_type(self):
        return self._content_type


class _PublicResponse:
    def __init__(self, url: str, data: bytes, content_type: str = "image/jpeg"):
        self._url = url
        self._data = data
        self.headers = _PublicHeaders(content_type)

    def read(self, limit: int):
        return self._data[:limit]

    def geturl(self):
        return self._url

    def close(self):
        return None


def _set_attachment_descriptor(session, evidence, descriptor):
    row = session.scalar(select(TestRunEvidence).where(TestRunEvidence.external_ref == "RUN-1"))
    row.payload = {"attachments": [descriptor]}
    session.commit()


def test_share_link_download_is_unauthenticated_and_indexed_by_source(
    session, settings, evidence, monkeypatch
):
    url = "https://cernbox.cern.ch/s/public/photo.jpg"
    _set_attachment_descriptor(
        session,
        evidence,
        {
            "code": "a" * 64,
            "filename": "photo.jpg",
            "content_type": None,
            "title": "Visual inspection",
            "type": "share_link",
            "source": "share_link",
            "url": url,
        },
    )
    monkeypatch.setattr(
        attachment_store,
        "_open_public_url",
        lambda requested, timeout: _PublicResponse(requested, JPEG),
    )

    # Public share links must not require or receive PDB credentials.
    stats = download_attachments(
        session,
        _FakeGateway(configured=False),
        settings,
        "20USEM20000041",
    )
    session.commit()

    row = session.scalar(select(TestRunAttachment))
    assert stats.downloaded == 1
    assert row.source == "share_link"
    assert resolve_path(settings, row).read_bytes() == JPEG


@pytest.mark.parametrize(
    "payload,max_bytes",
    [(HTML_ERROR_PAGE, 1024), (b"12345", 4)],
)
def test_share_link_refuses_html_and_oversized_payloads(
    session, settings, evidence, monkeypatch, payload, max_bytes
):
    url = "https://cernbox.cern.ch/s/public/data"
    _set_attachment_descriptor(
        session,
        evidence,
        {
            "code": "b" * 64,
            "type": "share_link",
            "source": "share_link",
            "url": url,
        },
    )
    settings.attachment_max_bytes = max_bytes
    monkeypatch.setattr(
        attachment_store,
        "_open_public_url",
        lambda requested, timeout: _PublicResponse(requested, payload, "text/plain"),
    )

    stats = download_attachments(session, _FakeGateway(), settings, "20USEM20000041")

    assert stats.failed == 1
    assert resolve_path(settings, session.scalar(select(TestRunAttachment))) is None


def test_share_link_refuses_local_or_credential_bearing_urls(
    session, settings, evidence, monkeypatch
):
    called = False

    def should_not_open(url, timeout):
        nonlocal called
        called = True
        raise AssertionError("unsafe URL must be rejected before opening")

    monkeypatch.setattr(attachment_store, "_open_public_url", should_not_open)
    for index, url in enumerate(
        ("http://127.0.0.1/private", "https://user:password@example.org/file"),
        start=1,
    ):
        _set_attachment_descriptor(
            session,
            evidence,
            {
                "code": str(index) * 64,
                "type": "share_link",
                "source": "share_link",
                "url": url,
            },
        )
        stats = download_attachments(session, _FakeGateway(), settings, "20USEM20000041")
        assert stats.failed == 1
    assert called is False


# --- transient-vs-permanent download failures -------------------------------
#
# A real institute sweep finished with attachments_failed=11 of 363 during a
# short home-connection outage: every network hiccup used to count as a final
# failure for this sweep. A transient error must now be retried with backoff
# (bounded by settings.sync_page_max_attempts, the shared budget), while a
# permanent answer (404, HTML page, oversized) must fail immediately.


class _FlakyClient:
    """Raises for the first N `get` calls, then serves the JPEG."""

    def __init__(self, failures: int, make_error=None):
        self._failures = failures
        self._make_error = make_error or (
            lambda: ConnectionResetError("Connection reset by peer")
        )
        self.calls = 0

    def get(self, action, json=None):
        self.calls += 1
        if self.calls <= self._failures:
            raise self._make_error()

        class _BinaryFile:
            content = JPEG
            mimetype = "image/jpeg"

        return _BinaryFile()


class _HttpStatusError(RuntimeError):
    """Shape of an itkdb ResponseException: carries a requests-like response."""

    def __init__(self, status: int):
        super().__init__(f"HTTP {status}")

        class _Response:
            status_code = status

        self.response = _Response()


@pytest.fixture()
def no_sleep(monkeypatch):
    naps: list[float] = []
    monkeypatch.setattr(attachment_store, "sleep", naps.append)
    return naps


def test_transient_network_error_is_retried_then_succeeds(
    session, settings, evidence, no_sleep
):
    client = _FlakyClient(failures=2)
    stats = download_attachments(session, _FakeGateway(client), settings, "20USEM20000041")
    session.commit()

    # Attempt 1 tries both routes (2 calls), backs off, attempt 2 succeeds.
    assert stats.downloaded == 1 and stats.failed == 0
    assert client.calls == 3
    assert no_sleep == [0.5]
    row = session.scalar(select(TestRunAttachment))
    assert resolve_path(settings, row).read_bytes() == JPEG


def test_transient_retry_budget_follows_the_shared_setting(
    session, evidence, no_sleep, tmp_path
):
    settings = Settings(
        database_url="sqlite:///:memory:",
        attachment_dir=str(tmp_path / "attachments"),
        sync_page_max_attempts=2,
        _env_file=None,
    )
    client = _FlakyClient(failures=99, make_error=lambda: TimeoutError("timed out"))

    stats = download_attachments(session, _FakeGateway(client), settings, "20USEM20000041")
    session.commit()

    assert stats.failed == 1 and stats.downloaded == 0
    # Two attempts of two routes each, one backoff between them — then honest failure.
    assert client.calls == 4
    assert no_sleep == [0.5]
    assert resolve_path(settings, session.scalar(select(TestRunAttachment))) is None


def test_a_permanent_http_answer_is_not_retried(session, settings, evidence, no_sleep):
    client = _FlakyClient(failures=99, make_error=lambda: _HttpStatusError(404))

    stats = download_attachments(session, _FakeGateway(client), settings, "20USEM20000041")
    session.commit()

    assert stats.failed == 1
    # Each route is tried once (the fallback exists for exactly this case);
    # a 404 will not turn into a file by waiting, so there is no backoff.
    assert client.calls == 2
    assert no_sleep == []


def test_a_server_error_answer_is_retried(session, settings, evidence, no_sleep):
    client = _FlakyClient(failures=2, make_error=lambda: _HttpStatusError(503))

    stats = download_attachments(session, _FakeGateway(client), settings, "20USEM20000041")
    session.commit()

    assert stats.downloaded == 1
    assert client.calls == 3
    assert no_sleep == [0.5]


def test_an_html_answer_is_permanent_and_not_retried(session, settings, evidence, no_sleep):
    client = _RoutingClient(
        {
            "getTestRunAttachment": (HTML_ERROR_PAGE, "text/html"),
            "uu-app-binarystore/getBinaryData": (HTML_ERROR_PAGE, "text/html"),
        }
    )
    stats = download_attachments(session, _FakeGateway(client), settings, "20USEM20000041")

    assert stats.failed == 1
    assert client.calls == ["getTestRunAttachment", "uu-app-binarystore/getBinaryData"]
    assert no_sleep == []


def test_a_failed_attachment_is_retried_on_the_next_sweep(
    session, settings, evidence, no_sleep
):
    """A failure must never be recorded as stored; the next sweep tries again."""
    outage = _FlakyClient(failures=99)
    first = download_attachments(session, _FakeGateway(outage), settings, "20USEM20000041")
    session.commit()
    assert first.failed == 1
    row = session.scalar(select(TestRunAttachment))
    assert row is not None and resolve_path(settings, row) is None

    second = download_attachments(session, _FakeGateway(_FakeClient()), settings, "20USEM20000041")
    session.commit()

    assert second.downloaded == 1 and second.reused == 0 and second.failed == 0
    assert resolve_path(settings, session.scalar(select(TestRunAttachment))) is not None


def test_transient_client_construction_is_retried(session, settings, evidence, no_sleep):
    class _FlakyGateway:
        is_configured = True

        def __init__(self):
            self.client_calls = 0
            self._client = _FakeClient()

        def client(self):
            self.client_calls += 1
            if self.client_calls == 1:
                raise ConnectionResetError("Connection reset by peer")
            return self._client

    gateway = _FlakyGateway()
    stats = download_attachments(session, gateway, settings, "20USEM20000041")
    session.commit()

    assert stats.downloaded == 1
    assert gateway.client_calls == 2
    assert no_sleep == [0.5]


def test_exhausted_client_construction_fails_remaining_files_fast(
    session, settings, evidence, no_sleep
):
    """Without a client every PDB descriptor fails identically; hammering the
    gateway once per file only stretches the outage. The next sweep retries."""
    row = session.scalar(select(TestRunEvidence).where(TestRunEvidence.external_ref == "RUN-1"))
    row.payload = {
        "attachments": [
            {"code": "c" * 8, "filename": "a.jpg", "content_type": "image/jpeg", "title": None},
            {"code": "d" * 8, "filename": "b.jpg", "content_type": "image/jpeg", "title": None},
        ]
    }
    session.commit()

    class _DownGateway:
        is_configured = True

        def __init__(self):
            self.client_calls = 0

        def client(self):
            self.client_calls += 1
            raise ConnectionResetError("Connection reset by peer")

    gateway = _DownGateway()
    stats = download_attachments(session, gateway, settings, "20USEM20000041")
    session.commit()

    assert stats.failed == 2
    # Bounded by the retry budget once, not once per attachment.
    assert gateway.client_calls == 3
    assert no_sleep == [0.5, 1.0]


def test_share_link_server_error_is_retried_and_client_error_is_not(
    session, settings, evidence, monkeypatch, no_sleep
):
    from urllib.error import HTTPError

    # Not a recognisable /s/<token> share form: exactly one candidate URL.
    url = "https://files.example.org/plots/photo.jpg"
    opens: list[str] = []
    outage_opens = 2

    def open_url(requested, timeout):
        opens.append(requested)
        if len(opens) <= outage_opens:
            raise HTTPError(requested, 503, "Service Unavailable", None, None)
        return _PublicResponse(requested, JPEG)

    monkeypatch.setattr(attachment_store, "_open_public_url", open_url)
    _set_attachment_descriptor(
        session,
        evidence,
        {"code": "e" * 64, "type": "share_link", "source": "share_link", "url": url},
    )
    stats = download_attachments(
        session, _FakeGateway(configured=False), settings, "20USEM20000041"
    )
    session.commit()
    assert stats.downloaded == 1
    assert len(opens) == 3
    assert no_sleep == [0.5, 1.0]

    # A 404 is the share answering "this does not exist" — retrying is noise.
    opens.clear()
    no_sleep.clear()

    def open_404(requested, timeout):
        opens.append(requested)
        raise HTTPError(requested, 404, "Not Found", None, None)

    monkeypatch.setattr(attachment_store, "_open_public_url", open_404)
    _set_attachment_descriptor(
        session,
        evidence,
        {"code": "f" * 64, "type": "share_link", "source": "share_link", "url": url},
    )
    stats = download_attachments(
        session, _FakeGateway(configured=False), settings, "20USEM20000041"
    )
    assert stats.failed == 1
    assert len(opens) == 1
    assert no_sleep == []


SHARE_TOKEN = "6LPpeXmuIBwS5ST"
SHARE_URL = f"https://cernbox.cern.ch/index.php/s/{SHARE_TOKEN}"
DAV_URL = f"https://cernbox.cern.ch/remote.php/dav/public-files/{SHARE_TOKEN}"
DOWNLOAD_URL = f"https://cernbox.cern.ch/s/{SHARE_TOKEN}/download"


def _stage_share_descriptor(session, evidence, code: str, url: str = SHARE_URL) -> None:
    _set_attachment_descriptor(
        session,
        evidence,
        {
            "code": code,
            "filename": SHARE_TOKEN,
            "content_type": None,
            "type": "share_link",
            "source": "share_link",
            "url": url,
        },
    )


def test_share_token_url_downloads_via_the_dav_route(
    session, settings, evidence, monkeypatch, no_sleep
):
    """A CERNBox/ownCloud share link points at an HTML viewer page, not the
    file (verified live: the plain URL answers `text/html`). The WebDAV
    public-files route serves the actual bytes and is tried first."""
    opens: list[str] = []

    def open_url(requested, timeout):
        opens.append(requested)
        if "/remote.php/dav/public-files/" in requested:
            return _PublicResponse(requested, JPEG, "image/jpeg")
        return _PublicResponse(requested, HTML_ERROR_PAGE, "text/html")

    monkeypatch.setattr(attachment_store, "_open_public_url", open_url)
    _stage_share_descriptor(session, evidence, "a1" * 32)

    stats = download_attachments(
        session, _FakeGateway(configured=False), settings, "20USEM20000041"
    )
    session.commit()

    assert stats.downloaded == 1 and stats.failed == 0
    assert opens == [DAV_URL]
    assert no_sleep == []
    row = session.scalar(
        select(TestRunAttachment).where(TestRunAttachment.pdb_code == "a1" * 32)
    )
    assert resolve_path(settings, row).read_bytes() == JPEG
    # The descriptor carries no content type for share links; the stored one
    # must come from the response so `is_image` and the thumbnail work.
    assert row.content_type == "image/jpeg"
    assert row.is_image is True
    assert row.relative_path.endswith(".jpg")


def test_share_page_html_falls_back_to_the_download_route(
    session, settings, evidence, monkeypatch, no_sleep
):
    opens: list[str] = []

    def open_url(requested, timeout):
        opens.append(requested)
        if requested.endswith("/download"):
            return _PublicResponse(requested, JPEG, "image/jpeg")
        return _PublicResponse(requested, HTML_ERROR_PAGE, "text/html")

    monkeypatch.setattr(attachment_store, "_open_public_url", open_url)
    _stage_share_descriptor(session, evidence, "b2" * 32)

    stats = download_attachments(
        session, _FakeGateway(configured=False), settings, "20USEM20000041"
    )
    session.commit()

    assert stats.downloaded == 1 and stats.failed == 0
    assert opens == [DAV_URL, DOWNLOAD_URL]
    row = session.scalar(
        select(TestRunAttachment).where(TestRunAttachment.pdb_code == "b2" * 32)
    )
    assert resolve_path(settings, row).read_bytes() == JPEG


def test_a_share_that_only_serves_html_fails_and_stays_retryable(
    session, settings, evidence, monkeypatch, no_sleep
):
    """A viewer page must never be stored as the attachment — and the failure
    must not be final: once the share works again, the next sweep mirrors it."""
    opens: list[str] = []

    def only_html(requested, timeout):
        opens.append(requested)
        return _PublicResponse(requested, HTML_ERROR_PAGE, "text/html")

    monkeypatch.setattr(attachment_store, "_open_public_url", only_html)
    _stage_share_descriptor(session, evidence, "c3" * 32)

    stats = download_attachments(
        session, _FakeGateway(configured=False), settings, "20USEM20000041"
    )
    session.commit()

    assert stats.failed == 1 and stats.downloaded == 0
    # HTML is a final answer for this sweep: all candidates once, no backoff.
    assert opens == [DAV_URL, DOWNLOAD_URL, SHARE_URL]
    assert no_sleep == []
    row = session.scalar(
        select(TestRunAttachment).where(TestRunAttachment.pdb_code == "c3" * 32)
    )
    assert resolve_path(settings, row) is None

    monkeypatch.setattr(
        attachment_store,
        "_open_public_url",
        lambda requested, timeout: _PublicResponse(requested, JPEG, "image/jpeg"),
    )
    second = download_attachments(
        session, _FakeGateway(configured=False), settings, "20USEM20000041"
    )
    session.commit()
    assert second.downloaded == 1
    assert resolve_path(settings, session.scalar(
        select(TestRunAttachment).where(TestRunAttachment.pdb_code == "c3" * 32)
    )) is not None


def test_share_link_candidates_cover_both_share_url_forms():
    candidates = attachment_store._share_link_candidates
    # Both public-share URL forms yield: DAV public-files, /s/<token>/download,
    # then the original URL as last resort. Never /index.php/.../download —
    # that form failed name resolution during live validation.
    for base in ("https://cernbox.cern.ch/s/tok", "https://cernbox.cern.ch/index.php/s/tok"):
        assert candidates(base) == [
            "https://cernbox.cern.ch/remote.php/dav/public-files/tok",
            "https://cernbox.cern.ch/s/tok/download",
            base,
        ]
    # Already-direct download forms are used as-is.
    direct = "https://cernbox.cern.ch/s/tok/download"
    assert candidates(direct) == [direct]
    named = "https://syncandshare.example.org/index.php/s/tok/download/metro_current.txt"
    assert candidates(named) == [named]
    # A URL that is not a recognisable share form is fetched as-is.
    plain_file = "https://files.example.org/plots/iv_curve.png"
    assert candidates(plain_file) == [plain_file]


def test_same_filename_across_runs_all_land_on_disk(session, settings):
    """Observed live: several runs of one module carry attachments with the
    identical filename but distinct PDB codes, and one variant stayed
    unstored. The storage name is the code, so every variant must land —
    none may shadow or overwrite another."""
    for index in range(3):
        session.add(
            TestRunEvidence(
                component_sn="20USEM20000042",
                test_type="MODULE_BOW",
                passed=True,
                source="pdb",
                external_ref=f"BOW-RUN-{index}",
                payload={
                    "attachments": [
                        {
                            "code": f"bowcode{index}",
                            "filename": "R5M0_bowmeasure.txt",
                            "content_type": "text/plain",
                            "title": None,
                        }
                    ]
                },
            )
        )
    session.commit()

    stats = download_attachments(session, _FakeGateway(), settings, "20USEM20000042")
    session.commit()

    assert stats.downloaded == 3 and stats.failed == 0
    rows = session.scalars(
        select(TestRunAttachment).order_by(TestRunAttachment.pdb_code)
    ).all()
    assert len(rows) == 3
    assert len({row.relative_path for row in rows}) == 3
    for row in rows:
        assert resolve_path(settings, row) is not None


def test_a_duplicate_code_across_runs_stays_stored(session, settings):
    """The same PDB code listed by two runs is one file: downloaded once,
    reused for the second descriptor, and never flipped back to unstored."""
    for run in ("RUN-A", "RUN-B"):
        session.add(
            TestRunEvidence(
                component_sn="20USEM20000043",
                test_type="MODULE_BOW",
                passed=True,
                source="pdb",
                external_ref=run,
                payload={
                    "attachments": [
                        {
                            "code": "sharedcode",
                            "filename": "R5M0_bowmeasure.txt",
                            "content_type": "text/plain",
                            "title": None,
                        }
                    ]
                },
            )
        )
    session.commit()

    stats = download_attachments(session, _FakeGateway(), settings, "20USEM20000043")
    session.commit()

    assert stats.downloaded == 1 and stats.reused == 1 and stats.failed == 0
    row = session.scalar(select(TestRunAttachment))
    assert resolve_path(settings, row) is not None


def test_download_heartbeat_fires_per_file_and_per_retry(
    session, settings, evidence, no_sleep
):
    """A slow attachment phase must keep the durable job heartbeat fresh:
    three 60s attempts plus backoff exceed the 3-minute startup-recovery grace."""
    beats: list[int] = []
    client = _FlakyClient(failures=2)

    download_attachments(
        session,
        _FakeGateway(client),
        settings,
        "20USEM20000041",
        heartbeat=lambda: beats.append(1),
    )

    # Once before the retry backoff, once when the file is done.
    assert len(beats) == 2


@pytest.mark.parametrize(
    "error,expected",
    [
        # DNS never resolving is an outage, not an answer.
        (__import__("socket").gaierror(-2, "Name or service not known"), True),
        (__import__("socket").gaierror(11001, "getaddrinfo failed"), True),
        (ConnectionResetError(104, "Connection reset by peer"), True),
        (ConnectionRefusedError(111, "Connection refused"), True),
        (TimeoutError("timed out"), True),
        (__import__("ssl").SSLError("The handshake operation timed out"), True),
        (_HttpStatusError(502), True),
        (_HttpStatusError(503), True),
        (_HttpStatusError(504), True),
        (_HttpStatusError(408), True),
        (_HttpStatusError(429), True),
        # 4xx means the request itself is wrong or the file is gone.
        (_HttpStatusError(400), False),
        (_HttpStatusError(403), False),
        (_HttpStatusError(404), False),
        (RuntimeError("PDB said no"), False),
        (ValueError("bad descriptor"), False),
    ],
)
def test_transient_download_classification(error, expected):
    assert attachment_store.is_transient_download_error(error) is expected


def test_transient_download_classification_walks_the_cause_chain():
    try:
        try:
            raise TimeoutError("timed out")
        except TimeoutError as inner:
            raise RuntimeError("itkdb wrapped it") from inner
    except RuntimeError as wrapped:
        assert attachment_store.is_transient_download_error(wrapped) is True


def test_urllib_http_errors_classify_by_status():
    from urllib.error import HTTPError

    url = "https://cernbox.cern.ch/s/public/x"
    assert attachment_store.is_transient_download_error(
        HTTPError(url, 503, "Service Unavailable", None, None)
    )
    assert not attachment_store.is_transient_download_error(
        HTTPError(url, 404, "Not Found", None, None)
    )


class _EosClient:
    def __init__(self):
        self.detail_calls = 0
        self.download_urls: list[str] = []

    def get(self, action, json=None):
        if action == "getTestRun":
            self.detail_calls += 1
            assert json == {"testRun": "RUN-1", "noEosToken": False}
            return {
                "attachments": [
                    {
                        "code": "eos-code",
                        "type": "eos",
                        "url": (
                            "https://eosatlas.cern.ch/eos/photo.jpg"
                            f"?fresh-signature={self.detail_calls}"
                        ),
                    }
                ]
            }
        if isinstance(action, str) and action.startswith("https://eosatlas.cern.ch/"):
            self.download_urls.append(action)

            class _BinaryFile:
                content = JPEG
                mimetype = "image/jpeg"

            return _BinaryFile()
        raise AssertionError(f"unexpected EOS request: {action}")


def test_eos_download_refreshes_the_signed_url_and_never_persists_it(session, settings, evidence):
    _set_attachment_descriptor(
        session,
        evidence,
        {
            "code": "eos-code",
            "filename": "photo.jpg",
            "content_type": "image/jpeg",
            "type": "eos",
            "source": "pdb",
            "url": "https://eosatlas.cern.ch/eos/photo.jpg",
        },
    )
    client = _EosClient()
    gateway = _FakeGateway(client)

    first = download_attachments(session, gateway, settings, "20USEM20000041")
    session.commit()
    second = download_attachments(
        session,
        gateway,
        settings,
        "20USEM20000041",
        force=True,
    )
    session.commit()

    assert first.downloaded == second.downloaded == 1
    assert client.detail_calls == 2
    assert client.download_urls[0] != client.download_urls[1]
    row = session.scalar(select(TestRunAttachment))
    assert "fresh-signature" not in repr(vars(row))
    mirrored = session.scalar(
        select(TestRunEvidence).where(TestRunEvidence.external_ref == "RUN-1")
    )
    assert "fresh-signature" not in repr(mirrored.payload)


# --- phased download: bytes before transaction, no .part corpses -----------
#
# A real institute sweep held SQLite's write lock open for as long as a
# retried, multi-megabyte image took to download: `_upsert_row` + `flush()`
# ran *before* the network fetch, so every other HTTP request and worker tick
# saw "database is locked" while one attachment was still in flight. Bytes
# must now be fully fetched (and staged on disk) before any row is touched.


def test_no_session_writes_are_pending_during_the_network_fetch(
    session, settings, evidence
):
    """Pins "bytes before transaction": while the fake client is answering a
    `.get()` call, nothing may be staged on the session yet."""
    observed: list[tuple[int, int]] = []

    class _WatchingClient:
        def get(self, action, json=None):
            observed.append((len(session.new), len(session.dirty)))

            class _BinaryFile:
                content = JPEG
                mimetype = "image/jpeg"

            return _BinaryFile()

    stats = download_attachments(
        session, _FakeGateway(_WatchingClient()), settings, "20USEM20000041"
    )
    session.commit()

    assert stats.downloaded == 1
    assert observed, "the fake client was never called"
    assert observed == [(0, 0)] * len(observed)


def test_a_concurrent_writer_is_never_blocked_during_the_network_fetch(tmp_path):
    """The actual production incident, reproduced: a second, independent
    connection to the same database file must be able to write while a
    download is in flight. `session.new`/`session.dirty` being empty (the
    test above) is necessary but not sufficient — a `flush()` without commit
    clears both while still holding SQLite's write lock. This uses a
    file-backed database (`:memory:` is not shared across connections) and a
    raw second `sqlite3` connection to prove the lock itself is free.

    Confirmed to reproduce against the pre-fix implementation: the probe
    below fails with "database is locked" when `_upsert_row` + `flush()` run
    before the network call.
    """
    import sqlite3

    db_path = tmp_path / "lock_probe.db"
    settings = Settings(
        database_url=f"sqlite:///{db_path}",
        attachment_dir=str(tmp_path / "attachments"),
        _env_file=None,
    )
    engine = make_engine(settings.database_url)
    Base.metadata.create_all(engine)
    session = make_session_factory(engine)()
    try:
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

        probe_errors: list[str] = []

        class _WatchingClient:
            def get(self, action, json=None):
                probe = sqlite3.connect(str(db_path), timeout=0.3)
                try:
                    probe.execute("PRAGMA user_version = 42")
                    probe.commit()
                except sqlite3.OperationalError as exc:
                    probe_errors.append(str(exc))
                finally:
                    probe.close()

                class _BinaryFile:
                    content = JPEG
                    mimetype = "image/jpeg"

                return _BinaryFile()

        stats = download_attachments(
            session, _FakeGateway(_WatchingClient()), settings, "20USEM20000041"
        )
        session.commit()
    finally:
        session.close()

    assert stats.downloaded == 1
    assert probe_errors == []


def test_a_failed_download_leaves_no_part_file_and_no_relative_path(
    session, settings, evidence
):
    stats = download_attachments(
        session, _FakeGateway(_FakeClient(fail=True)), settings, "20USEM20000041"
    )
    session.commit()

    assert stats.failed == 1
    row = session.scalar(select(TestRunAttachment))
    assert row.relative_path is None
    root = attachment_store.attachment_root(settings)
    assert list(root.rglob("*.part")) == []


def test_a_successful_download_lands_on_the_final_name_with_no_part_file(
    session, settings, evidence
):
    stats = download_attachments(session, _FakeGateway(), settings, "20USEM20000041")
    session.commit()

    assert stats.downloaded == 1
    row = session.scalar(select(TestRunAttachment))
    stored = resolve_path(settings, row)
    assert stored is not None and stored.name == "abc123.jpg"
    root = attachment_store.attachment_root(settings)
    assert list(root.rglob("*.part")) == []


def test_a_stale_part_file_from_a_crashed_run_is_overwritten(
    session, settings, evidence
):
    """A previous process could die mid-write; the leftover `.part` file must
    not make the next sweep fail or serve stale bytes."""
    root = attachment_store.attachment_root(settings)
    stale = root / "20USEM20000041" / "abc123.jpg.part"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_bytes(b"leftover-from-a-crashed-process")

    stats = download_attachments(session, _FakeGateway(), settings, "20USEM20000041")
    session.commit()

    assert stats.downloaded == 1
    row = session.scalar(select(TestRunAttachment))
    assert resolve_path(settings, row).read_bytes() == JPEG
    assert list(root.rglob("*.part")) == []


# --- outage circuit breaker --------------------------------------------------
#
# During a full outage every remaining file still burns its complete
# transient-retry ladder (attempts x read timeout + backoff, minutes per
# file); with hundreds of pending files a sweep crawls for hours at zero
# progress while looking alive. Several *consecutive* transient failures are
# therefore read as "the network is down", not "these files are broken": the
# caller stops the phase and fails transiently so the automatic retry can
# resume once the outage is over. Permanent per-file answers stay best effort.


def test_breaker_trips_after_consecutive_transient_failures():
    breaker = attachment_store.OutageCircuitBreaker(threshold=3)
    breaker.record_failure(transient=True)
    breaker.record_failure(transient=True)
    assert breaker.tripped is False
    breaker.record_failure(transient=True)
    assert breaker.tripped is True


def test_permanent_failures_and_successes_reset_the_breaker():
    breaker = attachment_store.OutageCircuitBreaker(threshold=2)
    breaker.record_failure(transient=True)
    breaker.record_failure(transient=False)  # a 404/HTML page is a real answer
    breaker.record_failure(transient=True)
    breaker.record_success()
    breaker.record_failure(transient=True)
    assert breaker.tripped is False


def test_the_default_breaker_threshold_is_a_small_named_constant():
    assert attachment_store.ATTACHMENT_OUTAGE_BREAKER_THRESHOLD == 5
    assert (
        attachment_store.OutageCircuitBreaker().threshold
        == attachment_store.ATTACHMENT_OUTAGE_BREAKER_THRESHOLD
    )


def _add_many_attachments(session, count: int) -> None:
    session.add(
        TestRunEvidence(
            component_sn="20USEM20000050",
            test_type="VISUAL_INSPECTION",
            passed=True,
            source="pdb",
            external_ref="RUN-9",
            payload={
                "attachments": [
                    {
                        "code": f"breaker-code-{index}",
                        "filename": f"photo-{index}.jpg",
                        "content_type": "image/jpeg",
                        "title": None,
                    }
                    for index in range(count)
                ]
            },
        )
    )
    session.commit()


def test_a_tripped_breaker_stops_fetching_remaining_files(session, settings, no_sleep):
    _add_many_attachments(session, 4)
    client = _FlakyClient(failures=999)  # network-shaped forever
    breaker = attachment_store.OutageCircuitBreaker(threshold=2)

    stats = download_attachments(
        session, _FakeGateway(client), settings, "20USEM20000050", breaker=breaker
    )
    session.commit()

    assert breaker.tripped is True
    # Only the files that tripped the breaker were attempted; the rest are
    # left for the retried job instead of burning their own ladders too.
    assert stats.failed == 2 and stats.total == 2
    # Each attempted file exhausted its full ladder first (3 attempts x 2 routes).
    assert client.calls == 12


def test_permanent_file_failures_never_trip_the_breaker(session, settings, no_sleep):
    _add_many_attachments(session, 4)
    client = _FlakyClient(failures=999, make_error=lambda: _HttpStatusError(404))
    breaker = attachment_store.OutageCircuitBreaker(threshold=2)

    stats = download_attachments(
        session, _FakeGateway(client), settings, "20USEM20000050", breaker=breaker
    )
    session.commit()

    assert breaker.tripped is False
    assert stats.failed == 4 and stats.total == 4


def test_transient_client_unavailability_counts_toward_the_breaker(
    session, settings, no_sleep
):
    """When the authenticated client cannot even be built during an outage,
    the fast-failed remaining files are outage-shaped too: they must be able
    to trip the breaker instead of counting as quiet per-file verdicts."""
    _add_many_attachments(session, 4)

    class _OutageGateway:
        is_configured = True

        def client(self):
            raise TimeoutError("handshake operation timed out")

    breaker = attachment_store.OutageCircuitBreaker(threshold=3)
    stats = download_attachments(
        session, _OutageGateway(), settings, "20USEM20000050", breaker=breaker
    )
    session.commit()

    assert breaker.tripped is True
    assert stats.failed == 3 and stats.total == 3


def test_download_accepts_a_precomputed_descriptor_plan(session, settings, evidence):
    """The sweep computes pending descriptors once and hands them in, instead
    of loading every evidence payload a second time inside the download."""
    descriptors = pending_attachments(session, "20USEM20000041")
    stats = download_attachments(
        session, _FakeGateway(), settings, "20USEM20000041", descriptors=descriptors
    )
    session.commit()

    assert stats.downloaded == 1
    row = session.scalar(select(TestRunAttachment))
    assert resolve_path(settings, row) is not None


def test_reuse_keeps_the_content_type_the_download_established(session, settings):
    """A PDB listing usually declares no content type; the real one is sniffed
    from the response. A later sweep that finds the file already on disk must
    not blank it — `is_image` derives from it, so a whole-site re-sweep once
    turned 430 of 432 mirrored images invisible while every byte on disk
    stayed intact. Only the second sweep proves it; the first always looked
    right.
    """
    session.add(
        TestRunEvidence(
            component_sn="20USEM20000041",
            test_type="VISUAL_INSPECTION",
            passed=True,
            source="pdb",
            external_ref="RUN-1",
            payload={
                "attachments": [
                    # As the PDB really lists it: a name, no declared type.
                    {"code": "abc123", "filename": "Untitled", "content_type": None}
                ]
            },
        )
    )
    session.commit()

    class _TypedClient(_FakeClient):
        def get(self, action, json=None):
            result = super().get(action, json)
            result.content_type = "image/jpeg"
            return result

    gateway = _FakeGateway(_TypedClient())
    first = download_attachments(session, gateway, settings, "20USEM20000041")
    session.commit()
    row = session.scalar(select(TestRunAttachment))
    assert first.downloaded == 1
    assert row.content_type == "image/jpeg" and row.is_image

    second = download_attachments(session, gateway, settings, "20USEM20000041")
    session.commit()
    session.refresh(row)

    assert second.reused == 1 and second.downloaded == 0
    assert row.content_type == "image/jpeg", "the reuse path blanked the sniffed type"
    assert row.is_image, "a mirrored image must stay visible after a re-sweep"
