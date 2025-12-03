import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from intric.mcp_servers.domain.entities.mcp_server import MCPServer, MCPServerTool
from intric.mcp_servers.infrastructure.client.mcp_client import MCPClient, MCPClientError
from intric.roles.permissions import Permission, validate_permissions

if TYPE_CHECKING:
    from intric.mcp_servers.domain.repositories.mcp_server_repo import MCPServerRepository
    from intric.mcp_servers.domain.repositories.mcp_server_tool_repo import MCPServerToolRepository
    from intric.users.user import UserInDB

logger = logging.getLogger(__name__)


@dataclass
class ConnectionResult:
    """Result of MCP server connection attempt."""

    success: bool
    tools_discovered: int = 0
    error_message: str | None = None


@dataclass
class MCPServerCreateResult:
    """Result of MCP server creation including connection status."""

    server: MCPServer
    connection: ConnectionResult


class MCPServerService:
    """Service for managing global MCP server catalog (admin only)."""

    def __init__(
        self,
        mcp_server_repo: "MCPServerRepository",
        mcp_server_tool_repo: "MCPServerToolRepository",
        user: "UserInDB",
    ):
        self.repo = mcp_server_repo
        self.tool_repo = mcp_server_tool_repo
        self.user = user

    async def get_mcp_servers(self, tags: list[str] | None = None) -> list[MCPServer]:
        """Get all MCP servers from global catalog with optional tag filtering."""
        if tags:
            return await self.repo.query(tags=tags)
        return await self.repo.all()

    async def get_mcp_server(self, mcp_server_id: UUID) -> MCPServer:
        """Get a single MCP server by ID."""
        return await self.repo.one(id=mcp_server_id)

    @validate_permissions(Permission.ADMIN)
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
    ) -> MCPServerCreateResult:
        """Create a new MCP server for the tenant (admin only, uses Streamable HTTP transport)."""
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
        )
        mcp_server = await self.repo.add(mcp_server)

        # Auto-discover tools after creating server
        # Uses http_auth_config_schema as credentials if provided
        auth_credentials = http_auth_config_schema if http_auth_config_schema else None
        tools, connection_result = await self.discover_and_sync_tools(mcp_server, auth_credentials)

        return MCPServerCreateResult(server=mcp_server, connection=connection_result)

    @validate_permissions(Permission.ADMIN)
    async def update_mcp_server(
        self,
        mcp_server_id: UUID,
        name: str | None = None,
        http_url: str | None = None,
        http_auth_type: str | None = None,
        description: str | None = None,
        http_auth_config_schema: dict | None = None,
        tags: list[str] | None = None,
        icon_url: str | None = None,
        documentation_url: str | None = None,
    ) -> MCPServer:
        """Update an MCP server in global catalog (admin only, uses Streamable HTTP transport)."""
        mcp_server = await self.repo.one(id=mcp_server_id)

        if name is not None:
            mcp_server.name = name
        if http_url is not None:
            mcp_server.http_url = http_url
        if http_auth_type is not None:
            mcp_server.http_auth_type = http_auth_type
        if description is not None:
            mcp_server.description = description
        if http_auth_config_schema is not None:
            mcp_server.http_auth_config_schema = http_auth_config_schema
        if tags is not None:
            mcp_server.tags = tags
        if icon_url is not None:
            mcp_server.icon_url = icon_url
        if documentation_url is not None:
            mcp_server.documentation_url = documentation_url

        return await self.repo.update(mcp_server)

    @validate_permissions(Permission.ADMIN)
    async def delete_mcp_server(self, mcp_server_id: UUID) -> None:
        """Delete an MCP server from global catalog (admin only)."""
        await self.repo.delete(id=mcp_server_id)

    async def discover_and_sync_tools(
        self,
        mcp_server: MCPServer,
        auth_credentials: dict[str, str] | None = None
    ) -> tuple[list[MCPServerTool], ConnectionResult]:
        """
        Connect to MCP server, discover tools, and sync them to database.

        Args:
            mcp_server: MCP server to discover tools from
            auth_credentials: Optional authentication credentials

        Returns:
            Tuple of (list of discovered and synced tools, connection result)
        """
        try:
            logger.info(f"Discovering tools for MCP server: {mcp_server.name}")

            # Connect to MCP server and list tools
            async with MCPClient(mcp_server, auth_credentials) as client:
                tool_defs = await client.list_tools()

            logger.info(f"Discovered {len(tool_defs)} tools from {mcp_server.name}")

            # Convert to domain entities and upsert
            synced_tools = []
            for tool_def in tool_defs:
                tool = MCPServerTool(
                    mcp_server_id=mcp_server.id,
                    name=tool_def["name"],
                    description=tool_def.get("description"),
                    input_schema=tool_def.get("input_schema"),
                    is_enabled_by_default=True,
                )

                # Upsert tool (update if exists, insert if new)
                synced_tool = await self.tool_repo.upsert_by_server_and_name(tool)
                synced_tools.append(synced_tool)

            logger.info(f"Synced {len(synced_tools)} tools for {mcp_server.name}")
            return synced_tools, ConnectionResult(
                success=True,
                tools_discovered=len(synced_tools)
            )

        except MCPClientError as e:
            # Connection/protocol error - provide user-friendly message
            error_msg = str(e)
            if "Connection refused" in error_msg:
                error_msg = f"Could not connect to {mcp_server.http_url}. Please verify the URL and that the server is running."
            elif "timed out" in error_msg.lower():
                error_msg = f"Connection to {mcp_server.http_url} timed out. The server may be slow or unreachable."
            logger.warning(f"Failed to discover tools for {mcp_server.name}: {e}")
            return [], ConnectionResult(success=False, error_message=error_msg)

        except Exception as e:
            logger.error(f"Failed to discover tools for {mcp_server.name}: {e}")
            return [], ConnectionResult(
                success=False,
                error_message=f"Failed to connect: {e}"
            )

    @validate_permissions(Permission.ADMIN)
    async def refresh_tools(
        self,
        mcp_server_id: UUID,
        auth_credentials: dict[str, str] | None = None
    ) -> tuple[list[MCPServerTool], ConnectionResult]:
        """
        Manually refresh tools for an MCP server (admin only).

        Args:
            mcp_server_id: ID of MCP server to refresh
            auth_credentials: Optional authentication credentials

        Returns:
            Tuple of (list of refreshed tools, connection result)
        """
        mcp_server = await self.repo.one(id=mcp_server_id)
        return await self.discover_and_sync_tools(mcp_server, auth_credentials)

    @validate_permissions(Permission.ADMIN)
    async def update_tool_default_enabled(
        self,
        tool_id: UUID,
        is_enabled: bool
    ) -> MCPServerTool:
        """
        Update the global default enabled status for a tool (admin only).

        Args:
            tool_id: ID of the tool to update
            is_enabled: Whether tool should be enabled by default

        Returns:
            Updated tool
        """
        tool = await self.tool_repo.one(id=tool_id)
        tool.is_enabled_by_default = is_enabled
        return await self.tool_repo.update(tool)

    @validate_permissions(Permission.ADMIN)
    async def update_tenant_tool_enabled(
        self,
        tool_id: UUID,
        is_enabled: bool
    ) -> MCPServerTool:
        """
        Update tenant-level enablement for a tool (admin only).
        Creates or updates a record in mcp_server_tool_settings.

        Args:
            tool_id: ID of the tool to update
            is_enabled: Whether tool should be enabled for this tenant

        Returns:
            Tool with updated tenant setting applied
        """
        from intric.database.tables.mcp_server_table import MCPServerToolSettings

        # Verify tool exists
        tool = await self.tool_repo.one(id=tool_id)

        # Upsert tenant tool setting
        from datetime import datetime, timezone
        from sqlalchemy.dialects.postgresql import insert

        now = datetime.now(timezone.utc)
        stmt = insert(MCPServerToolSettings).values(
            tenant_id=self.user.tenant_id,
            mcp_server_tool_id=tool_id,
            is_enabled=is_enabled,
            created_at=now,
            updated_at=now
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=['tenant_id', 'mcp_server_tool_id'],
            set_={
                'is_enabled': is_enabled,
                'updated_at': now
            }
        )

        await self.repo.session.execute(stmt)
        await self.repo.session.commit()

        # Return tool with tenant setting applied
        tool.is_enabled_by_default = is_enabled
        return tool

    async def get_tools_with_tenant_settings(
        self,
        mcp_server_id: UUID
    ) -> list[MCPServerTool]:
        """
        Get all tools for an MCP server with tenant-level settings applied.

        Args:
            mcp_server_id: ID of the MCP server

        Returns:
            List of tools with effective tenant-level enablement
        """
        import sqlalchemy as sa
        from intric.database.tables.mcp_server_table import MCPServerToolSettings

        # Get all tools for this server
        tools = await self.tool_repo.by_server(mcp_server_id)

        # Load tenant-level tool settings
        tenant_settings_query = (
            sa.select(MCPServerToolSettings)
            .where(MCPServerToolSettings.tenant_id == self.user.tenant_id)
        )
        tenant_settings_result = await self.repo.session.execute(tenant_settings_query)
        tenant_settings_db = tenant_settings_result.scalars().all()

        # Create map: tool_id -> is_enabled (tenant level)
        tenant_tool_settings = {
            setting.mcp_server_tool_id: setting.is_enabled
            for setting in tenant_settings_db
        }

        # Apply tenant settings to tools
        for tool in tools:
            if tool.id in tenant_tool_settings:
                # Override with tenant setting
                tool.is_enabled_by_default = tenant_tool_settings[tool.id]

        return tools
