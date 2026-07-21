from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

import eneo.mcp_servers.infrastructure.proxy.mcp_proxy_session as proxy_module
from eneo.main.exceptions import MCPClientError
from eneo.mcp_servers.domain.entities.mcp_server import MCPServer, MCPServerTool
from eneo.mcp_servers.infrastructure.proxy.mcp_proxy_session import MCPProxySession


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


def _make_identity_scoped_server() -> MCPServer:
    server_id = uuid4()
    tools = [
        MCPServerTool(
            mcp_server_id=server_id,
            name=name,
            description=f"Approved {name}",
            input_schema={"type": "object", "properties": {}},
        )
        for name in ("shared", "admin_only", "ordinary_only")
    ]
    return MCPServer(
        id=server_id,
        tenant_id=uuid4(),
        name="identity-server",
        http_url="http://localhost:8080/mcp",
        forward_identity=True,
        tools=tools,
    )


class _FakeMCPClient:
    live_tools_by_user: dict[str, list[dict[str, str]]] = {}
    failing_users: set[str] = set()
    instances: list["_FakeMCPClient"] = []

    def __init__(
        self,
        mcp_server: MCPServer,
        auth_credentials: dict[str, str] | None = None,
        *,
        identity_headers: dict[str, str] | None = None,
        **options: object,
    ) -> None:
        self.user_id = (identity_headers or {}).get("X-Eneo-User-Id", "")
        self.enter_task = None
        self.exit_task = None
        self.connect_task = None
        self.disconnect_task = None
        self.assigned_mcp_session_id = None
        self.supports_tools_list_changed = False
        type(self).instances.append(self)

    async def __aenter__(self) -> "_FakeMCPClient":
        self.enter_task = asyncio.current_task()
        return self

    async def __aexit__(self, *args: object) -> None:
        self.exit_task = asyncio.current_task()

    async def connect(self) -> None:
        self.connect_task = asyncio.current_task()

    async def disconnect(self) -> None:
        self.disconnect_task = asyncio.current_task()

    async def list_tools(self) -> list[dict[str, str]]:
        if self.user_id in self.failing_users:
            raise MCPClientError("discovery unavailable")
        return self.live_tools_by_user[self.user_id]

    async def call_tool(
        self, name: str, arguments: dict[str, object]
    ) -> dict[str, object]:
        return {"content": [{"type": "text", "text": name}], "is_error": False}


def _install_fake_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    live_tools_by_user: dict[str, list[dict[str, str]]],
    failing_users: tuple[str, ...] | set[str] = (),
) -> None:
    _FakeMCPClient.live_tools_by_user = live_tools_by_user
    _FakeMCPClient.failing_users = set(failing_users)
    _FakeMCPClient.instances = []
    monkeypatch.setattr(proxy_module, "MCPClient", _FakeMCPClient)


def test_live_tool_refresh_only_exposes_db_approved_definitions():
    server = _make_server()
    proxy = MCPProxySession([server])

    changed = proxy._rebuild_server_tools(  # pyright: ignore[reportPrivateUsage]
        server,
        [
            {
                "name": "tool",
                "title": "Injected title",
                "description": "Injected description",
                "input_schema": {
                    "type": "object",
                    "properties": {"admin": {"type": "boolean"}},
                },
            },
            {
                "name": "unknown_tool",
                "description": "Not synced or approved",
                "input_schema": {"type": "object"},
            },
        ],
    )

    assert changed is False
    assert proxy.get_allowed_tool_names() == {"server__tool"}
    [definition] = proxy.get_tools_for_llm()
    assert definition["function"]["description"] == "Test tool"
    assert definition["function"]["parameters"] == {
        "type": "object",
        "properties": {},
    }


@pytest.mark.asyncio
async def test_identity_scoped_catalog_is_intersected_with_each_users_live_tools(
    monkeypatch: pytest.MonkeyPatch,
):
    _install_fake_client(
        monkeypatch,
        live_tools_by_user={
            "admin": [{"name": "shared"}, {"name": "admin_only"}],
            "ordinary": [{"name": "shared"}, {"name": "ordinary_only"}],
        },
    )
    server = _make_identity_scoped_server()
    admin_proxy = MCPProxySession(
        [server], identity_headers={"X-Eneo-User-Id": "admin"}
    )
    ordinary_proxy = MCPProxySession(
        [server], identity_headers={"X-Eneo-User-Id": "ordinary"}
    )

    await admin_proxy.prepare_tools_for_context()
    await ordinary_proxy.prepare_tools_for_context()

    assert admin_proxy.get_allowed_tool_names() == {
        "identity-server__shared",
        "identity-server__admin_only",
    }
    assert ordinary_proxy.get_allowed_tool_names() == {
        "identity-server__shared",
        "identity-server__ordinary_only",
    }


@pytest.mark.asyncio
async def test_identity_scoped_catalog_fails_closed_when_live_discovery_fails(
    monkeypatch: pytest.MonkeyPatch,
):
    _install_fake_client(
        monkeypatch,
        live_tools_by_user={"user": []},
        failing_users={"user"},
    )
    server = _make_identity_scoped_server()
    proxy = MCPProxySession([server], identity_headers={"X-Eneo-User-Id": "user"})

    await proxy.prepare_tools_for_context()

    assert proxy.get_tools_for_llm() == []
    assert proxy.get_allowed_tool_names() == set()
    assert proxy._clients == {}
    assert proxy._owner_task is None


@pytest.mark.asyncio
async def test_identity_discovery_does_not_claim_the_streaming_owner_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_client(
        monkeypatch,
        live_tools_by_user={"user": [{"name": "shared"}]},
    )
    server = _make_identity_scoped_server()
    proxy = MCPProxySession([server], identity_headers={"X-Eneo-User-Id": "user"})

    discovery_task = asyncio.create_task(proxy.prepare_tools_for_context())
    await discovery_task

    assert proxy._owner_task is None
    assert proxy._clients == {}
    [discovery_client] = _FakeMCPClient.instances
    assert discovery_client.enter_task is discovery_task
    assert discovery_client.exit_task is discovery_task

    async def run_streaming_phase():
        current_task = asyncio.current_task()
        result = await proxy.call_tools_parallel(
            [("identity-server__shared", {"query": "hello"})]
        )
        await proxy.close()
        return current_task, result

    streaming_task = asyncio.create_task(run_streaming_phase())
    owner_task, [result] = await streaming_task

    assert result["is_error"] is False
    assert owner_task is streaming_task
    assert len(_FakeMCPClient.instances) == 2
    runtime_client = _FakeMCPClient.instances[1]
    assert runtime_client.connect_task is streaming_task
    assert runtime_client.disconnect_task is streaming_task


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
