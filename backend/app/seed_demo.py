"""Seed the configured database with the anonymised demo component fixture.

Run with:
    python -m app.seed_demo

Uses `Settings.database_url` (ITKFLOW_DATABASE_URL) and creates the schema
the same way `app.main` does. Idempotent: re-running updates the mirror
instead of duplicating it.
"""

from pathlib import Path

from sqlalchemy import select

from app.config import get_settings
from app.db import Base, ensure_phase0_sqlite_schema, make_engine, make_session_factory
from app.models import InstituteProfile
from app.sync import SyncStats, load_fixture_records, sync_components

DEMO_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "demo_components.json"


def _default_prefix(code: str, local_names: list[str]) -> str:
    candidates = [name for name in local_names if name.startswith(f"{code}-")]
    return f"{code}-" if candidates else ""


def seed(database_url: str, fixture_path: Path = DEMO_FIXTURE_PATH) -> SyncStats:
    engine = make_engine(database_url)
    # Phase 0/1: create the schema directly, exactly like app.main.create_app.
    Base.metadata.create_all(engine)
    ensure_phase0_sqlite_schema(engine)
    records = load_fixture_records(fixture_path)
    with make_session_factory(engine)() as session:
        by_institute: dict[str, list[str]] = {}
        for record in records:
            if record.local_name is not None:
                by_institute.setdefault(record.institute_code, []).append(record.local_name)
            else:
                by_institute.setdefault(record.institute_code, [])
        for code, local_names in by_institute.items():
            profile = session.scalar(select(InstituteProfile).where(InstituteProfile.code == code))
            if profile is None:
                session.add(
                    InstituteProfile(
                        code=code,
                        name=f"Demo {code}",
                        local_name_prefix=_default_prefix(code, local_names),
                        settings={},
                    )
                )
        stats = sync_components(session, records)
        session.commit()
    return stats


def main() -> None:
    settings = get_settings()
    stats = seed(settings.database_url)
    print(
        f"Seeded {DEMO_FIXTURE_PATH.name} into {settings.database_url}: "
        f"{stats.created} created, {stats.updated} updated, {stats.unchanged} unchanged."
    )


if __name__ == "__main__":
    main()
