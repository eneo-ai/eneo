"""Repository protocol for per-user MCP connection state lookups."""

from datetime import datetime
from typing import Protocol
from uuid import UUID


class MCPConnectionRepository(Protocol):
    """Read-only lookups backing the /me/mcp-connections read-out."""

    async def get_user_idp_issuers(self, user_id: UUID) -> set[str]:
        """Issuers (trailing-slash-normalized) with an active token row."""
        ...

    async def get_exchanged_tokens_by_server(
        self, *, tenant_id: UUID, user_id: UUID
    ) -> dict[UUID, datetime]:
        """Map of mcp_server_id -> expires_at for the caller's cached tokens.

        Covers both subject types: the user's own rows and the tenant
        service-account rows (which serve every user in the tenant).
        """
        ...
