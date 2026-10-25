"""The websocket manager's Redis listeners.

They subscribe on the process's subscription client, and every one leaves its
subscription before shutdown returns.
"""

import asyncio
from typing import Any, cast
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
import redis.asyncio as aioredis

from eneo.main.models import ChannelType
from eneo.redis.clients import redis_clients
from eneo.server.websockets.websocket_manager import (
    WebSocketManager,
    websocket_manager,
)


class _ListeningPubSub:
    """Blocks in get_message like a subscription with nothing published."""

    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.subscribed = asyncio.Event()

    async def __aenter__(self) -> "_ListeningPubSub":
        return self

    async def __aexit__(self, *exc: object) -> None:
        self.events.append("unsubscribed")

    async def subscribe(self, channel: str) -> None:
        self.subscribed.set()

    async def get_message(self, **_: object) -> None:
        await asyncio.Event().wait()


async def test_shutdown_ends_every_subscription_and_forgets_its_channels() -> None:
    events: list[str] = []
    pubsubs: list[_ListeningPubSub] = []

    def pubsub() -> _ListeningPubSub:
        pubsubs.append(_ListeningPubSub(events))
        return pubsubs[-1]

    redis = MagicMock()
    redis.pubsub.side_effect = pubsub
    manager = WebSocketManager(redis=cast(aioredis.Redis, redis))
    websocket: Any = MagicMock()
    for channel_type in (ChannelType.APP_RUN_UPDATES, ChannelType.CRAWL_RUN_UPDATES):
        manager.subscribe(websocket, channel_type=channel_type, user_id=uuid4())
    await asyncio.wait_for(
        asyncio.gather(*(p.subscribed.wait() for p in pubsubs)), timeout=1
    )

    # Cancelled listeners are the expected outcome, not a shutdown failure.
    await manager.shutdown()

    assert events == ["unsubscribed", "unsubscribed"]
    assert manager.channels == {}


async def test_the_process_manager_listens_on_the_subscription_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    listening = _ListeningPubSub(events)
    subscriptions = MagicMock()
    subscriptions.pubsub.return_value = listening
    monkeypatch.setattr(redis_clients, "subscriptions", lambda: subscriptions)

    websocket_manager.subscribe(
        cast(Any, MagicMock()),
        channel_type=ChannelType.APP_RUN_UPDATES,
        user_id=uuid4(),
    )
    await asyncio.wait_for(listening.subscribed.wait(), timeout=1)
    await websocket_manager.shutdown()

    subscriptions.pubsub.assert_called_once_with()
    assert events == ["unsubscribed"]


class _SlowCleanupPubSub(_ListeningPubSub):
    """Pauses while leaving its subscription until the test releases it."""

    def __init__(self, events: list[str]) -> None:
        super().__init__(events)
        self.cleaning_up = asyncio.Event()
        self.release = asyncio.Event()

    async def __aexit__(self, *exc: object) -> None:
        self.cleaning_up.set()
        await self.release.wait()
        self.events.append("unsubscribed")


async def test_shutdown_waits_for_a_listener_still_leaving_after_unsubscribe() -> None:
    events: list[str] = []
    pubsub = _SlowCleanupPubSub(events)
    redis = MagicMock()
    redis.pubsub.return_value = pubsub
    manager = WebSocketManager(redis=cast(aioredis.Redis, redis))
    websocket: Any = MagicMock()
    user_id = uuid4()
    manager.subscribe(
        websocket, channel_type=ChannelType.APP_RUN_UPDATES, user_id=user_id
    )
    await asyncio.wait_for(pubsub.subscribed.wait(), timeout=1)
    manager.unsubscribe(
        websocket, channel_type=ChannelType.APP_RUN_UPDATES, user_id=user_id
    )
    await asyncio.wait_for(pubsub.cleaning_up.wait(), timeout=1)

    shutdown = asyncio.create_task(manager.shutdown())
    await asyncio.sleep(0.05)
    assert not shutdown.done()

    # Shutdown leaves the cleanup in progress uninterrupted.
    pubsub.release.set()
    await asyncio.wait_for(shutdown, timeout=1)
    assert events == ["unsubscribed"]
