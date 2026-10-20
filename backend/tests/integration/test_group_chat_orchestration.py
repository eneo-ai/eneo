"""Persisted configuration and deletion contracts for orchestrated groups."""

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.group_chats_table import GroupChatsTable
from eneo.database.tables.spaces_table import Spaces
from eneo.group_chat.domain.entities.group_chat import GroupChat
from eneo.group_chat.infrastructure.group_chat_repo import GroupChatRepository
from eneo.main.exceptions import BadRequestException


async def test_orchestrator_configuration_is_scoped_and_can_be_explicitly_cleared(
    async_session,
    admin_user,
    space_factory,
    assistant_factory,
    completion_model_factory,
):
    model = await completion_model_factory(async_session, "gpt-4")
    source = await space_factory(async_session, "Source", [model.id])
    other = await space_factory(async_session, "Other", [model.id])
    coordinator = await assistant_factory(
        async_session, "Coordinator", model.id, space_id=source.id
    )
    outsider = await assistant_factory(
        async_session, "Other coordinator", model.id, space_id=other.id
    )
    group = GroupChat.create(name="Group", space_id=source.id, user_id=admin_user.id)
    repo = GroupChatRepository(async_session)
    await repo.add(group)
    await repo.update(group.id, source.id, orchestrator_assistant_id=coordinator.id)
    await repo.update(group.id, source.id, name="Renamed")
    selection = sa.select(GroupChatsTable.orchestrator_assistant_id).where(
        GroupChatsTable.id == group.id
    )
    assert await async_session.scalar(selection) == coordinator.id
    with pytest.raises(BadRequestException, match="belong"):
        await repo.update(group.id, source.id, orchestrator_assistant_id=outsider.id)
    assert await async_session.scalar(selection) == coordinator.id
    await repo.update(group.id, source.id, orchestrator_assistant_id=None)
    assert await async_session.scalar(selection) is None


async def test_orchestrator_cannot_disappear_but_whole_space_can_be_deleted(
    db_container, admin_user, space_factory, assistant_factory, completion_model_factory
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "gpt-4")
        source = await space_factory(session, "Source", [model.id])
        target = await space_factory(session, "Target", [model.id])
        coordinator = await assistant_factory(
            session, "Coordinator", model.id, space_id=source.id
        )
        source_id, target_id, coordinator_id = source.id, target.id, coordinator.id
        group = GroupChat.create(
            name="Group", space_id=source_id, user_id=admin_user.id
        )
        repo = GroupChatRepository(session)
        await repo.add(group)
        await repo.update(group.id, source_id, orchestrator_assistant_id=coordinator_id)
        group_id = group.id

    async with db_container() as container:
        repo = container.assistant_repo()
        with pytest.raises(BadRequestException, match="orchestrator"):
            await repo.delete(coordinator_id, source_id)
        with pytest.raises(BadRequestException, match="orchestrator"):
            await repo.move(coordinator_id, source_id, target_id)
        # The database also rejects a dangling reference from a direct write.
        session = container.session()
        with pytest.raises(IntegrityError):
            async with session.begin_nested():
                await session.execute(
                    sa.delete(Assistants).where(Assistants.id == coordinator_id)
                )
                await session.execute(sa.text("SET CONSTRAINTS ALL IMMEDIATE"))

    # Both references disappear in the same transaction when deleting a Space.
    async with db_container() as container:
        await container.session().execute(
            sa.delete(Spaces).where(Spaces.id == source_id)
        )
    async with db_container() as container:
        session = container.session()
        assert (
            await session.scalar(
                sa.select(Assistants.id).where(Assistants.id == coordinator_id)
            )
            is None
        )
        assert (
            await session.scalar(
                sa.select(GroupChatsTable.id).where(GroupChatsTable.id == group_id)
            )
            is None
        )
