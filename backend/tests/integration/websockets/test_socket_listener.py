"""The live-update listener on a quiet Redis channel, with Redis."""

import asyncio
import contextlib
from typing import Any

import pytest
import redis.asyncio as aioredis

from eneo.main.config import get_settings
from eneo.redis.connection import build_redis_pool_kwargs
from eneo.server.websockets.websocket_manager import WebSocketManager

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

CHANNEL = "quiet-channel"
LISTENER = "quiet-channel-listener"


async def _subscriber_ids(admin: aioredis.Redis) -> list[str]:
    clients = await admin.client_list(_type="pubsub")
    return [client["id"] for client in clients if client.get("name") == LISTENER]


async def test_the_socket_listener_survives_a_quiet_channel_longer_than_the_read_timeout(
    monkeypatch,
):
    # Every read on the shared pool has a deadline. A channel with nothing to
    # say for longer than that is normal: the listener keeps its subscription,
    # rather than reconnecting at each deadline and missing what is published
    # while it is away.
    settings = get_settings()
    kwargs = build_redis_pool_kwargs(
        settings.model_copy(update={"redis_conn_timeout": 1}), decode_responses=False
    )
    redis = aioredis.Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        client_name=LISTENER,
        **kwargs,
    )
    admin = aioredis.Redis(host=settings.redis_host, port=settings.redis_port, **kwargs)
    manager = WebSocketManager(redis=redis)
    received: list[Any] = []

    async def record(channel: str, raw_message: dict[str, Any]) -> None:  # noqa: ARG001
        received.append(raw_message["data"])

    monkeypatch.setattr(manager, "_process_redis_message", record)
    listener = asyncio.create_task(manager._listen_to_redis(CHANNEL))
    try:
        async with asyncio.timeout(5):
            while not (subscribed := await _subscriber_ids(admin)):
                await asyncio.sleep(0.05)

        await asyncio.sleep(2.5)  # longer than a read and its retry

        assert not listener.done(), listener.exception()
        assert await _subscriber_ids(admin) == subscribed
        await admin.publish(CHANNEL, b"update")
        async with asyncio.timeout(5):
            while not received:
                await asyncio.sleep(0.05)
    finally:
        listener.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await listener
        await redis.aclose()
        await admin.aclose()

    assert received == [b"update"]
