"""Deleting a space removes the Files that live in it, and only those."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.files_table import Files
from eneo.database.tables.questions_table import Questions, QuestionsFiles
from eneo.database.tables.sessions_table import Sessions
from eneo.database.tables.spaces_table import Spaces
from eneo.files.file_home import FileHomes, FileInUseElsewhereError
from eneo.files.file_models import FileType


async def _file(session, admin_user, *, parent_id: UUID | None = None) -> UUID:
    file = Files(
        name="minutes.txt",
        mimetype="text/plain",
        file_type=FileType.TEXT.value,
        tenant_id=admin_user.tenant_id,
        owner_user_id=admin_user.id,
        parent_file_id=parent_id,
    )
    session.add(file)
    await session.flush()
    return file.id


async def _space(container, name: str) -> UUID:
    space = await container.space_init_service().create_space(
        f"{name} {uuid4().hex[:6]}"
    )
    assert space.id is not None
    return space.id


async def _asked_of(session, admin_user, assistant_id: UUID, file_id: UUID) -> None:
    """Use a File by asking about it in a conversation with an assistant."""
    conversation = Sessions(
        user_id=admin_user.id, name="Meeting", assistant_id=assistant_id
    )
    session.add(conversation)
    await session.flush()
    question = Questions(
        question="Summarise",
        answer="",
        num_tokens_question=0,
        num_tokens_answer=0,
        tenant_id=admin_user.tenant_id,
        session_id=conversation.id,
    )
    session.add(question)
    await session.flush()
    session.add(QuestionsFiles(question_id=question.id, file_id=file_id, type="user"))
    await session.flush()


async def _uses(session, file_id: UUID, *, assistant_id: UUID) -> int:
    return await session.scalar(
        sa.select(sa.func.count())
        .select_from(QuestionsFiles)
        .join(Questions, Questions.id == QuestionsFiles.question_id)
        .join(Sessions, Sessions.id == Questions.session_id)
        .where(QuestionsFiles.file_id == file_id, Sessions.assistant_id == assistant_id)
    )


async def _existing(session, table, ids: list[UUID]) -> set[UUID]:
    return set(
        (await session.scalars(sa.select(table.id).where(table.id.in_(ids)))).all()
    )


async def test_deleting_a_space_removes_the_files_that_live_in_it(
    db_container, admin_user, assistant_factory, completion_model_factory
) -> None:
    async with db_container() as container:
        session = container.session()
        space_id = await _space(container, "Meetings")
        model = await completion_model_factory(session, "Deletion model")
        assistant = await assistant_factory(
            session, "Minute taker", model.id, space_id=space_id
        )
        recording = await _file(session, admin_user)
        transcript = await _file(session, admin_user, parent_id=recording)
        unused = await _file(session, admin_user)
        homes = FileHomes(session)
        for file_id in (recording, unused):
            await homes.set_home(
                file_id, space_id=space_id, tenant_id=admin_user.tenant_id
            )
        await _asked_of(session, admin_user, assistant.id, recording)

    async with db_container() as container:
        await container.space_service().delete_space(space_id)

    async with db_container() as container:
        session = container.session()
        assert await _existing(session, Spaces, [space_id]) == set()
        assert await _existing(session, Files, [recording, transcript, unused]) == set()


async def test_a_file_without_a_home_survives_the_space_it_was_used_in(
    db_container, admin_user, assistant_factory, completion_model_factory
) -> None:
    """An empty home never means "may be deleted": the File is still used in
    another space, or is left for the cleanup of unused Files."""
    async with db_container() as container:
        session = container.session()
        deleted_space = await _space(container, "Meetings")
        other_space = await _space(container, "Economy")
        model = await completion_model_factory(session, "Survivor model")
        going = await assistant_factory(
            session, "Minute taker", model.id, space_id=deleted_space
        )
        staying = await assistant_factory(
            session, "Bookkeeper", model.id, space_id=other_space
        )
        shared = await _file(session, admin_user)
        used_only_here = await _file(session, admin_user)
        await _asked_of(session, admin_user, going.id, shared)
        await _asked_of(session, admin_user, staying.id, shared)
        await _asked_of(session, admin_user, going.id, used_only_here)
        staying_id = staying.id

    async with db_container() as container:
        await container.space_service().delete_space(deleted_space)

    async with db_container() as container:
        session = container.session()
        assert await _existing(session, Files, [shared, used_only_here]) == {
            shared,
            used_only_here,
        }
        assert await _uses(session, shared, assistant_id=staying_id) == 1


async def test_a_space_is_not_deleted_while_one_of_its_files_is_used_elsewhere(
    db_container, admin_user, assistant_factory, completion_model_factory
) -> None:
    async with db_container() as container:
        session = container.session()
        home = await _space(container, "Meetings")
        other_space = await _space(container, "Economy")
        model = await completion_model_factory(session, "Refusal model")
        local = await assistant_factory(
            session, "Minute taker", model.id, space_id=home
        )
        outside = await assistant_factory(
            session, "Bookkeeper", model.id, space_id=other_space
        )
        file_id = await _file(session, admin_user)
        only_here = await _file(session, admin_user)
        homes = FileHomes(session)
        for homed in (file_id, only_here):
            await homes.set_home(homed, space_id=home, tenant_id=admin_user.tenant_id)
        await _asked_of(session, admin_user, local.id, file_id)
        await _asked_of(session, admin_user, outside.id, file_id)
        await _asked_of(session, admin_user, local.id, only_here)
        local_id = local.id

    with pytest.raises(FileInUseElsewhereError):
        async with db_container() as container:
            await container.space_service().delete_space(home)

    # Nothing is half done: the space, its assistant, both Files and the uses
    # inside the space are all still there.
    async with db_container() as container:
        session = container.session()
        assert await _existing(session, Spaces, [home]) == {home}
        assert await _existing(session, Assistants, [local_id]) == {local_id}
        assert await _existing(session, Files, [file_id, only_here]) == {
            file_id,
            only_here,
        }
        assert await _uses(session, file_id, assistant_id=local_id) == 1
        assert await _uses(session, only_here, assistant_id=local_id) == 1
        assert await FileHomes(session).homes_of([file_id]) == {file_id: home}


async def test_removing_a_person_removes_the_files_that_live_in_their_own_space(
    db_container, admin_user
) -> None:
    from eneo.database.tables.users_table import Users

    async with db_container() as container:
        session = container.session()
        person = Users(
            username=f"file-home-{uuid4()}",
            email=f"file-home-{uuid4()}@example.com",
            state="active",
            used_tokens=0,
            tenant_id=admin_user.tenant_id,
        )
        session.add(person)
        await session.flush()
        personal = Spaces(
            name="Personal", tenant_id=admin_user.tenant_id, user_id=person.id
        )
        session.add(personal)
        await session.flush()
        # The File is the admin's, so only its home ties it to the person.
        file_id = await _file(session, admin_user)
        await FileHomes(session).set_home(
            file_id, space_id=personal.id, tenant_id=admin_user.tenant_id
        )
        person_id, personal_id = person.id, personal.id

    async with db_container() as container:
        await container.user_repo().delete(person_id)

    async with db_container() as container:
        session = container.session()
        assert await _existing(session, Spaces, [personal_id]) == set()
        assert await _existing(session, Files, [file_id]) == set()
