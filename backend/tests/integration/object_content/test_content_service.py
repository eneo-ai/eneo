import asyncio
import base64
from collections.abc import AsyncIterator
from datetime import timedelta
from hashlib import sha256
from threading import Event
from typing import TYPE_CHECKING, cast
from uuid import uuid4

import pytest
from botocore.config import Config
from botocore.exceptions import ReadTimeoutError
from botocore.session import get_session
from sqlalchemy import delete, func, select

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
    from mypy_boto3_s3.type_defs import (
        HeadObjectOutputTypeDef,
        HeadObjectRequestTypeDef,
        PutObjectOutputTypeDef,
        PutObjectRequestTypeDef,
    )

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


class _DelayedSingleUploadClient:
    def __init__(self, delegate: "S3Client") -> None:
        self._delegate = delegate
        self.put_finished = Event()
        self.release_put = Event()
        self.head_started = Event()
        self.release_head = Event()

    def put_object(self, **request: object) -> "PutObjectOutputTypeDef":
        result = self._delegate.put_object(**cast("PutObjectRequestTypeDef", request))
        self.put_finished.set()
        if not self.release_put.wait(timeout=10):
            raise TimeoutError("test did not release the completed PUT")
        return result

    def head_object(self, **request: object) -> "HeadObjectOutputTypeDef":
        self.head_started.set()
        if not self.release_head.wait(timeout=10):
            raise TimeoutError("test did not release the verification HEAD")
        return self._delegate.head_object(**cast("HeadObjectRequestTypeDef", request))


async def _wait_for(event: Event) -> None:
    assert await asyncio.to_thread(event.wait, 10)


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
async def test_single_upload_renews_before_head_and_cannot_be_reconciled(
    monkeypatch: pytest.MonkeyPatch,
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
) -> None:
    clock = [0.0]
    monkeypatch.setattr(
        "eneo.object_content.content_service.monotonic",
        lambda: clock[0],
    )
    monkeypatch.setattr(
        "eneo.object_content.lease.monotonic",
        lambda: clock[0],
    )
    raw_client = _raw_client(real_object_store)
    delayed_client = _DelayedSingleUploadClient(raw_client)
    delayed_store = S3ObjectStore(
        real_object_store.settings,
        client=cast("S3Client", delayed_client),
    )
    service = ObjectContentService(
        real_object_store.settings,
        delayed_store,
        object_content_database,
    )
    payload = b"lease-fenced-single-upload"

    try:
        async with capture_content(
            _payload_bytes(payload),
            declared_media_type="application/octet-stream",
            verified_media_type="application/octet-stream",
            maximum_size_bytes=len(payload),
            spool_memory_bytes=real_object_store.settings.spool_memory_bytes,
            multipart_part_bytes=real_object_store.settings.multipart_part_bytes,
        ) as captured:
            async with object_content_database.session() as session, session.begin():
                tenant_id = (await session.scalars(select(Tenants.id))).one()
                user_id = (await session.scalars(select(Users.id))).one()
                owner = Files(
                    name=f"{uuid4().hex}.bin",
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

            upload = asyncio.create_task(
                service.store_and_verify(
                    content_id=prepared.id,
                    content=captured,
                )
            )
            await _wait_for(delayed_client.put_finished)
            async with object_content_database.session() as session, session.begin():
                now = await session.scalar(select(func.now()))
                assert now is not None
                row = await session.get(ObjectContents, prepared.id)
                assert row is not None
                row.lease_until = now - timedelta(seconds=1)
                row.updated_at = now - timedelta(
                    seconds=real_object_store.settings.pending_stale_seconds + 1
                )
            clock[0] = (
                real_object_store.settings.reconciliation_lease_seconds
                - real_object_store.settings.sdk_request_budget_seconds
                + 1
            )
            delayed_client.release_put.set()
            await _wait_for(delayed_client.head_started)

            try:
                concurrent = await ObjectContentReconciler(
                    real_object_store.settings,
                    real_object_store.store,
                    object_content_database,
                ).run_once()
            finally:
                delayed_client.release_head.set()
            available = await upload

            assert concurrent.content_processed == 0
            assert available.content_id == prepared.id
            async with object_content_database.session() as session, session.begin():
                row = await session.get(ObjectContents, prepared.id)
                assert row is not None
                assert row.state == ContentState.AVAILABLE.value
    finally:
        delayed_client.release_put.set()
        delayed_client.release_head.set()
        if "prepared" in locals():
            await real_object_store.store.delete_and_confirm(prepared.object_key)
        raw_client.close()


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
