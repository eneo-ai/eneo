from __future__ import annotations

from functools import partial
from uuid import UUID

import anyio
from celery import Celery

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
        run_id: UUID,
        flow_id: UUID,
        tenant_id: UUID,
        user_id: UUID | None,
    ) -> None:
        await anyio.to_thread.run_sync(
            partial(
                self.celery_app.send_task,
                FLOW_EXECUTE_TASK_NAME,
                kwargs={
                    "run_id": str(run_id),
                    "flow_id": str(flow_id),
                    "tenant_id": str(tenant_id),
                    "user_id": str(user_id) if user_id is not None else None,
                },
                queue=self.queue_name,
            )
        )
        logger.info(
            "Dispatched flow run to Celery queue",
            extra={
                "run_id": str(run_id),
                "flow_id": str(flow_id),
                "tenant_id": str(tenant_id),
                "queue": self.queue_name,
            },
        )
