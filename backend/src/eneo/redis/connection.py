"""Redis connection helpers shared across services."""

from __future__ import annotations

import asyncio
from typing import Any

from arq.connections import RedisSettings
from redis.asyncio.connection import AbstractConnection

from eneo.main.config import Settings, get_settings


def _get_redis_database(settings: Settings) -> int:
    redis_db = getattr(settings, "redis_db", None)
    return redis_db if redis_db is not None else 0


def build_redis_url(settings: Settings | None = None) -> str:
    """The Redis address. Credentials travel as client arguments, never in the URL."""
    resolved_settings = settings or get_settings()
    return f"redis://{resolved_settings.redis_host}:{resolved_settings.redis_port}"


def build_redis_auth_kwargs(settings: Settings | None = None) -> dict[str, Any]:
    """Credentials for a Redis client; empty when authentication is not configured."""
    resolved_settings = settings or get_settings()
    auth: dict[str, Any] = {}
    if resolved_settings.redis_username is not None:
        auth["username"] = resolved_settings.redis_username
    if resolved_settings.redis_password is not None:
        auth["password"] = resolved_settings.redis_password
    return auth


def build_arq_redis_settings(settings: Settings | None = None) -> RedisSettings:
    """Build ARQ Redis settings with connection resilience defaults."""
    resolved_settings = settings or get_settings()
    return RedisSettings(
        host=resolved_settings.redis_host,
        port=resolved_settings.redis_port,
        username=resolved_settings.redis_username,
        password=resolved_settings.redis_password,
        database=_get_redis_database(resolved_settings),
        conn_timeout=resolved_settings.redis_conn_timeout,
        conn_retries=resolved_settings.redis_conn_retries,
        conn_retry_delay=resolved_settings.redis_conn_retry_delay,
        retry_on_timeout=resolved_settings.redis_retry_on_timeout,
        max_connections=resolved_settings.redis_max_connections,
    )


async def _connect_without_health_check(connection: AbstractConnection) -> None:
    """Set up a new connection without first checking its health.

    redis-py checks health from inside its own setup. Against a Redis that
    accepts connections and never answers, each failed check reconnects into
    another check, so no read timeout ends the wait. A connection that has
    just connected needs no check: its interval starts now.
    """
    # ponytail: a workaround for redis-py 5.x; recheck it, and drop it if the
    # silent-Redis tests pass without it, whenever redis-py is upgraded.
    loop = asyncio.get_running_loop()
    connection.next_health_check = loop.time() + connection.health_check_interval
    await connection.on_connect()


def build_redis_pool_kwargs(
    settings: Settings | None = None,
    *,
    decode_responses: bool,
) -> dict[str, Any]:
    """Build keyword arguments for redis.asyncio connection pools."""
    resolved_settings = settings or get_settings()
    kwargs: dict[str, Any] = {
        **build_redis_auth_kwargs(resolved_settings),
        "decode_responses": decode_responses,
        "socket_connect_timeout": resolved_settings.redis_conn_timeout,
        # A Redis that accepts connections and never answers must not hold a
        # request: every read ends at the same bound as the connect.
        "socket_timeout": resolved_settings.redis_conn_timeout,
        "retry_on_timeout": resolved_settings.redis_retry_on_timeout,
        "socket_keepalive": resolved_settings.redis_socket_keepalive,
        "health_check_interval": resolved_settings.redis_health_check_interval,
        "redis_connect_func": _connect_without_health_check,
    }

    if resolved_settings.redis_max_connections is not None:
        kwargs["max_connections"] = resolved_settings.redis_max_connections

    redis_db = getattr(resolved_settings, "redis_db", None)
    if redis_db is not None:
        kwargs["db"] = redis_db

    return kwargs
