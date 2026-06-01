from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

import intric.mcp_servers.infrastructure.proxy.mcp_proxy_session as proxy_module
from intric.main.exceptions import MCPClientError
from intric.mcp_servers.domain.entities.mcp_server import MCPServer, MCPServerTool
from intric.mcp_servers.infrastructure.proxy.mcp_proxy_session import MCPProxySession


def _make_server(name: str = "server") -> MCPServer:
    server_id = uuid4()
    tool = MCPServerTool(
        mcp_server_id=server_id,
        name="tool",
        description="Test tool",
        input_schema={"type": "object", "properties": {}},
        is_enabled_by_default=True,
    )
    return MCPServer(
        id=server_id,
        tenant_id=uuid4(),
        name=name,
        http_url="http://localhost:8080/mcp",
        tools=[tool],
    )


@pytest.mark.asyncio
async def test_call_tool_marks_server_failed_but_keeps_client_for_close():
    """On MCP error, the client must stay in _clients so close() can disconnect
    it on the owner task. Dropping it would orphan the streamablehttp_client's
    anyio TaskGroup (its HTTP read/write loops keep running until __aexit__
    on the streams context). Subsequent calls should short-circuit via the
    failed-server set."""
    server = _make_server()
    proxy = MCPProxySession([server])

    dead_client = SimpleNamespace(
        call_tool=AsyncMock(side_effect=MCPClientError("upstream unavailable"))
    )
    proxy._clients[server.id] = dead_client

    with pytest.raises(MCPClientError):
        await proxy.call_tool("server__tool", {"q": "x"})

    assert server.id in proxy._clients, (
        "Client must remain cached so close() can disconnect it on the owner task"
    )
    assert server.id in proxy._failed_server_ids

    # Subsequent call short-circuits without invoking the dead client again
    result = await proxy.call_tool("server__tool", {"q": "x"})
    assert result["is_error"] is True
    assert dead_client.call_tool.await_count == 1


@pytest.mark.asyncio
async def test_call_tool_returns_error_when_no_client_cached():
    """call_tool must NOT trigger a connect (it runs under asyncio.gather, on a
    task other than the proxy's owner task). When no pre-connected client is
    in the cache, return an error result."""
    server = _make_server()
    proxy = MCPProxySession([server])
    # No pre-connect happened — _clients is empty.

    result = await proxy.call_tool("server__tool", {"q": "x"})

    assert result["is_error"] is True
    assert server.id in proxy._failed_server_ids
    assert server.id not in proxy._clients


@pytest.mark.asyncio
async def test_circuit_breaker_open_returns_generic_message_without_internal_details():
    server = _make_server(name="internal-tools")
    proxy = MCPProxySession([server])
    tool_name = "internal-tools__tool"

    proxy_module._CIRCUIT_BREAKER_STATE[server.id] = {
        "failures": 99,
        "open_until": time.time() + 60,
    }

    try:
        result = await proxy.call_tool(tool_name, {"q": "x"})
    finally:
        proxy_module._CIRCUIT_BREAKER_STATE.pop(server.id, None)

    assert result["is_error"] is True
    message = result["content"][0]["text"]
    assert "temporarily unavailable" in message.lower()
    assert "circuit" not in message.lower()
    assert "open_until" not in message.lower()
    assert str(server.id) not in message
