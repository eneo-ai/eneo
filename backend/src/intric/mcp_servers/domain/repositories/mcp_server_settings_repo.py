from abc import ABC, abstractmethod
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from intric.mcp_servers.domain.entities.mcp_server import MCPServerSettings


class MCPServerSettingsRepository(ABC):
    """Abstract repository for tenant MCP server settings."""

    @abstractmethod
    async def query(self, tenant_id: UUID) -> list["MCPServerSettings"]:
        """Get all MCP server settings for a tenant."""
        ...

    @abstractmethod
    async def one(self, tenant_id: UUID, mcp_server_id: UUID) -> "MCPServerSettings":
        """Get one setting. Raises if not found."""
        ...

    @abstractmethod
    async def one_or_none(
        self, tenant_id: UUID, mcp_server_id: UUID
    ) -> "MCPServerSettings | None":
        """Get one setting or None."""
        ...

    @abstractmethod
    async def add(self, obj: "MCPServerSettings") -> "MCPServerSettings":
        """Add/enable MCP server for tenant."""
        ...

    @abstractmethod
    async def update(self, obj: "MCPServerSettings") -> "MCPServerSettings":
        """Update tenant MCP server settings."""
        ...

    @abstractmethod
    async def delete(self, tenant_id: UUID, mcp_server_id: UUID) -> None:
        """Delete/disable MCP server for tenant."""
        ...
