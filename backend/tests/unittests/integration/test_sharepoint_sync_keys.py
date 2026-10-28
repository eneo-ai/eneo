"""The pending-marker steps the sync tasks and the webhook service share."""

from unittest.mock import AsyncMock, call

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from eneo.integration.infrastructure.sharepoint_sync_keys import (
    SHAREPOINT_SYNC_PENDING_TTL_SECONDS,
    leave_marker,
    marker_then_recheck,
    sync_lock_key,
    sync_pending_full_key,
    sync_pending_key,
)

KNOWLEDGE_ID = "knowledge-1"


@pytest.mark.parametrize(
    ("full", "key"),
    [
        pytest.param(False, sync_pending_key(KNOWLEDGE_ID), id="delta"),
        pytest.param(True, sync_pending_full_key(KNOWLEDGE_ID), id="full"),
    ],
)
async def test_a_marker_outlives_any_sync(full: bool, key: str):
    redis = AsyncMock()

    assert await leave_marker(redis, KNOWLEDGE_ID, full=full) is True

    redis.set.assert_awaited_once_with(key, "1", ex=SHAREPOINT_SYNC_PENDING_TTL_SECONDS)


async def test_a_marker_redis_refuses_is_reported_not_raised():
    redis = AsyncMock()
    redis.set.side_effect = RedisConnectionError("refused")

    assert await leave_marker(redis, KNOWLEDGE_ID) is False


@pytest.mark.parametrize(
    ("held", "expected"),
    [
        pytest.param(1, True, id="holder-reads-it"),
        pytest.param(0, False, id="released-in-between"),
    ],
)
async def test_the_lease_is_checked_after_the_marker_is_set(held, expected):
    redis = AsyncMock()
    steps: list[str] = []
    redis.set.side_effect = lambda *_, **__: steps.append("set")
    redis.exists.side_effect = lambda *_: steps.append("exists") or held

    assert await marker_then_recheck(redis, KNOWLEDGE_ID) is expected

    assert steps == ["set", "exists"]
    redis.exists.assert_awaited_once_with(sync_lock_key(KNOWLEDGE_ID))


@pytest.mark.parametrize("failing", ["set", "exists"])
async def test_a_recheck_redis_fails_leaves_the_change_to_the_caller(failing: str):
    redis = AsyncMock()
    redis.exists.return_value = 1
    getattr(redis, failing).side_effect = RedisConnectionError("refused")

    assert await marker_then_recheck(redis, KNOWLEDGE_ID) is False
    if failing == "set":
        redis.exists.assert_not_awaited()
    else:
        assert redis.set.await_args_list == [
            call(
                sync_pending_key(KNOWLEDGE_ID),
                "1",
                ex=SHAREPOINT_SYNC_PENDING_TTL_SECONDS,
            )
        ]
