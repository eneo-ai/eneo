"""Live progress of running SharePoint syncs, kept in Redis.

One JSON entry per integration knowledge item, written by the worker while a
sync runs and removed once the sync's database transaction has ended. Progress
is advisory: a Redis failure is logged and never fails a sync or the page that
reads it.
"""

import asyncio
import time
from collections import deque
from collections.abc import Callable, Coroutine, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import partial
from typing import Any, Literal, cast
from uuid import UUID

import redis.asyncio as redis
from pydantic import TypeAdapter, ValidationError
from redis.exceptions import RedisError

from eneo.integration.domain.skip_reasons import SkippedDetail
from eneo.integration.domain.sync_progress import (
    IntegrationSyncProgress,
    IntegrationSyncProgressFile,
)
from eneo.integration.infrastructure.content_service.types import SyncStats
from eneo.main.logging import get_logger

logger = get_logger(__name__)

SyncType = Literal["full", "delta"]
SyncPhase = Literal["discovering", "processing", "finishing"]
FileOutcome = Literal["indexed", "unchanged", "skipped"]

# Same window as SHAREPOINT_SYNC_LOCK_TTL_SECONDS: an entry outlives a crashed
# worker no longer than its lock. Every write renews it, and a running sync
# writes at least once per heartbeat, however long one file or the finishing
# phase takes.
SYNC_PROGRESS_TTL_SECONDS = 300
HEARTBEAT_INTERVAL_SECONDS = 60.0
# A finished sync's entry waits for its transaction to end; should that never
# be seen, it lapses after this instead of the full TTL.
FINISHED_TTL_SECONDS = 120
MIN_WRITE_INTERVAL_SECONDS = 1.0
RECENT_FILES_LIMIT = 8

# Runs the callback once the sync's database transaction has committed or rolled
# back. Returns False when that cannot be arranged.
AfterTransaction = Callable[[Callable[[], Coroutine[Any, Any, None]]], bool]


def sync_progress_key(integration_knowledge_id: UUID) -> str:
    return f"sharepoint_sync_progress:{integration_knowledge_id}"


# Removes KEYS[1] unless it holds the entry of a run other than the one that
# started at ARGV[1]. ARGV[1] is serialized like the entry's own started_at.
CLEAR_RUN_SCRIPT = """
local value = redis.call('GET', KEYS[1])
if not value then
    return 0
end
local ok, entry = pcall(cjson.decode, value)
if ok and type(entry) == 'table' and type(entry['started_at']) == 'string'
        and entry['started_at'] ~= ARGV[1] then
    return 0
end
return redis.call('DEL', KEYS[1])
"""
_STARTED_AT: TypeAdapter[datetime] = TypeAdapter(datetime)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SharePointSyncProgressStore:
    def __init__(self, redis_client: "redis.Redis") -> None:
        super().__init__()
        self.redis_client = redis_client

    async def save(self, progress: IntegrationSyncProgress) -> None:
        await self.redis_client.set(
            sync_progress_key(progress.integration_knowledge_id),
            progress.model_dump_json(),
            ex=SYNC_PROGRESS_TTL_SECONDS,
        )

    async def clear(
        self, integration_knowledge_id: UUID, *, started_at: datetime | None = None
    ) -> None:
        """Remove the entry; with ``started_at``, only the entry of that run.

        The run's entry is compared and removed in one step in Redis, so a
        run that has started meanwhile keeps its entry. An entry without a
        readable start is removed.
        """
        key = sync_progress_key(integration_knowledge_id)
        if started_at is None:
            await self.redis_client.delete(key)
            return
        # Redis EVAL runs the Lua script atomically; it is not Python's eval.
        await cast(Any, self.redis_client).eval(
            CLEAR_RUN_SCRIPT, 1, key, _STARTED_AT.dump_python(started_at, mode="json")
        )

    async def expire(self, integration_knowledge_id: UUID, seconds: int) -> None:
        await self.redis_client.expire(
            sync_progress_key(integration_knowledge_id), seconds
        )

    async def get_many(
        self, integration_knowledge_ids: Sequence[UUID]
    ) -> list[IntegrationSyncProgress]:
        """Progress of the given items that are syncing now, in one round trip."""
        if not integration_knowledge_ids:
            return []
        keys = [sync_progress_key(item_id) for item_id in integration_knowledge_ids]
        try:
            values: list[bytes | str | None] = await self.redis_client.mget(keys)
        except RedisError as exc:
            logger.warning("Could not read SharePoint sync progress: %s", exc)
            return []
        progress: list[IntegrationSyncProgress] = []
        for value in values:
            if value is None:
                continue
            try:
                progress.append(IntegrationSyncProgress.model_validate_json(value))
            except ValidationError:
                logger.warning("Ignoring a malformed SharePoint sync progress entry")
        return progress


_FinishedFile = tuple[str, FileOutcome, SkippedDetail | None]


def _skip_fields(detail: SkippedDetail | None) -> dict[str, Any]:
    if detail is None:
        return {}
    return {
        "reason": detail["reason"],
        "code": detail.get("code"),
        "params": detail.get("params", {}),
        "retry": detail.get("retry", False),
    }


def _recent_files() -> deque[_FinishedFile]:
    return deque(maxlen=RECENT_FILES_LIMIT)


@dataclass
class _Run:
    integration_knowledge_id: UUID
    sync_type: SyncType
    started_at: datetime
    phase: SyncPhase = "discovering"
    total: int | None = None
    indexed: int = 0
    unchanged: int = 0
    skipped: int = 0
    deleted: int = 0
    skip_reasons: int = 0
    current: str | None = None
    recent: deque[_FinishedFile] = field(default_factory=_recent_files)


class SyncProgressReporter:
    """Publishes the progress of one sync at a time from its ``SyncStats``.

    Writes happen when a sync begins, on every phase change, otherwise at most
    once per ``min_interval_seconds``, and while a sync runs at least once per
    ``heartbeat_interval_seconds`` (None disables the heartbeat); every call
    still updates the state the next write publishes. Without a store, or for
    a sync without an item id, every call is a no-op.

    With ``after_transaction`` a finished sync's entry stays until the sync's
    transaction ends, so the page never shows no sync while the item's rows
    still hold what was there before it.
    """

    def __init__(
        self,
        store: SharePointSyncProgressStore | None,
        *,
        min_interval_seconds: float = MIN_WRITE_INTERVAL_SECONDS,
        heartbeat_interval_seconds: float | None = HEARTBEAT_INTERVAL_SECONDS,
        after_transaction: AfterTransaction | None = None,
        clock: Callable[[], datetime] = _utcnow,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__()
        self._store = store
        self._min_interval_seconds = min_interval_seconds
        self._heartbeat_interval_seconds = heartbeat_interval_seconds
        self._after_transaction = after_transaction
        self._clock = clock
        self._monotonic = monotonic
        self._run: _Run | None = None
        self._last_write: float | None = None
        self._heartbeat: asyncio.Task[None] | None = None

    async def begin(
        self, integration_knowledge_id: UUID | None, sync_type: SyncType
    ) -> None:
        """Start reporting; a sync started inside another replaces it."""
        if self._store is None or integration_knowledge_id is None:
            self._run = None
            return
        self._run = _Run(
            integration_knowledge_id=integration_knowledge_id,
            sync_type=sync_type,
            started_at=self._clock(),
        )
        await self._write()
        # One heartbeat serves nested runs: it writes whichever run is current.
        if self._heartbeat is None and self._heartbeat_interval_seconds is not None:
            self._heartbeat = asyncio.create_task(
                self._beat(self._heartbeat_interval_seconds)
            )

    def add_total(self, count: int) -> None:
        """Count files or pages a listing returned for processing."""
        if self._run is not None:
            self._run.total = (self._run.total or 0) + count

    async def set_phase(self, phase: SyncPhase, stats: SyncStats) -> None:
        run = self._run
        if run is None:
            return
        if run.phase == phase:
            await self.update(stats)
            return
        run.phase = phase
        self._apply(run, stats, current=None)
        await self._write()

    async def update(self, stats: SyncStats, *, current: str | None = None) -> None:
        """Record ``stats`` and the file or page about to be handled.

        What changed in ``stats`` since the previous call is the outcome of the
        item handled in between. Pass ``current=None`` for folders and deleted
        items so they never enter the feed.
        """
        run = self._run
        if run is None:
            return
        self._apply(run, stats, current=current)
        # There is no trailing write: a slow item that starts within the
        # interval after a write is published by the next heartbeat at the
        # latest.
        if (
            self._last_write is not None
            and self._monotonic() - self._last_write < self._min_interval_seconds
        ):
            return
        await self._write()

    async def end(self) -> None:
        """Stop reporting and remove the entry: once the sync's transaction has
        ended when ``after_transaction`` arranges it, otherwise now.

        The heartbeat is stopped first so no write can re-create the entry.
        """
        run, self._run = self._run, None
        await self._stop_heartbeat()
        if run is None or self._store is None:
            return
        store, item_id = self._store, run.integration_knowledge_id
        # A later sync of the item may already be writing when the deferred
        # clear runs (the lease is released before the commit), so only this
        # run's entry is removed.
        deferred_clear = partial(self._clear, item_id, started_at=run.started_at)
        try:
            deferred = self._after_transaction is not None and self._after_transaction(
                deferred_clear
            )
        except Exception as exc:  # noqa: BLE001 - progress must never fail a sync
            logger.warning(
                "Could not wait for the transaction of integration knowledge %s: %s",
                item_id,
                exc,
            )
            deferred = False
        if deferred:
            try:
                await store.expire(item_id, FINISHED_TTL_SECONDS)
            except Exception as exc:  # noqa: BLE001 - progress must never fail a sync
                logger.warning(
                    "Could not shorten sync progress of integration knowledge %s: %s",
                    item_id,
                    exc,
                )
            return
        await self._clear(item_id, started_at=run.started_at)

    async def _clear(
        self, integration_knowledge_id: UUID, *, started_at: datetime
    ) -> None:
        if self._store is None:
            return
        try:
            await self._store.clear(integration_knowledge_id, started_at=started_at)
        except Exception as exc:  # noqa: BLE001 - progress must never fail a sync
            logger.warning(
                "Could not clear sync progress of integration knowledge %s: %s",
                integration_knowledge_id,
                exc,
            )

    async def _beat(self, interval: float) -> None:
        while True:
            await asyncio.sleep(interval)
            await self._write()

    async def _stop_heartbeat(self) -> None:
        heartbeat, self._heartbeat = self._heartbeat, None
        if heartbeat is None:
            return
        heartbeat.cancel()
        # wait() rather than awaiting the task: the heartbeat's cancellation
        # must not be mistaken for a cancellation of the sync itself.
        await asyncio.wait([heartbeat])

    @staticmethod
    def _apply(run: _Run, stats: SyncStats, *, current: str | None) -> None:
        indexed = stats["files_processed"] + stats["pages_processed"]
        details = stats["skipped_details"]
        if run.current is not None:
            outcome: FileOutcome | None = None
            detail: SkippedDetail | None = None
            if stats["skipped_items"] > run.skipped:
                outcome = "skipped"
                # A skip that also fails to remove the old copy adds a second
                # detail; the first one says why the file was skipped.
                if new_details := details[run.skip_reasons :]:
                    detail = new_details[0]
            elif indexed > run.indexed:
                outcome = "indexed"
            elif stats["unchanged_items"] > run.unchanged:
                outcome = "unchanged"
            if outcome is not None:
                run.recent.appendleft((run.current, outcome, detail))
        run.indexed = indexed
        run.unchanged = stats["unchanged_items"]
        run.skipped = stats["skipped_items"]
        run.deleted = stats["files_deleted"]
        run.skip_reasons = len(details)
        run.current = current or None

    async def _write(self) -> None:
        run = self._run
        if run is None or self._store is None:
            return
        self._last_write = self._monotonic()
        done = run.indexed + run.unchanged + run.skipped
        try:
            progress = IntegrationSyncProgress(
                integration_knowledge_id=run.integration_knowledge_id,
                sync_type=run.sync_type,
                phase=run.phase,
                started_at=run.started_at,
                updated_at=self._clock(),
                # A file whose cleanup also fails is counted as skipped twice.
                total=None if run.total is None else max(run.total, done),
                done=done,
                indexed=run.indexed,
                unchanged=run.unchanged,
                skipped=run.skipped,
                deleted=run.deleted,
                current=run.current,
                recent=[
                    IntegrationSyncProgressFile(
                        name=name, outcome=outcome, **_skip_fields(detail)
                    )
                    for name, outcome, detail in run.recent
                ],
            )
            await self._store.save(progress)
        except Exception as exc:  # noqa: BLE001 - progress must never fail a sync
            logger.warning(
                "Could not write sync progress of integration knowledge %s: %s",
                run.integration_knowledge_id,
                exc,
            )
