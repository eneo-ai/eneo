from typing import cast
from uuid import UUID, uuid4

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
from redis.asyncio.client import Pipeline
from redis.exceptions import ConnectionError as RedisConnectionError

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


class _Pipeline(Pipeline):
    """A transaction that hands its connection back however its cleanup ends.

    redis-py 5 hands it back only when the UNWATCH that ends a transaction is
    answered or fails with ConnectionError. After a read timeout it stays
    counted as in use for ever, so a few stalls leave a pool capped by
    REDIS_MAX_CONNECTIONS with no connection, and an uncapped one growing.
    """

    # ponytail: works around redis-py 5.x; recheck whenever redis-py is
    # upgraded, and drop it if the silent-Redis tests pass without it.
    async def reset(self) -> None:
        try:
            await super().reset()
        except BaseException:
            connection, self.connection = self.connection, None
            self.watching = False
            if connection is not None:
                await connection.disconnect(nowait=True)
                await cast(ConnectionPool, self.connection_pool).release(connection)
            raise


class _QueueRedis(ArqRedis):
    def pipeline(
        self, transaction: bool = True, shard_hint: str | None = None
    ) -> Pipeline:
        return _Pipeline(
            cast(ConnectionPool, self.connection_pool),
            self.response_callbacks,
            transaction,
            shard_hint,
        )


class JobManager:
    def __init__(self) -> None:
        super().__init__()
        self._redis: ArqRedis | None = None

    async def init(self):
        settings = get_settings()
        # create_pool connects, with its retries, and checks Redis answers.
        checked = await create_pool(build_arq_redis_settings(settings))
        # arq's settings carry no read timeout. Without one, an enqueue on a
        # Redis that accepts connections and never answers waits for ever, and
        # so does the transaction cleanup after it. Every read now ends at the
        # bound the other Redis clients use.
        connections = cast(ConnectionPool, checked.connection_pool)
        connections.connection_kwargs["socket_timeout"] = settings.redis_conn_timeout  # pyright: ignore[reportUnknownMemberType]
        # The connection create_pool checked Redis with predates the bound.
        await connections.disconnect()
        connections.reset()
        self._redis = _QueueRedis(
            connections,
            job_serializer=serialize_job,
            job_deserializer=deserialize_job,
        )

        logger.debug(
            f"Job manager connected to redis on host {settings.redis_host}"
            f" and port {settings.redis_port}"
        )

    async def close(self):
        if self._redis is None:
            return
        await self._redis.aclose(close_connection_pool=True)
        self._redis = None

    async def enqueue(self, task: Task, job_id: UUID, params: TaskParams) -> Job | None:
        return await self._enqueue(task, job_id, params)

    async def enqueue_jobless(self, task: Task) -> None:
        """Queue a task that takes no parameters."""
        await self._enqueue(task, uuid4())

    async def _enqueue(
        self, task: Task, job_id: UUID, *params: TaskParams
    ) -> Job | None:
        if self._redis is None:
            raise NotReadyException("Job manager is not initialized!")

        job = await self._redis.enqueue_job(
            task,
            *params,
            _job_id=str(job_id),
            _queue_name=queue_name_for_task(task),
        )
        # arq answers None for a job that is already queued, and also for a
        # transaction a lost or timed-out connection ended. Only the first
        # leaves the job behind.
        if job is None and not await self._redis.exists(
            job_key_prefix + str(job_id), result_key_prefix + str(job_id)
        ):
            raise RedisConnectionError(f"Redis did not confirm job {job_id}")
        return job

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
