"""Unit tests for SharePointContentService - content sync from SharePoint.

Tests the content pulling, delta change processing, and token handling
for SharePoint integrations. What one item writes (SharePointIndex), the
reconciliation and the sync results have test files of their own.
"""

import asyncio
import hashlib
import json
import logging
import unicodedata
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import aiohttp
import pytest
import sqlalchemy as sa
from aiohttp.client_reqrep import RequestInfo
from multidict import CIMultiDict, CIMultiDictProxy
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import event
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from yarl import URL

from eneo.integration.domain.entities.integration_knowledge import (
    IntegrationKnowledge,
)
from eneo.integration.infrastructure.clients.sharepoint_content_client import (
    DeltaTokenExpiredException,
    IncompleteDownloadError,
    MissingDownloadUrlError,
)
from eneo.integration.infrastructure.content_service import (
    sharepoint_content_service as content_service_module,
)
from eneo.integration.infrastructure.content_service import (
    sharepoint_index as index_module,
)
from eneo.integration.infrastructure.content_service import (
    sharepoint_reconciliation as reconciliation_module,
)
from eneo.integration.infrastructure.content_service import (
    sharepoint_results as sync_results,
)
from eneo.integration.infrastructure.content_service import (
    sharepoint_scope as scope_rules,
)
from eneo.integration.infrastructure.content_service.parsing import (
    extract_text_from_canvas_layout,
)
from eneo.integration.infrastructure.content_service.sharepoint_content_service import (
    SharePointContentService,
    SimpleSharePointToken,
)
from eneo.integration.infrastructure.content_service.sharepoint_results import (
    SyncAccessDenied,
    SyncItemsFailed,
)
from eneo.integration.infrastructure.content_service.sharepoint_scope import (
    ScopeFolderUnavailable,
)
from eneo.integration.infrastructure.content_service.utils import (
    EMPTY_CONTENT_REASON,
    NO_TEXT_LAYER_REASON,
    NO_TEXT_REASONS,
    PASSWORD_PROTECTED_REASON,
    ExtractionResult,
    extract_sharepoint_content,
)
from eneo.integration.infrastructure.sharepoint_sync_progress import (
    CLEAR_RUN_SCRIPT,
    FINISHED_TTL_SECONDS,
    SharePointSyncProgressStore,
    SyncProgressReporter,
    sync_progress_key,
)
from tests.unittests.integration.infrastructure.content_service.helpers import (
    delta_file,
    descendant,
    http_error,
    mock_graph_client,
    org_token_provider,
    real_integration_knowledge,
    reasons,
    size_ledger,
)
from tests.unittests.integration.sharepoint_fixtures import (
    XLSX_MIME,
    header_only_xlsx_bytes,
)


def _feed(files):
    """Name, outcome and text of each live-feed entry."""
    return [
        {
            "name": entry["name"],
            "outcome": entry["outcome"],
            "reason": entry.get("reason"),
        }
        for entry in files
    ]


ONE_FILE_FAILED = "1 file could not be processed; the next sync retries it"


class TestSimpleSharePointToken:
    """Tests for SimpleSharePointToken wrapper class."""

    def test_creates_token_with_access_token(self):
        """SimpleSharePointToken stores access_token."""
        token = SimpleSharePointToken(access_token="test-access-token-123")
        assert token.access_token == "test-access-token-123"

    def test_token_is_used_for_tenant_app_auth(self):
        """SimpleSharePointToken is used for tenant app integrations."""
        token = SimpleSharePointToken(access_token="tenant-app-token")
        assert hasattr(token, "access_token")


class TestTokenHandling:
    """Tests for token handling in pull_content."""

    async def test_uses_personal_oauth_token_when_token_id_provided(
        self, service, mock_dependencies, mock_oauth_token, mock_integration_knowledge
    ):
        """Uses OAuth token from repo when token_id is provided."""
        mock_dependencies["oauth_token_repo"].one.return_value = mock_oauth_token
        mock_dependencies[
            "integration_knowledge_repo"
        ].one.return_value = mock_integration_knowledge

        with patch(
            "eneo.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.get_default_drive_id.return_value = "drive-123"
            mock_client.get_drive_root_children.return_value = []
            mock_client.get_site_pages.return_value = {"value": []}
            mock_client.initialize_delta_token.return_value = "delta-token"
            mock_client_class.return_value = mock_client

            await service.pull_content(
                token_id=mock_oauth_token.id,
                integration_knowledge_id=mock_integration_knowledge.id,
                site_id="site-123",
            )

        mock_dependencies["oauth_token_repo"].one.assert_called_once_with(
            id=mock_oauth_token.id
        )

    async def test_raises_error_when_no_token_or_tenant_app_provided(
        self, service, mock_dependencies, mock_integration_knowledge
    ):
        """Raises ValueError when neither token_id nor tenant_app_id is provided."""
        mock_dependencies[
            "integration_knowledge_repo"
        ].one.return_value = mock_integration_knowledge

        with pytest.raises(
            ValueError, match="Either token_id or tenant_app_id must be provided"
        ):
            await service.pull_content(
                integration_knowledge_id=mock_integration_knowledge.id,
                site_id="site-123",
            )

    async def test_org_token_provider_supplies_token_and_reacquire_callback(
        self, mock_dependencies, mock_tenant_app, mock_integration_knowledge
    ):
        provider = org_token_provider("provider-token")
        reacquire = provider.access_token_provider.return_value
        mock_dependencies["org_token_provider"] = provider
        svc = SharePointContentService(**mock_dependencies)
        mock_dependencies[
            "tenant_sharepoint_app_repo"
        ].get_by_id.return_value = mock_tenant_app
        mock_dependencies[
            "integration_knowledge_repo"
        ].one.return_value = mock_integration_knowledge

        with patch(
            "eneo.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.get_default_drive_id.return_value = "drive-123"
            mock_client.get_drive_root_children.return_value = []
            mock_client.get_site_pages.return_value = {"value": []}
            mock_client.initialize_delta_token.return_value = "delta-token"
            mock_client_class.return_value = mock_client

            await svc.pull_content(
                tenant_app_id=mock_tenant_app.id,
                integration_knowledge_id=mock_integration_knowledge.id,
                site_id="site-123",
            )

        provider.get_access_token.assert_awaited_once_with(mock_tenant_app)
        assert mock_client_class.call_args_list
        for call in mock_client_class.call_args_list:
            assert call.kwargs["api_token"] == "provider-token"
            assert call.kwargs["access_token_provider"] is reacquire


class TestIsItemInFolderScope:
    """Tests for _is_item_in_folder_scope method."""

    def test_returns_true_when_no_scope_folder(self, service):
        """Returns True when scope_folder_id is None."""
        item = {"id": "item-1", "parentReference": {"id": "some-parent"}}

        result = scope_rules.is_item_in_folder_scope(item, scope_folder_id=None)

        assert result is True

    def test_returns_true_for_site_root_type(self, service):
        """Returns True when selected_item_type is site_root."""
        item = {"id": "item-1", "parentReference": {"id": "some-parent"}}

        result = scope_rules.is_item_in_folder_scope(
            item, scope_folder_id="folder-123", selected_item_type="site_root"
        )

        assert result is True

    def test_returns_true_when_selected_item_type_is_none(self, service):
        """Returns True when selected_item_type is None (defaults to include all)."""
        item = {"id": "item-1", "parentReference": {"id": "some-parent"}}

        result = scope_rules.is_item_in_folder_scope(
            item, scope_folder_id="folder-123", selected_item_type=None
        )

        assert result is True

    def test_returns_true_for_exact_file_match(self, service):
        """Returns True when item ID matches scope_folder_id for file type."""
        item = {"id": "file-123", "parentReference": {"id": "some-parent"}}

        result = scope_rules.is_item_in_folder_scope(
            item, scope_folder_id="file-123", selected_item_type="file"
        )

        assert result is True

    def test_returns_false_for_non_matching_file(self, service):
        """Returns False when item ID doesn't match for file type."""
        item = {"id": "other-file", "parentReference": {"id": "some-parent"}}

        result = scope_rules.is_item_in_folder_scope(
            item, scope_folder_id="file-123", selected_item_type="file"
        )

        assert result is False

    def test_returns_true_for_direct_child_of_folder(self, service):
        """Returns True when item is direct child of scope folder."""
        item = {"id": "child-1", "parentReference": {"id": "folder-123"}}

        result = scope_rules.is_item_in_folder_scope(
            item, scope_folder_id="folder-123", selected_item_type="folder"
        )

        assert result is True

    def test_returns_true_for_selected_folder_itself(self, service):
        """Returns True when a folder delta is for the selected folder itself."""
        item = {
            "id": "folder-123",
            "name": "Reports",
            "folder": {},
            "parentReference": {"id": "parent-folder"},
        }

        result = scope_rules.is_item_in_folder_scope(
            item, scope_folder_id="folder-123", selected_item_type="folder"
        )

        assert result is True

    def test_returns_true_for_known_subfolder_child(self, service):
        """Returns True when item is child of known subfolder."""
        item = {"id": "grandchild-1", "parentReference": {"id": "subfolder-1"}}
        known_subfolders = {"subfolder-1", "subfolder-2"}

        result = scope_rules.is_item_in_folder_scope(
            item,
            scope_folder_id="folder-123",
            selected_item_type="folder",
            known_subfolder_ids=known_subfolders,
        )

        assert result is True

    def test_returns_false_for_item_outside_folder_scope(self, service):
        """Returns False when item is not in folder hierarchy."""
        item = {"id": "orphan-1", "parentReference": {"id": "other-folder"}}

        result = scope_rules.is_item_in_folder_scope(
            item, scope_folder_id="folder-123", selected_item_type="folder"
        )

        assert result is False

    def test_matches_path_with_encoded_spaces(self, service):
        """Percent-encoded spaces in the Graph path match a decoded scope path."""
        item = {
            "id": "child-1",
            "parentReference": {
                "id": "subfolder-x",
                "path": "/drives/d/root:/Documents/My%20Files",
            },
        }

        result = scope_rules.is_item_in_folder_scope(
            item,
            scope_folder_id="folder-123",
            scope_folder_path="/Documents/My Files",
            selected_item_type="folder",
        )

        assert result is True

    def test_matches_path_with_encoded_non_ascii(self, service):
        """Percent-encoded å/ä/ö in the Graph path match a decoded scope path."""
        item = {
            "id": "child-1",
            "parentReference": {
                "id": "subfolder-x",
                # UTF-8 percent-encoding of "Åäö"
                "path": "/drives/d/root:/Dokument/%C3%85%C3%A4%C3%B6",
            },
        }

        result = scope_rules.is_item_in_folder_scope(
            item,
            scope_folder_id="folder-123",
            scope_folder_path="/Dokument/Åäö",
            selected_item_type="folder",
        )

        assert result is True

    def test_matches_path_with_nfd_unicode(self, service):
        """NFD-form Unicode in the Graph path matches an NFC-form scope path."""
        nfd_path = unicodedata.normalize("NFD", "/Dokument/Åäö")
        item = {
            "id": "child-1",
            "parentReference": {
                "id": "subfolder-x",
                "path": f"/drives/d/root:{nfd_path}",
            },
        }

        result = scope_rules.is_item_in_folder_scope(
            item,
            scope_folder_id="folder-123",
            # scope stored in NFC form
            scope_folder_path=unicodedata.normalize("NFC", "/Dokument/Åäö"),
            selected_item_type="folder",
        )

        assert result is True

    def test_matches_path_case_insensitively(self, service):
        """Mixed-case Graph path matches a differently-cased scope path."""
        item = {
            "id": "child-1",
            "parentReference": {
                "id": "subfolder-x",
                "path": "/drives/d/root:/documents/REPORTS",
            },
        }

        result = scope_rules.is_item_in_folder_scope(
            item,
            scope_folder_id="folder-123",
            scope_folder_path="/Documents/Reports",
            selected_item_type="folder",
        )

        assert result is True

    def test_matches_nested_descendant_path(self, service):
        """An item nested below the scope folder is in scope."""
        item = {
            "id": "child-1",
            "parentReference": {
                "id": "subfolder-x",
                "path": "/drives/d/root:/Documents/Reports/2024/Q1",
            },
        }

        result = scope_rules.is_item_in_folder_scope(
            item,
            scope_folder_id="folder-123",
            scope_folder_path="/Documents/Reports",
            selected_item_type="folder",
        )

        assert result is True

    def test_does_not_match_sibling_prefix_path(self, service):
        """A sibling whose name merely starts with the scope name is out of scope."""
        item = {
            "id": "child-1",
            "parentReference": {
                "id": "subfolder-x",
                "path": "/drives/d/root:/Documents/ReportsArchive",
            },
        }

        result = scope_rules.is_item_in_folder_scope(
            item,
            scope_folder_id="folder-123",
            scope_folder_path="/Documents/Reports",
            selected_item_type="folder",
        )

        assert result is False

    def test_matches_path_with_trailing_slash_in_scope(self, service):
        """A trailing slash on the scope path does not break matching."""
        item = {
            "id": "child-1",
            "parentReference": {
                "id": "subfolder-x",
                "path": "/drives/d/root:/Documents/Reports",
            },
        }

        result = scope_rules.is_item_in_folder_scope(
            item,
            scope_folder_id="folder-123",
            scope_folder_path="/Documents/Reports/",
            selected_item_type="folder",
        )

        assert result is True


class TestGetItemType:
    """Tests for _get_item_type method."""

    def test_returns_folder_for_folder_item(self, service):
        """Returns 'folder' for folder items."""
        item = {"name": "Documents", "folder": {"childCount": 5}}

        result = service._get_item_type(item)

        assert result == "folder"

    def test_returns_file_type_based_on_extension(self, service):
        """Returns file type based on extension."""
        item = {"name": "document.docx"}

        result = service._get_item_type(item)

        # The actual type depends on file_extension_to_type implementation
        assert result is not None
        assert result != "folder"


class TestDeltaChangesProcessing:
    """Tests for process_delta_changes method."""

    async def test_falls_back_to_full_sync_without_delta_token(
        self, service, mock_dependencies, mock_oauth_token, mock_integration_knowledge
    ):
        """Falls back to full sync when no delta token exists."""
        mock_integration_knowledge.delta_token = None
        mock_dependencies["oauth_token_repo"].one.return_value = mock_oauth_token
        mock_dependencies[
            "integration_knowledge_repo"
        ].one.return_value = mock_integration_knowledge

        with patch.object(service, "pull_content", new_callable=AsyncMock) as mock_pull:
            mock_pull.return_value = "Imported 5 files"

            result = await service.process_delta_changes(
                token_id=mock_oauth_token.id,
                integration_knowledge_id=mock_integration_knowledge.id,
                site_id="site-123",
            )

        mock_pull.assert_called_once()
        kwargs = mock_pull.call_args.kwargs
        assert kwargs["sync_trigger"] == "webhook"
        assert kwargs["recovery"] == "missing_delta_token"
        assert "Imported" in result

    async def test_falls_back_to_full_sync_when_delta_token_expired(
        self, service, mock_dependencies, mock_oauth_token, mock_integration_knowledge
    ):
        """Falls back to full sync when Microsoft Graph rejects the delta token."""
        mock_integration_knowledge.delta_token = "expired-delta-token"
        mock_integration_knowledge.drive_id = "drive-123"
        mock_dependencies["oauth_token_repo"].one.return_value = mock_oauth_token
        mock_dependencies[
            "integration_knowledge_repo"
        ].one.return_value = mock_integration_knowledge

        with (
            patch.object(service, "pull_content", new_callable=AsyncMock) as mock_pull,
            patch(
                "eneo.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
            ) as mock_client_class,
        ):
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.get_delta_changes.side_effect = DeltaTokenExpiredException()
            mock_client_class.return_value = mock_client
            mock_pull.return_value = "Imported 5 files"

            result = await service.process_delta_changes(
                token_id=mock_oauth_token.id,
                integration_knowledge_id=mock_integration_knowledge.id,
                site_id="site-123",
                drive_id="drive-123",
            )

        assert mock_integration_knowledge.delta_token is None
        mock_dependencies[
            "integration_knowledge_repo"
        ].update_sync_state.assert_any_await(
            mock_integration_knowledge.id, delta_token=None
        )
        mock_pull.assert_called_once()
        kwargs = mock_pull.call_args.kwargs
        assert kwargs["sync_trigger"] == "webhook"
        assert kwargs["recovery"] == "delta_token_expired"
        assert "Imported" in result

    async def test_processes_delta_changes_with_existing_token(
        self, service, mock_dependencies, mock_oauth_token, mock_integration_knowledge
    ):
        """Processes delta changes when delta token exists."""
        mock_integration_knowledge.delta_token = "existing-delta-token-123"
        mock_dependencies["oauth_token_repo"].one.return_value = mock_oauth_token
        mock_dependencies[
            "integration_knowledge_repo"
        ].one.return_value = mock_integration_knowledge

        with patch(
            "eneo.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.get_default_drive_id.return_value = "drive-123"
            mock_client.get_delta_changes.return_value = ([], "new-delta-token")
            mock_client_class.return_value = mock_client

            result = await service.process_delta_changes(
                token_id=mock_oauth_token.id,
                integration_knowledge_id=mock_integration_knowledge.id,
                site_id="site-123",
            )

        mock_client.get_delta_changes.assert_called_once()
        assert "Imported" in result

    async def test_updates_delta_token_after_processing(
        self, service, mock_dependencies, mock_oauth_token, mock_integration_knowledge
    ):
        """Updates delta token after processing changes."""
        mock_integration_knowledge.delta_token = "old-delta-token"
        mock_integration_knowledge.drive_id = "drive-123"
        mock_dependencies["oauth_token_repo"].one.return_value = mock_oauth_token
        mock_dependencies[
            "integration_knowledge_repo"
        ].one.return_value = mock_integration_knowledge

        with patch(
            "eneo.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.get_default_drive_id.return_value = "drive-123"
            mock_client.get_delta_changes.return_value = ([], "new-delta-token-xyz")
            mock_client_class.return_value = mock_client

            await service.process_delta_changes(
                token_id=mock_oauth_token.id,
                integration_knowledge_id=mock_integration_knowledge.id,
                site_id="site-123",
            )

        # Verify the delta token was updated
        assert mock_integration_knowledge.delta_token == "new-delta-token-xyz"
        written = mock_dependencies["integration_knowledge_repo"].update_sync_state
        assert written.await_args.kwargs["delta_token"] == "new-delta-token-xyz"

    async def test_deleted_delta_uses_sharepoint_item_id_for_delete(
        self, service, mock_dependencies, mock_oauth_token, mock_integration_knowledge
    ):
        """Deleted items should be removed by sharepoint_item_id, not by title."""
        mock_integration_knowledge.delta_token = "existing-delta-token-123"
        mock_integration_knowledge.drive_id = "drive-123"
        mock_integration_knowledge.selected_item_type = "site_root"
        mock_integration_knowledge.folder_id = None

        mock_dependencies["oauth_token_repo"].one.return_value = mock_oauth_token
        mock_dependencies[
            "integration_knowledge_repo"
        ].one.return_value = mock_integration_knowledge
        mock_dependencies[
            "info_blob_service"
        ].repo.delete_by_sharepoint_item_and_integration_knowledge = AsyncMock(
            return_value=[]
        )
        mock_dependencies[
            "info_blob_service"
        ].repo.delete_by_title_and_integration_knowledge = AsyncMock(return_value=[])

        with patch(
            "eneo.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.get_delta_changes.return_value = (
                [
                    {
                        "id": "item-123",
                        "name": "duplicate-name.docx",
                        "deleted": True,
                        "folder": False,
                    }
                ],
                "new-delta-token",
            )
            mock_client_class.return_value = mock_client

            await service.process_delta_changes(
                token_id=mock_oauth_token.id,
                integration_knowledge_id=mock_integration_knowledge.id,
                site_id="site-123",
                drive_id="drive-123",
            )

        mock_dependencies[
            "info_blob_service"
        ].repo.delete_by_sharepoint_item_and_integration_knowledge.assert_called_once_with(
            sharepoint_item_id="item-123",
            integration_knowledge_id=mock_integration_knowledge.id,
        )
        mock_dependencies[
            "info_blob_service"
        ].repo.delete_by_title_and_integration_knowledge.assert_not_called()

    async def test_deleted_delta_accepts_graph_deleted_facet_object(
        self, service, mock_dependencies, mock_oauth_token, mock_integration_knowledge
    ):
        """Graph deleted facets are objects, not always booleans."""
        mock_integration_knowledge.delta_token = "existing-delta-token-123"
        mock_integration_knowledge.drive_id = "drive-123"
        mock_integration_knowledge.selected_item_type = "site_root"
        mock_integration_knowledge.folder_id = None

        mock_dependencies["oauth_token_repo"].one.return_value = mock_oauth_token
        mock_dependencies[
            "integration_knowledge_repo"
        ].one.return_value = mock_integration_knowledge
        mock_dependencies[
            "info_blob_service"
        ].repo.delete_by_sharepoint_item_and_integration_knowledge = AsyncMock(
            return_value=[]
        )

        with patch(
            "eneo.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.get_delta_changes.return_value = (
                [
                    {
                        "id": "item-123",
                        "name": "deleted.docx",
                        "deleted": {},
                    }
                ],
                "new-delta-token",
            )
            mock_client_class.return_value = mock_client

            await service.process_delta_changes(
                token_id=mock_oauth_token.id,
                integration_knowledge_id=mock_integration_knowledge.id,
                site_id="site-123",
                drive_id="drive-123",
            )

        mock_dependencies[
            "info_blob_service"
        ].repo.delete_by_sharepoint_item_and_integration_knowledge.assert_called_once_with(
            sharepoint_item_id="item-123",
            integration_knowledge_id=mock_integration_knowledge.id,
        )
        mock_client.get_file_extraction_by_id.assert_not_called()

    async def test_deleted_delta_size_never_goes_below_zero(
        self, service, mock_dependencies, mock_oauth_token, mock_integration_knowledge
    ):
        """Deleted deltas clamp integration_knowledge.size at zero."""
        mock_integration_knowledge.delta_token = "existing-delta-token-123"
        mock_integration_knowledge.drive_id = "drive-123"
        mock_integration_knowledge.selected_item_type = "site_root"
        mock_integration_knowledge.folder_id = None
        mock_integration_knowledge.size = 10

        deleted_blob = MagicMock()
        deleted_blob.size = 25

        mock_dependencies["oauth_token_repo"].one.return_value = mock_oauth_token
        mock_dependencies[
            "integration_knowledge_repo"
        ].one.return_value = mock_integration_knowledge
        mock_dependencies[
            "info_blob_service"
        ].repo.delete_by_sharepoint_item_and_integration_knowledge = AsyncMock(
            return_value=[deleted_blob]
        )
        mock_dependencies[
            "info_blob_service"
        ].repo.delete_by_title_and_integration_knowledge = AsyncMock(return_value=[])

        with patch(
            "eneo.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.get_delta_changes.return_value = (
                [
                    {
                        "id": "item-123",
                        "name": "deleted.docx",
                        "deleted": True,
                        "folder": False,
                    }
                ],
                "new-delta-token",
            )
            mock_client_class.return_value = mock_client

            await service.process_delta_changes(
                token_id=mock_oauth_token.id,
                integration_knowledge_id=mock_integration_knowledge.id,
                site_id="site-123",
                drive_id="drive-123",
            )

        assert mock_integration_knowledge.size == 0

    async def test_unextractable_delta_deletes_existing_local_blob(
        self, service, mock_dependencies, mock_oauth_token, mock_integration_knowledge
    ):
        """Changed files that no longer extract should not leave stale RAG content."""
        mock_integration_knowledge.delta_token = "existing-delta-token-123"
        mock_integration_knowledge.drive_id = "drive-123"
        mock_integration_knowledge.selected_item_type = "site_root"
        mock_integration_knowledge.folder_id = None
        mock_integration_knowledge.size = 100

        deleted_blob = MagicMock()
        deleted_blob.size = 40

        mock_dependencies["oauth_token_repo"].one.return_value = mock_oauth_token
        mock_dependencies[
            "integration_knowledge_repo"
        ].one.return_value = mock_integration_knowledge
        mock_dependencies[
            "info_blob_service"
        ].repo.delete_by_sharepoint_item_and_integration_knowledge = AsyncMock(
            return_value=[deleted_blob]
        )

        with patch(
            "eneo.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.get_delta_changes.return_value = (
                [
                    {
                        "id": "item-123",
                        "name": "now-empty.docx",
                        "webUrl": "https://example.com/now-empty.docx",
                    }
                ],
                "new-delta-token",
            )
            mock_client.get_file_extraction_by_id.return_value = (
                ExtractionResult.no_text(EMPTY_CONTENT_REASON)
            )
            mock_client_class.return_value = mock_client

            with patch.object(service._index, "upsert", AsyncMock()) as mock_process:
                result = await service.process_delta_changes(
                    token_id=mock_oauth_token.id,
                    integration_knowledge_id=mock_integration_knowledge.id,
                    site_id="site-123",
                    drive_id="drive-123",
                )

        mock_process.assert_not_called()
        mock_dependencies[
            "info_blob_service"
        ].repo.delete_by_sharepoint_item_and_integration_knowledge.assert_called_once_with(
            sharepoint_item_id="item-123",
            integration_knowledge_id=mock_integration_knowledge.id,
        )
        assert mock_integration_knowledge.size == 60
        assert "1 deleted file" in result

    async def test_out_of_scope_delta_deletes_existing_local_blob(
        self, service, mock_dependencies, mock_oauth_token, mock_integration_knowledge
    ):
        """Moved files outside the selected folder scope are removed locally."""
        mock_integration_knowledge.delta_token = "existing-delta-token-123"
        mock_integration_knowledge.drive_id = "drive-123"
        mock_integration_knowledge.selected_item_type = "folder"
        mock_integration_knowledge.folder_id = "folder-a"
        mock_integration_knowledge.folder_path = "/Documents/A"
        mock_integration_knowledge.size = 100

        deleted_blob = MagicMock()
        deleted_blob.size = 40

        mock_dependencies["oauth_token_repo"].one.return_value = mock_oauth_token
        mock_dependencies[
            "integration_knowledge_repo"
        ].one.return_value = mock_integration_knowledge
        mock_dependencies[
            "info_blob_service"
        ].repo.delete_by_sharepoint_item_and_integration_knowledge = AsyncMock(
            return_value=[deleted_blob]
        )

        with patch(
            "eneo.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.get_file_metadata.return_value = {
                "id": "folder-a",
                "name": "A",
                "folder": {},
                "parentReference": {"path": "/drives/drive-123/root:/Documents"},
            }
            mock_client.get_delta_changes.return_value = (
                [
                    {
                        "id": "item-123",
                        "name": "moved.docx",
                        "parentReference": {
                            "id": "folder-b",
                            "path": "/drives/drive-123/root:/Documents/B",
                        },
                    }
                ],
                "new-delta-token",
            )
            mock_client_class.return_value = mock_client

            result = await service.process_delta_changes(
                token_id=mock_oauth_token.id,
                integration_knowledge_id=mock_integration_knowledge.id,
                site_id="site-123",
                drive_id="drive-123",
            )

        mock_dependencies[
            "info_blob_service"
        ].repo.delete_by_sharepoint_item_and_integration_knowledge.assert_called_once_with(
            sharepoint_item_id="item-123",
            integration_knowledge_id=mock_integration_knowledge.id,
        )
        mock_client.get_file_extraction_by_id.assert_not_called()
        assert mock_integration_knowledge.size == 60
        sync_log = mock_dependencies["sync_log_repo"].add.call_args[0][0]
        assert sync_log.metadata["trigger"] == "webhook"
        assert sync_log.metadata["changes_detected"] == 1
        assert sync_log.metadata["out_of_scope_deleted"] == 1
        assert "1 deleted file" in result

    async def test_selected_folder_delta_updates_folder_path_without_deleting_subtree(
        self, service, mock_dependencies, mock_oauth_token, mock_integration_knowledge
    ):
        """Rename/move deltas for the selected folder stay in scope."""
        mock_integration_knowledge.delta_token = "existing-delta-token-123"
        mock_integration_knowledge.drive_id = "drive-123"
        mock_integration_knowledge.selected_item_type = "folder"
        mock_integration_knowledge.folder_id = "folder-a"
        mock_integration_knowledge.folder_path = "/Documents/A"

        mock_dependencies["oauth_token_repo"].one.return_value = mock_oauth_token
        mock_dependencies[
            "integration_knowledge_repo"
        ].one.return_value = mock_integration_knowledge
        mock_dependencies[
            "info_blob_service"
        ].repo.delete_by_sharepoint_item_and_integration_knowledge = AsyncMock(
            return_value=[]
        )

        with patch(
            "eneo.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
        ) as mock_client_class:
            renamed_folder = {
                "id": "folder-a",
                "name": "A renamed",
                "folder": {},
                "parentReference": {
                    "id": "documents-folder",
                    "path": "/drives/drive-123/root:/Documents",
                },
            }
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.get_file_metadata.return_value = renamed_folder
            mock_client.get_delta_changes.return_value = (
                [renamed_folder],
                "new-delta-token",
            )
            mock_client_class.return_value = mock_client

            with patch.object(
                service._reconciliation, "remove_subtree", AsyncMock()
            ) as mock_delete_subtree:
                result = await service.process_delta_changes(
                    token_id=mock_oauth_token.id,
                    integration_knowledge_id=mock_integration_knowledge.id,
                    site_id="site-123",
                    drive_id="drive-123",
                )

        mock_dependencies[
            "info_blob_service"
        ].repo.delete_by_sharepoint_item_and_integration_knowledge.assert_not_called()
        mock_delete_subtree.assert_not_called()
        assert mock_integration_knowledge.folder_path == "/Documents/A renamed"
        assert "1 folder scanned" in result

    async def test_unresolved_legacy_folder_path_skips_uncertain_deletion(
        self, service, mock_dependencies, mock_oauth_token, mock_integration_knowledge
    ):
        """Do not delete nested content when a legacy folder scope cannot be
        resolved: the scope folder is gone (404), no path was stored, and the
        change set does not carry the folder itself."""
        mock_integration_knowledge.delta_token = "existing-delta-token-123"
        mock_integration_knowledge.drive_id = "drive-123"
        mock_integration_knowledge.selected_item_type = "folder"
        mock_integration_knowledge.folder_id = "folder-a"
        mock_integration_knowledge.folder_path = None

        mock_dependencies["oauth_token_repo"].one.return_value = mock_oauth_token
        mock_dependencies[
            "integration_knowledge_repo"
        ].one.return_value = mock_integration_knowledge
        mock_dependencies[
            "info_blob_service"
        ].repo.delete_by_sharepoint_item_and_integration_knowledge = AsyncMock(
            return_value=[]
        )

        with patch(
            "eneo.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.get_file_metadata.side_effect = http_error(404, "Not Found")
            mock_client.get_delta_changes.return_value = (
                [
                    {
                        "id": "item-123",
                        "name": "nested.docx",
                        "parentReference": {"id": "nested-folder"},
                    }
                ],
                "new-delta-token",
            )
            mock_client_class.return_value = mock_client

            result = await service.process_delta_changes(
                token_id=mock_oauth_token.id,
                integration_knowledge_id=mock_integration_knowledge.id,
                site_id="site-123",
                drive_id="drive-123",
            )

        mock_client.get_file_metadata.assert_called_once_with(
            drive_id="drive-123",
            item_id="folder-a",
        )
        mock_dependencies[
            "info_blob_service"
        ].repo.delete_by_sharepoint_item_and_integration_knowledge.assert_not_called()
        mock_client.get_file_extraction_by_id.assert_not_called()
        assert mock_integration_knowledge.folder_path is None
        assert "1 item skipped" in result
        sync_log = mock_dependencies["sync_log_repo"].add.call_args[0][0]
        # The item may sit outside the folder, so it is named by its id.
        assert reasons(sync_log.metadata["skipped_details"]) == [
            {"file": "item-123", "reason": "Folder scope path unavailable"}
        ]


class TestOneDriveFolderTraversal:
    """Tests for OneDrive-specific folder traversal."""

    async def test_onedrive_folder_fetch_uses_drive_endpoint(
        self, service, mock_dependencies, mock_oauth_token
    ):
        """Folder traversal for OneDrive must use drive-only endpoint."""
        mock_client = AsyncMock()
        mock_client.get_drive_folder_items = AsyncMock(return_value=[])
        mock_client.get_folder_items = AsyncMock(return_value=[])

        await service._fetch_and_process_content(
            site_id=None,
            drive_id="drive-123",
            resource_type="onedrive",
            integration_knowledge=MagicMock(id=uuid4()),
            client=mock_client,
            stats=sync_results.initialize_stats(),
            folder_id="folder-456",
            processed_items=set(),
        )

        mock_client.get_drive_folder_items.assert_called_once_with(
            drive_id="drive-123",
            folder_id="folder-456",
        )
        mock_client.get_folder_items.assert_not_called()

    @pytest.mark.parametrize("reason", sorted(NO_TEXT_REASONS))
    async def test_full_sync_no_text_file_deletes_existing_local_blob(
        self,
        service,
        mock_dependencies,
        mock_oauth_token,
        mock_integration_knowledge,
        reason,
    ):
        """A parser that completed and found nothing clears the stale blob."""
        mock_integration_knowledge.size = 100
        mock_dependencies[
            "integration_knowledge_repo"
        ].one.return_value = mock_integration_knowledge

        deleted_blob = MagicMock()
        deleted_blob.size = 40
        mock_dependencies[
            "info_blob_service"
        ].repo.delete_by_sharepoint_item_and_integration_knowledge = AsyncMock(
            return_value=[deleted_blob]
        )

        mock_client = AsyncMock()
        mock_client.get_file_extraction_by_id.return_value = ExtractionResult.no_text(
            reason
        )
        stats = sync_results.initialize_stats()

        with patch.object(service._index, "upsert", AsyncMock()) as mock_process:
            await service._process_folder_results(
                site_id="site-123",
                drive_id="drive-123",
                resource_type="site",
                client=mock_client,
                results=[
                    {
                        "id": "item-123",
                        "name": "slides.pptx",
                        "webUrl": "https://example.com/slides.pptx",
                        "parentReference": {"driveId": "drive-123"},
                    }
                ],
                integration_knowledge=mock_integration_knowledge,
                processed_items=set(),
                stats=stats,
            )

        mock_process.assert_not_called()
        mock_dependencies[
            "info_blob_service"
        ].repo.delete_by_sharepoint_item_and_integration_knowledge.assert_called_once_with(
            sharepoint_item_id="item-123",
            integration_knowledge_id=mock_integration_knowledge.id,
        )
        assert mock_integration_knowledge.size == 60
        assert stats["files_deleted"] == 1
        assert len(stats["skipped_details"]) == 1
        assert stats["skipped_details"][0]["file"] == "slides.pptx"
        assert stats["skipped_details"][0]["reason"] in NO_TEXT_REASONS

    @pytest.mark.parametrize(
        ("outcome", "expected_reason", "failed"),
        [
            (Exception("Graph timeout"), "Error: Graph timeout", True),
            (
                http_error(503, "Service Unavailable"),
                "Error: HTTP 503 Service Unavailable",
                True,
            ),
            (http_error(404, "Not Found"), "Error: HTTP 404 Not Found", False),
            (
                ExtractionResult.error("Corrupt or malformed file"),
                "Error: Corrupt or malformed file",
                False,
            ),
            (
                ExtractionResult.error(
                    "Incomplete download of 'still-readable.docx' (10 of 20 bytes)"
                ),
                "Error: Incomplete download of 'still-readable.docx' (10 of 20 bytes)",
                False,
            ),
            (
                ExtractionResult.skipped("Exceeds extraction limit (1000 PDF pages)"),
                "Exceeds extraction limit (1000 PDF pages)",
                False,
            ),
            (
                ExtractionResult.skipped("Unsupported file type (binary)"),
                "Unsupported file type (binary)",
                False,
            ),
        ],
    )
    async def test_full_sync_failure_does_not_delete_existing_local_blob(
        self,
        service,
        mock_dependencies,
        mock_oauth_token,
        mock_integration_knowledge,
        outcome,
        expected_reason,
        failed,
    ):
        """Errors, truncated downloads and limits are non-destructive skips;
        only Graph or network trouble counts as a failure of the pass."""
        mock_dependencies[
            "integration_knowledge_repo"
        ].one.return_value = mock_integration_knowledge
        mock_dependencies[
            "info_blob_service"
        ].repo.delete_by_sharepoint_item_and_integration_knowledge = AsyncMock(
            return_value=[]
        )

        mock_client = AsyncMock()
        if isinstance(outcome, Exception):
            mock_client.get_file_extraction_by_id.side_effect = outcome
        else:
            mock_client.get_file_extraction_by_id.return_value = outcome
        stats = sync_results.initialize_stats()

        with patch.object(service._index, "upsert", AsyncMock()) as mock_process:
            await service._process_folder_results(
                site_id="site-123",
                drive_id="drive-123",
                resource_type="site",
                client=mock_client,
                results=[
                    {
                        "id": "item-123",
                        "name": "still-readable.docx",
                        "webUrl": "https://example.com/still-readable.docx",
                        "parentReference": {"driveId": "drive-123"},
                    }
                ],
                integration_knowledge=mock_integration_knowledge,
                processed_items=set(),
                stats=stats,
            )

        mock_process.assert_not_called()
        mock_dependencies[
            "info_blob_service"
        ].repo.delete_by_sharepoint_item_and_integration_knowledge.assert_not_called()
        assert stats["files_deleted"] == 0
        assert stats["skipped_items"] == 1
        assert stats["failed_items"] == (1 if failed else 0)
        assert reasons(stats["skipped_details"]) == [
            {
                "file": "still-readable.docx",
                "reason": expected_reason,
                **({"retry": True} if failed else {}),
            }
        ]

    async def test_full_sync_keeps_a_workbook_whose_only_text_is_its_header_row(
        self,
        service,
        mock_dependencies,
        mock_oauth_token,
        mock_integration_knowledge,
    ):
        """The header row is text, so the indexed copy is replaced, not removed."""
        mock_dependencies[
            "integration_knowledge_repo"
        ].one.return_value = mock_integration_knowledge
        mock_dependencies[
            "info_blob_service"
        ].repo.delete_by_sharepoint_item_and_integration_knowledge = AsyncMock(
            return_value=[MagicMock(size=40)]
        )

        mock_client = AsyncMock()
        mock_client.get_file_extraction_by_id.return_value = (
            await extract_sharepoint_content(
                header_only_xlsx_bytes(), XLSX_MIME, "names.xlsx"
            )
        )
        stats = sync_results.initialize_stats()

        with patch.object(
            service._index, "upsert", AsyncMock(return_value="added")
        ) as mock_process:
            await service._process_folder_results(
                site_id="site-123",
                drive_id="drive-123",
                resource_type="site",
                client=mock_client,
                results=[
                    {
                        "id": "item-123",
                        "name": "names.xlsx",
                        "webUrl": "https://example.com/names.xlsx",
                        "parentReference": {"driveId": "drive-123"},
                    }
                ],
                integration_knowledge=mock_integration_knowledge,
                processed_items=set(),
                stats=stats,
            )

        mock_process.assert_awaited_once()
        assert (
            "Sheet: Budget | headers: Name | Value"
            in mock_process.await_args.kwargs["text"]
        )
        mock_dependencies[
            "info_blob_service"
        ].repo.delete_by_sharepoint_item_and_integration_knowledge.assert_not_called()
        assert stats["files_deleted"] == 0
        assert stats["files_processed"] == 1
        assert stats["skipped_details"] == []


class _FlushProbeBase(DeclarativeBase):
    pass


class _FlushProbe(_FlushProbeBase):
    __tablename__ = "flush_probe"
    id: Mapped[int] = mapped_column(primary_key=True)


def _fail_a_flush(session: Session) -> None:
    """Leave ``session`` as a failed top-level flush does: its transaction
    already rolled back, its rollback event already sent."""
    _FlushProbeBase.metadata.create_all(session.connection())
    session.execute(sa.insert(_FlushProbe).values(id=1))
    session.add(_FlushProbe(id=1))
    with pytest.raises(sa.exc.IntegrityError):
        session.flush()
    transaction = session.get_transaction()
    assert transaction is not None and not transaction.is_active


@pytest.fixture
def sqlite_session(mock_dependencies):
    engine = sa.create_engine("sqlite://")
    sync_session = Session(engine)
    mock_dependencies["session"].sync_session = sync_session
    yield sync_session
    sync_session.close()
    engine.dispose()


class TestPostCommitChangeKeys:
    """Tests for deferred ChangeKey cache writes."""

    async def test_flushes_change_keys_after_commit(
        self, service, mock_dependencies, sqlite_session
    ):
        """ChangeKeys are written after the SQLAlchemy transaction commits."""
        sqlite_session.begin()
        integration_knowledge_id = uuid4()
        update_change_key = mock_dependencies["change_key_service"].update_change_key

        service._schedule_post_commit_change_keys(
            [(integration_knowledge_id, "item-123", "etag-123")]
        )
        update_change_key.assert_not_called()

        sqlite_session.commit()
        await asyncio.gather(*service._post_transaction_tasks)

        update_change_key.assert_awaited_once_with(
            integration_knowledge_id=integration_knowledge_id,
            item_id="item-123",
            change_key="etag-123",
        )

    async def test_does_not_flush_change_keys_after_rollback(
        self, service, mock_dependencies, sqlite_session
    ):
        """Rolled-back syncs must not mark a ChangeKey as processed."""
        sync_session = sqlite_session
        # A transaction that did work, so its rollback is a real one.
        sync_session.begin()
        sync_session.execute(sa.text("SELECT 1"))
        rolled_back: list[Session] = []
        event.listen(sync_session, "after_rollback", rolled_back.append)

        service._schedule_post_commit_change_keys([(uuid4(), "item-123", "etag-123")])
        sync_session.rollback()
        await asyncio.sleep(0)

        assert rolled_back == [sync_session]
        assert not service._post_transaction_tasks
        mock_dependencies["change_key_service"].update_change_key.assert_not_called()

    async def test_change_keys_are_not_scheduled_once_a_flush_failed(
        self, service, mock_dependencies, sqlite_session
    ):
        """The transaction is gone; the items are re-processed next sync."""
        sqlite_session.begin()
        _fail_a_flush(sqlite_session)

        with patch("eneo.database.transaction_callbacks.event.listen") as listen:
            service._schedule_post_commit_change_keys([(uuid4(), "item-1", "ck-1")])

        listen.assert_not_called()

    async def test_the_transaction_end_runs_its_callback_once(
        self, service, sqlite_session
    ):
        """The listeners stay on the session; later transactions of the same
        session are not the end the callback waited for."""
        calls: list[str] = []

        async def callback() -> None:
            calls.append("ran")

        sqlite_session.begin()
        assert service._after_transaction(callback, on_rollback=True)
        sqlite_session.commit()
        for ending in ("commit", "rollback"):
            sqlite_session.begin()
            sqlite_session.execute(sa.text("SELECT 1"))
            getattr(sqlite_session, ending)()
        await asyncio.gather(*service._post_transaction_tasks)

        assert calls == ["ran"]

    @pytest.mark.parametrize("state", ["never begun", "rolled back by a flush"])
    def test_no_hook_without_an_active_transaction(
        self, service, sqlite_session, state
    ):
        if state == "rolled back by a flush":
            sqlite_session.begin()
            _fail_a_flush(sqlite_session)

        assert not service._after_transaction(AsyncMock(), on_rollback=True)

    async def test_a_savepoint_commit_does_not_flush_change_keys(
        self, service, mock_dependencies
    ):
        """A pending delta pass after the sync publishes blobs in savepoints;
        only the outer commit makes the first pass's work durable."""
        engine = sa.create_engine("sqlite://")
        sync_session = Session(engine)
        mock_dependencies["session"].sync_session = sync_session
        update_change_key = mock_dependencies["change_key_service"].update_change_key

        try:
            sync_session.begin()
            service._schedule_post_commit_change_keys([(uuid4(), "item-1", "ck-1")])

            with sync_session.begin_nested():
                sync_session.execute(sa.text("SELECT 1"))
            sync_session.begin_nested().rollback()
            await asyncio.sleep(0)
            update_change_key.assert_not_called()

            sync_session.commit()
            await asyncio.gather(*service._post_transaction_tasks)
            update_change_key.assert_awaited_once()
        finally:
            sync_session.close()
            engine.dispose()

    async def test_flush_change_keys_writes_each_pending_entry(
        self, service, mock_dependencies
    ):
        """Every accumulated (item_id, change_key) pair is written on flush."""
        ik_id = uuid4()
        pending = [
            (ik_id, "item-1", "ck-1"),
            (ik_id, "item-2", "ck-2"),
        ]

        await service._flush_change_keys(pending)

        change_key_service = mock_dependencies["change_key_service"]
        assert change_key_service.update_change_key.await_count == 2
        change_key_service.update_change_key.assert_any_await(
            integration_knowledge_id=ik_id, item_id="item-1", change_key="ck-1"
        )
        change_key_service.update_change_key.assert_any_await(
            integration_knowledge_id=ik_id, item_id="item-2", change_key="ck-2"
        )

    def test_schedule_is_noop_for_empty_pending(self, service):
        """No event listener is registered when there is nothing to flush."""
        with patch("eneo.database.transaction_callbacks.event.listen") as mock_listen:
            service._schedule_post_commit_change_keys([])

        mock_listen.assert_not_called()


class TestSyncLogging:
    """Tests for sync log creation."""

    async def test_creates_success_sync_log_when_files_processed(
        self, service, mock_dependencies, mock_oauth_token, mock_integration_knowledge
    ):
        """Creates success sync log when files are processed."""
        mock_dependencies["oauth_token_repo"].one.return_value = mock_oauth_token
        mock_dependencies[
            "integration_knowledge_repo"
        ].one.return_value = mock_integration_knowledge

        with patch(
            "eneo.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.get_default_drive_id.return_value = "drive-123"
            mock_client.get_drive_root_children.return_value = [
                {
                    "id": "file-1",
                    "name": "doc.txt",
                    "webUrl": "https://example.com/doc.txt",
                    "parentReference": {
                        "driveId": "drive-123",
                        "siteId": "site-123",
                    },
                }
            ]
            mock_client.get_site_pages.return_value = {"value": []}
            mock_client.get_file_extraction_by_id.return_value = ExtractionResult.ok(
                "File content", "text/plain"
            )
            mock_client.initialize_delta_token.return_value = "delta-token"
            mock_client_class.return_value = mock_client

            await service.pull_content(
                token_id=mock_oauth_token.id,
                integration_knowledge_id=mock_integration_knowledge.id,
                site_id="site-123",
            )

        mock_dependencies["sync_log_repo"].add.assert_called_once()
        sync_log = mock_dependencies["sync_log_repo"].add.call_args[0][0]
        assert sync_log.status == "success"
        assert sync_log.sync_type == "full"
        assert sync_log.metadata["trigger"] == "manual"
        assert sync_log.metadata["files_processed"] == 1

    async def test_creates_error_sync_log_on_exception(
        self, service, mock_dependencies, mock_oauth_token, mock_integration_knowledge
    ):
        """Creates error sync log when exception occurs."""
        mock_dependencies["oauth_token_repo"].one.return_value = mock_oauth_token
        mock_dependencies["integration_knowledge_repo"].one.side_effect = Exception(
            "Test error"
        )

        with pytest.raises(Exception, match="Test error"):
            await service.pull_content(
                token_id=mock_oauth_token.id,
                integration_knowledge_id=mock_integration_knowledge.id,
                site_id="site-123",
            )

        # Verify error sync log was created
        mock_dependencies["sync_log_repo"].add.assert_called_once()
        sync_log = mock_dependencies["sync_log_repo"].add.call_args[0][0]
        assert sync_log.status == "error"
        assert "Test error" in sync_log.error_message
        assert sync_log.metadata["trigger"] == "manual"


class TestTokenRefreshCallback:
    """Tests for token_refresh_callback method."""

    async def test_refreshes_and_returns_new_tokens(self, service, mock_dependencies):
        """Refreshes token and returns new access/refresh tokens."""
        token_id = uuid4()
        refreshed_token = MagicMock()
        refreshed_token.access_token = "new-access-token"
        refreshed_token.refresh_token = "new-refresh-token"

        mock_dependencies[
            "oauth_token_service"
        ].refresh_and_update_token.return_value = refreshed_token

        result = await service.token_refresh_callback(token_id)

        assert result["access_token"] == "new-access-token"
        assert result["refresh_token"] == "new-refresh-token"
        mock_dependencies[
            "oauth_token_service"
        ].refresh_and_update_token.assert_called_once_with(token_id=token_id)


class TestExtractTextFromCanvasLayout:
    def test_extracts_text_from_horizontal_sections(self):
        content = {
            "canvasLayout": {
                "horizontalSections": [
                    {
                        "columns": [
                            {
                                "webparts": [
                                    {
                                        "@odata.type": "#microsoft.graph.textWebPart",
                                        "innerHtml": "<p>Hello <b>world</b></p>",
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        }
        result = extract_text_from_canvas_layout(content)
        assert "Hello" in result
        assert "world" in result

    def test_extracts_text_from_vertical_section(self):
        content = {
            "canvasLayout": {
                "horizontalSections": [],
                "verticalSection": {
                    "webparts": [
                        {
                            "@odata.type": "#microsoft.graph.textWebPart",
                            "innerHtml": "<h1>Sidebar content</h1>",
                        }
                    ]
                },
            }
        }
        result = extract_text_from_canvas_layout(content)
        assert "Sidebar content" in result

    def test_ignores_non_text_webparts(self):
        content = {
            "canvasLayout": {
                "horizontalSections": [
                    {
                        "columns": [
                            {
                                "webparts": [
                                    {
                                        "@odata.type": "#microsoft.graph.standardWebPart",
                                        "data": {"some": "data"},
                                    },
                                    {
                                        "@odata.type": "#microsoft.graph.textWebPart",
                                        "innerHtml": "<p>Visible text</p>",
                                    },
                                ]
                            }
                        ]
                    }
                ]
            }
        }
        result = extract_text_from_canvas_layout(content)
        assert "Visible text" in result
        assert "data" not in result

    def test_returns_empty_string_when_no_canvas_layout(self):
        assert extract_text_from_canvas_layout({}) == ""
        assert extract_text_from_canvas_layout({"canvasLayout": None}) == ""

    def test_combines_multiple_sections(self):
        content = {
            "canvasLayout": {
                "horizontalSections": [
                    {
                        "columns": [
                            {
                                "webparts": [
                                    {
                                        "@odata.type": "#microsoft.graph.textWebPart",
                                        "innerHtml": "<p>First section</p>",
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        "columns": [
                            {
                                "webparts": [
                                    {
                                        "@odata.type": "#microsoft.graph.textWebPart",
                                        "innerHtml": "<p>Second section</p>",
                                    }
                                ]
                            }
                        ]
                    },
                ],
            }
        }
        result = extract_text_from_canvas_layout(content)
        assert "First section" in result
        assert "Second section" in result


class TestOutOfScopeFolderInADelta:
    """A changed folder outside the scope, as a delta pass meets it; the
    subtree cleanup itself is tested with SharePointReconciliation."""

    async def test_a_file_scope_never_walks_an_out_of_scope_folder(
        self, service, mock_dependencies, mock_oauth_token
    ):
        """Nothing under any folder is indexed for a file scope, so a changed
        folder elsewhere in the drive costs one no-op delete, not a subtree walk."""
        ik = real_integration_knowledge(
            delta_token="token-1", selected_item_type="file", folder_id="file-1"
        )
        mock_dependencies["oauth_token_repo"].one.return_value = mock_oauth_token
        mock_dependencies["integration_knowledge_repo"].one.return_value = ik
        delete = mock_dependencies[
            "info_blob_service"
        ].repo.delete_by_sharepoint_item_and_integration_knowledge = AsyncMock(
            return_value=[]
        )

        with (
            patch(
                "eneo.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
            ) as mock_client_class,
            patch.object(scope_rules, "enumerate_items", AsyncMock()) as enumerate_ids,
        ):
            mock_graph_client(
                mock_client_class,
                get_delta_changes=AsyncMock(
                    return_value=(
                        [{"id": "folder-z", "name": "Z", "folder": {}}],
                        "token-2",
                    )
                ),
            )
            await service.process_delta_changes(
                token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
            )

        enumerate_ids.assert_not_called()
        delete.assert_awaited_once_with(
            sharepoint_item_id="folder-z", integration_knowledge_id=ik.id
        )
        assert ik.delta_token == "token-2"


class TestFolderFullSyncRefreshesFolderPath:
    """Full-sync recovery must refresh a stale folder scope path.

    Regression: a folder-scoped integration recovers from an expired/missing
    delta token via a full sync. If the selected folder was renamed or moved
    during the token-invalid window, the stored folder_path is stale and is
    never re-emitted as a delta change. Leaving it stale makes the next delta
    misclassify valid nested descendants as out-of-scope and delete them.
    """

    def _folder_scoped_ik(self, mock_integration_knowledge):
        ik = mock_integration_knowledge
        ik.folder_id = "folder-a"
        ik.folder_path = "/Documents/A"  # stale, pre-rename
        ik.selected_item_type = "folder"
        ik.delta_token = None
        ik.drive_id = "drive-456"
        ik.site_id = "site-123"
        return ik

    async def test_refreshes_stale_folder_path_on_recovery(
        self, service, mock_dependencies, mock_oauth_token, mock_integration_knowledge
    ):
        """A renamed selected folder updates the stored folder_path."""
        ik = self._folder_scoped_ik(mock_integration_knowledge)
        mock_dependencies["oauth_token_repo"].one.return_value = mock_oauth_token
        mock_dependencies["integration_knowledge_repo"].one.return_value = ik

        with patch(
            "eneo.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.get_file_metadata.return_value = {
                "id": "folder-a",
                "name": "A renamed",
                "folder": {},
                "parentReference": {
                    "id": "documents-folder",
                    "path": "/drives/drive-456/root:/Documents",
                },
            }
            mock_client.initialize_delta_token.return_value = "new-delta-token"
            mock_client_class.return_value = mock_client

            with (
                patch.object(service, "_fetch_and_process_content", AsyncMock()),
                patch.object(service._reconciliation, "reconcile", AsyncMock()),
            ):
                await service.pull_content(
                    token_id=mock_oauth_token.id,
                    integration_knowledge_id=ik.id,
                    site_id="site-123",
                    drive_id="drive-456",
                    recovery="delta_token_expired",
                )

        assert ik.folder_path == "/Documents/A renamed"
        mock_dependencies[
            "integration_knowledge_repo"
        ].update_sync_state.assert_any_await(
            ik.id, selected_item_type="folder", folder_path="/Documents/A renamed"
        )

    async def test_keeps_folder_path_when_metadata_has_no_resolvable_path(
        self, service, mock_dependencies, mock_oauth_token, mock_integration_knowledge
    ):
        """A good stored path is never clobbered when metadata yields no path."""
        ik = self._folder_scoped_ik(mock_integration_knowledge)
        mock_dependencies["oauth_token_repo"].one.return_value = mock_oauth_token
        mock_dependencies["integration_knowledge_repo"].one.return_value = ik

        with patch(
            "eneo.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            # No parentReference / name -> _folder_path_from_item returns None.
            mock_client.get_file_metadata.return_value = {
                "id": "folder-a",
                "folder": {},
            }
            mock_client.initialize_delta_token.return_value = "new-delta-token"
            mock_client_class.return_value = mock_client

            with (
                patch.object(service, "_fetch_and_process_content", AsyncMock()),
                patch.object(service._reconciliation, "reconcile", AsyncMock()),
            ):
                await service.pull_content(
                    token_id=mock_oauth_token.id,
                    integration_knowledge_id=ik.id,
                    site_id="site-123",
                    drive_id="drive-456",
                    recovery="delta_token_expired",
                )

        assert ik.folder_path == "/Documents/A"


class TestProcessPages:
    """Site pages are isolated per item: one bad page never aborts the sync."""

    @staticmethod
    def _page(page_id: str) -> dict:
        return {
            "id": page_id,
            "name": f"{page_id}.aspx",
            "parentReference": {"siteId": "site-1"},
        }

    @pytest.mark.parametrize(
        "empty_content",
        [
            {"title": "Blank", "webUrl": "https://x/blank"},
            {"title": "Blank", "description": "   \n", "webUrl": "https://x/blank"},
        ],
        ids=["no-canvas-no-description", "whitespace-description"],
    )
    async def test_empty_page_is_skipped_and_loop_continues(
        self, service, mock_integration_knowledge, empty_content
    ):
        client = AsyncMock()
        client.get_page_content.side_effect = [
            empty_content,
            {
                "title": "Real",
                "description": "Some text",
                "webUrl": "https://x/real",
            },
        ]
        stats = sync_results.initialize_stats()

        with patch.object(
            service._index, "upsert", AsyncMock(return_value="added")
        ) as process:
            await service._process_pages(
                pages=[self._page("p-empty"), self._page("p-real")],
                client=client,
                integration_knowledge=mock_integration_knowledge,
                stats=stats,
            )

        assert process.await_count == 1
        assert process.await_args.kwargs["sharepoint_item_id"] == "p-real"
        assert stats["pages_processed"] == 1
        assert reasons(stats["skipped_details"]) == [
            {"file": "p-empty.aspx", "reason": "Empty or unreadable content"}
        ]

    async def test_failing_page_is_counted_and_loop_continues(
        self, service, mock_integration_knowledge
    ):
        client = AsyncMock()
        client.get_page_content.side_effect = [
            RuntimeError("Graph 500"),
            {"title": "Real", "description": "Some text", "webUrl": "https://x"},
        ]
        stats = sync_results.initialize_stats()

        with patch.object(
            service._index, "upsert", AsyncMock(return_value="added")
        ) as process:
            await service._process_pages(
                pages=[self._page("p-bad"), self._page("p-real")],
                client=client,
                integration_knowledge=mock_integration_knowledge,
                stats=stats,
            )

        assert process.await_count == 1
        assert stats["pages_processed"] == 1
        assert stats["skipped_items"] == 1
        assert stats["failed_items"] == 1
        assert reasons(stats["skipped_details"]) == [
            {"file": "p-bad.aspx", "reason": "Error: Graph 500", "retry": True}
        ]


class TestSyncStatus:
    """Every run records its outcome; a quiet run is still a successful one."""

    async def test_full_sync_with_nothing_changed_is_a_success_and_is_logged(
        self, service, mock_dependencies, mock_oauth_token
    ):
        ik = real_integration_knowledge()
        mock_dependencies["oauth_token_repo"].one.return_value = mock_oauth_token
        mock_dependencies["integration_knowledge_repo"].one.return_value = ik

        with patch(
            "eneo.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
        ) as mock_client_class:
            mock_graph_client(mock_client_class)
            await service.pull_content(
                token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
            )

        assert ik.last_sync_status == "success"
        assert ik.last_sync_error is None
        assert ik.last_sync_attempted_at is not None
        assert ik.last_synced_at is not None
        assert ik.last_synced_at >= ik.last_sync_attempted_at
        assert ik.last_sync_summary["files_processed"] == 0
        assert ik.last_sync_summary["skipped_total"] == 0
        assert ik.last_sync_summary["skipped_truncated"] is False
        sync_log = mock_dependencies["sync_log_repo"].add.call_args[0][0]
        assert sync_log.sync_type == "full"
        assert sync_log.status == "success"

    async def test_full_sync_failure_is_persisted_before_reraise(
        self, service, mock_dependencies, mock_oauth_token
    ):
        ik = real_integration_knowledge(last_synced_at=None)
        mock_dependencies["oauth_token_repo"].one.return_value = mock_oauth_token
        mock_dependencies["integration_knowledge_repo"].one.return_value = ik
        written = mock_dependencies["integration_knowledge_repo"].update_sync_state

        with patch.object(
            service, "_pull_content", AsyncMock(side_effect=RuntimeError("Graph 503"))
        ):
            with pytest.raises(RuntimeError, match="Graph 503"):
                await service.pull_content(
                    token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
                )

        assert ik.last_sync_status == "error"
        assert ik.last_sync_error == "Graph 503"
        assert ik.last_synced_at is None
        assert written.await_args.args == (ik.id,)
        assert written.await_args.kwargs == {
            "last_sync_status": "error",
            "last_sync_error": "Graph 503",
        }
        sync_log = mock_dependencies["sync_log_repo"].add.call_args[0][0]
        assert sync_log.status == "error"

    async def test_a_failed_full_sync_logs_what_it_changed_before_the_error(
        self, service, mock_dependencies, mock_oauth_token
    ):
        """The worker commits after a soft failure, so the blobs stay."""
        ik = real_integration_knowledge()
        mock_dependencies["oauth_token_repo"].one.return_value = mock_oauth_token
        mock_dependencies["integration_knowledge_repo"].one.return_value = ik

        async def index_then_fail(**kwargs):
            stats = kwargs["stats"]
            sync_results.count_outcome(stats, "added", "Beslut.pdf")
            stats["files_deleted"] += 1
            stats["skipped_items"] += 1
            stats["skipped_details"].append(
                {"file": "scan.pdf", "reason": NO_TEXT_LAYER_REASON}
            )
            raise RuntimeError("Graph 503")

        with patch.object(
            service, "_pull_content", AsyncMock(side_effect=index_then_fail)
        ):
            with pytest.raises(RuntimeError, match="Graph 503"):
                await service.pull_content(
                    token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
                )

        sync_log = mock_dependencies["sync_log_repo"].add.await_args.args[0]
        assert (sync_log.status, sync_log.sync_type) == ("error", "full")
        metadata = sync_log.metadata
        assert metadata["trigger"] == "manual"
        assert (metadata["files_processed"], metadata["files_deleted"]) == (1, 1)
        assert metadata["changed_details"] == [
            {"file": "Beslut.pdf", "change": "added"}
        ]
        assert (metadata["changed_total"], metadata["changed_truncated"]) == (1, False)
        assert reasons(metadata["skipped_details"]) == [
            {"file": "scan.pdf", "reason": NO_TEXT_LAYER_REASON}
        ]
        assert (metadata["skipped_total"], metadata["skipped_truncated"]) == (1, False)

    async def test_a_failed_delta_sync_logs_what_it_changed_before_the_error(
        self, service, mock_dependencies, mock_oauth_token
    ):
        ik = real_integration_knowledge(delta_token="token-1")
        mock_dependencies["oauth_token_repo"].one.return_value = mock_oauth_token
        mock_dependencies["integration_knowledge_repo"].one.return_value = ik

        # The start is recorded; writing the success fails; the failure is recorded.
        async def write(knowledge_id, **fields):
            if fields.get("last_sync_status") == "success":
                raise RuntimeError("db gone")

        mock_dependencies["integration_knowledge_repo"].update_sync_state = AsyncMock(
            side_effect=write
        )

        with (
            patch(
                "eneo.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
            ) as mock_client_class,
            patch.object(service._index, "upsert", AsyncMock(return_value="added")),
        ):
            mock_graph_client(
                mock_client_class,
                get_delta_changes=AsyncMock(
                    return_value=([delta_file("a", "a.docx")], "token-2")
                ),
                get_file_extraction_by_id=AsyncMock(
                    return_value=ExtractionResult.ok("Body")
                ),
            )
            with pytest.raises(RuntimeError, match="db gone"):
                await service.process_delta_changes(
                    token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
                )

        sync_log = mock_dependencies["sync_log_repo"].add.await_args.args[0]
        assert (sync_log.status, sync_log.sync_type) == ("error", "delta")
        assert sync_log.metadata["trigger"] == "webhook"
        assert sync_log.metadata["files_processed"] == 1
        assert sync_log.metadata["changed_details"] == [
            {"file": "a.docx", "change": "added"}
        ]
        assert sync_log.metadata["changed_total"] == 1

    @pytest.mark.parametrize("mode", ["full", "delta"])
    async def test_success_after_a_prior_error_clears_the_error(
        self, service, mock_dependencies, mock_oauth_token, mode
    ):
        ik = real_integration_knowledge(
            delta_token="token-1" if mode == "delta" else None,
            last_sync_status="error",
            last_sync_error="Graph 503",
            last_synced_at=None,
        )
        mock_dependencies["oauth_token_repo"].one.return_value = mock_oauth_token
        mock_dependencies["integration_knowledge_repo"].one.return_value = ik

        with patch(
            "eneo.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
        ) as mock_client_class:
            mock_graph_client(
                mock_client_class,
                get_delta_changes=AsyncMock(return_value=([], "token-2")),
            )
            if mode == "full":
                await service.pull_content(
                    token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
                )
            else:
                await service.process_delta_changes(
                    token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
                )

        assert ik.last_sync_status == "success"
        assert ik.last_sync_error is None
        assert ik.last_synced_at is not None

    async def test_delta_with_zero_changes_is_a_success_without_a_log(
        self, service, mock_dependencies, mock_oauth_token
    ):
        ik = real_integration_knowledge(delta_token="token-1")
        mock_dependencies["oauth_token_repo"].one.return_value = mock_oauth_token
        mock_dependencies["integration_knowledge_repo"].one.return_value = ik

        with patch(
            "eneo.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
        ) as mock_client_class:
            mock_graph_client(
                mock_client_class,
                get_delta_changes=AsyncMock(return_value=([], "token-2")),
            )
            await service.process_delta_changes(
                token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
            )

        assert ik.last_sync_status == "success"
        assert ik.last_synced_at is not None
        assert ik.delta_token == "token-2"
        mock_dependencies["sync_log_repo"].add.assert_not_called()

    async def test_delta_failure_is_persisted_before_reraise(
        self, service, mock_dependencies, mock_oauth_token
    ):
        ik = real_integration_knowledge(delta_token="token-1")
        mock_dependencies["oauth_token_repo"].one.return_value = mock_oauth_token
        mock_dependencies["integration_knowledge_repo"].one.return_value = ik
        written = mock_dependencies["integration_knowledge_repo"].update_sync_state

        with patch(
            "eneo.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
        ) as mock_client_class:
            mock_graph_client(
                mock_client_class,
                get_delta_changes=AsyncMock(side_effect=RuntimeError("throttled")),
            )
            with pytest.raises(RuntimeError, match="throttled"):
                await service.process_delta_changes(
                    token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
                )

        assert ik.last_sync_status == "error"
        assert ik.last_sync_error == "throttled"
        assert ik.last_sync_attempted_at is not None
        assert written.await_args.args == (ik.id,)
        assert written.await_args.kwargs == {
            "last_sync_status": "error",
            "last_sync_error": "throttled",
        }

    @pytest.mark.parametrize("mode", ["full", "delta"])
    async def test_a_pass_writes_only_sync_state_columns(
        self, service, mock_dependencies, mock_oauth_token, mode
    ):
        """The entity copy is minutes old by the end of a pass; a rename committed
        meanwhile survives because no pass writes the whole row."""
        ik = real_integration_knowledge(
            delta_token="token-1" if mode == "delta" else None
        )
        repo = mock_dependencies["integration_knowledge_repo"]
        mock_dependencies["oauth_token_repo"].one.return_value = mock_oauth_token
        repo.one.return_value = ik

        with patch(
            "eneo.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
        ) as mock_client_class:
            mock_graph_client(
                mock_client_class,
                get_delta_changes=AsyncMock(return_value=([], "token-2")),
            )
            if mode == "full":
                await service.pull_content(
                    token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
                )
            else:
                await service.process_delta_changes(
                    token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
                )

        repo.update.assert_not_awaited()
        assert repo.update_sync_state.await_count >= 2
        for call in repo.update_sync_state.await_args_list:
            assert call.args == (ik.id,)
            assert "name" not in call.kwargs and "wrapper_name" not in call.kwargs

    async def test_unrecorded_delta_failure_leaves_the_owning_sync_status(
        self, service, mock_dependencies, mock_oauth_token
    ):
        ik = real_integration_knowledge(
            delta_token="token-1", last_sync_status="success"
        )
        mock_dependencies["oauth_token_repo"].one.return_value = mock_oauth_token
        mock_dependencies["integration_knowledge_repo"].one.return_value = ik

        with patch(
            "eneo.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
        ) as mock_client_class:
            mock_graph_client(
                mock_client_class,
                get_delta_changes=AsyncMock(side_effect=RuntimeError("throttled")),
            )
            with pytest.raises(RuntimeError, match="throttled"):
                await service.process_delta_changes(
                    token_id=mock_oauth_token.id,
                    integration_knowledge_id=ik.id,
                    record_failure=False,
                )

        assert ik.last_sync_status == "success"
        assert ik.last_sync_error is None
        mock_dependencies["sync_log_repo"].add.assert_not_awaited()

    @pytest.mark.parametrize("processed_something", [False, True])
    async def test_a_quiet_pending_pass_keeps_the_owning_syncs_summary(
        self, service, mock_dependencies, mock_oauth_token, processed_something
    ):
        """The pending pass follows the full sync the person is looking at; its
        empty summary must not replace "300 files imported". A pending pass that
        did process something reports it."""
        owning_summary = {"files_processed": 300, "skipped_total": 0}
        ik = real_integration_knowledge(
            delta_token="token-1",
            last_sync_status="success",
            last_sync_summary=owning_summary,
        )
        mock_dependencies["oauth_token_repo"].one.return_value = mock_oauth_token
        mock_dependencies["integration_knowledge_repo"].one.return_value = ik
        changes = [delta_file("item-1", "a.docx")] if processed_something else []

        with (
            patch(
                "eneo.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
            ) as mock_client_class,
            patch.object(service._index, "upsert", AsyncMock(return_value="added")),
        ):
            mock_graph_client(
                mock_client_class,
                get_delta_changes=AsyncMock(return_value=(changes, "token-2")),
                get_file_extraction_by_id=AsyncMock(
                    return_value=ExtractionResult.ok("Body")
                ),
            )
            await service.process_delta_changes(
                token_id=mock_oauth_token.id,
                integration_knowledge_id=ik.id,
                record_failure=False,
            )

        written = mock_dependencies["integration_knowledge_repo"].update_sync_state
        assert ik.delta_token == "token-2"
        assert ik.last_sync_status == "success"
        assert ik.last_sync_attempted_at is not None
        if processed_something:
            assert ik.last_sync_summary["files_processed"] == 1
            assert (
                written.await_args.kwargs["last_sync_summary"] == ik.last_sync_summary
            )
        else:
            assert ik.last_sync_summary == owning_summary
            assert "last_sync_summary" not in written.await_args.kwargs

    @pytest.mark.parametrize(
        ("delta_token", "delta_outcome", "recovery", "record_failure"),
        [
            (None, None, "missing_delta_token", True),
            (
                "token-1",
                DeltaTokenExpiredException("410"),
                "delta_token_expired",
                True,
            ),
            # A pending pass does not record its own failure, but the recovery
            # full sync it delegated to was attempted and cleared the token.
            (
                "token-1",
                DeltaTokenExpiredException("410"),
                "delta_token_expired",
                False,
            ),
        ],
    )
    async def test_a_failed_full_sync_fallback_is_recorded_once(
        self,
        service,
        mock_dependencies,
        mock_oauth_token,
        delta_token,
        delta_outcome,
        recovery,
        record_failure,
    ):
        ik = real_integration_knowledge(
            delta_token=delta_token, last_sync_status="success"
        )
        mock_dependencies["oauth_token_repo"].one.return_value = mock_oauth_token
        mock_dependencies["integration_knowledge_repo"].one.return_value = ik

        with (
            patch(
                "eneo.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
            ) as mock_client_class,
            patch.object(
                service,
                "_pull_content",
                AsyncMock(side_effect=RuntimeError("Graph 503")),
            ),
        ):
            mock_graph_client(
                mock_client_class,
                get_delta_changes=AsyncMock(side_effect=delta_outcome),
            )
            with pytest.raises(RuntimeError, match="Graph 503"):
                await service.process_delta_changes(
                    token_id=mock_oauth_token.id,
                    integration_knowledge_id=ik.id,
                    record_failure=record_failure,
                )

        assert ik.delta_token is None
        assert ik.last_sync_status == "error"
        assert ik.last_sync_error == "Graph 503"
        add = mock_dependencies["sync_log_repo"].add
        add.assert_awaited_once()
        sync_log = add.await_args.args[0]
        assert sync_log.status == "error"
        assert sync_log.sync_type == "full"
        assert sync_log.metadata["recovery"] == recovery

    async def test_failure_is_logged_even_when_the_status_row_cannot_be_written(
        self, service, mock_dependencies, mock_oauth_token
    ):
        ik = real_integration_knowledge()
        mock_dependencies["oauth_token_repo"].one.return_value = mock_oauth_token
        mock_dependencies["integration_knowledge_repo"].one.side_effect = [
            ik,
            RuntimeError("db gone"),
        ]

        with patch.object(
            service, "_pull_content", AsyncMock(side_effect=RuntimeError("Graph 503"))
        ):
            with pytest.raises(RuntimeError, match="Graph 503"):
                await service.pull_content(
                    token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
                )

        sync_log = mock_dependencies["sync_log_repo"].add.await_args.args[0]
        assert sync_log.status == "error"
        assert sync_log.error_message == "Graph 503"

    async def test_a_failing_sync_log_write_never_replaces_the_error(
        self, service, mock_dependencies, mock_oauth_token
    ):
        ik = real_integration_knowledge()
        mock_dependencies["oauth_token_repo"].one.return_value = mock_oauth_token
        mock_dependencies["integration_knowledge_repo"].one.return_value = ik
        mock_dependencies["sync_log_repo"].add.side_effect = RuntimeError(
            "sync_logs locked"
        )

        with patch.object(
            service, "_pull_content", AsyncMock(side_effect=RuntimeError("Graph 503"))
        ):
            with pytest.raises(RuntimeError, match="Graph 503"):
                await service.pull_content(
                    token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
                )

        assert ik.last_sync_status == "error"
        assert ik.last_sync_error == "Graph 503"

    @pytest.mark.parametrize("mode", ["full", "delta"])
    async def test_a_failing_sync_log_write_does_not_flip_a_finished_success(
        self, service, mock_dependencies, mock_oauth_token, mode
    ):
        """Blobs, status and token are written before the log; the log is a record
        of the pass, not part of it."""
        ik = real_integration_knowledge(
            delta_token="token-1" if mode == "delta" else None
        )
        mock_dependencies["oauth_token_repo"].one.return_value = mock_oauth_token
        mock_dependencies["integration_knowledge_repo"].one.return_value = ik
        mock_dependencies[
            "info_blob_service"
        ].repo.get_sharepoint_item_ids_for_integration_knowledge = AsyncMock(
            return_value=[]
        )
        add = mock_dependencies["sync_log_repo"].add
        add.side_effect = RuntimeError("sync_logs locked")
        listing = [delta_file("item-1", "a.docx")]

        with (
            patch(
                "eneo.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
            ) as mock_client_class,
            patch.object(service._index, "upsert", AsyncMock(return_value="added")),
        ):
            mock_graph_client(
                mock_client_class,
                get_drive_root_children=AsyncMock(return_value=listing),
                get_delta_changes=AsyncMock(return_value=(listing, "token-2")),
                get_file_extraction_by_id=AsyncMock(
                    return_value=ExtractionResult.ok("Body")
                ),
            )
            if mode == "full":
                result = await service.pull_content(
                    token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
                )
            else:
                result = await service.process_delta_changes(
                    token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
                )

        add.assert_awaited_once()
        assert result == "Imported 1 file"
        assert ik.last_sync_status == "success"
        assert ik.last_sync_error is None
        assert ik.delta_token == ("token-2" if mode == "delta" else "delta-token")
        written = mock_dependencies["integration_knowledge_repo"].update_sync_state
        assert written.await_args.kwargs["last_sync_status"] == "success"

    @pytest.mark.parametrize("mode", ["full", "delta"])
    async def test_a_partial_pass_is_a_warning_without_a_stack_trace(
        self, service, mock_dependencies, mock_oauth_token, mode
    ):
        ik = real_integration_knowledge(
            delta_token="token-1" if mode == "delta" else None
        )
        mock_dependencies["oauth_token_repo"].one.return_value = mock_oauth_token
        mock_dependencies["integration_knowledge_repo"].one.return_value = ik
        mock_dependencies[
            "info_blob_service"
        ].repo.get_sharepoint_item_ids_for_integration_knowledge = AsyncMock(
            return_value=[]
        )
        listing = [delta_file("item-1", "a.docx")]

        with (
            patch(
                "eneo.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
            ) as mock_client_class,
            patch(
                "eneo.integration.infrastructure.content_service.sharepoint_content_service.logger"
            ) as log,
            pytest.raises(SyncItemsFailed, match=ONE_FILE_FAILED),
        ):
            mock_graph_client(
                mock_client_class,
                get_drive_root_children=AsyncMock(return_value=listing),
                get_delta_changes=AsyncMock(return_value=(listing, "token-2")),
                get_file_extraction_by_id=AsyncMock(
                    side_effect=http_error(503, "Service Unavailable")
                ),
            )
            if mode == "full":
                await service.pull_content(
                    token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
                )
            else:
                await service.process_delta_changes(
                    token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
                )

        assert any(
            isinstance(call.args[-1], SyncItemsFailed)
            for call in log.warning.call_args_list
        )
        assert not any(
            isinstance(call.args[-1], SyncItemsFailed)
            for call in log.error.call_args_list
        )

    async def test_reconcile_warning_reaches_summary_and_sync_log(
        self, service, mock_dependencies, mock_oauth_token
    ):
        ik = real_integration_knowledge()
        mock_dependencies["oauth_token_repo"].one.return_value = mock_oauth_token
        mock_dependencies["integration_knowledge_repo"].one.return_value = ik

        async def refuse(*, stats, **_):
            stats["reconcile_warning"] = "Orphan cleanup skipped: 9 of 10 missing"

        with (
            patch(
                "eneo.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
            ) as mock_client_class,
            patch.object(service._reconciliation, "reconcile", refuse),
        ):
            mock_graph_client(mock_client_class)
            await service.pull_content(
                token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
            )

        assert ik.last_sync_status == "success"
        assert (
            ik.last_sync_summary["reconcile_warning"]
            == "Orphan cleanup skipped: 9 of 10 missing"
        )
        sync_log = mock_dependencies["sync_log_repo"].add.call_args[0][0]
        assert (
            sync_log.metadata["reconcile_warning"]
            == "Orphan cleanup skipped: 9 of 10 missing"
        )


class TestDeltaBaseline:
    """The baseline precedes enumeration: a change made while the full sync is
    listing folders is replayed by the first delta instead of lost."""

    async def test_change_during_enumeration_is_seen_by_the_first_delta(
        self, service, mock_dependencies, mock_oauth_token
    ):
        ik = real_integration_knowledge()
        mock_dependencies["oauth_token_repo"].one.return_value = mock_oauth_token
        mock_dependencies["integration_knowledge_repo"].one.return_value = ik
        mock_dependencies[
            "info_blob_service"
        ].repo.get_sharepoint_item_ids_for_integration_knowledge = AsyncMock(
            return_value=[]
        )
        drive_log: list[dict] = []

        async def mint(drive_id):
            return f"seq:{len(drive_log)}"

        async def list_root(drive_id):
            # An edit lands while the folder is first listed; the listing
            # returned to the sync predates it.
            if not drive_log:
                drive_log.append(delta_file("late-1", "late.docx"))
            return []

        async def delta(drive_id, delta_token):
            since = int(delta_token.removeprefix("seq:"))
            return drive_log[since:], f"seq:{len(drive_log)}"

        with (
            patch(
                "eneo.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
            ) as mock_client_class,
            patch.object(service._index, "upsert", AsyncMock(return_value="added")),
        ):
            client = mock_graph_client(
                mock_client_class,
                initialize_delta_token=AsyncMock(side_effect=mint),
                get_drive_root_children=AsyncMock(side_effect=list_root),
                get_delta_changes=AsyncMock(side_effect=delta),
                get_file_extraction_by_id=AsyncMock(
                    return_value=ExtractionResult.ok("Body")
                ),
            )
            await service.pull_content(
                token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
            )
            assert ik.delta_token == "seq:0"
            result = await service.process_delta_changes(
                token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
            )

        client.get_file_extraction_by_id.assert_awaited_once_with(
            drive_id="drive-456", item_id="late-1"
        )
        assert "1 file" in result
        assert ik.delta_token == "seq:1"


class TestFullSyncUsesStoredDrive:
    """Enumeration and reconciliation run against the drive the knowledge is bound to."""

    async def test_root_listing_and_reconciliation_use_the_stored_drive(
        self, service, mock_dependencies, mock_oauth_token
    ):
        ik = real_integration_knowledge(drive_id="drive-stored")
        mock_dependencies["oauth_token_repo"].one.return_value = mock_oauth_token
        mock_dependencies["integration_knowledge_repo"].one.return_value = ik
        mock_dependencies[
            "info_blob_service"
        ].repo.get_sharepoint_item_ids_for_integration_knowledge = AsyncMock(
            return_value=[]
        )

        with patch(
            "eneo.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
        ) as mock_client_class:
            client = mock_graph_client(mock_client_class)
            client.get_default_drive_id.return_value = "drive-default"
            await service.pull_content(
                token_id=mock_oauth_token.id,
                integration_knowledge_id=ik.id,
                site_id="site-123",
            )

        listed_drives = {
            call.args[0] for call in client.get_drive_root_children.await_args_list
        }
        assert listed_drives == {"drive-stored"}
        client.get_default_drive_id.assert_not_called()


class TestDeltaFolderScopeOrdering:
    """Scope decisions use the scope folder's newest path, whatever Graph's order."""

    @pytest.fixture
    def folder_scoped(self, mock_integration_knowledge):
        mock_integration_knowledge.delta_token = "existing-delta-token-123"
        mock_integration_knowledge.drive_id = "drive-123"
        mock_integration_knowledge.selected_item_type = "folder"
        mock_integration_knowledge.folder_id = "folder-a"
        mock_integration_knowledge.folder_path = "/Documents/A"
        return mock_integration_knowledge

    async def _run_delta(
        self,
        service,
        mock_dependencies,
        mock_oauth_token,
        ik,
        changes,
        folder_metadata=None,
    ):
        """Without ``folder_metadata`` Graph answers 404 for the scope folder, so
        the pass has only the stored path and the folder's own delta entry; an
        exception is what the metadata read raises, a function answers per item."""
        mock_dependencies["oauth_token_repo"].one.return_value = mock_oauth_token
        mock_dependencies["integration_knowledge_repo"].one.return_value = ik
        mock_dependencies[
            "info_blob_service"
        ].repo.delete_by_sharepoint_item_and_integration_knowledge = AsyncMock(
            return_value=[]
        )
        if folder_metadata is None:
            folder_metadata = http_error(404, "Not Found")
        with patch(
            "eneo.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
        ) as mock_client_class:
            client = mock_graph_client(
                mock_client_class,
                get_delta_changes=AsyncMock(return_value=(changes, "new-token")),
                get_file_metadata=(
                    AsyncMock(side_effect=folder_metadata)
                    if isinstance(folder_metadata, Exception)
                    or callable(folder_metadata)
                    else AsyncMock(return_value=folder_metadata)
                ),
                get_file_extraction_by_id=AsyncMock(
                    return_value=ExtractionResult.ok("text", "text/plain")
                ),
            )
            result = await service.process_delta_changes(
                token_id=mock_oauth_token.id,
                integration_knowledge_id=ik.id,
                site_id="site-123",
                drive_id="drive-123",
            )
        return client, result

    async def test_descendant_listed_before_renamed_scope_folder_stays_in_scope(
        self, service, mock_dependencies, mock_oauth_token, folder_scoped
    ):
        changes = [
            {
                "id": "nested-1",
                "name": "nested.docx",
                "webUrl": "https://x/nested.docx",
                "parentReference": {
                    "id": "sub-folder",
                    "path": "/drives/drive-123/root:/Documents/A renamed/Sub",
                },
            },
            {
                "id": "folder-a",
                "name": "A renamed",
                "folder": {},
                "parentReference": {
                    "id": "documents-folder",
                    "path": "/drives/drive-123/root:/Documents",
                },
            },
        ]

        client, result = await self._run_delta(
            service, mock_dependencies, mock_oauth_token, folder_scoped, changes
        )

        mock_dependencies[
            "info_blob_service"
        ].repo.delete_by_sharepoint_item_and_integration_knowledge.assert_not_called()
        client.get_file_extraction_by_id.assert_awaited_once_with(
            drive_id="drive-123", item_id="nested-1"
        )
        assert folder_scoped.folder_path == "/Documents/A renamed"
        assert "1 file" in result

    async def test_renamed_ancestor_keeps_the_scope_folder_in_scope(
        self, service, mock_dependencies, mock_oauth_token, folder_scoped
    ):
        """Graph emits the renamed ancestor, never the unchanged scope folder, so
        the current path comes from the folder's metadata, not from the changes."""
        changes = [
            {
                "id": "nested-1",
                "name": "nested.docx",
                "webUrl": "https://x/nested.docx",
                "parentReference": {
                    "id": "sub-folder",
                    "path": "/drives/drive-123/root:/Docs renamed/A/Sub",
                },
            }
        ]
        scope_folder_now = {
            "id": "folder-a",
            "name": "A",
            "folder": {},
            "parentReference": {
                "id": "documents-folder",
                "path": "/drives/drive-123/root:/Docs renamed",
            },
        }

        client, result = await self._run_delta(
            service,
            mock_dependencies,
            mock_oauth_token,
            folder_scoped,
            changes,
            folder_metadata=scope_folder_now,
        )

        client.get_file_metadata.assert_awaited_once_with(
            drive_id="drive-123", item_id="folder-a"
        )
        mock_dependencies[
            "info_blob_service"
        ].repo.delete_by_sharepoint_item_and_integration_knowledge.assert_not_called()
        client.get_file_extraction_by_id.assert_awaited_once_with(
            drive_id="drive-123", item_id="nested-1"
        )
        assert folder_scoped.folder_path == "/Docs renamed/A"
        assert "1 file" in result

    @pytest.mark.parametrize(
        ("ancestor_name", "scope_path_now"),
        [("Documents", "/Documents/A"), ("Docs renamed", "/Docs renamed/A")],
        ids=["parent chain of a change", "renamed ancestor"],
    )
    async def test_an_ancestor_entry_is_neither_cleaned_up_nor_walked(
        self,
        service,
        mock_dependencies,
        mock_oauth_token,
        folder_scoped,
        ancestor_name,
        scope_path_now,
    ):
        """Graph lists the parent chain of a changed item and emits a renamed
        ancestor on its own. An ancestor is above the scope, not out of it: its
        subtree holds the scope's documents and nothing of its own is indexed."""
        changes = [
            {
                "id": "documents-folder",
                "name": ancestor_name,
                "folder": {"childCount": 3},
                "parentReference": {"id": "root-id", "path": "/drives/drive-123/root:"},
            },
            {
                "id": "nested-1",
                "name": "nested.docx",
                "webUrl": "https://x/nested.docx",
                "parentReference": {
                    "id": "sub-folder",
                    "path": f"/drives/drive-123/root:{scope_path_now}/Sub",
                },
            },
        ]
        scope_folder_now = {
            "id": "folder-a",
            "name": "A",
            "folder": {},
            "parentReference": {
                "id": "documents-folder",
                "path": f"/drives/drive-123/root:/{ancestor_name}",
            },
        }

        client, result = await self._run_delta(
            service,
            mock_dependencies,
            mock_oauth_token,
            folder_scoped,
            changes,
            folder_metadata=scope_folder_now,
        )

        mock_dependencies[
            "info_blob_service"
        ].repo.delete_by_sharepoint_item_and_integration_knowledge.assert_not_called()
        client.get_folder_items.assert_not_awaited()
        client.get_file_extraction_by_id.assert_awaited_once_with(
            drive_id="drive-123", item_id="nested-1"
        )
        assert folder_scoped.folder_path == scope_path_now
        assert folder_scoped.delta_token == "new-token"
        assert "1 file" in result

    async def test_cleaning_a_folder_that_left_scope_keeps_descendants_inside_it(
        self, service, mock_dependencies, mock_oauth_token, folder_scoped
    ):
        """The folder's own parent path decides its fate; each descendant is
        placed against the scope before its documents go, and one Graph cannot
        place stays for the next full sync to reconcile."""
        changes = [
            {
                "id": "folder-b",
                "name": "B",
                "folder": {},
                "parentReference": {
                    "id": "documents-folder",
                    "path": "/drives/drive-123/root:/Documents",
                },
            }
        ]
        descendants = [
            {
                "id": "b-file",
                "name": "b.docx",
                "file": {},
                "parentReference": {
                    "id": "folder-b",
                    "path": "/drives/drive-123/root:/Documents/B",
                },
            },
            {
                "id": "a-file",
                "name": "a.docx",
                "file": {},
                "parentReference": {
                    "id": "sub-folder",
                    "path": "/drives/drive-123/root:/Documents/A/Sub",
                },
            },
            {"id": "unplaced", "name": "x.docx", "file": {}, "parentReference": {}},
        ]
        mock_dependencies[
            "info_blob_service"
        ].repo.get_sharepoint_item_ids_for_integration_knowledge = AsyncMock(
            return_value=[(uuid4(), item["id"]) for item in descendants]
        )
        scope_folder_now = {
            "id": "folder-a",
            "name": "A",
            "folder": {},
            "parentReference": {
                "id": "documents-folder",
                "path": "/drives/drive-123/root:/Documents",
            },
        }

        with patch.object(
            scope_rules,
            "enumerate_items",
            AsyncMock(return_value=descendants),
        ) as walk:
            await self._run_delta(
                service,
                mock_dependencies,
                mock_oauth_token,
                folder_scoped,
                changes,
                folder_metadata=scope_folder_now,
            )

        walk.assert_awaited_once()
        assert walk.await_args.kwargs["folder_id"] == "folder-b"
        delete = mock_dependencies[
            "info_blob_service"
        ].repo.delete_by_sharepoint_item_and_integration_knowledge
        removed = [call.kwargs["sharepoint_item_id"] for call in delete.await_args_list]
        assert removed == ["folder-b", "b-file"]
        assert folder_scoped.delta_token == "new-token"

    async def test_unreadable_scope_folder_fails_the_pass_before_classifying(
        self, service, mock_dependencies, mock_oauth_token
    ):
        """With an ancestor renamed meanwhile the stored path is stale; a Graph
        error other than 404 must not let it decide what is out of scope."""
        ik = real_integration_knowledge(
            delta_token="existing-delta-token-123",
            drive_id="drive-123",
            selected_item_type="folder",
            folder_id="folder-a",
            folder_path="/Documents/A",
        )
        changes = [
            {
                "id": "nested-1",
                "name": "nested.docx",
                "webUrl": "https://x/nested.docx",
                "parentReference": {
                    "id": "sub-folder",
                    "path": "/drives/drive-123/root:/Docs renamed/A/Sub",
                },
            }
        ]

        with pytest.raises(
            ScopeFolderUnavailable,
            match="Could not read the selected folder from SharePoint: "
            "HTTP 503 Service Unavailable",
        ):
            await self._run_delta(
                service,
                mock_dependencies,
                mock_oauth_token,
                ik,
                changes,
                folder_metadata=http_error(503, "Service Unavailable"),
            )

        mock_dependencies[
            "info_blob_service"
        ].repo.delete_by_sharepoint_item_and_integration_knowledge.assert_not_called()
        assert ik.delta_token == "existing-delta-token-123"
        assert ik.folder_path == "/Documents/A"
        assert ik.last_sync_status == "error"
        sync_log = mock_dependencies["sync_log_repo"].add.call_args[0][0]
        assert sync_log.status == "error"
        assert sync_log.sync_type == "delta"

    async def test_folder_moved_into_scope_indexes_its_unindexed_files(
        self, service, mock_dependencies, mock_oauth_token, folder_scoped
    ):
        changes = [
            {
                "id": "folder-x",
                "name": "X",
                "folder": {},
                "parentReference": {
                    "id": "folder-a",
                    "path": "/drives/drive-123/root:/Documents/A",
                },
            },
            {
                "id": "x-new",
                "name": "created-with-folder.docx",
                "webUrl": "https://x/created.docx",
                "parentReference": {
                    "id": "folder-x",
                    "path": "/drives/drive-123/root:/Documents/A/X",
                },
            },
        ]
        descendants = [
            {"id": "x-1", "name": "one.docx", "webUrl": "https://x/one.docx"},
            {"id": "x-2", "name": "two.docx", "webUrl": "https://x/two.docx"},
            {"id": "x-new", "name": "created-with-folder.docx"},
        ]
        mock_dependencies[
            "info_blob_service"
        ].repo.get_sharepoint_item_ids_for_integration_knowledge = AsyncMock(
            return_value=[(uuid4(), "x-2")]
        )

        with patch.object(
            scope_rules,
            "enumerate_items",
            AsyncMock(return_value=descendants),
        ) as enumerate_items:
            client, result = await self._run_delta(
                service, mock_dependencies, mock_oauth_token, folder_scoped, changes
            )

        assert enumerate_items.await_args.kwargs["folder_id"] == "folder-x"
        fetched = [
            call.kwargs["item_id"]
            for call in client.get_file_extraction_by_id.await_args_list
        ]
        # x-2 is already indexed; x-new arrives as its own delta entry (once).
        assert sorted(fetched) == ["x-1", "x-new"]
        assert "2 files" in result
        assert "1 folder scanned" in result

    async def test_nested_folders_entering_scope_read_the_index_once(
        self, service, mock_dependencies, mock_oauth_token, folder_scoped
    ):
        """X and its subfolder X/Y both arrive as entries; Y's files were already
        indexed by X's walk and the indexed-id set is read once for the pass."""
        changes = [
            {
                "id": "folder-x",
                "name": "X",
                "folder": {},
                "parentReference": {"id": "folder-a"},
            },
            {
                "id": "folder-y",
                "name": "Y",
                "folder": {},
                "parentReference": {"id": "folder-x"},
            },
        ]
        subtree = {
            "folder-x": [
                {"id": "x-1", "name": "one.docx"},
                {"id": "y-1", "name": "deep.docx"},
            ],
            "folder-y": [{"id": "y-1", "name": "deep.docx"}],
        }
        indexed = mock_dependencies[
            "info_blob_service"
        ].repo.get_sharepoint_item_ids_for_integration_knowledge = AsyncMock(
            return_value=[]
        )

        with patch.object(
            scope_rules,
            "enumerate_items",
            AsyncMock(side_effect=lambda **kw: subtree[kw["folder_id"]]),
        ):
            client, result = await self._run_delta(
                service, mock_dependencies, mock_oauth_token, folder_scoped, changes
            )

        indexed.assert_awaited_once()
        fetched = [
            call.kwargs["item_id"]
            for call in client.get_file_extraction_by_id.await_args_list
        ]
        assert sorted(fetched) == ["x-1", "y-1"]
        assert "2 files" in result

    async def test_the_drive_root_entry_is_never_classified(
        self, service, mock_dependencies, mock_oauth_token, folder_scoped
    ):
        """Graph emits the root with no parent path; for a folder scope it would
        be out of scope and have the whole drive enumerated for deletion."""
        changes = [{"id": "root-1", "name": "root", "root": {}, "folder": {}}]

        with patch.object(scope_rules, "enumerate_items", AsyncMock()) as enumerate_ids:
            _, result = await self._run_delta(
                service, mock_dependencies, mock_oauth_token, folder_scoped, changes
            )

        enumerate_ids.assert_not_called()
        mock_dependencies[
            "info_blob_service"
        ].repo.delete_by_sharepoint_item_and_integration_knowledge.assert_not_called()
        assert result == "Imported 0 files"

    async def test_unlistable_folder_entering_scope_fails_the_pass_and_keeps_the_token(
        self, service, mock_dependencies, mock_oauth_token, folder_scoped
    ):
        changes = [
            {
                "id": "folder-x",
                "name": "X",
                "folder": {},
                "parentReference": {"id": "folder-a"},
            }
        ]

        with (
            patch.object(
                scope_rules,
                "enumerate_items",
                AsyncMock(side_effect=RuntimeError("throttled")),
            ),
            pytest.raises(SyncItemsFailed, match=ONE_FILE_FAILED),
        ):
            await self._run_delta(
                service, mock_dependencies, mock_oauth_token, folder_scoped, changes
            )

        assert folder_scoped.delta_token == "existing-delta-token-123"
        assert folder_scoped.last_sync_summary["skipped_items"] == 1
        assert folder_scoped.last_sync_summary["failed_items"] == 1
        sync_log = mock_dependencies["sync_log_repo"].add.call_args[0][0]
        assert sync_log.status == "error"
        assert reasons(sync_log.metadata["skipped_details"]) == [
            {
                "file": "X",
                "reason": "Could not list folder contents: throttled",
                "retry": True,
            }
        ]

    @staticmethod
    def _indexed(mock_dependencies, *item_ids):
        repo = mock_dependencies["info_blob_service"].repo
        repo.get_sharepoint_item_ids_for_integration_knowledge = AsyncMock(
            return_value=[(uuid4(), item_id) for item_id in item_ids]
        )
        return repo.get_sharepoint_item_ids_for_integration_knowledge

    @staticmethod
    def _graph_places(**located):
        """get_file_metadata as Graph answers it outside delta, path included:
        the scope folder under /Documents, each named item under the parent
        path given, or the error given."""

        async def metadata(*, drive_id, item_id):
            if item_id == "folder-a":
                return {
                    "id": "folder-a",
                    "name": "A",
                    "folder": {},
                    "parentReference": {
                        "id": "documents-folder",
                        "path": "/drives/drive-123/root:/Documents",
                    },
                }
            answer = located[item_id]
            if isinstance(answer, Exception):
                raise answer
            return {
                "id": item_id,
                "name": item_id,
                "parentReference": {
                    "id": "some-folder",
                    "path": f"/drives/drive-123/root:{answer}",
                },
            }

        return metadata

    def _removed(self, mock_dependencies):
        delete = mock_dependencies[
            "info_blob_service"
        ].repo.delete_by_sharepoint_item_and_integration_knowledge
        return [call.kwargs["sharepoint_item_id"] for call in delete.await_args_list]

    async def test_a_pathless_file_listed_before_its_folder_stays_in_scope(
        self, service, mock_dependencies, mock_oauth_token, folder_scoped
    ):
        """Graph orders a change set arbitrarily and need not give a path in
        delta; the folders of the whole set place a file, not those seen first."""
        changes = [
            {
                "id": "n-1",
                "name": "nested.docx",
                "webUrl": "https://x/nested.docx",
                "parentReference": {"id": "sub-folder"},
            },
            {
                "id": "sub-folder",
                "name": "Sub",
                "folder": {},
                "parentReference": {"id": "folder-a"},
            },
        ]
        self._indexed(mock_dependencies, "n-1")

        with patch.object(scope_rules, "enumerate_items", AsyncMock(return_value=[])):
            client, result = await self._run_delta(
                service,
                mock_dependencies,
                mock_oauth_token,
                folder_scoped,
                changes,
                folder_metadata=self._graph_places(),
            )

        assert self._removed(mock_dependencies) == []
        client.get_file_metadata.assert_awaited_once_with(
            drive_id="drive-123", item_id="folder-a"
        )
        client.get_file_extraction_by_id.assert_awaited_once_with(
            drive_id="drive-123", item_id="n-1"
        )
        assert folder_scoped.delta_token == "new-token"
        assert "1 file" in result

    @pytest.mark.parametrize(
        ("graph_path", "removed"),
        [("/Documents/A/Sub", []), ("/Documents/B", ["deep-1"])],
        ids=["still in scope", "moved out"],
    )
    async def test_an_indexed_pathless_file_is_placed_by_graph_before_it_goes(
        self,
        service,
        mock_dependencies,
        mock_oauth_token,
        folder_scoped,
        graph_path,
        removed,
    ):
        """A missing path is no evidence of a move: the file's parent is just
        not part of this change set. Graph says where the file is before its
        documents go."""
        changes = [
            {
                "id": "deep-1",
                "name": "deep.docx",
                "webUrl": "https://x/deep.docx",
                "parentReference": {"id": "sub-folder"},
            }
        ]
        self._indexed(mock_dependencies, "deep-1")

        client, _ = await self._run_delta(
            service,
            mock_dependencies,
            mock_oauth_token,
            folder_scoped,
            changes,
            folder_metadata=self._graph_places(**{"deep-1": graph_path}),
        )

        client.get_file_metadata.assert_any_await(
            drive_id="drive-123", item_id="deep-1"
        )
        assert self._removed(mock_dependencies) == removed
        assert client.get_file_extraction_by_id.await_count == (0 if removed else 1)
        assert folder_scoped.delta_token == "new-token"

    async def test_an_indexed_file_graph_no_longer_finds_is_kept(
        self, service, mock_dependencies, mock_oauth_token, folder_scoped
    ):
        """Gone since the delta was read: the next delta reports the deletion."""
        changes = [
            {
                "id": "deep-1",
                "name": "deep.docx",
                "parentReference": {"id": "sub-folder"},
            }
        ]
        self._indexed(mock_dependencies, "deep-1")

        _, result = await self._run_delta(
            service,
            mock_dependencies,
            mock_oauth_token,
            folder_scoped,
            changes,
            folder_metadata=self._graph_places(
                **{"deep-1": http_error(404, "Not Found")}
            ),
        )

        assert self._removed(mock_dependencies) == []
        assert folder_scoped.delta_token == "new-token"
        assert "1 item skipped" in result
        sync_log = mock_dependencies["sync_log_repo"].add.call_args[0][0]
        assert reasons(sync_log.metadata["skipped_details"]) == [
            {
                "file": "deep-1",
                "reason": "Could not confirm where the file is in SharePoint "
                "(HTTP 404 Not Found); kept until the next full sync",
            }
        ]

    async def test_an_indexed_file_graph_cannot_place_now_fails_the_pass(
        self, service, mock_dependencies, mock_oauth_token, folder_scoped
    ):
        changes = [
            {
                "id": "deep-1",
                "name": "deep.docx",
                "parentReference": {"id": "sub-folder"},
            }
        ]
        self._indexed(mock_dependencies, "deep-1")

        with pytest.raises(SyncItemsFailed, match=ONE_FILE_FAILED):
            await self._run_delta(
                service,
                mock_dependencies,
                mock_oauth_token,
                folder_scoped,
                changes,
                folder_metadata=self._graph_places(
                    **{"deep-1": http_error(503, "Service Unavailable")}
                ),
            )

        assert self._removed(mock_dependencies) == []
        assert folder_scoped.delta_token == "existing-delta-token-123"

    @pytest.mark.parametrize(
        "path, indexed", [("/Documents/A/Deep", 1), ("/Documents/Other", 0)]
    )
    async def test_a_new_pathless_file_is_located_before_advancing_the_token(
        self, service, mock_dependencies, mock_oauth_token, folder_scoped, path, indexed
    ):
        changes = [
            {
                "id": "new-1",
                "name": "new.docx",
                "parentReference": {"id": "unchanged-parent"},
            }
        ]
        self._indexed(mock_dependencies)
        client, _ = await self._run_delta(
            service,
            mock_dependencies,
            mock_oauth_token,
            folder_scoped,
            changes,
            folder_metadata=self._graph_places(**{"new-1": path}),
        )
        client.get_file_metadata.assert_any_await(drive_id="drive-123", item_id="new-1")
        assert client.get_file_extraction_by_id.await_count == indexed
        assert folder_scoped.delta_token == "new-token"

    @pytest.mark.parametrize("status", [429, 503])
    async def test_a_new_file_with_unavailable_location_keeps_the_token(
        self, service, mock_dependencies, mock_oauth_token, folder_scoped, status
    ):
        self._indexed(mock_dependencies)
        with pytest.raises(SyncItemsFailed):
            await self._run_delta(
                service,
                mock_dependencies,
                mock_oauth_token,
                folder_scoped,
                [
                    {
                        "id": "new-1",
                        "name": "new.docx",
                        "parentReference": {"id": "unchanged-parent"},
                    }
                ],
                folder_metadata=self._graph_places(
                    **{"new-1": http_error(status, "unavailable")}
                ),
            )
        assert self._removed(mock_dependencies) == []
        assert folder_scoped.delta_token == "existing-delta-token-123"

    @pytest.mark.parametrize(
        ("graph_answer", "indexed_files", "removed", "indexed_now"),
        [
            ("/Documents/A/Deep", [], [], 1),
            ("/Documents/B", ["q-1"], ["folder-q", "q-1"], 0),
            (http_error(404, "Not Found"), ["q-1"], [], 0),
        ],
        ids=["entered scope", "left scope", "unplaceable"],
    )
    async def test_a_pathless_folder_is_placed_by_graph_before_its_subtree_is_judged(
        self,
        service,
        mock_dependencies,
        mock_oauth_token,
        folder_scoped,
        graph_answer,
        indexed_files,
        removed,
        indexed_now,
    ):
        changes = [
            {
                "id": "folder-q",
                "name": "Q",
                "folder": {"childCount": 1},
                "parentReference": {"id": "elsewhere"},
            }
        ]
        self._indexed(mock_dependencies, *indexed_files)
        q_path = graph_answer if isinstance(graph_answer, str) else "/Unknown"
        descendants = [descendant("q-1", f"{q_path}/folder-q")]

        with patch.object(
            scope_rules,
            "enumerate_items",
            AsyncMock(return_value=descendants),
        ) as walk:
            client, _ = await self._run_delta(
                service,
                mock_dependencies,
                mock_oauth_token,
                folder_scoped,
                changes,
                folder_metadata=self._graph_places(**{"folder-q": graph_answer}),
            )

        client.get_file_metadata.assert_any_await(
            drive_id="drive-123", item_id="folder-q"
        )
        assert self._removed(mock_dependencies) == removed
        assert walk.await_count == (0 if isinstance(graph_answer, Exception) else 1)
        assert client.get_file_extraction_by_id.await_count == indexed_now
        assert folder_scoped.delta_token == "new-token"

    async def test_a_folder_walked_before_under_the_same_parent_is_not_walked_again(
        self, service, mock_dependencies, mock_oauth_token, folder_scoped
    ):
        """A permission change or a replayed pass re-emits a folder whose files
        were indexed when it was walked; a rename or a move needs a new walk,
        which refreshes its files' links."""
        cache: dict[str, str] = {}
        change_keys = mock_dependencies["change_key_service"]
        change_keys.should_process = AsyncMock(
            side_effect=lambda *, integration_knowledge_id, item_id, change_key: (
                cache.get(item_id) != change_key
            )
        )

        def folder_x(parent_id, name="X"):
            return [
                {
                    "id": "folder-x",
                    "name": name,
                    "folder": {"childCount": 1},
                    "parentReference": {"id": parent_id},
                }
            ]

        sub_folder = {
            "id": "folder-s",
            "name": "S",
            "folder": {},
            "parentReference": {"id": "folder-a"},
        }
        with (
            patch.object(
                scope_rules,
                "enumerate_items",
                AsyncMock(return_value=[{"id": "x-1", "name": "one.docx"}]),
            ) as walk,
            patch.object(
                service,
                "_schedule_post_commit_change_keys",
                side_effect=lambda pending: cache.update(
                    {item_id: key for _, item_id, key in pending}
                ),
            ),
        ):
            for changes in (
                folder_x("folder-a"),
                folder_x("folder-a"),
                folder_x("folder-a", name="X renamed"),
                [sub_folder, *folder_x("folder-s", name="X renamed")],
            ):
                await self._run_delta(
                    service, mock_dependencies, mock_oauth_token, folder_scoped, changes
                )

        walked = [call.kwargs["folder_id"] for call in walk.await_args_list]
        assert walked == ["folder-x", "folder-x", "folder-s", "folder-x"]

    async def test_a_renamed_folder_refreshes_the_links_of_its_indexed_files(
        self, service, mock_dependencies, mock_oauth_token, folder_scoped
    ):
        """Graph emits only the folder; its files keep their cTag."""
        self._indexed(mock_dependencies, "x-1")
        refresh = mock_dependencies[
            "info_blob_service"
        ].repo.refresh_sharepoint_citation = AsyncMock(return_value=True)
        renamed = {
            "id": "folder-x",
            "name": "X renamed",
            "folder": {"childCount": 1},
            "parentReference": {"id": "folder-a"},
        }
        moved_file = {
            "id": "x-1",
            "name": "one.docx",
            "webUrl": "https://x/Documents/A/X renamed/one.docx",
        }
        with patch.object(
            scope_rules, "enumerate_items", AsyncMock(return_value=[moved_file])
        ):
            client, _ = await self._run_delta(
                service, mock_dependencies, mock_oauth_token, folder_scoped, [renamed]
            )

        client.get_file_extraction_by_id.assert_not_called()
        refresh.assert_awaited_once_with(
            sharepoint_item_id="x-1",
            integration_knowledge_id=folder_scoped.id,
            title="one.docx",
            url="https://x/Documents/A/X renamed/one.docx",
        )

    async def test_a_folder_whose_walk_failed_is_walked_again(
        self, service, mock_dependencies, mock_oauth_token, folder_scoped
    ):
        cache: dict[str, str] = {}
        change_keys = mock_dependencies["change_key_service"]
        change_keys.should_process = AsyncMock(
            side_effect=lambda *, integration_knowledge_id, item_id, change_key: (
                cache.get(item_id) != change_key
            )
        )
        changes = [
            {
                "id": "folder-x",
                "name": "X",
                "folder": {},
                "parentReference": {"id": "folder-a"},
            }
        ]

        with (
            patch.object(
                scope_rules,
                "enumerate_items",
                AsyncMock(side_effect=[RuntimeError("throttled"), []]),
            ) as walk,
            patch.object(
                service,
                "_schedule_post_commit_change_keys",
                side_effect=lambda pending: cache.update(
                    {item_id: key for _, item_id, key in pending}
                ),
            ),
        ):
            with pytest.raises(SyncItemsFailed):
                await self._run_delta(
                    service, mock_dependencies, mock_oauth_token, folder_scoped, changes
                )
            await self._run_delta(
                service, mock_dependencies, mock_oauth_token, folder_scoped, changes
            )

        assert walk.await_count == 2
        assert "folder-x" in cache

    @pytest.mark.parametrize(
        ("indexed_files", "child_count", "walked", "removed"),
        [
            (["z-1", "a-1"], 3, True, ["folder-z", "z-1"]),
            ([], 3, False, ["folder-z"]),
            (["z-1"], 0, False, ["folder-z"]),
        ],
        ids=["only indexed descendants go", "nothing indexed", "empty folder"],
    )
    async def test_a_folder_leaving_scope_costs_only_what_was_indexed_under_it(
        self,
        service,
        mock_dependencies,
        mock_oauth_token,
        folder_scoped,
        indexed_files,
        child_count,
        walked,
        removed,
    ):
        changes = [
            {
                "id": "folder-z",
                "name": "Z",
                "folder": {"childCount": child_count},
                "parentReference": {
                    "id": "documents-folder",
                    "path": "/drives/drive-123/root:/Documents",
                },
            }
        ]
        indexed = self._indexed(mock_dependencies, *indexed_files)
        descendants = [descendant(f"z-{i}", "/Documents/Z") for i in (1, 2, 3)]

        with patch.object(
            scope_rules,
            "enumerate_items",
            AsyncMock(return_value=descendants),
        ) as walk:
            await self._run_delta(
                service,
                mock_dependencies,
                mock_oauth_token,
                folder_scoped,
                changes,
                folder_metadata=self._graph_places(),
            )

        assert walk.await_count == (1 if walked else 0)
        assert self._removed(mock_dependencies) == removed
        assert indexed.await_count <= 1
        assert folder_scoped.delta_token == "new-token"


class TestDeltaExtractionOutcomes:
    """The delta path decides from the ExtractionResult exactly as the folder
    path does: only a completed parse without text removes the local copy."""

    async def _run(self, service, mock_dependencies, mock_oauth_token, outcome):
        ik = real_integration_knowledge(delta_token="token-1")
        mock_dependencies["oauth_token_repo"].one.return_value = mock_oauth_token
        mock_dependencies["integration_knowledge_repo"].one.return_value = ik
        size_ledger(mock_dependencies["integration_knowledge_repo"], 100)
        mock_dependencies[
            "info_blob_service"
        ].repo.get_sharepoint_item_ids_for_integration_knowledge = AsyncMock(
            return_value=[(uuid4(), "item-1")]
        )
        delete = mock_dependencies[
            "info_blob_service"
        ].repo.delete_by_sharepoint_item_and_integration_knowledge = AsyncMock(
            return_value=[MagicMock(size=40)]
        )
        extraction = (
            AsyncMock(side_effect=outcome)
            if isinstance(outcome, Exception)
            else AsyncMock(return_value=outcome)
        )
        with patch(
            "eneo.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
        ) as mock_client_class:
            mock_graph_client(
                mock_client_class,
                get_delta_changes=AsyncMock(
                    return_value=([delta_file("item-1", "scan.pdf")], "token-2")
                ),
                get_file_extraction_by_id=extraction,
            )
            failure = None
            with patch.object(service._index, "upsert", AsyncMock()) as process:
                try:
                    await service.process_delta_changes(
                        token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
                    )
                except SyncItemsFailed as exc:
                    failure = exc
        return ik, delete, process, failure

    async def test_scanned_pdf_removes_the_local_copy_with_its_reason(
        self, service, mock_dependencies, mock_oauth_token
    ):
        ik, delete, process, _ = await self._run(
            service,
            mock_dependencies,
            mock_oauth_token,
            ExtractionResult.no_text(NO_TEXT_LAYER_REASON, "application/pdf"),
        )

        process.assert_not_called()
        delete.assert_awaited_once_with(
            sharepoint_item_id="item-1", integration_knowledge_id=ik.id
        )
        assert ik.last_sync_status == "success"
        assert ik.delta_token == "token-2"
        assert ik.last_sync_summary["files_deleted"] == 1
        assert ik.last_sync_summary["skipped_items"] == 1
        sync_log = mock_dependencies["sync_log_repo"].add.call_args[0][0]
        assert reasons(sync_log.metadata["skipped_details"]) == [
            {"file": "scan.pdf", "reason": NO_TEXT_LAYER_REASON}
        ]

    @pytest.mark.parametrize(
        ("outcome", "expected_reason"),
        [
            (
                ExtractionResult.error("Corrupt or malformed file"),
                "Error: Corrupt or malformed file",
            ),
            (
                ExtractionResult.error(
                    "Incomplete download of 'scan.pdf' (1 of 2 bytes)"
                ),
                "Error: Incomplete download of 'scan.pdf' (1 of 2 bytes)",
            ),
            (
                ExtractionResult.skipped("Exceeds extraction limit (1000 PDF pages)"),
                "Exceeds extraction limit (1000 PDF pages)",
            ),
            (http_error(404, "Not Found"), "Error: HTTP 404 Not Found"),
            (
                MissingDownloadUrlError("No download URL available for file 'x'"),
                "Error: SharePoint offers no download for this item",
            ),
        ],
    )
    async def test_file_level_outcomes_keep_the_local_copy_and_advance(
        self, service, mock_dependencies, mock_oauth_token, outcome, expected_reason
    ):
        """Parser errors, limits and a file that is gone or closed to us say
        something about the file: the pass moves on and the token advances."""
        ik, delete, process, failure = await self._run(
            service, mock_dependencies, mock_oauth_token, outcome
        )

        assert failure is None
        process.assert_not_called()
        delete.assert_not_called()
        assert ik.last_sync_status == "success"
        assert ik.delta_token == "token-2"
        assert ik.last_sync_summary["files_deleted"] == 0
        assert ik.last_sync_summary["skipped_items"] == 1
        assert "failed_items" not in ik.last_sync_summary
        sync_log = mock_dependencies["sync_log_repo"].add.call_args[0][0]
        assert sync_log.status == "success"
        assert reasons(sync_log.metadata["skipped_details"]) == [
            {"file": "scan.pdf", "reason": expected_reason}
        ]

    @pytest.mark.parametrize(
        ("outcome", "expected_reason"),
        [
            (
                ValueError("SharePoint file 'x' exceeds max download size (1 > 0)"),
                "File too large (exceeds 50 MB limit)",
            ),
            (
                ExtractionResult.skipped("Unsupported file type (.bin)"),
                "Unsupported file type (.bin)",
            ),
        ],
    )
    async def test_a_file_that_can_no_longer_be_read_loses_its_old_text(
        self, service, mock_dependencies, mock_oauth_token, outcome, expected_reason
    ):
        """A file that grew past the limit or turned into a type without text
        must not keep answering with what it said before."""
        ik, delete, process, failure = await self._run(
            service, mock_dependencies, mock_oauth_token, outcome
        )

        assert failure is None
        process.assert_not_called()
        delete.assert_awaited_once_with(
            sharepoint_item_id="item-1", integration_knowledge_id=ik.id
        )
        assert ik.delta_token == "token-2"
        assert ik.last_sync_summary["files_deleted"] == 1
        sync_log = mock_dependencies["sync_log_repo"].add.call_args[0][0]
        assert reasons(sync_log.metadata["skipped_details"]) == [
            {"file": "scan.pdf", "reason": expected_reason}
        ]

    async def test_a_rename_to_an_unsupported_type_drops_the_old_text(
        self, service, mock_dependencies, mock_oauth_token
    ):
        """A rename keeps the cTag, so the type is checked before the ChangeKey."""
        ik = real_integration_knowledge(delta_token="token-1")
        mock_dependencies["oauth_token_repo"].one.return_value = mock_oauth_token
        mock_dependencies["integration_knowledge_repo"].one.return_value = ik
        repo = mock_dependencies["info_blob_service"].repo
        repo.get_sharepoint_item_ids_for_integration_knowledge = AsyncMock(
            return_value=[(uuid4(), "item-1")]
        )
        delete = repo.delete_by_sharepoint_item_and_integration_knowledge = AsyncMock(
            return_value=[MagicMock(size=0, title="report.docx")]
        )
        mock_dependencies["change_key_service"].should_process.return_value = False
        with patch(
            "eneo.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
        ) as mock_client_class:
            client = mock_graph_client(
                mock_client_class,
                get_delta_changes=AsyncMock(
                    return_value=([delta_file("item-1", "report.zip")], "token-2")
                ),
            )
            await service.process_delta_changes(
                token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
            )

        client.get_file_extraction_by_id.assert_not_called()
        delete.assert_awaited_once_with(
            sharepoint_item_id="item-1", integration_knowledge_id=ik.id
        )
        assert ik.delta_token == "token-2"

    async def test_an_unsupported_file_never_indexed_costs_no_delete(
        self, service, mock_dependencies, mock_oauth_token
    ):
        ik = real_integration_knowledge(delta_token="token-1")
        mock_dependencies["oauth_token_repo"].one.return_value = mock_oauth_token
        mock_dependencies["integration_knowledge_repo"].one.return_value = ik
        repo = mock_dependencies["info_blob_service"].repo
        repo.get_sharepoint_item_ids_for_integration_knowledge = AsyncMock(
            return_value=[(uuid4(), "another-item")]
        )
        delete = repo.delete_by_sharepoint_item_and_integration_knowledge = AsyncMock(
            return_value=[]
        )
        images = [delta_file(f"image-{index}", f"{index}.png") for index in range(5)]
        with patch(
            "eneo.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
        ) as mock_client_class:
            mock_graph_client(
                mock_client_class,
                get_delta_changes=AsyncMock(return_value=(images, "token-2")),
            )
            await service.process_delta_changes(
                token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
            )

        delete.assert_not_called()
        repo.get_sharepoint_item_ids_for_integration_knowledge.assert_awaited_once()
        assert ik.last_sync_summary["skipped_items"] == 5

    async def test_a_rename_reaches_the_index_without_a_download(
        self, service, mock_dependencies, mock_oauth_token
    ):
        """A rename or move keeps the cTag: the ChangeKey says unchanged, but the
        title and citation URL must follow."""
        ik = real_integration_knowledge(delta_token="token-1")
        mock_dependencies["oauth_token_repo"].one.return_value = mock_oauth_token
        mock_dependencies["integration_knowledge_repo"].one.return_value = ik
        cached: dict[str, str] = {}

        async def should_process(*, integration_knowledge_id, item_id, change_key):
            return cached.get(item_id) != change_key

        async def update_change_key(*, integration_knowledge_id, item_id, change_key):
            cached[item_id] = change_key

        change_keys = mock_dependencies["change_key_service"]
        change_keys.should_process.side_effect = should_process
        change_keys.update_change_key.side_effect = update_change_key
        renamed = delta_file(
            "item-1", "Budget 2027.docx", webUrl="https://x/Ekonomi/Budget 2027.docx"
        )
        cached["item-1"] = renamed["cTag"]
        refresh = mock_dependencies[
            "info_blob_service"
        ].repo.refresh_sharepoint_citation = AsyncMock(return_value=True)
        with (
            patch(
                "eneo.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
            ) as mock_client_class,
            patch.object(
                service,
                "_schedule_post_commit_change_keys",
                side_effect=lambda pending: [
                    cached.__setitem__(item_id, key) for _, item_id, key in pending
                ],
            ),
        ):
            client = mock_graph_client(
                mock_client_class,
                get_delta_changes=AsyncMock(return_value=([renamed], "token-2")),
            )
            for _ in range(2):
                await service.process_delta_changes(
                    token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
                )

        client.get_file_extraction_by_id.assert_not_called()
        refresh.assert_awaited_once_with(
            sharepoint_item_id="item-1",
            integration_knowledge_id=ik.id,
            title="Budget 2027.docx",
            url="https://x/Ekonomi/Budget 2027.docx",
        )
        assert ik.delta_token == "token-2"
        assert ik.last_sync_summary["unchanged_items"] == 1

    async def test_a_onenote_notebook_is_skipped_without_a_download(
        self, service, mock_dependencies, mock_oauth_token
    ):
        """Graph serves a notebook as a package: no folder facet, no download."""
        ik = real_integration_knowledge(delta_token="token-1")
        mock_dependencies["oauth_token_repo"].one.return_value = mock_oauth_token
        mock_dependencies["integration_knowledge_repo"].one.return_value = ik
        notebook = {
            "id": "notebook-1",
            "name": "Mötesanteckningar",
            "package": {"type": "oneNote"},
            "cTag": "ctag-notebook",
            "parentReference": {"driveId": "drive-456"},
        }
        with patch(
            "eneo.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
        ) as mock_client_class:
            client = mock_graph_client(
                mock_client_class,
                get_delta_changes=AsyncMock(return_value=([notebook], "token-2")),
            )
            await service.process_delta_changes(
                token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
            )

        client.get_file_extraction_by_id.assert_not_called()
        assert ik.delta_token == "token-2"
        sync_log = mock_dependencies["sync_log_repo"].add.call_args[0][0]
        assert reasons(sync_log.metadata["skipped_details"]) == [
            {"file": "Mötesanteckningar", "reason": "Unsupported file type (OneNote)"}
        ]

    @pytest.mark.parametrize(
        ("outcome", "expected_reason"),
        [
            (
                http_error(503, "Service Unavailable"),
                "Error: HTTP 503 Service Unavailable",
            ),
            (
                http_error(429, "Too Many Requests"),
                "Error: HTTP 429 Too Many Requests",
            ),
            (aiohttp.ClientConnectionError("reset"), "Error: Connection error"),
            (TimeoutError(), "Error: Request timed out"),
            (RuntimeError("Graph timeout"), "Error: Graph timeout"),
            (
                IncompleteDownloadError(
                    "Incomplete download of 'scan.pdf' (1 of 2 bytes)"
                ),
                "Error: Incomplete download of 'scan.pdf' (1 of 2 bytes)",
            ),
        ],
    )
    async def test_infrastructure_failures_keep_the_local_copy_and_the_token(
        self, service, mock_dependencies, mock_oauth_token, outcome, expected_reason
    ):
        """Graph never re-emits an item once a pass moved past it, so a pass
        that could not finish an item keeps its token and ends as an error."""
        ik, delete, process, failure = await self._run(
            service, mock_dependencies, mock_oauth_token, outcome
        )

        assert str(failure) == ONE_FILE_FAILED
        process.assert_not_called()
        delete.assert_not_called()
        assert ik.delta_token == "token-1"
        assert ik.last_sync_status == "error"
        assert ik.last_sync_error == ONE_FILE_FAILED
        assert ik.last_sync_summary["files_deleted"] == 0
        assert ik.last_sync_summary["skipped_items"] == 1
        assert ik.last_sync_summary["failed_items"] == 1
        sync_log = mock_dependencies["sync_log_repo"].add.call_args[0][0]
        assert sync_log.status == "error"
        assert sync_log.sync_type == "delta"
        assert sync_log.error_message == ONE_FILE_FAILED
        assert sync_log.metadata["changes_detected"] == 1
        assert sync_log.metadata["failed_items"] == 1
        assert reasons(sync_log.metadata["skipped_details"]) == [
            {"file": "scan.pdf", "reason": expected_reason, "retry": True}
        ]

    async def _run_refusals(
        self, service, mock_dependencies, mock_oauth_token, outcomes
    ):
        """One file per outcome, all of them indexed before the pass."""
        ik = real_integration_knowledge(delta_token="token-1")
        mock_dependencies["oauth_token_repo"].one.return_value = mock_oauth_token
        mock_dependencies["integration_knowledge_repo"].one.return_value = ik
        item_ids = [f"item-{index}" for index in range(len(outcomes))]
        repo = mock_dependencies["info_blob_service"].repo
        repo.get_sharepoint_item_ids_for_integration_knowledge = AsyncMock(
            return_value=[(uuid4(), item_id) for item_id in item_ids]
        )
        delete = repo.delete_by_sharepoint_item_and_integration_knowledge = AsyncMock(
            return_value=[MagicMock(size=0, title="indexed copy")]
        )
        failure = None
        with (
            patch(
                "eneo.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
            ) as mock_client_class,
            patch.object(service._index, "upsert", AsyncMock(return_value="added")),
        ):
            mock_graph_client(
                mock_client_class,
                get_delta_changes=AsyncMock(
                    return_value=(
                        [
                            delta_file(item_id, f"{item_id}.docx")
                            for item_id in item_ids
                        ],
                        "token-2",
                    )
                ),
                get_file_extraction_by_id=AsyncMock(side_effect=outcomes),
            )
            try:
                await service.process_delta_changes(
                    token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
                )
            except SyncAccessDenied as exc:
                failure = exc
        removed = [call.kwargs["sharepoint_item_id"] for call in delete.await_args_list]
        return ik, removed, failure

    @pytest.mark.parametrize(
        "outcomes",
        [
            pytest.param([http_error(403, "Forbidden")], id="the-only-download"),
            pytest.param(
                [http_error(403, "Forbidden"), ExtractionResult.ok("Body")],
                id="among-successes",
            ),
            pytest.param(
                [http_error(403, "Forbidden"), http_error(403, "Forbidden")],
                id="two-of-two",
            ),
        ],
    )
    async def test_a_first_refusal_keeps_the_indexed_copy_and_advances(
        self, service, mock_dependencies, mock_oauth_token, outcomes
    ):
        """A passing 403 must not drop a file, and one restricted file must not
        hold the token back: the refusal is recorded, and a second one later
        removes the copy (see test_sharepoint_sync_ledger)."""
        ik, removed, failure = await self._run_refusals(
            service, mock_dependencies, mock_oauth_token, outcomes
        )

        refused = [
            f"item-{index}"
            for index, outcome in enumerate(outcomes)
            if isinstance(outcome, Exception)
        ]
        assert failure is None
        assert removed == []
        assert ik.delta_token == "token-2"
        assert ik.last_sync_status == "success"
        assert ik.last_sync_summary["files_deleted"] == 0
        assert "failed_items" not in ik.last_sync_summary
        written = mock_dependencies["integration_knowledge_repo"].update_sync_state
        (record,) = [
            call.kwargs["sync_failed_items"]
            for call in written.await_args_list
            if "sync_failed_items" in call.kwargs
        ]
        assert sorted(record["items"]) == refused
        assert all(entry[3] is not None for entry in record["items"].values())
        sync_log = mock_dependencies["sync_log_repo"].add.call_args[0][0]
        assert {"file": "item-0.docx", "reason": "Error: HTTP 403 Forbidden"} in (
            reasons(sync_log.metadata["skipped_details"])
        )

    async def test_every_download_of_several_refused_is_about_the_identity(
        self, service, mock_dependencies, mock_oauth_token
    ):
        """A pass in which nothing of three could be downloaded names the
        identity: nothing is removed and the pass keeps its token."""
        ik, removed, failure = await self._run_refusals(
            service,
            mock_dependencies,
            mock_oauth_token,
            [http_error(403, "Forbidden")] * 3,
        )

        assert str(failure) == (
            "SharePoint refused all 3 downloads (HTTP 403); check the "
            "integration's access to this library, the next sync retries them"
        )
        assert removed == []
        assert ik.delta_token == "token-1"
        assert ik.last_sync_status == "error"
        assert ik.last_sync_summary["failed_items"] == 3
        sync_log = mock_dependencies["sync_log_repo"].add.call_args[0][0]
        assert sync_log.status == "error"
        assert sync_log.metadata["changes_detected"] == 3

    async def test_an_encrypted_file_loses_its_indexed_copy(
        self, service, mock_dependencies, mock_oauth_token
    ):
        """A sensitivity label with encryption leaves a file Eneo cannot read."""
        ik, removed, failure = await self._run_refusals(
            service,
            mock_dependencies,
            mock_oauth_token,
            [ExtractionResult.error(PASSWORD_PROTECTED_REASON)],
        )

        assert failure is None
        assert removed == ["item-0"]
        assert ik.delta_token == "token-2"
        sync_log = mock_dependencies["sync_log_repo"].add.call_args[0][0]
        assert reasons(sync_log.metadata["skipped_details"]) == [
            {"file": "item-0.docx", "reason": "Error: Password-protected file"}
        ]
        assert sync_log.metadata["changed_details"] == [
            {"file": "indexed copy", "change": "deleted"}
        ]

    async def test_a_full_sync_records_a_file_it_may_no_longer_download(
        self, service, mock_dependencies, mock_oauth_token
    ):
        """The file is still listed, so only the refusal says it is closed; the
        next pass that is refused it too removes the copy."""
        ik = real_integration_knowledge(delta_token=None)
        mock_dependencies["oauth_token_repo"].one.return_value = mock_oauth_token
        mock_dependencies["integration_knowledge_repo"].one.return_value = ik
        repo = mock_dependencies["info_blob_service"].repo
        repo.get_sharepoint_item_ids_for_integration_knowledge = AsyncMock(
            return_value=[(uuid4(), "secret"), (uuid4(), "open")]
        )
        delete = repo.delete_by_sharepoint_item_and_integration_knowledge = AsyncMock(
            return_value=[MagicMock(size=0, title="secret.docx")]
        )
        files = [
            {
                **delta_file(item_id, f"{item_id}.docx"),
                "parentReference": {"driveId": "drive-456", "siteId": "site-123"},
            }
            for item_id in ("secret", "open")
        ]
        with (
            patch(
                "eneo.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
            ) as mock_client_class,
            patch.object(service._index, "upsert", AsyncMock(return_value="unchanged")),
        ):
            mock_graph_client(
                mock_client_class,
                get_drive_root_children=AsyncMock(return_value=files),
                get_file_extraction_by_id=AsyncMock(
                    side_effect=[
                        http_error(403, "Forbidden"),
                        ExtractionResult.ok("Body"),
                    ]
                ),
            )
            await service.pull_content(
                token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
            )

        delete.assert_not_called()
        assert ik.last_sync_status == "success"
        assert ik.delta_token == "delta-token"
        written = mock_dependencies["integration_knowledge_repo"].update_sync_state
        (record,) = [
            call.kwargs["sync_failed_items"]
            for call in written.await_args_list
            if "sync_failed_items" in call.kwargs
        ]
        assert list(record["items"]) == ["secret"]

    async def test_a_stale_copy_that_cannot_be_removed_fails_the_item_once_uncached(
        self, service, mock_dependencies, mock_oauth_token
    ):
        """Text that sanitises to nothing removes the local copy; when that
        removal fails the item is one failure, and its ChangeKey is not cached
        so the replay removes the copy instead of skipping the item."""
        ik = real_integration_knowledge(delta_token="token-1")
        mock_dependencies["oauth_token_repo"].one.return_value = mock_oauth_token
        mock_dependencies["integration_knowledge_repo"].one.return_value = ik
        mock_dependencies[
            "info_blob_service"
        ].repo.delete_by_sharepoint_item_and_integration_knowledge = AsyncMock(
            side_effect=RuntimeError("db down")
        )

        with (
            patch(
                "eneo.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
            ) as mock_client_class,
            patch.object(service, "_schedule_post_commit_change_keys") as schedule,
            pytest.raises(SyncItemsFailed, match=ONE_FILE_FAILED),
        ):
            mock_graph_client(
                mock_client_class,
                get_delta_changes=AsyncMock(
                    return_value=([delta_file("item-1", "nulls.txt")], "token-2")
                ),
                get_file_extraction_by_id=AsyncMock(
                    return_value=ExtractionResult.ok("\x00\x00", "text/plain")
                ),
            )
            await service.process_delta_changes(
                token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
            )

        assert ik.delta_token == "token-1"
        schedule.assert_called_once_with([])
        assert ik.last_sync_summary["skipped_items"] == 1
        assert ik.last_sync_summary["failed_items"] == 1
        sync_log = mock_dependencies["sync_log_repo"].add.call_args[0][0]
        assert reasons(sync_log.metadata["skipped_details"]) == [
            {
                "file": "nulls.txt",
                "reason": "Could not remove unextractable: db down",
                "retry": True,
            }
        ]

    async def test_text_that_sanitises_to_nothing_removes_the_local_copy_once(
        self, service, mock_dependencies, mock_oauth_token
    ):
        ik = real_integration_knowledge(delta_token="token-1")
        mock_dependencies["oauth_token_repo"].one.return_value = mock_oauth_token
        mock_dependencies["integration_knowledge_repo"].one.return_value = ik
        size_ledger(mock_dependencies["integration_knowledge_repo"], 100)
        delete = mock_dependencies[
            "info_blob_service"
        ].repo.delete_by_sharepoint_item_and_integration_knowledge = AsyncMock(
            return_value=[MagicMock(size=40)]
        )
        publish = mock_dependencies[
            "info_blob_service"
        ].publish_info_blob_without_validation

        with patch(
            "eneo.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
        ) as mock_client_class:
            mock_graph_client(
                mock_client_class,
                get_delta_changes=AsyncMock(
                    return_value=([delta_file("item-1", "nulls.txt")], "token-2")
                ),
                get_file_extraction_by_id=AsyncMock(
                    return_value=ExtractionResult.ok("\x00\x00", "text/plain")
                ),
            )
            await service.process_delta_changes(
                token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
            )

        publish.assert_not_called()
        delete.assert_awaited_once_with(
            sharepoint_item_id="item-1", integration_knowledge_id=ik.id
        )
        assert ik.size == 60
        assert ik.last_sync_summary["files_deleted"] == 1
        assert ik.last_sync_summary["skipped_items"] == 1
        sync_log = mock_dependencies["sync_log_repo"].add.call_args[0][0]
        assert reasons(sync_log.metadata["skipped_details"]) == [
            {"file": "nulls.txt", "reason": EMPTY_CONTENT_REASON}
        ]

    async def test_a_failing_item_fails_the_pass_after_the_other_items(
        self, service, mock_dependencies, mock_oauth_token
    ):
        """The items that did succeed are indexed and their ChangeKeys cached,
        so the replay of the kept token skips them as unchanged."""
        ik = real_integration_knowledge(delta_token="token-1")
        mock_dependencies["oauth_token_repo"].one.return_value = mock_oauth_token
        mock_dependencies["integration_knowledge_repo"].one.return_value = ik
        mock_dependencies["change_key_service"].should_process.side_effect = [
            RuntimeError("redis down"),
            True,
        ]
        mock_dependencies[
            "info_blob_service"
        ].publish_info_blob_without_validation.return_value = MagicMock(size=10)
        size_ledger(mock_dependencies["integration_knowledge_repo"], 0)

        with (
            patch(
                "eneo.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
            ) as mock_client_class,
            patch.object(service, "_schedule_post_commit_change_keys") as schedule,
            pytest.raises(SyncItemsFailed, match=ONE_FILE_FAILED),
        ):
            client = mock_graph_client(
                mock_client_class,
                get_delta_changes=AsyncMock(
                    return_value=(
                        [
                            delta_file("item-1", "a.docx"),
                            delta_file("item-2", "b.docx"),
                        ],
                        "token-2",
                    )
                ),
                get_file_extraction_by_id=AsyncMock(
                    return_value=ExtractionResult.ok("Body")
                ),
            )
            await service.process_delta_changes(
                token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
            )

        assert ik.last_sync_status == "error"
        assert ik.last_sync_error == ONE_FILE_FAILED
        assert ik.delta_token == "token-1"
        assert client.get_file_extraction_by_id.await_args.kwargs["item_id"] == "item-2"
        assert [key[1] for key in schedule.call_args.args[0]] == [
            "item-2",
            "item-2#citation",
        ]
        assert ik.last_sync_summary["files_processed"] == 1
        assert ik.last_sync_summary["skipped_items"] == 1
        assert ik.last_sync_summary["failed_items"] == 1
        sync_log = mock_dependencies["sync_log_repo"].add.call_args[0][0]
        assert sync_log.status == "error"
        assert sync_log.metadata["files_processed"] == 1
        assert reasons(sync_log.metadata["skipped_details"]) == [
            {"file": "a.docx", "reason": "Error: redis down", "retry": True}
        ]


class TestSiteRootExtractionOutcomes:
    """Root-level documents of a full sync follow the same ExtractionResult rules."""

    async def _run(
        self, service, mock_dependencies, mock_oauth_token, outcome, delta_token=None
    ):
        ik = real_integration_knowledge(delta_token=delta_token)
        mock_dependencies["oauth_token_repo"].one.return_value = mock_oauth_token
        mock_dependencies["integration_knowledge_repo"].one.return_value = ik
        size_ledger(mock_dependencies["integration_knowledge_repo"], 100)
        delete = mock_dependencies[
            "info_blob_service"
        ].repo.delete_by_sharepoint_item_and_integration_knowledge = AsyncMock(
            return_value=[MagicMock(size=40)]
        )
        mock_dependencies[
            "info_blob_service"
        ].repo.get_sharepoint_item_ids_for_integration_knowledge = AsyncMock(
            return_value=[]
        )
        with patch(
            "eneo.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
        ) as mock_client_class:
            mock_graph_client(
                mock_client_class,
                get_drive_root_children=AsyncMock(
                    return_value=[delta_file("item-1", "photo")]
                ),
                get_file_extraction_by_id=(
                    AsyncMock(side_effect=outcome)
                    if isinstance(outcome, Exception)
                    else AsyncMock(return_value=outcome)
                ),
            )
            failure = None
            with patch.object(service._index, "upsert", AsyncMock()) as process:
                try:
                    await service.pull_content(
                        token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
                    )
                except SyncItemsFailed as exc:
                    failure = exc
        return ik, delete, process, failure

    async def test_unsupported_content_type_is_skipped_with_its_reason(
        self, service, mock_dependencies, mock_oauth_token
    ):
        ik, delete, process, _ = await self._run(
            service,
            mock_dependencies,
            mock_oauth_token,
            ExtractionResult.skipped("Unsupported file type (image)", "image/png"),
        )

        process.assert_not_called()
        delete.assert_not_called()
        assert ik.last_sync_status == "success"
        assert ik.last_sync_summary["skipped_items"] == 1
        assert ik.last_sync_summary["files_deleted"] == 0
        sync_log = mock_dependencies["sync_log_repo"].add.call_args[0][0]
        assert reasons(sync_log.metadata["skipped_details"]) == [
            {"file": "photo", "reason": "Unsupported file type (image)"}
        ]

    async def test_empty_document_removes_the_local_copy(
        self, service, mock_dependencies, mock_oauth_token
    ):
        ik, delete, process, _ = await self._run(
            service,
            mock_dependencies,
            mock_oauth_token,
            ExtractionResult.no_text(EMPTY_CONTENT_REASON),
        )

        process.assert_not_called()
        delete.assert_awaited_once_with(
            sharepoint_item_id="item-1", integration_knowledge_id=ik.id
        )
        assert ik.last_sync_summary["files_deleted"] == 1
        sync_log = mock_dependencies["sync_log_repo"].add.call_args[0][0]
        assert reasons(sync_log.metadata["skipped_details"]) == [
            {"file": "photo", "reason": EMPTY_CONTENT_REASON}
        ]

    @pytest.mark.parametrize("delta_token", [None, "token-1"], ids=["first", "tokened"])
    async def test_a_download_failure_fails_the_sync_and_records_the_file(
        self, service, mock_dependencies, mock_oauth_token, delta_token
    ):
        """The sync keeps its change tracking (the baseline it minted, or the
        token it had) and records the file on the knowledge row, so the next
        delta retries it instead of the next sync being a full one."""
        ik, delete, process, failure = await self._run(
            service,
            mock_dependencies,
            mock_oauth_token,
            http_error(503, "Service Unavailable"),
            delta_token=delta_token,
        )

        assert str(failure) == ONE_FILE_FAILED
        process.assert_not_called()
        delete.assert_not_called()
        assert ik.delta_token == (delta_token or "delta-token")
        written = mock_dependencies["integration_knowledge_repo"].update_sync_state
        assert written.await_args.kwargs["delta_token"] == ik.delta_token
        (recorded,) = [
            call.kwargs["sync_failed_items"]
            for call in written.await_args_list
            if "sync_failed_items" in call.kwargs
        ]
        assert list(recorded["items"]) == ["item-1"]
        assert ik.last_sync_status == "error"
        assert ik.last_sync_error == ONE_FILE_FAILED
        assert ik.last_synced_at is None
        assert ik.last_sync_summary["failed_items"] == 1
        sync_log = mock_dependencies["sync_log_repo"].add.call_args[0][0]
        assert sync_log.status == "error"
        assert sync_log.sync_type == "full"
        assert reasons(sync_log.metadata["skipped_details"]) == [
            {
                "file": "photo",
                "reason": "Error: HTTP 503 Service Unavailable",
                "retry": True,
            }
        ]


def _indexed_blob(title: str, *, text: str | None = None) -> MagicMock:
    """An active document; with ``text`` it already holds that content."""
    return MagicMock(
        title=title,
        url=f"https://x/{title}",
        size=5,
        source_metadata=[],
        content_hash=(
            hashlib.sha256(text.encode()).digest() if text is not None else b"stale"
        ),
    )


class TestChangedDetails:
    """The sync log names the documents a run added, re-indexed or removed."""

    def _index(self, mock_dependencies, documents: dict[str, MagicMock]) -> AsyncMock:
        info_blob_service = mock_dependencies["info_blob_service"]
        info_blob_service.repo.get_by_sharepoint_item_and_integration_knowledge = (
            AsyncMock(
                side_effect=lambda sharepoint_item_id, integration_knowledge_id: (
                    documents.get(sharepoint_item_id)
                )
            )
        )
        info_blob_service.publish_info_blob_without_validation.return_value = MagicMock(
            size=10
        )
        size_ledger(mock_dependencies["integration_knowledge_repo"], 100)
        return info_blob_service.repo

    async def test_delta_sync_lists_added_updated_and_deleted_but_not_unchanged(
        self, service, mock_dependencies, mock_oauth_token
    ):
        ik = real_integration_knowledge(delta_token="token-1")
        mock_dependencies["oauth_token_repo"].one.return_value = mock_oauth_token
        mock_dependencies["integration_knowledge_repo"].one.return_value = ik
        repo = self._index(
            mock_dependencies,
            {
                "item-b": _indexed_blob("b.docx"),
                "item-c": _indexed_blob("c.docx", text="Body"),
            },
        )
        repo.delete_by_sharepoint_item_and_integration_knowledge = AsyncMock(
            return_value=[_indexed_blob("d.docx")]
        )

        with patch(
            "eneo.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
        ) as mock_client_class:
            mock_graph_client(
                mock_client_class,
                get_delta_changes=AsyncMock(
                    return_value=(
                        [
                            delta_file("item-a", "a.docx"),
                            delta_file("item-b", "b.docx"),
                            delta_file("item-c", "c.docx"),
                            {"id": "item-d", "name": "d.docx", "deleted": {}},
                        ],
                        "token-2",
                    )
                ),
                get_file_extraction_by_id=AsyncMock(
                    return_value=ExtractionResult.ok("Body")
                ),
            )
            await service.process_delta_changes(
                token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
            )

        sync_log = mock_dependencies["sync_log_repo"].add.call_args[0][0]
        assert sync_log.sync_type == "delta"
        assert sync_log.metadata["unchanged_items"] == 1
        assert sync_log.metadata["changed_details"] == [
            {"file": "a.docx", "change": "added"},
            {"file": "b.docx", "change": "updated"},
            {"file": "d.docx", "change": "deleted"},
        ]
        assert sync_log.metadata["changed_total"] == 3
        assert sync_log.metadata["changed_truncated"] is False

    async def test_full_sync_names_a_removed_orphan_by_its_document(
        self, service, mock_dependencies, mock_oauth_token
    ):
        ik = real_integration_knowledge()
        mock_dependencies["oauth_token_repo"].one.return_value = mock_oauth_token
        mock_dependencies["integration_knowledge_repo"].one.return_value = ik
        repo = self._index(mock_dependencies, {"item-b": _indexed_blob("b.docx")})
        repo.get_sharepoint_item_ids_for_integration_knowledge = AsyncMock(
            return_value=[(uuid4(), "item-b"), (uuid4(), "item-gone")]
        )
        repo.delete_by_sharepoint_item_and_integration_knowledge = AsyncMock(
            return_value=[_indexed_blob("Budget 2025.xlsx")]
        )

        with patch(
            "eneo.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
        ) as mock_client_class:
            mock_graph_client(
                mock_client_class,
                get_drive_root_children=AsyncMock(
                    return_value=[
                        delta_file("item-a", "a.docx"),
                        delta_file("item-b", "b.docx"),
                    ]
                ),
                get_file_extraction_by_id=AsyncMock(
                    return_value=ExtractionResult.ok("Body")
                ),
            )
            await service.pull_content(
                token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
            )

        repo.delete_by_sharepoint_item_and_integration_knowledge.assert_awaited_once_with(
            sharepoint_item_id="item-gone", integration_knowledge_id=ik.id
        )
        sync_log = mock_dependencies["sync_log_repo"].add.call_args[0][0]
        assert sync_log.sync_type == "full"
        assert sync_log.metadata["changed_details"] == [
            {"file": "a.docx", "change": "added"},
            {"file": "b.docx", "change": "updated"},
            {"file": "Budget 2025.xlsx", "change": "deleted"},
        ]
        assert sync_log.metadata["changed_total"] == 3
        assert sync_log.metadata["changed_truncated"] is False


class TestSelectedItemTypePersistence:
    """The full sync corrects selected_item_type from Graph; the correction
    must reach the row even though later steps re-read the knowledge."""

    @pytest.mark.parametrize(
        ("stale_type", "folder_id", "metadata", "expected"),
        [
            (
                "folder",
                "file-1",
                {"id": "file-1", "name": "doc.txt", "webUrl": "https://x/doc.txt"},
                "file",
            ),
            ("folder", None, None, "site_root"),
            (
                "site_root",
                "folder-a",
                {
                    "id": "folder-a",
                    "name": "A",
                    "folder": {},
                    "parentReference": {"path": "/drives/drive-456/root:/Docs"},
                },
                "folder",
            ),
        ],
    )
    async def test_correction_is_persisted(
        self,
        service,
        mock_dependencies,
        mock_oauth_token,
        stale_type,
        folder_id,
        metadata,
        expected,
    ):
        knowledge_id = uuid4()
        repo = mock_dependencies["integration_knowledge_repo"]

        # Like the mapper, every read yields a fresh entity: only an explicit
        # sync-state write carries an in-memory correction to the row.
        async def fresh_read(**_) -> IntegrationKnowledge:
            return real_integration_knowledge(
                id=knowledge_id, selected_item_type=stale_type, folder_id=folder_id
            )

        persisted: list[str] = []
        repo.one = AsyncMock(side_effect=fresh_read)
        repo.update_sync_state = AsyncMock(
            side_effect=lambda _id, **fields: persisted.append(
                fields.get("selected_item_type")
            )
        )
        mock_dependencies["oauth_token_repo"].one.return_value = mock_oauth_token
        mock_dependencies[
            "info_blob_service"
        ].repo.get_sharepoint_item_ids_for_integration_knowledge = AsyncMock(
            return_value=[]
        )

        with (
            patch(
                "eneo.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
            ) as mock_client_class,
            patch.object(service._index, "upsert", AsyncMock(return_value="added")),
        ):
            mock_graph_client(
                mock_client_class,
                get_file_metadata=AsyncMock(return_value=metadata),
                get_folder_items=AsyncMock(return_value=[]),
                get_file_extraction_by_id=AsyncMock(
                    return_value=ExtractionResult.ok("Body")
                ),
            )
            await service.pull_content(
                token_id=mock_oauth_token.id, integration_knowledge_id=knowledge_id
            )

        assert expected in persisted


def _run_clears(redis_client: AsyncMock) -> list[str]:
    """Keys whose clear removed the run's own entry only."""
    return [
        call.args[2]
        for call in redis_client.eval.await_args_list
        if call.args[0] == CLEAR_RUN_SCRIPT
    ]


def _progress_phases(redis_client: AsyncMock) -> list[dict]:
    """The first progress written in each phase, in order."""
    firsts: list[dict] = []
    for call in redis_client.set.await_args_list:
        progress = json.loads(call.args[1])
        if not firsts or firsts[-1]["phase"] != progress["phase"]:
            firsts.append(progress)
    return firsts


class TestSyncProgress:
    """A running sync publishes its progress and removes it when it ends."""

    @pytest.fixture
    def progress_redis(self):
        return AsyncMock()

    @pytest.fixture
    def progress_service(self, mock_dependencies, progress_redis):
        return SharePointContentService(
            **mock_dependencies,
            sync_progress_store=SharePointSyncProgressStore(progress_redis),
        )

    async def test_full_sync_total_grows_with_each_listing(
        self, progress_service, progress_redis, mock_dependencies, mock_oauth_token
    ):
        ik = real_integration_knowledge()
        mock_dependencies["oauth_token_repo"].one.return_value = mock_oauth_token
        mock_dependencies["integration_knowledge_repo"].one.return_value = ik
        mock_dependencies[
            "info_blob_service"
        ].repo.get_sharepoint_item_ids_for_integration_knowledge = AsyncMock(
            return_value=[]
        )
        subfolder = delta_file(
            "sub",
            "Bilagor",
            folder={"childCount": 1},
            parentReference={"driveId": "drive-456", "siteId": "site-123"},
        )
        page = {"id": "page-1", "name": "Start", "parentReference": {"siteId": "s"}}

        with patch(
            "eneo.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
        ) as mock_client_class:
            mock_graph_client(
                mock_client_class,
                get_drive_root_children=AsyncMock(
                    return_value=[
                        delta_file("a", "a.docx"),
                        delta_file("b", "b.docx"),
                        subfolder,
                    ]
                ),
                get_folder_items=AsyncMock(return_value=[delta_file("c", "c.docx")]),
                get_site_pages=AsyncMock(return_value={"value": [page]}),
                get_page_content=AsyncMock(
                    return_value={"title": "Start", "description": "Welcome"}
                ),
                get_file_extraction_by_id=AsyncMock(
                    return_value=ExtractionResult.ok("Body")
                ),
            )
            with patch.object(
                progress_service._index,
                "upsert",
                AsyncMock(side_effect=["added", "unchanged", "added", "added"]),
            ):
                await progress_service.pull_content(
                    token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
                )

        phases = _progress_phases(progress_redis)
        assert [
            (p["sync_type"], p["phase"], p["total"], p["done"], p["indexed"])
            for p in phases
        ] == [
            ("full", "discovering", None, 0, 0),
            ("full", "processing", 2, 0, 0),
            ("full", "finishing", 4, 4, 3),
        ]
        # The folder Bilagor is never in the feed; the page is.
        assert [(f["name"], f["outcome"]) for f in phases[-1]["recent"]] == [
            ("Start", "indexed"),
            ("c.docx", "indexed"),
            ("b.docx", "unchanged"),
            ("a.docx", "indexed"),
        ]
        assert _run_clears(progress_redis) == [sync_progress_key(ik.id)]

    async def test_delta_sync_counts_changes_without_a_total(
        self, progress_service, progress_redis, mock_dependencies, mock_oauth_token
    ):
        ik = real_integration_knowledge(delta_token="token-1")
        mock_dependencies["oauth_token_repo"].one.return_value = mock_oauth_token
        mock_dependencies["integration_knowledge_repo"].one.return_value = ik
        size_ledger(mock_dependencies["integration_knowledge_repo"], 100)
        mock_dependencies[
            "info_blob_service"
        ].repo.delete_by_sharepoint_item_and_integration_knowledge = AsyncMock(
            return_value=[MagicMock(size=40)]
        )
        changes = [
            delta_file("a", "a.docx"),
            delta_file("b", "b.docx"),
            {"id": "old", "name": "old.docx", "deleted": {"state": "deleted"}},
        ]

        with patch(
            "eneo.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
        ) as mock_client_class:
            mock_graph_client(
                mock_client_class,
                get_delta_changes=AsyncMock(return_value=(changes, "token-2")),
                get_file_extraction_by_id=AsyncMock(
                    return_value=ExtractionResult.ok("Body")
                ),
            )
            with patch.object(
                progress_service._index,
                "upsert",
                AsyncMock(side_effect=["added", "unchanged"]),
            ):
                await progress_service.process_delta_changes(
                    token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
                )

        phases = _progress_phases(progress_redis)
        assert [
            (p["sync_type"], p["phase"], p["total"], p["done"], p["deleted"])
            for p in phases
        ] == [
            ("delta", "discovering", None, 0, 0),
            ("delta", "processing", None, 0, 0),
            ("delta", "finishing", None, 2, 1),
        ]
        # The deleted old.docx is counted under deleted, not in the feed.
        assert [(f["name"], f["outcome"]) for f in phases[-1]["recent"]] == [
            ("b.docx", "unchanged"),
            ("a.docx", "indexed"),
        ]
        assert _run_clears(progress_redis) == [sync_progress_key(ik.id)]

    @pytest.mark.parametrize("mode", ["full", "delta"])
    async def test_a_failed_sync_removes_its_progress(
        self,
        progress_service,
        progress_redis,
        mock_dependencies,
        mock_oauth_token,
        mode,
    ):
        ik = real_integration_knowledge(delta_token="token-1")
        mock_dependencies["oauth_token_repo"].one.return_value = mock_oauth_token
        mock_dependencies["integration_knowledge_repo"].one.return_value = ik

        with patch(
            "eneo.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
        ) as mock_client_class:
            mock_graph_client(
                mock_client_class,
                get_drive_root_children=AsyncMock(side_effect=RuntimeError("503")),
                get_delta_changes=AsyncMock(side_effect=RuntimeError("503")),
            )
            with pytest.raises(RuntimeError, match="503"):
                if mode == "full":
                    await progress_service.pull_content(
                        token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
                    )
                else:
                    await progress_service.process_delta_changes(
                        token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
                    )

        assert _progress_phases(progress_redis)[0]["sync_type"] == mode
        assert _run_clears(progress_redis) == [sync_progress_key(ik.id)]
        assert ik.last_sync_status == "error"

    @pytest.fixture
    def transaction(self, mock_dependencies, progress_redis):
        """A real session for the after-transaction hook."""
        engine = sa.create_engine("sqlite://")
        sync_session = Session(engine)
        mock_dependencies["session"].sync_session = sync_session
        sync_session.begin()
        yield sync_session
        sync_session.close()
        engine.dispose()

    @pytest.mark.parametrize("ending", ["commit", "rollback"])
    async def test_progress_stays_until_the_sync_transaction_ends(
        self,
        progress_service,
        progress_redis,
        mock_dependencies,
        mock_oauth_token,
        transaction,
        ending,
    ):
        """Until the commit the item's rows still hold what was there before
        the sync, so the page must keep showing it as syncing."""
        ik = real_integration_knowledge(delta_token="token-1")
        mock_dependencies["oauth_token_repo"].one.return_value = mock_oauth_token
        mock_dependencies["integration_knowledge_repo"].one.return_value = ik
        key = sync_progress_key(ik.id)

        with patch(
            "eneo.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
        ) as mock_client_class:
            mock_graph_client(
                mock_client_class,
                get_delta_changes=AsyncMock(return_value=([], "token-2")),
            )
            await progress_service.process_delta_changes(
                token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
            )
        # A pending delta pass publishes in savepoints inside the same
        # transaction; neither a released nor a rolled-back one is its end.
        with transaction.begin_nested():
            transaction.execute(sa.text("SELECT 1"))
        transaction.begin_nested().rollback()
        await asyncio.sleep(0)

        progress_redis.delete.assert_not_awaited()
        progress_redis.eval.assert_not_awaited()
        progress_redis.expire.assert_awaited_once_with(key, FINISHED_TTL_SECONDS)

        getattr(transaction, ending)()
        await asyncio.gather(*progress_service._post_transaction_tasks)

        assert _run_clears(progress_redis) == [key]

    async def test_a_transaction_rolled_back_by_a_failed_flush_clears_at_once(
        self,
        progress_service,
        progress_redis,
        mock_dependencies,
        mock_oauth_token,
        transaction,
    ):
        """The rollback came before the sync ended, so no rollback event is
        left to clear the entry; it must not show a running sync until it
        lapses."""
        ik = real_integration_knowledge(delta_token="token-1")
        mock_dependencies["oauth_token_repo"].one.return_value = mock_oauth_token
        mock_dependencies["integration_knowledge_repo"].one.return_value = ik

        def failing_flush(**_):
            _fail_a_flush(transaction)
            raise sa.exc.IntegrityError("INSERT", {}, Exception("duplicate key"))

        with patch(
            "eneo.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
        ) as mock_client_class:
            mock_graph_client(
                mock_client_class,
                get_delta_changes=AsyncMock(side_effect=failing_flush),
            )
            with pytest.raises(sa.exc.IntegrityError):
                await progress_service.process_delta_changes(
                    token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
                )

        assert _run_clears(progress_redis) == [sync_progress_key(ik.id)]
        progress_redis.expire.assert_not_awaited()
        assert not progress_service._post_transaction_tasks

    async def test_a_delta_that_falls_back_to_a_full_sync_clears_once(
        self,
        progress_service,
        progress_redis,
        mock_dependencies,
        mock_oauth_token,
        transaction,
    ):
        ik = real_integration_knowledge()
        mock_dependencies["oauth_token_repo"].one.return_value = mock_oauth_token
        mock_dependencies["integration_knowledge_repo"].one.return_value = ik

        with patch(
            "eneo.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
        ) as mock_client_class:
            mock_graph_client(mock_client_class)
            await progress_service.process_delta_changes(
                token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
            )

        assert [p["sync_type"] for p in _progress_phases(progress_redis)][:2] == [
            "delta",
            "full",
        ]
        progress_redis.expire.assert_awaited_once()
        transaction.commit()
        await asyncio.gather(*progress_service._post_transaction_tasks)
        assert _run_clears(progress_redis) == [sync_progress_key(ik.id)]

    @pytest.mark.parametrize("removal", ["succeeds", "fails"])
    async def test_text_that_sanitises_to_nothing_shows_why_in_the_feed(
        self,
        progress_service,
        progress_redis,
        mock_dependencies,
        mock_oauth_token,
        removal,
    ):
        """When removing the old copy fails, that failure is the file's reason,
        and the pass fails so the next sync retries the file."""
        ik = real_integration_knowledge(delta_token="token-1")
        mock_dependencies["oauth_token_repo"].one.return_value = mock_oauth_token
        mock_dependencies["integration_knowledge_repo"].one.return_value = ik
        mock_dependencies[
            "info_blob_service"
        ].repo.delete_by_sharepoint_item_and_integration_knowledge = (
            AsyncMock(return_value=[])
            if removal == "succeeds"
            else AsyncMock(side_effect=RuntimeError("503"))
        )

        with patch(
            "eneo.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
        ) as mock_client_class:
            mock_graph_client(
                mock_client_class,
                get_delta_changes=AsyncMock(
                    return_value=([delta_file("item-1", "nulls.txt")], "token-2")
                ),
                get_file_extraction_by_id=AsyncMock(
                    return_value=ExtractionResult.ok("\x00\x00", "text/plain")
                ),
            )
            run = progress_service.process_delta_changes(
                token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
            )
            if removal == "succeeds":
                await run
            else:
                with pytest.raises(SyncItemsFailed):
                    await run

        reason = (
            EMPTY_CONTENT_REASON
            if removal == "succeeds"
            else "Could not remove unextractable: 503"
        )
        assert _feed(_progress_phases(progress_redis)[-1]["recent"]) == [
            {"name": "nulls.txt", "outcome": "skipped", "reason": reason}
        ]


# Delta changes cover the whole drive. These names sit outside the imported
# folder (or cannot be placed in it) and must never reach its readers.
_OUT_OF_SCOPE_NAMES = (
    "Lönelista HR.xlsx",
    "Hemligt",
    "Dold fil.xlsx",
    "Raderad.docx",
    "Utan id.pdf",
)


def _scope_child(item_id: str, name: str, parent: str = "folder-a") -> dict:
    return delta_file(
        item_id,
        name,
        parentReference={
            "id": parent,
            "driveId": "drive-123",
            "path": f"/drives/drive-123/root:/Documents/{parent}",
        },
    )


def _scope_folder_metadata() -> dict:
    """What Graph says about the imported folder: it is still at its stored path."""
    return {
        "id": "folder-a",
        "name": "folder-a",
        "folder": {"childCount": 2},
        "parentReference": {
            "driveId": "drive-123",
            "path": "/drives/drive-123/root:/Documents",
        },
    }


def _outside(item_id: str | None, name: str, **facets) -> dict:
    return {
        **({"id": item_id} if item_id else {}),
        "name": name,
        "parentReference": {
            "id": "hr",
            "driveId": "drive-123",
            "path": "/drives/drive-123/root:/Documents/HR",
        },
        **facets,
    }


class TestOutOfScopeNamesStayPrivate:
    """Readers of an item see its own files only, never other files of the drive."""

    @pytest.fixture
    def progress_redis(self):
        return AsyncMock()

    @pytest.fixture
    def unthrottled_service(self, mock_dependencies, progress_redis):
        service = SharePointContentService(**mock_dependencies)
        # Every update is written, so whatever any update holds is seen.
        service._progress = SyncProgressReporter(
            SharePointSyncProgressStore(progress_redis),
            min_interval_seconds=0,
            heartbeat_interval_seconds=None,
        )
        return service

    @pytest.fixture
    def logged(self):
        records: list[str] = []

        class Collect(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                records.append(record.getMessage())

        # Every module of the split sync; one without a logger is covered once it gets one.
        loggers = [
            module.logger
            for module in (
                content_service_module,
                scope_rules,
                sync_results,
                index_module,
                reconciliation_module,
            )
            if hasattr(module, "logger")
        ]
        handler = Collect(logging.DEBUG)
        levels = [logger.level for logger in loggers]
        for logger in loggers:
            logger.addHandler(handler)
            logger.setLevel(logging.DEBUG)
        yield records
        for logger, level in zip(loggers, levels):
            logger.removeHandler(handler)
            logger.setLevel(level)

    async def _run_delta(
        self,
        service,
        mock_dependencies,
        mock_oauth_token,
        ik,
        changes,
        *,
        scope_folder,
        fails=False,
    ):
        mock_dependencies["oauth_token_repo"].one.return_value = mock_oauth_token
        mock_dependencies["integration_knowledge_repo"].one.return_value = ik
        # Every removal fails, so each item that is cleaned up also leaves a
        # skip detail behind, and a pass that cleaned something up fails.
        mock_dependencies[
            "info_blob_service"
        ].repo.delete_by_sharepoint_item_and_integration_knowledge = AsyncMock(
            side_effect=RuntimeError("database unavailable")
        )
        with (
            patch(
                "eneo.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
            ) as mock_client_class,
            patch.object(
                service._index,
                "upsert",
                AsyncMock(side_effect=["added", "added"]),
            ),
            patch.object(
                scope_rules,
                "enumerate_items",
                AsyncMock(
                    return_value=[
                        {
                            "id": "hidden-child",
                            "name": "Dold fil.xlsx",
                            "file": {},
                            "parentReference": {
                                "id": "out-folder",
                                "path": "/drives/drive-123/root:/Documents/HR/Hemligt",
                            },
                        }
                    ]
                ),
            ),
        ):
            mock_graph_client(
                mock_client_class,
                get_delta_changes=AsyncMock(return_value=(changes, "token-2")),
                get_file_metadata=scope_folder,
                get_file_extraction_by_id=AsyncMock(
                    return_value=ExtractionResult.ok("Body")
                ),
            )
            run = service.process_delta_changes(
                token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
            )
            if fails:
                with pytest.raises(SyncItemsFailed):
                    await run
            else:
                await run

    def _published(self, progress_redis) -> list[dict]:
        return [json.loads(call.args[1]) for call in progress_redis.set.await_args_list]

    def _assert_private(self, mock_dependencies, progress_redis, ik, logged):
        sync_log = mock_dependencies["sync_log_repo"].add.call_args[0][0]
        seen = {
            "progress": json.dumps(self._published(progress_redis), ensure_ascii=False),
            "sync log": json.dumps(sync_log.metadata, ensure_ascii=False),
            "summary": json.dumps(ik.last_sync_summary, ensure_ascii=False),
            "logs": "\n".join(logged),
        }
        for where, text in seen.items():
            for name in _OUT_OF_SCOPE_NAMES:
                assert name not in text, f"{name} in the {where}"
        return sync_log

    async def test_no_name_outside_the_folder_is_published_or_logged(
        self,
        unthrottled_service,
        mock_dependencies,
        mock_oauth_token,
        progress_redis,
        logged,
    ):
        ik = real_integration_knowledge(
            delta_token="token-1",
            drive_id="drive-123",
            folder_id="folder-a",
            folder_path="/Documents/folder-a",
            selected_item_type="folder",
        )
        changes = [
            _scope_child("in-1", "Protokoll.docx"),
            _outside("out-1", "Lönelista HR.xlsx", file={}),
            _outside("out-folder", "Hemligt", folder={"childCount": 1}),
            {"id": "gone-1", "name": "Raderad.docx", "deleted": {"state": "deleted"}},
            _outside(None, "Utan id.pdf", file={}),
            _scope_child("in-2", "Budget.docx"),
        ]

        # The optimized cleanup walks only when a descendant was indexed.
        mock_dependencies[
            "info_blob_service"
        ].repo.get_sharepoint_item_ids_for_integration_knowledge.return_value = [
            (uuid4(), "hidden-child")
        ]
        await self._run_delta(
            unthrottled_service,
            mock_dependencies,
            mock_oauth_token,
            ik,
            changes,
            scope_folder=AsyncMock(return_value=_scope_folder_metadata()),
            fails=True,
        )

        sync_log = self._assert_private(mock_dependencies, progress_redis, ik, logged)
        # The item's own files are still shown, with their own outcomes.
        published = self._published(progress_redis)
        assert {p["current"] for p in published} == {
            None,
            "Protokoll.docx",
            "Budget.docx",
        }
        assert _feed(published[-1]["recent"]) == [
            {"name": "Budget.docx", "outcome": "indexed", "reason": None},
            {"name": "Protokoll.docx", "outcome": "indexed", "reason": None},
        ]
        assert [detail["file"] for detail in sync_log.metadata["skipped_details"]] == [
            "out-1",
            "out-folder",
            "hidden-child",
            "gone-1",
        ]
        # The id-less item is counted, not listed.
        assert sync_log.metadata["skipped_items"] == 5

    @pytest.mark.parametrize("status", [403, 429])
    async def test_pathless_placement_failures_keep_unconfirmed_names_private(
        self,
        unthrottled_service,
        mock_dependencies,
        mock_oauth_token,
        progress_redis,
        logged,
        status,
    ):
        ik = real_integration_knowledge(
            delta_token="token-1",
            drive_id="drive-123",
            folder_id="folder-a",
            folder_path="/Documents/folder-a",
            selected_item_type="folder",
        )
        item = _outside("unplaced", "Lönelista HR.xlsx", file={})
        del item["parentReference"]["path"]

        async def locate(*, drive_id, item_id):
            if item_id == "folder-a":
                return _scope_folder_metadata()
            raise http_error(status, "Placement unavailable")

        await self._run_delta(
            unthrottled_service,
            mock_dependencies,
            mock_oauth_token,
            ik,
            [item],
            scope_folder=AsyncMock(side_effect=locate),
            fails=status == 429,
        )
        sync_log = self._assert_private(mock_dependencies, progress_redis, ik, logged)
        detail = sync_log.metadata["skipped_details"][0]
        assert detail["file"] == "unplaced"
        assert detail["code"] == "error"
        assert detail.get("retry", False) is (status == 429)
        assert ik.delta_token == ("token-1" if status == 429 else "token-2")
        mock_dependencies[
            "info_blob_service"
        ].repo.delete_by_sharepoint_item_and_integration_knowledge.assert_not_awaited()

    async def test_unplaceable_items_are_listed_by_id_when_the_folder_path_is_unknown(
        self,
        unthrottled_service,
        mock_dependencies,
        mock_oauth_token,
        progress_redis,
        logged,
    ):
        ik = real_integration_knowledge(
            delta_token="token-1",
            drive_id="drive-123",
            folder_id="folder-a",
            folder_path=None,
            selected_item_type="folder",
        )
        changes = [
            _scope_child("in-1", "Protokoll.docx"),
            _outside("out-1", "Lönelista HR.xlsx", file={}),
        ]

        # Graph does not know the folder either, so nothing can be placed.
        await self._run_delta(
            unthrottled_service,
            mock_dependencies,
            mock_oauth_token,
            ik,
            changes,
            scope_folder=AsyncMock(side_effect=_refused(404, "Not Found")),
        )

        sync_log = self._assert_private(mock_dependencies, progress_redis, ik, logged)
        assert reasons(sync_log.metadata["skipped_details"]) == [
            {"file": "out-1", "reason": "Folder scope path unavailable"}
        ]


_SIGNED_URL = (
    "https://contoso.sharepoint.com/sites/KS/_layouts/15/download.aspx"
    "?UniqueId=abc&tempauth=v1.eyJzaWduZWQiOiJ0b2tlbiJ9.c2lnbmF0dXJl&ApiVersion=2.0"
)
# Fragments of URLs, SQL, bound values and internal hosts that the errors
# below carry and that no user may see.
_INTERNALS = (
    "tempauth",
    "eyJ",
    "DELETE FROM",
    "secret-param",
    "db.internal",
    "10.0.0.7",
    "redis.internal",
)


def _refused(
    status: int = 403, reason: str = "Forbidden"
) -> aiohttp.ClientResponseError:
    url = URL(_SIGNED_URL)
    return aiohttp.ClientResponseError(
        RequestInfo(url, "GET", CIMultiDictProxy(CIMultiDict()), url),
        (),
        status=status,
        message=reason,
    )


def _database_error() -> sa.exc.OperationalError:
    return sa.exc.OperationalError(
        "DELETE FROM info_blobs WHERE sharepoint_item_id = %(id)s",
        {"id": "secret-param"},
        Exception('connection to server at "db.internal" (10.0.0.7), port 5432 failed'),
    )


def _redis_error() -> RedisConnectionError:
    return RedisConnectionError("Error 111 connecting to redis.internal:6379.")


def _assert_no_internals(*texts: str) -> None:
    for text in texts:
        for fragment in _INTERNALS:
            assert fragment not in text, f"{fragment!r} in {text!r}"


class TestUserVisibleErrors:
    """Skip reasons, sync status and sync logs describe errors without their
    URLs, SQL, bound values or host names."""

    @pytest.fixture
    def progress_redis(self):
        return AsyncMock()

    @pytest.fixture
    def visible_service(self, mock_dependencies, progress_redis):
        service = SharePointContentService(**mock_dependencies)
        service._progress = SyncProgressReporter(
            SharePointSyncProgressStore(progress_redis),
            min_interval_seconds=0,
            heartbeat_interval_seconds=None,
        )
        return service

    async def test_skip_reasons_name_the_kind_of_failure(
        self, visible_service, mock_dependencies, mock_oauth_token, progress_redis
    ):
        ik = real_integration_knowledge(
            delta_token="token-1",
            drive_id="drive-123",
            folder_id="folder-a",
            folder_path="/Documents/folder-a",
            selected_item_type="folder",
        )
        mock_dependencies["oauth_token_repo"].one.return_value = mock_oauth_token
        mock_dependencies["integration_knowledge_repo"].one.return_value = ik
        mock_dependencies["change_key_service"].should_process.side_effect = [
            True,
            _redis_error(),
            True,
        ]
        mock_dependencies[
            "info_blob_service"
        ].repo.delete_by_sharepoint_item_and_integration_knowledge = AsyncMock(
            side_effect=_database_error()
        )
        changes = [
            _scope_child("refused", "refused.docx"),
            _scope_child("cached", "cached.docx"),
            _scope_child("empty", "empty.docx"),
            _outside("away", "away.docx", file={}),
        ]

        with patch(
            "eneo.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
        ) as mock_client_class:
            mock_graph_client(
                mock_client_class,
                get_delta_changes=AsyncMock(return_value=(changes, "token-2")),
                get_file_metadata=AsyncMock(return_value=_scope_folder_metadata()),
                get_file_extraction_by_id=AsyncMock(
                    side_effect=[
                        _refused(),
                        ExtractionResult.no_text(EMPTY_CONTENT_REASON),
                    ]
                ),
            )
            # The cache and database failures say nothing about the files, so
            # the pass fails and the next sync retries them.
            with pytest.raises(SyncItemsFailed):
                await visible_service.process_delta_changes(
                    token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
                )

        sync_log = mock_dependencies["sync_log_repo"].add.call_args[0][0]
        assert reasons(sync_log.metadata["skipped_details"]) == [
            {"file": "refused.docx", "reason": "Error: HTTP 403 Forbidden"},
            {
                "file": "cached.docx",
                "reason": "Error: Cache service error",
                "retry": True,
            },
            {
                "file": "empty.docx",
                "reason": "Could not remove unextractable: Database error",
                "retry": True,
            },
            {
                "file": "away",
                "reason": "Could not remove out-of-scope: Database error",
                "retry": True,
            },
        ]
        published = [call.args[1] for call in progress_redis.set.await_args_list]
        assert _feed(json.loads(published[-1])["recent"])[-1] == {
            "name": "refused.docx",
            "outcome": "skipped",
            "reason": "Error: HTTP 403 Forbidden",
        }
        _assert_no_internals(
            json.dumps(sync_log.metadata), json.dumps(ik.last_sync_summary), *published
        )

    @pytest.mark.parametrize(
        ("make_error", "expected"),
        [
            (
                lambda: _refused(503, "Service Unavailable"),
                "HTTP 503 Service Unavailable",
            ),
            (_database_error, "Database error"),
            (_redis_error, "Cache service error"),
        ],
        ids=["http", "database", "redis"],
    )
    @pytest.mark.parametrize("mode", ["full", "delta"])
    async def test_a_failed_sync_records_the_kind_of_failure(
        self, service, mock_dependencies, mock_oauth_token, make_error, expected, mode
    ):
        ik = real_integration_knowledge(delta_token="token-1")
        mock_dependencies["oauth_token_repo"].one.return_value = mock_oauth_token
        mock_dependencies["integration_knowledge_repo"].one.return_value = ik
        error = make_error()

        with patch(
            "eneo.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
        ) as mock_client_class:
            mock_graph_client(
                mock_client_class,
                get_drive_root_children=AsyncMock(side_effect=error),
                get_delta_changes=AsyncMock(side_effect=error),
            )
            with pytest.raises(type(error)):
                if mode == "full":
                    await service.pull_content(
                        token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
                    )
                else:
                    await service.process_delta_changes(
                        token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
                    )

        sync_log = mock_dependencies["sync_log_repo"].add.call_args[0][0]
        assert (ik.last_sync_error, sync_log.error_message) == (expected, expected)

    async def test_skipped_cleanup_and_unlistable_folders_say_why_without_internals(
        self, service, mock_integration_knowledge
    ):
        client = AsyncMock()
        client.get_drive_root_children.return_value = []
        client.get_site_pages.return_value = {"value": []}
        stats = sync_results.initialize_stats()
        service._index.info_blob_service.repo.get_sharepoint_item_ids_for_integration_knowledge = AsyncMock(
            side_effect=_database_error()
        )

        await service._reconciliation.reconcile(
            client=client,
            integration_knowledge=mock_integration_knowledge,
            resource_type="site",
            site_id="site-1",
            drive_id="drive-1",
            folder_id=None,
            stats=stats,
        )
        with patch.object(
            scope_rules,
            "enumerate_items",
            AsyncMock(side_effect=_refused()),
        ):
            await service._index_folder_subtree_entering_scope(
                content_client=client,
                resource_type="site",
                site_id="site-1",
                drive_id="drive-1",
                folder_id="folder-x",
                folder_name="X",
                integration_knowledge=mock_integration_knowledge,
                stats=stats,
                pending_change_keys=[],
                change_ids=set(),
                indexed_ids=set(),
            )
        client.get_page_content.side_effect = _refused(404, "Not Found")
        await service._process_pages(
            pages=[
                {"id": "p-1", "name": "Start.aspx", "parentReference": {"siteId": "s"}}
            ],
            client=client,
            integration_knowledge=mock_integration_knowledge,
            stats=stats,
        )

        assert stats["reconcile_warning"] == (
            "Orphan cleanup skipped: could not list SharePoint items (Database error)"
        )
        assert reasons(stats["skipped_details"]) == [
            {
                "file": "X",
                "reason": "Could not list folder contents: HTTP 403 Forbidden",
                "retry": True,
            },
            {
                "file": "Start.aspx",
                "reason": "Error: HTTP 404 Not Found",
                "retry": True,
            },
        ]

    def test_the_summary_cleans_whatever_text_reached_the_stats(self, service):
        stats = sync_results.initialize_stats()
        stats["skipped_items"] = 1
        stats["skipped_details"] = [
            {
                "file": "a.docx",
                "reason": f"Error: 403, message='Forbidden', url='{_SIGNED_URL}'",
            }
        ]
        stats["reconcile_warning"] = f"Orphan cleanup skipped ({_SIGNED_URL})"

        summary = sync_results.build_summary_stats(stats)

        assert reasons(summary["skipped_details"]) == [
            {"file": "a.docx", "reason": "Error: HTTP 403 Forbidden"}
        ]
        assert summary["reconcile_warning"] == (
            "Orphan cleanup skipped (https://contoso.sharepoint.com/sites/KS/"
            "_layouts/15/download.aspx)"
        )
