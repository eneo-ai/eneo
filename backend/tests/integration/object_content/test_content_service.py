import base64
from collections.abc import AsyncIterator
from hashlib import sha256
from typing import TYPE_CHECKING, cast
from uuid import uuid4

import pytest
from botocore.config import Config
from botocore.exceptions import ReadTimeoutError
from botocore.session import get_session
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
    ContentFailureCode,
    ContentIntent,
    ContentReadGrant,
    ContentState,
    ObjectContentIntegrityError,
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


async def _payload_bytes(payload: bytes) -> AsyncIterator[bytes]:
    yield payload


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


def _raw_client(real_store: RealObjectStore) -> "S3Client":
    settings = real_store.settings
    return cast(
        "S3Client",
        get_session().create_client(
            "s3",
            endpoint_url=settings.endpoint_url,
            region_name=settings.region,
            aws_access_key_id=settings.access_key_id.get_secret_value(),
            aws_secret_access_key=settings.secret_access_key.get_secret_value(),
            verify=True,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": settings.addressing_style},
            ),
        ),
    )


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


@pytest.mark.asyncio
@pytest.mark.parametrize("range_header", [None, "bytes=2-5"], ids=("full", "range"))
async def test_service_rejects_replaced_bytes_before_response_and_marks_them_corrupt(
    range_header: str | None,
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
) -> None:
    original = b"abcdefghij"
    replacement = b"0123456789"
    settings = real_object_store.settings
    service = ObjectContentService(
        settings,
        real_object_store.store,
        object_content_database,
    )

    async with capture_content(
        _payload_bytes(original),
        declared_media_type="application/octet-stream",
        verified_media_type="application/octet-stream",
        maximum_size_bytes=len(original),
        spool_memory_bytes=settings.spool_memory_bytes,
        multipart_part_bytes=settings.multipart_part_bytes,
    ) as captured:
        async with object_content_database.session() as session, session.begin():
            tenant_id = (await session.scalars(select(Tenants.id))).one()
            user_id = (await session.scalars(select(Users.id))).one()
            owner = Files(
                name=f"{uuid4().hex}.bin",
                text=None,
                blob=None,
                checksum=sha256(original).hexdigest(),
                size=len(original),
                mimetype="application/octet-stream",
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
                    idempotency_key=uuid4().hex,
                    producer_receipt=f"file:{owner.id}:original:0",
                ),
                content=captured,
            )
            session.add(
                FileContentReferences(
                    file_id=owner.id,
                    content_id=prepared.id,
                    variant="original",
                    ordinal=0,
                )
            )
            await session.flush()
        await service.store_and_verify(content_id=prepared.id, content=captured)

    client = _raw_client(real_object_store)
    try:
        client.put_object(
            Bucket=settings.bucket,
            Key=prepared.object_key,
            Body=replacement,
            ContentLength=len(replacement),
            ContentType="application/octet-stream",
            ChecksumSHA256=base64.b64encode(sha256(replacement).digest()).decode(),
        )
        emitted = bytearray()
        grant = ContentReadGrant(
            content_id=prepared.id,
            tenant_id=tenant_id,
            access_class=ContentAccessClass.PRIVATE_RESOURCE,
        )
        with pytest.raises(ObjectContentIntegrityError):
            async with service.open_content(
                grant,
                range_header=range_header,
            ) as opened:
                async for chunk in opened.chunks:
                    emitted.extend(chunk)
        assert emitted == b""

        async with object_content_database.session() as session, session.begin():
            row = await session.get(ObjectContents, prepared.id)
            assert row is not None
            assert row.state == ContentState.FAILED.value
            assert row.failure_code == ContentFailureCode.REMOTE_CORRUPT.value
    finally:
        await real_object_store.store.delete_and_confirm(prepared.object_key)
        client.close()
