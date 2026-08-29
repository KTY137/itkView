# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-FileComment: itkflow-04958b1d6f0a
"""Read-only access to a component's image attachments in the PDB.

Metrology plots and visual-inspection photos are stored as attachments on a
component and on its test runs. This module lists their metadata and streams
the binaries. Strictly read-only and only reachable behind the production
opt-in; when the gateway is not configured it returns nothing so the UI simply
shows an empty gallery.

Live validation (2026-08-25) settled the download route: `getTestRunAttachment`
with the attachment code *and its owning test run* returns the file, while
`uu-app-binarystore/getBinaryData` answered with an HTML page. That page is the
right size and arrives with a 200, so it has to be rejected explicitly — served
as an image it just renders as a broken thumbnail.
"""

from typing import Any

_IMAGE_CONTENT_PREFIX = "image/"
# A binary route answering with a document means an error or sign-in page.
_HTML_PREFIXES = (b"<!DOC", b"<!doc", b"<html", b"<HTML", b"<?xml")
_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tif", ".tiff")


def _code(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    if isinstance(value, dict):
        code = value.get("code")
        if isinstance(code, str) and code:
            return code
    return None


def looks_like_html(data: bytes) -> bool:
    return data[:5] in _HTML_PREFIXES


def _content_type_of(response: Any) -> str:
    """itkdb sniffs the real type; fall back to the response headers."""
    for attribute in ("mimetype", "content_type"):
        value = getattr(response, attribute, None)
        if isinstance(value, str) and value:
            return value
    headers = getattr(response, "headers", None)
    if headers is not None:
        value = headers.get("content-type")
        if isinstance(value, str) and value:
            return value
    return "application/octet-stream"


def _iter_attachments(component: dict):
    """Yield (test_type, test_run_ref, attachment) from a getComponent payload,
    tolerant of the exact nesting (component-level, per test, per test run).

    The run reference travels with the attachment because the download route
    needs it; without it only the fallback route is available."""
    for att in component.get("attachments") or []:
        yield None, None, att
    for test in component.get("tests") or []:
        if not isinstance(test, dict):
            continue
        test_type = _code(test.get("testType")) or _code(test.get("code"))
        for att in test.get("attachments") or []:
            yield test_type, None, att
        for run in test.get("testRuns") or []:
            if isinstance(run, dict):
                run_ref = run.get("id") or run.get("code")
                for att in run.get("attachments") or []:
                    yield test_type, (str(run_ref) if run_ref else None), att


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
    for test_type, run_ref, att in _iter_attachments(component):
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
                "test_run_ref": run_ref,
                "filename": att.get("filename"),
                "content_type": att.get("contentType") or att.get("type"),
            }
        )
    return images


def fetch_image_binary(
    gateway: Any, sn: str, attachment_id: str, test_run_ref: str | None = None
) -> tuple[str, bytes] | None:
    """Download one attachment's bytes + content type, or None if unavailable.

    `getTestRunAttachment` is the route that actually returns the file and it
    needs the owning run. The binary store is tried only as a fallback: it has
    been observed answering with an HTML error page, which is why anything it
    returns is checked before being handed on as an image.
    """
    if not getattr(gateway, "is_configured", False):
        return None
    try:
        client = gateway.client()
    except Exception:
        return None

    attempts: list[tuple[str, dict[str, Any]]] = []
    if test_run_ref:
        attempts.append(
            ("getTestRunAttachment", {"code": attachment_id, "testRun": test_run_ref})
        )
    attempts.append(("uu-app-binarystore/getBinaryData", {"code": attachment_id}))

    for action, payload in attempts:
        try:
            response = client.get(action, json=payload)
        except Exception:
            continue
        content = getattr(response, "content", None)
        if not isinstance(content, (bytes, bytearray)) or not content:
            continue
        data = bytes(content)
        if looks_like_html(data):
            # An error page served as an image renders as a broken thumbnail
            # and looks like a bug in the gallery rather than in the fetch.
            continue
        return _content_type_of(response), data
    return None
