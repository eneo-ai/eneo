"""Saving a space must not delete rows the loader skipped as invalid.

The space loader leaves out assistants whose stored row fails validation (for
example a non-numeric completion_model_kwargs temperature). The space update
re-synchronises the assistant and group chat lists and deletes rows that are
absent, so without the recorded skip any save of the space, such as a rename,
would permanently delete that assistant and drop it from its group chats.

The one exception is an explicit member-list replacement on a group chat: the
submitted list is the whole membership, so a skipped member's seat goes too."""

from __future__ import annotations

from uuid import uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.group_chats_table import (
    GroupChatsAssistantsMapping,
    GroupChatsTable,
)
from eneo.database.tables.spaces_table import Spaces

CORRUPT_KWARGS = {"temperature": "hot"}


async def _clone_assistant(session, source_id, *, name, kwargs):
    row = (
        (
            await session.execute(
                sa.select(Assistants.__table__).where(Assistants.id == source_id)
            )
        )
        .mappings()
        .one()
    )
    values = dict(row)
    clone_id = uuid4()
    values.update(
        id=clone_id, name=name, is_default=False, completion_model_kwargs=kwargs
    )
    await session.execute(sa.insert(Assistants.__table__).values(**values))
    return clone_id


async def _mapping_assistant_ids(session, group_chat_id) -> set:
    rows = await session.execute(
        sa.select(GroupChatsAssistantsMapping.assistant_id).where(
            GroupChatsAssistantsMapping.group_chat_id == group_chat_id
        )
    )
    return set(rows.scalars().all())


@pytest.fixture
async def space_with_skipped_assistant(db_container, admin_user):
    async with db_container() as container:
        session = container.session()
        space = await container.space_init_service().create_space("Keep my assistants")
        assert space.id is not None
        assert space.default_assistant is not None
        default_id = space.default_assistant.id

        valid_id = await _clone_assistant(
            session, default_id, name="Valid sibling", kwargs={}
        )
        corrupt_id = await _clone_assistant(
            session, default_id, name="Corrupt sibling", kwargs=CORRUPT_KWARGS
        )

        group_chat_id = uuid4()
        await session.execute(
            sa.insert(GroupChatsTable).values(
                id=group_chat_id,
                name="Both siblings",
                space_id=space.id,
                user_id=admin_user.id,
                type="group-chat",
                allow_mentions=False,
                show_response_label=False,
                published=False,
                insight_enabled=False,
            )
        )
        await session.execute(
            sa.insert(GroupChatsAssistantsMapping).values(
                [
                    dict(group_chat_id=group_chat_id, assistant_id=valid_id),
                    dict(group_chat_id=group_chat_id, assistant_id=corrupt_id),
                ]
            )
        )

    return {
        "space_id": space.id,
        "valid_id": valid_id,
        "corrupt_id": corrupt_id,
        "group_chat_id": group_chat_id,
    }


@pytest.mark.integration
@pytest.mark.asyncio
async def test_renaming_a_space_keeps_a_skipped_assistant_and_its_group_chat_seat(
    db_container, space_with_skipped_assistant
):
    ids = space_with_skipped_assistant

    async with db_container() as container:
        space = await container.space_service().get_space(ids["space_id"])
        # The corrupt sibling really is skipped on load, so this exercises the
        # path that would otherwise delete it.
        assert ids["corrupt_id"] not in {a.id for a in space.assistants}
        assert ids["corrupt_id"] in space.unloaded_assistant_ids

        await container.space_service().update_space(id=ids["space_id"], name="Renamed")

    async with db_container() as container:
        session = container.session()
        space_row = await session.get(Spaces, ids["space_id"])
        assert space_row is not None
        assert space_row.name == "Renamed"

        corrupt_row = await session.get(Assistants, ids["corrupt_id"])
        assert corrupt_row is not None
        assert corrupt_row.completion_model_kwargs == CORRUPT_KWARGS
        assert await session.get(Assistants, ids["valid_id"]) is not None
        assert await session.get(GroupChatsTable, ids["group_chat_id"]) is not None
        assert await _mapping_assistant_ids(session, ids["group_chat_id"]) == {
            ids["valid_id"],
            ids["corrupt_id"],
        }


@pytest.mark.integration
@pytest.mark.asyncio
async def test_deleting_a_loaded_assistant_still_works_and_spares_the_skipped_one(
    db_container, space_with_skipped_assistant
):
    ids = space_with_skipped_assistant

    async with db_container() as container:
        await container.assistant_service().delete_assistant(ids["valid_id"])

    async with db_container() as container:
        session = container.session()
        assert await session.get(Assistants, ids["valid_id"]) is None
        corrupt_row = await session.get(Assistants, ids["corrupt_id"])
        assert corrupt_row is not None
        assert corrupt_row.completion_model_kwargs == CORRUPT_KWARGS
        assert ids["corrupt_id"] in await _mapping_assistant_ids(
            session, ids["group_chat_id"]
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_clearing_a_group_chats_assistants_also_unseats_the_skipped_one(
    db_container, space_with_skipped_assistant
):
    """PATCH tools.assistants=[] reaches the service as current_assistants=[]
    and means clear-all. The skipped sibling is hidden from the response, so
    keeping its seat would leave the stored membership out of step with it."""
    ids = space_with_skipped_assistant

    async with db_container() as container:
        updated = await container.group_chat_service().update_group_chat(
            id=ids["group_chat_id"], current_assistants=[]
        )
        assert updated.assistants == []

    async with db_container() as container:
        session = container.session()
        assert await session.get(GroupChatsTable, ids["group_chat_id"]) is not None
        assert await _mapping_assistant_ids(session, ids["group_chat_id"]) == set()
        # Only the seat is gone. The skipped row itself is still untouched.
        corrupt_row = await session.get(Assistants, ids["corrupt_id"])
        assert corrupt_row is not None
        assert corrupt_row.completion_model_kwargs == CORRUPT_KWARGS
        assert await session.get(Assistants, ids["valid_id"]) is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_renaming_a_group_chat_keeps_the_skipped_members_seat(
    db_container, space_with_skipped_assistant
):
    """A group chat save that leaves the member list alone (current_assistants
    omitted) is not a replacement, so the skipped member keeps its seat."""
    ids = space_with_skipped_assistant

    async with db_container() as container:
        await container.group_chat_service().update_group_chat(
            id=ids["group_chat_id"], name="Renamed chat"
        )

    async with db_container() as container:
        session = container.session()
        chat_row = await session.get(GroupChatsTable, ids["group_chat_id"])
        assert chat_row is not None
        assert chat_row.name == "Renamed chat"
        assert await _mapping_assistant_ids(session, ids["group_chat_id"]) == {
            ids["valid_id"],
            ids["corrupt_id"],
        }
