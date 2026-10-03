"""A server built into Eneo exposes the running runtime's tool definitions,
keeping only the administrator's per-tool decisions from the persisted rows."""

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
