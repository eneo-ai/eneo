from __future__ import annotations

from typing import Any, Awaitable, Callable, cast

from intric.audit.infrastructure.rate_limiting import (
    RateLimitConfig,
    RateLimitResult,
    RateLimitServiceUnavailableError,
    check_rate_limit as _raw_check_rate_limit,  # pyright: ignore[reportUnknownVariableType]
)
from intric.authentication.api_key_resolver import ApiKeyValidationError
from intric.authentication.auth_models import ApiKeyScopeType, ApiKeyV2InDB
from intric.main.config import get_settings
from intric.main.logging import get_logger

logger = get_logger(__name__)
CheckRateLimit = Callable[
    [Any, str, RateLimitConfig | None], Awaitable[RateLimitResult]
]
_check_rate_limit = cast(CheckRateLimit, _raw_check_rate_limit)  # pyright: ignore[reportUnknownVariableType]


class ApiKeyRateLimiter:
    def __init__(self, redis_client: Any):
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
