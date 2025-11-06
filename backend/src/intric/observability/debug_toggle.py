"""Runtime toggle management for OIDC debug logging."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import aiohttp
import redis.asyncio as aioredis

from intric.main.config import get_loglevel
from intric.main.logging import get_logger


FLAG_KEY = "observability:oidc_debug"
REFRESH_INTERVAL = timedelta(seconds=5)
MAX_DURATION = timedelta(hours=2)
DEFAULT_DURATION = timedelta(minutes=30)
FLAG_PATH = Path(os.getenv("OIDC_DEBUG_FLAG_PATH", "/app/data/debug_flags/oidc_debug.json"))


@dataclass
class DebugFlag:
    enabled: bool = False
    enabled_at: Optional[datetime] = None
    enabled_by: Optional[str] = None
    expires_at: Optional[datetime] = None
    reason: Optional[str] = None

    def is_expired(self, now: datetime) -> bool:
        return bool(self.expires_at and now >= self.expires_at)


_cache = DebugFlag()
_last_refresh = datetime.min.replace(tzinfo=timezone.utc)
_lock = asyncio.Lock()
_base_log_level = get_loglevel()
_OIDC_LOGGER_ATTRS = (
    ("intric.authentication.federation_router", "logger"),
    ("intric.authentication.auth_service", "logger"),
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _flag_to_payload(flag: DebugFlag) -> dict[str, Any]:
    return {
        "enabled": flag.enabled,
        "enabled_at": flag.enabled_at.isoformat() if flag.enabled_at else None,
        "enabled_by": flag.enabled_by,
        "expires_at": flag.expires_at.isoformat() if flag.expires_at else None,
        "reason": flag.reason,
    }


def _payload_to_flag(data: dict[str, Any]) -> DebugFlag:
    def _parse(dt: Any) -> Optional[datetime]:
        if not dt:
            return None
        return datetime.fromisoformat(dt).astimezone(timezone.utc)

    return DebugFlag(
        enabled=bool(data.get("enabled")),
        enabled_at=_parse(data.get("enabled_at")) or _now(),
        enabled_by=data.get("enabled_by"),
        expires_at=_parse(data.get("expires_at")),
        reason=data.get("reason"),
    )


async def _read_from_redis(redis_client: aioredis.Redis) -> DebugFlag:
    raw = await redis_client.get(FLAG_KEY)
    if not raw:
        return DebugFlag()
    try:
        text = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw
        data = json.loads(text)
    except json.JSONDecodeError:
        return DebugFlag()
    return _payload_to_flag(data)


async def _write_to_redis(redis_client: aioredis.Redis, flag: DebugFlag) -> None:
    payload = json.dumps(_flag_to_payload(flag))
    if flag.enabled and flag.expires_at:
        ttl_seconds = max(int((flag.expires_at - _now()).total_seconds()), 0)
        await redis_client.set(FLAG_KEY, payload, ex=ttl_seconds or None)
    elif flag.enabled:
        await redis_client.set(FLAG_KEY, payload)
    else:
        await redis_client.delete(FLAG_KEY)


async def _read_from_file() -> DebugFlag:
    if not FLAG_PATH.exists():
        return DebugFlag()
    try:
        raw = await asyncio.to_thread(FLAG_PATH.read_text)
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return DebugFlag()
    return _payload_to_flag(data)


async def _write_to_file(flag: DebugFlag) -> None:
    if not FLAG_PATH.parent.exists():
        FLAG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not flag.enabled:
        try:
            FLAG_PATH.unlink()
        except FileNotFoundError:
            pass
        return
    payload = json.dumps(_flag_to_payload(flag))
    await asyncio.to_thread(FLAG_PATH.write_text, payload)


def _use_redis(redis_client: Optional[aioredis.Redis]) -> bool:
    return redis_client is not None


async def _read_flag(redis_client: Optional[aioredis.Redis]) -> DebugFlag:
    if _use_redis(redis_client):
        try:
            return await _read_from_redis(redis_client)  # type: ignore[arg-type]
        except Exception:
            return DebugFlag()
    return await _read_from_file()


async def _write_flag(redis_client: Optional[aioredis.Redis], flag: DebugFlag) -> None:
    if _use_redis(redis_client):
        await _write_to_redis(redis_client, flag)  # type: ignore[arg-type]
    else:
        await _write_to_file(flag)


async def set_debug_flag(
    redis_client: Optional[aioredis.Redis],
    *,
    enabled: bool,
    enabled_by: str,
    duration: Optional[timedelta] = None,
    reason: Optional[str] = None,
) -> DebugFlag:
    now = _now()
    if duration is None:
        duration = DEFAULT_DURATION
    duration = min(duration, MAX_DURATION)

    if enabled:
        expires_at = now + duration
        flag = DebugFlag(
            enabled=True,
            enabled_at=now,
            enabled_by=enabled_by,
            expires_at=expires_at,
            reason=reason,
        )
    else:
        flag = DebugFlag(
            enabled=False,
            enabled_at=now,
            enabled_by=enabled_by,
            expires_at=None,
            reason=reason,
        )

    try:
        await _write_flag(redis_client, flag)
    except Exception:
        # Never surface storage failures to callers; fall back to cached/off state.
        if enabled:
            flag = DebugFlag()
        _update_cache(flag)
        return flag

    _update_cache(flag)
    return flag


def _update_cache(flag: DebugFlag) -> None:
    global _cache, _last_refresh
    _cache = flag
    _last_refresh = _now()
    _apply_logger_override(flag.enabled and not flag.is_expired(_now()))


def _apply_logger_override(enabled: bool) -> None:
    target_level = logging.DEBUG if enabled else _base_log_level

    for module_path, attr_name in _OIDC_LOGGER_ATTRS:
        try:
            module = __import__(module_path, fromlist=[attr_name])
        except ImportError:
            continue

        logger = getattr(module, attr_name, None)
        if not isinstance(logger, logging.Logger):
            continue

        logger.setLevel(target_level)
        for handler in getattr(logger, "handlers", []):
            handler.setLevel(target_level)


async def get_debug_flag(redis_client: Optional[aioredis.Redis]) -> DebugFlag:
    now = _now()
    if now - _last_refresh < REFRESH_INTERVAL:
        if _cache.is_expired(now):
            await set_debug_flag(redis_client, enabled=False, enabled_by="system", reason="expired")
        return _cache

    async with _lock:
        if now - _last_refresh < REFRESH_INTERVAL:
            return _cache

        flag = await _read_flag(redis_client)
        if flag.is_expired(now):
            flag = await set_debug_flag(redis_client, enabled=False, enabled_by="system", reason="expired")
        else:
            _update_cache(flag)
        return flag


async def is_debug_enabled(redis_client: Optional[aioredis.Redis]) -> bool:
    flag = await get_debug_flag(redis_client)
    return flag.enabled and not flag.is_expired(_now())


def get_cached_flag() -> DebugFlag:
    return _cache


def create_oidc_trace_config(correlation_id: str) -> aiohttp.TraceConfig:
    """
    Create aiohttp TraceConfig with timing hooks for OIDC debug mode.

    Logs detailed network timing information:
    - DNS resolution time
    - TCP connection time
    - TLS handshake time
    - Time to first byte (TTFB)
    - Total request time

    Args:
        correlation_id: Request correlation ID for log tracing

    Returns:
        aiohttp.TraceConfig with debug logging hooks
    """
    trace_logger = get_logger(__name__)
    trace_config = aiohttp.TraceConfig()

    @trace_config.on_request_start.append
    async def on_request_start(session, trace_config_ctx, params):
        trace_config_ctx.start = time.perf_counter()
        trace_config_ctx.trace_request_ctx = {
            "correlation_id": correlation_id,
            "method": params.method,
            "url": str(params.url),
        }
        trace_logger.debug(
            "[OIDC TRACE] Request started",
            extra={
                "event": "trace_request_start",
                "correlation_id": correlation_id,
                "method": params.method,
                "url": str(params.url),
            },
        )

    @trace_config.on_dns_resolvehost_start.append
    async def on_dns_start(session, trace_config_ctx, params):
        trace_config_ctx.dns_start = time.perf_counter()

    @trace_config.on_dns_resolvehost_end.append
    async def on_dns_end(session, trace_config_ctx, params):
        dns_ms = int((time.perf_counter() - trace_config_ctx.dns_start) * 1000)
        trace_logger.debug(
            "[OIDC TRACE] DNS resolution completed",
            extra={
                "event": "trace_dns_resolved",
                "correlation_id": correlation_id,
                "dns_ms": dns_ms,
                "host": params.host,
            },
        )

    @trace_config.on_connection_create_start.append
    async def on_connection_start(session, trace_config_ctx, params):
        trace_config_ctx.connect_start = time.perf_counter()

    @trace_config.on_connection_create_end.append
    async def on_connection_end(session, trace_config_ctx, params):
        connect_ms = int((time.perf_counter() - trace_config_ctx.connect_start) * 1000)
        trace_logger.debug(
            "[OIDC TRACE] TCP connection established",
            extra={
                "event": "trace_connection_established",
                "correlation_id": correlation_id,
                "tcp_connect_ms": connect_ms,
            },
        )

    @trace_config.on_request_end.append
    async def on_request_end(session, trace_config_ctx, params):
        total_ms = int((time.perf_counter() - trace_config_ctx.start) * 1000)
        trace_logger.debug(
            "[OIDC TRACE] Request completed",
            extra={
                "event": "trace_request_completed",
                "correlation_id": correlation_id,
                "status": params.response.status,
                "total_ms": total_ms,
            },
        )

    @trace_config.on_request_exception.append
    async def on_request_exception(session, trace_config_ctx, params):
        total_ms = int((time.perf_counter() - trace_config_ctx.start) * 1000)
        trace_logger.debug(
            "[OIDC TRACE] Request failed with exception",
            extra={
                "event": "trace_request_exception",
                "correlation_id": correlation_id,
                "exception": params.exception.__class__.__name__,
                "total_ms": total_ms,
            },
        )

    return trace_config
