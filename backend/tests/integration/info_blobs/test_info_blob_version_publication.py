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
from eneo.database.tables.integration_table import IntegrationKnowledge
from eneo.database.tables.spaces_table import Spaces
from eneo.database.tables.websites_table import Websites
from eneo.files.chunk_embedding_list import ChunkEmbeddingList
from eneo.info_blobs.info_blob import InfoBlobAdd
from eneo.main.exceptions import QuotaExceededException
from eneo.websites.domain.crawl_run import CrawlType


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


async def test_same_content_is_reembedded_after_model_change(db_container) -> None:
    title = "model-change.txt"
    text = "Knowledge retained while its embedding model changes"

    async with db_container() as container:
        group, old_model, active, _ = await _seed_active_document(
            container,
            text=text,
            title=title,
        )
        new_model = EmbeddingModels(
            name=f"replacement-embedding-{uuid4().hex[:8]}",
            open_source=True,
            dimensions=3,
            max_input=8_192,
            max_batch_size=32,
            family="test",
            stability="stable",
            hosting="self-hosted",
        )
        container.session().add(new_model)
        await container.session().flush()
        await container.session().execute(
            sa.update(CollectionsTable)
            .where(CollectionsTable.id == group.id)
            .values(embedding_model_id=new_model.id)
            .execution_options(synchronize_session=False)
        )
        await container.session().refresh(group)
        active.group = group

        embeddings = AsyncMock()
        embeddings.get_embeddings.side_effect = _embedding_result
        container.create_embeddings_service.override(providers.Object(embeddings))

        published = await container.text_processor().process_text(
            text=text,
            title=title,
            embedding_model=new_model,
            group_id=group.id,
        )

        assert published.id != active.id
        assert published.embedding_model_id == new_model.id
        assert published.embedding_model_id != old_model.id
        versions = (
            await container.session().scalars(
                sa.select(InfoBlobs).where(InfoBlobs.source_id == active.source_id)
            )
        ).all()
        states_by_id = {version.id: version.version_state for version in versions}
        assert states_by_id == {
            active.id: InfoBlobVersionState.SUPERSEDED.value,
            published.id: InfoBlobVersionState.ACTIVE.value,
        }
        matches = await container.info_blob_chunk_repo().semantic_search(
            [0.7, 0.8, 0.9],
            group_ids=[group.id],
        )
        assert [match.info_blob_id for match in matches] == [published.id]


async def test_changed_website_file_publishes_from_a_fresh_session(
    db_container,
) -> None:
    title = "downloaded-website-file.txt"
    previous_text = "Previous downloaded file content"
    replacement_text = "Replacement downloaded file content"

    async with db_container() as container:
        session = container.session()
        user = container.user()
        embedding_model_id = await session.scalar(
            sa.select(EmbeddingModels.id).limit(1)
        )
        assert embedding_model_id is not None
        website = Websites(
            name="Knowledge version website",
            url="https://knowledge-version.example.com",
            download_files=True,
            crawl_type=CrawlType.CRAWL,
            update_interval="never",
            size=0,
            tenant_id=user.tenant_id,
            user_id=user.id,
            embedding_model_id=embedding_model_id,
        )
        session.add(website)
        await session.flush()
        previous = InfoBlobs(
            title=title,
            text=previous_text,
            size=len(previous_text.encode("utf-8")),
            content_hash=sha256(previous_text.encode("utf-8")).digest(),
            source_id=uuid4(),
            version_state=InfoBlobVersionState.ACTIVE.value,
            user_id=user.id,
            tenant_id=user.tenant_id,
            website_id=website.id,
            embedding_model_id=embedding_model_id,
        )
        session.add(previous)
        await session.flush()
        website_id = website.id
        previous_id = previous.id
        source_id = previous.source_id

    async with db_container() as container:
        embedding_model = await container.embedding_model_repo2().one(
            embedding_model_id
        )
        embeddings = AsyncMock()
        embeddings.get_embeddings.side_effect = _embedding_result
        container.create_embeddings_service.override(providers.Object(embeddings))

        published = await container.text_processor().process_text(
            text=replacement_text,
            title=title,
            embedding_model=embedding_model,
            website_id=website_id,
        )
        versions = (
            await container.session().scalars(
                sa.select(InfoBlobs).where(InfoBlobs.source_id == source_id)
            )
        ).all()
        assert {version.id: version.version_state for version in versions} == {
            previous_id: InfoBlobVersionState.SUPERSEDED.value,
            published.id: InfoBlobVersionState.ACTIVE.value,
        }


async def test_sharepoint_family_delete_reads_only_active_version(
    db_container,
    user_integration_factory,
) -> None:
    async with db_container() as container:
        group, embedding_model, _, _ = await _seed_active_document(
            container,
            text="Fixture knowledge",
            title="fixture.txt",
        )
        session = container.session()
        user = container.user()
        user_integration = await user_integration_factory(
            session,
            tenant_id=user.tenant_id,
        )
        knowledge = IntegrationKnowledge(
            name="SharePoint version deletion",
            url="https://example.test/sharepoint",
            space_id=group.space_id,
            tenant_id=user.tenant_id,
            embedding_model_id=embedding_model.id,
            user_integration_id=user_integration.id,
            size=321,
        )
        session.add(knowledge)
        await session.flush()

        source_id = uuid4()
        item_id = f"sharepoint-{uuid4().hex}"
        history = [
            InfoBlobs(
                title="retained.docx",
                text=f"retained version {index}",
                size=index + 1,
                content_hash=sha256(str(index).encode()).digest(),
                source_id=source_id,
                version_state=InfoBlobVersionState.SUPERSEDED.value,
                user_id=user.id,
                tenant_id=user.tenant_id,
                integration_knowledge_id=knowledge.id,
                embedding_model_id=embedding_model.id,
                sharepoint_item_id=item_id,
            )
            for index in range(32)
        ]
        active = InfoBlobs(
            title="retained.docx",
            text="current version",
            size=321,
            content_hash=sha256(b"current version").digest(),
            source_id=source_id,
            version_state=InfoBlobVersionState.ACTIVE.value,
            user_id=user.id,
            tenant_id=user.tenant_id,
            integration_knowledge_id=knowledge.id,
            embedding_model_id=embedding_model.id,
            sharepoint_item_id=item_id,
        )
        session.add_all([*history, active])
        await session.flush()

        deleted = await container.info_blob_repo().delete_by_sharepoint_item_and_integration_knowledge(
            item_id,
            knowledge.id,
        )

        assert [(blob.id, blob.size) for blob in deleted] == [(active.id, 321)]
        remaining = await session.scalar(
            sa.select(sa.func.count())
            .select_from(InfoBlobs)
            .where(InfoBlobs.source_id == source_id)
        )
        assert remaining == 0


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
