from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from intric.audit.application.audit_metadata import AuditMetadata
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
from intric.main.container.container import Container
from intric.main.exceptions import BadRequestException
from intric.main.models import NOT_PROVIDED, PaginatedResponse
from intric.mcp_servers.presentation.models import (
    MCPConnectionStatus,
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
    ToolChangePublic,
    ToolReviewRequest,
    ToolReviewResponse,
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

    # Audit logging
    user = container.user()
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.MCP_SERVER_ENABLED,
        entity_type=EntityType.MCP_SERVER,
        entity_id=settings.id,
        description=f"Enabled MCP server '{settings.name}'",
        metadata=AuditMetadata.standard(actor=user, target=settings),
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

    # Get server info before disabling for audit context
    mcp_server_service = container.mcp_server_service()
    mcp_server = await mcp_server_service.get_mcp_server(mcp_server_id)

    await service.update_mcp_settings(
        mcp_server_id=mcp_server_id,
        is_org_enabled=False,
    )

    # Audit logging
    user = container.user()
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.MCP_SERVER_DISABLED,
        entity_type=EntityType.MCP_SERVER,
        entity_id=mcp_server_id,
        description=f"Disabled MCP server '{mcp_server.name}'",
        metadata=AuditMetadata.standard(actor=user, target=mcp_server),
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

    # Fetch tool and server info before update (update does manual session.commit())
    tool_before = await service.tool_repo.one(id=tool_id)
    mcp_server = await service.get_mcp_server(tool_before.mcp_server_id)

    # Update tool's tenant-level enabled status
    tool = await service.update_tenant_tool_enabled(tool_id, data.is_enabled)

    # Audit logging
    user = container.user()
    audit_service = container.audit_service()
    action = ActionType.MCP_SERVER_TOOL_ENABLED if data.is_enabled else ActionType.MCP_SERVER_TOOL_DISABLED
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=action,
        entity_type=EntityType.MCP_SERVER_TOOL,
        entity_id=tool.id,
        description=f"{'Enabled' if data.is_enabled else 'Disabled'} tool '{tool.name}' on MCP server '{mcp_server.name}' (tenant)",
        metadata=AuditMetadata.standard(
            actor=user,
            target=tool,
            extra={"mcp_server_id": str(mcp_server.id), "mcp_server_name": mcp_server.name},
        ),
    )

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

    # Resolve security classification if provided
    security_classification = None
    if data.security_classification is not None:
        sc_service = container.security_classification_service()
        security_classification = await sc_service.get_security_classification(
            data.security_classification.id
        )

    result = await service.create_mcp_server(
        name=data.name,
        http_url=str(data.http_url),
        http_auth_type=data.http_auth_type,
        description=data.description,
        http_auth_config_schema=data.http_auth_config_schema,
        tags=data.tags,
        icon_url=str(data.icon_url) if data.icon_url else None,
        documentation_url=str(data.documentation_url) if data.documentation_url else None,
        security_classification=security_classification,
    )

    # If connection failed, return 400 error with message
    if not result.connection.success:
        raise BadRequestException(
            result.connection.error_message or "Failed to connect to MCP server"
        )

    # Audit logging
    user = container.user()
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.MCP_SERVER_CREATED,
        entity_type=EntityType.MCP_SERVER,
        entity_id=result.server.id,
        description=f"Created MCP server '{result.server.name}'",
        metadata=AuditMetadata.standard(actor=user, target=result.server),
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

    # Get old state for change tracking
    old_server = await service.get_mcp_server(id)

    # Resolve security classification if provided
    security_classification = NOT_PROVIDED
    if data.security_classification is not NOT_PROVIDED:
        if data.security_classification is None:
            security_classification = None
        else:
            sc_service = container.security_classification_service()
            security_classification = await sc_service.get_security_classification(
                data.security_classification.id
            )

    result = await service.update_mcp_server(
        mcp_server_id=id,
        name=data.name,
        http_url=str(data.http_url) if data.http_url else None,
        http_auth_type=data.http_auth_type,
        description=data.description,
        http_auth_config_schema=data.http_auth_config_schema,
        tags=data.tags,
        icon_url=str(data.icon_url) if data.icon_url else None,
        documentation_url=str(data.documentation_url) if data.documentation_url else None,
        security_classification=security_classification,
    )

    # If connection validation failed, return 400 error with message
    if result.connection and not result.connection.success:
        raise BadRequestException(
            result.connection.error_message or "Failed to connect to MCP server"
        )

    mcp_server = result.server

    # Build changes dict
    changes: dict[str, Any] = {}
    if data.name is not None and data.name != old_server.name:
        changes["name"] = {"old": old_server.name, "new": data.name}
    if data.http_url is not None and str(data.http_url) != old_server.http_url:
        changes["http_url"] = {"old": old_server.http_url, "new": str(data.http_url)}
    if data.description is not None and data.description != old_server.description:
        changes["description"] = {"old": old_server.description, "new": data.description}
    if data.http_auth_type is not None and data.http_auth_type != old_server.http_auth_type:
        changes["http_auth_type"] = {"old": old_server.http_auth_type, "new": data.http_auth_type}
    if data.tags is not None and data.tags != old_server.tags:
        changes["tags"] = {"old": old_server.tags, "new": data.tags}
    if data.http_auth_config_schema is not None:
        changes["credentials_updated"] = True

    # Audit logging
    user = container.user()
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.MCP_SERVER_UPDATED,
        entity_type=EntityType.MCP_SERVER,
        entity_id=mcp_server.id,
        description=f"Updated MCP server '{mcp_server.name}'",
        metadata=AuditMetadata.standard(actor=user, target=mcp_server, changes=changes),
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

    # Get server info before deletion for audit context
    mcp_server = await service.get_mcp_server(id)

    await service.delete_mcp_server(id)

    # Audit logging
    user = container.user()
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.MCP_SERVER_DELETED,
        entity_type=EntityType.MCP_SERVER,
        entity_id=id,
        description=f"Deleted MCP server '{mcp_server.name}'",
        metadata=AuditMetadata.standard(actor=user, target=mcp_server),
    )


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
    """Sync tools from remote MCP server (admin only).

    Detects new, changed, and removed tools. Changes are stored as pending
    and require explicit approval before becoming active. This prevents a
    compromised MCP server from injecting malicious tool definitions.

    Returns 400 if connection to the MCP server fails.
    """
    service = container.mcp_server_service()
    assembler = container.mcp_server_tool_assembler()

    sync_result = await service.refresh_tools(id)

    # If connection failed, return 400 error with message
    if not sync_result.connection.success:
        raise BadRequestException(
            sync_result.connection.error_message or "Failed to connect to MCP server"
        )

    def _to_change_public(change):
        return ToolChangePublic(
            tool=assembler.from_domain_to_model(change.tool),
            change_type=change.change_type,
            current_description=change.current_description,
            current_input_schema=change.current_input_schema,
            pending_description=change.pending_description,
            pending_input_schema=change.pending_input_schema,
        )

    return MCPServerToolSyncResponse(
        connection=MCPConnectionStatus(
            success=sync_result.connection.success,
            tools_discovered=sync_result.connection.tools_discovered,
            error_message=sync_result.connection.error_message,
        ),
        new_tools=[_to_change_public(c) for c in sync_result.new_tools],
        changed_tools=[_to_change_public(c) for c in sync_result.changed_tools],
        removed_tools=[_to_change_public(c) for c in sync_result.removed_tools],
        unchanged_count=sync_result.unchanged_count,
    )


@router.post(
    "/{id}/tools/review/approve/",
    response_model=ToolReviewResponse,
    responses=responses.get_responses([400, 403, 404]),
)
async def approve_tool_changes(
    id: UUID,
    data: ToolReviewRequest,
    container: Container = Depends(get_container(with_user=True)),
):
    """Approve pending tool changes (admin only).

    For new/changed tools: pending values become active.
    For removed tools: tool is deleted from database.
    """
    service = container.mcp_server_service()
    assembler = container.mcp_server_tool_assembler()

    approved = await service.approve_tool_changes(id, data.tool_ids)

    # Audit logging
    user = container.user()
    audit_service = container.audit_service()
    mcp_server = await service.get_mcp_server(id)
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.MCP_SERVER_UPDATED,
        entity_type=EntityType.MCP_SERVER,
        entity_id=id,
        description=f"Approved {len(data.tool_ids)} tool change(s) on MCP server '{mcp_server.name}'",
        metadata=AuditMetadata.standard(
            actor=user,
            target=mcp_server,
            extra={"approved_tool_ids": [str(tid) for tid in data.tool_ids]},
        ),
    )

    return ToolReviewResponse(
        approved_tools=[assembler.from_domain_to_model(t) for t in approved],
        deleted_count=len(data.tool_ids) - len(approved),
    )


@router.post(
    "/{id}/tools/review/reject/",
    response_model=ToolReviewResponse,
    responses=responses.get_responses([400, 403, 404]),
)
async def reject_tool_changes(
    id: UUID,
    data: ToolReviewRequest,
    container: Container = Depends(get_container(with_user=True)),
):
    """Reject pending tool changes (admin only).

    For new tools: tool is deleted (never activated).
    For changed tools: pending values are cleared, active values kept.
    For removed tools: removed flag is cleared, tool stays active.
    """
    service = container.mcp_server_service()
    assembler = container.mcp_server_tool_assembler()

    rejected = await service.reject_tool_changes(id, data.tool_ids)

    # Audit logging
    user = container.user()
    audit_service = container.audit_service()
    mcp_server = await service.get_mcp_server(id)
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.MCP_SERVER_UPDATED,
        entity_type=EntityType.MCP_SERVER,
        entity_id=id,
        description=f"Rejected {len(data.tool_ids)} tool change(s) on MCP server '{mcp_server.name}'",
        metadata=AuditMetadata.standard(
            actor=user,
            target=mcp_server,
            extra={"rejected_tool_ids": [str(tid) for tid in data.tool_ids]},
        ),
    )

    return ToolReviewResponse(
        rejected_tools=[assembler.from_domain_to_model(t) for t in rejected],
        deleted_count=len(data.tool_ids) - len(rejected),
    )


@router.post(
    "/{id}/tools/review/approve-all/",
    response_model=ToolReviewResponse,
    responses=responses.get_responses([400, 403, 404]),
)
async def approve_all_tool_changes(
    id: UUID,
    container: Container = Depends(get_container(with_user=True)),
):
    """Approve all pending tool changes for an MCP server (admin only)."""
    service = container.mcp_server_service()
    assembler = container.mcp_server_tool_assembler()

    approved = await service.approve_all_tool_changes(id)

    # Audit logging
    user = container.user()
    audit_service = container.audit_service()
    mcp_server = await service.get_mcp_server(id)
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.MCP_SERVER_UPDATED,
        entity_type=EntityType.MCP_SERVER,
        entity_id=id,
        description=f"Approved all tool changes on MCP server '{mcp_server.name}'",
        metadata=AuditMetadata.standard(actor=user, target=mcp_server),
    )

    return ToolReviewResponse(
        approved_tools=[assembler.from_domain_to_model(t) for t in approved],
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

    # Fetch server info before update for audit context
    mcp_server = await service.get_mcp_server(id)

    # Update tool's default enabled status
    tool = await service.update_tool_default_enabled(tool_id, data.is_enabled)

    # Audit logging
    user = container.user()
    audit_service = container.audit_service()
    action = ActionType.MCP_SERVER_TOOL_ENABLED if data.is_enabled else ActionType.MCP_SERVER_TOOL_DISABLED
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=action,
        entity_type=EntityType.MCP_SERVER_TOOL,
        entity_id=tool.id,
        description=f"{'Enabled' if data.is_enabled else 'Disabled'} tool '{tool.name}' on MCP server '{mcp_server.name}' (default)",
        metadata=AuditMetadata.standard(
            actor=user,
            target=tool,
            extra={"mcp_server_id": str(mcp_server.id), "mcp_server_name": mcp_server.name},
        ),
    )

    return assembler.from_domain_to_model(tool)
