from typing import cast
from uuid import UUID

from arq import create_pool
from arq.connections import ArqRedis
from arq.constants import (
    abort_jobs_ss,
    in_progress_key_prefix,
    job_key_prefix,
    result_key_prefix,
    retry_key_prefix,
)
from arq.jobs import Job
from arq.utils import timestamp_ms
from redis.asyncio import ConnectionPool

from eneo.jobs.job_models import Task
from eneo.jobs.job_serialization import deserialize_job, serialize_job
from eneo.jobs.task_models import TaskParams
from eneo.main.config import get_settings
from eneo.main.exceptions import NotReadyException
from eneo.main.logging import get_logger
from eneo.redis.connection import build_arq_redis_settings

logger = get_logger(__name__)

DEFAULT_QUEUE_NAME = "arq:queue"
CRAWLER_QUEUE_NAME = "arq:crawler"


def queue_name_for_task(task: Task) -> str:
    if task == Task.CRAWL:
        return CRAWLER_QUEUE_NAME
    return DEFAULT_QUEUE_NAME


class JobManager:
    def __init__(self) -> None:
        super().__init__()
        self._redis: ArqRedis | None = None

    async def init(self):
        settings = get_settings()
        self._redis = await create_pool(
            build_arq_redis_settings(settings),
            job_serializer=serialize_job,
            job_deserializer=deserialize_job,
        )
        # arq's settings carry no read timeout. Without one, an enqueue on a
        # Redis that accepts connections and never answers waits for ever, and
        # so does the transaction cleanup after it. Every read now ends at the
        # bound the other Redis clients use.
        # ponytail: redis-py 5.x leaves the connection of a transaction whose
        # cleanup timed out counted as in use; with REDIS_MAX_CONNECTIONS set,
        # enough such stalls exhaust this pool until restart. Recheck whenever
        # redis-py is upgraded.
        connections = cast(ConnectionPool, self._redis.connection_pool)
        connections.connection_kwargs["socket_timeout"] = settings.redis_conn_timeout  # pyright: ignore[reportUnknownMemberType]
        # The connection create_pool checked Redis with predates the bound.
        await connections.disconnect()
        connections.reset()

        logger.debug(
            f"Job manager connected to redis on host {settings.redis_host}"
            f" and port {settings.redis_port}"
        )

    async def close(self):
        if self._redis is None:
            return
        await self._redis.aclose()
        self._redis = None

    async def enqueue(self, task: Task, job_id: UUID, params: TaskParams) -> Job | None:
        if self._redis is None:
            raise NotReadyException("Job manager is not initialized!")

        return await self._redis.enqueue_job(
            task,
            params,
            _job_id=str(job_id),
            _queue_name=queue_name_for_task(task),
        )

    async def enqueue_jobless(self, task: Task):
        assert self._redis is not None
        await self._redis.enqueue_job(task, _queue_name=queue_name_for_task(task))

    async def discard_crawl_deliveries(self, job_ids: tuple[UUID, ...]) -> None:
        """Atomically remove terminal crawl deliveries and their ARQ bookkeeping."""
        if not job_ids:
            return
        if self._redis is None:
            raise NotReadyException("Job manager is not initialized!")

        members = tuple(str(job_id) for job_id in job_ids)
        keys = tuple(
            key
            for member in members
            for key in (
                job_key_prefix + member,
                in_progress_key_prefix + member,
                retry_key_prefix + member,
                result_key_prefix + member,
            )
        )
        # Deletion is idempotent; PostgreSQL retains the cleanup obligation
        # until this transaction succeeds and the caller acknowledges it.
        async with self._redis.pipeline(transaction=True) as transaction:
            transaction.zrem(CRAWLER_QUEUE_NAME, *members)
            transaction.zrem(abort_jobs_ss, *members)
            transaction.delete(*keys)
            await transaction.execute()

    async def signal_crawl_abort(self, job_id: UUID) -> None:
        """Record ARQ's abort marker for a running crawler delivery."""
        if self._redis is None:
            raise NotReadyException("Job manager is not initialized!")
        await self._redis.zadd(abort_jobs_ss, {str(job_id): timestamp_ms()})

    async def get_job_status(self, job_id: UUID, task: Task):
        if self._redis is None:
            raise NotReadyException("Job manager is not initialized!")
        job = Job(
            job_id=str(job_id),
            redis=self._redis,
            _queue_name=queue_name_for_task(task),
        )

        return await job.status()


job_manager = JobManager()
