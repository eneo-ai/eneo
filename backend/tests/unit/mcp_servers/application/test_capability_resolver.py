"""Ask-time resolution of capability markers to the provider serving a user."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.mcp_servers.application import capability_resolver
from eneo.mcp_servers.application.capability_resolver import (
    active_capability_providers,
    availability_from_providers,
    general_servers_for_space,
    meets_security_classification,
    resolve_capability_servers,
    select_provider_for_user,
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


def _every_server(_server_id: object) -> bool:
    return True


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


def _scalars(records):
    result = MagicMock()
    result.all.return_value = records
    return result


class TestActiveCapabilityProviders:
    @pytest.mark.parametrize("purpose", CAPABILITY_PURPOSES)
    async def test_query_is_scoped_to_tenant_and_purpose(self, purpose):
        session = AsyncMock()
        session.scalars.return_value = _scalars([])
        tenant_id = uuid4()

        result = await active_capability_providers(
            session, tenant_id, purposes=(purpose,)
        )

        assert result == []
        statement = session.scalars.await_args.args[0]
        compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
        assert f"mcp_servers.purpose IN ('{purpose}')" in compiled
        assert "mcp_servers.is_enabled = true" in compiled
        assert tenant_id.hex in compiled

    async def test_tenant_tool_settings_overlay_effective_enablement(self, monkeypatch):
        server = _server("web_search", tools=[_tool(), _tool(enabled=False)])
        on_tool, off_tool = server.tools
        session = AsyncMock()
        session.scalars.return_value = _scalars([object()])
        session.execute.return_value = [
            (server.tenant_id, on_tool.id, False),
            (server.tenant_id, off_tool.id, True),
        ]
        monkeypatch.setattr(
            capability_resolver.MCPServerMapper, "to_entity", lambda record: server
        )

        resolved = await active_capability_providers(
            session, server.tenant_id, purposes=("web_search",)
        )

        assert resolved == [server]
        assert on_tool.is_enabled is False
        assert off_tool.is_enabled is True
        assert on_tool.is_enabled_by_default is True
        assert off_tool.is_enabled_by_default is False


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


class TestGeneralServersForSpace:
    def test_capability_markers_are_left_to_the_resolver(self):
        general = _server("general")

        assert general_servers_for_space(
            [general, _server("web_search"), _server("image_generation")],
            None,
            in_space=_every_server,
        ) == [general]

    def test_server_below_space_classification_is_left_out(self):
        """A general server is called directly, so a classification that no
        longer meets the space's must keep it out of the turn."""
        space = _classification(2)
        matching = _server("general", security_level=2, name="matching")
        above = _server("general", security_level=3, name="above")
        below = _server("general", security_level=1, name="below")
        unclassified = _server("general", name="unclassified")

        assert general_servers_for_space(
            [matching, below, above, unclassified], space, in_space=_every_server
        ) == [matching, above]

    def test_unclassified_space_keeps_every_general_server(self):
        servers = [_server("general"), _server("general", security_level=0)]

        assert (
            general_servers_for_space(servers, None, in_space=_every_server) == servers
        )

    def test_server_the_space_no_longer_has_is_left_out(self):
        # Kills the mutant that asks only the classification: a server a space
        # admin removed stayed callable for every assistant that had picked it.
        kept = _server("general", name="kept")
        removed = _server("general", name="removed")

        assert general_servers_for_space(
            [kept, removed], None, in_space=lambda server_id: server_id == kept.id
        ) == [kept]


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
        monkeypatch.setattr(capability_resolver, "active_capability_providers", lookup)
        general = _server("general")

        resolution = await resolve_capability_servers(
            AsyncMock(),
            uuid4(),
            [general],
            requested_capabilities=[
                s.purpose for s in [general] if s.purpose != "general"
            ],
            supports_tool_calling=True,
            in_space=_every_server,
        )

        assert resolution.general_servers == [general]
        assert resolution.capability_servers == []
        lookup.assert_not_awaited()

    async def test_general_server_the_space_no_longer_has_is_left_out(self):
        # Kills the mutant that resolves capabilities without asking the space.
        kept = _server("general", name="kept")
        removed = _server("general", name="removed")

        resolution = await resolve_capability_servers(
            AsyncMock(),
            uuid4(),
            [kept, removed],
            supports_tool_calling=True,
            in_space=lambda server_id: server_id == kept.id,
        )

        assert resolution.general_servers == [kept]

    async def test_general_server_below_space_classification_is_left_out(
        self, monkeypatch
    ):
        monkeypatch.setattr(
            capability_resolver, "active_capability_providers", AsyncMock()
        )
        kept = _server("general", security_level=2, name="kept")
        below = _server("general", security_level=1, name="below")

        resolution = await resolve_capability_servers(
            AsyncMock(),
            uuid4(),
            [kept, below],
            requested_capabilities=[],
            supports_tool_calling=True,
            in_space=_every_server,
            space_security_classification=_classification(2),
        )

        assert resolution.general_servers == [kept]

    async def test_markers_are_replaced_by_active_providers_in_purpose_order(
        self, monkeypatch
    ):
        active = {purpose: _server(purpose) for purpose in CAPABILITY_PURPOSES}

        async def lookup(session, tenant_id, purposes):
            # Every purpose's provider in one list, unrelated purposes too.
            return list(active.values())

        monkeypatch.setattr(capability_resolver, "active_capability_providers", lookup)
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
            in_space=_every_server,
        )

        assert resolution.general_servers == [general]
        assert resolution.capability_servers == [
            active[purpose] for purpose in CAPABILITY_PURPOSES
        ]

    async def test_model_without_tool_calling_strips_markers_and_resolves_nothing(
        self, monkeypatch
    ):
        lookup = AsyncMock()
        monkeypatch.setattr(capability_resolver, "active_capability_providers", lookup)
        markers = [_server(purpose) for purpose in CAPABILITY_PURPOSES]

        resolution = await resolve_capability_servers(
            AsyncMock(),
            uuid4(),
            markers,
            requested_capabilities=[
                s.purpose for s in markers if s.purpose != "general"
            ],
            supports_tool_calling=False,
            in_space=_every_server,
        )

        assert resolution.general_servers == []
        assert resolution.capability_servers == []
        lookup.assert_not_awaited()

    async def test_missing_or_toolless_provider_is_silently_unavailable(
        self, monkeypatch
    ):
        web_search = _server("web_search")
        toolless = _server("image_generation", tools=[_tool(approved=False)])

        async def lookup(session, tenant_id, purposes):
            return [web_search, toolless]

        monkeypatch.setattr(capability_resolver, "active_capability_providers", lookup)
        markers = [_server(purpose) for purpose in CAPABILITY_PURPOSES]

        resolution = await resolve_capability_servers(
            AsyncMock(),
            uuid4(),
            markers,
            requested_capabilities=[
                s.purpose for s in markers if s.purpose != "general"
            ],
            supports_tool_calling=True,
            in_space=_every_server,
        )

        assert resolution.capability_servers == [web_search]

    async def test_only_requested_purposes_are_looked_up(self, monkeypatch):
        looked_up: list[str] = []

        async def lookup(session, tenant_id, purposes):
            looked_up.append(purposes)
            return []

        monkeypatch.setattr(capability_resolver, "active_capability_providers", lookup)

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
            in_space=_every_server,
        )

        assert looked_up == [("image_generation",)]

    async def test_purposes_outside_the_users_permissions_are_not_looked_up(
        self, monkeypatch
    ):
        lookup = AsyncMock(return_value=[_server("web_search")])
        monkeypatch.setattr(capability_resolver, "active_capability_providers", lookup)
        markers = [_server(purpose) for purpose in CAPABILITY_PURPOSES]

        resolution = await resolve_capability_servers(
            AsyncMock(),
            uuid4(),
            markers,
            requested_capabilities=[
                s.purpose for s in markers if s.purpose != "general"
            ],
            supports_tool_calling=True,
            in_space=_every_server,
            allowed_purposes={"web_search"},
        )

        assert [s.purpose for s in resolution.capability_servers] == ["web_search"]
        assert lookup.await_args_list[0].args[2] == ("web_search",)
        assert lookup.await_count == 1

    async def test_user_group_selects_the_provider(self, monkeypatch):
        group_id = uuid4()
        default = _server("web_search", name="Default")
        targeted = _server(
            "web_search", name="Legal", audience=AUDIENCE_GROUPS, group_ids=[group_id]
        )
        monkeypatch.setattr(
            capability_resolver,
            "active_capability_providers",
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
            in_space=_every_server,
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
            in_space=_every_server,
            user_group_ids={uuid4()},
        )

        assert member.capability_servers == [targeted]
        assert outsider.capability_servers == [default]

    async def test_provider_below_space_classification_is_unavailable(
        self, monkeypatch
    ):
        monkeypatch.setattr(
            capability_resolver,
            "active_capability_providers",
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
            in_space=_every_server,
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

    async def test_query_loads_what_resolution_reads(self, monkeypatch):
        session = AsyncMock()
        session.scalars.return_value = MagicMock(all=lambda: [])

        await active_capability_providers(
            session, uuid4(), purposes=("image_generation",)
        )

        query = session.scalars.await_args.args[0]
        loaded = [str(getattr(opt, "path", "")) for opt in query._with_options]
        for relationship in (
            "tools",
            "user_groups",
            "security_classification",
            "image_model",
        ):
            assert any(relationship in path for path in loaded), relationship

    async def test_disabled_backing_model_is_silently_unavailable(self, monkeypatch):
        purpose = "image_generation"
        marker = _server(purpose)
        provider = _server(purpose, backing_model=_backing_model(enabled=False))
        monkeypatch.setattr(
            capability_resolver,
            "active_capability_providers",
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
            in_space=_every_server,
        )

        assert resolution.capability_servers == []

    async def test_enabled_backing_model_resolves(self, monkeypatch):
        purpose = "image_generation"
        marker = _server(purpose)
        provider = _server(purpose, backing_model=_backing_model())
        monkeypatch.setattr(
            capability_resolver,
            "active_capability_providers",
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
            in_space=_every_server,
        )

        assert resolution.capability_servers == [provider]


async def test_provider_attachment_without_purpose_grant_does_not_enable_capability(
    monkeypatch,
):
    lookup = AsyncMock()
    monkeypatch.setattr(capability_resolver, "active_capability_providers", lookup)
    result = await resolve_capability_servers(
        AsyncMock(),
        uuid4(),
        [_server("image_generation")],
        supports_tool_calling=True,
        in_space=_every_server,
    )
    assert result.capability_servers == []
    assert result.general_servers == []
    lookup.assert_not_awaited()


async def test_retaining_or_removing_unavailable_capability_does_not_require_provider(
    monkeypatch,
):
    lookup = AsyncMock()
    monkeypatch.setattr(capability_resolver, "active_capability_providers", lookup)
    await capability_resolver.validate_capability_additions(
        AsyncMock(), uuid4(), ["image_generation"], ["image_generation"]
    )
    await capability_resolver.validate_capability_additions(
        AsyncMock(), uuid4(), [], ["image_generation"]
    )
    lookup.assert_not_awaited()


class _ProviderSession:
    """Answers capability-provider SELECTs from in-memory providers.

    Providers come back in the given (creation) order, narrowed to the
    purposes the statement names; ``tool_settings`` is the tenant overlay.
    Each provider SELECT is counted.
    """

    def __init__(self, providers, tool_settings=None):
        self.providers = providers
        self.tool_settings = tool_settings or {}
        self.provider_selects = 0

    async def scalars(self, statement):
        self.provider_selects += 1
        compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
        return _scalars([p for p in self.providers if f"'{p.purpose}'" in compiled])

    async def execute(self, statement):
        return [
            (provider.tenant_id, tool.id, self.tool_settings[tool.id])
            for provider in self.providers
            for tool in provider.tools
            if tool.id in self.tool_settings
        ]


@pytest.fixture
def entity_records(monkeypatch):
    """The fake session's records are already entities."""
    monkeypatch.setattr(
        capability_resolver.MCPServerMapper, "to_entity", lambda record: record
    )


def _states(availability) -> dict[str, tuple[bool, str | None]]:
    assert [s.purpose for s in availability] == list(CAPABILITY_PURPOSES)
    return {s.purpose: (s.available, s.reason) for s in availability}


def _unavailable(**states) -> dict[str, tuple[bool, str | None]]:
    expected = {
        purpose: (False, "no_active_provider") for purpose in CAPABILITY_PURPOSES
    }
    expected.update(states)
    return expected


_GROUP_A, _GROUP_B, _GROUP_G, _GROUP_H = uuid4(), uuid4(), uuid4(), uuid4()


def _tie_providers():
    return [
        _server("web_search", name="Default"),
        _server(
            "web_search",
            name="Beta",
            audience=AUDIENCE_GROUPS,
            priority=10,
            group_ids=[_GROUP_B],
        ),
        _server(
            "web_search",
            name="Alpha",
            audience=AUDIENCE_GROUPS,
            priority=10,
            group_ids=[_GROUP_A],
            tools=[_tool(approved=False)],
        ),
    ]


def _mixed_purpose_providers():
    # web_search has only a group-targeted provider; image_generation has a
    # default plus a toolless group-targeted one for the same group. No
    # purpose may ever pick another purpose's provider.
    return [
        _server("image_generation", name="Images"),
        _server(
            "web_search",
            name="Legal search",
            audience=AUDIENCE_GROUPS,
            group_ids=[_GROUP_G],
        ),
        _server(
            "image_generation",
            name="Legal images",
            audience=AUDIENCE_GROUPS,
            group_ids=[_GROUP_G],
            tools=[_tool(approved=False)],
        ),
    ]


def _tool_overlay_providers():
    disabled = _server("compute")
    enabled = _server("file_creation", tools=[_tool(enabled=False)])
    return [disabled, enabled], {
        disabled.tools[0].id: False,
        enabled.tools[0].id: True,
    }


_AVAILABILITY_MATRIX = {
    "no_provider": (lambda: ([], {}), {}, _unavailable()),
    "default_only": (
        lambda: ([_server("web_search")], {}),
        {},
        _unavailable(web_search=(True, None)),
    ),
    "group_tie_tenant_scope": (
        lambda: (_tie_providers(), {}),
        {},
        _unavailable(web_search=(True, None)),
    ),
    "group_tie_picks_name_then_its_readiness": (
        lambda: (_tie_providers(), {}),
        {"user_group_ids": {_GROUP_A, _GROUP_B}},
        _unavailable(web_search=(False, "no_approved_tools")),
    ),
    "group_member_gets_its_provider": (
        lambda: (_tie_providers(), {}),
        {"user_group_ids": {_GROUP_B}},
        _unavailable(web_search=(True, None)),
    ),
    "no_approved_tools": (
        lambda: ([_server("charts", tools=[_tool(approved=False)])], {}),
        {},
        _unavailable(charts=(False, "no_approved_tools")),
    ),
    "tenant_tool_overlay": (
        _tool_overlay_providers,
        {},
        _unavailable(compute=(False, "no_approved_tools"), file_creation=(True, None)),
    ),
    "backing_model_disabled": (
        lambda: (
            [
                _server(
                    "image_generation",
                    backing_model=_backing_model(enabled=False),
                )
            ],
            {},
        ),
        {},
        _unavailable(image_generation=(False, "model_disabled")),
    ),
    "stricter_classification": (
        lambda: (
            [
                _server("web_search", security_level=0),
                _server(
                    "image_generation", backing_model=_backing_model(security_level=2)
                ),
            ],
            {},
        ),
        {"classification": _classification(1)},
        _unavailable(
            web_search=(False, "classification"), image_generation=(True, None)
        ),
    ),
    "allowed_purposes_exclude_a_purpose": (
        lambda: ([_server("web_search"), _server("image_generation")], {}),
        {"allowed_purposes": {"web_search"}},
        {
            **_unavailable(web_search=(True, None)),
            **{
                purpose: (False, "permission")
                for purpose in CAPABILITY_PURPOSES
                if purpose != "web_search"
            },
        },
    ),
    "targeted_only_tenant_scope": (
        lambda: (
            [_server("web_search", audience=AUDIENCE_GROUPS, group_ids=[_GROUP_A])],
            {},
        ),
        {"user_group_ids": None},
        _unavailable(web_search=(True, None)),
    ),
    "targeted_only_user_without_groups": (
        lambda: (
            [_server("web_search", audience=AUDIENCE_GROUPS, group_ids=[_GROUP_A])],
            {},
        ),
        {"user_group_ids": set()},
        _unavailable(),
    ),
    "mixed_purposes_outsider": (
        lambda: (_mixed_purpose_providers(), {}),
        {"user_group_ids": {_GROUP_H}},
        _unavailable(image_generation=(True, None)),
    ),
    "mixed_purposes_member": (
        lambda: (_mixed_purpose_providers(), {}),
        {"user_group_ids": {_GROUP_G}},
        _unavailable(
            web_search=(True, None), image_generation=(False, "no_approved_tools")
        ),
    ),
}


class TestCapabilityAvailability:
    @pytest.mark.parametrize(
        ("build", "kwargs", "expected"),
        list(_AVAILABILITY_MATRIX.values()),
        ids=list(_AVAILABILITY_MATRIX),
    )
    async def test_stored_readiness_matrix(
        self, entity_records, build, kwargs, expected
    ):
        providers, tool_settings = build()
        kwargs = dict(kwargs)
        classification = kwargs.pop("classification", None)

        availability = await capability_resolver.capability_availability(
            _ProviderSession(providers, tool_settings),
            uuid4(),
            classification,
            **kwargs,
        )

        assert _states(availability) == expected

    async def test_loads_every_purpose_with_one_provider_select(self, entity_records):
        session = _ProviderSession(_mixed_purpose_providers())

        await capability_resolver.capability_availability(session, uuid4())

        assert session.provider_selects == 1

    @pytest.mark.parametrize("user_group_ids", [None, set(), {_GROUP_G}, {_GROUP_H}])
    async def test_one_load_describes_every_scope(self, entity_records, user_group_ids):
        providers = _mixed_purpose_providers()
        scope = {"user_group_ids": user_group_ids, "allowed_purposes": {"web_search"}}

        assert availability_from_providers(
            providers, _classification(0), **scope
        ) == await capability_resolver.capability_availability(
            _ProviderSession(providers), uuid4(), _classification(0), **scope
        )


class TestResolveFromOneLoad:
    async def test_each_purpose_picks_only_its_own_providers(self, entity_records):
        images, legal_search, _legal_images = _mixed_purpose_providers()
        providers = [images, legal_search, _legal_images]
        requested = ["web_search", "image_generation", "file_analysis"]

        async def resolve(user_group_ids):
            return await resolve_capability_servers(
                _ProviderSession(providers),
                uuid4(),
                [],
                requested_capabilities=requested,
                supports_tool_calling=True,
                in_space=_every_server,
                user_group_ids=user_group_ids,
            )

        outsider = await resolve({_GROUP_H})
        member = await resolve({_GROUP_G})

        assert outsider.capability_servers == [images]
        assert member.capability_servers == [legal_search]

    async def test_requested_purposes_load_with_one_provider_select(
        self, entity_records
    ):
        session = _ProviderSession(_mixed_purpose_providers())

        resolution = await resolve_capability_servers(
            session,
            uuid4(),
            [],
            requested_capabilities=["web_search", "image_generation", "charts"],
            supports_tool_calling=True,
            in_space=_every_server,
        )

        assert [s.name for s in resolution.capability_servers] == ["Images"]
        assert session.provider_selects == 1
