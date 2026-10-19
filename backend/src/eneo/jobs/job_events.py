"""Live job updates for the signed-in user.

Every status change the job repository commits is published to Redis on a
per-user channel, and ``stream_job_events`` relays that channel to one
server-sent-events connection. Workers and the API share Redis, so a change a
worker writes reaches the browser without the client polling for it. The
publish is registered to run after the surrounding transaction commits: a
client that refetches on the event must see the new row.
"""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import redis.asyncio as aioredis
from fastapi import Request
from sse_starlette import ServerSentEvent

from eneo.database.database import AsyncSession
from eneo.database.transaction_callbacks import after_outer_transaction
from eneo.jobs.job_models import JobInDb, JobPublic
from eneo.main.logging import get_logger
from eneo.worker.redis import get_redis

logger = get_logger(__name__)

JOB_UPDATES_CHANNEL = "job_updates"
JOB_EVENT_NAME = "job"
# How long the relay waits for a Redis message before checking whether the
# browser is still there. Short enough that a closed tab releases its
# subscription promptly; sse-starlette's own ping keeps the connection warm.
_POLL_SECONDS = 1.0


def job_updates_channel(user_id: UUID) -> str:
    """The Redis channel carrying one user's job updates."""
    return f"{JOB_UPDATES_CHANNEL}:{user_id}"


def job_event_payload(job: JobInDb) -> str:
    """The event body: the same shape ``GET /jobs/`` returns for the job."""
    return JobPublic.model_validate(job.model_dump()).model_dump_json()


async def publish_job_update(job: JobInDb, redis: aioredis.Redis | None = None) -> None:
    """Publish one job's current state to its owner's channel; never raises."""
    try:
        client: Any = redis or get_redis()
        await client.publish(job_updates_channel(job.user_id), job_event_payload(job))
    except Exception:
        # Live updates are a courtesy on top of polling; a Redis hiccup must
        # not fail the job write that triggered it.
        logger.warning(
            "Job update not published", extra={"job_id": str(job.id)}, exc_info=True
        )


def publish_job_update_after_commit(session: AsyncSession, job: JobInDb) -> None:
    """Publish once the transaction that changed the job has committed.

    Inside a savepoint there is no outer-commit hook to attach to; the update
    is then published right away, which is early but never wrong for a
    client that only refetches.
    """
    sync_session = session.sync_session
    if sync_session.in_nested_transaction():
        asyncio.get_running_loop().create_task(publish_job_update(job))
        return
    after_outer_transaction(sync_session, on_commit=lambda: publish_job_update(job))


async def stream_job_events(
    user_id: UUID,
    request: Request,
    redis: aioredis.Redis | None = None,
) -> AsyncIterator[ServerSentEvent]:
    """Relay the user's job channel as ``event: job`` messages until the
    browser disconnects."""
    client: Any = redis or get_redis()
    pubsub = client.pubsub()
    async with pubsub:
        await pubsub.subscribe(job_updates_channel(user_id))
        while not await request.is_disconnected():
            message = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=_POLL_SECONDS
            )
            if message is None:
                continue
            data = message.get("data")
            payload = data.decode() if isinstance(data, bytes) else data
            if not isinstance(payload, str):
                continue
            try:
                job_id = json.loads(payload).get("id")
            except (ValueError, AttributeError):
                logger.warning(
                    "Malformed job update dropped", extra={"user_id": str(user_id)}
                )
                continue
            yield ServerSentEvent(data=payload, event=JOB_EVENT_NAME, id=str(job_id))
