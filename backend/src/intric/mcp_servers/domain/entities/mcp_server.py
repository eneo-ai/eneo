from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from intric.base.base_entity import Entity


class MCPServerTool(Entity):
    """Domain entity for MCP server tool."""

    def __init__(
        self,
        mcp_server_id: UUID,
        name: str,
        description: Optional[str] = None,
        input_schema: Optional[dict[str, Any]] = None,
        is_enabled_by_default: bool = True,
        id: Optional[UUID] = None,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
    ):
        super().__init__(id=id, created_at=created_at, updated_at=updated_at)
        self.mcp_server_id = mcp_server_id
        self.name = name
        self.description = description
        self.input_schema = input_schema
        self.is_enabled_by_default = is_enabled_by_default


class MCPServer(Entity):
    """Domain entity for MCP server (tenant-scoped, HTTP-only)."""

    def __init__(
        self,
        tenant_id: UUID,
        name: str,
        http_url: str,
        description: Optional[str] = None,
        http_auth_type: str = "none",
        http_auth_config_schema: Optional[dict[str, Any]] = None,
        is_enabled: bool = True,
        env_vars: Optional[dict[str, Any]] = None,
        tags: Optional[list[str]] = None,
        icon_url: Optional[str] = None,
        documentation_url: Optional[str] = None,
        tools: Optional[list[MCPServerTool]] = None,
        id: Optional[UUID] = None,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
    ):
        super().__init__(id=id, created_at=created_at, updated_at=updated_at)
        self.tenant_id = tenant_id
        self.name = name
        self.description = description
        self.http_url = http_url
        self.http_auth_type = http_auth_type
        self.http_auth_config_schema = http_auth_config_schema
        self.is_enabled = is_enabled
        self.env_vars = env_vars
        self.tags = tags
        self.icon_url = icon_url
        self.documentation_url = documentation_url
        self.tools = tools or []


class MCPServerSettings(Entity):
    """Domain entity for MCP server settings (tenant-scoped configuration)."""

    def __init__(
        self,
        tenant_id: UUID,
        mcp_server_id: UUID,
        is_org_enabled: bool = True,
        env_vars: Optional[dict[str, Any]] = None,
        mcp_server: Optional[MCPServer] = None,
        id: Optional[UUID] = None,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
    ):
        super().__init__(id=id, created_at=created_at, updated_at=updated_at)
        self.tenant_id = tenant_id
        self.mcp_server_id = mcp_server_id
        self.is_org_enabled = is_org_enabled
        self.env_vars = env_vars
        self.mcp_server = mcp_server
