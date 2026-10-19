"""The sync ledger against Redis: failed items survive between passes,
forgetting one item leaves the others, and every full sync moves the walk
generation on."""

from uuid import uuid4

import pytest

from eneo.integration.infrastructure.content_service.sharepoint_sync_ledger import (
    FailedItem,
    SyncLedger,
)


@pytest.fixture
async def knowledge_id(redis_client):
    knowledge_id = uuid4()
    yield knowledge_id
    await redis_client.delete(
        SyncLedger._failures_key(knowledge_id),
        SyncLedger._walk_generation_key(knowledge_id),
    )


async def test_failed_items_round_trip_and_expire(redis_client, knowledge_id):
    ledger = SyncLedger(redis_client)
    assert await ledger.failed_items(knowledge_id) == {}

    await ledger.record_failed_items(
        knowledge_id, {"item-a": FailedItem(1, 100), "item-b": FailedItem(2, 200)}
    )
    await ledger.record_failed_items(
        knowledge_id, {"item-a": FailedItem(3, 300, set_aside_at=300)}
    )

    assert await ledger.failed_items(knowledge_id) == {
        "item-a": FailedItem(3, 300, set_aside_at=300),
        "item-b": FailedItem(2, 200),
    }
    assert await redis_client.ttl(SyncLedger._failures_key(knowledge_id)) > 0


async def test_forgetting_an_item_keeps_the_others(redis_client, knowledge_id):
    ledger = SyncLedger(redis_client)
    await ledger.record_failed_items(
        knowledge_id, {"item-a": FailedItem(1, 100), "item-b": FailedItem(1, 100)}
    )

    await ledger.forget(knowledge_id, {"item-a"})
    await ledger.forget(knowledge_id, set())

    assert await ledger.failed_items(knowledge_id) == {"item-b": FailedItem(1, 100)}


async def test_a_count_written_before_failure_times_reads_as_one(
    redis_client, knowledge_id
):
    await redis_client.hset(SyncLedger._failures_key(knowledge_id), "item-a", "2")

    assert await SyncLedger(redis_client).failed_items(knowledge_id) == {
        "item-a": FailedItem(2, 0)
    }


async def test_the_walk_generation_moves_on_and_expires(redis_client, knowledge_id):
    ledger = SyncLedger(redis_client)
    assert await ledger.walk_generation(knowledge_id) == 0

    await ledger.advance_walk_generation(knowledge_id)
    await ledger.advance_walk_generation(knowledge_id)

    assert await ledger.walk_generation(knowledge_id) == 2
    assert await redis_client.ttl(SyncLedger._walk_generation_key(knowledge_id)) > 0
