# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any, Optional
from uuid import UUID
from zoneinfo import ZoneInfo

import redis.exceptions

from eneo.audit.infrastructure.rate_limiting import (
    RateLimitConfig,
    RateLimitServiceUnavailableError,
    check_rate_limit,
)
from eneo.main.config import Settings, get_settings
from eneo.main.logging import get_logger
from eneo.widgets.domain.exceptions import (
    WidgetBudgetExhaustedError,
    WidgetProtectionUnavailableError,
    WidgetRateLimitedError,
)
from eneo.widgets.domain.widget import Widget

logger = get_logger(__name__)

VISITOR_WINDOW_SECONDS = 600
IP_WINDOW_SECONDS = 3600
CHALLENGE_WINDOW_SECONDS = 60


def _widget_key(widget: Widget, *parts: str) -> str:
    return ":".join(["widget", str(widget.id), *parts])


class WidgetLimiter:
    """Request-count limits on the anonymous widget surface.

    Keys are per widget so one widget cannot starve another; the atomic
    INCR+EXPIRE primitive is shared with API-key rate limiting.
    """

    def __init__(self, redis_client: Any, settings: Optional[Settings] = None) -> None:
        self.redis = redis_client
        self.settings = settings or get_settings()

    async def check_challenge(self, widget: Widget, client_ip: Optional[str]) -> None:
        await self._check(
            _widget_key(widget, "challenge", client_ip or "unknown"),
            max_requests=self.settings.widget_challenge_rate_limit_per_minute,
            window_seconds=CHALLENGE_WINDOW_SECONDS,
            code="rate_limited_challenge",
            message="Too many challenge requests. Try again shortly.",
        )

    async def check_mint(self, widget: Widget, client_ip: Optional[str]) -> None:
        await self._check(
            _widget_key(widget, "mint", client_ip or "unknown"),
            max_requests=self.settings.widget_challenge_rate_limit_per_minute,
            window_seconds=CHALLENGE_WINDOW_SECONDS,
            code="rate_limited_mint",
            message="Too many session requests. Try again shortly.",
        )

    async def check_message(
        self, widget: Widget, visitor_id: UUID, client_ip: Optional[str]
    ) -> None:
        await self._check(
            _widget_key(widget, "visitor", str(visitor_id)),
            max_requests=widget.limits.messages_per_visitor_10min,
            window_seconds=VISITOR_WINDOW_SECONDS,
            code="rate_limited_visitor",
            message="You are sending messages too quickly. Please wait a moment.",
        )
        # IP limits are a backstop only: CGNAT and campus networks share IPs.
        if client_ip:
            await self._check(
                _widget_key(widget, "ip", client_ip),
                max_requests=widget.limits.messages_per_ip_hour,
                window_seconds=IP_WINDOW_SECONDS,
                code="rate_limited_ip",
                message="Too many messages from this network. Please try again later.",
            )

    async def _check(
        self,
        key: str,
        *,
        max_requests: int,
        window_seconds: int,
        code: str,
        message: str,
    ) -> None:
        config = RateLimitConfig(
            max_requests=max_requests,
            window_seconds=window_seconds,
            key_prefix="widget",
        )
        try:
            result = await check_rate_limit(self.redis, key, config)
        except RateLimitServiceUnavailableError as exc:
            if self.settings.widget_rate_limit_fail_open:
                logger.warning(
                    "Widget rate limit skipped: Redis unavailable",
                    extra={"key": key, "error": str(exc)},
                )
                return
            raise WidgetProtectionUnavailableError() from exc
        if not result.allowed:
            raise WidgetRateLimitedError(
                code, retry_after=result.window_seconds, message=message
            )


@dataclass(frozen=True)
class BudgetReservation:
    key: str
    reserved_tokens: int


class WidgetBudget:
    """Daily token budget per widget, reserve-then-settle.

    The reservation is added before the model call so concurrent requests
    cannot collectively overshoot the cap; the actual usage replaces it once
    the answer is complete. Days roll over at local midnight.
    """

    def __init__(self, redis_client: Any, settings: Optional[Settings] = None) -> None:
        self.redis = redis_client
        self.settings = settings or get_settings()

    def _day_key(self, widget: Widget) -> tuple[str, int]:
        zone = ZoneInfo(self.settings.widget_budget_timezone)
        now = datetime.now(zone)
        midnight = datetime.combine(
            now.date() + timedelta(days=1), time.min, tzinfo=zone
        )
        ttl = max(1, int((midnight - now).total_seconds()))
        return _widget_key(widget, "budget", now.date().isoformat()), ttl

    async def reserve(self, widget: Widget, tokens: int) -> BudgetReservation:
        key, ttl = self._day_key(widget)
        tokens = max(0, tokens)
        try:
            async with self.redis.pipeline(transaction=True) as pipe:
                pipe.incrby(key, tokens)
                pipe.expire(key, ttl)
                results = await pipe.execute()
            total = int(results[0])
            if total > widget.limits.daily_token_budget:
                await self.redis.decrby(key, tokens)
                raise WidgetBudgetExhaustedError(retry_after=ttl)
        except redis.exceptions.RedisError as exc:
            if self.settings.widget_rate_limit_fail_open:
                logger.warning(
                    "Widget budget check skipped: Redis unavailable",
                    extra={"key": key, "error": str(exc)},
                )
                return BudgetReservation(key=key, reserved_tokens=0)
            raise WidgetProtectionUnavailableError() from exc
        return BudgetReservation(key=key, reserved_tokens=tokens)

    async def settle(self, reservation: BudgetReservation, actual_tokens: int) -> None:
        delta = max(0, actual_tokens) - reservation.reserved_tokens
        if delta == 0:
            return
        try:
            await self.redis.incrby(reservation.key, delta)
        except redis.exceptions.RedisError as exc:
            # The reservation stays as the charged amount; never block an
            # answer that has already been produced.
            logger.warning(
                "Widget budget settlement failed",
                extra={"key": reservation.key, "delta": delta, "error": str(exc)},
            )

    async def used_today(self, widget: Widget) -> int:
        key, _ = self._day_key(widget)
        try:
            value = await self.redis.get(key)
        except redis.exceptions.RedisError:
            return 0
        return int(value or 0)
