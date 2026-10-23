"""Redis keys the SharePoint sync tasks and the webhook service agree on.

A sync task holds ``sync_lock_key`` for the knowledge it syncs. Anyone who
wants a delta pass while that lease is held leaves ``sync_pending_key``; a
manual full sync that finds the lease held leaves ``sync_pending_full_key``.
The holder runs the pending delta passes before releasing and, once the lease
is released, queues a job for any marker still left. Whoever leaves a marker
checks the lease again afterwards and syncs itself if it was released in
between, so a marker is never left without a reader (``marker_then_recheck``).

The marker helpers never raise on a Redis failure; they log it and answer
False, and the caller serves the change itself (queues or runs a sync). As
for the queue slot, a duplicate sync is cheaper than a lost change.

A sync that takes the lease removes the markers its own pass covers, so a job
that fails before reading them does not queue itself again. The TTL only
guards against leaks and must outlive any sync, since Graph does not notify
again for a change it already reported.

``sync_queued_key`` is held from the moment a system-initiated sync job is
queued until a sync task starts, so a burst of notifications queues one job
per knowledge instead of one per notification. ``sync_catch_up_key`` and
``sync_catch_up_marker_key`` keep the periodic catch-up from queueing the
same stale source, or the same unread marker, again before its window has
passed, whatever became of the sync it queued.
"""

from typing import TYPE_CHECKING

from redis.exceptions import RedisError

from eneo.main.logging import get_logger

if TYPE_CHECKING:
    import redis.asyncio as aioredis

logger = get_logger(__name__)

SHAREPOINT_SYNC_PENDING_TTL_SECONDS = 24 * 3600
# A queued job that has not started within this window (lost delivery, or a
# worker far behind) no longer blocks another one; the stale-job reaper fails
# the old one after the same time.
SHAREPOINT_SYNC_QUEUED_TTL_SECONDS = 2 * 3600


def sync_lock_key(knowledge_id: str) -> str:
    return f"sharepoint_sync_lock:{knowledge_id}"


def sync_pending_key(knowledge_id: str) -> str:
    return f"sharepoint_sync_pending:{knowledge_id}"


def sync_pending_full_key(knowledge_id: str) -> str:
    return f"sharepoint_sync_pending_full:{knowledge_id}"


def sync_queued_key(knowledge_id: str) -> str:
    return f"sharepoint_sync_queued:{knowledge_id}"


def sync_catch_up_key(knowledge_id: str) -> str:
    return f"sharepoint_sync_catch_up:{knowledge_id}"


def sync_catch_up_marker_key(knowledge_id: str) -> str:
    return f"sharepoint_sync_catch_up_marker:{knowledge_id}"


async def claim_sync_queue_slot(
    redis_client: "aioredis.Redis", knowledge_id: str
) -> bool:
    """True when no system-initiated sync job is queued for the knowledge yet.

    Fails open: without Redis a duplicate job is cheaper than a lost change.
    """
    try:
        return bool(
            await redis_client.set(
                sync_queued_key(knowledge_id),
                "1",
                nx=True,
                ex=SHAREPOINT_SYNC_QUEUED_TTL_SECONDS,
            )
        )
    except (RedisError, OSError) as exc:
        logger.warning(
            "Could not check for a queued sync of knowledge %s (%s); queuing one",
            knowledge_id,
            type(exc).__name__,
        )
        return True


async def release_sync_queue_slot(
    redis_client: "aioredis.Redis", knowledge_id: str
) -> None:
    try:
        await redis_client.delete(sync_queued_key(knowledge_id))
    except (RedisError, OSError) as exc:
        logger.warning(
            "Could not clear the queued-sync marker of knowledge %s (%s); it "
            "expires on its own",
            knowledge_id,
            type(exc).__name__,
        )


async def leave_marker(
    redis_client: "aioredis.Redis", knowledge_id: str, *, full: bool = False
) -> bool:
    """Leave the pending marker (the full-sync one with ``full``); False when
    Redis could not take it."""
    key = sync_pending_full_key if full else sync_pending_key
    try:
        await redis_client.set(
            key(knowledge_id), "1", ex=SHAREPOINT_SYNC_PENDING_TTL_SECONDS
        )
    except (RedisError, OSError) as exc:
        logger.warning(
            "Could not leave a pending marker for knowledge %s (%s)",
            knowledge_id,
            type(exc).__name__,
        )
        return False
    return True


async def marker_then_recheck(
    redis_client: "aioredis.Redis", knowledge_id: str, *, full: bool = False
) -> bool:
    """Leave the pending marker for the lease holder; True when it will read it.

    The lease is checked after the marker is set. The holder reads the
    markers after releasing, so a marker set before the release is served by
    the holder. False (the lease was released in between, or Redis failed)
    leaves the change to the caller.
    """
    if not await leave_marker(redis_client, knowledge_id, full=full):
        return False
    try:
        held = bool(await redis_client.exists(sync_lock_key(knowledge_id)))
    except (RedisError, OSError) as exc:
        logger.warning(
            "Could not check the sync lease for knowledge %s (%s)",
            knowledge_id,
            type(exc).__name__,
        )
        return False
    if not held:
        logger.info(
            "Sync lease for knowledge %s was released while the pending marker "
            "was left",
            knowledge_id,
        )
    return held
