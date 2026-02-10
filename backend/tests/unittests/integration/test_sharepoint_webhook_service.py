"""Unit tests for SharePointWebhookService - webhook notification processing.

Tests the webhook processing logic that handles Microsoft Graph change notifications,
including ChangeKey deduplication, scope filtering, and job queuing.
"""

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from intric.integration.infrastructure.sharepoint_webhook_service import SharepointWebhookService
from intric.jobs.job_models import Task


@dataclass
class Setup:
    """Test setup fixture data."""

    service: SharepointWebhookService
    session: AsyncMock
    oauth_token_repo: AsyncMock
    job_repo: AsyncMock
    user_repo: AsyncMock
    change_key_service: AsyncMock


@pytest.fixture
def setup():
    """Create SharepointWebhookService with all dependencies mocked."""
    session = AsyncMock()
    oauth_token_repo = AsyncMock()
    job_repo = AsyncMock()
    user_repo = AsyncMock()
    change_key_service = AsyncMock()

    service = SharepointWebhookService(
        session=session,
        oauth_token_repo=oauth_token_repo,
        job_repo=job_repo,
        user_repo=user_repo,
        change_key_service=change_key_service,
    )

    # Set expected client state for testing
    service.expected_client_state = "test-client-state-123"

    return Setup(
        service=service,
        session=session,
        oauth_token_repo=oauth_token_repo,
        job_repo=job_repo,
        user_repo=user_repo,
        change_key_service=change_key_service,
    )


@pytest.fixture
def mock_notification():
    """Create a mock webhook notification."""
    return {
        "subscriptionId": "sub-123",
        "clientState": "test-client-state-123",
        "resource": "sites/site-123/drives/drive-456/root",
        "changeType": "updated",
        "changeKey": "change-key-789",
        "resourceData": {
            "@odata.type": "#Microsoft.Graph.driveItem",
            "id": "item-123",
            "changeKey": "change-key-789",
        },
    }


@pytest.fixture
def mock_knowledge_db():
    """Create a mock IntegrationKnowledge DB model."""
    knowledge = MagicMock()
    knowledge.id = uuid4()
    knowledge.user_integration_id = uuid4()
    knowledge.site_id = "site-123"
    knowledge.folder_id = None
    knowledge.folder_path = None
    knowledge.selected_item_type = "site_root"
    knowledge.delta_token = None
    knowledge.name = "Test SharePoint Integration"
    return knowledge


@pytest.fixture
def mock_user_integration_db():
    """Create a mock UserIntegration DB model (user OAuth)."""
    integration = MagicMock()
    integration.id = uuid4()
    integration.user_id = uuid4()
    integration.tenant_id = uuid4()
    integration.auth_type = "user_oauth"
    integration.tenant_app_id = None
    return integration


@pytest.fixture
def mock_tenant_app_integration_db():
    """Create a mock UserIntegration DB model (tenant app)."""
    integration = MagicMock()
    integration.id = uuid4()
    integration.user_id = None  # Person-independent
    integration.tenant_id = uuid4()
    integration.auth_type = "tenant_app"
    integration.tenant_app_id = uuid4()
    return integration


@pytest.fixture
def mock_user():
    """Create a mock UserInDB."""
    user = MagicMock()
    user.id = uuid4()
    user.email = "test@example.com"
    user.tenant_id = uuid4()
    return user


@pytest.fixture
def mock_oauth_token():
    """Create a mock OAuth token."""
    token = MagicMock()
    token.id = uuid4()
    token.access_token = "access-token-123"
    return token


async def test_client_state_validation_accepts_valid(setup: Setup, mock_notification):
    """Notifications with correct client state are accepted."""
    # Set up mock responses
    setup.service._fetch_knowledge_by_site = AsyncMock(return_value=[])

    notifications = {"value": [mock_notification]}

    await setup.service.handle_notifications(notifications)

    # Verify _fetch_knowledge_by_site was called (notification was processed)
    setup.service._fetch_knowledge_by_site.assert_called_once_with(site_id="site-123")


async def test_client_state_validation_rejects_invalid(setup: Setup, mock_notification):
    """Notifications with incorrect client state are rejected."""
    # Modify notification to have wrong client state
    mock_notification["clientState"] = "wrong-client-state"

    # Set up mock responses
    setup.service._fetch_knowledge_by_site = AsyncMock(return_value=[])

    notifications = {"value": [mock_notification]}

    await setup.service.handle_notifications(notifications)

    # Verify _fetch_knowledge_by_site was NOT called (notification was rejected)
    setup.service._fetch_knowledge_by_site.assert_not_called()


async def test_empty_notifications_handled_gracefully(setup: Setup):
    """Empty notification list is handled without errors."""
    notifications = {"value": []}

    # Should not raise
    await setup.service.handle_notifications(notifications)


async def test_missing_value_key_handled_gracefully(setup: Setup):
    """Missing 'value' key is handled without errors."""
    notifications = {}

    # Should not raise
    await setup.service.handle_notifications(notifications)


async def test_changekey_deduplication_prevents_duplicate_processing(
    setup: Setup, mock_notification, mock_knowledge_db, mock_user_integration_db, mock_user, mock_oauth_token
):
    """Duplicate ChangeKeys are filtered out to prevent reprocessing."""
    # First notification should process, second with same ChangeKey should skip
    setup.change_key_service.should_process.side_effect = [True, False]
    setup.change_key_service.update_change_key.return_value = None

    # Mock database responses
    setup.service._fetch_knowledge_by_site = AsyncMock(
        return_value=[(mock_knowledge_db, mock_user_integration_db)]
    )
    setup.oauth_token_repo.one_or_none.return_value = mock_oauth_token
    setup.user_repo.get_user_by_id.return_value = mock_user

    # Mock job service creation
    mock_job_service = AsyncMock()
    mock_job_service.queue_job = AsyncMock()

    with patch(
        "intric.integration.infrastructure.sharepoint_webhook_service.JobService",
        return_value=mock_job_service
    ):
        # Send two identical notifications
        notifications = {
            "value": [
                mock_notification.copy(),
                mock_notification.copy(),
            ]
        }

        await setup.service.handle_notifications(notifications)

        # Verify ChangeKey service was called twice
        assert setup.change_key_service.should_process.call_count == 2

        # Verify update_change_key was only called once (for the unique notification)
        setup.change_key_service.update_change_key.assert_called_once()


async def test_changekey_deduplication_allows_new_changekeys(
    setup: Setup, mock_notification, mock_knowledge_db, mock_user_integration_db, mock_user, mock_oauth_token
):
    """New ChangeKeys are processed normally."""
    # Both notifications should process (different ChangeKeys)
    setup.change_key_service.should_process.side_effect = [True, True]
    setup.change_key_service.update_change_key.return_value = None

    # Create two notifications with different change keys
    notification1 = mock_notification.copy()
    notification1["changeKey"] = "change-key-1"
    notification1["resourceData"] = {
        "@odata.type": "#Microsoft.Graph.driveItem",
        "id": "item-1",
        "changeKey": "change-key-1",
    }

    notification2 = mock_notification.copy()
    notification2["changeKey"] = "change-key-2"
    notification2["resourceData"] = {
        "@odata.type": "#Microsoft.Graph.driveItem",
        "id": "item-2",
        "changeKey": "change-key-2",
    }

    # Mock database responses
    setup.service._fetch_knowledge_by_site = AsyncMock(
        return_value=[(mock_knowledge_db, mock_user_integration_db)]
    )
    setup.oauth_token_repo.one_or_none.return_value = mock_oauth_token
    setup.user_repo.get_user_by_id.return_value = mock_user

    # Mock job service
    mock_job_service = AsyncMock()
    mock_job_service.queue_job = AsyncMock()

    with patch(
        "intric.integration.infrastructure.sharepoint_webhook_service.JobService",
        return_value=mock_job_service
    ):
        notifications = {"value": [notification1, notification2]}

        await setup.service.handle_notifications(notifications)

        # Verify update_change_key was called twice (for both unique notifications)
        assert setup.change_key_service.update_change_key.call_count == 2


def test_site_root_integration_processes_all_notifications(setup: Setup, mock_notification, mock_knowledge_db):
    """Site-level integrations process all notifications."""
    mock_knowledge_db.selected_item_type = "site_root"
    mock_knowledge_db.folder_id = None

    result = setup.service._is_notification_in_scope(mock_notification, mock_knowledge_db)

    assert result is True


def test_file_integration_filters_by_exact_item_id(setup: Setup, mock_notification, mock_knowledge_db):
    """File-level integrations filter by exact item ID match."""
    mock_knowledge_db.selected_item_type = "file"
    mock_knowledge_db.folder_id = "item-123"  # folder_id stores the file ID for file-level

    # Notification for the exact file
    notification_matching = mock_notification.copy()
    notification_matching["resourceData"]["id"] = "item-123"

    result_match = setup.service._is_notification_in_scope(notification_matching, mock_knowledge_db)
    assert result_match is True

    # Notification for a different file
    notification_not_matching = mock_notification.copy()
    notification_not_matching["resourceData"]["id"] = "item-999"

    result_no_match = setup.service._is_notification_in_scope(notification_not_matching, mock_knowledge_db)
    assert result_no_match is False


def test_file_integration_without_item_id_queues_anyway(setup: Setup, mock_notification, mock_knowledge_db):
    """File-level integrations without item_id in notification queue for delta sync."""
    mock_knowledge_db.selected_item_type = "file"
    mock_knowledge_db.folder_id = "item-123"

    # Notification without item_id (common from Microsoft)
    notification_no_id = mock_notification.copy()
    notification_no_id["resourceData"] = {
        "@odata.type": "#Microsoft.Graph.driveItem",
    }

    result = setup.service._is_notification_in_scope(notification_no_id, mock_knowledge_db)

    # Should queue (True) to let delta sync handle it
    assert result is True


def test_folder_integration_queues_for_sync_service_filtering(setup: Setup, mock_notification, mock_knowledge_db):
    """Folder-level integrations queue notifications for sync service filtering."""
    mock_knowledge_db.selected_item_type = "folder"
    mock_knowledge_db.folder_id = "folder-456"

    result = setup.service._is_notification_in_scope(mock_notification, mock_knowledge_db)

    # Should queue (True) and let sync service do full filtering
    assert result is True


async def test_tenant_app_integration_uses_tenant_app_id(
    setup: Setup, mock_notification, mock_knowledge_db, mock_tenant_app_integration_db, mock_user
):
    """Tenant app integrations use tenant_app_id, no OAuth token."""
    # Mock database responses
    setup.service._fetch_knowledge_by_site = AsyncMock(
        return_value=[(mock_knowledge_db, mock_tenant_app_integration_db)]
    )

    # Mock tenant admin lookup
    setup.user_repo.list_tenant_admins.return_value = [mock_user]

    # Mock change key service to allow notification
    setup.change_key_service.should_process.return_value = True
    setup.change_key_service.update_change_key.return_value = None

    # Mock job service
    mock_job_service = AsyncMock()
    mock_job_service.queue_job = AsyncMock()

    with patch(
        "intric.integration.infrastructure.sharepoint_webhook_service.JobService",
        return_value=mock_job_service
    ):
        notifications = {"value": [mock_notification]}

        await setup.service.handle_notifications(notifications)

        # Verify OAuth token was NOT fetched
        setup.oauth_token_repo.one_or_none.assert_not_called()

        # Verify admin user was fetched
        setup.user_repo.list_tenant_admins.assert_called_once_with(
            tenant_id=mock_tenant_app_integration_db.tenant_id
        )

        # Verify job was queued with tenant_app_id
        mock_job_service.queue_job.assert_called_once()
        call_args = mock_job_service.queue_job.call_args
        params = call_args.kwargs["task_params"]
        assert params.tenant_app_id == mock_tenant_app_integration_db.tenant_app_id
        assert params.token_id is None  # No OAuth token for tenant app


async def test_user_oauth_integration_uses_oauth_token(
    setup: Setup, mock_notification, mock_knowledge_db, mock_user_integration_db, mock_user, mock_oauth_token
):
    """User OAuth integrations use OAuth token, no tenant_app_id."""
    # Mock database responses
    setup.service._fetch_knowledge_by_site = AsyncMock(
        return_value=[(mock_knowledge_db, mock_user_integration_db)]
    )

    # Mock OAuth token lookup
    setup.oauth_token_repo.one_or_none.return_value = mock_oauth_token

    # Mock user lookup
    setup.user_repo.get_user_by_id.return_value = mock_user

    # Mock change key service
    setup.change_key_service.should_process.return_value = True
    setup.change_key_service.update_change_key.return_value = None

    # Mock job service
    mock_job_service = AsyncMock()
    mock_job_service.queue_job = AsyncMock()

    with patch(
        "intric.integration.infrastructure.sharepoint_webhook_service.JobService",
        return_value=mock_job_service
    ):
        notifications = {"value": [mock_notification]}

        await setup.service.handle_notifications(notifications)

        # Verify OAuth token was fetched
        setup.oauth_token_repo.one_or_none.assert_called_once_with(
            user_integration_id=mock_user_integration_db.id
        )

        # Verify admin user was NOT fetched
        setup.user_repo.list_tenant_admins.assert_not_called()

        # Verify job was queued with token_id
        mock_job_service.queue_job.assert_called_once()
        call_args = mock_job_service.queue_job.call_args
        params = call_args.kwargs["task_params"]
        assert params.token_id == mock_oauth_token.id
        assert params.tenant_app_id is None  # No tenant app for user OAuth


async def test_tenant_app_integration_uses_admin_user_for_job(
    setup: Setup, mock_notification, mock_knowledge_db, mock_tenant_app_integration_db, mock_user
):
    """Tenant app integrations use tenant admin as job owner."""
    # Mock database responses
    setup.service._fetch_knowledge_by_site = AsyncMock(
        return_value=[(mock_knowledge_db, mock_tenant_app_integration_db)]
    )

    # Mock admin user lookup
    admin_user = mock_user.copy() if hasattr(mock_user, 'copy') else mock_user
    admin_user.id = uuid4()
    setup.user_repo.list_tenant_admins.return_value = [admin_user]

    # Mock change key service
    setup.change_key_service.should_process.return_value = True
    setup.change_key_service.update_change_key.return_value = None

    # Mock job service
    mock_job_service = AsyncMock()
    mock_job_service.queue_job = AsyncMock()

    with patch(
        "intric.integration.infrastructure.sharepoint_webhook_service.JobService",
        return_value=mock_job_service
    ):
        notifications = {"value": [mock_notification]}

        await setup.service.handle_notifications(notifications)

        # Verify job was created with admin user
        mock_job_service.queue_job.assert_called_once()
        call_args = mock_job_service.queue_job.call_args
        params = call_args.kwargs["task_params"]
        assert params.user_id == admin_user.id


async def test_missing_tenant_admin_skips_integration(
    setup: Setup, mock_notification, mock_knowledge_db, mock_tenant_app_integration_db
):
    """Missing tenant admin causes integration to be skipped with warning."""
    # Mock database responses
    setup.service._fetch_knowledge_by_site = AsyncMock(
        return_value=[(mock_knowledge_db, mock_tenant_app_integration_db)]
    )

    # Mock admin user lookup - no admins found
    setup.user_repo.list_tenant_admins.return_value = []

    # Mock change key service
    setup.change_key_service.should_process.return_value = True
    setup.change_key_service.update_change_key.return_value = None

    # Mock job service
    mock_job_service = AsyncMock()
    mock_job_service.queue_job = AsyncMock()

    with patch(
        "intric.integration.infrastructure.sharepoint_webhook_service.JobService",
        return_value=mock_job_service
    ):
        notifications = {"value": [mock_notification]}

        await setup.service.handle_notifications(notifications)

        # Verify NO job was queued (integration skipped)
        mock_job_service.queue_job.assert_not_called()


async def test_missing_oauth_token_skips_integration(
    setup: Setup, mock_notification, mock_knowledge_db, mock_user_integration_db
):
    """Missing OAuth token causes integration to be skipped with warning."""
    # Mock database responses
    setup.service._fetch_knowledge_by_site = AsyncMock(
        return_value=[(mock_knowledge_db, mock_user_integration_db)]
    )

    # Mock OAuth token lookup - no token found
    setup.oauth_token_repo.one_or_none.return_value = None

    # Mock change key service
    setup.change_key_service.should_process.return_value = True
    setup.change_key_service.update_change_key.return_value = None

    # Mock job service
    mock_job_service = AsyncMock()
    mock_job_service.queue_job = AsyncMock()

    with patch(
        "intric.integration.infrastructure.sharepoint_webhook_service.JobService",
        return_value=mock_job_service
    ):
        notifications = {"value": [mock_notification]}

        await setup.service.handle_notifications(notifications)

        # Verify NO job was queued
        mock_job_service.queue_job.assert_not_called()


async def test_delta_sync_when_delta_token_exists(
    setup: Setup, mock_notification, mock_knowledge_db, mock_user_integration_db, mock_user, mock_oauth_token
):
    """Delta sync task is queued when delta_token exists."""
    # Set delta token
    mock_knowledge_db.delta_token = "delta-token-123"

    # Mock database responses
    setup.service._fetch_knowledge_by_site = AsyncMock(
        return_value=[(mock_knowledge_db, mock_user_integration_db)]
    )

    setup.oauth_token_repo.one_or_none.return_value = mock_oauth_token
    setup.user_repo.get_user_by_id.return_value = mock_user

    # Mock change key service
    setup.change_key_service.should_process.return_value = True
    setup.change_key_service.update_change_key.return_value = None

    # Mock job service
    mock_job_service = AsyncMock()
    mock_job_service.queue_job = AsyncMock()

    with patch(
        "intric.integration.infrastructure.sharepoint_webhook_service.JobService",
        return_value=mock_job_service
    ):
        notifications = {"value": [mock_notification]}

        await setup.service.handle_notifications(notifications)

        # Verify delta sync task was queued
        mock_job_service.queue_job.assert_called_once()
        call_args = mock_job_service.queue_job.call_args
        assert call_args.kwargs["task"] == Task.SYNC_SHAREPOINT_DELTA


async def test_full_sync_when_no_delta_token(
    setup: Setup, mock_notification, mock_knowledge_db, mock_user_integration_db, mock_user, mock_oauth_token
):
    """Full sync task is queued when delta_token is None."""
    # No delta token
    mock_knowledge_db.delta_token = None

    # Mock database responses
    setup.service._fetch_knowledge_by_site = AsyncMock(
        return_value=[(mock_knowledge_db, mock_user_integration_db)]
    )

    setup.oauth_token_repo.one_or_none.return_value = mock_oauth_token
    setup.user_repo.get_user_by_id.return_value = mock_user

    # Mock change key service
    setup.change_key_service.should_process.return_value = True
    setup.change_key_service.update_change_key.return_value = None

    # Mock job service
    mock_job_service = AsyncMock()
    mock_job_service.queue_job = AsyncMock()

    with patch(
        "intric.integration.infrastructure.sharepoint_webhook_service.JobService",
        return_value=mock_job_service
    ):
        notifications = {"value": [mock_notification]}

        await setup.service.handle_notifications(notifications)

        # Verify full sync task was queued
        mock_job_service.queue_job.assert_called_once()
        call_args = mock_job_service.queue_job.call_args
        assert call_args.kwargs["task"] == Task.PULL_SHAREPOINT_CONTENT


def test_extract_site_id_from_resource_url(setup: Setup):
    """Site ID extracted correctly from resource URL."""
    notification = {
        "resource": "sites/site-abc-123/drives/drive-456/root"
    }

    site_id = setup.service._extract_site_id_from_notification(notification)

    assert site_id == "site-abc-123"


def test_extract_site_id_from_resource_data_fallback(setup: Setup):
    """Site ID extracted from resourceData if resource URL missing."""
    notification = {
        "resourceData": {
            "siteId": "site-xyz-789"
        }
    }

    site_id = setup.service._extract_site_id_from_notification(notification)

    assert site_id == "site-xyz-789"


def test_parse_site_id_from_various_formats(setup: Setup):
    """_parse_site_id handles various resource URL formats."""
    # Format 1: sites/{siteId}/drives/{driveId}/root
    assert setup.service._parse_site_id("sites/site-123/drives/drive-456/root") == "site-123"

    # Format 2: sites/{siteId}/lists/{listId}
    assert setup.service._parse_site_id("sites/site-789/lists/list-012") == "site-789"

    # Invalid format
    assert setup.service._parse_site_id("invalid/format") is None


async def test_onedrive_notifications_use_drive_lookup(setup: Setup):
    """Drive-scoped notifications must query integrations by drive_id."""
    notification = {
        "subscriptionId": "sub-123",
        "clientState": "test-client-state-123",
        "resource": "drives/drive-456/root",
        "changeType": "updated",
        "resourceData": {
            "@odata.type": "#Microsoft.Graph.driveItem",
            "id": "item-123",
            "changeKey": "change-key-789",
        },
    }

    setup.service._fetch_knowledge_by_drive = AsyncMock(return_value=[])
    setup.service._fetch_knowledge_by_site = AsyncMock(return_value=[])

    await setup.service.handle_notifications({"value": [notification]})

    setup.service._fetch_knowledge_by_drive.assert_called_once_with(drive_id="drive-456")
    setup.service._fetch_knowledge_by_site.assert_not_called()


async def test_onedrive_queued_job_contains_drive_id(
    setup: Setup, mock_user, mock_oauth_token
):
    """Queued task params should preserve OneDrive identity."""
    knowledge = MagicMock()
    knowledge.id = uuid4()
    knowledge.user_integration_id = uuid4()
    knowledge.site_id = None
    knowledge.drive_id = "drive-456"
    knowledge.resource_type = "onedrive"
    knowledge.folder_id = None
    knowledge.folder_path = None
    knowledge.selected_item_type = "site_root"
    knowledge.delta_token = None
    knowledge.name = "OneDrive Integration"

    user_integration = MagicMock()
    user_integration.id = uuid4()
    user_integration.user_id = uuid4()
    user_integration.tenant_id = uuid4()
    user_integration.auth_type = "user_oauth"
    user_integration.tenant_app_id = None

    notification = {
        "subscriptionId": "sub-123",
        "clientState": "test-client-state-123",
        "resource": "drives/drive-456/root",
        "changeType": "updated",
        "changeKey": "change-key-789",
        "resourceData": {
            "@odata.type": "#Microsoft.Graph.driveItem",
            "id": "item-123",
            "changeKey": "change-key-789",
        },
    }

    setup.service._fetch_knowledge_by_drive = AsyncMock(return_value=[(knowledge, user_integration)])
    setup.oauth_token_repo.one_or_none.return_value = mock_oauth_token
    setup.user_repo.get_user_by_id.return_value = mock_user
    setup.change_key_service.should_process.return_value = True
    setup.change_key_service.update_change_key.return_value = None

    mock_job_service = AsyncMock()
    mock_job_service.queue_job = AsyncMock()

    with patch(
        "intric.integration.infrastructure.sharepoint_webhook_service.JobService",
        return_value=mock_job_service
    ):
        await setup.service.handle_notifications({"value": [notification]})

    call_args = mock_job_service.queue_job.call_args
    task_params = call_args.kwargs["task_params"]
    assert task_params.drive_id == "drive-456"
    assert task_params.site_id is None
    assert task_params.resource_type == "onedrive"
