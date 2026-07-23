from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime
from secrets import token_hex
from time import monotonic
from uuid import UUID, uuid4

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.database import DatabaseSessionManager, sessionmanager
from eneo.object_content.configuration import (
    ObjectContentCoreSettings,
    ObjectContentSettings,
)
from eneo.object_content.content import (
    ByteRange,
    CapturedContent,
    ContentFailureCode,
    ContentIntent,
    ContentRead,
    ContentReadGrant,
    ObjectContentBusyError,
    ObjectContentConfigurationError,
    ObjectContentIntegrityError,
    ObjectContentUnavailableError,
    StorageKind,
    content_request_fingerprint,
)
from eneo.object_content.content_repository import (
    ObjectContentRepository,
    PreparedContent,
    ReadableContent,
    UploadLease,
)
from eneo.object_content.inline_content_store import InlineContentStore
from eneo.object_content.lease import OperationLeaseCheckpoint
from eneo.object_content.reconciliation_repository import (
    ObjectContentReconciliationRepository,
)
from eneo.object_content.s3_object_store import (
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
        core_settings: ObjectContentCoreSettings,
        database: DatabaseSessionManager = sessionmanager,
        *,
        object_store_settings: ObjectContentSettings | None = None,
        object_store: S3ObjectStore | None = None,
    ) -> None:
        if (object_store_settings is None) != (object_store is None):
            raise ValueError(
                "Object-store settings and adapter must be supplied together"
            )
        self._core_settings = core_settings
        self._object_store_settings = object_store_settings
        self._object_store = object_store
        self._inline_store = InlineContentStore(
            maximum_size_bytes=core_settings.inline_maximum_bytes,
            io_chunk_bytes=core_settings.inline_io_chunk_bytes,
        )
        self._database = database

    @property
    def object_store_configured(self) -> bool:
        return self._object_store is not None

    async def check_object_store_ready(self) -> None:
        settings, store = self._require_object_store()
        try:
            await store.check_ready()
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
                    settings.deployment_id,
                    claim_id=claim_id,
                    claim_seconds=settings.binding_claim_seconds,
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
            marker_exists = await store.verify_binding(binding.binding_id)
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
                creation = await store.prepare_binding_creation(binding.binding_id)
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
                    await store.create_binding(creation)
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
        storage_kind: StorageKind,
    ) -> PreparedContent:
        """Persist intent inside the owning resource's transaction.

        The owning operation checks readiness before opening this transaction,
        then creates its concrete first reference before commit. PostgreSQL
        enforces that pending-reference boundary.
        """
        repository = ObjectContentRepository(session)
        request_fingerprint = content_request_fingerprint(
            intent,
            content,
            storage_kind,
        )
        match storage_kind:
            case StorageKind.POSTGRES_INLINE:
                payload = await self._inline_store.materialize(content)
                return await repository.prepare_inline(
                    intent=intent,
                    content=content,
                    payload=payload,
                    request_fingerprint=request_fingerprint,
                )
            case StorageKind.OBJECT_STORE:
                settings, _store = self._require_object_store()
                return await repository.prepare_object_store(
                    intent=intent,
                    content=content,
                    object_key=new_object_key(settings),
                    request_fingerprint=request_fingerprint,
                )

    async def store_and_verify(
        self,
        *,
        content_id: UUID,
        content: CapturedContent,
    ) -> ReadableContent:
        settings, store = self._require_object_store()
        lease_owner = token_hex(16)
        lease_started_at = monotonic()
        async with self._database.session() as session, session.begin():
            lease = await ObjectContentRepository(session).claim_upload(
                content_id=content_id,
                content=content,
                lease_owner=lease_owner,
                lease_seconds=settings.reconciliation_lease_seconds,
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
                    lease_seconds=settings.reconciliation_lease_seconds,
                )

        lease_checkpoint = OperationLeaseCheckpoint(
            lease_started_at=lease_started_at,
            lease_seconds=settings.reconciliation_lease_seconds,
            request_budget_seconds=settings.sdk_request_budget_seconds,
            renew=renew_upload_lease,
        )

        if lease.previous_multipart_upload_id is not None:
            try:
                await store.abort_multipart(
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
            await store.upload(
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
    ) -> AsyncGenerator[ContentRead]:
        async with self._database.session() as session, session.begin():
            repository = ObjectContentRepository(session)
            content = await repository.get_readable(
                content_id=grant.content_id,
                tenant_id=grant.tenant_id,
                access_class=grant.access_class,
            )
            inline_payload = (
                await repository.get_inline_payload(content.content_id)
                if content.storage_kind is StorageKind.POSTGRES_INLINE
                else None
            )
            object_store_descriptor = (
                await repository.get_object_store_descriptor(content.content_id)
                if content.storage_kind is StorageKind.OBJECT_STORE
                else None
            )
        byte_range = (
            None
            if range_header is None
            else ByteRange.parse(range_header, size_bytes=content.size_bytes)
        )

        match content.storage_kind:
            case StorageKind.POSTGRES_INLINE:
                if inline_payload is None:
                    raise RuntimeError("Inline content dispatch lost its payload")
                try:
                    async with self._inline_store.open_verified_read(
                        inline_payload,
                        expected_sha256=content.sha256,
                        expected_size_bytes=content.size_bytes,
                        expected_media_type=content.media_type,
                        byte_range=byte_range,
                    ) as opened:
                        yield opened
                except ObjectContentIntegrityError:
                    await self._mark_backend_failure(
                        content.content_id,
                        ContentFailureCode.BACKEND_CORRUPT,
                    )
                    raise
            case StorageKind.OBJECT_STORE:
                if object_store_descriptor is None:
                    raise RuntimeError(
                        "Object-store content dispatch lost its descriptor"
                    )
                _settings, store = self._require_object_store()
                try:
                    async with store.open_verified_read(
                        object_store_descriptor.object_key,
                        expected_sha256=content.sha256,
                        expected_size_bytes=content.size_bytes,
                        expected_media_type=content.media_type,
                        byte_range=byte_range,
                    ) as opened:
                        yield opened
                except ObjectStoreNotFoundError as error:
                    await self._mark_backend_failure(
                        content.content_id,
                        ContentFailureCode.BACKEND_MISSING,
                    )
                    raise ObjectContentUnavailableError(
                        "Durable object content is unavailable"
                    ) from error
                except ObjectStoreIntegrityError as error:
                    await self._mark_backend_failure(
                        content.content_id,
                        ContentFailureCode.BACKEND_CORRUPT,
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
            base_seconds=self._core_settings.reconciliation_retry_base_seconds,
            maximum_seconds=self._core_settings.reconciliation_retry_max_seconds,
        )
        async with self._database.session() as session, session.begin():
            await ObjectContentRepository(session).record_retryable_upload(
                content_id=lease.content_id,
                lease_owner=lease_owner,
                retry_delay_seconds=delay,
            )

    async def _mark_backend_failure(
        self,
        content_id: UUID,
        failure_code: ContentFailureCode,
    ) -> None:
        async with self._database.session() as session, session.begin():
            await ObjectContentRepository(session).mark_backend_failure(
                content_id=content_id,
                failure_code=failure_code,
            )

    def _require_object_store(self) -> tuple[ObjectContentSettings, S3ObjectStore]:
        settings = self._object_store_settings
        store = self._object_store
        if settings is None or store is None:
            raise ObjectContentConfigurationError(
                "Object-store content is not configured for this deployment"
            )
        return settings, store
