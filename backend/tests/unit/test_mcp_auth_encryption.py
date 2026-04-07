"""Unit tests for MCP server bearer token auth and credential encryption.

Tests cover:
- Encryption/decryption of auth config in MCPServerService
- Credential preservation on update (no credentials provided)
- Credential clearing when switching auth type to "none"
- has_credentials boolean and credential_preview in assemblers
- Proxy factory decryption of http_auth_config_schema
- Auth type literal validation (only "none" and "bearer")
- refresh_tools uses stored encrypted credentials
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from pydantic import ValidationError

from intric.mcp_servers.presentation.models import (
    MCPServerCreate,
    MCPServerPublic,
    MCPServerUpdate,
)
from intric.settings.encryption_service import EncryptionService


# =============================================================================
# Helpers
# =============================================================================


def _make_encryption_service() -> EncryptionService:
    """Create an EncryptionService with a real Fernet key for testing."""
    from cryptography.fernet import Fernet

    key = Fernet.generate_key().decode()
    return EncryptionService(key)


def _make_service(encryption_service=None):
    """Create an MCPServerService with mocked repos."""
    from intric.mcp_servers.application.mcp_server_service import MCPServerService

    mock_repo = AsyncMock()
    mock_tool_repo = AsyncMock()
    mock_user = MagicMock()
    mock_user.tenant_id = uuid4()
    mock_user.permissions = ["admin"]

    service = MCPServerService(
        mcp_server_repo=mock_repo,
        mcp_server_tool_repo=mock_tool_repo,
        user=mock_user,
        encryption_service=encryption_service,
    )
    return service, mock_repo, mock_tool_repo


# =============================================================================
# Auth type validation
# =============================================================================


class TestAuthTypeLiterals:
    """Test that only 'none' and 'bearer' are accepted."""

    def test_create_accepts_none(self):
        dto = MCPServerCreate(name="test", http_url="http://localhost:8080")
        assert dto.http_auth_type == "none"

    def test_create_accepts_bearer(self):
        dto = MCPServerCreate(
            name="test",
            http_url="http://localhost:8080",
            http_auth_type="bearer",
        )
        assert dto.http_auth_type == "bearer"

    def test_create_rejects_api_key(self):
        with pytest.raises(ValidationError):
            MCPServerCreate(
                name="test",
                http_url="http://localhost:8080",
                http_auth_type="api_key",
            )

    def test_create_rejects_custom_headers(self):
        with pytest.raises(ValidationError):
            MCPServerCreate(
                name="test",
                http_url="http://localhost:8080",
                http_auth_type="custom_headers",
            )

    def test_update_accepts_bearer(self):
        dto = MCPServerUpdate(http_auth_type="bearer")
        assert dto.http_auth_type == "bearer"

    def test_update_rejects_api_key(self):
        with pytest.raises(ValidationError):
            MCPServerUpdate(http_auth_type="api_key")


# =============================================================================
# MCPServerPublic has_credentials field
# =============================================================================


class TestMCPServerPublicHasCredentials:
    """Test has_credentials field instead of raw config."""

    def test_has_credentials_true(self):
        dto = MCPServerPublic(
            id=uuid4(),
            name="test",
            description=None,
            http_url="http://localhost:8080",
            http_auth_type="bearer",
            has_credentials=True,
            tags=None,
            icon_url=None,
            documentation_url=None,
        )
        assert dto.has_credentials is True

    def test_has_credentials_false(self):
        dto = MCPServerPublic(
            id=uuid4(),
            name="test",
            description=None,
            http_url="http://localhost:8080",
            http_auth_type="none",
            has_credentials=False,
            tags=None,
            icon_url=None,
            documentation_url=None,
        )
        assert dto.has_credentials is False

    def test_no_http_auth_config_schema_field(self):
        """Ensure http_auth_config_schema is not exposed in MCPServerPublic."""
        dto = MCPServerPublic(
            id=uuid4(),
            name="test",
            description=None,
            http_url="http://localhost:8080",
            http_auth_type="none",
            has_credentials=False,
            tags=None,
            icon_url=None,
            documentation_url=None,
        )
        assert "http_auth_config_schema" not in dto.model_fields


# =============================================================================
# Encryption helpers in service
# =============================================================================


class TestServiceEncryptionHelpers:
    """Test _encrypt_auth_config and _decrypt_auth_config."""

    def test_encrypt_bearer_token(self):
        enc = _make_encryption_service()
        service, _, _ = _make_service(encryption_service=enc)

        config = {"token": "my-bearer-token-123"}
        encrypted = service._encrypt_auth_config(config)

        assert encrypted is not None
        assert encrypted["token"].startswith("enc:fernet:v1:")

    def test_decrypt_bearer_token(self):
        enc = _make_encryption_service()
        service, _, _ = _make_service(encryption_service=enc)

        config = {"token": "my-bearer-token-123"}
        encrypted = service._encrypt_auth_config(config)
        decrypted = service._decrypt_auth_config(encrypted)

        assert decrypted["token"] == "my-bearer-token-123"

    def test_encrypt_returns_none_for_none(self):
        enc = _make_encryption_service()
        service, _, _ = _make_service(encryption_service=enc)

        assert service._encrypt_auth_config(None) is None

    def test_decrypt_returns_none_for_none(self):
        enc = _make_encryption_service()
        service, _, _ = _make_service(encryption_service=enc)

        assert service._decrypt_auth_config(None) is None

    def test_encrypt_without_encryption_service(self):
        """Without encryption service, config passes through unchanged."""
        service, _, _ = _make_service(encryption_service=None)

        config = {"token": "my-bearer-token"}
        result = service._encrypt_auth_config(config)

        assert result["token"] == "my-bearer-token"

    def test_decrypt_plaintext_without_encryption_service(self):
        """Without encryption service, plaintext config passes through."""
        service, _, _ = _make_service(encryption_service=None)

        config = {"token": "my-bearer-token"}
        result = service._decrypt_auth_config(config)

        assert result["token"] == "my-bearer-token"


# =============================================================================
# Assembler has_credentials
# =============================================================================


class TestAssemblerHasCredentials:
    """Test assemblers compute has_credentials from http_auth_config_schema."""

    def test_from_domain_to_model_with_credentials(self):
        from intric.mcp_servers.presentation.assemblers.mcp_server_assembler import (
            MCPServerAssembler,
        )

        server = MagicMock()
        server.id = uuid4()
        server.name = "test"
        server.description = None
        server.http_url = "http://localhost"
        server.http_auth_type = "bearer"
        server.http_auth_config_schema = {"token": "enc:fernet:v1:xxx"}
        server.tags = None
        server.icon_url = None
        server.documentation_url = None
        server.security_classification = None

        assembler = MCPServerAssembler()
        dto = assembler.from_domain_to_model(server)
        assert dto.has_credentials is True

    def test_from_domain_to_model_without_credentials(self):
        from intric.mcp_servers.presentation.assemblers.mcp_server_assembler import (
            MCPServerAssembler,
        )

        server = MagicMock()
        server.id = uuid4()
        server.name = "test"
        server.description = None
        server.http_url = "http://localhost"
        server.http_auth_type = "none"
        server.http_auth_config_schema = None
        server.tags = None
        server.icon_url = None
        server.documentation_url = None
        server.security_classification = None

        assembler = MCPServerAssembler()
        dto = assembler.from_domain_to_model(server)
        assert dto.has_credentials is False
        assert dto.credential_preview is None

    def test_settings_assembler_with_credentials(self):
        from intric.mcp_servers.presentation.assemblers.mcp_server_assembler import (
            MCPServerSettingsAssembler,
        )

        server = MagicMock()
        server.id = uuid4()
        server.name = "test"
        server.description = None
        server.http_url = "http://localhost"
        server.http_auth_type = "bearer"
        server.http_auth_config_schema = {"token": "enc:fernet:v1:xxx"}
        server.tags = None
        server.icon_url = None
        server.documentation_url = None
        server.security_classification = None
        server.is_enabled = True
        server.tools = []

        assembler = MCPServerSettingsAssembler()
        dto = assembler.from_domain_to_model(server)
        assert dto.has_credentials is True

    def test_settings_assembler_without_credentials(self):
        from intric.mcp_servers.presentation.assemblers.mcp_server_assembler import (
            MCPServerSettingsAssembler,
        )

        server = MagicMock()
        server.id = uuid4()
        server.name = "test"
        server.description = None
        server.http_url = "http://localhost"
        server.http_auth_type = "none"
        server.http_auth_config_schema = None
        server.tags = None
        server.icon_url = None
        server.documentation_url = None
        server.security_classification = None
        server.is_enabled = False
        server.tools = []

        assembler = MCPServerSettingsAssembler()
        dto = assembler.from_domain_to_model(server)
        assert dto.has_credentials is False
        assert dto.credential_preview is None

    def test_credential_preview_with_encryption(self):
        """Test that credential_preview shows masked token when encryption is available."""
        from intric.mcp_servers.presentation.assemblers.mcp_server_assembler import (
            MCPServerAssembler,
        )

        enc = _make_encryption_service()
        encrypted_token = enc.encrypt("my-secret-bearer-token-12345")

        server = MagicMock()
        server.id = uuid4()
        server.name = "test"
        server.description = None
        server.http_url = "http://localhost"
        server.http_auth_type = "bearer"
        server.http_auth_config_schema = {"token": encrypted_token}
        server.tags = None
        server.icon_url = None
        server.documentation_url = None
        server.security_classification = None

        assembler = MCPServerAssembler(encryption_service=enc)
        dto = assembler.from_domain_to_model(server)
        assert dto.has_credentials is True
        assert dto.credential_preview is not None
        # Should end with last 4 chars of the original token
        assert dto.credential_preview.endswith("2345")
        # Should contain masking characters
        assert "*" in dto.credential_preview

    def test_credential_preview_without_encryption_service(self):
        """Test that credential_preview still works with plaintext tokens."""
        from intric.mcp_servers.presentation.assemblers.mcp_server_assembler import (
            MCPServerAssembler,
        )

        server = MagicMock()
        server.id = uuid4()
        server.name = "test"
        server.description = None
        server.http_url = "http://localhost"
        server.http_auth_type = "bearer"
        server.http_auth_config_schema = {"token": "plaintext-token-5678"}
        server.tags = None
        server.icon_url = None
        server.documentation_url = None
        server.security_classification = None

        assembler = MCPServerAssembler(encryption_service=None)
        dto = assembler.from_domain_to_model(server)
        assert dto.has_credentials is True
        assert dto.credential_preview is not None
        assert dto.credential_preview.endswith("5678")
        assert "*" in dto.credential_preview


# =============================================================================
# Proxy factory decryption
# =============================================================================


class TestProxyFactoryDecryption:
    """Test MCPProxySessionFactory reads and decrypts http_auth_config_schema."""

    def test_creates_auth_map_from_http_auth_config_schema(self):
        from intric.mcp_servers.infrastructure.proxy.mcp_proxy_factory import (
            MCPProxySessionFactory,
        )

        server = MagicMock()
        server.id = uuid4()
        server.name = "test"
        server.http_url = "http://localhost"
        server.http_auth_type = "bearer"
        server.http_auth_config_schema = {
            "token": "my-bearer-token",
        }
        server.tools = []

        factory = MCPProxySessionFactory(encryption_service=None)
        proxy = factory.create([server])

        # Auth map should contain the server's credentials
        assert server.id in proxy.auth_credentials_map
        assert proxy.auth_credentials_map[server.id]["token"] == "my-bearer-token"

    def test_decrypts_encrypted_credentials(self):
        from intric.mcp_servers.infrastructure.proxy.mcp_proxy_factory import (
            MCPProxySessionFactory,
        )

        enc = _make_encryption_service()
        encrypted_token = enc.encrypt("sk-secret-123")

        server = MagicMock()
        server.id = uuid4()
        server.name = "test"
        server.http_url = "http://localhost"
        server.http_auth_type = "bearer"
        server.http_auth_config_schema = {
            "token": encrypted_token,
        }
        server.tools = []

        factory = MCPProxySessionFactory(encryption_service=enc)
        proxy = factory.create([server])

        assert proxy.auth_credentials_map[server.id]["token"] == "sk-secret-123"

    def test_skips_servers_without_credentials(self):
        from intric.mcp_servers.infrastructure.proxy.mcp_proxy_factory import (
            MCPProxySessionFactory,
        )

        server = MagicMock()
        server.id = uuid4()
        server.name = "public-server"
        server.http_url = "http://localhost"
        server.http_auth_type = "none"
        server.http_auth_config_schema = None
        server.tools = []

        factory = MCPProxySessionFactory(encryption_service=None)
        proxy = factory.create([server])

        assert server.id not in proxy.auth_credentials_map


# =============================================================================
# Update connection validation
# =============================================================================


class TestUpdateConnectionValidation:
    """Test that update_mcp_server validates connection before saving when
    connection-affecting fields (http_url, http_auth_type, credentials) change."""

    @pytest.fixture
    def _setup(self):
        """Set up service with mocked repo and connection test."""
        from intric.mcp_servers.domain.entities.mcp_server import MCPServer

        enc = _make_encryption_service()
        service, mock_repo, _ = _make_service(encryption_service=enc)

        existing = MCPServer(
            tenant_id=service.user.tenant_id,
            name="test",
            http_url="http://localhost:8080",
            http_auth_type="bearer",
            http_auth_config_schema={"token": enc.encrypt("old-token")},
        )
        # Give it a fake id
        existing.id = uuid4()
        mock_repo.one.return_value = existing
        mock_repo.update.return_value = existing

        return service, mock_repo, existing, enc

    @pytest.mark.asyncio
    async def test_rejects_update_when_url_change_fails_connection(self, _setup):
        """Changing URL triggers validation; failure blocks the update."""
        from intric.mcp_servers.application.mcp_server_service import ConnectionResult

        service, mock_repo, existing, _ = _setup

        service._test_connection_and_discover_tools = AsyncMock(
            return_value=([], ConnectionResult(success=False, error_message="Connection refused"))
        )

        result = await service.update_mcp_server(
            mcp_server_id=existing.id,
            http_url="http://bad-host:9999",
        )

        assert result.connection is not None
        assert result.connection.success is False
        assert "Connection refused" in result.connection.error_message
        # Should NOT have saved
        mock_repo.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_allows_update_when_url_change_passes_connection(self, _setup):
        """Changing URL triggers validation; success allows the update."""
        from intric.mcp_servers.application.mcp_server_service import ConnectionResult

        service, mock_repo, existing, _ = _setup

        service._test_connection_and_discover_tools = AsyncMock(
            return_value=([], ConnectionResult(success=True, tools_discovered=3))
        )

        result = await service.update_mcp_server(
            mcp_server_id=existing.id,
            http_url="http://new-host:8080",
        )

        assert result.connection is None or result.connection.success is not False
        mock_repo.update.assert_called_once()

    @pytest.mark.asyncio
    async def test_rejects_update_when_auth_type_change_fails(self, _setup):
        """Changing auth type from bearer to none triggers validation."""
        from intric.mcp_servers.application.mcp_server_service import ConnectionResult

        service, mock_repo, existing, _ = _setup

        service._test_connection_and_discover_tools = AsyncMock(
            return_value=([], ConnectionResult(success=False, error_message="Unauthorized"))
        )

        result = await service.update_mcp_server(
            mcp_server_id=existing.id,
            http_auth_type="none",
        )

        assert result.connection is not None
        assert result.connection.success is False
        mock_repo.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_validation_for_non_connection_changes(self, _setup):
        """Changing only name/description does NOT trigger connection validation."""
        from intric.mcp_servers.application.mcp_server_service import ConnectionResult

        service, mock_repo, existing, _ = _setup

        service._test_connection_and_discover_tools = AsyncMock(
            return_value=([], ConnectionResult(success=False, error_message="should not be called"))
        )

        result = await service.update_mcp_server(
            mcp_server_id=existing.id,
            name="renamed",
            description="updated description",
        )

        # Should save without validation
        assert result.connection is None
        mock_repo.update.assert_called_once()
        service._test_connection_and_discover_tools.assert_not_called()

    @pytest.mark.asyncio
    async def test_rejects_credential_update_when_connection_fails(self, _setup):
        """Providing new credentials triggers validation."""
        from intric.mcp_servers.application.mcp_server_service import ConnectionResult

        service, mock_repo, existing, _ = _setup

        service._test_connection_and_discover_tools = AsyncMock(
            return_value=([], ConnectionResult(success=False, error_message="Invalid token"))
        )

        result = await service.update_mcp_server(
            mcp_server_id=existing.id,
            http_auth_config_schema={"token": "bad-token"},
        )

        assert result.connection is not None
        assert result.connection.success is False
        assert "Invalid token" in result.connection.error_message
        mock_repo.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_uses_plaintext_new_credentials_for_test(self, _setup):
        """When new credentials are provided, they are used in plaintext for the connection test."""
        from intric.mcp_servers.application.mcp_server_service import ConnectionResult

        service, mock_repo, existing, _ = _setup

        service._test_connection_and_discover_tools = AsyncMock(
            return_value=([], ConnectionResult(success=True, tools_discovered=2))
        )

        await service.update_mcp_server(
            mcp_server_id=existing.id,
            http_auth_config_schema={"token": "new-token"},
        )

        # Verify the test was called with plaintext credentials
        call_args = service._test_connection_and_discover_tools.call_args
        test_credentials = call_args[0][1]  # second positional arg
        assert test_credentials == {"token": "new-token"}

    @pytest.mark.asyncio
    async def test_decrypts_existing_credentials_for_url_change_test(self, _setup):
        """When URL changes but credentials don't, existing encrypted credentials are decrypted for the test."""
        from intric.mcp_servers.application.mcp_server_service import ConnectionResult

        service, mock_repo, existing, _ = _setup

        service._test_connection_and_discover_tools = AsyncMock(
            return_value=([], ConnectionResult(success=True, tools_discovered=2))
        )

        await service.update_mcp_server(
            mcp_server_id=existing.id,
            http_url="http://new-host:8080",
        )

        # Verify decrypted existing credentials were used
        call_args = service._test_connection_and_discover_tools.call_args
        test_credentials = call_args[0][1]
        assert test_credentials["token"] == "old-token"

    @pytest.mark.asyncio
    async def test_same_url_resent_does_not_trigger_validation(self, _setup):
        """Sending the same URL that's already stored should not trigger validation."""
        from intric.mcp_servers.application.mcp_server_service import ConnectionResult

        service, mock_repo, existing, _ = _setup

        service._test_connection_and_discover_tools = AsyncMock(
            return_value=([], ConnectionResult(success=False, error_message="should not be called"))
        )

        await service.update_mcp_server(
            mcp_server_id=existing.id,
            http_url="http://localhost:8080",  # same as existing
        )

        mock_repo.update.assert_called_once()
        service._test_connection_and_discover_tools.assert_not_called()
