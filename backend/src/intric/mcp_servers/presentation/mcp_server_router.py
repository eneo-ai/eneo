from uuid import UUID

from fastapi import APIRouter, Depends, Query

from intric.main.container.container import Container
from intric.main.exceptions import BadRequestException
from intric.main.models import PaginatedResponse
from intric.mcp_servers.presentation.models import (
    MCPConnectionStatus,
    MCPResourceReadResponse,
    MCPServerCreate,
    MCPServerCreateResponse,
    MCPServerPublic,
    MCPServerSettingsCreate,
    MCPServerSettingsPublic,
    MCPServerSettingsUpdate,
    MCPServerToolList,
    MCPServerToolPublic,
    MCPServerToolSyncResponse,
    MCPServerToolUpdate,
    MCPServerUpdate,
)
from intric.server.dependencies.container import get_container
from intric.server.protocol import responses

router = APIRouter()


# ============================================================================
# Global MCP Server Catalog Endpoints (Admin)
# ============================================================================


@router.get(
    "/",
    response_model=PaginatedResponse[MCPServerPublic],
    responses=responses.get_responses([404]),
)
async def get_mcp_servers(
    tags: list[str] | None = Query(None),
    container: Container = Depends(get_container(with_user=True)),
):
    """Get all MCP servers from global catalog with optional tag filtering."""
    service = container.mcp_server_service()
    assembler = container.mcp_server_assembler()

    mcp_servers = await service.get_mcp_servers(tags=tags)
    return assembler.to_paginated_response(mcp_servers)


# ============================================================================
# Tenant MCP Server Settings Endpoints (MUST come before /{id}/ route)
# ============================================================================


@router.get(
    "/settings/",
    response_model=PaginatedResponse[MCPServerSettingsPublic],
    responses=responses.get_responses([404]),
)
async def get_tenant_mcp_settings(
    container: Container = Depends(get_container(with_user=True)),
):
    """Get all available MCP servers with tenant enablement status."""
    service = container.mcp_server_settings_service()
    assembler = container.mcp_server_settings_assembler()

    settings = await service.get_available_mcp_servers()
    return assembler.to_paginated_response(settings)


@router.post(
    "/settings/{mcp_server_id}/",
    response_model=MCPServerSettingsPublic,
    responses=responses.get_responses([400, 404]),
)
async def enable_mcp_for_tenant(
    mcp_server_id: UUID,
    data: MCPServerSettingsCreate,
    container: Container = Depends(get_container(with_user=True)),
):
    """Enable an MCP server for the current tenant with optional credentials."""
    service = container.mcp_server_settings_service()
    assembler = container.mcp_server_settings_assembler()

    settings = await service.update_mcp_settings(
        mcp_server_id=mcp_server_id,
        is_org_enabled=True,
        env_vars=data.env_vars,
    )
    return assembler.from_domain_to_model(settings)


@router.put(
    "/settings/{mcp_server_id}/",
    response_model=MCPServerSettingsPublic,
    responses=responses.get_responses([400, 403, 404]),
)
async def update_mcp_settings(
    mcp_server_id: UUID,
    data: MCPServerSettingsUpdate,
    container: Container = Depends(get_container(with_user=True)),
):
    """Update MCP server settings for the current tenant."""
    service = container.mcp_server_settings_service()
    assembler = container.mcp_server_settings_assembler()

    settings = await service.update_mcp_settings(
        mcp_server_id=mcp_server_id,
        is_org_enabled=data.is_org_enabled,
        env_vars=data.env_vars,
    )
    return assembler.from_domain_to_model(settings)


@router.delete(
    "/settings/{mcp_server_id}/",
    status_code=204,
    responses=responses.get_responses([403, 404]),
)
async def disable_mcp_for_tenant(
    mcp_server_id: UUID,
    container: Container = Depends(get_container(with_user=True)),
):
    """Disable an MCP server for the current tenant."""
    service = container.mcp_server_settings_service()
    await service.update_mcp_settings(
        mcp_server_id=mcp_server_id,
        is_org_enabled=False,
    )


@router.put(
    "/settings/tools/{tool_id}/",
    response_model=MCPServerToolPublic,
    responses=responses.get_responses([403, 404]),
)
async def update_tenant_tool_enabled(
    tool_id: UUID,
    data: MCPServerToolUpdate,
    container: Container = Depends(get_container(with_user=True)),
):
    """Update tenant-level enablement for a tool (admin only)."""
    service = container.mcp_server_service()
    assembler = container.mcp_server_tool_assembler()

    # Update tool's tenant-level enabled status
    tool = await service.update_tenant_tool_enabled(tool_id, data.is_enabled)
    return assembler.from_domain_to_model(tool)


# ============================================================================
# Global MCP Server Catalog Endpoints - Specific ID routes (MUST come after /settings/)
# ============================================================================


@router.get(
    "/{id}/",
    response_model=MCPServerPublic,
    responses=responses.get_responses([404]),
)
async def get_mcp_server(
    id: UUID,
    container: Container = Depends(get_container(with_user=True)),
):
    """Get a single MCP server by ID."""
    service = container.mcp_server_service()
    assembler = container.mcp_server_assembler()

    mcp_server = await service.get_mcp_server(id)
    return assembler.from_domain_to_model(mcp_server)


@router.post(
    "/",
    response_model=MCPServerCreateResponse,
    responses=responses.get_responses([400, 403]),
)
async def create_mcp_server(
    data: MCPServerCreate,
    container: Container = Depends(get_container(with_user=True)),
):
    """Create a new MCP server in global catalog (admin only).

    Validates connection before saving. Returns 400 if connection fails.
    """
    service = container.mcp_server_service()
    assembler = container.mcp_server_assembler()

    result = await service.create_mcp_server(
        name=data.name,
        http_url=str(data.http_url),
        http_auth_type=data.http_auth_type,
        description=data.description,
        http_auth_config_schema=data.http_auth_config_schema,
        tags=data.tags,
        icon_url=str(data.icon_url) if data.icon_url else None,
        documentation_url=str(data.documentation_url)
        if data.documentation_url
        else None,
    )

    # If connection failed, return 400 error with message
    if not result.connection.success:
        raise BadRequestException(
            result.connection.error_message or "Failed to connect to MCP server"
        )

    return MCPServerCreateResponse(
        server=assembler.from_domain_to_model(result.server),
        connection=MCPConnectionStatus(
            success=result.connection.success,
            tools_discovered=result.connection.tools_discovered,
            error_message=result.connection.error_message,
        ),
    )


@router.post(
    "/{id}/",
    response_model=MCPServerPublic,
    responses=responses.get_responses([400, 403, 404]),
)
async def update_mcp_server(
    id: UUID,
    data: MCPServerUpdate,
    container: Container = Depends(get_container(with_user=True)),
):
    """Update an MCP server in global catalog (admin only)."""
    service = container.mcp_server_service()
    assembler = container.mcp_server_assembler()

    mcp_server = await service.update_mcp_server(
        mcp_server_id=id,
        name=data.name,
        http_url=str(data.http_url) if data.http_url else None,
        http_auth_type=data.http_auth_type,
        description=data.description,
        http_auth_config_schema=data.http_auth_config_schema,
        tags=data.tags,
        icon_url=str(data.icon_url) if data.icon_url else None,
        documentation_url=str(data.documentation_url)
        if data.documentation_url
        else None,
    )
    return assembler.from_domain_to_model(mcp_server)


@router.delete(
    "/{id}/",
    status_code=204,
    responses=responses.get_responses([403, 404]),
)
async def delete_mcp_server(
    id: UUID,
    container: Container = Depends(get_container(with_user=True)),
):
    """Delete an MCP server from global catalog (admin only)."""
    service = container.mcp_server_service()
    await service.delete_mcp_server(id)


# ============================================================================
# MCP Server Tools Endpoints
# ============================================================================


@router.get(
    "/{id}/tools/",
    response_model=MCPServerToolList,
    responses=responses.get_responses([404]),
)
async def get_mcp_server_tools(
    id: UUID,
    container: Container = Depends(get_container(with_user=True)),
):
    """Get all tools for an MCP server with tenant-level settings applied."""
    service = container.mcp_server_service()
    assembler = container.mcp_server_tool_assembler()

    # Get tools with tenant settings applied
    tools = await service.get_tools_with_tenant_settings(id)
    return assembler.to_paginated_response(tools)


@router.post(
    "/{id}/tools/sync/",
    response_model=MCPServerToolSyncResponse,
    responses=responses.get_responses([400, 403, 404]),
)
async def sync_mcp_server_tools(
    id: UUID,
    container: Container = Depends(get_container(with_user=True)),
):
    """Manually refresh/sync tools for an MCP server (admin only).

    Returns 400 if connection to the MCP server fails.
    """
    service = container.mcp_server_service()
    assembler = container.mcp_server_tool_assembler()

    # Refresh tools from MCP server
    tools, connection_result = await service.refresh_tools(id)

    # If connection failed, return 400 error with message
    if not connection_result.success:
        raise BadRequestException(
            connection_result.error_message or "Failed to connect to MCP server"
        )

    return MCPServerToolSyncResponse(
        tools=[assembler.from_domain_to_model(t) for t in tools],
        connection=MCPConnectionStatus(
            success=connection_result.success,
            tools_discovered=connection_result.tools_discovered,
            error_message=connection_result.error_message,
        ),
    )


@router.get(
    "/{id}/resources/read",
    response_model=MCPResourceReadResponse,
    responses=responses.get_responses([400, 404]),
)
async def read_mcp_resource(
    id: UUID,
    uri: str = Query(..., description="Resource URI to read"),
    container: Container = Depends(get_container(with_user=True)),
):
    """Read a resource from an MCP server (e.g., UI resource HTML for MCP Apps)."""
    from intric.mcp_servers.infrastructure.client.mcp_client import MCPClientError

    service = container.mcp_server_service()

    try:
        result = await service.read_resource(mcp_server_id=id, uri=uri)
    except MCPClientError as e:
        raise BadRequestException(str(e))

    return MCPResourceReadResponse(
        content=result["content"],
        mime_type=result.get("mime_type", "text/html"),
    )



@router.put(
    "/{id}/tools/{tool_id}/",
    response_model=MCPServerToolPublic,
    responses=responses.get_responses([403, 404]),
)
async def update_tool_default_enabled(
    id: UUID,
    tool_id: UUID,
    data: MCPServerToolUpdate,
    container: Container = Depends(get_container(with_user=True)),
):
    """Update global default enabled status for a tool (admin only)."""
    service = container.mcp_server_service()
    assembler = container.mcp_server_tool_assembler()

    # Update tool's default enabled status
    tool = await service.update_tool_default_enabled(tool_id, data.is_enabled)
    return assembler.from_domain_to_model(tool)
