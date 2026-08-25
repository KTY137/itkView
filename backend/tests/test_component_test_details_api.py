"""API for mirrored test detail and locally stored attachments.

Covers what the glue-weight, metrology and IV views read, plus the rule that
attachment bytes are served from disk only — never lazily re-fetched behind an
image tag.
"""

import pytest
from authutil import authenticate
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models import TestRunAttachment, TestRunEvidence
from app.pdb_credentials import generate_pdb_credential_encryption_key

JPEG = b"\xff\xd8\xff\xe0itkflow"
SN = "20USEM20000041"


@pytest.fixture()
def attachments_dir(tmp_path):
    return tmp_path / "attachments"


@pytest.fixture()
def client(attachments_dir) -> TestClient:
    settings = Settings(
        database_url="sqlite:///:memory:",
        pdb_credential_encryption_key=generate_pdb_credential_encryption_key(),
        attachment_dir=str(attachments_dir),
        _env_file=None,
    )
    return TestClient(create_app(settings))


@pytest.fixture()
def as_operator(client) -> TestClient:
    authenticate(client, client.app.state.session_factory, role="operator")
    return client


@pytest.fixture()
def mirrored(client):
    """A glue-weight run and an IV run, as the detailed sync would leave them."""
    factory = client.app.state.session_factory
    with factory() as session:
        session.add(
            TestRunEvidence(
                component_sn=SN,
                test_type="GLUE_WEIGHT",
                passed=True,
                source="pdb",
                external_ref="RUN-GW",
                payload={
                    "run_number": "1",
                    "results": {"GW_GLUE_H1": 0.166, "GW_HYBRID2": None},
                    "result_meta": {
                        "GW_GLUE_H1": {"name": "Weight of glue under hybrid 1 [g]"}
                    },
                    "properties": {"GW_METHOD": "Stencil"},
                    "attachments": [
                        {
                            "code": "att-1",
                            "filename": "scale.jpg",
                            "content_type": "image/jpeg",
                            "title": None,
                        }
                    ],
                },
            )
        )
        session.add(
            TestRunEvidence(
                component_sn=SN,
                test_type="MODULE_IV_PS_V1",
                passed=True,
                source="pdb",
                external_ref="RUN-IV",
                payload={"results": {"CURRENT": [1.0, 2.0], "VOLTAGE": [0.0, -10.0]}},
            )
        )
        session.commit()


def _store_attachment(client, attachments_dir, *, stored=True):
    factory = client.app.state.session_factory
    relative = f"{SN}/att-1.jpg"
    if stored:
        target = attachments_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(JPEG)
    with factory() as session:
        session.add(
            TestRunAttachment(
                component_sn=SN,
                test_type="GLUE_WEIGHT",
                test_run_ref="RUN-GW",
                source="pdb",
                pdb_code="att-1",
                filename="scale.jpg",
                content_type="image/jpeg",
                size_bytes=len(JPEG) if stored else None,
                relative_path=relative if stored else None,
            )
        )
        session.commit()


# --- test detail -----------------------------------------------------------


def test_measured_values_are_served(as_operator, mirrored):
    response = as_operator.get(f"/api/components/{SN}/tests")
    assert response.status_code == 200, response.text

    glue = next(r for r in response.json() if r["test_type"] == "GLUE_WEIGHT")
    assert glue["results"]["GW_GLUE_H1"] == 0.166
    assert glue["properties"]["GW_METHOD"] == "Stencil"
    assert glue["run_number"] == "1"


def test_result_names_are_served_so_units_survive(as_operator, mirrored):
    response = as_operator.get(f"/api/components/{SN}/tests")
    glue = next(r for r in response.json() if r["test_type"] == "GLUE_WEIGHT")
    assert glue["result_meta"]["GW_GLUE_H1"]["name"].endswith("[g]")


def test_iv_arrays_are_served_whole(as_operator, mirrored):
    response = as_operator.get(f"/api/components/{SN}/tests")
    iv = next(r for r in response.json() if r["test_type"] == "MODULE_IV_PS_V1")
    assert iv["results"]["CURRENT"] == [1.0, 2.0]
    assert iv["results"]["VOLTAGE"] == [0.0, -10.0]


def test_unmeasured_values_stay_null(as_operator, mirrored):
    response = as_operator.get(f"/api/components/{SN}/tests")
    glue = next(r for r in response.json() if r["test_type"] == "GLUE_WEIGHT")
    assert glue["results"]["GW_HYBRID2"] is None


def test_a_component_without_a_mirror_returns_an_empty_list(as_operator):
    response = as_operator.get("/api/components/20USEM99999999/tests")
    assert response.status_code == 200
    assert response.json() == []


def test_test_details_need_a_signed_in_user(client, mirrored):
    assert client.get(f"/api/components/{SN}/tests").status_code == 401


# --- attachments -----------------------------------------------------------


def test_attachments_are_listed_with_their_stored_state(
    as_operator, attachments_dir, mirrored
):
    _store_attachment(as_operator, attachments_dir)
    response = as_operator.get(f"/api/components/{SN}/attachments")
    assert response.status_code == 200

    entry = response.json()[0]
    assert entry["code"] == "att-1"
    assert entry["stored"] is True
    assert entry["is_image"] is True


def test_a_known_but_unmirrored_attachment_reports_not_stored(
    as_operator, attachments_dir, mirrored
):
    _store_attachment(as_operator, attachments_dir, stored=False)
    entry = as_operator.get(f"/api/components/{SN}/attachments").json()[0]
    # Known but not on disk: the UI can offer the sync rather than hide it.
    assert entry["stored"] is False


def test_attachments_are_attached_to_their_run(as_operator, attachments_dir, mirrored):
    _store_attachment(as_operator, attachments_dir)
    response = as_operator.get(f"/api/components/{SN}/tests")

    glue = next(r for r in response.json() if r["test_type"] == "GLUE_WEIGHT")
    iv = next(r for r in response.json() if r["test_type"] == "MODULE_IV_PS_V1")
    assert [a["code"] for a in glue["attachments"]] == ["att-1"]
    assert iv["attachments"] == []


def test_stored_bytes_are_served(as_operator, attachments_dir, mirrored):
    _store_attachment(as_operator, attachments_dir)
    response = as_operator.get(f"/api/components/{SN}/attachments/att-1")

    assert response.status_code == 200
    assert response.content == JPEG
    assert response.headers["content-type"].startswith("image/jpeg")


def test_an_unmirrored_attachment_is_404_not_a_silent_pdb_fetch(
    as_operator, attachments_dir, mirrored
):
    _store_attachment(as_operator, attachments_dir, stored=False)
    response = as_operator.get(f"/api/components/{SN}/attachments/att-1")

    assert response.status_code == 404
    assert "Sync attachments" in response.json()["detail"]


def test_an_unknown_attachment_is_404(as_operator, mirrored):
    assert as_operator.get(f"/api/components/{SN}/attachments/nope").status_code == 404


def test_attachment_bytes_need_a_signed_in_user(client, attachments_dir, mirrored):
    _store_attachment(client, attachments_dir)
    assert client.get(f"/api/components/{SN}/attachments/att-1").status_code == 401


# --- list thumbnails -------------------------------------------------------


def test_thumbnails_index_one_image_per_component(as_operator, attachments_dir, mirrored):
    _store_attachment(as_operator, attachments_dir)
    response = as_operator.get("/api/components/thumbnails")

    assert response.status_code == 200
    assert response.json() == {SN: "att-1"}


def test_thumbnails_skip_files_that_are_not_on_disk(
    as_operator, attachments_dir, mirrored
):
    _store_attachment(as_operator, attachments_dir, stored=False)
    # Every returned entry must be renderable; a missing file would show as a
    # broken image in every row of the list.
    assert as_operator.get("/api/components/thumbnails").json() == {}


def test_thumbnails_skip_non_images(as_operator, attachments_dir, mirrored):
    factory = as_operator.app.state.session_factory
    relative = f"{SN}/att-pdf.pdf"
    target = attachments_dir / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"%PDF-1.4")
    with factory() as session:
        session.add(
            TestRunAttachment(
                component_sn=SN,
                test_type="GLUE_WEIGHT",
                source="pdb",
                pdb_code="att-pdf",
                content_type="application/pdf",
                relative_path=relative,
            )
        )
        session.commit()

    assert as_operator.get("/api/components/thumbnails").json() == {}


def test_thumbnails_need_a_signed_in_user(client):
    assert client.get("/api/components/thumbnails").status_code == 401


def test_thumbnails_route_is_not_shadowed_by_the_serial_route(as_operator):
    """"thumbnails" must not be parsed as a serial number.

    It sits on the same path segment as /api/components/{sn}, so registration
    order is load-bearing.
    """
    response = as_operator.get("/api/components/thumbnails")
    assert response.status_code == 200
    assert isinstance(response.json(), dict)
