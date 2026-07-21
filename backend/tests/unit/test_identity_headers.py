"""Unit tests for per-server MCP identity-header forwarding (#5).

Covers the header builder's content/sanitization and that MCPClient forwards the
headers only when its own server opted in via ``forward_identity``.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import unquote
from uuid import uuid4

import httpx
import pytest
from mcp.shared._httpx_utils import create_mcp_http_client

from eneo.mcp_servers.application.mcp_server_service import MCPServerService
from eneo.mcp_servers.domain.entities.mcp_server import MCPServerTool
from eneo.mcp_servers.infrastructure.client.mcp_client import MCPClient
from eneo.mcp_servers.infrastructure.identity_headers import build_identity_headers
from eneo.mcp_servers.infrastructure.proxy.mcp_proxy_factory import (
    MCPProxySessionFactory,
)


def _user(**overrides):
    """A minimal user stand-in with the attributes the builder reads."""
    defaults = dict(
        id=uuid4(),
        email="anna.svensson@kommun.se",
        username="anna",
        tenant_id=uuid4(),
        roles=[SimpleNamespace(name="admin"), SimpleNamespace(name="editor")],
        tenant=SimpleNamespace(name="Kommun AB"),
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestBuildIdentityHeaders:
    def test_returns_empty_when_no_user(self):
        assert build_identity_headers(None, None) == {}

    def test_emits_all_headers_when_populated(self):
        user = _user()
        headers = build_identity_headers(user, user.tenant)

        assert headers["X-Eneo-User-Id"] == str(user.id)
        assert headers["X-Eneo-User-Email"] == "anna.svensson@kommun.se"
        assert headers["X-Eneo-User-Name"] == "anna"
        assert headers["X-Eneo-Tenant-Id"] == str(user.tenant_id)
        assert headers["X-Eneo-Tenant-Name"] == "Kommun AB"
        assert headers["X-Eneo-Role"] == "admin, editor"

    def test_username_falls_back_to_email_local_part(self):
        headers = build_identity_headers(_user(username=None), None)
        assert headers["X-Eneo-User-Name"] == "anna.svensson"

    def test_strips_crlf_to_prevent_header_injection(self):
        user = _user(username="anna\r\nX-Injected: evil")
        headers = build_identity_headers(user, user.tenant)
        assert "\r" not in headers["X-Eneo-User-Name"]
        assert "\n" not in headers["X-Eneo-User-Name"]

    def test_values_are_ascii_and_decode_back_to_the_original(self):
        # httpx encodes str header values as ASCII, so every emitted value must
        # be ASCII; percent-encoding keeps it lossless (unquote round-trips).
        user = _user(
            username="Åsa Öberg \U0001f600",
            tenant=SimpleNamespace(name="Härnösands kommun"),
        )
        headers = build_identity_headers(user, user.tenant)
        for value in headers.values():
            value.encode("ascii")  # must not raise
        assert unquote(headers["X-Eneo-User-Name"]) == "Åsa Öberg \U0001f600"
        assert unquote(headers["X-Eneo-Tenant-Name"]) == "Härnösands kommun"

    @pytest.mark.asyncio
    async def test_headers_construct_the_actual_http_clients(self):
        # The mapping is handed verbatim to create_mcp_http_client (MCP
        # transport) and to a plain httpx request (the connect diagnostic).
        # Client/request construction is where httpx encodes headers, so it
        # must succeed for Swedish and non-latin-1 identity values.
        user = _user(
            username="Åsa Öberg \U0001f600",
            tenant=SimpleNamespace(name="Härnösands kommun"),
        )
        headers = build_identity_headers(user, user.tenant)

        async with create_mcp_http_client(headers=headers) as client:
            request = client.build_request(
                "POST",
                "http://localhost:9000",
                headers={**headers, "Content-Type": "application/json"},
            )
        assert unquote(request.headers["X-Eneo-User-Name"]) == "Åsa Öberg \U0001f600"

        httpx.Headers(headers)  # must not raise

    def test_empty_values_are_omitted(self):
        user = _user(username=None, email=None, roles=[], tenant=None, tenant_id=None)
        headers = build_identity_headers(user, None)
        assert "X-Eneo-User-Email" not in headers
        assert "X-Eneo-Role" not in headers
        assert "X-Eneo-Tenant-Name" not in headers


class TestMCPClientIdentityForwarding:
    def _server(self, forward_identity: bool):
        server = MagicMock()
        server.name = "srv"
        server.http_url = "http://localhost:9000"
        server.http_auth_type = "bearer"
        server.forward_identity = forward_identity
        return server

    @pytest.mark.asyncio
    async def test_identity_forwarded_only_when_server_opted_in(self):
        identity = {"X-Eneo-User-Id": "u1", "X-Eneo-Tenant-Id": "t1"}

        opted_in = MCPClient(
            self._server(forward_identity=True),
            auth_credentials={"token": "secret"},
            identity_headers=identity,
        )
        headers = await opted_in._build_auth_headers()
        assert headers["Authorization"] == "Bearer secret"
        assert headers["X-Eneo-User-Id"] == "u1"
        assert headers["X-Eneo-Tenant-Id"] == "t1"

    @pytest.mark.asyncio
    async def test_identity_absent_when_not_opted_in(self):
        identity = {"X-Eneo-User-Id": "u1"}
        client = MCPClient(
            self._server(forward_identity=False),
            auth_credentials={"token": "secret"},
            identity_headers=identity,
        )
        headers = await client._build_auth_headers()
        assert headers == {"Authorization": "Bearer secret"}
        assert "X-Eneo-User-Id" not in headers


class TestManagementPathsCarryIdentity:
    """Connection validation (create/update) and tool discovery run as the
    acting admin, so the service must hand the admin's identity headers to
    every client it builds; each client applies its own server's
    ``forward_identity`` gate (covered above)."""

    def _recording_client_cls(self):
        client = MagicMock()
        client.list_tools = AsyncMock(return_value=[])
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=client)
        cm.__aexit__ = AsyncMock(return_value=None)
        return MagicMock(return_value=cm)

    def _service(self, user):
        service = MCPServerService(
            mcp_server_repo=AsyncMock(),
            mcp_server_tool_repo=AsyncMock(),
            user=user,
            mcp_state_repo=AsyncMock(),
        )
        return service

    @pytest.mark.asyncio
    async def test_create_validation_carries_the_acting_admins_identity(self):
        user = _user(permissions=["admin"])
        service = self._service(user)
        client_cls = self._recording_client_cls()

        with patch(
            "eneo.mcp_servers.application.mcp_server_service.MCPClient", client_cls
        ):
            result = await service.create_mcp_server(
                name="srv",
                http_url="http://localhost:9000",
                forward_identity=True,
            )

        assert result.connection.success
        identity = client_cls.call_args.kwargs["identity_headers"]
        assert identity["X-Eneo-User-Id"] == str(user.id)
        assert identity["X-Eneo-User-Name"] == "anna"

    @pytest.mark.asyncio
    async def test_refresh_tools_discovery_carries_the_acting_admins_identity(self):
        user = _user(permissions=["admin"])
        service = self._service(user)
        server = MagicMock()
        server.id = uuid4()
        server.name = "srv"
        server.tenant_id = user.tenant_id
        server.http_auth_config_schema = None
        service.repo.one = AsyncMock(return_value=server)
        service.tool_repo.by_server = AsyncMock(return_value=[])
        client_cls = self._recording_client_cls()

        with patch(
            "eneo.mcp_servers.application.mcp_server_service.MCPClient", client_cls
        ):
            result = await service.refresh_tools(server.id)

        assert result.connection.success
        identity = client_cls.call_args.kwargs["identity_headers"]
        assert identity["X-Eneo-User-Id"] == str(user.id)

    @pytest.mark.asyncio
    async def test_identity_scoped_admin_sync_does_not_remove_user_only_tools(self):
        user = _user(permissions=["admin"])
        service = self._service(user)
        server = MagicMock()
        server.id = uuid4()
        server.name = "srv"
        server.tenant_id = user.tenant_id
        server.forward_identity = True
        existing = MCPServerTool(
            mcp_server_id=server.id,
            name="ordinary_only",
            description="Approved ordinary-user tool",
            input_schema={"type": "object", "properties": {}},
        )
        service.tool_repo.by_server = AsyncMock(return_value=[existing])
        client_cls = self._recording_client_cls()

        with patch(
            "eneo.mcp_servers.application.mcp_server_service.MCPClient", client_cls
        ):
            result = await service.discover_and_sync_tools(server)

        assert result.connection.success
        assert result.removed_tools == []
        service.tool_repo.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_global_admin_sync_still_marks_missing_tools_removed(self):
        user = _user(permissions=["admin"])
        service = self._service(user)
        server = MagicMock()
        server.id = uuid4()
        server.name = "srv"
        server.tenant_id = user.tenant_id
        server.forward_identity = False
        existing = MCPServerTool(
            mcp_server_id=server.id,
            name="removed_tool",
            description="Previously approved",
            input_schema={"type": "object", "properties": {}},
        )
        service.tool_repo.by_server = AsyncMock(return_value=[existing])
        client_cls = self._recording_client_cls()

        with patch(
            "eneo.mcp_servers.application.mcp_server_service.MCPClient", client_cls
        ):
            result = await service.discover_and_sync_tools(server)

        assert [change.tool.name for change in result.removed_tools] == ["removed_tool"]
        assert existing.removed_from_remote is True
        assert existing.requires_approval is True


class TestTerminationCarriesIdentityOnTheWire:
    """factory.terminate sends a plain httpx DELETE, so the opt-in gate can be
    asserted on the actual outgoing request via a recording transport."""

    def _server(self, forward_identity: bool):
        return SimpleNamespace(
            id=uuid4(),
            name="srv",
            http_url="http://localhost:9000",
            http_auth_type="bearer",
            http_auth_config_schema=None,
            forward_identity=forward_identity,
        )

    def _record_http(self, monkeypatch):
        recorded: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            recorded.append(request)
            return httpx.Response(404)  # terminate treats 404 as success

        real_client = httpx.AsyncClient

        class RecordingClient(real_client):
            def __init__(self, **kwargs):
                super().__init__(transport=httpx.MockTransport(handler), **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", RecordingClient)
        return recorded

    @pytest.mark.asyncio
    async def test_terminate_sends_identity_when_server_opted_in(self, monkeypatch):
        recorded = self._record_http(monkeypatch)
        factory = MCPProxySessionFactory(encryption_service=None)

        await factory.terminate(
            self._server(forward_identity=True),
            "mcp-session-1",
            identity_headers={"X-Eneo-User-Id": "u1"},
        )

        (request,) = recorded
        assert request.method == "DELETE"
        assert request.headers["X-Eneo-User-Id"] == "u1"
        assert request.headers["Mcp-Session-Id"] == "mcp-session-1"

    @pytest.mark.asyncio
    async def test_terminate_omits_identity_when_server_not_opted_in(self, monkeypatch):
        recorded = self._record_http(monkeypatch)
        factory = MCPProxySessionFactory(encryption_service=None)

        await factory.terminate(
            self._server(forward_identity=False),
            "mcp-session-1",
            identity_headers={"X-Eneo-User-Id": "u1"},
        )

        (request,) = recorded
        assert "X-Eneo-User-Id" not in request.headers
