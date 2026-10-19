"""Publishing into an integration knowledge: what one sync transaction holds.

A sync publishes every document of a library in a single transaction. Locks it
takes per document live until that transaction commits, so their footprint must
not grow with the size of the library.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import sqlalchemy as sa
from dependency_injector import providers

from eneo.database.tables.ai_models_table import EmbeddingModels
from eneo.database.tables.info_blobs_table import InfoBlobs, InfoBlobVersionState
from eneo.database.tables.integration_table import IntegrationKnowledge
from eneo.database.tables.spaces_table import Spaces
from eneo.files.chunk_embedding_list import ChunkEmbeddingList
from eneo.info_blobs.info_blob import InfoBlobAdd
from eneo.integration.infrastructure.content_service import (
    sharepoint_results as sync_results,
)
from eneo.integration.infrastructure.content_service.sharepoint_index import (
    SharePointIndex,
)

_SESSION_LOCKS = sa.text(
    "SELECT count(*) FILTER (WHERE locktype = 'advisory') AS advisory, "
    "count(*) AS total FROM pg_locks WHERE pid = pg_backend_pid()"
)


def _embedding_result(*, model, chunks):
    result = ChunkEmbeddingList()
    result.add(chunks, [[0.7, 0.8, 0.9] for _ in chunks])
    return result


def _with_fake_embeddings(container) -> None:
    embeddings = AsyncMock()
    embeddings.get_embeddings.side_effect = _embedding_result
    container.create_embeddings_service.override(providers.Object(embeddings))


async def _seed_knowledge(container, user_integration_factory) -> tuple[UUID, UUID]:
    session = container.session()
    user = container.user()
    model = (await session.scalars(sa.select(EmbeddingModels).limit(1))).one()
    space = Spaces(
        name=f"Publication lock space {uuid4().hex[:8]}",
        tenant_id=user.tenant_id,
        user_id=user.id,
    )
    session.add(space)
    await session.flush()
    user_integration = await user_integration_factory(session, tenant_id=user.tenant_id)
    knowledge = IntegrationKnowledge(
        name="SharePoint library",
        url="https://example.test/sharepoint",
        space_id=space.id,
        tenant_id=user.tenant_id,
        embedding_model_id=model.id,
        user_integration_id=user_integration.id,
        size=0,
    )
    session.add(knowledge)
    await session.flush()
    return knowledge.id, model.id


def _document(container, knowledge_id: UUID, item_id: str, text: str) -> InfoBlobAdd:
    user = container.user()
    return InfoBlobAdd(
        title=f"{item_id}.docx",
        text=text,
        url=f"https://example.test/sharepoint/{item_id}.docx",
        user_id=user.id,
        tenant_id=user.tenant_id,
        group_id=None,
        website_id=None,
        integration_knowledge_id=knowledge_id,
        sharepoint_item_id=item_id,
    )


async def _publish(container, knowledge_id: UUID, model_id: UUID, item_id: str):
    model = await container.embedding_model_repo2().one(model_id)
    return await container.info_blob_service().publish_info_blob_without_validation(
        _document(container, knowledge_id, item_id, f"Text of {item_id}"),
        embedding_model=model,
    )


async def test_one_transaction_holds_no_lock_per_published_document(
    db_container, user_integration_factory
) -> None:
    async with db_container() as setup:
        knowledge_id, model_id = await _seed_knowledge(setup, user_integration_factory)

    async with db_container() as container:
        _with_fake_embeddings(container)
        session = container.session()
        for index in range(3):
            await _publish(container, knowledge_id, model_id, f"item-{index}")
        after_few = (await session.execute(_SESSION_LOCKS)).one()
        for index in range(3, 80):
            await _publish(container, knowledge_id, model_id, f"item-{index}")
        after_many = (await session.execute(_SESSION_LOCKS)).one()

        published = await session.scalar(
            sa.select(sa.func.count())
            .select_from(InfoBlobs)
            .where(InfoBlobs.integration_knowledge_id == knowledge_id)
        )

    assert published == 80
    assert after_many.advisory == 0
    assert after_many.total == after_few.total


async def test_a_sync_holds_no_lock_per_indexed_or_removed_document(
    db_container, user_integration_factory
) -> None:
    """The whole per-item path of a sync, savepoints included."""
    async with db_container() as setup:
        knowledge_id, _ = await _seed_knowledge(setup, user_integration_factory)

    async with db_container() as container:
        _with_fake_embeddings(container)
        session = container.session()
        knowledge = await container.integration_knowledge_repo().one(id=knowledge_id)
        index = SharePointIndex(
            container.info_blob_service(),
            container.integration_knowledge_repo(),
            container.user(),
            None,
        )
        stats = sync_results.initialize_stats()

        async def index_and_remove(item_ids: range) -> None:
            for index_no in item_ids:
                item_id = f"item-{index_no}"
                await index.upsert(
                    f"{item_id}.docx",
                    f"Text of {item_id}",
                    f"https://example.test/{item_id}.docx",
                    knowledge,
                    stats=stats,
                    sharepoint_item_id=item_id,
                )
                if index_no % 2:
                    await index.remove(
                        item_id=item_id,
                        item_name=f"{item_id}.docx",
                        integration_knowledge=knowledge,
                        integration_knowledge_id=knowledge.id,
                        stats=stats,
                        reason="removed",
                    )

        await index_and_remove(range(4))
        after_few = (await session.execute(_SESSION_LOCKS)).one()
        await index_and_remove(range(4, 80))
        after_many = (await session.execute(_SESSION_LOCKS)).one()

    assert stats.get("failed_items", 0) == 0
    assert after_many.advisory == 0
    assert after_many.total == after_few.total


async def _blocked_on_a_lock(db_container) -> bool:
    async with db_container() as probe:
        waiting = await probe.session().scalar(
            sa.text(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE wait_event_type = 'Lock' AND datname = current_database()"
            )
        )
    return bool(waiting)


async def test_concurrent_publications_of_one_item_keep_one_active_version(
    db_container, user_integration_factory
) -> None:
    async with db_container() as setup:
        knowledge_id, model_id = await _seed_knowledge(setup, user_integration_factory)

    first_published = asyncio.Event()
    release_first = asyncio.Event()

    async def publish(text: str, *, hold: bool):
        async with db_container() as container:
            _with_fake_embeddings(container)
            model = await container.embedding_model_repo2().one(model_id)
            blob = await container.info_blob_service().publish_info_blob_without_validation(
                _document(container, knowledge_id, "item-1", text),
                embedding_model=model,
            )
            if hold:
                first_published.set()
                await release_first.wait()
            return blob

    first = asyncio.create_task(publish("First version", hold=True))
    second: asyncio.Task[object] | None = None
    try:
        await asyncio.wait_for(first_published.wait(), timeout=10)
        second = asyncio.create_task(publish("Second version", hold=False))
        async with asyncio.timeout(10):
            while not second.done() and not await _blocked_on_a_lock(db_container):
                await asyncio.sleep(0.05)
        assert not second.done(), (
            "A second publisher of the same document did not wait for the first"
        )
    finally:
        release_first.set()
        await asyncio.gather(
            first, *([second] if second else []), return_exceptions=True
        )
    first_blob = first.result()
    assert second is not None
    second_blob = second.result()

    async with db_container() as verification:
        versions = (
            await verification.session().execute(
                sa.select(
                    InfoBlobs.id, InfoBlobs.source_id, InfoBlobs.version_state
                ).where(
                    InfoBlobs.integration_knowledge_id == knowledge_id,
                    InfoBlobs.sharepoint_item_id == "item-1",
                )
            )
        ).all()
    assert {row.id: row.version_state for row in versions} == {
        first_blob.id: InfoBlobVersionState.SUPERSEDED.value,
        second_blob.id: InfoBlobVersionState.ACTIVE.value,
    }
    assert len({row.source_id for row in versions}) == 1
