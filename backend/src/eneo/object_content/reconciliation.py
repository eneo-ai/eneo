from __future__ import annotations

import asyncio
from dataclasses import dataclass
from secrets import token_hex
from time import monotonic
from uuid import UUID

from eneo.database.database import DatabaseSessionManager, sessionmanager
from eneo.object_content.configuration import (
    ObjectContentCoreSettings,
    ObjectContentSettings,
)
from eneo.object_content.content import (
    ContentFailureCode,
    ContentState,
    ObjectContentBusyError,
    ObjectContentStateError,
)
from eneo.object_content.content_repository import ObjectContentRepository
from eneo.object_content.content_service import retry_delay_seconds
from eneo.object_content.lease import OperationLeaseCheckpoint
from eneo.object_content.reconciliation_repository import (
    MultipartAbortLease,
    ObjectContentHealthFacts,
    ObjectContentReconciliationRepository,
    OrphanDeleteLease,
    ReconciliationWork,
)
from eneo.object_content.s3_object_store import (
    ObjectStoreIntegrityError,
    ObjectStoreNotFoundError,
    ObjectStoreUnavailableError,
    S3ObjectStore,
)


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    lifecycle_advanced: int
    inline_deleted: int
    content_processed: int
    references_audited: int
    reference_drifts: int
    missing_objects: int
    object_cycle_completed: bool
    multipart_aborted: int
    orphan_objects_deleted: int

    @classmethod
    def empty(cls) -> "ReconciliationResult":
        return cls(
            lifecycle_advanced=0,
            inline_deleted=0,
            content_processed=0,
            references_audited=0,
            reference_drifts=0,
            missing_objects=0,
            object_cycle_completed=False,
            multipart_aborted=0,
            orphan_objects_deleted=0,
        )


class ObjectContentReconciler:
    """Converge one bounded page/batch without holding DB locks during S3 I/O."""

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
        self._store = object_store
        self._database = database

    async def run_once(self) -> ReconciliationResult:
        async with self._database.session() as session, session.begin():
            repository = ObjectContentReconciliationRepository(session)
            lifecycle_advanced = await repository.advance_local_lifecycle(
                limit=self._core_settings.reconciliation_batch_size,
                pending_stale_seconds=self._core_settings.pending_stale_seconds,
            )
            inline_deleted = await repository.tombstone_inline_deletions(
                limit=self._core_settings.reconciliation_batch_size,
            )

        settings = self._object_store_settings
        store = self._store
        if settings is None or store is None:
            async with self._database.session() as session, session.begin():
                (
                    references_audited,
                    reference_drifts,
                ) = await ObjectContentReconciliationRepository(
                    session
                ).audit_reference_counts(
                    limit=self._core_settings.reconciliation_batch_size
                )
            return ReconciliationResult(
                lifecycle_advanced=lifecycle_advanced,
                inline_deleted=inline_deleted,
                content_processed=0,
                references_audited=references_audited,
                reference_drifts=reference_drifts,
                missing_objects=0,
                object_cycle_completed=False,
                multipart_aborted=0,
                orphan_objects_deleted=0,
            )

        lease_owner = token_hex(16)
        content_lease_started_at = monotonic()
        async with self._database.session() as session, session.begin():
            repository = ObjectContentReconciliationRepository(session)
            work = await repository.claim_content_work(
                lease_owner=lease_owner,
                lease_seconds=settings.reconciliation_lease_seconds,
                pending_stale_seconds=settings.pending_stale_seconds,
                limit=min(
                    settings.reconciliation_batch_size,
                    settings.reconciliation_concurrency,
                ),
            )

        await asyncio.gather(
            *(
                self._process_content(
                    item,
                    lease_owner,
                    lease_started_at=content_lease_started_at,
                )
                for item in work
            )
        )

        try:
            object_cycle_completed = await self._reconcile_object_page()
            async with self._database.session() as session, session.begin():
                missing_objects = await ObjectContentReconciliationRepository(
                    session
                ).mark_missing_from_completed_inventory(
                    limit=settings.reconciliation_batch_size
                )
            multipart_aborted = await self._reconcile_multipart_page()
            orphan_objects_deleted = await self._delete_orphans(lease_owner)
        except ObjectStoreUnavailableError:
            object_cycle_completed = False
            missing_objects = 0
            multipart_aborted = 0
            orphan_objects_deleted = 0
        async with self._database.session() as session, session.begin():
            (
                references_audited,
                reference_drifts,
            ) = await ObjectContentReconciliationRepository(
                session
            ).audit_reference_counts(
                limit=self._core_settings.reconciliation_batch_size
            )
        return ReconciliationResult(
            lifecycle_advanced=lifecycle_advanced,
            inline_deleted=inline_deleted,
            content_processed=len(work),
            references_audited=references_audited,
            reference_drifts=reference_drifts,
            missing_objects=missing_objects,
            object_cycle_completed=object_cycle_completed,
            multipart_aborted=multipart_aborted,
            orphan_objects_deleted=orphan_objects_deleted,
        )

    async def health_facts(self) -> ObjectContentHealthFacts:
        async with self._database.session() as session, session.begin():
            return await ObjectContentReconciliationRepository(session).health_facts()

    async def _process_content(
        self,
        work: ReconciliationWork,
        lease_owner: str,
        *,
        lease_started_at: float,
    ) -> None:
        if work.state is ContentState.PENDING:
            await self._reconcile_pending(
                work,
                lease_owner,
                lease_started_at=lease_started_at,
            )
            return
        if work.state is ContentState.DELETE_PENDING:
            await self._reconcile_delete(
                work,
                lease_owner,
                lease_started_at=lease_started_at,
            )
            return
        raise RuntimeError(f"Unsupported reconciliation state: {work.state}")

    async def _reconcile_pending(
        self,
        work: ReconciliationWork,
        lease_owner: str,
        *,
        lease_started_at: float,
    ) -> None:
        settings, store = self._require_object_store()

        async def renew_pending_lease() -> None:
            async with self._database.session() as session, session.begin():
                await ObjectContentRepository(session).renew_pending_lease(
                    content_id=work.content_id,
                    lease_owner=lease_owner,
                    lease_seconds=settings.reconciliation_lease_seconds,
                )

        lease_checkpoint = OperationLeaseCheckpoint(
            lease_started_at=lease_started_at,
            lease_seconds=settings.reconciliation_lease_seconds,
            request_budget_seconds=settings.sdk_request_budget_seconds,
            renew=renew_pending_lease,
        )

        try:
            if work.multipart_upload_id is not None:
                await store.abort_multipart(
                    work.object_key,
                    work.multipart_upload_id,
                    operation_checkpoint=lease_checkpoint,
                )
            digest = await store.recompute_sha256(
                work.object_key,
                expected_size_bytes=work.size_bytes,
                expected_media_type=work.media_type,
                operation_checkpoint=lease_checkpoint,
            )
        except ObjectStoreNotFoundError:
            async with self._database.session() as session, session.begin():
                await ObjectContentRepository(session).record_pending_missing(
                    content_id=work.content_id,
                    lease_owner=lease_owner,
                )
            return
        except ObjectStoreIntegrityError:
            await self._record_integrity_failure(work.content_id, lease_owner)
            return
        except ObjectStoreUnavailableError:
            await self._record_retry(work, lease_owner)
            return
        except (ObjectContentBusyError, ObjectContentStateError):
            # An expired lease may legally move to another reconciler while a
            # stalled process resumes. The current lease owner will converge it.
            return

        if digest != work.sha256:
            await self._record_integrity_failure(work.content_id, lease_owner)
            return
        try:
            async with self._database.session() as session, session.begin():
                await ObjectContentRepository(session).promote_available(
                    content_id=work.content_id,
                    lease_owner=lease_owner,
                )
        except ObjectContentStateError:
            # A final owner detach can legally win while the remote verification runs.
            return

    async def _reconcile_delete(
        self,
        work: ReconciliationWork,
        lease_owner: str,
        *,
        lease_started_at: float,
    ) -> None:
        settings, store = self._require_object_store()

        async def renew_delete_lease() -> None:
            async with self._database.session() as session, session.begin():
                await ObjectContentRepository(session).renew_delete_lease(
                    content_id=work.content_id,
                    lease_owner=lease_owner,
                    lease_seconds=settings.reconciliation_lease_seconds,
                )

        lease_checkpoint = OperationLeaseCheckpoint(
            lease_started_at=lease_started_at,
            lease_seconds=settings.reconciliation_lease_seconds,
            request_budget_seconds=settings.sdk_request_budget_seconds,
            renew=renew_delete_lease,
        )
        try:
            await store.delete_and_confirm(
                work.object_key,
                operation_checkpoint=lease_checkpoint,
            )
        except ObjectStoreUnavailableError:
            await self._record_retry(work, lease_owner)
            return
        except (ObjectContentBusyError, ObjectContentStateError):
            return
        try:
            async with self._database.session() as session, session.begin():
                await ObjectContentRepository(session).mark_tombstoned(
                    content_id=work.content_id,
                    lease_owner=lease_owner,
                    # WI-26B's database-owned retention policy supplies this horizon.
                    # The foundation must not invent an environment business policy.
                    purge_after=None,
                )
        except (ObjectContentBusyError, ObjectContentStateError):
            return

    async def _record_integrity_failure(
        self,
        content_id: UUID,
        lease_owner: str,
    ) -> None:
        async with self._database.session() as session, session.begin():
            await ObjectContentRepository(session).record_integrity_failure(
                content_id=content_id,
                lease_owner=lease_owner,
            )

    async def _record_retry(
        self,
        work: ReconciliationWork,
        lease_owner: str,
    ) -> None:
        failure_code = (
            ContentFailureCode.UPLOAD_RETRYABLE
            if work.state is ContentState.PENDING
            else ContentFailureCode.DELETE_RETRYABLE
        )
        delay = retry_delay_seconds(
            work.attempt_count,
            base_seconds=self._core_settings.reconciliation_retry_base_seconds,
            maximum_seconds=self._core_settings.reconciliation_retry_max_seconds,
        )
        async with self._database.session() as session, session.begin():
            await ObjectContentRepository(session).record_reconciliation_retry(
                content_id=work.content_id,
                lease_owner=lease_owner,
                failure_code=failure_code,
                retry_delay_seconds=delay,
            )

    async def _reconcile_object_page(self) -> bool:
        settings, store = self._require_object_store()
        async with self._database.session() as session, session.begin():
            cursor = await ObjectContentReconciliationRepository(
                session
            ).object_inventory_cursor()
        page = await store.list_object_page(
            continuation_token=cursor.continuation_token
        )
        async with self._database.session() as session, session.begin():
            return await ObjectContentReconciliationRepository(
                session
            ).record_object_page(
                cursor=cursor,
                objects=page.objects,
                next_token=page.next_token,
                orphan_grace_seconds=settings.orphan_grace_seconds,
            )

    async def _reconcile_multipart_page(self) -> int:
        settings, store = self._require_object_store()
        async with self._database.session() as session, session.begin():
            cursor = await ObjectContentReconciliationRepository(
                session
            ).multipart_inventory_cursor()
        page = await store.list_multipart_page(
            key_marker=cursor.key_marker,
            upload_id_marker=cursor.upload_id_marker,
        )
        async with self._database.session() as session, session.begin():
            await ObjectContentReconciliationRepository(session).record_multipart_page(
                cursor=cursor,
                uploads=page.uploads,
                next_key_marker=page.next_key_marker,
                next_upload_id_marker=page.next_upload_id_marker,
                orphan_grace_seconds=settings.orphan_grace_seconds,
            )
        multipart_lease_owner = token_hex(16)
        async with self._database.session() as session, session.begin():
            abortable = await ObjectContentReconciliationRepository(
                session
            ).claim_multipart_aborts(
                lease_owner=multipart_lease_owner,
                lease_seconds=settings.reconciliation_lease_seconds,
                limit=min(
                    settings.reconciliation_batch_size,
                    settings.reconciliation_concurrency,
                ),
            )
        results = await asyncio.gather(
            *(
                self._abort_multipart(lease, multipart_lease_owner)
                for lease in abortable
            )
        )
        return sum(results)

    async def _abort_multipart(
        self,
        lease: MultipartAbortLease,
        lease_owner: str,
    ) -> int:
        settings, store = self._require_object_store()
        lease_started_at = monotonic()
        async with self._database.session() as session, session.begin():
            confirmed = await ObjectContentReconciliationRepository(
                session
            ).confirm_multipart_abort_lease(
                lease=lease,
                lease_owner=lease_owner,
                lease_seconds=settings.reconciliation_lease_seconds,
            )
        if not confirmed:
            return 0

        async def renew_multipart_abort_lease() -> None:
            async with self._database.session() as session, session.begin():
                await ObjectContentReconciliationRepository(
                    session
                ).renew_multipart_abort_lease(
                    lease=lease,
                    lease_owner=lease_owner,
                    lease_seconds=settings.reconciliation_lease_seconds,
                )

        lease_checkpoint = OperationLeaseCheckpoint(
            lease_started_at=lease_started_at,
            lease_seconds=settings.reconciliation_lease_seconds,
            request_budget_seconds=settings.sdk_request_budget_seconds,
            renew=renew_multipart_abort_lease,
        )
        try:
            await store.abort_multipart(
                lease.object_key,
                lease.upload_id,
                operation_checkpoint=lease_checkpoint,
            )
        except ObjectStoreUnavailableError:
            async with self._database.session() as session, session.begin():
                await ObjectContentReconciliationRepository(
                    session
                ).release_multipart_abort(
                    lease=lease,
                    lease_owner=lease_owner,
                )
            return 0
        except (ObjectContentBusyError, ObjectContentStateError):
            return 0
        async with self._database.session() as session, session.begin():
            try:
                await ObjectContentReconciliationRepository(
                    session
                ).complete_multipart_abort(
                    lease=lease,
                    lease_owner=lease_owner,
                )
            except ObjectContentBusyError:
                return 0
        return 1

    async def _delete_orphans(self, lease_owner: str) -> int:
        settings, _store = self._require_object_store()
        lease_started_at = monotonic()
        async with self._database.session() as session, session.begin():
            leases = await ObjectContentReconciliationRepository(
                session
            ).claim_orphan_deletes(
                lease_owner=lease_owner,
                lease_seconds=settings.reconciliation_lease_seconds,
                limit=min(
                    settings.reconciliation_batch_size,
                    settings.reconciliation_concurrency,
                ),
            )
        results = await asyncio.gather(
            *(
                self._delete_orphan(
                    lease,
                    lease_owner,
                    lease_started_at=lease_started_at,
                )
                for lease in leases
            )
        )
        return sum(results)

    async def _delete_orphan(
        self,
        lease: OrphanDeleteLease,
        lease_owner: str,
        *,
        lease_started_at: float,
    ) -> int:
        settings, store = self._require_object_store()
        async with self._database.session() as session, session.begin():
            confirmed = await ObjectContentReconciliationRepository(
                session
            ).confirm_orphan_delete_lease(
                object_key=lease.object_key,
                lease_owner=lease_owner,
            )
        if not confirmed:
            return 0

        async def renew_orphan_delete_lease() -> None:
            async with self._database.session() as session, session.begin():
                await ObjectContentReconciliationRepository(
                    session
                ).renew_orphan_delete_lease(
                    object_key=lease.object_key,
                    lease_owner=lease_owner,
                    lease_seconds=settings.reconciliation_lease_seconds,
                )

        lease_checkpoint = OperationLeaseCheckpoint(
            lease_started_at=lease_started_at,
            lease_seconds=settings.reconciliation_lease_seconds,
            request_budget_seconds=settings.sdk_request_budget_seconds,
            renew=renew_orphan_delete_lease,
        )
        try:
            await store.delete_and_confirm(
                lease.object_key,
                operation_checkpoint=lease_checkpoint,
            )
        except ObjectStoreUnavailableError:
            async with self._database.session() as session, session.begin():
                await ObjectContentReconciliationRepository(
                    session
                ).release_orphan_delete(
                    object_key=lease.object_key,
                    lease_owner=lease_owner,
                )
            return 0
        except (ObjectContentBusyError, ObjectContentStateError):
            return 0
        async with self._database.session() as session, session.begin():
            await ObjectContentReconciliationRepository(session).complete_orphan_delete(
                object_key=lease.object_key,
                lease_owner=lease_owner,
            )
        return 1

    def _require_object_store(self) -> tuple[ObjectContentSettings, S3ObjectStore]:
        settings = self._object_store_settings
        store = self._store
        if settings is None or store is None:
            raise RuntimeError("Object-store reconciliation is not configured")
        return settings, store
