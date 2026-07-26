from collections.abc import AsyncGenerator, AsyncIterable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
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
    ObjectContentStateError,
    ObjectContentUnavailableError,
    StorageKind,
    capture_content,
    content_request_fingerprint,
)
from eneo.object_content.content_repository import (
    ObjectContentRepository,
    PreparedContent,
    ReadableContent,
    ReadableContentSource,
    UploadLease,
)
from eneo.object_content.inline_content_store import InlineContentStore
from eneo.object_content.lease import OperationLeaseCheckpoint
from eneo.object_content.reconciliation_repository import (
    ObjectContentReconciliationRepository,
    PublicationReservation,
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


# This is an internal PostgreSQL bind/query chunk, not a user-visible content
# limit. Larger requests are processed across multiple bounded pages.
_READ_BATCH_MAX_ITEMS = 500


@dataclass(frozen=True, slots=True)
class VerifiedObjectUpload:
    object_key: str
    sha256: bytes
    size_bytes: int
    declared_media_type: str
    verified_media_type: str


@dataclass(frozen=True, slots=True)
class VerifiedObjectPublication:
    lease_owner: str
    uploads: tuple[VerifiedObjectUpload, ...]


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

    @asynccontextmanager
    async def capture_for_target(
        self,
        source: AsyncIterable[bytes],
        *,
        storage_kind: StorageKind,
        declared_media_type: str,
        verified_media_type: str,
        business_maximum_bytes: int | None = None,
    ) -> AsyncGenerator[CapturedContent]:
        if business_maximum_bytes is not None and business_maximum_bytes < 1:
            raise ValueError("business_maximum_bytes must be positive")
        if storage_kind is StorageKind.POSTGRES_INLINE:
            maximum_size_bytes = (
                self._core_settings.inline_maximum_bytes
                if business_maximum_bytes is None
                else min(
                    business_maximum_bytes,
                    self._core_settings.inline_maximum_bytes,
                )
            )
            spool_memory_bytes = self._core_settings.inline_io_chunk_bytes
            multipart_part_bytes = self._core_settings.inline_io_chunk_bytes
        else:
            if business_maximum_bytes is None:
                raise ValueError(
                    "business_maximum_bytes is required for object-store capture"
                )
            settings, _store = self._require_object_store()
            maximum_size_bytes = min(
                business_maximum_bytes,
                settings.maximum_multipart_bytes,
            )
            spool_memory_bytes = settings.spool_memory_bytes
            multipart_part_bytes = settings.multipart_part_bytes
        async with capture_content(
            source,
            declared_media_type=declared_media_type,
            verified_media_type=verified_media_type,
            maximum_size_bytes=maximum_size_bytes,
            spool_memory_bytes=spool_memory_bytes,
            multipart_part_bytes=multipart_part_bytes,
        ) as captured:
            yield captured

    async def ensure_target_ready(self, storage_kind: StorageKind) -> None:
        if storage_kind is StorageKind.OBJECT_STORE:
            await self.check_object_store_ready()

    @asynccontextmanager
    async def upload_for_publication(
        self,
        contents: Sequence[CapturedContent],
    ) -> AsyncGenerator[VerifiedObjectPublication]:
        if not contents:
            raise ValueError("Object publication requires at least one content item")
        settings, store = self._require_object_store()
        lease_owner = token_hex(16)
        reservations = tuple(
            PublicationReservation(
                object_key=new_object_key(settings),
                size_bytes=content.size_bytes,
            )
            for content in contents
        )
        lease_started_at = monotonic()
        try:
            async with self._database.session() as session, session.begin():
                await ObjectContentReconciliationRepository(
                    session
                ).reserve_publication_objects(
                    reservations,
                    lease_owner=lease_owner,
                    lease_seconds=settings.reconciliation_lease_seconds,
                    orphan_grace_seconds=settings.orphan_grace_seconds,
                )
        except ObjectContentBusyError as error:
            raise ObjectContentUnavailableError(
                "Durable object publication is temporarily unavailable"
            ) from error
        except (OSError, SQLAlchemyError) as error:
            raise ObjectContentUnavailableError(
                "Unable to reserve durable object publication"
            ) from error

        async def renew_publication_reservations() -> None:
            async with self._database.session() as session, session.begin():
                await ObjectContentReconciliationRepository(
                    session
                ).renew_publication_reservations(
                    reservations,
                    lease_owner=lease_owner,
                    lease_seconds=settings.reconciliation_lease_seconds,
                )

        checkpoint = OperationLeaseCheckpoint(
            lease_started_at=lease_started_at,
            lease_seconds=settings.reconciliation_lease_seconds,
            request_budget_seconds=settings.sdk_request_budget_seconds,
            renew=renew_publication_reservations,
        )
        try:
            try:
                uploads: list[VerifiedObjectUpload] = []
                for reservation, content in zip(reservations, contents, strict=True):
                    await store.upload(
                        reservation.object_key,
                        content,
                        operation_checkpoint=checkpoint,
                    )
                    uploads.append(
                        VerifiedObjectUpload(
                            object_key=reservation.object_key,
                            sha256=content.sha256,
                            size_bytes=content.size_bytes,
                            declared_media_type=content.declared_media_type,
                            verified_media_type=content.verified_media_type,
                        )
                    )
            except ObjectStoreIntegrityError as error:
                raise ObjectContentIntegrityError(
                    "Durable object verification failed"
                ) from error
            except (ObjectContentBusyError, ObjectStoreUnavailableError) as error:
                raise ObjectContentUnavailableError(
                    "Durable object content is temporarily unavailable"
                ) from error
            except (OSError, SQLAlchemyError) as error:
                raise ObjectContentUnavailableError(
                    "Unable to renew durable object publication"
                ) from error

            yield VerifiedObjectPublication(
                lease_owner=lease_owner,
                uploads=tuple(uploads),
            )
        finally:
            try:
                async with self._database.session() as session, session.begin():
                    await ObjectContentReconciliationRepository(
                        session
                    ).release_publication_reservations(
                        reservations,
                        lease_owner=lease_owner,
                    )
            except (OSError, SQLAlchemyError):
                # The bounded lease expires after a process or database failure;
                # the existing orphan inventory remains the durable cleanup owner.
                pass

    async def adopt_verified_in_transaction(
        self,
        session: AsyncSession,
        *,
        intents: Sequence[ContentIntent],
        contents: Sequence[CapturedContent],
        publication: VerifiedObjectPublication,
    ) -> tuple[PreparedContent, ...]:
        if not session.in_transaction():
            raise RuntimeError("Verified publication requires an owning transaction")
        if len(intents) != len(contents) or len(contents) != len(publication.uploads):
            raise ValueError("Verified publication inputs must have equal lengths")

        reservations: list[PublicationReservation] = []
        for content, upload in zip(contents, publication.uploads, strict=True):
            if (
                upload.sha256 != content.sha256
                or upload.size_bytes != content.size_bytes
                or upload.declared_media_type != content.declared_media_type
                or upload.verified_media_type != content.verified_media_type
            ):
                raise ObjectContentStateError(
                    "Verified publication does not match captured content"
                )
            reservations.append(
                PublicationReservation(
                    object_key=upload.object_key,
                    size_bytes=upload.size_bytes,
                )
            )

        await ObjectContentReconciliationRepository(
            session
        ).consume_publication_reservations(
            reservations,
            lease_owner=publication.lease_owner,
        )
        repository = ObjectContentRepository(session)
        prepared: list[PreparedContent] = []
        for intent, content, upload in zip(
            intents,
            contents,
            publication.uploads,
            strict=True,
        ):
            prepared.append(
                await repository.prepare_verified_object_store(
                    intent=intent,
                    content=content,
                    object_key=upload.object_key,
                    request_fingerprint=content_request_fingerprint(
                        intent,
                        content,
                        StorageKind.OBJECT_STORE,
                    ),
                )
            )
        return tuple(prepared)

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
                # Keep PENDING for persisted rows and explicit store_and_verify
                # recovery. Delete it only after a database audit finds no such
                # rows and every live producer/cutover uses verified publication.
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
            sources = await ObjectContentRepository(session).get_readable_sources(
                [grant]
            )
        source = sources[grant.content_id]
        byte_range = (
            None
            if range_header is None
            else ByteRange.parse(
                range_header,
                size_bytes=source.content.size_bytes,
            )
        )
        async with self._open_readable_source(
            source,
            byte_range=byte_range,
        ) as opened:
            yield opened

    @asynccontextmanager
    async def _open_readable_source(
        self,
        source: ReadableContentSource,
        *,
        byte_range: ByteRange | None = None,
    ) -> AsyncGenerator[ContentRead]:
        content = source.content
        match content.storage_kind:
            case StorageKind.POSTGRES_INLINE:
                if source.inline_payload is None:
                    raise RuntimeError("Inline content dispatch lost its payload")
                try:
                    async with self._inline_store.open_verified_read(
                        source.inline_payload,
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
                if source.object_store_descriptor is None:
                    raise RuntimeError(
                        "Object-store content dispatch lost its descriptor"
                    )
                _settings, store = self._require_object_store()
                try:
                    async with store.open_verified_read(
                        source.object_store_descriptor.object_key,
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

    async def read_content_bytes(
        self,
        grants: Sequence[ContentReadGrant],
    ) -> dict[UUID, bytes]:
        """Materialize authorized content with one source query per bounded page.

        Controls plus inline payloads or private object-store descriptors are
        loaded and access-validated together. Both storage kinds then use the
        same verified backend dispatch; callers do not branch on placement.
        """
        unique_grants: dict[UUID, ContentReadGrant] = {}
        for grant in grants:
            existing = unique_grants.get(grant.content_id)
            if existing is not None and existing != grant:
                raise ObjectContentStateError(
                    "Conflicting access grants target the same object content"
                )
            unique_grants[grant.content_id] = grant

        ordered_grants = list(unique_grants.values())
        payloads: dict[UUID, bytes] = {}
        for offset in range(0, len(ordered_grants), _READ_BATCH_MAX_ITEMS):
            page = ordered_grants[offset : offset + _READ_BATCH_MAX_ITEMS]
            async with self._database.session() as session, session.begin():
                sources = await ObjectContentRepository(session).get_readable_sources(
                    page
                )

            for grant in page:
                source = sources[grant.content_id]
                payloads[grant.content_id] = await self._read_source_bytes(
                    source,
                )
        return payloads

    async def _read_source_bytes(
        self,
        source: ReadableContentSource,
    ) -> bytes:
        async with self._open_readable_source(source) as opened:
            return b"".join([chunk async for chunk in opened.chunks])

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
