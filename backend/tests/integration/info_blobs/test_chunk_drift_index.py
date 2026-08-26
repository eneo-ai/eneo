"""The SharePoint delta's chunk-drift check must stay scoped to one source.

``process_delta_changes`` asks this question on every webhook delta, including the
common case where nothing drifted. ``info_blobs.integration_knowledge_id`` carries only
a foreign key, so without a partial index the negative answer is proved by examining
every active blob — table-size work on a routine no-op sync.
"""

from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.ai_models_table import EmbeddingModels
from eneo.database.tables.collections_table import CollectionsTable
from eneo.database.tables.info_blobs_table import InfoBlobs, InfoBlobVersionState
from eneo.database.tables.integration_table import IntegrationKnowledge
from eneo.database.tables.spaces_table import Spaces
from eneo.info_blobs.info_blob_repo import InfoBlobRepository

pytestmark = pytest.mark.integration

INDEX_NAME = "ix_info_blobs_integration_knowledge_chunking"

# Enough rows that a scan is decisively worse than an index lookup, and enough sources
# that "scoped to this source" is a meaningful claim.
SOURCES = 8
BLOBS_PER_SOURCE = 150


def _walk_plan(plan: Mapping[str, object]) -> list[Mapping[str, object]]:
    nodes = [plan]
    children = plan.get("Plans")
    if isinstance(children, list):
        for child in children:
            if isinstance(child, dict):
                nodes.extend(_walk_plan(child))
    return nodes


async def _seed_integration_corpus(container, user_integration_factory) -> list[UUID]:
    """Populate several integration sources whose stamps all match 200/40."""
    session = container.session()
    user = container.user()
    embedding_model = (await session.scalars(sa.select(EmbeddingModels).limit(1))).one()
    space = Spaces(
        name=f"Chunk drift space {uuid4().hex[:8]}",
        tenant_id=user.tenant_id,
        user_id=user.id,
    )
    session.add(space)
    await session.flush()
    group = CollectionsTable(
        name=f"Chunk drift group {uuid4().hex[:8]}",
        size=0,
        user_id=user.id,
        tenant_id=user.tenant_id,
        embedding_model_id=embedding_model.id,
        space_id=space.id,
    )
    session.add(group)
    await session.flush()

    user_integration = await user_integration_factory(session, tenant_id=user.tenant_id)

    knowledge_ids: list[UUID] = []
    for source_index in range(SOURCES):
        knowledge = IntegrationKnowledge(
            name=f"Source {source_index}",
            tenant_id=user.tenant_id,
            space_id=space.id,
            embedding_model_id=embedding_model.id,
            user_integration_id=user_integration.id,
            url=f"https://example.invalid/source-{source_index}",
            size=0,
        )
        session.add(knowledge)
        await session.flush()
        knowledge_ids.append(knowledge.id)

        for blob_index in range(BLOBS_PER_SOURCE):
            text = f"source {source_index} document {blob_index}"
            session.add(
                InfoBlobs(
                    title=f"doc-{source_index}-{blob_index}.txt",
                    text=text,
                    size=len(text.encode("utf-8")),
                    content_hash=sha256(text.encode("utf-8")).digest(),
                    source_id=uuid4(),
                    version_state=InfoBlobVersionState.ACTIVE.value,
                    user_id=user.id,
                    tenant_id=user.tenant_id,
                    group_id=group.id,
                    embedding_model_id=embedding_model.id,
                    integration_knowledge_id=knowledge.id,
                    chunk_size=200,
                    chunk_overlap=40,
                )
            )
        await session.flush()

    # The planner needs statistics before its choice says anything about the index.
    connection = await session.connection()
    await connection.exec_driver_sql("ANALYZE info_blobs")
    return knowledge_ids


async def test_the_no_drift_answer_is_scoped_to_one_source(
    db_container, user_integration_factory
) -> None:
    async with db_container() as container:
        knowledge_ids = await _seed_integration_corpus(
            container, user_integration_factory
        )
        session = container.session()
        repo = InfoBlobRepository(session=session)

        # The answer itself: nothing drifted for this source.
        assert (
            await repo.any_active_chunking_differs_for_integration_knowledge(
                knowledge_ids[0],
                effective_chunk_size=200,
                effective_chunk_overlap=40,
            )
            is False
        )

        connection = await session.connection()
        # The id is inlined rather than bound: asyncpg's paramstyle differs from the
        # named form, and a literal also keeps the plan free of generic-plan effects
        # that would make the index choice say less than it should.
        explained = await connection.exec_driver_sql(
            f"""
            EXPLAIN (ANALYZE, COSTS OFF, SUMMARY OFF, FORMAT JSON)
            SELECT EXISTS (
                SELECT info_blobs.id FROM info_blobs
                WHERE info_blobs.integration_knowledge_id = '{knowledge_ids[0]}'::uuid
                  AND info_blobs.version_state = 'active'
                  AND info_blobs.chunk_size IS NOT NULL
                  AND info_blobs.chunk_overlap IS NOT NULL
                  AND (info_blobs.chunk_size <> 200 OR info_blobs.chunk_overlap <> 40)
            )
            """
        )
        document = explained.scalar_one()
        assert isinstance(document, list)
        root = document[0]
        assert isinstance(root, dict)
        plan = root.get("Plan")
        assert isinstance(plan, dict)
        nodes = _walk_plan(plan)

        index_names = {
            node.get("Index Name") for node in nodes if node.get("Index Name")
        }
        assert INDEX_NAME in index_names, index_names

        # Scoped, not scanned. Proving "no drift" does have to look at this source's
        # own index entries — nothing can rule out a differing row without checking
        # them — but it must not touch the other sources', which is the difference
        # between this source's corpus and the table.
        total_blobs = SOURCES * BLOBS_PER_SOURCE
        examined = sum(
            int(node.get("Actual Rows") or 0)
            for node in nodes
            if node.get("Index Name") == INDEX_NAME
        )
        assert examined <= BLOBS_PER_SOURCE, (examined, total_blobs)


async def test_a_drifted_stamp_is_still_found_through_the_index(
    db_container, user_integration_factory
) -> None:
    async with db_container() as container:
        knowledge_ids = await _seed_integration_corpus(
            container, user_integration_factory
        )
        session = container.session()
        repo = InfoBlobRepository(session=session)

        # One document of one source was chunked under a superseded configuration.
        await session.execute(
            sa.update(InfoBlobs)
            .where(InfoBlobs.integration_knowledge_id == knowledge_ids[1])
            .where(InfoBlobs.title == "doc-1-7.txt")
            .values(chunk_size=500, chunk_overlap=100)
        )
        await session.flush()

        assert (
            await repo.any_active_chunking_differs_for_integration_knowledge(
                knowledge_ids[1],
                effective_chunk_size=200,
                effective_chunk_overlap=40,
            )
            is True
        )
        # And the neighbouring source is unaffected, so the drift really is per-source.
        assert (
            await repo.any_active_chunking_differs_for_integration_knowledge(
                knowledge_ids[0],
                effective_chunk_size=200,
                effective_chunk_overlap=40,
            )
            is False
        )
