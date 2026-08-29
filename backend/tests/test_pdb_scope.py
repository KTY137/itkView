# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-FileComment: itkflow-aed56720f6d5
"""Offline tests for the DUMMY write scope (docs/09, ADR 003)."""

from app.config import Settings
from app.pdb_scope import dummy_batch_name, is_dummy_target, is_registrable_type
from app.sync import SyncRecord, sync_components


def make_settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def seed_component(session_factory, sn: str, *, is_dummy: bool) -> None:
    record = SyncRecord(
        sn=sn,
        component_type="MODULE",
        type_code="R5M0",
        stage="GLUED",
        location="TUDO",
        institute_code="TUDO",
        local_name=None,
        parent_sn=None,
        is_dummy=is_dummy,
        trashed=False,
    )
    with session_factory() as session:
        sync_components(session, [record])
        session.commit()


def test_dummy_batch_name_uses_institute_code():
    assert dummy_batch_name("TUDO") == "DUMMY_TUDO"
    assert dummy_batch_name("DESYZ") == "DUMMY_DESYZ"


def test_registrable_types_allowlist():
    settings = make_settings()
    assert is_registrable_type("MODULE", settings)
    assert is_registrable_type("HYBRID", settings)
    # Never sensors or ASICs — no dummy mechanism exists for them and
    # registering one corrupts collaboration serial numbering.
    for forbidden in ("SENSOR", "ABC", "HCC", "AMAC", "PWB", "ASIC"):
        assert not is_registrable_type(forbidden, settings)


def test_registrable_types_can_be_narrowed_but_forbidden_stay_out():
    settings = make_settings(pdb_dummy_component_types=["MODULE"])
    assert is_registrable_type("MODULE", settings)
    assert not is_registrable_type("HYBRID", settings)
    assert not is_registrable_type("SENSOR", settings)


def test_is_dummy_target_requires_mirrored_dummy(session_factory):
    seed_component(session_factory, "20UPGM10000001", is_dummy=False)
    seed_component(session_factory, "20UPGM19999999", is_dummy=True)
    with session_factory() as session:
        assert not is_dummy_target(session, "20UPGM10000001")  # real part
        assert is_dummy_target(session, "20UPGM19999999")  # our dummy
        assert not is_dummy_target(session, "20UPGM17777777")  # unknown SN
        assert not is_dummy_target(session, "")
        assert not is_dummy_target(session, None)
