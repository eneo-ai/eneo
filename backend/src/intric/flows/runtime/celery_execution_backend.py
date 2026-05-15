from __future__ import annotations

from functools import partial
from typing import Any, Callable, cast

from anyio.to_thread import run_sync
from celery import Celery  # pyright: ignore[reportMissingTypeStubs]

from intric.flows.flow_run_dispatch_request import (
    FlowRunDispatchRequest,
    flow_run_dispatch_task_kwargs,
)
from intric.main.config import get_settings
from intric.main.logging import get_logger

logger = get_logger(__name__)

FLOW_EXECUTE_TASK_NAME = "flows.execute"


class CeleryFlowExecutionBackend:
    """Celery-backed flow execution dispatcher."""

    def __init__(
        self,
        celery_app: Celery,
        queue_name: str | None = None,
    ):
        self.celery_app = celery_app
        self.queue_name = queue_name or get_settings().flow_celery_queue

    async def dispatch(
        self,
        *,
        request: FlowRunDispatchRequest,
    ) -> None:
        send_task = cast(
            Callable[..., Any],
            self.celery_app.send_task,  # pyright: ignore[reportUnknownMemberType]
        )
        await run_sync(
            cast(
                Callable[[], Any],
                partial(
                    send_task,
                    FLOW_EXECUTE_TASK_NAME,
                    kwargs=flow_run_dispatch_task_kwargs(request),
                    queue=self.queue_name,
                ),
            )
        )
        logger.info(
            "Dispatched flow run to Celery queue",
            extra={
                "run_id": str(request.run_id),
                "flow_id": str(request.flow_id),
                "tenant_id": str(request.tenant_id),
                "queue": self.queue_name,
            },
        )
