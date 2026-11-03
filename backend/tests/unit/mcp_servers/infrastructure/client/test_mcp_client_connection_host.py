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
import httpx
import pytest
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import StreamableHTTPTransport
from mcp.server.fastmcp import FastMCP
from mcp.types import InitializeResult

from eneo.main import stream_lifecycle
from eneo.main.exceptions import MCPClientError
from eneo.main.stream_lifecycle import (
    finalization_deadline,
    finalization_owner,
    finalizing,
)
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
    except BaseException:
        # A failed assertion can leave a client connected. Let shutdown finish
        # so its open stream cannot hide the original test failure.
        server.config.timeout_graceful_shutdown = 1
        raise
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


@pytest.mark.asyncio
async def test_a_shutdown_drain_ends_a_healthy_connection_gracefully(
    monkeypatch: pytest.MonkeyPatch, teardown_errors: Mock
):
    """The drain asks the host to leave its contexts as a disconnect would,
    so it ends on its own with the session terminated, not by cancellation;
    cancelling is only for a host that misses the deadline."""
    warnings = Mock()
    monkeypatch.setattr(client_module.logger, "warning", warnings)
    terminated: list[str | None] = []
    terminate_session = StreamableHTTPTransport.terminate_session

    async def recording_terminate_session(
        self: StreamableHTTPTransport, client: httpx.AsyncClient
    ) -> None:
        await terminate_session(self, client)
        terminated.append(self.session_id)

    monkeypatch.setattr(
        StreamableHTTPTransport, "terminate_session", recording_terminate_session
    )
    async with _mcp_server() as url:
        client = MCPClient(_server_row(url), None)
        await client.connect()
        host = client._host
        assert host is not None

        assert await drain_connection_hosts(5.0) == 1

    assert not _live_hosts()
    assert host.task.done() and not host.task.cancelled()
    assert len(terminated) == 1 and terminated[0] is not None
    assert client.session is None
    assert [c.args[0] for c in warnings.call_args_list] == [
        "%d MCP connection(s) still open at shutdown; closing them"
    ]
    teardown_errors.assert_not_called()


@pytest.mark.asyncio
async def test_a_close_whose_budget_is_spent_still_ends_the_connections(
    monkeypatch: pytest.MonkeyPatch, teardown_errors: Mock
):
    monkeypatch.setattr(stream_lifecycle, "FINALIZATION_BUDGET_SECONDS", 0.05)
    async with _mcp_server() as url:
        proxy = MCPProxySession([_server_row(url)])
        await proxy.call_tool("probe__echo", {"text": "a"})
        assert len(_live_hosts()) == 1

        with finalization_owner():
            with finalizing("spends the budget"):
                await asyncio.sleep(10)
            deadline = finalization_deadline()
            assert deadline is not None and deadline <= anyio.current_time()
            with finalizing("mcp proxy"):
                assert finalization_deadline() == deadline
                await proxy.close()

        async with asyncio.timeout(5):
            while _live_hosts():
                await asyncio.sleep(0.01)

    teardown_errors.assert_not_called()


@pytest.mark.asyncio
async def test_a_server_slow_to_end_its_session_is_cut_off_with_the_budget(
    monkeypatch: pytest.MonkeyPatch, teardown_errors: Mock
):
    """The budget bounds how long the request waits; a host still unwinding
    when it runs out is cancelled rather than left to finish at its pace."""
    monkeypatch.setattr(stream_lifecycle, "FINALIZATION_BUDGET_SECONDS", 0.3)

    async def slow_terminate_session(
        self: StreamableHTTPTransport, client: object
    ) -> None:
        await asyncio.sleep(5)

    monkeypatch.setattr(
        StreamableHTTPTransport, "terminate_session", slow_terminate_session
    )
    async with _mcp_server() as url:
        proxy = MCPProxySession([_server_row(url)])
        await proxy.call_tool("probe__echo", {"text": "a"})
        assert len(_live_hosts()) == 1

        with finalizing("mcp proxy"):
            await proxy.close()

        # Well under the 5 s the server takes, with headroom for a loaded
        # runner over the 0.3 s budget.
        async with asyncio.timeout(2):
            while _live_hosts():
                await asyncio.sleep(0.01)

    teardown_errors.assert_not_called()


@pytest.mark.asyncio
async def test_a_cancelled_connect_does_not_disturb_the_next_one(
    monkeypatch: pytest.MonkeyPatch, teardown_errors: Mock
):
    warnings = Mock()
    monkeypatch.setattr(client_module.logger, "warning", warnings)
    first_handshake = asyncio.Event()
    release_first_handshake = asyncio.Event()
    initialize = ClientSession.initialize

    async def pause_first_handshake(session: ClientSession) -> InitializeResult:
        result = await initialize(session)
        if not first_handshake.is_set():
            first_handshake.set()
            await release_first_handshake.wait()
        return result

    monkeypatch.setattr(ClientSession, "initialize", pause_first_handshake)
    async with _mcp_server() as url:
        client = MCPClient(_server_row(url), None)

        connecting = asyncio.create_task(client.connect())
        try:
            async with asyncio.timeout(5):
                await first_handshake.wait()
                connecting.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await connecting

                # Keep the abandoned handshake pending until its replacement
                # is connected, so it cannot accidentally overwrite that session.
                await client.connect()
        finally:
            release_first_handshake.set()
        async with asyncio.timeout(5):  # the abandoned host finishes unwinding
            while len(_live_hosts()) > 1:
                await asyncio.sleep(0.01)
        result = await client.call_tool("echo", {"text": "still connected"})
        await client.disconnect()

    assert result["content"][0]["text"] == "still connected"
    assert not _live_hosts()
    warnings.assert_not_called()
    teardown_errors.assert_not_called()


@pytest.mark.asyncio
async def test_a_shutdown_drain_during_the_handshake_fails_the_connect_plainly():
    async with _mcp_server() as url:
        client = MCPClient(_server_row(url), None)
        connecting = asyncio.create_task(client.connect())
        await asyncio.sleep(0)
        await drain_connection_hosts(5)

        with pytest.raises(MCPClientError):
            await connecting

    assert client.session is None
    assert not _live_hosts()


@pytest.mark.asyncio
async def test_connecting_twice_keeps_the_one_connection(teardown_errors: Mock):
    async with _mcp_server() as url:
        client = MCPClient(_server_row(url), None)
        await client.connect()
        await client.connect()
        assert len(_live_hosts()) == 1

        result = await client.call_tool("echo", {"text": "once"})
        await client.disconnect()

    assert result["content"][0]["text"] == "once"
    assert not _live_hosts()
    teardown_errors.assert_not_called()


@pytest.mark.asyncio
async def test_a_host_that_ends_after_its_handshake_is_detached(
    teardown_errors: Mock,
):
    """A read timeout, a closed stream or a transport error ends the host
    after it published its session. The client must notice: connecting again
    opens a new connection instead of reporting the dead one as connected."""
    async with _mcp_server() as url:
        client = MCPClient(_server_row(url), None)
        await client.connect()
        host = client._host
        assert host is not None

        host.task.cancel()
        await asyncio.wait({host.task})

        assert client._host is None
        assert client.session is None
        assert not _live_hosts()

        await client.connect()
        assert len(_live_hosts()) == 1
        tools = await client.list_tools()
        result = await client.call_tool("echo", {"text": "again"})
        await client.disconnect()

    assert [tool["name"] for tool in tools] == ["echo"]
    assert result["content"][0]["text"] == "again"
    assert not _live_hosts()
    teardown_errors.assert_not_called()


@pytest.mark.asyncio
async def test_the_proxy_marks_a_server_failed_when_its_host_ended_between_calls(
    teardown_errors: Mock,
):
    """The proxy reuses a cached client without reconnecting it: a server
    whose connection ended mid-session fails like any other mid-session
    failure and is not retried for the rest of the session."""
    async with _mcp_server() as url:
        proxy = MCPProxySession([_server_row(url)])
        first = await proxy.call_tool("probe__echo", {"text": "a"})
        (client,) = proxy._clients.values()
        host = client._host
        assert host is not None

        host.task.cancel()
        await asyncio.wait({host.task})
        assert not _live_hosts()

        with pytest.raises(MCPClientError):
            await proxy.call_tool("probe__echo", {"text": "b"})
        refused = await proxy.call_tool("probe__echo", {"text": "c"})
        await proxy.close()

    assert first["content"][0]["text"] == "a"
    assert refused["is_error"]
    assert not _live_hosts()
    teardown_errors.assert_not_called()


@pytest.mark.asyncio
async def test_concurrent_connects_open_one_connection(teardown_errors: Mock):
    async with _mcp_server() as url:
        client = MCPClient(_server_row(url), None)
        await asyncio.gather(client.connect(), client.connect(), client.connect())
        assert len(_live_hosts()) == 1

        result = await client.call_tool("echo", {"text": "once"})
        await client.disconnect()

    assert result["content"][0]["text"] == "once"
    assert not _live_hosts()
    teardown_errors.assert_not_called()
