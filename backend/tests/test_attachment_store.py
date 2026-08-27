"""Local attachment mirror: path safety, idempotency, partial failure."""

import ast
import gzip
import inspect
import io
import tarfile
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Lock
from urllib.error import HTTPError

import pytest
from sqlalchemy import event, select

from app import attachment_store
from app.attachment_store import (
    download_attachments,
    pending_attachments,
    resolve_path,
    storage_path,
)
from app.config import Settings
from app.db import Base, make_engine, make_session_factory
from app.models import (
    TestRunAttachment,
    TestRunAttachmentReference,
    TestRunEvidence,
)
from app.share_credentials import SharePasswordResolver, public_share_identity

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
    path = storage_path(
        "20USEM20000041", "abc123", "image/jpeg", "x.jpg", source="pdb"
    )
    assert path == "20USEM20000041/pdb/abc123.jpg"


def test_storage_path_ignores_the_pdb_filename():
    """A PDB-supplied name must never reach the filesystem."""
    path = storage_path(
        "20USEM1", "code9", "image/png", "../../evil.exe", source="pdb"
    )
    assert path == "20USEM1/pdb/code9.png"
    assert ".." not in path and "evil" not in path


def test_storage_path_sanitises_a_hostile_code():
    path = storage_path(
        "20USEM1", "../../../etc/passwd", "image/png", None, source="pdb"
    )
    assert ".." not in path
    assert path.count("/") == 2


def test_storage_path_sanitises_source_without_aliasing_distinct_names():
    first = storage_path("SN", "c", "image/png", None, source="future/source")
    second = storage_path("SN", "c", "image/png", None, source="future?source")
    empty = storage_path("SN", "c", "image/png", None, source="")
    literal_unknown = storage_path("SN", "c", "image/png", None, source="unknown")

    assert ".." not in first
    assert first.count("/") == 2
    assert first != second
    assert empty != literal_unknown


def test_unknown_content_type_gets_no_extension():
    # Better a extension-less file than writing an arbitrary one.
    assert (
        storage_path(
            "SN", "c", "application/x-msdownload", "a.exe", source="pdb"
        )
        == "SN/pdb/c"
    )


def test_extension_falls_back_to_a_trusted_suffix():
    assert storage_path("SN", "c", None, "photo.png", source="pdb") == "SN/pdb/c.png"


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
    assert row.relative_path == "20USEM20000041/pdb/abc123.jpg"
    assert row.size_bytes == len(JPEG)
    assert row.downloaded_at is not None

    stored = resolve_path(settings, row)
    assert stored is not None and stored.read_bytes() == JPEG


def test_equal_codes_from_different_sources_keep_distinct_same_suffix_files(
    session, settings, monkeypatch
):
    """The database identity `(source, code)` must also be the disk identity."""
    code = "same-code"
    component_sn = "20USEM20000041"
    payloads = {
        "pdb": b"\xff\xd8\xffpdb-image",
        "share_link": b"\xff\xd8\xffshare-image",
    }
    descriptors = [
        {
            "component_sn": component_sn,
            "test_type": "VISUAL_INSPECTION",
            "test_run_ref": f"RUN-{source}",
            "code": code,
            "filename": f"{source}.jpg",
            "content_type": "image/jpeg",
            "title": source,
            "source": source,
            "type": "share_link" if source == "share_link" else "file",
            "url": "https://example.invalid/public.jpg"
            if source == "share_link"
            else None,
        }
        for source in payloads
    ]

    def fetch_by_source(client, descriptor, *, timeout, max_bytes):  # noqa: ARG001
        return payloads[descriptor["source"]], "image/jpeg"

    monkeypatch.setattr(attachment_store, "_fetch_bytes", fetch_by_source)

    stats = download_attachments(
        session,
        _FakeGateway(),
        settings,
        component_sn,
        descriptors=descriptors,
    )
    session.commit()

    assert stats.downloaded == 2
    rows = list(
        session.scalars(
            select(TestRunAttachment)
            .where(TestRunAttachment.pdb_code == code)
            .order_by(TestRunAttachment.source)
        )
    )
    assert {row.source for row in rows} == {"pdb", "share_link"}
    assert {row.relative_path for row in rows} == {
        f"{component_sn}/pdb/{code}.jpg",
        f"{component_sn}/share_link/{code}.jpg",
    }
    assert len({row.relative_path for row in rows}) == 2
    for row in rows:
        path = resolve_path(settings, row)
        assert path is not None
        assert path.read_bytes() == payloads[row.source]
    assert len(list(session.scalars(select(TestRunAttachmentReference)))) == 2


def test_reuse_preserves_an_existing_flat_legacy_relative_path(
    session, settings, evidence
):
    legacy_relative_path = "20USEM20000041/abc123.jpg"
    legacy_path = attachment_store.attachment_root(settings) / legacy_relative_path
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_path.write_bytes(JPEG)
    row = TestRunAttachment(
        component_sn="20USEM20000041",
        test_type="VISUAL_INSPECTION",
        test_run_ref="RUN-1",
        source="pdb",
        pdb_code="abc123",
        filename="Untitled.jpg",
        content_type="image/jpeg",
        relative_path=legacy_relative_path,
        size_bytes=len(JPEG),
    )
    session.add(row)
    session.commit()

    client = _FakeClient(fail=True)
    stats = download_attachments(
        session, _FakeGateway(client), settings, "20USEM20000041"
    )
    session.commit()
    session.refresh(row)

    assert stats.reused == 1 and stats.downloaded == 0
    assert client.calls == 0
    assert row.relative_path == legacy_relative_path
    assert resolve_path(settings, row) == legacy_path.resolve()


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
    assert (
        storage_path(
            "SN", "c", "application/octet-stream", "iv_002.dat", source="pdb"
        )
        == "SN/pdb/c.dat"
    )
    assert (
        storage_path(
            "SN", "c", "application/octet-stream", "run.log", source="pdb"
        )
        == "SN/pdb/c.log"
    )


def test_an_executable_suffix_is_still_refused():
    for name in ("payload.exe", "script.bat", "lib.dll", "run.ps1", "x.cmd"):
        assert (
            storage_path(
                "SN", "c", "application/octet-stream", name, source="pdb"
            )
            == "SN/pdb/c"
        ), name


# --- EOS and public share-link sources -------------------------------------


class _PublicHeaders:
    def __init__(self, content_type: str):
        self._content_type = content_type

    def get_content_type(self):
        return self._content_type


class _PublicResponse:
    """A stand-in for `http.client.HTTPResponse`: reads *consume* the body.

    Deliberately not a slice of a fixed buffer. The mirror now sniffs the
    leading bytes of a share response before deciding whether it is a file or
    an archive, and a double whose `read` returns the same prefix forever
    would make that sniff invisible — and would hide a double-read bug behind
    a test that passes.
    """

    def __init__(self, url: str, data: bytes, content_type: str = "image/jpeg"):
        self._url = url
        self._data = data
        self._offset = 0
        self.headers = _PublicHeaders(content_type)

    def read(self, limit: int = -1):
        if limit is None or limit < 0:
            limit = len(self._data) - self._offset
        chunk = self._data[self._offset : self._offset + limit]
        self._offset += len(chunk)
        return chunk

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
    "payload,max_bytes,expected_failed,expected_skipped,expected_auth",
    [
        (HTML_ERROR_PAGE, 1024, 0, 1, 1),
        (b"12345", 4, 1, 0, 0),
    ],
)
def test_share_link_refuses_html_and_oversized_payloads(
    session,
    settings,
    evidence,
    monkeypatch,
    payload,
    max_bytes,
    expected_failed,
    expected_skipped,
    expected_auth,
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

    assert stats.failed == expected_failed
    assert stats.skipped == expected_skipped
    assert stats.authentication_required == expected_auth
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
        assert stats.failed == 0
        assert stats.skipped == 1
        assert stats.authentication_required == 0
    assert called is False


def test_password_protected_public_share_uses_account_resolver(
    session, settings, evidence, monkeypatch
):
    url = "https://cernbox.cern.ch/s/protected-share"
    _set_attachment_descriptor(
        session,
        evidence,
        {
            "code": "c" * 64,
            "type": "share_link",
            "source": "share_link",
            "url": url,
        },
    )
    calls = []

    def open_url(requested, timeout, password=None):
        calls.append((requested, timeout, password))
        return _PublicResponse(requested, JPEG, "image/jpeg")

    monkeypatch.setattr(attachment_store, "_open_public_url", open_url)
    identity = public_share_identity(url)
    resolver = SharePasswordResolver({identity.share_key: "share-secret"})

    stats = download_attachments(
        session,
        _FakeGateway(),
        settings,
        "20USEM20000041",
        share_passwords=resolver,
    )

    assert stats.downloaded == 1
    assert stats.authentication_required == 0
    assert calls[0][2] == "share-secret"
    assert "share-secret" not in repr(resolver)


def test_public_share_authorization_never_redirects_to_another_host():
    request = attachment_store.Request(
        "https://cernbox.cern.ch/remote.php/dav/public-files/token",
        headers={"Authorization": "Basic sentinel"},
    )

    with pytest.raises(HTTPError, match="Credential-bearing"):
        attachment_store._SafeShareRedirects().redirect_request(
            request,
            None,
            302,
            "Found",
            {},
            "https://attacker.example/download",
        )


def test_public_share_authorization_never_redirects_to_another_port():
    request = attachment_store.Request(
        "https://cernbox.cern.ch/remote.php/dav/public-files/token",
        headers={"Authorization": "Basic sentinel"},
    )

    with pytest.raises(HTTPError, match="Credential-bearing"):
        attachment_store._SafeShareRedirects().redirect_request(
            request,
            None,
            302,
            "Found",
            {},
            "https://cernbox.cern.ch:8443/download",
        )


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


def test_a_share_that_only_serves_html_is_skipped_and_stays_retryable(
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

    assert stats.failed == 0 and stats.downloaded == 0
    assert stats.skipped == 1 and stats.authentication_required == 1
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


def test_the_web_ui_share_url_maps_onto_the_dav_route():
    """CERNBox's web UI addresses the same public share as
    `/files/link/public/<token>[/<file inside it>]`, and links pasted out of a
    browser carry that form — 20 powerboard pictures in the owner's mirror do.
    Unrewritten it serves the single-page app, which the HTML guard refuses, so
    those bytes were never stored."""
    candidates = attachment_store._share_link_candidates
    host = "https://cernbox.cern.ch"

    # A folder share plus the file's own path inside it: the path is carried
    # over to the DAV route first, because that is the route that serves plain
    # bytes wherever it works. It does not work here — measured live, a folder
    # share answers `501 Not Implemented`, which no credential changes — so the
    # archive route follows it, naming the entry. A *bare*
    # `/s/<token>/download` is deliberately absent: on a folder share it
    # answers with the whole share, and storing part of that under one
    # attachment's code is the failure a missing file is preferable to.
    assert candidates(f"{host}/files/link/public/tok/20USED20000062") == [
        f"{host}/remote.php/dav/public-files/tok/20USED20000062",
        f"{host}/s/tok/download?files=20USED20000062",
        f"{host}/files/link/public/tok/20USED20000062",
    ]
    # A nested entry keeps its whole path in the query, url-encoded once.
    assert candidates(f"{host}/files/link/public/tok/2026/vis/front%20left.jpg")[1] == (
        f"{host}/s/tok/download?files=2026%2Fvis%2Ffront+left.jpg"
    )
    # A bare token addresses a single shared file, so the older routes remain.
    assert candidates(f"{host}/files/link/public/tok") == [
        f"{host}/remote.php/dav/public-files/tok",
        f"{host}/s/tok/download",
        f"{host}/files/link/public/tok",
    ]
    # Nested paths survive whole.
    assert candidates(f"{host}/files/link/public/tok/2026/vis/front.jpg")[0] == (
        f"{host}/remote.php/dav/public-files/tok/2026/vis/front.jpg"
    )


def test_a_web_ui_share_link_is_downloaded_from_the_dav_route(
    session, settings, evidence, monkeypatch
):
    served: list[str] = []

    def _open(url, timeout):
        served.append(url)
        if "/remote.php/dav/public-files/" in url:
            return _PublicResponse(url, JPEG)
        return _PublicResponse(url, HTML_ERROR_PAGE, "text/html")

    _set_attachment_descriptor(
        session,
        evidence,
        {
            "code": "d" * 64,
            "filename": "20USED20000062",
            "type": "share_link",
            "source": "share_link",
            "url": "https://cernbox.cern.ch/files/link/public/tok/20USED20000062",
        },
    )
    monkeypatch.setattr(attachment_store, "_open_public_url", _open)

    stats = download_attachments(
        session, _FakeGateway(configured=False), settings, "20USEM20000041"
    )
    session.commit()

    assert stats.downloaded == 1
    assert served == [
        "https://cernbox.cern.ch/remote.php/dav/public-files/tok/20USED20000062"
    ]
    row = session.scalar(select(TestRunAttachment))
    assert resolve_path(settings, row).read_bytes() == JPEG


def test_a_web_ui_share_link_serving_only_html_is_still_refused(
    session, settings, evidence, monkeypatch
):
    """The new route must not weaken the guard that made these misses visible:
    an expired or sign-in-walled share answers 200 with the viewer page, and a
    stored viewer page is a broken image that looks mirrored."""
    _set_attachment_descriptor(
        session,
        evidence,
        {
            "code": "e" * 63 + "1",
            "type": "share_link",
            "source": "share_link",
            "url": "https://cernbox.cern.ch/files/link/public/tok/photo.jpg",
        },
    )
    monkeypatch.setattr(
        attachment_store,
        "_open_public_url",
        lambda url, timeout: _PublicResponse(url, HTML_ERROR_PAGE, "text/html"),
    )

    stats = download_attachments(
        session, _FakeGateway(configured=False), settings, "20USEM20000041"
    )
    session.commit()

    assert stats.failed == 0
    assert stats.skipped == 1
    assert stats.authentication_required == 1
    assert resolve_path(settings, session.scalar(select(TestRunAttachment))) is None


def test_a_private_web_ui_location_is_refused_without_any_request(
    session, settings, evidence, monkeypatch
):
    """One row in the owner's mirror points at somebody's personal CERNBox
    space rather than at a share. It is unfetchable by design — itkFlow holds
    no credentials for it — so it must cost nothing, this sweep and every
    later one, instead of collecting the same login page forever."""

    def _must_not_open(url, timeout):
        raise AssertionError("a private web-UI location must not be requested")

    monkeypatch.setattr(attachment_store, "_open_public_url", _must_not_open)
    for index, url in enumerate(
        (
            "https://cernbox.cern.ch/files/spaces/eos/user/a/aabel/Sensors?view-mode=tiles",
            "https://syncandshare.example.org/index.php/apps/files/?dir=/Inspection",
        ),
        start=1,
    ):
        _set_attachment_descriptor(
            session,
            evidence,
            {
                "code": f"{index}" * 64,
                "type": "share_link",
                "source": "share_link",
                "url": url,
            },
        )

        stats = download_attachments(
            session, _FakeGateway(configured=False), settings, "20USEM20000041"
        )
        session.commit()

        assert stats.failed == 0, url
        assert stats.skipped == 1, url
        assert stats.authentication_required == 1, url
        assert attachment_store._share_link_candidates(url) == [], url


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

    client = _FakeClient()
    gateway = _FakeGateway(client)
    stats = download_attachments(session, gateway, settings, "20USEM20000043")
    session.commit()

    assert stats.downloaded == 1 and stats.reused == 1 and stats.failed == 0
    row = session.scalar(select(TestRunAttachment))
    assert resolve_path(settings, row) is not None

    forced = download_attachments(
        session, gateway, settings, "20USEM20000043", force=True
    )
    session.commit()

    assert forced.downloaded == 1 and forced.reused == 1 and forced.failed == 0
    assert client.calls == 2, "each sweep must fetch a physical blob only once"
    assert resolve_path(settings, row).read_bytes() == JPEG


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


def test_overlapping_component_syncs_fetch_and_store_one_shared_blob(
    tmp_path, monkeypatch
):
    """Direct/background overlap is serialized by physical attachment key.

    Two calls even target the same component. A third component proves that
    serialization retains every association instead of duplicating the bytes
    under each serial number. Cross-process staging isolation has its own test
    below because separate processes do not share this in-memory lock.
    """
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'parallel-attachments.db'}",
        attachment_dir=str(tmp_path / "attachments"),
        _env_file=None,
    )
    engine = make_engine(settings.database_url)
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    primary_sn = "20USEP00000001"
    component_sns = [primary_sn, primary_sn, "20USEP00000002"]
    descriptor_by_component = {
        component_sn: {
            "component_sn": component_sn,
            "test_type": "VISUAL_INSPECTION",
            "test_run_ref": f"RUN-{component_sn}",
            "code": "parallel-shared-code",
            "filename": "picture.jpg",
            "content_type": "image/jpeg",
            "title": "Inspection picture",
            "type": "share_link",
            "url": "https://example.invalid/s/public",
            "source": "share_link",
        }
        for component_sn in set(component_sns)
    }
    with factory() as session:
        descriptor = descriptor_by_component[primary_sn]
        session.add(
            TestRunEvidence(
                component_sn=primary_sn,
                test_type=descriptor["test_type"],
                passed=True,
                source="pdb",
                external_ref=descriptor["test_run_ref"],
                payload={
                    "attachments": [
                        {
                            key: value
                            for key, value in descriptor.items()
                            if key not in {"component_sn", "test_type", "test_run_ref"}
                        }
                    ]
                },
            )
        )
        session.commit()

    first_fetch_started = Event()
    contenders_ready = Barrier(3)
    savepoint_ended = Event()
    commit_flush_ended = Event()
    allow_root_commit = Event()
    duplicate_fetch_started = Event()
    fetch_guard = Lock()
    fetches: list[str] = []

    def fetch_once(client, descriptor, *, timeout, max_bytes):  # noqa: ARG001
        with fetch_guard:
            fetches.append(descriptor["code"])
            first = len(fetches) == 1
        if first:
            first_fetch_started.set()
            contenders_ready.wait(timeout=5)
        else:
            duplicate_fetch_started.set()
        return JPEG, "image/jpeg"

    monkeypatch.setattr(attachment_store, "_fetch_bytes", fetch_once)

    class _NoPdbGateway:
        is_configured = False

    def mirror(component_sn: str, *, planned: bool):
        if planned:
            first_fetch_started.wait(timeout=5)
            contenders_ready.wait(timeout=5)
        with factory() as session:
            stats = download_attachments(
                session,
                _NoPdbGateway(),
                settings,
                component_sn,
                descriptors=[descriptor_by_component[component_sn]] if planned else None,
            )
            if planned:
                session.commit()
                return stats

            # Ending a SAVEPOINT and the internal transaction used by the
            # commit autoflush both emit `after_transaction_end`. Neither may
            # release the physical-key lock before the root transaction ends.
            with session.begin_nested():
                pass
            savepoint_ended.set()
            blob = session.scalar(select(TestRunAttachment))
            blob.title = "Dirty again so root commit must autoflush"
            root_transaction = session.get_transaction()

            def pause_after_commit_flush(
                active_session, transaction  # noqa: ARG001
            ):
                if transaction.parent is root_transaction and not transaction.nested:
                    commit_flush_ended.set()
                    allow_root_commit.wait(timeout=5)

            event.listen(session, "after_transaction_end", pause_after_commit_flush)
            try:
                session.commit()
            finally:
                event.remove(session, "after_transaction_end", pause_after_commit_flush)
            return stats

    with ThreadPoolExecutor(max_workers=len(component_sns)) as executor:
        direct = executor.submit(mirror, primary_sn, planned=False)
        background_same_component = executor.submit(mirror, primary_sn, planned=True)
        background_other_component = executor.submit(
            mirror, component_sns[-1], planned=True
        )
        try:
            assert savepoint_ended.wait(timeout=5)
            assert commit_flush_ended.wait(timeout=5)
            # Both waiters are already trying the same key. If either the
            # SAVEPOINT or commit-flush child event released it, one enters the
            # fetch before the deliberately paused root COMMIT can finish.
            assert not duplicate_fetch_started.wait(timeout=1)
            assert not background_same_component.done()
            assert not background_other_component.done()
        finally:
            allow_root_commit.set()
        stats = [
            direct.result(timeout=10),
            background_same_component.result(timeout=10),
            background_other_component.result(timeout=10),
        ]

    assert sum(item.downloaded for item in stats) == 1
    assert sum(item.reused for item in stats) == 2
    assert fetches == ["parallel-shared-code"]
    with factory() as session:
        assert len(list(session.scalars(select(TestRunAttachment)))) == 1
        references = list(session.scalars(select(TestRunAttachmentReference)))
        assert {reference.component_sn for reference in references} == set(component_sns)
        assert len(references) == 2
        for component_sn in set(component_sns):
            assert [
                row.pdb_code
                for row in attachment_store.known_attachments(session, component_sn)
            ] == ["parallel-shared-code"]

    root = attachment_store.attachment_root(settings)
    stored_files = [
        path for path in root.rglob("*") if path.is_file() and not path.name.endswith(".part")
    ]
    assert len(stored_files) == 1
    assert stored_files[0].read_bytes() == JPEG
    assert list(root.rglob("*.part")) == []


def test_separate_workers_stage_same_blob_without_cross_owner_cleanup(
    tmp_path, monkeypatch
):
    """A stale process must only discard the staging file that it owns.

    Separate packaged processes have separate in-memory key-lock registries,
    so bypass that registry here while two workers fetch the same physical
    blob. Both reach their lease fence with independently intact bytes. The
    stale worker then loses its fence and runs the ordinary exception cleanup;
    the active worker's staging file must survive and publish atomically.
    """
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'process-fence.db'}",
        attachment_dir=str(tmp_path / "attachments"),
        _env_file=None,
    )
    engine = make_engine(settings.database_url)
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    component_sn = "20USEP00000003"
    stale_bytes = JPEG + b"-stale-worker"
    active_bytes = JPEG + b"-active-worker"
    fetch_barrier = Barrier(2)
    stale_at_fence = Event()
    active_at_fence = Event()
    allow_stale_fence_loss = Event()
    allow_active_commit = Event()

    def fetch_for_owner(client, descriptor, *, timeout, max_bytes):  # noqa: ARG001
        fetch_barrier.wait(timeout=5)
        return descriptor["payload"], "image/jpeg"

    # This is what makes the two calls model different OS processes: their
    # Python lock registries cannot coordinate, even though their disk and DB
    # are shared.
    monkeypatch.setattr(attachment_store, "_acquire_attachment_key_locks", lambda *args: [])
    monkeypatch.setattr(attachment_store, "_fetch_bytes", fetch_for_owner)

    class _NoPdbGateway:
        is_configured = False

    def mirror(owner: str):
        payload = stale_bytes if owner == "stale" else active_bytes
        descriptor = {
            "component_sn": component_sn,
            "test_type": "VISUAL_INSPECTION",
            "test_run_ref": f"RUN-{owner}",
            "code": "cross-process-shared-code",
            "filename": "picture.jpg",
            "content_type": "image/jpeg",
            "title": owner,
            "type": "share_link",
            "url": "https://example.invalid/s/public",
            "source": "share_link",
            "payload": payload,
        }

        def fence(session):  # noqa: ARG001
            if owner == "stale":
                stale_at_fence.set()
                allow_stale_fence_loss.wait(timeout=5)
                raise RuntimeError("attachment lease fence lost")
            active_at_fence.set()
            allow_active_commit.wait(timeout=5)

        with factory() as session:
            stats = download_attachments(
                session,
                _NoPdbGateway(),
                settings,
                component_sn,
                descriptors=[descriptor],
                before_commit=fence,
            )
            session.commit()
            return stats

    with ThreadPoolExecutor(max_workers=2) as executor:
        stale = executor.submit(mirror, "stale")
        active = executor.submit(mirror, "active")
        try:
            assert stale_at_fence.wait(timeout=5)
            assert active_at_fence.wait(timeout=5)
            root = attachment_store.attachment_root(settings)
            staged = list(root.rglob("*.part"))
            assert len(staged) == 2
            assert {path.read_bytes() for path in staged} == {stale_bytes, active_bytes}

            allow_stale_fence_loss.set()
            with pytest.raises(RuntimeError, match="lease fence lost"):
                stale.result(timeout=5)

            remaining = list(root.rglob("*.part"))
            assert len(remaining) == 1
            assert remaining[0].read_bytes() == active_bytes

            allow_active_commit.set()
            stats = active.result(timeout=5)
        finally:
            allow_stale_fence_loss.set()
            allow_active_commit.set()

    assert stats.downloaded == 1
    final_files = [path for path in root.rglob("*") if path.is_file()]
    assert len(final_files) == 1
    assert final_files[0].name == "cross-process-shared-code.jpg"
    assert final_files[0].read_bytes() == active_bytes


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


def test_a_stale_legacy_part_file_is_ignored_without_cross_owner_cleanup(
    session, settings, evidence
):
    """A previous process's unknown `.part` owner is never overwritten or
    deleted; it is harmless and can be reaped by a separate age-based policy."""
    root = attachment_store.attachment_root(settings)
    stale = root / "20USEM20000041" / "pdb" / "abc123.jpg.part"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_bytes(b"leftover-from-a-crashed-process")

    stats = download_attachments(session, _FakeGateway(), settings, "20USEM20000041")
    session.commit()

    assert stats.downloaded == 1
    row = session.scalar(select(TestRunAttachment))
    assert resolve_path(settings, row).read_bytes() == JPEG
    assert list(root.rglob("*.part")) == [stale]
    assert stale.read_bytes() == b"leftover-from-a-crashed-process"


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
    assert breaker.sweep_is_doomed is False
    breaker.record_failure(transient=True)
    assert breaker.sweep_is_doomed is True


def test_permanent_failures_and_successes_reset_the_breaker():
    breaker = attachment_store.OutageCircuitBreaker(threshold=2)
    breaker.record_failure(transient=True)
    breaker.record_failure(transient=False)  # a 404/HTML page is a real answer
    breaker.record_failure(transient=True)
    breaker.record_success()
    breaker.record_failure(transient=True)
    assert breaker.sweep_is_doomed is False


def test_reused_file_does_not_reset_transient_failure_streak(
    session, settings, no_sleep
):
    def descriptor(code: str) -> dict:
        return {
            "component_sn": "20USEM20000051",
            "test_type": "VISUAL_INSPECTION",
            "test_run_ref": "RUN-10",
            "code": code,
            "filename": f"{code}.jpg",
            "content_type": "image/jpeg",
            "title": None,
            "type": "file",
            "url": None,
            "source": "pdb",
        }

    reused = descriptor("already-mirrored")
    first = download_attachments(
        session,
        _FakeGateway(),
        settings,
        "20USEM20000051",
        descriptors=[reused],
    )
    session.commit()
    assert first.downloaded == 1

    breaker = attachment_store.OutageCircuitBreaker(threshold=2)
    outage = _FlakyClient(failures=999)
    stats = download_attachments(
        session,
        _FakeGateway(outage),
        settings,
        "20USEM20000051",
        descriptors=[descriptor("missing-1"), reused, descriptor("missing-2")],
        breaker=breaker,
    )
    session.commit()

    assert stats.failed == 2 and stats.reused == 1
    assert breaker.sweep_is_doomed is True


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


def _add_share_link_attachment(session, code: str, url: str) -> None:
    """A URL-valued result, the shape zFlow-era visual inspections still use."""
    session.add(
        TestRunEvidence(
            component_sn="20USEM20000050",
            test_type="VISUAL_INSPECTION",
            passed=True,
            source="pdb",
            external_ref=f"RUN-share-{code}",
            payload={
                "attachments": [
                    {
                        "code": code,
                        "filename": "photo.jpg",
                        "content_type": None,
                        "title": "Shared attachment",
                        "type": "share_link",
                        "url": url,
                        "source": "share_link",
                    }
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

    assert breaker.sweep_is_doomed is True
    # Every file still gets an honest outcome — none is silently skipped, and
    # none is recorded as stored, so the next sweep retries them all.
    assert stats.failed == 4 and stats.total == 4
    # But only the two that tripped the route touched the network, each
    # exhausting its full ladder (3 attempts x 2 routes). The remaining two
    # failed immediately: that is the entire point, since burning a ladder per
    # file is what turned an unreachable host into an hours-long crawl.
    assert client.calls == 12


def test_permanent_file_failures_never_trip_the_breaker(session, settings, no_sleep):
    _add_many_attachments(session, 4)
    client = _FlakyClient(failures=999, make_error=lambda: _HttpStatusError(404))
    breaker = attachment_store.OutageCircuitBreaker(threshold=2)

    stats = download_attachments(
        session, _FakeGateway(client), settings, "20USEM20000050", breaker=breaker
    )
    session.commit()

    assert breaker.sweep_is_doomed is False
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

    # The PDB route is the one route whose loss abandons the whole sweep.
    assert breaker.sweep_is_doomed is True
    assert stats.failed == 4 and stats.total == 4


def test_one_dead_share_host_does_not_doom_a_sweep_the_pdb_is_serving(
    session, settings, no_sleep, monkeypatch
):
    """The failure the owner actually hit, in miniature.

    87 consecutive attachments pointed into a single CERNBox folder share that
    answers `501 Not Implemented`. With one global streak, five of them in a
    row failed the entire evidence sync — at the same file, every time — while
    the PDB was answering perfectly and every other attachment was fine.

    A dead share host must cost its own files and nothing more.
    """
    _add_many_attachments(session, 2)
    _add_share_link_attachment(session, "dead-1", "https://share.example.org/s/AAA")
    _add_share_link_attachment(session, "dead-2", "https://share.example.org/s/BBB")
    _add_share_link_attachment(session, "dead-3", "https://share.example.org/s/CCC")

    def _always_down(url, timeout):
        raise TimeoutError("connection timed out")

    monkeypatch.setattr(attachment_store, "_open_public_url", _always_down)

    client = _FlakyClient(failures=0)  # the PDB is healthy
    breaker = attachment_store.OutageCircuitBreaker(threshold=2)
    stats = download_attachments(
        session, _FakeGateway(client), settings, "20USEM20000050", breaker=breaker
    )
    session.commit()

    # The share host is contained...
    assert breaker.is_tripped("share.example.org") is True
    # ...but the sweep is not abandoned, so the PDB files still arrive.
    assert breaker.sweep_is_doomed is False
    assert stats.downloaded == 2
    assert stats.failed == 3


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


def test_a_501_is_a_permanent_answer_not_an_outage():
    """`501 Not Implemented` must never be retried, and never look like one.

    Measured against the owner's live mirror: CERNBox answers 501 to a DAV
    request against a *folder* share, and 87 consecutive attachments point
    into one such share. Classified with the rest of 5xx as transient, each
    burned its full retry ladder and the run of them tripped the outage
    breaker, so every evidence sync aborted at the same file. A 501 is the
    server stating it does not implement the request; no retry can change it.
    """
    assert attachment_store.is_transient_download_error(_HttpStatusError(501)) is False
    assert attachment_store.is_transient_download_error(_HttpStatusError(505)) is False
    # The genuinely retryable server failures are untouched.
    for status in (500, 502, 503, 504):
        assert attachment_store.is_transient_download_error(_HttpStatusError(status)) is True
    for status in (408, 425, 429):
        assert attachment_store.is_transient_download_error(_HttpStatusError(status)) is True
    # And a 501 therefore cannot trip the breaker on its own.
    breaker = attachment_store.OutageCircuitBreaker(threshold=2)
    for _ in range(5):
        breaker.record_failure(transient=False)
    assert breaker.sweep_is_doomed is False


# --- folder shares answer with an archive ------------------------------------
#
# Measured live and anonymously against the owner's own share links on
# 2026-08-27. One CERNBox *folder* share backs 87 attachment descriptors on 76
# powerboards, collapsing to 20 rows, and none of them was fetchable:
#
#   /files/link/public/<token>/<entry>          200 text/html (the web app)
#   /remote.php/dav/public-files/<token>/<...>  501 Not Implemented
#   /s/<token>/download?files=<entry>           200, a POSIX **ustar** archive
#   /s/<token>/download?path=/&files=<entry>    500 Internal Server Error
#
# The archive really does hold the entry and its contents:
#
#   20USED50000029/                                        directory
#   20USED50000029/20USED50000029_2.JPG                     8 845 759 bytes
#   20USED50000029/20USED50000029_4.JPG                     6 951 643 bytes
#   20USED50000029/20USED50000029_2025_09_08_pics1-4.txt          104 bytes
#   20USED50000029/20USED50000029_1.CR2                    32 642 645 bytes
#   20USED50000029/20USED50000029_3.CR2                    30 617 214 bytes
#
# So the descriptor names a *folder*, several members could plausibly be "the
# picture", and the bytes come from a remote host. Every test below pins one
# rule that keeps that from turning into a wrong or a dangerous file on an
# operator's disk.

FOLDER_TOKEN = "4NM0Or4I05ztJUA"
FOLDER_ENTRY = "20USED50000029"
FOLDER_SHARE_URL = (
    f"https://cernbox.cern.ch/files/link/public/{FOLDER_TOKEN}/{FOLDER_ENTRY}"
)
FOLDER_DAV_URL = (
    f"https://cernbox.cern.ch/remote.php/dav/public-files/{FOLDER_TOKEN}/{FOLDER_ENTRY}"
)
FOLDER_ARCHIVE_URL = (
    f"https://cernbox.cern.ch/s/{FOLDER_TOKEN}/download?files={FOLDER_ENTRY}"
)

PNG = b"\x89PNG\r\n\x1a\n" + b"itkflow-test-png"


def _entry(name, payload=b"", *, kind=tarfile.REGTYPE, declared=None, link=""):
    """One archive member, ready to be assembled by hand.

    Built through `TarInfo.tobuf` rather than `TarFile.addfile` on purpose:
    `addfile` refuses to write a header that disagrees with the bytes it is
    given, and a header that lies about its member is precisely what has to
    be tested here.
    """
    info = tarfile.TarInfo(name)
    info.type = kind
    info.linkname = link
    info.size = len(payload) if declared is None else declared
    return info, payload


def _tar(entries, *, compress=False, tail=True, archive_format=tarfile.GNU_FORMAT) -> bytes:
    blob = b""
    for info, payload in entries:
        blob += info.tobuf(format=archive_format)
        if payload:
            blob += payload + b"\x00" * (-len(payload) % 512)
    if tail:
        blob += b"\x00" * 1024
    return gzip.compress(blob) if compress else blob


def _gzip_with_filename(payload: bytes, filename: str) -> bytes:
    """A gzip stream carrying the optional FNAME header field."""
    target = io.BytesIO()
    with gzip.GzipFile(filename=filename, mode="wb", fileobj=target, mtime=0) as stream:
        stream.write(payload)
    return target.getvalue()


def _folder_archive(*, compress=False, entry=FOLDER_ENTRY) -> bytes:
    """The shape the live share really returns, with tiny payloads."""
    return _tar(
        [
            _entry(f"{entry}/", kind=tarfile.DIRTYPE),
            _entry(f"{entry}/{entry}_2.JPG", JPEG),
            _entry(f"{entry}/{entry}_4.JPG", b"\xff\xd8\xff\xe0second-picture"),
            _entry(f"{entry}/{entry}_2025_09_08_pics1-4.txt", b"pictures 1-4\n"),
            _entry(f"{entry}/{entry}_1.CR2", b"raw-canon-bytes"),
            _entry(f"{entry}/{entry}_3.CR2", b"raw-canon-bytes-too"),
        ],
        compress=compress,
    )


def _share_opener(opens, *, archive: bytes | None = None, dav_status: int = 501):
    """Serve the routes exactly as the live host does."""

    def _open(url, timeout):
        opens.append(url)
        if "/remote.php/dav/public-files/" in url:
            raise HTTPError(url, dav_status, "Not Implemented", None, None)
        if "/download?files=" in url and archive is not None:
            return _PublicResponse(url, archive, "application/octet-stream")
        return _PublicResponse(url, HTML_ERROR_PAGE, "text/html")

    return _open


def _stage_folder_descriptor(session, evidence, code="ar" * 32, url=FOLDER_SHARE_URL):
    _set_attachment_descriptor(
        session,
        evidence,
        {
            "code": code,
            # As the mirror really records it: the folder name, no extension.
            "filename": FOLDER_ENTRY,
            "content_type": None,
            "title": "Link to Picture",
            "type": "share_link",
            "source": "share_link",
            "url": url,
        },
    )


def test_no_archive_member_is_ever_written_out_by_name():
    """The one line that would undo every guard below.

    `extractall` (and `extract`) write members to disk under their *own*
    names, which is the whole class of failure this section exists to prevent.
    Asserted against the parsed module rather than its text, so that the
    prose explaining the rule does not count as breaking it — and so that no
    spelling of the call slips through.
    """
    forbidden = {"extractall", "extract", "extractfile_to", "makefile"}
    called: set[str] = set()
    for node in ast.walk(ast.parse(inspect.getsource(attachment_store))):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            called.add(node.func.attr)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            called.add(node.func.id)
    assert called & forbidden == set()
    # Reading one member in memory is the only sanctioned way in.
    assert "extractfile" in called


def test_a_folder_share_archive_yields_the_entry_the_descriptor_named(
    session, settings, evidence, monkeypatch, no_sleep
):
    opens: list[str] = []
    monkeypatch.setattr(
        attachment_store,
        "_open_public_url",
        _share_opener(opens, archive=_folder_archive()),
    )
    _stage_folder_descriptor(session, evidence)

    stats = download_attachments(
        session, _FakeGateway(configured=False), settings, "20USEM20000041"
    )
    session.commit()

    assert stats.downloaded == 1 and stats.failed == 0
    # The plain-bytes route keeps priority; the archive route is what answers.
    assert opens == [FOLDER_DAV_URL, FOLDER_ARCHIVE_URL]
    # A 501 is a capability answer, so it must not cost a retry ladder either.
    assert no_sleep == []
    row = session.scalar(select(TestRunAttachment))
    assert resolve_path(settings, row).read_bytes() == JPEG
    # The descriptor's own name carries no extension; without a type taken
    # from the member the file would land extension-less with `is_image`
    # false, and the gallery would stay as empty as it was before the fix.
    assert row.content_type == "image/jpeg"
    assert row.is_image is True
    assert row.relative_path.endswith(".jpg")


def test_the_stored_archive_member_is_the_one_the_rule_names(
    session, settings, evidence, monkeypatch, no_sleep
):
    """Which of five plausible members is picked, and why it cannot drift.

    The live folder holds two JPEGs, two Canon raws and a note. An older TIFF
    is added here to prove that a browser-displayable image wins before the
    path tie-breaker. The choice stays a pure function of the archive's
    *content*, never of the order a host streams members in.
    """
    shuffled = _tar(
        [
            _entry(f"{FOLDER_ENTRY}/{FOLDER_ENTRY}_1.CR2", b"raw-canon-bytes"),
            _entry(f"{FOLDER_ENTRY}/{FOLDER_ENTRY}_0.TIFF", b"II*\x00tiff-image"),
            _entry(f"{FOLDER_ENTRY}/{FOLDER_ENTRY}_4.JPG", b"\xff\xd8\xff\xe0second"),
            _entry(f"{FOLDER_ENTRY}/", kind=tarfile.DIRTYPE),
            _entry(f"{FOLDER_ENTRY}/{FOLDER_ENTRY}_2025_09_08_pics1-4.txt", b"note\n"),
            _entry(f"{FOLDER_ENTRY}/{FOLDER_ENTRY}_2.JPG", JPEG),
        ]
    )
    monkeypatch.setattr(
        attachment_store, "_open_public_url", _share_opener([], archive=shuffled)
    )
    _stage_folder_descriptor(session, evidence)

    stats = download_attachments(
        session, _FakeGateway(configured=False), settings, "20USEM20000041"
    )
    session.commit()

    assert stats.downloaded == 1
    row = session.scalar(select(TestRunAttachment))
    # `_2.JPG`: not the lexicographically earlier TIFF, not the note or raw,
    # and not `_4.JPG` that arrived earlier in the stream.
    assert resolve_path(settings, row).read_bytes() == JPEG


def test_archive_image_ranking_uses_sniffed_bytes_not_remote_extensions():
    """A misleading suffix must not outrank the image a browser can paint."""
    real_tiff = b"II*\x00tiff-image"
    real_jpeg = b"\xff\xd8\xff\xe0jpeg-image"
    archive = _tar(
        [
            # Lexicographically first and named like a JPEG, but the bytes are
            # TIFF. The later member has the inverse mismatch and must win.
            _entry(f"{FOLDER_ENTRY}/a.jpg", real_tiff),
            _entry(f"{FOLDER_ENTRY}/b.tiff", real_jpeg),
        ]
    )
    stream = attachment_store._CappedStream(io.BytesIO(archive), len(archive) + 1)

    selected = attachment_store._archive_member(
        stream,
        mode="r|",
        wanted=FOLDER_ENTRY,
        max_bytes=4096,
        budget=len(archive) + 1,
    )

    assert selected == (f"{FOLDER_ENTRY}/b.tiff", real_jpeg)
    assert attachment_store._member_content_type(*selected) == "image/jpeg"


def test_the_exactly_named_entry_beats_every_other_member():
    """When the descriptor names a file rather than a folder, that file wins
    even against an image sitting next to it."""
    rank = attachment_store._member_rank
    assert rank("photo", "photo", None) < rank("shiny.png", "photo", "image/png")
    assert rank("shiny.png", "photo", "image/png") < rank(
        "older.tiff", "photo", "image/tiff"
    )
    assert rank("older.tiff", "photo", "image/tiff") < rank(
        "readme.txt", "photo", None
    )
    assert rank("readme.txt", "photo", None) < rank("scan.cr2", "photo", None)
    # Without a named entry there is no exact match to prefer.
    assert rank("photo", "", None) == rank("photo.cr2", "", None)


@pytest.mark.parametrize("exact_first", [False, True])
def test_the_exact_wanted_path_wins_in_the_stream_too(exact_first):
    exact = _entry("folder/photo", b"exact-file")
    descendant = _entry("folder/photo/shiny.jpg", JPEG)
    archive = _tar([exact, descendant] if exact_first else [descendant, exact])
    stream = attachment_store._CappedStream(io.BytesIO(archive), len(archive) + 1)

    assert attachment_store._archive_member(
        stream,
        mode="r|",
        wanted="folder/photo",
        max_bytes=4096,
        budget=len(archive) + 1,
    ) == ("folder/photo", b"exact-file")


def test_a_duplicate_normalised_member_path_is_first_wins():
    """Tar permits byte-distinct duplicates; their first occurrence is final."""
    first = b"II*\x00first-is-tiff"
    later_but_higher_rank = b"\xff\xd8\xff\xe0second-is-jpeg"
    path = f"{FOLDER_ENTRY}/same-picture"
    archive = _tar([_entry(path, first), _entry(path, later_but_higher_rank)])
    stream = attachment_store._CappedStream(io.BytesIO(archive), len(archive) + 1)

    assert attachment_store._archive_member(
        stream,
        mode="r|",
        wanted=FOLDER_ENTRY,
        max_bytes=4096,
        budget=len(archive) + 1,
    ) == (path, first)


def test_a_member_escaping_its_directory_is_refused():
    """`..` in any position, in any of the shapes a tar can carry it."""
    for hostile in (
        "../escape.jpg",
        "a/../../escape.jpg",
        f"{FOLDER_ENTRY}/../../escape.jpg",
        "..",
        "./../escape.jpg",
    ):
        info, _ = _entry(hostile, JPEG)
        assert attachment_store.safe_archive_member_name(info) is None, hostile


def test_an_absolute_or_windows_member_path_is_refused():
    for hostile in (
        "/etc/passwd",
        "/tmp/x.jpg",
        "C:\\Windows\\win.ini",
        "dir\\file.jpg",
        "C:/Windows/win.ini",
        "file.jpg:stream",
    ):
        info, _ = _entry(hostile, JPEG)
        assert attachment_store.safe_archive_member_name(info) is None, hostile


def test_a_control_character_in_a_member_name_is_refused():
    for hostile in ("photo\nINFO fake log line.jpg", "photo\x00.jpg", "photo\x7f.jpg"):
        info, _ = _entry(hostile, JPEG)
        assert attachment_store.safe_archive_member_name(info) is None, repr(hostile)


def test_only_regular_files_are_ever_eligible():
    """Symlinks, hardlinks, devices, fifos, directories and every sparse form.

    A symlink is the classic one: written out, it would point the stored name
    at a file elsewhere on the operator's disk. It is refused on *type*,
    before its name or its target is considered at all.
    """
    for kind in (
        tarfile.SYMTYPE,
        tarfile.LNKTYPE,
        tarfile.CHRTYPE,
        tarfile.BLKTYPE,
        tarfile.FIFOTYPE,
        tarfile.DIRTYPE,
        tarfile.GNUTYPE_SPARSE,
    ):
        info, _ = _entry("harmless.jpg", kind=kind, link="/etc/passwd")
        assert attachment_store.safe_archive_member_name(info) is None, kind
    ordinary, _ = _entry("harmless.jpg", JPEG)
    assert attachment_store.safe_archive_member_name(ordinary) == "harmless.jpg"

    # PAX sparse metadata is represented by tarfile as a regular type with a
    # sparse map; a type-only guard therefore misses it.
    pax_sparse = tarfile.TarInfo("looks-regular.jpg")
    pax_sparse.type = tarfile.REGTYPE
    pax_sparse.size = len(JPEG)
    pax_sparse.sparse = [(0, len(JPEG))]
    assert pax_sparse.isreg() and pax_sparse.issparse()
    assert attachment_store.safe_archive_member_name(pax_sparse) is None


def test_a_parsed_pax_sparse_member_is_never_selected():
    """Exercise the real tar parser path, not only a constructed TarInfo."""
    payload = b"abc"
    info = tarfile.TarInfo(f"{FOLDER_ENTRY}/looks-regular.jpg")
    info.type = tarfile.REGTYPE
    info.size = len(payload)
    info.pax_headers = {"GNU.sparse.map": "0,3", "GNU.sparse.size": "3"}
    archive = (
        info.tobuf(format=tarfile.PAX_FORMAT)
        + payload
        + b"\x00" * (-len(payload) % 512)
        + b"\x00" * 1024
    )
    stream = attachment_store._CappedStream(io.BytesIO(archive), len(archive) + 1)

    assert (
        attachment_store._archive_member(
            stream,
            mode="r|",
            wanted=FOLDER_ENTRY,
            max_bytes=4096,
            budget=len(archive) + 1,
        )
        is None
    )


def test_a_symlink_member_is_not_stored_even_when_it_is_the_named_entry(
    session, settings, evidence, monkeypatch, no_sleep
):
    archive = _tar(
        [
            _entry(FOLDER_ENTRY, kind=tarfile.SYMTYPE, link="/etc/passwd"),
            _entry("../escape.jpg", JPEG),
            _entry("/etc/passwd", b"root:x:0:0"),
        ]
    )
    monkeypatch.setattr(
        attachment_store, "_open_public_url", _share_opener([], archive=archive)
    )
    _stage_folder_descriptor(session, evidence)

    stats = download_attachments(
        session, _FakeGateway(configured=False), settings, "20USEM20000041"
    )
    session.commit()

    assert stats.failed == 1 and stats.downloaded == 0
    assert resolve_path(settings, session.scalar(select(TestRunAttachment))) is None


def test_a_member_outside_the_requested_entry_is_never_stored(
    session, settings, evidence, monkeypatch, no_sleep
):
    """The measured whole-share answer, which must select nothing.

    `/s/<token>/download?path=/<entry>` really does answer with the entire
    share rooted at the token instead of with the entry. Every member in it is
    a perfectly ordinary regular file with a perfectly ordinary name - and
    none of them is the file this attachment code stands for.
    """
    archive = _tar(
        [
            _entry(f"{FOLDER_TOKEN}/20USED20000062/20USED20000062_10.JPG", JPEG),
            _entry(f"{FOLDER_TOKEN}/20USED50000038/20USED50000038_1.JPG", PNG),
        ]
    )
    monkeypatch.setattr(
        attachment_store, "_open_public_url", _share_opener([], archive=archive)
    )
    _stage_folder_descriptor(session, evidence)

    stats = download_attachments(
        session, _FakeGateway(configured=False), settings, "20USEM20000041"
    )
    session.commit()

    assert stats.failed == 1 and stats.downloaded == 0
    assert resolve_path(settings, session.scalar(select(TestRunAttachment))) is None


def test_an_unnamed_entry_needs_an_archive_with_exactly_one_candidate(
    session, settings, evidence, monkeypatch, no_sleep
):
    """A share URL with no path inside it says nothing about which member is
    meant, so only a single-candidate archive is unambiguous."""
    bare = f"https://cernbox.cern.ch/s/{FOLDER_TOKEN}"

    def _serve(archive):
        def _open(url, timeout):
            if url.endswith("/download"):
                return _PublicResponse(url, archive, "application/octet-stream")
            raise HTTPError(url, 501, "Not Implemented", None, None)

        return _open

    monkeypatch.setattr(
        attachment_store,
        "_open_public_url",
        _serve(_tar([_entry("a/one.jpg", JPEG), _entry("a/two.jpg", PNG)])),
    )
    _stage_folder_descriptor(session, evidence, code="c1" * 32, url=bare)
    ambiguous = download_attachments(
        session, _FakeGateway(configured=False), settings, "20USEM20000041"
    )
    session.commit()
    assert ambiguous.failed == 1 and ambiguous.downloaded == 0

    monkeypatch.setattr(
        attachment_store, "_open_public_url", _serve(_tar([_entry("a/one.jpg", JPEG)]))
    )
    _stage_folder_descriptor(session, evidence, code="c2" * 32, url=bare)
    stats = download_attachments(
        session, _FakeGateway(configured=False), settings, "20USEM20000041"
    )
    session.commit()
    assert stats.downloaded == 1
    row = session.scalar(
        select(TestRunAttachment).where(TestRunAttachment.pdb_code == "c2" * 32)
    )
    assert resolve_path(settings, row).read_bytes() == JPEG


def test_the_declared_size_decides_whether_a_member_is_read_at_all():
    """A member whose header is already over the limit is never read.

    A remote host can put any number in a tar header. Reading first and
    measuring afterwards is how a sweep ends up holding bytes it knew from the
    header it would refuse — and the header is the cheapest possible place to
    say no.
    """
    oversized = _tar([_entry(f"{FOLDER_ENTRY}/big.jpg", b"\xff\xd8\xff" + b"x" * 8189)])
    stream = attachment_store._CappedStream(
        _PublicResponse("https://share.example.org/x", oversized, "application/octet-stream"),
        1024**2,
    )
    assert (
        attachment_store._archive_member(
            stream, mode="r|", wanted=FOLDER_ENTRY, max_bytes=4096, budget=1024**2
        )
        is None
    )


def test_a_member_declaring_a_huge_size_never_reaches_memory(
    session, settings, evidence, monkeypatch, no_sleep
):
    served: list[int] = []

    class _CountingResponse(_PublicResponse):
        def read(self, limit=-1):
            chunk = super().read(limit)
            served.append(len(chunk))
            return chunk

    archive = _tar(
        [_entry(f"{FOLDER_ENTRY}/{FOLDER_ENTRY}_2.JPG", JPEG, declared=10 * 1024**3)]
    )

    def _open(url, timeout):
        if "/download?files=" in url:
            return _CountingResponse(url, archive, "application/octet-stream")
        raise HTTPError(url, 501, "Not Implemented", None, None)

    monkeypatch.setattr(attachment_store, "_open_public_url", _open)
    _stage_folder_descriptor(session, evidence)

    stats = download_attachments(
        session, _FakeGateway(configured=False), settings, "20USEM20000041"
    )
    session.commit()

    assert stats.failed == 1 and stats.downloaded == 0
    assert sum(served) < 64 * 1024


def test_a_member_over_the_attachment_limit_loses_to_a_smaller_sibling(
    session, settings, evidence, monkeypatch, no_sleep
):
    settings.attachment_max_bytes = 4096
    archive = _tar(
        [
            # Ranks first by path, but no single attachment may be this big.
            _entry(f"{FOLDER_ENTRY}/{FOLDER_ENTRY}_1.JPG", b"\xff\xd8\xff" + b"x" * 8192),
            _entry(f"{FOLDER_ENTRY}/{FOLDER_ENTRY}_2.JPG", JPEG),
        ]
    )
    monkeypatch.setattr(
        attachment_store, "_open_public_url", _share_opener([], archive=archive)
    )
    _stage_folder_descriptor(session, evidence)

    stats = download_attachments(
        session, _FakeGateway(configured=False), settings, "20USEM20000041"
    )
    session.commit()

    assert stats.downloaded == 1
    row = session.scalar(select(TestRunAttachment))
    assert resolve_path(settings, row).read_bytes() == JPEG


def test_a_truncated_or_lying_archive_is_refused_as_a_verdict_not_an_error():
    """A header that promises more than the archive contains.

    Measured behaviour of the streaming reader: it raises rather than handing
    back a short member. That has to become an explicit refusal — logged, and
    unambiguously final — instead of an anonymous exception that the network
    error classifier then has to guess about.
    """
    truncated = _tar(
        [_entry(f"{FOLDER_ENTRY}/a.JPG", JPEG, declared=len(JPEG) + 4096)], tail=False
    )
    stream = attachment_store._CappedStream(
        _PublicResponse("https://share.example.org/x", truncated, "application/octet-stream"),
        1024**2,
    )
    with pytest.raises(attachment_store._ArchiveRefused):
        attachment_store._archive_member(
            stream, mode="r|", wanted=FOLDER_ENTRY, max_bytes=1024**2, budget=1024**2
        )


def test_a_short_member_is_refused_even_by_a_reader_that_tolerates_it():
    """Declared and delivered must agree, whoever is doing the reading.

    Python's streaming tar reader raises on a short member, so on this path
    the check is defence in depth — but it is the line that decides what
    happens if a reader ever hands back less than the header promised, and a
    half-delivered picture stored under a right code is a lie that never gets
    corrected. Driven directly, because the stdlib reader cannot produce the
    situation.
    """
    info, _ = _entry(f"{FOLDER_ENTRY}/a.JPG", JPEG, declared=len(JPEG) + 4096)

    class _TolerantReader:
        def __iter__(self):
            return iter([info])

        def extractfile(self, member):
            return io.BytesIO(JPEG)

    with pytest.raises(attachment_store._ArchiveRefused):
        attachment_store._walk_archive(
            _TolerantReader(), wanted=FOLDER_ENTRY, max_bytes=1024**2, budget=1024**2
        )


def test_a_lying_archive_stores_nothing(
    session, settings, evidence, monkeypatch, no_sleep
):
    archive = _tar(
        [_entry(f"{FOLDER_ENTRY}/{FOLDER_ENTRY}_2.JPG", JPEG, declared=len(JPEG) + 4096)],
        tail=False,
    )
    monkeypatch.setattr(
        attachment_store, "_open_public_url", _share_opener([], archive=archive)
    )
    _stage_folder_descriptor(session, evidence)

    stats = download_attachments(
        session, _FakeGateway(configured=False), settings, "20USEM20000041"
    )
    session.commit()

    assert stats.failed == 1 and stats.downloaded == 0
    assert resolve_path(settings, session.scalar(select(TestRunAttachment))) is None


def test_an_archive_with_thousands_of_members_is_refused():
    crowd = _tar(
        [
            _entry(f"{FOLDER_ENTRY}/{index:05d}.jpg", JPEG)
            for index in range(attachment_store.ARCHIVE_MEMBER_LIMIT + 8)
        ]
    )
    stream = attachment_store._CappedStream(
        _PublicResponse("https://share.example.org/x", crowd, "application/octet-stream"),
        len(crowd) * 2,
    )
    with pytest.raises(attachment_store._ArchiveRefused):
        attachment_store._archive_member(
            stream,
            mode="r|",
            wanted=FOLDER_ENTRY,
            max_bytes=1024 * 1024,
            budget=len(crowd) * 2,
        )


def test_the_declared_member_bytes_are_capped_as_well_as_the_stream():
    """An archive that *promises* far more than it ships.

    Neither byte cap can see this coming: a few hundred bytes arrive on the
    wire and a few hundred come out of the decompressor, and only the header
    says that sixty-four megabytes are supposed to follow. Summing the
    declared sizes is what turns that into a refusal at the very first header,
    before a single byte of payload is inflated or skipped.

    The refusal *reason* is asserted, not merely the refusal. Without this
    check the archive is still refused — the reader runs off the end of it —
    but only after the whole promised length has been chased, which is exactly
    the work the check exists to avoid.
    """
    bomb = _tar(
        [
            _entry(f"{FOLDER_ENTRY}/{index}.jpg", b"", declared=64 * 1024**2)
            for index in range(64)
        ],
        compress=True,
    )
    assert len(bomb) < 1024**2, "the bomb must be small on the wire to test the right cap"
    stream = attachment_store._CappedStream(
        _PublicResponse("https://share.example.org/x", bomb, "application/octet-stream"),
        4 * 1024**2,
    )
    with pytest.raises(attachment_store._ArchiveRefused, match="declare more bytes"):
        attachment_store._archive_member(
            stream,
            mode="r|gz",
            wanted=FOLDER_ENTRY,
            max_bytes=2 * 1024**2,
            budget=4 * 1024**2,
        )


@pytest.mark.parametrize("archive_format", [tarfile.GNU_FORMAT, tarfile.PAX_FORMAT])
def test_gzipped_extended_metadata_counts_towards_the_decompressed_budget(
    archive_format,
):
    """GNU longname/PAX data is consumed before tarfile yields a TarInfo.

    It therefore never reaches the declared-member-byte accounting below.
    Repetitive metadata compresses to almost nothing, so only a cap around the
    *decompressed* tar stream prevents it from becoming an unbounded allocation.
    """
    budget = 64 * 1024
    private_long_name = f"{FOLDER_ENTRY}/" + "private-person-name-" * 16_384 + ".jpg"
    bomb = _tar(
        [_entry(private_long_name, JPEG)],
        compress=True,
        archive_format=archive_format,
    )
    assert len(bomb) < budget, "metadata must be small on the wire to test decompression"
    stream = attachment_store._CappedStream(
        _PublicResponse("https://share.example.org/x", bomb, "application/octet-stream"),
        budget,
    )

    with pytest.raises(attachment_store._ArchiveRefused, match="decompressed archive"):
        attachment_store._archive_member(
            stream,
            mode="r|gz",
            wanted=FOLDER_ENTRY,
            max_bytes=budget,
            budget=budget,
        )


def test_an_endless_response_is_cut_off_at_the_archive_budget(
    session, settings, evidence, monkeypatch, no_sleep
):
    """A host that never stops sending must not be able to run a sweep out of
    time or memory.

    Deliberately an *endless well-formed* archive: every member is a valid,
    empty, in-scope regular file, so neither the member-count limit nor the
    declared-byte limit is what stops it. Only the cap on the bytes taken off
    the wire can.
    """
    settings.attachment_max_bytes = 64 * 1024
    budget = 64 * 1024 * attachment_store.ARCHIVE_SIZE_BUDGET_FACTOR
    sent: list[int] = []

    class _Endless:
        """Emits header after header. Stops at 4x the budget so that removing
        the cap fails the test instead of hanging it."""

        headers = _PublicHeaders("application/octet-stream")

        def __init__(self, url):
            self._url = url
            self._index = 0

        def read(self, limit=-1):
            if sum(sent) >= budget * 4:
                return b""
            size = 32 * 1024 if limit is None or limit < 0 else min(limit, 32 * 1024)
            chunk = b""
            while len(chunk) < size:
                header = tarfile.TarInfo(f"{FOLDER_ENTRY}/{self._index:08d}.dat")
                header.size = 0
                self._index += 1
                chunk += header.tobuf(format=tarfile.GNU_FORMAT)
            chunk = chunk[:size]
            sent.append(len(chunk))
            return chunk

        def geturl(self):
            return self._url

        def close(self):
            return None

    def _open(url, timeout):
        if "/download?files=" in url:
            return _Endless(url)
        raise HTTPError(url, 501, "Not Implemented", None, None)

    monkeypatch.setattr(attachment_store, "_open_public_url", _open)
    _stage_folder_descriptor(session, evidence)

    stats = download_attachments(
        session, _FakeGateway(configured=False), settings, "20USEM20000041"
    )
    session.commit()

    assert stats.failed == 1 and stats.downloaded == 0
    assert sum(sent) <= budget + 32 * 1024


def test_an_archive_whose_member_is_an_html_error_page_is_refused(
    session, settings, evidence, monkeypatch, no_sleep
):
    """An archive is a new transport, not a new trust level.

    The guard that made these misses visible in the first place - a sign-in
    page stored under an image's name renders as a broken tile forever - has
    to run on bytes that arrive inside an archive too.
    """
    archive = _tar([_entry(f"{FOLDER_ENTRY}/{FOLDER_ENTRY}_2.JPG", HTML_ERROR_PAGE)])
    monkeypatch.setattr(
        attachment_store, "_open_public_url", _share_opener([], archive=archive)
    )
    _stage_folder_descriptor(session, evidence)

    stats = download_attachments(
        session, _FakeGateway(configured=False), settings, "20USEM20000041"
    )
    session.commit()

    assert stats.failed == 1 and stats.downloaded == 0
    assert resolve_path(settings, session.scalar(select(TestRunAttachment))) is None


@pytest.mark.parametrize(
    "optional_filename_bytes",
    [0, 4096, attachment_store._GZIP_ARCHIVE_SNIFF_BYTES - 11],
)
def test_a_gzip_compressed_archive_is_unpacked_too(
    session, settings, evidence, monkeypatch, no_sleep, optional_filename_bytes
):
    plain_archive = _folder_archive()
    archive = (
        _gzip_with_filename(plain_archive, "x" * optional_filename_bytes)
        if optional_filename_bytes
        else gzip.compress(plain_archive)
    )
    if optional_filename_bytes:
        assert attachment_store._gzip_header_end(archive[:512]) is None
        probe = attachment_store._CappedStream(
            io.BytesIO(archive),
            len(archive) + 1,
        )
        assert attachment_store._sniff_archive_stream_mode(probe) == "r|gz"
        assert probe.consumed <= (
            attachment_store._GZIP_ARCHIVE_SNIFF_BYTES
            + attachment_store._GZIP_DEFLATE_SNIFF_BYTES
        )
        if optional_filename_bytes == attachment_store._GZIP_ARCHIVE_SNIFF_BYTES - 11:
            assert (
                attachment_store._gzip_header_end(
                    archive[: attachment_store._GZIP_ARCHIVE_SNIFF_BYTES]
                )
                == attachment_store._GZIP_ARCHIVE_SNIFF_BYTES
            )
    monkeypatch.setattr(
        attachment_store,
        "_open_public_url",
        _share_opener([], archive=archive),
    )
    _stage_folder_descriptor(session, evidence)

    stats = download_attachments(
        session, _FakeGateway(configured=False), settings, "20USEM20000041"
    )
    session.commit()

    assert stats.downloaded == 1
    row = session.scalar(select(TestRunAttachment))
    assert resolve_path(settings, row).read_bytes() == JPEG
    assert row.content_type == "image/jpeg"


def test_a_gzip_header_beyond_the_fixed_cap_is_refused():
    archive = _gzip_with_filename(
        _folder_archive(), "x" * attachment_store._GZIP_ARCHIVE_SNIFF_BYTES
    )
    stream = attachment_store._CappedStream(io.BytesIO(archive), len(archive) + 1)

    with pytest.raises(attachment_store._ArchiveRefused, match="gzip header"):
        attachment_store._sniff_archive_stream_mode(stream)
    assert stream.consumed == attachment_store._GZIP_ARCHIVE_SNIFF_BYTES


def test_a_gzip_deflate_probe_is_bounded_when_it_yields_no_output():
    # A valid sequence of non-final empty stored blocks can consume arbitrary
    # compressed input without producing one clear byte. It must not turn the
    # archive sniff into an unbounded search for the tar header.
    header = b"\x1f\x8b\x08\x00" + b"\x00" * 4 + b"\x00\xff"
    empty_deflate_block = b"\x00\x00\x00\xff\xff"
    blocks = (
        attachment_store._GZIP_DEFLATE_SNIFF_BYTES // len(empty_deflate_block)
    ) + 10
    wire_bytes = header + empty_deflate_block * blocks
    stream = attachment_store._CappedStream(io.BytesIO(wire_bytes), len(wire_bytes) + 1)

    with pytest.raises(attachment_store._ArchiveRefused, match="sniff budget"):
        attachment_store._sniff_archive_stream_mode(stream)
    assert stream.consumed == len(header) + attachment_store._GZIP_DEFLATE_SNIFF_BYTES


def test_an_ordinary_gzip_with_a_maximum_header_stays_byte_identical():
    wire_bytes = _gzip_with_filename(
        b"ordinary compressed file" * 100,
        "x" * (attachment_store._GZIP_ARCHIVE_SNIFF_BYTES - 11),
    )
    stream = attachment_store._CappedStream(io.BytesIO(wire_bytes), len(wire_bytes) + 1)

    assert attachment_store._sniff_archive_stream_mode(stream) is None
    assert stream.read(len(wire_bytes) + 1) == wire_bytes


def test_archive_success_log_never_contains_the_remote_member_name(
    session, settings, evidence, monkeypatch, no_sleep, caplog
):
    private_member = f"{FOLDER_ENTRY}/alice-private-inspection.JPG"
    monkeypatch.setattr(
        attachment_store,
        "_open_public_url",
        _share_opener([], archive=_tar([_entry(private_member, JPEG)])),
    )
    _stage_folder_descriptor(session, evidence)

    with caplog.at_level("INFO", logger="app.attachment_store"):
        stats = download_attachments(
            session, _FakeGateway(configured=False), settings, "20USEM20000041"
        )
    session.commit()

    assert stats.downloaded == 1
    assert "unpacked from an archive" in caplog.text
    assert private_member not in caplog.text
    assert "alice-private-inspection" not in caplog.text


def test_only_tar_and_gzipped_tar_count_as_archives():
    """bzip2 and xz are refused by omission, and a gzipped *file* is not an
    archive at all - it must stay on the ordinary download path rather than be
    swallowed by a tar reader that cannot open it."""
    mode = attachment_store._archive_stream_mode
    assert mode(_folder_archive()[:512]) == "r|"
    assert mode(_folder_archive(compress=True)[:512]) == "r|gz"
    assert mode(gzip.compress(JPEG * 200)[:512]) is None
    assert mode(JPEG + b"\x00" * 512) is None
    assert mode(b"PK\x03\x04" + b"\x00" * 512) is None
    assert mode(b"\xfd7zXZ\x00" + b"\x00" * 512) is None
    assert mode(b"BZh9" + b"\x00" * 512) is None


def test_a_plain_share_file_survives_the_archive_sniff_byte_for_byte(
    session, settings, evidence, monkeypatch, no_sleep
):
    """The share links that already work must keep working exactly.

    Sniffing reads the first bytes of every share response; if they were not
    handed back, every stored file would silently lose its first 512 bytes - a
    corruption that only shows on a payload longer than the sniff window.
    """
    picture = JPEG + bytes(range(256)) * 32
    assert len(picture) > 512
    monkeypatch.setattr(
        attachment_store,
        "_open_public_url",
        lambda url, timeout: _PublicResponse(url, picture, "image/jpeg"),
    )
    _stage_share_descriptor(session, evidence, "f0" * 32)

    stats = download_attachments(
        session, _FakeGateway(configured=False), settings, "20USEM20000041"
    )
    session.commit()

    assert stats.downloaded == 1
    row = session.scalar(select(TestRunAttachment))
    assert resolve_path(settings, row).read_bytes() == picture
    assert row.size_bytes == len(picture)


def test_the_stored_type_comes_from_the_bytes_before_the_member_name(
    session, settings, evidence, monkeypatch, no_sleep
):
    """The member name is part of what the remote host chose; the bytes are
    what gets stored. A `.txt` holding a PNG is stored as a PNG."""
    archive = _tar([_entry(f"{FOLDER_ENTRY}/readme.txt", PNG)])
    monkeypatch.setattr(
        attachment_store, "_open_public_url", _share_opener([], archive=archive)
    )
    _stage_folder_descriptor(session, evidence)

    stats = download_attachments(
        session, _FakeGateway(configured=False), settings, "20USEM20000041"
    )
    session.commit()

    assert stats.downloaded == 1
    row = session.scalar(select(TestRunAttachment))
    assert row.content_type == "image/png"
    assert row.relative_path.endswith(".png")


def test_an_unsniffable_member_falls_back_to_its_extension(
    session, settings, evidence, monkeypatch, no_sleep
):
    archive = _tar([_entry(f"{FOLDER_ENTRY}/notes.csv", b"sn,value\n20USED1,3\n")])
    monkeypatch.setattr(
        attachment_store, "_open_public_url", _share_opener([], archive=archive)
    )
    _stage_folder_descriptor(session, evidence)

    download_attachments(
        session, _FakeGateway(configured=False), settings, "20USEM20000041"
    )
    session.commit()

    row = session.scalar(select(TestRunAttachment))
    assert row.content_type == "text/csv"
    assert row.relative_path.endswith(".csv")


def test_the_two_extension_tables_cannot_drift_apart():
    """`_CONTENT_TYPE_BY_EXTENSION` is written out by hand so the ambiguous
    pairs resolve deliberately; this is what keeps it complete."""
    for extension in set(attachment_store._EXTENSION_BY_CONTENT_TYPE.values()):
        assert extension in attachment_store._CONTENT_TYPE_BY_EXTENSION, extension
    for content_type in attachment_store._CONTENT_TYPE_BY_EXTENSION.values():
        assert content_type in attachment_store._EXTENSION_BY_CONTENT_TYPE, content_type


def test_the_archive_budget_is_derived_from_the_configured_attachment_limit(
    session, settings, evidence, monkeypatch, no_sleep
):
    """One knob, not two: an operator who lowers the attachment limit also
    lowers what a share host is allowed to stream at them."""
    settings.attachment_max_bytes = 2048
    budget = 2048 * attachment_store.ARCHIVE_SIZE_BUDGET_FACTOR
    padding = b"\xff\xd8\xff" + b"p" * 1600
    oversized = _tar(
        [_entry(f"{FOLDER_ENTRY}/{index}.jpg", padding) for index in range(8)]
    )
    assert len(oversized) > budget
    monkeypatch.setattr(
        attachment_store, "_open_public_url", _share_opener([], archive=oversized)
    )
    _stage_folder_descriptor(session, evidence)

    stats = download_attachments(
        session, _FakeGateway(configured=False), settings, "20USEM20000041"
    )
    session.commit()

    assert stats.failed == 1 and stats.downloaded == 0


def _folder_descriptor(component_sn: str, code: str) -> dict:
    """One row of the shape the mirror really holds: many components, one code."""
    return {
        "component_sn": component_sn,
        "test_type": "PICTURE",
        "test_run_ref": f"RUN-{component_sn}",
        "code": code,
        "filename": FOLDER_ENTRY,
        "content_type": None,
        "title": "Link to Picture",
        "type": "share_link",
        "url": FOLDER_SHARE_URL,
        "source": "share_link",
    }


def test_one_folder_share_is_asked_once_per_sweep_not_once_per_component(
    session, settings, monkeypatch, no_sleep
):
    """The measured cost of the owner's mirror: 87 descriptors, 76 components,
    20 distinct attachment codes, one shared folder.

    A *stored* file needs no memo - the next component finds it on disk
    through the `(source, code)` key and reuses it. A permanently refused one
    has nothing on disk, so without a memo the same multi-megabyte archive is
    fetched and thrown away once per referring component; in the live mirror
    that is up to nine times for a single folder.
    """
    opens: list[str] = []
    # Nothing inside the entry the descriptor names, so the archive is refused.
    archive = _tar([_entry("some-other-folder/one.jpg", JPEG)])
    monkeypatch.setattr(
        attachment_store, "_open_public_url", _share_opener(opens, archive=archive)
    )

    breaker = attachment_store.OutageCircuitBreaker()
    for component_sn in ("20USEP00000001", "20USEP00000002", "20USEP00000003"):
        download_attachments(
            session,
            _FakeGateway(configured=False),
            settings,
            component_sn,
            descriptors=[_folder_descriptor(component_sn, "shared" * 4)],
            breaker=breaker,
        )
        session.commit()

    # Refused once, and asked for exactly once - not once per component.
    assert opens == [FOLDER_DAV_URL, FOLDER_ARCHIVE_URL, FOLDER_SHARE_URL]
    assert breaker.has_permanent_miss(("share_link", "shared" * 4)) is True
    # The memo is a remembered verdict, not a fresh outage observation.
    assert breaker.sweep_is_doomed is False


def test_a_shared_folder_that_works_is_fetched_once_and_then_reused(
    session, settings, monkeypatch, no_sleep
):
    """The reason no archive is ever cached in memory: the natural key does
    the work. 87 descriptors collapse to 20 `(source, code)` rows, and once
    one component has stored the file every other component reuses it."""
    opens: list[str] = []
    monkeypatch.setattr(
        attachment_store,
        "_open_public_url",
        _share_opener(opens, archive=_folder_archive()),
    )

    totals = []
    breaker = attachment_store.OutageCircuitBreaker()
    for component_sn in ("20USEP00000001", "20USEP00000002", "20USEP00000003"):
        totals.append(
            download_attachments(
                session,
                _FakeGateway(configured=False),
                settings,
                component_sn,
                descriptors=[_folder_descriptor(component_sn, "works" * 4)],
                breaker=breaker,
            )
        )
        session.commit()

    assert [stats.downloaded for stats in totals] == [1, 0, 0]
    assert [stats.reused for stats in totals] == [0, 1, 1]
    assert opens == [FOLDER_DAV_URL, FOLDER_ARCHIVE_URL]
    assert len(list(session.scalars(select(TestRunAttachment)))) == 1
    references = list(session.scalars(select(TestRunAttachmentReference)))
    assert {reference.component_sn for reference in references} == {
        "20USEP00000001",
        "20USEP00000002",
        "20USEP00000003",
    }
    assert len(references) == 3
    for component_sn in {reference.component_sn for reference in references}:
        assert [
            row.pdb_code for row in attachment_store.known_attachments(session, component_sn)
        ] == ["works" * 4]
    stored_files = [
        path for path in attachment_store.attachment_root(settings).rglob("*") if path.is_file()
    ]
    assert len(stored_files) == 1
    assert stored_files[0].read_bytes() == JPEG


def test_reference_resync_updates_metadata_but_separates_null_run_test_types(
    session, settings, monkeypatch, no_sleep
):
    """A missing run id does not make two test types the same association."""
    opens: list[str] = []
    monkeypatch.setattr(
        attachment_store,
        "_open_public_url",
        _share_opener(opens, archive=_folder_archive()),
    )
    component_sn = "20USEP00000001"
    code = "metadata" * 4
    first = {
        **_folder_descriptor(component_sn, code),
        "test_type": "VISUAL_INSPECTION",
        "test_run_ref": None,
        "title": "Original title",
    }
    second = {
        **first,
        "test_type": "METROLOGY",
        "title": "Other test",
    }
    updated = {
        **first,
        "filename": "operator-facing-name.jpg",
        "title": "Updated title",
    }
    with_run = {
        **first,
        "test_run_ref": "RUN-STABLE",
        "test_type": "OLD_TEST_TYPE",
        "title": "Before upstream correction",
    }
    corrected_run = {
        **with_run,
        "test_type": "CORRECTED_TEST_TYPE",
        "title": "After upstream correction",
    }

    outcomes = []
    for descriptor in (
        first,
        second,
        updated,
        updated,
        with_run,
        corrected_run,
        corrected_run,
    ):
        outcomes.append(
            download_attachments(
                session,
                _FakeGateway(configured=False),
                settings,
                component_sn,
                descriptors=[descriptor],
            )
        )
        session.commit()

    assert [outcome.downloaded for outcome in outcomes] == [1, 0, 0, 0, 0, 0, 0]
    assert [outcome.reused for outcome in outcomes] == [0, 1, 1, 1, 1, 1, 1]
    assert opens == [FOLDER_DAV_URL, FOLDER_ARCHIVE_URL]
    assert len(list(session.scalars(select(TestRunAttachment)))) == 1
    references = list(
        session.scalars(
            select(TestRunAttachmentReference).order_by(TestRunAttachmentReference.test_type)
        )
    )
    assert len(references) == 3
    assert [reference.test_type for reference in references] == [
        "CORRECTED_TEST_TYPE",
        "METROLOGY",
        "VISUAL_INSPECTION",
    ]
    assert {
        reference.test_run_ref
        for reference in references
        if reference.test_type in {"METROLOGY", "VISUAL_INSPECTION"}
    } == {""}
    corrected = next(
        reference for reference in references if reference.test_run_ref == "RUN-STABLE"
    )
    assert corrected.test_type == "CORRECTED_TEST_TYPE"
    assert corrected.title == "After upstream correction"
    visual = next(
        reference for reference in references if reference.test_type == "VISUAL_INSPECTION"
    )
    assert visual.filename == "operator-facing-name.jpg"
    assert visual.title == "Updated title"
    assert attachment_store.attachment_counts_by_run(session, [component_sn]) == {
        component_sn: {
            "CORRECTED_TEST_TYPE": {"RUN-STABLE": 1},
            "METROLOGY": {None: 1},
            "VISUAL_INSPECTION": {None: 1},
        }
    }


def test_a_transient_share_failure_is_never_memoised(session, settings, monkeypatch, no_sleep):
    """Only *final* answers may be remembered. A file that failed because the
    line dropped has to stay reachable for the next component in the sweep."""
    opens: list[str] = []

    def _down(url, timeout):
        opens.append(url)
        raise TimeoutError("connection timed out")

    monkeypatch.setattr(attachment_store, "_open_public_url", _down)

    breaker = attachment_store.OutageCircuitBreaker(threshold=99)
    for component_sn in ("20USEP00000001", "20USEP00000002"):
        download_attachments(
            session,
            _FakeGateway(configured=False),
            settings,
            component_sn,
            descriptors=[_folder_descriptor(component_sn, "flaky" * 4)],
            breaker=breaker,
        )
        session.commit()

    assert breaker.has_permanent_miss(("share_link", "flaky" * 4)) is False
    # Both components really tried, each burning its own retry ladder.
    assert len(opens) > 3


def test_the_permanent_miss_memo_is_bounded():
    """It lives as long as a sweep and a mirror holds tens of thousands of
    attachments, so it must not be able to grow without limit."""
    breaker = attachment_store.OutageCircuitBreaker()
    limit = attachment_store.OutageCircuitBreaker.PERMANENT_MISS_MEMO_LIMIT
    for index in range(limit + 100):
        breaker.note_permanent_miss(("pdb", f"code-{index}"))
    assert len(breaker._permanent_misses) == limit
    # The oldest verdicts are the ones dropped, and dropping one only means it
    # gets asked again - never that something wrong is served.
    assert breaker.has_permanent_miss(("pdb", "code-0")) is False
    assert breaker.has_permanent_miss(("pdb", f"code-{limit + 99}")) is True


def test_a_refused_archive_is_retried_by_the_next_sweep(
    session, settings, evidence, monkeypatch, no_sleep
):
    """No verdict is ever persisted. A refusal costs this sweep only, so that
    a later code change - or a repaired share - brings the file back into
    reach without anyone having to clear a flag. A durable "permanently
    failed" column was considered and rejected for exactly this reason: it
    would have frozen the 20 folder rows this change repairs.
    """
    monkeypatch.setattr(
        attachment_store,
        "_open_public_url",
        _share_opener([], archive=_tar([_entry("elsewhere/other.jpg", JPEG)])),
    )
    _stage_folder_descriptor(session, evidence)
    first = download_attachments(
        session, _FakeGateway(configured=False), settings, "20USEM20000041"
    )
    session.commit()
    assert first.failed == 1

    monkeypatch.setattr(
        attachment_store,
        "_open_public_url",
        _share_opener([], archive=_folder_archive()),
    )
    second = download_attachments(
        session, _FakeGateway(configured=False), settings, "20USEM20000041"
    )
    session.commit()

    assert second.downloaded == 1
    row = session.scalar(select(TestRunAttachment))
    assert resolve_path(settings, row).read_bytes() == JPEG


def test_the_share_member_path_is_decoded_before_it_is_matched():
    """Member names in a tar are plain text; the URL is percent-encoded. If
    the two were compared as-is, every share entry with a space or a non-ASCII
    character in its name would silently match nothing."""
    member_path = attachment_store._share_member_path
    host = "https://cernbox.cern.ch"
    assert member_path(f"{host}/files/link/public/tok/front%20left.jpg") == (
        "front left.jpg"
    )
    assert member_path(f"{host}/files/link/public/tok/2026/vis/a.jpg") == "2026/vis/a.jpg"
    # A share that names no entry has no path inside it to match against.
    assert member_path(f"{host}/files/link/public/tok") == ""
    assert member_path(f"{host}/s/tok") == ""
    assert member_path(f"{host}/index.php/s/tok") == ""
