from hashlib import sha256
from random import Random

import pytest
from sqlalchemy import event, select, text

from eneo.database.database import DatabaseSessionManager
from eneo.database.tables.object_content_table import ObjectContentReconciliationState
from eneo.object_content.configuration import ObjectContentCoreSettings
from eneo.object_content.content import ContentAccessClass, ContentReadGrant
from eneo.object_content.content_service import ObjectContentService
from eneo.object_content.reconciliation import ObjectContentReconciler
from tests.integration.object_content.test_inline_external_storage import (
    _legacy_upload,
    _physical_sizes,
    _upload,
)
from tests.integration.object_content.test_storage_ownership import _owner_ids


async def _toast_chunks(database):
    async with database.session() as session, session.begin():
        relation = await session.scalar(
            text(
                "SELECT reltoastrelid::regclass::text FROM pg_class "
                "WHERE oid = 'inline_content_payloads'::regclass"
            )
        )
        return await session.scalar(text(f"SELECT count(*) FROM {relation}"))


@pytest.mark.parametrize("local_path", [False, True])
async def test_mixed_representations_dispatch_without_conversion(
    object_content_database, local_path
):
    database = object_content_database
    settings = ObjectContentCoreSettings(_env_file=None)
    fixtures = [
        ("compressed_external", b"a" * (2 * 1024 * 1024), True, True),
        ("compressed_heap", b"a" * 12000, True, False),
        ("uncompressed_external", Random(13).randbytes(2 * 1024 * 1024), False, True),
        ("small_heap", b"small heap payload", False, False),
        ("empty", b"", False, False),
    ]
    contents = []
    for name, payload, compressed, external in fixtures:
        before = await _toast_chunks(database)
        content_id = (
            await (_legacy_upload if compressed else _upload)(database, payload)
            if payload
            else await _empty_upload(database)
        )
        stored, raw = await _physical_sizes(database, content_id)
        assert raw == len(payload)
        assert (stored < raw) == compressed, name
        assert ((await _toast_chunks(database)) > before) == external, name
        contents.append((content_id, payload, compressed))
    tenant_id, _ = await _owner_ids(database)
    async with database.session() as session, session.begin():
        assert (
            await session.scalar(
                select(ObjectContentReconciliationState.inline_conversion_ready_at)
            )
            is None
        )
    statements = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(database._engine.sync_engine, "before_cursor_execute", capture)
    try:
        for content_id, payload, compressed in contents:
            statements.clear()
            grant = ContentReadGrant(
                content_id, tenant_id, ContentAccessClass.PRIVATE_RESOURCE
            )
            async with ObjectContentService(settings, database).open_content(
                grant, require_local_path=local_path
            ) as opened:
                assert b"".join([chunk async for chunk in opened.chunks]) == payload
                if local_path and not compressed:
                    assert opened.verified_path.read_bytes() == payload
            assert any("substr(" in sql for sql in statements) == (
                bool(payload) and not compressed
            )
            assert (
                any(", inline_content_payloads.payload," in sql for sql in statements)
                == compressed
            )
            assert not any("inline_conversion_ready_at" in sql for sql in statements)
    finally:
        event.remove(database._engine.sync_engine, "before_cursor_execute", capture)


@pytest.mark.parametrize("compressed", [False, True])
async def test_metadata_size_functions_do_not_fetch_external_payload(
    object_content_database, compressed
):
    from eneo.object_content.content_repository import ContentReadSnapshot

    database = object_content_database
    payload = b"a" * (2 * 1024 * 1024)
    content_id = await (_legacy_upload if compressed else _upload)(database, payload)
    stored, raw = await _physical_sizes(database, content_id)
    assert (stored < raw) == compressed
    assert await _toast_chunks(database) > 0
    tenant_id, _ = await _owner_ids(database)
    grant = ContentReadGrant(content_id, tenant_id, ContentAccessClass.PRIVATE_RESOURCE)
    statements = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        if "octet_length(inline_content_payloads.payload)" in statement:
            statements.append((statement, parameters))

    event.listen(database._engine.sync_engine, "before_cursor_execute", capture)
    try:
        async with ContentReadSnapshot.open(database) as snapshot:
            (
                _,
                physical_size,
                slice_capable,
            ) = await snapshot.repository.get_read_metadata(grant)
    finally:
        event.remove(database._engine.sync_engine, "before_cursor_execute", capture)
    assert physical_size == len(payload)
    assert slice_capable == (not compressed)
    assert len(statements) == 1
    metadata, parameters = statements[0]
    assert "pg_column_size(inline_content_payloads.payload)" in metadata
    assert "inline_conversion_ready_at" not in metadata
    baseline = metadata.replace(
        "octet_length(inline_content_payloads.payload)",
        "inline_content_payloads.content_id",
    ).replace(
        "pg_column_size(inline_content_payloads.payload)",
        "inline_content_payloads.content_id",
    )
    detoast = metadata.replace(
        "pg_column_size(inline_content_payloads.payload)",
        "sha256(inline_content_payloads.payload)",
    )
    blocks = []
    async with database._engine.connect() as connection:
        for statement in (baseline, metadata, detoast):
            result = await connection.exec_driver_sql(
                "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + statement, parameters
            )
            plan = result.scalar_one()[0]["Plan"]
            blocks.append(plan["Shared Hit Blocks"] + plan["Shared Read Blocks"])
    assert blocks[1] == blocks[0]
    assert blocks[2] > blocks[1] + 4
    print({"compressed": compressed, "baseline_metadata_detoast_blocks": blocks})


async def test_conversion_after_metadata_preserves_compressed_snapshot(
    object_content_database, monkeypatch
):
    from eneo.database.tables.object_content_table import ObjectContents
    from eneo.object_content.content_repository import ObjectContentRepository

    database = object_content_database
    payload = b"a" * (2 * 1024 * 1024)
    content_id = await _legacy_upload(database, payload)
    settings = ObjectContentCoreSettings(_env_file=None)
    tenant_id, _ = await _owner_ids(database)
    grant = ContentReadGrant(content_id, tenant_id, ContentAccessClass.PRIVATE_RESOURCE)
    original = ObjectContentRepository.get_read_metadata
    converted = False

    async def convert_after_metadata(repository, grant):
        nonlocal converted
        result = await original(repository, grant)
        if not converted:
            converted = True
            assert result[2] is False
            conversion = await ObjectContentReconciler(settings, database).run_once()
            assert conversion.inline_conversion.converted == 1
            stored, raw = (
                await repository._session.execute(
                    text(
                        "SELECT pg_column_size(payload), octet_length(payload) "
                        "FROM inline_content_payloads WHERE content_id = :id"
                    ),
                    {"id": content_id},
                )
            ).one()
            assert stored < raw == len(payload)
            assert await _physical_sizes(database, content_id) == (
                len(payload),
                len(payload),
            )
            assert (await original(repository, grant))[2] is False
        else:
            assert result[2] is True
        return result

    monkeypatch.setattr(
        ObjectContentRepository, "get_read_metadata", convert_after_metadata
    )
    statements = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(database._engine.sync_engine, "before_cursor_execute", capture)
    try:
        for expect_slices in (False, True):
            statements.clear()
            async with ObjectContentService(settings, database).open_content(
                grant
            ) as opened:
                assert b"".join([chunk async for chunk in opened.chunks]) == payload
            assert any("substr(" in sql for sql in statements) == expect_slices
            assert any(
                ", inline_content_payloads.payload," in sql for sql in statements
            ) == (not expect_slices)
        assert converted
    finally:
        event.remove(database._engine.sync_engine, "before_cursor_execute", capture)
    async with database.session() as session, session.begin():
        control = await session.get(ObjectContents, content_id)
        assert control.state == "available"
        assert control.failure_code is None


async def _empty_upload(database):
    from eneo.database.tables.object_content_table import (
        FileContentReferences,
        InlineContentPayloads,
    )
    from tests.integration.object_content.test_storage_ownership import (
        _file,
        _inline_content,
    )

    tenant_id, user_id = await _owner_ids(database)
    async with database.session() as session, session.begin():
        owner = _file(tenant_id=tenant_id, user_id=user_id, name="empty")
        control = _inline_content(
            tenant_id=tenant_id, user_id=user_id, idempotency_key="empty", payload=b""
        )
        session.add_all([owner, control])
        await session.flush()
        session.add_all(
            [
                InlineContentPayloads(
                    content_id=control.id, storage_kind="postgres_inline", payload=b""
                ),
                FileContentReferences(
                    file_id=owner.id,
                    content_id=control.id,
                    variant="original",
                    ordinal=0,
                ),
            ]
        )
        content_id = control.id
    return content_id


@pytest.mark.parametrize("local_path", [False, True])
@pytest.mark.parametrize("converted", [False, True])
async def test_ready_inline_download_uses_snapshot_slices(
    object_content_database: DatabaseSessionManager,
    local_path: bool,
    converted: bool,
) -> None:
    database = object_content_database
    settings = ObjectContentCoreSettings(_env_file=None)
    payload = (
        b"a" * (2 * 1024 * 1024 + 7)
        if converted
        else Random(42).randbytes(2 * 1024 * 1024 + 7)
    )
    content_id = await (_legacy_upload if converted else _upload)(database, payload)
    await ObjectContentReconciler(settings, database).run_once()
    async with database.session() as session, session.begin():
        assert (
            await session.scalar(
                select(ObjectContentReconciliationState.inline_conversion_ready_at)
            )
            is not None
        )
    assert await _physical_sizes(database, content_id) == (len(payload), len(payload))
    tenant_id, _ = await _owner_ids(database)
    grant = ContentReadGrant(content_id, tenant_id, ContentAccessClass.PRIVATE_RESOURCE)
    engine = database._engine
    assert engine is not None
    statements = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        statements.append((statement, parameters, id(connection)))

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        async with ObjectContentService(settings, database).open_content(
            grant, require_local_path=local_path
        ) as opened:
            assert engine.pool.checkedout() == 0
            assert (opened.verified_path is not None) == local_path
            digest = sha256()
            size = 0
            async for chunk in opened.chunks:
                assert len(chunk) <= settings.inline_io_chunk_bytes
                digest.update(chunk)
                size += len(chunk)
            assert size == len(payload)
            assert digest.digest() == sha256(payload).digest()
        if opened.verified_path is not None:
            assert not opened.verified_path.exists()
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)

    slices = [(sql, params) for sql, params, _ in statements if "substr" in sql.lower()]
    expected_count = (
        len(payload) + settings.inline_io_chunk_bytes - 1
    ) // settings.inline_io_chunk_bytes
    assert len(slices) == expected_count
    for index, (_, parameters) in enumerate(slices):
        assert index * settings.inline_io_chunk_bytes + 1 in parameters
        assert (
            min(
                settings.inline_io_chunk_bytes,
                len(payload) - index * settings.inline_io_chunk_bytes,
            )
            in parameters
        )
    assert len({connection for _, _, connection in statements}) == 1
    assert any(
        "REPEATABLE READ" in sql and "READ ONLY" in sql for sql, _, _ in statements
    )
    assert not any("inline_conversion_ready_at" in sql for sql, _, _ in statements)
    for sql, _, _ in statements:
        assert "sha256(" not in sql.lower()
        assert "SELECT inline_content_payloads.payload" not in sql
        assert ", inline_content_payloads.payload," not in sql


@pytest.mark.parametrize(
    ("compressed", "damage"),
    [
        (compressed, damage)
        for compressed in (False, True)
        for damage in ("hash", "short", "trailing")
    ]
    + [(False, "empty")],
)
async def test_inline_corruption_reports_complete_observation_after_snapshot_close(
    object_content_database, monkeypatch, tmp_path, compressed, damage
):
    from eneo.database.tables.object_content_table import ObjectContents
    from eneo.object_content.content import ObjectContentIntegrityError
    from eneo.object_content.content_repository import ObjectContentRepository
    from tests.integration.object_content.test_inline_external_storage import (
        _corrupt_payload,
    )

    database = object_content_database
    payload = b"a" * (512 * 1024 + 5)
    content_id = await _upload(database, payload)
    settings = ObjectContentCoreSettings(_env_file=None)
    corrupted = {
        "hash": b"b" * len(payload),
        "short": payload[:-1],
        "trailing": payload + b"unexpected",
        "empty": b"",
    }[damage]
    await _corrupt_payload(database, content_id, corrupted, compressed=compressed)
    stored, raw = await _physical_sizes(database, content_id)
    assert (stored < raw) == compressed
    tenant_id, _ = await _owner_ids(database)
    grant = ContentReadGrant(content_id, tenant_id, ContentAccessClass.PRIVATE_RESOURCE)
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
    original = ObjectContentRepository.mark_backend_failure
    observations = []
    paths = []
    original_metadata = ObjectContentRepository.get_read_metadata

    async def metadata(repository, grant):
        result = await original_metadata(repository, grant)
        paths.append(result[2])
        return result

    async def report(repository, **kwargs):
        assert database._engine.pool.checkedout() == 0
        observations.append(kwargs.get("observed_inline_sha256"))
        return await original(repository, **kwargs)

    monkeypatch.setattr(ObjectContentRepository, "mark_backend_failure", report)
    monkeypatch.setattr(ObjectContentRepository, "get_read_metadata", metadata)
    with pytest.raises(ObjectContentIntegrityError):
        async with ObjectContentService(settings, database).open_content(grant):
            pytest.fail("Corruption exposed a download")
    assert observations == [sha256(corrupted).digest()]
    assert paths == [not compressed]
    assert list(tmp_path.iterdir()) == []
    async with database.session() as session, session.begin():
        control = await session.get(ObjectContents, content_id)
        assert control.state == "failed"
        assert control.failure_code == "backend_corrupt"


@pytest.mark.parametrize("compressed", [False, True])
async def test_download_stale_corruption_retries_after_inline_round_trip(
    object_content_database, monkeypatch, compressed
):
    from eneo.database.tables.object_content_table import ObjectContents
    from eneo.object_content.content import StorageKind
    from eneo.object_content.content_repository import ObjectContentRepository
    from eneo.object_content.move_repository import ObjectContentMoveRepository
    from tests.integration.object_content.test_inline_external_storage import (
        _corrupt_payload,
    )
    from tests.integration.object_content.test_moves import (
        _publish_object_store_move,
        _queue_move,
    )

    database = object_content_database
    payload = b"a" * (512 * 1024)
    content_id = await _upload(database, payload)
    settings = ObjectContentCoreSettings(_env_file=None)
    await _corrupt_payload(
        database, content_id, b"b" * len(payload), compressed=compressed
    )
    stored, raw = await _physical_sizes(database, content_id)
    assert (stored < raw) == compressed
    tenant_id, actor_id = await _owner_ids(database)
    original = ObjectContentRepository.mark_backend_failure
    reports = 0
    paths = []
    original_metadata = ObjectContentRepository.get_read_metadata

    async def metadata(repository, grant):
        result = await original_metadata(repository, grant)
        paths.append(result[2])
        return result

    async def replace_placement(repository, **kwargs):
        nonlocal reports
        reports += 1
        assert database._engine.pool.checkedout() == 0
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
            assert (
                await moves.claim(lease_owner="download-round-trip", lease_seconds=300)
                is not None
            )
            await moves.complete_to_inline(
                content_id=content_id,
                lease_owner="download-round-trip",
                payload=payload,
                captured_size_bytes=len(payload),
                captured_sha256=sha256(payload).digest(),
                orphan_grace_seconds=300,
            )
        return await original(repository, **kwargs)

    monkeypatch.setattr(
        ObjectContentRepository, "mark_backend_failure", replace_placement
    )
    monkeypatch.setattr(ObjectContentRepository, "get_read_metadata", metadata)
    grant = ContentReadGrant(content_id, tenant_id, ContentAccessClass.PRIVATE_RESOURCE)
    async with ObjectContentService(settings, database).open_content(grant) as opened:
        assert b"".join([chunk async for chunk in opened.chunks]) == payload
    assert reports == 1
    assert paths == [not compressed, True]
    async with database.session() as session, session.begin():
        control = await session.get(ObjectContents, content_id)
        assert control.state == "available"
        assert control.failure_code is None


async def test_move_between_slices_keeps_the_original_snapshot(
    object_content_database, monkeypatch
):
    from eneo.database.tables.object_content_table import ObjectContents
    from eneo.object_content.content_repository import ObjectContentRepository
    from tests.integration.object_content.test_moves import _publish_object_store_move

    database = object_content_database
    payload = Random(8).randbytes(1024 * 1024)
    content_id = await _upload(database, payload)
    settings = ObjectContentCoreSettings(_env_file=None)
    await ObjectContentReconciler(settings, database).run_once()
    tenant_id, actor_id = await _owner_ids(database)
    original = ObjectContentRepository.read_inline_slice
    moved = False

    async def slice_after_move(repository, **kwargs):
        nonlocal moved
        if kwargs["offset"] > 0 and not moved:
            moved = True
            await _publish_object_store_move(
                database, content_id=content_id, actor_id=actor_id, payload=payload
            )
        return await original(repository, **kwargs)

    monkeypatch.setattr(ObjectContentRepository, "read_inline_slice", slice_after_move)
    grant = ContentReadGrant(content_id, tenant_id, ContentAccessClass.PRIVATE_RESOURCE)
    async with ObjectContentService(settings, database).open_content(grant) as opened:
        assert b"".join([chunk async for chunk in opened.chunks]) == payload
    assert moved
    async with database.session() as session, session.begin():
        control = await session.get(ObjectContents, content_id)
        assert control.storage_kind == "object_store"
        assert control.state == "available"
        assert control.failure_code is None


async def test_inline_path_is_adopted_by_audio_without_consuming_chunks(
    object_content_database, tmp_path, monkeypatch
):
    from eneo.files.file_service import FileDownload
    from eneo.flows.runtime.audio_spool import spool_audio
    from eneo.object_content.content_service import detach_content_read

    database = object_content_database
    payload = b"audio fixture" * 50000
    content_id = await _upload(database, payload)
    settings = ObjectContentCoreSettings(_env_file=None)
    await ObjectContentReconciler(settings, database).run_once()
    tenant_id, _ = await _owner_ids(database)
    grant = ContentReadGrant(content_id, tenant_id, ContentAccessClass.PRIVATE_RESOURCE)
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
    source_paths = []

    async def forbidden_chunks():
        pytest.fail("Audio copied already verified bytes")
        yield b""

    async def download(file_id):
        opened = await detach_content_read(
            ObjectContentService(settings, database).open_content(
                grant, require_local_path=True
            )
        )
        source_paths.append(opened.verified_path)
        return FileDownload(
            file_id=file_id,
            tenant_id=tenant_id,
            chunks=forbidden_chunks(),
            content_length=opened.content_length,
            media_type="audio/wav",
            filename="audio.wav",
            sha256=sha256(payload).digest(),
            content_range=None,
            range_supported=True,
            _close=opened.aclose,
            verified_path=opened.verified_path,
        )

    audio = await spool_audio(content_id, open_audio_download=download)
    try:
        assert audio.path.read_bytes() == payload
        assert audio.digest == sha256(payload).hexdigest()
        assert source_paths[0] is not None and not source_paths[0].exists()
        assert list(tmp_path.iterdir()) == [audio.path]
    finally:
        await audio.aclose()
    assert list(tmp_path.iterdir()) == []


async def test_compressed_download_and_batch_keep_materialized_sources(
    object_content_database,
):
    from uuid import uuid4

    from eneo.object_content.content import ObjectContentStateError

    database = object_content_database
    payload = b"not converted" * 10000
    content_id = await _legacy_upload(database, payload)
    tenant_id, _ = await _owner_ids(database)
    grant = ContentReadGrant(content_id, tenant_id, ContentAccessClass.PRIVATE_RESOURCE)
    settings = ObjectContentCoreSettings(_env_file=None)
    service = ObjectContentService(settings, database)
    statements = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(database._engine.sync_engine, "before_cursor_execute", capture)
    try:
        async with service.open_content(grant) as opened:
            assert b"".join([chunk async for chunk in opened.chunks]) == payload
        assert any(", inline_content_payloads.payload," in sql for sql in statements)
        assert not any("substr" in sql for sql in statements)
        await ObjectContentReconciler(settings, database).run_once()
        statements.clear()
        assert await service.read_content_bytes([grant, grant]) == {content_id: payload}
        assert len(statements) == 1
        assert ", inline_content_payloads.payload," in statements[0]
        conflicting = ContentReadGrant(content_id, uuid4(), grant.access_class)
        with pytest.raises((ValueError, ObjectContentStateError)):
            await service.read_content_bytes([grant, conflicting])
        assert len(statements) == 1
    finally:
        event.remove(database._engine.sync_engine, "before_cursor_execute", capture)


@pytest.mark.parametrize(
    "invalid", ["tenant", "access", "id", "state", "missing_payload"]
)
async def test_snapshot_metadata_preserves_access_and_missing_payload_contract(
    object_content_database, invalid
):
    from dataclasses import replace
    from uuid import uuid4

    from sqlalchemy import text

    from eneo.object_content.content import ObjectContentStateError

    database = object_content_database
    content_id = await _upload(database, b"private")
    settings = ObjectContentCoreSettings(_env_file=None)
    await ObjectContentReconciler(settings, database).run_once()
    tenant_id, _ = await _owner_ids(database)
    grant = ContentReadGrant(content_id, tenant_id, ContentAccessClass.PRIVATE_RESOURCE)
    if invalid == "tenant":
        grant = replace(grant, tenant_id=uuid4())
    elif invalid == "access":
        grant = replace(
            grant,
            access_class=next(
                value for value in ContentAccessClass if value != grant.access_class
            ),
        )
    elif invalid == "id":
        grant = replace(grant, content_id=uuid4())
    else:
        async with database.session() as session, session.begin():
            await session.execute(text("SET LOCAL session_replication_role = replica"))
            await session.execute(
                text(
                    "DELETE FROM inline_content_payloads WHERE content_id = :id"
                    if invalid == "missing_payload"
                    else "UPDATE object_contents SET state = 'failed', failure_code = 'backend_corrupt' WHERE id = :id"
                ),
                {"id": content_id},
            )
    with pytest.raises(ObjectContentStateError):
        async with ObjectContentService(settings, database).open_content(grant):
            pytest.fail("Unavailable content exposed a download")
    assert database._engine.pool.checkedout() == 0


@pytest.mark.parametrize("phase", ["opening", "querying"])
async def test_cancellation_during_postgres_operation_releases_snapshot(
    object_content_database, monkeypatch, tmp_path, phase
):
    import asyncio

    database = object_content_database
    content_id = await _upload(database, b"a" * 512000)
    settings = ObjectContentCoreSettings(_env_file=None)
    await ObjectContentReconciler(settings, database).run_once()
    tenant_id, _ = await _owner_ids(database)
    grant = ContentReadGrant(content_id, tenant_id, ContentAccessClass.PRIVATE_RESOURCE)
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
    entered = asyncio.Event()
    engine = database._engine.sync_engine

    def pending_query(connection, cursor, statement, parameters, context, executemany):
        target = "SET TRANSACTION" if phase == "opening" else "substr("
        if target in statement:
            entered.set()
            return "SELECT pg_sleep(10)", ()
        return statement, parameters

    event.listen(engine, "before_cursor_execute", pending_query, retval=True)

    async def read():
        async with ObjectContentService(settings, database).open_content(grant):
            pytest.fail("Cancelled query exposed a download")

    task = asyncio.create_task(read())
    try:
        await asyncio.wait_for(entered.wait(), 3)
        await asyncio.sleep(0.05)
        assert database._engine.pool.checkedout() == 1
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 3)
        assert database._engine.pool.checkedout() == 0
        assert list(tmp_path.iterdir()) == []
    finally:
        event.remove(engine, "before_cursor_execute", pending_query)
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("phase", ["write", "read", "close"])
async def test_cancellation_during_spool_io_settles_and_unlinks(
    object_content_database, monkeypatch, tmp_path, phase
):
    import asyncio
    from threading import Event

    from eneo.object_content import verified_spool

    database = object_content_database
    content_id = await _upload(database, b"a" * 512000)
    settings = ObjectContentCoreSettings(_env_file=None)
    await ObjectContentReconciler(settings, database).run_once()
    tenant_id, _ = await _owner_ids(database)
    grant = ContentReadGrant(content_id, tenant_id, ContentAccessClass.PRIVATE_RESOURCE)
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
    entered = asyncio.Event()
    release = Event()
    loop = asyncio.get_running_loop()
    original = verified_spool.NamedTemporaryFile
    files = []

    def create(*args, **kwargs):
        file = original(*args, **kwargs)
        files.append(file)
        operation = getattr(file, phase)

        def pending(*args):
            loop.call_soon_threadsafe(entered.set)
            assert release.wait(5)
            return operation(*args)

        setattr(file, phase, pending)
        return file

    monkeypatch.setattr(verified_spool, "NamedTemporaryFile", create)

    async def read():
        async with ObjectContentService(settings, database).open_content(
            grant, require_local_path=True
        ) as opened:
            if phase != "close":
                async for _ in opened.chunks:
                    pass

    task = asyncio.create_task(read())
    try:
        await asyncio.wait_for(entered.wait(), 3)
        task.cancel()
        await asyncio.sleep(0.02)
        task.cancel()
        await asyncio.sleep(0.02)
        assert not task.done()
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 3)
    assert database._engine.pool.checkedout() == 0
    assert all(file.closed for file in files)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("failure", ["write", "read"])
async def test_local_spool_failure_preserves_inline_availability(
    object_content_database, monkeypatch, tmp_path, failure
):
    from eneo.database.tables.object_content_table import ObjectContents
    from eneo.object_content import verified_spool
    from eneo.object_content.content import ObjectContentUnavailableError

    database = object_content_database
    content_id = await _upload(database, b"a" * 512000)
    settings = ObjectContentCoreSettings(_env_file=None)
    await ObjectContentReconciler(settings, database).run_once()
    tenant_id, _ = await _owner_ids(database)
    grant = ContentReadGrant(content_id, tenant_id, ContentAccessClass.PRIVATE_RESOURCE)
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
    original = verified_spool.NamedTemporaryFile

    def create(*args, **kwargs):
        file = original(*args, **kwargs)

        def fail(*args):
            raise OSError("injected local I/O failure")

        setattr(file, failure, fail)
        return file

    monkeypatch.setattr(verified_spool, "NamedTemporaryFile", create)
    with pytest.raises(ObjectContentUnavailableError):
        async with ObjectContentService(settings, database).open_content(
            grant
        ) as opened:
            async for _ in opened.chunks:
                pass
    assert list(tmp_path.iterdir()) == []
    assert database._engine.pool.checkedout() == 0
    async with database.session() as session, session.begin():
        control = await session.get(ObjectContents, content_id)
        assert control.state == "available"
        assert control.failure_code is None


@pytest.mark.parametrize("local_path", [False, True])
async def test_empty_inline_content_verifies_without_slice_queries(
    object_content_database, local_path
):
    database = object_content_database
    content_id = await _empty_upload(database)
    tenant_id, _ = await _owner_ids(database)
    settings = ObjectContentCoreSettings(_env_file=None)
    await ObjectContentReconciler(settings, database).run_once()
    grant = ContentReadGrant(content_id, tenant_id, ContentAccessClass.PRIVATE_RESOURCE)
    statements = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(database._engine.sync_engine, "before_cursor_execute", capture)
    try:
        async with ObjectContentService(settings, database).open_content(
            grant, require_local_path=local_path
        ) as opened:
            assert opened.content_length == 0
            assert [chunk async for chunk in opened.chunks] == []
            if local_path:
                assert opened.verified_path.read_bytes() == b""
        assert not any("substr(" in statement for statement in statements)
    finally:
        event.remove(database._engine.sync_engine, "before_cursor_execute", capture)


async def test_short_slice_refuses_exposure_without_an_incomplete_failure_observation(
    object_content_database, tmp_path, monkeypatch
):
    from eneo.database.tables.object_content_table import ObjectContents
    from eneo.object_content.content import ObjectContentUnavailableError

    database = object_content_database
    content_id = await _upload(database, b"a" * 512000)
    settings = ObjectContentCoreSettings(_env_file=None)
    await ObjectContentReconciler(settings, database).run_once()
    tenant_id, _ = await _owner_ids(database)
    grant = ContentReadGrant(content_id, tenant_id, ContentAccessClass.PRIVATE_RESOURCE)
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))

    def short_slice(connection, cursor, statement, parameters, context, executemany):
        if "substr(" in statement:
            parameters = (parameters[0], parameters[1] - 1, *parameters[2:])
        return statement, parameters

    event.listen(
        database._engine.sync_engine, "before_cursor_execute", short_slice, retval=True
    )
    try:
        with pytest.raises(ObjectContentUnavailableError, match="slice is incomplete"):
            async with ObjectContentService(settings, database).open_content(grant):
                pytest.fail("Incomplete slice exposed a download")
    finally:
        event.remove(database._engine.sync_engine, "before_cursor_execute", short_slice)
    assert list(tmp_path.iterdir()) == []
    assert database._engine.pool.checkedout() == 0
    async with database.session() as session, session.begin():
        control = await session.get(ObjectContents, content_id)
        assert control.state == "available"
        assert control.failure_code is None


async def test_inline_batch_materialization_keeps_500_unique_grants_per_query(
    object_content_database,
):
    from eneo.database.tables.object_content_table import (
        FileContentReferences,
        InlineContentPayloads,
    )
    from tests.integration.object_content.test_storage_ownership import (
        _file,
        _inline_content,
    )

    database = object_content_database
    tenant_id, user_id = await _owner_ids(database)
    expected = {}
    async with database.session() as session, session.begin():
        owner = _file(tenant_id=tenant_id, user_id=user_id, name="batch")
        session.add(owner)
        await session.flush()
        for index in range(501):
            payload = str(index).encode()
            control = _inline_content(
                tenant_id=tenant_id,
                user_id=user_id,
                idempotency_key=f"batch-{index}",
                payload=payload,
            )
            session.add(control)
            await session.flush()
            session.add_all(
                [
                    InlineContentPayloads(
                        content_id=control.id,
                        storage_kind="postgres_inline",
                        payload=payload,
                    ),
                    FileContentReferences(
                        file_id=owner.id,
                        content_id=control.id,
                        variant="original",
                        ordinal=index,
                    ),
                ]
            )
            expected[control.id] = payload
    grants = [
        ContentReadGrant(content_id, tenant_id, ContentAccessClass.PRIVATE_RESOURCE)
        for content_id in expected
    ]
    settings = ObjectContentCoreSettings(_env_file=None)
    statements = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        statements.append((statement, parameters))

    event.listen(database._engine.sync_engine, "before_cursor_execute", capture)
    try:
        assert (
            await ObjectContentService(settings, database).read_content_bytes(
                grants + grants[:5]
            )
            == expected
        )
    finally:
        event.remove(database._engine.sync_engine, "before_cursor_execute", capture)
    assert len(statements) == 2
    assert all(", inline_content_payloads.payload," in sql for sql, _ in statements)
    assert [len(params) for _, params in statements] == [1501, 4]


@pytest.mark.parametrize("corrupt_outside_range", [False, True])
async def test_ready_inline_range_verifies_the_complete_payload(
    object_content_database, corrupt_outside_range
):
    from eneo.object_content.content import ObjectContentIntegrityError
    from tests.integration.object_content.test_inline_external_storage import (
        _corrupt_payload,
    )

    database = object_content_database
    payload = b"01234567" * 65536
    content_id = await _upload(database, payload)
    settings = ObjectContentCoreSettings(_env_file=None)
    await ObjectContentReconciler(settings, database).run_once()
    tenant_id, _ = await _owner_ids(database)
    grant = ContentReadGrant(content_id, tenant_id, ContentAccessClass.PRIVATE_RESOURCE)
    service = ObjectContentService(settings, database)
    if corrupt_outside_range:
        await _corrupt_payload(database, content_id, payload[:-1] + b"x")
        with pytest.raises(ObjectContentIntegrityError):
            async with service.open_content(grant, range_header="bytes=2-5"):
                pytest.fail("Range exposed a corrupt source")
    else:
        async with service.open_content(grant, range_header="bytes=2-5") as opened:
            assert b"".join([chunk async for chunk in opened.chunks]) == b"2345"
            assert opened.content_range == f"bytes 2-5/{len(payload)}"
            assert opened.content_length == 4
