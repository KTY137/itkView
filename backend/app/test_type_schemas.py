# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-FileComment: itkflow-6113f8ed4911
"""Upsert service for the local read-only test-type schema mirror."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import TestTypeSchema, utcnow
from app.pdb_test_types import TestTypeSchemaRecord


@dataclass(frozen=True)
class TestTypeSchemaSyncStats:
    created: int = 0
    updated: int = 0
    unchanged: int = 0

    @property
    def total(self) -> int:
        return self.created + self.updated + self.unchanged


def upsert_test_type_schemas(
    session: Session,
    records: list[TestTypeSchemaRecord],
    *,
    component_type: str | None = None,
) -> TestTypeSchemaSyncStats:
    """Idempotently replace complete schema snapshots in the requested scope.

    A successful PDB fetch is strict and therefore authoritative for its
    component type.  Rows absent from that snapshot must disappear locally or
    the manual-entry picker would keep offering retired schemas forever.  The
    explicit scope also lets an empty catalogue clear only the requested
    component type.  The caller owns the transaction.
    """
    records_by_key: dict[tuple[str, str], TestTypeSchemaRecord] = {}
    for record in records:
        key = (record.component_type, record.test_code)
        previous = records_by_key.get(key)
        if previous is not None and previous != record:
            raise ValueError("Conflicting duplicate test-type schema records.")
        records_by_key[key] = record

    keys = set(records_by_key)
    component_types = (
        {component_type}
        if component_type is not None
        else {record_component_type for record_component_type, _ in keys}
    )
    if component_type is not None and any(
        record_component_type != component_type for record_component_type, _ in keys
    ):
        raise ValueError("Test-type schema record is outside the requested component scope.")
    existing_rows = (
        list(
            session.scalars(
                select(TestTypeSchema).where(
                    TestTypeSchema.component_type.in_(component_types)
                )
            )
        )
        if component_types
        else []
    )
    existing = {(row.component_type, row.test_code): row for row in existing_rows}

    created = updated = unchanged = 0
    synced_at = utcnow()
    for record in records_by_key.values():
        key = (record.component_type, record.test_code)
        row = existing.get(key)
        if row is None:
            row = TestTypeSchema(
                component_type=record.component_type,
                test_code=record.test_code,
                name=record.name,
                schema_data=record.schema,
                synced_at=synced_at,
            )
            session.add(row)
            existing[key] = row
            created += 1
            continue

        changed = row.name != record.name or row.schema_data != record.schema
        row.name = record.name
        row.schema_data = record.schema
        row.synced_at = synced_at
        if changed:
            updated += 1
        else:
            unchanged += 1

    for key, row in existing.items():
        if key not in keys:
            session.delete(row)
    session.flush()
    return TestTypeSchemaSyncStats(created=created, updated=updated, unchanged=unchanged)
