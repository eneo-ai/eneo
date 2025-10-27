from typing import TYPE_CHECKING
from uuid import UUID

from intric.main.exceptions import BadRequestException, UnauthorizedException
from intric.mcp_servers.domain.entities.mcp_server import MCPServerSettings

if TYPE_CHECKING:
    from intric.mcp_servers.domain.repositories.mcp_server_repo import MCPServerRepository
    from intric.mcp_servers.domain.repositories.mcp_server_settings_repo import (
        MCPServerSettingsRepository,
    )
    from intric.users.user import UserInDB


class MCPServerSettingsService:
    """Service for managing tenant-level MCP server enablement and credentials."""

    def __init__(
        self,
        settings_repo: "MCPServerSettingsRepository",
        mcp_server_repo: "MCPServerRepository",
        user: "UserInDB",
    ):
        self.settings_repo = settings_repo
        self.mcp_server_repo = mcp_server_repo
        self.user = user

    async def get_tenant_mcp_servers(self) -> list[MCPServerSettings]:
        """Get all MCP servers enabled for the current tenant."""
        return await self.settings_repo.query(tenant_id=self.user.tenant_id)

    async def get_available_mcp_servers(self) -> list[MCPServerSettings]:
        """
        Get all available MCP servers (global catalog + tenant enabled status).
        Returns both enabled and disabled MCPs for the tenant.
        """
        # Get all global MCP servers
        all_mcp_servers = await self.mcp_server_repo.all()

        # Get tenant's enabled MCPs
        tenant_settings = await self.settings_repo.query(tenant_id=self.user.tenant_id)
        tenant_settings_map = {
            setting.mcp_server_id: setting for setting in tenant_settings
        }

        # Build list with enabled status
        result = []
        for mcp_server in all_mcp_servers:
            if mcp_server.id in tenant_settings_map:
                # Already enabled for tenant
                result.append(tenant_settings_map[mcp_server.id])
            else:
                # Not enabled yet - create virtual settings object
                result.append(
                    MCPServerSettings(
                        tenant_id=self.user.tenant_id,
                        mcp_server_id=mcp_server.id,
                        is_org_enabled=False,
                        env_vars=None,
                        mcp_server=mcp_server,
                    )
                )

        return result

    async def enable_mcp_for_tenant(
        self,
        mcp_server_id: UUID,
        env_vars: dict | None = None,
    ) -> MCPServerSettings:
        """Enable an MCP server for the current tenant with optional credentials."""
        # Verify MCP server exists in global catalog
        mcp_server = await self.mcp_server_repo.one(id=mcp_server_id)

        # Check if already enabled
        existing = await self.settings_repo.one_or_none(
            tenant_id=self.user.tenant_id, mcp_server_id=mcp_server_id
        )
        if existing:
            raise BadRequestException("MCP server already enabled for tenant")

        # Create settings
        settings = MCPServerSettings(
            tenant_id=self.user.tenant_id,
            mcp_server_id=mcp_server_id,
            is_org_enabled=True,
            env_vars=env_vars,  # TODO: Encrypt sensitive values
            mcp_server=mcp_server,
        )

        return await self.settings_repo.add(settings)

    async def update_mcp_settings(
        self,
        mcp_server_id: UUID,
        is_org_enabled: bool | None = None,
        env_vars: dict | None = None,
    ) -> MCPServerSettings:
        """Update MCP server settings for the current tenant."""
        settings = await self.settings_repo.one(
            tenant_id=self.user.tenant_id, mcp_server_id=mcp_server_id
        )

        # Verify tenant ownership
        if settings.tenant_id != self.user.tenant_id:
            raise UnauthorizedException()

        if is_org_enabled is not None:
            settings.is_org_enabled = is_org_enabled
        if env_vars is not None:
            settings.env_vars = env_vars  # TODO: Encrypt sensitive values

        return await self.settings_repo.update(settings)

    async def disable_mcp_for_tenant(self, mcp_server_id: UUID) -> None:
        """Disable an MCP server for the current tenant."""
        settings = await self.settings_repo.one(
            tenant_id=self.user.tenant_id, mcp_server_id=mcp_server_id
        )

        # Verify tenant ownership
        if settings.tenant_id != self.user.tenant_id:
            raise UnauthorizedException()

        await self.settings_repo.delete(
            tenant_id=self.user.tenant_id, mcp_server_id=mcp_server_id
        )

    async def is_enabled_for_tenant(
        self, mcp_server_id: UUID, tenant_id: UUID
    ) -> bool:
        """Check if an MCP server is enabled for a specific tenant."""
        settings = await self.settings_repo.one_or_none(
            tenant_id=tenant_id, mcp_server_id=mcp_server_id
        )
        return settings is not None and settings.is_org_enabled
