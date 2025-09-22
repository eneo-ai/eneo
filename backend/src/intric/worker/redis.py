import redis.asyncio as aioredis
from datetime import datetime, timezone
from typing import NamedTuple

from intric.main.config import SETTINGS

pool = aioredis.ConnectionPool.from_url(
    f"redis://{SETTINGS.redis_host}:{SETTINGS.redis_port}"
)
r = aioredis.Redis(connection_pool=pool)


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
                status="healthy",
                last_heartbeat=datetime.now(timezone.utc).isoformat(),
                details=worker_health_str
            )
        else:
            return WorkerHealth(
                status="unhealthy",
                last_heartbeat=None,
                details="Worker health check key not found or expired"
            )

    except Exception as e:
        return WorkerHealth(
            status="unknown",
            last_heartbeat=None,
            details=f"Redis connection error: {str(e)}"
        )
