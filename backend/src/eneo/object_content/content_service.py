from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime
from secrets import token_hex
from time import monotonic
from uuid import UUID, uuid4

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.database import DatabaseSessionManager, sessionmanager
from eneo.object_content.configuration import ObjectContentSettings
from eneo.object_content.content import (
    ByteRange,
    CapturedContent,
    ContentFailureCode,
    ContentIntent,
    ContentReadGrant,
    ObjectContentBusyError,
    ObjectContentConfigurationError,
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
from eneo.object_content.lease import OperationLeaseCheckpoint
from eneo.object_content.reconciliation_repository import (
    ObjectContentReconciliationRepository,
)
from eneo.object_content.s3_object_store import (
    ObjectRead,
    ObjectStoreBindingError,
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
        claim_id = uuid4()
        try:
            async with self._database.session() as session, session.begin():
                binding = await ObjectContentReconciliationRepository(
                    session
                ).get_or_initialize_store_binding(
                    self._settings.deployment_id,
                    claim_id=claim_id,
                    claim_seconds=self._settings.binding_claim_seconds,
                )
        except ObjectContentConfigurationError:
            raise
        except (OSError, SQLAlchemyError) as error:
            raise ObjectContentUnavailableError(
                "Unable to verify the object-content database binding"
            ) from error

        if not binding.confirmed and binding.claim_id is None:
            raise ObjectContentUnavailableError(
                "Object-content storage binding is being established"
            )

        try:
            marker_exists = await self._store.verify_binding(binding.binding_id)
        except ObjectStoreBindingError as error:
            raise ObjectContentConfigurationError(
                "Object-content storage does not match PostgreSQL"
            ) from error
        except ObjectStoreUnavailableError as error:
            raise ObjectContentUnavailableError(
                "Durable object content is temporarily unavailable"
            ) from error

        if binding.confirmed:
            if not marker_exists:
                raise ObjectContentConfigurationError(
                    "The confirmed object-content storage binding is missing"
                )
            return

        if not marker_exists:
            if binding.creation_started:
                raise ObjectContentConfigurationError(
                    "Object-content marker creation has an ambiguous prior outcome"
                )
            try:
                creation = await self._store.prepare_binding_creation(
                    binding.binding_id
                )
            except ObjectStoreBindingError as error:
                raise ObjectContentConfigurationError(
                    "Object-content storage does not match PostgreSQL"
                ) from error
            except ObjectStoreUnavailableError as error:
                raise ObjectContentUnavailableError(
                    "Durable object content is temporarily unavailable"
                ) from error
            if creation is not None:
                try:
                    async with self._database.session() as session, session.begin():
                        await ObjectContentReconciliationRepository(
                            session
                        ).mark_store_binding_creation_started(
                            deployment_id=binding.deployment_id,
                            binding_id=binding.binding_id,
                            claim_id=claim_id,
                        )
                except ObjectContentConfigurationError:
                    raise
                except ObjectContentBusyError as error:
                    raise ObjectContentUnavailableError(
                        "Object-content storage binding claim changed"
                    ) from error
                except (OSError, SQLAlchemyError) as error:
                    raise ObjectContentUnavailableError(
                        "Unable to claim object-content marker creation"
                    ) from error
                try:
                    await self._store.create_binding(creation)
                except ObjectStoreBindingError as error:
                    raise ObjectContentConfigurationError(
                        "Object-content storage does not match PostgreSQL"
                    ) from error
                except ObjectStoreUnavailableError as error:
                    raise ObjectContentUnavailableError(
                        "Durable object content is temporarily unavailable"
                    ) from error

        try:
            async with self._database.session() as session, session.begin():
                await ObjectContentReconciliationRepository(
                    session
                ).confirm_store_binding(
                    deployment_id=binding.deployment_id,
                    binding_id=binding.binding_id,
                    claim_id=claim_id,
                )
        except ObjectContentConfigurationError:
            raise
        except ObjectContentBusyError as error:
            raise ObjectContentUnavailableError(
                "Object-content storage binding claim changed"
            ) from error
        except (OSError, SQLAlchemyError) as error:
            raise ObjectContentUnavailableError(
                "Unable to confirm the object-content database binding"
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
        lease_started_at = monotonic()
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

        async def renew_upload_lease() -> None:
            async with self._database.session() as session, session.begin():
                await ObjectContentRepository(session).renew_pending_lease(
                    content_id=content_id,
                    lease_owner=lease_owner,
                    lease_seconds=self._settings.reconciliation_lease_seconds,
                )

        lease_checkpoint = OperationLeaseCheckpoint(
            lease_started_at=lease_started_at,
            lease_seconds=self._settings.reconciliation_lease_seconds,
            request_budget_seconds=self._settings.sdk_request_budget_seconds,
            renew=renew_upload_lease,
        )

        if lease.previous_multipart_upload_id is not None:
            try:
                await self._store.abort_multipart(
                    lease.object_key,
                    lease.previous_multipart_upload_id,
                    operation_checkpoint=lease_checkpoint,
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

        try:
            await self._store.upload(
                lease.object_key,
                content,
                multipart_started=record_multipart_started,
                operation_checkpoint=lease_checkpoint,
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
            async with self._store.open_verified_read(
                content.object_key,
                expected_sha256=content.sha256,
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
