"""Capability intent survives the complete provider lifecycle in PostgreSQL."""

import re
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from sqlalchemy import select

from eneo.database.tables.capabilities_table import (
    AssistantCapabilities,
    GovernancePolicyCapabilities,
    SpaceCapabilities,
)
from eneo.database.tables.governance_policy_table import GovernancePolicies
from eneo.database.tables.mcp_server_table import MCPServers, MCPServerTools
from eneo.main.exceptions import BadRequestException
from eneo.mcp_servers.application.capability_resolver import resolve_capability_servers
from eneo.mcp_servers.application.mcp_server_service import ConnectionResult
from eneo.mcp_servers.domain.entities.mcp_server import CAPABILITY_PURPOSES


async def provider(
    session, tenant_id, name, *, purpose="image_generation", is_enabled=False
):
    row = MCPServers(
        tenant_id=tenant_id,
        name=name,
        purpose=purpose,
        http_url="https://example.test/mcp",
        http_auth_type="none",
        is_enabled=is_enabled,
    )
    session.add(row)
    await session.flush()
    session.add(
        MCPServerTools(
            mcp_server_id=row.id,
            name="generate",
            description="Generate an image",
            input_schema={"type": "object"},
            is_enabled_by_default=True,
            requires_approval=False,
            removed_from_remote=False,
        )
    )
    await session.flush()
    return row


async def test_intent_survives_switch_delete_and_restore(
    db_container, admin_user, space_factory, assistant_factory, monkeypatch
):
    async with db_container() as container:
        session = container.session()
        space = await space_factory(session, "Capability lifecycle")
        assistant = await assistant_factory(session, "Images", None, space_id=space.id)
        policy = GovernancePolicies(
            tenant_id=admin_user.tenant_id,
            scope="capability_lifecycle",
            mcp_restriction_enabled=True,
        )
        session.add(policy)
        await session.flush()
        intent = [
            (SpaceCapabilities, "space_id", space.id),
            (AssistantCapabilities, "assistant_id", assistant.id),
            (GovernancePolicyCapabilities, "policy_id", policy.id),
        ]
        for table, key, identifier in intent:
            session.add(
                table(
                    **{key: identifier, "purpose": "image_generation"},
                    **(
                        {"is_default_enabled": False}
                        if table is GovernancePolicyCapabilities
                        else {}
                    ),
                )
            )
        await session.flush()
        service = container.mcp_server_service()
        connection = AsyncMock(return_value=([], ConnectionResult(success=True)))
        monkeypatch.setattr(service, "_test_connection_and_discover_tools", connection)
        a = await provider(session, admin_user.tenant_id, "A")
        b = await provider(session, admin_user.tenant_id, "B")
        b_id = b.id
        await service.activate_capability_server(a.id)
        result = await service.activate_capability_server(b_id)
        assert result.deactivated_server_ids == [a.id]
        await service.delete_mcp_server(a.id)

        async def assert_intent(expected_provider):
            for table, key, identifier in intent:
                row = (
                    await session.scalars(
                        select(table).where(getattr(table, key) == identifier)
                    )
                ).one()
                assert row.purpose == "image_generation"
                if table is GovernancePolicyCapabilities:
                    assert row.is_default_enabled is False
            result = await resolve_capability_servers(
                session,
                admin_user.tenant_id,
                [],
                requested_capabilities=["image_generation"],
                supports_tool_calling=True,
                in_space=lambda _server_id: True,
            )
            assert [p.id for p in result.capability_servers] == expected_provider

        await assert_intent([b_id])
        # Failed validation cannot disturb B.
        c = await provider(session, admin_user.tenant_id, "C")
        c_id = c.id
        connection.return_value = (
            [],
            ConnectionResult(success=False, error_message="Offline"),
        )
        with pytest.raises(BadRequestException, match="Offline"):
            await service.activate_capability_server(c_id)
        await assert_intent([b_id])
        # A persistence failure after deactivation must roll the whole switch back.
        connection.return_value = ([], ConnectionResult(success=True))
        original_update = service.repo.update
        monkeypatch.setattr(
            service.repo, "update", AsyncMock(side_effect=RuntimeError("Write failed"))
        )
        with pytest.raises(RuntimeError, match="Write failed"):
            async with session.begin_nested():
                await service.activate_capability_server(c_id)
        monkeypatch.setattr(service.repo, "update", original_update)
        await assert_intent([b_id])
        await service.delete_mcp_server(b_id)
        await assert_intent([])
        connection.return_value = ([], ConnectionResult(success=True))
        await service.activate_capability_server(c_id)
        await assert_intent([c_id])

        # Relationship updates must retain existing purposes without duplicate keys.
        await session.refresh(space, ["capabilities"])
        space.capabilities = [SpaceCapabilities(purpose="image_generation")]
        await session.refresh(assistant, ["capabilities"])
        assistant.capabilities = [AssistantCapabilities(purpose="image_generation")]
        await session.flush()
        await assert_intent([c_id])


async def test_create_and_activate_is_one_transaction(
    db_container, admin_user, image_model_factory, monkeypatch
):
    async with db_container() as container:
        session = container.session()
        service = container.mcp_server_service()
        model = await image_model_factory(session, "transactional-image")
        tools = [
            {
                "name": "generate_image",
                "description": "Generate",
                "input_schema": {"type": "object"},
            }
        ]
        connection = AsyncMock(return_value=(tools, ConnectionResult(success=True)))
        monkeypatch.setattr(service, "_test_connection_and_discover_tools", connection)
        created = await service.create_mcp_server(
            name="Working",
            http_url="",
            http_auth_type="internal",
            purpose="image_generation",
            image_model_id=model.id,
            activate=True,
        )
        assert created.server.is_enabled
        working_id = created.server.id
        connection.side_effect = [
            (tools, ConnectionResult(success=True)),
            (
                [],
                ConnectionResult(success=False, error_message="Activation unavailable"),
            ),
        ]
        with pytest.raises(BadRequestException, match="Activation unavailable"):
            async with session.begin_nested():
                await service.create_mcp_server(
                    name="Failed replacement",
                    http_url="",
                    http_auth_type="internal",
                    purpose="image_generation",
                    image_model_id=model.id,
                    activate=True,
                )
        assert (
            await session.scalars(
                select(MCPServers.id).where(
                    MCPServers.tenant_id == admin_user.tenant_id,
                    MCPServers.is_enabled.is_(True),
                )
            )
        ).all() == [working_id]
        assert (
            await session.scalars(
                select(MCPServers.id).where(
                    MCPServers.tenant_id == admin_user.tenant_id,
                    MCPServers.name == "Failed replacement",
                )
            )
        ).all() == []


_PROVIDER_SELECT = re.compile(
    r"FROM mcp_servers\b.*\bmcp_servers\.purpose (=|IN)", re.S
)


async def test_space_and_ask_load_capability_providers_once(
    db_container, admin_user, space_factory, assistant_factory
):
    async with db_container() as container:
        session = container.session()
        space = await space_factory(session, "Capability load")
        assistant = await assistant_factory(session, "Search", None, space_id=space.id)
        session.add(SpaceCapabilities(space_id=space.id, purpose="web_search"))
        for purpose in ("web_search", "image_generation"):
            await provider(
                session, admin_user.tenant_id, purpose, purpose=purpose, is_enabled=True
            )

        statements: list[str] = []

        def capture_statement(
            _connection, _cursor, statement, _parameters, _context, _executemany
        ) -> None:
            statements.append(statement)

        assert session.bind is not None
        engine = session.bind.sync_engine
        sa.event.listen(engine, "before_cursor_execute", capture_statement)
        try:
            loaded = await container.space_repo().get_space_by_assistant(assistant.id)
            space_selects = sum(map(bool, map(_PROVIDER_SELECT.search, statements)))
            statements.clear()
            resolution = await resolve_capability_servers(
                session,
                admin_user.tenant_id,
                [],
                requested_capabilities=["web_search", "image_generation"],
                supports_tool_calling=True,
                in_space=lambda _server_id: True,
            )
            ask_selects = sum(map(bool, map(_PROVIDER_SELECT.search, statements)))
        finally:
            sa.event.remove(engine, "before_cursor_execute", capture_statement)

        tenant_states = {s.purpose: s for s in loaded.available_capabilities}
        assert tenant_states["web_search"].available
        assert tenant_states["image_generation"].available
        [loaded_assistant] = [a for a in loaded.assistants if a.id == assistant.id]
        assert [s.purpose for s in loaded_assistant.available_capabilities] == list(
            CAPABILITY_PURPOSES
        )
        assistant_states = {
            s.purpose: s for s in loaded_assistant.available_capabilities
        }
        assert assistant_states["image_generation"].reason == "space_disabled"
        assert [p.purpose for p in resolution.capability_servers] == [
            "web_search",
            "image_generation",
        ]
        # The tenant-wide and user-scoped availability share one provider
        # load, and ask-time resolution loads every requested purpose at once.
        assert space_selects == 1
        assert ask_selects == 1
