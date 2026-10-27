"""Platform maintenance workers on the test broker, built from the shipped
settings, for tests of how ARQ runs the webhook outbox job and its cron.

Only the startup hooks, which need the whole application, are left out."""

from __future__ import annotations

import asyncio
import warnings
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from dataclasses import replace
from datetime import datetime, timezone

from arq import create_pool
from arq.constants import in_progress_key_prefix, job_key_prefix, result_key_prefix
from arq.cron import CronJob
from arq.worker import Worker, create_worker
from dependency_injector import providers
from redis.asyncio import Redis

from eneo.jobs.job_manager import JobManager
from eneo.jobs.job_serialization import deserialize_job, serialize_job
from eneo.main.config import get_settings
from eneo.main.container.container import Container
from eneo.redis.connection import build_arq_redis_settings
from eneo.tasks.arq_adapter import ArqTaskEnqueuer
from eneo.tasks.routing import (
    FLOW_DELIVER_WEBHOOK_OUTBOX_TASK,
    FLOW_DRAIN_WEBHOOK_OUTBOX_TASK,
    task_queue_routing,
)
from eneo.worker.platform_tasks import PlatformMaintenanceWorkerSettings

_NEVER = datetime.max.replace(tzinfo=timezone.utc)


def webhook_cron() -> CronJob:
    """A copy of the shipped webhook outbox cron that schedules no tick of its
    own: a worker holding it runs ticks as the cron, and only
    ``tick_webhook_cron`` makes them."""
    [cron_job] = [
        job
        for job in PlatformMaintenanceWorkerSettings.cron_jobs
        if job.name == FLOW_DELIVER_WEBHOOK_OUTBOX_TASK
    ]
    return replace(cron_job, next_run=_NEVER)


@asynccontextmanager
async def platform_task_enqueuer() -> AsyncIterator[ArqTaskEnqueuer]:
    """The adapter runs and the cron send their requests through, installed
    as the container's for the block."""
    manager = JobManager()
    await manager.init()
    enqueuer = ArqTaskEnqueuer(job_manager=manager, routing=task_queue_routing())
    Container.platform_task_enqueuer.override(providers.Object(enqueuer))
    try:
        yield enqueuer
    finally:
        Container.platform_task_enqueuer.reset_last_overriding()
        await manager.close()


async def outbox_job_key_is_free(redis: Redis) -> bool:
    """No outbox job is queued or running, and none left anything under the
    fixed key that would refuse the next request."""
    key = FLOW_DRAIN_WEBHOOK_OUTBOX_TASK
    return (
        await redis.exists(
            job_key_prefix + key, in_progress_key_prefix + key, result_key_prefix + key
        )
        == 0
    )


async def clear_webhook_outbox_jobs(redis: Redis) -> None:
    """Remove the outbox job's and the cron ticks' ARQ keys and queue entries."""
    queue = get_settings().task_maintenance_queue
    for member in await redis.zrange(queue, 0, -1):
        if b"webhook_outbox" in member:
            await redis.zrem(queue, member)
    keys = [key async for key in redis.scan_iter(match="arq:*webhook_outbox*")]
    if keys:
        await redis.delete(*keys)


@asynccontextmanager
async def running_maintenance_worker() -> AsyncIterator[Worker]:
    """A maintenance worker polling the maintenance queue until the block ends."""
    worker = create_worker(
        PlatformMaintenanceWorkerSettings,
        redis_settings=build_arq_redis_settings(get_settings()),
        cron_jobs=[webhook_cron()],
        on_startup=None,
        on_shutdown=None,
        handle_signals=False,
        poll_delay=0.02,
    )
    run = asyncio.create_task(worker.async_run())
    try:
        yield worker
    finally:
        # Worker.close cancels the jobs still running, and a cancellation that
        # lands in ARQ's shielded finish escapes it before the pool closes. A
        # job can still be recording or finishing when the block's condition
        # holds, so polling stops first (a poll already under way can still
        # start a job) and the jobs it started get a bounded chance to end.
        run.cancel()
        try:
            with suppress(asyncio.CancelledError):
                await run
        finally:
            running = [task for task in worker.tasks.values() if not task.done()]
            if running:
                await asyncio.wait(running, timeout=10)
            with warnings.catch_warnings():
                # ARQ's Worker.close still calls the deprecated Redis close().
                warnings.simplefilter("ignore", DeprecationWarning)
                await worker.close()


@asynccontextmanager
async def webhook_cron_scheduler() -> AsyncIterator[Worker]:
    """A worker's cron scheduling, which ``tick_webhook_cron`` runs once per
    call; the worker itself never polls."""
    pool = await create_pool(
        build_arq_redis_settings(get_settings()),
        job_serializer=serialize_job,
        job_deserializer=deserialize_job,
    )
    try:
        yield create_worker(
            PlatformMaintenanceWorkerSettings,
            redis_pool=pool,
            functions=[],
            cron_jobs=[webhook_cron()],
            on_startup=None,
            on_shutdown=None,
            handle_signals=False,
        )
    finally:
        await pool.aclose()


async def tick_webhook_cron(scheduler: Worker, *, at: datetime) -> None:
    """Enqueue the cron's tick due at ``at`` (in the past) exactly as ARQ's
    heartbeat does, under the job id ARQ gives that tick."""
    [cron_job] = scheduler.cron_jobs
    cron_job.next_run = at
    await scheduler.run_cron(at, delay=0.5)
    cron_job.next_run = _NEVER


async def eventually(
    condition: Callable[[], Awaitable[bool]], *, timeout_seconds: float = 10
) -> None:
    async with asyncio.timeout(timeout_seconds):
        while not await condition():
            await asyncio.sleep(0.02)
