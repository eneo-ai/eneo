"""The deferred clear of a sync's progress, against Redis: it removes the
ended run's entry, never one a later run wrote, in one atomic step."""

from collections.abc import Callable, Coroutine
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest

from eneo.integration.domain.sync_progress import IntegrationSyncProgress
from eneo.integration.infrastructure.sharepoint_sync_progress import (
    SharePointSyncProgressStore,
    SyncProgressReporter,
    sync_progress_key,
)

# Microseconds, as datetime.now() gives them, must survive the comparison.
STARTED = datetime(2026, 10, 14, 9, 0, 0, 123456, tzinfo=timezone.utc)
LATER = STARTED + timedelta(minutes=5)


def _progress(item_id: UUID, started_at: datetime) -> IntegrationSyncProgress:
    return IntegrationSyncProgress(
        integration_knowledge_id=item_id,
        sync_type="full",
        phase="processing",
        started_at=started_at,
        updated_at=started_at,
        total=None,
        done=0,
        indexed=0,
        unchanged=0,
        skipped=0,
        deleted=0,
    )


@pytest.fixture
async def item_id(redis_client):
    item_id = uuid4()
    yield item_id
    await redis_client.delete(sync_progress_key(item_id))


async def test_the_run_that_ended_loses_its_entry(redis_client, item_id):
    store = SharePointSyncProgressStore(redis_client)
    await store.save(_progress(item_id, STARTED))

    await store.clear(item_id, started_at=STARTED)

    assert await redis_client.get(sync_progress_key(item_id)) is None


async def test_a_later_run_keeps_its_entry(redis_client, item_id):
    store = SharePointSyncProgressStore(redis_client)
    await store.save(_progress(item_id, LATER))

    await store.clear(item_id, started_at=STARTED)

    [kept] = await store.get_many([item_id])
    assert kept.started_at == LATER


class _OtherSyncWritesBetweenCommands:
    """Forwards to Redis; once the first command of the clear is answered,
    the next sync writes its entry, as it may at any moment."""

    def __init__(self, redis_client: Any, item_id: UUID) -> None:
        self._redis = redis_client
        self._item_id = item_id
        self._written = False

    def __getattr__(self, name: str) -> Any:
        command = getattr(self._redis, name)

        async def forward(*args: Any, **kwargs: Any) -> Any:
            answer = await command(*args, **kwargs)
            if not self._written:
                self._written = True
                await SharePointSyncProgressStore(self._redis).save(
                    _progress(self._item_id, LATER)
                )
            return answer

        return forward


async def test_a_run_starting_during_the_clear_keeps_its_entry(redis_client, item_id):
    """Compare and delete are one step: no later write falls between them."""
    await SharePointSyncProgressStore(redis_client).save(_progress(item_id, STARTED))
    store = SharePointSyncProgressStore(
        _OtherSyncWritesBetweenCommands(redis_client, item_id)
    )

    await store.clear(item_id, started_at=STARTED)

    [kept] = await SharePointSyncProgressStore(redis_client).get_many([item_id])
    assert kept.started_at == LATER


@pytest.mark.parametrize(
    "value", [b"{not json", b'{"phase": "processing"}', b"null", b"[]"]
)
async def test_an_entry_without_a_readable_start_is_removed(
    redis_client, item_id, value
):
    key = sync_progress_key(item_id)
    await redis_client.set(key, value)

    await SharePointSyncProgressStore(redis_client).clear(item_id, started_at=STARTED)

    assert await redis_client.get(key) is None


async def test_clearing_a_missing_entry_is_a_no_op(redis_client, item_id):
    store = SharePointSyncProgressStore(redis_client)

    await store.clear(item_id, started_at=STARTED)
    await store.clear(item_id)

    assert await redis_client.get(sync_progress_key(item_id)) is None


async def test_a_clear_without_a_run_removes_any_entry(redis_client, item_id):
    store = SharePointSyncProgressStore(redis_client)
    await store.save(_progress(item_id, LATER))

    await store.clear(item_id)

    assert await redis_client.get(sync_progress_key(item_id)) is None


class TransactionEnd:
    def __init__(self) -> None:
        self.callbacks: list[Callable[[], Coroutine[Any, Any, None]]] = []

    def __call__(self, callback: Callable[[], Coroutine[Any, Any, None]]) -> bool:
        self.callbacks.append(callback)
        return True

    async def end(self) -> None:
        for callback in self.callbacks:
            await callback()


async def test_a_sync_whose_transaction_ends_late_leaves_the_next_sync_alone(
    redis_client, item_id
):
    store = SharePointSyncProgressStore(redis_client)
    transaction = TransactionEnd()
    first = SyncProgressReporter(
        store,
        heartbeat_interval_seconds=None,
        after_transaction=transaction,
        clock=lambda: STARTED,
    )
    second = SyncProgressReporter(
        store, heartbeat_interval_seconds=None, clock=lambda: LATER
    )
    await first.begin(item_id, "full")
    await first.end()
    # The lease is released before the commit: the next sync is writing
    # when the first one's transaction ends.
    await second.begin(item_id, "delta")

    await transaction.end()

    [running] = await store.get_many([item_id])
    assert (running.sync_type, running.started_at) == ("delta", LATER)
    await second.end()
    assert await store.get_many([item_id]) == []


async def test_nested_runs_of_one_transaction_all_go_when_it_ends(
    redis_client, item_id
):
    store = SharePointSyncProgressStore(redis_client)
    transaction = TransactionEnd()
    ticks = iter(STARTED + timedelta(seconds=tick) for tick in range(100))
    reporter = SyncProgressReporter(
        store,
        heartbeat_interval_seconds=None,
        after_transaction=transaction,
        clock=lambda: next(ticks),
    )
    # A delta that falls back to a full sync, then a pending delta pass.
    await reporter.begin(item_id, "delta")
    await reporter.begin(item_id, "full")
    await reporter.end()
    await reporter.end()
    await reporter.begin(item_id, "delta")
    await reporter.end()
    assert len(await store.get_many([item_id])) == 1

    await transaction.end()

    assert await store.get_many([item_id]) == []
