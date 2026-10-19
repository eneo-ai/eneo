"""An OAuth server nobody has authorized answers with the connect remedy, in
the result text for the model and under meta for the client; a refused token
mid-session does the same; and identity-scoped discovery keeps the admin
catalog instead of hiding the tools."""

from types import SimpleNamespace
from uuid import uuid4

import httpx

from eneo.main.exceptions import MCPAuthenticationError, MCPUserActionRequiredError
from eneo.mcp_servers.domain.entities.mcp_server import (
    OAUTH_AUTH_TYPE,
    MCPServer,
    MCPServerTool,
)
from eneo.mcp_servers.infrastructure.oauth.bearer_auth import MCPOAuthBearerAuth
from eneo.mcp_servers.infrastructure.oauth.discovery import OAuthChallenge
from eneo.mcp_servers.infrastructure.proxy import mcp_proxy_session as proxy_module
from eneo.mcp_servers.infrastructure.proxy.mcp_proxy_session import MCPProxySession

TOOL = "vendor__search"


def _server(forward_identity: bool = False) -> MCPServer:
    server = MCPServer(
        id=uuid4(),
        tenant_id=uuid4(),
        name="vendor",
        http_url="https://vendor.example/mcp",
        http_auth_type=OAUTH_AUTH_TYPE,
        forward_identity=forward_identity,
    )
    server.tools = [
        MCPServerTool(
            id=uuid4(),
            mcp_server_id=server.id,
            name="search",
            description="Search",
            input_schema={"type": "object"},
        )
    ]
    return server


def _error(server: MCPServer) -> MCPUserActionRequiredError:
    return MCPUserActionRequiredError(
        "connect first",
        mcp_server_id=server.id,
        server_name=server.name,
        auth_scope="per_user",
        connect_url=f"https://eneo.example/mcp-oauth/connect?server={server.id}",
        reason="not_connected",
    )


class _Resolver:
    def __init__(
        self, error: MCPUserActionRequiredError | None = None, token: str = "tok"
    ):
        self.error = error
        self.token = token
        self.denials: list[MCPServer] = []
        self.forgotten: list[MCPServer] = []

    def forget(self, server: MCPServer) -> None:
        self.forgotten.append(server)

    async def auth_for(self, server: MCPServer) -> httpx.Auth:
        if self.error is not None:
            raise self.error
        return MCPOAuthBearerAuth(self.token)

    async def record_denial(self, server: MCPServer, auth=None):
        self.denials.append(server)
        return _error(server)


class _RefusingClient:
    """A connected client whose server now rejects the token."""

    def __init__(self, server: MCPServer):
        self.auth = MCPOAuthBearerAuth("tok")
        self.auth.challenge = OAuthChallenge(401, None, None, "invalid_token")
        self.mcp_server = server

    @property
    def oauth_token_refused(self) -> bool:
        return True

    async def call_tool(self, name, arguments):
        raise MCPAuthenticationError("401")


def _proxy(monkeypatch, server: MCPServer, resolver) -> MCPProxySession:
    monkeypatch.setattr(
        proxy_module, "get_settings", lambda: SimpleNamespace(mcp_apps_enabled=False)
    )
    return MCPProxySession([server], oauth_auth_resolver=resolver)


async def test_unauthorized_server_returns_the_remedy_without_connecting(monkeypatch):
    server = _server()
    proxy = _proxy(monkeypatch, server, _Resolver(error=_error(server)))

    results = await proxy.call_tools_parallel([(TOOL, {"q": "x"}), (TOOL, {"q": "y"})])

    for result in results:
        assert result["is_error"] is True
        assert "AUTHORIZATION_REQUIRED" in result["content"][0]["text"]
        assert "vendor" in result["content"][0]["text"]
        remedy = result["meta"]["eneo/authorization_required"]
        assert remedy["code"] == "mcp_authorization_required"
        assert remedy["mcp_server_id"] == str(server.id)
        assert remedy["connect_url"].endswith(str(server.id))
    assert server.id not in proxy._clients


async def test_shared_server_remedy_points_to_an_administrator(monkeypatch):
    server = _server()
    server.auth_scope = "shared"
    error = _error(server)
    error.auth_scope = "shared"
    error.connect_url = None
    proxy = _proxy(monkeypatch, server, _Resolver(error=error))

    (result,) = await proxy.call_tools_parallel([(TOOL, {})])

    assert "administrator" in result["content"][0]["text"]
    assert "connect_url" not in result["meta"]["eneo/authorization_required"]


async def test_a_token_refused_mid_session_becomes_the_remedy(monkeypatch):
    server = _server()
    resolver = _Resolver()
    proxy = _proxy(monkeypatch, server, resolver)
    proxy._clients[server.id] = _RefusingClient(server)  # type: ignore[assignment]

    first = await proxy.call_tool(TOOL, {})
    second = await proxy.call_tool(TOOL, {})

    assert (
        first["meta"]["eneo/authorization_required"]["code"]
        == "mcp_authorization_required"
    )
    assert resolver.denials == [server]
    # The second call never reaches the server again.
    assert second == first


async def test_without_a_resolver_an_oauth_server_cannot_be_called(monkeypatch):
    server = _server()
    proxy = _proxy(monkeypatch, server, None)

    (result,) = await proxy.call_tools_parallel([(TOOL, {})])

    assert result["meta"]["eneo/authorization_required"]["reason"] == "no_resolver"


async def test_identity_scoped_discovery_keeps_the_catalog_when_unauthorized(
    monkeypatch,
):
    server = _server(forward_identity=True)
    proxy = _proxy(monkeypatch, server, _Resolver(error=_error(server)))

    await proxy.prepare_tools_for_context()

    assert TOOL in proxy._tool_registry
    (result,) = await proxy.call_tools_parallel([(TOOL, {})])
    assert "AUTHORIZATION_REQUIRED" in result["content"][0]["text"]


async def test_prepare_reports_awaiting_servers_and_retry_reconnects_after_authorization(
    monkeypatch,
):
    server = _server()
    resolver = _Resolver(error=_error(server))
    proxy = _proxy(monkeypatch, server, resolver)

    awaiting = await proxy.prepare_calls([(TOOL, {})])
    assert set(awaiting) == {server.id}
    assert awaiting[server.id].reason == "not_connected"
    assert proxy.server_id_for_tool(TOOL) == server.id

    # The user connected meanwhile: the resolver now hands out a token and the
    # proxy connects the server for real (stubbed here).
    resolver.error = None
    connected_servers: list[MCPServer] = []

    async def fake_connect(self_, s):
        connected_servers.append(s)
        proxy._clients[s.id] = object()  # type: ignore[assignment]
        return proxy._clients[s.id]

    monkeypatch.setattr(type(proxy), "_get_or_create_client", fake_connect)
    connected = await proxy.retry_authorization([server.id])

    assert connected == {server.id}
    assert resolver.forgotten == [server]
    assert server.id not in proxy._authorization_required
    assert await proxy.prepare_calls([(TOOL, {})]) == {}


async def test_retry_keeps_the_remedy_when_still_unauthorized(monkeypatch):
    server = _server()
    resolver = _Resolver(error=_error(server))
    proxy = _proxy(monkeypatch, server, resolver)
    await proxy.prepare_calls([(TOOL, {})])

    assert await proxy.retry_authorization([server.id]) == set()
    assert server.id in proxy._authorization_required
