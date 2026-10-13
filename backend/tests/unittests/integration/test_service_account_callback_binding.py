import asyncio
import json
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from dependency_injector import providers
from fastapi import HTTPException

from eneo.integration.infrastructure.auth_service.service_account_auth_service import (
    ServiceAccountAuthService,
)
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
    monkeypatch.setattr(
        router,
        "_pop_oauth_state",
        AsyncMock(
            return_value={
                "tenant_id": str(user.tenant_id),
                "user_id": str(uuid4()),
                "client_id": "test-client",
                "client_secret": "test-secret",
                "tenant_domain": "example.onmicrosoft.com",
                "redirect_uri": "https://beta.example/integrations/callback/token/",
            }
        ),
    )
    container = Container(user=providers.Object(user))
    with pytest.raises(HTTPException) as error:
        await router.service_account_auth_callback(
            ServiceAccountAuthCallback(auth_code="test-code", state="test-state"),
            container,
        )
    assert error.value.status_code == 400
    provider.exchange_token.assert_not_awaited()


async def test_service_account_state_is_consumed_once_under_concurrent_callbacks(
    monkeypatch,
):
    payload = {"user_id": str(uuid4()), "tenant_id": str(uuid4())}
    states = {router.OAUTH_STATE_PREFIX + "state": json.dumps(payload)}
    redis = AsyncMock()
    redis.getdel.side_effect = lambda key: states.pop(key, None)
    monkeypatch.setattr(router, "_get_redis_client", AsyncMock(return_value=redis))
    results = await asyncio.gather(
        router._pop_oauth_state("state"), router._pop_oauth_state("state")
    )
    assert results.count(payload) == 1
    assert results.count(None) == 1
    assert states == {}
