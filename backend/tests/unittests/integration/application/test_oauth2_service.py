"""OAuth tenant isolation and CSRF contracts through the real HTTP/service flow."""

import json
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import httpx
import pytest
from dependency_injector import providers
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

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
from eneo.integration.presentation.models import AuthCallbackParams
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
    redis.get.side_effect = lambda key: states.get(key)
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
    if failure in ("other_user", "other_integration"):
        # A caller the state was not issued to cannot spend it.
        assert list(flow.states) == [key]
    else:
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


def _token_endpoint_error(status: int, body: dict[str, str]) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://login.example/token")
    response = httpx.Response(status, json=body, request=request)
    return httpx.HTTPStatusError("refused", request=request, response=response)


async def test_a_refused_code_is_a_400_the_person_can_act_on(oauth_flow):
    """An expired or reused code was a 500 from raise_for_status."""
    flow = oauth_flow
    flow.provider.exchange_token.side_effect = _token_endpoint_error(
        400,
        {
            "error": "invalid_grant",
            "error_description": "AADSTS70008: The provided authorization code "
            "has expired.\r\nTrace ID: 1f2e Correlation ID: 3a4b",
        },
    )
    started = await flow.client.get(f"/integrations/auth/{flow.own.id}/url/")

    response = await flow.client.post(
        "/integrations/auth/callback/token/",
        json={
            "tenant_integration_id": str(flow.own.id),
            "auth_code": "expired-code",
            "state": started.json()["state"],
        },
    )

    assert response.status_code == 400, response.text
    body = response.json()
    assert body["code"] == "oauth_code_rejected"
    assert "AADSTS70008" in body["message"]
    assert "Start the sign-in again" in body["message"]
    assert "Trace ID" not in body["message"]
    assert flow.tokens == []
    flow.audit.log_async.assert_not_awaited()


def _logged(log: MagicMock) -> str:
    return " ".join(
        str(call.args[0]) % call.args[1:] for call in log.warning.call_args_list
    )


async def test_a_refused_app_is_a_400_for_an_administrator(oauth_flow, monkeypatch):
    """A wrong or expired client secret is not fixed by signing in again."""
    flow = oauth_flow
    log = MagicMock()
    monkeypatch.setattr("eneo.integration.application.oauth2_service.logger", log)
    flow.provider.exchange_token.side_effect = _token_endpoint_error(
        401,
        {
            "error": "invalid_client",
            "error_description": "AADSTS7000215: Invalid client secret provided "
            "for app '11111111-2222-3333-4444-555555555555'. Trace ID: 1f",
        },
    )
    started = await flow.client.get(f"/integrations/auth/{flow.own.id}/url/")

    response = await flow.client.post(
        "/integrations/auth/callback/token/",
        json={
            "tenant_integration_id": str(flow.own.id),
            "auth_code": "test-code",
            "state": started.json()["state"],
        },
    )

    assert response.status_code == 400, response.text
    body = response.json()
    assert body["code"] == "oauth_client_rejected"
    assert "AADSTS7000215" in body["message"]
    assert "administrator" in body["message"]
    assert "11111111-2222" not in response.text
    assert "invalid_client AADSTS7000215" in _logged(log)
    assert "11111111-2222" not in _logged(log)


async def test_a_refused_code_names_no_account(oauth_flow, monkeypatch):
    flow = oauth_flow
    log = MagicMock()
    monkeypatch.setattr("eneo.integration.application.oauth2_service.logger", log)
    flow.provider.exchange_token.side_effect = _token_endpoint_error(
        400,
        {
            "error": "invalid_grant",
            "error_description": "AADSTS50034: The user account "
            "anna.svensson@sundsvall.se does not exist in the "
            "1a2b3c4d-0000-1111-2222-333344445555 directory.",
        },
    )
    started = await flow.client.get(f"/integrations/auth/{flow.own.id}/url/")

    response = await flow.client.post(
        "/integrations/auth/callback/token/",
        json={
            "tenant_integration_id": str(flow.own.id),
            "auth_code": "test-code",
            "state": started.json()["state"],
        },
    )

    assert response.json()["code"] == "oauth_code_rejected"
    assert "invalid_grant AADSTS50034" in _logged(log)
    for text in (response.text, _logged(log)):
        assert "anna.svensson" not in text
        assert "1a2b3c4d" not in text


@pytest.mark.parametrize(
    "status, body",
    [
        (503, {"error": "temporarily_unavailable"}),
        (429, {"error": "temporarily_unavailable"}),
        (400, {"error": "invalid_request", "error_description": "AADSTS900144"}),
    ],
    ids=["outage", "throttled", "malformed-request"],
)
async def test_a_token_endpoint_outage_is_not_reported_as_a_refused_code(
    oauth_flow, status, body
):
    flow = oauth_flow
    flow.provider.exchange_token.side_effect = _token_endpoint_error(status, body)
    started = await flow.client.get(f"/integrations/auth/{flow.own.id}/url/")

    with pytest.raises(httpx.HTTPStatusError):
        await flow.client.post(
            "/integrations/auth/callback/token/",
            json={
                "tenant_integration_id": str(flow.own.id),
                "auth_code": "test-code",
                "state": started.json()["state"],
            },
        )


async def test_a_mismatched_callback_leaves_the_state_to_its_owner(oauth_flow):
    flow = oauth_flow
    started = await flow.client.get(f"/integrations/auth/{flow.own.id}/url/")
    state = started.json()["state"]

    wrong = await flow.client.post(
        "/integrations/auth/callback/token/",
        json={
            "tenant_integration_id": str(uuid4()),
            "auth_code": "attacker-code",
            "state": state,
        },
    )
    right = await flow.client.post(
        "/integrations/auth/callback/token/",
        json={
            "tenant_integration_id": str(flow.own.id),
            "auth_code": "test-code",
            "state": state,
        },
    )

    assert wrong.status_code == 400
    assert right.status_code == 200, right.text
    assert flow.states == {}
    assert flow.provider.exchange_token.await_count == 1


def test_the_callback_state_is_bounded():
    with pytest.raises(ValidationError):
        AuthCallbackParams(
            auth_code="code", tenant_integration_id=uuid4(), state="s" * 257
        )
    assert AuthCallbackParams(
        auth_code="code", tenant_integration_id=uuid4(), state="s" * 43
    )
