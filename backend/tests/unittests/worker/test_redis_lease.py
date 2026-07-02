"""Unit tests for redis_lease — the self-renewing, owner-checked Redis lock."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eneo.worker.redis.lease import redis_lease

_REFRESH = "eneo.worker.redis.lease.LuaScripts.refresh_leader_lock"
_RELEASE = "eneo.worker.redis.lease.LuaScripts.release_leader_lock"


def _redis(set_result):
    redis_mock = MagicMock()
    redis_mock.set = AsyncMock(return_value=set_result)
    return redis_mock


@pytest.mark.asyncio
async def test_yields_true_when_acquired_and_releases_on_exit():
    redis_mock = _redis(set_result=True)

    with (
        patch(_REFRESH, new=AsyncMock(return_value=True)),
        patch(_RELEASE, new=AsyncMock(return_value=True)) as release,
    ):
        async with redis_lease(
            redis_mock, "lock:k", ttl_seconds=300, renew_interval_seconds=999
        ) as acquired:
            assert acquired is True

    # SET NX EX with a unique owner token (not a constant value).
    args, kwargs = redis_mock.set.call_args
    assert args[0] == "lock:k"
    assert args[1] != "locked" and len(args[1]) > 0
    assert kwargs == {"nx": True, "ex": 300}

    # Owner-checked release happens exactly once on exit, for this key + owner.
    release.assert_awaited_once()
    assert release.await_args.args[1] == "lock:k"
    assert release.await_args.args[2] == args[1]


@pytest.mark.asyncio
async def test_yields_false_when_held_by_another_and_does_not_release():
    redis_mock = _redis(set_result=None)

    with (
        patch(_REFRESH, new=AsyncMock()) as refresh,
        patch(_RELEASE, new=AsyncMock()) as release,
    ):
        async with redis_lease(redis_mock, "lock:k") as acquired:
            assert acquired is False

    # Never acquired → no watchdog refresh and no release of someone else's lock.
    refresh.assert_not_awaited()
    release.assert_not_awaited()


@pytest.mark.asyncio
async def test_watchdog_refreshes_ttl_while_held():
    redis_mock = _redis(set_result=True)

    with (
        patch(_REFRESH, new=AsyncMock(return_value=True)) as refresh,
        patch(_RELEASE, new=AsyncMock(return_value=True)),
    ):
        async with redis_lease(
            redis_mock, "lock:k", ttl_seconds=300, renew_interval_seconds=0.01
        ) as acquired:
            assert acquired is True
            await asyncio.sleep(0.05)

    assert refresh.await_count >= 1
    assert refresh.await_args.args[1] == "lock:k"


@pytest.mark.asyncio
async def test_releases_even_when_body_raises():
    redis_mock = _redis(set_result=True)

    with (
        patch(_REFRESH, new=AsyncMock(return_value=True)),
        patch(_RELEASE, new=AsyncMock(return_value=True)) as release,
    ):
        with pytest.raises(ValueError, match="boom"):
            async with redis_lease(redis_mock, "lock:k", renew_interval_seconds=999):
                raise ValueError("boom")

    release.assert_awaited_once()


@pytest.mark.asyncio
async def test_watchdog_cancels_body_when_lease_lost():
    redis_mock = _redis(set_result=True)

    async def run_with_lease():
        async with redis_lease(
            redis_mock, "lock:k", ttl_seconds=300, renew_interval_seconds=0.01
        ) as acquired:
            assert acquired is True
            await asyncio.sleep(10)

    # refresh returns False → lease lost; watchdog must cancel protected work.
    with (
        patch(_REFRESH, new=AsyncMock(return_value=False)) as refresh,
        patch(_RELEASE, new=AsyncMock(return_value=False)) as release,
    ):
        task = asyncio.create_task(run_with_lease())
        with pytest.raises(asyncio.CancelledError):
            await task

    # Stopped after detecting the loss rather than spinning on every interval.
    assert refresh.await_count == 1
    release.assert_awaited_once()


@pytest.mark.asyncio
async def test_watchdog_cancels_body_when_ownership_unconfirmed_for_ttl():
    redis_mock = _redis(set_result=True)

    async def run_with_lease():
        async with redis_lease(
            redis_mock, "lock:k", ttl_seconds=300, renew_interval_seconds=0.01
        ) as acquired:
            assert acquired is True
            await asyncio.sleep(10)

    with (
        patch(_REFRESH, new=AsyncMock(side_effect=RuntimeError("redis down"))),
        patch(_RELEASE, new=AsyncMock(return_value=False)) as release,
        patch("eneo.worker.redis.lease.monotonic", side_effect=[0.0, 301.0]),
    ):
        task = asyncio.create_task(run_with_lease())
        with pytest.raises(asyncio.CancelledError):
            await task

    release.assert_awaited_once()
