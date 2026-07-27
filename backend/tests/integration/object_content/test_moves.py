from __future__ import annotations

import json
import re
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from hashlib import sha256
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select, text, update

from eneo.database.database import DatabaseSessionManager
from eneo.database.tables.files_table import Files
from eneo.database.tables.object_content_policy_table import (
    ObjectContentDeploymentPolicy,
)
from eneo.database.tables.object_content_table import (
    FileContentReferences,
    InlineContentPayloads,
    ObjectContentAuditEvents,
    ObjectContentHolds,
    ObjectContentMoves,
    ObjectContentOrphanCandidates,
    ObjectContents,
    ObjectStoreObjects,
)
from eneo.database.tables.tenant_table import Tenants
from eneo.database.tables.users_table import Users
from eneo.main.container.container import Container
from eneo.object_content import deployment_policy_router
from eneo.object_content import move_repository as move_repository_module
from eneo.object_content.configuration import (
    ObjectContentCoreSettings,
    ObjectContentSettings,
)
from eneo.object_content.content import (
    CapturedContent,
    ContentAccessClass,
    ContentIntent,
    ContentRead,
    ContentState,
    ObjectContentConfigurationError,
    ObjectContentUnavailableError,
    StorageKind,
    capture_content,
)
from eneo.object_content.content_service import ObjectContentService
from eneo.object_content.deployment_policy import DeploymentPolicyPauseUpdate
from eneo.object_content.deployment_policy_router import MoveQueueRequest
from eneo.object_content.lease import OperationCheckpoint
from eneo.object_content.move_executor import ObjectContentMoveExecutor
from eneo.object_content.move_repository import (
    MoveWork,
    ObjectContentMoveRepository,
)
from eneo.object_content.reconciliation import ObjectContentReconciler
from eneo.object_content.reconciliation_repository import PublicationReservation
from eneo.object_content.runtime import (
    ObjectContentReadinessCode,
    ObjectContentRuntime,
    StorageCapability,
)
from eneo.object_content.s3_object_store import (
    MultipartStarted,
    ObjectHead,
    ObjectStoreNotFoundError,
    ObjectStoreUnavailableError,
)
from tests.integration.object_content.conftest import RealObjectStore


async def _payload_source(payload: bytes) -> AsyncIterator[bytes]:
    yield payload


class SimulatedWorkerCrash(BaseException):
    pass


async def _create_inline_content(
    database: DatabaseSessionManager,
    *,
    payload: bytes,
    idempotency_key: str,
) -> tuple[UUID, UUID]:
    settings = ObjectContentCoreSettings(
        _env_file=None,
        inline_maximum_bytes=max(len(payload), 1),
        inline_io_chunk_bytes=max(len(payload), 1),
    )
    service = ObjectContentService(settings, database)
    async with capture_content(
        _payload_source(payload),
        declared_media_type="application/octet-stream",
        verified_media_type="application/octet-stream",
        maximum_size_bytes=max(len(payload), 1),
        spool_memory_bytes=max(len(payload), 1),
        multipart_part_bytes=max(len(payload), 1),
    ) as captured:
        async with database.session() as session, session.begin():
            tenant_id = (await session.scalars(select(Tenants.id))).one()
            user_id = (await session.scalars(select(Users.id))).one()
            owner = Files(
                name=f"{idempotency_key}.bin",
                mimetype="application/octet-stream",
                file_type="text",
                tenant_id=tenant_id,
                user_id=user_id,
                parent_file_id=None,
            )
            session.add(owner)
            await session.flush()
            prepared = await service.prepare_in_transaction(
                session,
                intent=ContentIntent(
                    tenant_id=tenant_id,
                    created_by_user_id=user_id,
                    access_class=ContentAccessClass.PRIVATE_RESOURCE,
                    idempotency_key=idempotency_key,
                    producer_receipt=f"file:{owner.id}:original:0",
                ),
                content=captured,
                storage_kind=StorageKind.POSTGRES_INLINE,
            )
            session.add(
                FileContentReferences(
                    file_id=owner.id,
                    content_id=prepared.id,
                    variant="original",
                    ordinal=0,
                )
            )
        return prepared.id, user_id


async def _queue_move(
    database: DatabaseSessionManager,
    *,
    target_kind: StorageKind,
    actor_id: UUID,
    target_maximum_bytes: int,
) -> None:
    async with database.session() as session, session.begin():
        result = await ObjectContentMoveRepository(session).queue(
            target_kind=target_kind,
            limit=1,
            requested_by_user_id=actor_id,
            target_maximum_bytes=target_maximum_bytes,
        )
        assert result.queued_count == 1


async def _expire_crashed_operation(
    database: DatabaseSessionManager,
    *,
    content_id: UUID,
    object_key: str | None,
) -> None:
    expired = func.now() - text("interval '1 second'")
    async with database.session() as session, session.begin():
        await session.execute(
            update(ObjectContents)
            .where(ObjectContents.id == content_id)
            .values(lease_until=expired)
        )
        if object_key is not None:
            await session.execute(
                update(ObjectContentOrphanCandidates)
                .where(ObjectContentOrphanCandidates.object_key == object_key)
                .values(lease_owner="expired-worker", lease_until=expired)
            )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_queue_creates_only_bounded_per_content_intents(
    object_content_database: DatabaseSessionManager,
) -> None:
    first_id, actor_id = await _create_inline_content(
        object_content_database,
        payload=b"first",
        idempotency_key=f"move-{uuid4().hex}",
    )
    second_id, _ = await _create_inline_content(
        object_content_database,
        payload=b"second",
        idempotency_key=f"move-{uuid4().hex}",
    )

    async with object_content_database.session() as session, session.begin():
        first = await ObjectContentMoveRepository(session).queue(
            target_kind=StorageKind.OBJECT_STORE,
            limit=1,
            requested_by_user_id=actor_id,
            target_maximum_bytes=1024,
        )
    async with object_content_database.session() as session, session.begin():
        second = await ObjectContentMoveRepository(session).queue(
            target_kind=StorageKind.OBJECT_STORE,
            limit=1,
            requested_by_user_id=actor_id,
            target_maximum_bytes=1024,
        )
        count = await session.scalar(
            select(func.count()).select_from(ObjectContentMoves)
        )
        queued_ids = set(await session.scalars(select(ObjectContentMoves.content_id)))

    assert first.queued_count == 1
    assert second.queued_count == 1
    assert first.target_too_large_count == 0
    assert count == 2
    assert queued_ids == {first_id, second_id}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_queue_records_maximum_plus_one_as_a_bounded_typed_failure(
    object_content_database: DatabaseSessionManager,
) -> None:
    content_id, actor_id = await _create_inline_content(
        object_content_database,
        payload=b"12345",
        idempotency_key=f"move-{uuid4().hex}",
    )

    async with object_content_database.session() as session, session.begin():
        result = await ObjectContentMoveRepository(session).queue(
            target_kind=StorageKind.OBJECT_STORE,
            limit=1,
            requested_by_user_id=actor_id,
            target_maximum_bytes=4,
        )
        move = await session.get(ObjectContentMoves, content_id)
        move_state = None if move is None else move.state
        failure_code = None if move is None else move.failure_code

    assert result.queued_count == 0
    assert result.target_too_large_count == 1
    assert move is not None
    assert move_state == "failed"
    assert failure_code == "target_too_large"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_admin_command_requires_readiness_before_queueing(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content_id, actor_id = await _create_inline_content(
        object_content_database,
        payload=b"admin readiness gate",
        idempotency_key=f"move-{uuid4().hex}",
    )

    class Runtime:
        inline_maximum_bytes = real_object_store.settings.inline_maximum_bytes
        object_store_maximum_bytes = real_object_store.settings.maximum_multipart_bytes
        selectable = False

        async def storage_capabilities(self) -> tuple[StorageCapability, ...]:
            return (
                StorageCapability(
                    target=StorageKind.OBJECT_STORE,
                    configured=True,
                    selectable=self.selectable,
                    readiness_code=(
                        ObjectContentReadinessCode.READY
                        if self.selectable
                        else ObjectContentReadinessCode.STORE_DEGRADED
                    ),
                ),
            )

    runtime = Runtime()
    monkeypatch.setattr(
        deployment_policy_router,
        "object_content_runtime",
        runtime,
    )
    async with object_content_database.session() as session:
        container = cast(
            Container,
            SimpleNamespace(
                session=lambda: session,
                user=lambda: SimpleNamespace(id=actor_id),
            ),
        )
        request = MoveQueueRequest(target=StorageKind.OBJECT_STORE, limit=1)
        with pytest.raises(ObjectContentUnavailableError):
            await deployment_policy_router.queue_object_content_moves(
                request,
                container,
            )
        assert not session.in_transaction()
        async with session.begin():
            content_before_recovery = await session.get(ObjectContents, content_id)
            assert content_before_recovery is not None
            assert (
                content_before_recovery.storage_kind
                == StorageKind.POSTGRES_INLINE.value
            )
            assert await session.get(ObjectContentMoves, content_id) is None

        runtime.selectable = True
        queued = await deployment_policy_router.queue_object_content_moves(
            request,
            container,
        )
        paused = await deployment_policy_router.set_object_content_moves_paused(
            DeploymentPolicyPauseUpdate(
                expected_revision=1,
                moves_paused=True,
            ),
            container,
        )
        projection = await deployment_policy_router._read_moves(session)
        resumed = await deployment_policy_router.set_object_content_moves_paused(
            DeploymentPolicyPauseUpdate(
                expected_revision=2,
                moves_paused=False,
            ),
            container,
        )

    assert queued.queued_count == 1
    assert queued.target_too_large_count == 0
    assert paused.policy_revision == 2
    assert paused.paused is True
    assert resumed.policy_revision == 3
    assert resumed.paused is False
    assert projection.paused is True
    assert len(projection.moves) == 1
    assert projection.moves[0].state.value == "pending"
    async with object_content_database.session() as session, session.begin():
        content = await session.get(ObjectContents, content_id)
        move = await session.get(ObjectContentMoves, content_id)
        assert content is not None
        assert move is not None
        assert content.storage_kind == StorageKind.POSTGRES_INLINE.value
        assert move.target_kind == StorageKind.OBJECT_STORE.value


@pytest.mark.integration
@pytest.mark.asyncio
async def test_reconciler_moves_verified_bytes_in_both_directions(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"verified move payload"
    content_id, actor_id = await _create_inline_content(
        object_content_database,
        payload=payload,
        idempotency_key=f"move-{uuid4().hex}",
    )
    reconciler = ObjectContentReconciler(
        real_object_store.settings,
        object_content_database,
        object_store_settings=real_object_store.settings,
        object_store=real_object_store.store,
    )

    async with object_content_database.session() as session, session.begin():
        await ObjectContentMoveRepository(session).queue(
            target_kind=StorageKind.OBJECT_STORE,
            limit=1,
            requested_by_user_id=actor_id,
            target_maximum_bytes=real_object_store.settings.maximum_multipart_bytes,
        )

    first = await reconciler.run_once()
    assert first.moves_processed == 1

    async with object_content_database.session() as session, session.begin():
        content = await session.get(ObjectContents, content_id)
        inline = await session.get(InlineContentPayloads, content_id)
        descriptor = await session.get(ObjectStoreObjects, content_id)
        move = await session.get(ObjectContentMoves, content_id)
        assert content is not None
        assert descriptor is not None
        assert move is None
        object_key = descriptor.object_key
        assert content.storage_kind == StorageKind.OBJECT_STORE.value
        assert content.sha256 == sha256(payload).digest()
        assert content.size_bytes == len(payload)
        assert content.verified_media_type == "application/octet-stream"
        assert inline is None
        assert await session.get(ObjectContentOrphanCandidates, object_key) is None

    async with real_object_store.store.open_verified_read(
        object_key,
        expected_sha256=sha256(payload).digest(),
        expected_size_bytes=len(payload),
        expected_media_type="application/octet-stream",
    ) as opened:
        assert b"".join([chunk async for chunk in opened.chunks]) == payload

    async with object_content_database.session() as session, session.begin():
        await ObjectContentMoveRepository(session).queue(
            target_kind=StorageKind.POSTGRES_INLINE,
            limit=1,
            requested_by_user_id=actor_id,
            target_maximum_bytes=real_object_store.settings.inline_maximum_bytes,
        )

    flip_started = False
    original_complete = ObjectContentMoveRepository.complete_to_inline
    original_open = real_object_store.store.open_verified_read

    async def observe_complete(
        self: ObjectContentMoveRepository,
        *,
        content_id: UUID,
        lease_owner: str,
        payload: bytes,
        captured_size_bytes: int,
        captured_sha256: bytes,
        orphan_grace_seconds: int,
    ) -> None:
        nonlocal flip_started
        flip_started = True
        await original_complete(
            self,
            content_id=content_id,
            lease_owner=lease_owner,
            payload=payload,
            captured_size_bytes=captured_size_bytes,
            captured_sha256=captured_sha256,
            orphan_grace_seconds=orphan_grace_seconds,
        )

    @asynccontextmanager
    async def observe_verified_read(
        key: str,
        *,
        expected_sha256: bytes,
        expected_size_bytes: int,
        expected_media_type: str,
    ) -> AsyncGenerator[ContentRead, None]:
        assert not flip_started, "remote reads must finish before the authority flip"
        async with original_open(
            key,
            expected_sha256=expected_sha256,
            expected_size_bytes=expected_size_bytes,
            expected_media_type=expected_media_type,
        ) as opened:
            yield opened

    def reject_flip_hashing(_payload: bytes) -> None:
        if flip_started:
            raise AssertionError(
                "payload hashing must finish before the authority flip"
            )

    monkeypatch.setattr(
        ObjectContentMoveRepository,
        "complete_to_inline",
        observe_complete,
    )
    monkeypatch.setattr(
        real_object_store.store,
        "open_verified_read",
        observe_verified_read,
    )
    monkeypatch.setattr(
        move_repository_module,
        "sha256",
        reject_flip_hashing,
        raising=False,
    )
    second = await reconciler.run_once()
    assert second.moves_processed == 1

    async with object_content_database.session() as session, session.begin():
        content = await session.get(ObjectContents, content_id)
        inline = await session.get(InlineContentPayloads, content_id)
        descriptor = await session.get(ObjectStoreObjects, content_id)
        move = await session.get(ObjectContentMoves, content_id)
        audit = tuple(
            await session.scalars(
                select(ObjectContentAuditEvents)
                .where(
                    ObjectContentAuditEvents.content_id == content_id,
                    ObjectContentAuditEvents.event_type == "storage_moved",
                )
                .order_by(ObjectContentAuditEvents.created_at)
            )
        )
        assert content is not None
        assert inline is not None
        assert move is None
        assert content.storage_kind == StorageKind.POSTGRES_INLINE.value
        assert inline.payload == payload
        assert descriptor is None
        assert [event.actor_user_id for event in audit] == [actor_id, actor_id]
        assert [event.detail for event in audit] == [
            StorageKind.OBJECT_STORE.value,
            StorageKind.POSTGRES_INLINE.value,
        ]
        candidate = await session.get(ObjectContentOrphanCandidates, object_key)
        assert candidate is not None
        assert candidate.completed_observations == 0
        now = await session.scalar(select(func.now()))
        assert now is not None
        candidate.eligible_after = now - timedelta(seconds=1)
        candidate.lease_until = now - timedelta(seconds=1)

    inline_runtime = ObjectContentRuntime(database=object_content_database)
    inline_runtime.start(
        core_settings=ObjectContentCoreSettings(
            _env_file=None,
            inline_maximum_bytes=len(payload),
            inline_io_chunk_bytes=len(payload),
        )
    )
    with pytest.raises(ObjectContentConfigurationError):
        await inline_runtime.validate_configuration()

    first_cleanup = await reconciler.run_once()
    assert first_cleanup.orphan_objects_deleted == 0
    async with object_content_database.session() as session, session.begin():
        candidate = await session.get(ObjectContentOrphanCandidates, object_key)
        assert candidate is not None
        assert candidate.completed_observations == 1

    second_cleanup = await reconciler.run_once()
    assert second_cleanup.orphan_objects_deleted == 1
    with pytest.raises(ObjectStoreNotFoundError):
        await real_object_store.store.head(object_key)
    await inline_runtime.validate_configuration()
    await inline_runtime.stop()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_reconciler_round_trips_content_across_the_multipart_boundary(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
) -> None:
    payload_size = (
        max(
            real_object_store.settings.multipart_threshold_bytes,
            real_object_store.settings.multipart_part_bytes,
        )
        + 1
    )
    pattern = bytes(range(251))
    payload = (pattern * ((payload_size + len(pattern) - 1) // len(pattern)))[
        :payload_size
    ]
    digest = sha256(payload).digest()
    content_id, actor_id = await _create_inline_content(
        object_content_database,
        payload=payload,
        idempotency_key=f"move-{uuid4().hex}",
    )
    reconciler = ObjectContentReconciler(
        real_object_store.settings,
        object_content_database,
        object_store_settings=real_object_store.settings,
        object_store=real_object_store.store,
    )

    await _queue_move(
        object_content_database,
        target_kind=StorageKind.OBJECT_STORE,
        actor_id=actor_id,
        target_maximum_bytes=real_object_store.settings.maximum_multipart_bytes,
    )
    moved_to_store = await reconciler.run_once()
    assert moved_to_store.moves_processed == 1

    async with object_content_database.session() as session, session.begin():
        content = await session.get(ObjectContents, content_id)
        inline = await session.get(InlineContentPayloads, content_id)
        descriptor = await session.get(ObjectStoreObjects, content_id)
        assert content is not None
        assert descriptor is not None
        await session.refresh(
            descriptor,
            attribute_names=["verification_chunk_sha256"],
        )
        object_key = descriptor.object_key
        expected_parts = (
            payload_size + real_object_store.settings.multipart_part_bytes - 1
        ) // real_object_store.settings.multipart_part_bytes
        assert content.storage_kind == StorageKind.OBJECT_STORE.value
        assert content.sha256 == digest
        assert content.size_bytes == payload_size
        assert content.verified_media_type == "application/octet-stream"
        assert inline is None
        assert (
            descriptor.verification_chunk_size_bytes
            == real_object_store.settings.multipart_part_bytes
        )
        assert len(descriptor.verification_chunk_sha256) == expected_parts * 32

    async with real_object_store.store.open_verified_read(
        object_key,
        expected_sha256=digest,
        expected_size_bytes=payload_size,
        expected_media_type="application/octet-stream",
    ) as opened:
        assert b"".join([chunk async for chunk in opened.chunks]) == payload

    await _queue_move(
        object_content_database,
        target_kind=StorageKind.POSTGRES_INLINE,
        actor_id=actor_id,
        target_maximum_bytes=real_object_store.settings.inline_maximum_bytes,
    )
    moved_to_inline = await reconciler.run_once()
    assert moved_to_inline.moves_processed == 1

    async with object_content_database.session() as session, session.begin():
        content = await session.get(ObjectContents, content_id)
        inline = await session.get(InlineContentPayloads, content_id)
        descriptor = await session.get(ObjectStoreObjects, content_id)
        candidate = await session.get(ObjectContentOrphanCandidates, object_key)
        assert content is not None
        assert inline is not None
        assert candidate is not None
        assert content.storage_kind == StorageKind.POSTGRES_INLINE.value
        assert content.sha256 == digest
        assert content.size_bytes == payload_size
        assert content.verified_media_type == "application/octet-stream"
        assert inline.payload == payload
        assert descriptor is None
        assert candidate.completed_observations == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_store_outage_retries_without_changing_authority(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"retry after object-store outage"
    content_id, actor_id = await _create_inline_content(
        object_content_database,
        payload=payload,
        idempotency_key=f"move-{uuid4().hex}",
    )
    reconciler = ObjectContentReconciler(
        real_object_store.settings,
        object_content_database,
        object_store_settings=real_object_store.settings,
        object_store=real_object_store.store,
    )
    async with object_content_database.session() as session, session.begin():
        await ObjectContentMoveRepository(session).queue(
            target_kind=StorageKind.OBJECT_STORE,
            limit=1,
            requested_by_user_id=actor_id,
            target_maximum_bytes=real_object_store.settings.maximum_multipart_bytes,
        )

    original_upload = real_object_store.store.upload
    unavailable_upload = AsyncMock(
        side_effect=ObjectStoreUnavailableError("store unavailable")
    )
    monkeypatch.setattr(real_object_store.store, "upload", unavailable_upload)
    first = await reconciler.run_once()

    async with object_content_database.session() as session, session.begin():
        content = await session.get(ObjectContents, content_id)
        move = await session.get(ObjectContentMoves, content_id)
        assert content is not None
        assert move is not None
        assert content.storage_kind == StorageKind.POSTGRES_INLINE.value
        assert move.state == "pending"
        assert move.failure_code == "store_unavailable"
        await session.execute(
            update(ObjectContentMoves)
            .where(ObjectContentMoves.content_id == content_id)
            .values(next_attempt_at=func.now())
        )

    assert first.moves_processed == 1
    monkeypatch.setattr(real_object_store.store, "upload", original_upload)
    second = await reconciler.run_once()
    assert second.moves_processed == 1
    async with object_content_database.session() as session, session.begin():
        content = await session.get(ObjectContents, content_id)
        move = await session.get(ObjectContentMoves, content_id)
        assert content is not None
        assert move is None
        assert content.storage_kind == StorageKind.OBJECT_STORE.value


@pytest.mark.integration
@pytest.mark.asyncio
async def test_current_target_limits_fence_io_after_configuration_changes(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exact_payload = b"exact-inline-limit"
    content_id, actor_id = await _create_inline_content(
        object_content_database,
        payload=exact_payload,
        idempotency_key=f"move-{uuid4().hex}",
    )
    reconciler = ObjectContentReconciler(
        real_object_store.settings,
        object_content_database,
        object_store_settings=real_object_store.settings,
        object_store=real_object_store.store,
    )
    await _queue_move(
        object_content_database,
        target_kind=StorageKind.OBJECT_STORE,
        actor_id=actor_id,
        target_maximum_bytes=real_object_store.settings.maximum_multipart_bytes,
    )
    assert (await reconciler.run_once()).moves_processed == 1
    await _queue_move(
        object_content_database,
        target_kind=StorageKind.POSTGRES_INLINE,
        actor_id=actor_id,
        target_maximum_bytes=real_object_store.settings.inline_maximum_bytes,
    )
    exact_inline_settings = real_object_store.settings.model_copy(
        update={
            "inline_maximum_bytes": len(exact_payload),
            "inline_io_chunk_bytes": len(exact_payload),
        }
    )
    exact_inline_reconciler = ObjectContentReconciler(
        exact_inline_settings,
        object_content_database,
        object_store_settings=exact_inline_settings,
        object_store=real_object_store.store,
    )
    assert (await exact_inline_reconciler.run_once()).moves_processed == 1

    await _queue_move(
        object_content_database,
        target_kind=StorageKind.OBJECT_STORE,
        actor_id=actor_id,
        target_maximum_bytes=real_object_store.settings.maximum_multipart_bytes,
    )
    assert (await reconciler.run_once()).moves_processed == 1
    await _queue_move(
        object_content_database,
        target_kind=StorageKind.POSTGRES_INLINE,
        actor_id=actor_id,
        target_maximum_bytes=real_object_store.settings.inline_maximum_bytes,
    )
    smaller_inline_settings = real_object_store.settings.model_copy(
        update={
            "inline_maximum_bytes": len(exact_payload) - 1,
            "inline_io_chunk_bytes": len(exact_payload) - 1,
        }
    )
    smaller_inline_reconciler = ObjectContentReconciler(
        smaller_inline_settings,
        object_content_database,
        object_store_settings=smaller_inline_settings,
        object_store=real_object_store.store,
    )
    forbidden_read = MagicMock(
        side_effect=AssertionError("oversized inline target must not read the store")
    )
    monkeypatch.setattr(
        real_object_store.store,
        "open_verified_read",
        forbidden_read,
    )
    assert (await smaller_inline_reconciler.run_once()).moves_processed == 1
    forbidden_read.assert_not_called()
    async with object_content_database.session() as session, session.begin():
        content = await session.get(ObjectContents, content_id)
        move = await session.get(ObjectContentMoves, content_id)
        assert content is not None
        assert move is not None
        assert content.storage_kind == StorageKind.OBJECT_STORE.value
        assert move.state == "failed"
        assert move.failure_code == "target_too_large"

    object_payload = b"object-target-max-plus-one"
    object_content_id, actor_id = await _create_inline_content(
        object_content_database,
        payload=object_payload,
        idempotency_key=f"move-{uuid4().hex}",
    )
    await _queue_move(
        object_content_database,
        target_kind=StorageKind.OBJECT_STORE,
        actor_id=actor_id,
        target_maximum_bytes=real_object_store.settings.maximum_multipart_bytes,
    )
    original_upload = real_object_store.store.upload
    forbidden_upload = AsyncMock(
        side_effect=AssertionError("oversized object target must not upload")
    )
    monkeypatch.setattr(real_object_store.store, "upload", forbidden_upload)
    with monkeypatch.context() as target_limit:
        target_limit.setattr(
            ObjectContentSettings,
            "maximum_multipart_bytes",
            property(lambda _settings: len(object_payload) - 1),
        )
        assert (await reconciler.run_once()).moves_processed == 1
    forbidden_upload.assert_not_awaited()
    monkeypatch.setattr(real_object_store.store, "upload", original_upload)
    async with object_content_database.session() as session, session.begin():
        content = await session.get(ObjectContents, object_content_id)
        move = await session.get(ObjectContentMoves, object_content_id)
        assert content is not None
        assert move is not None
        assert content.storage_kind == StorageKind.POSTGRES_INLINE.value
        assert move.state == "failed"
        assert move.failure_code == "target_too_large"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_pause_blocks_move_claim_until_resumed(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
) -> None:
    content_id, actor_id = await _create_inline_content(
        object_content_database,
        payload=b"pause and resume",
        idempotency_key=f"move-{uuid4().hex}",
    )
    reconciler = ObjectContentReconciler(
        real_object_store.settings,
        object_content_database,
        object_store_settings=real_object_store.settings,
        object_store=real_object_store.store,
    )
    async with object_content_database.session() as session, session.begin():
        await ObjectContentMoveRepository(session).queue(
            target_kind=StorageKind.OBJECT_STORE,
            limit=1,
            requested_by_user_id=actor_id,
            target_maximum_bytes=real_object_store.settings.maximum_multipart_bytes,
        )
        await session.execute(
            update(ObjectContentDeploymentPolicy)
            .where(ObjectContentDeploymentPolicy.id == 1)
            .values(moves_paused=True)
        )

    paused = await reconciler.run_once()
    assert paused.moves_processed == 0
    async with object_content_database.session() as session, session.begin():
        content = await session.get(ObjectContents, content_id)
        move = await session.get(ObjectContentMoves, content_id)
        assert content is not None
        assert move is not None
        assert content.storage_kind == StorageKind.POSTGRES_INLINE.value
        assert move.state == "pending"
        await session.execute(
            update(ObjectContentDeploymentPolicy)
            .where(ObjectContentDeploymentPolicy.id == 1)
            .values(moves_paused=False)
        )

    resumed = await reconciler.run_once()
    assert resumed.moves_processed == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_blocked_move_does_not_starve_eligible_work_or_lose_its_source(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
) -> None:
    payload = b"retained authoritative source"
    content_id, actor_id = await _create_inline_content(
        object_content_database,
        payload=payload,
        idempotency_key=f"move-{uuid4().hex}",
    )
    reconciler = ObjectContentReconciler(
        real_object_store.settings,
        object_content_database,
        object_store_settings=real_object_store.settings,
        object_store=real_object_store.store,
    )
    async with object_content_database.session() as session, session.begin():
        await ObjectContentMoveRepository(session).queue(
            target_kind=StorageKind.OBJECT_STORE,
            limit=1,
            requested_by_user_id=actor_id,
            target_maximum_bytes=real_object_store.settings.maximum_multipart_bytes,
        )
        session.add(
            ObjectContentHolds(
                content_id=content_id,
                kind="legal",
                reason="preserve durable content",
                actor_user_id=actor_id,
            )
        )
        await session.execute(
            delete(FileContentReferences).where(
                FileContentReferences.content_id == content_id
            )
        )

    eligible_id, _actor_id = await _create_inline_content(
        object_content_database,
        payload=b"eligible move",
        idempotency_key=f"move-{uuid4().hex}",
    )
    await _queue_move(
        object_content_database,
        target_kind=StorageKind.OBJECT_STORE,
        actor_id=actor_id,
        target_maximum_bytes=real_object_store.settings.maximum_multipart_bytes,
    )

    first = await reconciler.run_once()
    assert first.moves_processed == 1
    async with object_content_database.session() as session, session.begin():
        eligible = await session.get(ObjectContents, eligible_id)
        blocked_move = await session.get(ObjectContentMoves, content_id)
        assert eligible is not None
        assert blocked_move is not None
        assert eligible.storage_kind == StorageKind.OBJECT_STORE.value
        assert blocked_move.state == "pending"

    second = await reconciler.run_once()
    assert second.moves_processed == 1
    async with object_content_database.session() as session, session.begin():
        content = await session.get(ObjectContents, content_id)
        inline = await session.get(InlineContentPayloads, content_id)
        move = await session.get(ObjectContentMoves, content_id)
        assert content is not None
        assert inline is not None
        assert move is not None
        assert content.state == ContentState.RETAINED.value
        assert content.storage_kind == StorageKind.POSTGRES_INLINE.value
        assert inline.payload == payload
        assert move.state == "failed"
        assert move.failure_code == "content_ineligible"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_inline_to_object_recovers_at_each_crash_boundary(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reconciler = ObjectContentReconciler(
        real_object_store.settings,
        object_content_database,
        object_store_settings=real_object_store.settings,
        object_store=real_object_store.store,
    )
    original_upload = real_object_store.store.upload

    before_upload_id, actor_id = await _create_inline_content(
        object_content_database,
        payload=b"crash before upload",
        idempotency_key=f"move-{uuid4().hex}",
    )
    await _queue_move(
        object_content_database,
        target_kind=StorageKind.OBJECT_STORE,
        actor_id=actor_id,
        target_maximum_bytes=real_object_store.settings.maximum_multipart_bytes,
    )
    monkeypatch.setattr(
        real_object_store.store,
        "upload",
        AsyncMock(side_effect=SimulatedWorkerCrash()),
    )
    with pytest.raises(SimulatedWorkerCrash):
        await reconciler.run_once()
    async with object_content_database.session() as session, session.begin():
        content = await session.get(ObjectContents, before_upload_id)
        move = await session.get(ObjectContentMoves, before_upload_id)
        assert content is not None
        assert move is not None
        assert move.object_key is not None
        before_upload_key = move.object_key
        assert content.storage_kind == StorageKind.POSTGRES_INLINE.value
        assert move.state == "pending"
    with pytest.raises(ObjectStoreNotFoundError):
        await real_object_store.store.head(before_upload_key)
    await _expire_crashed_operation(
        object_content_database,
        content_id=before_upload_id,
        object_key=before_upload_key,
    )
    monkeypatch.setattr(real_object_store.store, "upload", original_upload)
    assert (await reconciler.run_once()).moves_processed == 1

    after_upload_id, actor_id = await _create_inline_content(
        object_content_database,
        payload=b"crash after upload",
        idempotency_key=f"move-{uuid4().hex}",
    )
    await _queue_move(
        object_content_database,
        target_kind=StorageKind.OBJECT_STORE,
        actor_id=actor_id,
        target_maximum_bytes=real_object_store.settings.maximum_multipart_bytes,
    )

    async def upload_then_crash(
        key: str,
        content: CapturedContent,
        *,
        multipart_started: MultipartStarted | None = None,
        operation_checkpoint: OperationCheckpoint | None = None,
    ) -> ObjectHead:
        await original_upload(
            key,
            content,
            multipart_started=multipart_started,
            operation_checkpoint=operation_checkpoint,
        )
        raise SimulatedWorkerCrash

    monkeypatch.setattr(real_object_store.store, "upload", upload_then_crash)
    with pytest.raises(SimulatedWorkerCrash):
        await reconciler.run_once()
    async with object_content_database.session() as session, session.begin():
        content = await session.get(ObjectContents, after_upload_id)
        move = await session.get(ObjectContentMoves, after_upload_id)
        assert content is not None
        assert move is not None
        assert move.object_key is not None
        after_upload_key = move.object_key
        assert content.storage_kind == StorageKind.POSTGRES_INLINE.value
        assert move.state == "pending"
    assert (await real_object_store.store.head(after_upload_key)).size_bytes == len(
        b"crash after upload"
    )
    await _expire_crashed_operation(
        object_content_database,
        content_id=after_upload_id,
        object_key=after_upload_key,
    )
    monkeypatch.setattr(real_object_store.store, "upload", original_upload)
    assert (await reconciler.run_once()).moves_processed == 1
    async with object_content_database.session() as session, session.begin():
        descriptor = await session.get(ObjectStoreObjects, after_upload_id)
        assert descriptor is not None
        assert descriptor.object_key == after_upload_key

    before_flip_id, actor_id = await _create_inline_content(
        object_content_database,
        payload=b"crash before authority flip",
        idempotency_key=f"move-{uuid4().hex}",
    )
    await _queue_move(
        object_content_database,
        target_kind=StorageKind.OBJECT_STORE,
        actor_id=actor_id,
        target_maximum_bytes=real_object_store.settings.maximum_multipart_bytes,
    )
    original_complete = ObjectContentMoveRepository.complete_to_object_store

    async def crash_before_flip(
        self: ObjectContentMoveRepository,
        *,
        content_id: UUID,
        lease_owner: str,
        reservation: PublicationReservation,
        publication_lease_owner: str,
    ) -> None:
        raise SimulatedWorkerCrash

    monkeypatch.setattr(
        ObjectContentMoveRepository,
        "complete_to_object_store",
        crash_before_flip,
    )
    with pytest.raises(SimulatedWorkerCrash):
        await reconciler.run_once()
    async with object_content_database.session() as session, session.begin():
        content = await session.get(ObjectContents, before_flip_id)
        move = await session.get(ObjectContentMoves, before_flip_id)
        assert content is not None
        assert move is not None
        assert move.object_key is not None
        before_flip_key = move.object_key
        assert content.storage_kind == StorageKind.POSTGRES_INLINE.value
        assert move.state == "target_verified"
    await _expire_crashed_operation(
        object_content_database,
        content_id=before_flip_id,
        object_key=before_flip_key,
    )
    monkeypatch.setattr(
        ObjectContentMoveRepository,
        "complete_to_object_store",
        original_complete,
    )
    assert (await reconciler.run_once()).moves_processed == 1

    after_flip_id, actor_id = await _create_inline_content(
        object_content_database,
        payload=b"crash after authority flip",
        idempotency_key=f"move-{uuid4().hex}",
    )
    await _queue_move(
        object_content_database,
        target_kind=StorageKind.OBJECT_STORE,
        actor_id=actor_id,
        target_maximum_bytes=real_object_store.settings.maximum_multipart_bytes,
    )
    original_move = ObjectContentMoveExecutor._move_to_object_store

    async def crash_after_flip(
        self: ObjectContentMoveExecutor,
        work: MoveWork,
        *,
        lease_owner: str,
        lease_started_at: float,
    ) -> None:
        await original_move(
            self,
            work,
            lease_owner=lease_owner,
            lease_started_at=lease_started_at,
        )
        raise SimulatedWorkerCrash

    monkeypatch.setattr(
        ObjectContentMoveExecutor,
        "_move_to_object_store",
        crash_after_flip,
    )
    with pytest.raises(SimulatedWorkerCrash):
        await reconciler.run_once()
    async with object_content_database.session() as session, session.begin():
        content = await session.get(ObjectContents, after_flip_id)
        move = await session.get(ObjectContentMoves, after_flip_id)
        assert content is not None
        assert move is None
        assert content.storage_kind == StorageKind.OBJECT_STORE.value
    monkeypatch.setattr(
        ObjectContentMoveExecutor,
        "_move_to_object_store",
        original_move,
    )
    assert (await reconciler.run_once()).moves_processed == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_object_to_inline_recovers_when_capture_precedes_a_crash(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"remote source survives interrupted inline flip"
    content_id, actor_id = await _create_inline_content(
        object_content_database,
        payload=payload,
        idempotency_key=f"move-{uuid4().hex}",
    )
    reconciler = ObjectContentReconciler(
        real_object_store.settings,
        object_content_database,
        object_store_settings=real_object_store.settings,
        object_store=real_object_store.store,
    )
    await _queue_move(
        object_content_database,
        target_kind=StorageKind.OBJECT_STORE,
        actor_id=actor_id,
        target_maximum_bytes=real_object_store.settings.maximum_multipart_bytes,
    )
    assert (await reconciler.run_once()).moves_processed == 1
    await _queue_move(
        object_content_database,
        target_kind=StorageKind.POSTGRES_INLINE,
        actor_id=actor_id,
        target_maximum_bytes=real_object_store.settings.inline_maximum_bytes,
    )
    original_complete = ObjectContentMoveRepository.complete_to_inline

    async def crash_before_inline_flip(
        self: ObjectContentMoveRepository,
        *,
        content_id: UUID,
        lease_owner: str,
        payload: bytes,
        captured_size_bytes: int,
        captured_sha256: bytes,
        orphan_grace_seconds: int,
    ) -> None:
        raise SimulatedWorkerCrash

    monkeypatch.setattr(
        ObjectContentMoveRepository,
        "complete_to_inline",
        crash_before_inline_flip,
    )
    with pytest.raises(SimulatedWorkerCrash):
        await reconciler.run_once()
    async with object_content_database.session() as session, session.begin():
        content = await session.get(ObjectContents, content_id)
        inline = await session.get(InlineContentPayloads, content_id)
        descriptor = await session.get(ObjectStoreObjects, content_id)
        move = await session.get(ObjectContentMoves, content_id)
        assert content is not None
        assert descriptor is not None
        assert move is not None
        object_key = descriptor.object_key
        assert inline is None
        assert content.storage_kind == StorageKind.OBJECT_STORE.value
        assert move.state == "pending"
    assert (await real_object_store.store.head(object_key)).size_bytes == len(payload)
    await _expire_crashed_operation(
        object_content_database,
        content_id=content_id,
        object_key=None,
    )
    monkeypatch.setattr(
        ObjectContentMoveRepository,
        "complete_to_inline",
        original_complete,
    )
    assert (await reconciler.run_once()).moves_processed == 1
    async with object_content_database.session() as session, session.begin():
        content = await session.get(ObjectContents, content_id)
        inline = await session.get(InlineContentPayloads, content_id)
        move = await session.get(ObjectContentMoves, content_id)
        assert content is not None
        assert inline is not None
        assert move is None
        assert content.storage_kind == StorageKind.POSTGRES_INLINE.value
        assert inline.payload == payload


@pytest.mark.integration
@pytest.mark.asyncio
async def test_local_timeout_is_not_reported_as_a_store_outage(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content_id, actor_id = await _create_inline_content(
        object_content_database,
        payload=b"local timeout",
        idempotency_key=f"move-{uuid4().hex}",
    )
    reconciler = ObjectContentReconciler(
        real_object_store.settings,
        object_content_database,
        object_store_settings=real_object_store.settings,
        object_store=real_object_store.store,
    )
    await _queue_move(
        object_content_database,
        target_kind=StorageKind.OBJECT_STORE,
        actor_id=actor_id,
        target_maximum_bytes=real_object_store.settings.maximum_multipart_bytes,
    )
    monkeypatch.setattr(
        ObjectContentMoveExecutor,
        "_move_to_object_store",
        AsyncMock(side_effect=TimeoutError("local operation timed out")),
    )

    with pytest.raises(TimeoutError, match="local operation timed out"):
        await reconciler.run_once()

    async with object_content_database.session() as session, session.begin():
        content = await session.get(ObjectContents, content_id)
        move = await session.get(ObjectContentMoves, content_id)
        assert content is not None
        assert move is not None
        assert content.storage_kind == StorageKind.POSTGRES_INLINE.value
        assert move.state == "pending"
        assert move.failure_code is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_move_candidate_query_uses_bounded_ordered_index(
    object_content_database: DatabaseSessionManager,
) -> None:
    async with object_content_database.session() as session, session.begin():
        tenant_id = (await session.scalars(select(Tenants.id))).one()
        user_id = (await session.scalars(select(Users.id))).one()
        owner = Files(
            name="move-plan.bin",
            mimetype="application/octet-stream",
            file_type="text",
            tenant_id=tenant_id,
            user_id=user_id,
            parent_file_id=None,
        )
        session.add(owner)
        await session.flush()
        await session.execute(
            text(
                """
                WITH created AS (
                    INSERT INTO object_contents (
                        id, tenant_id, storage_kind, state, access_class,
                        sha256, size_bytes, declared_media_type,
                        verified_media_type, idempotency_key,
                        request_fingerprint, available_at
                    )
                    SELECT
                        gen_random_uuid(), :tenant_id, 'postgres_inline',
                        'available', 'private_resource',
                        decode(repeat('00', 32), 'hex'), 0,
                        'application/octet-stream', 'application/octet-stream',
                        'move-plan-' || candidate::text,
                        decode(repeat('00', 32), 'hex'), now()
                    FROM generate_series(1, 20000) AS candidate
                    RETURNING id
                ), stored AS (
                    INSERT INTO inline_content_payloads (content_id, payload)
                    SELECT id, ''::bytea FROM created
                    RETURNING content_id
                )
                INSERT INTO file_content_references (
                    file_id, content_id, variant, ordinal
                )
                SELECT
                    :file_id,
                    content_id,
                    'generated_artifact',
                    row_number() OVER (ORDER BY content_id) - 1
                FROM stored
                """
            ),
            {"tenant_id": tenant_id, "file_id": owner.id},
        )
        await session.execute(text("ANALYZE object_contents, object_content_moves"))
        explained = await session.scalar(
            text(
                """
                EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
                SELECT content.id
                FROM object_contents AS content
                LEFT JOIN object_content_moves AS move
                    ON move.content_id = content.id
                WHERE content.storage_kind = 'postgres_inline'
                  AND content.state = 'available'
                  AND content.reference_count > 0
                  AND content.delete_requested_at IS NULL
                  AND (content.lease_until IS NULL OR content.lease_until <= now())
                  AND (
                      move.content_id IS NULL
                      OR (
                          move.state = 'failed'
                          AND (
                              move.target_kind <> 'object_store'
                              OR move.failure_code <> 'target_too_large'
                              OR content.size_bytes <= 1
                          )
                      )
                  )
                ORDER BY content.created_at, content.id
                LIMIT 10
                FOR UPDATE OF content SKIP LOCKED
                """
            )
        )

    plan = json.loads(explained) if isinstance(explained, str) else explained
    plan_text = json.dumps(plan)
    plan_nodes = re.findall(
        r'"(?:Node Type|Relation Name|Index Name)": "[^"]+"',
        plan_text,
    )
    assert "ix_object_contents_move_candidates" in plan_text, plan_nodes
