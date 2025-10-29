from typing import TYPE_CHECKING
from uuid import UUID

from intric.mcp_servers.domain.entities.mcp_server import MCPServer
from intric.roles.permissions import Permission, validate_permissions

if TYPE_CHECKING:
    from intric.mcp_servers.domain.repositories.mcp_server_repo import MCPServerRepository
    from intric.users.user import UserInDB


class MCPServerService:
    """Service for managing global MCP server catalog (admin only)."""

    def __init__(
        self,
        mcp_server_repo: "MCPServerRepository",
        user: "UserInDB",
    ):
        self.repo = mcp_server_repo
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
        server_type: str,
        description: str | None = None,
        npm_package: str | None = None,
        uvx_package: str | None = None,
        docker_image: str | None = None,
        http_url: str | None = None,
        config_schema: dict | None = None,
        tags: list[str] | None = None,
        icon_url: str | None = None,
        documentation_url: str | None = None,
    ) -> MCPServer:
        """Create a new MCP server in global catalog (admin only)."""
        mcp_server = MCPServer(
            name=name,
            server_type=server_type,
            description=description,
            npm_package=npm_package,
            uvx_package=uvx_package,
            docker_image=docker_image,
            http_url=http_url,
            config_schema=config_schema,
            tags=tags,
            icon_url=icon_url,
            documentation_url=documentation_url,
        )
        return await self.repo.add(mcp_server)

    @validate_permissions(Permission.ADMIN)
    async def update_mcp_server(
        self,
        mcp_server_id: UUID,
        name: str | None = None,
        description: str | None = None,
        server_type: str | None = None,
        npm_package: str | None = None,
        uvx_package: str | None = None,
        docker_image: str | None = None,
        http_url: str | None = None,
        config_schema: dict | None = None,
        tags: list[str] | None = None,
        icon_url: str | None = None,
        documentation_url: str | None = None,
    ) -> MCPServer:
        """Update an MCP server in global catalog (admin only)."""
        mcp_server = await self.repo.one(id=mcp_server_id)

        if name is not None:
            mcp_server.name = name
        if description is not None:
            mcp_server.description = description
        if server_type is not None:
            mcp_server.server_type = server_type
        if npm_package is not None:
            mcp_server.npm_package = npm_package
        if uvx_package is not None:
            mcp_server.uvx_package = uvx_package
        if docker_image is not None:
            mcp_server.docker_image = docker_image
        if http_url is not None:
            mcp_server.http_url = http_url
        if config_schema is not None:
            mcp_server.config_schema = config_schema
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
