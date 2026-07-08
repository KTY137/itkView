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
from app.models import InstituteProfile, Tool
from app.sync import SyncStats, load_fixture_records, sync_components

DEMO_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "demo_components.json"

# Demo-only branding for seeded institutes. This is seed *data*, not product
# logic: the app reads an institute's name/logo from its profile (hard rule #4),
# so real deployments set these in their own profile. This map only makes the
# built-in demo look complete for the TUDO instance.
DEMO_INSTITUTE_BRANDING: dict[str, dict] = {
    "TUDO": {
        "name": "TU Dortmund",
        "logo_url": (
            "https://upload.wikimedia.org/wikipedia/commons/e/e6/"
            "Technische_Universit%C3%A4t_Dortmund_Logo.svg"
        ),
    },
}


# Demo jigs/tools for the TUDO instance, tagged with the module types they fit
# (docs/07). Seed data only — real deployments manage their own registry.
DEMO_TOOLS: list[dict] = [
    {"kind": "jig", "code": "HV-TAB-JIG-R5", "rfid": "E28011700000000000000001",
     "compatible_types": ["R5M0", "R5M1"]},
    {"kind": "jig", "code": "HV-TAB-JIG-R2", "rfid": "E28011700000000000000002",
     "compatible_types": ["R2"]},
    {"kind": "pickup_tool", "code": "PICKUP-R5", "rfid": "E28011700000000000000003",
     "compatible_types": ["R5M0", "R5M1"]},
    {"kind": "pickup_tool", "code": "PICKUP-R2", "rfid": "E28011700000000000000004",
     "compatible_types": ["R2"]},
    {"kind": "panel", "code": "GLUE-PANEL-R5-01", "rfid": None,
     "compatible_types": ["R5M0", "R5M1"]},
]


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
            branding = DEMO_INSTITUTE_BRANDING.get(code, {})
            logo_url = branding.get("logo_url")
            profile = session.scalar(select(InstituteProfile).where(InstituteProfile.code == code))
            if profile is None:
                session.add(
                    InstituteProfile(
                        code=code,
                        name=branding.get("name", f"Demo {code}"),
                        local_name_prefix=_default_prefix(code, local_names),
                        settings={"logo_url": logo_url} if logo_url else {},
                    )
                )
            elif logo_url and not (profile.settings or {}).get("logo_url"):
                # Backfill demo branding on re-seed (JSON reassigned, not mutated).
                profile.settings = {**(profile.settings or {}), "logo_url": logo_url}
        session.flush()  # assign institute ids for tool attachment

        tudo = session.scalar(select(InstituteProfile).where(InstituteProfile.code == "TUDO"))
        if tudo is not None:
            for spec in DEMO_TOOLS:
                exists = session.scalar(select(Tool).where(Tool.code == spec["code"]))
                if exists is None:
                    session.add(Tool(institute_id=tudo.id, **spec))

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
