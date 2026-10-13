"""Endpoints serving MCP App views to the chat frontend.

The authenticated endpoint returns approved HTML as inert JSON plus a signed
URL for a trusted proxy on the dedicated content origin. The official SDK
sends that HTML to the proxy, which places it in an opaque srcdoc child. The
proxy's HTTP CSP constrains both resource access and child navigation.
"""

import time
from typing import TYPE_CHECKING, Annotated, cast
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse

from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.authentication.endpoint_access import (
    Authentication,
    Authorization,
    authenticates,
    endpoint_access,
)
from eneo.authentication.signed_urls import (
    generate_mcp_app_view_token,
    verify_mcp_app_view_token,
)
from eneo.main.config import get_settings
from eneo.main.container.container import Container
from eneo.main.exceptions import NotFoundException
from eneo.mcp_apps.domain.csp import build_app_csp
from eneo.mcp_apps.infrastructure.repo_impl.mcp_app_view_repo_impl import (
    McpAppViewRepo,
)
from eneo.mcp_apps.presentation.models import McpAppViewTokenResponse
from eneo.mcp_apps.presentation.sandbox import sandbox_document
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


@router.post(
    "/views/{view_id}/token/",
    response_model=McpAppViewTokenResponse,
    status_code=200,
    summary="Get approved MCP App HTML and a signed sandbox URL",
    description=(
        "Checks the view belongs to the caller's tenant, then returns "
        "approved HTML and a short-lived sandbox URL on the content origin. 424 when no "
        "content origin is configured."
    ),
    responses=responses.get_responses([404, 424]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason="A link is minted only for a view cached for the caller's tenant.",
)
async def mint_app_view_token(
    view_id: UUID,
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> McpAppViewTokenResponse:
    settings = get_settings()
    if not settings.mcp_apps_enabled:
        raise NotFoundException("MCP apps are not enabled")

    current_user = container.user()
    session = cast("AsyncSession", container.session())
    # Only a view approved for a tool of an enabled server gets a link: one
    # stored for review, or left behind by a tool that changed, does not.
    view = await McpAppViewRepo(session).get_for_tenant(
        view_id, current_user.tenant_id, approved_only=True
    )
    if view is None:
        raise NotFoundException("MCP app view not found")

    content_base = settings.mcp_app_content_base_url
    if not content_base:
        raise HTTPException(
            status_code=424,
            detail=(
                "MCP app views cannot render: MCP_APP_CONTENT_BASE_URL is not "
                "configured. An administrator must point it at a dedicated "
                "content origin."
            ),
        )

    expires_at = int(time.time()) + settings.mcp_app_view_token_expiry_seconds
    token = generate_mcp_app_view_token(
        view_id=view_id,
        tenant_id=current_user.tenant_id,
        expires_at=expires_at,
    )
    await container.audit_service().log_async(
        tenant_id=current_user.tenant_id,
        user=current_user,
        action=ActionType.MCP_APP_VIEW_LINK_CREATED,
        entity_type=EntityType.MCP_SERVER,
        entity_id=view.mcp_server_id,
        description=f"Created an MCP app view link for '{view.uri}'",
        metadata=AuditMetadata.standard(
            actor=current_user,
            target=view,
            extra={
                "view_id": str(view_id),
                "view_uri": view.uri,
                "expires_at": expires_at,
            },
        ),
    )
    url = (
        f"{content_base.rstrip('/')}/api/v1/mcp-apps/views/{view_id}/content"
        f"?token={token}"
    )
    return McpAppViewTokenResponse(url=url, expires_at=expires_at, html=view.html)


def _on_content_origin(request: Request) -> bool:
    """Whether the request came in on the host views are served from."""
    content_base = get_settings().mcp_app_content_base_url
    if not content_base:
        return False
    requested = request.headers.get("host", "").strip().lower()
    return requested != "" and requested == urlsplit(content_base).netloc.lower()


@authenticates(Authentication.SIGNED_URL)
def authorize_signed_app_view(
    view_id: UUID,
    token: Annotated[str, Query(description="The signed app-view token")],
) -> UUID:
    """The tenant whose view the token grants, when it names this view."""
    payload = verify_mcp_app_view_token(token)
    if payload is None or payload.get("view_id") != str(view_id):
        raise NotFoundException("MCP app view not found")
    return UUID(str(payload["tenant_id"]))


@router.get(
    "/views/{view_id}/content",
    response_class=HTMLResponse,
    response_model=None,
    description="Serve the isolated MCP App sandbox for an approved view authorized by a signed token.",
    summary="Serve the trusted MCP App sandbox (signed-token authorized)",
    responses=responses.get_responses([404]),
)
@endpoint_access(
    authentication=Authentication.SIGNED_URL,
    authorization=Authorization.SIGNED_URL,
    reason="A signed token grants access only to its view and tenant.",
)
async def serve_app_view_content(
    view_id: UUID,
    request: Request,
    tenant_id: Annotated[UUID, Depends(authorize_signed_app_view)],
    container: Annotated[Container, Depends(get_container(with_transaction=False))],
) -> HTMLResponse:
    # A view is served on the content origin and nowhere else. The same route
    # is reachable on Eneo's own address in an ordinary deployment, and a
    # server's HTML must never be handed out from there.
    if not get_settings().mcp_apps_enabled or not _on_content_origin(request):
        raise NotFoundException("MCP app view not found")

    session = cast("AsyncSession", container.session())
    view = await McpAppViewRepo(session).get_for_tenant(
        view_id, tenant_id, approved_only=True
    )
    if view is None:
        raise NotFoundException("MCP app view not found")

    ui_csp = (view.ui_meta or {}).get("csp")
    csp = build_app_csp(
        cast(dict[str, object], ui_csp) if isinstance(ui_csp, dict) else None,
        frame_ancestors=get_settings().public_origin or None,
    )
    return HTMLResponse(
        content=sandbox_document(get_settings().public_origin or ""),
        headers={
            "Content-Security-Policy": csp,
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "Cache-Control": "no-store",
        },
    )
