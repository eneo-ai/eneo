from __future__ import annotations

import logging
import os
import socket
from typing import TYPE_CHECKING, NoReturn

from eneo.flows.runtime import celery_preflight
from eneo.flows.runtime.celery_app import (
    inspect_flow_celery_consumers,
    read_flow_beat_freshness_ttl_seconds,
)
from eneo.main.config import get_loglevel, get_settings
from eneo.main.logging import get_logger

if TYPE_CHECKING:
    from eneo.main.config import Settings

# Celery task registration is per app instance; `src.eneo...` creates
# a second app with no Flow tasks registered.
FLOW_CELERY_APP = "eneo.flows.runtime.celery_app:celery_app"
DEFAULT_CELERYBEAT_SCHEDULE_FILE = "/tmp/celerybeat-schedule"
logger = get_logger(__name__)


def _celery_loglevel() -> str:
    return logging.getLevelName(get_loglevel())


def _flow_worker_queues(settings: "Settings") -> str:
    """Resolve which queues this worker consumes from its declared role.

    Deployment declares a ROLE, never a queue name: the two queue-name
    settings are the single owner, so renaming a queue cannot leave a
    worker subscribed to the old name while beat schedules onto the new
    one. There is deliberately no name override — the environment file is
    shared by every role, so an override would apply to all of them.
    """
    if settings.flow_celery_worker_role == "maintenance":
        return settings.flow_celery_maintenance_queue
    return settings.flow_celery_queue


def _flow_worker_argv() -> list[str]:
    settings = get_settings()
    worker_queues = _flow_worker_queues(settings)
    per_process_budget = settings.db_pool_size + settings.db_pool_max_overflow
    logger.info(
        "Flow worker database connection budget: %s processes * "
        "(%s pool_size + %s max_overflow) = %s connections",
        settings.flow_celery_worker_concurrency,
        settings.db_pool_size,
        settings.db_pool_max_overflow,
        settings.flow_celery_worker_concurrency * per_process_budget,
    )
    return [
        "celery",
        "-A",
        FLOW_CELERY_APP,
        "worker",
        "--loglevel",
        _celery_loglevel(),
        "--concurrency",
        str(settings.flow_celery_worker_concurrency),
        "--queues",
        worker_queues,
    ]


def _flow_beat_argv() -> list[str]:
    schedule_file = os.environ.get(
        "CELERYBEAT_SCHEDULE_FILE",
        DEFAULT_CELERYBEAT_SCHEDULE_FILE,
    )
    return [
        "celery",
        "-A",
        FLOW_CELERY_APP,
        "beat",
        "--loglevel",
        _celery_loglevel(),
        "--pidfile=",
        f"--schedule={schedule_file}",
    ]


def worker() -> NoReturn:
    celery_preflight.run_preflight()
    os.execvp("celery", _flow_worker_argv())


def beat() -> NoReturn:
    os.environ["RUN_AS_CELERY_BEAT"] = "true"
    os.execvp("celery", _flow_beat_argv())


def worker_health() -> NoReturn:
    settings = get_settings()
    node_name = f"celery@{socket.gethostname()}"
    consumer_presence = inspect_flow_celery_consumers(
        destination=node_name,
        timeout_seconds=1.0,
    )
    expected_queue = _flow_worker_queues(settings)
    expected_queue_has_consumer = (
        consumer_presence.maintenance
        if expected_queue == settings.flow_celery_maintenance_queue
        else consumer_presence.execution
    )
    raise SystemExit(0 if expected_queue_has_consumer else 1)


def beat_health() -> NoReturn:
    ttl_seconds = read_flow_beat_freshness_ttl_seconds(timeout_seconds=1.0)
    raise SystemExit(0 if ttl_seconds is not None else 1)
