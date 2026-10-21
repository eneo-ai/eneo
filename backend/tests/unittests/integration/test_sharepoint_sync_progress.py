"""Live sync progress in Redis: what is written, how often, and that it never fails a sync."""

import asyncio
import itertools
import json
from collections.abc import Callable, Coroutine
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from eneo.integration.infrastructure.content_service.types import SyncStats
from eneo.integration.infrastructure.sharepoint_sync_progress import (
    CLEAR_RUN_SCRIPT,
    FINISHED_TTL_SECONDS,
    SYNC_PROGRESS_TTL_SECONDS,
    SharePointSyncProgressStore,
    SyncProgressReporter,
    sync_progress_key,
)

STARTED = datetime(2026, 10, 14, 9, 0, tzinfo=timezone.utc)
LATER = datetime(2026, 10, 14, 9, 5, tzinfo=timezone.utc)


class FakeMonotonic:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def _stats(
    skipped_details: list[tuple[str, str]] | None = None, **counts: int
) -> SyncStats:
    stats: SyncStats = {
        "files_processed": 0,
        "files_deleted": 0,
        "out_of_scope_deleted": 0,
        "folders_processed": 0,
        "pages_processed": 0,
        "unchanged_items": 0,
        "skipped_items": 0,
        "skipped_details": [
            {"file": file, "reason": reason} for file, reason in skipped_details or []
        ],
    }
    stats.update(counts)  # type: ignore[typeddict-item]
    return stats


def _saved(redis_client: AsyncMock) -> list[dict[str, object]]:
    return [json.loads(call.args[1]) for call in redis_client.set.await_args_list]


@pytest.fixture
def redis_client() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def monotonic() -> FakeMonotonic:
    return FakeMonotonic()


@pytest.fixture
def reporter(redis_client: AsyncMock, monotonic: FakeMonotonic) -> SyncProgressReporter:
    clock = iter([STARTED, STARTED, LATER, LATER, LATER])
    return SyncProgressReporter(
        SharePointSyncProgressStore(redis_client),
        heartbeat_interval_seconds=None,
        clock=lambda: next(clock),
        monotonic=monotonic,
    )


async def test_progress_is_published_per_item_with_the_listed_total(
    reporter, redis_client
):
    item_id = uuid4()

    await reporter.begin(item_id, "full")
    reporter.add_total(7)
    await reporter.set_phase(
        "processing",
        _stats(
            files_processed=2,
            pages_processed=1,
            unchanged_items=3,
            skipped_items=1,
            files_deleted=4,
        ),
    )

    key = sync_progress_key(item_id)
    assert key == f"sharepoint_sync_progress:{item_id}"
    assert [call.args[0] for call in redis_client.set.await_args_list] == [key, key]
    assert all(
        call.kwargs == {"ex": SYNC_PROGRESS_TTL_SECONDS}
        for call in redis_client.set.await_args_list
    )
    assert _saved(redis_client) == [
        {
            "integration_knowledge_id": str(item_id),
            "sync_type": "full",
            "phase": "discovering",
            "started_at": "2026-10-14T09:00:00Z",
            "updated_at": "2026-10-14T09:00:00Z",
            "total": None,
            "done": 0,
            "indexed": 0,
            "unchanged": 0,
            "skipped": 0,
            "deleted": 0,
            "current": None,
            "recent": [],
        },
        {
            "integration_knowledge_id": str(item_id),
            "sync_type": "full",
            "phase": "processing",
            "started_at": "2026-10-14T09:00:00Z",
            "updated_at": "2026-10-14T09:05:00Z",
            "total": 7,
            "done": 7,
            "indexed": 3,
            "unchanged": 3,
            "skipped": 1,
            "deleted": 4,
            "current": None,
            "recent": [],
        },
    ]


async def test_updates_are_throttled_but_phase_changes_are_written_at_once(
    reporter, redis_client, monotonic
):
    await reporter.begin(uuid4(), "delta")

    await reporter.update(_stats(files_processed=1))
    monotonic.now += 0.5
    await reporter.update(_stats(files_processed=2))
    await reporter.set_phase("processing", _stats(files_processed=3))
    await reporter.set_phase("processing", _stats(files_processed=4))
    monotonic.now += 1.0
    await reporter.update(_stats(files_processed=5))

    assert [(p["phase"], p["indexed"]) for p in _saved(redis_client)] == [
        ("discovering", 0),
        ("processing", 3),
        ("processing", 5),
    ]


@pytest.mark.parametrize(
    ("listed", "stats", "expected_total"),
    [
        ([], _stats(files_processed=4), None),
        ([3, 2], _stats(files_processed=4), 5),
        ([0], _stats(), 0),
        # A file whose cleanup fails is counted as skipped twice.
        ([2], _stats(files_processed=1, skipped_items=2), 3),
    ],
)
async def test_total_is_null_until_listed_and_never_below_done(
    reporter, redis_client, listed, stats, expected_total
):
    await reporter.begin(uuid4(), "full")
    for count in listed:
        reporter.add_total(count)
    await reporter.set_phase("finishing", stats)

    assert _saved(redis_client)[-1]["total"] == expected_total


@pytest.fixture
def feed_reporter(
    redis_client: AsyncMock, monotonic: FakeMonotonic
) -> SyncProgressReporter:
    return SyncProgressReporter(
        SharePointSyncProgressStore(redis_client),
        heartbeat_interval_seconds=None,
        clock=lambda: STARTED,
        monotonic=monotonic,
    )


def _feed(files):
    return [
        {
            "name": entry["name"],
            "outcome": entry["outcome"],
            "reason": entry.get("reason"),
        }
        for entry in files
    ]


async def test_each_finished_file_enters_the_feed_with_its_outcome(
    feed_reporter, redis_client
):
    unsupported = ("c.zip", "Unsupported file type")
    no_text = ("f.pdf", "No text found")
    cleanup_failed = ("f.pdf", "Could not remove unextractable: 503")
    await feed_reporter.begin(uuid4(), "full")
    await feed_reporter.set_phase("processing", _stats())

    await feed_reporter.update(_stats(), current="a.docx")
    await feed_reporter.update(_stats(files_processed=1), current="b.docx")
    # A folder is never current, so what its subtree adds goes to no file.
    await feed_reporter.update(_stats(files_processed=1, unchanged_items=1))
    await feed_reporter.update(
        _stats(files_processed=4, unchanged_items=1), current="c.zip"
    )
    await feed_reporter.update(
        _stats([unsupported], files_processed=4, unchanged_items=1, skipped_items=1),
        current="d.docx",
    )
    # d.docx is skipped without a recorded reason.
    await feed_reporter.update(
        _stats([unsupported], files_processed=4, unchanged_items=1, skipped_items=2),
        current="e.docx",
    )
    # e.docx counts nothing, like an item already handled.
    await feed_reporter.update(
        _stats([unsupported], files_processed=4, unchanged_items=1, skipped_items=2),
        current="f.pdf",
    )
    await feed_reporter.update(
        _stats(
            [unsupported, no_text, cleanup_failed],
            files_processed=4,
            unchanged_items=1,
            skipped_items=4,
        ),
        current="Start.aspx",
    )
    await feed_reporter.set_phase(
        "finishing",
        _stats(
            [unsupported, no_text, cleanup_failed],
            files_processed=4,
            pages_processed=1,
            unchanged_items=1,
            skipped_items=4,
        ),
    )

    finishing = _saved(redis_client)[-1]
    assert finishing["phase"] == "finishing"
    assert finishing["current"] is None
    assert _feed(finishing["recent"]) == [
        {"name": "Start.aspx", "outcome": "indexed", "reason": None},
        {"name": "f.pdf", "outcome": "skipped", "reason": "No text found"},
        {"name": "d.docx", "outcome": "skipped", "reason": None},
        {"name": "c.zip", "outcome": "skipped", "reason": "Unsupported file type"},
        {"name": "b.docx", "outcome": "unchanged", "reason": None},
        {"name": "a.docx", "outcome": "indexed", "reason": None},
    ]


async def test_the_file_being_handled_is_published_with_the_files_before_it(
    feed_reporter, redis_client, monotonic
):
    await feed_reporter.begin(uuid4(), "delta")
    await feed_reporter.set_phase("processing", _stats())
    await feed_reporter.update(_stats(), current="a.docx")
    monotonic.now += 1.0

    await feed_reporter.update(_stats(unchanged_items=1), current="b.docx")

    processing = _saved(redis_client)[-1]
    assert (processing["phase"], processing["current"]) == ("processing", "b.docx")
    assert _feed(processing["recent"]) == [
        {"name": "a.docx", "outcome": "unchanged", "reason": None}
    ]


async def test_feed_keeps_the_newest_eight_files_first(feed_reporter, redis_client):
    await feed_reporter.begin(uuid4(), "full")
    await feed_reporter.set_phase("processing", _stats())
    for done in range(10):
        await feed_reporter.update(_stats(files_processed=done), current=f"{done}.docx")
    await feed_reporter.set_phase("finishing", _stats(files_processed=10))

    assert [f["name"] for f in _saved(redis_client)[-1]["recent"]] == [
        f"{done}.docx" for done in range(9, 1, -1)
    ]


async def test_end_removes_the_entry_and_stops_reporting(reporter, redis_client):
    item_id = uuid4()
    await reporter.begin(item_id, "full")

    await reporter.end()
    await reporter.set_phase("finishing", _stats(files_processed=1))
    await reporter.end()

    assert _cleared_runs(redis_client) == [
        (sync_progress_key(item_id), _saved(redis_client)[0]["started_at"])
    ]
    assert len(_saved(redis_client)) == 1


class TransactionEnd:
    """Stands in for the content service's hook on the sync's transaction."""

    def __init__(self, *, available: bool = True) -> None:
        self.available = available
        self.callbacks: list[Callable[[], Coroutine[Any, Any, None]]] = []

    def __call__(self, callback: Callable[[], Coroutine[Any, Any, None]]) -> bool:
        if self.available:
            self.callbacks.append(callback)
        return self.available

    async def end(self) -> None:
        for callback in self.callbacks:
            await callback()


def _cleared_runs(redis_client: AsyncMock) -> list[tuple[str, str]]:
    """(key, started_at) of each clear that removes one run's entry only.

    Redis compares and removes atomically; what it then keeps is tested
    against Redis in tests/integration/test_sharepoint_sync_progress_redis.py.
    """
    assert all(
        call.args[:2] == (CLEAR_RUN_SCRIPT, 1)
        for call in redis_client.eval.await_args_list
    )
    return [call.args[2:] for call in redis_client.eval.await_args_list]


async def test_a_finished_sync_stays_visible_until_its_transaction_ends(
    redis_client, monotonic
):
    transaction = TransactionEnd()
    reporter = SyncProgressReporter(
        SharePointSyncProgressStore(redis_client),
        heartbeat_interval_seconds=None,
        after_transaction=transaction,
        clock=lambda: STARTED,
        monotonic=monotonic,
    )
    item_id = uuid4()
    await reporter.begin(item_id, "full")
    await reporter.set_phase("finishing", _stats(files_processed=3))

    await reporter.end()

    key = sync_progress_key(item_id)
    redis_client.delete.assert_not_awaited()
    redis_client.eval.assert_not_awaited()
    # Should the transaction's end never be seen, the entry lapses soon.
    redis_client.expire.assert_awaited_once_with(key, FINISHED_TTL_SECONDS)
    assert _saved(redis_client)[-1]["phase"] == "finishing"

    await transaction.end()

    # This run's entry only, named by its start as the entry stores it.
    assert _cleared_runs(redis_client) == [
        (key, _saved(redis_client)[-1]["started_at"])
    ]
    redis_client.delete.assert_not_awaited()


async def test_the_transaction_end_clears_the_run_that_ended_not_a_later_one(
    redis_client, monotonic
):
    transaction = TransactionEnd()
    clock = iter([STARTED, STARTED, LATER, LATER])
    item_id = uuid4()
    first = SyncProgressReporter(
        SharePointSyncProgressStore(redis_client),
        heartbeat_interval_seconds=None,
        after_transaction=transaction,
        clock=lambda: next(clock),
        monotonic=monotonic,
    )
    await first.begin(item_id, "full")
    await first.end()
    # The lease is released before the commit, so the next sync may already
    # be writing when the first sync's transaction ends.
    second = SyncProgressReporter(
        SharePointSyncProgressStore(redis_client),
        heartbeat_interval_seconds=None,
        clock=lambda: next(clock),
        monotonic=monotonic,
    )
    await second.begin(item_id, "delta")

    await transaction.end()

    assert _cleared_runs(redis_client) == [
        (sync_progress_key(item_id), "2026-10-14T09:00:00Z")
    ]
    assert _saved(redis_client)[-1]["started_at"] == "2026-10-14T09:05:00Z"
    redis_client.delete.assert_not_awaited()


async def test_nested_syncs_defer_one_clear_per_run_of_the_transaction(
    redis_client, monotonic
):
    transaction = TransactionEnd()
    ticks = (STARTED + timedelta(seconds=tick) for tick in itertools.count())
    reporter = SyncProgressReporter(
        SharePointSyncProgressStore(redis_client),
        heartbeat_interval_seconds=None,
        after_transaction=transaction,
        clock=lambda: next(ticks),
        monotonic=monotonic,
    )
    item_id = uuid4()
    # A delta that falls back to a full sync, then a pending delta pass in the
    # same transaction.
    await reporter.begin(item_id, "delta")
    await reporter.begin(item_id, "full")
    await reporter.end()
    await reporter.end()
    await reporter.begin(item_id, "delta")
    await reporter.end()

    assert len(transaction.callbacks) == 2
    await transaction.end()

    # One clear per run that ended (each write also takes a tick): the full
    # sync started at :02, the pending pass at :04.
    key = sync_progress_key(item_id)
    assert _cleared_runs(redis_client) == [
        (key, "2026-10-14T09:00:02Z"),
        (key, "2026-10-14T09:00:04Z"),
    ]


async def test_without_a_transaction_hook_the_entry_goes_at_once(
    redis_client, monotonic
):
    reporter = SyncProgressReporter(
        SharePointSyncProgressStore(redis_client),
        heartbeat_interval_seconds=None,
        after_transaction=TransactionEnd(available=False),
        monotonic=monotonic,
    )
    item_id = uuid4()
    await reporter.begin(item_id, "full")

    await reporter.end()

    # Only this run's entry: another sync of the item may have started since.
    assert _cleared_runs(redis_client) == [
        (sync_progress_key(item_id), _saved(redis_client)[-1]["started_at"])
    ]
    redis_client.delete.assert_not_awaited()
    redis_client.expire.assert_not_awaited()


async def test_a_failing_transaction_hook_clears_at_once(redis_client, monotonic):
    def unavailable(callback: Callable[[], Coroutine[Any, Any, None]]) -> bool:
        raise RuntimeError("session already closed")

    reporter = SyncProgressReporter(
        SharePointSyncProgressStore(redis_client),
        heartbeat_interval_seconds=None,
        after_transaction=unavailable,
        monotonic=monotonic,
    )
    item_id = uuid4()
    await reporter.begin(item_id, "full")

    await reporter.end()

    assert _cleared_runs(redis_client) == [
        (sync_progress_key(item_id), _saved(redis_client)[-1]["started_at"])
    ]
    redis_client.expire.assert_not_awaited()


async def test_a_run_is_cleared_by_its_start_as_the_entry_stores_it(redis_client):
    started = datetime(2026, 10, 14, 9, 0, 1, 123456, tzinfo=timezone.utc)
    reporter = SyncProgressReporter(
        SharePointSyncProgressStore(redis_client),
        heartbeat_interval_seconds=None,
        after_transaction=(transaction := TransactionEnd()),
        clock=lambda: started,
    )
    item_id = uuid4()
    await reporter.begin(item_id, "delta")
    await reporter.end()

    await transaction.end()

    assert _cleared_runs(redis_client) == [
        (sync_progress_key(item_id), _saved(redis_client)[-1]["started_at"])
    ]


async def test_heartbeat_rewrites_the_state_while_one_file_takes_long(redis_client):
    written = asyncio.Event()

    async def set_entry(key, value, ex):
        written.set()

    redis_client.set.side_effect = set_entry
    reporter = SyncProgressReporter(
        SharePointSyncProgressStore(redis_client), heartbeat_interval_seconds=0.01
    )
    await reporter.begin(uuid4(), "full")
    await reporter.set_phase("processing", _stats())
    # Throttled: the file being handled is not written yet.
    await reporter.update(_stats(), current="big.pdf")
    assert _saved(redis_client)[-1]["current"] is None
    written.clear()

    await asyncio.wait_for(written.wait(), timeout=1)

    heartbeat = _saved(redis_client)[-1]
    assert (heartbeat["phase"], heartbeat["current"]) == ("processing", "big.pdf")
    assert all(
        call.kwargs == {"ex": SYNC_PROGRESS_TTL_SECONDS}
        for call in redis_client.set.await_args_list
    )
    await reporter.end()
    writes = redis_client.set.await_count
    await asyncio.sleep(0.03)
    assert redis_client.set.await_count == writes


async def test_a_heartbeat_write_in_flight_never_lands_after_the_clear(redis_client):
    entries: dict[str, str] = {}
    in_flight = asyncio.Event()
    release = asyncio.Event()

    async def set_entry(key, value, ex):
        if redis_client.set.await_count > 1:
            in_flight.set()
            await release.wait()
        entries[key] = value

    async def clear_entry(script, keys, key, started_at):
        entries.pop(key, None)
        # Whatever write is still in flight lands now.
        release.set()
        await asyncio.sleep(0)

    redis_client.set.side_effect = set_entry
    redis_client.eval.side_effect = clear_entry
    reporter = SyncProgressReporter(
        SharePointSyncProgressStore(redis_client), heartbeat_interval_seconds=0.01
    )
    await reporter.begin(uuid4(), "full")
    await asyncio.wait_for(in_flight.wait(), timeout=1)

    await reporter.end()
    await asyncio.sleep(0.03)

    assert entries == {}
    redis_client.eval.assert_awaited_once()


async def test_end_clears_only_after_a_heartbeat_write_already_sent_has_landed(
    redis_client,
):
    """Cancelling the heartbeat cannot take back a command already sent;
    end() waits for the heartbeat to finish before it clears."""
    entries: dict[str, str] = {}
    in_flight = asyncio.Event()

    async def set_entry(key, value, ex):
        if redis_client.set.await_count == 1:
            entries[key] = value
            return
        in_flight.set()
        try:
            await asyncio.sleep(3600)
        finally:
            entries[key] = value

    async def clear_entry(script, keys, key, started_at):
        entries.pop(key, None)

    redis_client.set.side_effect = set_entry
    redis_client.eval.side_effect = clear_entry
    reporter = SyncProgressReporter(
        SharePointSyncProgressStore(redis_client), heartbeat_interval_seconds=0.01
    )
    await reporter.begin(uuid4(), "full")
    await asyncio.wait_for(in_flight.wait(), timeout=1)

    await reporter.end()
    await asyncio.sleep(0.03)

    assert entries == {}


async def test_a_nested_run_reuses_the_running_heartbeat(redis_client):
    """A delta that falls back to a full sync starts no second heartbeat."""
    reporter = SyncProgressReporter(
        SharePointSyncProgressStore(redis_client), heartbeat_interval_seconds=3600
    )
    item_id = uuid4()
    before = asyncio.all_tasks()

    await reporter.begin(item_id, "delta")
    heartbeat = reporter._heartbeat
    await reporter.begin(item_id, "full")

    assert heartbeat is not None and reporter._heartbeat is heartbeat
    assert asyncio.all_tasks() - before == {heartbeat}
    await reporter.end()
    await reporter.end()
    assert heartbeat.done()


async def test_redis_failures_never_reach_the_sync_or_the_reader(redis_client):
    redis_client.set.side_effect = RedisConnectionError("redis down")
    redis_client.eval.side_effect = RedisConnectionError("redis down")
    redis_client.mget.side_effect = RedisConnectionError("redis down")
    store = SharePointSyncProgressStore(redis_client)
    reporter = SyncProgressReporter(store)

    await reporter.begin(uuid4(), "full")
    await reporter.set_phase("processing", _stats(files_processed=1))
    await reporter.end()

    assert await store.get_many([uuid4()]) == []
    assert redis_client.set.await_count == 2
    redis_client.eval.assert_awaited_once()

    redis_client.expire.side_effect = RedisConnectionError("redis down")
    transaction = TransactionEnd()
    deferred = SyncProgressReporter(store, after_transaction=transaction)
    await deferred.begin(uuid4(), "delta")
    await deferred.end()
    await transaction.end()

    redis_client.expire.assert_awaited_once()
    assert redis_client.eval.await_count == 2


async def test_reader_returns_running_items_in_one_round_trip(redis_client):
    running, idle, broken = uuid4(), uuid4(), uuid4()
    entry = {
        "integration_knowledge_id": str(running),
        "sync_type": "delta",
        "phase": "processing",
        "started_at": "2026-10-14T09:00:00Z",
        "updated_at": "2026-10-14T09:00:01Z",
        "total": None,
        "done": 2,
        "indexed": 1,
        "unchanged": 1,
        "skipped": 0,
        "deleted": 0,
    }
    redis_client.mget.return_value = [json.dumps(entry).encode(), None, b"{not json"]
    store = SharePointSyncProgressStore(redis_client)

    progress = await store.get_many([running, idle, broken])

    # Entries written before the file feed existed read with an empty feed.
    assert [item.model_dump(mode="json") for item in progress] == [
        {**entry, "current": None, "recent": []}
    ]
    redis_client.mget.assert_awaited_once_with(
        [sync_progress_key(running), sync_progress_key(idle), sync_progress_key(broken)]
    )
    assert await store.get_many([]) == []
    redis_client.mget.assert_awaited_once()
