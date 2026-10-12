"""The decision on an unattended tool call reads every level's own rows."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.orm import ORMExecuteState
from sqlalchemy.util import await_only

from eneo.database.database import sessionmanager
from eneo.database.tables.mcp_server_table import (
    MCPServers,
    MCPServerTools,
    MCPServerToolSettings,
    SpacesMCPServers,
    SpacesMCPServerTools,
)
from eneo.database.tables.security_classifications_table import (
    SecurityClassification as SecurityClassifications,
)
from eneo.database.tables.spaces_table import Spaces
from eneo.database.tables.users_table import Users
from eneo.main.exceptions import NotFoundException
from eneo.mcp_servers.application.unattended_tool_use import (
    UnattendedToolFacts,
    UnattendedToolRefusal,
    unattended_tool_refusal,
)
from eneo.mcp_servers.infrastructure.repo_impl.unattended_tool_facts_reader import (
    UnattendedToolFactsReader,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@dataclass(frozen=True)
class _Stored:
    """The chain for a server with two tools, and what lies beside it."""

    tenant_id: UUID
    ids: dict[str, UUID]

    async def read(
        self, space: str, tool: str, server: str = "server"
    ) -> UnattendedToolFacts:
        """Read in a session of its own; a name that is not stored is an unknown id."""
        async with sessionmanager.session() as session, session.begin():
            return await UnattendedToolFactsReader(session).read(
                tenant_id=self.tenant_id,
                space_id=self.ids.get(space, uuid4()),
                mcp_server_id=self.ids.get(server, uuid4()),
                tool_id=self.ids.get(tool, uuid4()),
            )


def _server(tenant_id: UUID, **columns: object) -> MCPServers:
    return MCPServers(
        tenant_id=tenant_id,
        name=f"unattended-facts-{uuid4()}",
        http_url="http://localhost:9000/mcp",
        http_auth_type="none",
        is_enabled=True,
        **columns,
    )


@pytest.fixture
async def stored(setup_database: None, admin_user) -> AsyncIterator[_Stored]:
    tenant_id = admin_user.tenant_id
    async with sessionmanager.session() as session, session.begin():
        level = SecurityClassifications(
            tenant_id=tenant_id, name=f"level-{uuid4().hex[:6]}", security_level=5
        )
        owner = Users(
            username=f"unattended-facts-{uuid4()}",
            email=f"unattended-facts-{uuid4()}@example.com",
            state="active",
            used_tokens=0,
            tenant_id=tenant_id,
        )
        session.add_all([level, owner])
        await session.flush()
        # A shared space hangs under the tenant's one organization space.
        organization_space_id = await session.scalar(
            sa.select(Spaces.id).where(
                Spaces.tenant_id == tenant_id,
                Spaces.user_id.is_(None),
                Spaces.tenant_space_id.is_(None),
            )
        )
        assert organization_space_id is not None
        activated = Spaces(
            tenant_id=tenant_id,
            tenant_space_id=organization_space_id,
            name=f"activated-{uuid4().hex[:6]}",
            security_classification_id=level.id,
        )
        untouched = Spaces(
            tenant_id=tenant_id,
            tenant_space_id=organization_space_id,
            name=f"untouched-{uuid4().hex[:6]}",
        )
        personal = Spaces(tenant_id=tenant_id, name="Personal", user_id=owner.id)
        server = _server(tenant_id, security_classification_id=level.id)
        second_server = _server(tenant_id)
        session.add_all([activated, untouched, personal, server, second_server])
        await session.flush()
        pending = MCPServerTools(
            mcp_server_id=server.id,
            name="lookup_case",
            is_enabled_by_default=False,
            requires_approval=True,
        )
        plain = MCPServerTools(
            mcp_server_id=server.id, name="list_cases", is_enabled_by_default=True
        )
        of_second_server = MCPServerTools(
            mcp_server_id=second_server.id, name="lookup_case"
        )
        session.add_all([pending, plain, of_second_server])
        await session.flush()
        session.add_all(
            [
                MCPServerToolSettings(
                    tenant_id=tenant_id, mcp_server_tool_id=plain.id, is_enabled=False
                ),
                SpacesMCPServers(space_id=activated.id, mcp_server_id=server.id),
                SpacesMCPServerTools(
                    space_id=activated.id,
                    mcp_server_tool_id=pending.id,
                    is_enabled=True,
                ),
            ]
        )
        ids = {
            "activated": activated.id,
            "untouched": untouched.id,
            "personal": personal.id,
            "server": server.id,
            "second-server": second_server.id,
            "pending": pending.id,
            "plain": plain.id,
            "of-second-server": of_second_server.id,
        }
        level_id, owner_id = level.id, owner.id
    try:
        yield _Stored(tenant_id=tenant_id, ids=ids)
    finally:
        async with sessionmanager.session() as session, session.begin():
            await session.execute(
                sa.delete(MCPServers).where(
                    MCPServers.id.in_([ids["server"], ids["second-server"]])
                )
            )
            await session.execute(
                sa.delete(Spaces).where(
                    Spaces.id.in_([ids["activated"], ids["untouched"]])
                )
            )
            # Their personal space goes with them.
            await session.execute(sa.delete(Users).where(Users.id == owner_id))
            await session.execute(
                sa.delete(SecurityClassifications).where(
                    SecurityClassifications.id == level_id
                )
            )


async def test_each_level_is_read_from_its_own_row_for_the_asked_space(
    stored: _Stored,
) -> None:
    """Kills the mutants that read a level from the wrong place.

    A reader that takes the space's activation or switch from another space,
    the instance switch from another tool, or a tool through the space's
    projection (which has no review state) lets a call out that a level
    refused, or refuses one every level allowed.
    """
    ids = stored.ids
    facts = await stored.read("activated", "pending")
    assert facts.server is not None and facts.tool is not None
    assert (facts.server.id, facts.tool.id) == (ids["server"], ids["pending"])
    assert facts.tool.requires_approval is True
    assert facts.server.security_classification is not None
    assert facts.space_security_classification is not None
    assert facts.space_security_classification.security_level == 5
    assert (
        facts.tenant_setting,
        facts.space_is_personal,
        facts.server_in_space,
        facts.space_override,
    ) == (None, False, True, True)
    # The stored rows give the decision its answer: the space turned the tool
    # on, but its changed definition waits for review.
    assert (
        unattended_tool_refusal(facts) is UnattendedToolRefusal.TOOL_WAITING_FOR_REVIEW
    )

    other_tool = await stored.read("activated", "plain")
    assert (other_tool.tenant_setting, other_tool.space_override) == (False, None)
    assert other_tool.tool is not None and not other_tool.tool.requires_approval

    other_space = await stored.read("untouched", "pending")
    assert (
        other_space.server_in_space,
        other_space.space_override,
        other_space.space_security_classification,
    ) == (False, None, None)

    gone = await stored.read("activated", "no-such-tool", server="no-such-server")
    assert (gone.server, gone.tool, gone.server_in_space) == (None, None, False)

    with pytest.raises(NotFoundException):
        await stored.read("no-such-space", "pending")


async def test_a_tool_is_a_fact_only_together_with_the_asked_server(
    stored: _Stored,
) -> None:
    # Kills the mutant that reads the tool by its id alone: the grant of one
    # server would be decided on the row of another server's tool.
    foreign = await stored.read("activated", "of-second-server")
    assert foreign.server is not None and foreign.tool is None
    assert unattended_tool_refusal(foreign) is UnattendedToolRefusal.TOOL_NOT_FOUND


async def test_a_personal_space_is_read_as_personal(stored: _Stored) -> None:
    # Kills the mutant that reads every space as shared: a flow in a personal
    # space would be decided on a chain that the space does not have.
    facts = await stored.read("personal", "pending")
    assert facts.space_is_personal is True
    assert unattended_tool_refusal(facts) is UnattendedToolRefusal.SPACE_IS_PERSONAL


async def test_a_second_read_in_one_session_shows_what_is_stored_now(
    stored: _Stored,
) -> None:
    """Kills the mutants that answer from rows the session already holds.

    The caller decides at publish, before the run and before each call, in a
    session that may hold the server, the tool or the space for its own work
    (a session forgets a row only when nothing refers to it): without a
    refresh the decision would be taken on the values that session loaded.
    """
    ids = stored.ids
    async with sessionmanager.session() as session, session.begin():
        reader = UnattendedToolFactsReader(session)
        held = [
            await session.get(MCPServers, ids["server"]),
            await session.get(MCPServerTools, ids["pending"]),
            await session.get(Spaces, ids["activated"]),
        ]

        async def read() -> UnattendedToolFacts:
            return await reader.read(
                tenant_id=stored.tenant_id,
                space_id=ids["activated"],
                mcp_server_id=ids["server"],
                tool_id=ids["pending"],
            )

        before = await read()
        async with sessionmanager.session() as other, other.begin():
            await other.execute(
                sa.update(MCPServers)
                .where(MCPServers.id == ids["server"])
                .values(is_enabled=False)
            )
            await other.execute(
                sa.update(MCPServerTools)
                .where(MCPServerTools.id == ids["pending"])
                .values(removed_from_remote=True)
            )
            await other.execute(
                sa.update(Spaces)
                .where(Spaces.id == ids["activated"])
                .values(security_classification_id=None)
            )
        after = await read()
        assert all(row is not None for row in held)

    assert before.server is not None and before.tool is not None
    assert (
        before.server.is_enabled,
        before.tool.removed_from_remote,
        before.space_security_classification is None,
    ) == (True, False, False)
    assert after.server is not None and after.tool is not None
    assert (
        after.server.is_enabled,
        after.tool.removed_from_remote,
        after.space_security_classification,
    ) == (False, True, None)


async def test_the_facts_are_one_moment_of_what_is_stored(stored: _Stored) -> None:
    """Kills the mutant that reads the levels one statement after another.

    The server is on and the tool waits for review: refused. An administrator
    then switches the server off and approves the tool: still refused. A read
    that takes the server before that change and the tool after it holds a
    server that is on and a tool that is approved, which was never stored, and
    the decision allows it. So the change is made before each statement of a
    read after its first, in turn, and no read may come out allowed.
    """
    ids = stored.ids

    async def store(*, server_on: bool, approved: bool) -> None:
        async with sessionmanager.session() as other, other.begin():
            await other.execute(
                sa.update(MCPServers)
                .where(MCPServers.id == ids["server"])
                .values(is_enabled=server_on)
            )
            await other.execute(
                sa.update(MCPServerTools)
                .where(MCPServerTools.id == ids["pending"])
                .values(requires_approval=not approved)
            )

    async def decided(
        change_before_statement: int,
    ) -> tuple[UnattendedToolRefusal | None, bool]:
        """The decision on one read, and whether the change was made in it."""
        statements = 0
        changed = False

        def before_statement(_: ORMExecuteState) -> None:
            nonlocal statements, changed
            statements += 1
            if statements == change_before_statement:
                await_only(store(server_on=False, approved=True))
                changed = True

        async with sessionmanager.session() as session, session.begin():
            event.listen(session.sync_session, "do_orm_execute", before_statement)
            facts = await UnattendedToolFactsReader(session).read(
                tenant_id=stored.tenant_id,
                space_id=ids["activated"],
                mcp_server_id=ids["server"],
                tool_id=ids["pending"],
            )
        return unattended_tool_refusal(facts), changed

    # The control: once the server is on and the tool approved, every level
    # allows the call, so a refusal below is not one that anything gives.
    await store(server_on=True, approved=True)
    assert await decided(change_before_statement=0) == (None, False)

    position = 2
    while True:
        await store(server_on=True, approved=False)
        refusal, changed = await decided(change_before_statement=position)
        assert refusal is not None, f"allowed, changed before statement {position}"
        if not changed:
            break
        position += 1
