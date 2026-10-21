"""Syncing a server stores each view its tools declare and notes the view's
hash on those tools. A view that cannot be read, has the wrong type, carries
an oversized policy or cannot be stored is left out; the sync still succeeds."""

from uuid import uuid4

from eneo.main.exceptions import MCPClientError
from eneo.mcp_apps.application.view_snapshots import (
    MAX_VIEWS_PER_SERVER,
    snapshot_app_views,
)
from eneo.mcp_apps.domain.mcp_app_view import view_content_hash
from eneo.mcp_servers.domain.entities.mcp_server import MCPServer
from eneo.mcp_servers.infrastructure.client.mcp_client import RESOURCE_META_MAX_BYTES

APP_MIME = "text/html;profile=mcp-app"
VIEW_URI = "ui://weather/dashboard"
HTML = "<html><body>weather</body></html>"


class _FakeClient:
    def __init__(self, resources: dict[str, dict | Exception]):
        self._resources = resources
        self.read: list[str] = []

    async def read_resource(self, uri: str) -> dict:
        self.read.append(uri)
        resource = self._resources[uri]
        if isinstance(resource, Exception):
            raise resource
        return resource


class _FakeRepo:
    def __init__(self, fails: bool = False):
        self.fails = fails
        self.upserts: list[dict] = []

    async def upsert(self, **kwargs):
        if self.fails:
            raise RuntimeError("database unavailable")
        self.upserts.append(kwargs)
        return uuid4()


def _server() -> MCPServer:
    return MCPServer(
        id=uuid4(),
        tenant_id=uuid4(),
        name="weather-server",
        http_url="http://weather.example/mcp",
    )


def _resource(**overrides) -> dict:
    return {
        "uri": VIEW_URI,
        "text": HTML,
        "mime_type": APP_MIME,
        "meta": {"ui": {"prefersBorder": True}},
        **overrides,
    }


def _tool(name: str, uri: str | None = VIEW_URI) -> dict:
    return {"name": name, "meta": {"ui": {"resourceUri": uri}} if uri else None}


async def _snapshot(resource: dict | Exception, repo: _FakeRepo | None = None):
    repo = repo or _FakeRepo()
    server = _server()
    tools = [_tool("get_weather")]
    await snapshot_app_views(
        _FakeClient({VIEW_URI: resource}),  # type: ignore[arg-type]
        server,
        tools,
        repo,  # type: ignore[arg-type]
    )
    return tools[0], repo, server


async def test_view_is_stored_for_the_tenant_and_its_hash_noted_on_the_tool():
    tool, repo, server = await _snapshot(_resource())

    expected = view_content_hash(HTML, {"prefersBorder": True})
    assert tool["ui_resource_sha256"] == expected
    assert repo.upserts == [
        {
            "tenant_id": server.tenant_id,
            "mcp_server_id": server.id,
            "uri": VIEW_URI,
            "content_hash": expected,
            "html": HTML,
            "ui_meta": {"prefersBorder": True},
        }
    ]


async def test_view_shared_by_several_tools_is_read_once():
    client = _FakeClient({VIEW_URI: _resource()})
    tools = [_tool("get_weather"), _tool("get_forecast"), _tool("plain", uri=None)]

    await snapshot_app_views(client, _server(), tools, _FakeRepo())  # type: ignore[arg-type]

    assert client.read == [VIEW_URI]
    assert tools[0]["ui_resource_sha256"] == tools[1]["ui_resource_sha256"]
    assert "ui_resource_sha256" not in tools[2]


async def test_plain_html_is_not_a_view():
    tool, repo, _ = await _snapshot(_resource(mime_type="text/html"))

    assert "ui_resource_sha256" not in tool
    assert repo.upserts == []


async def test_oversized_policy_is_refused_not_trimmed():
    policy = {
        "csp": {"connectDomains": ["https://x.example"]},
        "pad": "x" * RESOURCE_META_MAX_BYTES,
    }

    tool, repo, _ = await _snapshot(_resource(meta={"ui": policy}))

    assert "ui_resource_sha256" not in tool
    assert repo.upserts == []


async def test_view_that_cannot_be_read_is_left_out():
    tool, repo, _ = await _snapshot(MCPClientError("boom"))

    assert "ui_resource_sha256" not in tool
    assert repo.upserts == []


async def test_view_that_cannot_be_stored_is_left_out():
    tool, _, _ = await _snapshot(_resource(), _FakeRepo(fails=True))

    assert "ui_resource_sha256" not in tool


async def test_views_beyond_the_per_server_limit_are_not_read():
    uris = [f"ui://weather/view-{n}" for n in range(MAX_VIEWS_PER_SERVER + 1)]
    client = _FakeClient({uri: _resource(uri=uri) for uri in uris})
    tools = [_tool(f"tool_{n}", uri) for n, uri in enumerate(uris)]

    await snapshot_app_views(client, _server(), tools, _FakeRepo())  # type: ignore[arg-type]

    assert client.read == uris[:MAX_VIEWS_PER_SERVER]
    assert "ui_resource_sha256" not in tools[-1]
