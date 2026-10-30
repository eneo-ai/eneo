"""The process's Redis clients, started and stopped with the process.

Two clients, each with its own connection pool, because their connections live
differently. A command borrows a connection for one round trip; a pub/sub
subscription holds one for as long as it listens.

- ``commands`` serves every command: the containers' ``redis_client`` (API-key
  rate limiting, tickets, OAuth state, change keys and the rest) and
  ``eneo.worker.redis.get_redis()`` (the audit config cache, audit sessions,
  job publishes, crawl markers).
- ``subscriptions`` serves only the pub/sub listeners: job events and
  websockets.

With REDIS_MAX_CONNECTIONS set, each pool is bounded by it on its own, so
subscriptions that fill theirs never starve the fail-closed rate limiter or an
audit write. A command that finds its pool busy waits up to
REDIS_POOL_WAIT_TIMEOUT (unset: REDIS_CONN_TIMEOUT) for a free connection, so a
burst queues instead of failing; a subscription past its bound fails at once,
as it always has. Unset, both pools are unbounded, as every Redis pool here has
been.

Every process that builds containers (the API and the workers) starts the
clients in its lifespan. Outside that lifetime a client is refused, never
created on demand: an unowned client is a connection nothing closes.
"""

import redis.asyncio as aioredis

from eneo.main.config import Settings, get_settings
from eneo.main.exceptions import NotReadyException
from eneo.redis.connection import build_redis_pool_kwargs, build_redis_url


def _owned_client(settings: Settings, *, queue_when_busy: bool) -> aioredis.Redis:
    url = build_redis_url(settings)
    kwargs = build_redis_pool_kwargs(settings, decode_responses=False)
    # redis-py stubs declare ConnectionPool.from_url(**kwargs: Unknown), so
    # pyright marks the calls as partially unknown though the pool is concrete.
    if queue_when_busy and settings.redis_max_connections is not None:
        pool: aioredis.ConnectionPool = aioredis.BlockingConnectionPool.from_url(  # pyright: ignore[reportUnknownMemberType]
            url,
            timeout=settings.redis_pool_wait_timeout or settings.redis_conn_timeout,
            **kwargs,
        )
    else:
        pool = aioredis.ConnectionPool.from_url(url, **kwargs)  # pyright: ignore[reportUnknownMemberType]
    # The client owns its pool: aclose() closes it.
    return aioredis.Redis.from_pool(pool)


class RedisClients:
    def __init__(self) -> None:
        super().__init__()
        self._commands: aioredis.Redis | None = None
        self._subscriptions: aioredis.Redis | None = None

    def start(self) -> None:
        """Build both clients from the current settings; connects lazily."""
        if self._commands is not None:
            raise RuntimeError("Redis clients are already running in this process")
        settings = get_settings()
        # Both or neither: building a client connects nothing, so a failure
        # here leaves no connection behind, and no half-started owner.
        commands = _owned_client(settings, queue_when_busy=True)
        subscriptions = _owned_client(settings, queue_when_busy=False)
        self._commands, self._subscriptions = commands, subscriptions

    async def stop(self) -> None:
        """Close both pools, including connections still checked out."""
        commands, subscriptions = self._commands, self._subscriptions
        self._commands = self._subscriptions = None
        try:
            if commands is not None:
                await commands.aclose()
        finally:
            if subscriptions is not None:
                await subscriptions.aclose()

    def commands(self) -> aioredis.Redis:
        return self._running(self._commands)

    def subscriptions(self) -> aioredis.Redis:
        return self._running(self._subscriptions)

    @staticmethod
    def _running(client: aioredis.Redis | None) -> aioredis.Redis:
        if client is None:
            raise NotReadyException("Redis clients are not running in this process")
        return client


redis_clients = RedisClients()
