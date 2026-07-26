from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from uuid import UUID

from sqlalchemy import func, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.tables.object_content_table import (
    InlineContentPayloads,
    ObjectContentHolds,
    ObjectContents,
    ObjectStoreObjects,
)
from eneo.object_content.content import (
    CapturedContent,
    ContentAccessClass,
    ContentFailureCode,
    ContentIntent,
    ContentReadGrant,
    ContentState,
    ObjectContentBusyError,
    ObjectContentIdempotencyConflictError,
    ObjectContentStateError,
    StorageKind,
)

_SHA256_BYTES = 32


@dataclass(frozen=True, slots=True)
class PreparedContent:
    id: UUID
    storage_kind: StorageKind
    state: ContentState
    created: bool


@dataclass(frozen=True, slots=True)
class UploadLease:
    content_id: UUID
    object_key: str
    state: ContentState
    attempt_count: int
    previous_multipart_upload_id: str | None
    already_available: bool


@dataclass(frozen=True, slots=True)
class ReadableContent:
    content_id: UUID
    storage_kind: StorageKind
    sha256: bytes
    size_bytes: int
    media_type: str
    access_class: ContentAccessClass


@dataclass(frozen=True, slots=True)
class ObjectStoreDescriptor:
    content_id: UUID
    object_key: str
    verification_chunk_size_bytes: int
    verification_chunk_count: int


@dataclass(frozen=True, slots=True)
class ReadableContentSource:
    content: ReadableContent
    inline_payload: bytes | None
    object_store_descriptor: ObjectStoreDescriptor | None


class ObjectContentRepository:
    """Own PostgreSQL row locks and legal object-content mutations."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def prepare_object_store(
        self,
        *,
        intent: ContentIntent,
        content: CapturedContent,
        object_key: str,
        request_fingerprint: bytes,
    ) -> PreparedContent:
        row, created = await self._prepare_control(
            intent=intent,
            content=content,
            storage_kind=StorageKind.OBJECT_STORE,
            state=ContentState.PENDING,
            request_fingerprint=request_fingerprint,
        )
        if created:
            descriptor = ObjectStoreObjects()
            descriptor.content_id = row.id
            descriptor.storage_kind = StorageKind.OBJECT_STORE.value
            descriptor.object_key = object_key
            descriptor.verification_chunk_size_bytes = content.part_size_bytes
            descriptor.verification_chunk_sha256 = b"".join(content.part_sha256)
            self._session.add(descriptor)
            await self._session.flush()
        return PreparedContent(
            id=row.id,
            storage_kind=StorageKind(row.storage_kind),
            state=ContentState(row.state),
            created=created,
        )

    async def prepare_verified_object_store(
        self,
        *,
        intent: ContentIntent,
        content: CapturedContent,
        object_key: str,
        request_fingerprint: bytes,
    ) -> PreparedContent:
        row, created = await self._prepare_control(
            intent=intent,
            content=content,
            storage_kind=StorageKind.OBJECT_STORE,
            state=ContentState.AVAILABLE,
            request_fingerprint=request_fingerprint,
        )
        if created:
            descriptor = ObjectStoreObjects()
            descriptor.content_id = row.id
            descriptor.storage_kind = StorageKind.OBJECT_STORE.value
            descriptor.object_key = object_key
            descriptor.verification_chunk_size_bytes = content.part_size_bytes
            descriptor.verification_chunk_sha256 = b"".join(content.part_sha256)
            self._session.add(descriptor)
            await self._session.flush()
        else:
            descriptor = await self._object_store_descriptor(row.id, for_update=True)
            if descriptor.object_key != object_key:
                raise ObjectContentIdempotencyConflictError(
                    "The idempotency key is bound to another verified object"
                )
        return PreparedContent(
            id=row.id,
            storage_kind=StorageKind(row.storage_kind),
            state=ContentState(row.state),
            created=created,
        )

    async def prepare_inline(
        self,
        *,
        intent: ContentIntent,
        content: CapturedContent,
        payload: bytes,
        request_fingerprint: bytes,
    ) -> PreparedContent:
        if len(payload) != content.size_bytes:
            raise ObjectContentStateError(
                "Inline payload size does not match captured content"
            )
        if sha256(payload).digest() != content.sha256:
            raise ObjectContentStateError(
                "Inline payload SHA-256 does not match captured content"
            )
        row, created = await self._prepare_control(
            intent=intent,
            content=content,
            storage_kind=StorageKind.POSTGRES_INLINE,
            state=ContentState.AVAILABLE,
            request_fingerprint=request_fingerprint,
        )
        if created:
            stored_payload = InlineContentPayloads()
            stored_payload.content_id = row.id
            stored_payload.storage_kind = StorageKind.POSTGRES_INLINE.value
            stored_payload.payload = payload
            self._session.add(stored_payload)
            await self._session.flush()
        else:
            stored_payload = await self._session.get(InlineContentPayloads, row.id)
            if row.state == ContentState.TOMBSTONED.value:
                if stored_payload is not None:
                    raise ObjectContentStateError(
                        "Inline content tombstone still owns payload bytes"
                    )
            elif stored_payload is None or stored_payload.payload != payload:
                raise ObjectContentIdempotencyConflictError(
                    "The idempotency key is bound to different inline bytes"
                )
        return PreparedContent(
            id=row.id,
            storage_kind=StorageKind(row.storage_kind),
            state=ContentState(row.state),
            created=created,
        )

    async def _prepare_control(
        self,
        *,
        intent: ContentIntent,
        content: CapturedContent,
        storage_kind: StorageKind,
        state: ContentState,
        request_fingerprint: bytes,
    ) -> tuple[ObjectContents, bool]:
        available_at = func.now() if state is ContentState.AVAILABLE else None
        statement = (
            insert(ObjectContents)
            .values(
                tenant_id=intent.tenant_id,
                created_by_user_id=intent.created_by_user_id,
                storage_kind=storage_kind.value,
                state=state.value,
                access_class=intent.access_class.value,
                sha256=content.sha256,
                size_bytes=content.size_bytes,
                declared_media_type=content.declared_media_type,
                verified_media_type=content.verified_media_type,
                idempotency_key=intent.idempotency_key,
                request_fingerprint=request_fingerprint,
                minimum_retain_until=intent.minimum_retain_until,
                available_at=available_at,
            )
            .on_conflict_do_nothing(
                constraint="uq_object_contents_tenant_id_idempotency_key"
            )
            .returning(ObjectContents.id)
        )
        inserted_id = (await self._session.execute(statement)).scalar_one_or_none()
        created = inserted_id is not None

        row = (
            await self._session.scalars(
                select(ObjectContents)
                .where(
                    ObjectContents.tenant_id == intent.tenant_id,
                    ObjectContents.idempotency_key == intent.idempotency_key,
                )
                .with_for_update()
            )
        ).one()
        if row.request_fingerprint != request_fingerprint:
            raise ObjectContentIdempotencyConflictError(
                "The idempotency key is already bound to a different content request"
            )
        if row.storage_kind != storage_kind.value:
            raise ObjectContentIdempotencyConflictError(
                "The idempotency key is already bound to another byte backend"
            )
        return row, created

    async def claim_upload(
        self,
        *,
        content_id: UUID,
        content: CapturedContent,
        lease_owner: str,
        lease_seconds: int,
    ) -> UploadLease:
        row = await self._content_for_update(content_id)
        if row.storage_kind != StorageKind.OBJECT_STORE.value:
            raise ObjectContentStateError(
                "Only object-store content can acquire an upload lease"
            )
        descriptor = await self._object_store_descriptor(content_id, for_update=True)
        self._require_content_matches(row, content)
        if row.state == ContentState.AVAILABLE.value:
            return UploadLease(
                content_id=row.id,
                object_key=descriptor.object_key,
                state=ContentState.AVAILABLE,
                attempt_count=row.attempt_count,
                previous_multipart_upload_id=None,
                already_available=True,
            )
        if (
            row.state != ContentState.PENDING.value
            or row.delete_requested_at is not None
            or row.reference_count < 1
        ):
            raise ObjectContentStateError(
                "Only pending content with its initial owner can be uploaded"
            )

        now = await self._database_now()
        if row.lease_until is not None and row.lease_until > now:
            raise ObjectContentBusyError(
                "Another object-content operation holds the lease"
            )

        previous_upload_id = descriptor.multipart_upload_id
        row.lease_owner = lease_owner
        row.lease_until = now + timedelta(seconds=lease_seconds)
        row.attempt_count += 1
        row.next_attempt_at = None
        row.failure_code = None
        row.failure_detail = None
        await self._session.flush()
        return UploadLease(
            content_id=row.id,
            object_key=descriptor.object_key,
            state=ContentState.PENDING,
            attempt_count=row.attempt_count,
            previous_multipart_upload_id=previous_upload_id,
            already_available=False,
        )

    async def clear_previous_multipart(
        self,
        *,
        content_id: UUID,
        lease_owner: str,
        upload_id: str,
    ) -> None:
        await self._leased_content_for_update(content_id, lease_owner)
        descriptor = await self._object_store_descriptor(content_id, for_update=True)
        if descriptor.multipart_upload_id == upload_id:
            descriptor.multipart_upload_id = None
            descriptor.multipart_initiated_at = None
            await self._session.flush()

    async def record_multipart_started(
        self,
        *,
        content_id: UUID,
        lease_owner: str,
        upload_id: str,
    ) -> None:
        if not 1 <= len(upload_id) <= 1024:
            raise ObjectContentStateError(
                "The object store returned an invalid multipart identifier"
            )
        row = await self._leased_content_for_update(content_id, lease_owner)
        if row.state != ContentState.PENDING.value:
            raise ObjectContentStateError(
                "Multipart intent no longer belongs to pending content"
            )
        descriptor = await self._object_store_descriptor(content_id, for_update=True)
        if descriptor.multipart_upload_id not in {None, upload_id}:
            raise ObjectContentStateError(
                "A different multipart upload is already recorded"
            )
        descriptor.multipart_upload_id = upload_id
        descriptor.multipart_initiated_at = await self._database_now()
        await self._session.flush()

    async def renew_pending_lease(
        self,
        *,
        content_id: UUID,
        lease_owner: str,
        lease_seconds: int,
    ) -> None:
        row = await self._leased_content_for_update(content_id, lease_owner)
        if row.state != ContentState.PENDING.value:
            raise ObjectContentStateError(
                "Only pending content can renew its operation lease"
            )
        now = await self._database_now()
        row.lease_until = now + timedelta(seconds=lease_seconds)
        await self._session.flush()

    async def renew_delete_lease(
        self,
        *,
        content_id: UUID,
        lease_owner: str,
        lease_seconds: int,
    ) -> None:
        row = await self._leased_content_for_update(content_id, lease_owner)
        if row.state != ContentState.DELETE_PENDING.value or row.reference_count != 0:
            raise ObjectContentStateError(
                "Only unreferenced delete-pending content can renew its operation lease"
            )
        now = await self._database_now()
        row.lease_until = now + timedelta(seconds=lease_seconds)
        await self._session.flush()

    async def promote_available(
        self,
        *,
        content_id: UUID,
        lease_owner: str,
    ) -> ReadableContent:
        row = await self._leased_content_for_update(content_id, lease_owner)
        if (
            row.state != ContentState.PENDING.value
            or row.delete_requested_at is not None
            or row.reference_count < 1
        ):
            self._clear_lease(row)
            row.next_attempt_at = await self._database_now()
            await self._session.flush()
            raise ObjectContentStateError(
                "Content cannot become available after its initial owner detached"
            )

        now = await self._database_now()
        row.state = ContentState.AVAILABLE.value
        row.available_at = now
        row.failure_code = None
        row.failure_detail = None
        row.next_attempt_at = None
        descriptor = await self._object_store_descriptor(content_id, for_update=True)
        descriptor.multipart_upload_id = None
        descriptor.multipart_initiated_at = None
        self._clear_lease(row)
        await self._session.flush()
        return self._readable(row)

    async def record_retryable_upload(
        self,
        *,
        content_id: UUID,
        lease_owner: str,
        retry_delay_seconds: int,
    ) -> None:
        row = await self._content_for_update(content_id)
        if row.lease_owner != lease_owner:
            return
        if row.state == ContentState.PENDING.value:
            now = await self._database_now()
            row.failure_code = ContentFailureCode.UPLOAD_RETRYABLE.value
            row.failure_detail = "upload outcome is ambiguous; reconciliation required"
            row.next_attempt_at = now + timedelta(seconds=retry_delay_seconds)
        self._clear_lease(row)
        await self._session.flush()

    async def record_integrity_failure(
        self,
        *,
        content_id: UUID,
        lease_owner: str,
    ) -> None:
        row = await self._content_for_update(content_id)
        if row.lease_owner != lease_owner:
            return
        if row.state == ContentState.PENDING.value:
            row.state = ContentState.FAILED.value
            row.failure_code = ContentFailureCode.VERIFICATION_MISMATCH.value
            row.failure_detail = (
                "object-store verification did not match durable intent"
            )
            if row.reference_count == 0:
                now = await self._database_now()
                row.delete_requested_at = row.delete_requested_at or now
                row.next_attempt_at = now
            else:
                # Keep live-owner recovery and legal-hold options open. The
                # final-reference trigger records irreversible delete intent.
                row.next_attempt_at = None
        self._clear_lease(row)
        await self._session.flush()

    async def record_pending_missing(
        self,
        *,
        content_id: UUID,
        lease_owner: str,
    ) -> None:
        row = await self._leased_content_for_update(content_id, lease_owner)
        if row.state != ContentState.PENDING.value:
            raise ObjectContentStateError(
                "Only pending content can record an absent upload"
            )
        now = await self._database_now()
        row.state = ContentState.FAILED.value
        row.failure_code = ContentFailureCode.UPLOAD_REJECTED.value
        row.failure_detail = "stale durable intent has no complete object"
        row.delete_requested_at = row.delete_requested_at or now
        row.next_attempt_at = now if row.reference_count == 0 else None
        descriptor = await self._object_store_descriptor(content_id, for_update=True)
        descriptor.multipart_upload_id = None
        descriptor.multipart_initiated_at = None
        self._clear_lease(row)
        await self._session.flush()

    async def record_reconciliation_retry(
        self,
        *,
        content_id: UUID,
        lease_owner: str,
        failure_code: ContentFailureCode,
        retry_delay_seconds: int,
    ) -> None:
        if failure_code not in {
            ContentFailureCode.UPLOAD_RETRYABLE,
            ContentFailureCode.DELETE_RETRYABLE,
        }:
            raise ValueError("Invalid retryable reconciliation failure code")
        row = await self._leased_content_for_update(content_id, lease_owner)
        expected_state = (
            ContentState.PENDING
            if failure_code is ContentFailureCode.UPLOAD_RETRYABLE
            else ContentState.DELETE_PENDING
        )
        if row.state != expected_state.value:
            raise ObjectContentStateError(
                "Object-content state changed during reconciliation"
            )
        now = await self._database_now()
        row.failure_code = failure_code.value
        row.failure_detail = "object-store outcome is ambiguous; retry scheduled"
        row.next_attempt_at = now + timedelta(seconds=retry_delay_seconds)
        self._clear_lease(row)
        await self._session.flush()

    async def mark_tombstoned(
        self,
        *,
        content_id: UUID,
        lease_owner: str,
        purge_after: datetime | None,
    ) -> None:
        row = await self._leased_content_for_update(content_id, lease_owner)
        if row.state != ContentState.DELETE_PENDING.value or row.reference_count != 0:
            raise ObjectContentStateError(
                "Only unreferenced delete-pending content can become tombstoned"
            )
        now = await self._database_now()
        row.state = ContentState.TOMBSTONED.value
        row.payload_deleted_at = now
        row.tombstone_purge_after = purge_after
        row.failure_code = None
        row.failure_detail = None
        row.next_attempt_at = None
        if row.storage_kind == StorageKind.OBJECT_STORE.value:
            descriptor = await self._object_store_descriptor(
                content_id,
                for_update=True,
            )
            descriptor.multipart_upload_id = None
            descriptor.multipart_initiated_at = None
        elif row.storage_kind == StorageKind.POSTGRES_INLINE.value:
            payload = (
                await self._session.scalars(
                    select(InlineContentPayloads)
                    .where(InlineContentPayloads.content_id == content_id)
                    .with_for_update()
                )
            ).one_or_none()
            if payload is None:
                raise ObjectContentStateError("Inline content payload is missing")
            await self._session.delete(payload)
        else:
            raise ObjectContentStateError("Object content has an invalid storage kind")
        self._clear_lease(row)
        await self._session.flush()

    async def get_readable_sources(
        self,
        grants: Sequence[ContentReadGrant],
    ) -> dict[UUID, ReadableContentSource]:
        """Read access-validated controls and byte-source facts in one query."""
        if not grants:
            return {}

        requested = {
            (
                grant.content_id,
                grant.tenant_id,
                grant.access_class.value,
            )
            for grant in grants
        }
        rows = (
            await self._session.execute(
                select(
                    ObjectContents,
                    InlineContentPayloads.payload,
                    ObjectStoreObjects.object_key,
                    ObjectStoreObjects.verification_chunk_size_bytes,
                    func.octet_length(ObjectStoreObjects.verification_chunk_sha256),
                )
                .outerjoin(
                    InlineContentPayloads,
                    InlineContentPayloads.content_id == ObjectContents.id,
                )
                .outerjoin(
                    ObjectStoreObjects,
                    ObjectStoreObjects.content_id == ObjectContents.id,
                )
                .where(
                    tuple_(
                        ObjectContents.id,
                        ObjectContents.tenant_id,
                        ObjectContents.access_class,
                    ).in_(requested),
                    ObjectContents.state == ContentState.AVAILABLE.value,
                )
            )
        ).all()

        sources: dict[UUID, ReadableContentSource] = {}
        for (
            row,
            inline_payload,
            object_key,
            verification_chunk_size_bytes,
            verification_digest_bytes,
        ) in rows:
            content = self._readable(row)
            if (
                content.storage_kind is StorageKind.POSTGRES_INLINE
                and inline_payload is None
            ):
                raise ObjectContentStateError("Inline content payload is missing")
            if content.storage_kind is StorageKind.OBJECT_STORE and (
                object_key is None
                or verification_chunk_size_bytes is None
                or verification_digest_bytes is None
                or verification_chunk_size_bytes < 1
                or verification_digest_bytes < _SHA256_BYTES
                or verification_digest_bytes % _SHA256_BYTES != 0
            ):
                raise ObjectContentStateError(
                    "Object-store verification descriptor is missing or invalid"
                )
            sources[content.content_id] = ReadableContentSource(
                content=content,
                inline_payload=inline_payload,
                object_store_descriptor=(
                    ObjectStoreDescriptor(
                        content_id=content.content_id,
                        object_key=object_key,
                        verification_chunk_size_bytes=verification_chunk_size_bytes,
                        verification_chunk_count=(
                            verification_digest_bytes // _SHA256_BYTES
                        ),
                    )
                    if (
                        object_key is not None
                        and verification_chunk_size_bytes is not None
                        and verification_digest_bytes is not None
                    )
                    else None
                ),
            )

        requested_ids = {grant.content_id for grant in grants}
        if sources.keys() != requested_ids:
            raise ObjectContentStateError("Object content is not available")
        return sources

    async def get_object_store_verification_chunks(
        self,
        *,
        content_id: UUID,
        first_chunk_index: int,
        chunk_count: int,
    ) -> tuple[bytes, ...]:
        """Read only the packed digest interval needed for one ranged response."""
        if first_chunk_index < 0:
            raise ValueError("first_chunk_index must not be negative")
        if chunk_count < 1:
            raise ValueError("chunk_count must be positive")

        packed = await self._session.scalar(
            select(
                func.substring(
                    ObjectStoreObjects.verification_chunk_sha256,
                    (first_chunk_index * _SHA256_BYTES) + 1,
                    chunk_count * _SHA256_BYTES,
                )
            ).where(ObjectStoreObjects.content_id == content_id)
        )
        expected_bytes = chunk_count * _SHA256_BYTES
        if not isinstance(packed, bytes) or len(packed) != expected_bytes:
            raise ObjectContentStateError(
                "Object-store verification chunks are unavailable"
            )
        return tuple(
            packed[offset : offset + _SHA256_BYTES]
            for offset in range(0, expected_bytes, _SHA256_BYTES)
        )

    async def get_available_by_id(self, content_id: UUID) -> ReadableContent:
        row = (
            await self._session.scalars(
                select(ObjectContents).where(ObjectContents.id == content_id)
            )
        ).one_or_none()
        if row is None or row.state != ContentState.AVAILABLE.value:
            raise ObjectContentStateError("Object content is not available")
        return self._readable(row)

    async def mark_backend_failure(
        self,
        *,
        content_id: UUID,
        failure_code: ContentFailureCode,
    ) -> None:
        if failure_code not in {
            ContentFailureCode.BACKEND_MISSING,
            ContentFailureCode.BACKEND_CORRUPT,
        }:
            raise ValueError("mark_backend_failure requires a backend failure code")
        row = await self._content_for_update(content_id)
        if row.state == ContentState.AVAILABLE.value:
            row.state = ContentState.FAILED.value
            row.failure_code = failure_code.value
            row.failure_detail = "durable object bytes are unavailable or untrusted"
            row.next_attempt_at = None
            await self._session.flush()

    async def apply_hold(
        self,
        *,
        tenant_id: UUID,
        content_id: UUID,
        kind: str,
        reason: str,
        actor_user_id: UUID | None,
        expires_at: datetime | None,
    ) -> UUID:
        if kind not in {"legal", "recovery"}:
            raise ValueError("Object-content hold kind must be legal or recovery")
        if not 1 <= len(reason) <= 512:
            raise ValueError(
                "Object-content hold reason must contain 1 to 512 characters"
            )
        if expires_at is not None and expires_at.utcoffset() is None:
            raise ValueError("Object-content hold expiry must include a timezone")

        await self._tenant_content_for_update(content_id, tenant_id)
        hold = ObjectContentHolds()
        hold.content_id = content_id
        hold.kind = kind
        hold.reason = reason
        hold.actor_user_id = actor_user_id
        hold.expires_at = expires_at
        self._session.add(hold)
        await self._session.flush()
        return hold.id

    async def release_hold(
        self,
        *,
        tenant_id: UUID,
        hold_id: UUID,
    ) -> None:
        content_id = await self._session.scalar(
            select(ObjectContentHolds.content_id).where(
                ObjectContentHolds.id == hold_id
            )
        )
        if content_id is None:
            raise ObjectContentStateError("Object-content hold does not exist")
        await self._tenant_content_for_update(content_id, tenant_id)
        hold = (
            await self._session.scalars(
                select(ObjectContentHolds)
                .where(ObjectContentHolds.id == hold_id)
                .with_for_update()
            )
        ).one_or_none()
        if hold is None or hold.content_id != content_id:
            raise ObjectContentStateError("Object-content hold changed concurrently")
        if hold.released_at is None:
            hold.released_at = await self._database_now()
            await self._session.flush()

    async def extend_minimum_retention(
        self,
        *,
        tenant_id: UUID,
        content_id: UUID,
        retain_until: datetime,
    ) -> None:
        if retain_until.utcoffset() is None:
            raise ValueError("Minimum retention must include a timezone")
        row = await self._tenant_content_for_update(content_id, tenant_id)
        if row.state in {
            ContentState.DELETE_PENDING.value,
            ContentState.TOMBSTONED.value,
        }:
            raise ObjectContentStateError(
                "Minimum retention cannot change after physical delete intent"
            )
        if row.minimum_retain_until is None or retain_until > row.minimum_retain_until:
            row.minimum_retain_until = retain_until
            await self._session.flush()

    async def _content_for_update(self, content_id: UUID) -> ObjectContents:
        row = (
            await self._session.scalars(
                select(ObjectContents)
                .where(ObjectContents.id == content_id)
                .with_for_update()
            )
        ).one_or_none()
        if row is None:
            raise ObjectContentStateError("Object content does not exist")
        return row

    async def _tenant_content_for_update(
        self,
        content_id: UUID,
        tenant_id: UUID,
    ) -> ObjectContents:
        row = (
            await self._session.scalars(
                select(ObjectContents)
                .where(
                    ObjectContents.id == content_id,
                    ObjectContents.tenant_id == tenant_id,
                )
                .with_for_update()
            )
        ).one_or_none()
        if row is None:
            raise ObjectContentStateError("Object content does not exist")
        return row

    async def _leased_content_for_update(
        self,
        content_id: UUID,
        lease_owner: str,
    ) -> ObjectContents:
        row = await self._content_for_update(content_id)
        if row.lease_owner != lease_owner:
            raise ObjectContentBusyError("The object-content lease changed")
        return row

    async def _object_store_descriptor(
        self,
        content_id: UUID,
        *,
        for_update: bool = False,
    ) -> ObjectStoreObjects:
        statement = select(ObjectStoreObjects).where(
            ObjectStoreObjects.content_id == content_id
        )
        if for_update:
            statement = statement.with_for_update()
        descriptor = (await self._session.scalars(statement)).one_or_none()
        if descriptor is None:
            raise ObjectContentStateError("Object-store descriptor is missing")
        return descriptor

    async def _database_now(self) -> datetime:
        now = await self._session.scalar(select(func.now()))
        if now is None:
            raise RuntimeError("PostgreSQL did not return its current time")
        return now

    @staticmethod
    def _require_content_matches(
        row: ObjectContents,
        content: CapturedContent,
    ) -> None:
        if (
            row.sha256 != content.sha256
            or row.size_bytes != content.size_bytes
            or row.declared_media_type != content.declared_media_type
            or row.verified_media_type != content.verified_media_type
        ):
            raise ObjectContentIdempotencyConflictError(
                "Captured content does not match the durable request intent"
            )

    @staticmethod
    def _clear_lease(row: ObjectContents) -> None:
        row.lease_owner = None
        row.lease_until = None

    @staticmethod
    def _readable(row: ObjectContents) -> ReadableContent:
        return ReadableContent(
            content_id=row.id,
            storage_kind=StorageKind(row.storage_kind),
            sha256=row.sha256,
            size_bytes=row.size_bytes,
            media_type=row.verified_media_type,
            access_class=ContentAccessClass(row.access_class),
        )
