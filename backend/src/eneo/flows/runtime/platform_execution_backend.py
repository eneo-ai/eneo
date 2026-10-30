from __future__ import annotations

from uuid import uuid4

from eneo.flows.execution_backend import FlowExecutionDispatchRejected
from eneo.flows.flow_run_dispatch_request import (
    FlowRunDispatchRequest,
    flow_run_dispatch_task_kwargs,
)
from eneo.main.logging import get_logger
from eneo.tasks.contracts import (
    TaskCapacityClass,
    TaskEnqueuer,
    TaskEnqueueRequest,
    TaskEnqueueStatus,
)
from eneo.tasks.routing import FLOW_EXECUTE_TASK

logger = get_logger(__name__)


class PlatformFlowExecutionBackend:
    """Dispatch Flow runs through the queue-neutral platform task contract."""

    def __init__(self, *, task_enqueuer: TaskEnqueuer) -> None:
        self._task_enqueuer = task_enqueuer

    async def dispatch(self, *, request: FlowRunDispatchRequest) -> None:
        # Each durable dispatch attempt gets a fresh transport identity. Duplicate
        # delivery is safe because the run revision claim is the idempotency fence;
        # reusing an ARQ job id would prevent recovery when a queued delivery is lost
        # but its job metadata key remains in Redis.
        task_key = uuid4()
        result = await self._task_enqueuer.enqueue(
            TaskEnqueueRequest(
                task_name=FLOW_EXECUTE_TASK,
                capacity_class=TaskCapacityClass.EXECUTION,
                idempotency_key=str(task_key),
                payload=flow_run_dispatch_task_kwargs(request),
            )
        )
        if result.status is TaskEnqueueStatus.REFUSED:
            raise FlowExecutionDispatchRejected(
                "Platform task runtime refused the Flow dispatch request."
            )
        if result.status is TaskEnqueueStatus.OUTCOME_UNKNOWN:
            raise RuntimeError("Platform task enqueue outcome is unknown.")

        logger.info(
            "Dispatched flow run through platform task runtime",
            extra={
                "run_id": str(request.run_id),
                "flow_id": str(request.flow_id),
                "tenant_id": str(request.tenant_id),
                "task_id": result.task_id,
                "capacity_class": TaskCapacityClass.EXECUTION.value,
            },
        )
