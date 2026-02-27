from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:
    from intric.mcp_servers.domain.entities.mcp_server import MCPServer


class MCPServerRepository(ABC):
    """Abstract repository for MCP server operations."""

    # Session for direct SQL operations (implementation detail exposed for service layer)
    session: Any

    @abstractmethod
    async def all(self) -> list["MCPServer"]:
        """Get all MCP servers."""
        ...

    @abstractmethod
    async def query(
        self, tags: list[str] | None = None, **filters: object
    ) -> list["MCPServer"]:
        """Query MCP servers with optional tag filtering."""
        ...

    @abstractmethod
    async def query_by_tenant(self, tenant_id: UUID) -> list["MCPServer"]:
        """Get all MCP servers for a specific tenant."""
        ...

    @abstractmethod
    async def one(self, id: UUID) -> "MCPServer":
        """Get one MCP server by ID. Raises if not found."""
        ...

    @abstractmethod
    async def one_or_none(self, id: UUID) -> "MCPServer | None":
        """Get one MCP server by ID or None."""
        ...

    @abstractmethod
    async def add(self, obj: "MCPServer") -> "MCPServer":
        """Add a new MCP server."""
        ...

    @abstractmethod
    async def update(self, obj: "MCPServer") -> "MCPServer":
        """Update an existing MCP server."""
        ...

    @abstractmethod
    async def delete(self, id: UUID) -> None:
        """Delete an MCP server."""
        ...
