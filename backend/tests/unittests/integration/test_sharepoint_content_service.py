"""Unit tests for SharePointContentService - content sync from SharePoint.

Tests the content pulling, delta change processing, and token handling
for SharePoint integrations.
"""

import asyncio
import unicodedata
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from intric.integration.infrastructure.clients.sharepoint_content_client import (
    DeltaTokenExpiredException,
)
from intric.integration.infrastructure.content_service.sharepoint_content_service import (
    SharePointContentService,
    SimpleSharePointToken,
    extract_text_from_canvas_layout,
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
        mock_dependencies[
            "integration_knowledge_repo"
        ].one.return_value = mock_integration_knowledge

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

        mock_dependencies["oauth_token_repo"].one.assert_called_once_with(
            id=mock_oauth_token.id
        )

    async def test_uses_tenant_app_auth_when_tenant_app_id_provided(
        self, service, mock_dependencies, mock_tenant_app, mock_integration_knowledge
    ):
        """Uses tenant app auth service when tenant_app_id is provided."""
        mock_dependencies[
            "tenant_sharepoint_app_repo"
        ].get_by_id.return_value = mock_tenant_app
        mock_dependencies[
            "tenant_app_auth_service"
        ].get_access_token.return_value = "tenant-app-access-token"
        mock_dependencies[
            "integration_knowledge_repo"
        ].one.return_value = mock_integration_knowledge

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

        mock_dependencies[
            "tenant_app_auth_service"
        ].get_access_token.assert_called_once()

    async def test_uses_service_account_auth_when_configured(
        self,
        service,
        mock_dependencies,
        mock_tenant_app_service_account,
        mock_integration_knowledge,
    ):
        """Uses service account auth when tenant app is configured for service account."""
        mock_dependencies[
            "tenant_sharepoint_app_repo"
        ].get_by_id.return_value = mock_tenant_app_service_account
        mock_dependencies[
            "service_account_auth_service"
        ].refresh_access_token.return_value = {
            "access_token": "service-account-access-token",
            "refresh_token": "new-refresh-token",
        }
        mock_dependencies[
            "integration_knowledge_repo"
        ].one.return_value = mock_integration_knowledge

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

        mock_dependencies[
            "service_account_auth_service"
        ].refresh_access_token.assert_called_once()
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

    async def test_raises_error_when_service_account_auth_not_configured(
        self,
        mock_dependencies,
        mock_tenant_app_service_account,
        mock_integration_knowledge,
        mock_user,
    ):
        """Raises ValueError when service account is used but auth service not configured."""
        # Create service without service_account_auth_service
        deps = mock_dependencies.copy()
        deps["service_account_auth_service"] = None
        svc = SharePointContentService(**deps)

        deps[
            "tenant_sharepoint_app_repo"
        ].get_by_id.return_value = mock_tenant_app_service_account
        deps["integration_knowledge_repo"].one.return_value = mock_integration_knowledge

        with pytest.raises(
            ValueError, match="ServiceAccountAuthService not configured"
        ):
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
        assert "out_of_scope_deleted" in stats
        assert "folders_processed" in stats
        assert "pages_processed" in stats
        assert "skipped_items" in stats

    def test_all_stats_start_at_zero(self, service):
        """All stats are initialized to zero."""
        stats = service._initialize_stats()

        assert stats["files_processed"] == 0
        assert stats["files_deleted"] == 0
        assert stats["out_of_scope_deleted"] == 0
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

        mock_dependencies[
            "info_blob_service"
        ].repo.get_by_sharepoint_item_and_integration_knowledge = AsyncMock(
            return_value=existing_blob
        )
        mock_dependencies[
            "info_blob_service"
        ].upsert_info_blob_by_sharepoint_item_and_integration = AsyncMock(
            return_value=updated_blob
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

        mock_dependencies[
            "info_blob_service"
        ].repo.get_by_sharepoint_item_and_integration_knowledge = AsyncMock(
            return_value=existing_blob
        )
        mock_dependencies[
            "info_blob_service"
        ].upsert_info_blob_by_sharepoint_item_and_integration = AsyncMock(
            return_value=updated_blob
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

    async def test_skips_reembed_when_content_hash_unchanged(
        self, service, mock_dependencies, mock_integration_knowledge
    ):
        import hashlib

        from intric.integration.infrastructure.content_service.sharepoint_content_service import (  # noqa: E501
            sanitize_text_for_db,
        )

        text = "Identical content"
        existing_blob = MagicMock()
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
        ].upsert_info_blob_by_sharepoint_item_and_integration = AsyncMock()
        mock_dependencies["datastore"].add = AsyncMock()
        mock_dependencies["integration_knowledge_repo"].update = AsyncMock()

        await service._process_info_blob(
            title="Doc",
            text=text,
            url="https://example.com",
            integration_knowledge=mock_integration_knowledge,
            sharepoint_item_id="item-123",
        )

        # Unchanged content + metadata: no upsert, no chunk delete, no embedding,
        # no metadata update, no size update.
        mock_dependencies[
            "info_blob_service"
        ].upsert_info_blob_by_sharepoint_item_and_integration.assert_not_called()
        repo.update.assert_not_called()
        mock_dependencies["datastore"].add.assert_not_called()
        mock_dependencies["integration_knowledge_repo"].update.assert_not_called()

    async def test_refreshes_metadata_on_hash_match_when_renamed(
        self, service, mock_dependencies, mock_integration_knowledge
    ):
        """Hash match but title/url drifted (e.g. full-sync rename): refresh metadata
        without re-embedding."""
        import hashlib

        from intric.integration.infrastructure.content_service.sharepoint_content_service import (  # noqa: E501
            sanitize_text_for_db,
        )

        text = "Identical content"
        existing_blob = MagicMock()
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
        mock_dependencies["datastore"].add = AsyncMock()

        await service._process_info_blob(
            title="New name.docx",
            text=text,
            url="https://example.com/new",
            integration_knowledge=mock_integration_knowledge,
            sharepoint_item_id="item-123",
        )

        # Metadata refreshed, but NOT re-embedded.
        repo.update.assert_awaited_once()
        update_arg = repo.update.await_args.args[0]
        assert update_arg.title == "New name.docx"
        assert update_arg.url == "https://example.com/new"
        mock_dependencies["datastore"].add.assert_not_called()

    async def test_reembeds_when_content_hash_differs(
        self, service, mock_dependencies, mock_integration_knowledge
    ):
        existing_blob = MagicMock()
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
        ].upsert_info_blob_by_sharepoint_item_and_integration = AsyncMock(
            return_value=updated_blob
        )
        mock_dependencies["datastore"].add = AsyncMock()
        mock_dependencies["integration_knowledge_repo"].update = AsyncMock()
        mock_dependencies["info_blob_service"].repo.session.execute = AsyncMock()

        await service._process_info_blob(
            title="Doc",
            text="Brand new content",
            url="https://example.com",
            integration_knowledge=mock_integration_knowledge,
            sharepoint_item_id="item-123",
        )

        mock_dependencies["datastore"].add.assert_called_once()

    async def test_persists_content_hash_after_embedding_succeeds(
        self, service, mock_dependencies, mock_integration_knowledge
    ):
        import hashlib

        from intric.integration.infrastructure.content_service.sharepoint_content_service import (  # noqa: E501
            sanitize_text_for_db,
        )

        existing_blob = MagicMock()
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

        async def upsert(info_blob):
            upserted.append(info_blob)
            return updated_blob

        repo = mock_dependencies["info_blob_service"].repo
        repo.get_by_sharepoint_item_and_integration_knowledge = AsyncMock(
            return_value=existing_blob
        )
        repo.session.execute = AsyncMock()
        repo.update_content_hash = AsyncMock(return_value=updated_blob)
        mock_dependencies[
            "info_blob_service"
        ].upsert_info_blob_by_sharepoint_item_and_integration = AsyncMock(
            side_effect=upsert
        )
        mock_dependencies["datastore"].add = AsyncMock()

        await service._process_info_blob(
            title="Doc",
            text=text,
            url="https://example.com",
            integration_knowledge=mock_integration_knowledge,
            sharepoint_item_id="item-123",
        )

        assert upserted[0].content_hash is None
        repo.update_content_hash.assert_called_once_with(
            info_blob_id=updated_blob.id,
            content_hash=expected_hash,
        )

    async def test_embedding_failure_leaves_content_hash_unset_for_retry(
        self, service, mock_dependencies, mock_integration_knowledge
    ):
        existing_blob = MagicMock()
        existing_blob.size = 100
        existing_blob.content_hash = b"old-hash"

        updated_blob = MagicMock()
        updated_blob.id = uuid4()
        updated_blob.size = 100
        upserted: list = []

        async def upsert(info_blob):
            upserted.append(info_blob)
            return updated_blob

        repo = mock_dependencies["info_blob_service"].repo
        repo.get_by_sharepoint_item_and_integration_knowledge = AsyncMock(
            return_value=existing_blob
        )
        repo.session.execute = AsyncMock()
        repo.update_content_hash = AsyncMock()
        mock_dependencies[
            "info_blob_service"
        ].upsert_info_blob_by_sharepoint_item_and_integration = AsyncMock(
            side_effect=upsert
        )
        mock_dependencies["datastore"].add = AsyncMock(
            side_effect=Exception("embedding service unavailable")
        )

        await service._process_info_blob(
            title="Doc",
            text="Fresh content",
            url="https://example.com",
            integration_knowledge=mock_integration_knowledge,
            sharepoint_item_id="item-123",
        )

        assert upserted[0].content_hash is None
        repo.update_content_hash.assert_not_called()


class TestBuildSummaryStats:
    """Tests for _build_summary_stats method."""

    def test_builds_summary_from_stats(self, service):
        """Builds summary dictionary from stats."""
        stats = {
            "files_processed": 5,
            "files_deleted": 2,
            "out_of_scope_deleted": 1,
            "folders_processed": 3,
            "pages_processed": 1,
            "skipped_items": 4,
        }

        summary = service._build_summary_stats(stats)

        assert summary["files_processed"] == 5
        assert summary["files_deleted"] == 2
        assert summary["out_of_scope_deleted"] == 1
        assert summary["folders_processed"] == 3
        assert summary["pages_processed"] == 1
        assert summary["skipped_items"] == 4

    def test_handles_missing_keys_with_defaults(self, service):
        """Uses 0 for missing keys."""
        stats = {"files_processed": 10}

        summary = service._build_summary_stats(stats)

        assert summary["files_processed"] == 10
        assert summary["files_deleted"] == 0
        assert summary["out_of_scope_deleted"] == 0
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

    def test_returns_true_for_selected_folder_itself(self, service):
        """Returns True when a folder delta is for the selected folder itself."""
        item = {
            "id": "folder-123",
            "name": "Reports",
            "folder": {},
            "parentReference": {"id": "parent-folder"},
        }

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

    def test_matches_path_with_encoded_spaces(self, service):
        """Percent-encoded spaces in the Graph path match a decoded scope path."""
        item = {
            "id": "child-1",
            "parentReference": {
                "id": "subfolder-x",
                "path": "/drives/d/root:/Documents/My%20Files",
            },
        }

        result = service._is_item_in_folder_scope(
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

        result = service._is_item_in_folder_scope(
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

        result = service._is_item_in_folder_scope(
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

        result = service._is_item_in_folder_scope(
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

        result = service._is_item_in_folder_scope(
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

        result = service._is_item_in_folder_scope(
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

        result = service._is_item_in_folder_scope(
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
                "intric.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
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
        mock_dependencies["integration_knowledge_repo"].update.assert_called_with(
            obj=mock_integration_knowledge
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
        mock_dependencies[
            "integration_knowledge_repo"
        ].one.return_value = mock_integration_knowledge

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
            "intric.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
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
        mock_client.get_file_content_by_id.assert_not_called()

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
            "intric.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
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
            "intric.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
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
            mock_client.get_file_content_by_id.return_value = (
                "[No readable text found]",
                None,
            )
            mock_client_class.return_value = mock_client

            with patch.object(
                service, "_process_info_blob", AsyncMock()
            ) as mock_process:
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
            "intric.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
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
        mock_client.get_file_content_by_id.assert_not_called()
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
            "intric.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.get_delta_changes.return_value = (
                [
                    {
                        "id": "folder-a",
                        "name": "A renamed",
                        "folder": {},
                        "parentReference": {
                            "id": "documents-folder",
                            "path": "/drives/drive-123/root:/Documents",
                        },
                    }
                ],
                "new-delta-token",
            )
            mock_client_class.return_value = mock_client

            with patch.object(
                service, "_delete_out_of_scope_folder_subtree", AsyncMock()
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
        """Do not delete nested content when legacy folder scope cannot be resolved."""
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
            "intric.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.get_file_metadata.side_effect = Exception("Graph timeout")
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
        mock_client.get_file_content_by_id.assert_not_called()
        assert mock_integration_knowledge.folder_path is None
        assert "1 item skipped" in result
        sync_log = mock_dependencies["sync_log_repo"].add.call_args[0][0]
        assert sync_log.metadata["skipped_details"] == [
            {"file": "nested.docx", "reason": "Folder scope path unavailable"}
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

    async def test_full_sync_unextractable_file_deletes_existing_local_blob(
        self, service, mock_dependencies, mock_oauth_token, mock_integration_knowledge
    ):
        """Full sync should clear stale blobs for still-present unextractable files."""
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
        mock_client.get_file_content_by_id.return_value = (
            "[Could not extract text from PowerPoint presentation]",
            None,
        )
        stats = service._initialize_stats()

        with patch.object(service, "_process_info_blob", AsyncMock()) as mock_process:
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
                integration_knowledge_id=mock_integration_knowledge.id,
                token=mock_oauth_token,
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
        assert stats["skipped_details"] == [
            {"file": "slides.pptx", "reason": "Empty or unreadable content"}
        ]

    async def test_full_sync_download_error_does_not_delete_existing_local_blob(
        self, service, mock_dependencies, mock_oauth_token, mock_integration_knowledge
    ):
        """Transient download errors should remain non-destructive skips."""
        mock_dependencies[
            "integration_knowledge_repo"
        ].one.return_value = mock_integration_knowledge
        mock_dependencies[
            "info_blob_service"
        ].repo.delete_by_sharepoint_item_and_integration_knowledge = AsyncMock(
            return_value=[]
        )

        mock_client = AsyncMock()
        mock_client.get_file_content_by_id.side_effect = Exception("Graph timeout")
        stats = service._initialize_stats()

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
            integration_knowledge_id=mock_integration_knowledge.id,
            token=mock_oauth_token,
            processed_items=set(),
            stats=stats,
        )

        mock_dependencies[
            "info_blob_service"
        ].repo.delete_by_sharepoint_item_and_integration_knowledge.assert_not_called()
        assert stats["files_deleted"] == 0
        assert stats["skipped_details"] == [
            {"file": "still-readable.docx", "reason": "Error: Graph timeout"}
        ]


class TestPostCommitChangeKeys:
    """Tests for deferred ChangeKey cache writes."""

    async def test_flushes_change_keys_after_commit(self, service, mock_dependencies):
        """ChangeKeys are written after the SQLAlchemy transaction commits."""
        sync_session = Session()
        mock_dependencies["session"].sync_session = sync_session
        integration_knowledge_id = uuid4()

        try:
            service._schedule_post_commit_change_keys(
                [(integration_knowledge_id, "item-123", "etag-123")]
            )

            mock_dependencies[
                "change_key_service"
            ].update_change_key.assert_not_called()

            sync_session.commit()
            if service._pending_change_key_tasks:
                await asyncio.gather(*service._pending_change_key_tasks)

            mock_dependencies[
                "change_key_service"
            ].update_change_key.assert_awaited_once_with(
                integration_knowledge_id=integration_knowledge_id,
                item_id="item-123",
                change_key="etag-123",
            )
        finally:
            sync_session.close()

    async def test_does_not_flush_change_keys_after_rollback(
        self, service, mock_dependencies
    ):
        """Rolled-back syncs must not mark a ChangeKey as processed."""
        sync_session = Session()
        mock_dependencies["session"].sync_session = sync_session

        try:
            service._schedule_post_commit_change_keys(
                [(uuid4(), "item-123", "etag-123")]
            )

            sync_session.rollback()
            await asyncio.sleep(0)

            mock_dependencies[
                "change_key_service"
            ].update_change_key.assert_not_called()
        finally:
            sync_session.close()

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
        with patch(
            "intric.integration.infrastructure.content_service."
            "sharepoint_content_service.sa.event.listen"
        ) as mock_listen:
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
            "intric.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.get_default_drive_id.return_value = "drive-123"
            mock_client.get_documents_in_drive.return_value = [
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
            mock_client.get_file_content_by_id.return_value = (
                "File content",
                "text/plain",
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


class TestOutOfScopeFolderSubtreeCleanup:
    """A folder leaving scope must take its descendant blobs with it."""

    async def test_deletes_descendant_blobs_when_folder_leaves_scope(
        self, service, mock_dependencies
    ):
        ik = MagicMock()
        ik.id = uuid4()
        ik.size = 0
        repo = mock_dependencies["info_blob_service"].repo
        repo.delete_by_sharepoint_item_and_integration_knowledge.return_value = []
        content_client = AsyncMock()

        with patch.object(
            service,
            "_enumerate_authoritative_item_ids",
            AsyncMock(return_value={"child-1", "child-2"}),
        ):
            stats = service._initialize_stats()
            await service._delete_out_of_scope_folder_subtree(
                content_client=content_client,
                resource_type="site",
                site_id="site-1",
                drive_id="drive-1",
                folder_id="folder-1",
                folder_name="Moved",
                integration_knowledge=ik,
                integration_knowledge_id=ik.id,
                stats=stats,
            )

        assert repo.delete_by_sharepoint_item_and_integration_knowledge.await_count == 2
        called_item_ids = {
            call.kwargs["sharepoint_item_id"]
            for call in repo.delete_by_sharepoint_item_and_integration_knowledge.await_args_list
        }
        assert called_item_ids == {"child-1", "child-2"}

    async def test_cleans_onedrive_subtree_via_drive_enumeration(
        self, service, mock_dependencies
    ):
        """OneDrive (no site_id) is now cleaned inline via drive enumeration."""
        ik = MagicMock()
        ik.id = uuid4()
        ik.size = 0
        repo = mock_dependencies["info_blob_service"].repo
        repo.delete_by_sharepoint_item_and_integration_knowledge.return_value = []
        content_client = AsyncMock()

        with patch.object(
            service,
            "_enumerate_authoritative_item_ids",
            AsyncMock(return_value={"od-child"}),
        ) as mock_enum:
            stats = service._initialize_stats()
            await service._delete_out_of_scope_folder_subtree(
                content_client=content_client,
                resource_type="onedrive",
                site_id=None,
                drive_id="drive-1",
                folder_id="folder-1",
                folder_name="Moved",
                integration_knowledge=ik,
                integration_knowledge_id=ik.id,
                stats=stats,
            )

        mock_enum.assert_awaited_once()
        assert repo.delete_by_sharepoint_item_and_integration_knowledge.await_count == 1

    async def test_degrades_safely_without_drive_id(self, service, mock_dependencies):
        ik = MagicMock()
        ik.id = uuid4()
        content_client = AsyncMock()
        repo = mock_dependencies["info_blob_service"].repo

        with patch.object(service, "_enumerate_authoritative_item_ids") as mock_enum:
            stats = service._initialize_stats()
            await service._delete_out_of_scope_folder_subtree(
                content_client=content_client,
                resource_type="site",
                site_id="site-1",
                drive_id=None,
                folder_id="folder-1",
                folder_name="Moved",
                integration_knowledge=ik,
                integration_knowledge_id=ik.id,
                stats=stats,
            )

        mock_enum.assert_not_called()
        repo.delete_by_sharepoint_item_and_integration_knowledge.assert_not_called()


class TestIsUnextractableContent:
    """Extraction sentinels must not be treated as real document content."""

    def test_empty_and_whitespace_are_unextractable(self):
        from intric.integration.infrastructure.content_service.utils import (
            is_unextractable_content,
        )

        assert is_unextractable_content("") is True
        assert is_unextractable_content("   \n\t ") is True
        assert is_unextractable_content(None) is True

    def test_sentinel_strings_are_unextractable(self):
        from intric.integration.infrastructure.content_service.utils import (
            is_unextractable_content,
        )

        assert is_unextractable_content("[No readable text found]") is True
        assert (
            is_unextractable_content(
                "  [Could not extract text from PowerPoint presentation]  "
            )
            is True
        )
        assert (
            is_unextractable_content("[Could not extract text from Excel spreadsheet]")
            is True
        )

    def test_real_text_is_extractable(self):
        from intric.integration.infrastructure.content_service.utils import (
            is_unextractable_content,
        )

        assert is_unextractable_content("Real document content here.") is False


class TestFullSyncReconciliation:
    """Full-sync reconciliation must remove orphans but never mass-delete."""

    def _ik(self):
        ik = MagicMock()
        ik.id = uuid4()
        return ik

    async def test_deletes_only_orphaned_blobs(self, service, mock_dependencies):
        ik = self._ik()
        indexed = [(uuid4(), "keep-1"), (uuid4(), "orphan-1"), (uuid4(), "keep-2")]
        mock_dependencies[
            "info_blob_service"
        ].repo.get_sharepoint_item_ids_for_integration_knowledge = AsyncMock(
            return_value=indexed
        )

        with patch.object(
            service,
            "_enumerate_authoritative_item_ids",
            AsyncMock(return_value={"keep-1", "keep-2"}),
        ):
            with patch.object(
                service, "_delete_local_sharepoint_item", AsyncMock(return_value=1)
            ) as mock_delete:
                await service._reconcile_indexed_blobs(
                    client=AsyncMock(),
                    integration_knowledge=ik,
                    resource_type="site",
                    site_id="site-1",
                    drive_id="drive-1",
                    folder_id=None,
                    stats=service._initialize_stats(),
                )

        assert mock_delete.await_count == 1
        assert mock_delete.await_args.kwargs["item_id"] == "orphan-1"

    async def test_orphan_deletion_persists_size_decrease(
        self, service, mock_dependencies
    ):
        ik = self._ik()
        ik.size = 100
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
            service, "_enumerate_authoritative_item_ids", AsyncMock(return_value=set())
        ):
            await service._reconcile_indexed_blobs(
                client=AsyncMock(),
                integration_knowledge=ik,
                resource_type="site",
                site_id="site-1",
                drive_id="drive-1",
                folder_id=None,
                stats=service._initialize_stats(),
            )

        assert ik.size == 60
        mock_dependencies["integration_knowledge_repo"].update.assert_called_once_with(
            obj=ik
        )

    async def test_skips_when_enumeration_fails(self, service, mock_dependencies):
        ik = self._ik()
        mock_dependencies[
            "info_blob_service"
        ].repo.get_sharepoint_item_ids_for_integration_knowledge = AsyncMock(
            return_value=[(uuid4(), "anything")]
        )

        with patch.object(
            service,
            "_enumerate_authoritative_item_ids",
            AsyncMock(side_effect=Exception("throttled mid-listing")),
        ):
            with patch.object(
                service, "_delete_local_sharepoint_item", AsyncMock()
            ) as mock_delete:
                await service._reconcile_indexed_blobs(
                    client=AsyncMock(),
                    integration_knowledge=ik,
                    resource_type="site",
                    site_id="site-1",
                    drive_id="drive-1",
                    folder_id=None,
                    stats=service._initialize_stats(),
                )

        mock_delete.assert_not_called()

    async def test_skips_when_orphans_exceed_safety_cap(
        self, service, mock_dependencies
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
            service, "_enumerate_authoritative_item_ids", AsyncMock(return_value=set())
        ):
            with patch.object(
                service, "_delete_local_sharepoint_item", AsyncMock()
            ) as mock_delete:
                await service._reconcile_indexed_blobs(
                    client=AsyncMock(),
                    integration_knowledge=ik,
                    resource_type="site",
                    site_id="site-1",
                    drive_id="drive-1",
                    folder_id=None,
                    stats=service._initialize_stats(),
                )

        mock_delete.assert_not_called()

    async def test_noop_when_no_orphans(self, service, mock_dependencies):
        ik = self._ik()
        indexed = [(uuid4(), "a"), (uuid4(), "b")]
        mock_dependencies[
            "info_blob_service"
        ].repo.get_sharepoint_item_ids_for_integration_knowledge = AsyncMock(
            return_value=indexed
        )

        with patch.object(
            service,
            "_enumerate_authoritative_item_ids",
            AsyncMock(return_value={"a", "b", "c"}),
        ):
            with patch.object(
                service, "_delete_local_sharepoint_item", AsyncMock()
            ) as mock_delete:
                await service._reconcile_indexed_blobs(
                    client=AsyncMock(),
                    integration_knowledge=ik,
                    resource_type="site",
                    site_id="site-1",
                    drive_id="drive-1",
                    folder_id=None,
                    stats=service._initialize_stats(),
                )

        mock_delete.assert_not_called()


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
            "intric.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
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
                patch.object(service, "_reconcile_indexed_blobs", AsyncMock()),
            ):
                await service.pull_content(
                    token_id=mock_oauth_token.id,
                    integration_knowledge_id=ik.id,
                    site_id="site-123",
                    drive_id="drive-456",
                    recovery="delta_token_expired",
                )

        assert ik.folder_path == "/Documents/A renamed"
        mock_dependencies["integration_knowledge_repo"].update.assert_any_await(obj=ik)

    async def test_keeps_folder_path_when_metadata_has_no_resolvable_path(
        self, service, mock_dependencies, mock_oauth_token, mock_integration_knowledge
    ):
        """A good stored path is never clobbered when metadata yields no path."""
        ik = self._folder_scoped_ik(mock_integration_knowledge)
        mock_dependencies["oauth_token_repo"].one.return_value = mock_oauth_token
        mock_dependencies["integration_knowledge_repo"].one.return_value = ik

        with patch(
            "intric.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"
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
                patch.object(service, "_reconcile_indexed_blobs", AsyncMock()),
            ):
                await service.pull_content(
                    token_id=mock_oauth_token.id,
                    integration_knowledge_id=ik.id,
                    site_id="site-123",
                    drive_id="drive-456",
                    recovery="delta_token_expired",
                )

        assert ik.folder_path == "/Documents/A"


class TestEnumerateAuthoritativeItemIds:
    """Strict enumeration used by reconciliation + subtree cleanup (destructive path)."""

    async def test_site_recurses_files_and_pages_excluding_folders(self, service):
        client = AsyncMock()
        client.get_documents_in_drive.return_value = [
            {"id": "folder-1", "folder": {}},
            {"id": "file-1", "file": {}},
        ]
        client.get_folder_items.return_value = [{"id": "file-2", "file": {}}]
        client.get_site_pages.return_value = {"value": [{"id": "page-1"}]}

        result = await service._enumerate_authoritative_item_ids(
            client=client,
            resource_type="site",
            site_id="site-1",
            drive_id="drive-1",
            folder_id=None,
        )

        # Files (incl. nested) + pages, but NOT the folder id itself.
        assert result == {"file-1", "file-2", "page-1"}

    async def test_onedrive_uses_drive_listing_no_site_id(self, service):
        client = AsyncMock()
        client.get_drive_root_children.return_value = [{"id": "od-file", "file": {}}]

        result = await service._enumerate_authoritative_item_ids(
            client=client,
            resource_type="onedrive",
            site_id=None,
            drive_id="drive-1",
            folder_id=None,
        )

        assert result == {"od-file"}
        client.get_drive_root_children.assert_awaited_once()

    async def test_listing_error_propagates_not_swallowed(self, service):
        """A failed listing must raise so reconciliation never treats a partial
        enumeration as authoritative."""
        client = AsyncMock()
        client.get_documents_in_drive.side_effect = RuntimeError("graph throttled")

        with pytest.raises(RuntimeError):
            await service._enumerate_authoritative_item_ids(
                client=client,
                resource_type="site",
                site_id="site-1",
                drive_id="drive-1",
                folder_id=None,
            )
