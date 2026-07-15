from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime
from secrets import token_hex
from time import monotonic
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.database import DatabaseSessionManager, sessionmanager
from eneo.object_content.configuration import ObjectContentSettings
from eneo.object_content.content import (
    ByteRange,
    CapturedContent,
    ContentFailureCode,
    ContentIntent,
    ContentReadGrant,
    ObjectContentIntegrityError,
    ObjectContentUnavailableError,
    content_request_fingerprint,
)
from eneo.object_content.content_repository import (
    ObjectContentRepository,
    PreparedContent,
    ReadableContent,
    UploadLease,
)
from eneo.object_content.s3_object_store import (
    ObjectRead,
    ObjectStoreIntegrityError,
    ObjectStoreNotFoundError,
    ObjectStoreUnavailableError,
    S3ObjectStore,
    new_object_key,
)


def retry_delay_seconds(
    attempt_count: int,
    *,
    base_seconds: int,
    maximum_seconds: int,
) -> int:
    if attempt_count < 1 or base_seconds < 1 or maximum_seconds < base_seconds:
        raise ValueError("Invalid reconciliation retry bounds")
    exponent = min(attempt_count - 1, 30)
    return min(maximum_seconds, base_seconds * (2**exponent))


class ObjectContentService:
    """Orchestrate durable intent, the sole byte adapter, and legal transitions."""

    def __init__(
        self,
        settings: ObjectContentSettings,
        store: S3ObjectStore,
        database: DatabaseSessionManager = sessionmanager,
    ) -> None:
        self._settings = settings
        self._store = store
        self._database = database

    async def check_ready(self) -> None:
        try:
            await self._store.check_ready()
        except ObjectStoreUnavailableError as error:
            raise ObjectContentUnavailableError(
                "Durable object content is temporarily unavailable"
            ) from error

    async def prepare_in_transaction(
        self,
        session: AsyncSession,
        *,
        intent: ContentIntent,
        content: CapturedContent,
    ) -> PreparedContent:
        """Persist intent inside the owning resource's transaction.

        The owning operation checks readiness before opening this transaction,
        then creates its concrete first reference before commit. PostgreSQL
        enforces that pending-reference boundary.
        """
        repository = ObjectContentRepository(session)
        return await repository.prepare(
            intent=intent,
            content=content,
            object_key=new_object_key(self._settings),
            request_fingerprint=content_request_fingerprint(intent, content),
        )

    async def store_and_verify(
        self,
        *,
        content_id: UUID,
        content: CapturedContent,
    ) -> ReadableContent:
        lease_owner = token_hex(16)
        async with self._database.session() as session, session.begin():
            lease = await ObjectContentRepository(session).claim_upload(
                content_id=content_id,
                content=content,
                lease_owner=lease_owner,
                lease_seconds=self._settings.reconciliation_lease_seconds,
            )
        if lease.already_available:
            async with self._database.session() as session, session.begin():
                return await ObjectContentRepository(session).get_available_by_id(
                    content_id
                )

        lease_deadline = monotonic() + self._settings.reconciliation_lease_seconds

        if lease.previous_multipart_upload_id is not None:
            try:
                await self._store.abort_multipart(
                    lease.object_key,
                    lease.previous_multipart_upload_id,
                )
            except ObjectStoreUnavailableError as error:
                await self._record_retryable_upload(lease, lease_owner)
                raise ObjectContentUnavailableError(
                    "Durable object content is temporarily unavailable"
                ) from error
            async with self._database.session() as session, session.begin():
                await ObjectContentRepository(session).clear_previous_multipart(
                    content_id=content_id,
                    lease_owner=lease_owner,
                    upload_id=lease.previous_multipart_upload_id,
                )

        async def record_multipart_started(upload_id: str) -> None:
            async with self._database.session() as session, session.begin():
                await ObjectContentRepository(session).record_multipart_started(
                    content_id=content_id,
                    lease_owner=lease_owner,
                    upload_id=upload_id,
                )

        async def renew_upload_lease() -> None:
            nonlocal lease_deadline
            now = monotonic()
            if lease_deadline - now > self._settings.sdk_request_budget_seconds:
                return
            async with self._database.session() as session, session.begin():
                await ObjectContentRepository(session).renew_pending_lease(
                    content_id=content_id,
                    lease_owner=lease_owner,
                    lease_seconds=self._settings.reconciliation_lease_seconds,
                )
            lease_deadline = monotonic() + self._settings.reconciliation_lease_seconds

        try:
            await self._store.upload(
                lease.object_key,
                content,
                multipart_started=record_multipart_started,
                upload_checkpoint=renew_upload_lease,
            )
        except ObjectStoreIntegrityError as error:
            async with self._database.session() as session, session.begin():
                await ObjectContentRepository(session).record_integrity_failure(
                    content_id=content_id,
                    lease_owner=lease_owner,
                )
            raise ObjectContentIntegrityError(
                "Durable object verification failed"
            ) from error
        except ObjectStoreUnavailableError as error:
            await self._record_retryable_upload(lease, lease_owner)
            raise ObjectContentUnavailableError(
                "Durable object content is temporarily unavailable"
            ) from error

        async with self._database.session() as session, session.begin():
            return await ObjectContentRepository(session).promote_available(
                content_id=content_id,
                lease_owner=lease_owner,
            )

    @asynccontextmanager
    async def open_content(
        self,
        grant: ContentReadGrant,
        *,
        range_header: str | None = None,
    ) -> AsyncGenerator[ObjectRead]:
        async with self._database.session() as session, session.begin():
            content = await ObjectContentRepository(session).get_readable(
                content_id=grant.content_id,
                tenant_id=grant.tenant_id,
                access_class=grant.access_class,
            )
        byte_range = (
            None
            if range_header is None
            else ByteRange.parse(range_header, size_bytes=content.size_bytes)
        )

        try:
            async with self._store.open_read(
                content.object_key,
                expected_size_bytes=content.size_bytes,
                expected_media_type=content.media_type,
                byte_range=byte_range,
            ) as opened:
                yield opened
        except ObjectStoreNotFoundError as error:
            await self._mark_remote_failure(
                content.content_id,
                ContentFailureCode.REMOTE_MISSING,
            )
            raise ObjectContentUnavailableError(
                "Durable object content is unavailable"
            ) from error
        except ObjectStoreIntegrityError as error:
            await self._mark_remote_failure(
                content.content_id,
                ContentFailureCode.REMOTE_CORRUPT,
            )
            raise ObjectContentIntegrityError(
                "Durable object verification failed"
            ) from error
        except ObjectStoreUnavailableError as error:
            raise ObjectContentUnavailableError(
                "Durable object content is temporarily unavailable"
            ) from error

    async def apply_hold(
        self,
        session: AsyncSession,
        *,
        tenant_id: UUID,
        content_id: UUID,
        kind: str,
        reason: str,
        actor_user_id: UUID | None,
        expires_at: datetime | None,
    ) -> UUID:
        return await ObjectContentRepository(session).apply_hold(
            tenant_id=tenant_id,
            content_id=content_id,
            kind=kind,
            reason=reason,
            actor_user_id=actor_user_id,
            expires_at=expires_at,
        )

    async def release_hold(
        self,
        session: AsyncSession,
        *,
        tenant_id: UUID,
        hold_id: UUID,
    ) -> None:
        await ObjectContentRepository(session).release_hold(
            tenant_id=tenant_id,
            hold_id=hold_id,
        )

    async def extend_minimum_retention(
        self,
        session: AsyncSession,
        *,
        tenant_id: UUID,
        content_id: UUID,
        retain_until: datetime,
    ) -> None:
        await ObjectContentRepository(session).extend_minimum_retention(
            tenant_id=tenant_id,
            content_id=content_id,
            retain_until=retain_until,
        )

    async def _record_retryable_upload(
        self,
        lease: UploadLease,
        lease_owner: str,
    ) -> None:
        delay = retry_delay_seconds(
            lease.attempt_count,
            base_seconds=self._settings.reconciliation_retry_base_seconds,
            maximum_seconds=self._settings.reconciliation_retry_max_seconds,
        )
        async with self._database.session() as session, session.begin():
            await ObjectContentRepository(session).record_retryable_upload(
                content_id=lease.content_id,
                lease_owner=lease_owner,
                retry_delay_seconds=delay,
            )

    async def _mark_remote_failure(
        self,
        content_id: UUID,
        failure_code: ContentFailureCode,
    ) -> None:
        async with self._database.session() as session, session.begin():
            await ObjectContentRepository(session).mark_remote_failure(
                content_id=content_id,
                failure_code=failure_code,
            )
