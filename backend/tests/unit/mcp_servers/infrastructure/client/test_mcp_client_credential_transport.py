"""The MCP client never sends an admin-supplied credential over plain http."""

import logging
import socket
from uuid import uuid4

import pytest
from aiohttp import web

from eneo.main.exceptions import MCPClientError
from eneo.mcp_servers.domain.entities.mcp_server import MCPServer
from eneo.mcp_servers.infrastructure.client import mcp_client as client_module
from eneo.mcp_servers.infrastructure.client.mcp_client import (
    MCPClient,
    MCPInsecureCredentialTransportError,
)


# Kills: checking only on create/update (a row stored before the rule still
# connects), and a check placed after the transport opens or in the diagnostic
# fallback, where the header would already be on the wire.
async def test_a_legacy_http_row_is_refused_before_any_request(monkeypatch, caplog):
    def no_request(*args, **kwargs):
        raise AssertionError("a request was attempted")

    monkeypatch.setattr(client_module, "_open_streamable_http_client", no_request)
    monkeypatch.setattr(client_module, "_diagnose_http", no_request)
    server = MCPServer(
        id=uuid4(),
        tenant_id=uuid4(),
        name="Legacy",
        http_url="http://mcp.example.org/mcp",
        http_auth_type="api_key_header",
    )
    client = MCPClient(server, {"header_name": "X-Api-Key", "token": "sk-secret"})

    with (
        caplog.at_level(logging.DEBUG),
        pytest.raises(MCPInsecureCredentialTransportError) as raised,
    ):
        await client.connect()

    assert "https" in str(raised.value)
    assert "sk-secret" not in str(raised.value)
    assert "sk-secret" not in caplog.text


# Kills: applying the rule to Eneo's own loopback servers (knowledge, files),
# whose minted token goes to INTERNAL_MCP_BASE_URL, often a plain-http service
# name inside the deployment.
async def test_eneos_own_loopback_server_keeps_its_token():
    server = MCPServer(
        id=uuid4(),
        tenant_id=uuid4(),
        name="knowledge",
        http_url="http://eneo-backend:8000/internal-mcp/knowledge/mcp",
        http_auth_type="bearer",
        is_internal=True,
    )

    headers = await MCPClient(server, {"token": "minted"})._build_auth_headers()

    assert headers["Authorization"] == "Bearer minted"


# Kills: building the transport client or the diagnostic probe without the
# loopback proxy bypass, which hands a credential the rule allows over plain
# http (loopback only) to an HTTP_PROXY from the environment in clear.
async def test_a_loopback_credential_never_goes_through_an_env_proxy(monkeypatch):
    seen_by_proxy: list[str] = []

    async def proxy(request: web.Request) -> web.Response:
        seen_by_proxy.append(str(request.url))
        return web.Response(status=502)

    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", proxy)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    proxy_port = site._server.sockets[0].getsockname()[1]
    with socket.socket() as unused:
        unused.bind(("127.0.0.1", 0))
        closed_port = unused.getsockname()[1]
    for name in ("HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.setenv(name, f"http://127.0.0.1:{proxy_port}")
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.delenv(name, raising=False)
    server = MCPServer(
        id=uuid4(),
        tenant_id=uuid4(),
        name="Local",
        http_url=f"http://localhost:{closed_port}/mcp",
        http_auth_type="bearer",
    )

    try:
        with pytest.raises(MCPClientError):
            await MCPClient(server, {"token": "sk-secret"}, timeout=3).connect()
    finally:
        await runner.cleanup()

    assert seen_by_proxy == []
