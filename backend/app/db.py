from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.sql import text


class Base(DeclarativeBase):
    pass


def make_engine(database_url: str) -> Engine:
    if database_url.startswith("sqlite"):
        is_memory = ":memory:" in database_url
        # check_same_thread: FastAPI handles requests on a thread pool.
        # StaticPool keeps in-memory databases alive across connections (tests).
        engine = create_engine(
            database_url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool if is_memory else None,
        )
        if not is_memory:
            _enable_file_sqlite_concurrency(engine)
        return engine
    return create_engine(database_url)


def _enable_file_sqlite_concurrency(engine: Engine) -> None:
    """WAL plus a generous busy timeout for every connection to a file-backed
    SQLite database.

    Every non-Compose deployment (desktop bundle, dev launcher) shares one
    SQLite file between the API, the outbox worker/processor and the reminder
    scheduler. Python's sqlite3 driver otherwise gives up on a locked database
    after 5s, which surfaced live as a request-time `500` plus repeated
    "[outbox-processor] cycle failed" / "[reminder-scheduler] tick failed"
    lines during a single evidence sync. WAL mode is the actual fix: unlike the
    legacy rollback journal (where a writer's commit and any open reader
    transaction exclude each other), WAL lets one writer and any number of
    readers proceed concurrently. `busy_timeout` covers the remaining case —
    two writers racing — by making SQLite retry for 30s instead of failing
    after 5s. `synchronous=NORMAL` is the documented safe pairing with WAL
    (still durable across an application crash; only an OS-level power loss
    can lose the last commit).

    In-memory engines (":memory:") are skipped: WAL requires a real file, and
    `StaticPool` already funnels every connection through the same single
    connection, so there is no cross-connection locking to fix and tests must
    not be pointed at a mode that does not exist there.
    """

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, connection_record) -> None:  # noqa: ARG001
        cursor = dbapi_connection.cursor()
        try:
            # busy_timeout FIRST: converting a legacy rollback-journal file to
            # WAL needs a brief exclusive lock, and without the timeout that
            # very conversion can raise the "database is locked" error this
            # listener exists to fix (review M1).
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
        finally:
            cursor.close()


def is_sqlite_busy(error: BaseException) -> bool:
    """Whether `error` is SQLite's transient "database is locked" contention.

    This is expected under concurrent load (two writers, or a writer and a
    long-running reader outlasting `busy_timeout`) rather than a real failure.
    Shared by `sync_jobs` (lease-acquisition retries), `outbox_processor` and
    `reminders` (quiet-skip classification of an otherwise-broad `except
    Exception`) so the detection lives in one place. Safe to call with any
    exception, not just an `OperationalError`.
    """
    if not isinstance(error, OperationalError):
        return False
    detail = str(error).lower()
    return "database is locked" in detail or "database table is locked" in detail


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def ensure_phase0_sqlite_schema(engine: Engine) -> None:
    """Patch local SQLite dev DBs for additive Phase-0 schema changes.

    `Base.metadata.create_all()` creates new tables but does not alter existing
    SQLite tables. Until Alembic lands, keep this limited to additive,
    non-destructive columns needed by the current dev schema.
    """
    if engine.dialect.name != "sqlite":
        return
    with engine.begin() as connection:
        tables = {
            row[0]
            for row in connection.execute(
                text("SELECT name FROM sqlite_master WHERE type = 'table'")
            )
        }
        if "ingest_file" in tables:
            ingest_columns = {
                row[1] for row in connection.execute(text("PRAGMA table_info(ingest_file)"))
            }
            if "outbox_action_id" not in ingest_columns:
                connection.execute(
                    text("ALTER TABLE ingest_file ADD COLUMN outbox_action_id INTEGER")
                )
        if "outbox_action" in tables:
            outbox_columns = {
                row[1] for row in connection.execute(text("PRAGMA table_info(outbox_action)"))
            }
            if "external_ref" not in outbox_columns:
                connection.execute(
                    text("ALTER TABLE outbox_action ADD COLUMN external_ref VARCHAR(64)")
                )
            # Server-set attribution link to the signed-in user (docs/06). Nullable
            # and additive: the denormalised `created_by` string is kept for history.
            if "user_id" not in outbox_columns:
                connection.execute(
                    text("ALTER TABLE outbox_action ADD COLUMN user_id INTEGER")
                )
        if "audit_event" in tables:
            audit_columns = {
                row[1] for row in connection.execute(text("PRAGMA table_info(audit_event)"))
            }
            if "user_id" not in audit_columns:
                connection.execute(text("ALTER TABLE audit_event ADD COLUMN user_id INTEGER"))
        if "user_session" in tables:
            session_columns = {
                row[1] for row in connection.execute(text("PRAGMA table_info(user_session)"))
            }
            # Per-session CSRF token; existing sessions get NULL and must re-login.
            if "csrf_token" not in session_columns:
                connection.execute(
                    text("ALTER TABLE user_session ADD COLUMN csrf_token VARCHAR(64)")
                )
        if "component" in tables:
            component_columns = {
                row[1] for row in connection.execute(text("PRAGMA table_info(component)"))
            }
            if "stale" not in component_columns:
                connection.execute(
                    text("ALTER TABLE component ADD COLUMN stale BOOLEAN NOT NULL DEFAULT 0")
                )
        if "tool" in tables:
            tool_columns = {
                row[1] for row in connection.execute(text("PRAGMA table_info(tool)"))
            }
            if "label" not in tool_columns:
                connection.execute(text("ALTER TABLE tool ADD COLUMN label VARCHAR(120)"))
            # `Tool.__table_args__` declares `uq_tool_institute_code` on
            # (institute_id, code), but `create_all` only applies it to a table
            # it creates from scratch — SQLite has no `ALTER TABLE ADD
            # CONSTRAINT`, so an existing dev/desktop DB never gained it. Dedupe
            # before indexing or `CREATE UNIQUE INDEX` fails outright on real
            # duplicates. Keep the HIGHEST id: `tool_sync` updates the last row
            # it iterates (highest rowid), so keeping the oldest would
            # resurrect stale status/compatibility — e.g. silently re-activate
            # a blacklisted jig. Scoped to `institute_id IS NOT NULL`: SQLite
            # treats every NULL as distinct for uniqueness purposes, so rows
            # without an institute can never collide and must not be touched.
            deleted = connection.execute(
                text(
                    "DELETE FROM tool WHERE institute_id IS NOT NULL AND id NOT IN ("
                    "SELECT MAX(id) FROM tool WHERE institute_id IS NOT NULL "
                    "GROUP BY institute_id, code"
                    ")"
                )
            )
            if deleted.rowcount:
                # A destructive migration must never run silently.
                print(
                    f"[schema] removed {deleted.rowcount} duplicate tool row(s) "
                    "while retrofitting uq_tool_institute_code",
                    flush=True,
                )
            connection.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_tool_institute_code "
                    "ON tool (institute_id, code)"
                )
            )
        if "reminder" in tables:
            reminder_columns = {
                row[1] for row in connection.execute(text("PRAGMA table_info(reminder)"))
            }
            if "deleted_at" not in reminder_columns:
                connection.execute(text("ALTER TABLE reminder ADD COLUMN deleted_at DATETIME"))
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_reminder_deleted_at "
                    "ON reminder (deleted_at)"
                )
            )
        if "test_run_evidence" in tables:
            evidence_columns = {
                row[1] for row in connection.execute(text("PRAGMA table_info(test_run_evidence)"))
            }
            if "run_state" not in evidence_columns:
                connection.execute(
                    text("ALTER TABLE test_run_evidence ADD COLUMN run_state VARCHAR(32)")
                )
            # Backfill from the payload the mirror already stores, so an
            # existing database gets its withdrawn runs marked without waiting
            # for a full re-sync (on the owner's mirror: 102 of 14 759 rows).
            # Done in SQL on purpose — the payload column holds multi-megabyte
            # IV/response-curve blobs, and reading them into Python to look at
            # one key would pull hundreds of megabytes through the driver.
            # Only NULL rows are touched, so this never overwrites a state a
            # newer sync has already written and is safe to repeat on every
            # start.
            #
            # Every state is written, not only the withdrawn ones, precisely so
            # that the repeat is cheap: measured on the owner's 630 MB mirror,
            # writing all 14 759 states costs 27s once and 0.1s on every later
            # start, whereas a withdrawn-only backfill leaves ~14 700 rows NULL
            # and pays a 5.3s payload scan at *every* start forever. The
            # one-off sits well inside the desktop shell's 120s health wait.
            try:
                connection.execute(
                    text(
                        "UPDATE test_run_evidence "
                        "SET run_state = json_extract(payload, '$.state') "
                        "WHERE run_state IS NULL "
                        "AND json_extract(payload, '$.state') IS NOT NULL"
                    )
                )
            except OperationalError as error:
                # SQLite built without JSON1. Degrading to "no state known"
                # keeps every run counting as valid — the pre-fix behaviour —
                # instead of failing startup, but it must not be silent.
                print(
                    "[schema] could not backfill test_run_evidence.run_state "
                    f"({error.orig}); withdrawn PDB runs stay unmarked until the "
                    "next evidence sync",
                    flush=True,
                )
        attachment_reference_tables = (
            "test_run_attachment" in tables
            and "test_run_attachment_reference" in tables
        )
        if attachment_reference_tables:
            # Create the generic marker table in the ordinary additive-schema
            # transaction. The expensive association scan claims its row in a
            # fresh transaction below, where that INSERT is the first statement.
            connection.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS itkflow_schema_migration ("
                    "name VARCHAR(120) PRIMARY KEY, applied_at DATETIME NOT NULL"
                    ")"
                )
            )
        if "test_run_attachment" in tables:
            # Repair rows whose content type a re-sweep blanked (a PDB listing
            # declares none, and the reuse path used to overwrite the type the
            # download had sniffed). `is_image` derives from content_type, so
            # those rows went invisible in every gallery although their bytes
            # were untouched. The stored path still carries an exact suffix
            # from the mirror's established image allowlist, so the historical
            # type can be restored without opening the file or contacting the
            # PDB. Downloaded rows only — a row that was never fetched has
            # nothing to recover from.
            for suffix, content_type in (
                (".jpg", "image/jpeg"),
                (".jpeg", "image/jpeg"),
                (".png", "image/png"),
                (".gif", "image/gif"),
                (".webp", "image/webp"),
                (".bmp", "image/bmp"),
                (".avif", "image/avif"),
                (".tif", "image/tiff"),
                (".tiff", "image/tiff"),
                (".svg", "image/svg+xml"),
            ):
                connection.execute(
                    text(
                        "UPDATE test_run_attachment SET content_type = :content_type "
                        "WHERE content_type IS NULL AND downloaded_at IS NOT NULL "
                        "AND relative_path IS NOT NULL AND relative_path LIKE :pattern"
                    ),
                    {"content_type": content_type, "pattern": f"%{suffix}"},
                )

    if attachment_reference_tables:
        _backfill_sqlite_attachment_references(engine)


def _backfill_sqlite_attachment_references(engine: Engine) -> None:
    """Claim and run the one-shot Evidence-to-association backfill.

    This is deliberately a fresh transaction. Its first statement is the
    marker INSERT, so concurrent sidecars cannot both establish an older read
    snapshot and then race a check-before-insert. The winner keeps that write
    claim through the scan; the loser waits for the commit, gets rowcount zero
    and returns without parsing the Evidence JSON.
    """
    migration_name = "attachment_references_v1"
    with engine.begin() as connection:
        claim = connection.execute(
            text(
                "INSERT OR IGNORE INTO itkflow_schema_migration (name, applied_at) "
                "VALUES (:name, CURRENT_TIMESTAMP)"
            ),
            {"name": migration_name},
        )
        if claim.rowcount != 1:
            return

        try:
            # A savepoint lets a handled JSON1/SQL failure remove its marker
            # without committing any partial blob/reference rows. A process
            # crash rolls the whole outer transaction (including the claim)
            # back automatically.
            with connection.begin_nested():
                connection.execute(
                    text(
                        "CREATE TEMP TABLE itkflow_attachment_descriptor_backfill AS "
                        "SELECT e.id AS evidence_id, e.component_sn AS component_sn, "
                        "e.test_type AS test_type, COALESCE(e.external_ref, '') AS run_ref, "
                        "CASE WHEN json_extract(item.value, '$.source') = 'share_link' "
                        "THEN 'share_link' ELSE 'pdb' END AS source, "
                        "CAST(json_extract(item.value, '$.code') AS TEXT) AS pdb_code, "
                        "CAST(json_extract(item.value, '$.filename') AS TEXT) AS filename, "
                        "CAST(json_extract(item.value, '$.content_type') AS TEXT) "
                        "AS content_type, "
                        "CAST(json_extract(item.value, '$.title') AS TEXT) AS title, "
                        "COALESCE(e.synced_at, CURRENT_TIMESTAMP) AS synced_at "
                        "FROM test_run_evidence AS e, "
                        "json_each(e.payload, '$.attachments') AS item "
                        "WHERE json_extract(item.value, '$.code') IS NOT NULL"
                    )
                )
                # Some old Evidence descriptors never reached the download
                # phase, so create their not-yet-stored blob index too.
                connection.execute(
                    text(
                        "INSERT OR IGNORE INTO test_run_attachment "
                        "(component_sn, test_type, test_run_ref, source, pdb_code, "
                        "filename, content_type, title, synced_at) "
                        "SELECT component_sn, test_type, NULLIF(run_ref, ''), source, "
                        "pdb_code, filename, content_type, title, synced_at "
                        "FROM itkflow_attachment_descriptor_backfill "
                        "WHERE pdb_code <> '' ORDER BY evidence_id"
                    )
                )
                connection.execute(
                    text(
                        "INSERT OR IGNORE INTO test_run_attachment_reference "
                        "(attachment_id, component_sn, test_type, test_run_ref, "
                        "filename, title, synced_at) "
                        "SELECT attachment.id, descriptor.component_sn, "
                        "descriptor.test_type, descriptor.run_ref, "
                        "descriptor.filename, descriptor.title, descriptor.synced_at "
                        "FROM itkflow_attachment_descriptor_backfill AS descriptor "
                        "JOIN test_run_attachment AS attachment "
                        "ON attachment.source = descriptor.source "
                        "AND attachment.pdb_code = descriptor.pdb_code "
                        "WHERE descriptor.pdb_code <> ''"
                    )
                )
                # Rows created directly by older fixtures/tools may have no
                # Evidence descriptor. Preserve their one legacy association,
                # unless Evidence already supplied that blob/component.
                connection.execute(
                    text(
                        "INSERT OR IGNORE INTO test_run_attachment_reference "
                        "(attachment_id, component_sn, test_type, test_run_ref, "
                        "filename, title, synced_at) "
                        "SELECT attachment.id, attachment.component_sn, "
                        "attachment.test_type, COALESCE(attachment.test_run_ref, ''), "
                        "attachment.filename, attachment.title, attachment.synced_at "
                        "FROM test_run_attachment AS attachment "
                        "WHERE NOT EXISTS ("
                        "SELECT 1 FROM test_run_attachment_reference AS reference "
                        "WHERE reference.attachment_id = attachment.id "
                        "AND reference.component_sn = attachment.component_sn"
                        ")"
                    )
                )
        except OperationalError as error:
            connection.execute(
                text("DELETE FROM itkflow_schema_migration WHERE name = :name"),
                {"name": migration_name},
            )
            print(
                "[schema] could not backfill attachment references "
                f"({error.orig}); legacy rows remain readable and the next "
                "evidence sync will create associations",
                flush=True,
            )
        finally:
            connection.execute(
                text("DROP TABLE IF EXISTS itkflow_attachment_descriptor_backfill")
            )
