"""Moving an assistant changes which attached knowledge its space can load."""

from uuid import uuid4

import sqlalchemy as sa

from eneo.database.tables.assistant_table import AssistantsGroups, AssistantsWebsites
from eneo.database.tables.collections_table import CollectionsTable
from eneo.database.tables.spaces_table import SpacesEmbeddingModels
from eneo.database.tables.websites_table import Websites


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
