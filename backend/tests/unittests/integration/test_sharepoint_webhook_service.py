"""Unit tests for SharePointWebhookService - webhook notification processing.

Tests the webhook processing logic that handles Microsoft Graph change notifications,
including ChangeKey deduplication, scope filtering, and job queuing.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import RedisError

from eneo.integration.domain.entities.sharepoint_subscription import (
    SharePointSubscription,
)
from eneo.integration.infrastructure.sharepoint_sync_keys import (
    SHAREPOINT_SYNC_PENDING_TTL_SECONDS,
    SHAREPOINT_SYNC_QUEUED_TTL_SECONDS,
    sync_lock_key,
    sync_pending_full_key,
    sync_pending_key,
    sync_queued_key,
)
from eneo.integration.infrastructure.sharepoint_webhook_service import (
    SharepointWebhookService,
)
from eneo.integration.tasks import integration_task
from eneo.jobs.job_models import Task


async def _handle(service: SharepointWebhookService, payload) -> None:
    """The router's path: authenticate the body, then queue syncs for what passed."""
    await service.handle_notifications(service.authenticated_notifications(payload))


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
    redis: AsyncMock


@pytest.fixture
def setup():
    """Create SharepointWebhookService with all dependencies mocked."""
    session = AsyncMock()
    oauth_token_repo = AsyncMock()
    job_repo = AsyncMock()
    user_repo = AsyncMock()
    change_key_service = AsyncMock()
    sharepoint_subscription_repo = AsyncMock()
    redis = AsyncMock()
    redis.exists.return_value = 0
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
        redis_client=redis,
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
        redis=redis,
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

    await _handle(setup.service, notifications)

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

    await _handle(setup.service, notifications)

    # Verify _fetch_knowledge_by_subscription was NOT called (notification was rejected)
    setup.service._fetch_knowledge_by_subscription.assert_not_called()
    setup.sharepoint_subscription_repo.get_by_subscription_id.assert_not_called()


async def test_client_state_validation_rejects_malformed(
    setup: Setup, mock_notification
):
    """Non-string clientState values are rejected without crashing."""
    mock_notification["clientState"] = {"unexpected": "shape"}
    setup.service._fetch_knowledge_by_subscription = AsyncMock(return_value=[])

    await _handle(setup.service, {"value": [mock_notification]})

    setup.service._fetch_knowledge_by_subscription.assert_not_called()
    setup.sharepoint_subscription_repo.get_by_subscription_id.assert_not_called()


async def test_rejections_are_summarised_in_one_log_line_per_call(
    setup: Setup, mock_notification
):
    """The endpoint is public; a forged body must not write one line per element."""
    forged = [{**mock_notification, "clientState": "wrong"} for _ in range(1000)]
    payload = {"value": [*forged, 1, "x", mock_notification]}

    with patch(
        "eneo.integration.infrastructure.sharepoint_webhook_service.logger"
    ) as log:
        accepted = setup.service.authenticated_notifications(payload)

    assert accepted == [mock_notification]
    assert log.warning.call_count == 1
    assert log.warning.call_args.args[1:] == (1002, 1003, 1000, 2)


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
            redis_client=setup.redis,
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

    await _handle(setup.service, notifications)

    setup.service._fetch_knowledge_by_subscription.assert_not_called()
    setup.sharepoint_subscription_repo.get_by_subscription_id.assert_not_called()


async def test_valid_webhook_records_subscription_received(
    setup: Setup, mock_notification
):
    """Valid notifications update subscription webhook health."""
    setup.service._fetch_knowledge_by_subscription = AsyncMock(return_value=[])

    await _handle(setup.service, {"value": [mock_notification]})

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

    await _handle(setup.service, {"value": [mock_notification]})

    setup.service._fetch_knowledge_by_subscription.assert_not_called()
    setup.sharepoint_subscription_repo.update.assert_not_called()
    setup.session.execute.assert_not_called()


async def test_notification_without_subscription_id_is_ignored(
    setup: Setup, mock_notification
):
    del mock_notification["subscriptionId"]
    setup.service._fetch_knowledge_by_subscription = AsyncMock(return_value=[])

    await _handle(setup.service, {"value": [mock_notification]})

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

    await _handle(setup.service, {"value": [mock_notification, second]})

    assert setup.service._fetch_knowledge_by_subscription.await_args_list == [
        ((setup.subscription.id,),),
        ((other.id,),),
    ]


async def test_empty_notifications_handled_gracefully(setup: Setup):
    """Empty notification list is handled without errors."""
    notifications = {"value": []}

    # Should not raise
    await _handle(setup.service, notifications)


async def test_missing_value_key_handled_gracefully(setup: Setup):
    """Missing 'value' key is handled without errors."""
    notifications = {}

    # Should not raise
    await _handle(setup.service, notifications)


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

        await _handle(setup.service, notifications)

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

        await _handle(setup.service, notifications)

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


def _running_sync_setup(setup: Setup, knowledge_db, integration_db, user) -> None:
    setup.service._fetch_knowledge_by_subscription = AsyncMock(
        return_value=[(knowledge_db, integration_db)]
    )
    setup.user_repo.list_tenant_admins.return_value = [user]
    setup.change_key_service.should_process.return_value = True


@pytest.mark.parametrize("released_meanwhile", [False, True])
async def test_a_notification_during_a_running_sync_leaves_a_marker_not_a_job(
    setup: Setup,
    mock_notification,
    mock_knowledge_db,
    mock_tenant_app_integration_db,
    mock_user,
    released_meanwhile,
):
    """A job queued now would only find the lease taken; the holder reruns
    instead. If the holder released between the check and the marker, a job
    is queued after all so the marker is drained."""
    _running_sync_setup(
        setup, mock_knowledge_db, mock_tenant_app_integration_db, mock_user
    )
    setup.redis.exists.side_effect = [1, 0 if released_meanwhile else 1]
    job_service = AsyncMock()

    with patch(
        "eneo.integration.infrastructure.sharepoint_webhook_service.JobService",
        return_value=job_service,
    ):
        await _handle(setup.service, {"value": [mock_notification]})

    knowledge_id = str(mock_knowledge_db.id)
    assert setup.redis.exists.await_args_list == [
        call(sync_lock_key(knowledge_id)),
        call(sync_lock_key(knowledge_id)),
    ]
    marker = call(
        sync_pending_key(knowledge_id), "1", ex=SHAREPOINT_SYNC_PENDING_TTL_SECONDS
    )
    if released_meanwhile:
        assert setup.redis.set.await_args_list == [
            marker,
            call(
                sync_queued_key(knowledge_id),
                "1",
                nx=True,
                ex=SHAREPOINT_SYNC_QUEUED_TTL_SECONDS,
            ),
        ]
        job_service.queue_job.assert_awaited_once()
    else:
        assert setup.redis.set.await_args_list == [marker]
        job_service.queue_job.assert_not_awaited()


async def test_a_redis_outage_falls_back_to_queuing_the_job(
    setup: Setup,
    mock_notification,
    mock_knowledge_db,
    mock_tenant_app_integration_db,
    mock_user,
):
    _running_sync_setup(
        setup, mock_knowledge_db, mock_tenant_app_integration_db, mock_user
    )
    setup.redis.exists.side_effect = RedisConnectionError("refused")
    setup.redis.set.side_effect = RedisConnectionError("refused")
    job_service = AsyncMock()

    with patch(
        "eneo.integration.infrastructure.sharepoint_webhook_service.JobService",
        return_value=job_service,
    ):
        await _handle(setup.service, {"value": [mock_notification]})

    job_service.queue_job.assert_awaited_once()
    # Neither the marker nor the queued-sync check got through.
    assert [c.args[0] for c in setup.redis.set.await_args_list] == [
        sync_queued_key(str(mock_knowledge_db.id))
    ]


def test_the_webhook_uses_the_sync_tasks_lease_and_marker_keys():
    assert sync_lock_key("k") == integration_task._lock_key("k")  # pyright: ignore[reportPrivateUsage]
    assert sync_pending_key("k") == integration_task._pending_key("k")  # pyright: ignore[reportPrivateUsage]


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

        await _handle(setup.service, notifications)

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

        await _handle(setup.service, notifications)

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

        await _handle(setup.service, notifications)

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

        await _handle(setup.service, notifications)

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

        await _handle(setup.service, notifications)

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

        await _handle(setup.service, notifications)

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

        await _handle(setup.service, notifications)

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

    await _handle(setup.service, {"value": [mock_notification]})

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
        await _handle(setup.service, {"value": [notification]})

    call_args = mock_job_service.queue_job.call_args
    task_params = call_args.kwargs["task_params"]
    assert task_params.drive_id == "drive-456"
    assert task_params.site_id is None
    assert task_params.resource_type == "onedrive"


class _Transaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False


class _NxRedis:
    """Enough of Redis for the queued-sync marker: SET NX really refuses."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def exists(self, key):
        return 1 if key in self.store else 0

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def delete(self, key):
        return 1 if self.store.pop(key, None) is not None else 0


async def test_a_burst_of_notifications_queues_one_sync_per_knowledge(
    setup: Setup,
    mock_notification,
    mock_knowledge_db,
    mock_tenant_app_integration_db,
    mock_user,
):
    """Until the queued job starts, every later change is covered by it."""
    _running_sync_setup(
        setup, mock_knowledge_db, mock_tenant_app_integration_db, mock_user
    )
    setup.service.redis_client = _NxRedis()  # pyright: ignore[reportAttributeAccessIssue]
    job_service = AsyncMock()

    with patch(
        "eneo.integration.infrastructure.sharepoint_webhook_service.JobService",
        return_value=job_service,
    ):
        for _ in range(3):
            await _handle(setup.service, {"value": [mock_notification]})

    job_service.queue_job.assert_awaited_once()
    assert job_service.queue_job.await_args.kwargs["after_commit"] is True


async def test_a_job_that_could_not_be_queued_frees_the_queued_sync_marker(
    setup: Setup,
    mock_notification,
    mock_knowledge_db,
    mock_tenant_app_integration_db,
    mock_user,
):
    _running_sync_setup(
        setup, mock_knowledge_db, mock_tenant_app_integration_db, mock_user
    )
    redis = _NxRedis()
    setup.service.redis_client = redis  # pyright: ignore[reportAttributeAccessIssue]
    job_service = AsyncMock()
    job_service.queue_job.side_effect = RuntimeError("database down")

    with (
        patch(
            "eneo.integration.infrastructure.sharepoint_webhook_service.JobService",
            return_value=job_service,
        ),
        pytest.raises(RuntimeError),
    ):
        await _handle(setup.service, {"value": [mock_notification]})

    assert sync_queued_key(str(mock_knowledge_db.id)) not in redis.store


@pytest.mark.parametrize(
    ("delta_token", "full", "expected"),
    [
        ("token", False, Task.SYNC_SHAREPOINT_DELTA),
        ("token", True, Task.PULL_SHAREPOINT_CONTENT),
        (None, False, Task.PULL_SHAREPOINT_CONTENT),
    ],
)
async def test_queue_sync_for_knowledge_uses_the_rows_own_resource(
    setup: Setup,
    mock_knowledge_db,
    mock_tenant_app_integration_db,
    mock_user,
    delta_token,
    full,
    expected,
):
    mock_knowledge_db.delta_token = delta_token
    mock_knowledge_db.resource_type = "site"
    mock_knowledge_db.drive_id = "drive-456"
    setup.service._fetch_knowledge = AsyncMock(  # pyright: ignore[reportPrivateUsage]
        return_value=[(mock_knowledge_db, mock_tenant_app_integration_db)]
    )
    setup.user_repo.list_tenant_admins.return_value = [mock_user]
    job_service = AsyncMock()

    with patch(
        "eneo.integration.infrastructure.sharepoint_webhook_service.JobService",
        return_value=job_service,
    ):
        queued = await setup.service.queue_sync_for_knowledge(
            mock_knowledge_db.id, full=full
        )

    assert queued == expected
    kwargs = job_service.queue_job.await_args.kwargs
    assert kwargs["task"] == expected
    params = kwargs["task_params"]
    assert params.integration_knowledge_id == mock_knowledge_db.id
    assert params.site_id == "site-123"
    assert params.drive_id == "drive-456"
    assert params.tenant_app_id == mock_tenant_app_integration_db.tenant_app_id


async def test_queue_sync_for_a_deleted_knowledge_queues_nothing(setup: Setup):
    setup.service._fetch_knowledge = AsyncMock(return_value=[])  # pyright: ignore[reportPrivateUsage]
    job_service = AsyncMock()

    with patch(
        "eneo.integration.infrastructure.sharepoint_webhook_service.JobService",
        return_value=job_service,
    ):
        assert await setup.service.queue_sync_for_knowledge(uuid4()) is None

    job_service.queue_job.assert_not_awaited()


def _lifecycle(event: str, subscription_id: str = "sub-123") -> dict[str, str]:
    return {
        "subscriptionId": subscription_id,
        "clientState": "test-client-state-123",
        "lifecycleEvent": event,
        "subscriptionExpirationDateTime": "2026-11-01T00:00:00Z",
    }


async def test_missed_notifications_queue_a_sync_for_every_row_on_the_subscription(
    setup: Setup,
    mock_knowledge_db,
    mock_tenant_app_integration_db,
    mock_user,
):
    file_scoped = MagicMock()
    file_scoped.id = uuid4()
    file_scoped.site_id = "site-123"
    file_scoped.drive_id = None
    file_scoped.resource_type = "site"
    file_scoped.folder_id = "file-1"
    file_scoped.folder_path = None
    file_scoped.selected_item_type = "file"
    file_scoped.delta_token = "token"
    file_scoped.name = "One file"
    setup.service._fetch_knowledge_by_subscription = AsyncMock(
        return_value=[
            (mock_knowledge_db, mock_tenant_app_integration_db),
            (file_scoped, mock_tenant_app_integration_db),
        ]
    )
    setup.user_repo.list_tenant_admins.return_value = [mock_user]
    job_service = AsyncMock()

    with patch(
        "eneo.integration.infrastructure.sharepoint_webhook_service.JobService",
        return_value=job_service,
    ):
        maintenance = await setup.service.handle_notifications([_lifecycle("missed")])

    assert maintenance == []
    queued = {
        call.kwargs["task_params"].integration_knowledge_id
        for call in job_service.queue_job.await_args_list
    }
    assert queued == {mock_knowledge_db.id, file_scoped.id}
    setup.change_key_service.should_process.assert_not_called()


@pytest.mark.parametrize("event", ["reauthorizationRequired", "subscriptionRemoved"])
async def test_lifecycle_events_needing_graph_are_returned_once_per_window(
    setup: Setup, event
):
    store: dict[str, str] = {}

    async def set_nx(key, value, nx=False, ex=None):
        if nx and key in store:
            return None
        store[key] = value
        return True

    setup.redis.set.side_effect = set_nx
    setup.service._fetch_knowledge_by_subscription = AsyncMock(return_value=[])

    first = await setup.service.handle_notifications(
        [_lifecycle(event), _lifecycle(event)]
    )
    second = await setup.service.handle_notifications([_lifecycle(event)])

    assert [(m.subscription_id, m.event) for m in first] == [
        (setup.subscription.id, event)
    ]
    assert second == []
    setup.service._fetch_knowledge_by_subscription.assert_not_called()


async def test_lifecycle_events_call_graph_for_none_while_redis_is_down(setup: Setup):
    setup.redis.set.side_effect = RedisError("down")
    setup.service._fetch_knowledge_by_subscription = AsyncMock(return_value=[])

    maintenance = await setup.service.handle_notifications(
        [_lifecycle("reauthorizationRequired"), _lifecycle("subscriptionRemoved")]
    )

    assert maintenance == []


async def test_lifecycle_events_for_unknown_subscriptions_are_ignored(setup: Setup):
    setup.service._fetch_knowledge_by_subscription = AsyncMock(return_value=[])

    maintenance = await setup.service.handle_notifications(
        [_lifecycle("missed", "sub-unknown"), _lifecycle("subscriptionRemoved", "x")]
    )

    assert maintenance == []
    setup.service._fetch_knowledge_by_subscription.assert_not_called()


async def test_a_lifecycle_event_is_not_treated_as_a_change(setup: Setup):
    setup.service._fetch_knowledge_by_subscription = AsyncMock(return_value=[])

    await setup.service.handle_notifications([_lifecycle("somethingNew")])

    setup.service._fetch_knowledge_by_subscription.assert_not_called()
    setup.sharepoint_subscription_repo.update.assert_not_called()


@pytest.mark.parametrize(
    ("full", "marker"), [(False, sync_pending_key), (True, sync_pending_full_key)]
)
async def test_a_change_behind_a_dead_queued_sync_is_served_by_the_catch_up(
    setup: Setup,
    mock_knowledge_db,
    mock_tenant_app_integration_db,
    mock_user,
    full,
    marker,
):
    """The queued job may never run (lost delivery, worker gone); the change
    must then still reach the catch-up once the queued marker expires."""
    from eneo.integration.infrastructure.sharepoint_webhook_service import (
        _CatchUpCandidate,  # pyright: ignore[reportPrivateUsage]
    )

    knowledge_id = str(mock_knowledge_db.id)
    mock_knowledge_db.delta_token = "token"
    redis = _NxRedis()
    redis.store[sync_queued_key(knowledge_id)] = "1"
    setup.service.redis_client = redis  # pyright: ignore[reportAttributeAccessIssue]
    setup.service._fetch_knowledge = AsyncMock(  # pyright: ignore[reportPrivateUsage]
        return_value=[(mock_knowledge_db, mock_tenant_app_integration_db)]
    )
    setup.session.begin = MagicMock(return_value=_Transaction())
    setup.user_repo.list_tenant_admins.return_value = [mock_user]
    job_service = AsyncMock()

    with patch(
        "eneo.integration.infrastructure.sharepoint_webhook_service.JobService",
        return_value=job_service,
    ):
        assert (
            await setup.service.queue_sync_for_knowledge(
                mock_knowledge_db.id, full=full
            )
            is None
        )
        job_service.queue_job.assert_not_awaited()
        assert redis.store[marker(knowledge_id)] == "1"

        del redis.store[sync_queued_key(knowledge_id)]
        now = datetime.now(timezone.utc)
        setup.service._catch_up_candidates = AsyncMock(  # pyright: ignore[reportPrivateUsage]
            return_value=[
                _CatchUpCandidate(
                    id=mock_knowledge_db.id,
                    has_delta_token=True,
                    last_activity=now - timedelta(hours=1),
                )
            ]
        )
        setup.service._sync_states = AsyncMock(  # pyright: ignore[reportPrivateUsage]
            side_effect=lambda ids: {
                ids[0]: SimpleNamespace(
                    running=False,
                    queued=False,
                    full_requested=full,
                    delta_requested=not full,
                    recently_caught_up=False,
                    marker_recently_caught_up=False,
                )
            }
        )
        summary = await setup.service.queue_catch_up_syncs(
            stale_before=now - timedelta(hours=6), limit=25, window_seconds=6 * 3600
        )

    assert summary["markers"] == 1
    assert job_service.queue_job.await_args.kwargs["task"] == (
        Task.PULL_SHAREPOINT_CONTENT if full else Task.SYNC_SHAREPOINT_DELTA
    )
