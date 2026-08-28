"""Which mirrored images an operator can actually see.

Two defects measured against the owner's live mirror sit behind this file:

* the list thumbnail endpoint capped *attachment rows*, and the mirror's rows
  are overwhelmingly instrument `.txt` output — 3734 rows for 759 serials, so
  the first 2000 rows reached 460 serials and produced 83 tiles where 279
  components have a picture;
* the component gallery filtered by serial number alone, while 241 of the 432
  mirrored images hang on sensors that are a module's direct child and only 3
  on modules themselves.

Both groups of tests assert the *shape* of the answer (bounded by components,
tagged by owner) rather than a fixed number, so they keep meaning what they say.
"""

import pytest
from authutil import authenticate
from fastapi.testclient import TestClient
from sqlalchemy import event

from app.config import Settings
from app.main import create_app
from app.models import Component, TestRunAttachment, TestRunAttachmentReference
from app.pdb_credentials import generate_pdb_credential_encryption_key

JPEG = b"\xff\xd8\xff\xe0itkflow"
MODULE_SN = "20USEM20000041"


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


def _component(session, sn, component_type="MODULE", type_code="R5M0", parent=None):
    component = Component(
        sn=sn,
        component_type=component_type,
        type_code=type_code,
        stage="GLUED",
        location="TUDO",
        institute_code="TUDO",
        local_name=f"TUDO-{sn[-4:]}",
        parent=parent,
    )
    session.add(component)
    return component


def _attachment(session, attachments_dir, sn, code, *, content_type, suffix, on_disk=True):
    relative = f"{sn}/{code}{suffix}"
    if on_disk:
        target = attachments_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(JPEG)
    attachment = TestRunAttachment(
        component_sn=sn,
        test_type="VISUAL_INSPECTION",
        test_run_ref=f"RUN-{code}",
        source="pdb",
        pdb_code=code,
        filename=f"picture{suffix}",
        content_type=content_type,
        size_bytes=len(JPEG),
        relative_path=relative,
    )
    session.add(attachment)
    return attachment


def _image(session, attachments_dir, sn, code, on_disk=True):
    _attachment(
        session,
        attachments_dir,
        sn,
        code,
        content_type="image/jpeg",
        suffix=".jpg",
        on_disk=on_disk,
    )


def _instrument_data(session, attachments_dir, sn, code):
    _attachment(
        session, attachments_dir, sn, code, content_type="text/plain", suffix=".txt"
    )


# --- list thumbnails: the cap must bound components ------------------------


def _mirror_with_text_heavy_components(session_factory, attachments_dir, count):
    """Every component carries one picture behind several instrument files.

    That is the real mirror's proportion (2671 of 3734 rows are `.txt`), and it
    is what turned a row cap into a component cap a quarter of its size.
    """
    with session_factory() as session:
        for index in range(count):
            sn = f"20USES4000{index:04d}"
            _component(session, sn, component_type="SENSOR", type_code="ATLAS18R5")
            for run in range(5):
                _instrument_data(session, attachments_dir, sn, f"data-{index}-{run}")
            _image(session, attachments_dir, sn, f"photo-{index}")
        session.commit()


def test_the_thumbnail_limit_bounds_components_not_attachment_rows(
    as_operator, attachments_dir
):
    """Six rows per component, one of them the picture: a row cap of 4 reached
    a single component. The caller asked for a list of components."""
    _mirror_with_text_heavy_components(
        as_operator.app.state.session_factory, attachments_dir, count=4
    )

    response = as_operator.get("/api/components/thumbnails?limit=4")

    assert response.status_code == 200
    thumbnails = response.json()
    assert len(thumbnails) == 4, thumbnails
    assert sorted(thumbnails) == [f"20USES4000{index:04d}" for index in range(4)]
    assert sorted(locator["code"] for locator in thumbnails.values()) == [
        f"photo-{index}" for index in range(4)
    ]
    assert {locator["source"] for locator in thumbnails.values()} == {"pdb"}


def test_a_smaller_limit_returns_fewer_components_not_fewer_rows(
    as_operator, attachments_dir
):
    _mirror_with_text_heavy_components(
        as_operator.app.state.session_factory, attachments_dir, count=4
    )

    assert len(as_operator.get("/api/components/thumbnails?limit=2").json()) == 2


def test_a_component_with_only_instrument_data_yields_no_thumbnail(
    as_operator, attachments_dir
):
    """And it must not consume the slot of a component that does have one."""
    with as_operator.app.state.session_factory() as session:
        _component(session, "20USES40009001", component_type="SENSOR")
        _component(session, "20USES40009002", component_type="SENSOR")
        for run in range(3):
            _instrument_data(session, attachments_dir, "20USES40009001", f"iv-{run}")
        _image(session, attachments_dir, "20USES40009002", "photo-9002")
        session.commit()

    thumbnails = as_operator.get("/api/components/thumbnails?limit=1").json()

    assert thumbnails == {
        "20USES40009002": {
            "source": "pdb",
            "code": "photo-9002",
            "sn": "20USES40009002",
            "part": None,
        }
    }


def test_a_module_row_borrows_the_picture_of_a_part_and_says_whose_it_is(
    as_operator, attachments_dir
):
    """Almost no photograph is taken of a module: 3 of 432 on the owner's
    mirror, the rest of its parts. A list column filtered by serial alone is
    therefore empty on nearly every module row while the pictures exist.

    The row borrows a part's picture rather than staying blank, but never
    silently: `sn` names the component whose mirror holds the bytes, and `part`
    names whose part is in the picture, so the tile can be marked. Without that
    marking a sensor's photograph would read as a photograph of the module.
    """
    factory = as_operator.app.state.session_factory
    with factory() as session:
        module = _component(session, MODULE_SN)
        sensor = _component(
            session,
            f"{MODULE_SN}C0",
            component_type="SENSOR",
            type_code="ATLAS18R5",
            parent=module,
        )
        sensor.local_name = "TUDO-S-0042"
        _image(session, attachments_dir, sensor.sn, "sensorphoto")
        session.commit()

    thumbnails = as_operator.get("/api/components/thumbnails").json()

    assert thumbnails[MODULE_SN] == {
        "source": "pdb",
        "code": "sensorphoto",
        "sn": f"{MODULE_SN}C0",
        "part": {
            "sn": f"{MODULE_SN}C0",
            "component_type": "SENSOR",
            "type_code": "ATLAS18R5",
            "local_name": "TUDO-S-0042",
        },
    }
    # The part keeps its own unmarked tile: the picture is its own there.
    assert thumbnails[f"{MODULE_SN}C0"]["part"] is None


def test_a_components_own_picture_outranks_a_parts_picture(
    as_operator, attachments_dir
):
    factory = as_operator.app.state.session_factory
    with factory() as session:
        module = _component(session, MODULE_SN)
        sensor = _component(
            session,
            f"{MODULE_SN}C0",
            component_type="SENSOR",
            type_code="ATLAS18R5",
            parent=module,
        )
        _image(session, attachments_dir, sensor.sn, "sensorphoto")
        _image(session, attachments_dir, module.sn, "ownphoto")
        session.commit()

    thumbnails = as_operator.get("/api/components/thumbnails").json()

    assert thumbnails[MODULE_SN]["code"] == "ownphoto"
    assert thumbnails[MODULE_SN]["sn"] == MODULE_SN
    assert thumbnails[MODULE_SN]["part"] is None


def test_a_stitched_module_row_borrows_through_its_half_module(
    as_operator, attachments_dir
):
    """Same stitch as the gallery: for R3-R5 the parts hang under a half
    module, so a one-hop borrow would leave the full module's row blank."""
    factory = as_operator.app.state.session_factory
    with factory() as session:
        stitched = _component(session, MODULE_SN, type_code="R5")
        half = _component(
            session,
            f"{MODULE_SN}H0",
            component_type="MODULE",
            type_code="R5M0",
            parent=stitched,
        )
        sensor = _component(
            session,
            f"{MODULE_SN}S0",
            component_type="SENSOR",
            type_code="ATLAS18R5",
            parent=half,
        )
        _image(session, attachments_dir, sensor.sn, "deepphoto")
        session.commit()

    thumbnails = as_operator.get("/api/components/thumbnails").json()

    assert thumbnails[MODULE_SN]["code"] == "deepphoto"
    assert thumbnails[MODULE_SN]["part"]["sn"] == f"{MODULE_SN}S0"
    assert thumbnails[f"{MODULE_SN}H0"]["part"]["sn"] == f"{MODULE_SN}S0"


def test_thumbnails_still_skip_an_image_whose_file_is_gone(as_operator, attachments_dir):
    with as_operator.app.state.session_factory() as session:
        _component(session, "20USES40009003", component_type="SENSOR")
        _image(session, attachments_dir, "20USES40009003", "photo-gone", on_disk=False)
        session.commit()

    assert as_operator.get("/api/components/thumbnails").json() == {}


def test_thumbnails_choose_browser_displayable_images_for_legacy_and_associations(
    as_operator, attachments_dir
):
    """An older TIFF cannot hide a later JPEG or become a broken list tile."""
    legacy_mixed = "20USES40009011"
    legacy_tiff_only = "20USES40009012"
    referenced_mixed = "20USES40009013"
    referenced_tiff_only = "20USES40009014"
    with as_operator.app.state.session_factory() as session:
        for sn in (
            legacy_mixed,
            legacy_tiff_only,
            referenced_mixed,
            referenced_tiff_only,
        ):
            _component(session, sn, component_type="SENSOR")

        _attachment(
            session,
            attachments_dir,
            legacy_mixed,
            "legacy-older-tiff",
            content_type="image/tiff; charset=binary",
            suffix=".tiff",
        )
        session.flush()
        _attachment(
            session,
            attachments_dir,
            legacy_mixed,
            "legacy-newer-jpeg",
            content_type="IMAGE/JPEG; charset=binary",
            suffix=".jpg",
        )
        _attachment(
            session,
            attachments_dir,
            legacy_tiff_only,
            "legacy-only-tiff",
            content_type="IMAGE/TIFF; charset=binary",
            suffix=".tiff",
        )

        for target_sn, owner_sn, code, content_type, suffix in (
            (
                referenced_mixed,
                "BLOBOWNER0000000001",
                "reference-older-tiff",
                "image/tiff; charset=binary",
                ".tiff",
            ),
            (
                referenced_mixed,
                "BLOBOWNER0000000002",
                "reference-newer-jpeg",
                "IMAGE/JPEG; charset=binary",
                ".jpg",
            ),
            (
                referenced_tiff_only,
                "BLOBOWNER0000000003",
                "reference-only-tiff",
                "image/tiff; charset=binary",
                ".tiff",
            ),
        ):
            attachment = _attachment(
                session,
                attachments_dir,
                owner_sn,
                code,
                content_type=content_type,
                suffix=suffix,
            )
            session.flush()
            session.add(
                TestRunAttachmentReference(
                    attachment_id=attachment.id,
                    component_sn=target_sn,
                    test_type="VISUAL_INSPECTION",
                    test_run_ref=f"RUN-{code}",
                    filename=attachment.filename,
                )
            )
        session.commit()

    thumbnails = as_operator.get(
        "/api/components/thumbnails?institute_code=TUDO"
    ).json()

    assert thumbnails == {
        legacy_mixed: {
            "source": "pdb",
            "code": "legacy-newer-jpeg",
            "sn": legacy_mixed,
            "part": None,
        },
        referenced_mixed: {
            "source": "pdb",
            "code": "reference-newer-jpeg",
            "sn": referenced_mixed,
            "part": None,
        },
    }


def test_thumbnail_mime_normalization_matches_the_browser(
    as_operator, attachments_dir
):
    """Whitespace around the MIME base type cannot hide a paintable image."""
    legacy_sn = "20USES40009015"
    referenced_sn = "20USES40009016"
    with as_operator.app.state.session_factory() as session:
        for sn in (legacy_sn, referenced_sn):
            _component(session, sn, component_type="SENSOR")

        _attachment(
            session,
            attachments_dir,
            legacy_sn,
            "legacy-spaced-jpeg",
            content_type="\t  IMAGE/JPEG \t; charset=binary",
            suffix=".jpg",
        )
        referenced = _attachment(
            session,
            attachments_dir,
            "BLOBOWNER0000000004",
            "reference-spaced-jpeg",
            content_type="\tIMAGE/JPEG ;charset=binary",
            suffix=".jpg",
        )
        session.flush()
        session.add(
            TestRunAttachmentReference(
                attachment_id=referenced.id,
                component_sn=referenced_sn,
                test_type="VISUAL_INSPECTION",
                test_run_ref="RUN-reference-spaced-jpeg",
                filename=referenced.filename,
            )
        )
        session.commit()

    thumbnails = as_operator.get("/api/components/thumbnails").json()

    assert thumbnails[legacy_sn] == {
        "source": "pdb",
        "code": "legacy-spaced-jpeg",
        "sn": legacy_sn,
        "part": None,
    }
    assert thumbnails[referenced_sn] == {
        "source": "pdb",
        "code": "reference-spaced-jpeg",
        "sn": referenced_sn,
        "part": None,
    }


# --- the gallery: a module page shows the parts it is made of --------------


def _module_with_children(session_factory, attachments_dir, *, parent_sn, child_count):
    with session_factory() as session:
        module = _component(session, parent_sn)
        for index in range(child_count):
            child = _component(
                session,
                f"{parent_sn}C{index}",
                component_type="SENSOR",
                type_code="ATLAS18R5",
                parent=module,
            )
            _image(session, attachments_dir, child.sn, f"childphoto-{parent_sn}-{index}")
            _instrument_data(
                session, attachments_dir, child.sn, f"childiv-{parent_sn}-{index}"
            )
        session.commit()


def test_a_module_gallery_carries_its_childrens_images_tagged_by_child(
    as_operator, attachments_dir
):
    factory = as_operator.app.state.session_factory
    _module_with_children(factory, attachments_dir, parent_sn=MODULE_SN, child_count=2)
    with factory() as session:
        _image(session, attachments_dir, MODULE_SN, "ownphoto")
        session.commit()

    body = as_operator.get(f"/api/components/{MODULE_SN}/attachments").json()

    # The module's own images stay its own, and stay distinguishable.
    assert body["component_sn"] == MODULE_SN
    assert [a["code"] for a in body["attachments"]] == ["ownphoto"]
    # Each child's picture arrives labelled with whose picture it is.
    assert [group["sn"] for group in body["children"]] == [
        f"{MODULE_SN}C0",
        f"{MODULE_SN}C1",
    ]
    assert all(group["component_type"] == "SENSOR" for group in body["children"])
    assert [[a["code"] for a in group["attachments"]] for group in body["children"]] == [
        [f"childphoto-{MODULE_SN}-0"],
        [f"childphoto-{MODULE_SN}-1"],
    ]
    assert all(
        attachment["stored"] and attachment["is_image"]
        for group in body["children"]
        for attachment in group["attachments"]
    )


def test_a_stitched_module_gallery_reaches_through_its_half_modules(
    as_operator, attachments_dir
):
    """R3-R5 modules are stitched, so their parts hang one hop further down.

    A full stitched module's direct child is a half module, and the sensors,
    powerboard and hybrid assemblies carrying the photographs are that half
    module's children. Stopping at one hop is right for an unstitched module
    but leaves every stitched module page empty while its pictures exist: on
    the owner's mirror that silenced 22 modules whose only images sit at
    `MODULE > MODULE > SENSOR|PWB|HYBRID_ASSEMBLY`. The extra hop is taken
    only through a child that is itself a module, so no unrelated
    grandchildren are pulled into the gallery.
    """
    factory = as_operator.app.state.session_factory
    with factory() as session:
        stitched = _component(session, MODULE_SN, type_code="R5")
        half = _component(
            session,
            f"{MODULE_SN}H0",
            component_type="MODULE",
            type_code="R5M0",
            parent=stitched,
        )
        sensor = _component(
            session,
            f"{MODULE_SN}S0",
            component_type="SENSOR",
            type_code="ATLAS18R5",
            parent=half,
        )
        # A sensor hanging off the half module's own child must not be pulled
        # in: the extra hop follows the stitch, it does not walk the tree.
        deeper = _component(
            session,
            f"{MODULE_SN}S1",
            component_type="SENSOR",
            type_code="ATLAS18R5",
            parent=sensor,
        )
        _image(session, attachments_dir, half.sn, "halfphoto")
        _image(session, attachments_dir, sensor.sn, "sensorphoto")
        _image(session, attachments_dir, deeper.sn, "toodeep")
        session.commit()

    body = as_operator.get(f"/api/components/{MODULE_SN}/attachments").json()

    groups = {group["sn"]: group for group in body["children"]}
    assert [a["code"] for a in groups[f"{MODULE_SN}H0"]["attachments"]] == ["halfphoto"]
    assert [a["code"] for a in groups[f"{MODULE_SN}S0"]["attachments"]] == ["sensorphoto"]
    assert groups[f"{MODULE_SN}S0"]["component_type"] == "SENSOR"
    assert f"{MODULE_SN}S1" not in groups


def test_child_gallery_normalizes_image_mime_case_and_parameters(
    as_operator, attachments_dir
):
    factory = as_operator.app.state.session_factory
    with factory() as session:
        module = _component(session, MODULE_SN)
        child = _component(
            session,
            f"{MODULE_SN}C0",
            component_type="SENSOR",
            type_code="ATLAS18R5",
            parent=module,
        )
        _attachment(
            session,
            attachments_dir,
            child.sn,
            "childphoto-normalized-mime",
            content_type="\t  IMAGE/JPEG \t; charset=binary",
            suffix=".jpg",
        )
        session.commit()

    body = as_operator.get(f"/api/components/{MODULE_SN}/attachments").json()

    assert [[item["code"] for item in group["attachments"]] for group in body["children"]] == [
        ["childphoto-normalized-mime"]
    ]
    assert body["children"][0]["attachments"][0]["is_image"] is True


def test_a_childs_instrument_data_is_not_dragged_onto_the_parents_page(
    as_operator, attachments_dir
):
    """The gallery is the only reason the children are here. A sensor's several
    hundred `.txt` rows would cost far more than they show."""
    _module_with_children(
        as_operator.app.state.session_factory,
        attachments_dir,
        parent_sn=MODULE_SN,
        child_count=1,
    )

    body = as_operator.get(f"/api/components/{MODULE_SN}/attachments").json()

    codes = [a["code"] for group in body["children"] for a in group["attachments"]]
    assert codes == [f"childphoto-{MODULE_SN}-0"]


def test_a_childs_image_does_not_appear_under_the_parents_test_runs(
    as_operator, attachments_dir
):
    """A run belongs to exactly one component; only the gallery reaches wider."""
    _module_with_children(
        as_operator.app.state.session_factory,
        attachments_dir,
        parent_sn=MODULE_SN,
        child_count=1,
    )

    runs = as_operator.get(f"/api/components/{MODULE_SN}/tests").json()

    assert all(run["attachments"] == [] for run in runs)


def _attachment_query_count(as_operator, attachments_dir, *, parent_sn, child_count):
    factory = as_operator.app.state.session_factory
    _module_with_children(
        factory, attachments_dir, parent_sn=parent_sn, child_count=child_count
    )
    statements: list[str] = []

    def _record(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
        statements.append(statement)

    with factory() as session:
        engine = session.get_bind()
    event.listen(engine, "before_cursor_execute", _record)
    try:
        body = as_operator.get(f"/api/components/{parent_sn}/attachments").json()
    finally:
        event.remove(engine, "before_cursor_execute", _record)

    assert len(body["children"]) == child_count
    return len([s for s in statements if "test_run_attachment" in s])


def test_the_child_gallery_costs_the_same_for_one_child_and_for_many(
    as_operator, attachments_dir
):
    """One extra query for the whole family, never one per child — the same
    invariant the worksheet's child evidence pass is held to."""
    one = _attachment_query_count(
        as_operator, attachments_dir, parent_sn="20USEM20000801", child_count=1
    )
    many = _attachment_query_count(
        as_operator, attachments_dir, parent_sn="20USEM20000802", child_count=6
    )

    assert one == many, (one, many)


def test_a_module_without_children_reports_an_empty_family(as_operator, attachments_dir):
    with as_operator.app.state.session_factory() as session:
        _component(session, "20USEM20000803")
        session.commit()

    body = as_operator.get("/api/components/20USEM20000803/attachments").json()

    assert body == {
        "component_sn": "20USEM20000803",
        "attachments": [],
        "children": [],
    }
