"""The connection host against the real MCP SDK.

A FastMCP server runs in-process behind uvicorn on a loopback port; the
client connects over streamable HTTP with the SDK's own transport and
session. The point of the host is that the SDK's task-bound cancel scopes
never reach a caller's task, so connecting, calling and disconnecting from
different tasks, under a shield, and while the caller is cancelled all leave
nothing behind.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import Mock
from uuid import uuid4

import anyio
import pytest
import uvicorn
from mcp.server.fastmcp import FastMCP

from eneo.main.exceptions import MCPClientError
from eneo.mcp_servers.domain.entities.mcp_server import MCPServer, MCPServerTool
from eneo.mcp_servers.infrastructure.client import mcp_client as client_module
from eneo.mcp_servers.infrastructure.client.mcp_client import (
    MCPClient,
    drain_connection_hosts,
)
from eneo.mcp_servers.infrastructure.proxy.mcp_proxy_session import MCPProxySession


@asynccontextmanager
async def _mcp_server() -> AsyncIterator[str]:
    mcp = FastMCP("probe")

    @mcp.tool()
    def echo(text: str) -> str:
        return text

    config = uvicorn.Config(
        mcp.streamable_http_app(),
        host="127.0.0.1",
        port=0,
        log_level="warning",
        lifespan="on",
        ws="none",
    )
    server = uvicorn.Server(config)
    serving = asyncio.create_task(server.serve())
    while not server.started:
        if serving.done():
            serving.result()
        await asyncio.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        server.should_exit = True
        await serving


def _server_row(url: str) -> MCPServer:
    server_id = uuid4()
    return MCPServer(
        id=server_id,
        tenant_id=uuid4(),
        name="probe",
        http_url=url,
        tools=[
            MCPServerTool(
                mcp_server_id=server_id,
                name="echo",
                description="Echo",
                input_schema={"type": "object", "properties": {}},
                is_enabled_by_default=True,
            )
        ],
    )


def _live_hosts() -> set[asyncio.Task[None]]:
    return {task for task in client_module._connection_hosts if not task.done()}


@pytest.fixture
def teardown_errors(monkeypatch: pytest.MonkeyPatch) -> Mock:
    errors = Mock()
    monkeypatch.setattr(client_module.logger, "error", errors)
    return errors


@pytest.mark.asyncio
async def test_connect_call_and_disconnect_from_different_tasks_under_a_shield(
    teardown_errors: Mock,
):
    async with _mcp_server() as url:
        client = MCPClient(_server_row(url), None)
        await client.connect()

        results = await asyncio.gather(
            client.call_tool("echo", {"text": "one"}),
            client.call_tool("echo", {"text": "two"}),
        )

        async def close_elsewhere() -> None:
            # Like finalizing(): a scope pushed on top of the caller's stack
            # while the SDK's scopes are left, which only works because they
            # are on the host's stack, not this one.
            with anyio.CancelScope(shield=True):
                await client.disconnect()

        await asyncio.create_task(close_elsewhere())

    assert [r["content"][0]["text"] for r in results] == ["one", "two"]
    assert client.session is None
    assert not _live_hosts()
    teardown_errors.assert_not_called()


@pytest.mark.asyncio
async def test_the_proxy_closes_connections_opened_by_gathered_tool_calls(
    teardown_errors: Mock,
):
    async with _mcp_server() as url:
        proxy = MCPProxySession([_server_row(url)])
        results = await proxy.call_tools_parallel(
            [("probe__echo", {"text": "a"}), ("probe__echo", {"text": "b"})]
        )
        assert len(_live_hosts()) == 1
        await asyncio.create_task(proxy.close())

    assert [r["content"][0]["text"] for r in results] == ["a", "b"]
    assert not _live_hosts()
    teardown_errors.assert_not_called()


@pytest.mark.asyncio
async def test_a_cancelled_disconnect_still_closes_the_connection(
    teardown_errors: Mock,
):
    async with _mcp_server() as url:
        client = MCPClient(_server_row(url), None)
        await client.connect()

        closing = asyncio.create_task(client.disconnect())
        await asyncio.sleep(0)
        closing.cancel()
        with pytest.raises(asyncio.CancelledError):
            await closing

        async with asyncio.timeout(5):
            while _live_hosts():
                await asyncio.sleep(0.01)

    teardown_errors.assert_not_called()


@pytest.mark.asyncio
async def test_a_refused_connection_leaves_no_host_behind():
    async with _mcp_server() as url:
        pass  # the port is closed again

    client = MCPClient(_server_row(url), None)
    with pytest.raises(MCPClientError):
        await client.connect()

    assert client.session is None
    assert not _live_hosts()


@pytest.mark.asyncio
async def test_shutdown_drains_a_connection_left_open():
    async with _mcp_server() as url:
        client = MCPClient(_server_row(url), None)
        await client.connect()

        assert await drain_connection_hosts(5) == 1

    assert not _live_hosts()
    assert await drain_connection_hosts(5) == 0
