from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Optional
from uuid import UUID

from eneo.mcp_servers.domain.entities.mcp_oauth_connection import (
    IdpUserToken,
    MCPOAuthClientRegistration,
    MCPOAuthConnection,
)


class MCPOAuthRepository(ABC):
    """Connections, client registrations and login ID tokens for OAuth servers."""

    @abstractmethod
    async def get_connection(
        self, *, mcp_server_id: UUID, user_id: Optional[UUID]
    ) -> Optional[MCPOAuthConnection]:
        """The user's connection, or the shared one when ``user_id`` is None."""
        ...

    @abstractmethod
    async def list_connections(
        self, *, mcp_server_ids: Sequence[UUID], user_id: Optional[UUID]
    ) -> list[MCPOAuthConnection]:
        """Connections for these servers: the user's rows, or shared rows."""
        ...

    @abstractmethod
    async def save_connection(
        self, connection: MCPOAuthConnection
    ) -> MCPOAuthConnection:
        """Insert or replace the row keyed by (server, user)."""
        ...

    @abstractmethod
    async def delete_connection(
        self, *, mcp_server_id: UUID, user_id: Optional[UUID]
    ) -> bool: ...

    @abstractmethod
    async def get_registration(
        self, *, mcp_server_id: UUID, issuer: str
    ) -> Optional[MCPOAuthClientRegistration]: ...

    @abstractmethod
    async def save_registration(
        self, registration: MCPOAuthClientRegistration
    ) -> MCPOAuthClientRegistration: ...

    @abstractmethod
    async def get_idp_token(self, *, user_id: UUID) -> Optional[IdpUserToken]: ...

    @abstractmethod
    async def save_idp_token(self, token: IdpUserToken) -> IdpUserToken: ...
