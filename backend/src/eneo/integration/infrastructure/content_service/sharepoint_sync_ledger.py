"""What a SharePoint sync keeps about items between its passes, in Redis.

Failed items: per knowledge one hash, item id -> ``FailedItem``. A delta pass
retries the items in it. A failure counts toward the cap only once
``COUNT_INTERVAL_SECONDS`` have passed since the item's last counted one, so a
burst of notifications during an outage does not use the attempts up; an item
with ``SET_ASIDE_AFTER`` counted failures is set aside so the delta token can
advance. A set-aside item is tried again by the first pass after
``SET_ASIDE_SECONDS``, or by a full sync, and stays set aside for another
cool-off when it fails again. What adds work is written before the
transaction commits (an extra retry is harmless); what removes it only after,
so a rolled-back pass keeps it.

Walk generation: a counter every full sync moves on. The delta walk cache
records it, so a folder walked before the last full sync is walked again: the
full sync may have removed its files as orphans while it was elsewhere.

Not authoritative: losing the data only costs retries a full sync makes up for.
"""

from collections.abc import Awaitable, Collection, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional, cast
from uuid import UUID

if TYPE_CHECKING:
    import redis.asyncio as redis

SET_ASIDE_AFTER = 3
COUNT_INTERVAL_SECONDS = 30 * 60
SET_ASIDE_SECONDS = 24 * 3600
_FAILURES_TTL_SECONDS = 30 * 24 * 3600
# Far longer than a walk cache entry lives (7 days): a counter that expired and
# starts over at 0 cannot match an entry recorded before it expired.
_WALK_GENERATION_TTL_SECONDS = 90 * 24 * 3600


def _text(value: bytes | str) -> str:
    return value.decode("utf-8") if isinstance(value, bytes) else value


@dataclass(frozen=True)
class FailedItem:
    """An item passes could not finish. Times are epoch seconds."""

    # Failures that counted toward the cap, and when the last of them was.
    counted: int
    counted_at: int
    set_aside_at: Optional[int] = None

    def due(self, now: int) -> bool:
        """Whether a pass should try the item again now."""
        return self.set_aside_at is None or now - self.set_aside_at >= SET_ASIDE_SECONDS

    def after_failure(self, now: int) -> "FailedItem":
        """The item once a pass at ``now`` failed it again."""
        if self.set_aside_at is not None:
            return FailedItem(self.counted, self.counted_at, set_aside_at=now)
        if now - self.counted_at < COUNT_INTERVAL_SECONDS:
            return self
        return FailedItem.counted_now(self.counted + 1, now)

    @staticmethod
    def uncounted() -> "FailedItem":
        """Failed in a pass whose failures counted for nobody (an outage)."""
        return FailedItem(0, 0)

    @staticmethod
    def first_failure(now: int) -> "FailedItem":
        return FailedItem.counted_now(1, now)

    @staticmethod
    def counted_now(counted: int, now: int) -> "FailedItem":
        set_aside_at = now if counted >= SET_ASIDE_AFTER else None
        return FailedItem(counted, now, set_aside_at=set_aside_at)

    def encode(self) -> str:
        set_aside_at = "" if self.set_aside_at is None else str(self.set_aside_at)
        return f"{self.counted}:{self.counted_at}:{set_aside_at}"

    @staticmethod
    def decode(value: str) -> "FailedItem":
        counted, _, rest = value.partition(":")
        counted_at, _, set_aside_at = rest.partition(":")
        return FailedItem(
            int(counted),
            int(counted_at or 0),
            set_aside_at=int(set_aside_at) if set_aside_at else None,
        )


class SyncLedger:
    def __init__(self, redis_client: "redis.Redis") -> None:
        self._redis = redis_client

    @staticmethod
    def _failures_key(knowledge_id: UUID) -> str:
        return f"sharepoint_failed_items:{knowledge_id}"

    @staticmethod
    def _walk_generation_key(knowledge_id: UUID) -> str:
        return f"sharepoint_walk_generation:{knowledge_id}"

    async def failed_items(self, knowledge_id: UUID) -> dict[str, FailedItem]:
        # The stubs type the asyncio client's commands as sync ones.
        raw = await cast(
            "Awaitable[dict[bytes | str, bytes | str]]",
            self._redis.hgetall(self._failures_key(knowledge_id)),  # pyright: ignore[reportUnknownMemberType]  # redis stubs incomplete
        )
        return {
            _text(item_id): FailedItem.decode(_text(value))
            for item_id, value in raw.items()
        }

    async def record_failed_items(
        self, knowledge_id: UUID, items: Mapping[str, FailedItem]
    ) -> None:
        if not items:
            return
        key = self._failures_key(knowledge_id)
        mapping = {item_id: item.encode() for item_id, item in items.items()}
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.hset(key, mapping=mapping)  # pyright: ignore[reportUnknownMemberType]  # redis stubs incomplete
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
