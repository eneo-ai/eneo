# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Optional
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy.exc import SQLAlchemyError

from eneo.audit.infrastructure.rate_limiting import (
    RateLimitConfig,
    RateLimitServiceUnavailableError,
    check_rate_limit,
)
from eneo.database.database import sessionmanager
from eneo.main.config import Settings, get_settings
from eneo.main.logging import get_logger
from eneo.widgets.domain.exceptions import (
    WidgetBudgetExhaustedError,
    WidgetProtectionUnavailableError,
    WidgetRateLimitedError,
)
from eneo.widgets.domain.widget import Widget
from eneo.widgets.infrastructure.widget_usage_repo_impl import WidgetUsageRepoImpl

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
    id: UUID
    widget_id: UUID
    day: date
    reserved_tokens: int


class WidgetBudget:
    """Durable admission and exactly-once settlement, independent of Redis.

    Each operation commits separately from the streamed chat transaction. An
    interrupted process leaves its reservation charged for the admission day;
    unknown usage must never be silently refunded. Receipts contain no content.
    """

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()

    def today(self) -> date:
        return datetime.now(ZoneInfo(self.settings.widget_budget_timezone)).date()

    async def reserve(self, widget: Widget, tokens: int) -> BudgetReservation:
        assert widget.id is not None
        zone = ZoneInfo(self.settings.widget_budget_timezone)
        now = datetime.now(zone)
        midnight = datetime.combine(
            now.date() + timedelta(days=1), time.min, tzinfo=zone
        )
        reservation = BudgetReservation(uuid4(), widget.id, now.date(), max(0, tokens))
        try:
            async with sessionmanager.session() as session, session.begin():
                admitted = await WidgetUsageRepoImpl(session).reserve(
                    reservation.id,
                    widget.id,
                    reservation.day,
                    tokens=reservation.reserved_tokens,
                    limit=widget.limits.daily_token_budget,
                )
                if not admitted:
                    raise WidgetBudgetExhaustedError(
                        retry_after=max(1, int(midnight.timestamp() - now.timestamp()))
                    )
        except SQLAlchemyError as exc:
            raise WidgetProtectionUnavailableError() from exc
        return reservation

    async def release(self, reservation: BudgetReservation) -> None:
        async with sessionmanager.session() as session, session.begin():
            await WidgetUsageRepoImpl(session).finish_reservation(
                reservation.id,
                input_tokens=0,
                output_tokens=0,
                released=True,
            )

    async def settle(
        self,
        reservation: BudgetReservation,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        async with sessionmanager.session() as session, session.begin():
            await WidgetUsageRepoImpl(session).finish_reservation(
                reservation.id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )

    async def used_today(self, widget: Widget) -> int:
        assert widget.id is not None
        async with sessionmanager.session() as session, session.begin():
            return await WidgetUsageRepoImpl(session).budget_used(
                widget.id, self.today()
            )
