from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from secrets import token_hex
from tempfile import SpooledTemporaryFile
from time import monotonic

from eneo.database.database import DatabaseSessionManager
from eneo.object_content.configuration import (
    ObjectContentCoreSettings,
    ObjectContentSettings,
)
from eneo.object_content.content import (
    CapturedContent,
    ContentMoveFailureCode,
    ContentMoveState,
    ObjectContentBusyError,
    ObjectContentStateError,
    StorageKind,
    capture_content,
)
from eneo.object_content.content_service import retry_delay_seconds
from eneo.object_content.lease import OperationLeaseCheckpoint
from eneo.object_content.move_repository import (
    MoveWork,
    ObjectContentMoveRepository,
)
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


class ObjectContentMoveExecutor:
    """Move one content item without holding database locks during store I/O."""

    def __init__(
        self,
        core_settings: ObjectContentCoreSettings,
        database: DatabaseSessionManager,
        *,
        object_store_settings: ObjectContentSettings,
        object_store: S3ObjectStore,
    ) -> None:
        self._core_settings = core_settings
        self._database = database
        self._settings = object_store_settings
        self._store = object_store

    async def run_once(self) -> int:
        settings = self._settings
        lease_owner = token_hex(16)
        lease_started_at = monotonic()
        async with self._database.session() as session, session.begin():
            repository = ObjectContentMoveRepository(session)
            work = await repository.claim(
                lease_owner=lease_owner,
                lease_seconds=settings.reconciliation_lease_seconds,
            )
            if work is None and await repository.fail_one_ineligible():
                return 1
        if work is None:
            return 0

        if work.target_kind is StorageKind.OBJECT_STORE:
            await self._move_to_object_store(
                work,
                lease_owner=lease_owner,
                lease_started_at=lease_started_at,
            )
        else:
            await self._move_to_inline(
                work,
                lease_owner=lease_owner,
                lease_started_at=lease_started_at,
            )
        return 1

    async def _move_to_object_store(
        self,
        work: MoveWork,
        *,
        lease_owner: str,
        lease_started_at: float,
    ) -> None:
        settings = self._settings
        if work.size_bytes > settings.maximum_multipart_bytes:
            await self._record_move_failure(
                work,
                lease_owner,
                ContentMoveFailureCode.TARGET_TOO_LARGE,
                "content exceeds the current object-store target limit",
            )
            return
        payload = work.inline_payload
        if payload is None or len(payload) != work.size_bytes:
            await self._record_move_failure(
                work,
                lease_owner,
                ContentMoveFailureCode.SOURCE_CORRUPT,
                "inline source does not match canonical content",
            )
            return

        async def source_chunks() -> AsyncIterator[bytes]:
            for offset in range(0, len(payload), settings.io_chunk_bytes):
                yield payload[offset : offset + settings.io_chunk_bytes]

        async with capture_content(
            source_chunks(),
            declared_media_type=(work.declared_media_type or work.verified_media_type),
            verified_media_type=work.verified_media_type,
            maximum_size_bytes=work.size_bytes,
            spool_memory_bytes=settings.spool_memory_bytes,
            multipart_part_bytes=settings.multipart_part_bytes,
        ) as captured:
            if captured.sha256 != work.sha256:
                await self._record_move_failure(
                    work,
                    lease_owner,
                    ContentMoveFailureCode.SOURCE_CORRUPT,
                    "inline source does not match canonical content",
                )
                return

            await self._publish_captured_object_target(
                work,
                captured=captured,
                lease_owner=lease_owner,
                lease_started_at=lease_started_at,
            )

    async def _publish_captured_object_target(
        self,
        work: MoveWork,
        *,
        captured: CapturedContent,
        lease_owner: str,
        lease_started_at: float,
    ) -> None:
        settings, store = self._settings, self._store
        object_key = work.target_object_key or new_object_key(settings)
        if work.target_object_key is None:
            try:
                async with self._database.session() as session, session.begin():
                    await ObjectContentMoveRepository(session).record_object_target(
                        content_id=work.content_id,
                        lease_owner=lease_owner,
                        object_key=object_key,
                    )
            except (ObjectContentBusyError, ObjectContentStateError):
                return

        reservation = PublicationReservation(
            object_key=object_key,
            size_bytes=work.size_bytes,
        )
        publication_lease_owner = lease_owner
        try:
            async with self._database.session() as session, session.begin():
                await ObjectContentReconciliationRepository(
                    session
                ).reserve_publication_objects(
                    (reservation,),
                    lease_owner=publication_lease_owner,
                    lease_seconds=settings.reconciliation_lease_seconds,
                    orphan_grace_seconds=settings.orphan_grace_seconds,
                )
        except ObjectContentBusyError:
            await self._record_move_retry(
                work,
                lease_owner,
                failure_code=None,
                detail=None,
            )
            return

        async def renew_move_and_publication() -> None:
            async with self._database.session() as session, session.begin():
                await ObjectContentMoveRepository(session).renew_lease(
                    content_id=work.content_id,
                    lease_owner=lease_owner,
                    lease_seconds=settings.reconciliation_lease_seconds,
                )
                await ObjectContentReconciliationRepository(
                    session
                ).renew_publication_reservations(
                    (reservation,),
                    lease_owner=publication_lease_owner,
                    lease_seconds=settings.reconciliation_lease_seconds,
                )

        checkpoint = OperationLeaseCheckpoint(
            lease_started_at=lease_started_at,
            lease_seconds=settings.reconciliation_lease_seconds,
            request_budget_seconds=settings.sdk_request_budget_seconds,
            renew=renew_move_and_publication,
        )
        try:
            await store.upload(
                object_key,
                captured,
                operation_checkpoint=checkpoint,
            )
            if work.state is ContentMoveState.PENDING:
                async with self._database.session() as session, session.begin():
                    await ObjectContentMoveRepository(session).record_target_verified(
                        content_id=work.content_id,
                        lease_owner=lease_owner,
                        object_key=object_key,
                        verification_chunk_size_bytes=captured.part_size_bytes,
                        verification_chunk_sha256=b"".join(captured.part_sha256),
                    )
            async with self._database.session() as session, session.begin():
                await ObjectContentMoveRepository(session).complete_to_object_store(
                    content_id=work.content_id,
                    lease_owner=lease_owner,
                    reservation=reservation,
                    publication_lease_owner=publication_lease_owner,
                )
        except ObjectStoreUnavailableError:
            await self._record_move_retry(work, lease_owner)
        except ObjectStoreIntegrityError:
            await self._record_move_failure(
                work,
                lease_owner,
                ContentMoveFailureCode.TARGET_CORRUPT,
                "object-store target verification failed",
            )
        except (ObjectContentBusyError, ObjectContentStateError):
            await self._record_move_failure(
                work,
                lease_owner,
                ContentMoveFailureCode.CONTENT_INELIGIBLE,
                "content changed before the authority flip",
            )
        finally:
            async with self._database.session() as session, session.begin():
                await ObjectContentReconciliationRepository(
                    session
                ).release_publication_reservations(
                    (reservation,),
                    lease_owner=publication_lease_owner,
                )

    async def _move_to_inline(
        self,
        work: MoveWork,
        *,
        lease_owner: str,
        lease_started_at: float,
    ) -> None:
        settings, store = self._settings, self._store
        if work.size_bytes > self._core_settings.inline_maximum_bytes:
            await self._record_move_failure(
                work,
                lease_owner,
                ContentMoveFailureCode.TARGET_TOO_LARGE,
                "content exceeds the current inline target limit",
            )
            return
        source_object_key = work.source_object_key
        if source_object_key is None:
            await self._record_move_failure(
                work,
                lease_owner,
                ContentMoveFailureCode.SOURCE_MISSING,
                "object-store source descriptor is missing",
            )
            return

        async def renew_move() -> None:
            async with self._database.session() as session, session.begin():
                await ObjectContentMoveRepository(session).renew_lease(
                    content_id=work.content_id,
                    lease_owner=lease_owner,
                    lease_seconds=settings.reconciliation_lease_seconds,
                )

        checkpoint = OperationLeaseCheckpoint(
            lease_started_at=lease_started_at,
            lease_seconds=settings.reconciliation_lease_seconds,
            request_budget_seconds=settings.sdk_request_budget_seconds,
            renew=renew_move,
        )

        async def read_verified_source() -> bytes:
            spool: SpooledTemporaryFile[bytes] = SpooledTemporaryFile(
                max_size=settings.spool_memory_bytes,
                mode="w+b",
            )
            captured_size_bytes = 0
            try:
                async with store.open_verified_read(
                    source_object_key,
                    expected_sha256=work.sha256,
                    expected_size_bytes=work.size_bytes,
                    expected_media_type=work.verified_media_type,
                ) as opened:
                    async for chunk in opened.chunks:
                        captured_size_bytes += len(chunk)
                        if (
                            captured_size_bytes
                            > self._core_settings.inline_maximum_bytes
                        ):
                            raise ObjectStoreIntegrityError(
                                "Inline move target exceeded its configured bound"
                            )
                        written = await asyncio.to_thread(spool.write, chunk)
                        if written != len(chunk):
                            raise ObjectStoreIntegrityError(
                                "Inline move spool accepted a partial write"
                            )
                if captured_size_bytes != work.size_bytes:
                    raise ObjectStoreIntegrityError(
                        "Inline move target has the wrong size"
                    )
                await asyncio.to_thread(spool.seek, 0)
                return await asyncio.to_thread(spool.read)
            finally:
                await asyncio.to_thread(spool.close)

        try:
            payload = await checkpoint.run(read_verified_source)
        except ObjectStoreNotFoundError:
            await self._record_move_failure(
                work,
                lease_owner,
                ContentMoveFailureCode.SOURCE_MISSING,
                "object-store source is missing",
            )
            return
        except ObjectStoreIntegrityError:
            await self._record_move_failure(
                work,
                lease_owner,
                ContentMoveFailureCode.SOURCE_CORRUPT,
                "object-store source does not match canonical content",
            )
            return
        except ObjectStoreUnavailableError:
            await self._record_move_retry(work, lease_owner)
            return
        except (ObjectContentBusyError, ObjectContentStateError):
            return

        try:
            async with self._database.session() as session, session.begin():
                await ObjectContentMoveRepository(session).complete_to_inline(
                    content_id=work.content_id,
                    lease_owner=lease_owner,
                    payload=payload,
                    captured_size_bytes=len(payload),
                    captured_sha256=work.sha256,
                    orphan_grace_seconds=settings.orphan_grace_seconds,
                )
        except (ObjectContentBusyError, ObjectContentStateError):
            await self._record_move_failure(
                work,
                lease_owner,
                ContentMoveFailureCode.CONTENT_INELIGIBLE,
                "content changed before the authority flip",
            )

    async def _record_move_retry(
        self,
        work: MoveWork,
        lease_owner: str,
        *,
        failure_code: ContentMoveFailureCode | None = (
            ContentMoveFailureCode.STORE_UNAVAILABLE
        ),
        detail: str | None = ("compatible object storage is temporarily unavailable"),
    ) -> None:
        delay = retry_delay_seconds(
            work.attempt_count,
            base_seconds=self._core_settings.reconciliation_retry_base_seconds,
            maximum_seconds=self._core_settings.reconciliation_retry_max_seconds,
        )
        async with self._database.session() as session, session.begin():
            await ObjectContentMoveRepository(session).record_retry(
                content_id=work.content_id,
                lease_owner=lease_owner,
                retry_delay_seconds=delay,
                failure_code=failure_code,
                detail=detail,
            )

    async def _record_move_failure(
        self,
        work: MoveWork,
        lease_owner: str,
        failure_code: ContentMoveFailureCode,
        detail: str,
    ) -> None:
        async with self._database.session() as session, session.begin():
            await ObjectContentMoveRepository(session).record_failure(
                content_id=work.content_id,
                lease_owner=lease_owner,
                failure_code=failure_code,
                detail=detail,
            )
