from collections.abc import AsyncIterator
from hashlib import sha256
from typing import TYPE_CHECKING, cast
from uuid import uuid4

import pytest
from botocore.exceptions import ReadTimeoutError
from sqlalchemy import delete, select

from eneo.database.database import DatabaseSessionManager
from eneo.database.tables.files_table import Files
from eneo.database.tables.object_content_table import (
    FileContentReferences,
    ObjectContents,
)
from eneo.database.tables.tenant_table import Tenants
from eneo.database.tables.users_table import Users
from eneo.object_content.content import (
    ContentAccessClass,
    ContentIntent,
    ContentReadGrant,
    ContentState,
    ObjectContentStateError,
    ObjectContentUnavailableError,
    capture_content,
)
from eneo.object_content.content_service import ObjectContentService
from eneo.object_content.reconciliation import ObjectContentReconciler
from eneo.object_content.s3_object_store import (
    ObjectStoreNotFoundError,
    S3ObjectStore,
)
from tests.integration.object_content.conftest import RealObjectStore

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

_MEBIBYTE = 1024 * 1024


async def _repeated_bytes(
    total: int, chunk_size: int = 64 * 1024
) -> AsyncIterator[bytes]:
    chunk = b"x" * chunk_size
    remaining = total
    while remaining:
        emitted = chunk[:remaining]
        yield emitted
        remaining -= len(emitted)


class _TimeoutBody:
    def read(self, _size: int) -> bytes:
        raise ReadTimeoutError(
            endpoint_url="https://object-content.example.test",
            error=TimeoutError("injected read timeout"),
        )

    def close(self) -> None:
        return None


class _TimeoutReadClient:
    def __init__(self, size_bytes: int) -> None:
        self._size_bytes = size_bytes

    def get_object(self, **_request: object) -> dict[str, object]:
        return {
            "Body": _TimeoutBody(),
            "ContentLength": self._size_bytes,
            "ContentType": "application/octet-stream",
        }


@pytest.mark.asyncio
async def test_service_owns_real_upload_read_and_final_delete_lifecycle(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
) -> None:
    settings = real_object_store.settings
    service = ObjectContentService(
        settings,
        real_object_store.store,
        object_content_database,
    )
    reconciler = ObjectContentReconciler(
        settings,
        real_object_store.store,
        object_content_database,
    )
    size_bytes = 6 * _MEBIBYTE + 17
    idempotency_key = uuid4().hex

    async with capture_content(
        _repeated_bytes(size_bytes),
        declared_media_type="application/octet-stream",
        verified_media_type="application/octet-stream",
        maximum_size_bytes=size_bytes,
        spool_memory_bytes=settings.spool_memory_bytes,
        multipart_part_bytes=settings.multipart_part_bytes,
    ) as captured:
        async with object_content_database.session() as session, session.begin():
            tenant_id = (await session.scalars(select(Tenants.id))).one()
            user_id = (await session.scalars(select(Users.id))).one()
            owner = Files(
                name=f"{idempotency_key}.bin",
                text=None,
                blob=None,
                checksum=captured.sha256.hex(),
                size=captured.size_bytes,
                mimetype=captured.verified_media_type,
                file_type="text",
                transcription=None,
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
            )
            session.add(
                FileContentReferences(
                    file_id=owner_id,
                    content_id=prepared.id,
                    variant="original",
                    ordinal=0,
                )
            )
            await session.flush()

        available = await service.store_and_verify(
            content_id=prepared.id,
            content=captured,
        )
        replay = await service.store_and_verify(
            content_id=prepared.id,
            content=captured,
        )
        assert replay == available
        assert available.sha256 == captured.sha256

        received_digest = sha256()
        received_size = 0
        grant = ContentReadGrant(
            content_id=prepared.id,
            tenant_id=tenant_id,
            access_class=ContentAccessClass.PRIVATE_RESOURCE,
        )
        async with service.open_content(grant) as opened:
            async for chunk in opened.chunks:
                received_digest.update(chunk)
                received_size += len(chunk)
        assert received_size == size_bytes
        assert received_digest.digest() == captured.sha256

        async with service.open_content(grant, range_header="bytes=100-199") as opened:
            ranged = b"".join([chunk async for chunk in opened.chunks])
        assert ranged == b"x" * 100

        timeout_store = S3ObjectStore(
            settings,
            client=cast("S3Client", _TimeoutReadClient(size_bytes)),
        )
        timeout_service = ObjectContentService(
            settings,
            timeout_store,
            object_content_database,
        )
        with pytest.raises(ObjectContentUnavailableError):
            async with timeout_service.open_content(grant) as opened:
                _ = b"".join([chunk async for chunk in opened.chunks])
        async with object_content_database.session() as session, session.begin():
            row = await session.get(ObjectContents, prepared.id)
            assert row is not None
            assert row.state == ContentState.AVAILABLE.value
            assert row.failure_code is None

        with pytest.raises(ObjectContentStateError):
            async with service.open_content(
                ContentReadGrant(
                    content_id=prepared.id,
                    tenant_id=uuid4(),
                    access_class=ContentAccessClass.PRIVATE_RESOURCE,
                )
            ):
                pass

        async with object_content_database.session() as session, session.begin():
            await session.execute(
                delete(FileContentReferences).where(
                    FileContentReferences.file_id == owner_id
                )
            )

    result = await reconciler.run_once()
    assert result.content_processed == 1
    async with object_content_database.session() as session, session.begin():
        row = await session.get(ObjectContents, prepared.id)
        assert row is not None
        assert row.state == ContentState.TOMBSTONED.value
    with pytest.raises(ObjectStoreNotFoundError):
        await real_object_store.store.head(prepared.object_key)
