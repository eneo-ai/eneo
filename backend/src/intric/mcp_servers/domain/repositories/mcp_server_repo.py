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
        self,
        tags: list[str] | None = None,
        include_space_scoped: bool = False,
        **filters: object,
    ) -> list["MCPServer"]:
        """Query MCP servers with optional tag filtering.

        By default returns tenant-wide entries only (``space_id IS NULL``).
        """
        ...

    @abstractmethod
    async def query_by_tenant(self, tenant_id: UUID) -> list["MCPServer"]:
        """Get tenant-wide MCP servers for a tenant (excludes space-private)."""
        ...

    @abstractmethod
    async def query_by_space(
        self, tenant_id: UUID, space_id: UUID
    ) -> list["MCPServer"]:
        """Get space-private MCP servers owned by a given space."""
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
    async def delete(self, id: UUID) -> bool:
        """Delete an MCP server."""
        ...
