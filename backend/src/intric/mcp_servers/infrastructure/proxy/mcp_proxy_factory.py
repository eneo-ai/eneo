"""Factory for creating MCPProxySession instances with proper auth."""

import logging
from typing import TYPE_CHECKING
from uuid import UUID

from intric.mcp_servers.infrastructure.proxy.mcp_proxy_session import MCPProxySession

if TYPE_CHECKING:
    from intric.mcp_servers.domain.entities.mcp_server import MCPServer

logger = logging.getLogger(__name__)


class MCPProxySessionFactory:
    """
    Factory for creating MCPProxySession instances.

    Handles:
    - Resolving auth credentials from server env_vars
    - Creating properly configured proxy sessions
    """

    def create(
        self,
        mcp_servers: list["MCPServer"],
    ) -> MCPProxySession:
        """
        Create a new MCPProxySession for the given servers.

        Args:
            mcp_servers: List of MCP servers (already filtered by permissions)

        Returns:
            Configured MCPProxySession instance
        """
        # Build auth credentials map from server env_vars
        # env_vars contains the decrypted credentials for each server
        auth_map: dict[UUID, dict[str, str]] = {}

        for server in mcp_servers:
            if server.env_vars:
                auth_map[server.id] = server.env_vars
                logger.debug(
                    f"[MCPProxyFactory] Loaded credentials for server {server.name}"
                )

        logger.info(
            f"[MCPProxyFactory] Creating proxy session with {len(mcp_servers)} servers"
        )

        return MCPProxySession(
            mcp_servers=mcp_servers,
            auth_credentials_map=auth_map,
        )
