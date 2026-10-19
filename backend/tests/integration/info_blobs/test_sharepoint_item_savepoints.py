"""A sync writes every item in one transaction: a database error in one item
must cost that item only, not every write after it."""

from unittest.mock import patch

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from eneo.database.tables.info_blobs_table import InfoBlobs
from eneo.integration.infrastructure.content_service import (
    sharepoint_results as sync_results,
)
from eneo.integration.infrastructure.content_service.sharepoint_index import (
    SharePointIndex,
)
from tests.integration.info_blobs.test_integration_publication_locks import (
    _seed_knowledge,
    _with_fake_embeddings,
)


async def test_a_failed_item_write_leaves_the_transaction_usable(
    db_container, user_integration_factory
) -> None:
    async with db_container() as setup:
        knowledge_id, _ = await _seed_knowledge(setup, user_integration_factory)

    async with db_container() as container:
        _with_fake_embeddings(container)
        session = container.session()
        knowledge = await container.integration_knowledge_repo().one(id=knowledge_id)
        info_blob_service = container.info_blob_service()
        index = SharePointIndex(
            info_blob_service,
            container.integration_knowledge_repo(),
            container.user(),
            None,
        )
        repo = info_blob_service.repo
        lookup = repo.get_by_sharepoint_item_and_integration_knowledge
        delete = repo.delete_by_sharepoint_item_and_integration_knowledge

        async def broken(statement):
            await session.execute(sa.text("SELECT 1 / 0"))
            return await statement()

        async def lookup_once_broken(*, sharepoint_item_id, integration_knowledge_id):
            async def statement():
                return await lookup(
                    sharepoint_item_id=sharepoint_item_id,
                    integration_knowledge_id=integration_knowledge_id,
                )

            return await (
                broken(statement) if sharepoint_item_id == "broken" else statement()
            )

        async def delete_once_broken(*, sharepoint_item_id, integration_knowledge_id):
            async def statement():
                return await delete(
                    sharepoint_item_id=sharepoint_item_id,
                    integration_knowledge_id=integration_knowledge_id,
                )

            return await (
                broken(statement) if sharepoint_item_id == "broken" else statement()
            )

        stats = sync_results.initialize_stats()
        with (
            patch.object(
                repo,
                "get_by_sharepoint_item_and_integration_knowledge",
                lookup_once_broken,
            ),
            patch.object(
                repo,
                "delete_by_sharepoint_item_and_integration_knowledge",
                delete_once_broken,
            ),
        ):
            with pytest.raises(DBAPIError):
                await index.upsert(
                    "broken.docx",
                    "Never written",
                    "https://example.test/broken.docx",
                    knowledge,
                    stats=stats,
                    sharepoint_item_id="broken",
                )
            assert (
                await index.remove(
                    item_id="broken",
                    item_name="broken.docx",
                    integration_knowledge=knowledge,
                    integration_knowledge_id=knowledge.id,
                    stats=stats,
                    reason="removed",
                )
                is None
            )
            for item_id in ("kept", "dropped"):
                assert (
                    await index.upsert(
                        f"{item_id}.docx",
                        f"Text of {item_id}",
                        f"https://example.test/{item_id}.docx",
                        knowledge,
                        stats=stats,
                        sharepoint_item_id=item_id,
                    )
                    == "added"
                )
            assert (
                await index.remove(
                    item_id="dropped",
                    item_name="dropped.docx",
                    integration_knowledge=knowledge,
                    integration_knowledge_id=knowledge.id,
                    stats=stats,
                    reason="removed",
                )
                == 1
            )

    async with db_container() as verification:
        indexed = await verification.session().scalars(
            sa.select(InfoBlobs.sharepoint_item_id).where(
                InfoBlobs.integration_knowledge_id == knowledge_id
            )
        )
        assert list(indexed) == ["kept"]
    assert stats.get("failed_items") == 1


async def test_a_failed_read_of_the_indexed_ids_leaves_the_transaction_usable(
    db_container, user_integration_factory
) -> None:
    async with db_container() as setup:
        knowledge_id, _ = await _seed_knowledge(setup, user_integration_factory)

    async with db_container() as container:
        _with_fake_embeddings(container)
        session = container.session()
        knowledge = await container.integration_knowledge_repo().one(id=knowledge_id)
        info_blob_service = container.info_blob_service()
        index = SharePointIndex(
            info_blob_service,
            container.integration_knowledge_repo(),
            container.user(),
            None,
        )
        stats = sync_results.initialize_stats()
        await index.upsert(
            "archive.docx",
            "Text before it became an archive",
            "https://example.test/archive.docx",
            knowledge,
            stats=stats,
            sharepoint_item_id="archive",
        )

        async def broken_read(*, integration_knowledge_id):
            await session.execute(sa.text("SELECT 1 / 0"))
            return []

        with patch.object(
            info_blob_service.repo,
            "get_sharepoint_item_ids_for_integration_knowledge",
            broken_read,
        ):
            await index.record_unextractable(
                item_id="archive",
                item_name="archive.zip",
                skip_reason="Unsupported file type (.zip)",
                integration_knowledge=knowledge,
                integration_knowledge_id=knowledge.id,
                stats=stats,
            )

    async with db_container() as verification:
        remaining = await verification.session().scalar(
            sa.select(sa.func.count())
            .select_from(InfoBlobs)
            .where(InfoBlobs.integration_knowledge_id == knowledge_id)
        )
    assert remaining == 0
    assert stats.get("failed_items", 0) == 0
