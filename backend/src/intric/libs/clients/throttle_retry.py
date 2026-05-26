"""Retry helper for HTTP throttling (429) and transient overload (503).

Microsoft Graph (SharePoint) and other upstreams throttle per app/tenant and
reply with HTTP 429 — and sometimes 503 — together with a ``Retry-After``
header telling the client how long to wait. Without honoring it a single
throttled request aborts an entire sync. This helper wraps an async request so
it backs off and retries instead.

Only throttling statuses are retried, so existing per-status handling further up
the stack (401 token refresh, 410 delta-token expiry) is left untouched — those
statuses are never retried here and propagate as before.
"""

from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import TypeVar

import aiohttp
from tenacity import (
    AsyncRetrying,
    RetryCallState,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from intric.main.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T")

# 429 = throttled, 503 = service busy. Both mean the request was rejected (not
# processed), so retrying is safe regardless of HTTP method.
RETRYABLE_STATUS_CODES = frozenset({429, 503})
DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_MAX_WAIT_SECONDS = 60.0


def _is_throttle_error(exc: BaseException) -> bool:
    return (
        isinstance(exc, aiohttp.ClientResponseError)
        and exc.status in RETRYABLE_STATUS_CODES
    )


def parse_retry_after(value: str | None) -> float | None:
    """Parse a ``Retry-After`` header into seconds.

    Graph sends an integer number of seconds, but the HTTP spec also permits an
    HTTP-date; both are handled. Returns ``None`` when the value is absent or
    unparseable.
    """
    if not value:
        return None

    value = value.strip()
    if value.isdigit():
        return float(value)

    try:
        retry_at = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None

    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=timezone.utc)
    return max((retry_at - datetime.now(timezone.utc)).total_seconds(), 0.0)


def _retry_after_seconds(retry_state: RetryCallState) -> float | None:
    outcome = retry_state.outcome
    if outcome is None:
        return None
    exc = outcome.exception()
    if not isinstance(exc, aiohttp.ClientResponseError) or not exc.headers:
        return None
    return parse_retry_after(exc.headers.get("Retry-After"))


class _RetryAfterWait:
    """Honor a server ``Retry-After`` header, else exponential backoff w/ jitter."""

    def __init__(self, max_wait: float):
        self._max_wait = max_wait
        self._fallback = wait_exponential_jitter(initial=1.0, max=max_wait)

    def __call__(self, retry_state: RetryCallState) -> float:
        retry_after = _retry_after_seconds(retry_state)
        if retry_after is not None:
            return min(retry_after, self._max_wait)
        return self._fallback(retry_state)


def _log_before_sleep(retry_state: RetryCallState) -> None:
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    status = getattr(exc, "status", "unknown")
    sleep = getattr(retry_state.next_action, "sleep", None)
    logger.warning(
        "HTTP request throttled (status=%s), retrying in %.1fs (attempt %s)",
        status,
        sleep if sleep is not None else -1.0,
        retry_state.attempt_number,
    )


async def retry_on_throttle(
    fn: Callable[[], Awaitable[T]],
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    max_wait: float = DEFAULT_MAX_WAIT_SECONDS,
) -> T:
    """Run ``fn`` and retry on throttling (429/503), honoring ``Retry-After``.

    After ``max_attempts`` the last error is re-raised, preserving the original
    failure semantics for callers.
    """
    retryer = AsyncRetrying(
        retry=retry_if_exception(_is_throttle_error),
        wait=_RetryAfterWait(max_wait=max_wait),
        stop=stop_after_attempt(max_attempts),
        before_sleep=_log_before_sleep,
        reraise=True,
    )
    return await retryer(fn)
