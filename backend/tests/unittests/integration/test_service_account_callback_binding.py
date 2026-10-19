import asyncio
import json
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx
import pytest
from dependency_injector import providers
from fastapi import HTTPException
from pydantic import ValidationError

from eneo.integration.infrastructure.auth_service.base_auth_service import (
    OAuthClientRejectedError,
    OAuthCodeRejectedError,
)
from eneo.integration.infrastructure.auth_service.service_account_auth_service import (
    ServiceAccountAuthService,
)
from eneo.integration.infrastructure.oauth_state_store import OauthStateStore
from eneo.integration.presentation import admin_sharepoint_router as router
from eneo.integration.presentation.admin_models import ServiceAccountAuthCallback
from eneo.main.config import set_settings
from eneo.main.container.container import Container


async def test_service_account_callback_rejects_another_user_in_same_tenant(
    integration_access, test_settings, monkeypatch
):
    user = integration_access.user
    set_settings(
        test_settings.model_copy(
            update={"sharepoint_webhook_client_state": "test-webhook-state"}
        )
    )
    provider = AsyncMock(spec=ServiceAccountAuthService)
    monkeypatch.setattr(router, "ServiceAccountAuthService", lambda: provider)
    state_store = MagicMock()
    state_store.peek = AsyncMock(
        return_value={
            "tenant_id": str(user.tenant_id),
            "user_id": str(uuid4()),
            "client_id": "test-client",
            "client_secret": "test-secret",
            "tenant_domain": "example.onmicrosoft.com",
            "redirect_uri": "https://beta.example/integrations/callback/token/",
        }
    )
    state_store.pop = AsyncMock()
    monkeypatch.setattr(router, "_oauth_state_store", lambda container: state_store)
    container = Container(user=providers.Object(user))
    with pytest.raises(HTTPException) as error:
        await router.service_account_auth_callback(
            ServiceAccountAuthCallback(auth_code="test-code", state="test-state"),
            container,
        )
    assert error.value.status_code == 400
    provider.exchange_token.assert_not_awaited()
    # The admin who started the sign-in can still finish it.
    state_store.pop.assert_not_awaited()


async def test_service_account_state_is_consumed_once_under_concurrent_callbacks():
    payload = {"user_id": str(uuid4()), "tenant_id": str(uuid4())}
    states = {router.OAUTH_STATE_PREFIX + "state": "sealed"}
    redis = AsyncMock()
    redis.getdel.side_effect = lambda key: states.pop(key, None)
    encryption = MagicMock()
    encryption.decrypt.return_value = json.dumps(payload)
    store = OauthStateStore(
        redis, prefix=router.OAUTH_STATE_PREFIX, encryption_service=encryption
    )
    results = await asyncio.gather(store.pop("state"), store.pop("state"))
    assert results.count(payload) == 1
    assert results.count(None) == 1
    assert states == {}


def test_service_account_callback_state_is_bounded():
    with pytest.raises(ValidationError):
        ServiceAccountAuthCallback(auth_code="code", state="s" * 257)
    assert ServiceAccountAuthCallback(auth_code="code", state="s" * 43)


async def test_a_refused_service_account_code_is_a_400_not_a_500(
    integration_access, test_settings, monkeypatch
):
    user = integration_access.user
    set_settings(
        test_settings.model_copy(
            update={"sharepoint_webhook_client_state": "test-webhook-state"}
        )
    )
    request = httpx.Request("POST", "https://login.microsoftonline.com/x/token")
    provider = AsyncMock(spec=ServiceAccountAuthService)
    provider.exchange_token.side_effect = httpx.HTTPStatusError(
        "refused",
        request=request,
        response=httpx.Response(
            400,
            json={
                "error": "invalid_grant",
                "error_description": "AADSTS54005: OAuth2 Authorization code "
                "was already redeemed. Trace ID: 1f2e",
            },
            request=request,
        ),
    )
    monkeypatch.setattr(router, "ServiceAccountAuthService", lambda: provider)
    state_store = MagicMock()
    state_store.peek = AsyncMock(
        return_value={
            "tenant_id": str(user.tenant_id),
            "user_id": str(user.id),
            "client_id": "test-client",
            "client_secret": "test-secret",
            "tenant_domain": "example.onmicrosoft.com",
            "redirect_uri": "https://beta.example/integrations/callback/token/",
        }
    )
    state_store.pop = AsyncMock(return_value=state_store.peek.return_value)
    monkeypatch.setattr(router, "_oauth_state_store", lambda container: state_store)
    tenant_app_service = AsyncMock()
    container = Container(
        user=providers.Object(user),
        tenant_sharepoint_app_service=providers.Object(tenant_app_service),
    )

    with pytest.raises(OAuthCodeRejectedError) as error:
        await router.service_account_auth_callback(
            ServiceAccountAuthCallback(auth_code="used-code", state="test-state"),
            container,
        )

    assert error.value.code == "oauth_code_rejected"
    assert "AADSTS54005" in str(error.value)
    assert "Trace ID" not in str(error.value)
    tenant_app_service.configure_service_account.assert_not_awaited()


async def test_a_refused_service_account_secret_is_its_own_400(
    integration_access, test_settings, monkeypatch
):
    user = integration_access.user
    set_settings(
        test_settings.model_copy(
            update={"sharepoint_webhook_client_state": "test-webhook-state"}
        )
    )
    request = httpx.Request("POST", "https://login.microsoftonline.com/x/token")
    provider = AsyncMock(spec=ServiceAccountAuthService)
    provider.exchange_token.side_effect = httpx.HTTPStatusError(
        "refused",
        request=request,
        response=httpx.Response(
            401,
            json={
                "error": "invalid_client",
                "error_description": "AADSTS7000215: Invalid client secret.",
            },
            request=request,
        ),
    )
    monkeypatch.setattr(router, "ServiceAccountAuthService", lambda: provider)
    stored = {
        "tenant_id": str(user.tenant_id),
        "user_id": str(user.id),
        "client_id": "test-client",
        "client_secret": "wrong-secret",
        "tenant_domain": "example.onmicrosoft.com",
    }
    state_store = MagicMock()
    state_store.peek = AsyncMock(return_value=stored)
    state_store.pop = AsyncMock(return_value=stored)
    monkeypatch.setattr(router, "_oauth_state_store", lambda container: state_store)
    container = Container(
        user=providers.Object(user),
        tenant_sharepoint_app_service=providers.Object(AsyncMock()),
    )

    with pytest.raises(OAuthClientRejectedError) as error:
        await router.service_account_auth_callback(
            ServiceAccountAuthCallback(auth_code="code", state="test-state"),
            container,
        )

    assert error.value.code == "oauth_client_rejected"
    assert "AADSTS7000215" in str(error.value)
