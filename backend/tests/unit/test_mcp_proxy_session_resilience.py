from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

import eneo.mcp_servers.infrastructure.proxy.mcp_proxy_session as proxy_module
from eneo.main.exceptions import MCPClientError
from eneo.mcp_servers.application.mcp_server_service import MCPServerService
from eneo.mcp_servers.domain.entities.mcp_server import MCPServer, MCPServerTool
from eneo.mcp_servers.infrastructure.proxy.mcp_proxy_session import MCPProxySession
from eneo.roles.permissions import Permission


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


def _make_identity_scoped_server(name: str = "identity-server") -> MCPServer:
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
        name=name,
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


class _InMemoryToolRepo:
    def __init__(self, tools: list[MCPServerTool]) -> None:
        self.tools = {tool.id: tool for tool in tools}
        self.batch_observation_count = 0

    async def stage_observed(
        self, observed_tools: list[MCPServerTool]
    ) -> list[MCPServerTool]:
        self.batch_observation_count += 1
        staged: list[MCPServerTool] = []
        for observed in observed_tools:
            existing = next(
                (
                    saved
                    for saved in self.tools.values()
                    if saved.mcp_server_id == observed.mcp_server_id
                    and saved.name == observed.name
                ),
                None,
            )
            if existing is None:
                self.tools[observed.id] = observed
                staged.append(observed)
                continue
            if existing.requires_approval:
                continue
            if (
                existing.description == observed.pending_description
                and existing.input_schema == observed.pending_input_schema
            ):
                continue
            existing.pending_description = observed.pending_description
            existing.pending_input_schema = observed.pending_input_schema
            existing.requires_approval = True
            existing.removed_from_remote = False
            staged.append(existing)
        return staged

    async def by_server(self, mcp_server_id: UUID) -> list[MCPServerTool]:
        return [
            tool for tool in self.tools.values() if tool.mcp_server_id == mcp_server_id
        ]

    async def one(self, id: UUID) -> MCPServerTool:
        return self.tools[id]

    async def update(self, tool: MCPServerTool) -> MCPServerTool:
        self.tools[tool.id] = tool
        return tool


class _CoordinatedDiscoveryMCPClient:
    release_by_name: dict[str, asyncio.Event] = {}
    finished_by_name: dict[str, asyncio.Event] = {}
    all_started = asyncio.Event()
    started_names: set[str] = set()
    enter_tasks: dict[UUID, asyncio.Task[object] | None] = {}
    exit_tasks: dict[UUID, asyncio.Task[object] | None] = {}

    def __init__(
        self,
        mcp_server: MCPServer,
        auth_credentials: dict[str, str] | None = None,
        **options: object,
    ) -> None:
        self.mcp_server = mcp_server
        self.assigned_mcp_session_id = None

    @classmethod
    def configure(cls, server_names: tuple[str, ...]) -> None:
        cls.release_by_name = {name: asyncio.Event() for name in server_names}
        cls.finished_by_name = {name: asyncio.Event() for name in server_names}
        cls.all_started = asyncio.Event()
        cls.started_names = set()
        cls.enter_tasks = {}
        cls.exit_tasks = {}

    async def __aenter__(self) -> "_CoordinatedDiscoveryMCPClient":
        self.enter_tasks[self.mcp_server.id] = asyncio.current_task()
        return self

    async def __aexit__(self, *args: object) -> None:
        self.exit_tasks[self.mcp_server.id] = asyncio.current_task()

    async def list_tools(self) -> list[dict[str, str]]:
        name = self.mcp_server.name
        self.started_names.add(name)
        if len(self.started_names) == len(self.release_by_name):
            self.all_started.set()
        await self.release_by_name[name].wait()
        self.finished_by_name[name].set()
        return [{"name": "shared"}]


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
async def test_stable_approved_catalog_skips_runtime_staging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = _make_identity_scoped_server()
    _install_fake_client(
        monkeypatch,
        live_tools_by_user={
            "ordinary": [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.input_schema,
                }
                for tool in server.tools
            ]
        },
    )
    tool_repo = _InMemoryToolRepo(server.tools)
    proxy = MCPProxySession(
        [server],
        identity_headers={"X-Eneo-User-Id": "ordinary"},
        mcp_server_tool_repo=tool_repo,
    )

    await proxy.prepare_tools_for_context()

    assert tool_repo.batch_observation_count == 0
    assert proxy.get_allowed_tool_names() == {
        "identity-server__admin_only",
        "identity-server__ordinary_only",
        "identity-server__shared",
    }


@pytest.mark.asyncio
async def test_user_only_tool_is_staged_then_requires_admin_approval_before_exposure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_client(
        monkeypatch,
        live_tools_by_user={
            "ordinary": [
                {"name": "shared"},
                {
                    "name": "ordinary_only",
                    "title": "Ordinary only",
                    "description": "Visible only to an ordinary user",
                    "input_schema": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                    },
                },
            ]
        },
    )
    server = _make_identity_scoped_server()
    server.tools = [tool for tool in server.tools if tool.name != "ordinary_only"]
    tool_repo = _InMemoryToolRepo(server.tools)

    first_turn = MCPProxySession(
        [server],
        identity_headers={"X-Eneo-User-Id": "ordinary"},
        mcp_server_tool_repo=tool_repo,
    )
    await first_turn.prepare_tools_for_context()

    assert first_turn.get_allowed_tool_names() == {"identity-server__shared"}
    staged_tools = await tool_repo.by_server(server.id)
    staged = next(tool for tool in staged_tools if tool.name == "ordinary_only")
    assert staged.description is None
    assert staged.input_schema is None
    assert staged.pending_description == "Visible only to an ordinary user"
    assert staged.pending_input_schema == {
        "type": "object",
        "properties": {"query": {"type": "string"}},
    }
    assert staged.requires_approval is True

    admin = SimpleNamespace(
        tenant_id=server.tenant_id,
        permissions=[Permission.ADMIN],
    )
    server_repo = AsyncMock()
    server_repo.one.return_value = server
    service = MCPServerService(server_repo, tool_repo, admin)
    approved = await service.approve_tool_changes(server.id, [staged.id])
    assert [tool.name for tool in approved] == ["ordinary_only"]

    server.tools = await tool_repo.by_server(server.id)
    second_turn = MCPProxySession(
        [server],
        identity_headers={"X-Eneo-User-Id": "ordinary"},
        mcp_server_tool_repo=tool_repo,
    )
    await second_turn.prepare_tools_for_context()

    assert second_turn.get_allowed_tool_names() == {
        "identity-server__ordinary_only",
        "identity-server__shared",
    }


@pytest.mark.asyncio
async def test_user_only_definition_drift_is_queued_without_exposure_or_overwrite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    changed_schema = {
        "type": "object",
        "properties": {"location": {"type": "string"}},
        "required": ["location"],
    }
    _install_fake_client(
        monkeypatch,
        live_tools_by_user={
            "ordinary": [
                {
                    "name": "ordinary_only",
                    "description": "Changed user-only contract",
                    "input_schema": changed_schema,
                }
            ]
        },
    )
    server = _make_identity_scoped_server()
    approved = next(tool for tool in server.tools if tool.name == "ordinary_only")
    original_schema = approved.input_schema
    tool_repo = _InMemoryToolRepo(server.tools)

    first_observation = MCPProxySession(
        [server],
        identity_headers={"X-Eneo-User-Id": "ordinary"},
        mcp_server_tool_repo=tool_repo,
    )
    await first_observation.prepare_tools_for_context()

    [definition] = first_observation.get_tools_for_llm()
    assert definition["function"]["description"] == "Approved ordinary_only"
    assert definition["function"]["parameters"] == original_schema
    assert approved.pending_description == "Changed user-only contract"
    assert approved.pending_input_schema == changed_schema
    assert approved.requires_approval is True

    _FakeMCPClient.live_tools_by_user["ordinary"] = [
        {
            "name": "ordinary_only",
            "description": "A later unreviewed contract",
            "input_schema": {"type": "object", "properties": {"other": {}}},
        }
    ]
    second_observation = MCPProxySession(
        [server],
        identity_headers={"X-Eneo-User-Id": "ordinary"},
        mcp_server_tool_repo=tool_repo,
    )
    await second_observation.prepare_tools_for_context()

    assert approved.pending_description == "Changed user-only contract"
    assert approved.pending_input_schema == changed_schema


@pytest.mark.asyncio
async def test_oversized_identity_catalog_fails_closed_without_database_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_client(
        monkeypatch,
        live_tools_by_user={
            "ordinary": [{"name": f"tool_{index}"} for index in range(257)]
        },
    )
    server = _make_identity_scoped_server()
    tool_repo = _InMemoryToolRepo(server.tools)
    original_tool_ids = set(tool_repo.tools)
    proxy = MCPProxySession(
        [server],
        identity_headers={"X-Eneo-User-Id": "ordinary"},
        mcp_server_tool_repo=tool_repo,
    )

    await proxy.prepare_tools_for_context()

    assert proxy.get_tools_for_llm() == []
    assert set(tool_repo.tools) == original_tool_ids
    assert tool_repo.batch_observation_count == 0


@pytest.mark.asyncio
async def test_oversized_identity_definition_fails_closed_without_database_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_client(
        monkeypatch,
        live_tools_by_user={
            "ordinary": [
                {
                    "name": "oversized",
                    "description": "x" * 2048,
                    "input_schema": {"type": "object"},
                }
            ]
        },
    )
    server = _make_identity_scoped_server()
    server.tool_definition_max_bytes = 1024
    tool_repo = _InMemoryToolRepo(server.tools)
    original_tool_ids = set(tool_repo.tools)
    proxy = MCPProxySession(
        [server],
        identity_headers={"X-Eneo-User-Id": "ordinary"},
        mcp_server_tool_repo=tool_repo,
    )

    await proxy.prepare_tools_for_context()

    assert proxy.get_tools_for_llm() == []
    assert set(tool_repo.tools) == original_tool_ids
    assert tool_repo.batch_observation_count == 0


@pytest.mark.asyncio
async def test_oversized_identity_catalog_bytes_fail_closed_without_database_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_client(
        monkeypatch,
        live_tools_by_user={
            "ordinary": [
                {"name": "first", "description": "x" * 700},
                {"name": "second", "description": "y" * 700},
            ]
        },
    )
    server = _make_identity_scoped_server()
    server.tool_catalog_max_bytes = 1024
    server.tool_definition_max_bytes = 4096
    tool_repo = _InMemoryToolRepo(server.tools)
    original_tool_ids = set(tool_repo.tools)
    proxy = MCPProxySession(
        [server],
        identity_headers={"X-Eneo-User-Id": "ordinary"},
        mcp_server_tool_repo=tool_repo,
    )

    await proxy.prepare_tools_for_context()

    assert proxy.get_tools_for_llm() == []
    assert set(tool_repo.tools) == original_tool_ids
    assert tool_repo.batch_observation_count == 0


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
async def test_identity_scoped_catalog_fails_closed_when_staging_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_client(
        monkeypatch,
        live_tools_by_user={"ordinary": [{"name": "shared"}]},
    )
    server = _make_identity_scoped_server()
    tool_repo = AsyncMock()
    tool_repo.stage_observed.side_effect = RuntimeError("database unavailable")
    proxy = MCPProxySession(
        [server],
        identity_headers={"X-Eneo-User-Id": "ordinary"},
        mcp_server_tool_repo=tool_repo,
    )

    await proxy.prepare_tools_for_context()

    assert proxy.get_tools_for_llm() == []


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
    assert discovery_client.enter_task is discovery_client.exit_task

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
    assert discovery_client.enter_task is not streaming_task
    assert runtime_client.connect_task is streaming_task
    assert runtime_client.disconnect_task is streaming_task


@pytest.mark.asyncio
async def test_identity_catalog_probes_share_one_preparation_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _CoordinatedDiscoveryMCPClient.configure(("first", "second"))
    monkeypatch.setattr(proxy_module, "MCPClient", _CoordinatedDiscoveryMCPClient)
    monkeypatch.setattr(
        proxy_module,
        "MCP_IDENTITY_CATALOG_PREPARATION_TIMEOUT_SECONDS",
        0.03,
        raising=False,
    )
    servers = [
        _make_identity_scoped_server("first"),
        _make_identity_scoped_server("second"),
    ]
    proxy = MCPProxySession(servers, identity_headers={"X-Eneo-User-Id": "user"})

    started_at = time.perf_counter()
    await asyncio.wait_for(proxy.prepare_tools_for_context(), timeout=0.15)
    elapsed = time.perf_counter() - started_at

    assert elapsed < 0.12
    assert _CoordinatedDiscoveryMCPClient.started_names == {"first", "second"}
    assert proxy.get_tools_for_llm() == []
    for server in servers:
        assert (
            _CoordinatedDiscoveryMCPClient.enter_tasks[server.id]
            is _CoordinatedDiscoveryMCPClient.exit_tasks[server.id]
        )


@pytest.mark.asyncio
async def test_identity_catalog_results_keep_configured_server_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _CoordinatedDiscoveryMCPClient.configure(("first", "second"))
    monkeypatch.setattr(proxy_module, "MCPClient", _CoordinatedDiscoveryMCPClient)
    servers = [
        _make_identity_scoped_server("first"),
        _make_identity_scoped_server("second"),
    ]
    proxy = MCPProxySession(servers, identity_headers={"X-Eneo-User-Id": "user"})

    preparation = asyncio.create_task(proxy.prepare_tools_for_context())
    await asyncio.wait_for(
        _CoordinatedDiscoveryMCPClient.all_started.wait(), timeout=0.1
    )
    _CoordinatedDiscoveryMCPClient.release_by_name["second"].set()
    await asyncio.wait_for(
        _CoordinatedDiscoveryMCPClient.finished_by_name["second"].wait(), timeout=0.1
    )
    _CoordinatedDiscoveryMCPClient.release_by_name["first"].set()
    await asyncio.wait_for(preparation, timeout=0.1)

    assert _CoordinatedDiscoveryMCPClient.finished_by_name["second"].is_set()
    assert [tool["function"]["name"] for tool in proxy.get_tools_for_llm()] == [
        "first__shared",
        "second__shared",
    ]


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


def _make_files_loopback_server() -> MCPServer:
    server_id = uuid4()
    tool = MCPServerTool(
        mcp_server_id=server_id,
        name="read_file",
        title="Read attached file",
        description="Read the text content of an attached file.",
        input_schema={"type": "object", "properties": {}},
        is_enabled_by_default=True,
    )
    return MCPServer(
        id=server_id,
        tenant_id=uuid4(),
        name="files",
        http_url="http://localhost:8123/internal-mcp/files/mcp",
        tools=[tool],
    )


class TestReferenceFallbackHint:
    """A failed tool call that carried a signed attachment reference points the
    model at the loopback read_file instead of inviting a retry loop. The hint
    keys on the argument shape, not on which server failed, and only appears
    when read_file is actually registered."""

    def _reference_url(self) -> str:
        from eneo.authentication.signed_urls import (
            build_signed_original_download_url,
        )

        return build_signed_original_download_url(
            file_id=uuid4(),
            base_url="http://host.docker.internal:8123",
            expires_in=3600,
            tenant_id=uuid4(),
        )

    def _failing_client(self):
        return SimpleNamespace(
            call_tool=AsyncMock(
                return_value={
                    "content": [{"type": "text", "text": "could not fetch URL"}],
                    "is_error": True,
                }
            )
        )

    async def test_error_result_names_read_file_when_a_reference_url_failed(self):
        external = _make_server(name="tabular")
        proxy = MCPProxySession([_make_files_loopback_server(), external])
        proxy._clients[external.id] = self._failing_client()

        result = await proxy.call_tool("tabular__tool", {"url": self._reference_url()})

        assert result["is_error"] is True
        texts = [block["text"] for block in result["content"]]
        assert any("files__read_file" in text for text in texts)
        assert any('"Read attached file"' in text for text in texts)

    async def test_no_hint_for_non_reference_arguments(self):
        external = _make_server(name="tabular")
        proxy = MCPProxySession([_make_files_loopback_server(), external])
        proxy._clients[external.id] = self._failing_client()

        result = await proxy.call_tool(
            "tabular__tool", {"url": "https://example.com/data.csv"}
        )

        texts = [block["text"] for block in result["content"]]
        assert not any("files__read_file" in text for text in texts)

    async def test_no_hint_when_read_file_is_not_registered(self):
        external = _make_server(name="tabular")
        proxy = MCPProxySession([external])
        proxy._clients[external.id] = self._failing_client()

        result = await proxy.call_tool("tabular__tool", {"url": self._reference_url()})

        texts = [block["text"] for block in result["content"]]
        assert not any("read_file" in text for text in texts)

    async def test_unavailable_server_result_carries_the_hint(self):
        external = _make_server(name="tabular")
        proxy = MCPProxySession([_make_files_loopback_server(), external])
        proxy._failed_server_ids.add(external.id)

        result = await proxy.call_tool("tabular__tool", {"url": self._reference_url()})

        message = result["content"][0]["text"]
        assert "temporarily unavailable" in message.lower()
        assert "files__read_file" in message

    async def test_read_file_failure_does_not_hint_at_itself(self):
        files_server = _make_files_loopback_server()
        proxy = MCPProxySession([files_server])
        proxy._clients[files_server.id] = self._failing_client()

        result = await proxy.call_tool(
            "files__read_file", {"url": self._reference_url()}
        )

        texts = [block["text"] for block in result["content"]]
        assert not any("still readable" in text for text in texts)


class TestTruncateToolResult:
    """Oversized tool results are trimmed to the budget, never failed."""

    def _truncate(self, result):
        return MCPProxySession([])._truncate_tool_result(  # pyright: ignore[reportPrivateUsage]
            result
        )

    def test_small_result_passes_through_untouched(self):
        result = {"content": [{"type": "text", "text": "short"}], "is_error": False}

        assert self._truncate(result) is result

    def test_oversized_text_is_cut_not_errored(self):
        from eneo.main.config import get_settings

        max_chars = get_settings().mcp_tool_output_max_chars
        result = {
            "content": [{"type": "text", "text": "x" * (max_chars * 2)}],
            "is_error": False,
        }

        truncated = self._truncate(result)

        assert truncated["is_error"] is False
        head, notice = truncated["content"]
        assert head["text"].startswith("x")
        assert len(head["text"]) < max_chars
        assert "truncated" in notice["text"]

    def test_leading_blocks_kept_whole_and_tail_dropped(self):
        from eneo.main.config import get_settings

        max_chars = get_settings().mcp_tool_output_max_chars
        result = {
            "content": [
                {"type": "text", "text": "first block"},
                {"type": "text", "text": "y" * (max_chars * 2)},
                {"type": "image", "data": "AAAA", "mime_type": "image/png"},
            ],
            "is_error": False,
        }

        truncated = self._truncate(result)

        # Image blocks never compete for the text budget: they survive the
        # cut and follow the notice, so they still become generated files.
        first, cut, notice, image = truncated["content"]
        assert first == {"type": "text", "text": "first block"}
        assert cut["text"].startswith("y") and len(cut["text"]) < max_chars
        assert "dropped" not in notice["text"]
        assert image == {"type": "image", "data": "AAAA", "mime_type": "image/png"}

    def test_large_image_within_byte_cap_is_kept_without_truncation(self):
        from eneo.main.config import get_settings

        max_chars = get_settings().mcp_tool_output_max_chars
        image = {
            "type": "image",
            "data": "A" * (max_chars * 4),
            "mime_type": "image/png",
        }
        result = {
            "content": [{"type": "text", "text": "done"}, image],
            "is_error": False,
        }

        truncated = self._truncate(result)

        assert truncated["content"] == [{"type": "text", "text": "done"}, image]

    def test_image_over_byte_cap_is_dropped_with_notice(self, monkeypatch):
        from eneo.mcp_servers.infrastructure.proxy import mcp_proxy_session

        monkeypatch.setattr(
            mcp_proxy_session._settings,  # pyright: ignore[reportPrivateUsage]
            "mcp_tool_image_max_bytes",
            64,
        )
        result = {
            "content": [
                {"type": "text", "text": "done"},
                {"type": "image", "data": "A" * 400, "mime_type": "image/png"},
            ],
            "is_error": False,
        }

        truncated = self._truncate(result)

        text, notice = truncated["content"]
        assert text == {"type": "text", "text": "done"}
        assert notice["type"] == "text"
        assert "exceeded" in notice["text"] and "dropped" in notice["text"]

    def test_total_size_respects_budget(self):
        import json

        from eneo.main.config import get_settings

        max_chars = get_settings().mcp_tool_output_max_chars
        result = {
            "content": [
                {"type": "text", "text": "z\\" * max_chars},
                {"type": "text", "text": "tail"},
            ],
            "is_error": False,
        }

        truncated = self._truncate(result)

        # The notice block is the only allowance beyond the budget.
        without_notice = {**truncated, "content": truncated["content"][:-1]}
        serialized = json.dumps(without_notice, ensure_ascii=False, default=str)
        assert len(serialized) <= max_chars + 200
