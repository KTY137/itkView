"""Read-only access to a component's image attachments in the PDB.

Metrology plots and visual-inspection photos are stored as attachments on a
component and on its test runs. This module lists their metadata and streams
the binaries. Strictly read-only and only reachable behind the production
opt-in; when the gateway is not configured it returns nothing so the UI simply
shows an empty gallery.

The exact itkdb download action (`uu-app-binarystore/getBinaryData`) is isolated
in `fetch_image_binary` so it can be adjusted after a live validation without
touching callers or the API shape.
"""

from typing import Any

_IMAGE_CONTENT_PREFIX = "image/"
_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tif", ".tiff")


def _code(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    if isinstance(value, dict):
        code = value.get("code")
        if isinstance(code, str) and code:
            return code
    return None


def _iter_attachments(component: dict):
    """Yield (test_type, attachment) from a getComponent payload, tolerant of
    the exact nesting (component-level, per test, and per test run)."""
    for att in component.get("attachments") or []:
        yield None, att
    for test in component.get("tests") or []:
        if not isinstance(test, dict):
            continue
        test_type = _code(test.get("testType")) or _code(test.get("code"))
        for att in test.get("attachments") or []:
            yield test_type, att
        for run in test.get("testRuns") or []:
            if isinstance(run, dict):
                for att in run.get("attachments") or []:
                    yield test_type, att


def _is_image(att: dict) -> bool:
    content_type = str(att.get("contentType") or att.get("type") or "")
    filename = str(att.get("filename") or att.get("title") or "").lower()
    return content_type.startswith(_IMAGE_CONTENT_PREFIX) or filename.endswith(_IMAGE_SUFFIXES)


def list_component_images(gateway: Any, sn: str) -> list[dict]:
    """List image attachments for a component. Empty when not configured/reachable."""
    if not getattr(gateway, "is_configured", False):
        return []
    try:
        client = gateway.client()
        component = client.get("getComponent", json={"component": sn})
    except Exception:
        # Read-only best effort: never let a PDB hiccup break the detail page.
        return []
    if not isinstance(component, dict):
        return []

    images: list[dict] = []
    seen: set[str] = set()
    for test_type, att in _iter_attachments(component):
        if not isinstance(att, dict) or not _is_image(att):
            continue
        code = att.get("code") or att.get("id")
        if not code or str(code) in seen:
            continue
        seen.add(str(code))
        images.append(
            {
                "id": str(code),
                "title": att.get("title") or att.get("filename") or "image",
                "test_type": test_type,
                "filename": att.get("filename"),
                "content_type": att.get("contentType") or att.get("type"),
            }
        )
    return images


def fetch_image_binary(gateway: Any, sn: str, attachment_id: str) -> tuple[str, bytes] | None:
    """Download one attachment's bytes + content type, or None if unavailable."""
    if not getattr(gateway, "is_configured", False):
        return None
    try:
        client = gateway.client()
        response = client.get(
            "uu-app-binarystore/getBinaryData", json={"code": attachment_id}
        )
    except Exception:
        return None
    content = getattr(response, "content", None)
    if content is None:
        return None
    content_type = "application/octet-stream"
    headers = getattr(response, "headers", None)
    if headers is not None:
        content_type = headers.get("content-type", content_type) or content_type
    return content_type, bytes(content)
