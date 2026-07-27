from __future__ import annotations

from hashlib import sha256
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import sqlalchemy as sa
from dependency_injector import providers

from eneo.database.tables.ai_models_table import EmbeddingModels
from eneo.database.tables.collections_table import CollectionsTable
from eneo.database.tables.info_blob_chunk_table import InfoBlobChunks
from eneo.database.tables.info_blobs_table import (
    InfoBlobs,
    InfoBlobVersionState,
)
from eneo.database.tables.spaces_table import Spaces
from eneo.files.chunk_embedding_list import ChunkEmbeddingList
from eneo.info_blobs.info_blob import InfoBlobAdd
from eneo.main.exceptions import QuotaExceededException


async def _seed_active_document(
    container,
    *,
    text: str,
    title: str,
    url: str | None = None,
):
    session = container.session()
    user = container.user()
    embedding_model = (await session.scalars(sa.select(EmbeddingModels).limit(1))).one()
    space = Spaces(
        name=f"Knowledge version space {uuid4().hex[:8]}",
        tenant_id=user.tenant_id,
        user_id=user.id,
    )
    session.add(space)
    await session.flush()
    group = CollectionsTable(
        name=f"Knowledge version group {uuid4().hex[:8]}",
        size=0,
        user_id=user.id,
        tenant_id=user.tenant_id,
        embedding_model_id=embedding_model.id,
        space_id=space.id,
    )
    session.add(group)
    await session.flush()

    source_id = uuid4()
    blob = InfoBlobs(
        title=title,
        url=url,
        text=text,
        size=len(text.encode("utf-8")),
        content_hash=sha256(text.encode("utf-8")).digest(),
        source_id=source_id,
        version_state=InfoBlobVersionState.ACTIVE.value,
        user_id=user.id,
        tenant_id=user.tenant_id,
        group_id=group.id,
        embedding_model_id=embedding_model.id,
    )
    session.add(blob)
    await session.flush()
    chunk = InfoBlobChunks(
        info_blob_id=blob.id,
        tenant_id=user.tenant_id,
        chunk_no=0,
        text=text,
        size=len(text.encode("utf-8")),
        embedding=[0.1, 0.2, 0.3],
    )
    session.add(chunk)
    await session.flush()
    return group, embedding_model, blob, chunk


def _embedding_result(*, model, chunks):
    result = ChunkEmbeddingList()
    result.add(chunks, [[0.7, 0.8, 0.9] for _ in chunks])
    return result


async def test_changed_document_publishes_one_active_version_and_keeps_history(
    db_container,
) -> None:
    title = "versioned-knowledge.txt"
    previous_text = "Previously published knowledge"
    replacement_text = "Updated knowledge that should become searchable"

    async with db_container() as container:
        group, embedding_model, previous, previous_chunk = await _seed_active_document(
            container,
            text=previous_text,
            title=title,
        )
        embeddings = AsyncMock()
        embeddings.get_embeddings.side_effect = _embedding_result
        container.create_embeddings_service.override(providers.Object(embeddings))

        published = await container.text_processor().process_text(
            text=replacement_text,
            title=title,
            embedding_model=embedding_model,
            group_id=group.id,
        )

        versions = (
            await container.session().scalars(
                sa.select(InfoBlobs)
                .where(InfoBlobs.source_id == previous.source_id)
                .order_by(InfoBlobs.created_at, InfoBlobs.id)
            )
        ).all()
        assert {version.id: version.version_state for version in versions} == {
            previous.id: InfoBlobVersionState.SUPERSEDED.value,
            published.id: InfoBlobVersionState.ACTIVE.value,
        }
        assert published.id != previous.id
        assert published.source_id == previous.source_id

        chunk_rows = (
            await container.session().scalars(
                sa.select(InfoBlobChunks).where(
                    InfoBlobChunks.info_blob_id.in_([previous.id, published.id])
                )
            )
        ).all()
        assert {chunk.info_blob_id for chunk in chunk_rows} == {
            previous.id,
            published.id,
        }
        assert any(chunk.id == previous_chunk.id for chunk in chunk_rows)

        visible = await container.info_blob_repo().get_by_group(group.id)
        historical = await container.info_blob_repo().get(previous.id)
        assert [blob.id for blob in visible] == [published.id]
        assert historical.id == previous.id
        assert await container.info_blob_repo().get_count_of_group(group.id) == 1
        assert (
            await container.info_blob_repo().get_total_size_of_group(group.id)
            == published.size
        )

        semantic_matches = await container.info_blob_chunk_repo().semantic_search(
            [0.7, 0.8, 0.9],
            group_ids=[group.id],
        )
        current_keyword_matches = await container.info_blob_chunk_repo().keyword_search(
            "Updated",
            group_ids=[group.id],
        )
        previous_keyword_matches = (
            await container.info_blob_chunk_repo().keyword_search(
                "Previously",
                group_ids=[group.id],
            )
        )
        assert [chunk.info_blob_id for chunk in semantic_matches] == [published.id]
        assert [chunk.info_blob_id for chunk in current_keyword_matches] == [
            published.id
        ]
        assert previous_keyword_matches == []

        deleted = await container.info_blob_repo().delete(published.id)
        remaining_versions = (
            await container.session().scalars(
                sa.select(InfoBlobs).where(InfoBlobs.source_id == previous.source_id)
            )
        ).all()
        assert deleted.id == published.id
        assert remaining_versions == []


async def test_unchanged_document_reuses_active_version_without_embedding(
    db_container,
) -> None:
    title = "unchanged-knowledge.txt"
    text = "Knowledge that has not changed"

    async with db_container() as container:
        group, embedding_model, active, active_chunk = await _seed_active_document(
            container,
            text=text,
            title=title,
        )
        embeddings = AsyncMock()
        container.create_embeddings_service.override(providers.Object(embeddings))

        published = await container.text_processor().process_text(
            text=text,
            title=title,
            embedding_model=embedding_model,
            group_id=group.id,
        )

        versions = (
            await container.session().scalars(
                sa.select(InfoBlobs).where(InfoBlobs.source_id == active.source_id)
            )
        ).all()
        chunks = (
            await container.session().scalars(
                sa.select(InfoBlobChunks).where(
                    InfoBlobChunks.info_blob_id == active.id
                )
            )
        ).all()
        assert published.id == active.id
        assert [(version.id, version.version_state) for version in versions] == [
            (active.id, InfoBlobVersionState.ACTIVE.value)
        ]
        assert [chunk.id for chunk in chunks] == [active_chunk.id]
        embeddings.get_embeddings.assert_not_awaited()


async def test_unchanged_document_refreshes_citation_metadata(db_container) -> None:
    title = "moved-knowledge.txt"
    text = "Knowledge whose source location changed"
    old_url = "https://example.test/old"
    new_url = "https://example.test/new"

    async with db_container() as container:
        group, embedding_model, active, active_chunk = await _seed_active_document(
            container,
            text=text,
            title=title,
            url=old_url,
        )
        embeddings = AsyncMock()
        container.create_embeddings_service.override(providers.Object(embeddings))

        published = await container.text_processor().process_text(
            text=text,
            title=title,
            url=new_url,
            embedding_model=embedding_model,
            group_id=group.id,
        )

        persisted = await container.info_blob_repo().get(active.id)
        chunks = (
            await container.session().scalars(
                sa.select(InfoBlobChunks).where(
                    InfoBlobChunks.info_blob_id == active.id
                )
            )
        ).all()
        assert published.id == active.id
        assert published.url == new_url
        assert persisted.url == new_url
        assert [chunk.id for chunk in chunks] == [active_chunk.id]
        embeddings.get_embeddings.assert_not_awaited()


async def test_untitled_documents_remain_independent_and_searchable(
    db_container,
) -> None:
    async with db_container() as container:
        group, embedding_model, _, _ = await _seed_active_document(
            container,
            text="Existing titled knowledge",
            title="existing.txt",
        )
        embeddings = AsyncMock()
        embeddings.get_embeddings.side_effect = _embedding_result
        container.create_embeddings_service.override(providers.Object(embeddings))
        service = container.info_blob_service()
        user = container.user()

        first = await service.publish_info_blob_without_validation(
            InfoBlobAdd(
                text="First titleless publication",
                title=None,
                user_id=user.id,
                tenant_id=user.tenant_id,
                group_id=group.id,
            ),
            embedding_model=embedding_model,
        )
        second = await service.publish_info_blob_without_validation(
            InfoBlobAdd(
                text="Second titleless publication",
                title=None,
                user_id=user.id,
                tenant_id=user.tenant_id,
                group_id=group.id,
            ),
            embedding_model=embedding_model,
        )

        titleless = (
            await container.session().scalars(
                sa.select(InfoBlobs).where(
                    InfoBlobs.id.in_([first.id, second.id]),
                    InfoBlobs.version_state == InfoBlobVersionState.ACTIVE.value,
                )
            )
        ).all()
        first_matches = await container.info_blob_chunk_repo().keyword_search(
            "First titleless",
            group_ids=[group.id],
        )
        second_matches = await container.info_blob_chunk_repo().keyword_search(
            "Second titleless",
            group_ids=[group.id],
        )
        assert {blob.id for blob in titleless} == {first.id, second.id}
        assert first.source_id != second.source_id
        assert [chunk.info_blob_id for chunk in first_matches] == [first.id]
        assert [chunk.info_blob_id for chunk in second_matches] == [second.id]


async def test_retained_versions_consume_quota_until_family_deletion(
    db_container,
) -> None:
    async with db_container() as container:
        group, embedding_model, _, _ = await _seed_active_document(
            container,
            text="Initial retained knowledge",
            title="quota-history.txt",
        )
        embeddings = AsyncMock()
        embeddings.get_embeddings.side_effect = _embedding_result
        container.create_embeddings_service.override(providers.Object(embeddings))
        user = container.user()
        user.tenant.quota_limit = 1_000_000

        published = await container.text_processor().process_text(
            text="First replacement retained in history",
            title="quota-history.txt",
            embedding_model=embedding_model,
            group_id=group.id,
        )
        retained_usage = await container.info_blob_repo().get_retained_size_of_tenant(
            user.tenant_id
        )
        rejected_text = "Replacement that exceeds retained capacity"
        user.tenant.quota_limit = (
            retained_usage + len(rejected_text.encode("utf-8")) - 1
        )

        with pytest.raises(QuotaExceededException, match="Tenant quota limit exceeded"):
            await container.text_processor().process_text(
                text=rejected_text,
                title="quota-history.txt",
                embedding_model=embedding_model,
                group_id=group.id,
            )

        visible = await container.info_blob_repo().get_by_group(group.id)
        assert [blob.id for blob in visible if blob.title == "quota-history.txt"] == [
            published.id
        ]

        await container.info_blob_repo().delete(published.id)
        assert (
            await container.info_blob_repo().get_retained_size_of_tenant(user.tenant_id)
            == 0
        )


async def test_failed_replacement_preserves_the_active_version(db_container) -> None:
    title = "failed-replacement.txt"
    previous_text = "Published knowledge remains available"

    async with db_container() as container:
        group, embedding_model, active, active_chunk = await _seed_active_document(
            container,
            text=previous_text,
            title=title,
        )
        embeddings = AsyncMock()
        embeddings.get_embeddings.side_effect = RuntimeError("embedding unavailable")
        container.create_embeddings_service.override(providers.Object(embeddings))
        active_id = active.id
        active_source_id = active.source_id
        active_chunk_id = active_chunk.id

        try:
            await container.text_processor().process_text(
                text="Replacement that cannot be embedded",
                title=title,
                embedding_model=embedding_model,
                group_id=group.id,
            )
        except RuntimeError as exc:
            assert str(exc) == "embedding unavailable"
        else:
            raise AssertionError("Expected the replacement to fail")

        versions = (
            await container.session().scalars(
                sa.select(InfoBlobs).where(InfoBlobs.source_id == active_source_id)
            )
        ).all()
        chunks = (
            await container.session().scalars(
                sa.select(InfoBlobChunks).where(
                    InfoBlobChunks.info_blob_id == active_id
                )
            )
        ).all()
        assert [(version.id, version.version_state) for version in versions] == [
            (active_id, InfoBlobVersionState.ACTIVE.value)
        ]
        assert [chunk.id for chunk in chunks] == [active_chunk_id]
