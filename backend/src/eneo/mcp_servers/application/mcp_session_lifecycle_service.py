from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from uuid import UUID

from eneo.main.logging import get_logger
from eneo.mcp_servers.domain.repositories.mcp_server_repo import (
    MCPServerRepository,
)
from eneo.mcp_servers.infrastructure.identity_headers import build_identity_headers
from eneo.mcp_servers.infrastructure.proxy.mcp_proxy_factory import (
    MCPProxySessionFactory,
)
from eneo.mcp_servers.infrastructure.repo_impl.chat_session_mcp_state_repo_impl import (
    ChatSessionMcpStateRepo,
)

logger = get_logger(__name__)

if TYPE_CHECKING:
    from eneo.mcp_servers.domain.entities.mcp_server import MCPServer
    from eneo.users.user import UserInDB


class McpSessionLifecycleService:
    """Owns cleanup of remote MCP protocol sessions tied to a chat session."""

    def __init__(
        self,
        state_repo: ChatSessionMcpStateRepo,
        mcp_server_repo: MCPServerRepository,
        proxy_factory: MCPProxySessionFactory,
        user: "UserInDB | None" = None,
    ):
        self._state_repo = state_repo
        self._mcp_server_repo = mcp_server_repo
        self._proxy_factory = proxy_factory
        self._user = user

    async def terminate_for_chat_session(self, chat_session_id: UUID) -> None:
        states = await self._state_repo.list_for_chat_session(chat_session_id)
        if not states:
            return

        # Same identity as the chat requests that created these sessions, so a
        # forward_identity server accepts the DELETE. Empty in worker contexts
        # with no acting user; the client sends nothing for opted-out servers.
        identity_headers = build_identity_headers(self._user, None)

        targets: list[tuple[MCPServer, UUID, str]] = []
        for server_id, mcp_session_id in states:
            # SQLAlchemy AsyncSession is not safe for concurrent operations.
            # Resolve all DB entities serially, then parallelize only network I/O.
            server = await self._mcp_server_repo.one_or_none(id=server_id)
            if server is None or not server.http_url:
                logger.warning(
                    "Cannot terminate MCP session because server is unavailable",
                    extra={
                        "chat_session_id": str(chat_session_id),
                        "mcp_server_id": str(server_id),
                    },
                )
                continue
            targets.append((server, server_id, mcp_session_id))

        async def terminate(
            server: MCPServer, server_id: UUID, mcp_session_id: str
        ) -> None:
            try:
                await self._proxy_factory.terminate(
                    server, mcp_session_id, identity_headers=identity_headers
                )
            except Exception:
                # Local deletion must still complete. Server-side idle TTL is
                # the fallback when a remote server cannot be reached.
                logger.exception(
                    "Failed to terminate remote MCP session",
                    extra={
                        "chat_session_id": str(chat_session_id),
                        "mcp_server_id": str(server_id),
                    },
                )

        await asyncio.gather(
            *(
                terminate(server, server_id, session_id)
                for server, server_id, session_id in targets
            )
        )
