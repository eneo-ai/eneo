"""Redis connection helpers shared across services."""

from __future__ import annotations

from typing import Any

from arq.connections import RedisSettings

from intric.main.config import Settings, get_settings


def _get_redis_database(settings: Settings) -> int:
    redis_db = getattr(settings, "redis_db", None)
    return redis_db if redis_db is not None else 0


def build_arq_redis_settings(settings: Settings | None = None) -> RedisSettings:
    """Build ARQ Redis settings with connection resilience defaults."""
    resolved_settings = settings or get_settings()
    return RedisSettings(
        host=resolved_settings.redis_host,
        port=resolved_settings.redis_port,
        database=_get_redis_database(resolved_settings),
        conn_timeout=resolved_settings.redis_conn_timeout,
        conn_retries=resolved_settings.redis_conn_retries,
        conn_retry_delay=resolved_settings.redis_conn_retry_delay,
        retry_on_timeout=resolved_settings.redis_retry_on_timeout,
        max_connections=resolved_settings.redis_max_connections,
    )


def build_redis_pool_kwargs(
    settings: Settings | None = None,
    *,
    decode_responses: bool,
) -> dict[str, Any]:
    """Build keyword arguments for redis.asyncio connection pools."""
    resolved_settings = settings or get_settings()
    kwargs: dict[str, Any] = {
        "decode_responses": decode_responses,
        "socket_connect_timeout": resolved_settings.redis_conn_timeout,
        "retry_on_timeout": resolved_settings.redis_retry_on_timeout,
        "socket_keepalive": resolved_settings.redis_socket_keepalive,
        "health_check_interval": resolved_settings.redis_health_check_interval,
    }

    if resolved_settings.redis_max_connections is not None:
        kwargs["max_connections"] = resolved_settings.redis_max_connections

    redis_db = getattr(resolved_settings, "redis_db", None)
    if redis_db is not None:
        kwargs["db"] = redis_db

    return kwargs
