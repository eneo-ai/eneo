"""Unit tests for MCP backend improvements.

Tests cover:
- P1: list_tools() error propagation
- P2: Tool name collision handling (skip + warn)
- P3: Bare except fix in is_enabled_for_tenant
- P4: Tenant ownership enforcement in get_tools_with_tenant_settings
- P5: URL validation in DTOs (AnyHttpUrl)
- P6: Tool ownership validation in space updates
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from pydantic import ValidationError

from intric.main.exceptions import (
    BadRequestException,
    NotFoundException,
    UnauthorizedException,
)
from intric.mcp_servers.infrastructure.client.mcp_client import (
    MCPClient,
    MCPClientError,
)
from intric.mcp_servers.infrastructure.proxy.mcp_proxy_session import MCPProxySession
from intric.mcp_servers.presentation.models import (
    MCPServerCreate,
    MCPServerPublic,
    MCPServerUpdate,
)


# =============================================================================
# P1: list_tools() error propagation
# =============================================================================


class TestMCPClientListToolsErrorPropagation:
    """Test that list_tools() propagates errors instead of returning empty list."""

    @pytest.mark.asyncio
    async def test_list_tools_raises_mcp_client_error_on_failure(self):
        """When list_tools fails, it should raise MCPClientError, not return []."""
        # Create a mock MCP server
        mock_server = MagicMock()
        mock_server.name = "test-server"
        mock_server.http_url = "http://localhost:8080"
        mock_server.http_auth_type = "none"

        client = MCPClient(mock_server)

        # Mock session to raise an error
        mock_session = AsyncMock()
        mock_session.list_tools.side_effect = Exception("Connection lost")
        client.session = mock_session

        # Should raise MCPClientError, not return []
        with pytest.raises(MCPClientError) as exc_info:
            await client.list_tools()

        assert "Failed to list tools" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_list_tools_raises_when_not_connected(self):
        """list_tools should raise when not connected."""
        mock_server = MagicMock()
        mock_server.name = "test-server"

        client = MCPClient(mock_server)
        # session is None (not connected)

        with pytest.raises(MCPClientError) as exc_info:
            await client.list_tools()

        assert "Not connected" in str(exc_info.value)


# =============================================================================
# P2: Tool name collision handling (skip + warn)
# =============================================================================


class TestMCPProxySessionToolCollision:
    """Test tool name collision handling - skip duplicate, keep first, log warning."""

    def _create_mock_server(self, name: str, tools: list[dict]) -> MagicMock:
        """Create a mock MCP server with tools."""
        server = MagicMock()
        server.id = uuid4()
        server.name = name
        server.http_url = "http://localhost:8080"

        mock_tools = []
        for tool_def in tools:
            tool = MagicMock()
            tool.name = tool_def["name"]
            tool.description = tool_def.get("description", "")
            tool.input_schema = tool_def.get("input_schema", {})
            tool.is_enabled_by_default = tool_def.get("is_enabled", True)
            mock_tools.append(tool)

        server.tools = mock_tools
        return server

    def test_collision_keeps_first_tool_skips_second(self):
        """When two tools sanitize to the same name, first wins, second is skipped."""
        # Both servers have same name, so tools will collide
        server1 = self._create_mock_server(
            "api_server", [{"name": "list-items", "description": "First server's list"}]
        )
        server2 = self._create_mock_server(
            "api_server",
            [{"name": "list-items", "description": "Second server's list"}],
        )

        with patch(
            "intric.mcp_servers.infrastructure.proxy.mcp_proxy_session.logger"
        ) as mock_logger:
            proxy = MCPProxySession([server1, server2])

            # Should only have 1 tool (the first one)
            assert proxy.get_tool_count() == 1

            # The registered tool should be from server1
            tools = proxy.get_tools_for_llm()
            assert len(tools) == 1
            assert tools[0]["function"]["description"] == "First server's list"

            # Warning should have been logged
            mock_logger.warning.assert_called()
            warning_msg = mock_logger.warning.call_args[0][0]
            assert "Tool collision" in warning_msg
            assert "skipped" in warning_msg

    def test_no_collision_with_different_server_names(self):
        """Tools from different servers don't collide if server names differ."""
        server1 = self._create_mock_server(
            "api_v1", [{"name": "list-items", "description": "V1 list"}]
        )
        server2 = self._create_mock_server(
            "api_v2", [{"name": "list-items", "description": "V2 list"}]
        )

        proxy = MCPProxySession([server1, server2])

        # Should have 2 tools (no collision due to different server prefixes)
        assert proxy.get_tool_count() == 2

        # Both tools should be registered (dashes preserved by sanitizer)
        tool_names = proxy.get_allowed_tool_names()
        assert "api_v1__list-items" in tool_names
        assert "api_v2__list-items" in tool_names

    def test_collision_with_special_characters_sanitized(self):
        """Tools with special chars that sanitize to same name still collide."""
        server1 = self._create_mock_server(
            "server", [{"name": "list.items", "description": "Dot version"}]
        )
        server2 = self._create_mock_server(
            "server", [{"name": "list@items", "description": "At version"}]
        )

        # Both "list.items" and "list@items" sanitize to "list_items"
        with patch(
            "intric.mcp_servers.infrastructure.proxy.mcp_proxy_session.logger"
        ) as mock_logger:
            proxy = MCPProxySession([server1, server2])

            # Should only have 1 tool
            assert proxy.get_tool_count() == 1

            # First one wins
            tools = proxy.get_tools_for_llm()
            assert tools[0]["function"]["description"] == "Dot version"

            # Warning logged
            mock_logger.warning.assert_called()


# =============================================================================
# P3: Bare except fix in is_enabled_for_tenant
# =============================================================================


class TestMCPServerSettingsServiceBareExceptFix:
    """Test that is_enabled_for_tenant only catches NotFoundException."""

    @pytest.mark.asyncio
    async def test_returns_false_for_not_found(self):
        """Should return False when server is not found."""
        from intric.mcp_servers.application.mcp_server_settings_service import (
            MCPServerSettingsService,
        )

        mock_repo = AsyncMock()
        mock_repo.one.side_effect = NotFoundException("Server not found")

        mock_user = MagicMock()
        mock_user.tenant_id = uuid4()

        service = MCPServerSettingsService(mock_repo, mock_user)

        result = await service.is_enabled_for_tenant(uuid4(), uuid4())
        assert result is False

    @pytest.mark.asyncio
    async def test_propagates_other_exceptions(self):
        """Should propagate exceptions other than NotFoundException."""
        from intric.mcp_servers.application.mcp_server_settings_service import (
            MCPServerSettingsService,
        )

        mock_repo = AsyncMock()
        mock_repo.one.side_effect = RuntimeError("Database connection failed")

        mock_user = MagicMock()
        mock_user.tenant_id = uuid4()

        service = MCPServerSettingsService(mock_repo, mock_user)

        # Should NOT catch and return False - should propagate
        with pytest.raises(RuntimeError) as exc_info:
            await service.is_enabled_for_tenant(uuid4(), uuid4())

        assert "Database connection failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_returns_true_when_enabled(self):
        """Should return True when server exists, matches tenant, and is enabled."""
        from intric.mcp_servers.application.mcp_server_settings_service import (
            MCPServerSettingsService,
        )

        tenant_id = uuid4()

        mock_server = MagicMock()
        mock_server.tenant_id = tenant_id
        mock_server.is_enabled = True

        mock_repo = AsyncMock()
        mock_repo.one.return_value = mock_server

        mock_user = MagicMock()
        mock_user.tenant_id = tenant_id

        service = MCPServerSettingsService(mock_repo, mock_user)

        result = await service.is_enabled_for_tenant(uuid4(), tenant_id)
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_disabled(self):
        """Should return False when server exists but is disabled."""
        from intric.mcp_servers.application.mcp_server_settings_service import (
            MCPServerSettingsService,
        )

        tenant_id = uuid4()

        mock_server = MagicMock()
        mock_server.tenant_id = tenant_id
        mock_server.is_enabled = False

        mock_repo = AsyncMock()
        mock_repo.one.return_value = mock_server

        mock_user = MagicMock()
        mock_user.tenant_id = tenant_id

        service = MCPServerSettingsService(mock_repo, mock_user)

        result = await service.is_enabled_for_tenant(uuid4(), tenant_id)
        assert result is False


# =============================================================================
# P4: Tenant ownership enforcement in get_tools_with_tenant_settings
# =============================================================================


class TestMCPServerServiceTenantOwnership:
    """Test tenant ownership check in get_tools_with_tenant_settings."""

    @pytest.mark.asyncio
    async def test_raises_unauthorized_for_different_tenant(self):
        """Should raise UnauthorizedException when server belongs to different tenant."""
        from intric.mcp_servers.application.mcp_server_service import MCPServerService

        user_tenant_id = uuid4()
        server_tenant_id = uuid4()  # Different tenant

        mock_server = MagicMock()
        mock_server.tenant_id = server_tenant_id

        mock_repo = AsyncMock()
        mock_repo.one.return_value = mock_server

        mock_tool_repo = AsyncMock()

        mock_user = MagicMock()
        mock_user.tenant_id = user_tenant_id

        service = MCPServerService(mock_repo, mock_tool_repo, mock_user)

        with pytest.raises(UnauthorizedException) as exc_info:
            await service.get_tools_with_tenant_settings(uuid4())

        assert "not accessible" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_raises_not_found_when_server_missing(self):
        """Should raise NotFoundException when server doesn't exist."""
        from intric.mcp_servers.application.mcp_server_service import MCPServerService

        mock_repo = AsyncMock()
        mock_repo.one.side_effect = NotFoundException("Server not found")

        mock_tool_repo = AsyncMock()

        mock_user = MagicMock()
        mock_user.tenant_id = uuid4()

        service = MCPServerService(mock_repo, mock_tool_repo, mock_user)

        with pytest.raises(NotFoundException):
            await service.get_tools_with_tenant_settings(uuid4())


# =============================================================================
# P5: URL validation in DTOs (AnyHttpUrl)
# =============================================================================


class TestMCPServerURLValidation:
    """Test URL validation in MCP server DTOs."""

    def test_create_with_valid_http_url(self):
        """Should accept valid HTTP URL."""
        dto = MCPServerCreate(
            name="test-server",
            http_url="http://localhost:8080/mcp",
        )
        assert str(dto.http_url) == "http://localhost:8080/mcp"

    def test_create_with_valid_https_url(self):
        """Should accept valid HTTPS URL."""
        dto = MCPServerCreate(
            name="test-server",
            http_url="https://api.example.com/mcp",
        )
        assert "https://api.example.com" in str(dto.http_url)

    def test_create_rejects_invalid_url(self):
        """Should reject invalid URL with 422."""
        with pytest.raises(ValidationError) as exc_info:
            MCPServerCreate(
                name="test-server",
                http_url="not a url",
            )

        errors = exc_info.value.errors()
        assert any("url" in str(e).lower() for e in errors)

    def test_create_rejects_non_http_scheme(self):
        """Should reject non-HTTP schemes."""
        with pytest.raises(ValidationError):
            MCPServerCreate(
                name="test-server",
                http_url="ftp://example.com/mcp",
            )

    def test_create_with_optional_urls(self):
        """Should accept optional URL fields."""
        dto = MCPServerCreate(
            name="test-server",
            http_url="http://localhost:8080",
            icon_url="https://example.com/icon.png",
            documentation_url="https://docs.example.com",
        )
        assert dto.icon_url is not None
        assert dto.documentation_url is not None

    def test_create_rejects_invalid_optional_url(self):
        """Should reject invalid optional URLs."""
        with pytest.raises(ValidationError):
            MCPServerCreate(
                name="test-server",
                http_url="http://localhost:8080",
                icon_url="not a url",
            )

    def test_update_with_valid_url(self):
        """Should accept valid URL in update."""
        dto = MCPServerUpdate(
            http_url="http://new-server:9090/mcp",
        )
        assert "new-server:9090" in str(dto.http_url)

    def test_update_rejects_invalid_url(self):
        """Should reject invalid URL in update."""
        with pytest.raises(ValidationError):
            MCPServerUpdate(
                http_url="invalid",
            )

    def test_public_accepts_non_url_strings(self):
        """Public DTO should accept raw string URLs without validation."""
        dto = MCPServerPublic(
            id=uuid4(),
            name="dev-server",
            description=None,
            http_url="localhost:3000",
            http_auth_type="none",
            http_auth_config_schema=None,
            tags=None,
            icon_url=None,
            documentation_url=None,
        )
        assert dto.http_url == "localhost:3000"

    def test_public_with_ip_address_string(self):
        """Public DTO should accept IP address strings."""
        dto = MCPServerPublic(
            id=uuid4(),
            name="dev-server",
            description=None,
            http_url="192.168.1.100:8080",
            http_auth_type="none",
            http_auth_config_schema=None,
            tags=None,
            icon_url=None,
            documentation_url=None,
        )
        assert dto.http_url == "192.168.1.100:8080"


# =============================================================================
# P6: Tool ownership validation in space updates
# =============================================================================


class TestSpaceRepoToolOwnershipValidation:
    """Test that _set_mcp_tools validates tool ownership."""

    @pytest.mark.asyncio
    async def test_rejects_invalid_tool_ids(self):
        """Should raise BadRequestException for tool IDs not belonging to selected servers."""
        from intric.spaces.space_repo import SpaceRepository

        # Create mock session with query support
        mock_session = AsyncMock()

        # When querying for valid tools, return empty (no valid tools)
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_session.execute.return_value = mock_result

        # Create minimal repo (we'll call _set_mcp_tools directly)
        repo = object.__new__(SpaceRepository)
        repo.session = mock_session

        mock_space_in_db = MagicMock()
        mock_space_in_db.id = uuid4()

        invalid_tool_id = uuid4()
        valid_server_id = uuid4()

        # Call _set_mcp_tools with a tool that doesn't belong to any selected server
        with pytest.raises(BadRequestException) as exc_info:
            await repo._set_mcp_tools(
                mock_space_in_db,
                tool_settings=[(invalid_tool_id, True)],
                valid_server_ids=[valid_server_id],
            )

        assert "Invalid tool IDs" in str(exc_info.value)
        assert str(invalid_tool_id) in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_accepts_valid_tool_ids(self):
        """Should accept tool IDs that belong to selected servers."""
        from intric.spaces.space_repo import SpaceRepository

        valid_tool_id = uuid4()
        valid_server_id = uuid4()

        # Create mock session
        mock_session = AsyncMock()

        # First execute: DELETE existing settings
        # Second execute: SELECT valid tools (returns our tool)
        # Third execute: INSERT new settings
        call_count = [0]

        async def mock_execute(stmt):
            call_count[0] += 1
            if call_count[0] == 2:  # Second call is the validation query
                mock_result = MagicMock()
                mock_result.fetchall.return_value = [(valid_tool_id,)]
                return mock_result
            return MagicMock()

        mock_session.execute = mock_execute

        repo = object.__new__(SpaceRepository)
        repo.session = mock_session

        mock_space_in_db = MagicMock()
        mock_space_in_db.id = uuid4()

        # Should NOT raise - tool is valid
        await repo._set_mcp_tools(
            mock_space_in_db,
            tool_settings=[(valid_tool_id, True)],
            valid_server_ids=[valid_server_id],
        )

        # Verify all three queries were executed (delete, select, insert)
        assert call_count[0] == 3

    @pytest.mark.asyncio
    async def test_empty_tool_settings_skips_validation(self):
        """Should handle empty tool settings without error."""
        from intric.spaces.space_repo import SpaceRepository

        mock_session = AsyncMock()

        repo = object.__new__(SpaceRepository)
        repo.session = mock_session

        mock_space_in_db = MagicMock()
        mock_space_in_db.id = uuid4()

        # Should not raise - empty list
        await repo._set_mcp_tools(
            mock_space_in_db,
            tool_settings=[],
            valid_server_ids=[],
        )

        # Only DELETE should have been called
        assert mock_session.execute.call_count == 1
