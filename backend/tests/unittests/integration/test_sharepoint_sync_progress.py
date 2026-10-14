"""Live sync progress in Redis: what is written, how often, and that it never fails a sync."""

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from eneo.integration.infrastructure.content_service.types import SyncStats
from eneo.integration.infrastructure.sharepoint_sync_progress import (
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


def _stats(**counts: int) -> SyncStats:
    stats: SyncStats = {
        "files_processed": 0,
        "files_deleted": 0,
        "out_of_scope_deleted": 0,
        "folders_processed": 0,
        "pages_processed": 0,
        "unchanged_items": 0,
        "skipped_items": 0,
        "skipped_details": [],
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


async def test_end_removes_the_entry_and_stops_reporting(reporter, redis_client):
    item_id = uuid4()
    await reporter.begin(item_id, "full")

    await reporter.end()
    await reporter.set_phase("finishing", _stats(files_processed=1))
    await reporter.end()

    redis_client.delete.assert_awaited_once_with(sync_progress_key(item_id))
    assert len(_saved(redis_client)) == 1


async def test_redis_failures_never_reach_the_sync_or_the_reader(redis_client):
    redis_client.set.side_effect = RedisConnectionError("redis down")
    redis_client.delete.side_effect = RedisConnectionError("redis down")
    redis_client.mget.side_effect = RedisConnectionError("redis down")
    store = SharePointSyncProgressStore(redis_client)
    reporter = SyncProgressReporter(store)

    await reporter.begin(uuid4(), "full")
    await reporter.set_phase("processing", _stats(files_processed=1))
    await reporter.end()

    assert await store.get_many([uuid4()]) == []
    assert redis_client.set.await_count == 2
    redis_client.delete.assert_awaited_once()


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

    assert [item.model_dump(mode="json") for item in progress] == [entry]
    redis_client.mget.assert_awaited_once_with(
        [sync_progress_key(running), sync_progress_key(idle), sync_progress_key(broken)]
    )
    assert await store.get_many([]) == []
    redis_client.mget.assert_awaited_once()
