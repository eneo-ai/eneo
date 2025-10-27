from intric.mcp_servers.domain.entities.mcp_server import MCPServer, MCPServerSettings
from intric.mcp_servers.presentation.models import (
    MCPServerList,
    MCPServerPublic,
    MCPServerSettingsList,
    MCPServerSettingsPublic,
)


class MCPServerAssembler:
    """Assembler for converting MCP domain entities to presentation DTOs."""

    @staticmethod
    def from_domain_to_model(mcp_server: MCPServer) -> MCPServerPublic:
        """Convert MCPServer domain entity to DTO."""
        return MCPServerPublic(
            id=mcp_server.id,
            name=mcp_server.name,
            description=mcp_server.description,
            server_type=mcp_server.server_type,
            npm_package=mcp_server.npm_package,
            docker_image=mcp_server.docker_image,
            http_url=mcp_server.http_url,
            config_schema=mcp_server.config_schema,
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
    """Assembler for converting MCP settings domain entities to presentation DTOs."""

    @staticmethod
    def from_domain_to_model(settings: MCPServerSettings) -> MCPServerSettingsPublic:
        """Convert MCPServerSettings domain entity to DTO."""
        return MCPServerSettingsPublic(
            id=settings.mcp_server.id,
            mcp_server_id=settings.mcp_server_id,
            name=settings.mcp_server.name,
            description=settings.mcp_server.description,
            server_type=settings.mcp_server.server_type,
            npm_package=settings.mcp_server.npm_package,
            docker_image=settings.mcp_server.docker_image,
            http_url=settings.mcp_server.http_url,
            config_schema=settings.mcp_server.config_schema,
            tags=settings.mcp_server.tags,
            icon_url=settings.mcp_server.icon_url,
            documentation_url=settings.mcp_server.documentation_url,
            is_org_enabled=settings.is_org_enabled,
            has_credentials=settings.env_vars is not None and len(settings.env_vars) > 0,
        )

    @staticmethod
    def to_paginated_response(
        settings_list: list[MCPServerSettings],
    ) -> MCPServerSettingsList:
        """Convert list of MCPServerSettings entities to paginated response."""
        items = [
            MCPServerSettingsAssembler.from_domain_to_model(settings)
            for settings in settings_list
        ]
        return MCPServerSettingsList(items=items)
