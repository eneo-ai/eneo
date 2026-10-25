"""How ARQ runs the webhook outbox job and its cron, on a real broker.

The requests go in through the platform adapter, as a run and the cron send
them, and a worker built from the shipped maintenance settings runs them, so
the registered name, the fixed key, the payload, the timeouts and ARQ's own
bookkeeping are the real ones. Only the job's body is replaced: it counts its
runs, and can be held or made to fail."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from arq.constants import in_progress_key_prefix, job_key_prefix, retry_key_prefix

from eneo.flows.application.flow_webhook_delivery_policy import (
    flow_webhook_delivery_request,
)
from eneo.main.config import get_settings
from eneo.tasks.contracts import TaskEnqueueResult, TaskEnqueueStatus
from eneo.tasks.routing import (
    FLOW_DELIVER_WEBHOOK_OUTBOX_TASK,
    FLOW_DRAIN_WEBHOOK_OUTBOX_TASK,
)
from eneo.worker import platform_tasks
from tests.integration.flows.maintenance_worker_support import (
    clear_webhook_outbox_jobs,
    eventually,
    outbox_job_key_is_free,
    platform_task_enqueuer,
    running_maintenance_worker,
    tick_webhook_cron,
    webhook_cron_scheduler,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

_KEY = FLOW_DRAIN_WEBHOOK_OUTBOX_TASK


@pytest.fixture(autouse=True)
async def _outbox_jobs_cleared(redis_client) -> AsyncIterator[None]:
    await clear_webhook_outbox_jobs(redis_client)
    yield
    await clear_webhook_outbox_jobs(redis_client)


@pytest.fixture
def outbox_job(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Stands in for the outbox job's body. ``runs`` counts its runs; a run
    waits for ``gate`` and raises once ``fail_next`` is set."""
    job = SimpleNamespace(
        runs=0, running=asyncio.Event(), gate=asyncio.Event(), fail_next=False
    )
    job.gate.set()

    async def body() -> dict[str, int | str]:
        job.runs += 1
        job.running.set()
        await job.gate.wait()
        if job.fail_next:
            job.fail_next = False
            raise RuntimeError("outbox job failed")
        return {"status": "ok"}

    monkeypatch.setattr(platform_tasks, "deliver_flow_webhook_outbox", body)
    return job


async def test_a_maintenance_worker_runs_the_requested_outbox_job_under_its_key(
    outbox_job, redis_client
) -> None:
    outbox_job.gate.clear()
    async with platform_task_enqueuer() as enqueuer:
        result = await enqueuer.enqueue(flow_webhook_delivery_request())
        assert result == TaskEnqueueResult(
            status=TaskEnqueueStatus.ACCEPTED, task_id=_KEY
        )
        async with running_maintenance_worker():
            async with asyncio.timeout(10):
                await outbox_job.running.wait()
            assert await redis_client.exists(in_progress_key_prefix + _KEY) == 1
            outbox_job.gate.set()
            await eventually(lambda: outbox_job_key_is_free(redis_client))

    assert outbox_job.runs == 1


async def test_the_outbox_job_key_is_free_after_every_run_that_ended(
    outbox_job, redis_client
) -> None:
    """Kills: a kept result or in-progress marker under the fixed key, after a
    run that succeeded or one that failed, which refuses the next request."""
    async with platform_task_enqueuer() as enqueuer, running_maintenance_worker():
        for fails in (False, False, True, False):
            outbox_job.fail_next = fails
            runs_before = outbox_job.runs
            result = await enqueuer.enqueue(flow_webhook_delivery_request())
            assert result.status is TaskEnqueueStatus.ACCEPTED

            async def ended() -> bool:
                return outbox_job.runs > runs_before and await outbox_job_key_is_free(
                    redis_client
                )

            await eventually(ended)

    assert outbox_job.runs == 4


async def test_successive_cron_ticks_each_run_the_outbox_job(
    setup_database, outbox_job, redis_client
) -> None:
    """Kills: the cron under one fixed job id. An ended tick keeps ARQ's
    60-second in-progress marker; under a fixed id it would hold back the next
    tick, and the outbox job with it."""

    async def tick_keys(prefix: str) -> list[bytes]:
        pattern = f"{prefix}{FLOW_DELIVER_WEBHOOK_OUTBOX_TASK}*"
        return [key async for key in redis_client.scan_iter(match=pattern)]

    async def ended(runs: int) -> bool:
        return (
            outbox_job.runs >= runs
            and await outbox_job_key_is_free(redis_client)
            and not await tick_keys(job_key_prefix)
        )

    now = datetime.now(timezone.utc)
    async with (
        platform_task_enqueuer(),
        webhook_cron_scheduler() as scheduler,
        running_maintenance_worker(),
    ):
        await tick_webhook_cron(scheduler, at=now - timedelta(seconds=2))
        await eventually(lambda: ended(1))
        [marker] = await tick_keys(in_progress_key_prefix)
        assert 0 < await redis_client.pttl(marker) <= 60_000

        await tick_webhook_cron(scheduler, at=now - timedelta(seconds=1))
        await eventually(lambda: ended(2))

    assert outbox_job.runs == 2


async def test_requests_while_the_outbox_job_is_queued_or_running_share_it(
    outbox_job, redis_client
) -> None:
    """Two maintenance workers, and requests from many runs at once: one
    outbox job runs while it is queued or running."""
    request = flow_webhook_delivery_request()
    queue = get_settings().task_maintenance_queue
    outbox_job.gate.clear()
    async with platform_task_enqueuer() as enqueuer:
        queued = await asyncio.gather(*(enqueuer.enqueue(request) for _ in range(20)))
        assert {result.status for result in queued} == {TaskEnqueueStatus.ACCEPTED}
        assert await redis_client.zrange(queue, 0, -1) == [_KEY.encode()]

        async with running_maintenance_worker(), running_maintenance_worker():
            async with asyncio.timeout(10):
                await outbox_job.running.wait()
            running = await asyncio.gather(
                *(enqueuer.enqueue(request) for _ in range(20))
            )
            assert {result.status for result in running} == {TaskEnqueueStatus.ACCEPTED}
            # Both workers poll every 20 ms: a second job would have started.
            await asyncio.sleep(0.3)
            assert outbox_job.runs == 1
            outbox_job.gate.set()
            await eventually(lambda: outbox_job_key_is_free(redis_client))

    assert outbox_job.runs == 1


async def test_an_outbox_job_killed_mid_run_is_not_run_again_when_picked_up(
    outbox_job, redis_client
) -> None:
    """Kills: more than one try for the outbox job. A job killed mid-run keeps
    its try count; when ARQ picks it up again it records it as failed without
    running it, and the next request starts a new job."""
    async with platform_task_enqueuer() as enqueuer:
        result = await enqueuer.enqueue(flow_webhook_delivery_request())
        assert result.status is TaskEnqueueStatus.ACCEPTED
        # What a start that was killed leaves behind: ARQ counted its try.
        await redis_client.incr(retry_key_prefix + _KEY)
        async with running_maintenance_worker():
            await eventually(lambda: outbox_job_key_is_free(redis_client))
            assert outbox_job.runs == 0

            result = await enqueuer.enqueue(flow_webhook_delivery_request())
            assert result.status is TaskEnqueueStatus.ACCEPTED

            async def ran_once() -> bool:
                return outbox_job.runs == 1 and await outbox_job_key_is_free(
                    redis_client
                )

            await eventually(ran_once)

    assert outbox_job.runs == 1
