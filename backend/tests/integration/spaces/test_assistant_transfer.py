"""Moving an assistant changes which attached knowledge its space can load,
and takes along the Files that live in the space and only the assistant uses."""

from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.assistant_table import (
    Assistants,
    AssistantsGroups,
    AssistantsWebsites,
)
from eneo.database.tables.collections_table import CollectionsTable
from eneo.database.tables.files_table import Files
from eneo.database.tables.questions_table import Questions, QuestionsFiles
from eneo.database.tables.sessions_table import Sessions
from eneo.database.tables.spaces_table import SpacesEmbeddingModels
from eneo.database.tables.websites_table import Websites
from eneo.files.file_home import FileHomes
from eneo.files.file_models import FileType
from eneo.main.exceptions import BadRequestException


async def test_transfer_keeps_source_knowledge_and_reloads_only_available_attachments(
    db_container,
    admin_user,
    assistant_factory,
    completion_model_factory,
    embedding_model_factory,
):
    async with db_container() as container:
        session = container.session()
        source = await container.space_init_service().create_space("Source")
        target = await container.space_init_service().create_space("Target")
        source_id, target_id = source.id, target.id
        organization_id = source.tenant_space_id
        assert source_id is not None and target_id is not None
        assert organization_id is not None
        assert target.tenant_space_id == organization_id

        completion_model = await completion_model_factory(session, "Transfer model")
        embedding_model = await embedding_model_factory(session)
        assistant = await assistant_factory(
            session, "Assistant with knowledge", completion_model.id, space_id=source_id
        )
        assistant_id = assistant.id
        await session.execute(
            sa.insert(SpacesEmbeddingModels),
            [
                {"space_id": space_id, "embedding_model_id": embedding_model.id}
                for space_id in (source_id, target_id)
            ],
        )

        local_collection_id, local_website_id = uuid4(), uuid4()
        shared_collection_id, shared_website_id = uuid4(), uuid4()
        for owner_id, collection_id, website_id in (
            (source_id, local_collection_id, local_website_id),
            (organization_id, shared_collection_id, shared_website_id),
        ):
            await session.execute(
                sa.insert(CollectionsTable).values(
                    id=collection_id,
                    name="Attached collection",
                    size=0,
                    user_id=admin_user.id,
                    tenant_id=admin_user.tenant_id,
                    space_id=owner_id,
                    embedding_model_id=embedding_model.id,
                )
            )
            await session.execute(
                sa.insert(Websites).values(
                    id=website_id,
                    name="Attached website",
                    size=0,
                    user_id=admin_user.id,
                    tenant_id=admin_user.tenant_id,
                    space_id=owner_id,
                    embedding_model_id=embedding_model.id,
                    url="https://example.org/",
                    download_files=False,
                    crawl_type="crawl",
                    update_interval="never",
                )
            )
            await session.execute(
                sa.insert(AssistantsGroups).values(
                    assistant_id=assistant_id, group_id=collection_id
                )
            )
            await session.execute(
                sa.insert(AssistantsWebsites).values(
                    assistant_id=assistant_id, website_id=website_id
                )
            )

    async with db_container() as container:
        before, _ = await container.assistant_service().get_assistant(assistant_id)
        assert {collection.id for collection in before.collections} == {
            local_collection_id,
            shared_collection_id,
        }
        assert {website.id for website in before.websites} == {
            local_website_id,
            shared_website_id,
        }
        await container.resource_mover_service().move_assistant_to_space(
            assistant_id=assistant_id, space_id=target_id
        )

    # A fresh transaction exercises the persisted move and the real space loader.
    async with db_container() as container:
        moved, _ = await container.assistant_service().get_assistant(assistant_id)
        assert moved.space_id == target_id
        assert {collection.id for collection in moved.collections} == {
            shared_collection_id
        }
        assert {website.id for website in moved.websites} == {shared_website_id}

        source = await container.space_service().get_space(source_id)
        assert assistant_id not in {assistant.id for assistant in source.assistants}
        assert source.get_collection(local_collection_id).space_id == source_id
        assert source.get_website(local_website_id).space_id == source_id

        target = await container.space_service().get_space(target_id)
        assert {collection.id for collection in target.collections} == {
            shared_collection_id
        }
        assert {website.id for website in target.websites} == {shared_website_id}
        assert target.get_collection(shared_collection_id).space_id == organization_id
        assert target.get_website(shared_website_id).space_id == organization_id


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


async def _two_spaces_with_an_assistant(
    container, assistant_factory, completion_model_factory
) -> tuple[UUID, UUID, UUID, UUID]:
    session = container.session()
    source = await container.space_init_service().create_space(f"Source {uuid4()}")
    target = await container.space_init_service().create_space(f"Target {uuid4()}")
    assert source.id is not None and target.id is not None
    model = await completion_model_factory(session, f"Move model {uuid4()}")
    assistant = await assistant_factory(
        session, "Minute taker", model.id, space_id=source.id
    )
    return source.id, target.id, assistant.id, model.id


async def test_transfer_moves_the_home_of_the_files_only_the_assistant_uses(
    db_container, admin_user, assistant_factory, completion_model_factory
):
    async with db_container() as container:
        session = container.session()
        source_id, target_id, assistant_id, _ = await _two_spaces_with_an_assistant(
            container, assistant_factory, completion_model_factory
        )
        recording = await _file(session, admin_user)
        transcript = await _file(session, admin_user, parent_id=recording)
        asked_twice = await _file(session, admin_user)
        unused_in_source = await _file(session, admin_user)
        without_home = await _file(session, admin_user)
        homes = FileHomes(session)
        for file_id in (recording, asked_twice, unused_in_source):
            await homes.set_home(
                file_id, space_id=source_id, tenant_id=admin_user.tenant_id
            )
        await _asked_of(session, admin_user, assistant_id, transcript)
        await _asked_of(session, admin_user, assistant_id, asked_twice)
        await _asked_of(session, admin_user, assistant_id, asked_twice)
        await _asked_of(session, admin_user, assistant_id, without_home)

    async with db_container() as container:
        await container.resource_mover_service().move_assistant_to_space(
            assistant_id=assistant_id, space_id=target_id
        )

    async with db_container() as container:
        assert await FileHomes(container.session()).homes_of(
            [recording, transcript, asked_twice, unused_in_source, without_home]
        ) == {
            # The family follows through the use of its derived File.
            recording: target_id,
            transcript: target_id,
            asked_twice: target_id,
            # Not the assistant's: it stays where it lives.
            unused_in_source: source_id,
            # Moving an assistant gives no File a home.
            without_home: None,
        }


async def test_transfer_is_refused_when_a_file_is_also_used_by_something_else(
    db_container, admin_user, assistant_factory, completion_model_factory
):
    async with db_container() as container:
        session = container.session()
        (
            source_id,
            target_id,
            assistant_id,
            model_id,
        ) = await _two_spaces_with_an_assistant(
            container, assistant_factory, completion_model_factory
        )
        colleague = await assistant_factory(
            session, "Bookkeeper", model_id, space_id=source_id
        )
        own = await _file(session, admin_user)
        shared = await _file(session, admin_user)
        homes = FileHomes(session)
        for file_id in (own, shared):
            await homes.set_home(
                file_id, space_id=source_id, tenant_id=admin_user.tenant_id
            )
        await _asked_of(session, admin_user, assistant_id, own)
        await _asked_of(session, admin_user, assistant_id, shared)
        await _asked_of(session, admin_user, colleague.id, shared)

    with pytest.raises(BadRequestException, match="also used by something else"):
        async with db_container() as container:
            await container.resource_mover_service().move_assistant_to_space(
                assistant_id=assistant_id, space_id=target_id
            )

    # Nothing moved and nothing was copied: the assistant and both Files stay.
    async with db_container() as container:
        session = container.session()
        assert await FileHomes(session).homes_of([own, shared]) == {
            own: source_id,
            shared: source_id,
        }
        assert (
            await session.scalar(
                sa.select(Assistants.space_id).where(Assistants.id == assistant_id)
            )
            == source_id
        )
        assert (
            await session.scalar(
                sa.select(sa.func.count())
                .select_from(Files)
                .where(
                    Files.tenant_id == admin_user.tenant_id, Files.name == "minutes.txt"
                )
                .where(Files.id.in_([own, shared]))
            )
            == 2
        )
