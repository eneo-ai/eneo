"""SharePointReconciliation: removing what left the source or the scope."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from eneo.integration.infrastructure.clients.sharepoint_content_client import (
    SharePointItemLookup,
)
from eneo.integration.infrastructure.content_service import (
    sharepoint_results as sync_results,
)
from eneo.integration.infrastructure.content_service import (
    sharepoint_scope as scope_rules,
)
from tests.unittests.integration.infrastructure.content_service.helpers import (
    descendant,
    http_error,
    size_ledger,
)


class TestOutOfScopeFolderSubtreeCleanup:
    """A folder leaving scope takes its descendant blobs with it, each placed
    against the scope first."""

    async def test_deletes_descendant_blobs_when_folder_leaves_scope(
        self, reconciliation, mock_dependencies
    ):
        ik = MagicMock()
        ik.id = uuid4()
        ik.size = 0
        repo = mock_dependencies["info_blob_service"].repo
        repo.delete_by_sharepoint_item_and_integration_knowledge.return_value = []
        content_client = AsyncMock()

        with patch.object(
            scope_rules,
            "enumerate_items",
            AsyncMock(
                return_value=[
                    descendant("child-1", "/Documents/Moved"),
                    descendant("child-2", "/Documents/Moved/Sub"),
                ]
            ),
        ):
            stats = sync_results.initialize_stats()
            await reconciliation.remove_subtree(
                content_client=content_client,
                resource_type="site",
                site_id="site-1",
                drive_id="drive-1",
                folder_id="folder-1",
                folder_name="Moved",
                integration_knowledge=ik,
                integration_knowledge_id=ik.id,
                stats=stats,
                scope_folder_path="/Documents/A",
                known_subfolder_ids=set(),
                indexed_ids={"child-1", "child-2"},
            )

        assert repo.delete_by_sharepoint_item_and_integration_knowledge.await_count == 2
        called_item_ids = {
            call.kwargs["sharepoint_item_id"]
            for call in repo.delete_by_sharepoint_item_and_integration_knowledge.await_args_list
        }
        assert called_item_ids == {"child-1", "child-2"}

    async def test_cleans_onedrive_subtree_via_drive_enumeration(
        self, reconciliation, mock_dependencies
    ):
        """OneDrive (no site_id) is now cleaned inline via drive enumeration."""
        ik = MagicMock()
        ik.id = uuid4()
        ik.size = 0
        repo = mock_dependencies["info_blob_service"].repo
        repo.delete_by_sharepoint_item_and_integration_knowledge.return_value = []
        content_client = AsyncMock()

        with patch.object(
            scope_rules,
            "enumerate_items",
            AsyncMock(return_value=[descendant("od-child", "/Moved")]),
        ) as mock_enum:
            stats = sync_results.initialize_stats()
            await reconciliation.remove_subtree(
                content_client=content_client,
                resource_type="onedrive",
                site_id=None,
                drive_id="drive-1",
                folder_id="folder-1",
                folder_name="Moved",
                integration_knowledge=ik,
                integration_knowledge_id=ik.id,
                stats=stats,
                scope_folder_path="/A",
                known_subfolder_ids=set(),
                indexed_ids={"od-child"},
            )

        mock_enum.assert_awaited_once()
        assert repo.delete_by_sharepoint_item_and_integration_knowledge.await_count == 1

    async def test_degrades_safely_without_drive_id(
        self, reconciliation, mock_dependencies
    ):
        ik = MagicMock()
        ik.id = uuid4()
        content_client = AsyncMock()
        repo = mock_dependencies["info_blob_service"].repo

        with patch.object(scope_rules, "enumerate_items") as mock_enum:
            stats = sync_results.initialize_stats()
            await reconciliation.remove_subtree(
                content_client=content_client,
                resource_type="site",
                site_id="site-1",
                drive_id=None,
                folder_id="folder-1",
                folder_name="Moved",
                integration_knowledge=ik,
                integration_knowledge_id=ik.id,
                stats=stats,
                scope_folder_path="/Documents/A",
                known_subfolder_ids=set(),
                indexed_ids={"child-1"},
            )

        mock_enum.assert_not_called()
        repo.delete_by_sharepoint_item_and_integration_knowledge.assert_not_called()


class TestFullSyncReconciliation:
    """Full-sync reconciliation must remove orphans but never mass-delete."""

    def _ik(self):
        ik = MagicMock()
        ik.id = uuid4()
        return ik

    async def test_deletes_only_orphaned_blobs(
        self, reconciliation, index, mock_dependencies
    ):
        ik = self._ik()
        indexed = [(uuid4(), "keep-1"), (uuid4(), "orphan-1"), (uuid4(), "keep-2")]
        mock_dependencies[
            "info_blob_service"
        ].repo.get_sharepoint_item_ids_for_integration_knowledge = AsyncMock(
            return_value=indexed
        )

        with patch.object(
            reconciliation,
            "_enumerate_item_ids",
            AsyncMock(return_value={"keep-1", "keep-2"}),
        ):
            with patch.object(
                index, "remove", AsyncMock(return_value=1)
            ) as mock_delete:
                await reconciliation.reconcile(
                    client=AsyncMock(),
                    integration_knowledge=ik,
                    resource_type="site",
                    site_id="site-1",
                    drive_id="drive-1",
                    folder_id=None,
                    stats=sync_results.initialize_stats(),
                )

        assert mock_delete.await_count == 1
        assert mock_delete.await_args.kwargs["item_id"] == "orphan-1"

    async def test_orphan_deletion_persists_size_decrease(
        self, reconciliation, mock_dependencies
    ):
        ik = self._ik()
        ik.size = 100
        ledger = size_ledger(mock_dependencies["integration_knowledge_repo"], 100)
        indexed = [(uuid4(), "orphan-1")]
        deleted_blob = MagicMock()
        deleted_blob.size = 40
        repo = mock_dependencies["info_blob_service"].repo
        repo.get_sharepoint_item_ids_for_integration_knowledge = AsyncMock(
            return_value=indexed
        )
        repo.delete_by_sharepoint_item_and_integration_knowledge = AsyncMock(
            return_value=[deleted_blob]
        )

        with patch.object(
            reconciliation,
            "_enumerate_item_ids",
            AsyncMock(return_value=set()),
        ):
            await reconciliation.reconcile(
                client=AsyncMock(),
                integration_knowledge=ik,
                resource_type="site",
                site_id="site-1",
                drive_id="drive-1",
                folder_id=None,
                stats=sync_results.initialize_stats(),
            )

        assert ik.size == 60
        assert ledger["size"] == 60

    async def test_skips_when_enumeration_fails(
        self, reconciliation, index, mock_dependencies
    ):
        ik = self._ik()
        mock_dependencies[
            "info_blob_service"
        ].repo.get_sharepoint_item_ids_for_integration_knowledge = AsyncMock(
            return_value=[(uuid4(), "anything")]
        )

        with patch.object(
            reconciliation,
            "_enumerate_item_ids",
            AsyncMock(side_effect=Exception("throttled mid-listing")),
        ):
            with patch.object(index, "remove", AsyncMock()) as mock_delete:
                await reconciliation.reconcile(
                    client=AsyncMock(),
                    integration_knowledge=ik,
                    resource_type="site",
                    site_id="site-1",
                    drive_id="drive-1",
                    folder_id=None,
                    stats=sync_results.initialize_stats(),
                )

        mock_delete.assert_not_called()

    async def test_skips_when_orphans_exceed_safety_cap(
        self, reconciliation, index, mock_dependencies
    ):
        ik = self._ik()
        # 200 indexed, all orphaned -> over the 50%/floor cap -> refuse to delete.
        indexed = [(uuid4(), f"item-{i}") for i in range(200)]
        mock_dependencies[
            "info_blob_service"
        ].repo.get_sharepoint_item_ids_for_integration_knowledge = AsyncMock(
            return_value=indexed
        )

        with patch.object(
            reconciliation,
            "_enumerate_item_ids",
            AsyncMock(return_value=set()),
        ):
            with patch.object(index, "remove", AsyncMock()) as mock_delete:
                await reconciliation.reconcile(
                    client=AsyncMock(
                        get_item_metadata_batch=AsyncMock(return_value={})
                    ),
                    integration_knowledge=ik,
                    resource_type="site",
                    site_id="site-1",
                    drive_id="drive-1",
                    folder_id=None,
                    stats=sync_results.initialize_stats(),
                )

        mock_delete.assert_not_called()

    async def test_noop_when_no_orphans(self, reconciliation, index, mock_dependencies):
        ik = self._ik()
        indexed = [(uuid4(), "a"), (uuid4(), "b")]
        mock_dependencies[
            "info_blob_service"
        ].repo.get_sharepoint_item_ids_for_integration_knowledge = AsyncMock(
            return_value=indexed
        )

        with patch.object(
            reconciliation,
            "_enumerate_item_ids",
            AsyncMock(return_value={"a", "b", "c"}),
        ):
            with patch.object(index, "remove", AsyncMock()) as mock_delete:
                await reconciliation.reconcile(
                    client=AsyncMock(),
                    integration_knowledge=ik,
                    resource_type="site",
                    site_id="site-1",
                    drive_id="drive-1",
                    folder_id=None,
                    stats=sync_results.initialize_stats(),
                )

        mock_delete.assert_not_called()


class TestEnumerateAuthoritativeItemIds:
    """Strict enumeration used by reconciliation + subtree cleanup (destructive path)."""

    async def test_site_recurses_files_and_pages_excluding_folders(
        self, reconciliation
    ):
        client = AsyncMock()
        client.get_drive_root_children.return_value = [
            {"id": "folder-1", "folder": {}},
            {"id": "file-1", "file": {}},
        ]
        client.get_folder_items.return_value = [{"id": "file-2", "file": {}}]
        client.get_site_pages.return_value = {"value": [{"id": "page-1"}]}

        result = await reconciliation._enumerate_item_ids(
            client=client,
            resource_type="site",
            site_id="site-1",
            drive_id="drive-1",
            folder_id=None,
        )

        # Files (incl. nested) + pages, but NOT the folder id itself.
        assert result == {"file-1", "file-2", "page-1"}

    async def test_onedrive_uses_drive_listing_no_site_id(self, reconciliation):
        client = AsyncMock()
        client.get_drive_root_children.return_value = [{"id": "od-file", "file": {}}]

        result = await reconciliation._enumerate_item_ids(
            client=client,
            resource_type="onedrive",
            site_id=None,
            drive_id="drive-1",
            folder_id=None,
        )

        assert result == {"od-file"}
        client.get_drive_root_children.assert_awaited_once()

    async def test_listing_error_propagates_not_swallowed(self, reconciliation):
        """A failed listing must raise so reconciliation never treats a partial
        enumeration as authoritative."""
        client = AsyncMock()
        client.get_drive_root_children.side_effect = RuntimeError("graph throttled")

        with pytest.raises(RuntimeError):
            await reconciliation._enumerate_item_ids(
                client=client,
                resource_type="site",
                site_id="site-1",
                drive_id="drive-1",
                folder_id=None,
            )


class TestReconcileWarnings:
    @pytest.fixture
    def ik(self):
        ik = MagicMock()
        ik.id = uuid4()
        return ik

    async def test_cap_refusal_is_recorded_in_stats(
        self, reconciliation, mock_dependencies, ik
    ):
        indexed = [(uuid4(), f"item-{i}") for i in range(200)]
        mock_dependencies[
            "info_blob_service"
        ].repo.get_sharepoint_item_ids_for_integration_knowledge = AsyncMock(
            return_value=indexed
        )
        stats = sync_results.initialize_stats()

        with patch.object(
            reconciliation,
            "_enumerate_item_ids",
            AsyncMock(return_value=set()),
        ):
            await reconciliation.reconcile(
                client=AsyncMock(get_item_metadata_batch=AsyncMock(return_value={})),
                integration_knowledge=ik,
                resource_type="site",
                site_id="site-1",
                drive_id="drive-1",
                folder_id=None,
                stats=stats,
            )

        assert "200 of 200" in stats["reconcile_warning"]
        assert "safety cap" in stats["reconcile_warning"]

    async def test_enumeration_failure_is_recorded_in_stats(
        self, reconciliation, mock_dependencies, ik
    ):
        stats = sync_results.initialize_stats()

        with patch.object(
            reconciliation,
            "_enumerate_item_ids",
            AsyncMock(side_effect=RuntimeError("throttled mid-listing")),
        ):
            await reconciliation.reconcile(
                client=AsyncMock(),
                integration_knowledge=ik,
                resource_type="site",
                site_id="site-1",
                drive_id="drive-1",
                folder_id=None,
                stats=stats,
            )

        assert "throttled mid-listing" in stats["reconcile_warning"]

    async def test_clean_reconciliation_leaves_no_warning(
        self, reconciliation, mock_dependencies, ik
    ):
        mock_dependencies[
            "info_blob_service"
        ].repo.get_sharepoint_item_ids_for_integration_knowledge = AsyncMock(
            return_value=[(uuid4(), "a")]
        )
        stats = sync_results.initialize_stats()

        with patch.object(
            reconciliation,
            "_enumerate_item_ids",
            AsyncMock(return_value={"a"}),
        ):
            await reconciliation.reconcile(
                client=AsyncMock(),
                integration_knowledge=ik,
                resource_type="site",
                site_id="site-1",
                drive_id="drive-1",
                folder_id=None,
                stats=stats,
            )

        assert "reconcile_warning" not in stats


class TestReconcileAboveTheCap:
    """Only explicit Graph evidence can remove an orphan above the cap."""

    @pytest.fixture
    def ik(self):
        ik = MagicMock()
        ik.id = uuid4()
        return ik

    async def _reconcile(
        self,
        reconciliation,
        index,
        mock_dependencies,
        ik,
        orphan_ids,
        client,
        folder_id=None,
    ):
        mock_dependencies[
            "info_blob_service"
        ].repo.get_sharepoint_item_ids_for_integration_knowledge = AsyncMock(
            return_value=[(uuid4(), item_id) for item_id in orphan_ids]
        )
        stats = sync_results.initialize_stats()
        with (
            patch.object(
                reconciliation,
                "_enumerate_item_ids",
                AsyncMock(return_value=set()),
            ),
            patch.object(index, "remove", AsyncMock(return_value=1)) as delete,
        ):
            await reconciliation.reconcile(
                client=client,
                integration_knowledge=ik,
                resource_type="site",
                site_id="site-1",
                drive_id="drive-1",
                folder_id=folder_id,
                stats=stats,
            )
        return stats, [call.kwargs["item_id"] for call in delete.await_args_list]

    def _client(self, answers):
        client = AsyncMock()

        async def batch(drive_id, item_ids):
            return {item_id: answers(item_id) for item_id in item_ids}

        client.get_item_metadata_batch.side_effect = batch
        return client

    async def test_orphans_graph_confirms_gone_are_removed_and_the_rest_reported(
        self, reconciliation, index, mock_dependencies, ik
    ):
        ids = [str(i) for i in range(40)]
        client = self._client(
            lambda item_id: SharePointItemLookup(404 if int(item_id) % 2 == 0 else 403)
        )
        stats, removed = await self._reconcile(
            reconciliation, index, mock_dependencies, ik, ids, client
        )
        assert removed == ids[::2]
        assert client.get_item_metadata_batch.await_count == 2
        client.get_file_metadata.assert_not_awaited()
        assert "removed 20" in stats["reconcile_warning"]
        assert "kept 20" in stats["reconcile_warning"]

    async def test_a_large_deletion_graph_confirms_in_full_is_cleaned_quietly(
        self, reconciliation, index, mock_dependencies, ik
    ):
        client = self._client(lambda _: SharePointItemLookup(410))
        stats, removed = await self._reconcile(
            reconciliation,
            index,
            mock_dependencies,
            ik,
            [str(i) for i in range(30)],
            client,
        )
        assert len(removed) == 30
        assert "reconcile_warning" not in stats

    @pytest.mark.parametrize("status", [429, 503, 401])
    async def test_verification_stops_when_graph_cannot_answer(
        self, reconciliation, index, mock_dependencies, ik, status
    ):
        client = self._client(
            lambda item_id: SharePointItemLookup(404 if item_id == "0" else status)
        )
        stats, removed = await self._reconcile(
            reconciliation,
            index,
            mock_dependencies,
            ik,
            [str(i) for i in range(30)],
            client,
        )
        assert removed == ["0"]
        assert client.get_item_metadata_batch.await_count == 1
        assert "kept 29" in stats["reconcile_warning"]

    async def test_verification_is_bounded_per_sync(
        self, reconciliation, index, mock_dependencies, ik
    ):
        client = self._client(lambda _: SharePointItemLookup(404))
        stats, removed = await self._reconcile(
            reconciliation,
            index,
            mock_dependencies,
            ik,
            [str(i) for i in range(700)],
            client,
        )
        assert client.get_item_metadata_batch.await_count == 25
        assert all(
            len(call.args[1]) == 20
            for call in client.get_item_metadata_batch.await_args_list
        )
        assert len(removed) == 500
        assert "kept 200" in stats["reconcile_warning"]

    async def test_moves_out_are_verified_against_the_current_scope_path(
        self, reconciliation, index, mock_dependencies, ik
    ):
        def answer(item_id):
            path = "/RenamedScope/Deep" if int(item_id) % 2 else "/Elsewhere"
            return SharePointItemLookup(
                200, {"id": item_id, "parentReference": {"path": path}}
            )

        client = self._client(answer)
        client.get_file_metadata.return_value = {
            "id": "scope",
            "name": "RenamedScope",
            "parentReference": {"path": "/drives/d/root:"},
        }
        ids = [str(i) for i in range(30)]
        stats, removed = await self._reconcile(
            reconciliation, index, mock_dependencies, ik, ids, client, folder_id="scope"
        )
        assert removed == ids[::2]
        assert "kept 15" in stats["reconcile_warning"]

    @pytest.mark.parametrize("status", [429, 503])
    async def test_an_unavailable_scope_never_allows_cleanup(
        self, reconciliation, index, mock_dependencies, ik, status
    ):
        client = self._client(lambda _: SharePointItemLookup(404))
        client.get_file_metadata.side_effect = http_error(status, "unavailable")
        _, removed = await self._reconcile(
            reconciliation,
            index,
            mock_dependencies,
            ik,
            [str(i) for i in range(30)],
            client,
            folder_id="scope",
        )
        assert removed == []
        client.get_item_metadata_batch.assert_not_awaited()

    async def test_no_path_is_not_evidence_of_a_move(
        self, reconciliation, index, mock_dependencies, ik
    ):
        client = self._client(
            lambda item_id: SharePointItemLookup(200, {"id": item_id})
        )
        client.get_file_metadata.return_value = {
            "id": "scope",
            "name": "Scope",
            "parentReference": {"path": "/drives/d/root:"},
        }
        _, removed = await self._reconcile(
            reconciliation,
            index,
            mock_dependencies,
            ik,
            [str(i) for i in range(30)],
            client,
            folder_id="scope",
        )
        assert removed == []

    async def test_a_failed_batch_keeps_every_unverified_item(
        self, reconciliation, index, mock_dependencies, ik
    ):
        client = AsyncMock()
        client.get_item_metadata_batch.side_effect = ValueError(
            "Incomplete Graph metadata batch"
        )
        _, removed = await self._reconcile(
            reconciliation,
            index,
            mock_dependencies,
            ik,
            [str(i) for i in range(30)],
            client,
        )
        assert removed == []
        assert client.get_item_metadata_batch.await_count == 1
