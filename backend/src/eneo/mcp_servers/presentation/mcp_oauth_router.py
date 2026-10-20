"""Endpoints for Eneo's OAuth client toward MCP servers.

The connect flow (authorize-url, callback, disconnect) is per user for
``per_user`` servers and admin-only for ``shared`` ones; the service decides.
The Client ID Metadata Documents and the JWKS are public by nature:
authorization servers fetch them to learn who Eneo is and to verify its
``private_key_jwt`` assertions.
"""

from __future__ import annotations

from typing import Annotated, Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.authentication.auth_dependencies import (
    require_api_key_permission,
    require_user_for_creation,
    require_user_identity,
)
from eneo.authentication.auth_models import ApiKeyPermission
from eneo.authentication.endpoint_access import (
    Authentication,
    Authorization,
    endpoint_access,
)
from eneo.main.config import get_settings
from eneo.main.container.container import Container
from eneo.main.exceptions import NotFoundException
from eneo.mcp_servers.application.mcp_oauth_signing_keys import published_keys
from eneo.mcp_servers.infrastructure.oauth import client_metadata
from eneo.mcp_servers.infrastructure.oauth.client_assertion import jwks_document
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses

router = APIRouter()

# Connecting changes what Eneo may do on the caller's behalf: a read-only API
# key must not be able to do it. Bearer sessions are unaffected by this guard.
_WRITE_KEY = Depends(require_api_key_permission(ApiKeyPermission.WRITE))

_CONNECTION_ACCESS_REASON = (
    "Any tenant member may authorize an OAuth MCP server for themselves; the "
    "service restricts shared connections to administrators."
)


class MCPOAuthAuthorizeUrl(BaseModel):
    url: str
    state: str


class MCPOAuthCallback(BaseModel):
    code: str
    state: str
    iss: Optional[str] = None


class MCPOAuthConnectionPublic(BaseModel):
    mcp_server_id: UUID
    server_name: str
    auth_scope: str
    status: str  # connected | needs_authorization | not_connected
    strategy: Optional[str] = None
    scopes: list[str] = []
    connected_at: Optional[str] = None
    connected_by_user_id: Optional[UUID] = None
    last_error: Optional[str] = None


class MCPOAuthConnectionList(BaseModel):
    items: list[MCPOAuthConnectionPublic]


def _public(items: list[dict[str, Any]]) -> MCPOAuthConnectionList:
    return MCPOAuthConnectionList(
        items=[MCPOAuthConnectionPublic(**item) for item in items]
    )


@router.get(
    "/client.json",
    response_model=dict[str, Any],
    description=(
        "Eneo's OAuth Client ID Metadata Document. Authorization servers fetch "
        "it to validate Eneo's client id and redirect URI."
    ),
    responses=responses.get_responses([404]),
)
@endpoint_access(
    authentication=Authentication.PUBLIC,
    authorization=Authorization.PUBLIC,
    reason="A Client ID Metadata Document is public by definition.",
)
async def get_client_metadata_document():
    document = client_metadata.client_metadata_document(get_settings())
    if document is None:
        raise NotFoundException(
            "This deployment has no https public origin, so it has no "
            "client metadata document; authorization servers use Dynamic "
            "Client Registration instead."
        )
    return JSONResponse(
        document,
        headers={"Cache-Control": "public, max-age=3600"},
        media_type="application/json",
    )


@router.get(
    "/client-confidential.json",
    response_model=dict[str, Any],
    description=(
        "Eneo's confidential OAuth Client ID Metadata Document: the identity "
        "Eneo uses at authorization servers that accept private_key_jwt, "
        "verified against the JWKS."
    ),
    responses=responses.get_responses([404]),
)
@endpoint_access(
    authentication=Authentication.PUBLIC,
    authorization=Authorization.PUBLIC,
    reason="A Client ID Metadata Document is public by definition.",
)
async def get_confidential_client_metadata_document():
    document = client_metadata.client_metadata_document(
        get_settings(), confidential=True
    )
    if document is None:
        raise NotFoundException(
            "This deployment has no https public origin, so it has no "
            "client metadata document; authorization servers use Dynamic "
            "Client Registration instead."
        )
    return JSONResponse(
        document,
        headers={"Cache-Control": "public, max-age=3600"},
        media_type="application/json",
    )


@router.get(
    "/jwks.json",
    response_model=dict[str, Any],
    description=(
        "Eneo's public signing keys (RFC 7517), against which authorization "
        "servers verify its private_key_jwt client assertions."
    ),
    responses=responses.get_responses([]),
)
@endpoint_access(
    authentication=Authentication.PUBLIC,
    authorization=Authorization.PUBLIC,
    reason="A JWKS holds public keys only and is public by definition.",
)
async def get_jwks(
    container: Annotated[Container, Depends(get_container())],
):
    keys = await published_keys(container.mcp_oauth_repo())
    return JSONResponse(
        jwks_document(keys),
        headers={"Cache-Control": "public, max-age=300"},
        media_type="application/json",
    )


@router.post(
    "/servers/{id}/authorize-url/",
    dependencies=[_WRITE_KEY],
    response_model=MCPOAuthAuthorizeUrl,
    description="Start authorizing Eneo at this MCP server's authorization server.",
    responses=responses.get_responses([400, 403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_CONNECTION_ACCESS_REASON,
)
async def start_mcp_oauth(
    id: UUID,
    container: Annotated[Container, Depends(get_container(with_user=True))],
    _user_identity_guard: None = Depends(require_user_identity),
):
    result = await container.mcp_oauth_service().authorize_url(id)
    return MCPOAuthAuthorizeUrl(**result)


@router.post(
    "/servers/{id}/callback/",
    dependencies=[_WRITE_KEY],
    response_model=MCPOAuthConnectionPublic,
    description="Finish the authorization with the code the popup received.",
    responses=responses.get_responses([400, 403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_CONNECTION_ACCESS_REASON,
)
async def complete_mcp_oauth(
    id: UUID,
    data: MCPOAuthCallback,
    container: Annotated[Container, Depends(get_container(with_user=True))],
    _user_for_creation: None = Depends(require_user_for_creation),
):
    service = container.mcp_oauth_service()
    server = await container.mcp_server_service().get_mcp_server(id)
    state = await service.complete(id, code=data.code, state=data.state, iss=data.iss)

    user = container.user()
    await container.audit_service().log_async(
        tenant_id=user.tenant_id,
        user=user,
        action=ActionType.MCP_OAUTH_SHARED_CONNECTION_SET
        if state["auth_scope"] == "shared"
        else ActionType.MCP_OAUTH_CONNECTED,
        entity_type=EntityType.MCP_SERVER,
        entity_id=id,
        description=f"Connected MCP server '{state['server_name']}' via OAuth",
        metadata=AuditMetadata.standard(
            actor=user,
            target=server,
            extra={
                "auth_scope": state["auth_scope"],
                "strategy": state["strategy"],
                "scopes": state["scopes"],
            },
        ),
    )
    return MCPOAuthConnectionPublic(**state)


@router.post(
    "/servers/{id}/decline/",
    status_code=204,
    dependencies=[_WRITE_KEY],
    description=(
        "The user refused or abandoned the vendor's consent page: a turn paused "
        "on this authorization proceeds without it."
    ),
    responses=responses.get_responses([400, 403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_CONNECTION_ACCESS_REASON,
)
async def decline_mcp_oauth(
    id: UUID,
    container: Annotated[Container, Depends(get_container(with_user=True))],
    _user_identity_guard: None = Depends(require_user_identity),
):
    await container.mcp_oauth_service().decline(id)
    return None


@router.delete(
    "/servers/{id}/connection/",
    status_code=204,
    dependencies=[_WRITE_KEY],
    description="Forget the connection (and revoke its tokens when possible).",
    responses=responses.get_responses([400, 403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_CONNECTION_ACCESS_REASON,
)
async def disconnect_mcp_oauth(
    id: UUID,
    container: Annotated[Container, Depends(get_container(with_user=True))],
    _user_identity_guard: None = Depends(require_user_identity),
):
    service = container.mcp_oauth_service()
    server = await container.mcp_server_service().get_mcp_server(id)
    removed = await service.disconnect(id)
    if removed:
        user = container.user()
        await container.audit_service().log_async(
            tenant_id=user.tenant_id,
            user=user,
            action=ActionType.MCP_OAUTH_SHARED_CONNECTION_CLEARED
            if server.is_shared_oauth
            else ActionType.MCP_OAUTH_DISCONNECTED,
            entity_type=EntityType.MCP_SERVER,
            entity_id=id,
            description=f"Disconnected MCP server '{server.name}' (OAuth)",
            metadata=AuditMetadata.standard(
                actor=user, target=server, extra={"auth_scope": server.auth_scope}
            ),
        )
    return None


@router.get(
    "/connections/",
    response_model=MCPOAuthConnectionList,
    description="The caller's state at every OAuth MCP server of the tenant.",
    responses=responses.get_responses([403]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason="A user may see which servers they have authorized.",
)
async def list_my_mcp_connections(
    container: Annotated[Container, Depends(get_container(with_user=True))],
    _user_identity_guard: None = Depends(require_user_identity),
):
    return _public(await container.mcp_oauth_service().my_connections())


@router.get(
    "/assistants/{id}/connections/",
    response_model=MCPOAuthConnectionList,
    description=(
        "The caller's state at the OAuth servers a turn of this assistant would "
        "reach. Powers the connect chip in the chat and integrator pre-checks."
    ),
    responses=responses.get_responses([403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason="Reading an assistant's servers requires reading the assistant.",
)
async def list_assistant_mcp_connections(
    id: UUID,
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    servers = await container.assistant_service().mcp_servers_a_turn_reaches(id)
    return _public(await container.mcp_oauth_service().connections_for(servers))
