"""Fail a test when a GET changes state without a declared, reasoned effect.

A same-origin navigation carries the browser session cookie, so any page can
make the user's browser send a GET. A GET must therefore change nothing,
unless its ``endpoint_access(effect_on_get=...)`` says what and why that is
safe. This tripwire records database and Redis writes made while a GET or
HEAD is handled and reports those of endpoints without that declaration.

Requests carrying an API key are skipped: an API key rules the session cookie
out, and authenticating one records its use. Bearer requests stand in for the
cookie, which authenticates through the same dependency.

ponytail: sees only the GETs the integration tests send and the writes made
in-process before the response completes; the declared effects were reviewed
route by route (eneo-web-next-vite-ded5.3.12).
"""

import re
from collections.abc import Callable
from contextvars import ContextVar
from typing import Any

from redis.asyncio import Redis
from redis.asyncio.client import Pipeline
from sqlalchemy import event
from sqlalchemy.engine import Engine
from starlette.types import ASGIApp, Receive, Scope, Send

from eneo.authentication.endpoint_access import access_for
from eneo.main.config import get_settings

_SAFE_METHODS = frozenset({"GET", "HEAD"})
_SQL_WRITE = re.compile(
    r"^\s*(INSERT|UPDATE|DELETE|MERGE|TRUNCATE)\b"
    # A data-modifying CTE: WITH x AS (...) INSERT/UPDATE/DELETE ...
    r"|^\s*WITH\b.*\b(INSERT\s+INTO|DELETE\s+FROM|UPDATE\s+\S+\s+SET)\b",
    re.IGNORECASE | re.DOTALL,
)
_REDIS_WRITES = frozenset(
    {
        "APPEND", "COPY", "DECR", "DECRBY", "DEL", "EVAL", "EVALSHA", "EXPIRE",
        "EXPIREAT", "FCALL", "GETDEL", "GETEX", "GETSET", "HDEL", "HINCRBY",
        "HMSET", "HSET", "HSETNX", "INCR", "INCRBY", "INCRBYFLOAT", "LMOVE",
        "LPOP", "LPUSH", "LREM", "LTRIM", "MSET", "PERSIST", "PEXPIRE",
        "PEXPIREAT", "PSETEX", "PUBLISH", "RENAME", "RPOP", "RPUSH", "SADD",
        "SET", "SETEX", "SETNX", "SPOP", "SREM", "UNLINK", "XADD", "XDEL",
        "ZADD", "ZINCRBY", "ZREM",
    }
)  # fmt: skip

_writes: ContextVar[list[str] | None] = ContextVar("safe_method_writes", default=None)


def is_sql_write(statement: str) -> bool:
    return _SQL_WRITE.match(statement) is not None


def is_redis_write(command: object) -> bool:
    name = command.decode() if isinstance(command, bytes) else str(command)
    return name.upper() in _REDIS_WRITES


def _record(write: str) -> None:
    writes = _writes.get()
    if writes is not None:
        writes.append(write)


def _on_sql(_conn: Any, _cursor: Any, statement: str, *_args: Any) -> None:
    if is_sql_write(statement):
        _record(" ".join(statement.split())[:120])


class SafeMethodTripwire:
    """Pure ASGI middleware; collects violations instead of raising mid-request."""

    def __init__(self, app: ASGIApp, violations: list[str]) -> None:
        self.app = app
        self.violations = violations

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] not in _SAFE_METHODS
            or any(
                name.decode().lower() == get_settings().api_key_header_name.lower()
                for name, _ in scope["headers"]
            )
        ):
            await self.app(scope, receive, send)
            return
        writes: list[str] = []
        token = _writes.set(writes)
        try:
            await self.app(scope, receive, send)
        finally:
            _writes.reset(token)
        # Starlette's router records the matched endpoint on this scope.
        policy = access_for(scope.get("endpoint"))
        if writes and (policy is None or policy.effect_on_get is None):
            self.violations.append(
                f"{scope['method']} {scope['path']} changed state without "
                f"endpoint_access(effect_on_get=...): {writes}"
            )


def install() -> Callable[[], None]:
    """Start recording writes; returns the function that stops it."""
    redis_execute = Redis.execute_command
    pipeline_execute = Pipeline.execute

    async def execute_command(self: Redis, *args: Any, **options: Any) -> Any:
        if args and is_redis_write(args[0]):
            _record(f"redis {args[0]!s} {args[1]!s}" if len(args) > 1 else "redis")
        return await redis_execute(self, *args, **options)

    async def execute(self: Pipeline, *args: Any, **options: Any) -> Any:
        for command_args, _ in self.command_stack:
            if command_args and is_redis_write(command_args[0]):
                _record(f"redis pipeline {command_args[0]!s}")
        return await pipeline_execute(self, *args, **options)

    event.listen(Engine, "before_cursor_execute", _on_sql)
    Redis.execute_command = execute_command  # type: ignore[method-assign]
    Pipeline.execute = execute  # type: ignore[method-assign]

    def uninstall() -> None:
        event.remove(Engine, "before_cursor_execute", _on_sql)
        Redis.execute_command = redis_execute  # type: ignore[method-assign]
        Pipeline.execute = pipeline_execute  # type: ignore[method-assign]

    return uninstall
