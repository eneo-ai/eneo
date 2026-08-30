from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from hashlib import sha256
from uuid import uuid4

import pytest
import sqlalchemy as sa
from dependency_injector import providers
from sqlalchemy import event

from eneo.database.database import sessionmanager
from eneo.database.tables.ai_models_table import EmbeddingModels
from eneo.database.tables.collections_table import CollectionsTable
from eneo.database.tables.info_blob_chunk_table import InfoBlobChunks
from eneo.database.tables.info_blobs_table import InfoBlobs
from eneo.database.tables.object_content_table import ObjectContents
from eneo.database.tables.spaces_table import Spaces
from eneo.info_blobs.info_blob import (
    InfoBlobAdd,
    InfoBlobOriginalUnavailableError,
    PreparedKnowledgeOriginal,
)
from eneo.info_blobs.info_blob_repo import InfoBlobRepository
from eneo.main.container.container import Container
from eneo.main.exceptions import UnauthorizedException
from eneo.object_content.content import ContentState, StorageKind


async def _bytes(payload: bytes) -> AsyncGenerator[bytes]:
    yield payload


async def _seed_blob(container, *, title: str, state: str = "active") -> InfoBlobs:
    session = container.session()
    user = container.user()
    model = (await session.scalars(sa.select(EmbeddingModels).limit(1))).one()
    space = await session.scalar(
        sa.select(Spaces).where(
            Spaces.tenant_id == user.tenant_id,
            Spaces.user_id == user.id,
        )
    )
    if space is None:
        space = Spaces(
            name=f"original contract {uuid4().hex}",
            tenant_id=user.tenant_id,
            user_id=user.id,
        )
        session.add(space)
        await session.flush()
    group = CollectionsTable(
        name=f"original contract {uuid4().hex}",
        size=0,
        user_id=user.id,
        tenant_id=user.tenant_id,
        embedding_model_id=model.id,
        space_id=space.id,
    )
    session.add(group)
    await session.flush()
    text = f"text for {title}"
    blob = InfoBlobs(
        title=title,
        text=text,
        size=len(text),
        content_hash=sha256(text.encode()).digest(),
        source_id=uuid4(),
        version_state=state,
        user_id=user.id,
        tenant_id=user.tenant_id,
        group_id=group.id,
        embedding_model_id=model.id,
    )
    session.add(blob)
    await session.flush()
    session.add(
        InfoBlobChunks(
            info_blob_id=blob.id,
            tenant_id=user.tenant_id,
            chunk_no=0,
            text=text,
            size=len(text),
            embedding=[0.1, 0.2, 0.3],
        )
    )
    await session.flush()
    return blob


@asynccontextmanager
async def _original(
    container, payload: bytes
) -> AsyncGenerator[PreparedKnowledgeOriginal]:
    async with container.object_content_service().capture_for_target(
        _bytes(payload),
        storage_kind=StorageKind.POSTGRES_INLINE,
        declared_media_type="text/plain",
        verified_media_type="text/plain",
        business_maximum_bytes=100_000,
    ) as captured:
        yield PreparedKnowledgeOriginal(
            job_id=uuid4(),
            original_filename="source.txt",
            policy_revision=1,
            storage_kind=StorageKind.POSTGRES_INLINE,
            captured=captured,
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_public_info_blob_list_and_detail_report_original_availability(
    db_container,
):
    async with db_container() as container:
        available = await _seed_blob(container, title="available")
        unavailable = await _seed_blob(container, title="unavailable")
        available_id = available.id
        unavailable_id = unavailable.id
        async with _original(container, b"exact bytes") as original:
            prepared = await container.info_blob_service()._prepare_original(
                InfoBlobAdd(
                    text=available.text,
                    title=available.title,
                    group_id=available.group_id,
                    tenant_id=available.tenant_id,
                    user_id=available.user_id,
                ),
                original,
            )
            await InfoBlobRepository(container.session()).add_original_reference(
                info_blob_id=available.id,
                content_id=prepared.id,
                original_filename="source.txt",
            )
            content_id = prepared.id

    async with db_container() as container:
        service = container.info_blob_service()
        assert (await service.get_by_id(available_id)).original_available is True
        assert (await service.get_by_id(unavailable_id)).original_available is False
        listed = {blob.id: blob for blob in await service.get_by_user()}
        assert listed[available_id].original_available is True
        assert listed[unavailable_id].original_available is False

        await container.session().execute(
            sa.update(ObjectContents)
            .where(ObjectContents.id == content_id)
            .values(
                state=ContentState.FAILED.value,
                failure_code="backend_corrupt",
            )
        )
        assert (await service.get_by_id(available_id)).original_available is False
        with pytest.raises(InfoBlobOriginalUnavailableError):
            await service.ensure_original_available(available_id)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_original_availability_is_one_query_for_any_number_of_blobs(db_container):
    async with db_container() as container:
        blobs = [await _seed_blob(container, title=f"doc-{i}") for i in range(8)]
        statements: list[str] = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            if "info_blob_content_references" in statement:
                statements.append(statement)

        sync_engine = container.session().bind.sync_engine
        event.listen(sync_engine, "before_cursor_execute", capture)
        try:
            listed = {
                blob.id: blob
                for blob in await container.info_blob_service().get_by_user()
            }
        finally:
            event.remove(sync_engine, "before_cursor_execute", capture)
        assert all(listed[blob.id].original_available is False for blob in blobs)
        assert len(statements) == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_original_availability_uses_one_array_bind_for_duplicate_ids(
    db_container,
):
    async with db_container() as container:
        blobs = [await _seed_blob(container, title=f"array-doc-{i}") for i in range(3)]
        captured: list[tuple[str, object]] = []

        def capture(_conn, _cursor, statement, parameters, _context, _executemany):
            if "info_blob_content_references" in statement:
                captured.append((statement, parameters))

        sync_engine = container.session().bind.sync_engine
        event.listen(sync_engine, "before_cursor_execute", capture)
        try:
            result = await InfoBlobRepository(
                container.session()
            ).get_original_availability(
                [blobs[0].id, blobs[1].id, blobs[0].id, blobs[2].id]
            )
        finally:
            event.remove(sync_engine, "before_cursor_execute", capture)

        assert result == set()
        assert len(captured) == 1
        statement, parameters = captured[0]
        assert "ANY" in statement
        assert isinstance(parameters, (list, tuple))
        assert len(parameters) == 2
        assert len(parameters[0]) == 3


@pytest.mark.integration
@pytest.mark.asyncio
async def test_original_download_reresolves_reference_and_closes_lazy_stream(
    db_container,
):
    async with db_container() as container:
        blob = await _seed_blob(container, title="download")
        user = container.user()
        tenant = container.tenant()
        blob_id = blob.id
        tenant_id = blob.tenant_id
        payload = b"original bytes, not extracted text"
        async with _original(container, payload) as original:
            prepared = await container.info_blob_service()._prepare_original(
                InfoBlobAdd(
                    text=blob.text,
                    title=blob.title,
                    group_id=blob.group_id,
                    tenant_id=blob.tenant_id,
                    user_id=blob.user_id,
                ),
                original,
            )
            await InfoBlobRepository(container.session()).add_original_reference(
                info_blob_id=blob.id,
                content_id=prepared.id,
                original_filename="source.txt",
            )

    async with db_container() as container:
        persisted = await container.session().get(InfoBlobs, blob_id)
        assert persisted is not None
        persisted.title = "renamed knowledge"

    async with db_container():
        async with sessionmanager.session() as session:
            service = Container(
                session=providers.Object(session),
                user=providers.Object(user),
                tenant=providers.Object(tenant),
            ).info_blob_service(
                user=None,
            )
            with pytest.raises(UnauthorizedException):
                await service.get_original_download_no_auth(
                    blob_id,
                    expected_tenant_id=uuid4(),
                )
            reference_queries: list[str] = []

            def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
                if (
                    "FROM info_blobs" in statement
                    or "info_blob_content_references" in statement
                ):
                    reference_queries.append(statement)

            sync_engine = session.bind.sync_engine
            event.listen(sync_engine, "before_cursor_execute", capture)
            try:
                download = await service.get_original_download_no_auth(
                    blob_id,
                    expected_tenant_id=tenant_id,
                )
                assert download.content_length == len(payload)
                assert download.filename == "source.txt"
                assert [chunk async for chunk in download.chunks] == [payload]
                await download.aclose()
                await download.aclose()
            finally:
                event.remove(sync_engine, "before_cursor_execute", capture)

            assert len(reference_queries) == 1

    async with db_container() as container:
        await container.info_blob_service().delete(blob_id)

    async with db_container():
        async with sessionmanager.session() as session:
            service = Container(
                session=providers.Object(session),
                user=providers.Object(user),
                tenant=providers.Object(tenant),
            ).info_blob_service(user=None)
            with pytest.raises(InfoBlobOriginalUnavailableError):
                await service.get_original_download_no_auth(
                    blob_id,
                    expected_tenant_id=tenant_id,
                )
