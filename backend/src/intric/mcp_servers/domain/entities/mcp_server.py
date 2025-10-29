from datetime import datetime
from typing import Optional
from uuid import UUID

from intric.base.base_entity import Entity


class MCPServer(Entity):
    """Domain entity for MCP server (global catalog entry)."""

    def __init__(
        self,
        name: str,
        server_type: str,
        description: Optional[str] = None,
        npm_package: Optional[str] = None,
        uvx_package: Optional[str] = None,
        docker_image: Optional[str] = None,
        http_url: Optional[str] = None,
        config_schema: Optional[dict] = None,
        tags: Optional[list[str]] = None,
        icon_url: Optional[str] = None,
        documentation_url: Optional[str] = None,
        id: Optional[UUID] = None,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
    ):
        super().__init__(id=id, created_at=created_at, updated_at=updated_at)
        self.name = name
        self.description = description
        self.server_type = server_type
        self.npm_package = npm_package
        self.uvx_package = uvx_package
        self.docker_image = docker_image
        self.http_url = http_url
        self.config_schema = config_schema
        self.tags = tags
        self.icon_url = icon_url
        self.documentation_url = documentation_url


class MCPServerSettings(Entity):
    """Domain entity for tenant-level MCP server enablement."""

    def __init__(
        self,
        tenant_id: UUID,
        mcp_server_id: UUID,
        is_org_enabled: bool,
        mcp_server: MCPServer,
        env_vars: Optional[dict] = None,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
    ):
        super().__init__(id=None, created_at=created_at, updated_at=updated_at)
        self.tenant_id = tenant_id
        self.mcp_server_id = mcp_server_id
        self.is_org_enabled = is_org_enabled
        self.env_vars = env_vars
        self.mcp_server = mcp_server
