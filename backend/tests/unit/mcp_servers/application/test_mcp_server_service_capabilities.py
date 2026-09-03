"""Unit tests for the capability-provider boundary of MCPServerService.

Covers, for every capability purpose (web search, image generation):
- purpose literal on create DTOs (general default, capability purposes accepted)
- capability servers are created inactive (activation is explicit)
- activation guards: purpose, usable tools, reachability
- atomic switch: activating one provider deactivates the previous one for
  the same purpose only
- usable-tool filtering that gates provider activation
"""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from eneo.main.exceptions import BadRequestException
from eneo.mcp_servers.application.mcp_server_service import (
    ConnectionResult,
    MCPServerService,
)
from eneo.mcp_servers.domain.entities.mcp_server import (
    CAPABILITY_PURPOSES,
    MCPServer,
    MCPServerTool,
)
from eneo.mcp_servers.presentation.models import MCPServerCreate, MCPServerPublic


def _make_service():
    mock_repo = AsyncMock()
    mock_repo.session = AsyncMock()
    mock_tool_repo = AsyncMock()
    mock_user = MagicMock()
    mock_user.tenant_id = uuid4()
    mock_user.permissions = ["admin"]

    service = MCPServerService(
        mcp_server_repo=mock_repo,
        mcp_server_tool_repo=mock_tool_repo,
        user=mock_user,
    )
    return service, mock_repo, mock_tool_repo, mock_user


def _make_server(tenant_id, purpose=CAPABILITY_PURPOSES[0], is_enabled=False):
    return MCPServer(
        id=uuid4(),
        tenant_id=tenant_id,
        name="Provider",
        http_url="http://provider.example/mcp",
        purpose=purpose,
        is_enabled=is_enabled,
    )


def _make_tool(
    *,
    enabled=True,
    removed=False,
    approved=True,
):
    return MCPServerTool(
        id=uuid4(),
        mcp_server_id=uuid4(),
        name="search",
        description="Search the web" if approved else None,
        input_schema={"type": "object"} if approved else None,
        is_enabled_by_default=enabled,
        removed_from_remote=removed,
        requires_approval=not approved,
    )


class TestPurposeModels:
    def test_create_defaults_to_general(self):
        dto = MCPServerCreate(name="t", http_url="http://localhost:1")
        assert dto.purpose == "general"

    @pytest.mark.parametrize("purpose", CAPABILITY_PURPOSES)
    def test_create_accepts_capability_purposes(self, purpose):
        dto = MCPServerCreate(name="t", http_url="http://localhost:1", purpose=purpose)
        assert dto.purpose == purpose

    def test_create_rejects_unknown_purpose(self):
        with pytest.raises(ValidationError):
            MCPServerCreate(name="t", http_url="http://localhost:1", purpose="search")

    def test_public_defaults_to_general(self):
        dto = MCPServerPublic(
            id=uuid4(),
            name="t",
            description=None,
            http_url="http://localhost:1",
            http_auth_type="none",
            has_credentials=False,
            tags=None,
            icon_url=None,
            documentation_url=None,
        )
        assert dto.purpose == "general"
        assert dto.is_enabled is True


class TestCreateCapabilityServer:
    @pytest.mark.parametrize("purpose", CAPABILITY_PURPOSES)
    async def test_capability_server_is_created_inactive(self, monkeypatch, purpose):
        service, mock_repo, _, _ = _make_service()
        monkeypatch.setattr(
            service,
            "_test_connection_and_discover_tools",
            AsyncMock(return_value=([], ConnectionResult(success=True))),
        )
        mock_repo.add.side_effect = lambda server: server

        result = await service.create_mcp_server(
            name="Provider",
            http_url="http://provider.example/mcp",
            purpose=purpose,
        )

        assert result.server.purpose == purpose
        assert result.server.is_enabled is False

    async def test_general_server_is_created_enabled(self, monkeypatch):
        service, mock_repo, _, _ = _make_service()
        monkeypatch.setattr(
            service,
            "_test_connection_and_discover_tools",
            AsyncMock(return_value=([], ConnectionResult(success=True))),
        )
        mock_repo.add.side_effect = lambda server: server

        result = await service.create_mcp_server(
            name="Tools",
            http_url="http://tools.example/mcp",
        )

        assert result.server.purpose == "general"
        assert result.server.is_enabled is True


class TestActivation:
    async def test_rejects_general_purpose_server(self):
        service, mock_repo, _, user = _make_service()
        server = _make_server(user.tenant_id, purpose="general")
        mock_repo.one.return_value = server

        with pytest.raises(BadRequestException):
            await service.activate_capability_server(server.id)

    async def test_rejects_server_without_usable_tools(self, monkeypatch):
        service, mock_repo, _, user = _make_service()
        server = _make_server(user.tenant_id)
        mock_repo.one.return_value = server
        monkeypatch.setattr(
            service,
            "get_tools_with_tenant_settings",
            AsyncMock(return_value=[_make_tool(approved=False)]),
        )

        with pytest.raises(BadRequestException):
            await service.activate_capability_server(server.id)

    async def test_rejects_unreachable_server(self, monkeypatch):
        service, mock_repo, _, user = _make_service()
        server = _make_server(user.tenant_id)
        mock_repo.one.return_value = server
        monkeypatch.setattr(
            service,
            "get_tools_with_tenant_settings",
            AsyncMock(return_value=[_make_tool()]),
        )
        monkeypatch.setattr(
            service,
            "_test_connection_and_discover_tools",
            AsyncMock(
                return_value=([], ConnectionResult(success=False, error_message="down"))
            ),
        )

        with pytest.raises(BadRequestException):
            await service.activate_capability_server(server.id)

    @pytest.mark.parametrize("purpose", CAPABILITY_PURPOSES)
    async def test_activation_deactivates_previous_provider(self, monkeypatch, purpose):
        service, mock_repo, _, user = _make_service()
        server = _make_server(user.tenant_id, purpose=purpose)
        previous_id = uuid4()
        mock_repo.one.return_value = server
        mock_repo.update.side_effect = lambda obj: obj
        execute_result = MagicMock()
        execute_result.fetchall.return_value = [(previous_id,)]
        mock_repo.session.execute.return_value = execute_result
        monkeypatch.setattr(
            service,
            "get_tools_with_tenant_settings",
            AsyncMock(return_value=[_make_tool()]),
        )
        monkeypatch.setattr(
            service,
            "_test_connection_and_discover_tools",
            AsyncMock(return_value=([], ConnectionResult(success=True))),
        )

        result = await service.activate_capability_server(server.id)

        assert result.server.is_enabled is True
        assert result.deactivated_server_ids == [previous_id]
        mock_repo.session.execute.assert_awaited_once()
        # The switch is scoped to this server's own purpose: a provider for
        # another capability must stay active.
        statement = mock_repo.session.execute.await_args.args[0]
        compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
        assert f"mcp_servers.purpose = '{purpose}'" in compiled

    @pytest.mark.parametrize("purpose", CAPABILITY_PURPOSES)
    async def test_deactivation_disables_server(self, purpose):
        service, mock_repo, _, user = _make_service()
        server = _make_server(user.tenant_id, purpose=purpose, is_enabled=True)
        mock_repo.one.return_value = server
        mock_repo.update.side_effect = lambda obj: obj

        deactivated = await service.deactivate_capability_server(server.id)

        assert deactivated.is_enabled is False

    async def test_deactivation_rejects_general_server(self):
        service, mock_repo, _, user = _make_service()
        server = _make_server(user.tenant_id, purpose="general", is_enabled=True)
        mock_repo.one.return_value = server

        with pytest.raises(BadRequestException):
            await service.deactivate_capability_server(server.id)

    async def test_activation_enforces_tenant_boundary(self):
        service, mock_repo, _, _ = _make_service()
        server = _make_server(uuid4())  # different tenant
        mock_repo.one.return_value = server

        from eneo.main.exceptions import UnauthorizedException

        with pytest.raises(UnauthorizedException):
            await service.activate_capability_server(server.id)


class TestUsableTools:
    def test_filters_disabled_removed_and_unapproved(self):
        service, _, _, _ = _make_service()
        usable = _make_tool()
        tools = [
            usable,
            _make_tool(enabled=False),
            _make_tool(removed=True),
            _make_tool(approved=False),
        ]

        assert service._usable_tools(tools) == [usable]
