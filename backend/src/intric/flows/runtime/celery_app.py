from __future__ import annotations

import asyncio
from typing import Any

from celery import Celery  # pyright: ignore[reportMissingTypeStubs]
from celery.signals import (  # pyright: ignore[reportMissingTypeStubs]
    worker_process_init,
    worker_process_shutdown,
)

from intric.database.database import sessionmanager
from intric.main.aiohttp_client import aiohttp_client
from intric.main.config import get_settings
from intric.main.logging import get_logger
from intric.worker.celery import create_celery_app as create_shared_celery_app

logger = get_logger(__name__)


def create_flow_celery_app() -> Celery:
    settings = get_settings()
    app = create_shared_celery_app(
        app_name="intric_flows",
        default_queue=settings.flow_celery_queue,
        task_routes={
            "flows.execute": {"queue": settings.flow_celery_queue},
        },
    )
    app.conf.update(include=["intric.flows.runtime.tasks"])  # pyright: ignore[reportUnknownMemberType]
    return app


celery_app = create_flow_celery_app()


def _close_flow_worker_resources() -> None:
    asyncio.run(aiohttp_client.stop())
    asyncio.run(sessionmanager.close())


@worker_process_init.connect  # pyright: ignore[reportUnknownMemberType]
def _on_flow_worker_process_init(*_args: Any, **_kwargs: Any) -> None:  # pyright: ignore[reportUnusedFunction]
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
