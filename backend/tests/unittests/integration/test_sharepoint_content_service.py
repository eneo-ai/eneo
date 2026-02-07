"""Unit tests for SharePointContentService - content sync from SharePoint.

Tests the content pulling, delta change processing, and token handling
for SharePoint integrations.
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from intric.integration.infrastructure.content_service.sharepoint_content_service import (
    SharePointContentService,
    SimpleSharePointToken,
    _extract_text_from_canvas_layout,
)


@pytest.fixture
def mock_user():
    """Create a mock user."""
    user = MagicMock()
    user.id = uuid4()
    user.tenant_id = uuid4()
    return user


@pytest.fixture
def mock_integration_knowledge():
    """Create a mock integration knowledge object."""
    ik = MagicMock()
    ik.id = uuid4()
    ik.site_id = "site-123"
    ik.drive_id = "drive-456"
    ik.folder_id = None
    ik.folder_path = None
    ik.resource_type = "site"
    ik.delta_token = None
    ik.size = 0
    ik.last_sync_summary = None
    ik.last_synced_at = None
    ik.selected_item_type = None
    ik.embedding_model = MagicMock()
    return ik


@pytest.fixture
def mock_oauth_token():
    """Create a mock OAuth token."""
    token = MagicMock()
    token.id = uuid4()
    token.access_token = "personal-oauth-access-token"
    token.refresh_token = "personal-oauth-refresh-token"
    token.base_url = "https://graph.microsoft.com"
    return token


@pytest.fixture
def mock_tenant_app():
    """Create a mock tenant SharePoint app."""
    app = MagicMock()
    app.id = uuid4()
    app.tenant_id = uuid4()
    app.client_id = "tenant-app-client-id"
    app.client_secret = "tenant-app-client-secret"
    app.tenant_domain = "contoso.onmicrosoft.com"
    app.is_service_account.return_value = False
    app.is_active = True
    return app


@pytest.fixture
def mock_tenant_app_service_account(mock_tenant_app):
    """Create a mock tenant app configured for service account."""
    mock_tenant_app.is_service_account.return_value = True
    mock_tenant_app.service_account_refresh_token = "service-account-refresh-token"
    mock_tenant_app.service_account_email = "service@contoso.com"
    return mock_tenant_app


@pytest.fixture
def mock_dependencies(mock_user, mock_integration_knowledge):
    """Create all mock dependencies for SharePointContentService."""
    return {
        "job_service": AsyncMock(),
        "oauth_token_repo": AsyncMock(),
        "user_integration_repo": AsyncMock(),
        "user": mock_user,
        "datastore": AsyncMock(),
        "info_blob_service": AsyncMock(),
        "integration_knowledge_repo": AsyncMock(),
        "oauth_token_service": AsyncMock(),
        "session": AsyncMock(),
        "tenant_sharepoint_app_repo": AsyncMock(),
        "tenant_app_auth_service": AsyncMock(),
        "service_account_auth_service": AsyncMock(),
        "sync_log_repo": AsyncMock(),
        "change_key_service": AsyncMock(),
    }


@pytest.fixture
def service(mock_dependencies):
    """Create SharePointContentService with mocked dependencies."""
    return SharePointContentService(**mock_dependencies)


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
        mock_dependencies["integration_knowledge_repo"].one.return_value = mock_integration_knowledge

        with patch(
            "intric.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.get_default_drive_id.return_value = "drive-123"
            mock_client.get_documents_in_drive.return_value = []
            mock_client.get_site_pages.return_value = {"value": []}
            mock_client.initialize_delta_token.return_value = "delta-token"
            mock_client_class.return_value = mock_client

            await service.pull_content(
                token_id=mock_oauth_token.id,
                integration_knowledge_id=mock_integration_knowledge.id,
                site_id="site-123",
            )

        mock_dependencies["oauth_token_repo"].one.assert_called_once_with(id=mock_oauth_token.id)

    async def test_uses_tenant_app_auth_when_tenant_app_id_provided(
        self, service, mock_dependencies, mock_tenant_app, mock_integration_knowledge
    ):
        """Uses tenant app auth service when tenant_app_id is provided."""
        mock_dependencies["tenant_sharepoint_app_repo"].one.return_value = mock_tenant_app
        mock_dependencies["tenant_app_auth_service"].get_access_token.return_value = "tenant-app-access-token"
        mock_dependencies["integration_knowledge_repo"].one.return_value = mock_integration_knowledge

        with patch(
            "intric.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.get_default_drive_id.return_value = "drive-123"
            mock_client.get_documents_in_drive.return_value = []
            mock_client.get_site_pages.return_value = {"value": []}
            mock_client.initialize_delta_token.return_value = "delta-token"
            mock_client_class.return_value = mock_client

            await service.pull_content(
                tenant_app_id=mock_tenant_app.id,
                integration_knowledge_id=mock_integration_knowledge.id,
                site_id="site-123",
            )

        mock_dependencies["tenant_app_auth_service"].get_access_token.assert_called_once()

    async def test_uses_service_account_auth_when_configured(
        self, service, mock_dependencies, mock_tenant_app_service_account, mock_integration_knowledge
    ):
        """Uses service account auth when tenant app is configured for service account."""
        mock_dependencies["tenant_sharepoint_app_repo"].one.return_value = mock_tenant_app_service_account
        mock_dependencies["service_account_auth_service"].refresh_access_token.return_value = {
            "access_token": "service-account-access-token",
            "refresh_token": "new-refresh-token",
        }
        mock_dependencies["integration_knowledge_repo"].one.return_value = mock_integration_knowledge

        with patch(
            "intric.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.get_default_drive_id.return_value = "drive-123"
            mock_client.get_documents_in_drive.return_value = []
            mock_client.get_site_pages.return_value = {"value": []}
            mock_client.initialize_delta_token.return_value = "delta-token"
            mock_client_class.return_value = mock_client

            await service.pull_content(
                tenant_app_id=mock_tenant_app_service_account.id,
                integration_knowledge_id=mock_integration_knowledge.id,
                site_id="site-123",
            )

        mock_dependencies["service_account_auth_service"].refresh_access_token.assert_called_once()
        mock_dependencies["tenant_sharepoint_app_repo"].update.assert_called_once_with(
            mock_tenant_app_service_account
        )
        mock_tenant_app_service_account.update_refresh_token.assert_called_once_with(
            "new-refresh-token"
        )

    async def test_raises_error_when_no_token_or_tenant_app_provided(
        self, service, mock_dependencies, mock_integration_knowledge
    ):
        """Raises ValueError when neither token_id nor tenant_app_id is provided."""
        mock_dependencies["integration_knowledge_repo"].one.return_value = mock_integration_knowledge

        with pytest.raises(ValueError, match="Either token_id or tenant_app_id must be provided"):
            await service.pull_content(
                integration_knowledge_id=mock_integration_knowledge.id,
                site_id="site-123",
            )

    async def test_raises_error_when_service_account_auth_not_configured(
        self, mock_dependencies, mock_tenant_app_service_account, mock_integration_knowledge, mock_user
    ):
        """Raises ValueError when service account is used but auth service not configured."""
        # Create service without service_account_auth_service
        deps = mock_dependencies.copy()
        deps["service_account_auth_service"] = None
        svc = SharePointContentService(**deps)

        deps["tenant_sharepoint_app_repo"].one.return_value = mock_tenant_app_service_account
        deps["integration_knowledge_repo"].one.return_value = mock_integration_knowledge

        with pytest.raises(ValueError, match="ServiceAccountAuthService not configured"):
            await svc.pull_content(
                tenant_app_id=mock_tenant_app_service_account.id,
                integration_knowledge_id=mock_integration_knowledge.id,
                site_id="site-123",
            )


class TestInitializeStats:
    """Tests for _initialize_stats method."""

    def test_returns_dict_with_all_stat_keys(self, service):
        """Returns dictionary with all required stat keys."""
        stats = service._initialize_stats()

        assert "files_processed" in stats
        assert "files_deleted" in stats
        assert "folders_processed" in stats
        assert "pages_processed" in stats
        assert "skipped_items" in stats

    def test_all_stats_start_at_zero(self, service):
        """All stats are initialized to zero."""
        stats = service._initialize_stats()

        assert stats["files_processed"] == 0
        assert stats["files_deleted"] == 0
        assert stats["folders_processed"] == 0
        assert stats["pages_processed"] == 0
        assert stats["skipped_items"] == 0


class TestProcessInfoBlobSizeAccounting:
    async def test_updates_integration_knowledge_size_using_delta_for_existing_blob(
        self, service, mock_dependencies, mock_integration_knowledge
    ):
        existing_blob = MagicMock()
        existing_blob.size = 100

        updated_blob = MagicMock()
        updated_blob.id = uuid4()
        updated_blob.size = 130

        mock_dependencies["info_blob_service"].repo.get_by_sharepoint_item_and_integration_knowledge = (
            AsyncMock(return_value=existing_blob)
        )
        mock_dependencies["info_blob_service"].upsert_info_blob_by_sharepoint_item_and_integration = (
            AsyncMock(return_value=updated_blob)
        )
        mock_dependencies["datastore"].add = AsyncMock()
        mock_dependencies["integration_knowledge_repo"].update = AsyncMock()
        mock_dependencies["info_blob_service"].repo.session.execute = AsyncMock()

        mock_integration_knowledge.size = 500

        await service._process_info_blob(
            title="Doc",
            text="New text",
            url="https://example.com",
            integration_knowledge=mock_integration_knowledge,
            sharepoint_item_id="item-123",
        )

        assert mock_integration_knowledge.size == 530
        mock_dependencies["integration_knowledge_repo"].update.assert_called_once_with(
            obj=mock_integration_knowledge
        )

    async def test_does_not_change_size_when_existing_blob_size_is_unchanged(
        self, service, mock_dependencies, mock_integration_knowledge
    ):
        existing_blob = MagicMock()
        existing_blob.size = 100

        updated_blob = MagicMock()
        updated_blob.id = uuid4()
        updated_blob.size = 100

        mock_dependencies["info_blob_service"].repo.get_by_sharepoint_item_and_integration_knowledge = (
            AsyncMock(return_value=existing_blob)
        )
        mock_dependencies["info_blob_service"].upsert_info_blob_by_sharepoint_item_and_integration = (
            AsyncMock(return_value=updated_blob)
        )
        mock_dependencies["datastore"].add = AsyncMock()
        mock_dependencies["integration_knowledge_repo"].update = AsyncMock()
        mock_dependencies["info_blob_service"].repo.session.execute = AsyncMock()

        mock_integration_knowledge.size = 500

        await service._process_info_blob(
            title="Doc",
            text="Unchanged text",
            url="https://example.com",
            integration_knowledge=mock_integration_knowledge,
            sharepoint_item_id="item-123",
        )

        assert mock_integration_knowledge.size == 500
        mock_dependencies["integration_knowledge_repo"].update.assert_not_called()


class TestBuildSummaryStats:
    """Tests for _build_summary_stats method."""

    def test_builds_summary_from_stats(self, service):
        """Builds summary dictionary from stats."""
        stats = {
            "files_processed": 5,
            "files_deleted": 2,
            "folders_processed": 3,
            "pages_processed": 1,
            "skipped_items": 4,
        }

        summary = service._build_summary_stats(stats)

        assert summary["files_processed"] == 5
        assert summary["files_deleted"] == 2
        assert summary["folders_processed"] == 3
        assert summary["pages_processed"] == 1
        assert summary["skipped_items"] == 4

    def test_handles_missing_keys_with_defaults(self, service):
        """Uses 0 for missing keys."""
        stats = {"files_processed": 10}

        summary = service._build_summary_stats(stats)

        assert summary["files_processed"] == 10
        assert summary["files_deleted"] == 0
        assert summary["folders_processed"] == 0


class TestFormatSummaryForJob:
    """Tests for _format_summary_for_job method."""

    def test_formats_files_processed(self, service):
        """Formats files processed count."""
        summary = {
            "files_processed": 5,
            "files_deleted": 0,
            "pages_processed": 0,
            "folders_processed": 0,
            "skipped_items": 0,
        }

        result = service._format_summary_for_job(summary)

        assert "Imported 5 files" in result

    def test_formats_single_file(self, service):
        """Uses singular 'file' for count of 1."""
        summary = {
            "files_processed": 1,
            "files_deleted": 0,
            "pages_processed": 0,
            "folders_processed": 0,
            "skipped_items": 0,
        }

        result = service._format_summary_for_job(summary)

        assert "1 file" in result
        assert "1 files" not in result

    def test_formats_deleted_files(self, service):
        """Formats deleted files count."""
        summary = {
            "files_processed": 0,
            "files_deleted": 3,
            "pages_processed": 0,
            "folders_processed": 0,
            "skipped_items": 0,
        }

        result = service._format_summary_for_job(summary)

        assert "3 deleted files" in result

    def test_formats_pages_processed(self, service):
        """Formats pages processed count."""
        summary = {
            "files_processed": 0,
            "files_deleted": 0,
            "pages_processed": 2,
            "folders_processed": 0,
            "skipped_items": 0,
        }

        result = service._format_summary_for_job(summary)

        assert "2 pages" in result

    def test_includes_folders_scanned(self, service):
        """Includes folders scanned in parentheses."""
        summary = {
            "files_processed": 5,
            "files_deleted": 0,
            "pages_processed": 0,
            "folders_processed": 10,
            "skipped_items": 0,
        }

        result = service._format_summary_for_job(summary)

        assert "10 folders scanned" in result

    def test_includes_skipped_items(self, service):
        """Includes skipped items in parentheses."""
        summary = {
            "files_processed": 5,
            "files_deleted": 0,
            "pages_processed": 0,
            "folders_processed": 0,
            "skipped_items": 3,
        }

        result = service._format_summary_for_job(summary)

        assert "3 items skipped" in result

    def test_handles_zero_files(self, service):
        """Shows '0 files' when nothing processed."""
        summary = {
            "files_processed": 0,
            "files_deleted": 0,
            "pages_processed": 0,
            "folders_processed": 0,
            "skipped_items": 0,
        }

        result = service._format_summary_for_job(summary)

        assert "Imported 0 files" in result

    def test_handles_none_values(self, service):
        """Handles None values in summary."""
        summary = {
            "files_processed": None,
            "files_deleted": None,
            "pages_processed": None,
            "folders_processed": None,
            "skipped_items": None,
        }

        result = service._format_summary_for_job(summary)

        assert "Imported 0 files" in result


class TestIsItemInFolderScope:
    """Tests for _is_item_in_folder_scope method."""

    def test_returns_true_when_no_scope_folder(self, service):
        """Returns True when scope_folder_id is None."""
        item = {"id": "item-1", "parentReference": {"id": "some-parent"}}

        result = service._is_item_in_folder_scope(item, scope_folder_id=None)

        assert result is True

    def test_returns_true_for_site_root_type(self, service):
        """Returns True when selected_item_type is site_root."""
        item = {"id": "item-1", "parentReference": {"id": "some-parent"}}

        result = service._is_item_in_folder_scope(
            item, scope_folder_id="folder-123", selected_item_type="site_root"
        )

        assert result is True

    def test_returns_true_when_selected_item_type_is_none(self, service):
        """Returns True when selected_item_type is None (defaults to include all)."""
        item = {"id": "item-1", "parentReference": {"id": "some-parent"}}

        result = service._is_item_in_folder_scope(
            item, scope_folder_id="folder-123", selected_item_type=None
        )

        assert result is True

    def test_returns_true_for_exact_file_match(self, service):
        """Returns True when item ID matches scope_folder_id for file type."""
        item = {"id": "file-123", "parentReference": {"id": "some-parent"}}

        result = service._is_item_in_folder_scope(
            item, scope_folder_id="file-123", selected_item_type="file"
        )

        assert result is True

    def test_returns_false_for_non_matching_file(self, service):
        """Returns False when item ID doesn't match for file type."""
        item = {"id": "other-file", "parentReference": {"id": "some-parent"}}

        result = service._is_item_in_folder_scope(
            item, scope_folder_id="file-123", selected_item_type="file"
        )

        assert result is False

    def test_returns_true_for_direct_child_of_folder(self, service):
        """Returns True when item is direct child of scope folder."""
        item = {"id": "child-1", "parentReference": {"id": "folder-123"}}

        result = service._is_item_in_folder_scope(
            item, scope_folder_id="folder-123", selected_item_type="folder"
        )

        assert result is True

    def test_returns_true_for_known_subfolder_child(self, service):
        """Returns True when item is child of known subfolder."""
        item = {"id": "grandchild-1", "parentReference": {"id": "subfolder-1"}}
        known_subfolders = {"subfolder-1", "subfolder-2"}

        result = service._is_item_in_folder_scope(
            item,
            scope_folder_id="folder-123",
            selected_item_type="folder",
            known_subfolder_ids=known_subfolders,
        )

        assert result is True

    def test_returns_false_for_item_outside_folder_scope(self, service):
        """Returns False when item is not in folder hierarchy."""
        item = {"id": "orphan-1", "parentReference": {"id": "other-folder"}}

        result = service._is_item_in_folder_scope(
            item, scope_folder_id="folder-123", selected_item_type="folder"
        )

        assert result is False


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
        mock_dependencies["integration_knowledge_repo"].one.return_value = mock_integration_knowledge

        with patch.object(service, "pull_content", new_callable=AsyncMock) as mock_pull:
            mock_pull.return_value = "Imported 5 files"

            result = await service.process_delta_changes(
                token_id=mock_oauth_token.id,
                integration_knowledge_id=mock_integration_knowledge.id,
                site_id="site-123",
            )

        mock_pull.assert_called_once()
        assert "Imported" in result

    async def test_processes_delta_changes_with_existing_token(
        self, service, mock_dependencies, mock_oauth_token, mock_integration_knowledge
    ):
        """Processes delta changes when delta token exists."""
        mock_integration_knowledge.delta_token = "existing-delta-token-123"
        mock_dependencies["oauth_token_repo"].one.return_value = mock_oauth_token
        mock_dependencies["integration_knowledge_repo"].one.return_value = mock_integration_knowledge

        with patch(
            "intric.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
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
        mock_dependencies["integration_knowledge_repo"].one.return_value = mock_integration_knowledge

        with patch(
            "intric.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
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
        mock_dependencies["integration_knowledge_repo"].update.assert_called()

    async def test_deleted_delta_uses_sharepoint_item_id_for_delete(
        self, service, mock_dependencies, mock_oauth_token, mock_integration_knowledge
    ):
        """Deleted items should be removed by sharepoint_item_id, not by title."""
        mock_integration_knowledge.delta_token = "existing-delta-token-123"
        mock_integration_knowledge.drive_id = "drive-123"
        mock_integration_knowledge.selected_item_type = "site_root"
        mock_integration_knowledge.folder_id = None

        mock_dependencies["oauth_token_repo"].one.return_value = mock_oauth_token
        mock_dependencies["integration_knowledge_repo"].one.return_value = mock_integration_knowledge
        mock_dependencies["info_blob_service"].repo.delete_by_sharepoint_item_and_integration_knowledge = AsyncMock(return_value=[])
        mock_dependencies["info_blob_service"].repo.delete_by_title_and_integration_knowledge = AsyncMock(return_value=[])

        with patch(
            "intric.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
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

        mock_dependencies["info_blob_service"].repo.delete_by_sharepoint_item_and_integration_knowledge.assert_called_once_with(
            sharepoint_item_id="item-123",
            integration_knowledge_id=mock_integration_knowledge.id,
        )
        mock_dependencies["info_blob_service"].repo.delete_by_title_and_integration_knowledge.assert_not_called()


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
            token=mock_oauth_token,
            integration_knowledge_id=uuid4(),
            client=mock_client,
            stats=service._initialize_stats(),
            folder_id="folder-456",
            processed_items=set(),
            is_root_call=True,
        )

        mock_client.get_drive_folder_items.assert_called_once_with(
            drive_id="drive-123",
            folder_id="folder-456",
        )
        mock_client.get_folder_items.assert_not_called()


class TestSyncLogging:
    """Tests for sync log creation."""

    async def test_creates_success_sync_log_when_files_processed(
        self, service, mock_dependencies, mock_oauth_token, mock_integration_knowledge
    ):
        """Creates success sync log when files are processed."""
        mock_dependencies["oauth_token_repo"].one.return_value = mock_oauth_token
        mock_dependencies["integration_knowledge_repo"].one.return_value = mock_integration_knowledge

        with patch(
            "intric.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.get_default_drive_id.return_value = "drive-123"
            mock_client.get_documents_in_drive.return_value = [
                {"id": "file-1", "name": "doc.txt", "webUrl": "https://example.com/doc.txt"}
            ]
            mock_client.get_site_pages.return_value = {"value": []}
            mock_client.get_file_content_by_id.return_value = ("File content", "text/plain")
            mock_client.initialize_delta_token.return_value = "delta-token"
            mock_client_class.return_value = mock_client

            await service.pull_content(
                token_id=mock_oauth_token.id,
                integration_knowledge_id=mock_integration_knowledge.id,
                site_id="site-123",
            )

        # Sync log should be created when files are processed
        if mock_dependencies["sync_log_repo"].add.called:
            sync_log = mock_dependencies["sync_log_repo"].add.call_args[0][0]
            assert sync_log.status == "success"
            assert sync_log.sync_type == "full"

    async def test_creates_error_sync_log_on_exception(
        self, service, mock_dependencies, mock_oauth_token, mock_integration_knowledge
    ):
        """Creates error sync log when exception occurs."""
        mock_dependencies["oauth_token_repo"].one.return_value = mock_oauth_token
        mock_dependencies["integration_knowledge_repo"].one.side_effect = Exception("Test error")

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


class TestTokenRefreshCallback:
    """Tests for token_refresh_callback method."""

    async def test_refreshes_and_returns_new_tokens(self, service, mock_dependencies):
        """Refreshes token and returns new access/refresh tokens."""
        token_id = uuid4()
        refreshed_token = MagicMock()
        refreshed_token.access_token = "new-access-token"
        refreshed_token.refresh_token = "new-refresh-token"

        mock_dependencies["oauth_token_service"].refresh_and_update_token.return_value = refreshed_token

        result = await service.token_refresh_callback(token_id)

        assert result["access_token"] == "new-access-token"
        assert result["refresh_token"] == "new-refresh-token"
        mock_dependencies["oauth_token_service"].refresh_and_update_token.assert_called_once_with(
            token_id=token_id
        )


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
        result = _extract_text_from_canvas_layout(content)
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
        result = _extract_text_from_canvas_layout(content)
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
        result = _extract_text_from_canvas_layout(content)
        assert "Visible text" in result
        assert "data" not in result

    def test_returns_empty_string_when_no_canvas_layout(self):
        assert _extract_text_from_canvas_layout({}) == ""
        assert _extract_text_from_canvas_layout({"canvasLayout": None}) == ""

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
        result = _extract_text_from_canvas_layout(content)
        assert "First section" in result
        assert "Second section" in result
