from __future__ import annotations

import logging
import os
from typing import NoReturn

from eneo.flows.runtime import celery_preflight
from eneo.main.config import get_loglevel, get_settings

# Celery task registration is per app instance; `src.eneo...` creates
# a second app with no Flow tasks registered.
FLOW_CELERY_APP = "eneo.flows.runtime.celery_app:celery_app"
DEFAULT_CELERYBEAT_SCHEDULE_FILE = "/tmp/celerybeat-schedule"


def _celery_loglevel() -> str:
    return logging.getLevelName(get_loglevel())


def _flow_worker_argv() -> list[str]:
    settings = get_settings()
    return [
        "celery",
        "-A",
        FLOW_CELERY_APP,
        "worker",
        "--loglevel",
        _celery_loglevel(),
        "--queues",
        settings.flow_celery_queue,
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
