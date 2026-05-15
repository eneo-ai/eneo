"""Redis client connection management for worker operations."""

import json
import re
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, NamedTuple, Protocol, Self, cast

import redis.asyncio as aioredis
from intric.main.config import Settings, get_settings
from intric.redis.connection import build_redis_pool_kwargs


def create_worker_redis_client(
    settings: Settings, *, decode_responses: bool = False
) -> aioredis.Redis:
    """Create a worker Redis client through one typed redis-py boundary."""
    redis_url = f"redis://{settings.redis_host}:{settings.redis_port}"
    redis_kwargs = build_redis_pool_kwargs(settings, decode_responses=decode_responses)
    connection_pool_factory: Any = aioredis.ConnectionPool
    pool = connection_pool_factory.from_url(redis_url, **redis_kwargs)
    return aioredis.Redis(connection_pool=pool)


def _get_redis_connection() -> aioredis.Redis:
    """Lazy initialization of Redis connection using current settings.

    Honors settings.redis_db to ensure health endpoint reads from the same
    Redis database as the worker/feeder.
    """
    return create_worker_redis_client(get_settings())


# Initialize on first import
_redis_client: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    """Get Redis client, creating it if needed."""
    global _redis_client
    if _redis_client is None:
        _redis_client = _get_redis_connection()
    return _redis_client


def redis_pipeline_items(raw_result: Sequence[object]) -> tuple[object, ...]:
    """Return Redis pipeline results as an immutable tuple.

    redis-py exposes pipeline results through a weakly typed async boundary.
    Keep that uncertainty here so crawl phase modules do not need broad casts.
    """
    if isinstance(raw_result, str | bytes | bytearray):
        raise TypeError(
            f"Redis pipeline returned {type(raw_result).__name__}, "
            "expected a non-string sequence"
        )

    return tuple(raw_result)


r = get_redis()

WATCHDOG_LAST_SUCCESS_EPOCH_KEY = "crawl_watchdog:last_success_epoch"
WATCHDOG_LAST_METRICS_KEY = "crawl_watchdog:last_metrics"


@dataclass(frozen=True, slots=True)
class WatchdogLifecycleSnapshot:
    queued: int
    running_no_progress: int
    running_with_progress: int
    terminal: int


@dataclass(frozen=True, slots=True)
class WatchdogMetricsSnapshot:
    observed_at: datetime
    zombies_reconciled: int
    expired_killed: int
    rescued: int
    early_zombies_failed: int
    long_running_failed: int
    slots_released: int
    lifecycle_observed: WatchdogLifecycleSnapshot


@dataclass(frozen=True, slots=True)
class WatchdogStatusSnapshot:
    last_cleanup_at: datetime | None
    metrics: WatchdogMetricsSnapshot | None


def _redis_text(raw_value: object) -> str | None:
    if raw_value is None:
        return None
    if isinstance(raw_value, bytes):
        return raw_value.decode("utf-8")
    if isinstance(raw_value, str):
        return raw_value
    return None


def _string_key_mapping(source: object) -> Mapping[str, object] | None:
    if not isinstance(source, Mapping):
        return None
    source_mapping = cast(Mapping[object, object], source)
    values: dict[str, object] = {}
    for raw_key, raw_value in source_mapping.items():
        if not isinstance(raw_key, str):
            return None
        values[raw_key] = raw_value
    return values


def _int_field(source: Mapping[str, object], key: str) -> int | None:
    raw_value = source.get(key)
    if isinstance(raw_value, bool):
        return None
    if isinstance(raw_value, int):
        return raw_value
    return None


def _parse_epoch_seconds(raw_value: object) -> datetime | None:
    raw_text = _redis_text(raw_value)
    if raw_text is None:
        return None
    try:
        return datetime.fromtimestamp(int(raw_text), tz=timezone.utc)
    except ValueError:
        return None


def _parse_watchdog_metrics(raw_value: object) -> WatchdogMetricsSnapshot | None:
    raw_text = _redis_text(raw_value)
    if raw_text is None:
        return None

    try:
        payload: object = json.loads(raw_text)
    except json.JSONDecodeError:
        return None
    payload_mapping = _string_key_mapping(payload)
    if payload_mapping is None:
        return None

    raw_timestamp = payload_mapping.get("timestamp")
    if not isinstance(raw_timestamp, str):
        return None
    try:
        observed_at = datetime.fromisoformat(raw_timestamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)

    lifecycle_payload = payload_mapping.get("lifecycle_observed")
    lifecycle_mapping = _string_key_mapping(lifecycle_payload)
    if lifecycle_mapping is None:
        return None

    queued = _int_field(lifecycle_mapping, "queued")
    running_no_progress = _int_field(lifecycle_mapping, "running_no_progress")
    running_with_progress = _int_field(lifecycle_mapping, "running_with_progress")
    terminal = _int_field(lifecycle_mapping, "terminal")
    zombies_reconciled = _int_field(payload_mapping, "zombies_reconciled")
    expired_killed = _int_field(payload_mapping, "expired_killed")
    rescued = _int_field(payload_mapping, "rescued")
    early_zombies_failed = _int_field(payload_mapping, "early_zombies_failed")
    long_running_failed = _int_field(payload_mapping, "long_running_failed")
    slots_released = _int_field(payload_mapping, "slots_released")

    if (
        queued is None
        or running_no_progress is None
        or running_with_progress is None
        or terminal is None
        or zombies_reconciled is None
        or expired_killed is None
        or rescued is None
        or early_zombies_failed is None
        or long_running_failed is None
        or slots_released is None
    ):
        return None

    return WatchdogMetricsSnapshot(
        observed_at=observed_at,
        zombies_reconciled=zombies_reconciled,
        expired_killed=expired_killed,
        rescued=rescued,
        early_zombies_failed=early_zombies_failed,
        long_running_failed=long_running_failed,
        slots_released=slots_released,
        lifecycle_observed=WatchdogLifecycleSnapshot(
            queued=queued,
            running_no_progress=running_no_progress,
            running_with_progress=running_with_progress,
            terminal=terminal,
        ),
    )


async def read_watchdog_status_snapshot(
    redis: aioredis.Redis,
) -> WatchdogStatusSnapshot:
    """Read the watchdog's ephemeral Redis status snapshot."""
    redis_client: Any = redis
    raw_last_success: object = await redis_client.get(WATCHDOG_LAST_SUCCESS_EPOCH_KEY)
    raw_metrics: object = await redis_client.get(WATCHDOG_LAST_METRICS_KEY)
    return WatchdogStatusSnapshot(
        last_cleanup_at=_parse_epoch_seconds(raw_last_success),
        metrics=_parse_watchdog_metrics(raw_metrics),
    )


class RedisPipelineLike(Protocol):
    def expire(self, name: str, time: int) -> object: ...

    def set(
        self,
        name: str,
        value: str | bytes,
        ex: int | None = None,
        *,
        nx: bool = False,
    ) -> object: ...

    def get(self, name: str) -> object: ...

    def incr(self, name: str) -> object: ...

    async def execute(self) -> Sequence[object]: ...

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: object,
        exc_value: object,
        traceback: object,
    ) -> None: ...


def redis_pipeline(
    redis: aioredis.Redis, *, transaction: bool = True
) -> RedisPipelineLike:
    """Create a Redis pipeline through the worker's typed boundary."""
    return redis.pipeline(transaction=transaction)


async def redis_lrange_bytes(
    redis: aioredis.Redis, key: str, start: int, stop: int
) -> list[bytes]:
    redis_client: Any = redis
    raw_values: object = await redis_client.lrange(key, start, stop)
    if not isinstance(raw_values, list | tuple):
        raise TypeError(
            f"Redis LRANGE returned {type(raw_values).__name__}, expected a sequence"
        )

    raw_sequence = cast(Sequence[object], raw_values)
    values: list[bytes] = []
    for raw_value in raw_sequence:
        if not isinstance(raw_value, bytes):
            raise TypeError(
                "Redis LRANGE returned non-bytes value "
                f"{type(raw_value).__name__}; decode_responses must stay disabled"
            )
        values.append(raw_value)
    return values


async def redis_lrem_exact(redis: aioredis.Redis, key: str, raw_bytes: bytes) -> int:
    redis_client: Any = redis
    return int(await redis_client.lrem(key, 1, raw_bytes))


async def redis_rpush_text(redis: aioredis.Redis, key: str, value: str) -> int:
    redis_client: Any = redis
    return int(await redis_client.rpush(key, value))


async def redis_lpush_bytes(redis: aioredis.Redis, key: str, raw_bytes: bytes) -> int:
    redis_client: Any = redis
    return int(await redis_client.lpush(key, raw_bytes))


async def redis_ltrim_list(
    redis: aioredis.Redis, key: str, start: int, stop: int
) -> None:
    redis_client: Any = redis
    await redis_client.ltrim(key, start, stop)


async def redis_expire_key(redis: aioredis.Redis, key: str, seconds: int) -> None:
    redis_client: Any = redis
    await redis_client.expire(key, seconds)


async def redis_delete_keys(redis: aioredis.Redis, *keys: str) -> int:
    redis_client: Any = redis
    return int(await redis_client.delete(*keys))


async def redis_scan_match_bytes(
    redis: aioredis.Redis, *, pattern: str, count: int
) -> AsyncIterator[bytes]:
    """Yield Redis keys matching a pattern while owning SCAN cursor handling."""
    redis_client: Any = redis
    cursor = 0
    while True:
        raw_result: object = await redis_client.scan(
            cursor=cursor, match=pattern, count=count
        )
        if not isinstance(raw_result, tuple | list):
            raise TypeError(
                f"Redis SCAN returned {type(raw_result).__name__}, expected pair"
            )

        raw_pair = cast(Sequence[object], raw_result)
        if len(raw_pair) != 2:
            raise TypeError(
                f"Redis SCAN returned {type(raw_pair).__name__}, expected pair"
            )
        raw_cursor = raw_pair[0]
        if not isinstance(raw_cursor, int | str | bytes):
            raise TypeError(
                f"Redis SCAN cursor was {type(raw_cursor).__name__}, expected scalar"
            )
        cursor = int(raw_cursor)
        raw_keys = raw_pair[1]

        if not isinstance(raw_keys, list | tuple):
            raise TypeError(
                f"Redis SCAN returned {type(raw_keys).__name__}, expected keys sequence"
            )

        raw_key_sequence = cast(Sequence[object], raw_keys)
        for raw_key in raw_key_sequence:
            if not isinstance(raw_key, bytes):
                raise TypeError(
                    "Redis SCAN returned non-bytes key "
                    f"{type(raw_key).__name__}; decode_responses must stay disabled"
                )
            yield raw_key

        if cursor == 0:
            break


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


def parse_arq_health_string(raw: str) -> dict[str, int | str | float | None]:
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
    result: dict[str, int | str | float | None] = {
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
