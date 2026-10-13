"""A server built into Eneo exposes the running runtime's tool definitions,
keeping only the administrator's per-tool decisions from the persisted rows.
Rows that differ from the live catalog are stored from it, with the views its
tools declare, once per catalog."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from eneo.main.exceptions import MCPClientError
from eneo.mcp_servers.application import bundled_tools
from eneo.mcp_servers.application.bundled_tools import (
    forget_catalogs,
    merge_live_tools,
    with_live_bundled_tools,
)
from eneo.mcp_servers.domain.entities.mcp_server import MCPServer, MCPServerTool

LIVE = [
    {
        "name": "query_table",
        "title": "Query table",
        "description": "Run SQL over a file.",
        "input_schema": {"type": "object", "properties": {"sql": {"type": "string"}}},
    },
    {"name": "export_table", "title": None, "description": "New", "input_schema": {}},
]


def _server(http_auth_type: str = "bundled") -> MCPServer:
    server = MCPServer(
        id=uuid4(),
        tenant_id=uuid4(),
        name="Ask a file",
        http_url="http://tool-runtime:3010/mcp/file-analysis",
        http_auth_type=http_auth_type,
        purpose="file_analysis",
    )
    server.tools = [
        MCPServerTool(
            id=uuid4(),
            mcp_server_id=server.id,
            name="query_table",
            description="Old description",
            input_schema={"type": "object", "properties": {}},
            display_name="Fråga tabell",
            is_enabled_by_default=False,
        ),
        MCPServerTool(
            id=uuid4(),
            mcp_server_id=server.id,
            name="gone_tool",
            description="Removed in the new runtime",
            input_schema={},
        ),
    ]
    return server


@pytest.fixture(autouse=True)
def fresh_cache():
    forget_catalogs()
    yield
    forget_catalogs()


@pytest.fixture(autouse=True)
def stored(monkeypatch):
    """What was stored as a server's rows, in place of the database."""
    catalogs: list[tuple[object, list[dict]]] = []

    async def store(mcp_server_id, tenant_id, tool_defs):
        catalogs.append((mcp_server_id, tool_defs))

    monkeypatch.setattr(bundled_tools, "store_own_catalog", store)
    return catalogs


def _runtime(monkeypatch, catalogs):
    """A client whose list_tools answers from ``catalogs`` in order, counting calls."""
    calls: list[str] = []

    class FakeClient:
        def __init__(self, server, *args, **kwargs):
            self.server = server

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def list_tools(self):
            calls.append(self.server.http_url)
            answer = catalogs[min(len(calls) - 1, len(catalogs) - 1)]
            if isinstance(answer, Exception):
                raise answer
            return answer

    monkeypatch.setattr(bundled_tools, "MCPClient", FakeClient)
    return calls


def test_merge_keeps_admin_decisions_and_exposes_new_tools_enabled():
    server = _server()
    stored = server.tools[0]

    tools = merge_live_tools(server, LIVE)

    assert [tool.name for tool in tools] == ["query_table", "export_table"]
    assert tools[0].id == stored.id
    assert tools[0].display_name == "Fråga tabell"
    assert tools[0].is_enabled_by_default is False
    assert tools[0].description == "Run SQL over a file."
    assert "sql" in (tools[0].input_schema or {})["properties"]
    assert tools[1].is_enabled_by_default is True


async def test_bundled_server_gets_the_live_catalog_without_touching_the_entity(
    monkeypatch,
):
    _runtime(monkeypatch, [LIVE])
    server = _server()

    live = await with_live_bundled_tools(server)

    assert [tool.name for tool in live.tools] == ["query_table", "export_table"]
    assert [tool.name for tool in server.tools] == ["query_table", "gone_tool"]


async def test_catalog_is_listed_once_per_endpoint_until_it_expires(monkeypatch):
    calls = _runtime(monkeypatch, [LIVE])
    first = _server()
    second = _server()

    await with_live_bundled_tools(first)
    await with_live_bundled_tools(second)
    assert len(calls) == 1

    forget_catalogs()
    await with_live_bundled_tools(first)
    assert len(calls) == 2


async def test_unreachable_runtime_keeps_the_persisted_snapshot(monkeypatch):
    _runtime(monkeypatch, [MCPClientError("connection refused")])
    server = _server()

    assert await with_live_bundled_tools(server) is server


async def test_other_servers_pass_through(monkeypatch):
    calls = _runtime(monkeypatch, [LIVE])
    server = _server(http_auth_type="bearer")

    assert await with_live_bundled_tools(server) is server
    assert calls == []


async def test_rows_that_differ_are_stored_once_per_catalog(monkeypatch, stored):
    _runtime(monkeypatch, [LIVE])
    server = _server()

    await with_live_bundled_tools(server)
    await with_live_bundled_tools(server)

    assert [(server_id, [d["name"] for d in defs]) for server_id, defs in stored] == [
        (server.id, ["query_table", "export_table"])
    ]


async def test_rows_that_are_current_are_left_alone(monkeypatch, stored):
    _runtime(monkeypatch, [LIVE])
    server = _server()
    server.tools = [
        MCPServerTool(
            id=uuid4(),
            mcp_server_id=server.id,
            name=tool_def["name"],
            title=tool_def["title"],
            description=tool_def["description"],
            input_schema=tool_def["input_schema"],
            display_name="Renamed by the administrator",
            is_enabled_by_default=False,
        )
        for tool_def in LIVE
    ]

    await with_live_bundled_tools(server)

    assert stored == []


async def test_a_view_stored_now_is_shown_with_this_answer(monkeypatch, stored):
    view = {"ui": {"resourceUri": "ui://file-analysis/query-result.html"}}
    catalog = [{**LIVE[0], "meta": view}, LIVE[1]]
    _runtime(monkeypatch, [catalog])
    monkeypatch.setattr(
        bundled_tools,
        "get_settings",
        lambda: SimpleNamespace(mcp_apps_enabled=True),
    )

    class _Session:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(
        bundled_tools, "sessionmanager", SimpleNamespace(session=lambda: _Session())
    )

    async def snapshot(client, server, tool_defs, repo):
        for tool_def in tool_defs:
            if tool_def.get("meta"):
                tool_def["ui_resource_sha256"] = "f" * 64

    monkeypatch.setattr(bundled_tools, "snapshot_app_views", snapshot)

    live = await with_live_bundled_tools(_server())

    assert [tool.ui_resource_sha256 for tool in live.tools] == ["f" * 64, None]
    assert stored[0][1][0]["ui_resource_sha256"] == "f" * 64
    # The catalog every tenant shares is not the one the hash was written on.
    assert "ui_resource_sha256" not in catalog[0]


async def test_a_catalog_that_cannot_be_stored_does_not_fail_the_answer(monkeypatch):
    _runtime(monkeypatch, [LIVE])

    async def fail(mcp_server_id, tenant_id, tool_defs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(bundled_tools, "store_own_catalog", fail)

    live = await with_live_bundled_tools(_server())

    assert [tool.name for tool in live.tools] == ["query_table", "export_table"]


async def test_a_stored_catalog_is_audited_as_the_systems_own_change(monkeypatch):
    _runtime(monkeypatch, [LIVE])
    server = _server()
    audit = SimpleNamespace(entries=[])

    async def log_async(**entry):
        audit.entries.append(entry)

    audit.log_async = log_async

    await with_live_bundled_tools(server, audit)
    # The rows are current now: nothing more is stored or recorded.
    await with_live_bundled_tools(server, audit)

    (entry,) = audit.entries
    assert entry["tenant_id"] == server.tenant_id
    assert entry["entity_id"] == server.id
    assert entry["action"].value == "mcp_server_updated"
    assert entry["actor_type"].value == "system"
    assert entry["actor_id"] is None
    assert entry["metadata"]["tools"] == ["query_table", "export_table"]
    assert entry["metadata"]["approved_view_hashes"] == {}


async def test_a_catalog_that_was_not_stored_is_not_audited(monkeypatch):
    _runtime(monkeypatch, [LIVE])
    audit = SimpleNamespace(entries=[])

    async def log_async(**entry):
        audit.entries.append(entry)

    async def fail(mcp_server_id, tenant_id, tool_defs):
        raise RuntimeError("database unavailable")

    audit.log_async = log_async
    monkeypatch.setattr(bundled_tools, "store_own_catalog", fail)

    await with_live_bundled_tools(_server(), audit)

    assert audit.entries == []
