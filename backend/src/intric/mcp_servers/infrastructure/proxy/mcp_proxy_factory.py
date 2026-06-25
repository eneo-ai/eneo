"""Factory for creating MCPProxySession instances with proper auth."""

import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from intric.mcp_servers.infrastructure.client.mcp_client import MCPClient
from intric.mcp_servers.infrastructure.proxy.mcp_proxy_session import MCPProxySession

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from intric.mcp_servers.domain.entities.mcp_server import MCPServer
    from intric.settings.encryption_service import EncryptionService

logger = logging.getLogger(__name__)


class MCPProxySessionFactory:
    """
    Factory for creating MCPProxySession instances.

    Handles:
    - Resolving auth credentials from server http_auth_config_schema
    - Decrypting encrypted credentials
    - Creating properly configured proxy sessions
    """

    def __init__(
        self,
        encryption_service: "EncryptionService | None" = None,
    ):
        super().__init__()
        self.encryption_service = encryption_service

    # Keys in http_auth_config_schema that contain secrets
    _SECRET_KEYS = ("token",)

    def _decrypt_auth_config(
        self, config: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        """Decrypt sensitive values in auth config for use."""
        if not config:
            return config

        decrypted = dict(config)
        for key in self._SECRET_KEYS:
            if key in decrypted and decrypted[key]:
                if self.encryption_service and self.encryption_service.is_encrypted(
                    decrypted[key]
                ):
                    decrypted[key] = self.encryption_service.decrypt(decrypted[key])
        return decrypted

    def create(
        self,
        mcp_servers: list["MCPServer"],
        chat_session_id: UUID | None = None,
        db_session: "AsyncSession | None" = None,
    ) -> MCPProxySession:
        """
        Create a new MCPProxySession for the given servers.

        Args:
            mcp_servers: List of MCP servers (already filtered by permissions)
            chat_session_id: The eneo chat session id. When set together with
                ``db_session``, each MCP server's protocol-assigned
                ``mcp-session-id`` is loaded before connect (so the server
                resumes the prior logical session) and re-upserted after
                ``initialize()``. Pass ``None`` for non-chat callers (testing,
                one-shot tool execution).
            db_session: Active SQLAlchemy session used to read/write
                ``chat_session_mcp_state``. Required only when
                ``chat_session_id`` is set.

        Returns:
            Configured MCPProxySession instance
        """
        # Build auth credentials map from server http_auth_config_schema
        auth_map: dict[UUID, dict[str, str]] = {}

        for server in mcp_servers:
            if server.http_auth_config_schema:
                decrypted = self._decrypt_auth_config(server.http_auth_config_schema)
                if decrypted:
                    auth_map[server.id] = decrypted
                    logger.debug(
                        f"[MCPProxyFactory] Loaded credentials for server {server.name}"
                    )

        logger.info(
            f"[MCPProxyFactory] Creating proxy session with {len(mcp_servers)} servers"
        )

        return MCPProxySession(
            mcp_servers=mcp_servers,
            auth_credentials_map=auth_map,
            chat_session_id=chat_session_id,
            db_session=db_session,
        )

    async def terminate(
        self,
        mcp_server: "MCPServer",
        mcp_session_id: str,
    ) -> None:
        """Terminate one persisted protocol session using server credentials."""
        credentials: dict[str, str] | None = None
        if mcp_server.http_auth_config_schema:
            decrypted = self._decrypt_auth_config(mcp_server.http_auth_config_schema)
            if decrypted:
                credentials = {key: str(value) for key, value in decrypted.items()}

        client = MCPClient(
            mcp_server=mcp_server,
            auth_credentials=credentials,
        )
        await client.terminate_protocol_session(mcp_session_id)
