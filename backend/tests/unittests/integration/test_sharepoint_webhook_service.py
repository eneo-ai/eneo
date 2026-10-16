"""Unit tests for SharePointWebhookService - webhook notification processing.

Tests the webhook processing logic that handles Microsoft Graph change notifications,
including ChangeKey deduplication, scope filtering, and job queuing.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest

from eneo.integration.domain.entities.sharepoint_subscription import (
    SharePointSubscription,
)
from eneo.integration.infrastructure.sharepoint_webhook_service import (
    SharepointWebhookService,
)
from eneo.jobs.job_models import Task


def _subscription(
    *,
    subscription_id: str = "sub-123",
    site_id: str = "site-123",
    drive_id: str = "drive-456",
) -> SharePointSubscription:
    return SharePointSubscription(
        id=uuid4(),
        user_integration_id=uuid4(),
        site_id=site_id,
        subscription_id=subscription_id,
        drive_id=drive_id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=10),
    )


@dataclass
class Setup:
    """Test setup fixture data."""

    service: SharepointWebhookService
    session: AsyncMock
    oauth_token_repo: AsyncMock
    job_repo: AsyncMock
    user_repo: AsyncMock
    change_key_service: AsyncMock
    sharepoint_subscription_repo: AsyncMock
    subscription: SharePointSubscription


@pytest.fixture
def setup():
    """Create SharepointWebhookService with all dependencies mocked."""
    session = AsyncMock()
    oauth_token_repo = AsyncMock()
    job_repo = AsyncMock()
    user_repo = AsyncMock()
    change_key_service = AsyncMock()
    sharepoint_subscription_repo = AsyncMock()
    subscription = _subscription()
    sharepoint_subscription_repo.get_by_subscription_id.side_effect = (
        lambda subscription_id: subscription
        if subscription_id == subscription.subscription_id
        else None
    )

    service = SharepointWebhookService(
        session=session,
        oauth_token_repo=oauth_token_repo,
        job_repo=job_repo,
        user_repo=user_repo,
        change_key_service=change_key_service,
        sharepoint_subscription_repo=sharepoint_subscription_repo,
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
        sharepoint_subscription_repo=sharepoint_subscription_repo,
        subscription=subscription,
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
    setup.service._fetch_knowledge_by_subscription = AsyncMock(return_value=[])

    notifications = {"value": [mock_notification]}

    await setup.service.handle_notifications(notifications)

    setup.service._fetch_knowledge_by_subscription.assert_called_once_with(
        setup.subscription.id
    )


@pytest.mark.parametrize(
    "client_state",
    [
        pytest.param("wrong-client-state", id="wrong"),
        pytest.param("é", id="non-ascii"),
    ],
)
async def test_client_state_validation_rejects_invalid(
    setup: Setup, mock_notification, client_state
):
    """Notifications with incorrect client state are rejected."""
    mock_notification["clientState"] = client_state

    # Set up mock responses
    setup.service._fetch_knowledge_by_subscription = AsyncMock(return_value=[])

    notifications = {"value": [mock_notification]}

    await setup.service.handle_notifications(notifications)

    # Verify _fetch_knowledge_by_subscription was NOT called (notification was rejected)
    setup.service._fetch_knowledge_by_subscription.assert_not_called()
    setup.sharepoint_subscription_repo.get_by_subscription_id.assert_not_called()


async def test_client_state_validation_rejects_malformed(
    setup: Setup, mock_notification
):
    """Non-string clientState values are rejected without crashing."""
    mock_notification["clientState"] = {"unexpected": "shape"}
    setup.service._fetch_knowledge_by_subscription = AsyncMock(return_value=[])

    await setup.service.handle_notifications({"value": [mock_notification]})

    setup.service._fetch_knowledge_by_subscription.assert_not_called()
    setup.sharepoint_subscription_repo.get_by_subscription_id.assert_not_called()


async def test_configured_client_state_is_compared_stripped_as_utf8(
    setup: Setup, mock_notification
):
    """A secret with surrounding whitespace or non-ASCII characters still matches."""
    settings = MagicMock(sharepoint_webhook_client_state=" sécret \n")
    with patch(
        "eneo.integration.infrastructure.sharepoint_webhook_service.get_settings",
        return_value=settings,
    ):
        service = SharepointWebhookService(
            session=setup.session,
            oauth_token_repo=setup.oauth_token_repo,
            job_repo=setup.job_repo,
            user_repo=setup.user_repo,
            change_key_service=setup.change_key_service,
            sharepoint_subscription_repo=setup.sharepoint_subscription_repo,
        )
    mock_notification["clientState"] = "sécret"

    assert service.authenticated_notifications({"value": [mock_notification]}) == [
        mock_notification
    ]


async def test_rejects_all_when_client_state_not_configured(
    setup: Setup, mock_notification
):
    """Fail closed: with no configured secret, every notification is rejected."""
    setup.service.expected_client_state = ""
    setup.service._fetch_knowledge_by_subscription = AsyncMock(return_value=[])

    notifications = {"value": [mock_notification]}

    await setup.service.handle_notifications(notifications)

    setup.service._fetch_knowledge_by_subscription.assert_not_called()
    setup.sharepoint_subscription_repo.get_by_subscription_id.assert_not_called()


async def test_valid_webhook_records_subscription_received(
    setup: Setup, mock_notification
):
    """Valid notifications update subscription webhook health."""
    setup.service._fetch_knowledge_by_subscription = AsyncMock(return_value=[])

    await setup.service.handle_notifications({"value": [mock_notification]})

    setup.sharepoint_subscription_repo.get_by_subscription_id.assert_called_once_with(
        "sub-123"
    )
    assert setup.subscription.last_webhook_received_at is not None
    setup.sharepoint_subscription_repo.update.assert_called_once_with(
        setup.subscription
    )


async def test_unknown_subscription_is_ignored(setup: Setup, mock_notification):
    """A subscriptionId we never stored reaches no tenant's knowledge."""
    mock_notification["subscriptionId"] = "sub-from-someone-else"
    setup.service._fetch_knowledge_by_subscription = AsyncMock(return_value=[])

    await setup.service.handle_notifications({"value": [mock_notification]})

    setup.service._fetch_knowledge_by_subscription.assert_not_called()
    setup.sharepoint_subscription_repo.update.assert_not_called()
    setup.session.execute.assert_not_called()


async def test_notification_without_subscription_id_is_ignored(
    setup: Setup, mock_notification
):
    del mock_notification["subscriptionId"]
    setup.service._fetch_knowledge_by_subscription = AsyncMock(return_value=[])

    await setup.service.handle_notifications({"value": [mock_notification]})

    setup.sharepoint_subscription_repo.get_by_subscription_id.assert_not_called()
    setup.service._fetch_knowledge_by_subscription.assert_not_called()


async def test_knowledge_lookup_filters_on_the_subscription_row(setup: Setup):
    """Only knowledge referencing the subscription is loaded, never by site id."""
    result = MagicMock()
    result.all.return_value = []
    setup.session.execute.return_value = result

    await setup.service._fetch_knowledge_by_subscription(setup.subscription.id)

    statement = setup.session.execute.await_args.args[0]
    sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert (
        f"integration_knowledge.sharepoint_subscription_id = '{setup.subscription.id.hex}'"
        in sql
    )
    where_clause = sql.split("WHERE", 1)[1]
    assert "site_id" not in where_clause and "drive_id" not in where_clause


async def test_changekey_dedupe_is_scoped_per_subscription(
    setup: Setup, mock_notification
):
    """Two subscriptions on one site each see their own notification."""
    other = _subscription(subscription_id="sub-999")
    stored = {s.subscription_id: s for s in (setup.subscription, other)}
    setup.sharepoint_subscription_repo.get_by_subscription_id.side_effect = (
        lambda subscription_id: stored.get(subscription_id)
    )
    setup.service._fetch_knowledge_by_subscription = AsyncMock(return_value=[])
    second = dict(mock_notification, subscriptionId="sub-999")

    await setup.service.handle_notifications({"value": [mock_notification, second]})

    assert setup.service._fetch_knowledge_by_subscription.await_args_list == [
        ((setup.subscription.id,),),
        ((other.id,),),
    ]


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
    setup: Setup,
    mock_notification,
    mock_knowledge_db,
    mock_user_integration_db,
    mock_user,
    mock_oauth_token,
):
    """Duplicate ChangeKeys are filtered out to prevent reprocessing."""
    # First notification should process, second with same ChangeKey should skip
    setup.change_key_service.should_process.side_effect = [True, False]
    setup.change_key_service.update_change_key.return_value = None

    # Mock database responses
    setup.service._fetch_knowledge_by_subscription = AsyncMock(
        return_value=[(mock_knowledge_db, mock_user_integration_db)]
    )
    setup.oauth_token_repo.one_or_none.return_value = mock_oauth_token
    setup.user_repo.get_user_by_id.return_value = mock_user

    # Mock job service creation
    mock_job_service = AsyncMock()
    mock_job_service.queue_job = AsyncMock()

    with patch(
        "eneo.integration.infrastructure.sharepoint_webhook_service.JobService",
        return_value=mock_job_service,
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
    setup: Setup,
    mock_notification,
    mock_knowledge_db,
    mock_user_integration_db,
    mock_user,
    mock_oauth_token,
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
    setup.service._fetch_knowledge_by_subscription = AsyncMock(
        return_value=[(mock_knowledge_db, mock_user_integration_db)]
    )
    setup.oauth_token_repo.one_or_none.return_value = mock_oauth_token
    setup.user_repo.get_user_by_id.return_value = mock_user

    # Mock job service
    mock_job_service = AsyncMock()
    mock_job_service.queue_job = AsyncMock()

    with patch(
        "eneo.integration.infrastructure.sharepoint_webhook_service.JobService",
        return_value=mock_job_service,
    ):
        notifications = {"value": [notification1, notification2]}

        await setup.service.handle_notifications(notifications)

        # Verify update_change_key was called twice (for both unique notifications)
        assert setup.change_key_service.update_change_key.call_count == 2


def test_site_root_integration_processes_all_notifications(
    setup: Setup, mock_notification, mock_knowledge_db
):
    """Site-level integrations process all notifications."""
    mock_knowledge_db.selected_item_type = "site_root"
    mock_knowledge_db.folder_id = None

    result = setup.service._is_notification_in_scope(
        mock_notification, mock_knowledge_db
    )

    assert result is True


def test_file_integration_filters_by_exact_item_id(
    setup: Setup, mock_notification, mock_knowledge_db
):
    """File-level integrations filter by exact item ID match."""
    mock_knowledge_db.selected_item_type = "file"
    mock_knowledge_db.folder_id = (
        "item-123"  # folder_id stores the file ID for file-level
    )

    # Notification for the exact file
    notification_matching = mock_notification.copy()
    notification_matching["resourceData"]["id"] = "item-123"

    result_match = setup.service._is_notification_in_scope(
        notification_matching, mock_knowledge_db
    )
    assert result_match is True

    # Notification for a different file
    notification_not_matching = mock_notification.copy()
    notification_not_matching["resourceData"]["id"] = "item-999"

    result_no_match = setup.service._is_notification_in_scope(
        notification_not_matching, mock_knowledge_db
    )
    assert result_no_match is False


def test_file_integration_without_item_id_queues_anyway(
    setup: Setup, mock_notification, mock_knowledge_db
):
    """File-level integrations without item_id in notification queue for delta sync."""
    mock_knowledge_db.selected_item_type = "file"
    mock_knowledge_db.folder_id = "item-123"

    # Notification without item_id (common from Microsoft)
    notification_no_id = mock_notification.copy()
    notification_no_id["resourceData"] = {
        "@odata.type": "#Microsoft.Graph.driveItem",
    }

    result = setup.service._is_notification_in_scope(
        notification_no_id, mock_knowledge_db
    )

    # Should queue (True) to let delta sync handle it
    assert result is True


def test_folder_integration_queues_for_sync_service_filtering(
    setup: Setup, mock_notification, mock_knowledge_db
):
    """Folder-level integrations queue notifications for sync service filtering."""
    mock_knowledge_db.selected_item_type = "folder"
    mock_knowledge_db.folder_id = "folder-456"

    result = setup.service._is_notification_in_scope(
        mock_notification, mock_knowledge_db
    )

    # Should queue (True) and let sync service do full filtering
    assert result is True


async def test_tenant_app_integration_uses_tenant_app_id(
    setup: Setup,
    mock_notification,
    mock_knowledge_db,
    mock_tenant_app_integration_db,
    mock_user,
):
    """Tenant app integrations use tenant_app_id, no OAuth token."""
    # Mock database responses
    setup.service._fetch_knowledge_by_subscription = AsyncMock(
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
        "eneo.integration.infrastructure.sharepoint_webhook_service.JobService",
        return_value=mock_job_service,
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
    setup: Setup,
    mock_notification,
    mock_knowledge_db,
    mock_user_integration_db,
    mock_user,
    mock_oauth_token,
):
    """User OAuth integrations use OAuth token, no tenant_app_id."""
    # Mock database responses
    setup.service._fetch_knowledge_by_subscription = AsyncMock(
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
        "eneo.integration.infrastructure.sharepoint_webhook_service.JobService",
        return_value=mock_job_service,
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
    setup: Setup,
    mock_notification,
    mock_knowledge_db,
    mock_tenant_app_integration_db,
    mock_user,
):
    """Tenant app integrations use tenant admin as job owner."""
    # Mock database responses
    setup.service._fetch_knowledge_by_subscription = AsyncMock(
        return_value=[(mock_knowledge_db, mock_tenant_app_integration_db)]
    )

    # Mock admin user lookup
    admin_user = mock_user.copy() if hasattr(mock_user, "copy") else mock_user
    admin_user.id = uuid4()
    setup.user_repo.list_tenant_admins.return_value = [admin_user]

    # Mock change key service
    setup.change_key_service.should_process.return_value = True
    setup.change_key_service.update_change_key.return_value = None

    # Mock job service
    mock_job_service = AsyncMock()
    mock_job_service.queue_job = AsyncMock()

    with patch(
        "eneo.integration.infrastructure.sharepoint_webhook_service.JobService",
        return_value=mock_job_service,
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
    setup.service._fetch_knowledge_by_subscription = AsyncMock(
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
        "eneo.integration.infrastructure.sharepoint_webhook_service.JobService",
        return_value=mock_job_service,
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
    setup.service._fetch_knowledge_by_subscription = AsyncMock(
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
        "eneo.integration.infrastructure.sharepoint_webhook_service.JobService",
        return_value=mock_job_service,
    ):
        notifications = {"value": [mock_notification]}

        await setup.service.handle_notifications(notifications)

        # Verify NO job was queued
        mock_job_service.queue_job.assert_not_called()


async def test_delta_sync_when_delta_token_exists(
    setup: Setup,
    mock_notification,
    mock_knowledge_db,
    mock_user_integration_db,
    mock_user,
    mock_oauth_token,
):
    """Delta sync task is queued when delta_token exists."""
    # Set delta token
    mock_knowledge_db.delta_token = "delta-token-123"

    # Mock database responses
    setup.service._fetch_knowledge_by_subscription = AsyncMock(
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
        "eneo.integration.infrastructure.sharepoint_webhook_service.JobService",
        return_value=mock_job_service,
    ):
        notifications = {"value": [mock_notification]}

        await setup.service.handle_notifications(notifications)

        # Verify delta sync task was queued
        mock_job_service.queue_job.assert_called_once()
        call_args = mock_job_service.queue_job.call_args
        assert call_args.kwargs["task"] == Task.SYNC_SHAREPOINT_DELTA


async def test_full_sync_when_no_delta_token(
    setup: Setup,
    mock_notification,
    mock_knowledge_db,
    mock_user_integration_db,
    mock_user,
    mock_oauth_token,
):
    """Full sync task is queued when delta_token is None."""
    # No delta token
    mock_knowledge_db.delta_token = None

    # Mock database responses
    setup.service._fetch_knowledge_by_subscription = AsyncMock(
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
        "eneo.integration.infrastructure.sharepoint_webhook_service.JobService",
        return_value=mock_job_service,
    ):
        notifications = {"value": [mock_notification]}

        await setup.service.handle_notifications(notifications)

        # Verify full sync task was queued
        mock_job_service.queue_job.assert_called_once()
        call_args = mock_job_service.queue_job.call_args
        assert call_args.kwargs["task"] == Task.PULL_SHAREPOINT_CONTENT


async def test_dedupe_key_is_derived_from_the_subscription(
    setup: Setup, mock_notification
):
    setup.service._fetch_knowledge_by_subscription = AsyncMock(
        return_value=[(MagicMock(), MagicMock())]
    )
    setup.change_key_service.should_process.return_value = False

    await setup.service.handle_notifications({"value": [mock_notification]})

    kwargs = setup.change_key_service.should_process.await_args.kwargs
    assert kwargs["integration_knowledge_id"] == uuid5(
        NAMESPACE_URL, f"subscription:{setup.subscription.id}"
    )


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

    onedrive = _subscription(site_id="drive-456", drive_id="drive-456")
    setup.sharepoint_subscription_repo.get_by_subscription_id.side_effect = None
    setup.sharepoint_subscription_repo.get_by_subscription_id.return_value = onedrive
    setup.service._fetch_knowledge_by_subscription = AsyncMock(
        return_value=[(knowledge, user_integration)]
    )
    setup.oauth_token_repo.one_or_none.return_value = mock_oauth_token
    setup.user_repo.get_user_by_id.return_value = mock_user
    setup.change_key_service.should_process.return_value = True
    setup.change_key_service.update_change_key.return_value = None

    mock_job_service = AsyncMock()
    mock_job_service.queue_job = AsyncMock()

    with patch(
        "eneo.integration.infrastructure.sharepoint_webhook_service.JobService",
        return_value=mock_job_service,
    ):
        await setup.service.handle_notifications({"value": [notification]})

    call_args = mock_job_service.queue_job.call_args
    task_params = call_args.kwargs["task_params"]
    assert task_params.drive_id == "drive-456"
    assert task_params.site_id is None
    assert task_params.resource_type == "onedrive"
