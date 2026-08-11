from __future__ import annotations

import asyncio
import os
from collections.abc import Callable, Coroutine
from contextlib import closing
from dataclasses import dataclass
from typing import Any, cast

from celery import Celery  # pyright: ignore[reportMissingTypeStubs]
from celery.signals import (  # pyright: ignore[reportMissingTypeStubs]
    after_task_publish,
    worker_process_init,
    worker_process_shutdown,
)
from redis import Redis

from eneo.database.database import sessionmanager
from eneo.flows.application.flow_run_audit_outbox_policy import (
    FLOW_AUDIT_OUTBOX_DELIVERY_INTERVAL_SECONDS,
)
from eneo.flows.application.flow_webhook_delivery_policy import (
    FLOW_WEBHOOK_DELIVERY_INTERVAL_SECONDS,
)
from eneo.flows.domain.flow_run_recovery_policy import (
    FLOW_QUEUED_REDISPATCH_AFTER_SECONDS,
    FLOW_RUNNING_RECONCILE_INTERVAL_SECONDS,
    flow_task_hard_timeout_seconds,
)
from eneo.flows.flow_review_expiry_policy import (
    FLOW_REVIEW_EXPIRY_RECONCILE_INTERVAL_SECONDS,
)
from eneo.main.aiohttp_client import aiohttp_client
from eneo.main.config import get_settings
from eneo.main.logging import get_logger
from eneo.main.observability import init_observability
from eneo.object_content.content import ObjectContentUnavailableError
from eneo.object_content.runtime import object_content_runtime
from eneo.worker.celery import create_celery_app as create_shared_celery_app

logger = get_logger(__name__)

# One existing frequent schedule proves Beat's publish path without adding a
# second control-plane task whose only purpose is monitoring.
FLOW_BEAT_FRESHNESS_KEY = "flows:beat:freshness"
FLOW_BEAT_FRESHNESS_TASK = "flows.redispatch_stale_queued"
FLOW_BEAT_FRESHNESS_TTL_SECONDS = FLOW_QUEUED_REDISPATCH_AFTER_SECONDS * 3
FLOW_CELERY_INSPECTION_TIMEOUT_SECONDS = 1.0


@dataclass(frozen=True, slots=True)
class FlowCeleryConsumerPresence:
    execution: bool
    maintenance: bool


def create_flow_celery_app() -> Celery:
    settings = get_settings()
    soft_time_limit = max(int(settings.flow_task_timeout_seconds), 1)
    app = create_shared_celery_app(
        app_name="eneo_flows",
        default_queue=settings.flow_celery_queue,
        task_routes={
            "flows.execute": {"queue": settings.flow_celery_queue},
            "flows.reconcile_running": {
                "queue": settings.flow_celery_maintenance_queue
            },
            "flows.reconcile_review_expiry": {
                "queue": settings.flow_celery_maintenance_queue
            },
            "flows.redispatch_stale_queued": {
                "queue": settings.flow_celery_maintenance_queue
            },
            "flows.deliver_audit_outbox": {
                "queue": settings.flow_celery_maintenance_queue
            },
            "flows.deliver_webhook_outbox": {
                "queue": settings.flow_celery_maintenance_queue
            },
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
                "task": FLOW_BEAT_FRESHNESS_TASK,
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


def inspect_flow_celery_consumers(
    *,
    timeout_seconds: float = FLOW_CELERY_INSPECTION_TIMEOUT_SECONDS,
    destination: str | None = None,
) -> FlowCeleryConsumerPresence:
    """Return configured Flow queue consumers reported by responding workers."""
    try:
        inspection = cast(
            object,
            (
                celery_app.control.inspect(  # pyright: ignore[reportUnknownMemberType]
                    timeout=timeout_seconds,
                    destination=[destination],
                )
                if destination is not None
                else celery_app.control.inspect(  # pyright: ignore[reportUnknownMemberType]
                    timeout=timeout_seconds
                )
            ),
        )
        active_queues = cast(
            Callable[[], object],
            getattr(inspection, "active_queues"),
        )
        raw_active_queues = active_queues()
    except Exception:
        logger.warning("Flow Celery queue consumer inspection unavailable")
        return FlowCeleryConsumerPresence(execution=False, maintenance=False)

    if not isinstance(raw_active_queues, dict):
        return FlowCeleryConsumerPresence(execution=False, maintenance=False)
    active_queues = cast(dict[object, object], raw_active_queues)
    settings = get_settings()
    reported_queue_names: set[str] = set()
    for worker_queues in active_queues.values():
        if not isinstance(worker_queues, list):
            continue
        queues = cast(list[object], worker_queues)
        for queue in queues:
            if not isinstance(queue, dict):
                continue
            queue_data = cast(dict[object, object], queue)
            queue_name = queue_data.get("name")
            if isinstance(queue_name, str):
                reported_queue_names.add(queue_name)
    return FlowCeleryConsumerPresence(
        execution=settings.flow_celery_queue in reported_queue_names,
        maintenance=settings.flow_celery_maintenance_queue in reported_queue_names,
    )


def _open_flow_health_redis_client(*, timeout_seconds: float) -> Redis:
    settings = get_settings()
    return Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        db=settings.redis_db,
        socket_connect_timeout=timeout_seconds,
        socket_timeout=timeout_seconds,
        retry_on_timeout=False,
        socket_keepalive=settings.redis_socket_keepalive,
        health_check_interval=settings.redis_health_check_interval,
    )


def read_flow_beat_freshness_ttl_seconds(
    *, timeout_seconds: float = FLOW_CELERY_INSPECTION_TIMEOUT_SECONDS
) -> int | None:
    try:
        with closing(
            _open_flow_health_redis_client(timeout_seconds=timeout_seconds)
        ) as client:
            raw_ttl = client.ttl(FLOW_BEAT_FRESHNESS_KEY)
    except Exception:
        logger.warning("Flow Beat freshness inspection unavailable")
        return None

    if type(raw_ttl) is not int or raw_ttl <= 0:
        return None
    return raw_ttl


@after_task_publish.connect  # pyright: ignore[reportUnknownMemberType]
def _record_flow_beat_freshness(  # pyright: ignore[reportUnusedFunction]
    sender: str | None = None,
    **_kwargs: Any,
) -> None:
    if (
        os.environ.get("RUN_AS_CELERY_BEAT", "").lower() != "true"
        or sender != FLOW_BEAT_FRESHNESS_TASK
    ):
        return

    try:
        with closing(
            _open_flow_health_redis_client(
                timeout_seconds=FLOW_CELERY_INSPECTION_TIMEOUT_SECONDS
            )
        ) as client:
            client.set(
                FLOW_BEAT_FRESHNESS_KEY,
                "1",
                ex=FLOW_BEAT_FRESHNESS_TTL_SECONDS,
            )
    except Exception:
        # Publishing remains authoritative; a failed diagnostic write becomes
        # visible when the previous receipt expires and the healthcheck fails.
        logger.warning("Could not refresh Flow Beat freshness receipt")


async def _start_flow_worker_async_resources() -> None:
    object_content_runtime.start()
    try:
        await object_content_runtime.validate_configuration()
    except ObjectContentUnavailableError:
        # Match API startup semantics: a transient storage dependency outage
        # keeps the process live while task execution fails explicitly until
        # readiness recovers.
        pass
    aiohttp_client.start()


async def _close_flow_worker_async_resources() -> None:
    await object_content_runtime.stop()
    await aiohttp_client.stop()
    await sessionmanager.close()


def _run_on_flow_task_loop(coroutine: Coroutine[Any, Any, None]) -> None:
    # Import lazily because the task module owns the process-long async loop and
    # imports this Celery application during registration.
    from eneo.flows.runtime.tasks import get_flow_task_loop

    asyncio.run_coroutine_threadsafe(coroutine, get_flow_task_loop()).result()


def _close_flow_worker_resources() -> None:
    _run_on_flow_task_loop(_close_flow_worker_async_resources())


@worker_process_init.connect  # pyright: ignore[reportUnknownMemberType]
def _on_flow_worker_process_init(*_args: Any, **_kwargs: Any) -> None:  # pyright: ignore[reportUnusedFunction]
    init_observability()
    settings = get_settings()
    sessionmanager.init(settings.database_url)
    _run_on_flow_task_loop(_start_flow_worker_async_resources())
    logger.info("Initialized flow celery worker process resources")


@worker_process_shutdown.connect  # pyright: ignore[reportUnknownMemberType]
def _on_flow_worker_process_shutdown(*_args: Any, **_kwargs: Any) -> None:  # pyright: ignore[reportUnusedFunction]
    try:
        _close_flow_worker_resources()
    except Exception:
        logger.exception("Failed to cleanly close flow celery worker resources")
