"""What a SharePoint sync keeps about items between its passes.

Failed items live on the knowledge row (``sync_failed_items``), written in the
sync's own transaction, so they commit and roll back with the documents and
the delta token they are kept for: item id -> ``FailedItem``. A delta pass
retries the items in it. A failure counts toward the cap only once
``COUNT_INTERVAL_SECONDS`` have passed since the item's last counted one, so a
burst of notifications during an outage does not use the attempts up; an item
with ``SET_ASIDE_AFTER`` counted failures is set aside so the delta token can
advance. A set-aside item is tried again by the first pass after
``SET_ASIDE_SECONDS``, or by a full sync, and stays set aside for another
cool-off when it fails again. A file whose download is refused keeps its
indexed copy until a refusal at least ``COUNT_INTERVAL_SECONDS`` after the
first one, so a passing 403 does not drop it. Above ``MAX_FAILED_ITEMS``
nothing new is recorded: a full sync
then leaves the next sync a full one.

Walk generation: a counter in Redis every full sync moves on. The delta walk
cache (also in Redis) records it, so a folder walked before the last full sync
is walked again: the full sync may have removed its files as orphans while it
was elsewhere.
"""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Optional, cast
from uuid import UUID

if TYPE_CHECKING:
    import redis.asyncio as redis

SET_ASIDE_AFTER = 3
COUNT_INTERVAL_SECONDS = 30 * 60
SET_ASIDE_SECONDS = 24 * 3600
MAX_FAILED_ITEMS = 2000
_FORMAT_VERSION = 1
# Far longer than a walk cache entry lives (7 days): a counter that expired and
# starts over at 0 cannot match an entry recorded before it expired.
_WALK_GENERATION_TTL_SECONDS = 90 * 24 * 3600


def _text(value: bytes | str) -> str:
    return value.decode("utf-8") if isinstance(value, bytes) else value


@dataclass(frozen=True)
class FailedItem:
    """An item passes could not finish, or whose download was refused.

    Times are epoch seconds.
    """

    # Failures that counted toward the cap, and when the last of them was.
    counted: int
    counted_at: int
    set_aside_at: Optional[int] = None
    # The first refusal of the item since it was last read.
    refused_at: Optional[int] = None

    def due(self, now: int) -> bool:
        """Whether a pass should try the item again now."""
        return self.set_aside_at is None or now - self.set_aside_at >= SET_ASIDE_SECONDS

    def after_failure(self, now: int) -> "FailedItem":
        """The item once a pass at ``now`` failed it again."""
        if self.set_aside_at is not None:
            return replace(self, set_aside_at=now)
        if now - self.counted_at < COUNT_INTERVAL_SECONDS:
            return self
        counted = self.counted + 1
        return replace(
            self,
            counted=counted,
            counted_at=now,
            set_aside_at=now if counted >= SET_ASIDE_AFTER else None,
        )

    def after_refusal(self, now: int) -> tuple["FailedItem", bool]:
        """The item once a pass at ``now`` was refused it, and whether that
        confirms an earlier refusal: then its indexed copy goes."""
        if self.refused_at is None:
            return replace(self, refused_at=now), False
        return self, now - self.refused_at >= COUNT_INTERVAL_SECONDS

    @staticmethod
    def uncounted() -> "FailedItem":
        """Failed in a pass whose failures counted for nobody (an outage)."""
        return FailedItem(0, 0)

    @staticmethod
    def first_failure(now: int) -> "FailedItem":
        return FailedItem.uncounted().after_failure(now)

    def encode(self) -> list[int | None]:
        return [self.counted, self.counted_at, self.set_aside_at, self.refused_at]

    @staticmethod
    def decode(value: object) -> Optional["FailedItem"]:
        if not isinstance(value, list):
            return None
        fields = cast(list[object], value) + [None] * 4
        counted, counted_at, set_aside_at, refused_at = fields[:4]
        if not isinstance(counted, int) or not isinstance(counted_at, int):
            return None
        return FailedItem(
            counted,
            counted_at,
            set_aside_at=set_aside_at if isinstance(set_aside_at, int) else None,
            refused_at=refused_at if isinstance(refused_at, int) else None,
        )


def decode_failed_items(stored: object) -> dict[str, FailedItem]:
    """The column's items; anything unreadable is left out."""
    if not isinstance(stored, dict):
        return {}
    items = cast(dict[str, object], stored).get("items")
    if not isinstance(items, dict):
        return {}
    decoded: dict[str, FailedItem] = {}
    for item_id, value in cast(dict[object, object], items).items():
        item = FailedItem.decode(value)
        if isinstance(item_id, str) and item is not None:
            decoded[item_id] = item
    return decoded


def encode_failed_items(items: Mapping[str, FailedItem]) -> dict[str, Any] | None:
    if not items:
        return None
    return {
        "version": _FORMAT_VERSION,
        "items": {item_id: item.encode() for item_id, item in items.items()},
    }


class WalkGenerations:
    def __init__(self, redis_client: "redis.Redis") -> None:
        self._redis = redis_client

    @staticmethod
    def _key(knowledge_id: UUID) -> str:
        return f"sharepoint_walk_generation:{knowledge_id}"

    async def current(self, knowledge_id: UUID) -> int:
        value = await self._redis.get(self._key(knowledge_id))
        return int(_text(value)) if value else 0

    async def advance(self, knowledge_id: UUID) -> None:
        key = self._key(knowledge_id)
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, _WALK_GENERATION_TTL_SECONDS)
            await pipe.execute()
