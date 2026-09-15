import asyncio
import json
import os
import subprocess
import sys

import pytest
import sqlalchemy as sa

from eneo.database.tables.file_icon_backfill_table import (
    FileIconBackfillCampaign,
    FileIconBackfillItems,
)
from eneo.object_content import file_icon_backfill as migration
from tests.integration.object_content.test_file_icon_inline_backfill import (
    _backfill,
    _seed_legacy_text,
    _set_policy_target,
)

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
async def restore_storage_target(object_content_database):
    async with object_content_database.session() as session, session.begin():
        target = await session.scalar(
            sa.text(
                "SELECT new_write_storage_target FROM object_content_deployment_policy WHERE id = 1"
            )
        )
    try:
        yield
    finally:
        await _set_policy_target(object_content_database, target)


async def test_pause_survives_worker_restart_and_preserves_pending_admission(
    object_content_database,
):
    database = object_content_database
    await _seed_legacy_text(database, payload=b"legacy payload")
    async with database.session() as session, session.begin():
        await migration.set_file_icon_backfill_paused(session, paused=True)

    for worker in (_backfill(database), _backfill(database)):
        result = await worker.run_once()
        assert result.state.value == "paused"
        assert result.admitted_count == result.claimed_count == 0
    async with database.session() as session, session.begin():
        assert await session.scalar(sa.select(FileIconBackfillItems.state)) == "pending"
        assert await session.scalar(sa.select(FileIconBackfillCampaign.id)) is None
        await migration.set_file_icon_backfill_paused(session, paused=False)

    result = await _backfill(database).run_once()
    assert result.state is migration.FileIconBackfillState.COMPLETE
    assert result.completed_count == 1


async def test_status_reports_preparation_capacity_wait_and_complete_without_writes(
    object_content_database,
):
    database = object_content_database
    payload = b"legacy payload"
    await _seed_legacy_text(database, payload=payload)
    settings = migration.FileIconBackfillSettings(auto_inline_max_bytes=0)

    async def status():
        async with database.session() as session, session.begin():
            await session.execute(
                sa.text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            )
            return await migration.read_file_icon_backfill_status(session, settings)

    preparing = await status()
    assert preparing.state.value == "preparing"
    assert preparing.capacity_required_bytes is None
    assert preparing.paused is False
    await _backfill(database, auto_inline_max_bytes=0).run_once()
    waiting = await status()
    assert waiting.state is migration.FileIconBackfillState.WAITING_FOR_CAPACITY
    assert waiting.capacity_required_bytes == len(payload)
    async with database.session() as session, session.begin():
        assert await session.scalar(sa.select(FileIconBackfillCampaign.id)) is None
        await migration.set_file_icon_backfill_paused(session, paused=True)
    paused = await status()
    assert paused.paused is True
    assert paused.state is migration.FileIconBackfillState.WAITING_FOR_CAPACITY
    async with database.session() as session, session.begin():
        await migration.set_file_icon_backfill_paused(session, paused=False)
    await _backfill(database, inline_capacity_ack=len(payload)).run_once()
    complete = await status()
    assert complete.state is migration.FileIconBackfillState.COMPLETE
    assert complete.capacity_admitted_bytes == len(payload)


async def test_committed_pause_wins_before_a_waiting_worker_claims(
    object_content_database,
):
    database = object_content_database
    await _seed_legacy_text(database, payload=b"legacy payload")
    worker_task = None
    try:
        async with database.session() as pause_session:
            async with pause_session.begin():
                pause_pid = await pause_session.scalar(
                    sa.text("SELECT pg_backend_pid()")
                )
                await migration.set_file_icon_backfill_paused(
                    pause_session, paused=True
                )
                worker_task = asyncio.create_task(_backfill(database).run_once())
                async with asyncio.timeout(5):
                    while True:
                        assert not worker_task.done()
                        async with database.session() as session, session.begin():
                            blocked = await session.scalar(
                                sa.text(
                                    "SELECT EXISTS (SELECT 1 FROM pg_stat_activity "
                                    "WHERE datname = current_database() "
                                    "AND :pause_pid = ANY(pg_blocking_pids(pid)))"
                                ),
                                {"pause_pid": pause_pid},
                            )
                        if blocked:
                            break
                        await asyncio.sleep(0.01)
            result = await asyncio.wait_for(worker_task, timeout=5)
        assert result.state is migration.FileIconBackfillState.PAUSED
        assert result.claimed_count == result.admitted_count == 0
        async with database.session() as session, session.begin():
            assert (
                await session.scalar(sa.select(FileIconBackfillItems.state))
                == "pending"
            )
    finally:
        if worker_task is not None:
            if not worker_task.done():
                worker_task.cancel()
            await asyncio.gather(worker_task, return_exceptions=True)


async def test_resume_does_not_bypass_a_cached_capacity_wait(object_content_database):
    database = object_content_database
    await _seed_legacy_text(database, payload=b"legacy payload")
    worker = _backfill(database, auto_inline_max_bytes=0)
    waiting = await worker.run_once()
    assert waiting.state is migration.FileIconBackfillState.WAITING_FOR_CAPACITY
    async with database.session() as session, session.begin():
        await migration.set_file_icon_backfill_paused(session, paused=True)
    assert (await worker.run_once()).state is migration.FileIconBackfillState.PAUSED
    async with database.session() as session, session.begin():
        await migration.set_file_icon_backfill_paused(session, paused=False)
    resumed = await worker.run_once()
    assert resumed.state is migration.FileIconBackfillState.WAITING_FOR_CAPACITY
    assert resumed.claimed_count == resumed.completed_count == 0


async def test_active_pause_allows_claimed_batch_to_finish_then_resumes_remaining_work(
    object_content_database, monkeypatch
):
    database = object_content_database
    for payload in (b"first", b"second", b"third"):
        await _seed_legacy_text(database, payload=payload)
    worker = _backfill(database, batch_rows=2)
    assert (await worker.run_once()).claimed_count == 0
    claimed = asyncio.Event()
    continue_copy = asyncio.Event()
    original = migration._FileIconBackfillRepository.complete_inline

    async def complete_after_pause(repository, item, object_content):
        claimed.set()
        await continue_copy.wait()
        return await original(repository, item, object_content)

    monkeypatch.setattr(
        migration._FileIconBackfillRepository, "complete_inline", complete_after_pause
    )
    active_batch = asyncio.create_task(worker.run_once())
    try:
        await asyncio.wait_for(claimed.wait(), timeout=5)
        async with database.session() as session, session.begin():
            await migration.set_file_icon_backfill_paused(session, paused=True)
        continue_copy.set()
        result = await asyncio.wait_for(active_batch, timeout=5)
        assert result.claimed_count == result.completed_count == 2
        assert result.state is migration.FileIconBackfillState.ACTIVE
        paused = await worker.run_once()
        assert paused.state is migration.FileIconBackfillState.PAUSED
        assert paused.claimed_count == 0
        async with database.session() as session, session.begin():
            assert (
                await session.scalar(
                    sa.select(sa.func.count())
                    .select_from(FileIconBackfillItems)
                    .where(FileIconBackfillItems.state == "ready")
                )
                == 1
            )
            await migration.set_file_icon_backfill_paused(session, paused=False)
        resumed = await worker.run_once()
        assert resumed.completed_count == 1
        assert resumed.state is migration.FileIconBackfillState.COMPLETE
    finally:
        continue_copy.set()
        if not active_batch.done():
            active_batch.cancel()
        await asyncio.gather(active_batch, return_exceptions=True)


async def test_resume_preserves_a_halt_and_its_required_recovery_revision(
    object_content_database,
):
    database = object_content_database
    for payload in (b"first", b"second"):
        await _seed_legacy_text(database, payload=payload)
    worker = _backfill(database, batch_rows=1)
    for _ in range(4):
        if (await worker.run_once()).claimed_count == 1:
            break
    else:
        pytest.fail("The first migration item was not claimed")
    await _set_policy_target(database, migration.StorageKind.OBJECT_STORE.value)
    assert (await worker.run_once()).state is migration.FileIconBackfillState.HALTED
    async with database.session() as session, session.begin():
        before = await migration.read_file_icon_backfill_status(
            session, migration.FileIconBackfillSettings()
        )
        await migration.set_file_icon_backfill_paused(session, paused=True)
    await _set_policy_target(database, migration.StorageKind.POSTGRES_INLINE.value)
    async with database.session() as session, session.begin():
        await migration.set_file_icon_backfill_paused(session, paused=False)
        after = await migration.read_file_icon_backfill_status(
            session, migration.FileIconBackfillSettings()
        )
    assert after == before
    assert (await worker.run_once()).state is migration.FileIconBackfillState.HALTED
    recovery_worker = _backfill(database, resume_revision=1)
    recovered = await recovery_worker.run_once()
    assert recovered.completed_count == 1
    assert (
        await recovery_worker.run_once()
    ).state is migration.FileIconBackfillState.COMPLETE


async def test_status_explains_a_remote_target_wait_without_starting_a_campaign(
    object_content_database,
):
    database = object_content_database
    await _seed_legacy_text(database, payload=b"legacy payload")
    await _set_policy_target(database, migration.StorageKind.OBJECT_STORE.value)
    assert (
        await _backfill(database).run_once()
    ).state is migration.FileIconBackfillState.WAITING_FOR_OBJECT_STORE
    async with database.session() as session, session.begin():
        status = await migration.read_file_icon_backfill_status(
            session, migration.FileIconBackfillSettings()
        )
        assert await session.scalar(sa.select(FileIconBackfillCampaign.id)) is None
    assert status.state is migration.FileIconBackfillState.WAITING_FOR_OBJECT_STORE
    assert status.target_kind is migration.StorageKind.OBJECT_STORE
    assert "PostgreSQL inline" in status.detail


async def test_operator_command_uses_worker_settings_and_persists_only_pause(
    object_content_database, object_content_postgres_13, test_settings, tmp_path
):
    await _seed_legacy_text(object_content_database, payload=b"legacy payload")
    environment = os.environ.copy()
    environment.update(
        {
            name.upper(): str(getattr(test_settings, name))
            for name, field in type(test_settings).model_fields.items()
            if field.is_required()
        }
    )
    environment.update(
        POSTGRES_HOST=object_content_postgres_13.get_container_host_ip(),
        POSTGRES_PORT=str(object_content_postgres_13.get_exposed_port(5432)),
        POSTGRES_USER="object_content_test",
        POSTGRES_PASSWORD="object_content_test_password",
        POSTGRES_DB="object_content_test",
        FILE_ICON_BACKFILL_AUTO_INLINE_MAX_BYTES="0",
        FILE_ICON_BACKFILL_INLINE_CAPACITY_ACK="123",
        FILE_ICON_BACKFILL_RESUME_REVISION="4",
        TESTING="true",
    )

    async def command(action):
        result = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "-m", "eneo.object_content.file_icon_migration", action],
            cwd=tmp_path,
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    assert (await command("pause"))["paused"] is True
    status = await command("status")
    assert status["paused"] is True
    assert status["state"] == "preparing"
    assert status["configured_capacity_ack_bytes"] == 123
    assert status["configured_resume_revision"] == 4
    assert status["campaign_resume_revision"] is None
    assert (await command("resume"))["paused"] is False
    async with object_content_database.session() as session, session.begin():
        assert await session.scalar(sa.select(FileIconBackfillItems.state)) == "pending"
        assert await session.scalar(sa.select(FileIconBackfillCampaign.id)) is None
