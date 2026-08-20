from __future__ import annotations

from redis.exceptions import RedisError

from eneo.jobs.job_manager import JobManager
from eneo.main.exceptions import NotReadyException
from eneo.main.logging import get_logger
from eneo.tasks.contracts import (
    TaskEnqueueRequest,
    TaskEnqueueResult,
    TaskEnqueueStatus,
)
from eneo.tasks.routing import TASK_CAPACITY_BY_NAME, TaskQueueRouting

logger = get_logger(__name__)


class ArqTaskEnqueuer:
    """Platform ARQ adapter for queue-neutral task requests."""

    def __init__(
        self,
        *,
        job_manager: JobManager,
        routing: TaskQueueRouting,
    ) -> None:
        self._job_manager = job_manager
        self._routing = routing

    async def enqueue(self, request: TaskEnqueueRequest) -> TaskEnqueueResult:
        expected_capacity = TASK_CAPACITY_BY_NAME.get(request.task_name)
        if expected_capacity is None or expected_capacity is not request.capacity_class:
            return TaskEnqueueResult(status=TaskEnqueueStatus.REFUSED)

        queue_name = self._routing.queue_for(request.capacity_class)
        try:
            job = await self._job_manager.enqueue_named(
                task_name=request.task_name,
                payload=request.payload,
                job_id=request.idempotency_key,
                queue_name=queue_name,
            )
        except NotReadyException:
            return TaskEnqueueResult(status=TaskEnqueueStatus.REFUSED)
        except (RedisError, OSError):
            logger.warning(
                "Platform task enqueue outcome is unknown",
                extra={
                    "task_name": request.task_name,
                    "capacity_class": request.capacity_class.value,
                    "idempotency_key": request.idempotency_key,
                },
            )
            return TaskEnqueueResult(status=TaskEnqueueStatus.OUTCOME_UNKNOWN)

        # ARQ returns None when the idempotency key already exists. The prior
        # accepted task remains authoritative, so duplicates are accepted.
        task_id = request.idempotency_key if job is None else job.job_id
        return TaskEnqueueResult(
            status=TaskEnqueueStatus.ACCEPTED,
            task_id=task_id,
        )
