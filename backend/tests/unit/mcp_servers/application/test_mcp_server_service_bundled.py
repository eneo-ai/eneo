"""Unit tests for bundled tool runtime servers in MCPServerService.

A bundled server is an ordinary server whose URL and credential come from the
deployment (tool_runtime_url / tool_runtime_token). Each runtime endpoint fixes
the purpose its row serves and whether identity is forwarded. Only the preset
creates one, at most once per tenant and tool, and its connection cannot be
edited afterwards.
"""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.main.config import get_settings
from eneo.main.exceptions import (
    BadRequestException,
    NameCollisionException,
    NotFoundException,
)
from eneo.mcp_servers.application.mcp_server_service import (
    ConnectionResult,
    MCPServerService,
)
from eneo.mcp_servers.domain.entities.mcp_server import BUNDLED_AUTH_TYPE, MCPServer
from eneo.mcp_servers.infrastructure.client import mcp_client as client_module

RUNTIME_URL = "http://tool-runtime:3010"


@pytest.fixture
def runtime_configured(monkeypatch):
    settings = get_settings().model_copy(
        update={"tool_runtime_url": RUNTIME_URL, "tool_runtime_token": "t" * 40}
    )
    monkeypatch.setattr(client_module, "get_settings", lambda: settings)


def _make_service(monkeypatch):
    repo = AsyncMock()
    repo.query.return_value = []
    repo.add.side_effect = lambda server: server
    user = MagicMock()
    user.tenant_id = uuid4()
    user.permissions = ["admin"]
    service = MCPServerService(
        mcp_server_repo=repo, mcp_server_tool_repo=AsyncMock(), user=user
    )
    monkeypatch.setattr(
        service,
        "_test_connection_and_discover_tools",
        AsyncMock(return_value=([], ConnectionResult(success=True))),
    )
    return service, repo, user


def _bundled_server(tenant_id, tool="compute"):
    return MCPServer(
        id=uuid4(),
        tenant_id=tenant_id,
        name="Compute",
        http_url=f"{RUNTIME_URL}/mcp/{tool}",
        http_auth_type=BUNDLED_AUTH_TYPE,
    )


class TestCreateBundled:
    async def test_creates_a_general_server_without_credentials(
        self, monkeypatch, runtime_configured
    ):
        service, _, _ = _make_service(monkeypatch)

        result = await service.create_bundled_mcp_server("compute")

        server = result.server
        assert server.name == "Compute"
        assert server.http_url == f"{RUNTIME_URL}/mcp/compute"
        assert server.http_auth_type == BUNDLED_AUTH_TYPE
        assert server.http_auth_config_schema is None
        assert server.purpose == "general"
        assert server.is_enabled is True
        assert server.forward_identity is False

    async def test_requires_a_configured_runtime(self, monkeypatch):
        settings = get_settings().model_copy(
            update={"tool_runtime_url": RUNTIME_URL, "tool_runtime_token": None}
        )
        monkeypatch.setattr(client_module, "get_settings", lambda: settings)
        service, repo, _ = _make_service(monkeypatch)

        with pytest.raises(BadRequestException):
            await service.create_bundled_mcp_server("compute")
        repo.add.assert_not_called()

    async def test_takes_the_name_the_admin_ui_gives_it(
        self, monkeypatch, runtime_configured
    ):
        service, _, _ = _make_service(monkeypatch)

        result = await service.create_bundled_mcp_server("compute", name=" Beräkning ")

        assert result.server.name == "Beräkning"

    async def test_rejects_unknown_tools(self, monkeypatch, runtime_configured):
        service, _, _ = _make_service(monkeypatch)

        with pytest.raises(NotFoundException):
            await service.create_bundled_mcp_server("shell")

    async def test_is_added_at_most_once_per_tenant(
        self, monkeypatch, runtime_configured
    ):
        service, repo, user = _make_service(monkeypatch)
        repo.query.return_value = [_bundled_server(user.tenant_id)]

        with pytest.raises(NameCollisionException):
            await service.create_bundled_mcp_server("compute")
        repo.add.assert_not_called()

    async def test_generic_create_cannot_attach_credentials(
        self, monkeypatch, runtime_configured
    ):
        service, _, _ = _make_service(monkeypatch)

        with pytest.raises(BadRequestException):
            await service.create_mcp_server(
                name="Compute",
                http_url=f"{RUNTIME_URL}/mcp/compute",
                http_auth_type=BUNDLED_AUTH_TYPE,
                http_auth_config_schema={"token": "stolen"},
            )


class TestCreateBundledTabular:
    async def test_is_an_inactive_capability_provider_with_identity(
        self, monkeypatch, runtime_configured
    ):
        service, _, _ = _make_service(monkeypatch)

        result = await service.create_bundled_mcp_server("file-analysis")

        server = result.server
        assert server.http_url == f"{RUNTIME_URL}/mcp/file-analysis"
        assert server.purpose == "file_analysis"
        assert server.is_enabled is False
        # The runtime scopes its parsed-file cache per tenant and user.
        assert server.forward_identity is True

    async def test_activate_switches_it_in(self, monkeypatch, runtime_configured):
        service, _, _ = _make_service(monkeypatch)
        activate = AsyncMock(
            side_effect=lambda server_id: MagicMock(
                server=MagicMock(id=server_id), deactivated_server_ids=[]
            )
        )
        monkeypatch.setattr(service, "activate_capability_server", activate)

        await service.create_bundled_mcp_server("file-analysis", activate=True)

        activate.assert_awaited_once()

    async def test_generic_create_cannot_repurpose_a_bundled_endpoint(
        self, monkeypatch, runtime_configured
    ):
        service, _, _ = _make_service(monkeypatch)

        with pytest.raises(BadRequestException):
            await service.create_mcp_server(
                name="Compute as search",
                http_url=f"{RUNTIME_URL}/mcp/compute",
                http_auth_type=BUNDLED_AUTH_TYPE,
                purpose="web_search",
            )


class TestListBundled:
    async def test_reports_purpose_availability_and_the_added_server(
        self, monkeypatch, runtime_configured
    ):
        service, repo, user = _make_service(monkeypatch)
        added = _bundled_server(user.tenant_id)
        repo.query.return_value = [added]

        tools = {tool.tool: tool for tool in await service.list_bundled_tools()}

        assert tools["compute"].purpose == "general"
        assert tools["compute"].available is True
        assert tools["compute"].mcp_server_id == added.id
        assert tools["file-analysis"].purpose == "file_analysis"
        assert tools["file-analysis"].mcp_server_id is None

    async def test_unconfigured_runtime_is_unavailable(self, monkeypatch):
        settings = get_settings().model_copy(update={"tool_runtime_url": None})
        monkeypatch.setattr(client_module, "get_settings", lambda: settings)
        service, _, _ = _make_service(monkeypatch)

        tools = await service.list_bundled_tools()

        assert all(tool.available is False for tool in tools)
        assert all(tool.mcp_server_id is None for tool in tools)


class TestUpdateBundled:
    @pytest.mark.parametrize(
        "change",
        [
            {"http_url": "http://elsewhere.example/mcp"},
            {"http_auth_type": "bearer", "http_auth_config_schema": {"token": "x"}},
            {"http_auth_config_schema": {"token": "x"}},
            {"forward_identity": True},
            {"purpose": "web_search"},
        ],
    )
    async def test_connection_is_managed_by_the_deployment(
        self, monkeypatch, runtime_configured, change
    ):
        service, repo, user = _make_service(monkeypatch)
        repo.one.return_value = _bundled_server(user.tenant_id)

        with pytest.raises(BadRequestException):
            await service.update_mcp_server(repo.one.return_value.id, **change)

    async def test_name_and_description_stay_editable(
        self, monkeypatch, runtime_configured
    ):
        service, repo, user = _make_service(monkeypatch)
        server = _bundled_server(user.tenant_id)
        repo.one.return_value = server
        repo.update.side_effect = lambda s: s

        result = await service.update_mcp_server(
            server.id, name="Beräkning", description="Exakta beräkningar"
        )

        assert result.server.name == "Beräkning"
        assert result.server.http_auth_type == BUNDLED_AUTH_TYPE

    async def test_an_external_server_cannot_become_bundled(
        self, monkeypatch, runtime_configured
    ):
        service, repo, user = _make_service(monkeypatch)
        server = _bundled_server(user.tenant_id)
        server.http_auth_type = "none"
        repo.one.return_value = server

        with pytest.raises(BadRequestException):
            await service.update_mcp_server(server.id, http_auth_type=BUNDLED_AUTH_TYPE)
