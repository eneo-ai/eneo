"""Unit tests for SharePoint subscription worker - cron jobs for renewal and cleanup.

Tests the get_token_for_subscription helper function and cron job behavior
for both user OAuth and tenant app authentication methods.
"""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from eneo.integration.domain.entities.sharepoint_subscription import (
    SharePointSubscription,
)
from eneo.integration.infrastructure.auth_service.org_token_provider import (
    OrgTokenProvider,
)
from eneo.integration.infrastructure.sharepoint_subscription_worker import (
    SHAREPOINT_SYNC_STALE_TIMEOUT_MINUTES,
    SHAREPOINT_SYNC_TASKS,
    cleanup_orphaned_subscriptions,
    fail_stale_sharepoint_sync_jobs,
    get_token_for_subscription,
    record_failed_attempt,
    renew_expiring_subscriptions,
)


@asynccontextmanager
async def mock_session_context():
    """Mock async context manager for sessionmanager.session()."""
    mock_session = AsyncMock()
    mock_session.begin = MagicMock(
        return_value=AsyncMock(__aenter__=AsyncMock(), __aexit__=AsyncMock())
    )
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
    container.org_token_provider = MagicMock(
        side_effect=lambda: OrgTokenProvider(
            tenant_app_repo=container.tenant_sharepoint_app_repo(),
            tenant_app_auth_service=container.tenant_app_auth_service(),
            service_account_auth_service=container.service_account_auth_service(),
        )
    )

    # Mock session — begin/begin_nested return async context managers
    mock_session = AsyncMock()
    mock_session.begin = MagicMock(return_value=AsyncMock())
    mock_session.begin_nested = MagicMock(return_value=AsyncMock())
    container.session = MagicMock(return_value=mock_session)

    return container


class TestGetTokenForSubscription:
    """Tests for get_token_for_subscription helper function."""

    @pytest.mark.asyncio
    async def test_returns_oauth_token_for_user_oauth_auth(
        self, mock_subscription, mock_container
    ):
        """Test that OAuth token is returned for user_oauth auth type."""
        # Setup user integration with user_oauth auth
        user_integration = MagicMock()
        user_integration.auth_type = "user_oauth"
        user_integration.tenant_app_id = None

        mock_container.user_integration_repo().one = AsyncMock(
            return_value=user_integration
        )

        # Setup OAuth token
        oauth_token = MagicMock()
        oauth_token.token_type.is_sharepoint = True
        oauth_token.id = uuid4()
        oauth_token.access_token = "oauth-access-token"

        mock_container.oauth_token_service().get_oauth_token_by_user_integration = (
            AsyncMock(return_value=oauth_token)
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
    async def test_returns_tenant_app_token_for_tenant_app_auth(
        self, mock_subscription, mock_container
    ):
        """Test that tenant app token is returned for tenant_app auth type."""
        tenant_app_id = uuid4()

        # Setup user integration with tenant_app auth
        user_integration = MagicMock()
        user_integration.auth_type = "tenant_app"
        user_integration.tenant_app_id = tenant_app_id

        mock_container.user_integration_repo().one = AsyncMock(
            return_value=user_integration
        )

        # Setup tenant app (not service account)
        tenant_app = MagicMock()
        tenant_app.is_service_account = MagicMock(return_value=False)

        mock_container.tenant_sharepoint_app_repo().one = AsyncMock(
            return_value=tenant_app
        )
        mock_container.tenant_app_auth_service().get_access_token = AsyncMock(
            return_value="tenant-app-access-token"
        )

        # Execute
        token = await get_token_for_subscription(mock_subscription, mock_container)

        # Verify
        assert token is not None
        assert token.access_token == "tenant-app-access-token"
        mock_container.tenant_app_auth_service().get_access_token.assert_called_once_with(
            tenant_app, force_refresh=False
        )

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

        mock_container.user_integration_repo().one = AsyncMock(
            return_value=user_integration
        )

        # Setup tenant app (is service account)
        tenant_app = MagicMock()
        tenant_app.is_service_account = MagicMock(return_value=True)
        tenant_app.service_account_refresh_token = "old-refresh-token"

        mock_container.tenant_sharepoint_app_repo().one = AsyncMock(
            return_value=tenant_app
        )
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
            tenant_app, force_refresh=False
        )
        tenant_app.update_refresh_token.assert_called_once_with("new-refresh-token")
        mock_container.tenant_sharepoint_app_repo().update.assert_called_once_with(
            tenant_app
        )

    @pytest.mark.asyncio
    async def test_returns_none_when_no_oauth_token_found(
        self, mock_subscription, mock_container
    ):
        """Test that None is returned when no OAuth token exists."""
        user_integration = MagicMock()
        user_integration.auth_type = "user_oauth"

        mock_container.user_integration_repo().one = AsyncMock(
            return_value=user_integration
        )
        mock_container.oauth_token_service().get_oauth_token_by_user_integration = (
            AsyncMock(return_value=None)
        )

        token = await get_token_for_subscription(mock_subscription, mock_container)

        assert token is None

    @pytest.mark.asyncio
    async def test_returns_none_when_tenant_app_id_missing(
        self, mock_subscription, mock_container
    ):
        """Test that None is returned when tenant_app auth but no tenant_app_id."""
        user_integration = MagicMock()
        user_integration.auth_type = "tenant_app"
        user_integration.tenant_app_id = None

        mock_container.user_integration_repo().one = AsyncMock(
            return_value=user_integration
        )

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
        mock_container.sharepoint_subscription_repo().count_references = AsyncMock(
            return_value=1
        )

        # Patch sessionmanager and worker._create_container
        with patch(
            "eneo.integration.infrastructure.sharepoint_subscription_worker.worker._create_container",
            new_callable=AsyncMock,
            return_value=mock_container,
        ):
            with patch(
                "eneo.worker.worker.sessionmanager.session",
                return_value=mock_session_context(),
            ):
                result = await cleanup_orphaned_subscriptions({})

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
        mock_container.sharepoint_subscription_repo().count_references = AsyncMock(
            return_value=0
        )

        # Setup user integration with tenant app
        user_integration = MagicMock()
        user_integration.auth_type = "tenant_app"
        user_integration.tenant_app_id = uuid4()
        mock_container.user_integration_repo().one = AsyncMock(
            return_value=user_integration
        )

        # Setup tenant app
        tenant_app = MagicMock()
        tenant_app.is_service_account = MagicMock(return_value=False)
        mock_container.tenant_sharepoint_app_repo().one = AsyncMock(
            return_value=tenant_app
        )
        mock_container.tenant_app_auth_service().get_access_token = AsyncMock(
            return_value="access-token"
        )

        # Setup delete success
        mock_container.sharepoint_subscription_service().delete_subscription_if_unused = AsyncMock(
            return_value=True
        )

        # Patch sessionmanager and worker._create_container
        with patch(
            "eneo.integration.infrastructure.sharepoint_subscription_worker.worker._create_container",
            new_callable=AsyncMock,
            return_value=mock_container,
        ):
            with patch(
                "eneo.worker.worker.sessionmanager.session",
                return_value=mock_session_context(),
            ):
                result = await cleanup_orphaned_subscriptions({})

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
            expires_at=datetime.now(timezone.utc)
            + timedelta(hours=24),  # Expiring soon
        )

        # Setup subscription service
        mock_container.sharepoint_subscription_service().list_expiring_subscriptions = (
            AsyncMock(return_value=[subscription])
        )

        # Setup user integration with tenant app
        user_integration = MagicMock()
        user_integration.auth_type = "tenant_app"
        user_integration.tenant_app_id = uuid4()
        mock_container.user_integration_repo().one = AsyncMock(
            return_value=user_integration
        )

        # Setup tenant app
        tenant_app = MagicMock()
        tenant_app.is_service_account = MagicMock(return_value=False)
        mock_container.tenant_sharepoint_app_repo().one = AsyncMock(
            return_value=tenant_app
        )
        mock_container.tenant_app_auth_service().get_access_token = AsyncMock(
            return_value="access-token"
        )

        # Setup renewal success
        mock_container.sharepoint_subscription_service().renew_subscription = AsyncMock(
            return_value=True
        )
        mock_container.sharepoint_subscription_repo().link_unreferenced_knowledge = (
            AsyncMock(return_value=2)
        )

        # Patch sessionmanager and worker._create_container
        with patch(
            "eneo.integration.infrastructure.sharepoint_subscription_worker.worker._create_container",
            new_callable=AsyncMock,
            return_value=mock_container,
        ):
            with patch(
                "eneo.worker.worker.sessionmanager.session",
                return_value=mock_session_context(),
            ):
                result = await renew_expiring_subscriptions({})

        assert result["renewed"] == 1
        assert result["failed"] == 0
        mock_container.sharepoint_subscription_service().renew_subscription.assert_called_once()
        mock_container.sharepoint_subscription_repo().link_unreferenced_knowledge.assert_awaited_once_with(
            subscription
        )

    @pytest.mark.asyncio
    async def test_returns_early_when_no_expiring_subscriptions(self, mock_container):
        """Test that job returns early when no subscriptions need renewal."""
        mock_container.sharepoint_subscription_service().list_expiring_subscriptions = (
            AsyncMock(return_value=[])
        )

        # Patch sessionmanager and worker._create_container
        with patch(
            "eneo.integration.infrastructure.sharepoint_subscription_worker.worker._create_container",
            new_callable=AsyncMock,
            return_value=mock_container,
        ):
            with patch(
                "eneo.worker.worker.sessionmanager.session",
                return_value=mock_session_context(),
            ):
                result = await renew_expiring_subscriptions({})

        assert result["renewed"] == 0
        assert result["failed"] == 0

    @pytest.mark.asyncio
    async def test_records_failure_when_token_cannot_be_resolved(self, mock_container):
        """Token resolution failures are persisted on the subscription."""
        subscription = SharePointSubscription(
            id=uuid4(),
            user_integration_id=uuid4(),
            site_id="site-123,web-123,list-123",
            subscription_id="sub-123",
            drive_id="drive-123",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )

        mock_container.sharepoint_subscription_service().list_expiring_subscriptions = (
            AsyncMock(return_value=[subscription])
        )

        user_integration = MagicMock()
        user_integration.auth_type = "tenant_app"
        user_integration.tenant_app_id = None
        mock_container.user_integration_repo().one = AsyncMock(
            return_value=user_integration
        )
        mock_container.sharepoint_subscription_repo().update = AsyncMock(
            return_value=subscription
        )

        with patch(
            "eneo.integration.infrastructure.sharepoint_subscription_worker.worker._create_container",
            new_callable=AsyncMock,
            return_value=mock_container,
        ):
            with patch(
                "eneo.worker.worker.sessionmanager.session",
                return_value=mock_session_context(),
            ):
                result = await renew_expiring_subscriptions({})

        assert result["renewed"] == 0
        assert result["failed"] == 1
        assert subscription.consecutive_renewal_failures == 1
        assert subscription.last_renewal_failed_at is not None
        assert "Could not get token" in (subscription.last_renewal_error or "")
        mock_container.sharepoint_subscription_repo().update.assert_called_once_with(
            subscription
        )

    @pytest.mark.asyncio
    async def test_records_failure_when_renewal_returns_false(self, mock_container):
        """Graph renewal failures are persisted on the subscription."""
        subscription = SharePointSubscription(
            id=uuid4(),
            user_integration_id=uuid4(),
            site_id="site-123,web-123,list-123",
            subscription_id="sub-123",
            drive_id="drive-123",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )

        mock_container.sharepoint_subscription_service().list_expiring_subscriptions = (
            AsyncMock(return_value=[subscription])
        )

        user_integration = MagicMock()
        user_integration.auth_type = "tenant_app"
        user_integration.tenant_app_id = uuid4()
        mock_container.user_integration_repo().one = AsyncMock(
            return_value=user_integration
        )

        tenant_app = MagicMock()
        tenant_app.is_service_account = MagicMock(return_value=False)
        mock_container.tenant_sharepoint_app_repo().one = AsyncMock(
            return_value=tenant_app
        )
        mock_container.tenant_app_auth_service().get_access_token = AsyncMock(
            return_value="access-token"
        )
        mock_container.sharepoint_subscription_service().renew_subscription = AsyncMock(
            return_value=False
        )
        mock_container.sharepoint_subscription_repo().update = AsyncMock(
            return_value=subscription
        )

        with patch(
            "eneo.integration.infrastructure.sharepoint_subscription_worker.worker._create_container",
            new_callable=AsyncMock,
            return_value=mock_container,
        ):
            with patch(
                "eneo.worker.worker.sessionmanager.session",
                return_value=mock_session_context(),
            ):
                result = await renew_expiring_subscriptions({})

        assert result["renewed"] == 0
        assert result["failed"] == 1
        assert subscription.consecutive_renewal_failures == 1
        assert subscription.last_renewal_failed_at is not None
        assert "Renewal returned false" in (subscription.last_renewal_error or "")
        mock_container.sharepoint_subscription_repo().update.assert_called_once_with(
            subscription
        )
        mock_container.sharepoint_subscription_repo().link_unreferenced_knowledge.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_recorded_renewal_errors_carry_no_internal_text(self, mock_container):
        """The admin page shows last_renewal_error; URLs and tokens stay out of it."""
        subscription = SharePointSubscription(
            id=uuid4(),
            user_integration_id=uuid4(),
            site_id="site-123,web-123,list-123",
            subscription_id="sub-123",
            drive_id="drive-123",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )
        mock_container.sharepoint_subscription_service().list_expiring_subscriptions = (
            AsyncMock(return_value=[subscription])
        )
        user_integration = MagicMock()
        user_integration.auth_type = "tenant_app"
        user_integration.tenant_app_id = uuid4()
        mock_container.user_integration_repo().one = AsyncMock(
            return_value=user_integration
        )
        tenant_app = MagicMock()
        tenant_app.is_service_account = MagicMock(return_value=False)
        mock_container.tenant_sharepoint_app_repo().one = AsyncMock(
            return_value=tenant_app
        )
        mock_container.tenant_app_auth_service().get_access_token = AsyncMock(
            return_value="access-token"
        )
        mock_container.sharepoint_subscription_service().renew_subscription = AsyncMock(
            side_effect=RuntimeError(
                "PATCH https://graph.microsoft.com/v1.0/subscriptions/x?token=abc"
            )
        )
        mock_container.sharepoint_subscription_repo().update = AsyncMock(
            return_value=subscription
        )

        with patch(
            "eneo.integration.infrastructure.sharepoint_subscription_worker.worker._create_container",
            new_callable=AsyncMock,
            return_value=mock_container,
        ):
            with patch(
                "eneo.worker.worker.sessionmanager.session",
                return_value=mock_session_context(),
            ):
                result = await renew_expiring_subscriptions({})

        assert result["failed"] == 1
        assert subscription.last_renewal_error is not None
        assert "token=abc" not in subscription.last_renewal_error
        assert (
            "graph.microsoft.com/v1.0/subscriptions/x"
            in subscription.last_renewal_error
        )

    @pytest.mark.asyncio
    async def test_records_a_renewal_error_without_urls_or_hosts(self, mock_container):
        """The stored failure is the user-visible text: no link query, no host."""
        subscription = SharePointSubscription(
            id=uuid4(),
            user_integration_id=uuid4(),
            site_id="site-123,web-123,list-123",
            subscription_id="sub-123",
            drive_id="drive-123",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )
        mock_container.sharepoint_subscription_service().list_expiring_subscriptions = (
            AsyncMock(return_value=[subscription])
        )
        user_integration = MagicMock()
        user_integration.auth_type = "tenant_app"
        user_integration.tenant_app_id = uuid4()
        mock_container.user_integration_repo().one = AsyncMock(
            return_value=user_integration
        )
        tenant_app = MagicMock()
        tenant_app.is_service_account = MagicMock(return_value=False)
        mock_container.tenant_sharepoint_app_repo().one = AsyncMock(
            return_value=tenant_app
        )
        mock_container.tenant_app_auth_service().get_access_token = AsyncMock(
            return_value="access-token"
        )
        mock_container.sharepoint_subscription_service().renew_subscription = AsyncMock(
            side_effect=RuntimeError(
                "Renewal failed at https://kommun.sharepoint.com/_layouts/15/download.aspx"
                "?UniqueId=abc&tempauth=SECRET-TOKEN; Error 111 connecting to"
                " redis.internal:6379. Connection refused."
            )
        )
        mock_container.sharepoint_subscription_repo().update = AsyncMock(
            return_value=subscription
        )

        with patch(
            "eneo.integration.infrastructure.sharepoint_subscription_worker.worker._create_container",
            new_callable=AsyncMock,
            return_value=mock_container,
        ):
            with patch(
                "eneo.worker.worker.sessionmanager.session",
                return_value=mock_session_context(),
            ):
                result = await renew_expiring_subscriptions({})

        assert result["failed"] == 1
        stored = subscription.last_renewal_error or ""
        assert "Renewal failed" in stored
        assert "SECRET-TOKEN" not in stored
        assert "tempauth" not in stored
        assert "redis.internal" not in stored

    @pytest.mark.asyncio
    async def test_a_failure_the_service_recorded_is_persisted_once(
        self, mock_container
    ):
        """The savepoint rolls the service's write back; it is rewritten, not recounted."""
        subscription = SharePointSubscription(
            id=uuid4(),
            user_integration_id=uuid4(),
            site_id="site-123,web-123,list-123",
            subscription_id="sub-123",
            drive_id="drive-123",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )
        mock_container.sharepoint_subscription_service().list_expiring_subscriptions = (
            AsyncMock(return_value=[subscription])
        )
        user_integration = MagicMock()
        user_integration.auth_type = "tenant_app"
        user_integration.tenant_app_id = uuid4()
        mock_container.user_integration_repo().one = AsyncMock(
            return_value=user_integration
        )
        tenant_app = MagicMock()
        tenant_app.is_service_account = MagicMock(return_value=False)
        mock_container.tenant_sharepoint_app_repo().one = AsyncMock(
            return_value=tenant_app
        )
        mock_container.tenant_app_auth_service().get_access_token = AsyncMock(
            return_value="access-token"
        )

        async def recreation_fails(subscription, token):
            subscription.mark_renewal_failure("Graph refused the replacement")
            return False

        mock_container.sharepoint_subscription_service().renew_subscription = AsyncMock(
            side_effect=recreation_fails
        )
        mock_container.sharepoint_subscription_repo().update = AsyncMock(
            return_value=subscription
        )

        with patch(
            "eneo.integration.infrastructure.sharepoint_subscription_worker.worker._create_container",
            new_callable=AsyncMock,
            return_value=mock_container,
        ):
            with patch(
                "eneo.worker.worker.sessionmanager.session",
                return_value=mock_session_context(),
            ):
                result = await renew_expiring_subscriptions({})

        assert result["failed"] == 1
        assert subscription.consecutive_renewal_failures == 1
        assert subscription.last_renewal_error == "Graph refused the replacement"
        mock_container.sharepoint_subscription_repo().update.assert_awaited_once_with(
            subscription
        )

    @pytest.mark.asyncio
    async def test_refreshes_token_before_renewal_savepoint(self, mock_container):
        """Rotated refresh tokens must not roll back with Graph renewal failures."""
        events: list[str] = []

        @asynccontextmanager
        async def recording_nested():
            events.append("begin_nested")
            try:
                yield
            finally:
                events.append("end_nested")

        subscription = SharePointSubscription(
            id=uuid4(),
            user_integration_id=uuid4(),
            site_id="site-123,web-123,list-123",
            subscription_id="sub-123",
            drive_id="drive-123",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )

        mock_container.session().begin_nested = MagicMock(
            side_effect=lambda: recording_nested()
        )
        mock_container.sharepoint_subscription_service().list_expiring_subscriptions = (
            AsyncMock(return_value=[subscription])
        )

        user_integration = MagicMock()
        user_integration.auth_type = "user_oauth"
        user_integration.tenant_app_id = None
        mock_container.user_integration_repo().one = AsyncMock(
            return_value=user_integration
        )

        oauth_token = MagicMock()
        oauth_token.id = uuid4()
        oauth_token.access_token = "rotated-access-token"
        oauth_token.token_type.is_sharepoint = True
        mock_container.oauth_token_service().get_oauth_token_by_user_integration = (
            AsyncMock(return_value=oauth_token)
        )

        async def refresh_token(*, token_id):
            events.append("refresh_token")
            return oauth_token

        async def renew_subscription(*, subscription, token):
            events.append("renew_subscription")
            return False

        mock_container.oauth_token_service().refresh_and_update_token = AsyncMock(
            side_effect=refresh_token
        )
        mock_container.sharepoint_subscription_service().renew_subscription = AsyncMock(
            side_effect=renew_subscription
        )
        mock_container.sharepoint_subscription_repo().update = AsyncMock(
            return_value=subscription
        )

        with patch(
            "eneo.integration.infrastructure.sharepoint_subscription_worker.worker._create_container",
            new_callable=AsyncMock,
            return_value=mock_container,
        ):
            with patch(
                "eneo.worker.worker.sessionmanager.session",
                return_value=mock_session_context(),
            ):
                result = await renew_expiring_subscriptions({})

        assert result["renewed"] == 0
        assert result["failed"] == 1
        assert events.index("refresh_token") < events.index("begin_nested")
        assert events.index("begin_nested") < events.index("renew_subscription")


class TestFailStaleSharePointSyncJobs:
    """Tests for the stuck-job sweeper cron."""

    @pytest.mark.asyncio
    async def test_marks_stale_jobs_failed(self, mock_container):
        failed_ids = [uuid4(), uuid4()]
        job_repo = AsyncMock()
        job_repo.mark_stale_jobs_failed = AsyncMock(return_value=failed_ids)
        mock_container.job_repo = MagicMock(return_value=job_repo)

        with patch(
            "eneo.integration.infrastructure.sharepoint_subscription_worker.worker._create_container",
            new_callable=AsyncMock,
            return_value=mock_container,
        ):
            with patch(
                "eneo.worker.worker.sessionmanager.session",
                return_value=mock_session_context(),
            ):
                result = await fail_stale_sharepoint_sync_jobs({})

        assert result["failed_stale_jobs"] == 2
        call = job_repo.mark_stale_jobs_failed.await_args
        assert call.kwargs["tasks"] == SHAREPOINT_SYNC_TASKS
        # stale_before must be in the past by roughly the configured timeout
        stale_before = call.kwargs["stale_before"]
        delta_minutes = (datetime.now(timezone.utc) - stale_before).total_seconds() / 60
        assert (
            SHAREPOINT_SYNC_STALE_TIMEOUT_MINUTES - 5
            <= delta_minutes
            <= SHAREPOINT_SYNC_STALE_TIMEOUT_MINUTES + 5
        )

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_stale_jobs(self, mock_container):
        job_repo = AsyncMock()
        job_repo.mark_stale_jobs_failed = AsyncMock(return_value=[])
        mock_container.job_repo = MagicMock(return_value=job_repo)

        with patch(
            "eneo.integration.infrastructure.sharepoint_subscription_worker.worker._create_container",
            new_callable=AsyncMock,
            return_value=mock_container,
        ):
            with patch(
                "eneo.worker.worker.sessionmanager.session",
                return_value=mock_session_context(),
            ):
                result = await fail_stale_sharepoint_sync_jobs({})

        assert result["failed_stale_jobs"] == 0


class TestRecordFailedAttempt:
    """The failure write a renewal and a lifecycle event share."""

    async def test_a_failure_is_counted_with_its_visible_reason(
        self, mock_container, mock_subscription
    ):
        await record_failed_attempt(
            mock_subscription,
            mock_container,
            RuntimeError("Renewal failed for https://graph.microsoft.com/x?token=1"),
            failures_before=0,
        )

        assert mock_subscription.consecutive_renewal_failures == 1
        assert "Renewal failed" in (mock_subscription.last_renewal_error or "")
        assert "token=1" not in (mock_subscription.last_renewal_error or "")
        mock_container.sharepoint_subscription_repo().update.assert_awaited_once_with(
            mock_subscription
        )

    async def test_a_failure_the_service_counted_is_written_not_recounted(
        self, mock_container, mock_subscription
    ):
        mock_subscription.mark_renewal_failure("Graph refused the replacement")

        await record_failed_attempt(
            mock_subscription,
            mock_container,
            RuntimeError("Microsoft Graph refused"),
            failures_before=0,
        )

        assert mock_subscription.consecutive_renewal_failures == 1
        assert mock_subscription.last_renewal_error == "Graph refused the replacement"
        mock_container.sharepoint_subscription_repo().update.assert_awaited_once_with(
            mock_subscription
        )


class TestLifecycleMaintenance:
    """Graph calls a lifecycle event asks for, run after the acknowledgement."""

    @staticmethod
    def _setup(mock_container, mock_subscription, *, token=True):
        from eneo.integration.infrastructure import sharepoint_subscription_worker

        repo = mock_container.sharepoint_subscription_repo()
        repo.one_or_none = AsyncMock(return_value=mock_subscription)
        service = mock_container.sharepoint_subscription_service()
        webhooks = MagicMock()
        webhooks.queue_syncs_for_subscription = AsyncMock(return_value=2)
        mock_container.sharepoint_webhook_service = MagicMock(return_value=webhooks)
        get_token = AsyncMock(return_value=MagicMock() if token else None)
        return sharepoint_subscription_worker, service, webhooks, get_token, repo

    async def test_reauthorization_renews_the_subscription(
        self, mock_container, mock_subscription
    ):
        worker_module, service, webhooks, get_token, _ = self._setup(
            mock_container, mock_subscription
        )
        service.renew_subscription = AsyncMock(return_value=True)

        with patch.object(worker_module, "get_token_for_subscription", get_token):
            await worker_module._maintain_subscription(  # pyright: ignore[reportPrivateUsage]
                mock_container,
                worker_module.SubscriptionMaintenance(
                    mock_subscription.id, "reauthorizationRequired"
                ),
            )

        service.renew_subscription.assert_awaited_once()
        webhooks.queue_syncs_for_subscription.assert_not_called()

    async def test_a_removed_subscription_is_recreated_and_its_sources_synced(
        self, mock_container, mock_subscription
    ):
        worker_module, service, webhooks, get_token, _ = self._setup(
            mock_container, mock_subscription
        )
        service.recreate_expired_subscription = AsyncMock(return_value=True)

        with patch.object(worker_module, "get_token_for_subscription", get_token):
            await worker_module._maintain_subscription(  # pyright: ignore[reportPrivateUsage]
                mock_container,
                worker_module.SubscriptionMaintenance(
                    mock_subscription.id, "subscriptionRemoved"
                ),
            )

        service.recreate_expired_subscription.assert_awaited_once()
        assert (
            service.recreate_expired_subscription.await_args.kwargs["is_onedrive"]
            is False
        )
        webhooks.queue_syncs_for_subscription.assert_awaited_once_with(
            mock_subscription
        )

    async def test_a_refused_recreation_is_recorded_and_syncs_nothing(
        self, mock_container, mock_subscription
    ):
        worker_module, service, webhooks, get_token, repo = self._setup(
            mock_container, mock_subscription
        )
        service.recreate_expired_subscription = AsyncMock(return_value=False)

        with patch.object(worker_module, "get_token_for_subscription", get_token):
            await worker_module._maintain_subscription(  # pyright: ignore[reportPrivateUsage]
                mock_container,
                worker_module.SubscriptionMaintenance(
                    mock_subscription.id, "subscriptionRemoved"
                ),
            )

        webhooks.queue_syncs_for_subscription.assert_not_called()
        assert mock_subscription.consecutive_renewal_failures == 1
        repo.update.assert_awaited_with(mock_subscription)

    async def test_without_a_token_the_failure_is_recorded(
        self, mock_container, mock_subscription
    ):
        worker_module, service, _, get_token, repo = self._setup(
            mock_container, mock_subscription, token=False
        )
        service.renew_subscription = AsyncMock()

        with patch.object(worker_module, "get_token_for_subscription", get_token):
            await worker_module._maintain_subscription(  # pyright: ignore[reportPrivateUsage]
                mock_container,
                worker_module.SubscriptionMaintenance(
                    mock_subscription.id, "reauthorizationRequired"
                ),
            )

        service.renew_subscription.assert_not_called()
        assert mock_subscription.consecutive_renewal_failures == 1
        assert "reauthorize" in (mock_subscription.last_renewal_error or "")
        repo.update.assert_awaited_with(mock_subscription)

    @pytest.mark.parametrize(("failures_before", "synced"), [(0, False), (2, True)])
    async def test_a_reauthorization_after_a_failure_syncs_what_the_pause_missed(
        self, mock_container, mock_subscription, failures_before, synced
    ):
        """Graph pauses delivery until a subscription is reauthorized."""
        mock_subscription.consecutive_renewal_failures = failures_before
        worker_module, service, webhooks, get_token, _ = self._setup(
            mock_container, mock_subscription
        )

        async def renew(subscription, token):
            subscription.mark_renewal_success()
            return True

        service.renew_subscription = AsyncMock(side_effect=renew)

        with patch.object(worker_module, "get_token_for_subscription", get_token):
            await worker_module._maintain_subscription(  # pyright: ignore[reportPrivateUsage]
                mock_container,
                worker_module.SubscriptionMaintenance(
                    mock_subscription.id, "reauthorizationRequired"
                ),
            )

        assert webhooks.queue_syncs_for_subscription.await_count == int(synced)

    async def test_a_refused_reauthorization_is_recorded_like_a_renewal(
        self, mock_container, mock_subscription
    ):
        worker_module, service, webhooks, get_token, repo = self._setup(
            mock_container, mock_subscription
        )
        service.renew_subscription = AsyncMock(return_value=False)

        with patch.object(worker_module, "get_token_for_subscription", get_token):
            await worker_module._maintain_subscription(  # pyright: ignore[reportPrivateUsage]
                mock_container,
                worker_module.SubscriptionMaintenance(
                    mock_subscription.id, "reauthorizationRequired"
                ),
            )

        assert mock_subscription.consecutive_renewal_failures == 1
        assert "reauthorize" in (mock_subscription.last_renewal_error or "")
        repo.update.assert_awaited_with(mock_subscription)
        webhooks.queue_syncs_for_subscription.assert_not_called()


class TestRenewalTransactions:
    """Each renewal is committed on its own; a recovery syncs what it missed."""

    @staticmethod
    def _subscription(failures: int = 0) -> SharePointSubscription:
        subscription = SharePointSubscription(
            id=uuid4(),
            user_integration_id=uuid4(),
            site_id="site-1",
            subscription_id=f"sub-{uuid4()}",
            drive_id="drive-1",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )
        subscription.consecutive_renewal_failures = failures
        return subscription

    @staticmethod
    def _transactions(mock_container) -> list[str]:
        events: list[str] = []

        class Transaction:
            async def __aenter__(self):
                events.append("begin")
                return self

            async def __aexit__(self, exc_type, *_):
                events.append("rollback" if exc_type else "commit")
                return False

        mock_container.session().begin = MagicMock(side_effect=Transaction)
        return events

    async def _run(self, mock_container, subscriptions, renew):
        from eneo.integration.infrastructure import sharepoint_subscription_worker

        service = mock_container.sharepoint_subscription_service()
        service.list_expiring_subscriptions = AsyncMock(return_value=subscriptions)
        service.renew_subscription = AsyncMock(side_effect=renew)
        mock_container.sharepoint_subscription_repo().link_unreferenced_knowledge = (
            AsyncMock(return_value=0)
        )
        webhooks = MagicMock()
        webhooks.queue_syncs_for_subscription = AsyncMock(return_value=1)
        mock_container.sharepoint_webhook_service = MagicMock(return_value=webhooks)
        with (
            patch.object(
                sharepoint_subscription_worker,
                "get_token_for_subscription",
                AsyncMock(return_value=MagicMock()),
            ),
            patch(
                "eneo.integration.infrastructure.sharepoint_subscription_worker.worker._create_container",
                new_callable=AsyncMock,
                return_value=mock_container,
            ),
            patch(
                "eneo.worker.worker.sessionmanager.session",
                return_value=mock_session_context(),
            ),
        ):
            result = await renew_expiring_subscriptions({})
        return result, webhooks

    async def test_each_renewal_commits_before_the_next_starts(self, mock_container):
        events = self._transactions(mock_container)
        renewed: list[list[str]] = []

        async def renew(subscription, token):
            renewed.append(list(events))
            return True

        result, _ = await self._run(
            mock_container, [self._subscription(), self._subscription()], renew
        )

        assert result == {"renewed": 2, "failed": 0}
        # The listing, then one transaction per subscription.
        assert events == ["begin", "commit"] * 3
        assert renewed == [
            ["begin", "commit", "begin"],
            ["begin", "commit"] * 2 + ["begin"],
        ]

    async def test_a_renewal_whose_commit_fails_does_not_stop_the_next(
        self, mock_container
    ):
        first, second = self._subscription(), self._subscription()
        commits = 0

        class Transaction:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, *_):
                nonlocal commits
                commits += 1
                if commits == 2:
                    raise RuntimeError("commit refused")
                return False

        mock_container.session().begin = MagicMock(side_effect=Transaction)

        async def renew(subscription, token):
            return True

        result, _ = await self._run(mock_container, [first, second], renew)

        assert result == {"renewed": 1, "failed": 1}

    @pytest.mark.parametrize(("failures", "synced"), [(0, 0), (3, 1)])
    async def test_a_renewal_after_failures_syncs_what_was_missed(
        self, mock_container, failures, synced
    ):
        self._transactions(mock_container)

        async def renew(subscription, token):
            subscription.mark_renewal_success()
            return True

        _, webhooks = await self._run(
            mock_container, [self._subscription(failures)], renew
        )

        assert webhooks.queue_syncs_for_subscription.await_count == synced
