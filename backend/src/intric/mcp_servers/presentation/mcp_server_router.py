from uuid import UUID

from fastapi import APIRouter, Depends, Query

from intric.main.container.container import Container
from intric.main.models import PaginatedResponse
from intric.mcp_servers.presentation.models import (
    MCPServerCreate,
    MCPServerPublic,
    MCPServerSettingsCreate,
    MCPServerSettingsPublic,
    MCPServerSettingsUpdate,
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

    settings = await service.enable_mcp_for_tenant(
        mcp_server_id=mcp_server_id,
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
    await service.disable_mcp_for_tenant(mcp_server_id)


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
    response_model=MCPServerPublic,
    responses=responses.get_responses([400, 403]),
)
async def create_mcp_server(
    data: MCPServerCreate,
    container: Container = Depends(get_container(with_user=True)),
):
    """Create a new MCP server in global catalog (admin only)."""
    service = container.mcp_server_service()
    assembler = container.mcp_server_assembler()

    mcp_server = await service.create_mcp_server(
        name=data.name,
        server_type=data.server_type,
        description=data.description,
        npm_package=data.npm_package,
        docker_image=data.docker_image,
        http_url=data.http_url,
        config_schema=data.config_schema,
        tags=data.tags,
        icon_url=data.icon_url,
        documentation_url=data.documentation_url,
    )
    return assembler.from_domain_to_model(mcp_server)


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
        server_type=data.server_type,
        description=data.description,
        npm_package=data.npm_package,
        docker_image=data.docker_image,
        http_url=data.http_url,
        config_schema=data.config_schema,
        tags=data.tags,
        icon_url=data.icon_url,
        documentation_url=data.documentation_url,
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
