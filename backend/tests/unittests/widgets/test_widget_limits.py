from types import SimpleNamespace
from uuid import uuid4

import pytest

from eneo.audit.infrastructure.rate_limiting import (
    RateLimitResult,
    RateLimitServiceUnavailableError,
)
from eneo.widgets.application import widget_limits
from eneo.widgets.application.widget_limits import WidgetLimiter, network_key
from eneo.widgets.domain.exceptions import (
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


@pytest.mark.parametrize(
    ("client_ip", "key"),
    [
        ("203.0.113.5", "203.0.113.5"),
        ("2001:db8:1:2:3:4:5:6", "2001:db8:1:2::/64"),
        ("2001:db8:1:2:ffff:ffff:ffff:1", "2001:db8:1:2::/64"),
        ("::ffff:203.0.113.5", "203.0.113.5"),
        ("not-an-ip", "not-an-ip"),
        (None, "unknown"),
    ],
)
def test_network_key_counts_ipv6_per_64(client_ip, key):
    assert network_key(client_ip) == key


async def test_ip_limits_count_a_whole_ipv6_64(monkeypatch):
    counter = CountingRateLimit()
    monkeypatch.setattr(widget_limits, "check_rate_limit", counter)
    limiter = WidgetLimiter(redis_client=None, settings=_settings())
    widget = _widget(messages_per_ip_hour=2)

    # Every request from a fresh address in the same /64.
    for host in range(1, 3):
        await limiter.check_message(widget, uuid4(), f"2001:db8:1:2::{host}")
        await limiter.check_challenge(widget, f"2001:db8:1:2::{host}")
        await limiter.check_mint(widget, f"2001:db8:1:2::{host}")
    with pytest.raises(WidgetRateLimitedError) as exc:
        await limiter.check_message(widget, uuid4(), "2001:db8:1:2::3")
    assert exc.value.code == "rate_limited_ip"
    await limiter.check_challenge(widget, "2001:db8:1:2::3")
    with pytest.raises(WidgetRateLimitedError) as exc:
        await limiter.check_challenge(widget, "2001:db8:1:2::4")
    assert exc.value.code == "rate_limited_challenge"
    await limiter.check_mint(widget, "2001:db8:1:2::3")
    with pytest.raises(WidgetRateLimitedError) as exc:
        await limiter.check_mint(widget, "2001:db8:1:2::4")
    assert exc.value.code == "rate_limited_mint"
    # The next /64 is another subscriber.
    await limiter.check_message(widget, uuid4(), "2001:db8:1:3::1")
