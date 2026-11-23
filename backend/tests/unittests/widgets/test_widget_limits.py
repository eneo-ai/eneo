import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from eneo.redis.rate_limit import (
    RateLimitResult,
    RateLimitServiceUnavailableError,
)
from eneo.widgets.application import widget_limits
from eneo.widgets.application.widget_limits import (
    VisitorTokenRevocations,
    WidgetLimiter,
    network_key,
)
from eneo.widgets.domain.exceptions import (
    VisitorTokenInvalidError,
    WidgetProtectionUnavailableError,
    WidgetRateLimitedError,
)
from eneo.widgets.domain.visitor import VisitorClaims
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
            retry_after_seconds=config.window_seconds,
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


# ---------------------------------------------------------------------------
# Token revocation on rotation
# ---------------------------------------------------------------------------


class _FakeRedis:
    def __init__(self, *, fail: bool = False) -> None:
        self.keys: dict[str, int] = {}
        self.values: dict[str, bytes] = {}
        self.fail = fail

    async def eval(self, script, numkeys, key, argument):
        if self.fail:
            raise ConnectionError("down")
        if "DEL" in script:
            # WidgetLimiter._RELEASE: delete the hold only while it is the caller's.
            owner = argument.encode() if isinstance(argument, str) else argument
            if self.values.get(key) != owner:
                return 0
            self.keys.pop(key, None)
            self.values.pop(key, None)
            return 1
        ttl = argument - int(datetime.now(timezone.utc).timestamp())
        if key in self.keys or ttl <= 0:
            return 0
        self.keys[key] = ttl
        return 1

    async def exists(self, key):
        if self.fail:
            raise ConnectionError("down")
        return 1 if key in self.keys else 0

    async def set(self, key, value, *, nx=False, ex=None):
        if self.fail:
            raise ConnectionError("down")
        if nx and key in self.keys:
            return None
        self.keys[key] = ex or 0
        self.values[key] = value
        return True

    async def delete(self, key):
        if self.fail:
            raise ConnectionError("down")
        self.values.pop(key, None)
        return 1 if self.keys.pop(key, None) is not None else 0


def _claims(
    widget: Widget, *, jti: str = "abc", expires_in: int = 900
) -> VisitorClaims:
    now = datetime.now(timezone.utc)
    return VisitorClaims(
        widget_id=widget.id,
        tenant_id=widget.tenant_id,
        visitor_id=uuid4(),
        generation=widget.token_generation,
        issued_at=now,
        expires_at=now + timedelta(seconds=expires_in),
        jti=jti,
        preview=False,
    )


async def test_a_rotated_token_is_refused_until_it_could_not_be_used_anyway():
    redis = _FakeRedis()
    revocations = VisitorTokenRevocations(redis_client=redis, settings=_settings())
    widget = _widget()
    claims = _claims(widget, expires_in=600)

    await revocations.ensure_current(widget, claims)
    await revocations.consume_for_rotation(widget, claims, grace_seconds=900)
    with pytest.raises(VisitorTokenInvalidError):
        await revocations.ensure_current(widget, claims)

    # Held for the remaining lifetime plus the grace window, not for ever.
    (ttl,) = redis.keys.values()
    assert 1_495 <= ttl <= 1_501
    # Another widget's token with the same id is unaffected.
    await revocations.ensure_current(_widget(), claims)
    with pytest.raises(VisitorTokenInvalidError):
        await revocations.consume_for_rotation(
            widget, _claims(widget, jti="old", expires_in=-1_000), grace_seconds=900
        )
    assert len(redis.keys) == 1


async def test_a_token_without_an_id_never_came_from_the_minting_service():
    revocations = VisitorTokenRevocations(
        redis_client=_FakeRedis(), settings=_settings()
    )
    widget = _widget()
    with pytest.raises(VisitorTokenInvalidError):
        await revocations.ensure_current(widget, _claims(widget, jti=""))


async def test_only_one_concurrent_rotation_can_replace_a_token():
    revocations = VisitorTokenRevocations(
        redis_client=_FakeRedis(), settings=_settings()
    )
    widget = _widget()
    claims = _claims(widget)
    results = await asyncio.gather(
        revocations.consume_for_rotation(widget, claims, grace_seconds=900),
        revocations.consume_for_rotation(widget, claims, grace_seconds=900),
        return_exceptions=True,
    )
    assert sum(result is None for result in results) == 1
    assert sum(isinstance(result, VisitorTokenInvalidError) for result in results) == 1


async def test_fail_open_still_rejects_a_known_replay_when_redis_is_read_only(
    monkeypatch,
):
    redis = _FakeRedis()
    revocations = VisitorTokenRevocations(
        redis, _settings(widget_rate_limit_fail_open=True)
    )
    widget = _widget()
    claims = _claims(widget)
    await revocations.consume_for_rotation(widget, claims, grace_seconds=900)

    async def read_only(*args):
        raise ConnectionError("writes unavailable")

    monkeypatch.setattr(redis, "eval", read_only)
    with pytest.raises(VisitorTokenInvalidError):
        await revocations.consume_for_rotation(widget, claims, grace_seconds=900)


async def test_revocation_follows_the_limiter_fail_policy():
    widget = _widget()
    claims = _claims(widget)
    closed = VisitorTokenRevocations(
        redis_client=_FakeRedis(fail=True), settings=_settings()
    )
    with pytest.raises(WidgetProtectionUnavailableError):
        await closed.ensure_current(widget, claims)
    with pytest.raises(WidgetProtectionUnavailableError):
        await closed.consume_for_rotation(widget, claims, grace_seconds=900)

    opened = VisitorTokenRevocations(
        redis_client=_FakeRedis(fail=True),
        settings=_settings(widget_rate_limit_fail_open=True),
    )
    await opened.ensure_current(widget, claims)
    await opened.consume_for_rotation(widget, claims, grace_seconds=900)


async def test_a_conversation_answers_one_follow_up_at_a_time():
    redis = _FakeRedis()
    limiter = WidgetLimiter(redis_client=redis, settings=_settings())
    widget = _widget()
    session_id = uuid4()
    owner = await limiter.hold_turn(widget, session_id)
    assert owner
    with pytest.raises(WidgetRateLimitedError) as refused:
        await limiter.hold_turn(widget, session_id)
    assert refused.value.code == "rate_limited_session"
    # Another conversation of the same widget is not held up by it.
    await limiter.hold_turn(widget, uuid4())
    await limiter.release_turn(widget, session_id, owner)
    assert await limiter.hold_turn(widget, session_id) != owner


async def test_only_the_holder_of_a_turn_releases_it():
    redis = _FakeRedis()
    limiter = WidgetLimiter(redis_client=redis, settings=_settings())
    widget = _widget()
    session_id = uuid4()
    owner = await limiter.hold_turn(widget, session_id)

    # Another marker, or none at all, leaves the hold where it is.
    await limiter.release_turn(widget, session_id, "someone-else")
    await limiter.release_turn(widget, session_id, None)
    with pytest.raises(WidgetRateLimitedError):
        await limiter.hold_turn(widget, session_id)

    await limiter.release_turn(widget, session_id, owner)
    successor = await limiter.hold_turn(widget, session_id)
    # A request that outlived its hold and comes back to release it must not
    # free the turn its successor holds.
    await limiter.release_turn(widget, session_id, owner)
    with pytest.raises(WidgetRateLimitedError):
        await limiter.hold_turn(widget, session_id)
    await limiter.release_turn(widget, session_id, successor)
    assert await limiter.hold_turn(widget, session_id)


async def test_the_turn_hold_follows_the_limiter_fail_policy():
    widget = _widget()
    closed = WidgetLimiter(redis_client=_FakeRedis(fail=True), settings=_settings())
    with pytest.raises(WidgetProtectionUnavailableError):
        await closed.hold_turn(widget, uuid4())
    opened = WidgetLimiter(
        redis_client=_FakeRedis(fail=True),
        settings=_settings(widget_rate_limit_fail_open=True),
    )
    # No hold was taken, so there is nothing to release later.
    assert await opened.hold_turn(widget, uuid4()) is None
    await opened.release_turn(widget, uuid4(), None)
    await opened.release_turn(widget, uuid4(), "abc")
