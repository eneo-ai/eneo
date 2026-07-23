from collections.abc import AsyncIterator
from hashlib import sha256

import pytest
from sqlalchemy import delete, select

from eneo.database.database import DatabaseSessionManager
from eneo.database.tables.files_table import Files
from eneo.database.tables.object_content_table import (
    FileContentReferences,
    InlineContentPayloads,
    ObjectContents,
)
from eneo.database.tables.tenant_table import Tenants
from eneo.database.tables.users_table import Users
from eneo.object_content.configuration import ObjectContentCoreSettings
from eneo.object_content.content import (
    ContentAccessClass,
    ContentIntent,
    ContentReadGrant,
    ContentState,
    StorageKind,
    capture_content,
)
from eneo.object_content.content_service import ObjectContentService
from eneo.object_content.reconciliation import ObjectContentReconciler


async def _payload_source(payload: bytes) -> AsyncIterator[bytes]:
    yield payload


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

    async with capture_content(
        _payload_source(payload),
        declared_media_type="text/plain",
        verified_media_type="text/plain",
        maximum_size_bytes=len(payload),
        spool_memory_bytes=len(payload),
        multipart_part_bytes=len(payload),
    ) as captured:
        async with object_content_database.session() as session, session.begin():
            tenant_id = (await session.scalars(select(Tenants.id))).one()
            user_id = (await session.scalars(select(Users.id))).one()
            owner = Files(
                name="inline.txt",
                text=None,
                blob=None,
                checksum=sha256(payload).hexdigest(),
                size=len(payload),
                mimetype="text/plain",
                file_type="text",
                transcription=None,
                tenant_id=tenant_id,
                user_id=user_id,
                parent_file_id=None,
            )
            session.add(owner)
            await session.flush()
            prepared = await service.prepare_in_transaction(
                session,
                intent=ContentIntent(
                    tenant_id=tenant_id,
                    created_by_user_id=user_id,
                    access_class=ContentAccessClass.PRIVATE_RESOURCE,
                    idempotency_key="inline-service-create",
                    producer_receipt=f"file:{owner.id}:original:0",
                ),
                content=captured,
                storage_kind=StorageKind.POSTGRES_INLINE,
            )
            session.add(
                FileContentReferences(
                    file_id=owner.id,
                    content_id=prepared.id,
                    variant="original",
                    ordinal=0,
                )
            )

        assert prepared.state is ContentState.AVAILABLE
        assert prepared.storage_kind is StorageKind.POSTGRES_INLINE

        grant = ContentReadGrant(
            content_id=prepared.id,
            tenant_id=tenant_id,
            access_class=ContentAccessClass.PRIVATE_RESOURCE,
        )
        async with service.open_content(grant, range_header="bytes=9-14") as opened:
            ranged = b"".join([chunk async for chunk in opened.chunks])
        assert ranged == payload[9:15]
        assert opened.content_range == f"bytes 9-14/{len(payload)}"

        async with object_content_database.session() as session, session.begin():
            await session.execute(
                delete(FileContentReferences).where(
                    FileContentReferences.content_id == prepared.id
                )
            )

        result = await ObjectContentReconciler(
            settings,
            object_content_database,
        ).run_once()
        assert result.inline_deleted == 1

        async with object_content_database.session() as session, session.begin():
            control = await session.get(ObjectContents, prepared.id)
            stored_payload = await session.get(InlineContentPayloads, prepared.id)
            assert control is not None
            assert control.state == ContentState.TOMBSTONED.value
            assert control.payload_deleted_at is not None
            assert stored_payload is None
