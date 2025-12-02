from intric.mcp_servers.domain.entities.mcp_server import MCPServer
from intric.mcp_servers.presentation.models import (
    MCPServerList,
    MCPServerPublic,
    MCPServerSettingsList,
    MCPServerSettingsPublic,
)


class MCPServerAssembler:
    """Assembler for converting MCP domain entities to presentation DTOs."""

    @staticmethod
    def to_dict_with_tools(mcp_server: MCPServer) -> dict:
        """Convert MCPServer with tools to dict format (for assistant/space responses)."""
        return {
            "id": str(mcp_server.id),
            "name": mcp_server.name,
            "description": mcp_server.description,
            "http_url": mcp_server.http_url,
            "http_auth_type": mcp_server.http_auth_type,
            "tags": mcp_server.tags,
            "icon_url": mcp_server.icon_url,
            "tools": [
                {
                    "id": str(tool.id),
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.input_schema,
                    "is_enabled": tool.is_enabled_by_default,
                }
                for tool in mcp_server.tools
            ],
        }

    @staticmethod
    def from_domain_to_model(mcp_server: MCPServer) -> MCPServerPublic:
        """Convert MCPServer domain entity to DTO."""
        return MCPServerPublic(
            id=mcp_server.id,
            name=mcp_server.name,
            description=mcp_server.description,
            http_url=mcp_server.http_url,
            http_auth_type=mcp_server.http_auth_type,
            http_auth_config_schema=mcp_server.http_auth_config_schema,
            tags=mcp_server.tags,
            icon_url=mcp_server.icon_url,
            documentation_url=mcp_server.documentation_url,
        )

    @staticmethod
    def to_paginated_response(mcp_servers: list[MCPServer]) -> MCPServerList:
        """Convert list of MCPServer entities to paginated response."""
        items = [
            MCPServerAssembler.from_domain_to_model(server) for server in mcp_servers
        ]
        return MCPServerList(items=items)


class MCPServerSettingsAssembler:
    """Assembler for converting MCP servers to settings DTOs (simplified - no separate settings entity)."""

    @staticmethod
    def from_domain_to_model(mcp_server: MCPServer) -> MCPServerSettingsPublic:
        """Convert MCPServer domain entity to settings DTO."""
        return MCPServerSettingsPublic(
            id=mcp_server.id,
            mcp_server_id=mcp_server.id,
            name=mcp_server.name,
            description=mcp_server.description,
            http_url=mcp_server.http_url,
            http_auth_type=mcp_server.http_auth_type,
            http_auth_config_schema=mcp_server.http_auth_config_schema,
            tags=mcp_server.tags,
            icon_url=mcp_server.icon_url,
            documentation_url=mcp_server.documentation_url,
            is_org_enabled=mcp_server.is_enabled,
            has_credentials=mcp_server.env_vars is not None and len(mcp_server.env_vars) > 0,
        )

    @staticmethod
    def to_paginated_response(
        mcp_servers: list[MCPServer],
    ) -> MCPServerSettingsList:
        """Convert list of MCPServer entities to paginated settings response."""
        items = [
            MCPServerSettingsAssembler.from_domain_to_model(server)
            for server in mcp_servers
        ]
        return MCPServerSettingsList(items=items)
