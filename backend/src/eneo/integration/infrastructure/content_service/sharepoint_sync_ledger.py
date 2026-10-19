"""What a SharePoint sync keeps about items between its passes, in Redis.

Failed items: per knowledge one hash, item id -> consecutive passes that could
not finish it. A delta pass retries the items in it; one that failed
``SET_ASIDE_AFTER`` passes in a row is set aside so the delta token can advance,
and the next full sync, which tries every item, tries it again. What adds work
is written before the transaction commits (an extra retry is harmless); what
removes it only after, so a rolled-back pass keeps it.

Walk generation: a counter every full sync moves on. The delta walk cache
records it, so a folder walked before the last full sync is walked again: the
full sync may have removed its files as orphans while it was elsewhere.

Not authoritative: losing the data only costs retries a full sync makes up for.
"""

from collections.abc import Awaitable, Collection, Mapping
from typing import TYPE_CHECKING, cast
from uuid import UUID

if TYPE_CHECKING:
    import redis.asyncio as redis

SET_ASIDE_AFTER = 3
_FAILURES_TTL_SECONDS = 30 * 24 * 3600
# Far longer than a walk cache entry lives (7 days): a counter that expired and
# starts over at 0 cannot match an entry recorded before it expired.
_WALK_GENERATION_TTL_SECONDS = 90 * 24 * 3600


def _text(value: bytes | str) -> str:
    return value.decode("utf-8") if isinstance(value, bytes) else value


class SyncLedger:
    def __init__(self, redis_client: "redis.Redis") -> None:
        self._redis = redis_client

    @staticmethod
    def _failures_key(knowledge_id: UUID) -> str:
        return f"sharepoint_failed_items:{knowledge_id}"

    @staticmethod
    def _walk_generation_key(knowledge_id: UUID) -> str:
        return f"sharepoint_walk_generation:{knowledge_id}"

    async def failed_passes(self, knowledge_id: UUID) -> dict[str, int]:
        # The stubs type the asyncio client's commands as sync ones.
        raw = await cast(
            "Awaitable[dict[bytes | str, bytes | str]]",
            self._redis.hgetall(self._failures_key(knowledge_id)),  # pyright: ignore[reportUnknownMemberType]  # redis stubs incomplete
        )
        return {_text(item_id): int(_text(passes)) for item_id, passes in raw.items()}

    async def record_failed_passes(
        self, knowledge_id: UUID, passes: Mapping[str, int]
    ) -> None:
        if not passes:
            return
        key = self._failures_key(knowledge_id)
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.hset(key, mapping=dict(passes))  # pyright: ignore[reportUnknownMemberType]  # redis stubs incomplete
            pipe.expire(key, _FAILURES_TTL_SECONDS)
            await pipe.execute()

    async def forget(self, knowledge_id: UUID, item_ids: Collection[str]) -> None:
        if item_ids:
            await cast(
                "Awaitable[int]",
                self._redis.hdel(self._failures_key(knowledge_id), *item_ids),
            )

    async def walk_generation(self, knowledge_id: UUID) -> int:
        value = await self._redis.get(self._walk_generation_key(knowledge_id))
        return int(_text(value)) if value else 0

    async def advance_walk_generation(self, knowledge_id: UUID) -> None:
        key = self._walk_generation_key(knowledge_id)
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, _WALK_GENERATION_TTL_SECONDS)
            await pipe.execute()
