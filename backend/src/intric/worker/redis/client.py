"""Redis client connection management for worker operations."""

import re
from datetime import datetime, timezone
from typing import NamedTuple

import redis.asyncio as aioredis

from intric.main.config import get_settings
from intric.redis.connection import build_redis_pool_kwargs


def _get_redis_connection() -> aioredis.Redis:
    """Lazy initialization of Redis connection using current settings.

    Honors settings.redis_db to ensure health endpoint reads from the same
    Redis database as the worker/feeder.
    """
    settings = get_settings()
    redis_url = f"redis://{settings.redis_host}:{settings.redis_port}"
    redis_kwargs = build_redis_pool_kwargs(settings, decode_responses=False)
    pool = aioredis.ConnectionPool.from_url(redis_url, **redis_kwargs)
    return aioredis.Redis(connection_pool=pool)


# Initialize on first import
_redis_client: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
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
    """Check the health status of the arq worker via Redis health check key.

    Returns:
        WorkerHealth: Contains status, last_heartbeat timestamp, and details
    """
    try:
        # Default queue name in arq is "arq:queue", health check key is "{queue_name}:health-check"
        health_key = "arq:queue:health-check"
        worker_health_data = await r.get(health_key)

        if worker_health_data:
            worker_health_str = worker_health_data.decode("utf-8")
            return WorkerHealth(
                status="HEALTHY",
                last_heartbeat=datetime.now(timezone.utc).isoformat(),
                details=worker_health_str,
            )
        else:
            return WorkerHealth(
                status="UNHEALTHY",
                last_heartbeat=None,
                details="Worker health check key not found or expired",
            )

    except Exception as e:
        return WorkerHealth(
            status="UNKNOWN",
            last_heartbeat=None,
            details=f"Redis connection error: {str(e)}",
        )


def parse_arq_health_string(raw: str) -> dict:
    """Parse ARQ health-check string into structured data.

    Handles two timestamp formats:
    - ISO-8601: '2025-01-09T14:35:50.123456 j_complete=...' (timezone-aware)
    - ARQ default: 'Jan-09 14:35:50 j_complete=...' (naive local time)

    TIMEZONE LIMITATION:
    ARQ writes the default format using datetime.now() without timezone info,
    meaning the timestamp is in the WORKER's local time. We compare against
    the API server's local time, which is correct ONLY when both run in the
    same timezone.

    If API server and worker run in different timezones, arq_health_age_seconds
    may be incorrect by the timezone offset. In production, ensure all services
    run in the same timezone (typically UTC in containerized deployments).

    The presence of the health key in Redis (with its TTL) is a more reliable
    indicator of worker liveness than the parsed timestamp age.

    Returns dict with parsed timestamp and arq_health_age_seconds.
    """
    result = {
        "raw": raw,
        "timestamp": None,
        "timestamp_parsed": None,  # ISO string for debugging
        "arq_health_age_seconds": None,
        "j_complete": 0,
        "j_failed": 0,
        "j_retried": 0,
        "j_ongoing": 0,
        "queued": 0,
    }

    if not raw:
        return result

    parts = raw.split()

    # Try to parse timestamp
    timestamp_parsed = None
    now_for_comparison = None
    kv_start_idx = 0

    # Check if first token is ISO-8601 (contains 'T' and '-')
    if parts and "T" in parts[0] and "-" in parts[0]:
        try:
            # ISO-8601 format
            result["timestamp"] = parts[0]
            timestamp_parsed = datetime.fromisoformat(parts[0].replace("Z", "+00:00"))
            # Handle both aware and naive ISO timestamps:
            # - If aware (has tzinfo), compare against UTC
            # - If naive (no tzinfo), compare against naive local time
            if timestamp_parsed.tzinfo is not None:
                now_for_comparison = datetime.now(timezone.utc)
            else:
                now_for_comparison = datetime.now()  # naive local
            kv_start_idx = 1
        except ValueError:
            pass
    elif len(parts) >= 2:
        # Try ARQ default format: 'Jan-09 14:35:50'
        # Pattern: Mon-DD HH:MM:SS
        # NOTE: ARQ uses datetime.now() (naive local time) for this format
        combined = f"{parts[0]} {parts[1]}"
        if re.match(r"[A-Za-z]{3}-\d{2} \d{2}:\d{2}:\d{2}", combined):
            try:
                # Parse as naive local time (matching ARQ's behavior)
                now_local = datetime.now()  # naive local time
                year = now_local.year

                timestamp_parsed = datetime.strptime(
                    f"{year} {combined}", "%Y %b-%d %H:%M:%S"
                )

                # Year-boundary fix: if timestamp is in the future by more than
                # 1 day, it's likely from the previous year (e.g., Dec-31 parsed
                # in early January should use previous year)
                if timestamp_parsed > now_local:
                    time_diff = (timestamp_parsed - now_local).total_seconds()
                    if time_diff > 86400:  # More than 1 day in future
                        timestamp_parsed = datetime.strptime(
                            f"{year - 1} {combined}", "%Y %b-%d %H:%M:%S"
                        )

                result["timestamp"] = combined
                now_for_comparison = now_local  # Compare naive to naive
                kv_start_idx = 2
            except ValueError:
                pass

    # Calculate age if timestamp was parsed
    if timestamp_parsed and now_for_comparison:
        result["timestamp_parsed"] = timestamp_parsed.isoformat()
        age = (now_for_comparison - timestamp_parsed).total_seconds()
        result["arq_health_age_seconds"] = max(0, age)

    # Parse key=value pairs starting from kv_start_idx
    for part in parts[kv_start_idx:]:
        if "=" in part:
            key, _, value = part.partition("=")
            if key in result and key not in (
                "raw",
                "timestamp",
                "timestamp_parsed",
                "arq_health_age_seconds",
            ):
                try:
                    result[key] = int(value)
                except ValueError:
                    pass

    return result
