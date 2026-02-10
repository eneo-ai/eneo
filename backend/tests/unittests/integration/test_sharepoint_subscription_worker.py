"""Unit tests for SharePoint subscription worker - cron jobs for renewal and cleanup.

Tests the get_token_for_subscription helper function and cron job behavior
for both user OAuth and tenant app authentication methods.
"""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from intric.integration.domain.entities.sharepoint_subscription import SharePointSubscription
from intric.integration.infrastructure.sharepoint_subscription_worker import (
    get_token_for_subscription,
    cleanup_orphaned_subscriptions,
    renew_expiring_subscriptions,
)


@asynccontextmanager
async def mock_session_context():
    """Mock async context manager for sessionmanager.session()."""
    mock_session = AsyncMock()
    mock_session.begin = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(), __aexit__=AsyncMock()))
    yield mock_session


@pytest.fixture
def mock_subscription():
    """Create a mock SharePoint subscription entity."""
    return SharePointSubscription(
        id=uuid4(),
        user_integration_id=uuid4(),
        site_id="site-id-123,web-id-456,list-id-789",
        subscription_id="graph-subscription-id-abc",
        drive_id="drive-id-xyz",
        expires_at=datetime.now(timezone.utc) + timedelta(days=29),
    )


@pytest.fixture
def mock_container():
    """Create a mock DI container with all required services."""
    container = MagicMock()

    # Mock repositories
    container.user_integration_repo = MagicMock(return_value=AsyncMock())
    container.sharepoint_subscription_repo = MagicMock(return_value=AsyncMock())
    container.tenant_sharepoint_app_repo = MagicMock(return_value=AsyncMock())

    # Mock services
    container.oauth_token_service = MagicMock(return_value=AsyncMock())
    container.tenant_app_auth_service = MagicMock(return_value=AsyncMock())
    container.service_account_auth_service = MagicMock(return_value=AsyncMock())
    container.sharepoint_subscription_service = MagicMock(return_value=AsyncMock())

    # Mock session
    mock_session = AsyncMock()
    mock_session.begin = MagicMock(return_value=AsyncMock())
    container.session = MagicMock(return_value=mock_session)

    return container


class TestGetTokenForSubscription:
    """Tests for get_token_for_subscription helper function."""

    @pytest.mark.asyncio
    async def test_returns_oauth_token_for_user_oauth_auth(self, mock_subscription, mock_container):
        """Test that OAuth token is returned for user_oauth auth type."""
        # Setup user integration with user_oauth auth
        user_integration = MagicMock()
        user_integration.auth_type = "user_oauth"
        user_integration.tenant_app_id = None

        mock_container.user_integration_repo().one = AsyncMock(return_value=user_integration)

        # Setup OAuth token
        oauth_token = MagicMock()
        oauth_token.token_type.is_sharepoint = True
        oauth_token.id = uuid4()
        oauth_token.access_token = "oauth-access-token"

        mock_container.oauth_token_service().get_oauth_token_by_user_integration = AsyncMock(
            return_value=oauth_token
        )
        mock_container.oauth_token_service().refresh_and_update_token = AsyncMock(
            return_value=oauth_token
        )

        # Execute
        token = await get_token_for_subscription(mock_subscription, mock_container)

        # Verify
        assert token is not None
        assert token.access_token == "oauth-access-token"
        mock_container.oauth_token_service().get_oauth_token_by_user_integration.assert_called_once()
        mock_container.oauth_token_service().refresh_and_update_token.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_tenant_app_token_for_tenant_app_auth(self, mock_subscription, mock_container):
        """Test that tenant app token is returned for tenant_app auth type."""
        tenant_app_id = uuid4()

        # Setup user integration with tenant_app auth
        user_integration = MagicMock()
        user_integration.auth_type = "tenant_app"
        user_integration.tenant_app_id = tenant_app_id

        mock_container.user_integration_repo().one = AsyncMock(return_value=user_integration)

        # Setup tenant app (not service account)
        tenant_app = MagicMock()
        tenant_app.is_service_account = MagicMock(return_value=False)

        mock_container.tenant_sharepoint_app_repo().one = AsyncMock(return_value=tenant_app)
        mock_container.tenant_app_auth_service().get_access_token = AsyncMock(
            return_value="tenant-app-access-token"
        )

        # Execute
        token = await get_token_for_subscription(mock_subscription, mock_container)

        # Verify
        assert token is not None
        assert token.access_token == "tenant-app-access-token"
        mock_container.tenant_app_auth_service().get_access_token.assert_called_once_with(tenant_app)

    @pytest.mark.asyncio
    async def test_returns_service_account_token_for_service_account_auth(
        self, mock_subscription, mock_container
    ):
        """Test that service account token is returned for service account auth method."""
        tenant_app_id = uuid4()

        # Setup user integration with tenant_app auth
        user_integration = MagicMock()
        user_integration.auth_type = "tenant_app"
        user_integration.tenant_app_id = tenant_app_id

        mock_container.user_integration_repo().one = AsyncMock(return_value=user_integration)

        # Setup tenant app (is service account)
        tenant_app = MagicMock()
        tenant_app.is_service_account = MagicMock(return_value=True)
        tenant_app.service_account_refresh_token = "old-refresh-token"

        mock_container.tenant_sharepoint_app_repo().one = AsyncMock(return_value=tenant_app)
        mock_container.service_account_auth_service().refresh_access_token = AsyncMock(
            return_value={
                "access_token": "service-account-access-token",
                "refresh_token": "new-refresh-token",
            }
        )

        # Execute
        token = await get_token_for_subscription(mock_subscription, mock_container)

        # Verify
        assert token is not None
        assert token.access_token == "service-account-access-token"
        mock_container.service_account_auth_service().refresh_access_token.assert_called_once_with(
            tenant_app
        )
        tenant_app.update_refresh_token.assert_called_once_with("new-refresh-token")
        mock_container.tenant_sharepoint_app_repo().update.assert_called_once_with(tenant_app)

    @pytest.mark.asyncio
    async def test_returns_none_when_no_oauth_token_found(self, mock_subscription, mock_container):
        """Test that None is returned when no OAuth token exists."""
        user_integration = MagicMock()
        user_integration.auth_type = "user_oauth"

        mock_container.user_integration_repo().one = AsyncMock(return_value=user_integration)
        mock_container.oauth_token_service().get_oauth_token_by_user_integration = AsyncMock(
            return_value=None
        )

        token = await get_token_for_subscription(mock_subscription, mock_container)

        assert token is None

    @pytest.mark.asyncio
    async def test_returns_none_when_tenant_app_id_missing(self, mock_subscription, mock_container):
        """Test that None is returned when tenant_app auth but no tenant_app_id."""
        user_integration = MagicMock()
        user_integration.auth_type = "tenant_app"
        user_integration.tenant_app_id = None

        mock_container.user_integration_repo().one = AsyncMock(return_value=user_integration)

        token = await get_token_for_subscription(mock_subscription, mock_container)

        assert token is None

    @pytest.mark.asyncio
    async def test_returns_none_when_user_integration_not_found(
        self, mock_subscription, mock_container
    ):
        """Test that None is returned when user integration lookup fails."""
        mock_container.user_integration_repo().one = AsyncMock(
            side_effect=Exception("Not found")
        )

        token = await get_token_for_subscription(mock_subscription, mock_container)

        assert token is None


class TestCleanupOrphanedSubscriptions:
    """Tests for cleanup_orphaned_subscriptions cron job."""

    @pytest.mark.asyncio
    async def test_skips_subscriptions_with_references(self, mock_container):
        """Test that subscriptions with references are skipped."""
        subscription = SharePointSubscription(
            id=uuid4(),
            user_integration_id=uuid4(),
            site_id="site-123",
            subscription_id="sub-123",
            drive_id="drive-123",
            expires_at=datetime.now(timezone.utc) + timedelta(days=10),
        )

        mock_container.sharepoint_subscription_repo().list_all = AsyncMock(
            return_value=[subscription]
        )
        mock_container.sharepoint_subscription_repo().count_references = AsyncMock(return_value=1)

        # Patch sessionmanager and worker._create_container
        with patch(
            "intric.integration.infrastructure.sharepoint_subscription_worker.worker._create_container",
            new_callable=AsyncMock,
            return_value=mock_container,
        ):
            with patch(
                "intric.worker.worker.sessionmanager.session",
                return_value=mock_session_context(),
            ):
                result = await cleanup_orphaned_subscriptions()

        assert result["skipped"] == 1
        assert result["deleted"] == 0

    @pytest.mark.asyncio
    async def test_deletes_orphaned_subscription_with_tenant_app(self, mock_container):
        """Test that orphaned subscription with tenant app auth is deleted."""
        subscription = SharePointSubscription(
            id=uuid4(),
            user_integration_id=uuid4(),
            site_id="site-123,web-123,list-123",
            subscription_id="sub-123",
            drive_id="drive-123",
            expires_at=datetime.now(timezone.utc) + timedelta(days=10),
        )

        # Setup repos
        mock_container.sharepoint_subscription_repo().list_all = AsyncMock(
            return_value=[subscription]
        )
        mock_container.sharepoint_subscription_repo().count_references = AsyncMock(return_value=0)

        # Setup user integration with tenant app
        user_integration = MagicMock()
        user_integration.auth_type = "tenant_app"
        user_integration.tenant_app_id = uuid4()
        mock_container.user_integration_repo().one = AsyncMock(return_value=user_integration)

        # Setup tenant app
        tenant_app = MagicMock()
        tenant_app.is_service_account = MagicMock(return_value=False)
        mock_container.tenant_sharepoint_app_repo().one = AsyncMock(return_value=tenant_app)
        mock_container.tenant_app_auth_service().get_access_token = AsyncMock(
            return_value="access-token"
        )

        # Setup delete success
        mock_container.sharepoint_subscription_service().delete_subscription_if_unused = AsyncMock(
            return_value=True
        )

        # Patch sessionmanager and worker._create_container
        with patch(
            "intric.integration.infrastructure.sharepoint_subscription_worker.worker._create_container",
            new_callable=AsyncMock,
            return_value=mock_container,
        ):
            with patch(
                "intric.worker.worker.sessionmanager.session",
                return_value=mock_session_context(),
            ):
                result = await cleanup_orphaned_subscriptions()

        assert result["deleted"] == 1
        assert result["failed"] == 0
        mock_container.sharepoint_subscription_service().delete_subscription_if_unused.assert_called_once()


class TestRenewExpiringSubscriptions:
    """Tests for renew_expiring_subscriptions cron job."""

    @pytest.mark.asyncio
    async def test_renews_subscription_with_tenant_app(self, mock_container):
        """Test that expiring subscription with tenant app auth is renewed."""
        subscription = SharePointSubscription(
            id=uuid4(),
            user_integration_id=uuid4(),
            site_id="site-123,web-123,list-123",
            subscription_id="sub-123",
            drive_id="drive-123",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),  # Expiring soon
        )

        # Setup subscription service
        mock_container.sharepoint_subscription_service().list_expiring_subscriptions = AsyncMock(
            return_value=[subscription]
        )

        # Setup user integration with tenant app
        user_integration = MagicMock()
        user_integration.auth_type = "tenant_app"
        user_integration.tenant_app_id = uuid4()
        mock_container.user_integration_repo().one = AsyncMock(return_value=user_integration)

        # Setup tenant app
        tenant_app = MagicMock()
        tenant_app.is_service_account = MagicMock(return_value=False)
        mock_container.tenant_sharepoint_app_repo().one = AsyncMock(return_value=tenant_app)
        mock_container.tenant_app_auth_service().get_access_token = AsyncMock(
            return_value="access-token"
        )

        # Setup renewal success
        mock_container.sharepoint_subscription_service().renew_subscription = AsyncMock(
            return_value=True
        )

        # Patch sessionmanager and worker._create_container
        with patch(
            "intric.integration.infrastructure.sharepoint_subscription_worker.worker._create_container",
            new_callable=AsyncMock,
            return_value=mock_container,
        ):
            with patch(
                "intric.worker.worker.sessionmanager.session",
                return_value=mock_session_context(),
            ):
                result = await renew_expiring_subscriptions()

        assert result["renewed"] == 1
        assert result["failed"] == 0
        mock_container.sharepoint_subscription_service().renew_subscription.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_early_when_no_expiring_subscriptions(self, mock_container):
        """Test that job returns early when no subscriptions need renewal."""
        mock_container.sharepoint_subscription_service().list_expiring_subscriptions = AsyncMock(
            return_value=[]
        )

        # Patch sessionmanager and worker._create_container
        with patch(
            "intric.integration.infrastructure.sharepoint_subscription_worker.worker._create_container",
            new_callable=AsyncMock,
            return_value=mock_container,
        ):
            with patch(
                "intric.worker.worker.sessionmanager.session",
                return_value=mock_session_context(),
            ):
                result = await renew_expiring_subscriptions()

        assert result["renewed"] == 0
        assert result["failed"] == 0
