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

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import IntegrityError, OperationalError

from app.db import (
    Base,
    ensure_phase0_sqlite_schema,
    is_sqlite_busy,
    make_engine,
    make_session_factory,
)
from app.models import InstituteProfile

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
