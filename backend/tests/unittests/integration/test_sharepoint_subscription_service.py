"""Unit tests for SharePointSubscriptionService - webhook subscription management.

Tests the subscription creation, renewal, recreation, and deletion logic
for Microsoft Graph webhook subscriptions.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from intric.integration.domain.entities.sharepoint_subscription import SharePointSubscription
from intric.integration.infrastructure.sharepoint_subscription_service import (
    SharePointSubscriptionService,
)


@pytest.fixture
def mock_subscription_repo():
    """Create a mock SharePoint subscription repository."""
    repo = AsyncMock()
    repo.get_by_user_and_site = AsyncMock(return_value=None)
    repo.add = AsyncMock()
    repo.update = AsyncMock()
    repo.remove = AsyncMock()
    repo.get = AsyncMock()
    repo.count_references = AsyncMock(return_value=0)
    repo.list_expiring_before = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def mock_oauth_token_service():
    """Create a mock OAuth token service."""
    return AsyncMock()


@pytest.fixture
def mock_token():
    """Create a mock SharePoint token."""
    token = MagicMock()
    token.access_token = "mock-access-token-123"
    token.base_url = "https://graph.microsoft.com"
    return token


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
def expired_subscription():
    """Create an expired SharePoint subscription."""
    return SharePointSubscription(
        id=uuid4(),
        user_integration_id=uuid4(),
        site_id="site-id-123,web-id-456,list-id-789",
        subscription_id="expired-subscription-id",
        drive_id="drive-id-xyz",
        expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )


@pytest.fixture
def service(mock_subscription_repo, mock_oauth_token_service):
    """Create SharePointSubscriptionService with mocked dependencies."""
    with patch("intric.integration.infrastructure.sharepoint_subscription_service.get_settings") as mock_settings:
        settings = MagicMock()
        settings.sharepoint_webhook_notification_url = "https://example.com/webhook/"
        settings.sharepoint_webhook_client_state = "test-client-state"
        settings.public_origin = "https://example.com"
        mock_settings.return_value = settings

        return SharePointSubscriptionService(
            sharepoint_subscription_repo=mock_subscription_repo,
            oauth_token_service=mock_oauth_token_service,
        )


class TestEnsureSubscriptionForSite:
    """Tests for ensure_subscription_for_site method."""

    async def test_returns_existing_subscription_if_valid(
        self, service, mock_subscription_repo, mock_subscription, mock_token
    ):
        """Returns existing subscription if it hasn't expired."""
        mock_subscription_repo.get_by_user_and_site.return_value = mock_subscription

        result = await service.ensure_subscription_for_site(
            user_integration_id=mock_subscription.user_integration_id,
            site_id=mock_subscription.site_id,
            token=mock_token,
        )

        assert result == mock_subscription
        mock_subscription_repo.add.assert_not_called()

    async def test_creates_new_subscription_if_none_exists(
        self, service, mock_subscription_repo, mock_token
    ):
        """Creates new subscription when none exists for user+site."""
        user_integration_id = uuid4()
        site_id = "new-site-id-123"

        mock_subscription_repo.get_by_user_and_site.return_value = None
        mock_subscription_repo.add.return_value = MagicMock(id=uuid4())

        # Mock Graph API calls
        with patch.object(service, "_resolve_drive_id", return_value="resolved-drive-id"):
            with patch.object(service, "_create_graph_subscription", return_value="new-graph-sub-id"):
                result = await service.ensure_subscription_for_site(
                    user_integration_id=user_integration_id,
                    site_id=site_id,
                    token=mock_token,
                )

        assert result is not None
        mock_subscription_repo.add.assert_called_once()

    async def test_recreates_expired_subscription(
        self, service, mock_subscription_repo, expired_subscription, mock_token
    ):
        """Recreates subscription if existing one has expired."""
        mock_subscription_repo.get_by_user_and_site.return_value = expired_subscription

        with patch.object(service, "recreate_expired_subscription", return_value=True) as mock_recreate:
            result = await service.ensure_subscription_for_site(
                user_integration_id=expired_subscription.user_integration_id,
                site_id=expired_subscription.site_id,
                token=mock_token,
            )

        mock_recreate.assert_called_once()
        assert result == expired_subscription

    async def test_returns_none_if_notification_url_not_configured(
        self, mock_subscription_repo, mock_oauth_token_service, mock_token
    ):
        """Returns None if webhook notification URL is not configured."""
        with patch("intric.integration.infrastructure.sharepoint_subscription_service.get_settings") as mock_settings:
            settings = MagicMock()
            settings.sharepoint_webhook_notification_url = None
            settings.public_origin = None
            mock_settings.return_value = settings

            svc = SharePointSubscriptionService(
                sharepoint_subscription_repo=mock_subscription_repo,
                oauth_token_service=mock_oauth_token_service,
            )

            result = await svc.ensure_subscription_for_site(
                user_integration_id=uuid4(),
                site_id="site-id",
                token=mock_token,
            )

        assert result is None

    async def test_onedrive_uses_site_id_as_drive_id(
        self, service, mock_subscription_repo, mock_token
    ):
        """For OneDrive, site_id is used directly as drive_id."""
        user_integration_id = uuid4()
        onedrive_drive_id = "onedrive-drive-id-123"

        mock_subscription_repo.get_by_user_and_site.return_value = None
        mock_subscription_repo.add.return_value = MagicMock(id=uuid4())

        with patch.object(service, "_create_graph_subscription", return_value="new-sub-id") as mock_create:
            await service.ensure_subscription_for_site(
                user_integration_id=user_integration_id,
                site_id=onedrive_drive_id,
                token=mock_token,
                is_onedrive=True,
            )

        # For OneDrive, _resolve_drive_id should NOT be called
        mock_create.assert_called_once()
        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs["drive_id"] == onedrive_drive_id
        assert call_kwargs["site_id"] is None  # OneDrive doesn't use site_id


class TestRecreateExpiredSubscription:
    """Tests for recreate_expired_subscription method."""

    async def test_recreate_success(
        self, service, mock_subscription_repo, expired_subscription, mock_token
    ):
        """Successfully recreates an expired subscription."""
        with patch.object(service, "_delete_graph_subscription", return_value=True):
            with patch.object(service, "_create_graph_subscription", return_value="new-subscription-id"):
                result = await service.recreate_expired_subscription(
                    subscription=expired_subscription,
                    token=mock_token,
                )

        assert result is True
        mock_subscription_repo.update.assert_called_once()

        # Verify subscription was updated with new ID and expiration
        updated_sub = mock_subscription_repo.update.call_args[0][0]
        assert updated_sub.subscription_id == "new-subscription-id"
        assert updated_sub.expires_at > datetime.now(timezone.utc)

    async def test_recreate_deletes_old_subscription_first(
        self, service, mock_subscription_repo, expired_subscription, mock_token
    ):
        """Attempts to delete old subscription before creating new one."""
        old_subscription_id = expired_subscription.subscription_id

        with patch.object(service, "_delete_graph_subscription", return_value=True) as mock_delete:
            with patch.object(service, "_create_graph_subscription", return_value="new-sub-id"):
                await service.recreate_expired_subscription(
                    subscription=expired_subscription,
                    token=mock_token,
                )

        mock_delete.assert_called_once_with(
            subscription_id=old_subscription_id,
            token=mock_token,
        )

    async def test_recreate_fails_if_graph_creation_fails(
        self, service, mock_subscription_repo, expired_subscription, mock_token
    ):
        """Returns False if creating new Graph subscription fails."""
        with patch.object(service, "_delete_graph_subscription", return_value=True):
            with patch.object(service, "_create_graph_subscription", return_value=None):
                result = await service.recreate_expired_subscription(
                    subscription=expired_subscription,
                    token=mock_token,
                )

        assert result is False
        mock_subscription_repo.update.assert_not_called()

    async def test_recreate_continues_even_if_delete_fails(
        self, service, mock_subscription_repo, expired_subscription, mock_token
    ):
        """Continues with recreation even if old subscription delete fails."""
        with patch.object(service, "_delete_graph_subscription", return_value=False):
            with patch.object(service, "_create_graph_subscription", return_value="new-sub-id"):
                result = await service.recreate_expired_subscription(
                    subscription=expired_subscription,
                    token=mock_token,
                )

        # Should still succeed - old subscription may already be gone
        assert result is True


class TestRenewSubscription:
    """Tests for renew_subscription method."""

    async def test_renew_success(
        self, service, mock_subscription_repo, mock_subscription, mock_token
    ):
        """Successfully renews a subscription."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session.patch = MagicMock(return_value=mock_response)
            mock_session_class.return_value = mock_session

            result = await service.renew_subscription(
                subscription=mock_subscription,
                token=mock_token,
            )

        assert result is True
        mock_subscription_repo.update.assert_called_once()

    async def test_renew_recreates_on_404(
        self, service, mock_subscription_repo, mock_subscription, mock_token
    ):
        """Recreates subscription if Graph returns 404 (subscription not found)."""
        mock_response = MagicMock()
        mock_response.status = 404
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session.patch = MagicMock(return_value=mock_response)
            mock_session_class.return_value = mock_session

            with patch.object(service, "recreate_expired_subscription", return_value=True) as mock_recreate:
                result = await service.renew_subscription(
                    subscription=mock_subscription,
                    token=mock_token,
                )

        mock_recreate.assert_called_once_with(
            subscription=mock_subscription,
            token=mock_token,
            is_onedrive=False,
        )
        assert result is True

    async def test_renew_recreates_onedrive_on_404_with_onedrive_flag(
        self, service, mock_token
    ):
        """OneDrive subscriptions must pass is_onedrive=True on automatic recreation."""
        onedrive_subscription = SharePointSubscription(
            id=uuid4(),
            user_integration_id=uuid4(),
            site_id="drive-id-123",
            subscription_id="sub-id-123",
            drive_id="drive-id-123",
            expires_at=datetime.now(timezone.utc) + timedelta(days=10),
        )

        mock_response = MagicMock()
        mock_response.status = 404
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session.patch = MagicMock(return_value=mock_response)
            mock_session_class.return_value = mock_session

            with patch.object(service, "recreate_expired_subscription", return_value=True) as mock_recreate:
                result = await service.renew_subscription(
                    subscription=onedrive_subscription,
                    token=mock_token,
                )

        mock_recreate.assert_called_once_with(
            subscription=onedrive_subscription,
            token=mock_token,
            is_onedrive=True,
        )
        assert result is True

    async def test_renew_returns_false_on_error(
        self, service, mock_subscription_repo, mock_subscription, mock_token
    ):
        """Returns False on HTTP error."""
        mock_response = MagicMock()
        mock_response.status = 500
        mock_response.text = AsyncMock(return_value="Internal Server Error")
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session.patch = MagicMock(return_value=mock_response)
            mock_session_class.return_value = mock_session

            result = await service.renew_subscription(
                subscription=mock_subscription,
                token=mock_token,
            )

        assert result is False


class TestDeleteSubscriptionIfUnused:
    """Tests for delete_subscription_if_unused method."""

    async def test_does_not_delete_if_references_exist(
        self, service, mock_subscription_repo, mock_token
    ):
        """Keeps subscription if integration_knowledge records reference it."""
        subscription_id = uuid4()
        mock_subscription_repo.count_references.return_value = 2

        result = await service.delete_subscription_if_unused(
            subscription_id=subscription_id,
            token=mock_token,
        )

        assert result is True
        mock_subscription_repo.remove.assert_not_called()

    async def test_deletes_if_no_references(
        self, service, mock_subscription_repo, mock_subscription, mock_token
    ):
        """Deletes subscription if no references exist."""
        mock_subscription_repo.count_references.return_value = 0
        mock_subscription_repo.get.return_value = mock_subscription

        with patch.object(service, "_delete_graph_subscription", return_value=True):
            result = await service.delete_subscription_if_unused(
                subscription_id=mock_subscription.id,
                token=mock_token,
            )

        assert result is True
        mock_subscription_repo.delete.assert_called_once()


class TestGraphApiInteractions:
    """Tests for Microsoft Graph API interactions."""

    async def test_create_graph_subscription_sends_correct_payload(
        self, service, mock_token
    ):
        """Creates Graph subscription with correct payload."""
        mock_response = MagicMock()
        mock_response.status = 201
        mock_response.json = AsyncMock(return_value={"id": "new-graph-sub-id"})
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session.post = MagicMock(return_value=mock_response)
            mock_session_class.return_value = mock_session

            result = await service._create_graph_subscription(
                token=mock_token,
                site_id="site-123",
                drive_id="drive-456",
            )

        assert result == "new-graph-sub-id"

        # Verify payload
        call_kwargs = mock_session.post.call_args.kwargs
        payload = call_kwargs["json"]
        assert payload["changeType"] == "updated"
        assert payload["notificationUrl"] == "https://example.com/webhook/"
        assert "/sites/site-123/drives/drive-456/root" in payload["resource"]
        assert "expirationDateTime" in payload

    async def test_create_graph_subscription_onedrive_resource_format(
        self, service, mock_token
    ):
        """OneDrive subscriptions use /drives/{id}/root format (no site_id)."""
        mock_response = MagicMock()
        mock_response.status = 201
        mock_response.json = AsyncMock(return_value={"id": "onedrive-sub-id"})
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session.post = MagicMock(return_value=mock_response)
            mock_session_class.return_value = mock_session

            result = await service._create_graph_subscription(
                token=mock_token,
                site_id=None,  # OneDrive doesn't have site_id
                drive_id="onedrive-drive-123",
            )

        assert result == "onedrive-sub-id"
        payload = mock_session.post.call_args.kwargs["json"]
        assert payload["resource"] == "/drives/onedrive-drive-123/root"
        assert "/sites/" not in payload["resource"]

    async def test_delete_graph_subscription_handles_404(
        self, service, mock_token
    ):
        """Treats 404 as success (subscription already deleted)."""
        mock_response = MagicMock()
        mock_response.status = 404
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session.delete = MagicMock(return_value=mock_response)
            mock_session_class.return_value = mock_session

            result = await service._delete_graph_subscription(
                subscription_id="already-deleted-sub",
                token=mock_token,
            )

        assert result is True

    async def test_delete_graph_subscription_success(
        self, service, mock_token
    ):
        """Successfully deletes subscription (204 response)."""
        mock_response = MagicMock()
        mock_response.status = 204
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session.delete = MagicMock(return_value=mock_response)
            mock_session_class.return_value = mock_session

            result = await service._delete_graph_subscription(
                subscription_id="sub-to-delete",
                token=mock_token,
            )

        assert result is True


class TestListExpiringSubscriptions:
    """Tests for list_expiring_subscriptions method."""

    async def test_lists_subscriptions_expiring_within_threshold(
        self, service, mock_subscription_repo
    ):
        """Lists subscriptions expiring within specified hours."""
        expiring_subs = [MagicMock(), MagicMock()]
        mock_subscription_repo.list_expiring_before.return_value = expiring_subs

        result = await service.list_expiring_subscriptions(hours=4)

        assert result == expiring_subs
        mock_subscription_repo.list_expiring_before.assert_called_once()
