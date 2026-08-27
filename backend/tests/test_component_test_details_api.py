"""API for mirrored test detail and locally stored attachments.

Covers what the glue-weight, metrology and IV views read, plus the rule that
attachment bytes are served from disk only — never lazily re-fetched behind an
image tag.
"""

import pytest
from authutil import authenticate
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import attachment_store
from app.attachment_store import download_attachments, pending_attachments
from app.config import Settings
from app.main import create_app
from app.models import (
    Component,
    TestRunAttachment,
    TestRunAttachmentReference,
    TestRunEvidence,
)
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

    body = response.json()
    entry = body["attachments"][0]
    assert body["component_sn"] == SN
    assert entry["code"] == "att-1"
    assert entry["stored"] is True
    assert entry["is_image"] is True


def test_a_known_but_unmirrored_attachment_reports_not_stored(
    as_operator, attachments_dir, mirrored
):
    _store_attachment(as_operator, attachments_dir, stored=False)
    entry = as_operator.get(f"/api/components/{SN}/attachments").json()["attachments"][0]
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


def test_source_qualified_identity_keeps_equal_codes_addressable(
    as_operator, attachments_dir, mirrored
):
    """Blob identity is `(source, code)` all the way through the public API."""
    code = "same-code"
    payloads = {
        "pdb": ("pdb.jpg", "image/jpeg", b"pdb-bytes"),
        "share_link": ("share.jpg", "image/jpeg", b"share-bytes"),
    }
    with as_operator.app.state.session_factory() as session:
        for source, (filename, content_type, payload) in payloads.items():
            relative_path = f"{SN}/{source}/{code}.jpg"
            target = attachments_dir / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            blob = TestRunAttachment(
                component_sn=SN,
                test_type="VISUAL_INSPECTION",
                test_run_ref=f"RUN-{source}",
                source=source,
                pdb_code=code,
                filename=filename,
                content_type=content_type,
                size_bytes=len(payload),
                relative_path=relative_path,
            )
            session.add(blob)
            session.flush()
            session.add(
                TestRunAttachmentReference(
                    attachment_id=blob.id,
                    component_sn=SN,
                    test_type="VISUAL_INSPECTION",
                    test_run_ref=f"RUN-{source}",
                    filename=filename,
                )
            )
        session.commit()

    gallery = as_operator.get(f"/api/components/{SN}/attachments").json()
    assert {
        (attachment["source"], attachment["code"], attachment["filename"])
        for attachment in gallery["attachments"]
        if attachment["code"] == code
    } == {
        ("pdb", code, "pdb.jpg"),
        ("share_link", code, "share.jpg"),
    }

    for source, (_, _, payload) in payloads.items():
        response = as_operator.get(
            f"/api/components/{SN}/attachments/{code}?source={source}"
        )
        assert response.status_code == 200
        assert response.content == payload

    # Old bookmarks without `source` remain deterministic and usable.
    legacy = as_operator.get(f"/api/components/{SN}/attachments/{code}")
    assert legacy.status_code == 200
    assert legacy.content == payloads["pdb"][2]
    assert (
        as_operator.get(
            f"/api/components/{SN}/attachments/{code}?source=not-a-source"
        ).status_code
        == 404
    )

    # The thumbnail locator names the exact blob selected by MIN(id), so its
    # binary request cannot fall through to the other source.
    thumbnail = as_operator.get("/api/components/thumbnails").json()[SN]
    assert thumbnail == {"source": "pdb", "code": code}
    exact_thumbnail = as_operator.get(
        f"/api/components/{SN}/attachments/{thumbnail['code']}"
        f"?source={thumbnail['source']}"
    )
    assert exact_thumbnail.content == payloads["pdb"][2]


def test_attachment_bytes_need_a_signed_in_user(client, attachments_dir, mirrored):
    _store_attachment(client, attachments_dir)
    assert client.get(f"/api/components/{SN}/attachments/att-1").status_code == 401


# --- list thumbnails -------------------------------------------------------


def test_thumbnails_index_one_image_per_component(as_operator, attachments_dir, mirrored):
    _store_attachment(as_operator, attachments_dir)
    response = as_operator.get("/api/components/thumbnails")

    assert response.status_code == 200
    assert response.json() == {SN: {"source": "pdb", "code": "att-1"}}


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
    """ "thumbnails" must not be parsed as a serial number.

    It sits on the same path segment as /api/components/{sn}, so registration
    order is load-bearing.
    """
    response = as_operator.get("/api/components/thumbnails")
    assert response.status_code == 200
    assert isinstance(response.json(), dict)


def test_one_blob_stays_visible_on_every_component_and_run_that_references_it(
    as_operator, attachments_dir, monkeypatch
):
    """Blob identity is not association identity.

    One folder-share URL is repeated by several Powerboards (and sometimes by
    several runs on one board). The bytes must be fetched and stored once, but
    every component gallery, binary route and owning run must retain its own
    association. Re-syncing in a different component order must be idempotent.
    """
    factory = as_operator.app.state.session_factory
    parent_sn = "20USEM20000999"
    component_sns = ["20USEP00000001", "20USEP00000002", "20USEP00000003"]
    shared_code = "shared-folder-image"
    shared_url = "https://cernbox.cern.ch/files/link/public/token/folder"
    runs_by_component = {
        component_sns[0]: ["RUN-SHARED-A1", "RUN-SHARED-A2"],
        component_sns[1]: ["RUN-SHARED-B"],
        component_sns[2]: ["RUN-SHARED-C"],
    }

    with factory() as session:
        parent = Component(
            sn=parent_sn,
            component_type="MODULE",
            type_code="R5M0",
            stage="GLUED",
            location="TUDO",
            institute_code="TUDO",
        )
        session.add(parent)
        session.flush()
        for index, component_sn in enumerate(component_sns):
            session.add(
                Component(
                    sn=component_sn,
                    component_type="PWB",
                    type_code="PBR5",
                    stage="READY",
                    location="TUDO",
                    institute_code="TUDO",
                    parent=parent if index == 2 else None,
                )
            )
            for run_ref in runs_by_component[component_sn]:
                session.add(
                    TestRunEvidence(
                        component_sn=component_sn,
                        test_type="VISUAL_INSPECTION",
                        passed=True,
                        source="pdb",
                        external_ref=run_ref,
                        payload={
                            "attachments": [
                                {
                                    "source": "share_link",
                                    "type": "share_link",
                                    "code": shared_code,
                                    "url": shared_url,
                                    "filename": "folder",
                                    "content_type": None,
                                    "title": "Inspection picture",
                                }
                            ]
                        },
                    )
                )
        session.commit()

    fetches: list[str] = []

    def _fetch_once(client, descriptor, *, timeout, max_bytes):  # noqa: ARG001
        fetches.append(descriptor["code"])
        return JPEG, "image/jpeg"

    monkeypatch.setattr(attachment_store, "_fetch_bytes", _fetch_once)

    class _NoPdbGateway:
        is_configured = False

    def _sweep(order):
        with factory() as session:
            for component_sn in order:
                stats = download_attachments(
                    session,
                    _NoPdbGateway(),
                    as_operator.app.state.settings,
                    component_sn,
                    descriptors=pending_attachments(session, component_sn),
                )
                assert stats.failed == 0
                session.commit()

    _sweep(component_sns)
    _sweep(list(reversed(component_sns)))

    assert fetches == [shared_code]
    stored_files = [path for path in attachments_dir.rglob("*") if path.is_file()]
    assert len(stored_files) == 1
    assert stored_files[0].read_bytes() == JPEG

    with factory() as session:
        assert session.scalar(select(func.count()).select_from(TestRunAttachment)) == 1
        assert session.scalar(select(func.count()).select_from(TestRunAttachmentReference)) == 4
        blob = session.scalar(select(TestRunAttachment))
        assert blob.component_sn == component_sns[0]
        assert blob.test_run_ref == "RUN-SHARED-A1"
        assert sorted(session.scalars(select(TestRunAttachmentReference.test_run_ref))) == sorted(
            run for runs in runs_by_component.values() for run in runs
        )

    for component_sn, run_refs in runs_by_component.items():
        gallery = as_operator.get(f"/api/components/{component_sn}/attachments").json()
        assert [item["code"] for item in gallery["attachments"]] == [shared_code]
        assert gallery["attachments"][0]["stored"] is True

        response = as_operator.get(f"/api/components/{component_sn}/attachments/{shared_code}")
        assert response.status_code == 200
        assert response.content == JPEG

        runs = as_operator.get(f"/api/components/{component_sn}/tests").json()
        by_ref = {run["external_ref"]: run for run in runs}
        for run_ref in run_refs:
            assert [item["code"] for item in by_ref[run_ref]["attachments"]] == [shared_code]

        preview = as_operator.get(f"/api/components/{component_sn}/preview").json()
        worksheet_rows = [row for group in preview["worksheet"]["groups"] for row in group["rows"]]
        visual_row = next(row for row in worksheet_rows if row["test_type"] == "VISUAL_INSPECTION")
        # The physical blob is shared, but the latest run on each component
        # still owns one association and therefore reports one attachment.
        assert visual_row["latest"]["attachment_count"] == 1

    thumbnails = as_operator.get("/api/components/thumbnails").json()
    assert {sn: thumbnails[sn] for sn in component_sns} == {
        sn: {"source": "share_link", "code": shared_code}
        for sn in component_sns
    }
    family = as_operator.get(f"/api/components/{parent_sn}/attachments").json()
    assert [child["sn"] for child in family["children"]] == [component_sns[2]]
    assert family["children"][0]["attachments"][0]["code"] == shared_code
    parent_preview = as_operator.get(f"/api/components/{parent_sn}/preview").json()
    child = next(
        child
        for child in parent_preview["worksheet"]["children"]
        if child["sn"] == component_sns[2]
    )
    child_visual = next(row for row in child["rows"] if row["test_type"] == "VISUAL_INSPECTION")
    assert child_visual["latest"]["attachment_count"] == 1
