"""Unit tests for tenant-level MCP server settings.

A capability provider's enabled flag is its active-provider state and is
guarded by the single-active-provider index, so the per-tenant enable and
disable path must refuse it and leave the atomic switch as the only route.
"""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.main.exceptions import BadRequestException
from eneo.mcp_servers.application.mcp_server_settings_service import (
    MCPServerSettingsService,
)
from eneo.mcp_servers.domain.entities.mcp_server import (
    CAPABILITY_PURPOSES,
    MCPServer,
)


def _make_service():
    mock_repo = AsyncMock()
    mock_repo.update.side_effect = lambda obj: obj
    mock_user = MagicMock()
    mock_user.tenant_id = uuid4()
    mock_user.permissions = ["admin"]
    service = MCPServerSettingsService(mcp_server_repo=mock_repo, user=mock_user)
    return service, mock_repo, mock_user


def _make_server(tenant_id, purpose, is_enabled):
    return MCPServer(
        id=uuid4(),
        tenant_id=tenant_id,
        name="Server",
        http_url="http://server.example/mcp",
        purpose=purpose,
        is_enabled=is_enabled,
    )


class TestUpdateMcpSettings:
    @pytest.mark.parametrize("purpose", CAPABILITY_PURPOSES)
    @pytest.mark.parametrize("is_org_enabled", [True, False])
    async def test_refuses_to_toggle_capability_provider(self, purpose, is_org_enabled):
        service, mock_repo, user = _make_service()
        server = _make_server(user.tenant_id, purpose, is_enabled=not is_org_enabled)
        mock_repo.one.return_value = server

        with pytest.raises(BadRequestException):
            await service.update_mcp_settings(server.id, is_org_enabled=is_org_enabled)

        assert server.is_enabled is not is_org_enabled
        mock_repo.update.assert_not_awaited()

    async def test_toggles_general_server(self):
        service, mock_repo, user = _make_service()
        server = _make_server(user.tenant_id, "general", is_enabled=True)
        mock_repo.one.return_value = server

        updated = await service.update_mcp_settings(server.id, is_org_enabled=False)

        assert updated.is_enabled is False

    @pytest.mark.parametrize("purpose", CAPABILITY_PURPOSES)
    async def test_credentials_update_leaves_provider_state_alone(self, purpose):
        service, mock_repo, user = _make_service()
        server = _make_server(user.tenant_id, purpose, is_enabled=True)
        mock_repo.one.return_value = server

        updated = await service.update_mcp_settings(
            server.id, env_vars={"API_KEY": "secret"}
        )

        assert updated.is_enabled is True
