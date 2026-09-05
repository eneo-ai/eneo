"""Ask-time resolution of capability markers to the provider serving a user."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.mcp_servers.application import capability_resolver
from eneo.mcp_servers.application.capability_resolver import (
    get_active_capability_servers,
    meets_security_classification,
    resolve_capability_servers,
    select_provider_for_user,
    usable_capability_tools,
)
from eneo.mcp_servers.domain.entities.mcp_server import (
    AUDIENCE_EVERYONE,
    AUDIENCE_GROUPS,
    CAPABILITY_PURPOSES,
    MCPServer,
    MCPServerAudienceGroup,
    MCPServerBackingModel,
    MCPServerTool,
    allowed_capability_purposes,
    capability_permission,
)
from eneo.roles.permissions import Permission
from eneo.security_classifications.domain.entities.security_classification import (
    SecurityClassification,
)


def _server(
    purpose: str,
    *,
    tools: list[MCPServerTool] | None = None,
    name: str | None = None,
    audience: str = AUDIENCE_EVERYONE,
    priority: int = 100,
    group_ids: list | None = None,
    security_level: int | None = None,
    backing_model: MCPServerBackingModel | None = None,
) -> MCPServer:
    server = MCPServer(
        id=uuid4(),
        tenant_id=uuid4(),
        name=name or f"{purpose} provider",
        http_url="http://provider.example/mcp",
        purpose=purpose,
        is_enabled=True,
        audience=audience,
        audience_priority=priority,
        user_groups=[
            MCPServerAudienceGroup(id=group_id, name="group")
            for group_id in (group_ids or [])
        ],
        security_classification=(
            _classification(security_level) if security_level is not None else None
        ),
        image_model=backing_model,
        http_auth_type="internal" if backing_model else "none",
    )
    server.tools = tools or [_tool()]
    return server


def _backing_model(
    *, enabled: bool = True, security_level: int | None = None
) -> MCPServerBackingModel:
    return MCPServerBackingModel(
        id=uuid4(),
        name="gpt-image-1",
        nickname="GPT Image",
        provider_name="OpenAI",
        is_enabled=enabled,
        is_deleted=False,
        security_classification=(
            _classification(security_level) if security_level is not None else None
        ),
    )


def _classification(level: int, *, enabled: bool = True) -> SecurityClassification:
    return SecurityClassification(
        id=uuid4(),
        tenant_id=uuid4(),
        name=f"klass {level}",
        security_level=level,
        security_enabled=enabled,
    )


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


def _scalars(records):
    result = MagicMock()
    result.all.return_value = records
    return result


class TestGetActiveCapabilityServers:
    @pytest.mark.parametrize("purpose", CAPABILITY_PURPOSES)
    async def test_query_is_scoped_to_tenant_and_purpose(self, purpose):
        session = AsyncMock()
        session.scalars.return_value = _scalars([])
        tenant_id = uuid4()

        result = await get_active_capability_servers(session, tenant_id, purpose)

        assert result == []
        statement = session.scalars.await_args.args[0]
        compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
        assert f"mcp_servers.purpose = '{purpose}'" in compiled
        assert "mcp_servers.is_enabled = true" in compiled
        assert tenant_id.hex in compiled

    async def test_tenant_tool_settings_overlay_effective_enablement(self, monkeypatch):
        server = _server("web_search", tools=[_tool(), _tool(enabled=False)])
        on_tool, off_tool = server.tools
        session = AsyncMock()
        session.scalars.return_value = _scalars([object()])
        execute_result = AsyncMock()
        execute_result.all = lambda: [(on_tool.id, False), (off_tool.id, True)]
        session.execute.return_value = execute_result
        monkeypatch.setattr(
            capability_resolver.MCPServerMapper, "to_entity", lambda record: server
        )

        resolved = await get_active_capability_servers(session, uuid4(), "web_search")

        assert resolved == [server]
        assert on_tool.is_enabled_by_default is False
        assert off_tool.is_enabled_by_default is True


class TestSelectProviderForUser:
    def test_default_provider_serves_users_outside_every_audience(self):
        default = _server("web_search")
        targeted = _server("web_search", audience=AUDIENCE_GROUPS, group_ids=[uuid4()])

        assert select_provider_for_user([targeted, default], {uuid4()}) is default

    def test_group_provider_wins_over_default_for_its_members(self):
        group_id = uuid4()
        default = _server("web_search")
        targeted = _server("web_search", audience=AUDIENCE_GROUPS, group_ids=[group_id])

        assert select_provider_for_user([default, targeted], {group_id}) is targeted

    def test_lowest_priority_then_name_breaks_group_overlap(self):
        a_id, b_id = uuid4(), uuid4()
        low = _server(
            "web_search",
            name="Zeta",
            audience=AUDIENCE_GROUPS,
            priority=10,
            group_ids=[a_id],
        )
        high = _server(
            "web_search",
            name="Alpha",
            audience=AUDIENCE_GROUPS,
            priority=20,
            group_ids=[b_id],
        )
        same = _server(
            "web_search",
            name="Beta",
            audience=AUDIENCE_GROUPS,
            priority=10,
            group_ids=[b_id],
        )

        assert select_provider_for_user([high, low, same], {a_id, b_id}) is same

    def test_no_default_and_no_matching_group_yields_nothing(self):
        targeted = _server("web_search", audience=AUDIENCE_GROUPS, group_ids=[uuid4()])

        assert select_provider_for_user([targeted], set()) is None


class TestMeetsSecurityClassification:
    def test_unclassified_space_accepts_everything(self):
        assert meets_security_classification(_server("web_search"), None)

    def test_stricter_space_rejects_lower_or_missing_provider_level(self):
        space = _classification(1)

        assert not meets_security_classification(_server("web_search"), space)
        assert not meets_security_classification(
            _server("web_search", security_level=0), space
        )
        assert meets_security_classification(
            _server("web_search", security_level=1), space
        )

    def test_security_disabled_tenant_never_rejects(self):
        space = _classification(1, enabled=False)

        assert meets_security_classification(_server("web_search"), space)


class TestCapabilityPermissions:
    @pytest.mark.parametrize("purpose", CAPABILITY_PURPOSES)
    def test_every_capability_purpose_has_a_same_valued_permission(self, purpose):
        assert capability_permission(purpose) == Permission(purpose)
        assert capability_permission(purpose).value == purpose

    def test_allowed_purposes_follow_the_permission_set(self):
        assert allowed_capability_purposes(set()) == set()
        assert allowed_capability_purposes({Permission.WEB_SEARCH}) == {"web_search"}
        assert allowed_capability_purposes(
            {capability_permission(p) for p in CAPABILITY_PURPOSES}
        ) == set(CAPABILITY_PURPOSES)


class TestResolveCapabilityServers:
    async def test_general_servers_pass_through_without_lookups(self, monkeypatch):
        lookup = AsyncMock()
        monkeypatch.setattr(
            capability_resolver, "get_active_capability_servers", lookup
        )
        general = _server("general")

        resolution = await resolve_capability_servers(
            AsyncMock(),
            uuid4(),
            [general],
            requested_capabilities=[
                s.purpose for s in [general] if s.purpose != "general"
            ],
            supports_tool_calling=True,
        )

        assert resolution.general_servers == [general]
        assert resolution.capability_servers == []
        lookup.assert_not_awaited()

    async def test_markers_are_replaced_by_active_providers_in_purpose_order(
        self, monkeypatch
    ):
        active = {purpose: _server(purpose) for purpose in CAPABILITY_PURPOSES}

        async def lookup(session, tenant_id, purpose):
            return [active[purpose]]

        monkeypatch.setattr(
            capability_resolver, "get_active_capability_servers", lookup
        )
        general = _server("general")
        # Attach stale markers in reverse order; resolution follows the
        # canonical CAPABILITY_PURPOSES order regardless.
        markers = [_server(purpose) for purpose in reversed(CAPABILITY_PURPOSES)]

        resolution = await resolve_capability_servers(
            AsyncMock(),
            uuid4(),
            [*markers, general],
            requested_capabilities=[
                s.purpose for s in [*markers, general] if s.purpose != "general"
            ],
            supports_tool_calling=True,
        )

        assert resolution.general_servers == [general]
        assert resolution.capability_servers == [
            active[purpose] for purpose in CAPABILITY_PURPOSES
        ]

    async def test_model_without_tool_calling_strips_markers_and_resolves_nothing(
        self, monkeypatch
    ):
        lookup = AsyncMock()
        monkeypatch.setattr(
            capability_resolver, "get_active_capability_servers", lookup
        )
        markers = [_server(purpose) for purpose in CAPABILITY_PURPOSES]

        resolution = await resolve_capability_servers(
            AsyncMock(),
            uuid4(),
            markers,
            requested_capabilities=[
                s.purpose for s in markers if s.purpose != "general"
            ],
            supports_tool_calling=False,
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
            return [{"web_search": web_search, "image_generation": toolless}[purpose]]

        monkeypatch.setattr(
            capability_resolver, "get_active_capability_servers", lookup
        )
        markers = [_server(purpose) for purpose in CAPABILITY_PURPOSES]

        resolution = await resolve_capability_servers(
            AsyncMock(),
            uuid4(),
            markers,
            requested_capabilities=[
                s.purpose for s in markers if s.purpose != "general"
            ],
            supports_tool_calling=True,
        )

        assert resolution.capability_servers == [web_search]

    async def test_only_requested_purposes_are_looked_up(self, monkeypatch):
        looked_up: list[str] = []

        async def lookup(session, tenant_id, purpose):
            looked_up.append(purpose)
            return []

        monkeypatch.setattr(
            capability_resolver, "get_active_capability_servers", lookup
        )

        await resolve_capability_servers(
            AsyncMock(),
            uuid4(),
            [_server("image_generation")],
            requested_capabilities=[
                s.purpose
                for s in [_server("image_generation")]
                if s.purpose != "general"
            ],
            supports_tool_calling=True,
        )

        assert looked_up == ["image_generation"]

    async def test_purposes_outside_the_users_permissions_are_not_looked_up(
        self, monkeypatch
    ):
        lookup = AsyncMock(return_value=[_server("web_search")])
        monkeypatch.setattr(
            capability_resolver, "get_active_capability_servers", lookup
        )
        markers = [_server(purpose) for purpose in CAPABILITY_PURPOSES]

        resolution = await resolve_capability_servers(
            AsyncMock(),
            uuid4(),
            markers,
            requested_capabilities=[
                s.purpose for s in markers if s.purpose != "general"
            ],
            supports_tool_calling=True,
            allowed_purposes={"web_search"},
        )

        assert [s.purpose for s in resolution.capability_servers] == ["web_search"]
        assert lookup.await_args_list[0].args[2] == "web_search"
        assert lookup.await_count == 1

    async def test_user_group_selects_the_provider(self, monkeypatch):
        group_id = uuid4()
        default = _server("web_search", name="Default")
        targeted = _server(
            "web_search", name="Legal", audience=AUDIENCE_GROUPS, group_ids=[group_id]
        )
        monkeypatch.setattr(
            capability_resolver,
            "get_active_capability_servers",
            AsyncMock(return_value=[default, targeted]),
        )

        member = await resolve_capability_servers(
            AsyncMock(),
            uuid4(),
            [_server("web_search")],
            requested_capabilities=[
                s.purpose for s in [_server("web_search")] if s.purpose != "general"
            ],
            supports_tool_calling=True,
            user_group_ids={group_id},
        )
        outsider = await resolve_capability_servers(
            AsyncMock(),
            uuid4(),
            [_server("web_search")],
            requested_capabilities=[
                s.purpose for s in [_server("web_search")] if s.purpose != "general"
            ],
            supports_tool_calling=True,
            user_group_ids={uuid4()},
        )

        assert member.capability_servers == [targeted]
        assert outsider.capability_servers == [default]

    async def test_provider_below_space_classification_is_unavailable(
        self, monkeypatch
    ):
        monkeypatch.setattr(
            capability_resolver,
            "get_active_capability_servers",
            AsyncMock(return_value=[_server("web_search", security_level=0)]),
        )

        resolution = await resolve_capability_servers(
            AsyncMock(),
            uuid4(),
            [_server("web_search")],
            requested_capabilities=[
                s.purpose for s in [_server("web_search")] if s.purpose != "general"
            ],
            supports_tool_calling=True,
            space_security_classification=_classification(1),
        )

        assert resolution.capability_servers == []


class TestBackingModel:
    """A built-in provider runs on a catalog image model: the model's
    classification is what the space check sees, and a disabled model makes
    the provider unavailable."""

    def test_space_check_uses_the_backing_models_classification(self):
        provider = _server(
            "image_generation", backing_model=_backing_model(security_level=1)
        )

        assert not meets_security_classification(provider, _classification(2))
        assert meets_security_classification(provider, _classification(1))

    async def test_query_loads_the_backing_model(self, monkeypatch):
        session = AsyncMock()
        session.scalars.return_value = MagicMock(all=lambda: [])

        await get_active_capability_servers(session, uuid4(), "image_generation")

        query = session.scalars.await_args.args[0]
        loaded = [str(getattr(opt, "path", "")) for opt in query._with_options]
        assert any("image_model" in path for path in loaded)

    async def test_disabled_backing_model_is_silently_unavailable(self, monkeypatch):
        purpose = "image_generation"
        marker = _server(purpose)
        provider = _server(purpose, backing_model=_backing_model(enabled=False))
        monkeypatch.setattr(
            capability_resolver,
            "get_active_capability_servers",
            AsyncMock(return_value=[provider]),
        )

        resolution = await resolve_capability_servers(
            AsyncMock(),
            uuid4(),
            [marker],
            requested_capabilities=[
                s.purpose for s in [marker] if s.purpose != "general"
            ],
            supports_tool_calling=True,
        )

        assert resolution.capability_servers == []

    async def test_enabled_backing_model_resolves(self, monkeypatch):
        purpose = "image_generation"
        marker = _server(purpose)
        provider = _server(purpose, backing_model=_backing_model())
        monkeypatch.setattr(
            capability_resolver,
            "get_active_capability_servers",
            AsyncMock(return_value=[provider]),
        )

        resolution = await resolve_capability_servers(
            AsyncMock(),
            uuid4(),
            [marker],
            requested_capabilities=[
                s.purpose for s in [marker] if s.purpose != "general"
            ],
            supports_tool_calling=True,
        )

        assert resolution.capability_servers == [provider]


async def test_provider_attachment_without_purpose_grant_does_not_enable_capability(
    monkeypatch,
):
    lookup = AsyncMock()
    monkeypatch.setattr(capability_resolver, "get_active_capability_servers", lookup)
    result = await resolve_capability_servers(
        AsyncMock(), uuid4(), [_server("image_generation")], supports_tool_calling=True
    )
    assert result.capability_servers == []
    assert result.general_servers == []
    lookup.assert_not_awaited()


async def test_retaining_or_removing_unavailable_capability_does_not_require_provider(
    monkeypatch,
):
    lookup = AsyncMock()
    monkeypatch.setattr(capability_resolver, "get_active_capability_servers", lookup)
    await capability_resolver.validate_capability_additions(
        AsyncMock(), uuid4(), ["image_generation"], ["image_generation"]
    )
    await capability_resolver.validate_capability_additions(
        AsyncMock(), uuid4(), [], ["image_generation"]
    )
    lookup.assert_not_awaited()
