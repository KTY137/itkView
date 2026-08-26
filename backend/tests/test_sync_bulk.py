from datetime import datetime, timedelta, timezone

from sqlalchemy import event, select

from app.models import InstituteProfile
from app.sync import StageEventRecord, SyncRecord, sync_components
from app.tool_sync import sync_tools_from_components


def record(sn: str, *, events: int = 0) -> SyncRecord:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    return SyncRecord(
        sn=sn,
        component_type="MODULE",
        type_code="R5M0",
        stage="FINISHED",
        location="TUDO",
        institute_code="TUDO",
        stage_events=[
            StageEventRecord(stage=f"STAGE_{index}", entered_at=start + timedelta(days=index))
            for index in range(events)
        ],
    )


def test_component_sync_preloads_existing_rows_in_bounded_queries(session_factory):
    records = [record(f"20USEM{index:08d}") for index in range(120)]
    with session_factory() as session:
        sync_components(session, records, prune_scope="TUDO")
        session.commit()

    engine = session_factory.kw["bind"]
    component_selects: list[str] = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        normalized = " ".join(statement.lower().split())
        if normalized.startswith("select") and " from component " in f" {normalized} ":
            component_selects.append(normalized)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        with session_factory() as session:
            stats = sync_components(session, records, prune_scope="TUDO")
            session.commit()
    finally:
        event.remove(engine, "before_cursor_execute", capture)

    assert stats.unchanged == 120
    # One chunked preload plus the governed-row prune query, never 120 lookups.
    assert len(component_selects) <= 2


def test_stage_events_use_one_bulk_insert(session_factory):
    records = [record("20USEM00000001", events=3), record("20USEM00000002", events=2)]
    engine = session_factory.kw["bind"]
    stage_inserts: list[bool] = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        if statement.lower().lstrip().startswith("insert into stage_event"):
            stage_inserts.append(executemany)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        with session_factory() as session:
            sync_components(session, records)
            session.commit()
    finally:
        event.remove(engine, "before_cursor_execute", capture)

    assert stage_inserts == [True]


def test_stage_event_deletes_are_chunked_below_sqlite_bind_limit(session_factory):
    records = [record(f"20USEM{index:08d}", events=1) for index in range(501)]
    engine = session_factory.kw["bind"]
    delete_sizes: list[int] = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        if statement.lower().lstrip().startswith("delete from stage_event"):
            delete_sizes.append(len(parameters))

    event.listen(engine, "before_cursor_execute", capture)
    try:
        with session_factory() as session:
            sync_components(session, records)
            session.commit()
    finally:
        event.remove(engine, "before_cursor_execute", capture)

    assert delete_sizes == [500, 1]


def test_tool_sync_preloads_existing_tools(session_factory):
    tools = [
        SyncRecord(
            sn=f"20USERT{index:07d}",
            component_type="TOOLS",
            type_code="TOOL",
            stage="READY",
            location="TUDO",
            institute_code="TUDO",
            local_name=f"Module_Jig_R5M0_{index}",
        )
        for index in range(80)
    ]
    with session_factory() as session:
        institute = InstituteProfile(
            code="TUDO", name="TU Dortmund", local_name_prefix="TUDO-", settings={}
        )
        session.add(institute)
        sync_components(session, tools)
        session.flush()
        sync_tools_from_components(session, institute)
        session.commit()

    engine = session_factory.kw["bind"]
    tool_selects: list[str] = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        normalized = " ".join(statement.lower().split())
        if normalized.startswith("select") and " from tool " in f" {normalized} ":
            tool_selects.append(normalized)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        with session_factory() as session:
            institute = session.scalar(
                select(InstituteProfile).where(InstituteProfile.code == "TUDO")
            )
            stats = sync_tools_from_components(session, institute)
            session.commit()
    finally:
        event.remove(engine, "before_cursor_execute", capture)

    assert stats.unchanged == 80
    assert len(tool_selects) == 1
