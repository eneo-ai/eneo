import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException

from eneo.integration.domain.entities.integration import Integration
from eneo.integration.domain.entities.tenant_integration import TenantIntegration
from eneo.integration.domain.entities.tenant_sharepoint_app import (
    AUTH_METHOD_SERVICE_ACCOUNT,
    TenantSharePointApp,
)
from eneo.integration.infrastructure.auth_service.org_token_provider import (
    OrgTokenProvider,
)
from eneo.integration.infrastructure.auth_service.service_account_auth_service import (
    ServiceAccountTokenResult,
)
from eneo.integration.presentation.admin_models import TenantSharePointAppPublic
from eneo.integration.presentation.admin_sharepoint_router import (
    OAUTH_STATE_PREFIX,
    _get_sharepoint_token_for_user_integration,
    _require_sharepoint_webhook_client_state,
    _to_app_public,
    delete_sharepoint_app,
    get_sharepoint_app,
    list_sharepoint_subscriptions,
    recreate_all_subscriptions,
    recreate_subscription,
    renew_expired_subscriptions,
    restart_service_account_auth,
    router,
    service_account_auth_callback,
)
from eneo.integration.presentation.admin_sharepoint_router import (
    test_sharepoint_app_credentials as app_credentials_endpoint,
)
from eneo.settings.encryption_service import EncryptionService

_ROUTER = "eneo.integration.presentation.admin_sharepoint_router"


class _FakeRedis:
    """Dict-backed Redis without DEL, so a pop that is not GETDEL fails loudly.
    GET serves the binding check that runs before the state is spent."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value

    async def getdel(self, key: str) -> str | None:
        return self.store.pop(key, None)

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def delete(self, key: str) -> None:
        raise AssertionError("pop must use GETDEL, not DEL")


def _encryption_service() -> EncryptionService:
    return EncryptionService(Fernet.generate_key().decode())


def _service_account_app(tenant_id) -> TenantSharePointApp:
    now = datetime.now(timezone.utc)
    return TenantSharePointApp(
        id=uuid4(),
        tenant_id=tenant_id,
        client_id="stored-client-id",
        client_secret="stored-client-secret",
        tenant_domain="contoso.onmicrosoft.com",
        auth_method=AUTH_METHOD_SERVICE_ACCOUNT,
        service_account_refresh_token="stored-refresh",
        service_account_email="svc@contoso.com",
        created_at=now,
        updated_at=now,
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
    container.org_token_provider.return_value = OrgTokenProvider(
        tenant_app_repo=tenant_app_repo,
        tenant_app_auth_service=AsyncMock(),
        service_account_auth_service=service_account_auth,
    )

    token = await _get_sharepoint_token_for_user_integration(
        user_integration=user_integration,
        container=container,
    )

    assert token.access_token == "service-account-access-token"
    tenant_app.update_refresh_token.assert_called_once_with("new-refresh-token")
    tenant_app_repo.update.assert_called_once_with(tenant_app)


def _callback_container(stored: dict[str, str], user_id, tenant_id):
    container, user = _build_container_with_admin_user()
    user.id = user_id
    user.tenant_id = tenant_id
    redis = _FakeRedis()
    encryption = _encryption_service()
    container.redis_client.return_value = redis
    container.encryption_service.return_value = encryption
    redis.store[f"{OAUTH_STATE_PREFIX}state-1"] = encryption.encrypt(json.dumps(stored))
    return container


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", ["user_id", "tenant_id"])
async def test_callback_rejects_state_bound_to_another_principal(mismatch):
    user_id, tenant_id = uuid4(), uuid4()
    stored = {
        "client_id": "c",
        "client_secret": "s",
        "tenant_domain": "d",
        "tenant_id": str(tenant_id),
        "user_id": str(user_id),
    }
    stored[mismatch] = str(uuid4())
    container = _callback_container(stored, user_id, tenant_id)
    settings = MagicMock(sharepoint_webhook_client_state="secret")
    callback = MagicMock(state="state-1", auth_code="code")

    with (
        patch(f"{_ROUTER}.get_settings", return_value=settings),
        patch(f"{_ROUTER}.ServiceAccountAuthService") as auth_cls,
    ):
        with pytest.raises(HTTPException) as exc_info:
            await service_account_auth_callback(callback=callback, container=container)

    assert exc_info.value.status_code == 400
    auth_cls.return_value.exchange_token.assert_not_called()
    # Another principal cannot spend the state of the admin who started it.
    assert list(container.redis_client.return_value.store) == [
        f"{OAUTH_STATE_PREFIX}state-1"
    ]


@pytest.mark.asyncio
async def test_reauth_state_carries_no_secret_and_callback_reuses_stored_app():
    container, user = _build_container_with_admin_user()
    redis = _FakeRedis()
    encryption = _encryption_service()
    container.redis_client.return_value = redis
    container.encryption_service.return_value = encryption
    app = _service_account_app(user.tenant_id)
    tenant_app_service = AsyncMock()
    tenant_app_service.get_active_app_for_tenant.return_value = app
    tenant_app_service.configure_service_account.return_value = app
    container.tenant_sharepoint_app_service.return_value = tenant_app_service
    settings = MagicMock(sharepoint_webhook_client_state="secret")
    settings.integration_callback_uri.return_value = (
        "https://eneo.example/integrations/callback/token/"
    )

    with (
        patch(f"{_ROUTER}.get_settings", return_value=settings),
        patch(f"{_ROUTER}.ServiceAccountAuthService") as auth_cls,
    ):
        auth_cls.return_value.gen_auth_url.return_value = {"auth_url": "https://x"}
        started = await restart_service_account_auth(container=container)

        (stored_blob,) = redis.store.values()
        assert "stored-client-secret" not in stored_blob
        assert json.loads(encryption.decrypt(stored_blob)) == {
            "reauth": "1",
            "tenant_id": str(user.tenant_id),
            "user_id": str(user.id),
            "redirect_uri": "https://eneo.example/integrations/callback/token/",
        }

        auth_cls.return_value.exchange_token = AsyncMock(
            return_value=ServiceAccountTokenResult(
                access_token="at", refresh_token="new-refresh", email="svc@contoso.com"
            )
        )
        container.user_integration_repo.return_value = AsyncMock()
        tenant_integration_repo = AsyncMock()
        container.tenant_integration_repo.return_value = tenant_integration_repo
        tenant_integration_repo.query.return_value = [
            TenantIntegration(
                tenant_id=user.tenant_id,
                integration=Integration(
                    name="SharePoint", description="", integration_type="sharepoint"
                ),
            )
        ]
        callback = MagicMock(state=started.state, auth_code="code")
        result = await service_account_auth_callback(
            callback=callback, container=container
        )

    auth_cls.return_value.exchange_token.assert_awaited_once_with(
        auth_code="code",
        client_id="stored-client-id",
        client_secret="stored-client-secret",
        tenant_domain="contoso.onmicrosoft.com",
        redirect_uri="https://eneo.example/integrations/callback/token/",
    )
    configure_kwargs = tenant_app_service.configure_service_account.await_args.kwargs
    assert configure_kwargs["client_secret"] == "stored-client-secret"
    assert configure_kwargs["refresh_token"] == "new-refresh"
    assert result.id == app.id
    assert redis.store == {}


@pytest.mark.asyncio
async def test_testing_without_a_body_round_trips_the_stored_app():
    container, user = _build_container_with_admin_user()
    app = _service_account_app(user.tenant_id)
    container.tenant_sharepoint_app_service.return_value.get_active_app_for_tenant = (
        AsyncMock(return_value=app)
    )
    provider = AsyncMock()
    provider.test_connection.return_value = (False, "AADSTS50173: revoked")
    container.org_token_provider.return_value = provider

    result = await app_credentials_endpoint(container=container)

    provider.test_connection.assert_awaited_once_with(app)
    assert (result.success, result.error_message) == (False, "AADSTS50173: revoked")


@pytest.mark.asyncio
async def test_testing_without_a_body_requires_a_stored_app():
    container, _ = _build_container_with_admin_user()
    container.tenant_sharepoint_app_service.return_value.get_active_app_for_tenant = (
        AsyncMock(return_value=None)
    )

    with pytest.raises(HTTPException) as exc_info:
        await app_credentials_endpoint(container=container)

    assert exc_info.value.status_code == 400
    container.org_token_provider.assert_not_called()


def test_require_sharepoint_webhook_client_state_raises_when_missing():
    settings = MagicMock()
    settings.sharepoint_webhook_client_state = None

    with patch(
        "eneo.integration.presentation.admin_sharepoint_router.get_settings",
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
        "eneo.integration.presentation.admin_sharepoint_router.get_settings",
        return_value=settings,
    ):
        result = _require_sharepoint_webhook_client_state()

    assert result == "webhook-secret"


@pytest.mark.asyncio
async def test_recreate_all_recreates_every_tenant_subscription_and_reports_failures():
    container, user = _build_container_with_admin_user()
    healthy, broken = MagicMock(id=uuid4()), MagicMock(id=uuid4())
    for sub in (healthy, broken):
        sub.is_expired.return_value = False
        sub.site_id, sub.drive_id = "site", "drive"
    subscription_repo = AsyncMock()
    subscription_repo.list_by_tenant.return_value = [healthy, broken]
    container.sharepoint_subscription_repo.return_value = subscription_repo
    integration = MagicMock()
    integration.auth_type = "user_oauth"
    integration.tenant_integration.tenant_id = user.tenant_id
    container.user_integration_repo.return_value.one_or_none = AsyncMock(
        return_value=integration
    )
    subscription_service = AsyncMock()
    subscription_service.require_webhook_configuration = MagicMock()
    subscription_service.recreate_expired_subscription.side_effect = [True, False]
    container.sharepoint_subscription_service.return_value = subscription_service

    with patch(
        f"{_ROUTER}._get_sharepoint_token_for_user_integration",
        new=AsyncMock(return_value=MagicMock(access_token="t")),
    ):
        result = await recreate_all_subscriptions(container=container)

    subscription_repo.list_by_tenant.assert_awaited_once_with(user.tenant_id)
    assert [
        call.kwargs["subscription"]
        for call in subscription_service.recreate_expired_subscription.await_args_list
    ] == [healthy, broken]
    assert (result.total_subscriptions, result.recreated, result.failed) == (2, 1, 1)
    assert str(broken.id) in result.errors[0]


_LEAKY_ERROR = RuntimeError(
    "GET https://graph.microsoft.com/v1.0/drives/d/items?access_token=abc failed"
)


@pytest.mark.asyncio
async def test_recreate_all_reports_failures_without_internal_error_text():
    container, user = _build_container_with_admin_user()
    broken = MagicMock(id=uuid4())
    broken.is_expired.return_value = False
    broken.site_id, broken.drive_id = "site", "drive"
    container.sharepoint_subscription_repo.return_value.list_by_tenant = AsyncMock(
        return_value=[broken]
    )
    integration = MagicMock()
    integration.tenant_integration.tenant_id = user.tenant_id
    container.user_integration_repo.return_value.one_or_none = AsyncMock(
        return_value=integration
    )
    container.sharepoint_subscription_service.return_value.require_webhook_configuration = MagicMock()

    with patch(
        f"{_ROUTER}._get_sharepoint_token_for_user_integration",
        new=AsyncMock(side_effect=_LEAKY_ERROR),
    ):
        result = await recreate_all_subscriptions(container=container)

    assert result.failed == 1
    (error,) = result.errors
    assert str(broken.id) in error
    assert "access_token=abc" not in error
    assert "https://graph.microsoft.com/v1.0/drives/d/items" in error


@pytest.mark.asyncio
async def test_unexpected_failures_answer_500_without_the_exception_text():
    container, _ = _build_container_with_admin_user()
    container.tenant_sharepoint_app_service.return_value.get_active_app_for_tenant = (
        AsyncMock(side_effect=_LEAKY_ERROR)
    )

    with pytest.raises(HTTPException) as exc_info:
        await get_sharepoint_app(container=container)

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Failed to get SharePoint app"


def test_stored_credential_errors_are_cleaned_when_served():
    app = _service_account_app(uuid4())
    app.last_auth_error = (
        "HTTP 401 for url https://login.microsoftonline.com/t/token?client_secret=s"
    )
    encryption = MagicMock()
    encryption.mask_secret.return_value = "****"

    public = _to_app_public(app, encryption)

    assert isinstance(public, TenantSharePointAppPublic)
    assert public.last_auth_error is not None
    assert "client_secret=s" not in public.last_auth_error
    assert "https://login.microsoftonline.com/t/token" in public.last_auth_error


@pytest.mark.asyncio
async def test_recreate_all_is_refused_before_any_subscription_is_touched_when_webhooks_are_not_configured():
    container, _ = _build_container_with_admin_user()
    subscription_repo = AsyncMock()
    container.sharepoint_subscription_repo.return_value = subscription_repo
    subscription_service = AsyncMock()
    subscription_service.require_webhook_configuration = MagicMock(
        side_effect=ValueError("SHAREPOINT_WEBHOOK_CLIENT_STATE must be configured")
    )
    container.sharepoint_subscription_service.return_value = subscription_service

    with pytest.raises(HTTPException) as exc_info:
        await recreate_all_subscriptions(container=container)

    assert exc_info.value.status_code == 400
    assert "SHAREPOINT_WEBHOOK_CLIENT_STATE" in exc_info.value.detail
    subscription_repo.list_by_tenant.assert_not_awaited()
    subscription_service.recreate_expired_subscription.assert_not_awaited()


@pytest.mark.asyncio
async def test_deleting_the_app_removes_its_organization_connections_only():
    """The description promised personal OAuth tokens were deleted too."""
    app = MagicMock(id=uuid4())
    organization_connection = MagicMock(id=uuid4())
    container = MagicMock()
    tenant_app_service = container.tenant_sharepoint_app_service.return_value
    tenant_app_service.tenant_app_repo.get_by_tenant = AsyncMock(return_value=app)
    tenant_app_service.delete_app = AsyncMock(return_value=True)
    connections = container.user_integration_repo.return_value
    connections.query = AsyncMock(return_value=[organization_connection])
    connections.remove = AsyncMock()

    await delete_sharepoint_app(container=container)

    connections.query.assert_awaited_once_with(tenant_app_id=app.id)
    connections.remove.assert_awaited_once_with(id=organization_connection.id)
    (route,) = [
        route
        for route in router.routes
        if getattr(route, "endpoint", None) is delete_sharepoint_app
    ]
    assert "Personal SharePoint connections and their imports are kept" in (
        route.description
    )
    assert "oauth_tokens" not in route.description
