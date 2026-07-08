from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.sql import text


class Base(DeclarativeBase):
    pass


def make_engine(database_url: str) -> Engine:
    if database_url.startswith("sqlite"):
        # check_same_thread: FastAPI handles requests on a thread pool.
        # StaticPool keeps in-memory databases alive across connections (tests).
        return create_engine(
            database_url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool if ":memory:" in database_url else None,
        )
    return create_engine(database_url)


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
