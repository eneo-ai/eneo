"""Unit tests for the capability-provider boundary of MCPServerService.

Covers, for every capability purpose (web search, image generation):
- purpose literal on create DTOs (general default, capability purposes accepted)
- capability servers are created inactive (activation is explicit)
- activation guards: purpose, usable tools, reachability
- atomic switch: activating one provider deactivates the previous one for
  the same purpose only
- purpose changes on update re-home the server (inactive provider on the way
  in, enabled general server with its attachments detached on the way out)
- catalog write conflicts map to the matching domain error per constraint
- usable-tool filtering that gates provider activation
- audiences: the default provider replaces only the default, group-targeted
  providers coexist, and audience input is validated against the purpose
"""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from eneo.main.exceptions import BadRequestException, NameCollisionException
from eneo.mcp_servers.application.mcp_server_service import (
    ConnectionResult,
    MCPServerService,
    _raise_for_integrity_error,
)
from eneo.mcp_servers.domain.entities.mcp_server import (
    AUDIENCE_EVERYONE,
    AUDIENCE_GROUPS,
    CAPABILITY_PURPOSES,
    DEFAULT_AUDIENCE_PRIORITY,
    MCPServer,
    MCPServerAudienceGroup,
    MCPServerTool,
)
from eneo.mcp_servers.presentation.models import (
    MCPServerCreate,
    MCPServerPublic,
    MCPServerUpdate,
)


def _make_service():
    mock_repo = AsyncMock()
    mock_repo.session = AsyncMock()
    mock_tool_repo = AsyncMock()
    mock_user = MagicMock()
    mock_user.tenant_id = uuid4()
    mock_user.permissions = ["admin"]

    service = MCPServerService(
        mcp_server_repo=mock_repo,
        mcp_server_tool_repo=mock_tool_repo,
        user=mock_user,
    )
    return service, mock_repo, mock_tool_repo, mock_user


def _make_server(tenant_id, purpose=CAPABILITY_PURPOSES[0], is_enabled=False):
    return MCPServer(
        id=uuid4(),
        tenant_id=tenant_id,
        name="Provider",
        http_url="http://provider.example/mcp",
        purpose=purpose,
        is_enabled=is_enabled,
    )


def _make_tool(
    *,
    enabled=True,
    removed=False,
    approved=True,
):
    return MCPServerTool(
        id=uuid4(),
        mcp_server_id=uuid4(),
        name="search",
        description="Search the web" if approved else None,
        input_schema={"type": "object"} if approved else None,
        is_enabled_by_default=enabled,
        removed_from_remote=removed,
        requires_approval=not approved,
    )


class TestPurposeModels:
    def test_create_defaults_to_general(self):
        dto = MCPServerCreate(name="t", http_url="http://localhost:1")
        assert dto.purpose == "general"

    @pytest.mark.parametrize("purpose", CAPABILITY_PURPOSES)
    def test_create_accepts_capability_purposes(self, purpose):
        dto = MCPServerCreate(name="t", http_url="http://localhost:1", purpose=purpose)
        assert dto.purpose == purpose

    def test_create_rejects_unknown_purpose(self):
        with pytest.raises(ValidationError):
            MCPServerCreate(name="t", http_url="http://localhost:1", purpose="search")

    def test_public_defaults_to_general(self):
        dto = MCPServerPublic(
            id=uuid4(),
            name="t",
            description=None,
            http_url="http://localhost:1",
            http_auth_type="none",
            has_credentials=False,
            tags=None,
            icon_url=None,
            documentation_url=None,
        )
        assert dto.purpose == "general"
        assert dto.is_enabled is True


class TestCreateCapabilityServer:
    @pytest.mark.parametrize("purpose", CAPABILITY_PURPOSES)
    async def test_capability_server_is_created_inactive(self, monkeypatch, purpose):
        service, mock_repo, _, _ = _make_service()
        monkeypatch.setattr(
            service,
            "_test_connection_and_discover_tools",
            AsyncMock(return_value=([], ConnectionResult(success=True))),
        )
        mock_repo.add.side_effect = lambda server: server

        result = await service.create_mcp_server(
            name="Provider",
            http_url="http://provider.example/mcp",
            purpose=purpose,
        )

        assert result.server.purpose == purpose
        assert result.server.is_enabled is False

    async def test_general_server_is_created_enabled(self, monkeypatch):
        service, mock_repo, _, _ = _make_service()
        monkeypatch.setattr(
            service,
            "_test_connection_and_discover_tools",
            AsyncMock(return_value=([], ConnectionResult(success=True))),
        )
        mock_repo.add.side_effect = lambda server: server

        result = await service.create_mcp_server(
            name="Tools",
            http_url="http://tools.example/mcp",
        )

        assert result.server.purpose == "general"
        assert result.server.is_enabled is True


class TestActivation:
    async def test_rejects_general_purpose_server(self):
        service, mock_repo, _, user = _make_service()
        server = _make_server(user.tenant_id, purpose="general")
        mock_repo.one.return_value = server

        with pytest.raises(BadRequestException):
            await service.activate_capability_server(server.id)

    async def test_rejects_server_without_usable_tools(self, monkeypatch):
        service, mock_repo, _, user = _make_service()
        server = _make_server(user.tenant_id)
        mock_repo.one.return_value = server
        monkeypatch.setattr(
            service,
            "get_tools_with_tenant_settings",
            AsyncMock(return_value=[_make_tool(approved=False)]),
        )

        with pytest.raises(BadRequestException):
            await service.activate_capability_server(server.id)

    async def test_rejects_unreachable_server(self, monkeypatch):
        service, mock_repo, _, user = _make_service()
        server = _make_server(user.tenant_id)
        mock_repo.one.return_value = server
        monkeypatch.setattr(
            service,
            "get_tools_with_tenant_settings",
            AsyncMock(return_value=[_make_tool()]),
        )
        monkeypatch.setattr(
            service,
            "_test_connection_and_discover_tools",
            AsyncMock(
                return_value=([], ConnectionResult(success=False, error_message="down"))
            ),
        )

        with pytest.raises(BadRequestException):
            await service.activate_capability_server(server.id)

    @pytest.mark.parametrize("purpose", CAPABILITY_PURPOSES)
    async def test_activation_deactivates_previous_provider(self, monkeypatch, purpose):
        service, mock_repo, _, user = _make_service()
        server = _make_server(user.tenant_id, purpose=purpose)
        previous_id = uuid4()
        mock_repo.one.return_value = server
        mock_repo.update.side_effect = lambda obj: obj
        execute_result = MagicMock()
        execute_result.fetchall.return_value = [(previous_id,)]
        mock_repo.session.execute.return_value = execute_result
        monkeypatch.setattr(
            service,
            "get_tools_with_tenant_settings",
            AsyncMock(return_value=[_make_tool()]),
        )
        monkeypatch.setattr(
            service,
            "_test_connection_and_discover_tools",
            AsyncMock(return_value=([], ConnectionResult(success=True))),
        )

        result = await service.activate_capability_server(server.id)

        assert result.server.is_enabled is True
        assert result.deactivated_server_ids == [previous_id]
        mock_repo.session.execute.assert_awaited_once()
        # The switch is scoped to this server's own purpose: a provider for
        # another capability must stay active.
        statement = mock_repo.session.execute.await_args.args[0]
        compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
        assert f"mcp_servers.purpose = '{purpose}'" in compiled

    @pytest.mark.parametrize("purpose", CAPABILITY_PURPOSES)
    async def test_deactivation_disables_server(self, purpose):
        service, mock_repo, _, user = _make_service()
        server = _make_server(user.tenant_id, purpose=purpose, is_enabled=True)
        mock_repo.one.return_value = server
        mock_repo.update.side_effect = lambda obj: obj

        deactivated = await service.deactivate_capability_server(server.id)

        assert deactivated.is_enabled is False

    async def test_deactivation_rejects_general_server(self):
        service, mock_repo, _, user = _make_service()
        server = _make_server(user.tenant_id, purpose="general", is_enabled=True)
        mock_repo.one.return_value = server

        with pytest.raises(BadRequestException):
            await service.deactivate_capability_server(server.id)

    async def test_activation_enforces_tenant_boundary(self):
        service, mock_repo, _, _ = _make_service()
        server = _make_server(uuid4())  # different tenant
        mock_repo.one.return_value = server

        from eneo.main.exceptions import UnauthorizedException

        with pytest.raises(UnauthorizedException):
            await service.activate_capability_server(server.id)


class TestPurposeUpdate:
    def test_update_dto_accepts_capability_purposes(self):
        assert MCPServerUpdate().purpose is None
        for purpose in CAPABILITY_PURPOSES:
            assert MCPServerUpdate(purpose=purpose).purpose == purpose
        with pytest.raises(ValidationError):
            MCPServerUpdate(purpose="search")

    @pytest.mark.parametrize("purpose", CAPABILITY_PURPOSES)
    async def test_general_server_becomes_inactive_provider(self, purpose):
        service, mock_repo, _, user = _make_service()
        server = _make_server(user.tenant_id, purpose="general", is_enabled=True)
        mock_repo.one.return_value = server
        mock_repo.update.side_effect = lambda obj: obj

        result = await service.update_mcp_server(server.id, purpose=purpose)

        assert result.server.purpose == purpose
        assert result.server.is_enabled is False

    @pytest.mark.parametrize("purpose", CAPABILITY_PURPOSES)
    async def test_provider_becomes_enabled_general_server(self, purpose):
        service, mock_repo, _, user = _make_service()
        server = _make_server(user.tenant_id, purpose=purpose, is_enabled=True)
        mock_repo.one.return_value = server
        mock_repo.update.side_effect = lambda obj: obj

        result = await service.update_mcp_server(server.id, purpose="general")

        assert result.server.purpose == "general"
        assert result.server.is_enabled is True
        # Markers were admitted without the space classification check, so
        # they must not survive as attachments of a directly-called server.
        mock_repo.detach_from_spaces_and_assistants.assert_awaited_once_with(server.id)

    @pytest.mark.parametrize("purpose", CAPABILITY_PURPOSES)
    async def test_general_server_keeps_attachments_when_promoted(self, purpose):
        service, mock_repo, _, user = _make_service()
        server = _make_server(user.tenant_id, purpose="general", is_enabled=True)
        mock_repo.one.return_value = server
        mock_repo.update.side_effect = lambda obj: obj

        await service.update_mcp_server(server.id, purpose=purpose)

        mock_repo.detach_from_spaces_and_assistants.assert_not_awaited()

    async def test_switching_between_capabilities_deactivates(self):
        first, second = CAPABILITY_PURPOSES[0], CAPABILITY_PURPOSES[1]
        service, mock_repo, _, user = _make_service()
        server = _make_server(user.tenant_id, purpose=first, is_enabled=True)
        mock_repo.one.return_value = server
        mock_repo.update.side_effect = lambda obj: obj

        result = await service.update_mcp_server(server.id, purpose=second)

        assert result.server.purpose == second
        assert result.server.is_enabled is False

    @pytest.mark.parametrize("purpose", CAPABILITY_PURPOSES)
    async def test_same_purpose_keeps_activation_state(self, purpose):
        service, mock_repo, _, user = _make_service()
        server = _make_server(user.tenant_id, purpose=purpose, is_enabled=True)
        mock_repo.one.return_value = server
        mock_repo.update.side_effect = lambda obj: obj

        result = await service.update_mcp_server(
            server.id, purpose=purpose, name="Renamed"
        )

        assert result.server.is_enabled is True
        assert result.server.name == "Renamed"

    async def test_purpose_change_does_not_touch_connection(self, monkeypatch):
        service, mock_repo, _, user = _make_service()
        server = _make_server(user.tenant_id, purpose="general", is_enabled=True)
        mock_repo.one.return_value = server
        mock_repo.update.side_effect = lambda obj: obj
        probe = AsyncMock()
        monkeypatch.setattr(service, "_test_connection_and_discover_tools", probe)

        await service.update_mcp_server(server.id, purpose=CAPABILITY_PURPOSES[0])

        probe.assert_not_awaited()


def _integrity_error(constraint_name: str) -> IntegrityError:
    original = MagicMock()
    original.constraint_name = constraint_name
    return IntegrityError("INSERT INTO mcp_servers", {}, original)


class TestIntegrityErrorMapping:
    def test_name_conflict_is_a_name_collision(self):
        with pytest.raises(NameCollisionException, match="for this purpose"):
            _raise_for_integrity_error(
                _integrity_error("uq_mcp_servers_tenant_name_purpose")
            )

    def test_second_active_provider_is_a_bad_request(self):
        with pytest.raises(BadRequestException, match="already active"):
            _raise_for_integrity_error(
                _integrity_error("uq_mcp_servers_tenant_active_capability")
            )

    def test_unknown_constraint_is_re_raised(self):
        error = _integrity_error("fk_mcp_servers_tenant_id")
        with pytest.raises(IntegrityError):
            _raise_for_integrity_error(error)

    def test_constraint_name_is_read_from_message_when_not_reported(self):
        original = Exception(
            "duplicate key value violates unique constraint "
            '"uq_mcp_servers_tenant_name_purpose"'
        )
        error = IntegrityError("INSERT INTO mcp_servers", {}, original)
        with pytest.raises(NameCollisionException):
            _raise_for_integrity_error(error)

    async def test_activation_maps_index_conflict(self, monkeypatch):
        service, mock_repo, _, user = _make_service()
        server = _make_server(user.tenant_id)
        mock_repo.one.return_value = server
        mock_repo.update.side_effect = _integrity_error(
            "uq_mcp_servers_tenant_active_capability"
        )
        execute_result = MagicMock()
        execute_result.fetchall.return_value = []
        mock_repo.session.execute.return_value = execute_result
        monkeypatch.setattr(
            service,
            "get_tools_with_tenant_settings",
            AsyncMock(return_value=[_make_tool()]),
        )
        monkeypatch.setattr(
            service,
            "_test_connection_and_discover_tools",
            AsyncMock(return_value=([], ConnectionResult(success=True))),
        )

        with pytest.raises(BadRequestException, match="already active"):
            await service.activate_capability_server(server.id)


class TestUsableTools:
    def test_filters_disabled_removed_and_unapproved(self):
        service, _, _, _ = _make_service()
        usable = _make_tool()
        tools = [
            usable,
            _make_tool(enabled=False),
            _make_tool(removed=True),
            _make_tool(approved=False),
        ]

        assert service._usable_tools(tools) == [usable]


class TestAudience:
    """Who a provider serves: the tenant default or selected user groups."""

    def test_create_dto_defaults_to_everyone(self):
        dto = MCPServerCreate(name="p", http_url="http://p.example/mcp")

        assert dto.audience == "everyone"
        assert dto.user_group_ids == []
        assert dto.audience_priority == DEFAULT_AUDIENCE_PRIORITY

    def test_dtos_reject_negative_priority(self):
        with pytest.raises(ValidationError):
            MCPServerCreate(
                name="p", http_url="http://p.example/mcp", audience_priority=-1
            )
        with pytest.raises(ValidationError):
            MCPServerUpdate(audience_priority=-1)

    async def test_general_server_cannot_target_groups(self):
        service, *_ = _make_service()

        with pytest.raises(BadRequestException):
            await service._resolve_audience("general", AUDIENCE_GROUPS, [uuid4()])

    async def test_group_audience_requires_at_least_one_group(self):
        service, *_ = _make_service()

        with pytest.raises(BadRequestException):
            await service._resolve_audience(CAPABILITY_PURPOSES[0], AUDIENCE_GROUPS, [])

    async def test_default_audience_cannot_list_groups(self):
        service, *_ = _make_service()

        with pytest.raises(BadRequestException):
            await service._resolve_audience(
                CAPABILITY_PURPOSES[0], AUDIENCE_EVERYONE, [uuid4()]
            )

    async def test_groups_must_belong_to_the_tenant(self):
        service, *_ = _make_service()
        known = MagicMock(id=uuid4(), name="Legal")
        known.name = "Legal"
        service.user_groups_repo = AsyncMock()
        service.user_groups_repo.get_all_user_groups.return_value = [known]

        resolved = await service._resolve_audience(
            CAPABILITY_PURPOSES[0], AUDIENCE_GROUPS, [known.id, known.id]
        )
        assert [group.id for group in resolved] == [known.id]
        assert resolved[0].name == "Legal"

        with pytest.raises(BadRequestException):
            await service._resolve_audience(
                CAPABILITY_PURPOSES[0], AUDIENCE_GROUPS, [uuid4()]
            )

    @pytest.mark.parametrize("purpose", CAPABILITY_PURPOSES)
    async def test_group_provider_activation_deactivates_nothing(
        self, monkeypatch, purpose
    ):
        service, mock_repo, _, user = _make_service()
        server = _make_server(user.tenant_id, purpose=purpose)
        server.audience = AUDIENCE_GROUPS
        server.user_groups = [MCPServerAudienceGroup(id=uuid4(), name="Legal")]
        mock_repo.one.return_value = server
        mock_repo.update.side_effect = lambda obj: obj
        monkeypatch.setattr(
            service,
            "get_tools_with_tenant_settings",
            AsyncMock(return_value=[_make_tool()]),
        )
        monkeypatch.setattr(
            service,
            "_test_connection_and_discover_tools",
            AsyncMock(return_value=([], ConnectionResult(success=True))),
        )

        result = await service.activate_capability_server(server.id)

        assert result.server.is_enabled is True
        assert result.deactivated_server_ids == []
        mock_repo.session.execute.assert_not_awaited()

    async def test_default_provider_activation_only_replaces_the_default(
        self, monkeypatch
    ):
        service, mock_repo, _, user = _make_service()
        server = _make_server(user.tenant_id)
        mock_repo.one.return_value = server
        mock_repo.update.side_effect = lambda obj: obj
        execute_result = MagicMock()
        execute_result.fetchall.return_value = []
        mock_repo.session.execute.return_value = execute_result
        monkeypatch.setattr(
            service,
            "get_tools_with_tenant_settings",
            AsyncMock(return_value=[_make_tool()]),
        )
        monkeypatch.setattr(
            service,
            "_test_connection_and_discover_tools",
            AsyncMock(return_value=([], ConnectionResult(success=True))),
        )

        await service.activate_capability_server(server.id)

        statement = mock_repo.session.execute.await_args.args[0]
        compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
        assert "mcp_servers.audience = 'everyone'" in compiled

    async def test_moving_to_general_resets_the_audience(self):
        service, mock_repo, _, user = _make_service()
        server = _make_server(user.tenant_id, is_enabled=True)
        server.audience = AUDIENCE_GROUPS
        server.user_groups = [MCPServerAudienceGroup(id=uuid4(), name="Legal")]
        mock_repo.one.return_value = server
        mock_repo.update.side_effect = lambda obj: obj

        result = await service.update_mcp_server(server.id, purpose="general")

        assert result.server.audience == AUDIENCE_EVERYONE
        assert result.server.user_groups == []
        assert result.server.audience_priority == DEFAULT_AUDIENCE_PRIORITY
