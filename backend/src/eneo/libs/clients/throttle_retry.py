"""Retry helper for HTTP throttling and transient failures.

Microsoft Graph (SharePoint) and other upstreams throttle per app/tenant and
reply with HTTP 429 — and sometimes 503 — together with a ``Retry-After``
header telling the client how long to wait. Without honoring it a single
throttled request aborts an entire sync. This helper wraps an async request so
it backs off and retries instead.

Only the configured statuses are retried, so existing per-status handling
further up the stack (401 token refresh, 410 delta-token expiry) is left
untouched — those statuses are never retried here and propagate as before.
Callers whose request is safe to repeat can also retry gateway errors and
transport failures (a reset connection, a timeout, a cut-off body).
"""

import asyncio
from collections.abc import Awaitable, Callable, Collection, Iterator
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

from eneo.main.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T")

# 429 means the upstream rejected the request due to throttling; treat it as
# safe to retry for all methods. 503 is ambiguous for non-idempotent requests,
# so callers must opt in when retrying an operation that is safe to repeat.
THROTTLE_STATUS_CODES = frozenset({429})
THROTTLE_AND_OVERLOAD_STATUS_CODES = frozenset({429, 503})
# A gateway error or overload says nothing about the request itself; only for
# requests that are safe to repeat.
TRANSIENT_STATUS_CODES = frozenset({429, 502, 503, 504})
DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_MAX_BACKOFF_SECONDS = 60.0
DEFAULT_MAX_RETRY_AFTER_SECONDS = 300.0


def _is_retryable_response_error(
    exc: BaseException,
    retryable_status_codes: Collection[int],
) -> bool:
    return (
        isinstance(exc, aiohttp.ClientResponseError)
        and exc.status in retryable_status_codes
    )


def _explicit_causes(exc: BaseException) -> Iterator[BaseException]:
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__


def is_transient_transport_error(exc: BaseException) -> bool:
    """A reset or refused connection, a timeout or a body cut off mid-transfer.

    Seen through explicit wrapping (``raise ... from``). TLS and certificate
    failures are not transient and are never retried.
    """
    for cause in _explicit_causes(exc):
        if isinstance(
            cause, (aiohttp.ClientSSLError, aiohttp.ServerFingerprintMismatch)
        ):
            return False
        if isinstance(
            cause,
            (
                aiohttp.ClientConnectionError,
                aiohttp.ClientPayloadError,
                asyncio.TimeoutError,
            ),
        ):
            return True
    return False


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

    def __init__(self, max_backoff: float, max_retry_after: float):
        self._max_retry_after = max_retry_after
        self._fallback = wait_exponential_jitter(initial=1.0, max=max_backoff)

    def __call__(self, retry_state: RetryCallState) -> float:
        retry_after = _retry_after_seconds(retry_state)
        if retry_after is not None:
            return min(retry_after, self._max_retry_after)
        return self._fallback(retry_state)


def _log_before_sleep(retry_state: RetryCallState) -> None:
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    status = getattr(exc, "status", None) or type(exc).__name__
    sleep = getattr(retry_state.next_action, "sleep", None)
    logger.warning(
        "HTTP request failed transiently (%s), retrying in %.1fs (attempt %s)",
        status,
        sleep if sleep is not None else -1.0,
        retry_state.attempt_number,
    )


async def retry_on_throttle(
    fn: Callable[[], Awaitable[T]],
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    max_backoff: float = DEFAULT_MAX_BACKOFF_SECONDS,
    max_retry_after: float = DEFAULT_MAX_RETRY_AFTER_SECONDS,
    retryable_status_codes: Collection[int] = THROTTLE_STATUS_CODES,
    retry_transport_errors: bool = False,
) -> T:
    """Run ``fn`` and retry on configured HTTP statuses.

    With ``retry_transport_errors`` a transport failure is retried too; see
    ``is_transient_transport_error``. After ``max_attempts`` the last error is
    re-raised, preserving the original failure semantics for callers.
    """

    def should_retry(exc: BaseException) -> bool:
        return _is_retryable_response_error(exc, retryable_status_codes) or (
            retry_transport_errors and is_transient_transport_error(exc)
        )

    retryer = AsyncRetrying(
        retry=retry_if_exception(should_retry),
        wait=_RetryAfterWait(
            max_backoff=max_backoff,
            max_retry_after=max_retry_after,
        ),
        stop=stop_after_attempt(max_attempts),
        before_sleep=_log_before_sleep,
        reraise=True,
    )
    return await retryer(fn)
