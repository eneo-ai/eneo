from abc import ABC, abstractmethod
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from intric.mcp_servers.domain.entities.mcp_server import MCPServer


class MCPServerRepository(ABC):
    """Abstract repository for MCP server operations."""

    @abstractmethod
    async def all(self) -> list["MCPServer"]:
        """Get all MCP servers."""
        ...

    @abstractmethod
    async def query(self, tags: list[str] | None = None) -> list["MCPServer"]:
        """Query MCP servers with optional tag filtering."""
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
