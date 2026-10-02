"""Live job updates: the publish side and the server-sent-events relay."""

import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.jobs import job_events
from eneo.jobs.job_models import JobInDb
from eneo.main.models import Status


def make_job(**overrides) -> JobInDb:
    base = dict(
        id=uuid4(),
        user_id=uuid4(),
        name="Avtal.pdf",
        task="upload_info_blob",
        status=Status.COMPLETE,
        result_location="/api/v1/info-blobs/5d1b9c1e-0b4e-4c21-9d7c-2f0f0a6d3e11/",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    base.update(overrides)
    return JobInDb(**base)


class FakePubSub:
    """A pubsub that hands out queued messages, then nothing."""

    def __init__(self, messages: list[dict]):
        self.messages = list(messages)
        self.subscribed: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def subscribe(self, channel: str) -> None:
        self.subscribed.append(channel)

    async def get_message(self, ignore_subscribe_messages: bool, timeout: float):
        await asyncio.sleep(0)
        return self.messages.pop(0) if self.messages else None


def make_request(disconnect_after: int):
    """A request that reports itself disconnected after N checks."""
    request = MagicMock()
    checks = {"left": disconnect_after}

    async def is_disconnected() -> bool:
        checks["left"] -= 1
        return checks["left"] < 0

    request.is_disconnected = is_disconnected
    return request


@pytest.mark.asyncio
async def test_publish_sends_the_public_job_shape_to_the_owners_channel():
    job = make_job()
    redis = MagicMock()
    redis.publish = AsyncMock()

    await job_events.publish_job_update(job, redis=redis)

    channel, payload = redis.publish.await_args.args
    assert channel == f"job_updates:{job.user_id}"
    body = json.loads(payload)
    assert body["id"] == str(job.id)
    assert body["status"] == "complete"
    assert body["result_location"] == job.result_location
    # The public shape never leaks the owner.
    assert "user_id" not in body


@pytest.mark.asyncio
async def test_publish_never_raises_when_redis_is_down():
    redis = MagicMock()
    redis.publish = AsyncMock(side_effect=ConnectionError("redis away"))

    await job_events.publish_job_update(make_job(), redis=redis)


@pytest.mark.asyncio
async def test_stream_relays_job_messages_until_the_client_leaves():
    user_id = uuid4()
    first = make_job(user_id=user_id, status=Status.IN_PROGRESS)
    second = make_job(user_id=user_id, id=first.id)
    pubsub = FakePubSub(
        [
            {"data": job_events.job_event_payload(first).encode()},
            {"data": b"not json"},
            {"data": job_events.job_event_payload(second)},
        ]
    )
    redis = MagicMock()
    redis.pubsub = MagicMock(return_value=pubsub)

    events = []
    async for event in job_events.stream_job_events(
        user_id, make_request(disconnect_after=5), redis=redis
    ):
        events.append(event)

    assert pubsub.subscribed == [f"job_updates:{user_id}"]
    assert [event.event for event in events] == ["job", "job"]
    assert [json.loads(event.data)["status"] for event in events] == [
        "in progress",
        "complete",
    ]
    assert events[0].id == str(first.id)


@pytest.mark.asyncio
async def test_stream_stops_as_soon_as_the_client_disconnects():
    pubsub = FakePubSub([{"data": job_events.job_event_payload(make_job())}])
    redis = MagicMock()
    redis.pubsub = MagicMock(return_value=pubsub)

    events = [
        event
        async for event in job_events.stream_job_events(
            uuid4(), make_request(disconnect_after=0), redis=redis
        )
    ]

    assert events == []
