from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Literal, cast
from uuid import UUID

from eneo.audit.infrastructure.rate_limiting import (
    RateLimitConfig,
    RateLimitResult,
    RateLimitServiceUnavailableError,
)
from eneo.audit.infrastructure.rate_limiting import (
    check_rate_limit as _raw_check_rate_limit,  # pyright: ignore[reportUnknownVariableType]
)
from eneo.audit.infrastructure.rate_limiting import (
    read_rate_limit_count as _raw_read_rate_limit_count,  # pyright: ignore[reportUnknownVariableType]
)
from eneo.authentication.api_key_resolver import ApiKeyValidationError
from eneo.authentication.auth_models import ApiKeyScopeType, ApiKeyV2InDB
from eneo.main.config import get_settings
from eneo.main.logging import get_logger

logger = get_logger(__name__)
CheckRateLimit = Callable[
    [Any, str, RateLimitConfig | None], Awaitable[RateLimitResult]
]
_check_rate_limit = cast(CheckRateLimit, _raw_check_rate_limit)  # pyright: ignore[reportUnknownVariableType]
ReadRateLimitCount = Callable[[Any, str], Awaitable[int]]
_read_rate_limit_count = cast(ReadRateLimitCount, _raw_read_rate_limit_count)  # pyright: ignore[reportUnknownVariableType]

ApiKeyRateLimitSource = Literal["unlimited", "explicit", "scope_default"]


@dataclass(frozen=True, slots=True)
class ApiKeyRateCapacity:
    """What one authenticated key may still spend in the current window.

    `limit_source` is the discriminator: an unlimited key keeps no counter, so
    its limit, count and remaining are all absent rather than zero.
    """

    key_id: UUID
    scope_type: str
    scope_id: UUID | None
    limit_source: ApiKeyRateLimitSource
    window_seconds: int
    fail_open: bool
    limit: int | None = None
    current_count: int | None = None
    remaining: int | None = None


class ApiKeyRateLimiter:
    def __init__(self, redis_client: Any):
        super().__init__()
        self.redis_client = redis_client
        self.settings = get_settings()

    async def enforce(self, key: ApiKeyV2InDB) -> None:
        limit = self._resolve_limit(key)
        if limit is None:
            return

        if self.redis_client is None:
            if self.settings.api_key_rate_limit_fail_open:
                logger.warning("API key rate limit skipped: Redis unavailable")
                return
            raise ApiKeyValidationError(
                status_code=503,
                code="rate_limit_unavailable",
                message="Rate limiting is temporarily unavailable.",
            )

        config = RateLimitConfig(
            max_requests=limit,
            window_seconds=self.settings.api_key_rate_limit_window_seconds,
            key_prefix="rate_limit:api_key",
        )
        key_name = self._build_key(key)

        try:
            result: RateLimitResult = await _check_rate_limit(
                self.redis_client, key_name, config
            )
        except RateLimitServiceUnavailableError as exc:
            if self.settings.api_key_rate_limit_fail_open:
                logger.warning(
                    "API key rate limit check failed; allowing request",
                    extra={
                        "error": str(exc),
                        "api_key_id": str(key.id),
                        "tenant_id": str(key.tenant_id),
                    },
                )
                return
            raise ApiKeyValidationError(
                status_code=503,
                code="rate_limit_unavailable",
                message="Rate limiting is temporarily unavailable.",
            ) from exc

        if not result.allowed:
            raise ApiKeyValidationError(
                status_code=429,
                code="rate_limit_exceeded",
                message="API key rate limit exceeded.",
                headers={
                    "Retry-After": str(result.window_seconds),
                    "X-RateLimit-Limit": str(result.max_requests),
                    "X-RateLimit-Remaining": "0",
                },
            )

    async def snapshot(self, key: ApiKeyV2InDB) -> ApiKeyRateCapacity:
        """Report what this key may still spend, without spending any of it.

        A client that is about to submit a large batch needs the same limit
        `enforce` applies, so both read it from `_resolve_limit`. The counter is
        read, never incremented, and an unreadable counter is an error rather
        than an optimistic zero.
        """
        limit = self._resolve_limit(key)
        window_seconds = self.settings.api_key_rate_limit_window_seconds
        fail_open = self.settings.api_key_rate_limit_fail_open
        if limit is None:
            return ApiKeyRateCapacity(
                key_id=key.id,
                scope_type=ApiKeyScopeType(key.scope_type).value,
                scope_id=key.scope_id,
                limit_source="unlimited",
                window_seconds=window_seconds,
                fail_open=fail_open,
            )

        if self.redis_client is None:
            raise ApiKeyValidationError(
                status_code=503,
                code="rate_limit_unavailable",
                message="Rate limiting is temporarily unavailable.",
            )

        try:
            current_count = await _read_rate_limit_count(
                self.redis_client, self._build_key(key)
            )
        except RateLimitServiceUnavailableError as exc:
            raise ApiKeyValidationError(
                status_code=503,
                code="rate_limit_unavailable",
                message="Rate limiting is temporarily unavailable.",
            ) from exc

        return ApiKeyRateCapacity(
            key_id=key.id,
            scope_type=ApiKeyScopeType(key.scope_type).value,
            scope_id=key.scope_id,
            limit_source="explicit" if key.rate_limit is not None else "scope_default",
            window_seconds=window_seconds,
            fail_open=fail_open,
            limit=limit,
            current_count=current_count,
            remaining=max(0, limit - current_count),
        )

    def _resolve_limit(self, key: ApiKeyV2InDB) -> int | None:
        if key.rate_limit == -1:
            return None
        if key.rate_limit is not None:
            return int(key.rate_limit)
        return self._default_limit(ApiKeyScopeType(key.scope_type))

    def _default_limit(self, scope_type: ApiKeyScopeType) -> int:
        settings = self.settings
        if scope_type == ApiKeyScopeType.TENANT:
            return settings.api_key_rate_limit_tenant_default
        if scope_type == ApiKeyScopeType.SPACE:
            return settings.api_key_rate_limit_space_default
        if scope_type == ApiKeyScopeType.ASSISTANT:
            return settings.api_key_rate_limit_assistant_default
        return settings.api_key_rate_limit_app_default

    def _build_key(self, key: ApiKeyV2InDB) -> str:
        return f"rate_limit:api_key:{key.tenant_id}:{key.id}"
