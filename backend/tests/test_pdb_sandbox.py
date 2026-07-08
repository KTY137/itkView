"""Read-only smoke tests against the production PDB.

There is no PDB test server (docs/09); reads go against production behind the
double opt-in. Excluded from the default run (see pyproject addopts). Run
explicitly with:

    ITKFLOW_PDB_INSTANCE=production ITKFLOW_ALLOW_PRODUCTION=true \
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
    if settings.pdb_instance != "production" or not settings.allow_production:
        pytest.skip(
            "Production smoke needs ITKFLOW_PDB_INSTANCE=production and "
            "ITKFLOW_ALLOW_PRODUCTION=true (the test instance no longer exists)."
        )
    return PdbGateway(settings)


def test_read_only_connection(gateway: PdbGateway):
    info = gateway.verify_connection()
    assert info["instance"] == "production"
    assert info["identity"]
    assert info["first_name"] or info["last_name"]
    assert info["institutions"], "account should belong to at least one institute"


def test_list_own_institute_components_read_only(gateway: PdbGateway):
    """Count strip components at the caller's first institute — read-only."""
    client = gateway.client()
    me = gateway.verify_connection()
    institute = me["institutions"][0]
    response = client.get(
        "listComponents",
        json={
            "filterMap": {"project": "S", "institute": [institute]},
            "pageInfo": {"pageSize": 5},
        },
    )
    payloads = response.get("itemList", []) if isinstance(response, dict) else list(response)
    # Content varies per institute; the call succeeding read-only is the test.
    assert isinstance(payloads, list)
