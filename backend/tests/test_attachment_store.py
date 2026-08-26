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

    url = "https://cernbox.cern.ch/s/public/photo.jpg"
    opens: list[str] = []
    answers = [
        HTTPError(url, 503, "Service Unavailable", None, None),
        _PublicResponse(url, JPEG),
    ]

    def open_url(requested, timeout):
        opens.append(requested)
        answer = answers[min(len(opens), len(answers)) - 1]
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(attachment_store, "_open_public_url", open_url)
    _set_attachment_descriptor(
        session,
        evidence,
        {"code": "e" * 64, "type": "share_link", "source": "share_link", "url": url},
    )
    stats = download_attachments(session, _FakeGateway(configured=False), settings, "20USEM20000041")
    session.commit()
    assert stats.downloaded == 1
    assert len(opens) == 2
    assert no_sleep == [0.5]

    # A 404 is the share answering "this does not exist" — retrying is noise.
    opens.clear()
    no_sleep.clear()
    answers[:] = [HTTPError(url, 404, "Not Found", None, None)]
    _set_attachment_descriptor(
        session,
        evidence,
        {"code": "f" * 64, "type": "share_link", "source": "share_link", "url": url},
    )
    stats = download_attachments(session, _FakeGateway(configured=False), settings, "20USEM20000041")
    assert stats.failed == 1
    assert len(opens) == 1
    assert no_sleep == []


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
