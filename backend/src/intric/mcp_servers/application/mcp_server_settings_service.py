from typing import TYPE_CHECKING
from uuid import UUID

from intric.main.exceptions import NotFoundException, UnauthorizedException
from intric.mcp_servers.domain.entities.mcp_server import MCPServer

if TYPE_CHECKING:
    from intric.mcp_servers.domain.repositories.mcp_server_repo import MCPServerRepository
    from intric.users.user import UserInDB


class MCPServerSettingsService:
    """Service for managing tenant-level MCP servers (simplified - no separate settings table)."""

    def __init__(
        self,
        mcp_server_repo: "MCPServerRepository",
        user: "UserInDB",
    ):
        self.mcp_server_repo = mcp_server_repo
        self.user = user

    async def get_available_mcp_servers(self) -> list[MCPServer]:
        """Get all MCP servers for the current tenant (enabled and disabled)."""
        return await self.mcp_server_repo.query_by_tenant(tenant_id=self.user.tenant_id)

    async def create_mcp_server(
        self,
        name: str,
        http_url: str,
        http_auth_type: str = "none",
        description: str | None = None,
        http_auth_config_schema: dict | None = None,
        tags: list[str] | None = None,
        icon_url: str | None = None,
        documentation_url: str | None = None,
        is_enabled: bool = True,
        env_vars: dict | None = None,
    ) -> MCPServer:
        """Create a new MCP server for the current tenant (uses Streamable HTTP transport)."""
        mcp_server = MCPServer(
            tenant_id=self.user.tenant_id,
            name=name,
            http_url=http_url,
            http_auth_type=http_auth_type,
            description=description,
            http_auth_config_schema=http_auth_config_schema,
            tags=tags,
            icon_url=icon_url,
            documentation_url=documentation_url,
            is_enabled=is_enabled,
            env_vars=env_vars,  # TODO: Encrypt sensitive values
        )

        return await self.mcp_server_repo.add(mcp_server)

    async def update_mcp_settings(
        self,
        mcp_server_id: UUID,
        is_org_enabled: bool | None = None,
        env_vars: dict | None = None,
    ) -> MCPServer:
        """Update MCP server settings (enablement and credentials)."""
        mcp_server = await self.mcp_server_repo.one(id=mcp_server_id)

        # Verify tenant ownership
        if mcp_server.tenant_id != self.user.tenant_id:
            raise UnauthorizedException()

        if is_org_enabled is not None:
            mcp_server.is_enabled = is_org_enabled
        if env_vars is not None:
            mcp_server.env_vars = env_vars  # TODO: Encrypt sensitive values

        return await self.mcp_server_repo.update(mcp_server)

    async def delete_mcp_server(self, mcp_server_id: UUID) -> None:
        """Delete an MCP server for the current tenant."""
        mcp_server = await self.mcp_server_repo.one(id=mcp_server_id)

        # Verify tenant ownership
        if mcp_server.tenant_id != self.user.tenant_id:
            raise UnauthorizedException()

        await self.mcp_server_repo.delete(id=mcp_server_id)

    async def is_enabled_for_tenant(
        self, mcp_server_id: UUID, tenant_id: UUID
    ) -> bool:
        """Check if an MCP server is enabled for a specific tenant."""
        try:
            mcp_server = await self.mcp_server_repo.one(id=mcp_server_id)
            return mcp_server.tenant_id == tenant_id and mcp_server.is_enabled
        except NotFoundException:
            return False
