"""The proxy shows the MCP App view an administrator approved for a tool: the
stored snapshot with the approved hash. It never asks the server, a tool
without an approved view has none, and a failed lookup never breaks the tool
result. A tool its server offers to its view only is not offered to the model."""

from types import SimpleNamespace
from uuid import uuid4

from eneo.mcp_apps.domain.mcp_app_view import McpAppViewInfo
from eneo.mcp_servers.domain.entities.mcp_server import MCPServer, MCPServerTool
from eneo.mcp_servers.infrastructure.proxy import mcp_proxy_session as proxy_module
from eneo.mcp_servers.infrastructure.proxy.mcp_proxy_session import MCPProxySession

APP_MIME = "text/html;profile=mcp-app"
VIEW_URI = "ui://weather/dashboard"
TOOL_NAME = "weather-server__get_weather"
APPROVED_HASH = "a" * 64
UI_TOOL_META = {"ui": {"resourceUri": VIEW_URI}}


class _FakeClient:
    """Fails the test if the proxy reads from the server."""

    async def read_resource(self, uri: str) -> dict:
        raise AssertionError("a view must come from the stored snapshot")


class _FakeRepo:
    def __init__(self, stored_hash: str | None = APPROVED_HASH, fails: bool = False):
        self.stored_hash = stored_hash
        self.fails = fails
        self.lookups: list[dict] = []

    async def find_view(self, **kwargs) -> McpAppViewInfo | None:
        self.lookups.append(kwargs)
        if self.fails:
            raise RuntimeError("database unavailable")
        if kwargs["content_hash"] != self.stored_hash:
            return None
        return McpAppViewInfo(
            view_id=uuid4(),
            mcp_server_id=kwargs["mcp_server_id"],
            uri=kwargs["uri"],
            mime_type=APP_MIME,
            ui_meta={"prefersBorder": True},
        )


def _make_proxy(
    monkeypatch,
    *,
    tool_meta: dict | None = UI_TOOL_META,
    approved_hash: str | None = APPROVED_HASH,
    repo: _FakeRepo | None = None,
    enabled: bool = True,
    for_view: bool = False,
) -> tuple[MCPProxySession, MCPServer, _FakeRepo]:
    monkeypatch.setattr(
        proxy_module,
        "get_settings",
        lambda: SimpleNamespace(mcp_apps_enabled=enabled),
    )
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
            meta=tool_meta,
            ui_resource_sha256=approved_hash,
        )
    ]
    repo = repo or _FakeRepo()
    proxy = MCPProxySession(
        [server],
        app_view_repo=repo,  # type: ignore[arg-type]
        for_view=for_view,
    )
    proxy._clients[server.id] = _FakeClient()  # type: ignore[assignment]
    return proxy, server, repo


async def test_approved_view_is_found_by_its_hash_within_the_tenant(monkeypatch):
    proxy, server, repo = _make_proxy(monkeypatch)

    info = await proxy.approved_app_view(TOOL_NAME)

    assert info is not None
    assert info.uri == VIEW_URI
    assert info.ui_meta == {"prefersBorder": True}
    assert repo.lookups == [
        {
            "tenant_id": server.tenant_id,
            "mcp_server_id": server.id,
            "uri": VIEW_URI,
            "content_hash": APPROVED_HASH,
        }
    ]


async def test_view_that_was_never_approved_is_not_shown(monkeypatch):
    proxy, _, repo = _make_proxy(monkeypatch, approved_hash=None)

    assert await proxy.approved_app_view(TOOL_NAME) is None
    assert repo.lookups == []


async def test_snapshot_with_another_hash_is_not_shown(monkeypatch):
    proxy, _, _ = _make_proxy(monkeypatch, repo=_FakeRepo(stored_hash="b" * 64))

    assert await proxy.approved_app_view(TOOL_NAME) is None


async def test_declared_resource_outside_the_ui_scheme_is_not_shown(monkeypatch):
    proxy, _, repo = _make_proxy(
        monkeypatch, tool_meta={"ui": {"resourceUri": "https://evil.example/page"}}
    )

    assert await proxy.approved_app_view(TOOL_NAME) is None
    assert repo.lookups == []


async def test_feature_off_shows_no_view(monkeypatch):
    proxy, _, repo = _make_proxy(monkeypatch, enabled=False)

    assert await proxy.approved_app_view(TOOL_NAME) is None
    assert repo.lookups == []


async def test_lookup_failure_gives_no_view_and_is_tried_once(monkeypatch):
    proxy, _, repo = _make_proxy(monkeypatch, repo=_FakeRepo(fails=True))

    assert await proxy.approved_app_view(TOOL_NAME) is None
    assert await proxy.approved_app_view(TOOL_NAME) is None
    assert len(repo.lookups) == 1


async def test_view_is_looked_up_once_per_turn(monkeypatch):
    proxy, _, repo = _make_proxy(monkeypatch)

    first = await proxy.approved_app_view(TOOL_NAME)
    second = await proxy.approved_app_view(TOOL_NAME)

    assert first is second
    assert len(repo.lookups) == 1


def test_tool_offered_to_its_view_only_is_hidden_from_the_model(monkeypatch):
    proxy, _, _ = _make_proxy(
        monkeypatch,
        tool_meta={"ui": {"resourceUri": VIEW_URI, "visibility": ["app"]}},
    )

    assert proxy.get_tools_for_llm() == []
    assert TOOL_NAME not in proxy.get_allowed_tool_names()


def test_tool_offered_to_model_and_view_stays_available(monkeypatch):
    proxy, _, _ = _make_proxy(
        monkeypatch,
        tool_meta={"ui": {"resourceUri": VIEW_URI, "visibility": ["model", "app"]}},
    )

    assert TOOL_NAME in proxy.get_allowed_tool_names()


def test_view_is_offered_the_tool_kept_for_views(monkeypatch):
    proxy, server, _ = _make_proxy(
        monkeypatch,
        tool_meta={"ui": {"resourceUri": VIEW_URI, "visibility": ["app"]}},
        for_view=True,
    )

    assert proxy.prefixed_tool_name(server.id, "get_weather") == TOOL_NAME


def test_view_is_not_offered_a_tool_kept_for_the_model(monkeypatch):
    proxy, server, _ = _make_proxy(
        monkeypatch,
        tool_meta={"ui": {"resourceUri": VIEW_URI, "visibility": ["model"]}},
        for_view=True,
    )

    assert proxy.prefixed_tool_name(server.id, "get_weather") is None


def test_tool_of_another_server_is_never_found_for_a_view(monkeypatch):
    proxy, _, _ = _make_proxy(monkeypatch, for_view=True)

    assert proxy.prefixed_tool_name(uuid4(), "get_weather") is None
