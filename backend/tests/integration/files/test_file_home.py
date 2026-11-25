"""A File's home: the one space it belongs in, kept for the family's whole life."""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.database.database import sessionmanager
from eneo.database.tables.app_table import AppRuns, AppRunsFiles, AppsFiles
from eneo.database.tables.assistant_table import AssistantsFiles
from eneo.database.tables.files_table import Files
from eneo.database.tables.questions_table import Questions, QuestionsFiles
from eneo.database.tables.sessions_table import Sessions
from eneo.database.tables.tenant_table import Tenants
from eneo.files.file_home import (
    FileFamilyUse,
    FileHomeConflictError,
    FileHomes,
    FileHomeSpaceNotFoundError,
    FileInUseElsewhereError,
)
from eneo.files.file_models import FileType
from eneo.files.file_usage import FileUsageRepository


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


async def _home(session, file_id: UUID) -> UUID | None:
    return await session.scalar(
        sa.select(Files.home_space_id).where(Files.id == file_id)
    )


async def _space(container, name: str) -> UUID:
    space = await container.space_init_service().create_space(
        f"{name} {uuid4().hex[:6]}"
    )
    assert space.id is not None
    return space.id


async def _asked_in_conversation(
    session, admin_user, file_id: UUID, *, assistant_id: UUID | None
) -> None:
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


async def test_a_new_file_gets_its_home_with_its_whole_family(
    db_container, admin_user
) -> None:
    async with db_container() as container:
        session = container.session()
        space_id = await _space(container, "Meetings")
        root_id = await _file(session, admin_user)
        derived_id = await _file(session, admin_user, parent_id=root_id)
        homes = FileHomes(session)

        # Naming a derived File places the family it belongs to.
        await homes.set_home(
            derived_id, space_id=space_id, tenant_id=admin_user.tenant_id
        )
        await homes.set_home(root_id, space_id=space_id, tenant_id=admin_user.tenant_id)

        assert await homes.homes_of([root_id, derived_id]) == {
            root_id: space_id,
            derived_id: space_id,
        }


async def test_a_home_is_kept_when_another_space_asks_for_the_file(
    db_container, admin_user
) -> None:
    async with db_container() as container:
        session = container.session()
        home_id = await _space(container, "Meetings")
        other_id = await _space(container, "Economy")
        file_id = await _file(session, admin_user)
        homes = FileHomes(session)
        await homes.set_home(file_id, space_id=home_id, tenant_id=admin_user.tenant_id)

        for claim in (homes.set_home, homes.take):
            with pytest.raises(FileHomeConflictError):
                await claim(file_id, space_id=other_id, tenant_id=admin_user.tenant_id)
        with pytest.raises(FileHomeConflictError):
            await homes.require_no_other_home([file_id], space_id=other_id)

        await homes.require_no_other_home([file_id], space_id=home_id)
        assert await _home(session, file_id) == home_id


async def test_a_home_must_be_a_space_of_the_files_organisation(
    db_container, admin_user
) -> None:
    async with db_container() as container:
        session = container.session()
        file_id = await _file(session, admin_user)
        other_tenant = Tenants(
            name=f"file-home-{uuid4()}", quota_limit=1_000_000, state="active"
        )
        session.add(other_tenant)
        await session.flush()
        space_id = await _space(container, "Meetings")
        homes = FileHomes(session)

        with pytest.raises(FileHomeSpaceNotFoundError):
            await homes.set_home(
                file_id, space_id=uuid4(), tenant_id=admin_user.tenant_id
            )
        # A File of another organisation is not found, whatever space is named.
        with pytest.raises(Exception, match="does not exist"):
            await homes.set_home(file_id, space_id=space_id, tenant_id=other_tenant.id)

        assert await _home(session, file_id) is None


async def test_a_draft_takes_the_space_it_is_attached_in(
    db_container, admin_user
) -> None:
    async with db_container() as container:
        session = container.session()
        space_id = await _space(container, "Meetings")
        draft_id = await _file(session, admin_user)

        await FileHomes(session).take(
            draft_id, space_id=space_id, tenant_id=admin_user.tenant_id
        )

        assert await _home(session, draft_id) == space_id


async def test_a_file_in_use_without_a_home_is_taken_only_where_all_its_uses_are(
    db_container, admin_user, assistant_factory, completion_model_factory
) -> None:
    async with db_container() as container:
        session = container.session()
        used_in = await _space(container, "Meetings")
        elsewhere = await _space(container, "Economy")
        model = await completion_model_factory(session, "Home model")
        assistant = await assistant_factory(
            session, "Minute taker", model.id, space_id=used_in
        )
        file_id = await _file(session, admin_user)
        session.add(AssistantsFiles(assistant_id=assistant.id, file_id=file_id))
        await session.flush()
        homes = FileHomes(session)

        with pytest.raises(FileInUseElsewhereError):
            await homes.take(
                file_id, space_id=elsewhere, tenant_id=admin_user.tenant_id
            )
        assert await _home(session, file_id) is None

        await homes.take(file_id, space_id=used_in, tenant_id=admin_user.tenant_id)

        assert await _home(session, file_id) == used_in


async def test_a_use_that_leads_to_no_space_keeps_a_file_from_being_placed(
    db_container, admin_user
) -> None:
    async with db_container() as container:
        session = container.session()
        space_id = await _space(container, "Meetings")
        file_id = await _file(session, admin_user)
        await _asked_in_conversation(session, admin_user, file_id, assistant_id=None)
        homes = FileHomes(session)

        with pytest.raises(FileInUseElsewhereError):
            await homes.take(file_id, space_id=space_id, tenant_id=admin_user.tenant_id)

        assert await _home(session, file_id) is None


async def test_two_spaces_taking_one_draft_at_once_give_one_home(
    db_container, admin_user
) -> None:
    async with db_container() as container:
        first = await _space(container, "Meetings")
        second = await _space(container, "Economy")
        draft_id = await _file(container.session(), admin_user)

    async def take(space_id: UUID) -> UUID | None:
        async with sessionmanager.session() as session, session.begin():
            try:
                await FileHomes(session).take(
                    draft_id, space_id=space_id, tenant_id=admin_user.tenant_id
                )
            except FileHomeConflictError:
                return None
            # Hold the family long enough for the other space to queue up.
            await asyncio.sleep(0.2)
            return space_id

    taken = await asyncio.gather(take(first), take(second))

    winners = [space_id for space_id in taken if space_id is not None]
    assert len(winners) == 1
    async with db_container() as container:
        assert await _home(container.session(), draft_id) == winners[0]


async def test_a_file_made_from_another_gets_its_home(db_container, admin_user) -> None:
    async with db_container() as container:
        session = container.session()
        space_id = await _space(container, "Meetings")
        document_id = await _file(session, admin_user)
        homes = FileHomes(session)
        await homes.set_home(
            document_id, space_id=space_id, tenant_id=admin_user.tenant_id
        )
        new_version_id = await _file(session, admin_user)
        from_a_draft_id = await _file(session, admin_user)
        draft_id = await _file(session, admin_user)

        await homes.inherit(new_version_id, from_file_id=document_id)
        await homes.inherit(from_a_draft_id, from_file_id=draft_id)

        assert await _home(session, new_version_id) == space_id
        assert await _home(session, from_a_draft_id) is None


async def test_every_kind_of_use_leads_to_its_space(
    db_container,
    admin_user,
    assistant_factory,
    app_factory,
    completion_model_factory,
) -> None:
    async with db_container() as container:
        session = container.session()
        assistant_space = await _space(container, "Assistants")
        app_space = await _space(container, "Apps")
        model = await completion_model_factory(session, "Use model")
        assistant = await assistant_factory(
            session, "Minute taker", model.id, space_id=assistant_space
        )
        app = await app_factory(session, "Transcriber", model.id, space_id=app_space)
        run = AppRuns(
            tenant_id=admin_user.tenant_id,
            app_id=app.id,
            user_id=admin_user.id,
            completion_model_id=model.id,
            input_text="",
            output_text="",
        )
        session.add(run)
        await session.flush()
        attached = await _file(session, admin_user)
        attached_to_app = await _file(session, admin_user)
        run_input = await _file(session, admin_user)
        asked = await _file(session, admin_user)
        derived_of_asked = await _file(session, admin_user, parent_id=asked)
        draft = await _file(session, admin_user)
        session.add_all(
            [
                AssistantsFiles(assistant_id=assistant.id, file_id=attached),
                AppsFiles(app_id=app.id, file_id=attached_to_app),
                AppRunsFiles(app_run_id=run.id, file_id=run_input),
            ]
        )
        await session.flush()
        # The use of a derived File is a use of its family.
        await _asked_in_conversation(
            session, admin_user, derived_of_asked, assistant_id=assistant.id
        )
        roots = [attached, attached_to_app, run_input, asked, draft]

        root_of = await FileUsageRepository(session).lock_families(roots)
        use = await FileHomes(session).use_of_families(root_of)

        assert root_of[derived_of_asked] == asked
        assert use == {
            attached: FileFamilyUse(space_ids=frozenset({assistant_space})),
            attached_to_app: FileFamilyUse(space_ids=frozenset({app_space})),
            run_input: FileFamilyUse(space_ids=frozenset({app_space})),
            asked: FileFamilyUse(space_ids=frozenset({assistant_space})),
            draft: FileFamilyUse(space_ids=frozenset()),
        }
        assert not use[draft].in_use
