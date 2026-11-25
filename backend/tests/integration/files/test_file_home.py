"""A File's home: the one space it belongs in, kept for the family's whole life."""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.database.database import sessionmanager
from eneo.database.tables.app_table import AppRuns, AppRunsFiles, AppsFiles
from eneo.database.tables.assistant_table import Assistants, AssistantsFiles
from eneo.database.tables.files_table import Files
from eneo.database.tables.questions_table import Questions, QuestionsFiles
from eneo.database.tables.service_table import Services
from eneo.database.tables.sessions_table import Sessions
from eneo.database.tables.spaces_table import Spaces
from eneo.database.tables.tenant_table import Tenants
from eneo.files.file_home import (
    FileFamilyUse,
    FileHomeConflictError,
    FileHomes,
    FileHomeSpaceNotFoundError,
    FileHomeUnresolved,
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


async def test_filling_in_gives_a_home_to_what_is_used_in_one_space_only(
    db_container, admin_user, assistant_factory, completion_model_factory
) -> None:
    async with db_container() as container:
        session = container.session()
        here = await _space(container, "Meetings")
        elsewhere = await _space(container, "Economy")
        model = await completion_model_factory(session, "Fill model")
        local = await assistant_factory(
            session, "Minute taker", model.id, space_id=here
        )
        other = await assistant_factory(
            session, "Bookkeeper", model.id, space_id=elsewhere
        )
        only_here = await _file(session, admin_user)
        derived = await _file(session, admin_user, parent_id=only_here)
        in_two_spaces = await _file(session, admin_user)
        leads_nowhere = await _file(session, admin_user)
        draft = await _file(session, admin_user)
        already_placed = await _file(session, admin_user)
        homes = FileHomes(session)
        await homes.set_home(
            already_placed, space_id=here, tenant_id=admin_user.tenant_id
        )
        # The family is used through its derived File only.
        await _asked_in_conversation(
            session, admin_user, derived, assistant_id=local.id
        )
        for assistant in (local, other):
            await _asked_in_conversation(
                session, admin_user, in_two_spaces, assistant_id=assistant.id
            )
        await _asked_in_conversation(
            session, admin_user, leads_nowhere, assistant_id=local.id
        )
        await _asked_in_conversation(
            session, admin_user, leads_nowhere, assistant_id=None
        )
        await _asked_in_conversation(
            session, admin_user, already_placed, assistant_id=local.id
        )

        # One File at a time, as a job that is stopped and started again would.
        placed = 0
        unresolved: dict[UUID, FileHomeUnresolved] = {}
        after: UUID | None = None
        batches = 0
        while True:
            batch = await homes.fill_in_space(here, after=after, limit=1)
            placed += batch.placed
            unresolved.update(batch.unresolved)
            batches += 1
            after = batch.next_after
            if after is None:
                break
        again = await homes.fill_in_space(here)

        assert batches > 1
        assert placed == 1
        assert unresolved == {
            in_two_spaces: FileHomeUnresolved.SEVERAL_SPACES,
            leads_nowhere: FileHomeUnresolved.NO_SPACE,
        }
        # Every id is kept, and nothing that could not be placed got a home.
        assert await homes.homes_of(
            [only_here, derived, in_two_spaces, leads_nowhere, draft, already_placed]
        ) == {
            only_here: here,
            derived: here,
            in_two_spaces: None,
            leads_nowhere: None,
            draft: None,
            already_placed: here,
        }
        # Running it again places nothing new and reports the same Files.
        assert again.placed == 0
        assert again.unresolved == unresolved
        assert again.next_after is None


@pytest.mark.parametrize("first", ["attach", "delete"])
async def test_attaching_and_deleting_a_space_wait_for_each_other(
    db_container, admin_user, first
) -> None:
    """Both take the space before any file, so neither can hold what the
    other waits for: one finishes, then the other sees what it did."""
    async with db_container() as container:
        space_id = await _space(container, "Meetings")
        draft_id = await _file(container.session(), admin_user)

    async def attach(delay: float) -> str:
        await asyncio.sleep(delay)
        async with sessionmanager.session() as session, session.begin():
            try:
                await FileHomes(session).attach([draft_id], space_id=space_id)
            except FileHomeSpaceNotFoundError:
                return "space gone"
            await asyncio.sleep(0.3)
            return "attached"

    async def delete(delay: float) -> str:
        await asyncio.sleep(delay)
        async with sessionmanager.session() as session, session.begin():
            await FileHomes(session).remove_with_space(space_id)
            await asyncio.sleep(0.3)
            await session.execute(sa.delete(Spaces).where(Spaces.id == space_id))
            return "deleted"

    attached, deleted = await asyncio.gather(
        attach(0 if first == "attach" else 0.1),
        delete(0.1 if first == "attach" else 0),
    )

    assert deleted == "deleted"
    async with db_container() as container:
        session = container.session()
        space_left = await session.scalar(
            sa.select(sa.func.count()).select_from(Spaces).where(Spaces.id == space_id)
        )
        draft_left = (
            await _home(session, draft_id),
            await session.scalar(
                sa.select(sa.func.count())
                .select_from(Files)
                .where(Files.id == draft_id)
            ),
        )
    assert space_left == 0
    if first == "attach":
        # The file was placed first, so it went with the space it lived in.
        assert attached == "attached"
        assert draft_left == (None, 0)
    else:
        # The space went first: the attach is refused and the draft is still
        # a draft.
        assert attached == "space gone"
        assert draft_left == (None, 1)


async def test_moving_a_service_takes_along_the_files_only_its_questions_use(
    db_container, admin_user
) -> None:
    async with db_container() as container:
        session = container.session()
        source = await _space(container, "Source")
        target = await _space(container, "Target")
        service = Services(
            name="Classifier",
            prompt="Classify",
            user_id=admin_user.id,
            space_id=source,
        )
        session.add(service)
        await session.flush()

        async def asked_of_the_service(file_id: UUID) -> None:
            question = Questions(
                question="Classify",
                answer="",
                num_tokens_question=0,
                num_tokens_answer=0,
                tenant_id=admin_user.tenant_id,
                service_id=service.id,
            )
            session.add(question)
            await session.flush()
            session.add(
                QuestionsFiles(question_id=question.id, file_id=file_id, type="user")
            )
            await session.flush()

        own = await _file(session, admin_user)
        shared = await _file(session, admin_user)
        await asked_of_the_service(own)
        await asked_of_the_service(shared)
        await _asked_in_conversation(session, admin_user, shared, assistant_id=None)
        homes = FileHomes(session)
        for file_id in (own, shared):
            await homes.set_home(
                file_id, space_id=source, tenant_id=admin_user.tenant_id
            )

        with pytest.raises(FileInUseElsewhereError, match="the service"):
            await homes.move_with_service(
                service.id,
                source_space_id=source,
                target_space_id=target,
                tenant_id=admin_user.tenant_id,
            )
        assert await homes.homes_of([own, shared]) == {own: source, shared: source}

        # Without the file that something else uses too, the rest follows.
        await session.execute(
            sa.delete(QuestionsFiles).where(QuestionsFiles.file_id == shared)
        )
        moved = await homes.move_with_service(
            service.id,
            source_space_id=source,
            target_space_id=target,
            tenant_id=admin_user.tenant_id,
        )

        assert moved == 1
        assert await homes.homes_of([own, shared]) == {own: target, shared: source}


async def test_a_question_whose_assistant_moves_meanwhile_is_held_in_the_new_space(
    db_container, admin_user, assistant_factory, completion_model_factory
) -> None:
    """The space is read, locked and read again, so an attach that waited for
    a move places its file where the assistant now is, not where it was."""
    async with db_container() as container:
        session = container.session()
        source = await _space(container, "Source")
        target = await _space(container, "Target")
        model = await completion_model_factory(session, f"Hold model {uuid4()}")
        assistant = await assistant_factory(
            session, "Minute taker", model.id, space_id=source
        )
        conversation = Sessions(
            user_id=admin_user.id, name="Meeting", assistant_id=assistant.id
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
        draft_id = await _file(session, admin_user)
        assistant_id, question_id = assistant.id, question.id

    async def move() -> None:
        async with sessionmanager.session() as session, session.begin():
            for space_id in sorted((source, target), key=str):
                await session.execute(
                    sa.select(Spaces.id).where(Spaces.id == space_id).with_for_update()
                )
            await session.execute(
                sa.update(Assistants)
                .where(Assistants.id == assistant_id)
                .values(space_id=target)
            )
            # Long enough for the attach to read the old space and queue up.
            await asyncio.sleep(0.4)

    async def attach() -> UUID | None:
        await asyncio.sleep(0.1)
        async with sessionmanager.session() as session, session.begin():
            homes = FileHomes(session)
            held = await homes.hold_space_of_question(question_id)
            assert held is not None
            await homes.attach([draft_id], space_id=held)
            return held

    _, held = await asyncio.gather(move(), attach())

    assert held == target
    async with db_container() as container:
        assert await _home(container.session(), draft_id) == target


async def test_the_space_of_a_question_is_known_before_the_question_exists(
    db_container, admin_user, assistant_factory, completion_model_factory
) -> None:
    async with db_container() as container:
        session = container.session()
        of_assistant = await _space(container, "Assistants")
        of_service = await _space(container, "Services")
        model = await completion_model_factory(session, f"Where model {uuid4()}")
        assistant = await assistant_factory(
            session, "Minute taker", model.id, space_id=of_assistant
        )
        service = Services(
            name="Classifier",
            prompt="Classify",
            user_id=admin_user.id,
            space_id=of_service,
        )
        with_assistant = Sessions(
            user_id=admin_user.id, name="Meeting", assistant_id=assistant.id
        )
        with_nothing = Sessions(user_id=admin_user.id, name="Loose")
        session.add_all([service, with_assistant, with_nothing])
        await session.flush()
        homes = FileHomes(session)

        async def held(session_id: UUID | None, service_id: UUID | None) -> UUID | None:
            return await homes.hold_space_of_conversation(
                session_id=session_id, service_id=service_id
            )

        assert await held(with_assistant.id, None) == of_assistant
        assert await held(None, service.id) == of_service
        # The conversation's assistant decides before a service named beside it.
        assert await held(with_assistant.id, service.id) == of_assistant
        assert await held(with_nothing.id, service.id) == of_service
        assert await held(with_nothing.id, None) is None
        assert await held(None, None) is None


async def test_a_refused_move_names_what_else_in_the_space_uses_the_file(
    db_container, admin_user, assistant_factory, app_factory, completion_model_factory
) -> None:
    async with db_container() as container:
        session = container.session()
        source = await _space(container, "Source")
        target = await _space(container, "Target")
        elsewhere = await _space(container, "Elsewhere")
        model = await completion_model_factory(session, f"Blockers model {uuid4()}")
        moving = await assistant_factory(
            session, "Minute taker", model.id, space_id=source
        )
        colleague = await assistant_factory(
            session, "Bookkeeper", model.id, space_id=source
        )
        outside = await assistant_factory(
            session, "Archivist", model.id, space_id=elsewhere
        )
        app = await app_factory(session, "Transcriber", model.id, space_id=source)
        service = Services(
            name="Classifier", prompt="Classify", user_id=admin_user.id, space_id=source
        )
        session.add(service)
        await session.flush()
        shared = await _file(session, admin_user)
        homes = FileHomes(session)
        await homes.set_home(shared, space_id=source, tenant_id=admin_user.tenant_id)
        asked_of_service = Questions(
            question="Classify",
            answer="",
            num_tokens_question=0,
            num_tokens_answer=0,
            tenant_id=admin_user.tenant_id,
            service_id=service.id,
        )
        session.add(asked_of_service)
        await session.flush()
        session.add_all(
            [
                AssistantsFiles(assistant_id=moving.id, file_id=shared),
                AssistantsFiles(assistant_id=colleague.id, file_id=shared),
                # As earlier releases could leave it: also attached elsewhere.
                AssistantsFiles(assistant_id=outside.id, file_id=shared),
                AppsFiles(app_id=app.id, file_id=shared),
                QuestionsFiles(
                    question_id=asked_of_service.id, file_id=shared, type="user"
                ),
            ]
        )
        await session.flush()

        with pytest.raises(FileInUseElsewhereError) as refusal:
            await homes.move_with_assistant(
                moving.id,
                source_space_id=source,
                target_space_id=target,
                tenant_id=admin_user.tenant_id,
                viewer_user_id=admin_user.id,
            )

        assert refusal.value.details["blockers"] == {
            "assistants": [{"id": str(colleague.id), "name": "Bookkeeper"}],
            "apps": [{"id": str(app.id), "name": "Transcriber"}],
            "services": [{"id": str(service.id), "name": "Classifier"}],
            "conversations": [],
            "other_conversations": 0,
            # Counted, but not said where: it is in a space the mover may not see.
            "elsewhere": 1,
        }
        assert "Archivist" not in str(refusal.value.details)
        assert await _home(session, shared) == source
