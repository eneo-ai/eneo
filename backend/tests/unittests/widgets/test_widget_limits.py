from types import SimpleNamespace
from uuid import uuid4

import pytest
import redis.exceptions

from eneo.audit.infrastructure.rate_limiting import (
    RateLimitResult,
    RateLimitServiceUnavailableError,
)
from eneo.widgets.application import widget_limits
from eneo.widgets.application.widget_limits import WidgetBudget, WidgetLimiter
from eneo.widgets.domain.exceptions import (
    WidgetBudgetExhaustedError,
    WidgetProtectionUnavailableError,
    WidgetRateLimitedError,
)
from eneo.widgets.domain.widget import Widget, WidgetLimits


def _settings(**overrides) -> SimpleNamespace:
    base = dict(
        widget_challenge_rate_limit_per_minute=3,
        widget_rate_limit_fail_open=False,
        widget_budget_timezone="Europe/Stockholm",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _widget(**limits) -> Widget:
    widget = Widget.create(
        tenant_id=uuid4(), space_id=uuid4(), target_id=uuid4(), name="w"
    )
    return widget.model_copy(update={"id": uuid4(), "limits": WidgetLimits(**limits)})


class CountingRateLimit:
    """Stands in for check_rate_limit: counts calls per key within the test."""

    def __init__(self, *, fail: bool = False) -> None:
        self.counts: dict[str, int] = {}
        self.fail = fail

    async def __call__(self, redis_client, key, config):
        if self.fail:
            raise RateLimitServiceUnavailableError(RuntimeError("down"))
        self.counts[key] = self.counts.get(key, 0) + 1
        return RateLimitResult(
            allowed=self.counts[key] <= config.max_requests,
            current_count=self.counts[key],
            max_requests=config.max_requests,
            window_seconds=config.window_seconds,
        )


async def test_message_limits_are_per_visitor_and_per_ip(monkeypatch):
    counter = CountingRateLimit()
    monkeypatch.setattr(widget_limits, "check_rate_limit", counter)
    limiter = WidgetLimiter(redis_client=None, settings=_settings())
    widget = _widget(messages_per_visitor_10min=2, messages_per_ip_hour=3)
    visitor = uuid4()

    await limiter.check_message(widget, visitor, "203.0.113.5")
    await limiter.check_message(widget, visitor, "203.0.113.5")
    with pytest.raises(WidgetRateLimitedError) as exc:
        await limiter.check_message(widget, visitor, "203.0.113.5")
    assert exc.value.code == "rate_limited_visitor"
    assert exc.value.headers == {"Retry-After": "600"}

    # Another visitor on the same IP is still allowed once, then the IP cap hits.
    await limiter.check_message(widget, uuid4(), "203.0.113.5")
    with pytest.raises(WidgetRateLimitedError) as exc:
        await limiter.check_message(widget, uuid4(), "203.0.113.5")
    assert exc.value.code == "rate_limited_ip"
    assert exc.value.headers == {"Retry-After": "3600"}

    # Keys are namespaced per widget, so a second widget starts fresh.
    await limiter.check_message(_widget(), visitor, "203.0.113.5")


async def test_challenge_limit_and_fail_closed(monkeypatch):
    counter = CountingRateLimit()
    monkeypatch.setattr(widget_limits, "check_rate_limit", counter)
    limiter = WidgetLimiter(redis_client=None, settings=_settings())
    widget = _widget()
    for _ in range(3):
        await limiter.check_challenge(widget, "198.51.100.1")
    with pytest.raises(WidgetRateLimitedError) as exc:
        await limiter.check_challenge(widget, "198.51.100.1")
    assert exc.value.code == "rate_limited_challenge"

    monkeypatch.setattr(widget_limits, "check_rate_limit", CountingRateLimit(fail=True))
    with pytest.raises(WidgetProtectionUnavailableError):
        await limiter.check_mint(widget, None)
    open_limiter = WidgetLimiter(
        redis_client=None, settings=_settings(widget_rate_limit_fail_open=True)
    )
    await open_limiter.check_mint(widget, None)


class FakeBudgetRedis:
    def __init__(self, *, fail: bool = False) -> None:
        self.values: dict[str, int] = {}
        self.ttls: dict[str, int] = {}
        self.fail = fail

    def pipeline(self, transaction=True):
        return _Pipeline(self)

    async def incrby(self, key, amount):
        if self.fail:
            raise redis.exceptions.ConnectionError("down")
        self.values[key] = self.values.get(key, 0) + amount
        return self.values[key]

    async def decrby(self, key, amount):
        return await self.incrby(key, -amount)

    async def get(self, key):
        return self.values.get(key)


class _Pipeline:
    def __init__(self, parent: FakeBudgetRedis) -> None:
        self.parent = parent
        self.ops: list = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def incrby(self, key, amount):
        self.ops.append(("incrby", key, amount))

    def expire(self, key, ttl):
        self.ops.append(("expire", key, ttl))

    async def execute(self):
        results = []
        for op, key, arg in self.ops:
            if op == "incrby":
                results.append(await self.parent.incrby(key, arg))
            else:
                self.parent.ttls[key] = arg
                results.append(True)
        return results


async def test_budget_reserve_then_settle():
    fake = FakeBudgetRedis()
    budget = WidgetBudget(redis_client=fake, settings=_settings())
    widget = _widget(daily_token_budget=10_000)

    reservation = await budget.reserve(widget, 6_000)
    assert await budget.used_today(widget) == 6_000
    assert 0 < fake.ttls[reservation.key] <= 24 * 3600

    await budget.settle(reservation, 2_500)
    assert await budget.used_today(widget) == 2_500

    second = await budget.reserve(widget, 7_000)
    assert await budget.used_today(widget) == 9_500
    with pytest.raises(WidgetBudgetExhaustedError) as exc:
        await budget.reserve(widget, 1_000)
    assert "Retry-After" in (exc.value.headers or {})
    # The failed reservation is rolled back.
    assert await budget.used_today(widget) == 9_500
    await budget.settle(second, 7_000)


async def test_budget_redis_loss_fails_closed_or_open():
    widget = _widget()
    with pytest.raises(WidgetProtectionUnavailableError):
        await WidgetBudget(FakeBudgetRedis(fail=True), settings=_settings()).reserve(
            widget, 10
        )
    reservation = await WidgetBudget(
        FakeBudgetRedis(fail=True), settings=_settings(widget_rate_limit_fail_open=True)
    ).reserve(widget, 10)
    assert reservation.reserved_tokens == 0
