"""Tool `_meta` rides the sync/approval pipeline: a live catalog whose meta
diverges from the approved value is staged for admin review, approval promotes
the pending value, and rejection discards it without touching the active one."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

from eneo.mcp_servers.application.mcp_server_service import MCPServerService
from eneo.mcp_servers.domain.entities.mcp_server import MCPServer, MCPServerTool
from eneo.roles.permissions import Permission

UI_META = {"io.modelcontextprotocol/ui": {"resourceUri": "ui://weather/dashboard"}}


class _InMemoryToolRepo:
    def __init__(self, tools: list[MCPServerTool]) -> None:
        self.tools = {tool.id: tool for tool in tools}

    async def stage_observed(
        self, observed_tools: list[MCPServerTool]
    ) -> list[MCPServerTool]:
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
            if not existing.has_definition_drift(
                description=observed.pending_description,
                input_schema=observed.pending_input_schema,
                meta=observed.pending_meta,
                ui_resource_sha256=observed.pending_ui_resource_sha256,
            ):
                continue
            existing.pending_description = observed.pending_description
            existing.pending_input_schema = observed.pending_input_schema
            existing.pending_meta = observed.pending_meta
            existing.pending_ui_resource_sha256 = observed.pending_ui_resource_sha256
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

    async def delete(self, id: UUID) -> None:
        del self.tools[id]


def _make_server() -> MCPServer:
    server = MCPServer(
        id=uuid4(),
        tenant_id=uuid4(),
        name="weather-server",
        http_url="http://weather.example/mcp",
    )
    server.tools = [
        MCPServerTool(
            id=uuid4(),
            mcp_server_id=server.id,
            name="get_weather",
            description="Current weather",
            input_schema={"type": "object"},
            meta=None,
        )
    ]
    return server


def _make_service(server: MCPServer, tool_repo: _InMemoryToolRepo) -> MCPServerService:
    admin = SimpleNamespace(
        tenant_id=server.tenant_id,
        permissions=[Permission.ADMIN],
    )
    server_repo = AsyncMock()
    server_repo.one.return_value = server
    return MCPServerService(server_repo, tool_repo, admin, AsyncMock())


async def test_meta_only_drift_is_staged_as_changed_tool():
    server = _make_server()
    tool_repo = _InMemoryToolRepo(server.tools)
    service = _make_service(server, tool_repo)

    result = await service._sync_discovered_tool_definitions(
        server,
        [
            {
                "name": "get_weather",
                "description": "Current weather",
                "input_schema": {"type": "object"},
                "meta": UI_META,
            }
        ],
    )

    assert [change.tool.name for change in result.changed_tools] == ["get_weather"]
    assert result.changed_tools[0].pending_meta == UI_META
    staged = (await tool_repo.by_server(server.id))[0]
    assert staged.meta is None
    assert staged.pending_meta == UI_META
    assert staged.requires_approval is True


async def test_unchanged_meta_is_not_staged():
    server = _make_server()
    server.tools[0].meta = UI_META
    tool_repo = _InMemoryToolRepo(server.tools)
    service = _make_service(server, tool_repo)

    result = await service._sync_discovered_tool_definitions(
        server,
        [
            {
                "name": "get_weather",
                "description": "Current weather",
                "input_schema": {"type": "object"},
                "meta": UI_META,
            }
        ],
    )

    assert result.changed_tools == []
    assert result.unchanged_count == 1


async def test_approve_promotes_pending_meta():
    server = _make_server()
    tool = server.tools[0]
    tool.pending_meta = UI_META
    tool.requires_approval = True
    tool_repo = _InMemoryToolRepo(server.tools)
    service = _make_service(server, tool_repo)

    approved = await service.approve_tool_changes(server.id, [tool.id])

    assert [t.name for t in approved] == ["get_weather"]
    assert approved[0].meta == UI_META
    assert approved[0].pending_meta is None
    assert approved[0].requires_approval is False


async def test_reject_clears_pending_meta_and_keeps_active():
    server = _make_server()
    tool = server.tools[0]
    tool.meta = UI_META
    tool.pending_meta = {"io.modelcontextprotocol/ui": {"resourceUri": "ui://evil"}}
    tool.requires_approval = True
    tool_repo = _InMemoryToolRepo(server.tools)
    service = _make_service(server, tool_repo)

    rejected = await service.reject_tool_changes(server.id, [tool.id])

    assert [t.name for t in rejected] == ["get_weather"]
    assert rejected[0].meta == UI_META
    assert rejected[0].pending_meta is None
    assert rejected[0].requires_approval is False


VIEW_META = {"ui": {"resourceUri": "ui://weather/dashboard"}}


def _observed(view_hash: str | None) -> dict:
    observed = {
        "name": "get_weather",
        "description": "Current weather",
        "input_schema": {"type": "object"},
        "meta": VIEW_META,
    }
    if view_hash is not None:
        observed["ui_resource_sha256"] = view_hash
    return observed


async def test_changed_view_content_is_staged_and_the_approved_view_kept():
    server = _make_server()
    tool = server.tools[0]
    tool.meta = VIEW_META
    tool.ui_resource_sha256 = "a" * 64
    tool_repo = _InMemoryToolRepo(server.tools)
    service = _make_service(server, tool_repo)

    result = await service._sync_discovered_tool_definitions(
        server, [_observed("b" * 64)]
    )

    change = result.changed_tools[0]
    assert change.current_ui_resource_sha256 == "a" * 64
    assert change.pending_ui_resource_sha256 == "b" * 64
    assert tool.ui_resource_sha256 == "a" * 64
    assert tool.requires_approval is True


async def test_sync_that_could_not_read_the_view_leaves_it_as_approved():
    server = _make_server()
    tool = server.tools[0]
    tool.meta = VIEW_META
    tool.ui_resource_sha256 = "a" * 64
    tool_repo = _InMemoryToolRepo(server.tools)
    service = _make_service(server, tool_repo)

    result = await service._sync_discovered_tool_definitions(server, [_observed(None)])

    assert result.changed_tools == []
    assert tool.ui_resource_sha256 == "a" * 64


async def test_approving_a_changed_view_makes_it_the_approved_one():
    server = _make_server()
    tool = server.tools[0]
    tool.meta = VIEW_META
    tool.ui_resource_sha256 = "a" * 64
    tool_repo = _InMemoryToolRepo(server.tools)
    service = _make_service(server, tool_repo)
    await service._sync_discovered_tool_definitions(server, [_observed("b" * 64)])

    approved = await service.approve_tool_changes(server.id, [tool.id])

    assert approved[0].ui_resource_sha256 == "b" * 64
    assert approved[0].pending_ui_resource_sha256 is None


async def test_rejecting_a_changed_view_keeps_the_approved_one():
    server = _make_server()
    tool = server.tools[0]
    tool.meta = VIEW_META
    tool.ui_resource_sha256 = "a" * 64
    tool_repo = _InMemoryToolRepo(server.tools)
    service = _make_service(server, tool_repo)
    await service._sync_discovered_tool_definitions(server, [_observed("b" * 64)])

    rejected = await service.reject_tool_changes(server.id, [tool.id])

    assert rejected[0].ui_resource_sha256 == "a" * 64
    assert rejected[0].pending_ui_resource_sha256 is None


class _ViewRepo:
    def __init__(self, views: dict[str, tuple[int, dict | None]]):
        self.views = views

    async def describe_view(self, *, content_hash: str, **scope):
        return self.views.get(content_hash)


def _service_with_views(server, tool_repo, views) -> MCPServerService:
    service = _make_service(server, tool_repo)
    service.app_view_repo = _ViewRepo(views)  # type: ignore[assignment]
    return service


async def test_review_describes_the_view_awaiting_approval_not_the_approved_one():
    server = _make_server()
    tool = server.tools[0]
    tool.meta = VIEW_META
    tool.ui_resource_sha256 = "a" * 64
    tool.pending_meta = VIEW_META
    tool.pending_ui_resource_sha256 = "b" * 64
    tool.requires_approval = True
    views = {
        "a" * 64: (100, None),
        "b" * 64: (
            2048,
            {
                "csp": {
                    "connectDomains": ["https://collect.example", "not a host"],
                    "resourceDomains": ["https://cdn.example"],
                },
                "permissions": {"camera": {}, "clipboardWrite": {}},
            },
        ),
    }
    service = _service_with_views(server, _InMemoryToolRepo(server.tools), views)

    facts = await service.describe_tool_view(server.id, tool.id)

    assert facts is not None
    assert facts.pending is True
    assert facts.size_bytes == 2048
    # Only what the served policy will really open is listed.
    assert facts.domains["connectDomains"] == ["https://collect.example"]
    assert facts.domains["resourceDomains"] == ["https://cdn.example"]
    assert facts.permissions == ["camera", "clipboardWrite"]


async def test_review_describes_the_approved_view_when_nothing_is_pending():
    server = _make_server()
    tool = server.tools[0]
    tool.meta = VIEW_META
    tool.ui_resource_sha256 = "a" * 64
    service = _service_with_views(
        server, _InMemoryToolRepo(server.tools), {"a" * 64: (100, None)}
    )

    facts = await service.describe_tool_view(server.id, tool.id)

    assert facts is not None
    assert facts.pending is False
    assert facts.domains["connectDomains"] == []
    assert facts.permissions == []


async def test_tool_without_a_stored_view_has_nothing_to_review():
    server = _make_server()
    service = _service_with_views(server, _InMemoryToolRepo(server.tools), {})

    assert await service.describe_tool_view(server.id, server.tools[0].id) is None
