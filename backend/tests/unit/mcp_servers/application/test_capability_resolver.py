"""Ask-time resolution of capability markers to active providers."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from eneo.mcp_servers.application import capability_resolver
from eneo.mcp_servers.application.capability_resolver import (
    get_active_capability_server,
    resolve_capability_servers,
    usable_capability_tools,
)
from eneo.mcp_servers.domain.entities.mcp_server import (
    CAPABILITY_PURPOSES,
    MCPServer,
    MCPServerTool,
)


def _server(purpose: str, *, tools: list[MCPServerTool] | None = None) -> MCPServer:
    server = MCPServer(
        id=uuid4(),
        tenant_id=uuid4(),
        name=f"{purpose} provider",
        http_url="http://provider.example/mcp",
        purpose=purpose,
        is_enabled=True,
    )
    server.tools = tools or [_tool()]
    return server


def _tool(*, enabled=True, removed=False, approved=True) -> MCPServerTool:
    return MCPServerTool(
        id=uuid4(),
        mcp_server_id=uuid4(),
        name="tool",
        description="Does a thing" if approved else None,
        input_schema={"type": "object"} if approved else None,
        is_enabled_by_default=enabled,
        removed_from_remote=removed,
    )


class TestUsableCapabilityTools:
    def test_filters_disabled_removed_and_unapproved(self):
        usable = _tool()
        server = _server(
            "web_search",
            tools=[
                usable,
                _tool(enabled=False),
                _tool(removed=True),
                _tool(approved=False),
            ],
        )

        assert usable_capability_tools(server) == [usable]


class TestGetActiveCapabilityServer:
    @pytest.mark.parametrize("purpose", CAPABILITY_PURPOSES)
    async def test_query_is_scoped_to_tenant_and_purpose(self, purpose):
        session = AsyncMock()
        session.scalar.return_value = None
        tenant_id = uuid4()

        result = await get_active_capability_server(session, tenant_id, purpose)

        assert result is None
        statement = session.scalar.await_args.args[0]
        compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
        assert f"mcp_servers.purpose = '{purpose}'" in compiled
        assert "mcp_servers.is_enabled = true" in compiled
        assert tenant_id.hex in compiled

    async def test_tenant_tool_settings_overlay_effective_enablement(self, monkeypatch):
        server = _server("web_search", tools=[_tool(), _tool(enabled=False)])
        on_tool, off_tool = server.tools
        session = AsyncMock()
        session.scalar.return_value = object()
        execute_result = AsyncMock()
        execute_result.all = lambda: [(on_tool.id, False), (off_tool.id, True)]
        session.execute.return_value = execute_result
        monkeypatch.setattr(
            capability_resolver.MCPServerMapper, "to_entity", lambda record: server
        )

        resolved = await get_active_capability_server(session, uuid4(), "web_search")

        assert resolved is server
        assert on_tool.is_enabled_by_default is False
        assert off_tool.is_enabled_by_default is True


class TestResolveCapabilityServers:
    async def test_general_servers_pass_through_without_lookups(self, monkeypatch):
        lookup = AsyncMock()
        monkeypatch.setattr(capability_resolver, "get_active_capability_server", lookup)
        general = _server("general")

        resolution = await resolve_capability_servers(
            AsyncMock(), uuid4(), [general], supports_tool_calling=True
        )

        assert resolution.general_servers == [general]
        assert resolution.capability_servers == []
        lookup.assert_not_awaited()

    async def test_markers_are_replaced_by_active_providers_in_purpose_order(
        self, monkeypatch
    ):
        active = {purpose: _server(purpose) for purpose in CAPABILITY_PURPOSES}

        async def lookup(session, tenant_id, purpose):
            return active[purpose]

        monkeypatch.setattr(capability_resolver, "get_active_capability_server", lookup)
        general = _server("general")
        # Attach stale markers in reverse order; resolution follows the
        # canonical CAPABILITY_PURPOSES order regardless.
        markers = [_server(purpose) for purpose in reversed(CAPABILITY_PURPOSES)]

        resolution = await resolve_capability_servers(
            AsyncMock(), uuid4(), [*markers, general], supports_tool_calling=True
        )

        assert resolution.general_servers == [general]
        assert resolution.capability_servers == [
            active[purpose] for purpose in CAPABILITY_PURPOSES
        ]

    async def test_model_without_tool_calling_strips_markers_and_resolves_nothing(
        self, monkeypatch
    ):
        lookup = AsyncMock()
        monkeypatch.setattr(capability_resolver, "get_active_capability_server", lookup)
        markers = [_server(purpose) for purpose in CAPABILITY_PURPOSES]

        resolution = await resolve_capability_servers(
            AsyncMock(), uuid4(), markers, supports_tool_calling=False
        )

        assert resolution.general_servers == []
        assert resolution.capability_servers == []
        lookup.assert_not_awaited()

    async def test_missing_or_toolless_provider_is_silently_unavailable(
        self, monkeypatch
    ):
        web_search = _server("web_search")
        toolless = _server("image_generation", tools=[_tool(approved=False)])

        async def lookup(session, tenant_id, purpose):
            return {"web_search": web_search, "image_generation": toolless}[purpose]

        monkeypatch.setattr(capability_resolver, "get_active_capability_server", lookup)
        markers = [_server(purpose) for purpose in CAPABILITY_PURPOSES]

        resolution = await resolve_capability_servers(
            AsyncMock(), uuid4(), markers, supports_tool_calling=True
        )

        assert resolution.capability_servers == [web_search]

    async def test_only_requested_purposes_are_looked_up(self, monkeypatch):
        looked_up: list[str] = []

        async def lookup(session, tenant_id, purpose):
            looked_up.append(purpose)
            return None

        monkeypatch.setattr(capability_resolver, "get_active_capability_server", lookup)

        await resolve_capability_servers(
            AsyncMock(),
            uuid4(),
            [_server("image_generation")],
            supports_tool_calling=True,
        )

        assert looked_up == ["image_generation"]
