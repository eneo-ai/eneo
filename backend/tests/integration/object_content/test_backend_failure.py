import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from hashlib import sha256
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text

from eneo.database.database import DatabaseSessionManager
from eneo.database.tables.file_icon_backfill_table import (
    FileIconBackfillCampaign,
    FileIconBackfillItems,
)
from eneo.database.tables.object_content_table import (
    FileContentReferences,
    InlineContentPayloads,
    ObjectContents,
)
from eneo.object_content.configuration import ObjectContentSettings
from eneo.object_content.content import (
    ContentAccessClass,
    ContentReadGrant,
    ObjectContentUnavailableError,
    StorageKind,
)
from eneo.object_content.content_repository import ObjectContentRepository
from eneo.object_content.content_service import ObjectContentService
from eneo.object_content.file_icon_backfill import (
    FileIconBackfill,
    _FileIconBackfillRepository,
)
from eneo.object_content.move_repository import ObjectContentMoveRepository
from eneo.object_content.object_store_provider import (
    ObjectStoreLease,
    ObjectStoreProvider,
)
from eneo.object_content.reconciliation import ObjectContentReconciler
from eneo.object_content.reconciliation_repository import (
    ObjectContentReconciliationRepository,
)
from eneo.object_content.s3_object_store import (
    MultipartUploadPage,
    ObjectStoreNotFoundError,
    RemoteObject,
    RemoteObjectPage,
    S3ObjectStore,
)
from tests.integration.object_content.test_file_icon_inline_backfill import (
    _backfill,
    _seed_legacy_text,
    _tenant_and_user,
)
from tests.integration.object_content.test_moves import (
    _create_object_store_content,
    _publish_object_store_move,
    _queue_move,
)
from tests.integration.object_content.test_store_generation_fence import (
    _advance_connection_revision,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _settings() -> ObjectContentSettings:
    return ObjectContentSettings(
        _env_file=None,
        endpoint_url="http://localhost:1",
        region="local",
        bucket="failure-test",
        access_key_id="test",
        secret_access_key="test",
        deployment_id=uuid4(),
        allow_insecure_http=True,
    )


async def _adopt_remote_content(
    database: DatabaseSessionManager, payload: bytes
) -> tuple[UUID, UUID, str, FileIconBackfill]:
    file_id = await _seed_legacy_text(database, payload=payload)
    backfill = _backfill(database)
    assert (await backfill.run_once()).state.value == "complete"
    _, actor_id = await _tenant_and_user(database)
    async with database.session() as session, session.begin():
        content_id = await session.scalar(
            select(FileContentReferences.content_id).where(
                FileContentReferences.file_id == file_id
            )
        )
    assert content_id is not None
    object_key = await _publish_object_store_move(
        database, content_id=content_id, actor_id=actor_id, payload=payload
    )
    return file_id, content_id, object_key, backfill


def _inventory_reconciler(
    database: DatabaseSessionManager, *, objects: tuple[RemoteObject, ...]
) -> ObjectContentReconciler:
    store = MagicMock(spec=S3ObjectStore)
    store.list_object_page.return_value = RemoteObjectPage(objects, None)
    store.list_multipart_page.return_value = MultipartUploadPage((), None, None)
    settings = _settings()
    return ObjectContentReconciler(
        settings,
        database,
        object_store_provider=ObjectStoreProvider.fixed(settings, store),
    )


async def _complete_empty_inventories(database: DatabaseSessionManager) -> None:
    for _ in range(2):
        async with database.session() as session, session.begin():
            repository = ObjectContentReconciliationRepository(session)
            cursor = await repository.object_inventory_cursor()
            result = await repository.record_object_page(
                cursor=cursor, objects=(), next_token=None, orphan_grace_seconds=300
            )
            assert result.completed


@pytest.mark.parametrize("move_back_remote", [False, True])
async def test_ranged_read_handles_placement_changes_before_returning_bytes(
    object_content_database: DatabaseSessionManager,
    monkeypatch: pytest.MonkeyPatch,
    move_back_remote: bool,
) -> None:
    database = object_content_database
    payload = b"healthy bytes retained across the move"
    content_id, actor_id = await _create_object_store_content(
        database, payload=payload, idempotency_key=f"read-move-{uuid4().hex}"
    )
    await _queue_move(
        database,
        target_kind=StorageKind.POSTGRES_INLINE,
        actor_id=actor_id,
        target_maximum_bytes=len(payload),
    )
    async with database.session() as session, session.begin():
        tenant_id = await session.scalar(
            select(ObjectContents.tenant_id).where(ObjectContents.id == content_id)
        )
    assert tenant_id is not None
    original = ObjectContentRepository.get_object_store_verification_chunks
    moves_completed = 0

    async def move_before_chunk_lookup(
        repository: ObjectContentRepository,
        *,
        content_id: UUID,
        object_key: str,
        first_chunk_index: int,
        chunk_count: int,
    ) -> tuple[bytes, ...]:
        nonlocal moves_completed
        if moves_completed:
            await _queue_move(
                database,
                target_kind=StorageKind.POSTGRES_INLINE,
                actor_id=actor_id,
                target_maximum_bytes=len(payload),
            )
        async with database.session() as session, session.begin():
            moves = ObjectContentMoveRepository(session)
            work = await moves.claim(lease_owner="read-move", lease_seconds=300)
            assert work is not None and work.content_id == content_id
            await moves.complete_to_inline(
                content_id=content_id,
                lease_owner="read-move",
                payload=payload,
                captured_size_bytes=len(payload),
                captured_sha256=sha256(payload).digest(),
                orphan_grace_seconds=300,
            )
        moves_completed += 1
        if move_back_remote:
            await _publish_object_store_move(
                database, content_id=content_id, actor_id=actor_id, payload=payload
            )
        return await original(
            repository,
            content_id=content_id,
            object_key=object_key,
            first_chunk_index=first_chunk_index,
            chunk_count=chunk_count,
        )

    monkeypatch.setattr(
        ObjectContentRepository,
        "get_object_store_verification_chunks",
        move_before_chunk_lookup,
    )
    settings = _settings()
    store = MagicMock(spec=S3ObjectStore)
    provider = ObjectStoreProvider.fixed(settings, store)
    original_acquire = provider.acquire
    remote_lease_active = False

    @asynccontextmanager
    async def observe_lease(
        *, refresh: bool = True, expected_revision: int | None = None
    ) -> AsyncGenerator[ObjectStoreLease, None]:
        nonlocal remote_lease_active
        async with original_acquire(
            refresh=refresh, expected_revision=expected_revision
        ) as lease:
            remote_lease_active = True
            try:
                yield lease
            finally:
                remote_lease_active = False

    monkeypatch.setattr(provider, "acquire", observe_lease)
    service = ObjectContentService(
        settings,
        database,
        object_store_provider=provider,
    )
    grant = ContentReadGrant(content_id, tenant_id, ContentAccessClass.PRIVATE_RESOURCE)
    if move_back_remote:
        with pytest.raises(ObjectContentUnavailableError, match="placement changed"):
            async with service.open_content(grant, range_header="bytes=0-6"):
                pytest.fail("Repeated placement changes must not yield response bytes")
        assert moves_completed == 2
    else:
        async with service.open_content(grant, range_header="bytes=0-6") as opened:
            assert not remote_lease_active
            assert b"".join([chunk async for chunk in opened.chunks]) == payload[:7]
        assert moves_completed == 1

    store.open_verified_read.assert_not_called()
    async with database.session() as session, session.begin():
        content = await session.get(ObjectContents, content_id)
        inline = await session.get(InlineContentPayloads, content_id)
        assert content is not None
        assert content.state == "available"
        if move_back_remote:
            assert inline is None
            assert content.storage_kind == StorageKind.OBJECT_STORE.value
        else:
            assert inline is not None and inline.payload == payload
            assert content.storage_kind == StorageKind.POSTGRES_INLINE.value
        assert content.failure_code is None


@pytest.mark.parametrize("failure", ["missing", "length"])
async def test_inventory_failure_reopens_adopted_content_recovery(
    object_content_database: DatabaseSessionManager,
    failure: str,
) -> None:
    database = object_content_database
    payload = b"frozen legacy recovery source"
    file_id, content_id, object_key, backfill = await _adopt_remote_content(
        database, payload
    )
    reconciler = _inventory_reconciler(
        database,
        objects=(RemoteObject(object_key, len(payload) + 1),)
        if failure == "length"
        else (),
    )
    for _ in range(2):
        await reconciler.run_once()

    assert (await backfill.run_once()).state.value == "halted"
    async with database.session() as session, session.begin():
        content = await session.get(ObjectContents, content_id)
        campaign = await session.scalar(select(FileIconBackfillCampaign))
        item = await session.scalar(
            select(FileIconBackfillItems).where(
                FileIconBackfillItems.owner_id == file_id
            )
        )
        assert content is not None and campaign is not None and item is not None
        assert content.state == "failed"
        assert content.failure_code == (
            "backend_corrupt" if failure == "length" else "backend_missing"
        )
        assert campaign.state == "halted"
        assert item.state == "failed"
        assert item.content_id is None
        assert not item.capacity_admitted
        assert item.failure_revision == campaign.resume_revision


async def test_read_failure_from_a_superseded_connection_keeps_content_available(
    object_content_database: DatabaseSessionManager,
) -> None:
    database = object_content_database
    content_id, _ = await _create_object_store_content(
        database, payload=b"healthy current placement", idempotency_key=uuid4().hex
    )
    async with database.session() as session, session.begin():
        tenant_id = await session.scalar(
            select(ObjectContents.tenant_id).where(ObjectContents.id == content_id)
        )
    assert tenant_id is not None

    async def missing_from_old_connection() -> None:
        await _advance_connection_revision(database, revision=1)
        raise ObjectStoreNotFoundError("The old connection no longer has these bytes")

    store = MagicMock(spec=S3ObjectStore)
    store.open_verified_read.return_value.__aenter__.side_effect = (
        missing_from_old_connection
    )
    settings = _settings()
    service = ObjectContentService(
        settings,
        database,
        object_store_provider=ObjectStoreProvider.fixed(settings, store),
    )
    with pytest.raises(ObjectContentUnavailableError):
        async with service.open_content(
            ContentReadGrant(content_id, tenant_id, ContentAccessClass.PRIVATE_RESOURCE)
        ):
            pytest.fail("The superseded connection must not yield a response")
    async with database.session() as session, session.begin():
        content = await session.get(ObjectContents, content_id)
        assert content is not None
        assert content.state == "available"
        assert content.failure_code is None


@pytest.mark.parametrize("failure", ["missing", "length"])
async def test_new_inventory_observation_supersedes_a_failure_candidate(
    object_content_database: DatabaseSessionManager,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    database = object_content_database
    payload = b"healthy bytes observed again"
    _, content_id, object_key, backfill = await _adopt_remote_content(database, payload)
    await _complete_empty_inventories(database)
    original = ObjectContentRepository._has_completed_file_icon_item
    observed_again = False

    async def observe_before_failure_lock(
        repository: ObjectContentRepository, checked_content_id: UUID
    ) -> bool:
        nonlocal observed_again
        if checked_content_id == content_id and not observed_again:
            async with database.session() as session, session.begin():
                inventory = ObjectContentReconciliationRepository(session)
                cursor = await inventory.object_inventory_cursor()
                await inventory.record_object_page(
                    cursor=cursor,
                    objects=(RemoteObject(object_key, len(payload)),),
                    next_token=None,
                    orphan_grace_seconds=300,
                )
            observed_again = True
        return await original(repository, checked_content_id)

    monkeypatch.setattr(
        ObjectContentRepository,
        "_has_completed_file_icon_item",
        observe_before_failure_lock,
    )
    result = await _inventory_reconciler(
        database,
        objects=(RemoteObject(object_key, len(payload) + 1),)
        if failure == "length"
        else (),
    ).run_once()
    assert observed_again
    assert result.missing_objects == 0
    assert (await backfill.run_once()).state.value == "complete"
    async with database.session() as session, session.begin():
        content = await session.get(ObjectContents, content_id)
        assert content is not None and content.state == "available"
        assert content.failure_code is None


@pytest.mark.parametrize("failure", ["missing", "length"])
async def test_inventory_recovery_waits_for_admission_without_locking_content(
    object_content_database: DatabaseSessionManager,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    database = object_content_database
    payload = b"adopted bytes with coordinated recovery"
    _, content_id, object_key, backfill = await _adopt_remote_content(database, payload)
    await _complete_empty_inventories(database)
    admission_held = asyncio.Event()
    release_admission = asyncio.Event()
    admission_pid: int | None = None
    original = _FileIconBackfillRepository.lock_admission

    async def pause_admission(repository: _FileIconBackfillRepository) -> None:
        nonlocal admission_pid
        await original(repository)
        if not admission_held.is_set():
            admission_pid = await repository._session.scalar(
                text("SELECT pg_backend_pid()")
            )
            admission_held.set()
            await release_admission.wait()

    monkeypatch.setattr(_FileIconBackfillRepository, "lock_admission", pause_admission)
    admission_task = asyncio.create_task(_backfill(database).run_once())
    inventory_task = None
    try:
        await asyncio.wait_for(admission_held.wait(), timeout=5)
        assert admission_pid is not None
        inventory_task = asyncio.create_task(
            _inventory_reconciler(
                database,
                objects=(RemoteObject(object_key, len(payload) + 1),)
                if failure == "length"
                else (),
            ).run_once()
        )

        async def wait_for_inventory_on_admission() -> bool:
            async with database.session() as session, session.begin():
                while not inventory_task.done():
                    waiting = await session.scalar(
                        text("""
                        SELECT EXISTS (
                            SELECT 1 FROM pg_stat_activity
                            WHERE datname = current_database()
                              AND :blocking_pid = ANY(pg_blocking_pids(pid))
                        )
                    """),
                        {"blocking_pid": admission_pid},
                    )
                    if waiting:
                        return True
                    await asyncio.sleep(0.01)
            return False

        assert await asyncio.wait_for(wait_for_inventory_on_admission(), timeout=5)
        async with database.session() as session, session.begin():
            locked = await session.scalar(
                select(ObjectContents.id)
                .where(ObjectContents.id == content_id)
                .with_for_update(nowait=True)
            )
            assert locked == content_id
    finally:
        release_admission.set()
        pending = [admission_task]
        if inventory_task is not None:
            pending.append(inventory_task)
        await asyncio.wait_for(asyncio.gather(*pending), timeout=5)
    assert (await backfill.run_once()).state.value == "halted"
