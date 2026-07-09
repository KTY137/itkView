from fastapi.testclient import TestClient

from app.pdb_attachments import fetch_image_binary, list_component_images

COMPONENT = {
    "serialNumber": "20USEM00000001",
    "attachments": [
        {"code": "A1", "title": "photo", "filename": "front.png", "contentType": "image/png"},
        {"code": "D1", "filename": "notes.txt", "contentType": "text/plain"},  # not an image
    ],
    "tests": [
        {
            "testType": {"code": "MODULE_METROLOGY"},
            "attachments": [{"code": "M1", "filename": "metro.jpg", "contentType": "image/jpeg"}],
        },
        {
            "testType": "VISUAL_INSPECTION",
            "testRuns": [
                {"attachments": [{"code": "V1", "title": "vi", "filename": "vi.png",
                                  "contentType": "image/png"}]}
            ],
        },
    ],
}


class _FakeResponse:
    def __init__(self, content: bytes, content_type: str) -> None:
        self.content = content
        self.headers = {"content-type": content_type}


class _FakeClient:
    def __init__(self, component=None, binary=None) -> None:
        self._component = component
        self._binary = binary

    def get(self, action, json=None):
        if action == "getComponent":
            return self._component
        if action.endswith("getBinaryData"):
            return self._binary
        raise AssertionError(f"unexpected action {action}")


class _FakeGateway:
    def __init__(self, configured=True, component=None, binary=None) -> None:
        self.is_configured = configured
        self._client = _FakeClient(component, binary)

    def client(self):
        return self._client


def test_list_images_filters_and_maps_attachments():
    images = list_component_images(_FakeGateway(component=COMPONENT), "20USEM00000001")
    by_id = {img["id"]: img for img in images}
    assert set(by_id) == {"A1", "M1", "V1"}  # D1 (text) excluded
    assert by_id["M1"]["test_type"] == "MODULE_METROLOGY"
    assert by_id["V1"]["test_type"] == "VISUAL_INSPECTION"
    assert by_id["A1"]["test_type"] is None


def test_list_images_empty_when_not_configured():
    assert list_component_images(_FakeGateway(configured=False, component=COMPONENT), "X") == []


def test_list_images_tolerates_pdb_errors():
    class Boom(_FakeGateway):
        def client(self):
            raise RuntimeError("pdb down")

    assert list_component_images(Boom(), "X") == []


def test_fetch_binary_returns_bytes_and_type():
    gw = _FakeGateway(binary=_FakeResponse(b"PNGDATA", "image/png"))
    result = fetch_image_binary(gw, "SN", "M1")
    assert result == ("image/png", b"PNGDATA")


def test_fetch_binary_none_when_not_configured():
    assert fetch_image_binary(_FakeGateway(configured=False), "SN", "M1") is None


def test_images_endpoint_empty_without_pdb(client: TestClient):
    # Test settings have no access codes -> gateway inert -> graceful empty list.
    assert client.get("/api/components/20USEM00000001/images").json() == []


def test_images_endpoint_with_injected_gateway(client: TestClient):
    client.app.state.pdb_gateway = _FakeGateway(component=COMPONENT)
    body = client.get("/api/components/20USEM00000001/images").json()
    assert {img["id"] for img in body} == {"A1", "M1", "V1"}


def test_image_binary_endpoint_streams(client: TestClient):
    client.app.state.pdb_gateway = _FakeGateway(binary=_FakeResponse(b"PNGDATA", "image/png"))
    resp = client.get("/api/components/SN/images/M1")
    assert resp.status_code == 200
    assert resp.content == b"PNGDATA"
    assert resp.headers["content-type"].startswith("image/png")


def test_image_binary_endpoint_404_when_missing(client: TestClient):
    resp = client.get("/api/components/SN/images/NOPE")
    assert resp.status_code == 404
