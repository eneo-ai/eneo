"""OAuth tenant isolation and CSRF contracts through the real HTTP/service flow."""

import json
from dataclasses import dataclass
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from dependency_injector import providers
from httpx import ASGITransport, AsyncClient

from eneo.integration.application.oauth2_service import Oauth2Service
from eneo.integration.domain.entities.oauth_token import OauthToken
from eneo.integration.domain.entities.tenant_integration import TenantIntegration
from eneo.integration.domain.entities.user_integration import UserIntegration
from eneo.integration.domain.repositories.oauth_token_repo import OauthTokenRepository
from eneo.integration.domain.repositories.tenant_integration_repo import (
    TenantIntegrationRepository,
)
from eneo.integration.domain.repositories.user_integration_repo import (
    UserIntegrationRepository,
)
from eneo.integration.infrastructure.auth_service.confluence_auth_service import (
    ConfluenceAuthService,
)
from eneo.integration.infrastructure.auth_service.sharepoint_auth_service import (
    SharepointAuthService,
)
from eneo.main.config import set_settings
from eneo.main.container.container import Container
from eneo.main.exceptions import NotFoundException
from eneo.roles.permissions import Permission


@dataclass
class OAuthFlow:
    client: AsyncClient
    service: Oauth2Service
    own: TenantIntegration
    foreign: TenantIntegration
    provider: AsyncMock
    unused_provider: AsyncMock
    states: dict[str, str | bytes]
    connections: list[UserIntegration]
    tokens: list[OauthToken]
    audit: AsyncMock


@pytest.fixture(params=["sharepoint", "confluence"])
async def oauth_flow(
    request, integration_access, authenticated_integration_app, test_settings
):
    set_settings(
        test_settings.model_copy(
            update={
                "oauth_callback_url": "https://app.example/integrations/callback/token/",
                "oauth_callback_urls": [
                    "https://beta.example/integrations/callback/token/"
                ],
            }
        )
    )
    case = integration_access
    own = case.integration.tenant_integration
    own.integration.integration_type = request.param
    foreign = TenantIntegration(tenant_id=uuid4(), integration=own.integration)
    tenant_repo = AsyncMock(spec=TenantIntegrationRepository)

    async def find_integration(
        id: UUID | None = None, *, tenant_id: UUID | None = None
    ):
        for integration in (own, foreign):
            if integration.id == id and (
                tenant_id is None or integration.tenant_id == tenant_id
            ):
                return integration
        raise NotFoundException("Integration not found")

    tenant_repo.one.side_effect = find_integration
    connections: list[UserIntegration] = []
    tokens: list[OauthToken] = []
    connection_repo = AsyncMock(spec=UserIntegrationRepository)
    token_repo = AsyncMock(spec=OauthTokenRepository)

    async def find_connection(
        *, user_id: UUID, tenant_integration_id: UUID, authenticated: bool
    ):
        return next(
            (
                item
                for item in connections
                if item.user_id == user_id
                and item.tenant_integration.id == tenant_integration_id
                and item.authenticated == authenticated
            ),
            None,
        )

    async def add_connection(obj: UserIntegration):
        connections.append(obj)
        return obj

    async def add_token(obj: OauthToken):
        tokens.append(obj)
        return obj

    connection_repo.one_or_none.side_effect = find_connection
    connection_repo.add.side_effect = add_connection
    token_repo.add.side_effect = add_token
    states: dict[str, str | bytes] = {}
    redis = AsyncMock()

    async def store_state(key: str, value: str, *, ex: int):
        states[key] = value.encode("utf-8")

    redis.set.side_effect = store_state
    redis.getdel.side_effect = lambda key: states.pop(key, None)
    sharepoint = AsyncMock(spec=SharepointAuthService)
    confluence = AsyncMock(spec=ConfluenceAuthService)
    provider, unused_provider = (
        (sharepoint, confluence)
        if request.param == "sharepoint"
        else (confluence, sharepoint)
    )
    provider.gen_auth_url.return_value = {
        "auth_url": "https://provider.example/authorize"
    }
    provider.exchange_token.return_value = {
        "access_token": "test-access-token",
        "refresh_token": "test-refresh-token",
    }
    provider.get_resources.return_value = []
    audit = AsyncMock()
    container = Container(
        user=providers.Object(case.user),
        tenant_integration_repo=providers.Object(tenant_repo),
        user_integration_repo=providers.Object(connection_repo),
        oauth_token_repo=providers.Object(token_repo),
        redis_client=providers.Object(redis),
        sharepoint_auth_service=providers.Object(sharepoint),
        confluence_auth_service=providers.Object(confluence),
        audit_service=providers.Object(audit),
    )
    app = authenticated_integration_app(container)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield OAuthFlow(
            client,
            container.oauth2_service(),
            own,
            foreign,
            provider,
            unused_provider,
            states,
            connections,
            tokens,
            audit,
        )


async def test_personal_oauth_completes_in_own_tenant_and_state_cannot_be_replayed(
    oauth_flow,
):
    flow = oauth_flow
    assert Permission.ADMIN not in flow.service.user.permissions
    started = await flow.client.get(f"/integrations/auth/{flow.own.id}/url/")
    assert started.status_code == 200
    assert started.json()["auth_url"] == "https://provider.example/authorize"
    state = started.json()["state"]
    assert json.loads(next(iter(flow.states.values()))) == {
        "user_id": str(flow.service.user.id),
        "tenant_integration_id": str(flow.own.id),
        "redirect_uri": "https://app.example/integrations/callback/token/",
    }
    body = {
        "tenant_integration_id": str(flow.own.id),
        "auth_code": "test-code",
        "state": state,
    }
    response = await flow.client.post("/integrations/auth/callback/token/", json=body)

    assert response.status_code == 200
    assert response.json()["tenant_integration_id"] == str(flow.own.id)
    assert len(flow.connections) == len(flow.tokens) == 1
    assert flow.connections[0].user_id == flow.service.user.id
    assert (
        flow.connections[0].tenant_integration.tenant_id == flow.service.user.tenant_id
    )
    assert flow.tokens[0].user_integration is flow.connections[0]
    assert flow.tokens[0].access_token == "test-access-token"
    assert flow.states == {}
    if flow.own.integration_type == "sharepoint":
        flow.provider.gen_auth_url.assert_awaited_once_with(
            state,
            tenant_id=flow.service.user.tenant_id,
            redirect_uri="https://app.example/integrations/callback/token/",
        )
        flow.provider.exchange_token.assert_awaited_once_with(
            "test-code",
            tenant_id=flow.service.user.tenant_id,
            redirect_uri="https://app.example/integrations/callback/token/",
        )
    else:
        flow.provider.gen_auth_url.assert_awaited_once_with(
            state, redirect_uri="https://app.example/integrations/callback/token/"
        )
        flow.provider.exchange_token.assert_awaited_once_with(
            "test-code", redirect_uri="https://app.example/integrations/callback/token/"
        )
    flow.unused_provider.gen_auth_url.assert_not_awaited()
    flow.unused_provider.exchange_token.assert_not_awaited()

    replay = await flow.client.post("/integrations/auth/callback/token/", json=body)
    assert replay.status_code == 400
    assert len(flow.connections) == len(flow.tokens) == 1
    assert flow.provider.exchange_token.await_count == 1
    assert flow.audit.log_async.await_count == 1


async def test_existing_own_connection_is_preserved(oauth_flow, integration_access):
    flow = oauth_flow
    flow.connections.append(integration_access.integration)
    started = await flow.client.get(f"/integrations/auth/{flow.own.id}/url/")
    response = await flow.client.post(
        "/integrations/auth/callback/token/",
        json={
            "tenant_integration_id": str(flow.own.id),
            "auth_code": "test-code",
            "state": started.json()["state"],
        },
    )
    assert response.status_code == 200
    assert response.json()["id"] == str(integration_access.integration.id)
    assert flow.connections == [integration_access.integration]
    assert flow.tokens == []
    flow.provider.exchange_token.assert_not_awaited()


@pytest.mark.parametrize("endpoint", ["url", "callback"])
@pytest.mark.parametrize("target", ["foreign", "unknown"])
@pytest.mark.parametrize("is_admin", [False, True])
async def test_foreign_and_unknown_integrations_are_rejected_before_provider_or_writes(
    oauth_flow, endpoint, target, is_admin
):
    flow = oauth_flow
    if is_admin:
        flow.service.user.roles[0].permissions.append(Permission.ADMIN)
    id = flow.foreign.id if target == "foreign" else uuid4()
    if endpoint == "url":
        response = await flow.client.get(f"/integrations/auth/{id}/url/")
    else:
        # A correctly bound state issued before the fix must not authorize a
        # foreign integration. The callback must independently check its tenant.
        state = "issued-before-fix"
        flow.states[f"integration:oauth_state:{state}"] = json.dumps(
            {"user_id": str(flow.service.user.id), "tenant_integration_id": str(id)}
        )
        response = await flow.client.post(
            "/integrations/auth/callback/token/",
            json={
                "tenant_integration_id": str(id),
                "auth_code": "test-code",
                "state": state,
            },
        )
    assert response.status_code == 404
    assert flow.states == {}
    assert flow.connections == []
    assert flow.tokens == []
    for provider in (flow.provider, flow.unused_provider):
        provider.gen_auth_url.assert_not_awaited()
        provider.exchange_token.assert_not_awaited()
        provider.get_resources.assert_not_awaited()
    flow.audit.log_async.assert_not_awaited()


@pytest.mark.parametrize(
    "failure", ["expired", "other_user", "other_integration", "corrupt"]
)
async def test_invalid_state_still_rejects_callback_without_writes(oauth_flow, failure):
    flow = oauth_flow
    started = await flow.client.get(f"/integrations/auth/{flow.own.id}/url/")
    state = started.json()["state"]
    key = f"integration:oauth_state:{state}"
    if failure == "expired":
        flow.states.clear()
    elif failure == "corrupt":
        flow.states[key] = "not-json"
    else:
        flow.states[key] = json.dumps(
            {
                "user_id": str(
                    uuid4() if failure == "other_user" else flow.service.user.id
                ),
                "tenant_integration_id": str(
                    uuid4() if failure == "other_integration" else flow.own.id
                ),
            }
        )
    response = await flow.client.post(
        "/integrations/auth/callback/token/",
        json={
            "tenant_integration_id": str(flow.own.id),
            "auth_code": "test-code",
            "state": state,
        },
    )
    assert response.status_code == 400
    assert flow.states == {}
    assert flow.connections == []
    assert flow.tokens == []
    flow.provider.exchange_token.assert_not_awaited()
    flow.audit.log_async.assert_not_awaited()


async def test_callback_does_not_reuse_existing_foreign_connection(oauth_flow):
    flow = oauth_flow
    existing = UserIntegration(
        user_id=flow.service.user.id,
        tenant_integration=flow.foreign,
        authenticated=True,
    )
    flow.connections.append(existing)
    flow.states["integration:oauth_state:old-state"] = json.dumps(
        {
            "user_id": str(flow.service.user.id),
            "tenant_integration_id": str(flow.foreign.id),
        }
    )
    response = await flow.client.post(
        "/integrations/auth/callback/token/",
        json={
            "tenant_integration_id": str(flow.foreign.id),
            "auth_code": "test-code",
            "state": "old-state",
        },
    )
    assert response.status_code == 404
    assert flow.connections == [existing]
    assert flow.tokens == []
    flow.provider.exchange_token.assert_not_awaited()
    flow.audit.log_async.assert_not_awaited()


async def test_registered_beta_callback_survives_the_entire_oauth_flow(oauth_flow):
    flow = oauth_flow
    callback = "https://beta.example/integrations/callback/token/"
    started = await flow.client.get(
        f"/integrations/auth/{flow.own.id}/url/", params={"redirect_uri": callback}
    )
    assert started.status_code == 200
    assert flow.provider.gen_auth_url.call_args.kwargs["redirect_uri"] == callback
    response = await flow.client.post(
        "/integrations/auth/callback/token/",
        json={
            "tenant_integration_id": str(flow.own.id),
            "auth_code": "test-code",
            "state": started.json()["state"],
        },
    )
    assert response.status_code == 200
    assert flow.provider.exchange_token.call_args.kwargs["redirect_uri"] == callback
    assert flow.states == {}


@pytest.mark.parametrize(
    "callback",
    [
        "https://attacker.example/integrations/callback/token/",
        "https://beta.example.attacker.example/integrations/callback/token/",
        "https://beta.example/integrations/callback/token/?redirect=evil",
        "https://beta.example/integrations/callback/token",
    ],
)
async def test_unregistered_callback_is_rejected_before_oauth_starts(
    oauth_flow, callback
):
    flow = oauth_flow
    response = await flow.client.get(
        f"/integrations/auth/{flow.own.id}/url/", params={"redirect_uri": callback}
    )
    assert response.status_code == 400
    assert flow.states == {}
    flow.provider.gen_auth_url.assert_not_awaited()
