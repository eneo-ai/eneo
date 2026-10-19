"""The sync ledger against Redis: failure counts survive between passes,
forgetting one item leaves the others, and every full sync moves the walk
generation on."""

from uuid import uuid4

import pytest

from eneo.integration.infrastructure.content_service.sharepoint_sync_ledger import (
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


async def test_failed_passes_round_trip_and_expire(redis_client, knowledge_id):
    ledger = SyncLedger(redis_client)
    assert await ledger.failed_passes(knowledge_id) == {}

    await ledger.record_failed_passes(knowledge_id, {"item-a": 1, "item-b": 2})
    await ledger.record_failed_passes(knowledge_id, {"item-a": 2})

    assert await ledger.failed_passes(knowledge_id) == {"item-a": 2, "item-b": 2}
    assert await redis_client.ttl(SyncLedger._failures_key(knowledge_id)) > 0


async def test_forgetting_an_item_keeps_the_others(redis_client, knowledge_id):
    ledger = SyncLedger(redis_client)
    await ledger.record_failed_passes(knowledge_id, {"item-a": 1, "item-b": 1})

    await ledger.forget(knowledge_id, {"item-a"})
    await ledger.forget(knowledge_id, set())

    assert await ledger.failed_passes(knowledge_id) == {"item-b": 1}


async def test_the_walk_generation_moves_on_and_expires(redis_client, knowledge_id):
    ledger = SyncLedger(redis_client)
    assert await ledger.walk_generation(knowledge_id) == 0

    await ledger.advance_walk_generation(knowledge_id)
    await ledger.advance_walk_generation(knowledge_id)

    assert await ledger.walk_generation(knowledge_id) == 2
    assert await redis_client.ttl(SyncLedger._walk_generation_key(knowledge_id)) > 0
