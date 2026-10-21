"""SharePointIndex: what one item's upsert, extraction and removal write."""

import hashlib
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.integration.infrastructure.content_service import (
    sharepoint_results as sync_results,
)
from eneo.integration.infrastructure.content_service.utils import (
    EMPTY_CONTENT_REASON,
    NO_TEXT_LAYER_REASON,
    NO_TEXT_REASONS,
    ExtractionResult,
)
from tests.unittests.integration.infrastructure.content_service.helpers import (
    http_error,
    reasons,
    size_ledger,
)


class TestProcessInfoBlobSizeAccounting:
    async def test_updates_integration_knowledge_size_using_delta_for_existing_blob(
        self, index, mock_dependencies, mock_integration_knowledge
    ):
        existing_blob = MagicMock(source_metadata=None)
        existing_blob.size = 100

        updated_blob = MagicMock()
        updated_blob.id = uuid4()
        updated_blob.size = 130

        mock_dependencies[
            "info_blob_service"
        ].repo.get_by_sharepoint_item_and_integration_knowledge = AsyncMock(
            return_value=existing_blob
        )
        mock_dependencies[
            "info_blob_service"
        ].publish_info_blob_without_validation = AsyncMock(return_value=updated_blob)
        mock_dependencies["integration_knowledge_repo"].update = AsyncMock()
        mock_dependencies["info_blob_service"].repo.session.execute = AsyncMock()

        mock_integration_knowledge.size = 500

        await index.upsert(
            title="Doc",
            text="New text",
            url="https://example.com",
            integration_knowledge=mock_integration_knowledge,
            sharepoint_item_id="item-123",
            stats=sync_results.initialize_stats(),
        )

        assert mock_integration_knowledge.size == 530
        mock_dependencies[
            "integration_knowledge_repo"
        ].adjust_size.assert_awaited_once_with(mock_integration_knowledge.id, 30)
        mock_dependencies["integration_knowledge_repo"].update.assert_not_called()

    async def test_does_not_change_size_when_existing_blob_size_is_unchanged(
        self, index, mock_dependencies, mock_integration_knowledge
    ):
        existing_blob = MagicMock(source_metadata=None)
        existing_blob.size = 100

        updated_blob = MagicMock()
        updated_blob.id = uuid4()
        updated_blob.size = 100

        mock_dependencies[
            "info_blob_service"
        ].repo.get_by_sharepoint_item_and_integration_knowledge = AsyncMock(
            return_value=existing_blob
        )
        mock_dependencies[
            "info_blob_service"
        ].publish_info_blob_without_validation = AsyncMock(return_value=updated_blob)
        mock_dependencies["integration_knowledge_repo"].update = AsyncMock()
        mock_dependencies["info_blob_service"].repo.session.execute = AsyncMock()

        mock_integration_knowledge.size = 500

        await index.upsert(
            title="Doc",
            text="Unchanged text",
            url="https://example.com",
            integration_knowledge=mock_integration_knowledge,
            sharepoint_item_id="item-123",
            stats=sync_results.initialize_stats(),
        )

        assert mock_integration_knowledge.size == 500
        mock_dependencies["integration_knowledge_repo"].adjust_size.assert_not_called()
        mock_dependencies["integration_knowledge_repo"].update.assert_not_called()

    async def test_sequential_adjustments_from_stale_entity_copies_lose_nothing(
        self, index, mock_dependencies, mock_user
    ):
        """Two copies of the row, each with a stale size, must both land."""
        ledger = size_ledger(mock_dependencies["integration_knowledge_repo"], 100)
        knowledge_id = uuid4()
        copy_a = MagicMock(id=knowledge_id, size=100)
        copy_b = MagicMock(id=knowledge_id, size=100)

        new_blob = MagicMock(id=uuid4(), size=30)
        repo = mock_dependencies["info_blob_service"].repo
        repo.get_by_sharepoint_item_and_integration_knowledge = AsyncMock(
            return_value=None
        )
        mock_dependencies[
            "info_blob_service"
        ].publish_info_blob_without_validation = AsyncMock(return_value=new_blob)
        await index.upsert(
            title="New",
            text="fresh text",
            url="https://example.com/new",
            integration_knowledge=copy_a,
            sharepoint_item_id="item-new",
            stats=sync_results.initialize_stats(),
        )

        deleted_blob = MagicMock(size=40)
        repo.delete_by_sharepoint_item_and_integration_knowledge = AsyncMock(
            return_value=[deleted_blob]
        )
        await index.remove(
            item_id="item-old",
            item_name="old.docx",
            integration_knowledge=copy_b,
            integration_knowledge_id=knowledge_id,
            stats=sync_results.initialize_stats(),
            reason="removed",
        )

        assert ledger["size"] == 90
        assert copy_a.size == 130
        assert copy_b.size == 90
        mock_dependencies["integration_knowledge_repo"].update.assert_not_called()

    async def test_skips_reembed_when_content_hash_unchanged(
        self, index, mock_dependencies, mock_integration_knowledge
    ):
        from eneo.integration.infrastructure.content_service.parsing import (
            sanitize_text_for_db,
        )

        text = "Identical content"
        existing_blob = MagicMock(source_metadata=None)
        existing_blob.id = uuid4()
        existing_blob.size = 100
        existing_blob.title = "Doc"  # metadata unchanged too
        existing_blob.url = "https://example.com"
        existing_blob.content_hash = hashlib.sha256(
            sanitize_text_for_db(text).encode("utf-8")
        ).digest()

        repo = mock_dependencies["info_blob_service"].repo
        repo.get_by_sharepoint_item_and_integration_knowledge = AsyncMock(
            return_value=existing_blob
        )
        repo.update = AsyncMock()
        mock_dependencies[
            "info_blob_service"
        ].publish_info_blob_without_validation = AsyncMock()
        mock_dependencies["integration_knowledge_repo"].update = AsyncMock()

        await index.upsert(
            title="Doc",
            text=text,
            url="https://example.com",
            integration_knowledge=mock_integration_knowledge,
            sharepoint_item_id="item-123",
            stats=sync_results.initialize_stats(),
        )

        # Unchanged content + metadata: no publication, no embedding,
        # no metadata update, no size update.
        mock_dependencies[
            "info_blob_service"
        ].publish_info_blob_without_validation.assert_not_called()
        repo.update.assert_not_called()
        mock_dependencies["integration_knowledge_repo"].update.assert_not_called()

    async def test_refreshes_metadata_on_hash_match_when_renamed(
        self, index, mock_dependencies, mock_integration_knowledge
    ):
        """Hash match but title/url drifted (e.g. full-sync rename): refresh metadata
        without re-embedding."""

        from eneo.integration.infrastructure.content_service.parsing import (
            sanitize_text_for_db,
        )

        text = "Identical content"
        existing_blob = MagicMock(source_metadata=None)
        existing_blob.id = uuid4()
        existing_blob.size = 100
        existing_blob.title = "Old name.docx"
        existing_blob.url = "https://example.com/old"
        existing_blob.content_hash = hashlib.sha256(
            sanitize_text_for_db(text).encode("utf-8")
        ).digest()

        repo = mock_dependencies["info_blob_service"].repo
        repo.get_by_sharepoint_item_and_integration_knowledge = AsyncMock(
            return_value=existing_blob
        )
        repo.update = AsyncMock()
        mock_dependencies[
            "info_blob_service"
        ].publish_info_blob_without_validation = AsyncMock()

        await index.upsert(
            title="New name.docx",
            text=text,
            url="https://example.com/new",
            integration_knowledge=mock_integration_knowledge,
            sharepoint_item_id="item-123",
            stats=sync_results.initialize_stats(),
        )

        # Metadata refreshed, but no replacement is published.
        repo.update.assert_awaited_once()
        update_arg = repo.update.await_args.args[0]
        assert update_arg.title == "New name.docx"
        assert update_arg.url == "https://example.com/new"
        mock_dependencies[
            "info_blob_service"
        ].publish_info_blob_without_validation.assert_not_called()

    async def test_reembeds_when_content_hash_differs(
        self, index, mock_dependencies, mock_integration_knowledge
    ):
        existing_blob = MagicMock(source_metadata=None)
        existing_blob.size = 100
        existing_blob.content_hash = b"a-different-old-hash"

        updated_blob = MagicMock()
        updated_blob.id = uuid4()
        updated_blob.size = 100

        mock_dependencies[
            "info_blob_service"
        ].repo.get_by_sharepoint_item_and_integration_knowledge = AsyncMock(
            return_value=existing_blob
        )
        mock_dependencies[
            "info_blob_service"
        ].publish_info_blob_without_validation = AsyncMock(return_value=updated_blob)
        mock_dependencies["integration_knowledge_repo"].update = AsyncMock()
        mock_dependencies["info_blob_service"].repo.session.execute = AsyncMock()

        await index.upsert(
            title="Doc",
            text="Brand new content",
            url="https://example.com",
            integration_knowledge=mock_integration_knowledge,
            sharepoint_item_id="item-123",
            stats=sync_results.initialize_stats(),
        )

        mock_dependencies[
            "info_blob_service"
        ].publish_info_blob_without_validation.assert_awaited_once()

    async def test_persists_content_hash_after_embedding_succeeds(
        self, index, mock_dependencies, mock_integration_knowledge
    ):
        from eneo.integration.infrastructure.content_service.parsing import (
            sanitize_text_for_db,
        )

        existing_blob = MagicMock(source_metadata=None)
        existing_blob.size = 100
        existing_blob.content_hash = b"old-hash"

        updated_blob = MagicMock()
        updated_blob.id = uuid4()
        updated_blob.size = 100

        text = "Fresh content"
        expected_hash = hashlib.sha256(
            sanitize_text_for_db(text).encode("utf-8")
        ).digest()
        upserted: list = []

        async def publish(info_blob, *, embedding_model):
            upserted.append(info_blob)
            return updated_blob

        repo = mock_dependencies["info_blob_service"].repo
        repo.get_by_sharepoint_item_and_integration_knowledge = AsyncMock(
            return_value=existing_blob
        )
        mock_dependencies[
            "info_blob_service"
        ].publish_info_blob_without_validation = AsyncMock(side_effect=publish)

        await index.upsert(
            title="Doc",
            text=text,
            url="https://example.com",
            integration_knowledge=mock_integration_knowledge,
            sharepoint_item_id="item-123",
            stats=sync_results.initialize_stats(),
        )

        assert upserted[0].content_hash == expected_hash

    async def test_embedding_failure_propagates_for_transaction_rollback(
        self, index, mock_dependencies, mock_integration_knowledge
    ):
        existing_blob = MagicMock(source_metadata=None)
        existing_blob.size = 100
        existing_blob.content_hash = b"old-hash"

        repo = mock_dependencies["info_blob_service"].repo
        repo.get_by_sharepoint_item_and_integration_knowledge = AsyncMock(
            return_value=existing_blob
        )
        mock_dependencies[
            "info_blob_service"
        ].publish_info_blob_without_validation = AsyncMock(
            side_effect=RuntimeError("embedding index unavailable")
        )

        with pytest.raises(RuntimeError, match="embedding index unavailable"):
            await index.upsert(
                title="Doc",
                text="Fresh content",
                url="https://example.com",
                integration_knowledge=mock_integration_knowledge,
                sharepoint_item_id="item-123",
                stats=sync_results.initialize_stats(),
            )


class TestFileExtraction:
    """``_extract_file`` keeps its ``(content, skip_reason)`` shape and the
    delete guard only accepts a completed parse that found nothing."""

    ITEM = {
        "id": "item-1",
        "name": "Report.PDF",
        "file": {},
        "parentReference": {"driveId": "drive-1"},
    }

    async def test_text_is_returned_without_a_reason(self, index):
        client = AsyncMock()
        client.get_file_extraction_by_id.return_value = ExtractionResult.ok("Body")

        assert await index._extract_file(
            client, "drive-1", "item-1", "Report.PDF", sync_results.initialize_stats()
        ) == ("Body", None)
        client.get_file_extraction_by_id.assert_awaited_once_with(
            drive_id="drive-1", item_id="item-1"
        )

    @pytest.mark.parametrize(
        ("outcome", "expected_reason", "positive"),
        [
            (
                ExtractionResult.no_text(NO_TEXT_LAYER_REASON),
                NO_TEXT_LAYER_REASON,
                True,
            ),
            (
                ExtractionResult.no_text(EMPTY_CONTENT_REASON),
                EMPTY_CONTENT_REASON,
                True,
            ),
            (
                ExtractionResult.error("Corrupt or malformed file"),
                "Error: Corrupt or malformed file",
                False,
            ),
            (
                ExtractionResult.error("Incomplete download of 'x' (1 of 2 bytes)"),
                "Error: Incomplete download of 'x' (1 of 2 bytes)",
                False,
            ),
            (
                ExtractionResult.skipped("Unsupported file type (.xlsb)"),
                "Unsupported file type (.xlsb)",
                False,
            ),
            (http_error(404, "Not Found"), "Error: HTTP 404 Not Found", False),
            (
                ValueError("SharePoint file 'x' exceeds max download size (1 > 0)"),
                "File too large (exceeds 50 MB limit)",
                False,
            ),
        ],
    )
    async def test_only_a_completed_parse_without_text_is_positive(
        self, index, outcome, expected_reason, positive
    ):
        client = AsyncMock()
        if isinstance(outcome, Exception):
            client.get_file_extraction_by_id.side_effect = outcome
        else:
            client.get_file_extraction_by_id.return_value = outcome

        content, skip_reason = await index._extract_file(
            client, "drive-1", "item-1", "Report.PDF", sync_results.initialize_stats()
        )

        assert (content, skip_reason) == (None, expected_reason)
        assert (skip_reason in NO_TEXT_REASONS) is positive

    async def test_an_item_without_an_id_is_skipped_before_download(
        self, index, mock_integration_knowledge
    ):
        client = AsyncMock()
        stats = sync_results.initialize_stats()

        await index.index_file(
            client=client,
            drive_id="drive-1",
            item={"name": "a.pdf", "file": {}},
            integration_knowledge=mock_integration_knowledge,
            stats=stats,
        )

        client.get_file_extraction_by_id.assert_not_called()
        assert reasons(stats["skipped_details"]) == [
            {"file": "a.pdf", "reason": "Missing item id"}
        ]

    async def test_unsupported_extension_is_decided_before_download(
        self, index, mock_integration_knowledge
    ):
        client = AsyncMock()
        stats = sync_results.initialize_stats()

        await index.index_file(
            client=client,
            drive_id="drive-1",
            item={**self.ITEM, "name": "Old.DOC"},
            integration_knowledge=mock_integration_knowledge,
            stats=stats,
        )

        client.get_file_extraction_by_id.assert_not_called()
        assert reasons(stats["skipped_details"]) == [
            {
                "file": "Old.DOC",
                "reason": "Unsupported file type (legacy Word .doc, save as .docx)",
            }
        ]

    async def test_delete_helper_refuses_non_positive_reasons(
        self, index, mock_integration_knowledge
    ):
        with pytest.raises(ValueError, match="no-text reason"):
            await index._remove_empty(
                item_id="item-1",
                item_name="a.pdf",
                integration_knowledge=mock_integration_knowledge,
                integration_knowledge_id=mock_integration_knowledge.id,
                stats=sync_results.initialize_stats(),
                reason="Error: Corrupt or malformed file",
            )

    async def test_delete_helper_records_the_given_reason(
        self, index, mock_dependencies, mock_integration_knowledge
    ):
        mock_dependencies[
            "info_blob_service"
        ].repo.delete_by_sharepoint_item_and_integration_knowledge = AsyncMock(
            return_value=[]
        )
        stats = sync_results.initialize_stats()

        await index._remove_empty(
            item_id="item-1",
            item_name="scan.pdf",
            integration_knowledge=mock_integration_knowledge,
            integration_knowledge_id=mock_integration_knowledge.id,
            stats=stats,
            reason=NO_TEXT_LAYER_REASON,
        )

        assert reasons(stats["skipped_details"]) == [
            {"file": "scan.pdf", "reason": NO_TEXT_LAYER_REASON}
        ]

    async def test_delete_helper_counts_a_failed_delete_once(
        self, index, mock_dependencies, mock_integration_knowledge
    ):
        mock_dependencies[
            "info_blob_service"
        ].repo.delete_by_sharepoint_item_and_integration_knowledge = AsyncMock(
            side_effect=RuntimeError("db down")
        )
        stats = sync_results.initialize_stats()

        await index._remove_empty(
            item_id="item-1",
            item_name="scan.pdf",
            integration_knowledge=mock_integration_knowledge,
            integration_knowledge_id=mock_integration_knowledge.id,
            stats=stats,
            reason=NO_TEXT_LAYER_REASON,
        )

        assert stats["skipped_items"] == 1
        assert stats["failed_items"] == 1
        assert reasons(stats["skipped_details"]) == [
            {
                "file": "scan.pdf",
                "reason": "Could not remove unextractable: db down",
                "retry": True,
            }
        ]


class TestProcessInfoBlobEmptyText:
    """Text that sanitises to nothing is a no-text result: not published, and a
    previously indexed copy is removed and counted once."""

    @pytest.mark.parametrize("text", ["", "   \n\t", "\x00\x00"])
    async def test_previously_indexed_item_is_removed_and_counted_once(
        self, index, mock_dependencies, mock_integration_knowledge, text
    ):
        mock_integration_knowledge.size = 500
        size_ledger(mock_dependencies["integration_knowledge_repo"], 500)
        stale_blob = MagicMock(size=120)
        delete = mock_dependencies[
            "info_blob_service"
        ].repo.delete_by_sharepoint_item_and_integration_knowledge = AsyncMock(
            return_value=[stale_blob]
        )
        publish = mock_dependencies[
            "info_blob_service"
        ].publish_info_blob_without_validation
        stats = sync_results.initialize_stats()

        outcome = await index.upsert(
            title="Doc",
            text=text,
            url="https://example.com",
            integration_knowledge=mock_integration_knowledge,
            sharepoint_item_id="item-1",
            stats=stats,
        )
        sync_results.count_outcome(stats, outcome, "Doc")

        assert outcome == "empty"
        publish.assert_not_called()
        delete.assert_awaited_once_with(
            sharepoint_item_id="item-1",
            integration_knowledge_id=mock_integration_knowledge.id,
        )
        assert mock_integration_knowledge.size == 380
        assert stats["files_deleted"] == 1
        assert stats["skipped_items"] == 1
        assert reasons(stats["skipped_details"]) == [
            {"file": "Doc", "reason": EMPTY_CONTENT_REASON}
        ]
        mock_dependencies[
            "change_key_service"
        ].invalidate_change_key.assert_awaited_once_with(
            integration_knowledge_id=mock_integration_knowledge.id, item_id="item-1"
        )

    async def test_item_without_an_id_is_only_counted(
        self, index, mock_dependencies, mock_integration_knowledge
    ):
        delete = mock_dependencies[
            "info_blob_service"
        ].repo.delete_by_sharepoint_item_and_integration_knowledge
        stats = sync_results.initialize_stats()

        outcome = await index.upsert(
            title="Start",
            text="\x00",
            url="https://example.com",
            integration_knowledge=mock_integration_knowledge,
            stats=stats,
            item_name="Start.aspx",
        )
        sync_results.count_outcome(stats, outcome, "Start.aspx", page=True)

        assert outcome == "empty"
        delete.assert_not_called()
        assert stats["files_deleted"] == 0
        assert stats["skipped_items"] == 1
        assert reasons(stats["skipped_details"]) == [
            {"file": "Start.aspx", "reason": EMPTY_CONTENT_REASON}
        ]

    async def test_a_failed_removal_of_an_unreadable_item_fails_the_pass(
        self, index, mock_dependencies, mock_integration_knowledge
    ):
        """The stale copy stays, so the item is a failure the next sync retries;
        its one skip detail says why."""
        mock_dependencies[
            "info_blob_service"
        ].repo.delete_by_sharepoint_item_and_integration_knowledge = AsyncMock(
            side_effect=RuntimeError("503")
        )
        stats = sync_results.initialize_stats()

        outcome = await index.upsert(
            title="Doc",
            text="\x00",
            url="https://example.com",
            integration_knowledge=mock_integration_knowledge,
            sharepoint_item_id="item-1",
            stats=stats,
        )
        sync_results.count_outcome(stats, outcome, "Doc")

        assert outcome == "failed"
        assert (stats["failed_items"], stats["skipped_items"]) == (1, 1)
        assert reasons(stats["skipped_details"]) == [
            {
                "file": "Doc",
                "reason": "Could not remove unextractable: 503",
                "retry": True,
            }
        ]
