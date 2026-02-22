from typing import TYPE_CHECKING, Any
from uuid import UUID

from intric.main.exceptions import BadRequestException, NotFoundException, UnauthorizedException
from intric.main.logging import get_logger
from intric.mcp_servers.domain.entities.mcp_server import MCPServer
from intric.roles.permissions import Permission, validate_permissions

if TYPE_CHECKING:
    from intric.mcp_servers.domain.repositories.mcp_server_repo import MCPServerRepository
    from intric.settings.encryption_service import EncryptionService
    from intric.users.user import UserInDB

logger = get_logger(__name__)


class _NoopEncryptionService:
    def is_active(self) -> bool:
        return False

    def is_encrypted(self, value: str) -> bool:
        return False

    def encrypt(self, plaintext: str) -> str:
        return plaintext

    def decrypt(self, ciphertext: str) -> str:
        return ciphertext


class MCPServerSettingsService:
    """Service for managing tenant-level MCP servers (simplified - no separate settings table)."""

    def __init__(
        self,
        mcp_server_repo: "MCPServerRepository",
        user: "UserInDB",
        encryption_service: "EncryptionService | None" = None,
    ):
        self.mcp_server_repo = mcp_server_repo
        self.user = user
        self.encryption_service = encryption_service or _NoopEncryptionService()

    @staticmethod
    def _validate_env_vars(env_vars: dict[str, Any] | None) -> dict[str, str] | None:
        if env_vars is None:
            return None
        validated: dict[str, str] = {}
        for key, value in env_vars.items():
            if not isinstance(value, str):
                raise BadRequestException("env_vars values must be strings")
            validated[key] = value
        return validated

    def _encrypt_env_vars(self, env_vars: dict[str, str] | None) -> dict[str, str] | None:
        if env_vars is None:
            return None
        if not self.encryption_service.is_active():
            return env_vars
        encrypted: dict[str, str] = {}
        for key, value in env_vars.items():
            encrypted[key] = (
                value
                if self.encryption_service.is_encrypted(value)
                else self.encryption_service.encrypt(value)
            )
        return encrypted

    def _decrypt_env_vars(self, env_vars: dict[str, str] | None) -> dict[str, str] | None:
        if env_vars is None:
            return None
        if not self.encryption_service.is_active():
            return env_vars
        decrypted: dict[str, str] = {}
        for key, value in env_vars.items():
            decrypted[key] = self.encryption_service.decrypt(value)
        return decrypted

    @validate_permissions(Permission.ADMIN)
    async def get_available_mcp_servers(self) -> list[MCPServer]:
        """Get all MCP servers for the current tenant (enabled and disabled)."""
        servers = await self.mcp_server_repo.query_by_tenant(tenant_id=self.user.tenant_id)
        for server in servers:
            status = "missing"
            if server.env_vars:
                try:
                    server.env_vars = self._decrypt_env_vars(server.env_vars)
                    status = "ok"
                except Exception:
                    logger.critical(
                        "Failed to decrypt MCP server env_vars",
                        extra={
                            "mcp_server_id": str(server.id),
                            "tenant_id": str(server.tenant_id),
                        },
                        exc_info=True,
                    )
                    server.env_vars = None
                    status = "decryption_failed"
            setattr(server, "credential_status", status)
        return servers

    @validate_permissions(Permission.ADMIN)
    async def create_mcp_server(
        self,
        name: str,
        http_url: str,
        http_auth_type: str = "none",
        description: str | None = None,
        http_auth_config_schema: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        icon_url: str | None = None,
        documentation_url: str | None = None,
        is_enabled: bool = True,
        env_vars: dict[str, Any] | None = None,
    ) -> MCPServer:
        """Create a new MCP server for the current tenant (uses Streamable HTTP transport)."""
        validated_env_vars = self._encrypt_env_vars(self._validate_env_vars(env_vars))
        mcp_server = MCPServer(
            tenant_id=self.user.tenant_id,
            name=name,
            http_url=http_url,
            http_auth_type=http_auth_type,
            description=description,
            http_auth_config_schema=http_auth_config_schema,
            tags=tags,
            icon_url=icon_url,
            documentation_url=documentation_url,
            is_enabled=is_enabled,
            env_vars=validated_env_vars,  # TODO: Encrypt sensitive values
        )

        return await self.mcp_server_repo.add(mcp_server)

    @validate_permissions(Permission.ADMIN)
    async def update_mcp_settings(
        self,
        mcp_server_id: UUID,
        is_org_enabled: bool | None = None,
        env_vars: dict[str, Any] | None = None,
    ) -> MCPServer:
        """Update MCP server settings (enablement and credentials)."""
        mcp_server = await self.mcp_server_repo.one(id=mcp_server_id)

        # Verify tenant ownership
        if mcp_server.tenant_id != self.user.tenant_id:
            raise UnauthorizedException()

        if is_org_enabled is not None:
            mcp_server.is_enabled = is_org_enabled
        if env_vars is not None:
            mcp_server.env_vars = self._encrypt_env_vars(
                self._validate_env_vars(env_vars)
            )
            # TODO: Encrypt sensitive values

        return await self.mcp_server_repo.update(mcp_server)

    @validate_permissions(Permission.ADMIN)
    async def get_mcp_server_with_settings(self, mcp_server_id: UUID) -> MCPServer:
        """Get a single MCP server settings record with safe credential status."""
        mcp_server = await self.mcp_server_repo.one(id=mcp_server_id)
        if mcp_server.tenant_id != self.user.tenant_id:
            raise UnauthorizedException()

        status = "missing"
        if mcp_server.env_vars:
            try:
                mcp_server.env_vars = self._decrypt_env_vars(
                    self._validate_env_vars(mcp_server.env_vars)
                )
                status = "ok"
            except Exception:
                logger.critical(
                    "Failed to decrypt MCP server env_vars",
                    extra={"mcp_server_id": str(mcp_server.id)},
                    exc_info=True,
                )
                mcp_server.env_vars = None
                status = "decryption_failed"
        setattr(mcp_server, "credential_status", status)
        return mcp_server

    @validate_permissions(Permission.ADMIN)
    async def delete_mcp_server(self, mcp_server_id: UUID) -> None:
        """Delete an MCP server for the current tenant."""
        mcp_server = await self.mcp_server_repo.one(id=mcp_server_id)

        # Verify tenant ownership
        if mcp_server.tenant_id != self.user.tenant_id:
            raise UnauthorizedException()

        await self.mcp_server_repo.delete(id=mcp_server_id)

    async def is_enabled_for_tenant(
        self, mcp_server_id: UUID, tenant_id: UUID
    ) -> bool:
        """Check if an MCP server is enabled for a specific tenant."""
        try:
            mcp_server = await self.mcp_server_repo.one(id=mcp_server_id)
            return mcp_server.tenant_id == tenant_id and mcp_server.is_enabled
        except NotFoundException:
            return False
