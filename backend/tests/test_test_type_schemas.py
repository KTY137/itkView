from sqlalchemy import select

from app.models import TestTypeSchema
from app.pdb_test_types import TestTypeSchemaRecord
from app.test_type_schemas import upsert_test_type_schemas


def record(code="MODULE_IV", *, name="Module IV", result_code="CURRENT"):
    return TestTypeSchemaRecord(
        component_type="MODULE",
        test_code=code,
        name=name,
        schema={"code": code, "results": [{"code": result_code}]},
    )


def test_creates_and_lists_a_schema(session_factory):
    with session_factory() as session:
        stats = upsert_test_type_schemas(session, [record()])
        session.commit()
        row = session.scalar(select(TestTypeSchema))

    assert (stats.created, stats.updated, stats.unchanged, stats.total) == (1, 0, 0, 1)
    assert row is not None
    assert row.schema_data["results"][0]["code"] == "CURRENT"


def test_identical_refresh_is_idempotent(session_factory):
    with session_factory() as session:
        upsert_test_type_schemas(session, [record()])
        session.commit()
        stats = upsert_test_type_schemas(session, [record()])
        session.commit()
        rows = list(session.scalars(select(TestTypeSchema)))

    assert stats.unchanged == 1
    assert len(rows) == 1


def test_changed_definition_is_updated_in_place(session_factory):
    with session_factory() as session:
        upsert_test_type_schemas(session, [record()])
        session.commit()
        original_id = session.scalar(select(TestTypeSchema.id))
        stats = upsert_test_type_schemas(
            session,
            [record(name="New name", result_code="VOLTAGE")],
        )
        session.commit()
        row = session.scalar(select(TestTypeSchema))

    assert stats.updated == 1
    assert row is not None
    assert row.id == original_id
    assert row.name == "New name"
    assert row.schema_data["results"][0]["code"] == "VOLTAGE"


def test_component_types_do_not_collide(session_factory):
    module = record()
    sensor = TestTypeSchemaRecord(
        component_type="SENSOR",
        test_code=module.test_code,
        name=module.name,
        schema=module.schema,
    )
    with session_factory() as session:
        stats = upsert_test_type_schemas(session, [module, sensor])
        session.commit()

    assert stats.created == 2


def test_scoped_complete_refresh_removes_retired_schemas(session_factory):
    with session_factory() as session:
        upsert_test_type_schemas(session, [record(), record("MODULE_BOW")])
        session.commit()

        stats = upsert_test_type_schemas(
            session,
            [record("MODULE_BOW")],
            component_type="MODULE",
        )
        session.commit()
        rows = list(session.scalars(select(TestTypeSchema)))

    assert stats.unchanged == 1
    assert [row.test_code for row in rows] == ["MODULE_BOW"]


def test_empty_scoped_snapshot_clears_only_that_component_type(session_factory):
    sensor = TestTypeSchemaRecord(
        component_type="SENSOR",
        test_code="SENSOR_IV",
        name="Sensor IV",
        schema={"code": "SENSOR_IV"},
    )
    with session_factory() as session:
        upsert_test_type_schemas(session, [record(), sensor])
        session.commit()

        stats = upsert_test_type_schemas(session, [], component_type="MODULE")
        session.commit()
        rows = list(session.scalars(select(TestTypeSchema)))

    assert stats.total == 0
    assert [(row.component_type, row.test_code) for row in rows] == [
        ("SENSOR", "SENSOR_IV")
    ]
