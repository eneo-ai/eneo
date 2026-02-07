from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from intric.integration.presentation.admin_sharepoint_router import (
    _get_sharepoint_token_for_user_integration,
    _require_sharepoint_webhook_client_state,
    list_sharepoint_subscriptions,
    recreate_subscription,
    renew_expired_subscriptions,
)


def _build_container_with_admin_user():
    user = MagicMock()
    user.id = uuid4()
    user.tenant_id = uuid4()
    user.permissions = []

    container = MagicMock()
    container.user.return_value = user
    return container, user


@pytest.mark.asyncio
async def test_list_subscriptions_scopes_by_tenant():
    container, user = _build_container_with_admin_user()
    subscription_repo = AsyncMock()
    subscription_repo.list_by_tenant.return_value = []
    subscription_repo.list_all.return_value = [MagicMock()]

    container.sharepoint_subscription_repo.return_value = subscription_repo
    container.user_integration_repo.return_value = AsyncMock()
    container.user_repo.return_value = AsyncMock()

    with patch(
        "intric.integration.presentation.admin_sharepoint_router.validate_permission"
    ):
        result = await list_sharepoint_subscriptions(container=container)

    assert result == []
    subscription_repo.list_by_tenant.assert_called_once_with(user.tenant_id)
    subscription_repo.list_all.assert_not_called()


@pytest.mark.asyncio
async def test_renew_expired_subscriptions_scopes_by_tenant():
    container, user = _build_container_with_admin_user()
    subscription_repo = AsyncMock()
    subscription_repo.list_by_tenant.return_value = []
    subscription_repo.list_all.return_value = [MagicMock()]

    container.sharepoint_subscription_repo.return_value = subscription_repo
    container.sharepoint_subscription_service.return_value = AsyncMock()
    container.user_integration_repo.return_value = AsyncMock()

    with patch(
        "intric.integration.presentation.admin_sharepoint_router.validate_permission"
    ):
        result = await renew_expired_subscriptions(container=container)

    assert result.total_subscriptions == 0
    assert result.expired_count == 0
    subscription_repo.list_by_tenant.assert_called_once_with(user.tenant_id)
    subscription_repo.list_all.assert_not_called()


@pytest.mark.asyncio
async def test_recreate_subscription_uses_tenant_scoped_lookup():
    container, user = _build_container_with_admin_user()
    subscription_id = uuid4()
    subscription_repo = AsyncMock()
    subscription_repo.one_by_tenant.return_value = None

    container.sharepoint_subscription_repo.return_value = subscription_repo
    container.sharepoint_subscription_service.return_value = AsyncMock()
    container.user_integration_repo.return_value = AsyncMock()

    with patch(
        "intric.integration.presentation.admin_sharepoint_router.validate_permission"
    ):
        with pytest.raises(HTTPException) as exc_info:
            await recreate_subscription(
                subscription_id=subscription_id, container=container
            )

    assert exc_info.value.status_code == 404
    subscription_repo.one_by_tenant.assert_called_once_with(
        subscription_id=subscription_id,
        tenant_id=user.tenant_id,
    )


@pytest.mark.asyncio
async def test_token_helper_persists_rotated_service_account_refresh_token():
    container = MagicMock()
    user_integration = MagicMock()
    user_integration.id = uuid4()
    user_integration.auth_type = "tenant_app"
    user_integration.tenant_app_id = uuid4()

    tenant_app = MagicMock()
    tenant_app.is_service_account.return_value = True
    tenant_app.service_account_refresh_token = "old-refresh-token"

    container.oauth_token_service.return_value = AsyncMock()
    tenant_app_repo = AsyncMock()
    tenant_app_repo.get_by_id.return_value = tenant_app
    container.tenant_sharepoint_app_repo.return_value = tenant_app_repo

    service_account_auth = AsyncMock()
    service_account_auth.refresh_access_token.return_value = {
        "access_token": "service-account-access-token",
        "refresh_token": "new-refresh-token",
    }
    container.service_account_auth_service.return_value = service_account_auth

    token = await _get_sharepoint_token_for_user_integration(
        user_integration=user_integration,
        container=container,
    )

    assert token.access_token == "service-account-access-token"
    tenant_app.update_refresh_token.assert_called_once_with("new-refresh-token")
    tenant_app_repo.update.assert_called_once_with(tenant_app)


def test_require_sharepoint_webhook_client_state_raises_when_missing():
    settings = MagicMock()
    settings.sharepoint_webhook_client_state = None

    with patch(
        "intric.integration.presentation.admin_sharepoint_router.get_settings",
        return_value=settings,
    ):
        with pytest.raises(HTTPException) as exc_info:
            _require_sharepoint_webhook_client_state()

    assert exc_info.value.status_code == 400
    assert "SHAREPOINT_WEBHOOK_CLIENT_STATE" in exc_info.value.detail


def test_require_sharepoint_webhook_client_state_returns_trimmed_value():
    settings = MagicMock()
    settings.sharepoint_webhook_client_state = "  webhook-secret  "

    with patch(
        "intric.integration.presentation.admin_sharepoint_router.get_settings",
        return_value=settings,
    ):
        result = _require_sharepoint_webhook_client_state()

    assert result == "webhook-secret"
