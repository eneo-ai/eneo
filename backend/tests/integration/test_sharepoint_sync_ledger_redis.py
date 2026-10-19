"""The walk generation against Redis: every full sync moves it on."""

from uuid import uuid4

import pytest

from eneo.integration.infrastructure.content_service.sharepoint_sync_ledger import (
    WalkGenerations,
)


@pytest.fixture
async def knowledge_id(redis_client):
    knowledge_id = uuid4()
    yield knowledge_id
    await redis_client.delete(WalkGenerations._key(knowledge_id))


async def test_the_walk_generation_moves_on_and_expires(redis_client, knowledge_id):
    generations = WalkGenerations(redis_client)
    assert await generations.current(knowledge_id) == 0

    await generations.advance(knowledge_id)
    await generations.advance(knowledge_id)

    assert await generations.current(knowledge_id) == 2
    assert await redis_client.ttl(WalkGenerations._key(knowledge_id)) > 0
