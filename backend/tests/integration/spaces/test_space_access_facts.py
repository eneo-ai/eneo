"""A permission decision on a space, loaded without the space's MCP catalog."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import ORMExecuteState

from eneo.actors.actors.space_actor import SpaceActor
from eneo.database.tables.assistant_table import AssistantMCPServers
from eneo.database.tables.mcp_server_table import (
    MCPServers,
    MCPServerTools,
    SpacesMCPServers,
)
from eneo.database.tables.spaces_table import Spaces, SpacesUserGroups, SpacesUsers
from eneo.database.tables.user_groups_table import UserGroups
from eneo.database.tables.users_table import usergroups_users_table
from eneo.main.exceptions import NotFoundException, UnauthorizedException
from eneo.roles.permissions import Permission
from eneo.roles.role import RoleCreate
from eneo.users.user import UserInDB

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_Decision = tuple[object, ...]


def _reads_mcp_catalog(sql: str) -> bool:
    """A statement reads an MCP tool, or an MCP server that is not one an
    assistant of the space attaches (the space's server options and the
    capability providers)."""
    return "mcp_server_tools" in sql or (
        re.search(r"\bmcp_servers\b", sql) is not None
        and "assistant_mcp_servers" not in sql
    )


def _decision(actor: SpaceActor) -> _Decision:
    return (actor.can_read_space(), actor.can_read_flows(), actor.can_edit_flows())


async def _decided(load: Callable[[], Awaitable[SpaceActor]]) -> _Decision:
    try:
        return _decision(await load())
    except UnauthorizedException as refused:
        return (403, refused.code)
    except NotFoundException:
        return (404,)


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("editor", (True, True, True)),
        ("viewer", (True, True, False)),
        ("outsider", (403, "forbidden_action")),
        ("group-editor-in-the-loaded-user-only", (True, True, True)),
        ("unknown-space", (404,)),
    ],
)
async def test_the_access_facts_decide_as_the_loaded_space(
    db_container,
    user_factory,
    completion_model_factory,
    assistant_factory,
    case: str,
    expected: _Decision,
) -> None:
    """Kills the mutants of the load a flow's access check uses instead of
    the whole space: one that answers another refusal than get_space's 403
    forbidden_action, takes group roles from the stored memberships instead
    of the loaded user's (as read_space_access_facts does), or still reads
    the MCP catalog: the space's server options with their tools (here an
    activated server with a tool), an assistant's servers' tools (the same
    server, attached to an assistant of the space) or the capability
    providers."""
    async with db_container() as container:
        session = container.session()
        admin = container.user()
        org_id = await session.scalar(
            sa.select(Spaces.id).where(
                Spaces.tenant_id == admin.tenant_id,
                Spaces.user_id.is_(None),
                Spaces.tenant_space_id.is_(None),
            )
        )
        space = Spaces(
            name=f"access-facts-{uuid4().hex[:6]}",
            tenant_id=admin.tenant_id,
            tenant_space_id=org_id,
        )
        server = MCPServers(
            tenant_id=admin.tenant_id,
            name=f"access-facts-{uuid4()}",
            http_url="http://localhost:9000/mcp",
            http_auth_type="none",
            is_enabled=True,
        )
        group = UserGroups(
            name=f"access-facts-{uuid4().hex[:6]}", tenant_id=admin.tenant_id
        )
        caller = await user_factory(session)
        flows_role = await container.role_repo().create_role(
            RoleCreate(
                name=f"access-facts-{uuid4().hex[:8]}",
                permissions=[Permission.FLOWS],
                tenant_id=admin.tenant_id,
            )
        )
        session.add_all([space, server, group])
        await session.flush()
        await session.execute(
            sa.text("INSERT INTO users_roles (user_id, role_id) VALUES (:u, :r)"),
            {"u": caller.id, "r": flows_role.id},
        )
        model = await completion_model_factory(
            session, f"access-facts-{uuid4().hex[:6]}"
        )
        assistant = await assistant_factory(
            session, "Access facts", model.id, space_id=space.id
        )
        session.add_all(
            [
                SpacesMCPServers(space_id=space.id, mcp_server_id=server.id),
                MCPServerTools(mcp_server_id=server.id, name="lookup_case"),
                AssistantMCPServers(assistant_id=assistant.id, mcp_server_id=server.id),
            ]
        )
        if case in ("editor", "viewer"):
            session.add(SpacesUsers(space_id=space.id, user_id=caller.id, role=case))
        if case == "group-editor-in-the-loaded-user-only":
            await session.execute(
                sa.insert(usergroups_users_table).values(
                    user_id=caller.id, user_group_id=group.id
                )
            )
            session.add(
                SpacesUserGroups(
                    space_id=space.id, user_group_id=group.id, role="editor"
                )
            )
        await session.flush()
        user: UserInDB = await container.user_repo().get_user_by_id(caller.id)
        # The membership ends after the caller was loaded: both loads judge
        # the caller as loaded with the request.
        await session.execute(
            sa.delete(usergroups_users_table).where(
                usergroups_users_table.c.user_id == caller.id
            )
        )
        space_id: UUID = uuid4() if case == "unknown-space" else space.id
        stored = (space.id, server.id, group.id)

    # Each load has a session of its own, the access load first, as a request
    # makes it: a session that loaded the whole space would hand the access
    # load the space it already holds, and hide the statements it runs.
    async def decide_with_statements(*, whole: bool) -> tuple[_Decision, list[str]]:
        async with db_container(user=user) as container:
            statements: list[str] = []

            def record(state: ORMExecuteState) -> None:
                statements.append(
                    str(state.statement.compile(dialect=postgresql.dialect()))
                )

            event.listen(container.session().sync_session, "do_orm_execute", record)
            space_service, actors = container.space_service(), container.actor_manager()

            async def whole_space() -> SpaceActor:
                return actors.get_space_actor_from_space(
                    await space_service.get_space(space_id)
                )

            async def access_facts() -> SpaceActor:
                return actors.get_space_actor(
                    await space_service.get_space_access_facts(space_id)
                )

            decision = await _decided(whole_space if whole else access_facts)
            return decision, statements

    try:
        new, statements = await decide_with_statements(whole=False)
        old, whole_statements = await decide_with_statements(whole=True)
        catalog_reads = sum(_reads_mcp_catalog(sql) for sql in whole_statements)
    finally:
        async with db_container() as container:
            session = container.session()
            await session.execute(
                sa.delete(MCPServers).where(MCPServers.id == stored[1])
            )
            await session.execute(sa.delete(Spaces).where(Spaces.id == stored[0]))
            await session.execute(
                sa.delete(UserGroups).where(UserGroups.id == stored[2])
            )

    assert (old, new) == (expected, expected)
    if case != "unknown-space":
        # The control: the whole space reads the catalog this case activated.
        assert catalog_reads > 0
    assert not any(_reads_mcp_catalog(sql) for sql in statements)
