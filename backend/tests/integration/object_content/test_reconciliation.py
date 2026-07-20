import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from threading import Event
from typing import TYPE_CHECKING, cast
from uuid import UUID, uuid4

import pytest
from botocore.config import Config
from botocore.session import get_session
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import DBAPIError

from eneo.database.database import DatabaseSessionManager
from eneo.database.tables.files_table import Files
from eneo.database.tables.object_content_table import (
    FileContentReferences,
    ObjectContentHolds,
    ObjectContentMultipartCandidates,
    ObjectContentOrphanCandidates,
    ObjectContents,
)
from eneo.database.tables.tenant_table import Tenants
from eneo.database.tables.users_table import Users
from eneo.object_content.content import (
    ContentFailureCode,
    ContentState,
    ObjectContentBusyError,
    capture_content,
)
from eneo.object_content.content_repository import ObjectContentRepository
from eneo.object_content.reconciliation import ObjectContentReconciler
from eneo.object_content.reconciliation_repository import (
    ObjectContentReconciliationRepository,
)
from eneo.object_content.s3_object_store import (
    ObjectStoreNotFoundError,
    S3ObjectStore,
    new_object_key,
)
from tests.integration.object_content.conftest import RealObjectStore

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client
    from mypy_boto3_s3.type_defs import (
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
            text=None,
            blob=None,
            checksum=digest.hex(),
            size=len(resolved_payload),
            mimetype="application/octet-stream",
            file_type="text",
            transcription=None,
            tenant_id=tenant_id,
            user_id=user_id,
            parent_file_id=None,
        )
        object_key = new_object_key(real_store.settings)
        content = ObjectContents(
            tenant_id=tenant_id,
            created_by_user_id=user_id,
            object_key=object_key,
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
    reconciler = ObjectContentReconciler(
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
        assert complete_row.remote_deleted_at is not None
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
    reconciler = ObjectContentReconciler(
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

    result = await ObjectContentReconciler(
        real_object_store.settings,
        real_object_store.store,
        object_content_database,
    ).run_once()

    assert result.content_processed == 1
    async with object_content_database.session() as session, session.begin():
        row = await session.get(ObjectContents, pending.content_id)
        assert row is not None
        assert row.state == ContentState.TOMBSTONED.value
        assert row.remote_deleted_at is not None
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
        ObjectContentReconciler(
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

        concurrent = await ObjectContentReconciler(
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
        assert row.remote_deleted_at is not None


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
            row = await session.get(ObjectContents, completed.content_id)
            assert row is not None
            row.multipart_upload_id = upload_id
            row.multipart_initiated_at = await session.scalar(select(func.now()))

    try:
        async with object_content_database.session() as session, session.begin():
            row = await session.get(ObjectContents, incomplete.content_id)
            assert row is not None
            row.multipart_upload_id = incomplete_upload_id
            row.multipart_initiated_at = datetime.now(UTC)

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

        result = await ObjectContentReconciler(
            settings,
            real_object_store.store,
            object_content_database,
        ).run_once()
        assert result.content_processed == 2

        async with object_content_database.session() as session, session.begin():
            completed_row = await session.get(ObjectContents, completed.content_id)
            incomplete_row = await session.get(ObjectContents, incomplete.content_id)
            assert completed_row is not None
            assert incomplete_row is not None
            assert completed_row.state == ContentState.AVAILABLE.value
            assert completed_row.multipart_upload_id is None
            assert incomplete_row.state == ContentState.FAILED.value
            assert (
                incomplete_row.failure_code == ContentFailureCode.UPLOAD_REJECTED.value
            )
            assert incomplete_row.multipart_upload_id is None
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
        assert content is not None
        content.multipart_upload_id = upload_id
        content.multipart_initiated_at = now - timedelta(minutes=5)
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
    reconciler = ObjectContentReconciler(
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
    digest = sha256(payload).digest()
    object_key = new_object_key(settings)
    async with object_content_database.session() as session, session.begin():
        tenant_id = (await session.scalars(select(Tenants.id))).one()
        user_id = (await session.scalars(select(Users.id))).one()
        now = await session.scalar(select(func.now()))
        assert now is not None
        tombstone = ObjectContents(
            tenant_id=tenant_id,
            created_by_user_id=user_id,
            object_key=object_key,
            state=ContentState.TOMBSTONED.value,
            access_class="private_resource",
            sha256=digest,
            size_bytes=len(payload),
            declared_media_type="application/octet-stream",
            verified_media_type="application/octet-stream",
            idempotency_key=uuid4().hex,
            request_fingerprint=digest,
            reference_count=0,
            delete_requested_at=now,
            remote_deleted_at=now,
        )
        session.add(tombstone)

    async with capture_content(
        _source(payload),
        declared_media_type="application/octet-stream",
        verified_media_type="application/octet-stream",
        maximum_size_bytes=len(payload),
        spool_memory_bytes=settings.spool_memory_bytes,
        multipart_part_bytes=settings.multipart_part_bytes,
    ) as captured:
        await real_object_store.store.upload(object_key, captured)

    reconciler = ObjectContentReconciler(
        settings,
        real_object_store.store,
        object_content_database,
    )
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
                select(ObjectContents).where(ObjectContents.object_key == object_key)
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
    reconciler = ObjectContentReconciler(
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
