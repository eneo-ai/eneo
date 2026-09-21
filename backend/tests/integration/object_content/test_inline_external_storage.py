import asyncio
import runpy
from collections.abc import AsyncIterator
from hashlib import sha256
from pathlib import Path
from random import Random
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, event, select, text, update
from sqlalchemy.exc import DBAPIError

from alembic.migration import MigrationContext
from alembic.operations import Operations
from eneo.database.database import DatabaseSessionManager
from eneo.database.tables.file_icon_backfill_table import (
    FileIconBackfillAdmissionState,
    FileIconBackfillCampaign,
    FileIconBackfillItems,
)
from eneo.database.tables.object_content_table import (
    FileContentReferences,
    InlineContentPayloads,
    ObjectContentReconciliationState,
    ObjectContents,
)
from eneo.object_content.configuration import ObjectContentCoreSettings
from eneo.object_content.content import (
    ContentAccessClass,
    ContentIntent,
    StorageKind,
    capture_content,
    content_request_fingerprint,
)
from eneo.object_content.content_repository import ObjectContentRepository
from eneo.object_content.content_service import ObjectContentService
from eneo.object_content.move_repository import ObjectContentMoveRepository
from eneo.object_content.reconciliation import ObjectContentReconciler
from eneo.object_content.reconciliation_repository import (
    INLINE_CONVERSION_LOCK_TIMEOUT_SECONDS,
    ObjectContentReconciliationRepository,
)
from tests.integration.object_content.test_file_icon_inline_backfill import (
    _backfill,
    _seed_legacy_text,
)
from tests.integration.object_content.test_moves import (
    _create_object_store_content,
    _publish_object_store_move,
    _queue_move,
)
from tests.integration.object_content.test_storage_ownership import _file, _owner_ids


async def _source(payload: bytes) -> AsyncIterator[bytes]:
    yield payload


async def _upload(
    database: DatabaseSessionManager,
    payload: bytes,
    *,
    copy_from: UUID | None = None,
) -> UUID:
    tenant_id, user_id = await _owner_ids(database)
    service = ObjectContentService(ObjectContentCoreSettings(_env_file=None), database)
    async with capture_content(
        _source(payload),
        declared_media_type="application/octet-stream",
        verified_media_type="application/octet-stream",
        maximum_size_bytes=len(payload),
        spool_memory_bytes=len(payload),
        multipart_part_bytes=len(payload),
    ) as captured:
        async with database.session() as session, session.begin():
            owner = _file(tenant_id=tenant_id, user_id=user_id, name="payload.bin")
            session.add(owner)
            await session.flush()
            intent = ContentIntent(
                tenant_id=tenant_id,
                created_by_user_id=user_id,
                access_class=ContentAccessClass.PRIVATE_RESOURCE,
                idempotency_key=str(uuid4()),
                producer_receipt=f"file:{owner.id}:original:0",
            )
            if copy_from is None:
                prepared = await service.prepare_in_transaction(
                    session,
                    intent=intent,
                    content=captured,
                    storage_kind=StorageKind.POSTGRES_INLINE,
                )
            else:
                prepared = await ObjectContentRepository(
                    session
                ).prepare_inline_from_select(
                    intent=intent,
                    content=captured,
                    payload_select=select(InlineContentPayloads.payload).where(
                        InlineContentPayloads.content_id == copy_from
                    ),
                    request_fingerprint=content_request_fingerprint(
                        intent, captured, StorageKind.POSTGRES_INLINE
                    ),
                )
            session.add(
                FileContentReferences(
                    file_id=owner.id,
                    content_id=prepared.id,
                    variant="original",
                    ordinal=0,
                )
            )
        return prepared.id


async def _physical_sizes(
    database: DatabaseSessionManager, content_id: UUID
) -> tuple[int, int]:
    async with database.session() as session, session.begin():
        row = (
            await session.execute(
                text(
                    "SELECT pg_column_size(payload), octet_length(payload) "
                    "FROM inline_content_payloads WHERE content_id = :id"
                ),
                {"id": content_id},
            )
        ).one()
        return row[0], row[1]


async def _legacy_upload(database: DatabaseSessionManager, payload: bytes) -> UUID:
    async with database.session() as session, session.begin():
        await session.execute(
            text(
                "ALTER TABLE inline_content_payloads "
                "ALTER COLUMN payload SET STORAGE EXTENDED"
            )
        )
    try:
        return await _upload(database, payload)
    finally:
        async with database.session() as session, session.begin():
            await session.execute(
                text(
                    "ALTER TABLE inline_content_payloads "
                    "ALTER COLUMN payload SET STORAGE EXTERNAL"
                )
            )


async def _corrupt_payload(
    database: DatabaseSessionManager, content_id: UUID, payload: bytes
) -> None:
    async with database.session() as session, session.begin():
        await session.execute(text("SET LOCAL session_replication_role = replica"))
        await session.execute(
            text(
                "ALTER TABLE inline_content_payloads ALTER COLUMN payload SET STORAGE EXTENDED"
            )
        )
        await session.execute(
            text(
                "UPDATE inline_content_payloads SET payload = :bad WHERE content_id = :id"
            ),
            {"id": content_id, "bad": payload},
        )
        await session.execute(
            text(
                "ALTER TABLE inline_content_payloads ALTER COLUMN payload SET STORAGE EXTERNAL"
            )
        )


@pytest.mark.asyncio
async def test_inline_payload_storage_is_external_on_postgres_13(
    object_content_database: DatabaseSessionManager,
) -> None:
    async with object_content_database.session() as session, session.begin():
        version = await session.scalar(text("SHOW server_version_num"))
        assert version is not None
        assert 130000 <= int(version) < 140000
        storage = await session.scalar(
            text(
                "SELECT attstorage::text FROM pg_attribute "
                "WHERE attrelid = 'inline_content_payloads'::regclass "
                "AND attname = 'payload'"
            )
        )
        assert storage == "e"


@pytest.mark.asyncio
@pytest.mark.parametrize("compressible", [True, False])
async def test_upload_and_database_copy_store_identical_uncompressed_bytes(
    object_content_database: DatabaseSessionManager, compressible: bool
) -> None:
    payload = b"a" * 1_048_576 if compressible else Random(0).randbytes(1_048_576)
    old_id = await _legacy_upload(object_content_database, payload)
    stored, logical = await _physical_sizes(object_content_database, old_id)
    assert logical == len(payload)
    if compressible:
        assert stored < logical // 10
    else:
        assert stored == logical

    fresh_id = await _upload(object_content_database, payload)
    copied_id = await _upload(object_content_database, payload, copy_from=old_id)
    for content_id in (fresh_id, copied_id):
        assert await _physical_sizes(object_content_database, content_id) == (
            len(payload),
            len(payload),
        )
        async with object_content_database.session() as session, session.begin():
            stored_payload = await session.scalar(
                select(InlineContentPayloads.payload).where(
                    InlineContentPayloads.content_id == content_id
                )
            )
            assert stored_payload == payload


@pytest.mark.asyncio
async def test_conversion_commits_a_bounded_batch_and_resumes_after_restart(
    object_content_database: DatabaseSessionManager,
) -> None:
    payload = b"a" * 1_048_576
    ids = sorted(
        [await _legacy_upload(object_content_database, payload) for _ in range(5)]
    )
    settings = ObjectContentCoreSettings(_env_file=None, reconciliation_batch_size=2)
    first = await ObjectContentReconciler(settings, object_content_database).run_once()
    for content_id in ids[:2]:
        assert await _physical_sizes(object_content_database, content_id) == (
            len(payload),
            len(payload),
        )
    for content_id in ids[2:]:
        stored, logical = await _physical_sizes(object_content_database, content_id)
        assert stored < logical
    assert first.inline_conversion.scanned == 2
    assert first.inline_conversion.converted == 2
    assert not first.inline_conversion.sweep_completed
    assert not first.inline_conversion.ready
    async with object_content_database.session() as session, session.begin():
        committed = (
            await session.execute(
                text(
                    "SELECT content_id, ctid::text FROM inline_content_payloads "
                    "WHERE content_id <= :id ORDER BY content_id"
                ),
                {"id": ids[1]},
            )
        ).all()

    restarted = ObjectContentReconciler(settings, object_content_database)
    second = await restarted.run_once()
    assert second.inline_conversion.converted == 2
    final = await restarted.run_once()
    assert final.inline_conversion.converted == 1
    assert final.inline_conversion.sweep_completed
    assert final.inline_conversion.ready
    async with object_content_database.session() as session, session.begin():
        assert (
            await session.execute(
                text(
                    "SELECT content_id, ctid::text FROM inline_content_payloads "
                    "WHERE content_id <= :id ORDER BY content_id"
                ),
                {"id": ids[1]},
            )
        ).all() == committed
        assert await session.scalar(
            text(
                "SELECT bool_and(sha256(p.payload) = c.sha256) "
                "FROM inline_content_payloads p JOIN object_contents c "
                "ON c.id = p.content_id"
            )
        )


@pytest.mark.asyncio
async def test_locked_conversion_row_does_not_starve_later_rows_or_report_ready(
    object_content_database: DatabaseSessionManager,
) -> None:
    database = object_content_database
    payload = b"a" * 1_048_576
    ids = sorted([await _legacy_upload(database, payload) for _ in range(3)])
    reconciler = ObjectContentReconciler(
        ObjectContentCoreSettings(_env_file=None, reconciliation_batch_size=3),
        database,
    )
    async with database.session() as locked, locked.begin():
        await locked.execute(
            select(ObjectContents.id)
            .where(ObjectContents.id == ids[0])
            .with_for_update()
        )
        result = await asyncio.wait_for(reconciler.run_once(), timeout=10)
        assert result.inline_conversion.converted == 2
        assert result.inline_conversion.skipped == 1
        assert not result.inline_conversion.sweep_completed
        assert not result.inline_conversion.ready
        assert (await _physical_sizes(database, ids[0]))[0] < len(payload)
    resumed = await reconciler.run_once()
    assert resumed.inline_conversion.converted == 1
    assert resumed.inline_conversion.sweep_completed
    assert resumed.inline_conversion.ready


@pytest.mark.asyncio
async def test_converted_row_is_not_hashed_again_on_a_retry_sweep(
    object_content_database: DatabaseSessionManager,
) -> None:
    database = object_content_database
    payload = b"a" * 1_048_576
    ids = sorted([await _legacy_upload(database, payload) for _ in range(2)])
    reconciler = ObjectContentReconciler(
        ObjectContentCoreSettings(_env_file=None, reconciliation_batch_size=2), database
    )
    statements: list[str] = []

    def capture_query(
        _connection, _cursor, statement, _parameters, _context, _executemany
    ) -> None:
        statements.append(statement.lower())

    async with database.session() as locked, locked.begin():
        await locked.execute(
            select(ObjectContents.id)
            .where(ObjectContents.id == ids[1])
            .with_for_update()
        )
        assert locked.bind is not None
        sync_engine = locked.bind.sync_engine
        event.listen(sync_engine, "before_cursor_execute", capture_query)
        try:
            first = await reconciler.run_once()
            assert first.inline_conversion.scanned == 2
            assert first.inline_conversion.converted == 1
            assert first.inline_conversion.skipped == 1
            assert not first.inline_conversion.sweep_completed
            assert await _physical_sizes(database, ids[0]) == (
                len(payload),
                len(payload),
            )
            assert any("sha256(" in statement for statement in statements)
            statements.clear()

            retry = await reconciler.run_once()
            assert retry.inline_conversion.scanned == 2
            assert retry.inline_conversion.converted == 0
            assert retry.inline_conversion.skipped == 1
            assert not retry.inline_conversion.sweep_completed
            assert not retry.inline_conversion.ready
            assert any("pg_column_size(" in statement for statement in statements)
            assert not any("sha256(" in statement for statement in statements)
        finally:
            event.remove(sync_engine, "before_cursor_execute", capture_query)

    final = await reconciler.run_once()
    assert final.inline_conversion.converted == 1
    assert final.inline_conversion.ready


@pytest.mark.asyncio
async def test_compressed_corruption_is_detected_when_lengths_match(
    object_content_database: DatabaseSessionManager,
) -> None:
    database = object_content_database
    payload = b"a" * 1_048_576
    content_id = await _legacy_upload(database, payload)
    await _corrupt_payload(database, content_id, b"b" * len(payload))
    stored, logical = await _physical_sizes(database, content_id)
    assert stored < logical
    assert logical == len(payload)

    result = await ObjectContentReconciler(
        ObjectContentCoreSettings(_env_file=None, reconciliation_batch_size=1), database
    ).run_once()
    assert result.inline_conversion.scanned == 1
    assert result.inline_conversion.converted == 0
    assert result.inline_conversion.rejected == 1
    assert result.inline_conversion.sweep_completed
    assert not result.inline_conversion.ready
    assert await _physical_sizes(database, content_id) == (stored, logical)
    async with database.session() as session, session.begin():
        content = await session.get(ObjectContents, content_id)
        assert content is not None
        assert content.state == "failed"
        assert content.failure_code == "backend_corrupt"
        assert content.sha256 == sha256(payload).digest()


@pytest.mark.asyncio
@pytest.mark.parametrize("length_delta", [0, -1])
async def test_corrupt_conversion_row_is_rejected_without_blocking_completion(
    object_content_database: DatabaseSessionManager, length_delta: int
) -> None:
    database = object_content_database
    payload = b"a" * 1_048_576
    ids = sorted([await _legacy_upload(database, payload) for _ in range(3)])
    await _corrupt_payload(database, ids[1], b"b" * (len(payload) + length_delta))
    result = await ObjectContentReconciler(
        ObjectContentCoreSettings(_env_file=None, reconciliation_batch_size=3), database
    ).run_once()
    assert result.inline_conversion.converted == 2
    assert result.inline_conversion.rejected == 1
    assert result.inline_conversion.sweep_completed
    assert not result.inline_conversion.ready
    async with database.session() as session, session.begin():
        corrupt = await session.get(ObjectContents, ids[1])
        assert corrupt is not None
        assert corrupt.state == "failed"
        assert corrupt.failure_code == "backend_corrupt"
        progress = await session.get(ObjectContentReconciliationState, 1)
        assert progress is not None
        assert progress.inline_conversion_rejected == 1
        assert progress.inline_conversion_completed_at is not None
        assert progress.inline_conversion_ready_at is None
    assert (await _physical_sizes(database, ids[1]))[0] < len(payload)


@pytest.mark.asyncio
async def test_length_corrupt_quarantine_keeps_fences_and_can_be_deleted(
    object_content_database: DatabaseSessionManager,
) -> None:
    database = object_content_database
    payload = b"a" * 1_048_576
    content_id = await _legacy_upload(database, payload)
    await _corrupt_payload(database, content_id, b"b" * (len(payload) - 1))
    with pytest.raises(DBAPIError, match="inline payload size does not match"):
        async with database.session() as session, session.begin():
            await session.execute(
                text(
                    "UPDATE object_contents SET updated_at = updated_at WHERE id = :id"
                ),
                {"id": content_id},
            )

    result = await ObjectContentReconciler(
        ObjectContentCoreSettings(_env_file=None), database
    ).run_once()
    assert result.inline_conversion.rejected == 1
    with pytest.raises(DBAPIError, match="inline content payload is immutable"):
        async with database.session() as session, session.begin():
            await session.execute(
                update(InlineContentPayloads)
                .where(InlineContentPayloads.content_id == content_id)
                .values(payload=payload)
            )
    with pytest.raises(DBAPIError, match="exactly one matching byte backend"):
        async with database.session() as session, session.begin():
            await session.execute(
                delete(InlineContentPayloads).where(
                    InlineContentPayloads.content_id == content_id
                )
            )
    async with database.session() as session, session.begin():
        await session.execute(
            delete(FileContentReferences).where(
                FileContentReferences.content_id == content_id
            )
        )
    async with database.session() as session, session.begin():
        assert (
            await ObjectContentReconciliationRepository(
                session
            ).advance_local_lifecycle(limit=1, pending_stale_seconds=300)
            == 1
        )
    async with database.session() as session, session.begin():
        content = await session.get(ObjectContents, content_id)
        assert content is not None and content.state == "delete_pending"
        assert (
            await ObjectContentReconciliationRepository(
                session
            ).tombstone_inline_deletions(limit=1)
            == 1
        )
    async with database.session() as session, session.begin():
        content = await session.get(ObjectContents, content_id)
        assert content is not None and content.state == "tombstoned"
        assert await session.get(InlineContentPayloads, content_id) is None


@pytest.mark.asyncio
async def test_cancelled_conversion_rolls_back_only_the_uncommitted_row(
    object_content_database: DatabaseSessionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = object_content_database
    payload = b"a" * 1_048_576
    ids = sorted([await _legacy_upload(database, payload) for _ in range(3)])
    original = ObjectContentReconciliationRepository.convert_next_inline_payload
    calls = 0

    async def cancel_second(repository: ObjectContentReconciliationRepository):
        nonlocal calls
        result = await original(repository)
        calls += 1
        if calls == 2:
            raise asyncio.CancelledError
        return result

    settings = ObjectContentCoreSettings(_env_file=None, reconciliation_batch_size=3)
    with monkeypatch.context() as patch:
        patch.setattr(
            ObjectContentReconciliationRepository,
            "convert_next_inline_payload",
            cancel_second,
        )
        with pytest.raises(asyncio.CancelledError):
            await ObjectContentReconciler(settings, database).run_once()
    assert (await _physical_sizes(database, ids[0]))[0] == len(payload)
    for content_id in ids[1:]:
        assert (await _physical_sizes(database, content_id))[0] < len(payload)
    result = await ObjectContentReconciler(settings, database).run_once()
    assert result.inline_conversion.scanned == 2
    assert result.inline_conversion.converted == 2
    assert result.inline_conversion.ready


@pytest.mark.asyncio
async def test_quarantine_migration_is_transactional_idempotent_and_reversible(
    object_content_database: DatabaseSessionManager,
) -> None:
    database = object_content_database
    payload = b"a" * 1_048_576
    content_id = await _legacy_upload(database, payload)
    await _corrupt_payload(database, content_id, payload[:-1])
    before = await _physical_sizes(database, content_id)
    migration = runpy.run_path(
        str(
            Path(__file__).parents[3]
            / "alembic/versions/202609211300_inline_corrupt_quarantine.py"
        )
    )

    def apply(session, direction):
        with Operations.context(MigrationContext.configure(session.connection())):
            migration[direction]()

    fence_sql = text(
        "SELECT pg_get_functiondef('object_content_storage_owner_fence()'::regprocedure)"
    )
    identity_sql = text(
        "SELECT pg_get_functiondef('inline_content_payload_identity_fence()'::regprocedure)"
    )
    quarantine = (
        update(ObjectContents)
        .where(ObjectContents.id == content_id)
        .values(state="failed", failure_code="backend_corrupt")
    )
    async with database.session() as session, session.begin():
        identity_before = await session.scalar(identity_sql)
        await session.execute(text("SET LOCAL lock_timeout = '1ms'"))
        await session.run_sync(apply, "downgrade")
        assert (
            await session.scalar(text("SHOW lock_timeout"))
            == f"{INLINE_CONVERSION_LOCK_TIMEOUT_SECONDS}s"
        )
        original_fence = await session.scalar(fence_sql)
        with pytest.raises(DBAPIError, match="inline payload size does not match"):
            async with session.begin_nested():
                await session.execute(quarantine)
                await session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        with pytest.raises(RuntimeError, match="interrupted migration"):
            async with session.begin_nested():
                await session.run_sync(apply, "upgrade")
                assert await session.scalar(fence_sql) != original_fence
                raise RuntimeError("interrupted migration")
        assert await session.scalar(fence_sql) == original_fence
        await session.execute(text("SET LOCAL lock_timeout = '1ms'"))
        await session.run_sync(apply, "upgrade")
        assert (
            await session.scalar(text("SHOW lock_timeout"))
            == f"{INLINE_CONVERSION_LOCK_TIMEOUT_SECONDS}s"
        )
        upgraded_fence = await session.scalar(fence_sql)
        await session.run_sync(apply, "upgrade")
        assert await session.scalar(fence_sql) == upgraded_fence
        assert await session.scalar(identity_sql) == identity_before
        await session.execute(quarantine)
    async with database.session() as session, session.begin():
        content = await session.get(ObjectContents, content_id)
        assert content is not None and content.state == "failed"
    assert await _physical_sizes(database, content_id) == before


@pytest.mark.asyncio
async def test_external_migration_is_transactional_idempotent_and_metadata_only(
    object_content_database: DatabaseSessionManager,
) -> None:
    database = object_content_database
    payload = b"a" * 1_048_576
    content_id = await _legacy_upload(database, payload)
    before = await _physical_sizes(database, content_id)
    migration = runpy.run_path(
        str(
            Path(__file__).parents[3]
            / "alembic/versions/202609211200_inline_external_storage.py"
        )
    )

    def apply(session, direction):
        with Operations.context(MigrationContext.configure(session.connection())):
            migration[direction]()

    storage_sql = text(
        "SELECT attstorage::text FROM pg_attribute "
        "WHERE attrelid = 'inline_content_payloads'::regclass AND attname = 'payload'"
    )
    async with database.session() as session, session.begin():
        relation_before = await session.scalar(
            text(
                "SELECT relfilenode FROM pg_class WHERE oid = 'inline_content_payloads'::regclass"
            )
        )
        fence_before = await session.scalar(
            text(
                "SELECT pg_get_functiondef('inline_content_payload_identity_fence()'::regprocedure)"
            )
        )
        await session.run_sync(apply, "downgrade")
        with pytest.raises(RuntimeError, match="interrupted migration"):
            async with session.begin_nested():
                await session.run_sync(apply, "upgrade")
                assert await session.scalar(storage_sql) == "e"
                raise RuntimeError("interrupted migration")
        assert await session.scalar(storage_sql) == "x"
        assert not await session.scalar(
            text(
                "SELECT EXISTS (SELECT 1 FROM pg_attribute "
                "WHERE attrelid = 'object_content_reconciliation_state'::regclass "
                "AND attname = 'inline_conversion_cursor_id' AND NOT attisdropped)"
            )
        )
        await session.execute(text("SET LOCAL lock_timeout = '1ms'"))
        await session.run_sync(apply, "upgrade")
        assert (
            await session.scalar(text("SHOW lock_timeout"))
            == f"{INLINE_CONVERSION_LOCK_TIMEOUT_SECONDS}s"
        )
        await session.execute(
            text(
                "UPDATE object_content_reconciliation_state SET inline_conversion_converted = 7"
            )
        )
        await session.run_sync(apply, "upgrade")
        assert await session.scalar(storage_sql) == "e"
        assert (
            await session.scalar(text("SHOW lock_timeout"))
            == f"{INLINE_CONVERSION_LOCK_TIMEOUT_SECONDS}s"
        )
        assert (
            await session.scalar(
                text(
                    "SELECT inline_conversion_converted FROM object_content_reconciliation_state"
                )
            )
            == 7
        )
        assert (
            await session.scalar(
                text(
                    "SELECT relfilenode FROM pg_class WHERE oid = 'inline_content_payloads'::regclass"
                )
            )
            == relation_before
        )
        assert (
            await session.scalar(
                text(
                    "SELECT pg_get_functiondef('inline_content_payload_identity_fence()'::regprocedure)"
                )
            )
            == fence_before
        )
    assert await _physical_sizes(database, content_id) == before
    with pytest.raises(DBAPIError, match="inline content payload is immutable"):
        async with database.session() as session, session.begin():
            await session.execute(
                update(InlineContentPayloads)
                .where(InlineContentPayloads.content_id == content_id)
                .values(payload=b"b" * len(payload))
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("compressible", [True, False])
async def test_move_into_inline_stores_uncompressed_identical_bytes(
    object_content_database: DatabaseSessionManager, compressible: bool
) -> None:
    database = object_content_database
    payload = b"a" * 1_048_576 if compressible else Random(0).randbytes(1_048_576)
    content_id, actor_id = await _create_object_store_content(
        database, payload=payload, idempotency_key=str(uuid4())
    )
    await _queue_move(
        database,
        target_kind=StorageKind.POSTGRES_INLINE,
        actor_id=actor_id,
        target_maximum_bytes=len(payload),
    )
    async with database.session() as session, session.begin():
        moves = ObjectContentMoveRepository(session)
        work = await moves.claim(lease_owner="external-test", lease_seconds=300)
        assert work is not None and work.content_id == content_id
        await moves.complete_to_inline(
            content_id=content_id,
            lease_owner="external-test",
            payload=payload,
            captured_size_bytes=len(payload),
            captured_sha256=sha256(payload).digest(),
            orphan_grace_seconds=300,
        )
    assert await _physical_sizes(database, content_id) == (len(payload), len(payload))
    async with database.session() as session, session.begin():
        assert (
            await session.scalar(
                select(InlineContentPayloads.payload).where(
                    InlineContentPayloads.content_id == content_id
                )
            )
            == payload
        )


@pytest.mark.asyncio
async def test_overlapping_ticks_cannot_advance_uncommitted_conversion_progress(
    object_content_database: DatabaseSessionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = object_content_database
    payload = b"a" * 1_048_576
    ids = [await _legacy_upload(database, payload) for _ in range(3)]
    original = ObjectContentReconciliationRepository.convert_next_inline_payload
    converted = asyncio.Event()
    release = asyncio.Event()

    async def hold_first(repository):
        result = await original(repository)
        if result.converted and not converted.is_set():
            converted.set()
            await release.wait()
        return result

    monkeypatch.setattr(
        ObjectContentReconciliationRepository, "convert_next_inline_payload", hold_first
    )
    settings = ObjectContentCoreSettings(_env_file=None, reconciliation_batch_size=3)
    first = asyncio.create_task(ObjectContentReconciler(settings, database).run_once())
    try:
        await asyncio.wait_for(converted.wait(), timeout=5)
        other = await asyncio.wait_for(
            ObjectContentReconciler(settings, database).run_once(), timeout=5
        )
        assert other.inline_conversion.scanned == 0
        assert not other.inline_conversion.ready
        for content_id in ids:
            assert (await _physical_sizes(database, content_id))[0] < len(payload)
    finally:
        release.set()
        result = await asyncio.wait_for(first, timeout=5)
    assert result.inline_conversion.converted == 3
    assert result.inline_conversion.ready


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["move", "delete"])
async def test_discovered_conversion_row_can_move_or_be_deleted(
    object_content_database: DatabaseSessionManager,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
) -> None:
    database = object_content_database
    payload = b"a" * 1_048_576
    content_id = await _legacy_upload(database, payload)
    _, actor_id = await _owner_ids(database)
    original = ObjectContentReconciliationRepository._convert_inline_payload

    async def change_before_lock(repository, discovered_id):
        assert discovered_id == content_id
        if action == "move":
            await _publish_object_store_move(
                database, content_id=content_id, actor_id=actor_id, payload=payload
            )
        else:
            async with database.session() as session, session.begin():
                await session.execute(
                    delete(FileContentReferences).where(
                        FileContentReferences.content_id == content_id
                    )
                )
                local = ObjectContentReconciliationRepository(session)
                await local.advance_local_lifecycle(limit=1, pending_stale_seconds=300)
                assert await local.tombstone_inline_deletions(limit=1) == 1
        return await original(repository, discovered_id)

    monkeypatch.setattr(
        ObjectContentReconciliationRepository,
        "_convert_inline_payload",
        change_before_lock,
    )
    result = await ObjectContentReconciler(
        ObjectContentCoreSettings(_env_file=None), database
    ).run_once()
    assert result.inline_conversion.converted == 0
    assert result.inline_conversion.rejected == 0
    assert result.inline_conversion.ready
    async with database.session() as session, session.begin():
        content = await session.get(ObjectContents, content_id)
        assert content is not None
        assert content.state == ("available" if action == "move" else "tombstoned")
        assert await session.get(InlineContentPayloads, content_id) is None


@pytest.mark.asyncio
async def test_external_substring_plan_fetches_a_fraction_of_the_payload(
    object_content_database: DatabaseSessionManager,
) -> None:
    database = object_content_database
    payload = b"a" * 1_048_576
    content_id = await _legacy_upload(database, payload)
    async with database.session() as session, session.begin():
        conversion_plan = await session.scalar(
            text(
                "EXPLAIN (ANALYZE, BUFFERS, WAL, FORMAT JSON) "
                "UPDATE inline_content_payloads SET payload = payload || ''::bytea "
                "WHERE content_id = :id"
            ),
            {"id": content_id},
        )
    assert await _physical_sizes(database, content_id) == (len(payload), len(payload))
    async with database.session() as session, session.begin():
        plans = []
        for expression in ("substring(payload FROM 32769 FOR 4096)", "payload"):
            plan = await session.scalar(
                text(
                    f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) SELECT sha256({expression}) "
                    "FROM inline_content_payloads WHERE content_id = :id"
                ),
                {"id": content_id},
            )
            plans.append(plan[0]["Plan"])
        blocks = [p["Shared Hit Blocks"] + p["Shared Read Blocks"] for p in plans]
        assert blocks[0] < blocks[1] // 4
        ranged = await session.scalar(
            text(
                "SELECT substring(payload FROM 32769 FOR 4096) FROM inline_content_payloads WHERE content_id = :id"
            ),
            {"id": content_id},
        )
        assert ranged == payload[32768:36864]
        assert len(ranged) == 4096
    print(
        {
            "payload_bytes": len(payload),
            "range_blocks": blocks[0],
            "full_blocks": blocks[1],
            "conversion_wal_bytes": conversion_plan[0]["Plan"]["WAL Bytes"],
        }
    )


@pytest.mark.asyncio
async def test_corruption_recovery_releases_content_before_waiting_for_admission(
    object_content_database: DatabaseSessionManager,
) -> None:
    database = object_content_database
    payload = b"a" * 1_048_576
    file_id = await _seed_legacy_text(database, payload=payload)
    backfill = _backfill(
        database,
        auto_inline_max_bytes=len(payload),
        batch_bytes=len(payload),
        inline_maximum_bytes=len(payload),
    )
    assert (await backfill.run_once()).state.value == "complete"
    async with database.session() as session, session.begin():
        content_id = await session.scalar(
            select(FileContentReferences.content_id).where(
                FileContentReferences.file_id == file_id
            )
        )
    assert content_id is not None
    await _corrupt_payload(database, content_id, b"b" * len(payload))
    task = None
    try:
        async with database.session() as admission, admission.begin():
            await admission.execute(
                select(FileIconBackfillAdmissionState).with_for_update()
            )
            blocking_pid = await admission.scalar(text("SELECT pg_backend_pid()"))
            task = asyncio.create_task(
                ObjectContentReconciler(
                    ObjectContentCoreSettings(_env_file=None), database
                ).run_once()
            )

            async def waiting_on_admission():
                async with database.session() as observer, observer.begin():
                    while not task.done():
                        if await observer.scalar(
                            text(
                                "SELECT EXISTS (SELECT 1 FROM pg_stat_activity WHERE datname = current_database() AND :pid = ANY(pg_blocking_pids(pid)))"
                            ),
                            {"pid": blocking_pid},
                        ):
                            return True
                        await asyncio.sleep(0.01)
                return False

            assert await asyncio.wait_for(waiting_on_admission(), timeout=4)
            async with database.session() as session, session.begin():
                assert (
                    await session.scalar(
                        select(ObjectContents.id)
                        .where(ObjectContents.id == content_id)
                        .with_for_update(nowait=True)
                    )
                    == content_id
                )
    finally:
        if task is not None:
            result = await asyncio.wait_for(task, timeout=10)
    assert result.inline_conversion.rejected == 1
    async with database.session() as session, session.begin():
        campaign = await session.scalar(select(FileIconBackfillCampaign))
        item = await session.scalar(
            select(FileIconBackfillItems).where(
                FileIconBackfillItems.owner_id == file_id
            )
        )
        assert campaign is not None and campaign.state == "halted"
        assert item is not None and item.state == "failed" and item.content_id is None


@pytest.mark.asyncio
@pytest.mark.parametrize("detached_state", ["retained", "delete_pending"])
@pytest.mark.parametrize("handoff", ["observation", "completed_adoption"])
async def test_corruption_handoff_preserves_reference_detachment(
    object_content_database: DatabaseSessionManager,
    monkeypatch: pytest.MonkeyPatch,
    detached_state: str,
    handoff: str,
) -> None:
    database = object_content_database
    payload = b"a" * 1_048_576
    if handoff == "completed_adoption":
        file_id = await _seed_legacy_text(database, payload=payload)
        backfill = _backfill(
            database,
            auto_inline_max_bytes=len(payload),
            batch_bytes=len(payload),
            inline_maximum_bytes=len(payload),
        )
        assert (await backfill.run_once()).state.value == "complete"
        async with database.session() as session, session.begin():
            content_id = await session.scalar(
                select(FileContentReferences.content_id).where(
                    FileContentReferences.file_id == file_id
                )
            )
        assert content_id is not None
    else:
        content_id = await _legacy_upload(database, payload)
    if detached_state == "retained":
        async with database.session() as session, session.begin():
            await session.execute(
                update(ObjectContents)
                .where(ObjectContents.id == content_id)
                .values(minimum_retain_until=text("now() + interval '1 day'"))
            )
    await _corrupt_payload(database, content_id, b"b" * len(payload))
    original = ObjectContentRepository.mark_backend_failure

    async def detach_reference():
        async with database.session() as session, session.begin():
            await session.execute(
                select(ObjectContents.id)
                .where(ObjectContents.id == content_id)
                .with_for_update(nowait=True)
            )
            await session.execute(
                delete(FileContentReferences).where(
                    FileContentReferences.content_id == content_id
                )
            )
            assert (
                await session.scalar(
                    select(ObjectContents.state).where(ObjectContents.id == content_id)
                )
                == detached_state
            )

    async def detach_before_failure(repository, **kwargs):
        await detach_reference()
        return await original(repository, **kwargs)

    completed_checks: list[bool] = []
    if handoff == "completed_adoption":
        original_check = ObjectContentRepository._has_completed_file_icon_item
        original_lock = ObjectContentRepository._content_for_update

        async def completed_after_first_check(repository, checked_id):
            assert await original_check(repository, checked_id)
            completed = bool(completed_checks)
            completed_checks.append(completed)
            return completed

        async def detach_before_relocking(repository, locked_id):
            if len(completed_checks) == 2:
                await detach_reference()
            return await original_lock(repository, locked_id)

        monkeypatch.setattr(
            ObjectContentRepository,
            "_has_completed_file_icon_item",
            completed_after_first_check,
        )
        monkeypatch.setattr(
            ObjectContentRepository, "_content_for_update", detach_before_relocking
        )
    else:
        monkeypatch.setattr(
            ObjectContentRepository, "mark_backend_failure", detach_before_failure
        )
    reconciler = ObjectContentReconciler(
        ObjectContentCoreSettings(_env_file=None), database
    )
    result = await reconciler.run_once()
    assert result.inline_conversion.rejected == 1
    assert result.inline_conversion.sweep_completed
    assert not result.inline_conversion.ready
    if handoff == "completed_adoption":
        assert completed_checks == [False, True]
    async with database.session() as session, session.begin():
        content = await session.get(ObjectContents, content_id)
        assert content is not None and content.state == detached_state
        assert content.reference_count == 0
        assert content.delete_requested_at is not None
        assert content.failure_code == (
            "backend_corrupt" if detached_state == "retained" else None
        )
        if handoff == "completed_adoption":
            item = await session.scalar(
                select(FileIconBackfillItems).where(
                    FileIconBackfillItems.content_id == content_id
                )
            )
            assert item is not None and item.state == "done"
    if detached_state == "delete_pending":
        resumed = await reconciler.run_once()
        assert resumed.inline_deleted == 1
        assert resumed.inline_conversion.ready


@pytest.mark.asyncio
async def test_corruption_observation_cannot_fail_a_fresh_inline_placement(
    object_content_database: DatabaseSessionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = object_content_database
    payload = b"a" * 1_048_576
    content_id = await _legacy_upload(database, payload)
    await _corrupt_payload(database, content_id, b"b" * len(payload))
    _, actor_id = await _owner_ids(database)
    original = ObjectContentRepository.mark_backend_failure

    async def replace_placement(repository, **kwargs):
        await _publish_object_store_move(
            database, content_id=content_id, actor_id=actor_id, payload=payload
        )
        await _queue_move(
            database,
            target_kind=StorageKind.POSTGRES_INLINE,
            actor_id=actor_id,
            target_maximum_bytes=len(payload),
        )
        async with database.session() as session, session.begin():
            moves = ObjectContentMoveRepository(session)
            work = await moves.claim(lease_owner="replacement", lease_seconds=300)
            assert work is not None
            await moves.complete_to_inline(
                content_id=content_id,
                lease_owner="replacement",
                payload=payload,
                captured_size_bytes=len(payload),
                captured_sha256=sha256(payload).digest(),
                orphan_grace_seconds=300,
            )
        return await original(repository, **kwargs)

    monkeypatch.setattr(
        ObjectContentRepository, "mark_backend_failure", replace_placement
    )
    result = await ObjectContentReconciler(
        ObjectContentCoreSettings(_env_file=None), database
    ).run_once()
    assert result.inline_conversion.rejected == 0
    assert result.inline_conversion.ready
    async with database.session() as session, session.begin():
        content = await session.get(ObjectContents, content_id)
        assert content is not None and content.state == "available"
        assert content.failure_code is None
    assert await _physical_sizes(database, content_id) == (len(payload), len(payload))


@pytest.mark.asyncio
async def test_uncompressed_rows_count_toward_the_discovery_limit(
    object_content_database: DatabaseSessionManager,
) -> None:
    database = object_content_database
    payload = Random(0).randbytes(1_048_576)
    ids = [await _upload(database, payload) for _ in range(3)]
    ids.append(await _legacy_upload(database, b"a" * len(payload)))
    settings = ObjectContentCoreSettings(_env_file=None, reconciliation_batch_size=2)
    first = await ObjectContentReconciler(settings, database).run_once()
    assert first.inline_conversion.scanned == 2
    assert not first.inline_conversion.sweep_completed
    assert not first.inline_conversion.ready
    second = await ObjectContentReconciler(settings, database).run_once()
    assert second.inline_conversion.scanned == 2
    assert second.inline_conversion.sweep_completed
    assert second.inline_conversion.ready
    assert first.inline_conversion.converted + second.inline_conversion.converted == 1
