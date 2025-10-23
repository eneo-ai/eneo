import redis.asyncio as aioredis
from datetime import datetime, timezone
from typing import NamedTuple

from intric.main.config import get_settings


def _get_redis_connection():
    """Lazy initialization of Redis connection using current settings."""
    settings = get_settings()
    pool = aioredis.ConnectionPool.from_url(
        f"redis://{settings.redis_host}:{settings.redis_port}"
    )
    return aioredis.Redis(connection_pool=pool)


# Initialize on first import
_redis_client = None


def get_redis():
    """Get Redis client, creating it if needed."""
    global _redis_client
    if _redis_client is None:
        _redis_client = _get_redis_connection()
    return _redis_client


r = get_redis()


class WorkerHealth(NamedTuple):
    status: str  # "healthy", "unhealthy", "unknown"
    last_heartbeat: str | None
    details: str | None


async def get_worker_health() -> WorkerHealth:
    """
    Check the health status of the arq worker by looking for its health check key in Redis.

    Returns:
        WorkerHealth: Contains status, last_heartbeat timestamp, and details
    """
    try:
        # Check for arq worker health check key
        # Default queue name in arq is "arq:queue", health check key is "{queue_name}:health-check"
        health_key = "arq:queue:health-check"
        worker_health_data = await r.get(health_key)

        if worker_health_data:
            worker_health_str = worker_health_data.decode('utf-8')
            return WorkerHealth(
                status="HEALTHY",
                last_heartbeat=datetime.now(timezone.utc).isoformat(),
                details=worker_health_str
            )
        else:
            return WorkerHealth(
                status="UNHEALTHY",
                last_heartbeat=None,
                details="Worker health check key not found or expired"
            )

    except Exception as e:
        return WorkerHealth(
            status="UNKNOWN",
            last_heartbeat=None,
            details=f"Redis connection error: {str(e)}"
        )
