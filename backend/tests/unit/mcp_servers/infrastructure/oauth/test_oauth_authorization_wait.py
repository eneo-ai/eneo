"""The turn waits for the authorization mark the callback leaves in Redis,
consumes it, and gives up at the timeout."""

import asyncio
from uuid import uuid4

from eneo.mcp_servers.infrastructure.oauth.authorization_wait import (
    MCPOAuthAuthorizationWaiter,
    connected_key,
)


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def set(self, key, value, ex=None, nx=False):
        self.store[key] = value
        return True

    async def mget(self, keys):
        return [self.store.get(key) for key in keys]

    async def delete(self, *keys):
        for key in keys:
            self.store.pop(key, None)


async def test_waits_until_every_server_is_marked_and_consumes_the_marks():
    redis = FakeRedis()
    waiter = MCPOAuthAuthorizationWaiter(redis, timeout_seconds=5, poll_seconds=0.01)  # type: ignore[arg-type]
    user, first, second = uuid4(), uuid4(), uuid4()

    async def connect_later():
        await asyncio.sleep(0.02)
        await waiter.mark_connected(user, first)
        await asyncio.sleep(0.02)
        await waiter.mark_connected(user, second)

    asyncio.create_task(connect_later())
    connected = await waiter.wait(user, [first, second])

    assert connected == {first, second}
    assert connected_key(user, first) not in redis.store
    assert connected_key(user, second) not in redis.store


async def test_times_out_with_what_was_connected():
    redis = FakeRedis()
    waiter = MCPOAuthAuthorizationWaiter(redis, timeout_seconds=0.05, poll_seconds=0.01)  # type: ignore[arg-type]
    user, first, second = uuid4(), uuid4(), uuid4()
    await waiter.mark_connected(user, first)

    connected = await waiter.wait(user, [first, second])

    assert connected == {first}


async def test_without_redis_there_is_nothing_to_wait_for():
    waiter = MCPOAuthAuthorizationWaiter(None, timeout_seconds=5)

    assert not waiter.available
    assert await waiter.wait(uuid4(), [uuid4()]) == set()


async def test_another_users_mark_is_not_ours():
    redis = FakeRedis()
    waiter = MCPOAuthAuthorizationWaiter(redis, timeout_seconds=0.03, poll_seconds=0.01)  # type: ignore[arg-type]
    server = uuid4()
    await waiter.mark_connected(uuid4(), server)

    assert await waiter.wait(uuid4(), [server]) == set()
