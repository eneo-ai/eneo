from uuid import UUID

from arq import create_pool
from arq.connections import ArqRedis
from arq.jobs import Job

from intric.jobs.job_models import Task
from intric.jobs.task_models import TaskParams
from intric.main.config import get_settings
from intric.main.exceptions import NotReadyException
from intric.main.logging import get_logger
from intric.redis.connection import build_arq_redis_settings

logger = get_logger(__name__)


class JobManager:
    def __init__(self):
        self._redis: ArqRedis | None = None

    async def init(self):
        settings = get_settings()
        self._redis = await create_pool(build_arq_redis_settings(settings))

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
        await self._redis.enqueue_job(task)

    async def get_job_status(self, job_id: UUID):
        job = Job(job_id=str(job_id), redis=self._redis)

        return await job.status()


job_manager = JobManager()
