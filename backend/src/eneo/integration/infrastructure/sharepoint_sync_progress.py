"""Live progress of running SharePoint syncs, kept in Redis.

One JSON entry per integration knowledge item, written by the worker while a
sync runs and removed when it ends. Progress is advisory: a Redis failure is
logged and never fails a sync or the page that reads it.
"""

import time
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

import redis.asyncio as redis
from pydantic import ValidationError
from redis.exceptions import RedisError

from eneo.integration.infrastructure.content_service.types import SyncStats
from eneo.integration.presentation.models import (
    IntegrationSyncProgress,
    IntegrationSyncProgressFile,
)
from eneo.main.logging import get_logger

logger = get_logger(__name__)

SyncType = Literal["full", "delta"]
SyncPhase = Literal["discovering", "processing", "finishing"]
FileOutcome = Literal["indexed", "unchanged", "skipped"]

# Same window as SHAREPOINT_SYNC_LOCK_TTL_SECONDS: an entry outlives a crashed
# worker no longer than its lock. Every write renews it.
# KNOWN GAP: unlike the lock there is no watchdog, so one file that takes longer
# than the TTL lets the entry lapse until the next file finishes.
SYNC_PROGRESS_TTL_SECONDS = 300
MIN_WRITE_INTERVAL_SECONDS = 1.0
RECENT_FILES_LIMIT = 8


def sync_progress_key(integration_knowledge_id: UUID) -> str:
    return f"sharepoint_sync_progress:{integration_knowledge_id}"


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

    async def clear(self, integration_knowledge_id: UUID) -> None:
        await self.redis_client.delete(sync_progress_key(integration_knowledge_id))

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


_FinishedFile = tuple[str, FileOutcome, str | None]


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

    Writes happen when a sync begins, on every phase change, and otherwise at
    most once per ``min_interval_seconds``; every call still updates the state
    the next write publishes. Without a store, or for a sync without an item
    id, every call is a no-op.
    """

    def __init__(
        self,
        store: SharePointSyncProgressStore | None,
        *,
        min_interval_seconds: float = MIN_WRITE_INTERVAL_SECONDS,
        clock: Callable[[], datetime] = _utcnow,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__()
        self._store = store
        self._min_interval_seconds = min_interval_seconds
        self._clock = clock
        self._monotonic = monotonic
        self._run: _Run | None = None
        self._last_write: float | None = None

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
        # KNOWN GAP: there is no trailing write, so a slow item that starts
        # within the interval after a write is published only once it is done.
        if (
            self._last_write is not None
            and self._monotonic() - self._last_write < self._min_interval_seconds
        ):
            return
        await self._write()

    async def end(self) -> None:
        run, self._run = self._run, None
        if run is None or self._store is None:
            return
        try:
            await self._store.clear(run.integration_knowledge_id)
        except Exception as exc:  # noqa: BLE001 - progress must never fail a sync
            logger.warning(
                "Could not clear sync progress of integration knowledge %s: %s",
                run.integration_knowledge_id,
                exc,
            )

    @staticmethod
    def _apply(run: _Run, stats: SyncStats, *, current: str | None) -> None:
        indexed = stats["files_processed"] + stats["pages_processed"]
        details = stats["skipped_details"]
        if run.current is not None:
            outcome: FileOutcome | None = None
            reason: str | None = None
            if stats["skipped_items"] > run.skipped:
                outcome = "skipped"
                # A skip that also fails to remove the old copy adds a second
                # detail; the first one says why the file was skipped.
                if new_details := details[run.skip_reasons :]:
                    reason = new_details[0].get("reason")
            elif indexed > run.indexed:
                outcome = "indexed"
            elif stats["unchanged_items"] > run.unchanged:
                outcome = "unchanged"
            if outcome is not None:
                run.recent.appendleft((run.current, outcome, reason))
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
                        name=name, outcome=outcome, reason=reason
                    )
                    for name, outcome, reason in run.recent
                ],
            )
            await self._store.save(progress)
        except Exception as exc:  # noqa: BLE001 - progress must never fail a sync
            logger.warning(
                "Could not write sync progress of integration knowledge %s: %s",
                run.integration_knowledge_id,
                exc,
            )
