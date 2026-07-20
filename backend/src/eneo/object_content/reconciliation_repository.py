from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import (
    and_,
    delete,
    exists,
    func,
    or_,
    select,
    union_all,
    update,
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from eneo.database.tables.object_content_table import (
    FileContentReferences,
    IconContentReferences,
    InfoBlobContentReferences,
    ObjectContentHolds,
    ObjectContentMultipartCandidates,
    ObjectContentOrphanCandidates,
    ObjectContentReconciliationState,
    ObjectContents,
)
from eneo.object_content.content import (
    ContentFailureCode,
    ContentState,
    ObjectContentConfigurationError,
)
from eneo.object_content.s3_object_store import (
    MultipartUpload,
    RemoteObject,
)


@dataclass(frozen=True, slots=True)
class ReconciliationWork:
    content_id: UUID
    object_key: str
    state: ContentState
    sha256: bytes
    size_bytes: int
    media_type: str
    attempt_count: int
    multipart_upload_id: str | None


@dataclass(frozen=True, slots=True)
class StoreBinding:
    deployment_id: UUID
    binding_id: UUID
    confirmed: bool
    allow_create: bool


@dataclass(frozen=True, slots=True)
class ObjectInventoryCursor:
    cycle_id: UUID
    cycle_started_at: datetime
    continuation_token: str | None


@dataclass(frozen=True, slots=True)
class MultipartInventoryCursor:
    cycle_id: UUID
    key_marker: str | None
    upload_id_marker: str | None


@dataclass(frozen=True, slots=True)
class OrphanDeleteLease:
    object_key: str


@dataclass(frozen=True, slots=True)
class MultipartAbortLease:
    object_key: str
    upload_id: str


@dataclass(frozen=True, slots=True)
class ContentStateFacts:
    state: ContentState
    count: int
    size_bytes: int
    oldest_created_at: datetime | None


@dataclass(frozen=True, slots=True)
class ObjectContentHealthFacts:
    states: tuple[ContentStateFacts, ...]
    integrity_failures: int
    reference_drifts: int
    orphan_candidates: int
    oldest_orphan_created_at: datetime | None
    last_object_cycle_completed_at: datetime | None


def _no_concrete_references() -> ColumnElement[bool]:
    return and_(
        ~exists(
            select(FileContentReferences.content_id).where(
                FileContentReferences.content_id == ObjectContents.id
            )
        ),
        ~exists(
            select(InfoBlobContentReferences.content_id).where(
                InfoBlobContentReferences.content_id == ObjectContents.id
            )
        ),
        ~exists(
            select(IconContentReferences.content_id).where(
                IconContentReferences.content_id == ObjectContents.id
            )
        ),
    )


class ObjectContentReconciliationRepository:
    """Private batched SQL used only by the object-content reconciler."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def advance_local_lifecycle(
        self,
        *,
        limit: int,
        pending_stale_seconds: int,
    ) -> int:
        now = await self._database_now()
        stale_before = now - timedelta(seconds=pending_stale_seconds)
        lease_available = or_(
            ObjectContents.lease_until.is_(None),
            ObjectContents.lease_until <= now,
        )
        unowned_pending = (
            await self._session.scalars(
                select(ObjectContents)
                .where(
                    ObjectContents.state == ContentState.PENDING.value,
                    ObjectContents.reference_count == 0,
                    ObjectContents.updated_at <= stale_before,
                    lease_available,
                )
                .order_by(ObjectContents.updated_at, ObjectContents.id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).all()
        for row in unowned_pending:
            row.state = ContentState.FAILED.value
            row.failure_code = ContentFailureCode.OWNER_DETACHED.value
            row.failure_detail = "pending content has no initial owner"
            row.delete_requested_at = row.delete_requested_at or now
            row.next_attempt_at = now

        remaining = limit - len(unowned_pending)
        if remaining <= 0:
            await self._session.flush()
            return len(unowned_pending)

        active_hold = exists(
            select(ObjectContentHolds.id).where(
                ObjectContentHolds.content_id == ObjectContents.id,
                ObjectContentHolds.released_at.is_(None),
                or_(
                    ObjectContentHolds.expires_at.is_(None),
                    ObjectContentHolds.expires_at > now,
                ),
            )
        )
        retention_clear = and_(
            or_(
                ObjectContents.minimum_retain_until.is_(None),
                ObjectContents.minimum_retain_until <= now,
            ),
            ~active_hold,
        )
        eligible_retained = and_(
            ObjectContents.state == ContentState.RETAINED.value,
            retention_clear,
        )
        eligible_failed = and_(
            ObjectContents.state == ContentState.FAILED.value,
            ObjectContents.delete_requested_at.is_not(None),
            retention_clear,
        )
        deletions = (
            await self._session.scalars(
                select(ObjectContents)
                .where(
                    or_(eligible_retained, eligible_failed),
                    ObjectContents.reference_count == 0,
                    _no_concrete_references(),
                    lease_available,
                )
                .order_by(ObjectContents.updated_at, ObjectContents.id)
                .limit(remaining)
                .with_for_update(skip_locked=True)
            )
        ).all()
        for row in deletions:
            row.state = ContentState.DELETE_PENDING.value
            row.next_attempt_at = now
            row.failure_code = None
            row.failure_detail = None

        await self._session.flush()
        return len(unowned_pending) + len(deletions)

    async def claim_content_work(
        self,
        *,
        lease_owner: str,
        lease_seconds: int,
        pending_stale_seconds: int,
        limit: int,
    ) -> tuple[ReconciliationWork, ...]:
        now = await self._database_now()
        stale_before = now - timedelta(seconds=pending_stale_seconds)
        lease_available = or_(
            ObjectContents.lease_until.is_(None),
            ObjectContents.lease_until <= now,
        )
        pending_due = and_(
            ObjectContents.state == ContentState.PENDING.value,
            ObjectContents.reference_count > 0,
            or_(
                ObjectContents.next_attempt_at <= now,
                and_(
                    ObjectContents.next_attempt_at.is_(None),
                    ObjectContents.updated_at <= stale_before,
                ),
            ),
        )
        delete_due = and_(
            ObjectContents.state == ContentState.DELETE_PENDING.value,
            ObjectContents.reference_count == 0,
            ObjectContents.next_attempt_at <= now,
            _no_concrete_references(),
        )
        rows = (
            await self._session.scalars(
                select(ObjectContents)
                .where(
                    or_(pending_due, delete_due),
                    lease_available,
                    or_(
                        ObjectContents.failure_code.is_(None),
                        ObjectContents.failure_code
                        != ContentFailureCode.REFERENCE_DRIFT.value,
                    ),
                )
                .order_by(
                    func.coalesce(
                        ObjectContents.next_attempt_at,
                        ObjectContents.updated_at,
                    ),
                    ObjectContents.id,
                )
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).all()
        work: list[ReconciliationWork] = []
        for row in rows:
            row.lease_owner = lease_owner
            row.lease_until = now + timedelta(seconds=lease_seconds)
            row.attempt_count += 1
            row.next_attempt_at = None
            row.failure_code = None
            row.failure_detail = None
            work.append(
                ReconciliationWork(
                    content_id=row.id,
                    object_key=row.object_key,
                    state=ContentState(row.state),
                    sha256=row.sha256,
                    size_bytes=row.size_bytes,
                    media_type=row.verified_media_type,
                    attempt_count=row.attempt_count,
                    multipart_upload_id=row.multipart_upload_id,
                )
            )
        await self._session.flush()
        return tuple(work)

    async def audit_reference_counts(self, *, limit: int) -> tuple[int, int]:
        rows = (
            await self._session.scalars(
                select(ObjectContents)
                .where(ObjectContents.reference_audited_at.is_(None))
                .order_by(ObjectContents.id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).all()
        if not rows:
            return 0, 0

        content_ids = tuple(row.id for row in rows)
        reference_ids = union_all(
            select(FileContentReferences.content_id.label("content_id")).where(
                FileContentReferences.content_id.in_(content_ids)
            ),
            select(InfoBlobContentReferences.content_id.label("content_id")).where(
                InfoBlobContentReferences.content_id.in_(content_ids)
            ),
            select(IconContentReferences.content_id.label("content_id")).where(
                IconContentReferences.content_id.in_(content_ids)
            ),
        ).subquery()
        counted = await self._session.execute(
            select(reference_ids.c.content_id, func.count())
            .select_from(reference_ids)
            .group_by(reference_ids.c.content_id)
        )
        actual_counts = {content_id: count for content_id, count in counted.all()}
        now = await self._database_now()
        mismatches = 0
        for row in rows:
            actual = int(actual_counts.get(row.id, 0))
            if actual != row.reference_count:
                mismatches += 1
                row.failure_code = ContentFailureCode.REFERENCE_DRIFT.value
                row.failure_detail = f"reference count drift: recorded={row.reference_count}, actual={actual}"
                if row.state in {
                    ContentState.PENDING.value,
                    ContentState.AVAILABLE.value,
                }:
                    row.state = ContentState.FAILED.value
                    if actual == 0:
                        row.delete_requested_at = row.delete_requested_at or now
            row.reference_audited_at = now
        await self._session.flush()
        return len(rows), mismatches

    async def object_inventory_cursor(self) -> ObjectInventoryCursor:
        state = await self._state_for_update()
        return ObjectInventoryCursor(
            cycle_id=state.object_cycle_id,
            cycle_started_at=state.object_cycle_started_at,
            continuation_token=state.object_continuation_token,
        )

    async def record_object_page(
        self,
        *,
        cursor: ObjectInventoryCursor,
        objects: Sequence[RemoteObject],
        next_token: str | None,
        orphan_grace_seconds: int,
    ) -> bool:
        state = await self._state_for_update()
        if (
            state.object_cycle_id != cursor.cycle_id
            or state.object_continuation_token != cursor.continuation_token
        ):
            return False

        now = await self._database_now()
        keys = tuple(item.key for item in objects)
        known_rows: Sequence[ObjectContents]
        if keys:
            known_rows = (
                await self._session.scalars(
                    select(ObjectContents)
                    .where(ObjectContents.object_key.in_(keys))
                    .order_by(ObjectContents.id)
                    .with_for_update()
                )
            ).all()
        else:
            known_rows = ()
        known_by_key: dict[str, ObjectContents] = {
            row.object_key: row for row in known_rows
        }
        for item in objects:
            row = known_by_key.get(item.key)
            if row is None:
                continue
            row.remote_observed_at = now
            if row.size_bytes != item.size_bytes:
                if row.state == ContentState.AVAILABLE.value:
                    row.state = ContentState.FAILED.value
                row.failure_code = ContentFailureCode.REMOTE_CORRUPT.value
                row.failure_detail = "object inventory length differs from PostgreSQL"

        live_known_keys = tuple(
            key
            for key, row in known_by_key.items()
            if row.state != ContentState.TOMBSTONED.value
        )
        if live_known_keys:
            await self._session.execute(
                delete(ObjectContentOrphanCandidates).where(
                    ObjectContentOrphanCandidates.object_key.in_(live_known_keys)
                )
            )

        unexpected_objects = [
            item
            for item in objects
            if (row := known_by_key.get(item.key)) is None
            or row.state == ContentState.TOMBSTONED.value
        ]
        if unexpected_objects:
            eligible_after = now + timedelta(seconds=orphan_grace_seconds)
            statement = insert(ObjectContentOrphanCandidates).values(
                [
                    {
                        "object_key": item.key,
                        "size_bytes": item.size_bytes,
                        "observed_cycle_id": cursor.cycle_id,
                        "eligible_after": eligible_after,
                        "last_observed_at": now,
                    }
                    for item in unexpected_objects
                ]
            )
            await self._session.execute(
                statement.on_conflict_do_update(
                    index_elements=[ObjectContentOrphanCandidates.object_key],
                    set_={
                        "size_bytes": statement.excluded.size_bytes,
                        "observed_cycle_id": statement.excluded.observed_cycle_id,
                        "last_observed_at": now,
                    },
                )
            )

        state.object_continuation_token = next_token
        if next_token is not None:
            await self._session.flush()
            return False

        await self._session.execute(
            delete(ObjectContentOrphanCandidates).where(
                ObjectContentOrphanCandidates.observed_cycle_id != cursor.cycle_id
            )
        )
        await self._session.execute(
            update(ObjectContentOrphanCandidates)
            .where(ObjectContentOrphanCandidates.observed_cycle_id == cursor.cycle_id)
            .values(
                completed_observations=(
                    ObjectContentOrphanCandidates.completed_observations + 1
                )
            )
        )
        state.object_completed_cycles += 1
        state.last_completed_object_cycle_started_at = cursor.cycle_started_at
        state.last_object_cycle_completed_at = now
        state.object_cycle_id = uuid4()
        state.object_cycle_started_at = now
        state.object_continuation_token = None
        await self._session.flush()
        return True

    async def mark_missing_from_completed_inventory(self, *, limit: int) -> int:
        state = await self._state_for_update()
        cutoff = state.last_completed_object_cycle_started_at
        if cutoff is None:
            return 0
        rows = (
            await self._session.scalars(
                select(ObjectContents)
                .where(
                    ObjectContents.state == ContentState.AVAILABLE.value,
                    ObjectContents.available_at < cutoff,
                    or_(
                        ObjectContents.remote_observed_at.is_(None),
                        ObjectContents.remote_observed_at < cutoff,
                    ),
                )
                .order_by(ObjectContents.available_at, ObjectContents.id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).all()
        for row in rows:
            row.state = ContentState.FAILED.value
            row.failure_code = ContentFailureCode.REMOTE_MISSING.value
            row.failure_detail = "complete object inventory did not observe the object"
        await self._session.flush()
        return len(rows)

    async def claim_orphan_deletes(
        self,
        *,
        lease_owner: str,
        lease_seconds: int,
        limit: int,
    ) -> tuple[OrphanDeleteLease, ...]:
        now = await self._database_now()
        live_row_exists = exists(
            select(ObjectContents.id).where(
                ObjectContents.object_key == ObjectContentOrphanCandidates.object_key,
                ObjectContents.state != ContentState.TOMBSTONED.value,
            )
        )
        rows = (
            await self._session.scalars(
                select(ObjectContentOrphanCandidates)
                .where(
                    ObjectContentOrphanCandidates.completed_observations >= 2,
                    ObjectContentOrphanCandidates.last_observed_at
                    >= ObjectContentOrphanCandidates.eligible_after,
                    or_(
                        ObjectContentOrphanCandidates.lease_until.is_(None),
                        ObjectContentOrphanCandidates.lease_until <= now,
                    ),
                    ~live_row_exists,
                )
                .order_by(
                    ObjectContentOrphanCandidates.eligible_after,
                    ObjectContentOrphanCandidates.object_key,
                )
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).all()
        for row in rows:
            row.lease_owner = lease_owner
            row.lease_until = now + timedelta(seconds=lease_seconds)
        await self._session.flush()
        return tuple(OrphanDeleteLease(object_key=row.object_key) for row in rows)

    async def confirm_orphan_delete_lease(
        self,
        *,
        object_key: str,
        lease_owner: str,
    ) -> bool:
        candidate = (
            await self._session.scalars(
                select(ObjectContentOrphanCandidates)
                .where(
                    ObjectContentOrphanCandidates.object_key == object_key,
                    ObjectContentOrphanCandidates.lease_owner == lease_owner,
                )
                .with_for_update()
            )
        ).one_or_none()
        if candidate is None:
            return False
        live_content_exists = await self._session.scalar(
            select(
                exists(
                    select(ObjectContents.id).where(
                        ObjectContents.object_key == object_key,
                        ObjectContents.state != ContentState.TOMBSTONED.value,
                    )
                )
            )
        )
        return not bool(live_content_exists)

    async def complete_orphan_delete(
        self,
        *,
        object_key: str,
        lease_owner: str,
    ) -> None:
        await self._session.execute(
            delete(ObjectContentOrphanCandidates).where(
                ObjectContentOrphanCandidates.object_key == object_key,
                ObjectContentOrphanCandidates.lease_owner == lease_owner,
            )
        )

    async def release_orphan_delete(
        self,
        *,
        object_key: str,
        lease_owner: str,
    ) -> None:
        row = (
            await self._session.scalars(
                select(ObjectContentOrphanCandidates)
                .where(
                    ObjectContentOrphanCandidates.object_key == object_key,
                    ObjectContentOrphanCandidates.lease_owner == lease_owner,
                )
                .with_for_update()
            )
        ).one_or_none()
        if row is not None:
            row.lease_owner = None
            row.lease_until = None
            await self._session.flush()

    async def multipart_inventory_cursor(self) -> MultipartInventoryCursor:
        state = await self._state_for_update()
        return MultipartInventoryCursor(
            cycle_id=state.multipart_cycle_id,
            key_marker=state.multipart_key_marker,
            upload_id_marker=state.multipart_upload_id_marker,
        )

    async def record_multipart_page(
        self,
        *,
        cursor: MultipartInventoryCursor,
        uploads: Sequence[MultipartUpload],
        next_key_marker: str | None,
        next_upload_id_marker: str | None,
        orphan_grace_seconds: int,
    ) -> bool:
        state = await self._state_for_update()
        if (
            state.multipart_cycle_id != cursor.cycle_id
            or state.multipart_key_marker != cursor.key_marker
            or state.multipart_upload_id_marker != cursor.upload_id_marker
        ):
            return False
        now = await self._database_now()
        if uploads:
            eligible_after = now + timedelta(seconds=orphan_grace_seconds)
            statement = insert(ObjectContentMultipartCandidates).values(
                [
                    {
                        "object_key": upload.key,
                        "upload_id": upload.upload_id,
                        "provider_initiated_at": upload.initiated_at,
                        "observed_cycle_id": cursor.cycle_id,
                        "eligible_after": eligible_after,
                        "last_observed_at": now,
                    }
                    for upload in uploads
                ]
            )
            await self._session.execute(
                statement.on_conflict_do_update(
                    index_elements=[
                        ObjectContentMultipartCandidates.object_key,
                        ObjectContentMultipartCandidates.upload_id,
                    ],
                    set_={
                        "provider_initiated_at": func.coalesce(
                            ObjectContentMultipartCandidates.provider_initiated_at,
                            statement.excluded.provider_initiated_at,
                        ),
                        "observed_cycle_id": statement.excluded.observed_cycle_id,
                        "last_observed_at": now,
                    },
                )
            )
        completed = next_key_marker is None and next_upload_id_marker is None
        state.multipart_key_marker = next_key_marker
        state.multipart_upload_id_marker = next_upload_id_marker
        if completed:
            await self._session.execute(
                delete(ObjectContentMultipartCandidates).where(
                    ObjectContentMultipartCandidates.observed_cycle_id
                    != cursor.cycle_id
                )
            )
            await self._session.execute(
                update(ObjectContentMultipartCandidates)
                .where(
                    ObjectContentMultipartCandidates.observed_cycle_id
                    == cursor.cycle_id
                )
                .values(
                    completed_observations=(
                        ObjectContentMultipartCandidates.completed_observations + 1
                    )
                )
            )
            state.last_multipart_cycle_completed_at = now
            state.multipart_cycle_started_at = now
            state.multipart_cycle_id = uuid4()
        await self._session.flush()
        return completed

    async def claim_multipart_aborts(
        self,
        *,
        lease_owner: str,
        lease_seconds: int,
        limit: int,
    ) -> tuple[MultipartAbortLease, ...]:
        now = await self._database_now()
        active_upload = exists(
            select(ObjectContents.id).where(
                ObjectContents.object_key
                == ObjectContentMultipartCandidates.object_key,
                ObjectContents.multipart_upload_id
                == ObjectContentMultipartCandidates.upload_id,
                ObjectContents.state == ContentState.PENDING.value,
                ObjectContents.lease_until > now,
            )
        )
        rows = (
            await self._session.scalars(
                select(ObjectContentMultipartCandidates)
                .where(
                    ObjectContentMultipartCandidates.completed_observations >= 2,
                    ObjectContentMultipartCandidates.last_observed_at
                    >= ObjectContentMultipartCandidates.eligible_after,
                    or_(
                        ObjectContentMultipartCandidates.lease_until.is_(None),
                        ObjectContentMultipartCandidates.lease_until <= now,
                    ),
                    ~active_upload,
                )
                .order_by(
                    ObjectContentMultipartCandidates.eligible_after,
                    ObjectContentMultipartCandidates.object_key,
                    ObjectContentMultipartCandidates.upload_id,
                )
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).all()
        for row in rows:
            row.lease_owner = lease_owner
            row.lease_until = now + timedelta(seconds=lease_seconds)
        await self._session.flush()
        return tuple(
            MultipartAbortLease(object_key=row.object_key, upload_id=row.upload_id)
            for row in rows
        )

    async def confirm_multipart_abort_lease(
        self,
        *,
        lease: MultipartAbortLease,
        lease_owner: str,
        lease_seconds: int,
    ) -> bool:
        candidate = (
            await self._session.scalars(
                select(ObjectContentMultipartCandidates)
                .where(
                    ObjectContentMultipartCandidates.object_key == lease.object_key,
                    ObjectContentMultipartCandidates.upload_id == lease.upload_id,
                    ObjectContentMultipartCandidates.lease_owner == lease_owner,
                )
                .with_for_update()
            )
        ).one_or_none()
        if candidate is None:
            return False

        content = (
            await self._session.scalars(
                select(ObjectContents)
                .where(
                    ObjectContents.object_key == lease.object_key,
                    ObjectContents.multipart_upload_id == lease.upload_id,
                )
                .with_for_update()
            )
        ).one_or_none()
        if content is None or content.state != ContentState.PENDING.value:
            return True

        now = await self._database_now()
        if (
            content.lease_owner != lease_owner
            and content.lease_until is not None
            and content.lease_until > now
        ):
            candidate.lease_owner = None
            candidate.lease_until = None
            await self._session.flush()
            return False

        # Revoke an expired uploader before leaving PostgreSQL. Its next
        # checkpoint then fails, while another reconciler cannot claim this
        # content row until the remote abort completes or this fence expires.
        content.lease_owner = lease_owner
        content.lease_until = now + timedelta(seconds=lease_seconds)
        await self._session.flush()
        return True

    async def complete_multipart_abort(
        self,
        *,
        lease: MultipartAbortLease,
        lease_owner: str,
    ) -> None:
        await self._session.execute(
            delete(ObjectContentMultipartCandidates).where(
                ObjectContentMultipartCandidates.object_key == lease.object_key,
                ObjectContentMultipartCandidates.upload_id == lease.upload_id,
                ObjectContentMultipartCandidates.lease_owner == lease_owner,
            )
        )
        row = (
            await self._session.scalars(
                select(ObjectContents)
                .where(
                    ObjectContents.object_key == lease.object_key,
                    ObjectContents.multipart_upload_id == lease.upload_id,
                )
                .with_for_update()
            )
        ).one_or_none()
        if row is not None:
            row.multipart_upload_id = None
            row.multipart_initiated_at = None
            if row.lease_owner == lease_owner:
                row.lease_owner = None
                row.lease_until = None
            if row.state == ContentState.PENDING.value:
                row.next_attempt_at = await self._database_now()
        await self._session.flush()

    async def release_multipart_abort(
        self,
        *,
        lease: MultipartAbortLease,
        lease_owner: str,
    ) -> None:
        row = (
            await self._session.scalars(
                select(ObjectContentMultipartCandidates)
                .where(
                    ObjectContentMultipartCandidates.object_key == lease.object_key,
                    ObjectContentMultipartCandidates.upload_id == lease.upload_id,
                    ObjectContentMultipartCandidates.lease_owner == lease_owner,
                )
                .with_for_update()
            )
        ).one_or_none()
        if row is not None:
            row.lease_owner = None
            row.lease_until = None
        content = (
            await self._session.scalars(
                select(ObjectContents)
                .where(
                    ObjectContents.object_key == lease.object_key,
                    ObjectContents.multipart_upload_id == lease.upload_id,
                )
                .with_for_update()
            )
        ).one_or_none()
        if content is not None and content.lease_owner == lease_owner:
            content.lease_owner = None
            content.lease_until = None
        await self._session.flush()

    async def health_facts(self) -> ObjectContentHealthFacts:
        grouped = await self._session.execute(
            select(
                ObjectContents.state,
                func.count(),
                func.coalesce(func.sum(ObjectContents.size_bytes), 0),
                func.min(ObjectContents.created_at),
            ).group_by(ObjectContents.state)
        )
        states = tuple(
            ContentStateFacts(
                state=ContentState(state),
                count=int(count),
                size_bytes=int(size_bytes),
                oldest_created_at=oldest,
            )
            for state, count, size_bytes, oldest in grouped.all()
        )
        integrity_failures = await self._session.scalar(
            select(func.count()).where(
                ObjectContents.failure_code.in_(
                    (
                        ContentFailureCode.VERIFICATION_MISMATCH.value,
                        ContentFailureCode.REMOTE_MISSING.value,
                        ContentFailureCode.REMOTE_CORRUPT.value,
                    )
                )
            )
        )
        reference_drifts = await self._session.scalar(
            select(func.count()).where(
                ObjectContents.failure_code == ContentFailureCode.REFERENCE_DRIFT.value
            )
        )
        orphan_row = (
            await self._session.execute(
                select(
                    func.count(),
                    func.min(ObjectContentOrphanCandidates.created_at),
                )
            )
        ).one()
        last_cycle = await self._session.scalar(
            select(
                ObjectContentReconciliationState.last_object_cycle_completed_at
            ).where(ObjectContentReconciliationState.id == 1)
        )
        return ObjectContentHealthFacts(
            states=states,
            integrity_failures=int(integrity_failures or 0),
            reference_drifts=int(reference_drifts or 0),
            orphan_candidates=int(orphan_row[0]),
            oldest_orphan_created_at=orphan_row[1],
            last_object_cycle_completed_at=last_cycle,
        )

    async def get_or_initialize_store_binding(
        self,
        deployment_id: UUID,
    ) -> StoreBinding:
        state = await self._state_for_update()
        has_content = bool(
            await self._session.scalar(
                select(exists().where(ObjectContents.id.is_not(None)))
            )
        )
        if state.store_binding_id is None:
            if has_content:
                raise ObjectContentConfigurationError(
                    "Object-content storage binding is missing for existing records"
                )
            state.store_deployment_id = deployment_id
            state.store_binding_id = uuid4()
            await self._session.flush()
        elif state.store_deployment_id != deployment_id:
            raise ObjectContentConfigurationError(
                "Object-content deployment identity does not match PostgreSQL"
            )

        binding_id = state.store_binding_id
        stored_deployment_id = state.store_deployment_id
        if stored_deployment_id is None:
            raise RuntimeError("Object-content storage binding is incomplete")
        return StoreBinding(
            deployment_id=stored_deployment_id,
            binding_id=binding_id,
            confirmed=state.store_binding_confirmed_at is not None,
            allow_create=(state.store_binding_confirmed_at is None and not has_content),
        )

    async def confirm_store_binding(
        self,
        *,
        deployment_id: UUID,
        binding_id: UUID,
    ) -> None:
        state = await self._state_for_update()
        if (
            state.store_deployment_id != deployment_id
            or state.store_binding_id != binding_id
        ):
            raise ObjectContentConfigurationError(
                "Object-content storage binding changed during verification"
            )
        if state.store_binding_confirmed_at is None:
            state.store_binding_confirmed_at = await self._database_now()
            await self._session.flush()

    async def _state_for_update(self) -> ObjectContentReconciliationState:
        state = (
            await self._session.scalars(
                select(ObjectContentReconciliationState)
                .where(ObjectContentReconciliationState.id == 1)
                .with_for_update()
            )
        ).one_or_none()
        if state is None:
            raise RuntimeError("Object-content reconciliation state is missing")
        return state

    async def _database_now(self) -> datetime:
        now = await self._session.scalar(select(func.now()))
        if now is None:
            raise RuntimeError("PostgreSQL did not return its current time")
        return now
