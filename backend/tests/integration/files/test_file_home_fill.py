"""The command that fills in the home of files from before homes existed."""

from __future__ import annotations

from uuid import UUID, uuid4

import sqlalchemy as sa

from eneo.database.database import sessionmanager
from eneo.database.tables.files_table import Files
from eneo.database.tables.questions_table import Questions, QuestionsFiles
from eneo.database.tables.sessions_table import Sessions
from eneo.files.file_home import FileHomes
from eneo.files.file_home_fill import FillProgress, fill_all, read_status
from eneo.files.file_models import FileType


async def _file(session, admin_user) -> UUID:
    file = Files(
        name="minutes.txt",
        mimetype="text/plain",
        file_type=FileType.TEXT.value,
        tenant_id=admin_user.tenant_id,
        owner_user_id=admin_user.id,
    )
    session.add(file)
    await session.flush()
    return file.id


async def _used_before_homes_existed(
    session, admin_user, file_id: UUID, *, assistant_id: UUID
) -> None:
    """A use written the way earlier releases wrote it: no home is taken."""
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
    await session.execute(
        sa.insert(QuestionsFiles).values(
            question_id=question.id, file_id=file_id, type="user"
        )
    )


async def test_the_fill_places_what_one_space_uses_and_lists_the_rest_once(
    db_container, admin_user, assistant_factory, completion_model_factory
) -> None:
    async with db_container() as container:
        session = container.session()
        first = await container.space_init_service().create_space(f"First {uuid4()}")
        second = await container.space_init_service().create_space(f"Second {uuid4()}")
        assert first.id is not None and second.id is not None
        model = await completion_model_factory(session, f"Fill model {uuid4()}")
        in_first = await assistant_factory(session, "A", model.id, space_id=first.id)
        in_second = await assistant_factory(session, "B", model.id, space_id=second.id)
        of_first = await _file(session, admin_user)
        of_second = await _file(session, admin_user)
        in_both = await _file(session, admin_user)
        draft = await _file(session, admin_user)
        await _used_before_homes_existed(
            session, admin_user, of_first, assistant_id=in_first.id
        )
        await _used_before_homes_existed(
            session, admin_user, of_second, assistant_id=in_second.id
        )
        for assistant in (in_first, in_second):
            await _used_before_homes_existed(
                session, admin_user, in_both, assistant_id=assistant.id
            )
        first_id, second_id = first.id, second.id
    before = await read_status(sessionmanager)

    progress = await fill_all(sessionmanager, FillProgress(), limit=1, pause_seconds=0)
    again = await fill_all(sessionmanager, FillProgress(), pause_seconds=0)

    assert progress.pass_complete
    assert progress.placed >= 2
    # Used in two spaces, met once in each, listed once.
    assert progress.unresolved[in_both] == "several_spaces"
    assert of_first not in progress.unresolved
    async with db_container() as container:
        assert await FileHomes(container.session()).homes_of(
            [of_first, of_second, in_both, draft]
        ) == {of_first: first_id, of_second: second_id, in_both: None, draft: None}
    # A second pass has nothing left to place and lists the same file.
    assert again.placed == 0
    assert again.unresolved[in_both] == "several_spaces"
    after = await read_status(sessionmanager)
    assert after.files_with_home - before.files_with_home == progress.placed
    assert before.in_use_without_home - after.in_use_without_home == progress.placed
    assert after.drafts == before.drafts
