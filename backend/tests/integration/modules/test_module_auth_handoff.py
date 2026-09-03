import asyncio
import contextlib
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.types import Message, Receive, Scope, Send

from eneo.authentication.auth_models import (
    ApiKeyHashVersion,
    ApiKeyOwnership,
    ApiKeyPermission,
    ApiKeyScopeType,
    ApiKeyState,
    ApiKeyType,
)
from eneo.database.database import get_session_with_transaction
from eneo.modules.module import ModuleCreate
from eneo.tenants.tenant import TenantBase
from eneo.users.user import UserAdd, UserState

pytestmark = pytest.mark.integration

REDIRECT_URI = "https://module.example.com/auth/callback"
UPDATED_REDIRECT_URI = "https://module.example.com/login/callback"


async def _request_at_transaction_boundary(
    app: FastAPI,
    *,
    method: str,
    path: str,
    payload: dict[str, object],
    headers: dict[str, str],
) -> Response:
    """Run a real route while holding transaction teardown at the ASGI edge."""
    response_started = asyncio.Event()
    teardown_started = asyncio.Event()
    release_teardown = asyncio.Event()

    async def blocked_transaction_teardown() -> AsyncIterator[AsyncSession]:
        async for session in get_session_with_transaction():
            try:
                yield session
            finally:
                teardown_started.set()
                await release_teardown.wait()

    async def record_response_start(
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        async def recording_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_started.set()
            await send(message)

        await app(scope, receive, recording_send)

    assert get_session_with_transaction not in app.dependency_overrides
    app.dependency_overrides[get_session_with_transaction] = (
        blocked_transaction_teardown
    )
    request_task: asyncio.Task[Response] | None = None
    try:
        async with AsyncClient(
            transport=ASGITransport(app=record_response_start),
            base_url="http://test.local",
        ) as boundary_client:
            request_task = asyncio.create_task(
                boundary_client.request(
                    method,
                    path,
                    json=payload,
                    headers=headers,
                )
            )
            try:
                await asyncio.wait_for(teardown_started.wait(), timeout=10)
                assert not response_started.is_set()
            finally:
                release_teardown.set()

            return await asyncio.wait_for(request_task, timeout=10)
    finally:
        release_teardown.set()
        if request_task is not None and not request_task.done():
            with contextlib.suppress(Exception):
                await request_task
        app.dependency_overrides.pop(get_session_with_transaction, None)


@pytest.fixture
async def admin_token(db_container, patch_auth_service_jwt, admin_user) -> str:
    async with db_container() as container:
        return container.auth_service().create_access_token_for_user(admin_user)


@pytest.fixture
async def enabled_module(db_container, admin_user):
    async with db_container() as container:
        module = await container.module_repo().add(
            ModuleCreate(name=f"module-{uuid4().hex[:12]}")
        )
        await container.tenant_repo().enable_module(
            tenant_id=admin_user.tenant_id, module_id=module.id
        )
        return module


async def create_api_key(
    client,
    *,
    token: str,
    ownership: ApiKeyOwnership,
    permission: ApiKeyPermission,
) -> dict:
    body: dict[str, object] = {
        "name": f"module-key-{uuid4().hex[:8]}",
        "key_type": ApiKeyType.SK.value,
        "ownership": ownership.value,
        "permission": permission.value,
        "scope_type": ApiKeyScopeType.TENANT.value,
    }
    if ownership == ApiKeyOwnership.SERVICE and permission != ApiKeyPermission.READ:
        body["expires_at"] = (
            datetime.now(timezone.utc) + timedelta(days=7)
        ).isoformat()

    response = await client.post(
        "/api/v1/api-keys",
        json=body,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def module_installation_path(module_key: str) -> str:
    return f"/api/v1/admin/modules/{module_key}/"


@pytest.mark.asyncio
async def test_ticket_request_uses_exact_public_module_key(
    client,
    admin_token,
    enabled_module,
):
    headers = {"Authorization": f"Bearer {admin_token}"}

    legacy_id = await client.post(
        "/api/v1/module-auth/tickets/",
        json={
            "module_id": str(enabled_module.id),
            "redirect_uri": REDIRECT_URI,
        },
        headers=headers,
    )
    assert legacy_id.status_code == 422, legacy_id.text

    for unknown_key in (enabled_module.name.upper(), f"unknown-{uuid4().hex}"):
        unknown = await client.post(
            "/api/v1/module-auth/tickets/",
            json={
                "module_key": unknown_key,
                "redirect_uri": REDIRECT_URI,
            },
            headers=headers,
        )
        assert unknown.status_code == 404, unknown.text

    exact_key = await client.post(
        "/api/v1/module-auth/tickets/",
        json={
            "module_key": enabled_module.name,
            "redirect_uri": REDIRECT_URI,
        },
        headers=headers,
    )
    # The exact key resolves the enabled module and reaches the deliberately
    # incomplete client config instead of falling through as unknown.
    assert exact_key.status_code == 400, exact_key.text


@pytest.mark.asyncio
async def test_ticket_rejects_module_not_enabled_for_callers_tenant(
    client,
    db_container,
    admin_token,
):
    async with db_container() as container:
        other_module = await container.module_repo().add(
            ModuleCreate(name=f"unassigned-{uuid4().hex[:12]}")
        )

    response = await client.post(
        "/api/v1/module-auth/tickets/",
        json={
            "module_key": other_module.name,
            "redirect_uri": REDIRECT_URI,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 403, response.text


@pytest.mark.asyncio
async def test_complete_reconfiguration_and_full_handoff_succeeds(
    app,
    client,
    admin_token,
    admin_user,
    enabled_module,
):
    service_key = await create_api_key(
        client,
        token=admin_token,
        ownership=ApiKeyOwnership.SERVICE,
        permission=ApiKeyPermission.WRITE,
    )
    service_key_id = service_key["api_key"]["id"]
    config_path = module_installation_path(enabled_module.name)
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    initial = await client.put(
        config_path,
        json={
            "redirect_uris": [REDIRECT_URI],
            "service_key_id": service_key_id,
        },
        headers=admin_headers,
    )
    assert initial.status_code == 200, initial.text

    partial = await _request_at_transaction_boundary(
        app,
        method="PUT",
        path=config_path,
        payload={
            "redirect_uris": [UPDATED_REDIRECT_URI],
            "service_key_id": service_key_id,
        },
        headers=admin_headers,
    )
    assert partial.status_code == 200, partial.text
    assert partial.json()["service_key_id"] == service_key_id

    # This is a new HTTP request and therefore a separate database session. It
    # must observe the PUT commit immediately, before any response is exposed.
    ticket_response = await _request_at_transaction_boundary(
        app,
        method="POST",
        path="/api/v1/module-auth/tickets/",
        payload={
            "module_key": enabled_module.name,
            "redirect_uri": UPDATED_REDIRECT_URI,
            "state": "module-csrf-binding-123",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert ticket_response.status_code == 201, ticket_response.text
    ticket_body = ticket_response.json()
    # redirect_target is the ticket's only carrier - the raw ticket must not
    # appear as a field of its own.
    assert "ticket" not in ticket_body
    redirect_target = ticket_body["redirect_target"]
    assert redirect_target.startswith(UPDATED_REDIRECT_URI + "?ticket=")
    assert redirect_target.endswith("&state=module-csrf-binding-123")
    ticket = parse_qs(urlparse(redirect_target).query)["ticket"][0]

    exchange = await _request_at_transaction_boundary(
        app,
        method="POST",
        path="/api/v1/module-auth/token/",
        payload={"ticket": ticket},
        headers={"X-API-Key": service_key["secret"]},
    )
    assert exchange.status_code == 200, exchange.text
    assert exchange.json()["tenant_id"] == str(admin_user.tenant_id)
    assert exchange.json()["module_key"] == enabled_module.name

    replay = await client.post(
        "/api/v1/module-auth/token/",
        json={"ticket": ticket},
        headers={"X-API-Key": service_key["secret"]},
    )
    assert replay.status_code == 401, replay.text


@pytest.mark.asyncio
async def test_token_refresh_slides_window_inside_fixed_session_ceiling(
    client,
    admin_token,
    enabled_module,
):
    service_key = await create_api_key(
        client,
        token=admin_token,
        ownership=ApiKeyOwnership.SERVICE,
        permission=ApiKeyPermission.WRITE,
    )
    config = await client.put(
        module_installation_path(enabled_module.name),
        json={
            "redirect_uris": [REDIRECT_URI],
            "service_key_id": service_key["api_key"]["id"],
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert config.status_code == 200, config.text

    ticket_response = await client.post(
        "/api/v1/module-auth/tickets/",
        json={
            "module_key": enabled_module.name,
            "redirect_uri": REDIRECT_URI,
            "state": "module-csrf-binding-refresh",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert ticket_response.status_code == 201, ticket_response.text
    ticket = parse_qs(urlparse(ticket_response.json()["redirect_target"]).query)[
        "ticket"
    ][0]

    exchange = await client.post(
        "/api/v1/module-auth/token/",
        json={"ticket": ticket},
        headers={"X-API-Key": service_key["secret"]},
    )
    assert exchange.status_code == 200, exchange.text
    exchanged = exchange.json()
    assert exchanged["session_expires_at"] is not None

    refresh_path = f"/api/v1/module-auth/{enabled_module.name}/token/refresh/"
    refresh = await client.post(
        refresh_path,
        headers={
            "Authorization": f"Bearer {exchanged['access_token']}",
            "X-API-Key": service_key["secret"],
        },
    )
    assert refresh.status_code == 200, refresh.text
    refreshed = refresh.json()
    # The ceiling is anchored at the original exchange and must not slide.
    assert refreshed["session_expires_at"] == exchanged["session_expires_at"]
    assert refreshed["module_key"] == enabled_module.name
    assert refreshed["expires_in"] > 0

    session = await client.get(
        f"/api/v1/module-auth/{enabled_module.name}/session/",
        headers={
            "Authorization": f"Bearer {refreshed['access_token']}",
            "X-API-Key": service_key["secret"],
        },
    )
    assert session.status_code == 200, session.text

    missing_bearer = await client.post(
        refresh_path,
        headers={"X-API-Key": service_key["secret"]},
    )
    assert missing_bearer.status_code == 401, missing_bearer.text


@pytest.mark.asyncio
async def test_client_config_rejects_revoked_key_and_preserves_prior_binding(
    client,
    db_container,
    admin_token,
    admin_user,
    enabled_module,
):
    """A dead key must be refused at binding time, not discovered at login.

    A key revoked after a valid binding still fails at ticket exchange with
    401 - that runtime path is owned by normal API-key authentication.
    """
    active_key = await create_api_key(
        client,
        token=admin_token,
        ownership=ApiKeyOwnership.SERVICE,
        permission=ApiKeyPermission.WRITE,
    )
    config_path = module_installation_path(enabled_module.name)
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    initial = await client.put(
        config_path,
        json={
            "redirect_uris": [REDIRECT_URI],
            "service_key_id": active_key["api_key"]["id"],
        },
        headers=admin_headers,
    )
    assert initial.status_code == 200, initial.text

    revoked_key = await create_api_key(
        client,
        token=admin_token,
        ownership=ApiKeyOwnership.SERVICE,
        permission=ApiKeyPermission.WRITE,
    )
    revoke = await client.post(
        f"/api/v1/api-keys/{revoked_key['api_key']['id']}/revoke",
        json={"reason_code": "security_concern", "reason_text": "Test revocation"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert revoke.status_code == 200, revoke.text

    rejected = await client.put(
        config_path,
        json={
            "redirect_uris": [REDIRECT_URI],
            "service_key_id": revoked_key["api_key"]["id"],
        },
        headers=admin_headers,
    )
    assert rejected.status_code == 400, rejected.text
    assert "revoked" in rejected.json()["message"].lower()

    async with db_container() as container:
        preserved = await container.module_repo().get_module_client_config(
            tenant_id=admin_user.tenant_id, module_id=enabled_module.id
        )
    assert preserved is not None
    assert str(preserved.service_key_id) == active_key["api_key"]["id"]

    # Revocation after a valid binding keeps failing at exchange with 401.
    ticket_response = await client.post(
        "/api/v1/module-auth/tickets/",
        json={"module_key": enabled_module.name, "redirect_uri": REDIRECT_URI},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert ticket_response.status_code == 201, ticket_response.text
    ticket = parse_qs(urlparse(ticket_response.json()["redirect_target"]).query)[
        "ticket"
    ][0]
    late_revoke = await client.post(
        f"/api/v1/api-keys/{active_key['api_key']['id']}/revoke",
        json={"reason_code": "security_concern", "reason_text": "Post-binding"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert late_revoke.status_code == 200, late_revoke.text

    exchange = await client.post(
        "/api/v1/module-auth/token/",
        json={"ticket": ticket},
        headers={"X-API-Key": active_key["secret"]},
    )
    assert exchange.status_code == 401, exchange.text


@pytest.mark.asyncio
async def test_stale_module_token_rejected_after_email_moves_to_replacement_account(
    client,
    db_container,
    patch_auth_service_jwt,
    admin_token,
    admin_user,
    enabled_module,
):
    """A module token must die with the account it was minted for.

    The active-email unique index excludes soft-deleted users, so an email can
    be re-assigned to a replacement account while an old module token is still
    inside its lifetime. That token must not authenticate as the replacement.
    """
    service_key = await create_api_key(
        client,
        token=admin_token,
        ownership=ApiKeyOwnership.SERVICE,
        permission=ApiKeyPermission.WRITE,
    )
    config = await client.put(
        module_installation_path(enabled_module.name),
        json={
            "redirect_uris": [REDIRECT_URI],
            "service_key_id": service_key["api_key"]["id"],
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert config.status_code == 200, config.text

    email = f"module-rebind-{uuid4().hex[:8]}@example.com"
    async with db_container() as container:
        original = await container.user_repo().add(
            UserAdd(
                email=email,
                username=f"module-rebind-{uuid4().hex[:8]}",
                state=UserState.ACTIVE,
                tenant_id=admin_user.tenant_id,
            )
        )
        original_token = container.auth_service().create_access_token_for_user(original)

    ticket_response = await client.post(
        "/api/v1/module-auth/tickets/",
        json={"module_key": enabled_module.name, "redirect_uri": REDIRECT_URI},
        headers={"Authorization": f"Bearer {original_token}"},
    )
    assert ticket_response.status_code == 201, ticket_response.text
    ticket = parse_qs(urlparse(ticket_response.json()["redirect_target"]).query)[
        "ticket"
    ][0]

    exchange = await client.post(
        "/api/v1/module-auth/token/",
        json={"ticket": ticket},
        headers={"X-API-Key": service_key["secret"]},
    )
    assert exchange.status_code == 200, exchange.text
    module_headers = {
        "Authorization": f"Bearer {exchange.json()['access_token']}",
        "X-API-Key": service_key["secret"],
    }
    session_path = f"/api/v1/module-auth/{enabled_module.name}/session/"

    live = await client.get(session_path, headers=module_headers)
    assert live.status_code == 200, live.text
    assert live.json()["user"]["id"] == str(original.id)

    # Soft-delete frees the email for a replacement account with a new id.
    async with db_container() as container:
        await container.user_repo().delete(original.id)
        replacement = await container.user_repo().add(
            UserAdd(
                email=email,
                username=f"module-rebind-replacement-{uuid4().hex[:8]}",
                state=UserState.ACTIVE,
                tenant_id=admin_user.tenant_id,
            )
        )
    assert replacement.id != original.id

    stale_session = await client.get(session_path, headers=module_headers)
    assert stale_session.status_code == 401, stale_session.text

    stale_refresh = await client.post(
        f"/api/v1/module-auth/{enabled_module.name}/token/refresh/",
        headers=module_headers,
    )
    assert stale_refresh.status_code == 401, stale_refresh.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("ownership", "permission"),
    [
        (ApiKeyOwnership.USER, ApiKeyPermission.WRITE),
        (ApiKeyOwnership.SERVICE, ApiKeyPermission.READ),
    ],
)
async def test_module_installation_rejects_key_that_cannot_exchange(
    client,
    admin_token,
    enabled_module,
    ownership,
    permission,
):
    api_key = await create_api_key(
        client,
        token=admin_token,
        ownership=ownership,
        permission=permission,
    )

    response = await client.put(
        module_installation_path(enabled_module.name),
        json={
            "redirect_uris": [REDIRECT_URI],
            "service_key_id": api_key["api_key"]["id"],
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 400, response.text


@pytest.mark.asyncio
async def test_module_installation_rejects_key_from_another_tenant(
    client,
    db_container,
    admin_token,
    admin_user,
    enabled_module,
):
    async with db_container() as container:
        other_tenant = await container.tenant_repo().add(
            TenantBase(name=f"other-tenant-{uuid4().hex[:8]}")
        )
        assert other_tenant is not None
        other_key = await container.api_key_v2_repo().create(
            tenant_id=other_tenant.id,
            ownership=ApiKeyOwnership.SERVICE.value,
            owner_user_id=None,
            created_by_user_id=None,
            scope_type=ApiKeyScopeType.TENANT.value,
            scope_id=None,
            permission=ApiKeyPermission.WRITE.value,
            key_type=ApiKeyType.SK.value,
            key_hash=uuid4().hex,
            hash_version=ApiKeyHashVersion.HMAC_SHA256.value,
            key_prefix=ApiKeyType.SK.value,
            key_suffix=uuid4().hex[-8:],
            name="other tenant module key",
            state=ApiKeyState.ACTIVE.value,
        )

    response = await client.put(
        module_installation_path(enabled_module.name),
        json={
            "redirect_uris": [REDIRECT_URI],
            "service_key_id": str(other_key.id),
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 400, response.text


@pytest.mark.asyncio
async def test_incomplete_module_installation_is_rejected(
    client,
    admin_token,
    enabled_module,
):
    response = await client.put(
        module_installation_path(enabled_module.name),
        json={},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 422, response.text
