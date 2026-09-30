"""Loopback MCP tool calls made on behalf of a service key.

A service key authenticates as a synthetic user with no ``users`` row. The
scoped token Eneo mints for its loopback servers must authenticate that
principal on the tool side, exactly like it authenticates a real user, and
must stop doing so once the key is no longer active. The token is good for
the loopback servers only: the rest of the API refuses it.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from eneo.authentication.auth_models import is_service_api_key
from eneo.internal_mcp.foundation import internal_tool_context
from eneo.main.exceptions import AuthenticationException
from tests.fixtures import mint_v2_api_key


def _loopback_ctx(token: str) -> SimpleNamespace:
    """The slice of a FastMCP ``Context`` the loopback foundation reads."""
    request = SimpleNamespace(headers={"authorization": f"Bearer {token}"})
    return SimpleNamespace(request_context=SimpleNamespace(request=request))


async def _create_service_key(client, *, token: str) -> UUID:
    resp = await client.post(
        "/api/v1/api-keys",
        json={
            "name": f"svc-key-{uuid4().hex[:8]}",
            "key_type": "sk_",
            "permission": "read",
            "scope_type": "tenant",
            "ownership": "service",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    return UUID(resp.json()["api_key"]["id"])


@pytest.fixture
async def admin_token(db_container, patch_auth_service_jwt, admin_user):
    async with db_container() as container:
        return container.auth_service().create_access_token_for_user(admin_user)


@pytest.fixture
async def service_principal_token(client, db_container, admin_user, admin_token):
    """A scoped loopback token minted for a service-key principal.

    Minted the way the ask path mints it: for the synthetic user that API-key
    authentication resolves the service key to.
    """
    key_id = await _create_service_key(client, token=admin_token)
    async with db_container() as container:
        key = await container.api_key_v2_repo().get(
            key_id=key_id, tenant_id=admin_user.tenant_id
        )
        assert key is not None
        principal = await container.user_service()._build_service_user(key)
        token = container.auth_service().create_scoped_mcp_token(
            principal, assistant_id=uuid4()
        )
    return SimpleNamespace(token=token, key_id=key_id, tenant_id=admin_user.tenant_id)


async def test_scoped_token_authenticates_the_service_principal(
    service_principal_token,
):
    ctx = _loopback_ctx(service_principal_token.token)

    async with internal_tool_context(ctx) as tool_context:
        assert tool_context.user.id == service_principal_token.key_id
        assert tool_context.user.tenant_id == service_principal_token.tenant_id
        assert is_service_api_key(tool_context.user)


async def test_scoped_token_is_refused_by_the_rest_of_the_api(
    client, service_principal_token
):
    resp = await client.get(
        "/api/v1/assistants/",
        headers={"Authorization": f"Bearer {service_principal_token.token}"},
    )

    assert resp.status_code == 401, resp.text


async def test_revoked_service_key_no_longer_authenticates(
    db_container, service_principal_token
):
    async with db_container() as container:
        await container.api_key_v2_repo().update(
            key_id=service_principal_token.key_id,
            tenant_id=service_principal_token.tenant_id,
            revoked_at=datetime.now(timezone.utc),
        )

    with pytest.raises(AuthenticationException):
        async with internal_tool_context(_loopback_ctx(service_principal_token.token)):
            pass


async def test_user_owned_key_id_is_not_a_principal(
    db_container, patch_auth_service_jwt, admin_user
):
    """Only service keys stand in for a missing users row."""
    async with db_container() as container:
        repo = container.api_key_v2_repo()
        minted = await mint_v2_api_key(
            repo, tenant_id=admin_user.tenant_id, user_id=admin_user.id
        )
        user_owned_key = await repo.get_by_hash(
            key_hash=hashlib.sha256(minted.key.encode()).hexdigest()
        )
        assert user_owned_key is not None
        impostor = admin_user.model_copy(update={"id": user_owned_key.id})
        token = container.auth_service().create_scoped_mcp_token(
            impostor, assistant_id=uuid4()
        )

    with pytest.raises(AuthenticationException):
        async with internal_tool_context(_loopback_ctx(token)):
            pass
