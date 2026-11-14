from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, event, select
from sqlalchemy.engine import Engine

from eneo.database.database import DatabaseSessionManager
from eneo.database.tables.files_table import Files
from eneo.database.tables.object_content_table import (
    FileContentReferences,
    InlineContentPayloads,
    ObjectContents,
)
from eneo.database.tables.tenant_table import Tenants
from eneo.database.tables.users_table import Users
from eneo.files.file_content_loader import FileContentLoader
from eneo.files.file_repo import FileRepository
from eneo.object_content.configuration import ObjectContentCoreSettings
from eneo.object_content.content import (
    ContentAccessClass,
    ContentIntent,
    ContentReadGrant,
    ContentState,
    ObjectContentStateError,
    StorageKind,
    capture_content,
)
from eneo.object_content.content_repository import PreparedContent
from eneo.object_content.content_service import ObjectContentService
from eneo.object_content.reconciliation import ObjectContentReconciler


async def _payload_source(payload: bytes) -> AsyncIterator[bytes]:
    yield payload


async def _store_inline_file(
    service: ObjectContentService,
    database: DatabaseSessionManager,
    payload: bytes,
    idempotency_key: str,
) -> tuple[UUID, UUID, PreparedContent]:
    """Store one File original inline and reference it; return tenant, file and content."""

    async with capture_content(
        _payload_source(payload),
        declared_media_type="text/plain",
        verified_media_type="text/plain",
        maximum_size_bytes=len(payload),
        spool_memory_bytes=len(payload),
        multipart_part_bytes=len(payload),
    ) as captured:
        async with database.session() as session, session.begin():
            tenant_id = (await session.scalars(select(Tenants.id))).one()
            user_id = (await session.scalars(select(Users.id))).one()
            owner = Files(
                name="inline.txt",
                mimetype="text/plain",
                file_type="text",
                tenant_id=tenant_id,
                user_id=user_id,
                parent_file_id=None,
            )
            session.add(owner)
            await session.flush()
            owner_id = owner.id
            prepared = await service.prepare_in_transaction(
                session,
                intent=ContentIntent(
                    tenant_id=tenant_id,
                    created_by_user_id=user_id,
                    access_class=ContentAccessClass.PRIVATE_RESOURCE,
                    idempotency_key=idempotency_key,
                    producer_receipt=f"file:{owner_id}:original:0",
                ),
                content=captured,
                storage_kind=StorageKind.POSTGRES_INLINE,
            )
            session.add(
                FileContentReferences(
                    file_id=owner_id,
                    content_id=prepared.id,
                    variant="original",
                    ordinal=0,
                )
            )
    return tenant_id, owner_id, prepared


@pytest.mark.asyncio
async def test_inline_create_read_range_and_final_delete_need_no_object_store(
    object_content_database: DatabaseSessionManager,
) -> None:
    payload = b"postgres-inline durable bytes"
    settings = ObjectContentCoreSettings(
        _env_file=None,
        inline_maximum_bytes=len(payload),
        inline_io_chunk_bytes=4,
    )
    service = ObjectContentService(settings, object_content_database)

    tenant_id, owner_id, prepared = await _store_inline_file(
        service, object_content_database, payload, "inline-service-create"
    )

    assert prepared.state is ContentState.AVAILABLE
    assert prepared.storage_kind is StorageKind.POSTGRES_INLINE
    assert service.object_store_configured is False

    # The file layer advertises the inline original as referenceable: the
    # signed-download surface reads it through the same service, so no
    # object store is needed for an assistant to receive it as a URL.
    async with object_content_database.session() as session, session.begin():
        repository = FileRepository(session)
        metadata = await repository.get_by_id(file_id=owner_id)
        loaded = await FileContentLoader(repository, service).load([metadata])
    assert loaded[owner_id].original_available is True

    grant = ContentReadGrant(
        content_id=prepared.id,
        tenant_id=tenant_id,
        access_class=ContentAccessClass.PRIVATE_RESOURCE,
    )
    async with service.open_content(grant, range_header="bytes=9-14") as opened:
        ranged = b"".join([chunk async for chunk in opened.chunks])
    assert ranged == payload[9:15]
    assert opened.content_range == f"bytes 9-14/{len(payload)}"

    with pytest.raises(ObjectContentStateError, match="not available"):
        await service.read_content_bytes(
            [
                ContentReadGrant(
                    content_id=prepared.id,
                    tenant_id=uuid4(),
                    access_class=ContentAccessClass.PRIVATE_RESOURCE,
                )
            ]
        )

    # A second deleted file and a file that stays referenced: the delete must
    # remove exactly the payloads of the deleted ones.
    kept_payload = payload[::-1]
    _, _, kept = await _store_inline_file(
        service, object_content_database, kept_payload, "inline-service-kept"
    )
    _, _, second = await _store_inline_file(
        service, object_content_database, payload, "inline-service-second"
    )
    deleted_ids = [prepared.id, second.id]

    async with object_content_database.session() as session, session.begin():
        await session.execute(
            delete(FileContentReferences).where(
                FileContentReferences.content_id.in_(deleted_ids)
            )
        )

    # Deleting a stored file must not load it: a reconciliation batch holds
    # up to reconciliation_batch_size rows, and each payload can be as large
    # as the inline ceiling.
    statements: list[str] = []

    def record(conn, cursor, statement, *args) -> None:  # noqa: ARG001
        statements.append(statement)

    event.listen(Engine, "before_cursor_execute", record)
    try:
        result = await ObjectContentReconciler(
            settings,
            object_content_database,
        ).run_once()
    finally:
        event.remove(Engine, "before_cursor_execute", record)
    assert result.inline_deleted == 2
    assert any(
        statement.lstrip().upper().startswith("DELETE FROM INLINE_CONTENT_PAYLOADS")
        for statement in statements
    )
    payload_reads = [
        statement
        for statement in statements
        if statement.lstrip().upper().startswith("SELECT")
        and "inline_content_payloads.payload" in statement
    ]
    assert payload_reads == []

    async with object_content_database.session() as session, session.begin():
        for content_id in deleted_ids:
            control = await session.get(ObjectContents, content_id)
            stored_payload = await session.get(InlineContentPayloads, content_id)
            assert control is not None
            assert control.state == ContentState.TOMBSTONED.value
            assert control.payload_deleted_at is not None
            assert stored_payload is None
        kept_control = await session.get(ObjectContents, kept.id)
        kept_stored = await session.get(InlineContentPayloads, kept.id)
        assert kept_control is not None
        assert kept_control.state == ContentState.AVAILABLE.value
        assert kept_stored is not None
        assert bytes(kept_stored.payload) == kept_payload
