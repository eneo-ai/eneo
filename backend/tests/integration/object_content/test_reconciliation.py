import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from threading import Event
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from botocore.config import Config
from botocore.session import get_session
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.sql.base import Executable

from eneo.database.database import DatabaseSessionManager
from eneo.database.tables.files_table import Files
from eneo.database.tables.object_content_table import (
    FileContentReferences,
    ObjectContentHolds,
    ObjectContentMultipartCandidates,
    ObjectContentOrphanCandidates,
    ObjectContentReconciliationState,
    ObjectContents,
    ObjectStoreObjects,
)
from eneo.database.tables.tenant_table import Tenants
from eneo.database.tables.users_table import Users
from eneo.object_content.configuration import ObjectContentSettings
from eneo.object_content.content import (
    ContentAccessClass,
    ContentFailureCode,
    ContentIntent,
    ContentState,
    ObjectContentBusyError,
    StorageKind,
    capture_content,
)
from eneo.object_content.content_repository import ObjectContentRepository
from eneo.object_content.content_service import ObjectContentService
from eneo.object_content.reconciliation import ObjectContentReconciler
from eneo.object_content.reconciliation_repository import (
    ObjectContentReconciliationRepository,
    PublicationReservation,
)
from eneo.object_content.s3_object_store import (
    ObjectStoreIntegrityError,
    ObjectStoreNotFoundError,
    ObjectStoreUnavailableError,
    S3ObjectStore,
    new_object_key,
)
from tests.integration.object_content.conftest import RealObjectStore

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client
    from mypy_boto3_s3.type_defs import (
        AbortMultipartUploadOutputTypeDef,
        AbortMultipartUploadRequestTypeDef,
        DeleteObjectOutputTypeDef,
        DeleteObjectRequestTypeDef,
        HeadObjectOutputTypeDef,
        HeadObjectRequestTypeDef,
        ListMultipartUploadsOutputTypeDef,
        ListMultipartUploadsRequestTypeDef,
        ListObjectsV2OutputTypeDef,
        ListObjectsV2RequestTypeDef,
    )


@dataclass(frozen=True, slots=True)
class _PendingContent:
    content_id: UUID
    file_id: UUID
    object_key: str
    payload: bytes


class _DelayedDeleteClient:
    def __init__(self, delegate: "S3Client") -> None:
        self._delegate = delegate
        self.delete_finished = Event()
        self.release_delete = Event()
        self.head_started = Event()
        self.release_head = Event()

    def delete_object(self, **request: object) -> "DeleteObjectOutputTypeDef":
        result = self._delegate.delete_object(
            **cast("DeleteObjectRequestTypeDef", request)
        )
        self.delete_finished.set()
        if not self.release_delete.wait(timeout=10):
            raise TimeoutError("test did not release the completed DELETE")
        return result

    def head_object(self, **request: object) -> "HeadObjectOutputTypeDef":
        self.head_started.set()
        if not self.release_head.wait(timeout=10):
            raise TimeoutError("test did not release the visibility HEAD")
        return self._delegate.head_object(**cast("HeadObjectRequestTypeDef", request))

    def list_objects_v2(self, **request: object) -> "ListObjectsV2OutputTypeDef":
        return self._delegate.list_objects_v2(
            **cast("ListObjectsV2RequestTypeDef", request)
        )

    def list_multipart_uploads(
        self,
        **request: object,
    ) -> "ListMultipartUploadsOutputTypeDef":
        return self._delegate.list_multipart_uploads(
            **cast("ListMultipartUploadsRequestTypeDef", request)
        )


class _DelayedMultipartAbortClient:
    def __init__(self, delegate: "S3Client") -> None:
        self._delegate = delegate
        self.abort_finished = Event()
        self.release_abort = Event()

    def abort_multipart_upload(
        self,
        **request: object,
    ) -> "AbortMultipartUploadOutputTypeDef":
        result = self._delegate.abort_multipart_upload(
            **cast("AbortMultipartUploadRequestTypeDef", request)
        )
        self.abort_finished.set()
        if not self.release_abort.wait(timeout=10):
            raise TimeoutError("test did not release the completed multipart abort")
        return result

    def list_objects_v2(self, **request: object) -> "ListObjectsV2OutputTypeDef":
        return self._delegate.list_objects_v2(
            **cast("ListObjectsV2RequestTypeDef", request)
        )

    def list_multipart_uploads(
        self,
        **request: object,
    ) -> "ListMultipartUploadsOutputTypeDef":
        return self._delegate.list_multipart_uploads(
            **cast("ListMultipartUploadsRequestTypeDef", request)
        )


class _TruncatedObjectInventoryClient:
    def list_objects_v2(self, **_request: object) -> "ListObjectsV2OutputTypeDef":
        return cast(
            "ListObjectsV2OutputTypeDef",
            {
                "IsTruncated": True,
                "Contents": [],
            },
        )

    def list_multipart_uploads(
        self,
        **_request: object,
    ) -> "ListMultipartUploadsOutputTypeDef":
        return cast(
            "ListMultipartUploadsOutputTypeDef",
            {
                "IsTruncated": False,
                "Uploads": [],
            },
        )


async def _wait_for(event: Event) -> None:
    assert await asyncio.to_thread(event.wait, 10)


async def _source(payload: bytes) -> AsyncIterator[bytes]:
    for offset in range(0, len(payload), 31_337):
        yield payload[offset : offset + 31_337]


async def _create_pending(
    database: DatabaseSessionManager,
    real_store: RealObjectStore,
    *,
    upload_remote: bool,
    payload: bytes | None = None,
) -> _PendingContent:
    async with database.session() as session, session.begin():
        tenant_id = (await session.scalars(select(Tenants.id))).one()
        user_id = (await session.scalars(select(Users.id))).one()
        token = uuid4().hex
        resolved_payload = (
            f"reconciliation-{token}".encode() if payload is None else payload
        )
        digest = sha256(resolved_payload).digest()
        owner = Files(
            name=f"{token}.txt",
            mimetype="application/octet-stream",
            file_type="text",
            tenant_id=tenant_id,
            owner_type="user",
            owner_user_id=user_id,
            parent_file_id=None,
        )
        object_key = new_object_key(real_store.settings)
        content = ObjectContents(
            tenant_id=tenant_id,
            created_by_user_id=user_id,
            storage_kind=StorageKind.OBJECT_STORE.value,
            state=ContentState.PENDING.value,
            access_class="private_resource",
            sha256=digest,
            size_bytes=len(resolved_payload),
            declared_media_type="application/octet-stream",
            verified_media_type="application/octet-stream",
            idempotency_key=token,
            request_fingerprint=digest,
        )
        session.add_all([owner, content])
        await session.flush()
        descriptor = ObjectStoreObjects()
        descriptor.content_id = content.id
        descriptor.storage_kind = StorageKind.OBJECT_STORE.value
        descriptor.object_key = object_key
        descriptor.verification_chunk_size_bytes = max(1, len(resolved_payload))
        descriptor.verification_chunk_sha256 = digest
        session.add(descriptor)
        session.add(
            FileContentReferences(
                file_id=owner.id,
                content_id=content.id,
                variant="original",
                ordinal=0,
            )
        )
        await session.flush()
        pending = _PendingContent(
            content_id=content.id,
            file_id=owner.id,
            object_key=object_key,
            payload=resolved_payload,
        )

    if upload_remote:
        settings = real_store.settings
        async with capture_content(
            _source(pending.payload),
            declared_media_type="application/octet-stream",
            verified_media_type="application/octet-stream",
            maximum_size_bytes=len(pending.payload),
            spool_memory_bytes=settings.spool_memory_bytes,
            multipart_part_bytes=settings.multipart_part_bytes,
        ) as captured:
            await real_store.store.upload(pending.object_key, captured)

    async with database.session() as session, session.begin():
        await session.execute(
            text(
                "UPDATE object_contents "
                "SET updated_at = now() - interval '10 seconds' "
                "WHERE id = :content_id"
            ),
            {"content_id": pending.content_id},
        )
    return pending


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


def _reconciler(
    settings: ObjectContentSettings,
    store: S3ObjectStore,
    database: DatabaseSessionManager,
) -> ObjectContentReconciler:
    return ObjectContentReconciler(
        settings,
        database,
        object_store_settings=settings,
        object_store=store,
    )


@pytest.mark.asyncio
async def test_reconciler_promotes_ambiguous_upload_fails_missing_and_tombstones(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
) -> None:
    complete = await _create_pending(
        object_content_database,
        real_object_store,
        upload_remote=True,
    )
    missing = await _create_pending(
        object_content_database,
        real_object_store,
        upload_remote=False,
    )
    reconciler = _reconciler(
        real_object_store.settings,
        real_object_store.store,
        object_content_database,
    )

    first_result = await reconciler.run_once()
    assert first_result.content_processed == 2
    async with object_content_database.session() as session, session.begin():
        complete_row = await session.get(ObjectContents, complete.content_id)
        missing_row = await session.get(ObjectContents, missing.content_id)
        assert complete_row is not None
        assert missing_row is not None
        assert complete_row.state == ContentState.AVAILABLE.value
        assert complete_row.sha256 == sha256(complete.payload).digest()
        assert missing_row.state == ContentState.FAILED.value
        assert missing_row.failure_code == ContentFailureCode.UPLOAD_REJECTED.value

        await session.execute(
            delete(FileContentReferences).where(
                FileContentReferences.file_id == complete.file_id
            )
        )

    second_result = await reconciler.run_once()
    assert second_result.content_processed >= 1
    async with object_content_database.session() as session, session.begin():
        complete_row = await session.get(ObjectContents, complete.content_id)
        assert complete_row is not None
        assert complete_row.state == ContentState.TOMBSTONED.value
        assert complete_row.payload_deleted_at is not None
        assert complete_row.tombstone_purge_after is None
    with pytest.raises(ObjectStoreNotFoundError):
        await real_object_store.store.head(complete.object_key)


@pytest.mark.asyncio
async def test_reconciliation_preserves_bytes_behind_an_active_hold(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
) -> None:
    pending = await _create_pending(
        object_content_database,
        real_object_store,
        upload_remote=True,
    )
    reconciler = _reconciler(
        real_object_store.settings,
        real_object_store.store,
        object_content_database,
    )
    try:
        await reconciler.run_once()

        async with object_content_database.session() as session, session.begin():
            content = await session.get(ObjectContents, pending.content_id)
            actor_user_id = (await session.scalars(select(Users.id))).one()
            assert content is not None
            assert content.state == ContentState.AVAILABLE.value
            hold_id = await ObjectContentRepository(session).apply_hold(
                tenant_id=content.tenant_id,
                content_id=content.id,
                kind="legal",
                reason="reconciliation must preserve held remote bytes",
                actor_user_id=actor_user_id,
                expires_at=None,
            )
            await session.execute(
                delete(FileContentReferences).where(
                    FileContentReferences.file_id == pending.file_id
                )
            )

        with pytest.raises(DBAPIError, match="cannot be hard-deleted"):
            async with object_content_database.session() as session, session.begin():
                await session.execute(
                    delete(ObjectContentHolds).where(ObjectContentHolds.id == hold_id)
                )

        result = await reconciler.run_once()
        assert result.content_processed == 0
        async with object_content_database.session() as session, session.begin():
            content = await session.get(ObjectContents, pending.content_id)
            assert content is not None
            assert content.state == ContentState.RETAINED.value
        await real_object_store.store.head(pending.object_key)
    finally:
        await real_object_store.store.delete_and_confirm(pending.object_key)


@pytest.mark.asyncio
async def test_completed_inventory_reports_missing_retained_bytes_once(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
) -> None:
    pending = await _create_pending(
        object_content_database,
        real_object_store,
        upload_remote=True,
    )
    reconciler = _reconciler(
        real_object_store.settings,
        real_object_store.store,
        object_content_database,
    )
    await reconciler.run_once()

    async with object_content_database.session() as session, session.begin():
        content = await session.get(ObjectContents, pending.content_id)
        actor_user_id = (await session.scalars(select(Users.id))).one()
        assert content is not None
        await ObjectContentRepository(session).apply_hold(
            tenant_id=content.tenant_id,
            content_id=content.id,
            kind="legal",
            reason="retained bytes must remain under integrity monitoring",
            actor_user_id=actor_user_id,
            expires_at=None,
        )
        await session.execute(
            delete(FileContentReferences).where(
                FileContentReferences.file_id == pending.file_id
            )
        )

    await real_object_store.store.delete_and_confirm(pending.object_key)

    observation_boundary = await reconciler.run_once()
    first_missing = await reconciler.run_once()
    repeated_missing = await reconciler.run_once()
    facts = await reconciler.health_facts()

    assert observation_boundary.missing_objects == 0
    assert first_missing.missing_objects == 1
    assert repeated_missing.missing_objects == 0
    assert facts.integrity_failures >= 1
    async with object_content_database.session() as session, session.begin():
        content = await session.get(ObjectContents, pending.content_id)
        assert content is not None
        assert content.state == ContentState.RETAINED.value
        assert content.failure_code == ContentFailureCode.BACKEND_MISSING.value


@pytest.mark.asyncio
async def test_multipart_outage_preserves_committed_object_inventory_result(
    monkeypatch: pytest.MonkeyPatch,
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
) -> None:
    pending = await _create_pending(
        object_content_database,
        real_object_store,
        upload_remote=True,
    )
    reconciler = _reconciler(
        real_object_store.settings,
        real_object_store.store,
        object_content_database,
    )
    await reconciler.run_once()

    async with object_content_database.session() as session, session.begin():
        content = await session.get(ObjectContents, pending.content_id)
        actor_user_id = (await session.scalars(select(Users.id))).one()
        assert content is not None
        await ObjectContentRepository(session).apply_hold(
            tenant_id=content.tenant_id,
            content_id=content.id,
            kind="legal",
            reason="retain missing bytes for late-outage reporting",
            actor_user_id=actor_user_id,
            expires_at=None,
        )
        await session.execute(
            delete(FileContentReferences).where(
                FileContentReferences.file_id == pending.file_id
            )
        )

    await real_object_store.store.delete_and_confirm(pending.object_key)
    observation_boundary = await reconciler.run_once()
    assert observation_boundary.missing_objects == 0

    monkeypatch.setattr(
        real_object_store.store,
        "list_multipart_page",
        AsyncMock(
            side_effect=ObjectStoreUnavailableError("multipart inventory unavailable")
        ),
    )
    result = await reconciler.run_once()

    assert result.object_cycle_completed is True
    assert result.missing_objects == 1
    assert result.multipart_aborted == 0
    assert result.orphan_objects_deleted == 0
    async with object_content_database.session() as session, session.begin():
        content = await session.get(ObjectContents, pending.content_id)
        assert content is not None
        assert content.failure_code == ContentFailureCode.BACKEND_MISSING.value


@pytest.mark.asyncio
async def test_invalid_truncated_inventory_cannot_complete_a_cycle(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
) -> None:
    pending = await _create_pending(
        object_content_database,
        real_object_store,
        upload_remote=True,
    )
    healthy_reconciler = _reconciler(
        real_object_store.settings,
        real_object_store.store,
        object_content_database,
    )
    try:
        await healthy_reconciler.run_once()
        async with object_content_database.session() as session, session.begin():
            state = await session.get(ObjectContentReconciliationState, 1)
            assert state is not None
            completed_cycles = state.object_completed_cycles

        invalid_store = S3ObjectStore(
            real_object_store.settings,
            client=cast("S3Client", _TruncatedObjectInventoryClient()),
        )
        with pytest.raises(ObjectStoreIntegrityError, match="pagination"):
            await _reconciler(
                real_object_store.settings,
                invalid_store,
                object_content_database,
            ).run_once()

        async with object_content_database.session() as session, session.begin():
            state = await session.get(ObjectContentReconciliationState, 1)
            content = await session.get(ObjectContents, pending.content_id)
            assert state is not None
            assert content is not None
            assert state.object_completed_cycles == completed_cycles
            assert content.state == ContentState.AVAILABLE.value
    finally:
        await real_object_store.store.delete_and_confirm(pending.object_key)


@pytest.mark.asyncio
async def test_reconciler_reclaims_a_stale_delete_after_worker_crash(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
) -> None:
    pending = await _create_pending(
        object_content_database,
        real_object_store,
        upload_remote=True,
    )
    async with object_content_database.session() as session, session.begin():
        await session.execute(
            delete(FileContentReferences).where(
                FileContentReferences.file_id == pending.file_id
            )
        )
        now = await session.scalar(select(func.now()))
        assert now is not None
        row = await session.get(ObjectContents, pending.content_id)
        assert row is not None
        row.state = ContentState.DELETE_PENDING.value
        row.delete_requested_at = now
        row.next_attempt_at = None
        row.lease_owner = "crashed-delete-worker"
        row.lease_until = now - timedelta(seconds=1)
        row.updated_at = now - timedelta(
            seconds=real_object_store.settings.pending_stale_seconds + 1
        )

    result = await _reconciler(
        real_object_store.settings,
        real_object_store.store,
        object_content_database,
    ).run_once()

    assert result.content_processed == 1
    async with object_content_database.session() as session, session.begin():
        row = await session.get(ObjectContents, pending.content_id)
        assert row is not None
        assert row.state == ContentState.TOMBSTONED.value
        assert row.payload_deleted_at is not None
    with pytest.raises(ObjectStoreNotFoundError):
        await real_object_store.store.head(pending.object_key)


@pytest.mark.asyncio
async def test_delete_renews_before_head_and_cannot_be_reconciled_twice(
    monkeypatch: pytest.MonkeyPatch,
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
) -> None:
    clock = [0.0]
    monkeypatch.setattr(
        "eneo.object_content.reconciliation.monotonic",
        lambda: clock[0],
    )
    monkeypatch.setattr(
        "eneo.object_content.lease.monotonic",
        lambda: clock[0],
    )
    pending = await _create_pending(
        object_content_database,
        real_object_store,
        upload_remote=True,
    )
    async with object_content_database.session() as session, session.begin():
        await session.execute(
            delete(FileContentReferences).where(
                FileContentReferences.file_id == pending.file_id
            )
        )
        now = await session.scalar(select(func.now()))
        assert now is not None
        row = await session.get(ObjectContents, pending.content_id)
        assert row is not None
        row.state = ContentState.DELETE_PENDING.value
        row.delete_requested_at = now
        row.next_attempt_at = now
        row.lease_owner = None
        row.lease_until = None

    raw_client = _raw_client(real_object_store)
    delayed_client = _DelayedDeleteClient(raw_client)
    delayed_store = S3ObjectStore(
        real_object_store.settings,
        client=cast("S3Client", delayed_client),
    )
    first_run = asyncio.create_task(
        _reconciler(
            real_object_store.settings,
            delayed_store,
            object_content_database,
        ).run_once()
    )
    try:
        await _wait_for(delayed_client.delete_finished)
        async with object_content_database.session() as session, session.begin():
            now = await session.scalar(select(func.now()))
            assert now is not None
            row = await session.get(ObjectContents, pending.content_id)
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
        delayed_client.release_delete.set()
        await _wait_for(delayed_client.head_started)

        concurrent = await _reconciler(
            real_object_store.settings,
            real_object_store.store,
            object_content_database,
        ).run_once()
    finally:
        delayed_client.release_delete.set()
        delayed_client.release_head.set()
    first = await first_run
    raw_client.close()

    assert first.content_processed == 1
    assert concurrent.content_processed == 0
    async with object_content_database.session() as session, session.begin():
        row = await session.get(ObjectContents, pending.content_id)
        assert row is not None
        assert row.state == ContentState.TOMBSTONED.value
        assert row.payload_deleted_at is not None


@pytest.mark.asyncio
async def test_reconciler_converges_multipart_crashes_before_and_after_completion(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
) -> None:
    settings = real_object_store.settings
    mebibyte = 1024 * 1024
    completed = await _create_pending(
        object_content_database,
        real_object_store,
        upload_remote=False,
        payload=b"c" * (6 * mebibyte + 17),
    )
    incomplete = await _create_pending(
        object_content_database,
        real_object_store,
        upload_remote=False,
    )
    client = _raw_client(real_object_store)
    incomplete_upload_id = client.create_multipart_upload(
        Bucket=settings.bucket,
        Key=incomplete.object_key,
        ContentType="application/octet-stream",
        ChecksumAlgorithm="SHA256",
        ChecksumType="COMPOSITE",
    )["UploadId"]

    async def record_completed_upload(upload_id: str) -> None:
        async with object_content_database.session() as session, session.begin():
            descriptor = await session.get(ObjectStoreObjects, completed.content_id)
            assert descriptor is not None
            descriptor.multipart_upload_id = upload_id
            descriptor.multipart_initiated_at = await session.scalar(select(func.now()))

    try:
        async with object_content_database.session() as session, session.begin():
            descriptor = await session.get(ObjectStoreObjects, incomplete.content_id)
            assert descriptor is not None
            descriptor.multipart_upload_id = incomplete_upload_id
            descriptor.multipart_initiated_at = datetime.now(UTC)

        async with capture_content(
            _source(completed.payload),
            declared_media_type="application/octet-stream",
            verified_media_type="application/octet-stream",
            maximum_size_bytes=len(completed.payload),
            spool_memory_bytes=settings.spool_memory_bytes,
            multipart_part_bytes=settings.multipart_part_bytes,
        ) as captured:
            await real_object_store.store.upload(
                completed.object_key,
                captured,
                multipart_started=record_completed_upload,
            )

        async with object_content_database.session() as session, session.begin():
            await session.execute(
                text(
                    "UPDATE object_contents "
                    "SET updated_at = now() - interval '10 seconds' "
                    "WHERE id IN (:completed_id, :incomplete_id)"
                ),
                {
                    "completed_id": completed.content_id,
                    "incomplete_id": incomplete.content_id,
                },
            )

        result = await _reconciler(
            settings,
            real_object_store.store,
            object_content_database,
        ).run_once()
        assert result.content_processed == 2

        async with object_content_database.session() as session, session.begin():
            completed_row = await session.get(ObjectContents, completed.content_id)
            incomplete_row = await session.get(ObjectContents, incomplete.content_id)
            completed_descriptor = await session.get(
                ObjectStoreObjects, completed.content_id
            )
            incomplete_descriptor = await session.get(
                ObjectStoreObjects, incomplete.content_id
            )
            assert completed_row is not None
            assert incomplete_row is not None
            assert completed_descriptor is not None
            assert incomplete_descriptor is not None
            assert completed_row.state == ContentState.AVAILABLE.value
            assert completed_descriptor.multipart_upload_id is None
            assert incomplete_row.state == ContentState.FAILED.value
            assert (
                incomplete_row.failure_code == ContentFailureCode.UPLOAD_REJECTED.value
            )
            assert incomplete_descriptor.multipart_upload_id is None
    finally:
        await real_object_store.store.abort_multipart(
            incomplete.object_key,
            incomplete_upload_id,
        )
        await real_object_store.store.delete_and_confirm(completed.object_key)
        client.close()


@pytest.mark.asyncio
async def test_multipart_abort_rechecks_and_fences_a_stale_uploader(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
) -> None:
    pending = await _create_pending(
        object_content_database,
        real_object_store,
        upload_remote=False,
    )
    uploader = "stale-uploader"
    aborter = "multipart-aborter"
    upload_id = "recorded-incomplete-upload"
    async with object_content_database.session() as session, session.begin():
        now = await session.scalar(select(func.now()))
        assert now is not None
        content = await session.get(ObjectContents, pending.content_id)
        descriptor = await session.get(ObjectStoreObjects, pending.content_id)
        assert content is not None
        assert descriptor is not None
        descriptor.multipart_upload_id = upload_id
        descriptor.multipart_initiated_at = now - timedelta(minutes=5)
        content.lease_owner = uploader
        content.lease_until = now - timedelta(seconds=1)
        session.add(
            ObjectContentMultipartCandidates(
                object_key=pending.object_key,
                upload_id=upload_id,
                observed_cycle_id=uuid4(),
                eligible_after=now - timedelta(minutes=1),
                last_observed_at=now,
                completed_observations=2,
            )
        )

    async with object_content_database.session() as session, session.begin():
        leases = await ObjectContentReconciliationRepository(
            session
        ).claim_multipart_aborts(
            lease_owner=aborter,
            lease_seconds=300,
            limit=1,
        )
    assert len(leases) == 1

    # The old uploader can renew between candidate selection and confirmation.
    async with object_content_database.session() as session, session.begin():
        await ObjectContentRepository(session).renew_pending_lease(
            content_id=pending.content_id,
            lease_owner=uploader,
            lease_seconds=300,
        )
    async with object_content_database.session() as session, session.begin():
        confirmed = await ObjectContentReconciliationRepository(
            session
        ).confirm_multipart_abort_lease(
            lease=leases[0],
            lease_owner=aborter,
            lease_seconds=300,
        )
        candidate = await session.get(
            ObjectContentMultipartCandidates,
            (pending.object_key, upload_id),
        )
        assert candidate is not None
        assert candidate.lease_owner is None
    assert confirmed is False

    # Once the upload lease expires, confirmation takes a bounded content-row
    # fence so the old uploader cannot resume while remote abort is in flight.
    async with object_content_database.session() as session, session.begin():
        now = await session.scalar(select(func.now()))
        assert now is not None
        content = await session.get(ObjectContents, pending.content_id)
        assert content is not None
        content.lease_until = now - timedelta(seconds=1)
    async with object_content_database.session() as session, session.begin():
        leases = await ObjectContentReconciliationRepository(
            session
        ).claim_multipart_aborts(
            lease_owner=aborter,
            lease_seconds=300,
            limit=1,
        )
        assert len(leases) == 1
    async with object_content_database.session() as session, session.begin():
        confirmed = await ObjectContentReconciliationRepository(
            session
        ).confirm_multipart_abort_lease(
            lease=leases[0],
            lease_owner=aborter,
            lease_seconds=300,
        )
        content = await session.get(ObjectContents, pending.content_id)
        assert content is not None
        assert content.lease_owner == aborter
    assert confirmed is True

    with pytest.raises(ObjectContentBusyError, match="lease changed"):
        async with object_content_database.session() as session, session.begin():
            await ObjectContentRepository(session).renew_pending_lease(
                content_id=pending.content_id,
                lease_owner=uploader,
                lease_seconds=300,
            )

    async with object_content_database.session() as session, session.begin():
        await ObjectContentReconciliationRepository(session).release_multipart_abort(
            lease=leases[0],
            lease_owner=aborter,
        )
        content = await session.get(ObjectContents, pending.content_id)
        assert content is not None
        assert content.lease_owner is None
        assert content.lease_until is None


@pytest.mark.asyncio
async def test_slow_abort_renews_only_the_lease_confirmed_for_failed_content(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
) -> None:
    settings = ObjectContentSettings.model_validate(
        real_object_store.settings.model_dump()
        | {
            "connect_timeout_seconds": 0.01,
            "read_timeout_seconds": 0.01,
            "sdk_max_attempts": 1,
            "reconciliation_lease_seconds": 6,
        },
    )
    failed = await _create_pending(
        object_content_database,
        real_object_store,
        upload_remote=False,
    )
    raw_client = _raw_client(real_object_store)
    created = raw_client.create_multipart_upload(
        Bucket=settings.bucket,
        Key=failed.object_key,
        ContentType="application/octet-stream",
        ChecksumAlgorithm="SHA256",
        ChecksumType="COMPOSITE",
    )
    upload_id = created["UploadId"]
    delayed_client = _DelayedMultipartAbortClient(raw_client)
    delayed_store = S3ObjectStore(
        settings,
        client=cast("S3Client", delayed_client),
    )

    async with object_content_database.session() as session, session.begin():
        now = await session.scalar(select(func.now()))
        assert now is not None
        content = await session.get(ObjectContents, failed.content_id)
        descriptor = await session.get(ObjectStoreObjects, failed.content_id)
        assert content is not None
        assert descriptor is not None
        content.state = ContentState.FAILED.value
        content.failure_code = ContentFailureCode.UPLOAD_REJECTED.value
        descriptor.multipart_upload_id = upload_id
        descriptor.multipart_initiated_at = now - timedelta(minutes=5)
        content.lease_owner = None
        content.lease_until = None
        session.add(
            ObjectContentMultipartCandidates(
                object_key=failed.object_key,
                upload_id=upload_id,
                observed_cycle_id=uuid4(),
                eligible_after=now - timedelta(minutes=1),
                last_observed_at=now,
                completed_observations=2,
            )
        )

    running = asyncio.create_task(
        _reconciler(
            settings,
            delayed_store,
            object_content_database,
        ).run_once()
    )
    try:
        await _wait_for(delayed_client.abort_finished)
        await asyncio.sleep(settings.reconciliation_lease_seconds / 2 + 0.1)
        delayed_client.release_abort.set()
        result = await running

        assert result.multipart_aborted == 1
        async with object_content_database.session() as session, session.begin():
            candidate = await session.get(
                ObjectContentMultipartCandidates,
                (failed.object_key, upload_id),
            )
            content = await session.get(ObjectContents, failed.content_id)
            descriptor = await session.get(ObjectStoreObjects, failed.content_id)
            assert candidate is None
            assert content is not None
            assert descriptor is not None
            assert content.state == ContentState.FAILED.value
            assert descriptor.multipart_upload_id is None
    finally:
        delayed_client.release_abort.set()
        if not running.done():
            await running
        await real_object_store.store.abort_multipart(failed.object_key, upload_id)
        raw_client.close()


@pytest.mark.asyncio
async def test_active_publication_reservation_wins_orphan_delete_race(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
) -> None:
    settings = real_object_store.settings
    payload = b"verified-publication-race"
    content_service = ObjectContentService(
        settings,
        object_content_database,
        object_store_settings=settings,
        object_store=real_object_store.store,
    )
    object_key: str | None = None

    try:
        async with capture_content(
            _source(payload),
            declared_media_type="application/octet-stream",
            verified_media_type="application/octet-stream",
            maximum_size_bytes=len(payload),
            spool_memory_bytes=settings.spool_memory_bytes,
            multipart_part_bytes=settings.multipart_part_bytes,
        ) as captured:
            async with content_service.upload_for_publication(
                (captured,)
            ) as publication:
                object_key = publication.uploads[0].object_key
                async with (
                    object_content_database.session() as session,
                    session.begin(),
                ):
                    candidate = await session.get(
                        ObjectContentOrphanCandidates,
                        object_key,
                        with_for_update=True,
                    )
                    assert candidate is not None
                    assert candidate.lease_owner == publication.lease_owner
                    candidate.eligible_after = datetime.now(UTC) - timedelta(minutes=1)
                    candidate.last_observed_at = datetime.now(UTC)
                    candidate.completed_observations = 2

                async with (
                    object_content_database.session() as session,
                    session.begin(),
                ):
                    claimed = await ObjectContentReconciliationRepository(
                        session
                    ).claim_orphan_deletes(
                        lease_owner="competing-reconciler",
                        lease_seconds=settings.reconciliation_lease_seconds,
                        limit=1,
                    )
                    assert claimed == ()

                async with (
                    object_content_database.session() as session,
                    session.begin(),
                ):
                    tenant_id = (await session.scalars(select(Tenants.id))).one()
                    user_id = (await session.scalars(select(Users.id))).one()
                    owner = Files(
                        name=f"publication-race-{uuid4().hex}.bin",
                        mimetype="application/octet-stream",
                        file_type="text",
                        tenant_id=tenant_id,
                        owner_type="user",
                        owner_user_id=user_id,
                        parent_file_id=None,
                    )
                    session.add(owner)
                    await session.flush()
                    (prepared,) = await content_service.adopt_verified_in_transaction(
                        session,
                        intents=(
                            ContentIntent(
                                tenant_id=tenant_id,
                                created_by_user_id=user_id,
                                access_class=ContentAccessClass.PRIVATE_RESOURCE,
                                idempotency_key=f"file:{owner.id}:original:0",
                                producer_receipt=f"file:{owner.id}:original:0",
                            ),
                        ),
                        contents=(captured,),
                        publication=publication,
                    )
                    session.add(
                        FileContentReferences(
                            file_id=owner.id,
                            content_id=prepared.id,
                            variant="original",
                            ordinal=0,
                        )
                    )

        assert object_key is not None
        async with object_content_database.session() as session, session.begin():
            assert await session.get(ObjectContentOrphanCandidates, object_key) is None
            descriptor = await session.scalar(
                select(ObjectStoreObjects).where(
                    ObjectStoreObjects.object_key == object_key
                )
            )
            assert descriptor is not None
            content = await session.get(ObjectContents, descriptor.content_id)
            assert content is not None
            assert content.state == ContentState.AVAILABLE.value
            assert content.reference_count == 1
    finally:
        if object_key is not None:
            await real_object_store.store.delete_and_confirm(object_key)


@pytest.mark.asyncio
async def test_publication_reservation_is_not_an_inventory_observation(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
) -> None:
    settings = real_object_store.settings
    reservation = PublicationReservation(
        object_key=new_object_key(settings),
        size_bytes=17,
    )

    async with object_content_database.session() as session, session.begin():
        repository = ObjectContentReconciliationRepository(session)
        cursor = await repository.object_inventory_cursor()
        await repository.reserve_publication_objects(
            (reservation,),
            lease_owner="active-publisher",
            lease_seconds=settings.reconciliation_lease_seconds,
            orphan_grace_seconds=settings.orphan_grace_seconds,
        )
        completed = await repository.record_object_page(
            cursor=cursor,
            objects=(),
            next_token=None,
            orphan_grace_seconds=settings.orphan_grace_seconds,
        )
        candidate = await session.get(
            ObjectContentOrphanCandidates,
            reservation.object_key,
        )

        assert completed is True
        assert candidate is not None
        assert candidate.completed_observations == 0


@pytest.mark.asyncio
async def test_known_orphan_waits_for_a_cycle_started_after_registration(
    object_content_database: DatabaseSessionManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    object_key = f"v1/known-former/{uuid4().hex}"
    size_bytes = 19

    async with (
        object_content_database.session() as registration_session,
        registration_session.begin(),
    ):
        transaction_started_at = await registration_session.scalar(select(func.now()))
        assert transaction_started_at is not None

        registration_boundary = asyncio.Event()
        allow_registration = asyncio.Event()
        original_scalar = registration_session.scalar
        original_execute = registration_session.execute

        async def scalar_after_boundary(statement: Executable):
            result = await original_scalar(statement)
            if "clock_timestamp" in str(statement):
                registration_boundary.set()
                await allow_registration.wait()
            return result

        async def execute_after_boundary(statement: Executable):
            if "INSERT INTO object_content_orphan_candidates" in str(statement):
                registration_boundary.set()
                await allow_registration.wait()
            return await original_execute(statement)

        monkeypatch.setattr(registration_session, "scalar", scalar_after_boundary)
        monkeypatch.setattr(registration_session, "execute", execute_after_boundary)

        registration_repository = ObjectContentReconciliationRepository(
            registration_session
        )
        registration = asyncio.create_task(
            registration_repository.register_known_orphan(
                object_key=object_key,
                size_bytes=size_bytes,
                orphan_grace_seconds=1,
            )
        )
        await registration_boundary.wait()

        async with object_content_database.session() as session, session.begin():
            repository = ObjectContentReconciliationRepository(session)
            previous_cursor = await repository.object_inventory_cursor()
            completed = await repository.record_object_page(
                cursor=previous_cursor,
                objects=(),
                next_token=None,
                orphan_grace_seconds=1,
            )
            assert completed is True

        async with object_content_database.session() as session, session.begin():
            repository = ObjectContentReconciliationRepository(session)
            cursor = await repository.object_inventory_cursor()
            completed = await repository.record_object_page(
                cursor=cursor,
                objects=(),
                next_token="after-known-former-key",
                orphan_grace_seconds=1,
            )
            assert completed is False

        allow_registration.set()
        await registration
        candidate = await registration_session.get(
            ObjectContentOrphanCandidates,
            object_key,
            with_for_update=True,
        )
        assert candidate is not None
        assert candidate.last_observed_at > cursor.cycle_started_at
        candidate.eligible_after = transaction_started_at - timedelta(seconds=1)
        candidate.lease_until = transaction_started_at - timedelta(seconds=1)

    async with object_content_database.session() as session, session.begin():
        repository = ObjectContentReconciliationRepository(session)
        cursor = await repository.object_inventory_cursor()
        assert cursor.continuation_token == "after-known-former-key"
        completed = await repository.record_object_page(
            cursor=cursor,
            objects=(),
            next_token=None,
            orphan_grace_seconds=1,
        )
        candidate = await session.get(ObjectContentOrphanCandidates, object_key)
        assert completed is True
        assert candidate is not None
        assert candidate.completed_observations == 0


@pytest.mark.asyncio
async def test_expired_publication_reservation_converges_through_orphan_inventory(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
) -> None:
    settings = real_object_store.settings
    object_key = new_object_key(settings)
    payload = b"crashed-publication"
    reservation = PublicationReservation(
        object_key=object_key,
        size_bytes=len(payload),
    )

    try:
        async with object_content_database.session() as session, session.begin():
            await ObjectContentReconciliationRepository(
                session
            ).reserve_publication_objects(
                (reservation,),
                lease_owner="crashed-publisher",
                lease_seconds=settings.reconciliation_lease_seconds,
                orphan_grace_seconds=settings.orphan_grace_seconds,
            )

        async with capture_content(
            _source(payload),
            declared_media_type="application/octet-stream",
            verified_media_type="application/octet-stream",
            maximum_size_bytes=len(payload),
            spool_memory_bytes=settings.spool_memory_bytes,
            multipart_part_bytes=settings.multipart_part_bytes,
        ) as captured:
            await real_object_store.store.upload(object_key, captured)

        async with object_content_database.session() as session, session.begin():
            now = await session.scalar(select(func.now()))
            assert now is not None
            candidate = await session.get(
                ObjectContentOrphanCandidates,
                object_key,
                with_for_update=True,
            )
            assert candidate is not None
            candidate.lease_until = now - timedelta(seconds=1)
            candidate.eligible_after = now - timedelta(seconds=1)

        reconciler = _reconciler(
            settings,
            real_object_store.store,
            object_content_database,
        )
        first = await reconciler.run_once()
        assert first.orphan_objects_deleted == 0
        async with object_content_database.session() as session, session.begin():
            candidate = await session.get(
                ObjectContentOrphanCandidates,
                object_key,
            )
            assert candidate is not None
            assert candidate.completed_observations == 1

        second = await reconciler.run_once()
        assert second.orphan_objects_deleted == 1
        with pytest.raises(ObjectStoreNotFoundError):
            await real_object_store.store.head(object_key)
    finally:
        try:
            await real_object_store.store.delete_and_confirm(object_key)
        except ObjectStoreNotFoundError:
            pass


@pytest.mark.asyncio
async def test_two_complete_cycles_and_grace_delete_object_and_multipart_orphans(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
) -> None:
    settings = real_object_store.settings
    orphan_key = new_object_key(settings)
    payload = b"orphan-bytes"
    async with capture_content(
        _source(payload),
        declared_media_type="application/octet-stream",
        verified_media_type="application/octet-stream",
        maximum_size_bytes=len(payload),
        spool_memory_bytes=settings.spool_memory_bytes,
        multipart_part_bytes=settings.multipart_part_bytes,
    ) as captured:
        await real_object_store.store.upload(orphan_key, captured)

    client = _raw_client(real_object_store)
    multipart_key = new_object_key(settings)
    created = client.create_multipart_upload(
        Bucket=settings.bucket,
        Key=multipart_key,
        ContentType="application/octet-stream",
        ChecksumAlgorithm="SHA256",
        ChecksumType="COMPOSITE",
    )
    upload_id = created["UploadId"]
    reconciler = _reconciler(
        settings,
        real_object_store.store,
        object_content_database,
    )
    try:
        first = await reconciler.run_once()
        assert first.orphan_objects_deleted == 0
        assert first.multipart_aborted == 0
        async with object_content_database.session() as session, session.begin():
            orphan_candidate = await session.get(
                ObjectContentOrphanCandidates,
                orphan_key,
            )
            multipart_candidate = await session.get(
                ObjectContentMultipartCandidates,
                (multipart_key, upload_id),
            )
            assert orphan_candidate is not None
            assert multipart_candidate is not None
            assert orphan_candidate.completed_observations == 1
            assert multipart_candidate.completed_observations == 1

        await asyncio.sleep(settings.orphan_grace_seconds + 0.1)
        second = await reconciler.run_once()
        assert second.orphan_objects_deleted == 1
        assert second.multipart_aborted == 1
        with pytest.raises(ObjectStoreNotFoundError):
            await real_object_store.store.head(orphan_key)
        page = await real_object_store.store.list_multipart_page()
        assert all(item.upload_id != upload_id for item in page.uploads)
    finally:
        await real_object_store.store.abort_multipart(multipart_key, upload_id)
        client.close()


@pytest.mark.asyncio
async def test_reintroduced_bytes_for_a_tombstone_use_guarded_orphan_deletion(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
) -> None:
    settings = real_object_store.settings
    payload = b"bytes-reintroduced-by-an-older-object-snapshot"
    pending = await _create_pending(
        object_content_database,
        real_object_store,
        upload_remote=True,
        payload=payload,
    )
    object_key = pending.object_key
    reconciler = _reconciler(
        settings,
        real_object_store.store,
        object_content_database,
    )
    promoted = await reconciler.run_once()
    assert promoted.content_processed == 1
    async with object_content_database.session() as session, session.begin():
        await session.execute(
            delete(FileContentReferences).where(
                FileContentReferences.file_id == pending.file_id
            )
        )
    deleted = await reconciler.run_once()
    assert deleted.content_processed == 1

    async with capture_content(
        _source(payload),
        declared_media_type="application/octet-stream",
        verified_media_type="application/octet-stream",
        maximum_size_bytes=len(payload),
        spool_memory_bytes=settings.spool_memory_bytes,
        multipart_part_bytes=settings.multipart_part_bytes,
    ) as captured:
        await real_object_store.store.upload(object_key, captured)

    first = await reconciler.run_once()
    assert first.orphan_objects_deleted == 0
    async with object_content_database.session() as session, session.begin():
        candidate = await session.get(ObjectContentOrphanCandidates, object_key)
        assert candidate is not None
        assert candidate.completed_observations == 1

    await asyncio.sleep(settings.orphan_grace_seconds + 0.1)
    second = await reconciler.run_once()
    assert second.orphan_objects_deleted == 1
    with pytest.raises(ObjectStoreNotFoundError):
        await real_object_store.store.head(object_key)
    async with object_content_database.session() as session, session.begin():
        restored_tombstone = (
            await session.scalars(
                select(ObjectContents)
                .join(
                    ObjectStoreObjects,
                    ObjectStoreObjects.content_id == ObjectContents.id,
                )
                .where(ObjectStoreObjects.object_key == object_key)
            )
        ).one()
        assert restored_tombstone.state == ContentState.TOMBSTONED.value


@pytest.mark.asyncio
async def test_reference_drift_fails_closed_and_is_reported_by_health(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
) -> None:
    pending = await _create_pending(
        object_content_database,
        real_object_store,
        upload_remote=True,
    )
    reconciler = _reconciler(
        real_object_store.settings,
        real_object_store.store,
        object_content_database,
    )
    await reconciler.run_once()

    async with object_content_database.session() as session, session.begin():
        await session.execute(
            text(
                "ALTER TABLE object_contents "
                "DISABLE TRIGGER object_contents_10_guard_update"
            )
        )
        try:
            await session.execute(
                text(
                    "UPDATE object_contents "
                    "SET reference_count = reference_count + 1, "
                    "reference_audited_at = NULL "
                    "WHERE id = :content_id"
                ),
                {"content_id": pending.content_id},
            )
            await session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        finally:
            await session.execute(
                text(
                    "ALTER TABLE object_contents "
                    "ENABLE TRIGGER object_contents_10_guard_update"
                )
            )

    result = await reconciler.run_once()
    assert result.reference_drifts >= 1
    facts = await reconciler.health_facts()
    assert facts.reference_drifts >= 1
    async with object_content_database.session() as session, session.begin():
        content = await session.get(ObjectContents, pending.content_id)
        assert content is not None
        assert content.state == ContentState.FAILED.value
        assert content.failure_code == ContentFailureCode.REFERENCE_DRIFT.value
