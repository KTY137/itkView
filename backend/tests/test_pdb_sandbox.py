"""Integration tests against the PDB *test* instance.

Excluded from the default run (see pyproject addopts). Run explicitly with:

    pytest -m pdb_sandbox

Requires ITKFLOW_ITKDB_ACCESS_CODE1/2 in the environment or backend/.env.
Everything in here must stay strictly read-only.
"""

import pytest

from app.config import Settings
from app.pdb_gateway import PdbGateway

pytestmark = pytest.mark.pdb_sandbox


@pytest.fixture(scope="module")
def gateway() -> PdbGateway:
    settings = Settings()
    if not (settings.itkdb_access_code1 and settings.itkdb_access_code2):
        pytest.skip("No ITKDB access codes configured.")
    return PdbGateway(settings)


def test_read_only_connection_to_test_instance(gateway: PdbGateway):
    info = gateway.verify_connection()
    assert info["instance"] == "test"
    assert info["identity"]
    assert info["first_name"] or info["last_name"]
