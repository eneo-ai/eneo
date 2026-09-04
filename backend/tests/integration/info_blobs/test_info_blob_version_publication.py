from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from hashlib import sha256
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import numpy as np
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
from eneo.database.tables.object_content_table import (
    InfoBlobContentReferences,
    InlineContentPayloads,
    ObjectContents,
)
from eneo.database.tables.spaces_table import Spaces
from eneo.database.tables.tenant_table import Tenants
from eneo.database.tables.users_table import Users
from eneo.database.tables.websites_table import Websites
from eneo.files.chunk_embedding_list import ChunkEmbeddingList
from eneo.info_blobs.info_blob import (
    InfoBlobAdd,
    PreparedKnowledgeOriginal,
)
from eneo.info_blobs.info_blob_repo import InfoBlobRepository
from eneo.main.exceptions import (
    InfoBlobPublicationConflictError,
    QuotaExceededException,
)
from eneo.object_content.content import ContentState, StorageKind
from eneo.websites.domain.crawl_run import CrawlType
from eneo.worker.crawl.persistence import (
    _publish_prepared_pages,
    _refresh_http_validators,
)
from eneo.worker.crawl_context import CrawlContext, PreparedPage


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


async def test_crawler_float32_vector_round_trips_through_postgres(
    db_container,
    monkeypatch,
) -> None:
    content = "Float32 crawler publication contract"
    title = "https://knowledge-version.example.com/float32"
    source_vector = np.asarray([0.12345679, -0.5, 0.9876543], dtype=np.float32)

    async with db_container() as container:
        session = container.session()
        user = container.user()
        tenant = container.tenant()
        embedding_model_id = await session.scalar(
            sa.select(EmbeddingModels.id).limit(1)
        )
        assert embedding_model_id is not None
        website = Websites(
            name="Float32 publication website",
            url="https://knowledge-version.example.com",
            download_files=False,
            crawl_type=CrawlType.CRAWL,
            update_interval="never",
            size=0,
            tenant_id=user.tenant_id,
            user_id=user.id,
            embedding_model_id=embedding_model_id,
        )
        session.add(website)
        await session.flush()
        website_id = website.id
        user_id = user.id
        tenant_id = user.tenant_id
        tenant_slug = tenant.slug

    ctx = CrawlContext(
        website_id=website_id,
        tenant_id=tenant_id,
        tenant_slug=tenant_slug,
        user_id=user_id,
        attempt_id=uuid4(),
        lease_owner="float32-round-trip",
        embedding_model_id=embedding_model_id,
        embedding_model_name="round-trip-model",
        embedding_model_open_source=False,
        embedding_model_family=None,
        embedding_model_dimensions=len(source_vector),
    )
    prepared = PreparedPage(
        url=title,
        title=title,
        content=content,
        content_hash=sha256(content.encode("utf-8")).digest(),
        http_etag=None,
        http_last_modified=None,
        chunks=[content],
        embeddings=[source_vector],
        tenant_id=tenant_id,
        website_id=website_id,
        user_id=user_id,
        embedding_model_id=embedding_model_id,
    )
    lease_check = AsyncMock()
    monkeypatch.setattr(
        "eneo.worker.crawl.persistence._require_current_publication_lease",
        lease_check,
    )

    published, failures = await _publish_prepared_pages(
        prepared_pages=[prepared],
        ctx=ctx,
    )

    assert published == [title]
    assert failures == {}
    lease_check.assert_awaited_once()
    async with db_container() as container:
        stored_vector = await container.session().scalar(
            sa.select(InfoBlobChunks.embedding)
            .join(InfoBlobs)
            .where(
                InfoBlobs.website_id == website_id,
                InfoBlobs.title == title,
            )
        )
    assert stored_vector is not None
    np.testing.assert_array_equal(
        np.asarray(stored_vector, dtype=np.float32),
        source_vector,
    )


@pytest.mark.parametrize("database_failure", [False, True])
async def test_validator_refresh_updates_only_the_existing_website_version(
    db_container,
    monkeypatch,
    database_failure,
) -> None:
    title = "https://validator-refresh.example.com/page"
    original_text = "Unchanged page content"

    async with db_container() as container:
        session = container.session()
        engine = session.bind
        assert engine is not None
        user = container.user()
        tenant = container.tenant()
        embedding_model_id = await session.scalar(
            sa.select(EmbeddingModels.id).limit(1)
        )
        assert embedding_model_id is not None
        websites = [
            Websites(
                name=f"Validator refresh {index}",
                url=f"https://validator-refresh-{index}.example.com",
                download_files=False,
                crawl_type=CrawlType.CRAWL,
                update_interval="never",
                size=0,
                tenant_id=user.tenant_id,
                user_id=user.id,
                embedding_model_id=embedding_model_id,
            )
            for index in range(2)
        ]
        session.add_all(websites)
        await session.flush()
        other_tenant = Tenants(
            name=f"Validator refresh tenant {uuid4()}",
            slug=f"validator-refresh-{uuid4().hex[:12]}",
            quota_limit=1_000_000,
            state="active",
        )
        session.add(other_tenant)
        await session.flush()
        other_user = Users(
            username="validator-refresh-user",
            email=f"validator-refresh-{uuid4()}@example.com",
            state="active",
            used_tokens=0,
            tenant_id=other_tenant.id,
        )
        session.add(other_user)
        await session.flush()
        other_tenant_website = Websites(
            name="Other tenant validator refresh",
            url="https://other-tenant-validator-refresh.example.com",
            download_files=False,
            crawl_type=CrawlType.CRAWL,
            update_interval="never",
            size=0,
            tenant_id=other_tenant.id,
            user_id=other_user.id,
            embedding_model_id=embedding_model_id,
        )
        session.add(other_tenant_website)
        await session.flush()
        blobs = [
            InfoBlobs(
                title=title,
                url=title,
                text=original_text,
                size=len(original_text.encode()),
                content_hash=sha256(original_text.encode()).digest(),
                http_etag='"old"',
                http_last_modified="Wed, 12 Aug 2026 10:00:00 GMT",
                source_id=uuid4(),
                version_state=InfoBlobVersionState.ACTIVE.value,
                user_id=user.id,
                tenant_id=user.tenant_id,
                website_id=website.id,
                embedding_model_id=embedding_model_id,
            )
            for website in websites
        ]
        blobs.append(
            InfoBlobs(
                title=title,
                url=title,
                text=original_text,
                size=len(original_text.encode()),
                content_hash=sha256(original_text.encode()).digest(),
                http_etag='"old"',
                http_last_modified="Wed, 12 Aug 2026 10:00:00 GMT",
                source_id=uuid4(),
                version_state=InfoBlobVersionState.ACTIVE.value,
                user_id=other_user.id,
                tenant_id=other_tenant.id,
                website_id=other_tenant_website.id,
                embedding_model_id=embedding_model_id,
            )
        )
        session.add_all(blobs)
        await session.flush()
        target_website_id = websites[0].id
        other_website_id = websites[1].id
        other_tenant_website_id = other_tenant_website.id
        tenant_id = user.tenant_id
        user_id = user.id
        tenant_slug = tenant.slug

    ctx = CrawlContext(
        website_id=target_website_id,
        tenant_id=tenant_id,
        tenant_slug=tenant_slug,
        user_id=user_id,
        attempt_id=uuid4(),
        lease_owner="validator-refresh",
        embedding_model_id=embedding_model_id,
        embedding_model_name="validator-model",
        embedding_model_open_source=False,
        embedding_model_family=None,
        embedding_model_dimensions=1536,
    )
    lease_check = AsyncMock()
    monkeypatch.setattr(
        "eneo.worker.crawl.persistence._require_current_publication_lease",
        lease_check,
    )

    aborted = False

    def abort_after_update(
        connection, cursor, statement, parameters, context, executemany
    ):
        nonlocal aborted
        if statement.startswith("UPDATE info_blobs SET http_etag"):
            # Fail in PostgreSQL after the UPDATE, proving its transaction rolls back.
            aborted = True
            connection.exec_driver_sql("SELECT 1 / 0")

    if database_failure:
        sa.event.listen(engine.sync_engine, "after_cursor_execute", abort_after_update)
    try:
        refreshed = await _refresh_http_validators(
            ctx=ctx,
            rows=[
                {
                    "url": title,
                    "content": original_text,
                    "etag": '"new"',
                    "last_modified": "Thu, 13 Aug 2026 10:00:00 GMT",
                }
            ],
        )
    finally:
        if database_failure:
            sa.event.remove(
                engine.sync_engine, "after_cursor_execute", abort_after_update
            )
    assert refreshed is not database_failure
    assert aborted is database_failure

    lease_check.assert_awaited_once()
    async with db_container() as container:
        rows = (
            await container.session().execute(
                sa.select(
                    InfoBlobs.website_id,
                    InfoBlobs.http_etag,
                    InfoBlobs.http_last_modified,
                ).where(InfoBlobs.title == title)
            )
        ).all()
        stored = {
            website_id: (etag, last_modified)
            for website_id, etag, last_modified in rows
        }
        version_count = await container.session().scalar(
            sa.select(sa.func.count())
            .select_from(InfoBlobs)
            .where(InfoBlobs.title == title)
        )

    assert stored[target_website_id] == (
        ('"old"', "Wed, 12 Aug 2026 10:00:00 GMT")
        if database_failure
        else ('"new"', "Thu, 13 Aug 2026 10:00:00 GMT")
    )
    assert stored[other_website_id] == (
        '"old"',
        "Wed, 12 Aug 2026 10:00:00 GMT",
    )
    assert stored[other_tenant_website_id] == (
        '"old"',
        "Wed, 12 Aug 2026 10:00:00 GMT",
    )
    assert version_count == 3


async def _bytes_source(payload: bytes) -> AsyncGenerator[bytes]:
    yield payload


@asynccontextmanager
async def _inline_original(
    container,
    payload: bytes,
    *,
    filename: str,
) -> AsyncGenerator[PreparedKnowledgeOriginal]:
    async with container.object_content_service().capture_for_target(
        _bytes_source(payload),
        storage_kind=StorageKind.POSTGRES_INLINE,
        declared_media_type="text/plain",
        verified_media_type="text/plain",
        business_maximum_bytes=1_000_000,
    ) as captured:
        yield PreparedKnowledgeOriginal(
            job_id=uuid4(),
            original_filename=filename,
            policy_revision=3,
            storage_kind=StorageKind.POSTGRES_INLINE,
            captured=captured,
        )


async def _original_reference(session, info_blob_id):
    return (
        await session.execute(
            sa.select(
                InfoBlobContentReferences,
                ObjectContents,
                InlineContentPayloads.payload,
            )
            .join(
                ObjectContents,
                ObjectContents.id == InfoBlobContentReferences.content_id,
            )
            .outerjoin(
                InlineContentPayloads,
                InlineContentPayloads.content_id == ObjectContents.id,
            )
            .where(InfoBlobContentReferences.info_blob_id == info_blob_id)
        )
    ).one_or_none()


async def test_new_upload_retains_exact_inline_original_and_counts_it_once(
    db_container,
) -> None:
    text = "Searchable text from an exact original"
    payload = "Exact original café".encode()

    async with db_container() as container:
        group, embedding_model, _, _ = await _seed_active_document(
            container,
            text="Unrelated fixture",
            title="unrelated.txt",
        )
        embeddings = AsyncMock()
        embeddings.get_embeddings.side_effect = _embedding_result
        container.create_embeddings_service.override(providers.Object(embeddings))

        async with _inline_original(
            container,
            payload,
            filename="original.txt",
        ) as original:
            published = await container.text_processor().process_text(
                text=text,
                title="original.txt",
                embedding_model=embedding_model,
                group_id=group.id,
                original=original,
            )

        reference = await _original_reference(container.session(), published.id)
        assert reference is not None
        link, content, inline_payload = reference
        assert link.original_filename == "original.txt"
        assert content.storage_kind == StorageKind.POSTGRES_INLINE.value
        assert content.state == ContentState.AVAILABLE.value
        assert content.sha256 == sha256(payload).digest()
        assert content.size_bytes == len(payload)
        assert inline_payload == payload

        chunk_size = await container.session().scalar(
            sa.select(sa.func.coalesce(sa.func.sum(InfoBlobChunks.size), 0)).where(
                InfoBlobChunks.info_blob_id == published.id
            )
        )
        assert published.size == len(text.encode()) + int(chunk_size) + len(payload)

        first_size = published.size
        assert (
            await container.info_blob_service().update_info_blob_size(published.id)
        ).size == first_size
        assert (
            await container.info_blob_service().update_info_blob_size(published.id)
        ).size == first_size


async def test_identical_healthy_reupload_keeps_version_and_refreshes_filename(
    db_container,
) -> None:
    text = "Unchanged searchable knowledge"
    payload = b"unchanged exact bytes"

    async with db_container() as container:
        group, embedding_model, _, _ = await _seed_active_document(
            container,
            text="Unrelated fixture",
            title="fixture.txt",
        )
        embeddings = AsyncMock()
        embeddings.get_embeddings.side_effect = _embedding_result
        container.create_embeddings_service.override(providers.Object(embeddings))

        async with _inline_original(
            container,
            payload,
            filename="first-name.txt",
        ) as original:
            first = await container.text_processor().process_text(
                text=text,
                title="first-name.txt",
                embedding_model=embedding_model,
                group_id=group.id,
                original=original,
            )
        first_reference = await _original_reference(container.session(), first.id)
        assert first_reference is not None
        first_content_id = first_reference[0].content_id
        retained_before = await container.info_blob_repo().get_retained_size_of_tenant(
            container.user().tenant_id
        )
        container.user().tenant.quota_limit = retained_before

        async with _inline_original(
            container,
            payload,
            filename="renamed.txt",
        ) as original:
            second = await container.text_processor().process_text(
                text=text,
                title="renamed.txt",
                embedding_model=embedding_model,
                group_id=group.id,
                original=original,
            )

        second_reference = await _original_reference(container.session(), second.id)
        assert second_reference is not None
        assert second.id == first.id
        assert second.title == "renamed.txt"
        assert second_reference[0].content_id == first_content_id
        assert second_reference[0].original_filename == "renamed.txt"
        assert (
            await container.session().scalar(
                sa.select(sa.func.count()).select_from(ObjectContents)
            )
            == 1
        )
        assert (
            await container.info_blob_repo().get_retained_size_of_tenant(
                container.user().tenant_id
            )
            == retained_before
        )


async def test_concurrent_identical_uploads_serialize_by_digest_across_titles(
    db_container,
) -> None:
    text = "Concurrent identical searchable knowledge"
    payload = b"concurrent identical original"
    first_embedding_started = asyncio.Event()
    release_first_embedding = asyncio.Event()

    async with db_container() as setup:
        group, embedding_model, _, _ = await _seed_active_document(
            setup,
            text="Unrelated fixture",
            title="fixture.txt",
        )
        group_id = group.id
        embedding_model_id = embedding_model.id

    async def publish(
        *,
        filename: str,
        block_embedding: bool,
    ):
        async with db_container() as container:
            model = await container.session().get(
                EmbeddingModels,
                embedding_model_id,
            )
            assert model is not None
            embeddings = AsyncMock()

            if block_embedding:

                async def wait_before_embedding(*, model, chunks):
                    first_embedding_started.set()
                    await release_first_embedding.wait()
                    return _embedding_result(model=model, chunks=chunks)

                embeddings.get_embeddings.side_effect = wait_before_embedding
            else:
                embeddings.get_embeddings.side_effect = _embedding_result
            container.create_embeddings_service.override(providers.Object(embeddings))

            async with _inline_original(
                container,
                payload,
                filename=filename,
            ) as original:
                return await container.text_processor().process_text(
                    text=text,
                    title=filename,
                    embedding_model=model,
                    group_id=group_id,
                    original=original,
                )

    first_task = asyncio.create_task(
        publish(filename="first-name.txt", block_embedding=True)
    )
    await asyncio.wait_for(first_embedding_started.wait(), timeout=10)
    second_task = asyncio.create_task(
        publish(filename="second-name.txt", block_embedding=False)
    )
    await asyncio.sleep(0.1)
    release_first_embedding.set()
    first, second = await asyncio.gather(first_task, second_task)

    assert first.id == second.id
    async with db_container() as verification:
        active = (
            await verification.session().scalars(
                sa.select(InfoBlobs).where(
                    InfoBlobs.group_id == group_id,
                    InfoBlobs.title == "second-name.txt",
                    InfoBlobs.version_state == InfoBlobVersionState.ACTIVE.value,
                )
            )
        ).one()
        reference = await _original_reference(verification.session(), active.id)
        assert reference is not None
        assert reference[0].original_filename == "second-name.txt"
        assert (
            await verification.session().scalar(
                sa.select(sa.func.count())
                .select_from(InfoBlobContentReferences)
                .join(
                    InfoBlobs,
                    InfoBlobs.id == InfoBlobContentReferences.info_blob_id,
                )
                .where(InfoBlobs.group_id == group_id)
            )
            == 1
        )
        assert (
            await verification.session().scalar(
                sa.select(sa.func.count()).select_from(ObjectContents)
            )
            == 1
        )


async def test_concurrent_changed_originals_keep_one_active_version_and_history(
    db_container,
) -> None:
    title = "concurrent-version.txt"
    text = "Concurrent extracted text"
    first_embedding_started = asyncio.Event()
    release_first_embedding = asyncio.Event()

    async with db_container() as setup:
        group, embedding_model, _, _ = await _seed_active_document(
            setup,
            text="Unrelated fixture",
            title="fixture.txt",
        )
        group_id = group.id
        embedding_model_id = embedding_model.id

    async def publish(*, payload: bytes, block_embedding: bool):
        async with db_container() as container:
            model = await container.session().get(
                EmbeddingModels,
                embedding_model_id,
            )
            assert model is not None
            embeddings = AsyncMock()

            if block_embedding:

                async def wait_before_embedding(*, model, chunks):
                    first_embedding_started.set()
                    await release_first_embedding.wait()
                    return _embedding_result(model=model, chunks=chunks)

                embeddings.get_embeddings.side_effect = wait_before_embedding
            else:
                embeddings.get_embeddings.side_effect = _embedding_result
            container.create_embeddings_service.override(providers.Object(embeddings))

            async with _inline_original(
                container,
                payload,
                filename=title,
            ) as original:
                return await container.text_processor().process_text(
                    text=text,
                    title=title,
                    embedding_model=model,
                    group_id=group_id,
                    original=original,
                )

    first_task = asyncio.create_task(
        publish(payload=b"first concurrent original", block_embedding=True)
    )
    await asyncio.wait_for(first_embedding_started.wait(), timeout=10)
    second_task = asyncio.create_task(
        publish(payload=b"second concurrent original", block_embedding=False)
    )
    await asyncio.sleep(0.1)
    release_first_embedding.set()
    first, second = await asyncio.gather(first_task, second_task)

    assert first.id != second.id
    async with db_container() as verification:
        versions = (
            await verification.session().scalars(
                sa.select(InfoBlobs)
                .where(
                    InfoBlobs.source_id == first.source_id,
                    InfoBlobs.group_id == group_id,
                )
                .order_by(InfoBlobs.created_at, InfoBlobs.id)
            )
        ).all()
        assert {version.id: version.version_state for version in versions} == {
            first.id: InfoBlobVersionState.SUPERSEDED.value,
            second.id: InfoBlobVersionState.ACTIVE.value,
        }
        references = (
            await verification.session().scalars(
                sa.select(InfoBlobContentReferences)
                .join(
                    InfoBlobs,
                    InfoBlobs.id == InfoBlobContentReferences.info_blob_id,
                )
                .where(InfoBlobs.source_id == first.source_id)
            )
        ).all()
        assert len(references) == 2
        assert {reference.info_blob_id for reference in references} == {
            first.id,
            second.id,
        }


async def _seed_crossed_identity_sources(
    db_container,
) -> tuple[UUID, UUID, UUID, UUID]:
    async with db_container() as container:
        group, embedding_model, _, _ = await _seed_active_document(
            container,
            text="Unrelated fixture",
            title="fixture.txt",
        )
        embeddings = AsyncMock()
        embeddings.get_embeddings.side_effect = _embedding_result
        container.create_embeddings_service.override(providers.Object(embeddings))

        async with _inline_original(
            container,
            b"original A",
            filename="A.txt",
        ) as original:
            first = await container.text_processor().process_text(
                text="Searchable A",
                title="A.txt",
                embedding_model=embedding_model,
                group_id=group.id,
                original=original,
            )
        async with _inline_original(
            container,
            b"original B",
            filename="B.txt",
        ) as original:
            second = await container.text_processor().process_text(
                text="Searchable B",
                title="B.txt",
                embedding_model=embedding_model,
                group_id=group.id,
                original=original,
            )

        return group.id, embedding_model.id, first.id, second.id


async def test_conflicting_title_and_original_identities_preserve_both_sources(
    db_container,
) -> None:
    (
        group_id,
        embedding_model_id,
        first_id,
        second_id,
    ) = await _seed_crossed_identity_sources(db_container)

    async with db_container() as container:
        embedding_model = await container.session().get(
            EmbeddingModels,
            embedding_model_id,
        )
        assert embedding_model is not None
        embeddings = AsyncMock()
        embeddings.get_embeddings.side_effect = _embedding_result
        container.create_embeddings_service.override(providers.Object(embeddings))

        with pytest.raises(
            InfoBlobPublicationConflictError,
            match="identity is ambiguous",
        ):
            async with _inline_original(
                container,
                b"original A",
                filename="B.txt",
            ) as original:
                await container.text_processor().process_text(
                    text="Conflicting replacement",
                    title="B.txt",
                    embedding_model=embedding_model,
                    group_id=group_id,
                    original=original,
                )

        active = (
            await container.session().scalars(
                sa.select(InfoBlobs)
                .where(
                    InfoBlobs.id.in_((first_id, second_id)),
                    InfoBlobs.version_state == InfoBlobVersionState.ACTIVE.value,
                )
                .order_by(InfoBlobs.title)
            )
        ).all()
        assert [(row.id, row.title) for row in active] == [
            (first_id, "A.txt"),
            (second_id, "B.txt"),
        ]
        first_reference = await _original_reference(container.session(), first_id)
        second_reference = await _original_reference(container.session(), second_id)
        assert first_reference is not None
        assert second_reference is not None
        assert first_reference[1].sha256 == sha256(b"original A").digest()
        assert second_reference[1].sha256 == sha256(b"original B").digest()
        assert (
            await container.session().scalar(
                sa.select(sa.func.count()).select_from(ObjectContents)
            )
            == 2
        )


async def test_crossed_publication_identities_complete_without_deadlock(
    db_container,
) -> None:
    group_id, _, first_id, second_id = await _seed_crossed_identity_sources(
        db_container
    )
    ready = asyncio.Barrier(2)

    async def resolve_conflict(*, title: str, original_sha256: bytes) -> None:
        async with db_container() as container:
            info_blob = InfoBlobAdd(
                title=title,
                user_id=container.user().id,
                text="Conflicting replacement",
                group_id=group_id,
                tenant_id=container.user().tenant_id,
            )
            repo = InfoBlobRepository(container.session())

            with pytest.raises(
                InfoBlobPublicationConflictError,
                match="identity is ambiguous",
            ):
                async with container.session().begin_nested():
                    await repo.lock_publication_identity(
                        info_blob,
                        original_sha256=original_sha256,
                    )
                    await ready.wait()
                    await repo.get_active_for_publication(
                        info_blob,
                        original_sha256=original_sha256,
                    )

    await asyncio.wait_for(
        asyncio.gather(
            resolve_conflict(
                title="A.txt",
                original_sha256=sha256(b"original B").digest(),
            ),
            resolve_conflict(
                title="B.txt",
                original_sha256=sha256(b"original A").digest(),
            ),
        ),
        timeout=10,
    )

    async with db_container() as verification:
        active = (
            await verification.session().scalars(
                sa.select(InfoBlobs)
                .where(
                    InfoBlobs.id.in_((first_id, second_id)),
                    InfoBlobs.version_state == InfoBlobVersionState.ACTIVE.value,
                )
                .order_by(InfoBlobs.title)
            )
        ).all()
        assert [(row.id, row.title) for row in active] == [
            (first_id, "A.txt"),
            (second_id, "B.txt"),
        ]


async def test_different_original_with_same_text_creates_a_retained_version(
    db_container,
) -> None:
    text = "Same extracted text"

    async with db_container() as container:
        group, embedding_model, _, _ = await _seed_active_document(
            container,
            text="Unrelated fixture",
            title="fixture.txt",
        )
        embeddings = AsyncMock()
        embeddings.get_embeddings.side_effect = _embedding_result
        container.create_embeddings_service.override(providers.Object(embeddings))

        async with _inline_original(
            container,
            b"first original",
            filename="knowledge.txt",
        ) as original:
            first = await container.text_processor().process_text(
                text=text,
                title="knowledge.txt",
                embedding_model=embedding_model,
                group_id=group.id,
                original=original,
            )
        async with _inline_original(
            container,
            b"different original",
            filename="knowledge.txt",
        ) as original:
            second = await container.text_processor().process_text(
                text=text,
                title="knowledge.txt",
                embedding_model=embedding_model,
                group_id=group.id,
                original=original,
            )

        assert second.id != first.id
        versions = (
            await container.session().scalars(
                sa.select(InfoBlobs).where(InfoBlobs.source_id == first.source_id)
            )
        ).all()
        assert {row.id: row.version_state for row in versions} == {
            first.id: InfoBlobVersionState.SUPERSEDED.value,
            second.id: InfoBlobVersionState.ACTIVE.value,
        }
        first_reference = await _original_reference(container.session(), first.id)
        second_reference = await _original_reference(container.session(), second.id)
        assert first_reference is not None
        assert second_reference is not None
        content_ids = {
            first_reference[0].content_id,
            second_reference[0].content_id,
        }

        await container.info_blob_repo().delete(second.id)

        assert (
            await container.session().scalar(
                sa.select(sa.func.count())
                .select_from(InfoBlobs)
                .where(InfoBlobs.source_id == first.source_id)
            )
            == 0
        )
        assert (
            await container.session().scalar(
                sa.select(sa.func.count())
                .select_from(InfoBlobContentReferences)
                .where(InfoBlobContentReferences.content_id.in_(content_ids))
            )
            == 0
        )
        detached = (
            await container.session().scalars(
                sa.select(ObjectContents).where(ObjectContents.id.in_(content_ids))
            )
        ).all()
        assert len(detached) == 2
        for content in detached:
            await container.session().refresh(content)
        assert all(content.reference_count == 0 for content in detached)
        assert all(content.delete_requested_at is not None for content in detached)


async def test_legacy_active_version_without_original_gets_a_new_version(
    db_container,
) -> None:
    text = "Legacy searchable text"

    async with db_container() as container:
        group, embedding_model, legacy, _ = await _seed_active_document(
            container,
            text=text,
            title="legacy.txt",
        )
        embeddings = AsyncMock()
        embeddings.get_embeddings.side_effect = _embedding_result
        container.create_embeddings_service.override(providers.Object(embeddings))

        async with _inline_original(
            container,
            b"newly retained original",
            filename="legacy.txt",
        ) as original:
            published = await container.text_processor().process_text(
                text=text,
                title="legacy.txt",
                embedding_model=embedding_model,
                group_id=group.id,
                original=original,
            )

        assert published.id != legacy.id
        assert await _original_reference(container.session(), legacy.id) is None
        assert await _original_reference(container.session(), published.id) is not None


async def test_identical_reupload_repairs_failed_original_without_new_version_or_quota(
    db_container,
) -> None:
    text = "Knowledge whose original needs repair"
    payload = b"repairable bytes"

    async with db_container() as container:
        group, embedding_model, _, _ = await _seed_active_document(
            container,
            text="Unrelated fixture",
            title="fixture.txt",
        )
        embeddings = AsyncMock()
        embeddings.get_embeddings.side_effect = _embedding_result
        container.create_embeddings_service.override(providers.Object(embeddings))

        async with _inline_original(
            container,
            payload,
            filename="before.txt",
        ) as original:
            first = await container.text_processor().process_text(
                text=text,
                title="knowledge.txt",
                embedding_model=embedding_model,
                group_id=group.id,
                original=original,
            )
        before = await _original_reference(container.session(), first.id)
        assert before is not None
        failed_content_id = before[0].content_id
        await container.session().execute(
            sa.update(ObjectContents)
            .where(ObjectContents.id == failed_content_id)
            .values(
                state=ContentState.FAILED.value,
                failure_code="backend_missing",
                failure_detail="test repair",
            )
        )
        retained_before = await container.info_blob_repo().get_retained_size_of_tenant(
            container.user().tenant_id
        )
        container.user().tenant.quota_limit = retained_before

        async with _inline_original(
            container,
            payload,
            filename="after.txt",
        ) as original:
            repaired = await container.text_processor().process_text(
                text=text,
                title="knowledge.txt",
                embedding_model=embedding_model,
                group_id=group.id,
                original=original,
            )

        after = await _original_reference(container.session(), repaired.id)
        assert after is not None
        assert repaired.id == first.id
        assert after[0].content_id != failed_content_id
        assert after[0].original_filename == "after.txt"
        failed = await container.session().get(ObjectContents, failed_content_id)
        assert failed is not None
        await container.session().refresh(failed)
        assert failed.reference_count == 0
        assert failed.delete_requested_at is not None
        assert (
            await container.info_blob_repo().get_retained_size_of_tenant(
                container.user().tenant_id
            )
            == retained_before
        )


async def test_failed_original_repair_rolls_back_reference_replacement(
    db_container,
    monkeypatch,
) -> None:
    text = "Knowledge whose failed original must remain attached"
    payload = b"repair rollback bytes"

    async with db_container() as container:
        group, embedding_model, _, _ = await _seed_active_document(
            container,
            text="Unrelated fixture",
            title="fixture.txt",
        )
        embeddings = AsyncMock()
        embeddings.get_embeddings.side_effect = _embedding_result
        container.create_embeddings_service.override(providers.Object(embeddings))

        async with _inline_original(
            container,
            payload,
            filename="before.txt",
        ) as original:
            published = await container.text_processor().process_text(
                text=text,
                title="knowledge.txt",
                embedding_model=embedding_model,
                group_id=group.id,
                original=original,
            )
        before = await _original_reference(container.session(), published.id)
        assert before is not None
        failed_content_id = before[0].content_id
        await container.session().execute(
            sa.update(ObjectContents)
            .where(ObjectContents.id == failed_content_id)
            .values(
                state=ContentState.FAILED.value,
                failure_code="backend_missing",
                failure_detail="test repair rollback",
            )
        )
        content_count_before = await container.session().scalar(
            sa.select(sa.func.count()).select_from(ObjectContents)
        )
        retained_before = await container.info_blob_repo().get_retained_size_of_tenant(
            container.user().tenant_id
        )

        async def reject_replacement_reference(
            self,
            *,
            info_blob_id,
            content_id,
            original_filename,
        ) -> None:
            del self, info_blob_id, content_id, original_filename
            raise RuntimeError("injected reference replacement failure")

        monkeypatch.setattr(
            InfoBlobRepository,
            "add_original_reference",
            reject_replacement_reference,
        )

        with pytest.raises(
            RuntimeError,
            match="injected reference replacement failure",
        ):
            async with _inline_original(
                container,
                payload,
                filename="after.txt",
            ) as original:
                await container.text_processor().process_text(
                    text=text,
                    title="knowledge.txt",
                    embedding_model=embedding_model,
                    group_id=group.id,
                    original=original,
                )

        after = await _original_reference(container.session(), published.id)
        assert after is not None
        assert after[0].content_id == failed_content_id
        assert after[0].original_filename == "before.txt"
        assert (
            await container.session().scalar(
                sa.select(sa.func.count()).select_from(ObjectContents)
            )
            == content_count_before
        )
        failed = await container.session().get(ObjectContents, failed_content_id)
        assert failed is not None
        await container.session().refresh(failed)
        assert failed.reference_count == 1
        assert failed.delete_requested_at is None
        assert (
            await container.info_blob_repo().get_retained_size_of_tenant(
                container.user().tenant_id
            )
            == retained_before
        )


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
