"""The failed items a sync keeps live on the knowledge row, in the sync's own
transaction: they survive a Redis restart and roll back with the pass."""

import pytest

from eneo.integration.infrastructure.content_service.sharepoint_sync_ledger import (
    FailedItem,
    decode_failed_items,
    encode_failed_items,
)
from tests.integration.info_blobs.test_integration_publication_locks import (
    _seed_knowledge,
)


async def test_the_record_commits_and_rolls_back_with_the_sync(
    db_container, user_integration_factory
) -> None:
    async with db_container() as setup:
        knowledge_id, _ = await _seed_knowledge(setup, user_integration_factory)
    items = {
        "item-a": FailedItem(1, 100),
        "item-b": FailedItem(3, 300, set_aside_at=300),
    }

    async with db_container() as container:
        await container.integration_knowledge_repo().update_sync_state(
            knowledge_id, sync_failed_items=encode_failed_items(items)
        )

    class RolledBack(Exception):
        pass

    with pytest.raises(RolledBack):
        async with db_container() as container:
            await container.integration_knowledge_repo().update_sync_state(
                knowledge_id, sync_failed_items=None
            )
            raise RolledBack

    async with db_container() as verification:
        repo = verification.integration_knowledge_repo()
        stored = await repo.get_sync_failed_items(knowledge_id)
        knowledge = await repo.one(id=knowledge_id)
        await repo.update(knowledge)
        after_update = await repo.get_sync_failed_items(knowledge_id)

    assert decode_failed_items(stored) == items
    assert decode_failed_items(after_update) == items
