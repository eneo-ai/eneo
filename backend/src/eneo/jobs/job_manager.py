from uuid import UUID

from arq import create_pool
from arq.connections import ArqRedis
from arq.jobs import Job

from eneo.jobs.job_models import Task
from eneo.jobs.job_serialization import deserialize_job, serialize_job
from eneo.jobs.task_models import TaskParams
from eneo.main.config import get_settings
from eneo.main.exceptions import NotReadyException
from eneo.main.logging import get_logger
from eneo.redis.connection import build_arq_redis_settings

logger = get_logger(__name__)


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

        logger.debug(
            f"Job manager connected to redis on host {settings.redis_host}"
            f" and port {settings.redis_port}"
        )

    async def close(self):
        if self._redis is None:
            return
        await self._redis.aclose()
        self._redis = None

    async def enqueue(self, task: Task, job_id: UUID, params: TaskParams):
        if self._redis is None:
            raise NotReadyException("Job manager is not initialized!")

        await self._redis.enqueue_job(task, params, _job_id=str(job_id))

    async def enqueue_jobless(self, task: Task):
        assert self._redis is not None
        await self._redis.enqueue_job(task)

    async def get_job_status(self, job_id: UUID):
        if self._redis is None:
            raise NotReadyException("Job manager is not initialized!")
        job = Job(job_id=str(job_id), redis=self._redis)

        return await job.status()


job_manager = JobManager()
