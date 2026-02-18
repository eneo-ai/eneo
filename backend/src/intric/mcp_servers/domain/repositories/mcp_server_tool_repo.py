from abc import ABC, abstractmethod
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from intric.mcp_servers.domain.entities.mcp_server import MCPServerTool


class MCPServerToolRepository(ABC):
    """Abstract repository for MCP server tool operations."""

    @abstractmethod
    async def all(self) -> list["MCPServerTool"]:
        """Get all MCP server tools."""
        ...

    @abstractmethod
    async def by_server(self, mcp_server_id: UUID) -> list["MCPServerTool"]:
        """Get all tools for a specific MCP server."""
        ...

    @abstractmethod
    async def one(self, id: UUID) -> "MCPServerTool":
        """Get one tool by ID. Raises if not found."""
        ...

    @abstractmethod
    async def one_or_none(self, id: UUID) -> "MCPServerTool | None":
        """Get one tool by ID or None."""
        ...

    @abstractmethod
    async def find_by_name(self, mcp_server_id: UUID, name: str) -> "MCPServerTool | None":
        """Find a tool by server ID and name."""
        ...

    @abstractmethod
    async def add(self, obj: "MCPServerTool") -> "MCPServerTool":
        """Add a new tool."""
        ...

    @abstractmethod
    async def add_many(self, objs: list["MCPServerTool"]) -> list["MCPServerTool"]:
        """Add multiple tools at once (bulk operation)."""
        ...

    @abstractmethod
    async def update(self, obj: "MCPServerTool") -> "MCPServerTool":
        """Update an existing tool."""
        ...

    @abstractmethod
    async def upsert_by_server_and_name(self, obj: "MCPServerTool") -> "MCPServerTool":
        """Upsert a tool (update if exists by server+name, insert otherwise)."""
        ...

    @abstractmethod
    async def delete(self, id: UUID) -> None:
        """Delete a tool."""
        ...

    @abstractmethod
    async def delete_by_server(self, mcp_server_id: UUID) -> None:
        """Delete all tools for a specific MCP server."""
        ...
