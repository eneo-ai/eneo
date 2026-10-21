"""Unit tests for SharePointSubscriptionService - webhook subscription management.

Tests the subscription creation, renewal, recreation, and deletion logic
for Microsoft Graph webhook subscriptions.
"""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from eneo.integration.domain.entities.sharepoint_subscription import (
    SharePointSubscription,
)
from eneo.integration.domain.repositories.sharepoint_subscription_repo import (
    SharePointSubscriptionExists,
)
from eneo.integration.infrastructure.sharepoint_subscription_service import (
    SharePointSubscriptionService,
    lifecycle_notification_url_for,
)

LIFECYCLE_URL = "https://example.com/webhook/"


@pytest.fixture
def mock_subscription_repo():
    """Create a mock SharePoint subscription repository."""
    repo = AsyncMock()
    repo.get_by_user_and_site = AsyncMock(return_value=None)

    async def lock_user_site(**kwargs):
        # The lock's read is the same lookup; tests stub get_by_user_and_site.
        return await repo.get_by_user_and_site(**kwargs)

    repo.lock_user_site = AsyncMock(side_effect=lock_user_site)

    @asynccontextmanager
    async def own_transaction():
        yield repo

    repo.own_transaction = own_transaction
    repo.add = AsyncMock()
    repo.update = AsyncMock()
    repo.remove = AsyncMock()
    repo.get = AsyncMock()
    repo.count_references = AsyncMock(return_value=0)
    repo.list_expiring_before = AsyncMock(return_value=[])
    return repo


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
        lifecycle_notification_url=LIFECYCLE_URL,
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
def service(mock_subscription_repo):
    """Create SharePointSubscriptionService with mocked dependencies."""
    with patch(
        "eneo.integration.infrastructure.sharepoint_subscription_service.get_settings"
    ) as mock_settings:
        settings = MagicMock()
        settings.sharepoint_webhook_notification_url = "https://example.com/webhook/"
        settings.sharepoint_webhook_client_state = "test-client-state"
        settings.sharepoint_webhook_lifecycle_notification_url = None
        settings.public_origin = "https://example.com"
        mock_settings.return_value = settings

        return SharePointSubscriptionService(
            sharepoint_subscription_repo=mock_subscription_repo,
        )


@pytest.mark.parametrize(
    "stored_url, drifted",
    [
        pytest.param("https://example.com/webhook/", False, id="same"),
        pytest.param("https://example.com/webhook", False, id="no-trailing-slash"),
        pytest.param("HTTPS://Example.COM/webhook/", False, id="scheme-host-case"),
        pytest.param("https://example.com:443/webhook/", True, id="explicit-port"),
        pytest.param("https://example.com/Webhook/", True, id="path-case"),
        pytest.param("https://example.com/webhook/?v=2", True, id="query"),
        pytest.param("http://example.com/webhook/", True, id="scheme"),
        pytest.param("https://old-origin/webhook/", True, id="host"),
        pytest.param(None, False, id="legacy-unknown"),
    ],
)
def test_notification_url_drift_ignores_spelling_differences(
    service, mock_subscription, stored_url, drifted
):
    mock_subscription.notification_url = stored_url

    assert service.notification_url_drifted(mock_subscription) is drifted


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
        with patch.object(
            service, "_resolve_drive_id", return_value="resolved-drive-id"
        ):
            with patch.object(
                service, "_create_graph_subscription", return_value="new-graph-sub-id"
            ):
                result = await service.ensure_subscription_for_site(
                    user_integration_id=user_integration_id,
                    site_id=site_id,
                    token=mock_token,
                )

        assert result is not None
        mock_subscription_repo.add.assert_called_once()
        stored = mock_subscription_repo.add.call_args.args[0]
        assert stored.notification_url == "https://example.com/webhook/"

    async def test_losing_the_create_race_keeps_the_winner_and_drops_the_duplicate(
        self, service, mock_subscription_repo, mock_token, mock_subscription
    ):
        user_integration_id = uuid4()
        mock_subscription_repo.get_by_user_and_site.side_effect = [
            None,
            mock_subscription,
        ]
        mock_subscription_repo.add.side_effect = SharePointSubscriptionExists(
            user_integration_id, mock_subscription.site_id
        )

        with (
            patch.object(service, "_resolve_drive_id", return_value="drive-id"),
            patch.object(
                service, "_create_graph_subscription", return_value="duplicate-sub"
            ),
            patch.object(
                service, "_delete_graph_subscription", return_value=True
            ) as delete_graph,
        ):
            result = await service.ensure_subscription_for_site(
                user_integration_id=user_integration_id,
                site_id=mock_subscription.site_id,
                token=mock_token,
            )

        assert result is mock_subscription
        delete_graph.assert_awaited_once_with(
            subscription_id="duplicate-sub", token=mock_token
        )
        mock_subscription_repo.update.assert_not_called()

    async def test_reused_subscription_is_recreated_when_its_url_drifted(
        self, service, mock_subscription_repo, mock_token, mock_subscription
    ):
        mock_subscription.notification_url = "https://old-origin/webhook/"
        mock_subscription_repo.get_by_user_and_site.return_value = mock_subscription

        with patch.object(
            service, "recreate_expired_subscription", return_value=True
        ) as recreate:
            result = await service.ensure_subscription_for_site(
                user_integration_id=mock_subscription.user_integration_id,
                site_id=mock_subscription.site_id,
                token=mock_token,
            )

        assert result is mock_subscription
        # In the ensure's own transaction, on its repository.
        recreate.assert_awaited_once_with(
            subscription=mock_subscription,
            token=mock_token,
            is_onedrive=False,
            repo=mock_subscription_repo,
        )

    async def test_recreates_expired_subscription(
        self, service, mock_subscription_repo, expired_subscription, mock_token
    ):
        """Recreates subscription if existing one has expired."""
        mock_subscription_repo.get_by_user_and_site.return_value = expired_subscription

        with patch.object(
            service, "recreate_expired_subscription", return_value=True
        ) as mock_recreate:
            result = await service.ensure_subscription_for_site(
                user_integration_id=expired_subscription.user_integration_id,
                site_id=expired_subscription.site_id,
                token=mock_token,
            )

        mock_recreate.assert_called_once()
        assert result == expired_subscription

    async def test_returns_none_if_notification_url_not_configured(
        self, mock_subscription_repo, mock_token
    ):
        """Returns None if webhook notification URL is not configured."""
        with patch(
            "eneo.integration.infrastructure.sharepoint_subscription_service.get_settings"
        ) as mock_settings:
            settings = MagicMock()
            settings.sharepoint_webhook_notification_url = None
            settings.sharepoint_webhook_client_state = "test-client-state"
            settings.sharepoint_webhook_lifecycle_notification_url = None
            settings.public_origin = None
            mock_settings.return_value = settings

            svc = SharePointSubscriptionService(
                sharepoint_subscription_repo=mock_subscription_repo,
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

        with patch.object(
            service, "_create_graph_subscription", return_value="new-sub-id"
        ) as mock_create:
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
            with patch.object(
                service,
                "_create_graph_subscription",
                return_value="new-subscription-id",
            ):
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
        assert updated_sub.consecutive_renewal_failures == 0
        assert updated_sub.last_renewal_failed_at is None
        assert updated_sub.last_renewal_error is None

    async def test_recreate_writes_the_row_between_creating_and_deleting(
        self, service, mock_subscription_repo, expired_subscription, mock_token
    ):
        """Graph allows two subscriptions per resource; the old one goes last,
        after the row points at the new one."""
        old_subscription_id = expired_subscription.subscription_id
        steps = MagicMock()

        with (
            patch.object(
                service, "_delete_graph_subscription", return_value=True
            ) as mock_delete,
            patch.object(
                service, "_create_graph_subscription", return_value="new-sub-id"
            ) as mock_create,
        ):
            steps.attach_mock(mock_create, "create")
            steps.attach_mock(mock_subscription_repo.update, "update")
            steps.attach_mock(mock_delete, "delete")
            await service.recreate_expired_subscription(
                subscription=expired_subscription,
                token=mock_token,
            )

        assert [call[0] for call in steps.mock_calls] == [
            "create",
            "update",
            "delete",
        ]
        mock_delete.assert_called_once_with(
            subscription_id=old_subscription_id,
            token=mock_token,
        )

    async def test_a_failed_row_write_leaves_the_old_subscription_at_graph(
        self, service, mock_subscription_repo, expired_subscription, mock_token
    ):
        mock_subscription_repo.update.side_effect = RuntimeError("db down")

        with (
            patch.object(service, "_delete_graph_subscription") as mock_delete,
            patch.object(
                service, "_create_graph_subscription", return_value="new-sub-id"
            ),
            pytest.raises(RuntimeError),
        ):
            await service.recreate_expired_subscription(
                subscription=expired_subscription, token=mock_token
            )

        mock_delete.assert_not_called()

    async def test_recreate_keeps_the_old_subscription_when_creation_fails(
        self, service, mock_subscription_repo, expired_subscription, mock_token
    ):
        """A failed create leaves Graph untouched and is recorded on the row."""
        old_subscription_id = expired_subscription.subscription_id

        with (
            patch.object(service, "_delete_graph_subscription") as mock_delete,
            patch.object(service, "_create_graph_subscription", return_value=None),
        ):
            result = await service.recreate_expired_subscription(
                subscription=expired_subscription,
                token=mock_token,
            )

        assert result is False
        mock_delete.assert_not_called()
        assert expired_subscription.subscription_id == old_subscription_id
        assert expired_subscription.consecutive_renewal_failures == 1
        assert expired_subscription.last_renewal_failed_at is not None
        assert expired_subscription.last_renewal_error
        mock_subscription_repo.update.assert_awaited_once_with(expired_subscription)

    @pytest.mark.parametrize(
        "missing, named_setting",
        [
            pytest.param(
                "sharepoint_webhook_client_state",
                "SHAREPOINT_WEBHOOK_CLIENT_STATE",
                id="client-state",
            ),
            pytest.param(
                "sharepoint_webhook_notification_url",
                "SHAREPOINT_WEBHOOK_NOTIFICATION_URL",
                id="notification-url",
            ),
        ],
    )
    async def test_recreate_touches_nothing_when_webhooks_are_not_configured(
        self,
        mock_subscription_repo,
        expired_subscription,
        mock_token,
        missing,
        named_setting,
    ):
        """A live subscription must not be dropped at Graph with no replacement."""
        with patch(
            "eneo.integration.infrastructure.sharepoint_subscription_service.get_settings"
        ) as mock_settings:
            settings = MagicMock()
            settings.sharepoint_webhook_notification_url = (
                "https://example.com/webhook/"
            )
            settings.sharepoint_webhook_client_state = "test-client-state"
            settings.sharepoint_webhook_lifecycle_notification_url = None
            settings.public_origin = None
            setattr(settings, missing, None)
            mock_settings.return_value = settings
            service = SharePointSubscriptionService(
                sharepoint_subscription_repo=mock_subscription_repo,
            )
        old_subscription_id = expired_subscription.subscription_id

        with (
            patch.object(service, "_delete_graph_subscription") as delete_graph,
            patch.object(service, "_create_graph_subscription") as create_graph,
            pytest.raises(ValueError, match=named_setting),
        ):
            await service.recreate_expired_subscription(
                subscription=expired_subscription, token=mock_token
            )

        delete_graph.assert_not_called()
        create_graph.assert_not_called()
        mock_subscription_repo.update.assert_not_called()
        assert expired_subscription.subscription_id == old_subscription_id

    async def test_recreate_continues_even_if_delete_fails(
        self, service, mock_subscription_repo, expired_subscription, mock_token
    ):
        """Continues with recreation even if old subscription delete fails."""
        with patch.object(service, "_delete_graph_subscription", return_value=False):
            with patch.object(
                service, "_create_graph_subscription", return_value="new-sub-id"
            ):
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
        mock_subscription.consecutive_renewal_failures = 2
        mock_subscription.last_renewal_failed_at = datetime.now(timezone.utc)
        mock_subscription.last_renewal_error = "previous failure"

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
        updated_sub = mock_subscription_repo.update.call_args[0][0]
        assert updated_sub.consecutive_renewal_failures == 0
        assert updated_sub.last_renewal_failed_at is None
        assert updated_sub.last_renewal_error is None

    @pytest.mark.parametrize(
        "stored_url, recreated",
        [
            pytest.param("https://old-origin/webhook/", True, id="drifted"),
            pytest.param("https://example.com/webhook/", False, id="current"),
            pytest.param(None, False, id="legacy-unknown"),
        ],
    )
    async def test_renew_recreates_only_when_the_notification_url_drifted(
        self, service, mock_subscription, mock_token, stored_url, recreated
    ):
        mock_subscription.notification_url = stored_url
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        with (
            patch("aiohttp.ClientSession") as mock_session_class,
            patch.object(service, "_delete_graph_subscription", return_value=True),
            patch.object(
                service, "_create_graph_subscription", return_value="fresh-sub"
            ) as create_graph,
        ):
            mock_session = MagicMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session.patch = MagicMock(return_value=mock_response)
            mock_session_class.return_value = mock_session

            assert await service.renew_subscription(mock_subscription, mock_token)

        assert create_graph.await_count == (1 if recreated else 0)
        assert mock_session.patch.call_count == (0 if recreated else 1)
        if recreated:
            assert mock_subscription.subscription_id == "fresh-sub"
            assert mock_subscription.notification_url == "https://example.com/webhook/"
        else:
            assert mock_subscription.notification_url == stored_url

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

            with patch.object(
                service, "recreate_expired_subscription", return_value=True
            ) as mock_recreate:
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

            with patch.object(
                service, "recreate_expired_subscription", return_value=True
            ) as mock_recreate:
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
        assert payload["clientState"] == "test-client-state"

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
        assert payload["clientState"] == "test-client-state"

    async def test_create_graph_subscription_raises_if_client_state_missing(
        self, mock_subscription_repo, mock_token
    ):
        """Must fail fast if SHAREPOINT_WEBHOOK_CLIENT_STATE is not configured."""
        with patch(
            "eneo.integration.infrastructure.sharepoint_subscription_service.get_settings"
        ) as mock_settings:
            settings = MagicMock()
            settings.sharepoint_webhook_notification_url = (
                "https://example.com/webhook/"
            )
            settings.sharepoint_webhook_client_state = None
            settings.sharepoint_webhook_lifecycle_notification_url = None
            settings.public_origin = "https://example.com"
            mock_settings.return_value = settings

            service_without_client_state = SharePointSubscriptionService(
                sharepoint_subscription_repo=mock_subscription_repo,
            )

        with patch("aiohttp.ClientSession") as mock_session_class:
            with pytest.raises(ValueError) as exc_info:
                await service_without_client_state._create_graph_subscription(
                    token=mock_token,
                    site_id="site-123",
                    drive_id="drive-456",
                )

        assert "SHAREPOINT_WEBHOOK_CLIENT_STATE" in str(exc_info.value)
        mock_session_class.assert_not_called()

    async def test_delete_graph_subscription_handles_404(self, service, mock_token):
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

    async def test_delete_graph_subscription_success(self, service, mock_token):
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


@pytest.mark.parametrize(
    "notification_url, configured, expected",
    [
        pytest.param(
            "https://eneo.example/api/webhook/",
            None,
            "https://eneo.example/api/webhook/",
            id="the-webhook-url-by-default",
        ),
        pytest.param(
            "https://eneo.example/api/webhook/",
            " https://eneo.example/api/webhook/lifecycle/ ",
            "https://eneo.example/api/webhook/lifecycle/",
            id="configured",
        ),
        pytest.param(None, "https://eneo.example/x/", None, id="no-webhooks"),
    ],
)
def test_lifecycle_notification_url(notification_url, configured, expected):
    assert lifecycle_notification_url_for(notification_url, configured) == expected


class TestLifecycleNotificationUrl:
    @staticmethod
    def _graph(post_status: int = 201, patch_status: int = 200):
        posted = MagicMock()
        posted.status = post_status
        posted.json = AsyncMock(return_value={"id": "fresh-sub"})
        posted.text = AsyncMock(return_value="refused")
        posted.__aenter__ = AsyncMock(return_value=posted)
        posted.__aexit__ = AsyncMock(return_value=None)
        patched = MagicMock()
        patched.status = patch_status
        patched.__aenter__ = AsyncMock(return_value=patched)
        patched.__aexit__ = AsyncMock(return_value=None)
        session = MagicMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)
        session.post = MagicMock(return_value=posted)
        session.patch = MagicMock(return_value=patched)
        return session

    async def test_a_new_subscription_registers_and_remembers_it(
        self, service, mock_subscription_repo, mock_token
    ):
        mock_subscription_repo.add.side_effect = lambda subscription: subscription
        graph = self._graph()

        with (
            patch("aiohttp.ClientSession", return_value=graph),
            patch.object(service, "_resolve_drive_id", return_value="drive-1"),
        ):
            created = await service.ensure_subscription_for_site(
                user_integration_id=uuid4(), site_id="site-1", token=mock_token
            )

        assert graph.post.call_args.kwargs["json"]["lifecycleNotificationUrl"] == (
            LIFECYCLE_URL
        )
        assert created.lifecycle_notification_url == LIFECYCLE_URL

    async def test_renewal_recreates_a_subscription_created_without_it(
        self, service, mock_subscription, mock_token
    ):
        mock_subscription.lifecycle_notification_url = None
        graph = self._graph()

        with (
            patch("aiohttp.ClientSession", return_value=graph),
            patch.object(service, "_delete_graph_subscription", return_value=True),
        ):
            assert await service.renew_subscription(mock_subscription, mock_token)

        graph.patch.assert_not_called()
        assert mock_subscription.subscription_id == "fresh-sub"
        assert mock_subscription.lifecycle_notification_url == LIFECYCLE_URL

    async def test_a_subscription_that_cannot_be_recreated_is_renewed_as_it_is(
        self, service, mock_subscription, mock_token
    ):
        """Without lifecycle events it still delivers changes; letting it expire
        would not."""
        mock_subscription.lifecycle_notification_url = None
        graph = self._graph(post_status=400)

        with patch("aiohttp.ClientSession", return_value=graph):
            assert await service.renew_subscription(mock_subscription, mock_token)

        graph.patch.assert_called_once()
        assert mock_subscription.subscription_id == "graph-subscription-id-abc"
        assert mock_subscription.lifecycle_notification_url is None
        assert mock_subscription.consecutive_renewal_failures == 0

    async def test_a_subscription_that_has_it_is_renewed_in_place(
        self, service, mock_subscription, mock_token
    ):
        graph = self._graph()

        with patch("aiohttp.ClientSession", return_value=graph):
            assert await service.renew_subscription(mock_subscription, mock_token)

        graph.post.assert_not_called()
        graph.patch.assert_called_once()

    async def test_reuse_at_import_does_not_recreate_for_it(
        self, service, mock_subscription_repo, mock_subscription, mock_token
    ):
        """Renewal adds it; an import must not pay a Graph round trip for it."""
        mock_subscription.lifecycle_notification_url = None
        mock_subscription.notification_url = "https://example.com/webhook/"
        mock_subscription_repo.get_by_user_and_site.return_value = mock_subscription

        with patch.object(service, "_create_graph_subscription") as create:
            reused = await service.ensure_subscription_for_site(
                user_integration_id=mock_subscription.user_integration_id,
                site_id=mock_subscription.site_id,
                token=mock_token,
            )

        assert reused is mock_subscription
        create.assert_not_called()
