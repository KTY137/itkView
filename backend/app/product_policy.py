# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-FileComment: itkflow-b098b5bcf513
"""Server-owned product-variant policy for state-changing HTTP routes.

``itkView`` is a read-only production cockpit, but it still needs a writable
local mirror, account sessions and encrypted read credentials.  HTTP verbs do
not express that distinction: several POST routes only read remote systems and
refresh local cache tables.  Every unsafe API route is therefore classified
explicitly, and an unknown unsafe route is denied by default in the view
variant.
"""

from __future__ import annotations

from enum import Enum

from starlette.responses import JSONResponse
from starlette.routing import compile_path
from starlette.types import ASGIApp, Receive, Scope, Send


class RouteCapability(str, Enum):
    """The kind of local or external side effect an unsafe route performs."""

    CONTROL_PLANE = "control_plane"
    MIRROR_REFRESH = "mirror_refresh"
    WORKFLOW_WRITE = "workflow_write"
    OPERATIONS_WRITE = "operations_write"
    OUTBOUND_NOTIFICATION = "outbound_notification"


UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
VIEW_ALLOWED_CAPABILITIES = frozenset(
    {RouteCapability.CONTROL_PLANE, RouteCapability.MIRROR_REFRESH}
)


# This is deliberately an exhaustive inventory rather than a prefix policy.
# A newly added POST/PUT/PATCH/DELETE route remains unavailable in itkView
# until its side effect has been reviewed and classified here.
ROUTE_CAPABILITIES: dict[tuple[str, str], RouteCapability] = {
    # Authentication, first-run setup and local administration.
    ("POST", "/api/auth/login"): RouteCapability.CONTROL_PLANE,
    ("POST", "/api/auth/logout"): RouteCapability.CONTROL_PLANE,
    ("POST", "/api/setup/admin"): RouteCapability.CONTROL_PLANE,
    ("PUT", "/api/account/pdb-connection"): RouteCapability.CONTROL_PLANE,
    ("POST", "/api/account/pdb-connection/test"): RouteCapability.CONTROL_PLANE,
    ("DELETE", "/api/account/pdb-connection"): RouteCapability.CONTROL_PLANE,
    ("PUT", "/api/account/share-credentials"): RouteCapability.CONTROL_PLANE,
    (
        "DELETE",
        "/api/account/share-credentials/{credential_id}",
    ): RouteCapability.CONTROL_PLANE,
    ("POST", "/api/users"): RouteCapability.CONTROL_PLANE,
    ("PATCH", "/api/users/{user_id}"): RouteCapability.CONTROL_PLANE,
    ("POST", "/api/institutes"): RouteCapability.CONTROL_PLANE,
    ("PATCH", "/api/institutes/{code}"): RouteCapability.CONTROL_PLANE,

    # Remote reads which intentionally refresh the local DB/file mirror.
    (
        "POST",
        "/api/sync/jobs/components/{institute_code}",
    ): RouteCapability.MIRROR_REFRESH,
    (
        "POST",
        "/api/sync/jobs/evidence/{institute_code}",
    ): RouteCapability.MIRROR_REFRESH,
    ("POST", "/api/sync/components/{institute_code}"): RouteCapability.MIRROR_REFRESH,
    ("POST", "/api/sync/tools/{institute_code}"): RouteCapability.MIRROR_REFRESH,
    ("POST", "/api/test-types/sync"): RouteCapability.MIRROR_REFRESH,
    (
        "POST",
        "/api/components/{sn}/attachments/sync",
    ): RouteCapability.MIRROR_REFRESH,
    ("POST", "/api/components/{sn}/sync-evidence"): RouteCapability.MIRROR_REFRESH,
    ("POST", "/api/sync/evidence/{institute_code}"): RouteCapability.MIRROR_REFRESH,
    ("POST", "/api/sync/shipments/{institute_code}"): RouteCapability.MIRROR_REFRESH,

    # Test ingestion, outbox actions and PDB workflow authoring.
    ("POST", "/api/assembly/preview"): RouteCapability.WORKFLOW_WRITE,
    ("POST", "/api/assembly/actions"): RouteCapability.WORKFLOW_WRITE,
    ("POST", "/api/components/register"): RouteCapability.WORKFLOW_WRITE,
    ("POST", "/api/outbox"): RouteCapability.WORKFLOW_WRITE,
    ("POST", "/api/outbox/{action_id}/transition"): RouteCapability.WORKFLOW_WRITE,
    ("POST", "/api/ingest/files"): RouteCapability.WORKFLOW_WRITE,
    (
        "POST",
        "/api/ingest/files/{file_id}/propose-outbox",
    ): RouteCapability.WORKFLOW_WRITE,

    # Locally leading production records and acknowledgements.
    ("POST", "/api/tools"): RouteCapability.OPERATIONS_WRITE,
    ("PATCH", "/api/tools/{tool_id}"): RouteCapability.OPERATIONS_WRITE,
    ("DELETE", "/api/tools/{tool_id}"): RouteCapability.OPERATIONS_WRITE,
    ("POST", "/api/glue-batches"): RouteCapability.OPERATIONS_WRITE,
    ("PATCH", "/api/glue-batches/{batch_id}"): RouteCapability.OPERATIONS_WRITE,
    ("POST", "/api/glue-batches/{batch_id}/mix"): RouteCapability.OPERATIONS_WRITE,
    ("POST", "/api/glue-batches/{batch_id}/usage"): RouteCapability.OPERATIONS_WRITE,
    ("POST", "/api/shipments/{shipment_id}/reception"): RouteCapability.OPERATIONS_WRITE,
    ("POST", "/api/reminders"): RouteCapability.OPERATIONS_WRITE,
    ("PATCH", "/api/reminders/{reminder_id}"): RouteCapability.OPERATIONS_WRITE,
    ("DELETE", "/api/reminders/{reminder_id}"): RouteCapability.OPERATIONS_WRITE,
    (
        "POST",
        "/api/reminder-occurrences/{occurrence_id}/ack",
    ): RouteCapability.OPERATIONS_WRITE,

    # Makes an immediate SMTP/webhook/Telegram request.
    ("POST", "/api/notifications/test"): RouteCapability.OUTBOUND_NOTIFICATION,
}


_REQUEST_MATCHERS = tuple(
    (method, compile_path(path)[0], capability)
    for (method, path), capability in ROUTE_CAPABILITIES.items()
)


def route_capability(method: str, route_path: str) -> RouteCapability | None:
    """Return the reviewed capability for one canonical FastAPI route path."""

    return ROUTE_CAPABILITIES.get((method.upper(), route_path))


def request_capability(method: str, path: str) -> RouteCapability | None:
    """Resolve a concrete request path against the reviewed route templates."""

    normalized_method = method.upper()
    for candidate_method, path_regex, capability in _REQUEST_MATCHERS:
        if candidate_method == normalized_method and path_regex.fullmatch(path):
            return capability
    return None


class ProductVariantPolicyMiddleware:
    """Deny every non-reviewed mutation before request-body parsing in itkView."""

    def __init__(self, app: ASGIApp, *, product_variant: str) -> None:
        self.app = app
        self.product_variant = product_variant

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] == "http"
            and self.product_variant == "view"
            and scope.get("method", "").upper() in UNSAFE_METHODS
        ):
            capability = request_capability(
                scope.get("method", ""), scope.get("path", "")
            )
            if capability not in VIEW_ALLOWED_CAPABILITIES:
                response = JSONResponse(
                    status_code=403,
                    content={
                        "detail": {
                            "code": "itkview_read_only",
                            "message": "This operation is unavailable in itkView.",
                        }
                    },
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


__all__ = [
    "ProductVariantPolicyMiddleware",
    "ROUTE_CAPABILITIES",
    "RouteCapability",
    "UNSAFE_METHODS",
    "VIEW_ALLOWED_CAPABILITIES",
    "request_capability",
    "route_capability",
]
