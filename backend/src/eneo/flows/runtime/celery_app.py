from __future__ import annotations

import asyncio
from typing import Any

from celery import Celery  # pyright: ignore[reportMissingTypeStubs]
from celery.signals import (  # pyright: ignore[reportMissingTypeStubs]
    worker_process_init,
    worker_process_shutdown,
)

from eneo.database.database import sessionmanager
from eneo.flows.application.flow_run_audit_outbox_policy import (
    FLOW_AUDIT_OUTBOX_DELIVERY_INTERVAL_SECONDS,
)
from eneo.flows.application.flow_run_recovery_policy import (
    FLOW_QUEUED_REDISPATCH_AFTER_SECONDS,
    FLOW_RUNNING_RECONCILE_INTERVAL_SECONDS,
    flow_task_hard_timeout_seconds,
)
from eneo.flows.application.flow_webhook_delivery_policy import (
    FLOW_WEBHOOK_DELIVERY_INTERVAL_SECONDS,
)
from eneo.flows.flow_review_expiry_policy import (
    FLOW_REVIEW_EXPIRY_RECONCILE_INTERVAL_SECONDS,
)
from eneo.main.aiohttp_client import aiohttp_client
from eneo.main.config import get_settings
from eneo.main.logging import get_logger
from eneo.main.observability import init_observability
from eneo.worker.celery import create_celery_app as create_shared_celery_app

logger = get_logger(__name__)


def create_flow_celery_app() -> Celery:
    settings = get_settings()
    soft_time_limit = max(int(settings.flow_task_timeout_seconds), 1)
    app = create_shared_celery_app(
        app_name="eneo_flows",
        default_queue=settings.flow_celery_queue,
        task_routes={
            "flows.execute": {"queue": settings.flow_celery_queue},
            "flows.reconcile_running": {"queue": settings.flow_celery_queue},
            "flows.reconcile_review_expiry": {"queue": settings.flow_celery_queue},
            "flows.redispatch_stale_queued": {"queue": settings.flow_celery_queue},
            "flows.deliver_audit_outbox": {"queue": settings.flow_celery_queue},
            "flows.deliver_webhook_outbox": {"queue": settings.flow_celery_queue},
        },
    )
    app.conf.update(  # pyright: ignore[reportUnknownMemberType]
        include=["eneo.flows.runtime.tasks"],
        task_soft_time_limit=soft_time_limit,
        task_time_limit=flow_task_hard_timeout_seconds(
            task_timeout_seconds=soft_time_limit
        ),
        beat_schedule={
            "reconcile-stale-running": {
                "task": "flows.reconcile_running",
                "schedule": float(FLOW_RUNNING_RECONCILE_INTERVAL_SECONDS),
            },
            "redispatch-stale-queued": {
                "task": "flows.redispatch_stale_queued",
                "schedule": float(FLOW_QUEUED_REDISPATCH_AFTER_SECONDS),
            },
            "reconcile-review-expiry": {
                "task": "flows.reconcile_review_expiry",
                "schedule": float(FLOW_REVIEW_EXPIRY_RECONCILE_INTERVAL_SECONDS),
            },
            "deliver-flow-audit-outbox": {
                "task": "flows.deliver_audit_outbox",
                "schedule": float(FLOW_AUDIT_OUTBOX_DELIVERY_INTERVAL_SECONDS),
            },
            "deliver-flow-webhook-outbox": {
                "task": "flows.deliver_webhook_outbox",
                "schedule": float(FLOW_WEBHOOK_DELIVERY_INTERVAL_SECONDS),
            },
        },
    )
    return app


celery_app = create_flow_celery_app()


def _close_flow_worker_resources() -> None:
    asyncio.run(aiohttp_client.stop())
    asyncio.run(sessionmanager.close())


@worker_process_init.connect  # pyright: ignore[reportUnknownMemberType]
def _on_flow_worker_process_init(*_args: Any, **_kwargs: Any) -> None:  # pyright: ignore[reportUnusedFunction]
    init_observability()
    settings = get_settings()
    sessionmanager.init(settings.database_url)
    aiohttp_client.start()
    logger.info("Initialized flow celery worker process resources")


@worker_process_shutdown.connect  # pyright: ignore[reportUnknownMemberType]
def _on_flow_worker_process_shutdown(*_args: Any, **_kwargs: Any) -> None:  # pyright: ignore[reportUnusedFunction]
    try:
        _close_flow_worker_resources()
    except Exception:
        logger.exception("Failed to cleanly close flow celery worker resources")
