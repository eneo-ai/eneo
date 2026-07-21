from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.tables.object_content_table import ObjectContentHolds, ObjectContents
from eneo.object_content.content import (
    CapturedContent,
    ContentAccessClass,
    ContentFailureCode,
    ContentIntent,
    ContentState,
    ObjectContentBusyError,
    ObjectContentIdempotencyConflictError,
    ObjectContentStateError,
)


@dataclass(frozen=True, slots=True)
class PreparedContent:
    id: UUID
    object_key: str
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
    object_key: str
    sha256: bytes
    size_bytes: int
    media_type: str
    access_class: ContentAccessClass


class ObjectContentRepository:
    """Own PostgreSQL row locks and legal object-content mutations."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def prepare(
        self,
        *,
        intent: ContentIntent,
        content: CapturedContent,
        object_key: str,
        request_fingerprint: bytes,
    ) -> PreparedContent:
        statement = (
            insert(ObjectContents)
            .values(
                tenant_id=intent.tenant_id,
                created_by_user_id=intent.created_by_user_id,
                object_key=object_key,
                state=ContentState.PENDING.value,
                access_class=intent.access_class.value,
                sha256=content.sha256,
                size_bytes=content.size_bytes,
                declared_media_type=content.declared_media_type,
                verified_media_type=content.verified_media_type,
                idempotency_key=intent.idempotency_key,
                request_fingerprint=request_fingerprint,
                minimum_retain_until=intent.minimum_retain_until,
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
        return PreparedContent(
            id=row.id,
            object_key=row.object_key,
            state=ContentState(row.state),
            created=created,
        )

    async def claim_upload(
        self,
        *,
        content_id: UUID,
        content: CapturedContent,
        lease_owner: str,
        lease_seconds: int,
    ) -> UploadLease:
        row = await self._content_for_update(content_id)
        self._require_content_matches(row, content)
        if row.state == ContentState.AVAILABLE.value:
            return UploadLease(
                content_id=row.id,
                object_key=row.object_key,
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

        previous_upload_id = row.multipart_upload_id
        row.lease_owner = lease_owner
        row.lease_until = now + timedelta(seconds=lease_seconds)
        row.attempt_count += 1
        row.next_attempt_at = None
        row.failure_code = None
        row.failure_detail = None
        await self._session.flush()
        return UploadLease(
            content_id=row.id,
            object_key=row.object_key,
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
        row = await self._leased_content_for_update(content_id, lease_owner)
        if row.multipart_upload_id == upload_id:
            row.multipart_upload_id = None
            row.multipart_initiated_at = None
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
        if row.multipart_upload_id not in {None, upload_id}:
            raise ObjectContentStateError(
                "A different multipart upload is already recorded"
            )
        row.multipart_upload_id = upload_id
        row.multipart_initiated_at = await self._database_now()
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
        row.multipart_upload_id = None
        row.multipart_initiated_at = None
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
        row.multipart_upload_id = None
        row.multipart_initiated_at = None
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
        row.remote_deleted_at = now
        row.tombstone_purge_after = purge_after
        row.failure_code = None
        row.failure_detail = None
        row.next_attempt_at = None
        row.multipart_upload_id = None
        row.multipart_initiated_at = None
        self._clear_lease(row)
        await self._session.flush()

    async def get_readable(
        self,
        *,
        content_id: UUID,
        tenant_id: UUID,
        access_class: ContentAccessClass,
    ) -> ReadableContent:
        row = (
            await self._session.scalars(
                select(ObjectContents).where(
                    ObjectContents.id == content_id,
                    ObjectContents.tenant_id == tenant_id,
                    ObjectContents.access_class == access_class.value,
                )
            )
        ).one_or_none()
        if row is None or row.state != ContentState.AVAILABLE.value:
            raise ObjectContentStateError("Object content is not available")
        return self._readable(row)

    async def get_available_by_id(self, content_id: UUID) -> ReadableContent:
        row = (
            await self._session.scalars(
                select(ObjectContents).where(ObjectContents.id == content_id)
            )
        ).one_or_none()
        if row is None or row.state != ContentState.AVAILABLE.value:
            raise ObjectContentStateError("Object content is not available")
        return self._readable(row)

    async def mark_remote_failure(
        self,
        *,
        content_id: UUID,
        failure_code: ContentFailureCode,
    ) -> None:
        if failure_code not in {
            ContentFailureCode.REMOTE_MISSING,
            ContentFailureCode.REMOTE_CORRUPT,
        }:
            raise ValueError("mark_remote_failure requires a remote failure code")
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
            object_key=row.object_key,
            sha256=row.sha256,
            size_bytes=row.size_bytes,
            media_type=row.verified_media_type,
            access_class=ContentAccessClass(row.access_class),
        )
