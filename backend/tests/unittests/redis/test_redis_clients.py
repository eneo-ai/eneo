"""The process's Redis clients: one owner, two pools, refused outside its lifetime."""

from unittest.mock import AsyncMock

import pytest
import redis.asyncio as aioredis

from eneo.main.config import Settings, set_settings
from eneo.main.container.container import Container
from eneo.main.exceptions import NotReadyException
from eneo.redis.clients import RedisClients, redis_clients
from eneo.worker.redis import get_redis


@pytest.fixture
def owner(test_settings):
    set_settings(test_settings)
    return RedisClients()


async def test_clients_are_refused_before_start_and_after_stop(owner):
    with pytest.raises(NotReadyException, match="not running"):
        owner.commands()
    with pytest.raises(NotReadyException, match="not running"):
        owner.subscriptions()

    owner.start()
    owner.commands()
    owner.subscriptions()
    await owner.stop()

    with pytest.raises(NotReadyException, match="not running"):
        owner.commands()
    with pytest.raises(NotReadyException, match="not running"):
        owner.subscriptions()


async def test_commands_and_subscriptions_draw_on_separate_pools(owner):
    owner.start()
    try:
        commands, subscriptions = owner.commands(), owner.subscriptions()

        assert commands is owner.commands()
        assert commands is not subscriptions
        assert commands.connection_pool is not subscriptions.connection_pool
        # Each client closes its own pool when it is closed.
        assert commands.auto_close_connection_pool
        assert subscriptions.auto_close_connection_pool
    finally:
        await owner.stop()


async def test_a_second_start_is_refused_and_the_running_clients_stay(owner):
    owner.start()
    commands = owner.commands()
    try:
        with pytest.raises(RuntimeError, match="already running"):
            owner.start()

        assert owner.commands() is commands
    finally:
        await owner.stop()


async def test_every_pool_carries_the_configured_connection(test_settings):
    set_settings(
        test_settings.model_copy(
            update={
                "redis_host": "redis.internal",
                "redis_port": 6380,
                "redis_db": 3,
                "redis_username": "eneo",
                "redis_password": "example-password",
                "redis_max_connections": 7,
                "redis_conn_timeout": 4,
            }
        )
    )
    owner = RedisClients()
    owner.start()
    try:
        for client in (owner.commands(), owner.subscriptions()):
            pool = client.connection_pool
            kwargs = pool.connection_kwargs
            assert (kwargs["host"], kwargs["port"], kwargs["db"]) == (
                "redis.internal",
                6380,
                3,
            )
            assert (kwargs["username"], kwargs["password"]) == (
                "eneo",
                "example-password",
            )
            assert kwargs["decode_responses"] is False
            # The bound applies to each pool on its own.
            assert pool.max_connections == 7
        # Without a wait of its own, a busy command pool queues for up to the
        # connect timeout; a full subscription pool refuses at once.
        commands_pool = owner.commands().connection_pool
        assert isinstance(commands_pool, aioredis.BlockingConnectionPool)
        assert commands_pool.timeout == 4
        assert not isinstance(
            owner.subscriptions().connection_pool, aioredis.BlockingConnectionPool
        )
    finally:
        await owner.stop()


async def test_a_pool_wait_of_its_own_bounds_how_long_a_busy_command_queues(
    test_settings,
):
    set_settings(
        test_settings.model_copy(
            update={
                "redis_max_connections": 7,
                "redis_conn_timeout": 4,
                "redis_pool_wait_timeout": 1,
            }
        )
    )
    owner = RedisClients()
    owner.start()
    try:
        pool = owner.commands().connection_pool
        assert isinstance(pool, aioredis.BlockingConnectionPool)
        assert pool.timeout == 1
        # Connecting keeps the connect timeout.
        assert pool.connection_kwargs["socket_connect_timeout"] == 4
    finally:
        await owner.stop()


@pytest.mark.parametrize("wait", [0, -1])
def test_a_pool_wait_that_is_not_positive_is_refused(test_settings, wait):
    with pytest.raises(SystemExit):
        Settings.model_validate(
            test_settings.model_dump() | {"redis_pool_wait_timeout": wait}
        )


async def test_unbounded_pools_stay_unbounded(test_settings):
    set_settings(test_settings.model_copy(update={"redis_max_connections": None}))
    owner = RedisClients()
    owner.start()
    try:
        for client in (owner.commands(), owner.subscriptions()):
            pool = client.connection_pool
            assert not isinstance(pool, aioredis.BlockingConnectionPool)
            assert pool.max_connections == 2**31
    finally:
        await owner.stop()


async def test_stop_closes_the_subscription_pool_when_the_command_pool_fails(owner):
    owner.start()
    commands, subscriptions = owner.commands(), owner.subscriptions()
    commands.connection_pool.disconnect = AsyncMock(
        side_effect=OSError("the command pool did not close")
    )
    subscriptions.connection_pool.disconnect = AsyncMock()

    with pytest.raises(OSError, match="did not close"):
        await owner.stop()

    subscriptions.connection_pool.disconnect.assert_awaited_once()
    with pytest.raises(NotReadyException, match="not running"):
        owner.commands()


# The process's own clients run for every test (tests/conftest.py).


async def test_every_container_shares_the_process_command_client():
    first, second = Container(), Container()

    assert first.redis_client() is redis_clients.commands()
    assert second.redis_client() is first.redis_client()
    # Services built per container hold the same process client.
    assert (
        second.api_key_rate_limiter().redis_client
        is first.api_key_rate_limiter().redis_client
    )

    await redis_clients.stop()
    with pytest.raises(NotReadyException, match="not running"):
        Container().redis_client()


async def test_get_redis_serves_commands_and_leaves_the_subscription_pool_to_listeners():
    # The audit config cache, audit sessions, job publishes and crawl markers
    # run commands through get_redis(); only pub/sub listeners (job events,
    # websockets) hold subscription connections.
    assert get_redis() is redis_clients.commands()
    assert get_redis() is Container().redis_client()
    assert redis_clients.subscriptions() is not get_redis()
