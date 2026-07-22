from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

import eneo.mcp_servers.infrastructure.proxy.mcp_proxy_session as proxy_module
from eneo.main.exceptions import MCPClientError
from eneo.mcp_servers.application.mcp_server_service import MCPServerService
from eneo.mcp_servers.domain.entities.mcp_server import MCPServer, MCPServerTool
from eneo.mcp_servers.infrastructure.proxy.mcp_proxy_session import MCPProxySession
from eneo.roles.permissions import Permission

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


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


class _InMemoryMcpStateRepo:
    values: dict[tuple[UUID, UUID], str] = {}
    fail_reads = False
    fail_writes = False

    def __init__(self, session: object) -> None:
        self.session = session

    async def get(self, chat_session_id: UUID, mcp_server_id: UUID) -> str | None:
        if self.fail_reads:
            raise RuntimeError("persistence unavailable")
        return self.values.get((chat_session_id, mcp_server_id))

    async def claim(
        self,
        chat_session_id: UUID,
        mcp_server_id: UUID,
        candidate_mcp_session_id: str,
        expected_mcp_session_id: str | None,
    ) -> str | None:
        if self.fail_writes:
            raise RuntimeError("persistence unavailable")
        key = (chat_session_id, mcp_server_id)
        current = self.values.get(key)
        if expected_mcp_session_id is None and current is None:
            self.values[key] = candidate_mcp_session_id
        elif current == expected_mcp_session_id:
            self.values[key] = candidate_mcp_session_id
        return self.values.get(key)


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


class _StatefulMCPClient:
    instances: list[_StatefulMCPClient] = []
    protocol_sessions: dict[str, set[str]] = {}
    terminated_session_ids: list[str] = []
    next_session_number = 1
    fail_list_tools = False
    fail_termination = False
    initial_probe_barrier: asyncio.Barrier | None = None

    def __init__(
        self,
        mcp_server: MCPServer,
        auth_credentials: dict[str, str] | None = None,
        *,
        resume_mcp_session_id: str | None = None,
        identity_headers: dict[str, str] | None = None,
        **options: object,
    ) -> None:
        self.mcp_server = mcp_server
        self.resume_mcp_session_id = resume_mcp_session_id
        self.assigned_mcp_session_id: str | None = None
        self.supports_tools_list_changed = False
        self.connect_task: asyncio.Task[object] | None = None
        self.disconnect_task: asyncio.Task[object] | None = None
        type(self).instances.append(self)

    @classmethod
    def reset(cls) -> None:
        cls.instances = []
        cls.protocol_sessions = {}
        cls.terminated_session_ids = []
        cls.next_session_number = 1
        cls.fail_list_tools = False
        cls.fail_termination = False
        cls.initial_probe_barrier = None

    async def __aenter__(self) -> "_StatefulMCPClient":
        await self.connect()
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.disconnect()

    async def connect(self) -> None:
        self.connect_task = asyncio.current_task()
        if (
            self.resume_mcp_session_id is not None
            and self.resume_mcp_session_id in self.protocol_sessions
        ):
            self.assigned_mcp_session_id = self.resume_mcp_session_id
            return

        session_id = f"protocol-{type(self).next_session_number}"
        type(self).next_session_number += 1
        self.protocol_sessions[session_id] = {"shared"}
        self.assigned_mcp_session_id = session_id

    async def disconnect(self) -> None:
        self.disconnect_task = asyncio.current_task()

    async def list_tools(self) -> list[dict[str, str]]:
        assert self.assigned_mcp_session_id is not None
        if self.fail_list_tools:
            raise MCPClientError("discovery unavailable")
        if (
            self.resume_mcp_session_id is None
            and self.initial_probe_barrier is not None
        ):
            await self.initial_probe_barrier.wait()
        return [
            {"name": name}
            for name in sorted(self.protocol_sessions[self.assigned_mcp_session_id])
        ]

    async def call_tool(
        self, name: str, arguments: dict[str, object]
    ) -> dict[str, object]:
        assert self.assigned_mcp_session_id is not None
        if name == "shared":
            self.protocol_sessions[self.assigned_mcp_session_id].add("admin_only")
        return {"content": [{"type": "text", "text": name}], "is_error": False}

    async def terminate_protocol_session(self, mcp_session_id: str) -> None:
        self.terminated_session_ids.append(mcp_session_id)
        if self.fail_termination:
            raise MCPClientError("termination unavailable")
        self.protocol_sessions.pop(mcp_session_id, None)


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

    async def terminate_protocol_session(self, mcp_session_id: str) -> None:
        raise AssertionError("A stateless probe must not require termination")


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


def _install_stateful_client(monkeypatch: pytest.MonkeyPatch) -> None:
    _StatefulMCPClient.reset()
    _InMemoryMcpStateRepo.values = {}
    _InMemoryMcpStateRepo.fail_reads = False
    _InMemoryMcpStateRepo.fail_writes = False
    monkeypatch.setattr(proxy_module, "MCPClient", _StatefulMCPClient)
    monkeypatch.setattr(proxy_module, "ChatSessionMcpStateRepo", _InMemoryMcpStateRepo)


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
    service = MCPServerService(server_repo, tool_repo, admin, AsyncMock())
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
async def test_identity_discovery_and_tool_calls_resume_one_protocol_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_stateful_client(monkeypatch)
    server = _make_identity_scoped_server()
    chat_session_id = uuid4()
    db_session = cast("AsyncSession", object())

    first_turn = MCPProxySession(
        [server],
        chat_session_id=chat_session_id,
        db_session=db_session,
        identity_headers={"X-Eneo-User-Id": "user"},
    )
    await first_turn.prepare_tools_for_context()
    assert first_turn.get_allowed_tool_names() == {"identity-server__shared"}

    [result] = await first_turn.call_tools_parallel([("identity-server__shared", {})])
    assert result["is_error"] is False
    await first_turn.close()

    second_turn = MCPProxySession(
        [server],
        chat_session_id=chat_session_id,
        db_session=db_session,
        identity_headers={"X-Eneo-User-Id": "user"},
    )
    await second_turn.prepare_tools_for_context()

    assert second_turn.get_allowed_tool_names() == {
        "identity-server__admin_only",
        "identity-server__shared",
    }
    assert _InMemoryMcpStateRepo.values == {(chat_session_id, server.id): "protocol-1"}
    assert _StatefulMCPClient.protocol_sessions == {
        "protocol-1": {"admin_only", "shared"}
    }
    assert _StatefulMCPClient.terminated_session_ids == []


@pytest.mark.asyncio
async def test_ephemeral_global_session_executes_and_terminates_assigned_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_stateful_client(monkeypatch)
    proxy = MCPProxySession([_make_server()])

    [result] = await proxy.call_tools_parallel([("server__tool", {})])

    assert result["is_error"] is False
    assert set(_StatefulMCPClient.protocol_sessions) == {"protocol-1"}

    await proxy.close()

    assert _StatefulMCPClient.protocol_sessions == {}
    assert _StatefulMCPClient.terminated_session_ids == ["protocol-1"]
    assert _StatefulMCPClient.instances[0].disconnect_task is not None


@pytest.mark.asyncio
async def test_ephemeral_identity_session_exposes_calls_and_terminates_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_stateful_client(monkeypatch)
    server = _make_identity_scoped_server()
    proxy = MCPProxySession([server], identity_headers={"X-Eneo-User-Id": "ordinary"})

    await proxy.prepare_tools_for_context()

    assert proxy.get_allowed_tool_names() == {"identity-server__shared"}
    assert _StatefulMCPClient.protocol_sessions == {}
    assert _StatefulMCPClient.terminated_session_ids == ["protocol-1"]

    [result] = await proxy.call_tools_parallel([("identity-server__shared", {})])

    assert result["is_error"] is False
    assert set(_StatefulMCPClient.protocol_sessions) == {"protocol-2"}

    await proxy.close()

    assert _StatefulMCPClient.protocol_sessions == {}
    assert _StatefulMCPClient.terminated_session_ids == [
        "protocol-1",
        "protocol-2",
    ]


@pytest.mark.asyncio
async def test_ephemeral_close_disconnects_when_termination_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_stateful_client(monkeypatch)
    _StatefulMCPClient.fail_termination = True
    proxy = MCPProxySession([_make_server()])

    [result] = await proxy.call_tools_parallel([("server__tool", {})])
    await proxy.close()

    assert result["is_error"] is False
    assert _StatefulMCPClient.terminated_session_ids == ["protocol-1"]
    assert _StatefulMCPClient.instances[0].disconnect_task is not None


@pytest.mark.asyncio
async def test_runtime_call_fails_closed_when_durable_session_has_no_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_stateful_client(monkeypatch)
    proxy = MCPProxySession([_make_server()], chat_session_id=uuid4())

    [result] = await proxy.call_tools_parallel([("server__tool", {})])

    assert result["is_error"] is True
    assert _StatefulMCPClient.protocol_sessions == {}
    assert _StatefulMCPClient.terminated_session_ids == ["protocol-1"]
    assert _StatefulMCPClient.instances[0].disconnect_task is not None


@pytest.mark.asyncio
async def test_concurrent_first_turn_probes_keep_one_durable_protocol_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_stateful_client(monkeypatch)
    _StatefulMCPClient.initial_probe_barrier = asyncio.Barrier(2)
    server = _make_identity_scoped_server()
    chat_session_id = uuid4()
    db_session = cast("AsyncSession", object())
    proxies = [
        MCPProxySession(
            [server],
            chat_session_id=chat_session_id,
            db_session=db_session,
            identity_headers={"X-Eneo-User-Id": "user"},
        )
        for _ in range(2)
    ]

    await asyncio.wait_for(
        asyncio.gather(*(proxy.prepare_tools_for_context() for proxy in proxies)),
        timeout=0.5,
    )

    [durable_id] = _InMemoryMcpStateRepo.values.values()
    assert set(_StatefulMCPClient.protocol_sessions) == {durable_id}
    assert len(_StatefulMCPClient.terminated_session_ids) == 1
    assert _StatefulMCPClient.terminated_session_ids[0] != durable_id
    assert all(
        proxy.get_allowed_tool_names() == {"identity-server__shared"}
        for proxy in proxies
    )


@pytest.mark.asyncio
async def test_identity_discovery_terminates_session_when_it_cannot_be_persisted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_stateful_client(monkeypatch)
    _InMemoryMcpStateRepo.fail_writes = True
    server = _make_identity_scoped_server()
    proxy = MCPProxySession(
        [server],
        chat_session_id=uuid4(),
        db_session=cast("AsyncSession", object()),
        identity_headers={"X-Eneo-User-Id": "user"},
    )

    await proxy.prepare_tools_for_context()

    assert proxy.get_tools_for_llm() == []
    assert _StatefulMCPClient.protocol_sessions == {}
    assert _StatefulMCPClient.terminated_session_ids == ["protocol-1"]


@pytest.mark.asyncio
async def test_runtime_call_fails_closed_when_session_cannot_be_persisted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_stateful_client(monkeypatch)
    _InMemoryMcpStateRepo.fail_writes = True
    server = _make_identity_scoped_server()
    proxy = MCPProxySession(
        [server],
        chat_session_id=uuid4(),
        db_session=cast("AsyncSession", object()),
        identity_headers={"X-Eneo-User-Id": "user"},
    )

    [result] = await proxy.call_tools_parallel([("identity-server__shared", {})])

    assert result["is_error"] is True
    assert proxy._clients == {}
    assert _StatefulMCPClient.protocol_sessions == {}
    assert _StatefulMCPClient.terminated_session_ids == ["protocol-1"]
    assert _StatefulMCPClient.instances[0].disconnect_task is not None


@pytest.mark.asyncio
async def test_runtime_call_disconnects_when_unclaimed_session_termination_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_stateful_client(monkeypatch)
    _InMemoryMcpStateRepo.fail_writes = True
    _StatefulMCPClient.fail_termination = True
    server = _make_identity_scoped_server()
    proxy = MCPProxySession(
        [server],
        chat_session_id=uuid4(),
        db_session=cast("AsyncSession", object()),
        identity_headers={"X-Eneo-User-Id": "user"},
    )

    [result] = await proxy.call_tools_parallel([("identity-server__shared", {})])

    assert result["is_error"] is True
    assert proxy._clients == {}
    assert _StatefulMCPClient.terminated_session_ids == ["protocol-1"]
    assert _StatefulMCPClient.instances[0].disconnect_task is not None


@pytest.mark.asyncio
async def test_failed_discovery_does_not_terminate_a_persisted_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_stateful_client(monkeypatch)
    server = _make_identity_scoped_server()
    chat_session_id = uuid4()
    _InMemoryMcpStateRepo.values[(chat_session_id, server.id)] = "protocol-1"
    _StatefulMCPClient.protocol_sessions["protocol-1"] = {"shared"}
    _StatefulMCPClient.next_session_number = 2
    _StatefulMCPClient.fail_list_tools = True
    proxy = MCPProxySession(
        [server],
        chat_session_id=chat_session_id,
        db_session=cast("AsyncSession", object()),
        identity_headers={"X-Eneo-User-Id": "user"},
    )

    await proxy.prepare_tools_for_context()

    assert proxy.get_tools_for_llm() == []
    assert _StatefulMCPClient.protocol_sessions == {"protocol-1": {"shared"}}
    assert _StatefulMCPClient.terminated_session_ids == []


@pytest.mark.asyncio
async def test_identity_discovery_fails_closed_when_persisted_session_cannot_be_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_stateful_client(monkeypatch)
    server = _make_identity_scoped_server()
    chat_session_id = uuid4()
    _InMemoryMcpStateRepo.values[(chat_session_id, server.id)] = "protocol-1"
    _InMemoryMcpStateRepo.fail_reads = True
    _StatefulMCPClient.protocol_sessions["protocol-1"] = {"shared"}
    _StatefulMCPClient.next_session_number = 2
    proxy = MCPProxySession(
        [server],
        chat_session_id=chat_session_id,
        db_session=cast("AsyncSession", object()),
        identity_headers={"X-Eneo-User-Id": "user"},
    )

    await proxy.prepare_tools_for_context()

    assert proxy.get_tools_for_llm() == []
    assert _InMemoryMcpStateRepo.values == {(chat_session_id, server.id): "protocol-1"}
    assert _StatefulMCPClient.protocol_sessions == {"protocol-1": {"shared"}}
    assert _StatefulMCPClient.terminated_session_ids == []


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
