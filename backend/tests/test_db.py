"""Tests for `app/db.py`: SQLite concurrency pragmas and the additive
Phase-0 migration helper.

Context (docs/09): a live desktop-bundle evidence sync produced repeated
`sqlite3.OperationalError: database is locked` — once as a request-time 500,
several times as "[outbox-processor] cycle failed" / "[reminder-scheduler]
tick failed" — because a file-backed SQLite database had no WAL and no
`busy_timeout`, so Python's sqlite3 driver gave up after its hardcoded 5s
default the moment two of {API request, outbox worker/processor, reminder
scheduler} touched the file at once.
"""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock

import pytest
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.exc import IntegrityError, OperationalError

from app.db import (
    Base,
    ensure_phase0_sqlite_schema,
    is_sqlite_busy,
    make_engine,
    make_session_factory,
)
from app.models import (
    InstituteProfile,
    TestRunAttachment,
    TestRunAttachmentReference,
    TestRunEvidence,
    utcnow,
)

# ---------------------------------------------------------------------------
# 1. File-backed SQLite gets WAL + a generous busy timeout; :memory: does not.
# ---------------------------------------------------------------------------


def test_file_backed_engine_enables_wal_and_a_generous_busy_timeout(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'pragmas.db'}")
    with engine.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
        assert conn.exec_driver_sql("PRAGMA busy_timeout").scalar() == 30000
        # 1 == NORMAL, the documented safe pairing with WAL (still durable
        # across an application crash; only an OS-level power loss can lose
        # the last commit).
        assert conn.exec_driver_sql("PRAGMA synchronous").scalar() == 1


def test_file_backed_pragmas_apply_to_every_new_connection(tmp_path):
    """The pragmas are per-connection state, so a second/third connection off
    the same engine (a real pool, not `:memory:`'s single StaticPool
    connection) must get them too, not just the first one opened."""
    engine = make_engine(f"sqlite:///{tmp_path / 'pragmas-pool.db'}")
    for _ in range(3):
        with engine.connect() as conn:
            assert conn.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
            assert conn.exec_driver_sql("PRAGMA busy_timeout").scalar() == 30000


def test_in_memory_engine_is_left_untouched_and_stays_fully_functional():
    """`:memory:` must not be pointed at WAL (it does not exist there) and must
    keep working exactly as before — StaticPool already funnels every
    connection through one shared connection, so there is no cross-connection
    lock to fix."""
    engine = make_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA journal_mode").scalar() != "wal"

    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    with factory() as session:
        session.add(InstituteProfile(code="TUDO", name="TU Dortmund", local_name_prefix="TUDO-"))
        session.commit()
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(InstituteProfile)) == 1


def test_non_sqlite_urls_skip_the_sqlite_only_setup(monkeypatch):
    """Guard the dialect check: a non-sqlite URL must reach plain
    `create_engine(url)` — no sqlite-only `connect_args` and no pragma
    listener attached. Stubs `create_engine` so this does not need a real
    Postgres driver installed."""
    calls: list[tuple[str, dict]] = []

    def fake_create_engine(url, **kwargs):
        calls.append((url, kwargs))
        return "engine-stub"

    monkeypatch.setattr("app.db.create_engine", fake_create_engine)

    result = make_engine("postgresql+psycopg://user:pass@localhost/db")

    assert result == "engine-stub"
    assert calls == [("postgresql+psycopg://user:pass@localhost/db", {})]


# ---------------------------------------------------------------------------
# 1c. The actual proof: WAL lets a writer and a reader proceed concurrently.
# ---------------------------------------------------------------------------


def test_wal_lets_a_writer_commit_while_a_reader_holds_an_open_transaction(tmp_path):
    """The decisive, real proof that the pragmas are effective rather than set
    and ignored.

    SQLite's legacy rollback journal makes a writer's COMMIT and any other
    connection's still-open read transaction mutually exclusive: the writer
    needs an EXCLUSIVE file lock, and an open reader's SHARED lock refuses to
    yield one, so the commit blocks and eventually raises `database is
    locked`. That is exactly the shape of the observed live bug — a request
    handler reading the database while a sync/outbox/reminder tick tries to
    write. WAL removes that exclusion: one writer and any number of readers
    proceed concurrently. This test also covers the mirrored direction (a
    reader must not be blocked by a writer's still-open, uncommitted
    transaction either).
    """
    engine = make_engine(f"sqlite:///{tmp_path / 'wal-proof.db'}")
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)

    with factory() as seed:
        seed.add(InstituteProfile(code="TUDO", name="TU Dortmund", local_name_prefix="TUDO-"))
        seed.commit()

    # Direction 1: an open, uncommitted writer transaction must not block a
    # concurrent reader.
    writer = factory()
    writer.execute(text("BEGIN IMMEDIATE"))
    writer.add(InstituteProfile(code="DESYZ", name="DESY Zeuthen", local_name_prefix="DESYZ-"))
    writer.flush()
    try:
        with factory() as reader:
            count = reader.scalar(select(func.count()).select_from(InstituteProfile))
            assert count == 1  # the writer's insert is not committed/visible yet
    finally:
        writer.commit()
        writer.close()

    # Direction 2 — the one that actually distinguishes WAL from the legacy
    # rollback journal: a writer must be able to COMMIT while a reader still
    # holds its own open transaction.
    reader = factory()
    reader.execute(text("BEGIN"))
    reader.scalar(select(func.count()).select_from(InstituteProfile))  # opens the read txn
    try:
        with factory() as writer2:
            writer2.add(InstituteProfile(code="CERN", name="CERN", local_name_prefix="CERN-"))
            writer2.commit()  # must not raise `database is locked`
    finally:
        reader.rollback()
        reader.close()

    with factory() as verify:
        codes = set(verify.scalars(select(InstituteProfile.code)))
        assert codes == {"TUDO", "DESYZ", "CERN"}


def test_legacy_rollback_journal_deadlocks_the_same_scenario_wal_fixes(tmp_path):
    """Negative control for the test above: without the WAL pragma, this exact
    concurrent-commit shape really does raise `database is locked` — proving
    the positive test is not accidentally passing for an unrelated reason.
    Bypasses `app.db.make_engine` on purpose to get SQLite's untouched
    default (legacy rollback journal); the timeout is shortened only so the
    failure is immediate instead of waiting out Python's 5s default.
    """
    engine = create_engine(
        f"sqlite:///{tmp_path / 'no-wal.db'}", connect_args={"timeout": 0.05}
    )
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)

    with factory() as seed:
        seed.add(InstituteProfile(code="TUDO", name="TU Dortmund", local_name_prefix="TUDO-"))
        seed.commit()

    reader = factory()
    reader.execute(text("BEGIN"))
    reader.scalar(select(func.count()).select_from(InstituteProfile))
    try:
        with pytest.raises(OperationalError, match=r"(?i)database is locked"):
            with factory() as writer:
                writer.add(InstituteProfile(code="CERN", name="CERN", local_name_prefix="CERN-"))
                writer.commit()
    finally:
        reader.rollback()
        reader.close()


# ---------------------------------------------------------------------------
# `is_sqlite_busy` classifier shared with sync_jobs/outbox_processor/reminders
# ---------------------------------------------------------------------------


def test_is_sqlite_busy_matches_locked_operational_errors():
    locked = OperationalError("SELECT 1", {}, Exception("database is locked"))
    table_locked = OperationalError("SELECT 1", {}, Exception("database table is locked"))
    assert is_sqlite_busy(locked) is True
    assert is_sqlite_busy(table_locked) is True


def test_is_sqlite_busy_rejects_other_operational_errors_and_exception_types():
    other = OperationalError("SELECT 1", {}, Exception("no such table: outbox_action"))
    assert is_sqlite_busy(other) is False
    # Safe to call with any exception, including ones whose message happens to
    # mention the phrase but are not the SQLite driver's own error type.
    assert is_sqlite_busy(RuntimeError("database is locked")) is False


# ---------------------------------------------------------------------------
# 2. Additive migration: dedupe + retrofit `uq_tool_institute_code`.
# ---------------------------------------------------------------------------


def _create_legacy_tool_table(engine) -> None:
    """A `tool` table as it existed before `uq_tool_institute_code` — no
    unique index, so real duplicate (institute_id, code) rows could
    accumulate."""
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE tool (id INTEGER PRIMARY KEY, kind VARCHAR(24), "
                "code VARCHAR(64), institute_id INTEGER, status VARCHAR(16))"
            )
        )


def test_migration_dedupes_and_retrofits_the_tool_unique_index(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'legacy-tools.db'}")
    _create_legacy_tool_table(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO tool (id, kind, code, institute_id, status) VALUES "
                "(1, 'jig', 'JIG-1', 7, 'active'), "  # duplicate — dropped
                "(2, 'jig', 'JIG-1', 7, 'flagged'), "  # duplicate — dropped
                # Kept: HIGHEST id of the group — tool_sync maintains the last
                # row it iterates (in practice the highest rowid), so keeping
                # MIN would resurrect stale status/compatibility (review I3).
                "(3, 'jig', 'JIG-1', 7, 'blacklisted'), "
                "(4, 'jig', 'JIG-2', 7, 'active'), "  # untouched: not a duplicate
                "(5, 'jig', 'JIG-1', 8, 'active'), "  # untouched: different institute
                "(6, 'jig', 'JIG-3', NULL, 'active'), "  # untouched: NULL institute...
                "(7, 'jig', 'JIG-3', NULL, 'active')"  # ...never collides, even repeated
            )
        )

    ensure_phase0_sqlite_schema(engine)

    with engine.connect() as conn:
        remaining = conn.execute(text("SELECT id FROM tool ORDER BY id")).scalars().all()
        assert remaining == [3, 4, 5, 6, 7]
        # The maintained (blacklisted) row survived, not the stale active one.
        surviving_status = conn.execute(
            text("SELECT status FROM tool WHERE institute_id = 7 AND code = 'JIG-1'")
        ).scalar_one()
        assert surviving_status == "blacklisted"

        index_names = {
            row[0]
            for row in conn.execute(
                text("SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'tool'")
            )
        }
        assert "uq_tool_institute_code" in index_names


def test_migration_is_idempotent_on_an_already_clean_table(tmp_path):
    """Running the patch twice (every process start) on a DB that already has
    no duplicates and already has the index must not error or change data."""
    engine = make_engine(f"sqlite:///{tmp_path / 'clean-tools.db'}")
    _create_legacy_tool_table(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO tool (id, kind, code, institute_id, status) "
                "VALUES (1, 'jig', 'JIG-1', 7, 'active')"
            )
        )

    ensure_phase0_sqlite_schema(engine)
    ensure_phase0_sqlite_schema(engine)  # second run, same as every later app start

    with engine.connect() as conn:
        remaining = conn.execute(text("SELECT id FROM tool")).scalars().all()
        assert remaining == [1]


def test_migrated_unique_index_is_actually_enforced(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'enforced-tools.db'}")
    _create_legacy_tool_table(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO tool (id, kind, code, institute_id, status) "
                "VALUES (1, 'jig', 'JIG-1', 7, 'active')"
            )
        )

    ensure_phase0_sqlite_schema(engine)

    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO tool (kind, code, institute_id, status) "
                    "VALUES ('jig', 'JIG-1', 7, 'active')"
                )
            )


def test_fresh_database_migration_does_not_duplicate_or_break_the_index(tmp_path):
    """A brand-new DB already gets the constraint from `create_all`; the
    unconditional migration step must be a harmless no-op there too."""
    engine = make_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    Base.metadata.create_all(engine)
    ensure_phase0_sqlite_schema(engine)

    factory = make_session_factory(engine)
    from app.models import InstituteProfile as _InstituteProfile
    from app.models import Tool

    with factory() as session:
        institute = _InstituteProfile(
            code="TUDO", name="TU Dortmund", local_name_prefix="TUDO-"
        )
        session.add(institute)
        session.commit()
        session.add(Tool(kind="jig", code="JIG-1", institute_id=institute.id))
        session.commit()

        with pytest.raises(IntegrityError):
            session.add(Tool(kind="jig", code="JIG-1", institute_id=institute.id))
            session.commit()


# ---------------------------------------------------------------------------
# 3. Additive attachment-reference migration.
# ---------------------------------------------------------------------------


def test_attachment_content_type_repair_covers_every_supported_image_suffix(
    tmp_path,
):
    """The historical reuse bug blanked every image MIME, not only JPEG/PNG."""
    engine = make_engine(f"sqlite:///{tmp_path / 'attachment-content-types.db'}")
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    expected = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
        ".avif": "image/avif",
        ".tif": "image/tiff",
        ".tiff": "image/tiff",
        ".svg": "image/svg+xml",
    }
    with factory() as session:
        for index, suffix in enumerate(expected):
            session.add(
                TestRunAttachment(
                    component_sn=f"IMAGE-SN-{index}",
                    test_type="VISUAL_INSPECTION",
                    source="pdb",
                    pdb_code=f"image-{index}",
                    content_type=None,
                    relative_path=f"IMAGE-SN-{index}/image-{index}{suffix}",
                    downloaded_at=utcnow(),
                )
            )
        # Extension matching is exact and only repairs rows known to have
        # completed a download. It never infers SVG (or any other type) from
        # arbitrary bytes or a suffix embedded before another extension.
        session.add_all(
            [
                TestRunAttachment(
                    component_sn="NOT-DOWNLOADED",
                    test_type="VISUAL_INSPECTION",
                    source="pdb",
                    pdb_code="not-downloaded",
                    content_type=None,
                    relative_path="NOT-DOWNLOADED/not-downloaded.gif",
                    downloaded_at=None,
                ),
                TestRunAttachment(
                    component_sn="SVG-TEXT",
                    test_type="VISUAL_INSPECTION",
                    source="pdb",
                    pdb_code="svg-text",
                    content_type=None,
                    relative_path="SVG-TEXT/operator-note.svg.txt",
                    downloaded_at=utcnow(),
                ),
                TestRunAttachment(
                    component_sn="KNOWN-TYPE",
                    test_type="VISUAL_INSPECTION",
                    source="pdb",
                    pdb_code="known-type",
                    content_type="application/octet-stream",
                    relative_path="KNOWN-TYPE/known-type.svg",
                    downloaded_at=utcnow(),
                ),
            ]
        )
        session.commit()

    ensure_phase0_sqlite_schema(engine)
    ensure_phase0_sqlite_schema(engine)

    with factory() as session:
        repaired = {
            suffix: session.scalar(
                select(TestRunAttachment.content_type).where(
                    TestRunAttachment.pdb_code
                    == f"image-{list(expected).index(suffix)}"
                )
            )
            for suffix in expected
        }
        assert repaired == expected
        assert session.scalar(
            select(TestRunAttachment.content_type).where(
                TestRunAttachment.pdb_code == "not-downloaded"
            )
        ) is None
        assert session.scalar(
            select(TestRunAttachment.content_type).where(
                TestRunAttachment.pdb_code == "svg-text"
            )
        ) is None
        assert session.scalar(
            select(TestRunAttachment.content_type).where(
                TestRunAttachment.pdb_code == "known-type"
            )
        ) == "application/octet-stream"


def _attachment_reference_upgrade_fixture(tmp_path, name):
    engine = make_engine(f"sqlite:///{tmp_path / name}")
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    with factory() as session:
        session.add(
            TestRunAttachment(
                component_sn="20USEP00000001",
                test_type="VISUAL_INSPECTION",
                test_run_ref="RUN-SHARED",
                source="share_link",
                pdb_code="shared-folder-code",
                filename="folder",
                content_type="image/jpeg",
                relative_path="20USEP00000001/shared-folder-code.jpg",
            )
        )
        session.add(
            TestRunEvidence(
                component_sn="20USEP00000001",
                test_type="VISUAL_INSPECTION",
                passed=True,
                source="pdb",
                external_ref="RUN-SHARED",
                payload={
                    "attachments": [
                        {
                            "source": "share_link",
                            "code": "shared-folder-code",
                            "filename": "folder",
                            "content_type": None,
                            "title": "Inspection picture",
                        }
                    ]
                },
            )
        )
        session.commit()
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE test_run_attachment_reference"))
    Base.metadata.create_all(engine)
    return engine, factory


def test_attachment_reference_migration_backfills_evidence_and_legacy_rows_once(
    tmp_path,
):
    """Upgrade reconstructs every occurrence without copying a stored blob."""
    engine = make_engine(f"sqlite:///{tmp_path / 'attachment-references.db'}")
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    shared_code = "shared-folder-code"

    with factory() as session:
        shared_blob = TestRunAttachment(
            component_sn="20USEP00000001",
            test_type="VISUAL_INSPECTION",
            test_run_ref="RUN-A1",
            source="share_link",
            pdb_code=shared_code,
            filename="folder",
            content_type="image/jpeg",
            title="Legacy representative",
            size_bytes=1234,
            relative_path="20USEP00000001/shared-folder-code.jpg",
        )
        legacy_only_blob = TestRunAttachment(
            component_sn="20USEP00000099",
            test_type="CUSTOM_TEST",
            test_run_ref=None,
            source="pdb",
            pdb_code="legacy-only-code",
            filename="legacy.txt",
            content_type="text/plain",
            title="No Evidence payload exists",
        )
        session.add_all([shared_blob, legacy_only_blob])
        session.flush()
        shared_blob_id = shared_blob.id
        legacy_blob_id = legacy_only_blob.id

        associations = [
            ("20USEP00000001", "RUN-A1"),
            ("20USEP00000001", "RUN-A2"),
            ("20USEP00000002", "RUN-B"),
            ("20USEP00000003", "RUN-C"),
        ]
        for component_sn, run_ref in associations:
            attachments = [
                {
                    "source": "share_link",
                    "code": shared_code,
                    "filename": "folder",
                    "content_type": None,
                    "title": "Inspection picture",
                }
            ]
            if run_ref == "RUN-B":
                # Old Evidence can know metadata for a file whose download
                # never succeeded. Its blob index and association still need
                # to exist after migration, with no claim that bytes exist.
                attachments.append(
                    {
                        "code": "pending-pdb-code",
                        "filename": "pending.dat",
                        "content_type": None,
                        "title": "Pending binary",
                    }
                )
            session.add(
                TestRunEvidence(
                    component_sn=component_sn,
                    test_type="VISUAL_INSPECTION",
                    passed=True,
                    source="pdb",
                    external_ref=run_ref,
                    payload={"attachments": attachments},
                )
            )
        session.commit()

    # Model an upgrade from the old schema: create_all on the new application
    # adds the table before the SQLite startup helper performs the data backfill.
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE test_run_attachment_reference"))
    Base.metadata.create_all(engine)

    ensure_phase0_sqlite_schema(engine)
    ensure_phase0_sqlite_schema(engine)

    with factory() as session:
        blobs = {
            (blob.source, blob.pdb_code): blob
            for blob in session.scalars(select(TestRunAttachment))
        }
        assert len(blobs) == 3
        shared = blobs[("share_link", shared_code)]
        assert shared.id == shared_blob_id
        assert shared.relative_path == "20USEP00000001/shared-folder-code.jpg"
        assert shared.size_bytes == 1234
        pending = blobs[("pdb", "pending-pdb-code")]
        assert pending.relative_path is None
        assert pending.downloaded_at is None

        references = list(
            session.scalars(
                select(TestRunAttachmentReference).order_by(
                    TestRunAttachmentReference.attachment_id,
                    TestRunAttachmentReference.component_sn,
                    TestRunAttachmentReference.test_run_ref,
                )
            )
        )
        shared_references = [
            reference for reference in references if reference.attachment_id == shared_blob_id
        ]
        assert {
            (reference.component_sn, reference.test_type, reference.test_run_ref)
            for reference in shared_references
        } == {
            (component_sn, "VISUAL_INSPECTION", run_ref) for component_sn, run_ref in associations
        }
        assert len(shared_references) == 4
        assert [
            (
                reference.component_sn,
                reference.test_type,
                reference.test_run_ref,
            )
            for reference in references
            if reference.attachment_id == legacy_blob_id
        ] == [("20USEP00000099", "CUSTOM_TEST", "")]
        assert [
            (reference.component_sn, reference.test_run_ref)
            for reference in references
            if reference.attachment_id == pending.id
        ] == [("20USEP00000002", "RUN-B")]
        assert len(references) == 6

        marker_count = session.scalar(
            text(
                "SELECT COUNT(*) FROM itkflow_schema_migration "
                "WHERE name = 'attachment_references_v1'"
            )
        )
        assert marker_count == 1


def test_attachment_reference_migration_has_one_winner_under_parallel_startup(
    tmp_path,
):
    """Both processes attempt the claim; exactly one parses the Evidence JSON."""
    engine, factory = _attachment_reference_upgrade_fixture(
        tmp_path, "parallel-reference-migration.db"
    )
    claim_barrier = Barrier(2)
    count_guard = Lock()
    scans = 0

    def observe_sql(
        connection, cursor, statement, parameters, context, executemany  # noqa: ARG001
    ):
        nonlocal scans
        normalized = " ".join(statement.split())
        if normalized.startswith(
            "INSERT OR IGNORE INTO itkflow_schema_migration"
        ):
            claim_barrier.wait(timeout=10)
        elif normalized.startswith(
            "CREATE TEMP TABLE itkflow_attachment_descriptor_backfill"
        ):
            with count_guard:
                scans += 1

    event.listen(engine, "before_cursor_execute", observe_sql)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(ensure_phase0_sqlite_schema, engine)
                for _ in range(2)
            ]
            for future in futures:
                future.result(timeout=20)
    finally:
        event.remove(engine, "before_cursor_execute", observe_sql)

    assert scans == 1
    with factory() as session:
        assert (
            session.scalar(
                select(func.count()).select_from(TestRunAttachmentReference)
            )
            == 1
        )
        assert (
            session.scalar(
                text(
                    "SELECT COUNT(*) FROM itkflow_schema_migration "
                    "WHERE name = 'attachment_references_v1'"
                )
            )
            == 1
        )


def test_failed_attachment_reference_backfill_releases_claim_for_retry(tmp_path):
    engine, factory = _attachment_reference_upgrade_fixture(
        tmp_path, "retry-reference-migration.db"
    )

    def fail_descriptor_scan(
        connection, cursor, statement, parameters, context, executemany  # noqa: ARG001
    ):
        if "CREATE TEMP TABLE itkflow_attachment_descriptor_backfill" in statement:
            raise OperationalError(
                statement, parameters, Exception("simulated JSON scan failure")
            )

    event.listen(engine, "before_cursor_execute", fail_descriptor_scan)
    try:
        ensure_phase0_sqlite_schema(engine)
    finally:
        event.remove(engine, "before_cursor_execute", fail_descriptor_scan)

    with factory() as session:
        assert (
            session.scalar(
                select(func.count()).select_from(TestRunAttachmentReference)
            )
            == 0
        )
        assert (
            session.scalar(
                text(
                    "SELECT COUNT(*) FROM itkflow_schema_migration "
                    "WHERE name = 'attachment_references_v1'"
                )
            )
            == 0
        )

    ensure_phase0_sqlite_schema(engine)
    with factory() as session:
        assert (
            session.scalar(
                select(func.count()).select_from(TestRunAttachmentReference)
            )
            == 1
        )
