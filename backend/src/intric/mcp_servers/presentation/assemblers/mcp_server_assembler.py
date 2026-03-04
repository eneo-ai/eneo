from typing import TYPE_CHECKING, Any

from intric.mcp_servers.domain.entities.mcp_server import MCPServer
from intric.mcp_servers.presentation.models import (
    MCPServerList,
    MCPServerPublic,
    MCPServerSettingsList,
    MCPServerSettingsPublic,
    MCPServerToolPublic,
)

if TYPE_CHECKING:
    from intric.settings.encryption_service import EncryptionService

# Keys in http_auth_config_schema that contain secrets
_SECRET_KEYS = ("token",)


def _compute_credential_preview(
    config: dict[str, Any] | None,
    encryption_service: "EncryptionService | None",
) -> str | None:
    """Compute a masked preview of stored credentials (e.g. '••••••••sk12')."""
    if not config:
        return None

    for key in _SECRET_KEYS:
        value = config.get(key)
        if not value:
            continue

        try:
            from intric.settings.encryption_service import EncryptionService

            if encryption_service and encryption_service.is_encrypted(value):
                decrypted = encryption_service.decrypt(value)
                return EncryptionService.mask_secret(decrypted)
            elif value:
                return EncryptionService.mask_secret(value)
        except Exception:
            return "••••••••"

    return None


class MCPServerAssembler:
    """Assembler for converting MCP domain entities to presentation DTOs."""

    def __init__(
        self,
        encryption_service: "EncryptionService | None" = None,
    ):
        self.encryption_service = encryption_service

    @staticmethod
    def to_dict_with_tools(mcp_server: MCPServer) -> dict[str, Any]:
        """Convert MCPServer with tools to dict format (for assistant/space responses)."""
        # Sort tools by name for consistent ordering
        sorted_tools = sorted(mcp_server.tools, key=lambda t: t.name)
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
                for tool in sorted_tools
            ],
        }

    def from_domain_to_model(self, mcp_server: MCPServer) -> MCPServerPublic:
        """Convert MCPServer domain entity to DTO."""
        return MCPServerPublic(
            id=mcp_server.id,
            name=mcp_server.name,
            description=mcp_server.description,
            http_url=mcp_server.http_url,
            http_auth_type=mcp_server.http_auth_type,
            has_credentials=bool(mcp_server.http_auth_config_schema),
            credential_preview=_compute_credential_preview(
                mcp_server.http_auth_config_schema, self.encryption_service
            ),
            tags=mcp_server.tags,
            icon_url=mcp_server.icon_url,
            documentation_url=mcp_server.documentation_url,
        )

    def to_paginated_response(self, mcp_servers: list[MCPServer]) -> MCPServerList:
        """Convert list of MCPServer entities to paginated response."""
        items = [self.from_domain_to_model(server) for server in mcp_servers]
        return MCPServerList(items=items)


class MCPServerSettingsAssembler:
    """Assembler for converting MCP servers to settings DTOs (simplified - no separate settings entity)."""

    def __init__(
        self,
        encryption_service: "EncryptionService | None" = None,
    ):
        self.encryption_service = encryption_service

    def from_domain_to_model(self, mcp_server: MCPServer) -> MCPServerSettingsPublic:
        """Convert MCPServer domain entity to settings DTO."""
        # Sort tools by name for consistent ordering
        sorted_tools = sorted(mcp_server.tools, key=lambda t: t.name)
        tools = [
            MCPServerToolPublic(
                id=tool.id,
                mcp_server_id=tool.mcp_server_id,
                name=tool.name,
                description=tool.description,
                input_schema=tool.input_schema,
                is_enabled_by_default=tool.is_enabled_by_default,
            )
            for tool in sorted_tools
        ]

        has_creds = bool(mcp_server.http_auth_config_schema)
        credential_status = "ok" if has_creds else "missing"

        return MCPServerSettingsPublic(
            id=mcp_server.id,
            mcp_server_id=mcp_server.id,
            name=mcp_server.name,
            description=mcp_server.description,
            http_url=mcp_server.http_url,
            http_auth_type=mcp_server.http_auth_type,
            has_credentials=bool(mcp_server.http_auth_config_schema),
            credential_preview=_compute_credential_preview(
                mcp_server.http_auth_config_schema, self.encryption_service
            ),
            tags=mcp_server.tags,
            icon_url=mcp_server.icon_url,
            documentation_url=mcp_server.documentation_url,
            is_org_enabled=mcp_server.is_enabled,
            credential_status=credential_status,
            tools=tools,
        )

    def to_paginated_response(
        self,
        mcp_servers: list[MCPServer],
    ) -> MCPServerSettingsList:
        """Convert list of MCPServer entities to paginated settings response."""
        items = [self.from_domain_to_model(server) for server in mcp_servers]
        return MCPServerSettingsList(items=items)
