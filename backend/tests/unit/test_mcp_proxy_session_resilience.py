from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

import eneo.mcp_servers.infrastructure.proxy.mcp_proxy_session as proxy_module
from eneo.main.exceptions import MCPAuthenticationError, MCPClientError
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


class _RecordingMCPClient(_FakeMCPClient):
    """Fake client that keeps the constructor options the proxy passed."""

    options_by_server: dict[UUID, dict[str, object]] = {}

    def __init__(
        self,
        mcp_server: MCPServer,
        auth_credentials: dict[str, str] | None = None,
        *,
        identity_headers: dict[str, str] | None = None,
        **options: object,
    ) -> None:
        super().__init__(
            mcp_server, auth_credentials, identity_headers=identity_headers
        )
        type(self).options_by_server[mcp_server.id] = options


async def test_builtin_image_provider_gets_its_own_tool_call_budget(monkeypatch):
    """Image generation outlasts a general tool call; only the built-in
    provider carries the longer budget, other servers keep the default."""
    general = _make_server("general")
    image_provider = MCPServer(
        id=uuid4(),
        tenant_id=general.tenant_id,
        name="Images",
        http_url="http://localhost/internal-mcp/image_generation/mcp",
        http_auth_type="internal",
        purpose="image_generation",
        image_model_id=uuid4(),
    )
    monkeypatch.setattr(proxy_module, "MCPClient", _RecordingMCPClient)
    _RecordingMCPClient.options_by_server = {}
    proxy = MCPProxySession([general, image_provider])

    await proxy._get_or_create_client(general)  # pyright: ignore[reportPrivateUsage]
    await proxy._get_or_create_client(image_provider)  # pyright: ignore[reportPrivateUsage]

    options = _RecordingMCPClient.options_by_server
    assert options[general.id]["tool_call_timeout"] is None
    assert (
        options[image_provider.id]["tool_call_timeout"]
        == proxy_module._settings.image_generation_timeout_seconds  # pyright: ignore[reportPrivateUsage]
    )


def test_builtin_provider_tool_calls_are_reported_under_the_loopback_server():
    """A built-in provider's tools are Eneo's own: the trace names the
    loopback server (its purpose), not the admin-named row, so clients can
    localize them like the other internal servers. External servers keep
    their own name."""
    general = _make_server("general")
    provider_id = uuid4()
    image_provider = MCPServer(
        id=provider_id,
        tenant_id=general.tenant_id,
        name="Image Studio",
        http_url="http://localhost/internal-mcp/image_generation/mcp",
        http_auth_type="internal",
        purpose="image_generation",
        image_model_id=uuid4(),
        tools=[
            MCPServerTool(
                mcp_server_id=provider_id,
                name="generate_image",
                title="Generate image",
                description="Generate an image from a text description.",
                input_schema={"type": "object", "properties": {}},
                is_enabled_by_default=True,
            )
        ],
    )
    proxy = MCPProxySession([general, image_provider])

    assert proxy.get_tool_info("image_studio__generate_image") == (
        "image_generation",
        "generate_image",
        "Generate image",
    )
    assert proxy.get_tool_info("general__tool") == ("general", "tool", None)


def test_internal_tools_are_identified_by_the_server_flag_not_its_name():
    """Only a server built by the loopback factory is internal. An
    admin-registered server named "knowledge" or "files" is external, so its
    tools stay subject to approval and are never mistaken for the built-in
    file reader."""
    loopback_id = uuid4()
    loopback = MCPServer(
        id=loopback_id,
        tenant_id=uuid4(),
        name="files",
        http_url="http://localhost/internal-mcp/files/mcp",
        http_auth_type="bearer",
        is_internal=True,
        tools=[
            MCPServerTool(
                mcp_server_id=loopback_id,
                name="read_file",
                description="Read a file",
                input_schema={"type": "object", "properties": {}},
                is_enabled_by_default=True,
            )
        ],
    )
    impostor_id = uuid4()
    impostor = MCPServer(
        id=impostor_id,
        tenant_id=loopback.tenant_id,
        name="knowledge",
        http_url="http://external.example/mcp",
        tools=[
            MCPServerTool(
                mcp_server_id=impostor_id,
                name="search_knowledge",
                description="Not Eneo's",
                input_schema={"type": "object", "properties": {}},
                is_enabled_by_default=True,
            )
        ],
    )
    provider_id = uuid4()
    image_provider = MCPServer(
        id=provider_id,
        tenant_id=loopback.tenant_id,
        name="Image Studio",
        http_url="http://localhost/internal-mcp/image_generation/mcp",
        http_auth_type="internal",
        purpose="image_generation",
        image_model_id=uuid4(),
        tools=[
            MCPServerTool(
                mcp_server_id=provider_id,
                name="generate_image",
                description="Generate an image",
                input_schema={"type": "object", "properties": {}},
                is_enabled_by_default=True,
            )
        ],
    )
    proxy = MCPProxySession([loopback, impostor, image_provider])

    assert proxy.is_internal_tool("files__read_file") is True
    assert proxy.is_internal_tool("image_studio__generate_image") is True
    assert proxy.is_internal_tool("knowledge__search_knowledge") is False
    assert proxy.is_internal_tool("unknown__tool") is False
    assert proxy.is_bundled_tool("files__read_file") is False
    assert proxy.is_bundled_tool("unknown__tool") is False
    assert proxy.get_tool_info("knowledge__search_knowledge") == (
        "knowledge",
        "search_knowledge",
        None,
    )

    files_impostor = MCPServer(
        id=impostor_id,
        tenant_id=loopback.tenant_id,
        name="files",
        http_url="http://external.example/mcp",
        tools=[
            MCPServerTool(
                mcp_server_id=impostor_id,
                name="read_file",
                description="Not Eneo's",
                input_schema={"type": "object", "properties": {}},
                is_enabled_by_default=True,
            )
        ],
    )
    assert MCPProxySession([files_impostor])._files_read_file_entry() is None


def test_bundled_tools_are_identified_by_the_server_flag_not_its_name():
    """A server built into Eneo is known by its auth type. An external server
    an admin named after it is not, and the built-in loopback servers are
    internal rather than bundled."""
    bundled_id = uuid4()
    bundled = MCPServer(
        id=bundled_id,
        tenant_id=uuid4(),
        name="Ask a file",
        http_url="http://tool-runtime:3010/mcp/file-analysis",
        http_auth_type="bundled",
        purpose="file_analysis",
        tools=[
            MCPServerTool(
                mcp_server_id=bundled_id,
                name="query_table",
                input_schema={"type": "object", "properties": {}},
                is_enabled_by_default=True,
            )
        ],
    )
    impostor_id = uuid4()
    impostor = MCPServer(
        id=impostor_id,
        tenant_id=bundled.tenant_id,
        name="Built into Eneo",
        http_url="https://provider.example/mcp",
        http_auth_type="bearer",
        purpose="web_search",
        tools=[
            MCPServerTool(
                mcp_server_id=impostor_id,
                name="search",
                input_schema={"type": "object", "properties": {}},
                is_enabled_by_default=True,
            )
        ],
    )
    proxy = MCPProxySession([bundled, impostor])

    assert proxy.is_bundled_tool("ask_a_file__query_table") is True
    assert proxy.is_internal_tool("ask_a_file__query_table") is False
    assert proxy.is_bundled_tool("built_into_eneo__search") is False


def test_tool_purpose_names_the_capability_whichever_server_backs_it():
    """A capability provider's calls carry the purpose so clients render
    them as one function ("web search") rather than by the provider's name;
    general servers carry none, and unknown tools resolve to none."""
    general = _make_server("general")
    provider_id = uuid4()
    search_provider = MCPServer(
        id=provider_id,
        tenant_id=general.tenant_id,
        name="GDM Safe Search",
        http_url="https://search.example/mcp",
        http_auth_type="bearer",
        purpose="web_search",
        tools=[
            MCPServerTool(
                mcp_server_id=provider_id,
                name="search",
                title="Search",
                description="Search the web.",
                input_schema={"type": "object", "properties": {}},
                is_enabled_by_default=True,
            )
        ],
    )
    proxy = MCPProxySession([general, search_provider])

    assert proxy.get_tool_purpose("gdm_safe_search__search") == "web_search"
    assert proxy.get_tool_info("gdm_safe_search__search") == (
        "GDM Safe Search",
        "search",
        "Search",
    )
    assert proxy.get_tool_purpose("general__tool") is None
    assert proxy.get_tool_purpose("nope__tool") is None


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
                and existing.meta == observed.pending_meta
            ):
                continue
            existing.pending_description = observed.pending_description
            existing.pending_input_schema = observed.pending_input_schema
            existing.pending_meta = observed.pending_meta
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
    assert definition["function"]["description"].endswith("Test tool")
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
    assert definition["function"]["description"].endswith("Approved ordinary_only")
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
async def test_unscoped_server_keeps_lazy_connection_without_preflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_client(
        monkeypatch,
        live_tools_by_user={"": []},
        failing_users={""},
    )
    proxy = MCPProxySession([_make_server()])

    await proxy.prepare_tools_for_context()

    assert proxy.get_allowed_tool_names() == {"server__tool"}
    assert _FakeMCPClient.instances == []
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
async def test_unauthorized_tool_result_keeps_original_and_allows_corrected_call():
    server = _make_server(name="Sundsvall.se")
    proxy = MCPProxySession([server])
    client = SimpleNamespace(
        call_tool=AsyncMock(
            side_effect=[
                {
                    "content": [{"type": "text", "text": '{"error":"Unauthorized"}'}],
                    "is_error": True,
                    "meta": {"request_id": "upstream-123"},
                },
                {"content": [{"type": "text", "text": "works"}], "is_error": False},
            ]
        )
    )
    proxy._clients[server.id] = client

    first = await proxy.call_tool("sundsvall_se__tool", {"query": "bad"})
    corrected = await proxy.call_tool("sundsvall_se__tool", {"query": "good"})

    assert first["is_error"] is True
    assert first["content"][0]["text"] == '{"error":"Unauthorized"}'
    assert "credentials" in first["content"][1]["text"]
    assert first["meta"] == {"request_id": "upstream-123"}
    assert corrected["content"][0]["text"] == "works"
    assert client.call_tool.await_count == 2
    assert server.id not in proxy_module._CIRCUIT_BREAKER_STATE


@pytest.mark.asyncio
async def test_error_text_containing_401_does_not_imply_authentication_failure():
    server = _make_server()
    proxy = MCPProxySession([server])
    error = {
        "content": [{"type": "text", "text": "Page 401 failed to parse"}],
        "is_error": True,
    }
    proxy._clients[server.id] = SimpleNamespace(call_tool=AsyncMock(return_value=error))

    result = await proxy.call_tool("server__tool", {})

    assert result == error


@pytest.mark.asyncio
async def test_tool_error_result_does_not_trip_server_circuit_breaker():
    server = _make_server()
    proxy = MCPProxySession([server])
    client = SimpleNamespace(
        call_tool=AsyncMock(
            return_value={
                "content": [{"type": "text", "text": "Bad argument"}],
                "is_error": True,
            }
        )
    )
    proxy._clients[server.id] = client

    for _ in range(proxy_module._settings.mcp_circuit_breaker_failure_threshold + 1):
        result = await proxy.call_tool("server__tool", {})
        assert result["content"][0]["text"] == "Bad argument"

    assert client.call_tool.await_count == (
        proxy_module._settings.mcp_circuit_breaker_failure_threshold + 1
    )
    assert server.id not in proxy_module._CIRCUIT_BREAKER_STATE


@pytest.mark.asyncio
async def test_transport_authentication_failure_returns_actionable_error():
    server = _make_server()
    proxy = MCPProxySession([server])
    client = SimpleNamespace(
        call_tool=AsyncMock(
            side_effect=[
                MCPAuthenticationError("HTTP 401"),
                {"content": [{"type": "text", "text": "works"}], "is_error": False},
            ]
        )
    )
    proxy._clients[server.id] = client

    result = await proxy.call_tool("server__tool", {})
    retry = await proxy.call_tool("server__tool", {})

    assert result["is_error"] is True
    assert "credentials" in result["content"][0]["text"]
    assert retry["is_error"] is False
    assert server.id not in proxy._failed_server_ids
    assert server.id not in proxy_module._CIRCUIT_BREAKER_STATE


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
        is_internal=True,
    )


def _reference_url(file_id: UUID) -> str:
    from eneo.authentication.signed_urls import build_signed_original_download_url

    return build_signed_original_download_url(
        file_id=file_id,
        base_url="http://host.docker.internal:8123",
        expires_in=3600,
        tenant_id=uuid4(),
    )


def _conversation_reference_url(proxy: MCPProxySession) -> str:
    """A signed link to a file the proxy's conversation owns."""
    file_id = uuid4()
    proxy.allow_file_references([file_id])
    return _reference_url(file_id)


class TestReferenceFallbackHint:
    """A failed tool call that carried a signed attachment reference points the
    model at the loopback read_file instead of inviting a retry loop. The hint
    keys on the argument shape, not on which server failed, and only appears
    when read_file is actually registered."""

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

        result = await proxy.call_tool(
            "tabular__tool", {"url": _conversation_reference_url(proxy)}
        )

        assert result["is_error"] is True
        texts = [block["text"] for block in result["content"]]
        assert any("files__read_file" in text for text in texts)
        assert any('"Read attached file"' in text for text in texts)

    @pytest.mark.parametrize(
        "error",
        [
            "MCP error -32602: Input validation error: source.value_columns exceeds 8",
            "Input validation error: Invalid arguments for tool create_chart",
        ],
    )
    async def test_invalid_arguments_recover_with_same_tool_not_file_reader(
        self, error
    ):
        external = _make_server(name="charts")
        proxy = MCPProxySession([_make_files_loopback_server(), external])
        proxy._clients[external.id] = SimpleNamespace(
            call_tool=AsyncMock(
                return_value={
                    "content": [{"type": "text", "text": error}],
                    "is_error": True,
                }
            )
        )

        result = await proxy.call_tool(
            "charts__tool", {"source": {"url": _conversation_reference_url(proxy)}}
        )

        texts = [block["text"] for block in result["content"]]
        assert any("retry the same tool" in text for text in texts)
        assert not any("files__read_file" in text for text in texts)
        assert not any("still readable" in text for text in texts)
        assert external.id not in proxy._failed_server_ids

    async def test_no_hint_for_non_reference_arguments(self):
        external = _make_server(name="tabular")
        proxy = MCPProxySession([_make_files_loopback_server(), external])
        proxy._clients[external.id] = self._failing_client()

        result = await proxy.call_tool(
            "tabular__tool", {"url": "https://example.com/data.csv"}
        )

        texts = [block["text"] for block in result["content"]]
        assert not any("files__read_file" in text for text in texts)

    async def test_reference_stays_valid_when_read_file_is_not_registered(self):
        # Image references register no reader; the notice keeps the model from
        # asking for a re-upload when a remote tool could not fetch the url.
        external = _make_server(name="tabular")
        proxy = MCPProxySession([external])
        proxy._clients[external.id] = self._failing_client()

        result = await proxy.call_tool(
            "tabular__tool", {"url": _conversation_reference_url(proxy)}
        )

        texts = [block["text"] for block in result["content"]]
        assert not any("read_file" in text for text in texts)
        assert any("do not ask the user to re-upload" in text for text in texts)

    async def test_unavailable_server_result_carries_the_hint(self):
        external = _make_server(name="tabular")
        proxy = MCPProxySession([_make_files_loopback_server(), external])
        proxy._failed_server_ids.add(external.id)

        result = await proxy.call_tool(
            "tabular__tool", {"url": _conversation_reference_url(proxy)}
        )

        message = result["content"][0]["text"]
        assert "temporarily unavailable" in message.lower()
        assert "files__read_file" in message

    async def test_read_file_failure_does_not_hint_at_itself(self):
        files_server = _make_files_loopback_server()
        proxy = MCPProxySession([files_server])
        proxy._clients[files_server.id] = self._failing_client()

        result = await proxy.call_tool(
            "files__read_file", {"url": _conversation_reference_url(proxy)}
        )

        texts = [block["text"] for block in result["content"]]
        assert not any("still readable" in text for text in texts)


class TestConversationBoundReferences:
    """A tool call may only carry signed links to its own conversation's files.

    A signed link is a bearer credential bound to a file and tenant, not to a
    conversation, so the proxy refuses a call whose arguments link to any file
    the completion layer did not register, before a server is contacted.
    """

    def _proxy(self) -> tuple[MCPProxySession, AsyncMock]:
        server = _make_server(name="tabular")
        proxy = MCPProxySession([server])
        call_tool = AsyncMock(
            return_value={"content": [{"type": "text", "text": "ok"}]}
        )
        proxy._clients[server.id] = SimpleNamespace(call_tool=call_tool)
        return proxy, call_tool

    async def test_link_to_a_file_outside_the_conversation_is_refused(self):
        proxy, call_tool = self._proxy()
        own = _conversation_reference_url(proxy)

        result = await proxy.call_tool(
            "tabular__tool",
            {
                "file": {"url": own, "filename": "own.xlsx"},
                "files": [{"url": _reference_url(uuid4()), "alias": "other"}],
            },
        )

        assert result["is_error"] is True
        assert "does not belong to this conversation" in result["content"][0]["text"]
        call_tool.assert_not_awaited()

    async def test_links_to_the_conversations_files_reach_the_tool(self):
        proxy, call_tool = self._proxy()
        arguments = {
            "file": {"url": _conversation_reference_url(proxy)},
            "files": [{"url": _conversation_reference_url(proxy)}],
        }

        result = await proxy.call_tool("tabular__tool", arguments)

        assert not result.get("is_error")
        call_tool.assert_awaited_once_with("tool", arguments)

    async def test_file_generated_during_the_turn_is_admitted_once_registered(self):
        proxy, call_tool = self._proxy()
        generated_id = uuid4()
        arguments = {"source": {"url": _reference_url(generated_id)}}

        refused = await proxy.call_tool("tabular__tool", arguments)
        proxy.allow_file_references([generated_id])
        admitted = await proxy.call_tool("tabular__tool", arguments)

        assert refused["is_error"] is True
        assert not admitted.get("is_error")
        call_tool.assert_awaited_once()

    async def test_link_embedded_in_text_or_percent_encoded_is_still_refused(self):
        proxy, call_tool = self._proxy()
        link = _reference_url(uuid4())

        embedded = await proxy.call_tool("tabular__tool", {"note": f"fetch {link} now"})
        encoded = await proxy.call_tool(
            "tabular__tool", {"url": link.replace("download", "downloa%64")}
        )

        assert embedded["is_error"] is True
        assert encoded["is_error"] is True
        call_tool.assert_not_awaited()

    async def test_foreign_redacted_link_cannot_be_resolved_or_dispatched(self):
        from eneo.authentication.signed_urls import redact_reference_tokens

        proxy, call_tool = self._proxy()
        arguments = {"url": redact_reference_tokens(_reference_url(uuid4()))}

        result = await proxy.call_tool("tabular__tool", arguments)

        assert result["is_error"] is True
        call_tool.assert_not_awaited()

    async def test_other_urls_are_not_affected(self):
        proxy, call_tool = self._proxy()

        await proxy.call_tool(
            "tabular__tool", {"url": "https://example.org/data.csv?token=abc"}
        )

        call_tool.assert_awaited_once()


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

    def test_image_with_non_raster_mime_is_dropped_with_notice(self):
        # Only raster formats become generated files; a server cannot smuggle
        # HTML or SVG into the file store through an image block.
        result = {
            "content": [
                {"type": "text", "text": "done"},
                {"type": "image", "data": "AAAA", "mime_type": "text/html"},
                {"type": "image", "data": "AAAA", "mime_type": "image/svg+xml"},
            ],
            "is_error": False,
        }

        truncated = self._truncate(result)

        text, *notices = truncated["content"]
        assert text == {"type": "text", "text": "done"}
        assert [n["type"] for n in notices] == ["text", "text"]
        assert "'text/html'" in notices[0]["text"]
        assert "'image/svg+xml'" in notices[1]["text"]

    def test_image_without_mime_is_admitted_as_png(self):
        # The adapter reads a missing type as PNG; the proxy agrees and
        # records the normalized type so the two never disagree.
        result = {
            "content": [
                {"type": "image", "data": "AAAA"},
                {"type": "image", "data": "AAAA", "mime_type": "IMAGE/JPEG; q=1"},
            ],
            "is_error": False,
        }

        truncated = self._truncate(result)

        assert truncated["content"] == [
            {"type": "image", "data": "AAAA", "mime_type": "image/png"},
            {"type": "image", "data": "AAAA", "mime_type": "image/jpeg"},
        ]

    def test_images_beyond_count_cap_are_dropped_with_one_notice(self, monkeypatch):
        from eneo.mcp_servers.infrastructure.proxy import mcp_proxy_session

        monkeypatch.setattr(
            mcp_proxy_session._settings,  # pyright: ignore[reportPrivateUsage]
            "mcp_tool_image_max_count",
            2,
        )
        images = [
            {"type": "image", "data": f"AAA{i}", "mime_type": "image/png"}
            for i in range(5)
        ]
        result = {
            "content": [{"type": "text", "text": "done"}, *images],
            "is_error": False,
        }

        truncated = self._truncate(result)

        text, notice, *kept = truncated["content"]
        assert text == {"type": "text", "text": "done"}
        assert "3 image content block(s)" in notice["text"]
        assert kept == images[:2]

    def test_document_resource_from_a_document_provider_becomes_a_file(self):
        docx = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        result = {
            "content": [
                {"type": "text", "text": "Created the report."},
                {
                    "type": "resource",
                    "uri": "eneo-tool-runtime://documents/1/Kvartalsrapport.docx",
                    "mime_type": docx,
                    "blob": "UEsDBA==",
                },
            ],
            "is_error": False,
        }

        admitted = MCPProxySession([])._truncate_tool_result(  # pyright: ignore[reportPrivateUsage]
            result, "file_creation"
        )

        assert admitted["content"] == [
            {"type": "text", "text": "Created the report."},
            {
                "type": "file",
                "data": "UEsDBA==",
                "mime_type": docx,
                "filename": "Kvartalsrapport.docx",
            },
        ]

    def test_blobs_from_other_servers_or_of_other_types_are_stripped(self):
        resource = {
            "type": "resource",
            "uri": "https://example.com/a.pdf",
            "mime_type": "application/pdf",
            "blob": "JVBERi0=",
        }
        # A general server's binary resource stays an ordinary, citable result.
        general = MCPProxySession([])._truncate_tool_result(  # pyright: ignore[reportPrivateUsage]
            {"content": [resource], "is_error": False}, "general"
        )
        assert general["content"] == [
            {k: v for k, v in resource.items() if k != "blob"}
        ]
        # A file analysis provider delivers CSV exports, never a PDF.
        sheet = MCPProxySession([])._truncate_tool_result(  # pyright: ignore[reportPrivateUsage]
            {"content": [resource], "is_error": False}, "file_analysis"
        )
        assert all(block.get("type") != "file" for block in sheet["content"])
        assert all("blob" not in block for block in sheet["content"])
        assert "unsupported type" in sheet["content"][-1]["text"]

    def test_oversized_document_is_dropped_with_notice(self, monkeypatch):
        from eneo.mcp_servers.infrastructure.proxy import mcp_proxy_session

        monkeypatch.setattr(
            mcp_proxy_session._settings,  # pyright: ignore[reportPrivateUsage]
            "mcp_tool_file_max_bytes",
            3,
        )
        result = {
            "content": [
                {
                    "type": "resource",
                    "uri": "x://report.pdf",
                    "mime_type": "application/pdf",
                    "blob": "JVBERi0xLjc=",
                }
            ],
            "is_error": False,
        }

        admitted = MCPProxySession([])._truncate_tool_result(  # pyright: ignore[reportPrivateUsage]
            result, "file_creation"
        )

        assert [block["type"] for block in admitted["content"]] == ["text"]
        assert "exceeded" in admitted["content"][0]["text"]

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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "arguments",
    [
        {"content": "1\x0025"},
        {"sheets": [{"rows": [["a\x00b"]]}]},
        {"bad\x00key": "value"},
    ],
)
async def test_invalid_text_is_recoverable_and_never_dispatched(arguments):
    proxy = MCPProxySession([_make_server()])
    name = next(iter(proxy._tool_registry))
    result = await proxy.call_tool(name, arguments)
    assert result["is_error"] is True
    assert "INVALID_TEXT" in result["content"][0]["text"]
    assert "retry" in result["content"][0]["text"]


@pytest.mark.asyncio
async def test_dispatch_uses_current_authorized_reference_and_blocks_foreign_redacted_link():
    server = _make_server(name="tabular")
    proxy = MCPProxySession([server])
    client_call = AsyncMock(return_value={"content": []})
    proxy._clients[server.id] = SimpleNamespace(call_tool=client_call)
    file_id = uuid4()
    current = _reference_url(file_id)
    proxy.allow_file_references({file_id: current})
    damaged = current.split("?token=")[0] + "?token=incorrect-token"
    await proxy.call_tool("tabular__tool", {"file": {"url": damaged}})
    client_call.assert_awaited_once_with("tool", {"file": {"url": current}})
    foreign = _reference_url(uuid4()).split("?token=")[0] + "?token=REDACTED"
    result = await proxy.call_tool("tabular__tool", {"file": {"url": foreign}})
    assert result["is_error"] is True
    assert client_call.await_count == 1


@pytest.mark.asyncio
async def test_workbook_rewrite_binds_all_sheet_sources_to_current_authorized_link():
    from copy import deepcopy

    server = _make_server(name="documents")
    proxy = MCPProxySession([server])
    client_call = AsyncMock(return_value={"content": []})
    proxy._clients[server.id] = SimpleNamespace(call_tool=client_call)
    file_id = uuid4()
    current = _reference_url(file_id)
    proxy.allow_file_references({file_id: current})
    path = current.split("?")[0]
    arguments = {
        "revises": {"url": path + "?token=REDACTED", "filename": "report.xlsx"},
        "sheets": [
            {"name": "Updated", "columns": ["Budget"], "rows": [[123]]},
            {
                "name": "Departments",
                "source": {"url": path + "?token=wrong", "sheet": "Departments"},
            },
            {
                "name": "Accounts",
                "source": {"url": path + "LITERALLY?token=wrong", "sheet": "Accounts"},
            },
            {"name": "Read me", "source": {"url": path, "sheet": "Read me"}},
        ],
    }
    original = deepcopy(arguments)
    result = await proxy.call_tool("documents__tool", arguments)
    assert not result.get("is_error")
    sent = client_call.await_args.args[1]
    assert sent["revises"]["url"] == current
    assert sent["sheets"][0] == original["sheets"][0]
    assert all(sheet["source"]["url"] == current for sheet in sent["sheets"][1:])
    assert [sheet["source"]["sheet"] for sheet in sent["sheets"][1:]] == [
        "Departments",
        "Accounts",
        "Read me",
    ]
    assert arguments == original


@pytest.mark.asyncio
@pytest.mark.parametrize("suffix", ["", "LITERALLY?token=wrong"])
async def test_malformed_reference_cannot_bypass_conversation_file_admission(suffix):
    server = _make_server(name="documents")
    proxy = MCPProxySession([server])
    client_call = AsyncMock(return_value={"content": []})
    proxy._clients[server.id] = SimpleNamespace(call_tool=client_call)
    own_id = uuid4()
    proxy.allow_file_references({own_id: _reference_url(own_id)})
    foreign = _reference_url(uuid4()).split("?")[0] + suffix
    result = await proxy.call_tool(
        "documents__tool", {"sheets": [{"source": {"url": foreign}}]}
    )
    assert result["is_error"]
    assert "does not belong to this conversation" in result["content"][0]["text"]
    client_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_file_handles_resolve_for_external_provider_and_echoes_stay_credential_free():
    import json
    from copy import deepcopy

    from eneo.files.model_file_references import file_handle

    server = _make_server(name="external_documents")
    proxy = MCPProxySession([server])

    async def echo(name, arguments):
        return {"content": [{"type": "text", "text": json.dumps(arguments)}]}

    client_call = AsyncMock(side_effect=echo)
    proxy._clients[server.id] = SimpleNamespace(call_tool=client_call)
    source, image = uuid4(), uuid4()
    source_url, image_url = _reference_url(source), _reference_url(image)
    proxy.allow_file_references({source: source_url})
    unknown_args = {"images": [{"url": file_handle(image)}]}
    refused = await proxy.call_tool("external_documents__tool", unknown_args)
    assert refused["is_error"]
    assert "UNKNOWN_FILE_REFERENCE" in refused["content"][0]["text"]
    client_call.assert_not_awaited()
    # A generated chart becomes available only after the completion layer saves it.
    proxy.allow_file_references({image: image_url})
    arguments = {"revises": {"url": file_handle(source)}, **unknown_args}
    original = deepcopy(arguments)
    result = await proxy.call_tool("external_documents__tool", arguments)
    client_call.assert_awaited_once_with(
        "tool", {"revises": {"url": source_url}, "images": [{"url": image_url}]}
    )
    model_text = proxy.model_result_text(result["content"][0]["text"])
    assert json.loads(model_text) == arguments
    assert "token=" not in model_text
    # Provider resource/display data remains unmodified for the host renderer.
    assert image_url in result["content"][0]["text"]
    assert arguments == original


@pytest.mark.asyncio
async def test_handle_from_another_request_is_not_an_authorization_grant():
    from eneo.files.model_file_references import file_handle

    server = _make_server(name="files")
    first, second = MCPProxySession([server]), MCPProxySession([server])
    file_id = uuid4()
    first.allow_file_references({file_id: _reference_url(file_id)})
    # Even knowing the file ID (or allowing it without a current URL) grants no token.
    second.allow_file_references([file_id])
    client_call = AsyncMock()
    second._clients[server.id] = SimpleNamespace(call_tool=client_call)
    result = await second.call_tool("files__tool", {"url": file_handle(file_id)})
    assert result["is_error"]
    client_call.assert_not_awaited()
