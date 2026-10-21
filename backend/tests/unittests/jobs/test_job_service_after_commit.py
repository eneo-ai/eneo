"""queue_job(after_commit=True): the worker never sees a job before its row."""

import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.integration.domain.task_params import SharepointContentTaskParam
from eneo.jobs.job_models import JobInDb, Task
from eneo.jobs.job_service import JobService
from eneo.main.models import Status
from tests.fixtures import TEST_USER


def _params() -> SharepointContentTaskParam:
    return SharepointContentTaskParam(
        user_id=TEST_USER.id,
        id=uuid4(),
        integration_knowledge_id=uuid4(),
        site_id="site-1",
    )


def _repo(session: object) -> MagicMock:
    repo = MagicMock()
    repo.delegate.session = session
    repo.add_job = AsyncMock(
        return_value=JobInDb(
            id=uuid4(),
            user_id=TEST_USER.id,
            task=Task.SYNC_SHAREPOINT_DELTA,
            name="Library",
            status=Status.QUEUED,
        )
    )
    return repo


@pytest.fixture
def enqueue(monkeypatch) -> AsyncMock:
    enqueue = AsyncMock()
    monkeypatch.setattr("eneo.jobs.job_service.job_manager.enqueue", enqueue)
    return enqueue


async def test_dispatch_waits_for_the_commit(enqueue: AsyncMock) -> None:
    session = AsyncSession()
    repo = _repo(session)
    params = _params()

    async with session.begin():
        job = await JobService(TEST_USER, repo).queue_job(
            Task.SYNC_SHAREPOINT_DELTA,
            name="Library",
            task_params=params,
            after_commit=True,
        )
        enqueue.assert_not_awaited()
    await asyncio.sleep(0)
    await session.close()

    enqueue.assert_awaited_once_with(Task.SYNC_SHAREPOINT_DELTA, job.id, params)


async def test_a_rolled_back_job_is_never_dispatched(enqueue: AsyncMock) -> None:
    session = AsyncSession()
    repo = _repo(session)

    with pytest.raises(RuntimeError):
        async with session.begin():
            await JobService(TEST_USER, repo).queue_job(
                Task.SYNC_SHAREPOINT_DELTA,
                name="Library",
                task_params=_params(),
                after_commit=True,
            )
            raise RuntimeError("commit refused")
    await asyncio.sleep(0)
    await session.close()

    enqueue.assert_not_awaited()


async def test_without_after_commit_the_job_is_dispatched_at_once(
    enqueue: AsyncMock,
) -> None:
    session = AsyncSession()
    repo = _repo(session)

    async with session.begin():
        await JobService(TEST_USER, repo).queue_job(
            Task.SYNC_SHAREPOINT_DELTA, name="Library", task_params=_params()
        )
        enqueue.assert_awaited_once()
    await session.close()


async def test_a_job_queued_inside_a_savepoint_is_dispatched_after_the_commit(
    enqueue: AsyncMock,
) -> None:
    """The row is written in the savepoint; the hand-over waits for the outer
    commit, so a savepoint rolled back later leaves the worker no job."""
    session = AsyncSession()
    repo = _repo(session)
    service = JobService(TEST_USER, repo)
    params = _params()

    async with session.begin():
        async with session.begin_nested():
            job = await service.queue_job(
                Task.SYNC_SHAREPOINT_DELTA,
                name="Library",
                task_params=params,
                enqueue=False,
            )
            with pytest.raises(ValueError):
                await service.dispatch_after_commit(
                    Task.SYNC_SHAREPOINT_DELTA, job.id, params
                )
        await service.dispatch_after_commit(Task.SYNC_SHAREPOINT_DELTA, job.id, params)
        enqueue.assert_not_awaited()
    await asyncio.sleep(0)
    await session.close()

    enqueue.assert_awaited_once_with(Task.SYNC_SHAREPOINT_DELTA, job.id, params)
