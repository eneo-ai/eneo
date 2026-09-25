from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from eneo.database.tables.object_content_policy_table import (
    ObjectContentDeploymentPolicy,
)
from eneo.database.tables.object_content_table import (
    InlineContentPayloads,
    ObjectContentAuditEvents,
    ObjectContentMoves,
    ObjectContents,
    ObjectStoreObjects,
)
from eneo.object_content.content import (
    ContentMoveFailureCode,
    ContentMoveState,
    ContentState,
    ObjectContentBusyError,
    ObjectContentStateError,
    StorageKind,
)
from eneo.object_content.reconciliation_repository import (
    ObjectContentReconciliationRepository,
    PublicationReservation,
)


@dataclass(frozen=True, slots=True)
class MoveQueueResult:
    queued_count: int
    target_too_large_count: int


@dataclass(frozen=True, slots=True)
class MoveWork:
    content_id: UUID
    source_kind: StorageKind
    target_kind: StorageKind
    state: ContentMoveState
    sha256: bytes
    size_bytes: int
    declared_media_type: str | None
    verified_media_type: str
    inline_payload: bytes | None
    source_object_key: str | None
    target_object_key: str | None
    verification_chunk_size_bytes: int | None
    verification_chunk_sha256: bytes | None
    attempt_count: int


@dataclass(frozen=True, slots=True)
class MoveStateFacts:
    target_kind: StorageKind
    state: ContentMoveState
    failure_code: ContentMoveFailureCode | None
    count: int
    size_bytes: int
    oldest_updated_at: datetime | None


class ObjectContentMoveRepository:
    """Own the durable move state machine and its authority-flip transactions."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def state_facts(self) -> tuple[MoveStateFacts, ...]:
        rows = await self._session.execute(
            select(
                ObjectContentMoves.target_kind,
                ObjectContentMoves.state,
                ObjectContentMoves.failure_code,
                func.count(),
                func.coalesce(func.sum(ObjectContents.size_bytes), 0),
                func.min(ObjectContentMoves.updated_at),
            )
            .join(ObjectContents, ObjectContents.id == ObjectContentMoves.content_id)
            .group_by(
                ObjectContentMoves.target_kind,
                ObjectContentMoves.state,
                ObjectContentMoves.failure_code,
            )
            .order_by(
                ObjectContentMoves.target_kind,
                ObjectContentMoves.state,
                ObjectContentMoves.failure_code,
            )
        )
        return tuple(
            MoveStateFacts(
                target_kind=StorageKind(target_kind),
                state=ContentMoveState(state),
                failure_code=(
                    None
                    if failure_code is None
                    else ContentMoveFailureCode(failure_code)
                ),
                count=int(count),
                size_bytes=int(size_bytes),
                oldest_updated_at=oldest_updated_at,
            )
            for (
                target_kind,
                state,
                failure_code,
                count,
                size_bytes,
                oldest_updated_at,
            ) in rows.all()
        )

    async def queue(
        self,
        *,
        target_kind: StorageKind,
        limit: int,
        requested_by_user_id: UUID,
        target_maximum_bytes: int,
    ) -> MoveQueueResult:
        if not 1 <= limit <= 100:
            raise ValueError("Move queue limit must be between 1 and 100")
        if target_maximum_bytes < 1:
            raise ValueError("Move target maximum size must be positive")

        now = await self._database_now()
        source_kind = (
            StorageKind.POSTGRES_INLINE
            if target_kind is StorageKind.OBJECT_STORE
            else StorageKind.OBJECT_STORE
        )
        reusable_move = or_(
            ObjectContentMoves.content_id.is_(None),
            and_(
                ObjectContentMoves.state == ContentMoveState.FAILED.value,
                or_(
                    ObjectContentMoves.target_kind != target_kind.value,
                    ObjectContentMoves.failure_code
                    != ContentMoveFailureCode.TARGET_TOO_LARGE.value,
                    ObjectContents.size_bytes <= target_maximum_bytes,
                ),
            ),
        )
        rows = (
            await self._session.execute(
                select(ObjectContents, ObjectContentMoves)
                .outerjoin(
                    ObjectContentMoves,
                    ObjectContentMoves.content_id == ObjectContents.id,
                )
                .where(
                    ObjectContents.storage_kind == source_kind.value,
                    ObjectContents.state == ContentState.AVAILABLE.value,
                    ObjectContents.reference_count > 0,
                    ObjectContents.delete_requested_at.is_(None),
                    or_(
                        ObjectContents.lease_until.is_(None),
                        ObjectContents.lease_until <= now,
                    ),
                    reusable_move,
                )
                .order_by(ObjectContents.created_at, ObjectContents.id)
                .limit(limit)
                .with_for_update(of=ObjectContents, skip_locked=True)
            )
        ).all()
        target_too_large_count = 0
        for content, move in rows:
            if move is None:
                move = ObjectContentMoves()
                move.content_id = content.id
                self._session.add(move)
            move.target_kind = target_kind.value
            move.object_key = None
            move.verification_chunk_size_bytes = None
            move.verification_chunk_sha256 = None
            move.attempt_count = 0
            move.requested_by_user_id = requested_by_user_id
            if content.size_bytes > target_maximum_bytes:
                move.state = ContentMoveState.FAILED.value
                move.failure_code = ContentMoveFailureCode.TARGET_TOO_LARGE.value
                move.failure_detail = "content exceeds the target storage limit"
                move.next_attempt_at = None
                target_too_large_count += 1
            else:
                move.state = ContentMoveState.PENDING.value
                move.failure_code = None
                move.failure_detail = None
                move.next_attempt_at = now
        await self._session.flush()
        return MoveQueueResult(
            queued_count=len(rows) - target_too_large_count,
            target_too_large_count=target_too_large_count,
        )

    async def claim(
        self,
        *,
        lease_owner: str,
        lease_seconds: int,
    ) -> MoveWork | None:
        if await self._moves_paused_for_share():
            return None

        now = await self._database_now()
        row = (
            await self._session.execute(
                select(
                    ObjectContents,
                    ObjectContentMoves,
                    InlineContentPayloads.payload,
                    ObjectStoreObjects.object_key,
                    ObjectContentMoves.verification_chunk_sha256,
                )
                .join(
                    ObjectContentMoves,
                    ObjectContentMoves.content_id == ObjectContents.id,
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
                    ObjectContentMoves.state.in_(
                        (
                            ContentMoveState.PENDING.value,
                            ContentMoveState.TARGET_VERIFIED.value,
                        )
                    ),
                    or_(
                        ObjectContentMoves.next_attempt_at.is_(None),
                        ObjectContentMoves.next_attempt_at <= now,
                    ),
                    ObjectContents.state == ContentState.AVAILABLE.value,
                    ObjectContents.reference_count > 0,
                    ObjectContents.delete_requested_at.is_(None),
                    ObjectContents.storage_kind != ObjectContentMoves.target_kind,
                    or_(
                        ObjectContents.lease_until.is_(None),
                        ObjectContents.lease_until <= now,
                    ),
                )
                .order_by(ObjectContentMoves.updated_at, ObjectContentMoves.content_id)
                .limit(1)
                .with_for_update(
                    of=(ObjectContents, ObjectContentMoves),
                    skip_locked=True,
                )
            )
        ).one_or_none()
        if row is None:
            return None

        content, move, inline_payload, source_object_key, verification_chunks = row
        content.lease_owner = lease_owner
        content.lease_until = now + timedelta(seconds=lease_seconds)
        move.attempt_count += 1
        move.next_attempt_at = None
        move.failure_code = None
        move.failure_detail = None
        await self._session.flush()
        return MoveWork(
            content_id=content.id,
            source_kind=StorageKind(content.storage_kind),
            target_kind=StorageKind(move.target_kind),
            state=ContentMoveState(move.state),
            sha256=content.sha256,
            size_bytes=content.size_bytes,
            declared_media_type=content.declared_media_type,
            verified_media_type=content.verified_media_type,
            inline_payload=inline_payload,
            source_object_key=source_object_key,
            target_object_key=move.object_key,
            verification_chunk_size_bytes=move.verification_chunk_size_bytes,
            verification_chunk_sha256=verification_chunks,
            attempt_count=move.attempt_count,
        )

    async def fail_one_ineligible(self) -> bool:
        if await self._moves_paused_for_share():
            return False
        now = await self._database_now()
        row = (
            await self._session.execute(
                select(ObjectContents, ObjectContentMoves)
                .join(
                    ObjectContentMoves,
                    ObjectContentMoves.content_id == ObjectContents.id,
                )
                .where(
                    ObjectContentMoves.state.in_(
                        (
                            ContentMoveState.PENDING.value,
                            ContentMoveState.TARGET_VERIFIED.value,
                        )
                    ),
                    or_(
                        ObjectContents.lease_until.is_(None),
                        ObjectContents.lease_until <= now,
                    ),
                    or_(
                        ObjectContents.state != ContentState.AVAILABLE.value,
                        ObjectContents.reference_count < 1,
                        ObjectContents.delete_requested_at.is_not(None),
                        ObjectContents.storage_kind == ObjectContentMoves.target_kind,
                    ),
                )
                .order_by(ObjectContentMoves.updated_at, ObjectContentMoves.content_id)
                .limit(1)
                .with_for_update(
                    of=(ObjectContents, ObjectContentMoves),
                    skip_locked=True,
                )
            )
        ).one_or_none()
        if row is None:
            return False
        content, move = row
        move.state = ContentMoveState.FAILED.value
        move.failure_code = ContentMoveFailureCode.CONTENT_INELIGIBLE.value
        move.failure_detail = "content is no longer eligible to move"
        move.next_attempt_at = None
        self._clear_content_lease(content)
        await self._session.flush()
        return True

    async def record_object_target(
        self,
        *,
        content_id: UUID,
        lease_owner: str,
        object_key: str,
    ) -> None:
        _content, move = await self._leased_move_for_update(
            content_id=content_id,
            lease_owner=lease_owner,
        )
        if (
            move.target_kind != StorageKind.OBJECT_STORE.value
            or move.state != ContentMoveState.PENDING.value
        ):
            raise ObjectContentStateError(
                "Only a pending object-store move can record a target key"
            )
        if move.object_key not in {None, object_key}:
            raise ObjectContentStateError("The move already owns another target key")
        move.object_key = object_key
        await self._session.flush()

    async def record_target_verified(
        self,
        *,
        content_id: UUID,
        lease_owner: str,
        object_key: str,
        verification_chunk_size_bytes: int,
        verification_chunk_sha256: bytes,
    ) -> None:
        _content, move = await self._leased_move_for_update(
            content_id=content_id,
            lease_owner=lease_owner,
        )
        if (
            move.target_kind != StorageKind.OBJECT_STORE.value
            or move.state != ContentMoveState.PENDING.value
            or move.object_key != object_key
        ):
            raise ObjectContentStateError(
                "The verified target does not match the active move"
            )
        if (
            verification_chunk_size_bytes < 1
            or len(verification_chunk_sha256) < 32
            or len(verification_chunk_sha256) % 32 != 0
        ):
            raise ObjectContentStateError("Move verification chunks are invalid")
        move.state = ContentMoveState.TARGET_VERIFIED.value
        move.verification_chunk_size_bytes = verification_chunk_size_bytes
        move.verification_chunk_sha256 = verification_chunk_sha256
        move.failure_code = None
        move.failure_detail = None
        move.next_attempt_at = None
        await self._session.flush()

    async def record_retry(
        self,
        *,
        content_id: UUID,
        lease_owner: str,
        retry_delay_seconds: int,
        failure_code: ContentMoveFailureCode | None,
        detail: str | None,
    ) -> None:
        content = await self._move_content_for_update(content_id)
        if content.lease_owner != lease_owner:
            return
        move = await self._move_for_update(content_id)
        if move.state in {
            ContentMoveState.PENDING.value,
            ContentMoveState.TARGET_VERIFIED.value,
        }:
            now = await self._database_now()
            move.failure_code = None if failure_code is None else failure_code.value
            move.failure_detail = detail
            move.next_attempt_at = now + timedelta(seconds=retry_delay_seconds)
        self._clear_content_lease(content)
        await self._session.flush()

    async def record_failure(
        self,
        *,
        content_id: UUID,
        lease_owner: str,
        failure_code: ContentMoveFailureCode,
        detail: str,
    ) -> None:
        if len(detail) > 512:
            raise ValueError("Move failure detail must not exceed 512 characters")
        content = await self._move_content_for_update(content_id)
        if content.lease_owner != lease_owner:
            return
        move = await self._move_for_update(content_id)
        if move.state in {
            ContentMoveState.PENDING.value,
            ContentMoveState.TARGET_VERIFIED.value,
        }:
            move.state = ContentMoveState.FAILED.value
            move.failure_code = failure_code.value
            move.failure_detail = detail
            move.next_attempt_at = None
        self._clear_content_lease(content)
        await self._session.flush()

    async def renew_lease(
        self,
        *,
        content_id: UUID,
        lease_owner: str,
        lease_seconds: int,
    ) -> None:
        content, move = await self._leased_move_for_update(
            content_id=content_id,
            lease_owner=lease_owner,
        )
        self._require_move_eligible(content, move)
        now = await self._database_now()
        content.lease_until = now + timedelta(seconds=lease_seconds)
        await self._session.flush()

    async def complete_to_object_store(
        self,
        *,
        content_id: UUID,
        lease_owner: str,
        reservation: PublicationReservation,
        publication_lease_owner: str,
    ) -> None:
        await self._moves_paused_for_share()
        content, move = await self._leased_move_for_update(
            content_id=content_id,
            lease_owner=lease_owner,
        )
        self._require_move_eligible(
            content,
            move,
            target_kind=StorageKind.OBJECT_STORE,
            required_state=ContentMoveState.TARGET_VERIFIED,
        )
        if (
            move.object_key != reservation.object_key
            or reservation.size_bytes != content.size_bytes
            or move.verification_chunk_size_bytes is None
            or move.verification_chunk_sha256 is None
        ):
            raise ObjectContentStateError("Verified object target metadata is missing")
        source = await self._session.scalar(
            select(InlineContentPayloads)
            .where(InlineContentPayloads.content_id == content_id)
            .with_for_update()
        )
        if source is None:
            raise ObjectContentStateError("Inline move source is missing")

        await ObjectContentReconciliationRepository(
            self._session
        ).consume_publication_reservations(
            (reservation,),
            lease_owner=publication_lease_owner,
        )
        await self._session.delete(source)
        await self._session.flush()
        content.storage_kind = StorageKind.OBJECT_STORE.value
        await self._session.flush()
        target = ObjectStoreObjects()
        target.content_id = content_id
        target.storage_kind = StorageKind.OBJECT_STORE.value
        target.object_key = reservation.object_key
        target.verification_chunk_size_bytes = move.verification_chunk_size_bytes
        target.verification_chunk_sha256 = move.verification_chunk_sha256
        self._session.add(target)
        await self._session.flush()
        self._record_move_audit(content_id=content_id, move=move)
        await self._complete_move(content=content, move=move)
        await self._session.flush()

    async def complete_to_inline(
        self,
        *,
        content_id: UUID,
        lease_owner: str,
        payload: bytes,
        captured_size_bytes: int,
        captured_sha256: bytes,
        orphan_grace_seconds: int,
    ) -> None:
        await self._moves_paused_for_share()
        content, move = await self._leased_move_for_update(
            content_id=content_id,
            lease_owner=lease_owner,
        )
        self._require_move_eligible(
            content,
            move,
            target_kind=StorageKind.POSTGRES_INLINE,
            required_state=ContentMoveState.PENDING,
        )
        if (
            captured_size_bytes != content.size_bytes
            or captured_sha256 != content.sha256
            or len(payload) != captured_size_bytes
        ):
            raise ObjectContentStateError(
                "Captured inline target does not match canonical content"
            )
        source = await self._session.scalar(
            select(ObjectStoreObjects)
            .where(ObjectStoreObjects.content_id == content_id)
            .with_for_update()
        )
        if source is None:
            raise ObjectContentStateError("Object-store move source is missing")

        await ObjectContentReconciliationRepository(
            self._session
        ).register_known_orphan(
            object_key=source.object_key,
            size_bytes=content.size_bytes,
            orphan_grace_seconds=orphan_grace_seconds,
        )
        move.state = ContentMoveState.TARGET_VERIFIED.value
        move.failure_code = None
        move.failure_detail = None
        await self._session.flush()
        await self._session.delete(source)
        await self._session.flush()
        content.storage_kind = StorageKind.POSTGRES_INLINE.value
        await self._session.flush()
        target = InlineContentPayloads()
        target.content_id = content_id
        target.storage_kind = StorageKind.POSTGRES_INLINE.value
        target.payload = payload
        self._session.add(target)
        await self._session.flush()
        self._record_move_audit(content_id=content_id, move=move)
        await self._complete_move(content=content, move=move)
        await self._session.flush()

    async def _moves_paused_for_share(self) -> bool:
        policy = await self._session.scalar(
            select(ObjectContentDeploymentPolicy)
            .where(ObjectContentDeploymentPolicy.id == 1)
            .with_for_update(read=True)
        )
        if policy is None:
            raise RuntimeError("Object-content deployment policy is missing")
        return policy.moves_paused

    async def _move_content_for_update(self, content_id: UUID) -> ObjectContents:
        content = await self._session.scalar(
            select(ObjectContents)
            .where(ObjectContents.id == content_id)
            .with_for_update()
        )
        if content is None:
            raise ObjectContentStateError("Object content does not exist")
        return content

    async def _move_for_update(self, content_id: UUID) -> ObjectContentMoves:
        move = await self._session.scalar(
            select(ObjectContentMoves)
            .options(undefer(ObjectContentMoves.verification_chunk_sha256))
            .where(ObjectContentMoves.content_id == content_id)
            .with_for_update()
        )
        if move is None:
            raise ObjectContentStateError("Object-content move does not exist")
        return move

    async def _leased_move_for_update(
        self,
        *,
        content_id: UUID,
        lease_owner: str,
    ) -> tuple[ObjectContents, ObjectContentMoves]:
        content = await self._move_content_for_update(content_id)
        if content.lease_owner != lease_owner:
            raise ObjectContentBusyError("The object-content move lease changed")
        return content, await self._move_for_update(content_id)

    @staticmethod
    def _require_move_eligible(
        content: ObjectContents,
        move: ObjectContentMoves,
        *,
        target_kind: StorageKind | None = None,
        required_state: ContentMoveState | None = None,
    ) -> None:
        if (
            content.state != ContentState.AVAILABLE.value
            or content.reference_count < 1
            or content.delete_requested_at is not None
            or content.storage_kind == move.target_kind
            or target_kind is not None
            and move.target_kind != target_kind.value
            or required_state is not None
            and move.state != required_state.value
            or move.state
            not in {
                ContentMoveState.PENDING.value,
                ContentMoveState.TARGET_VERIFIED.value,
            }
        ):
            raise ObjectContentStateError("Object content is no longer move-eligible")

    def _record_move_audit(
        self,
        *,
        content_id: UUID,
        move: ObjectContentMoves,
    ) -> None:
        event = ObjectContentAuditEvents()
        event.content_id = content_id
        event.event_type = "storage_moved"
        event.detail = move.target_kind
        event.actor_user_id = move.requested_by_user_id
        self._session.add(event)

    async def _complete_move(
        self,
        *,
        content: ObjectContents,
        move: ObjectContentMoves,
    ) -> None:
        ObjectContentMoveRepository._clear_content_lease(content)
        await self._session.delete(move)

    @staticmethod
    def _clear_content_lease(content: ObjectContents) -> None:
        content.lease_owner = None
        content.lease_until = None

    async def _database_now(self) -> datetime:
        now = await self._session.scalar(select(func.now()))
        if now is None:
            raise RuntimeError("PostgreSQL did not return its current time")
        return now
