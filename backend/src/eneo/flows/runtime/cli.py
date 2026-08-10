from __future__ import annotations

import logging
import os
from typing import NoReturn

from eneo.flows.runtime import celery_preflight
from eneo.main.config import get_loglevel, get_settings
from eneo.main.logging import get_logger

# Celery task registration is per app instance; `src.eneo...` creates
# a second app with no Flow tasks registered.
FLOW_CELERY_APP = "eneo.flows.runtime.celery_app:celery_app"
DEFAULT_CELERYBEAT_SCHEDULE_FILE = "/tmp/celerybeat-schedule"
logger = get_logger(__name__)


def _celery_loglevel() -> str:
    return logging.getLevelName(get_loglevel())


def _flow_worker_argv() -> list[str]:
    settings = get_settings()
    worker_queues = settings.flow_celery_worker_queues or settings.flow_celery_queue
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
    os.execvp("celery", _flow_beat_argv())
