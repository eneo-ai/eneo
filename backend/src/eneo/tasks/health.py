from __future__ import annotations

import asyncio

from arq.constants import health_check_key_suffix
from redis.asyncio import Redis
from redis.exceptions import RedisError

from eneo.main.config import get_settings
from eneo.main.logging import get_logger
from eneo.redis.connection import build_redis_pool_kwargs
from eneo.tasks.contracts import TaskWorkerReadiness

logger = get_logger(__name__)


async def load_task_worker_readiness(
    *, timeout_seconds: float = 1.0
) -> TaskWorkerReadiness:
    settings = get_settings()
    redis = Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        **build_redis_pool_kwargs(settings, decode_responses=True),
    )
    try:
        async with asyncio.timeout(timeout_seconds):
            execution_ready, maintenance_ready = await redis.mget(
                f"{settings.task_execution_queue}{health_check_key_suffix}",
                f"{settings.task_maintenance_queue}{health_check_key_suffix}",
            )
    except (TimeoutError, RedisError, OSError):
        logger.warning("Platform task worker readiness probe failed")
        return TaskWorkerReadiness(
            execution_ready=False,
            maintenance_ready=False,
        )
    finally:
        await redis.aclose()

    return TaskWorkerReadiness(
        execution_ready=execution_ready is not None,
        maintenance_ready=maintenance_ready is not None,
    )
