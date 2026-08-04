from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from eneo.authentication.auth_models import (
    ApiKeyHashVersion,
    ApiKeyOwnership,
    ApiKeyPermission,
    ApiKeyScopeType,
    ApiKeyState,
    ApiKeyType,
)
from eneo.main.models import ModelId
from eneo.modules.module import ModuleBase
from eneo.tenants.tenant import TenantBase

pytestmark = pytest.mark.integration

REDIRECT_URI = "https://module.example.com/auth/callback"
UPDATED_REDIRECT_URI = "https://module.example.com/login/callback"


@pytest.fixture
async def admin_token(db_container, patch_auth_service_jwt, admin_user) -> str:
    async with db_container() as container:
        return container.auth_service().create_access_token_for_user(admin_user)


@pytest.fixture
async def enabled_module(db_container, admin_user):
    async with db_container() as container:
        module = await container.module_repo().add(
            ModuleBase(name=f"module-{uuid4().hex[:12]}")
        )
        await container.tenant_repo().add_modules(
            [ModelId(id=module.id)], admin_user.tenant_id
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


def client_config_path(*, tenant_id, module_id) -> str:
    return f"/api/v1/modules/{tenant_id}/{module_id}/client-config/"


@pytest.mark.asyncio
async def test_partial_config_patch_preserves_key_and_full_handoff_succeeds(
    client,
    admin_token,
    admin_user,
    enabled_module,
    test_settings,
):
    service_key = await create_api_key(
        client,
        token=admin_token,
        ownership=ApiKeyOwnership.SERVICE,
        permission=ApiKeyPermission.WRITE,
    )
    service_key_id = service_key["api_key"]["id"]
    config_path = client_config_path(
        tenant_id=admin_user.tenant_id, module_id=enabled_module.id
    )
    sysadmin_headers = {"X-API-Key": test_settings.eneo_super_duper_api_key}

    initial = await client.patch(
        config_path,
        json={
            "redirect_uris": [REDIRECT_URI],
            "service_key_id": service_key_id,
        },
        headers=sysadmin_headers,
    )
    assert initial.status_code == 200, initial.text

    partial = await client.patch(
        config_path,
        json={"redirect_uris": [UPDATED_REDIRECT_URI]},
        headers=sysadmin_headers,
    )
    assert partial.status_code == 200, partial.text
    assert partial.json()["service_key_id"] == service_key_id

    ticket_response = await client.post(
        "/api/v1/module-auth/tickets/",
        json={
            "module_id": str(enabled_module.id),
            "redirect_uri": UPDATED_REDIRECT_URI,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert ticket_response.status_code == 201, ticket_response.text
    ticket = ticket_response.json()["ticket"]

    exchange = await client.post(
        "/api/v1/module-auth/token/",
        json={"ticket": ticket},
        headers={"X-API-Key": service_key["secret"]},
    )
    assert exchange.status_code == 200, exchange.text
    assert exchange.json()["tenant_id"] == str(admin_user.tenant_id)
    assert exchange.json()["module"] == enabled_module.name

    replay = await client.post(
        "/api/v1/module-auth/token/",
        json={"ticket": ticket},
        headers={"X-API-Key": service_key["secret"]},
    )
    assert replay.status_code == 401, replay.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("ownership", "permission"),
    [
        (ApiKeyOwnership.USER, ApiKeyPermission.WRITE),
        (ApiKeyOwnership.SERVICE, ApiKeyPermission.READ),
    ],
)
async def test_client_config_rejects_key_that_cannot_exchange(
    client,
    admin_token,
    admin_user,
    enabled_module,
    test_settings,
    ownership,
    permission,
):
    api_key = await create_api_key(
        client,
        token=admin_token,
        ownership=ownership,
        permission=permission,
    )

    response = await client.patch(
        client_config_path(tenant_id=admin_user.tenant_id, module_id=enabled_module.id),
        json={"service_key_id": api_key["api_key"]["id"]},
        headers={"X-API-Key": test_settings.eneo_super_duper_api_key},
    )

    assert response.status_code == 400, response.text


@pytest.mark.asyncio
async def test_client_config_rejects_key_from_another_tenant(
    client,
    db_container,
    admin_user,
    enabled_module,
    test_settings,
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

    response = await client.patch(
        client_config_path(tenant_id=admin_user.tenant_id, module_id=enabled_module.id),
        json={"service_key_id": str(other_key.id)},
        headers={"X-API-Key": test_settings.eneo_super_duper_api_key},
    )

    assert response.status_code == 400, response.text


@pytest.mark.asyncio
async def test_empty_client_config_patch_is_rejected(
    client,
    admin_user,
    enabled_module,
    test_settings,
):
    response = await client.patch(
        client_config_path(tenant_id=admin_user.tenant_id, module_id=enabled_module.id),
        json={},
        headers={"X-API-Key": test_settings.eneo_super_duper_api_key},
    )

    assert response.status_code == 400, response.text
