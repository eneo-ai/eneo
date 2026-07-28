from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from arq.jobs import JobStatus

from eneo.database.database import sessionmanager
from eneo.database.tables.job_table import Jobs
from eneo.jobs.durable_dispatch import (
    DISPATCH_PAGE_SIZE,
    DISPATCH_STALE_AFTER,
    redispatch_stale_jobs,
)
from eneo.jobs.job_manager import job_manager
from eneo.jobs.job_models import Task
from eneo.jobs.job_repo import JobRepository
from eneo.jobs.job_service import JobService
from eneo.jobs.job_staging import job_staging_path
from eneo.jobs.task_models import (
    Transcription,
    UploadInfoBlob,
    build_dispatch_envelope,
)
from eneo.main.models import Status

pytestmark = pytest.mark.integration


def _params(task: Task, user_id: UUID) -> UploadInfoBlob | Transcription:
    model = UploadInfoBlob if task == Task.UPLOAD_FILE else Transcription
    return model(
        filename=f"{task.value}.txt",
        user_id=user_id,
        group_id=uuid4(),
        space_id=uuid4(),
        mimetype="text/plain",
    )


async def _insert_stale_job(
    session,
    *,
    task: Task,
    user_id: UUID,
    envelope: dict[str, object] | None = None,
    status: Status = Status.QUEUED,
    attempted_at: datetime | None = None,
    job_id: UUID | None = None,
) -> UUID:
    job_id = job_id or uuid4()
    params = _params(task, user_id)
    values = {
        "id": job_id,
        "user_id": user_id,
        "task": task.value,
        "status": status.value,
        "name": params.filename,
        "dispatch_envelope": envelope
        if envelope is not None
        else build_dispatch_envelope(task, params).model_dump(mode="json"),
        "dispatch_attempted_at": attempted_at,
        "created_at": datetime.now(timezone.utc) - DISPATCH_STALE_AFTER * 2,
    }
    await session.execute(sa.insert(Jobs).values(**values))
    return job_id


async def test_restart_safe_enqueue_waits_for_commit(admin_user) -> None:
    params = _params(Task.UPLOAD_FILE, admin_user.id)
    await job_manager.init()

    try:
        async with sessionmanager.session() as session:
            async with session.begin():
                service = JobService(admin_user, JobRepository(session))
                job = await service.queue_restart_safe_job(
                    Task.UPLOAD_FILE,
                    name=params.filename,
                    task_params=params,
                )
                assert await job_manager.get_job_status(job.id) == JobStatus.not_found

            for _ in range(50):
                if await job_manager.get_job_status(job.id) == JobStatus.queued:
                    break
                await asyncio.sleep(0.01)
            assert await job_manager.get_job_status(job.id) == JobStatus.queued
    finally:
        await job_manager.close()


async def test_redispatch_recovers_lost_delivery_and_advances_attempt(
    async_session, admin_user
) -> None:
    job_id = await _insert_stale_job(
        async_session, task=Task.UPLOAD_FILE, user_id=admin_user.id
    )
    enqueue = AsyncMock(return_value=None)

    result = await redispatch_stale_jobs(async_session, enqueue=enqueue)

    assert result.claimed == 1
    enqueue.assert_awaited_once()
    attempted_at = await async_session.scalar(
        sa.select(Jobs.dispatch_attempted_at).where(Jobs.id == job_id)
    )
    assert attempted_at is not None


async def test_redispatch_page_progress_and_cross_task_fairness(
    async_session, admin_user
) -> None:
    for offset in range(DISPATCH_PAGE_SIZE):
        await _insert_stale_job(
            async_session,
            task=Task.UPLOAD_FILE,
            user_id=admin_user.id,
            job_id=UUID(int=offset + 1),
        )
    transcription_id = await _insert_stale_job(
        async_session,
        task=Task.TRANSCRIPTION,
        user_id=admin_user.id,
        job_id=UUID(int=DISPATCH_PAGE_SIZE + 1),
    )
    enqueue = AsyncMock(return_value=None)

    first = await redispatch_stale_jobs(async_session, enqueue=enqueue)
    second = await redispatch_stale_jobs(async_session, enqueue=enqueue)

    assert first.claimed == DISPATCH_PAGE_SIZE
    assert second.claimed == 1
    assert any(call.args[1] == transcription_id for call in enqueue.await_args_list)


async def test_redispatch_refusal_advances_but_complete_job_is_ignored(
    async_session, admin_user
) -> None:
    queued_id = await _insert_stale_job(
        async_session, task=Task.UPLOAD_FILE, user_id=admin_user.id
    )
    complete_id = await _insert_stale_job(
        async_session,
        task=Task.TRANSCRIPTION,
        user_id=admin_user.id,
        status=Status.COMPLETE,
    )
    params = _params(Task.UPLOAD_FILE, admin_user.id)
    await job_manager.init()
    queued = await job_manager.enqueue(Task.UPLOAD_FILE, queued_id, params)
    assert queued is not None

    try:
        result = await redispatch_stale_jobs(async_session, enqueue=job_manager.enqueue)
    finally:
        await job_manager.close()

    assert result.claimed == 1
    assert result.enqueued == 0
    assert (
        await async_session.scalar(
            sa.select(Jobs.dispatch_attempted_at).where(Jobs.id == queued_id)
        )
        is not None
    )
    assert (
        await async_session.scalar(
            sa.select(Jobs.dispatch_attempted_at).where(Jobs.id == complete_id)
        )
        is None
    )


async def test_corrupt_envelope_fails_without_enqueue_or_path_influence(
    async_session, admin_user, tmp_path
) -> None:
    hostile_path = tmp_path / "hostile"
    hostile_path.write_text("untouched")
    job_id = await _insert_stale_job(
        async_session,
        task=Task.UPLOAD_FILE,
        user_id=admin_user.id,
        envelope={
            "version": 1,
            "task": Task.UPLOAD_FILE.value,
            "params": {
                "filepath": str(hostile_path),
                "filename": "bad.txt",
                "user_id": str(admin_user.id),
            },
        },
    )
    enqueue = AsyncMock()

    await redispatch_stale_jobs(async_session, enqueue=enqueue)

    enqueue.assert_not_awaited()
    row = (
        await async_session.execute(
            sa.select(Jobs.status, Jobs.result_location).where(Jobs.id == job_id)
        )
    ).one()
    assert row.status == Status.FAILED.value
    assert "dispatch envelope" in row.result_location
    assert hostile_path.read_text() == "untouched"


def test_staging_path_depends_only_on_job_id(tmp_path: Path) -> None:
    job_id = uuid4()

    path = job_staging_path(job_id, upload_tmp_dir=tmp_path)

    assert path == tmp_path / "job-staging" / str(job_id)
