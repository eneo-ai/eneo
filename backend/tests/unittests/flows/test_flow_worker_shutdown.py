"""A worker shutdown that cancels a run's task ends the run at once.

ARQ cancels a job's task for a worker shutdown, and the execution heartbeats
cancel it for a lost ownership; only the shutdown ends the run, with one
bounded write that the task waits for before its cancellation goes on.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from eneo.flows.domain.provider_call import ProviderCallUnknownReason
from eneo.flows.enums import FlowRunLifecycleSource
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.infrastructure.flow_run_repo import FlowRunExecutionOwner
from eneo.flows.runtime import execution_heartbeat as heartbeat
from eneo.flows.runtime import tasks as flow_runtime_tasks


class _Session:
    @asynccontextmanager
    async def begin(self):
        yield self


@pytest.fixture
def worker(monkeypatch):
    manager = heartbeat.FlowExecutionHeartbeats(max_active=2)
    renewal = AsyncMock(return_value=set())

    @asynccontextmanager
    async def session_scope():
        yield _Session()

    for module in (heartbeat, flow_runtime_tasks):
        monkeypatch.setattr(module.sessionmanager, "session", session_scope)
    monkeypatch.setattr(
        heartbeat,
        "FlowRunRepository",
        lambda **_: SimpleNamespace(renew_execution_heartbeats=renewal),
    )
    monkeypatch.setattr(flow_runtime_tasks, "execution_heartbeats", lambda: manager)

    started = asyncio.Event()

    async def execute(*, run_id: UUID, tenant_id: UUID, run_revision: int, **_):
        async with manager.track(
            FlowRunExecutionOwner(run_id, tenant_id, run_revision)
        ):
            started.set()
            await asyncio.Event().wait()

    monkeypatch.setattr(flow_runtime_tasks, "_execute_flow_run_async", execute)

    terminalizer = AsyncMock()
    terminalizer.terminalize_interrupted_running_run.return_value = SimpleNamespace(
        did_transition=True
    )
    provider_calls = AsyncMock()
    monkeypatch.setattr(
        flow_runtime_tasks,
        "Container",
        lambda **_: SimpleNamespace(
            flow_run_terminalizer=lambda: terminalizer,
            flow_provider_call_repo=lambda: provider_calls,
        ),
    )
    return SimpleNamespace(
        manager=manager,
        started=started,
        renewal=renewal,
        terminalizer=terminalizer,
        provider_calls=provider_calls,
    )


async def _attached_worker_task(manager: heartbeat.FlowExecutionHeartbeats):
    """Stands in for ARQ's poll task, the task that runs the startup hook."""

    async def poll() -> None:
        manager.attach_to_worker()
        await asyncio.Event().wait()

    task = asyncio.create_task(poll())
    await asyncio.sleep(0)
    return task


async def _started_job(worker, owner: FlowRunExecutionOwner) -> asyncio.Task:
    job = asyncio.create_task(
        flow_runtime_tasks.execute_flow_run_task(
            run_id=str(owner.run_id),
            flow_id=str(uuid4()),
            tenant_id=str(owner.tenant_id),
            run_revision=owner.revision,
            principal_type="user",
            principal_user_id=str(uuid4()),
            task_id="job-1",
            retry_count=0,
        )
    )
    await worker.started.wait()
    return job


def _shut_down(*, poll: asyncio.Task, jobs: list[asyncio.Task]) -> None:
    # ARQ's order once job_completion_wait is over: the job tasks, then its poll task.
    for job in jobs:
        job.cancel()
    poll.cancel()


async def _stop(worker, poll: asyncio.Task | None = None) -> None:
    if poll is not None:
        poll.cancel()
        with pytest.raises(asyncio.CancelledError):
            await poll
    await worker.manager.stop()


@pytest.mark.asyncio
async def test_the_shutdown_signal_is_the_worker_poll_task_being_cancelled(worker):
    manager = worker.manager
    assert manager.worker_is_shutting_down() is False

    poll = await _attached_worker_task(manager)
    assert manager.worker_is_shutting_down() is False

    poll.cancel()
    assert manager.worker_is_shutting_down() is True
    with pytest.raises(asyncio.CancelledError):
        await poll
    assert manager.worker_is_shutting_down() is True
    await manager.stop()


@pytest.mark.asyncio
async def test_worker_shutdown_fails_the_owned_run_and_keeps_the_cancellation(worker):
    owner = FlowRunExecutionOwner(uuid4(), uuid4(), 3)
    poll = await _attached_worker_task(worker.manager)
    job = await _started_job(worker, owner)

    _shut_down(poll=poll, jobs=[job])

    with pytest.raises(asyncio.CancelledError) as raised:
        await job
    assert not isinstance(raised.value, heartbeat.FlowExecutionOwnershipLost)
    worker.terminalizer.terminalize_interrupted_running_run.assert_awaited_once()
    call = worker.terminalizer.terminalize_interrupted_running_run.await_args.kwargs
    # The owner travels explicitly: the heartbeat context has reset it by now.
    assert call["owner"] == owner
    assert call["error"].code == FlowApiErrorCode.RUN_WORKER_SHUTDOWN
    assert call["error"].source == FlowRunLifecycleSource.TASK_FAILURE
    assert call["error"].retryable is False
    worker.provider_calls.mark_started_calls_outcome_unknown_for_run.assert_awaited_once_with(
        run_id=owner.run_id,
        tenant_id=owner.tenant_id,
        reason=ProviderCallUnknownReason.WORKER_INTERRUPTED,
    )
    await _stop(worker, poll)


@pytest.mark.asyncio
async def test_a_run_another_writer_already_ended_marks_no_provider_call(worker):
    owner = FlowRunExecutionOwner(uuid4(), uuid4(), 3)
    worker.terminalizer.terminalize_interrupted_running_run.return_value = (
        SimpleNamespace(did_transition=False)
    )
    poll = await _attached_worker_task(worker.manager)
    job = await _started_job(worker, owner)

    _shut_down(poll=poll, jobs=[job])

    with pytest.raises(asyncio.CancelledError):
        await job
    worker.provider_calls.mark_started_calls_outcome_unknown_for_run.assert_not_awaited()
    await _stop(worker, poll)


@pytest.mark.asyncio
async def test_a_cancellation_that_is_not_a_shutdown_leaves_the_run(worker):
    owner = FlowRunExecutionOwner(uuid4(), uuid4(), 1)
    poll = await _attached_worker_task(worker.manager)
    job = await _started_job(worker, owner)

    job.cancel()

    with pytest.raises(asyncio.CancelledError):
        await job
    worker.terminalizer.terminalize_interrupted_running_run.assert_not_awaited()
    worker.provider_calls.mark_started_calls_outcome_unknown_for_run.assert_not_awaited()
    await _stop(worker, poll)


@pytest.mark.asyncio
async def test_lost_ownership_during_a_shutdown_is_skipped_not_ended(worker):
    owner = FlowRunExecutionOwner(uuid4(), uuid4(), 1)
    poll = await _attached_worker_task(worker.manager)
    job = await _started_job(worker, owner)

    poll.cancel()
    # Another worker owns the run now: renewal no longer returns this owner.
    await worker.manager.renew()

    assert await job == {"status": "skipped", "reason": "execution_ownership_lost"}
    worker.terminalizer.terminalize_interrupted_running_run.assert_not_awaited()
    await _stop(worker, poll)


@pytest.mark.asyncio
async def test_a_hanging_shutdown_write_is_bounded(worker, monkeypatch):
    monkeypatch.setattr(
        flow_runtime_tasks, "FLOW_WORKER_SHUTDOWN_WRITE_TIMEOUT_SECONDS", 0.05
    )
    write_cancelled = asyncio.Event()

    async def hang(**_):
        try:
            await asyncio.Event().wait()
        finally:
            write_cancelled.set()

    worker.terminalizer.terminalize_interrupted_running_run.side_effect = hang
    poll = await _attached_worker_task(worker.manager)
    job = await _started_job(worker, owner=FlowRunExecutionOwner(uuid4(), uuid4(), 1))

    _shut_down(poll=poll, jobs=[job])

    async with asyncio.timeout(2):
        with pytest.raises(asyncio.CancelledError):
            await job
    # The write was stopped by its own bound, so its transaction rolls back.
    assert write_cancelled.is_set()
    worker.provider_calls.mark_started_calls_outcome_unknown_for_run.assert_not_awaited()
    await _stop(worker, poll)


@pytest.mark.asyncio
async def test_a_second_cancellation_does_not_interrupt_the_shutdown_write(worker):
    release = asyncio.Event()
    written = asyncio.Event()

    async def slow_write(**_):
        await release.wait()
        written.set()
        return SimpleNamespace(did_transition=True)

    worker.terminalizer.terminalize_interrupted_running_run.side_effect = slow_write
    poll = await _attached_worker_task(worker.manager)
    job = await _started_job(worker, owner=FlowRunExecutionOwner(uuid4(), uuid4(), 1))

    _shut_down(poll=poll, jobs=[job])
    for _ in range(5):
        await asyncio.sleep(0)
    job.cancel()

    with pytest.raises(asyncio.CancelledError):
        await job
    # The job is gone; the worker's shutdown hook (stop, then closing the
    # database) must still wait for the write the job started.
    stopping = asyncio.create_task(worker.manager.stop())
    for _ in range(5):
        await asyncio.sleep(0)
    assert not stopping.done()
    release.set()
    async with asyncio.timeout(2):
        await stopping
    assert written.is_set()
    poll.cancel()
    with pytest.raises(asyncio.CancelledError):
        await poll


@pytest.mark.asyncio
async def test_the_worker_shutdown_waits_for_a_job_still_cleaning_up(
    worker, monkeypatch
):
    # Tracking ends inside the execution session, whose cleanup the job awaits
    # before it reaches its shutdown write: the shutdown hook must wait for the
    # job itself, not only for the writes already started.
    cleaned_up = asyncio.Event()
    written = asyncio.Event()

    async def execute(*, run_id: UUID, tenant_id: UUID, run_revision: int, **_):
        try:
            async with worker.manager.track(
                FlowRunExecutionOwner(run_id, tenant_id, run_revision)
            ):
                worker.started.set()
                await asyncio.Event().wait()
        finally:
            await asyncio.shield(cleaned_up.wait())

    async def write(**_):
        written.set()
        return SimpleNamespace(did_transition=True)

    monkeypatch.setattr(flow_runtime_tasks, "_execute_flow_run_async", execute)
    worker.terminalizer.terminalize_interrupted_running_run.side_effect = write
    poll = await _attached_worker_task(worker.manager)
    job = await _started_job(worker, owner=FlowRunExecutionOwner(uuid4(), uuid4(), 1))

    _shut_down(poll=poll, jobs=[job])
    for _ in range(5):
        await asyncio.sleep(0)
    stopping = asyncio.create_task(worker.manager.stop())
    for _ in range(5):
        await asyncio.sleep(0)
    assert not stopping.done()
    assert not written.is_set()

    cleaned_up.set()
    async with asyncio.timeout(2):
        await stopping
    assert written.is_set()
    with pytest.raises(asyncio.CancelledError):
        await job
    with pytest.raises(asyncio.CancelledError):
        await poll


@pytest.mark.asyncio
async def test_the_worker_shutdown_waits_for_a_job_cancelled_before_it_tracks_its_run(
    worker, monkeypatch
):
    # A shutdown can cancel the job while it still claims the run (a commit
    # before tracking starts); the job then cleans up and starts its write.
    cleaned_up = asyncio.Event()
    claiming = asyncio.Event()
    written = asyncio.Event()

    async def execute(**_):
        try:
            claiming.set()
            await asyncio.Event().wait()
        finally:
            await asyncio.shield(cleaned_up.wait())

    async def write(**_):
        written.set()
        return SimpleNamespace(did_transition=True)

    monkeypatch.setattr(flow_runtime_tasks, "_execute_flow_run_async", execute)
    worker.terminalizer.terminalize_interrupted_running_run.side_effect = write
    poll = await _attached_worker_task(worker.manager)
    job = asyncio.create_task(
        flow_runtime_tasks.execute_flow_run_task(
            run_id=str(uuid4()),
            flow_id=str(uuid4()),
            tenant_id=str(uuid4()),
            run_revision=1,
            principal_type="user",
            principal_user_id=str(uuid4()),
            task_id="job-1",
            retry_count=0,
        )
    )
    await claiming.wait()

    _shut_down(poll=poll, jobs=[job])
    for _ in range(5):
        await asyncio.sleep(0)
    stopping = asyncio.create_task(worker.manager.stop())
    for _ in range(5):
        await asyncio.sleep(0)
    assert not stopping.done()

    cleaned_up.set()
    async with asyncio.timeout(2):
        await stopping
    assert written.is_set()
    with pytest.raises(asyncio.CancelledError):
        await job
    with pytest.raises(asyncio.CancelledError):
        await poll


@pytest.mark.asyncio
async def test_a_job_that_outlasts_the_shutdown_bound_leaves_its_run_to_the_reaper(
    worker, monkeypatch
):
    # Past the bound the worker goes on closing its database; a write started
    # after that would meet a closed database, so none starts and the
    # heartbeat reaper ends the run as it would after a crash.
    monkeypatch.setattr(heartbeat, "FLOW_WORKER_SHUTDOWN_WRITE_TIMEOUT_SECONDS", 0.05)
    cleaned_up = asyncio.Event()

    async def execute(*, run_id: UUID, tenant_id: UUID, run_revision: int, **_):
        try:
            async with worker.manager.track(
                FlowRunExecutionOwner(run_id, tenant_id, run_revision)
            ):
                worker.started.set()
                await asyncio.Event().wait()
        finally:
            await asyncio.shield(cleaned_up.wait())

    monkeypatch.setattr(flow_runtime_tasks, "_execute_flow_run_async", execute)
    poll = await _attached_worker_task(worker.manager)
    job = await _started_job(worker, owner=FlowRunExecutionOwner(uuid4(), uuid4(), 1))

    _shut_down(poll=poll, jobs=[job])
    async with asyncio.timeout(2):
        await worker.manager.stop()
    cleaned_up.set()
    with pytest.raises(asyncio.CancelledError):
        await job

    worker.terminalizer.terminalize_interrupted_running_run.assert_not_awaited()
    with pytest.raises(asyncio.CancelledError):
        await poll
