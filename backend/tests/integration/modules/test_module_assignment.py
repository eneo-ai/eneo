import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from eneo.authentication.auth_models import (
    ApiKeyOwnership,
    ApiKeyPermission,
    ApiKeyScopeType,
    ApiKeyType,
)

pytestmark = pytest.mark.integration

REDIRECT_URI = "https://module.example.com/auth/callback"
UPDATED_REDIRECT_URI = "https://module.example.com/login/callback"


@pytest.fixture
async def admin_token(db_container, patch_auth_service_jwt, admin_user) -> str:
    async with db_container() as container:
        return container.auth_service().create_access_token_for_user(admin_user)


async def create_module_service_key(client, *, token: str) -> dict:
    response = await client.post(
        "/api/v1/api-keys",
        json={
            "name": f"module-key-{uuid4().hex[:8]}",
            "key_type": ApiKeyType.SK.value,
            "ownership": ApiKeyOwnership.SERVICE.value,
            "permission": ApiKeyPermission.WRITE.value,
            "scope_type": ApiKeyScopeType.TENANT.value,
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def installation_path(module_key: str) -> str:
    return f"/api/v1/admin/modules/{module_key}/"


async def install_module(
    client,
    *,
    token: str,
    module_key: str,
    service_key_id: str,
    redirect_uri: str = REDIRECT_URI,
):
    return await client.put(
        installation_path(module_key),
        json={
            "redirect_uris": [redirect_uri],
            "service_key_id": service_key_id,
        },
        headers={"Authorization": f"Bearer {token}"},
    )


@pytest.mark.asyncio
async def test_install_list_reconfigure_and_uninstall_module(
    client,
    db_container,
    admin_user,
    admin_token,
):
    module_key = f"admin-module-{uuid4().hex[:12]}"
    service_key = await create_module_service_key(client, token=admin_token)

    installed = await install_module(
        client,
        token=admin_token,
        module_key=module_key,
        service_key_id=service_key["api_key"]["id"],
    )
    assert installed.status_code == 200, installed.text
    assert installed.json() == {
        "module_id": installed.json()["module_id"],
        "module_key": module_key,
        "redirect_uris": [REDIRECT_URI],
        "service_key_id": service_key["api_key"]["id"],
        "configured": True,
    }
    assert "tenant_id" not in installed.json()

    listed = await client.get(
        "/api/v1/admin/modules/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert listed.status_code == 200, listed.text
    matching = [
        item for item in listed.json()["items"] if item["module_key"] == module_key
    ]
    assert matching == [installed.json()]

    reconfigured = await install_module(
        client,
        token=admin_token,
        module_key=module_key,
        service_key_id=service_key["api_key"]["id"],
        redirect_uri=UPDATED_REDIRECT_URI,
    )
    assert reconfigured.status_code == 200, reconfigured.text
    assert reconfigured.json()["redirect_uris"] == [UPDATED_REDIRECT_URI]

    removed = await client.delete(
        installation_path(module_key),
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert removed.status_code == 200, removed.text
    assert removed.json() == {
        "module_id": installed.json()["module_id"],
        "module_key": module_key,
        "enabled": False,
        "changed": True,
    }
    assert "tenant_id" not in removed.json()

    async with db_container() as container:
        assert (
            await container.module_repo().get_module_client_config(
                tenant_id=admin_user.tenant_id,
                module_id=installed.json()["module_id"],
            )
            is None
        )


@pytest.mark.asyncio
async def test_install_rejects_non_url_safe_module_key(client, admin_token):
    service_key = await create_module_service_key(client, token=admin_token)

    response = await install_module(
        client,
        token=admin_token,
        module_key="reports key",
        service_key_id=service_key["api_key"]["id"],
    )

    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_invalid_service_key_rolls_back_global_registration(
    client,
    db_container,
    admin_token,
):
    module_key = f"invalid-key-{uuid4().hex[:12]}"

    response = await install_module(
        client,
        token=admin_token,
        module_key=module_key,
        service_key_id=str(uuid4()),
    )

    assert response.status_code == 400, response.text
    async with db_container() as container:
        assert await container.module_repo().get_module_by_key(module_key) is None


@pytest.mark.asyncio
async def test_revocation_committing_before_installation_prevents_binding(
    client,
    db_container,
    admin_token,
):
    module_key = f"revoked-concurrently-{uuid4().hex[:12]}"
    service_key = await create_module_service_key(client, token=admin_token)
    service_key_id = service_key["api_key"]["id"]

    async with db_container() as container:
        await container.api_key_lifecycle_service().revoke_key(
            key_id=UUID(service_key_id)
        )

        install_task = asyncio.create_task(
            install_module(
                client,
                token=admin_token,
                module_key=module_key,
                service_key_id=service_key_id,
            )
        )
        done, _pending = await asyncio.wait({install_task}, timeout=0.1)
        assert not done, "installation must wait for the key lifecycle transaction"

    response = await asyncio.wait_for(install_task, timeout=10)
    assert response.status_code == 400, response.text
    assert "revoked" in response.text

    async with db_container() as container:
        assert await container.module_repo().get_module_by_key(module_key) is None


@pytest.mark.asyncio
async def test_install_and_uninstall_are_idempotent_under_concurrent_retries(
    client,
    admin_token,
):
    module_key = f"concurrent-{uuid4().hex[:12]}"
    service_key = await create_module_service_key(client, token=admin_token)
    service_key_id = service_key["api_key"]["id"]

    installed = await asyncio.gather(
        install_module(
            client,
            token=admin_token,
            module_key=module_key,
            service_key_id=service_key_id,
        ),
        install_module(
            client,
            token=admin_token,
            module_key=module_key,
            service_key_id=service_key_id,
        ),
    )
    assert [response.status_code for response in installed] == [200, 200]
    assert {response.json()["module_id"] for response in installed} == {
        installed[0].json()["module_id"]
    }

    removed = await asyncio.gather(
        client.delete(
            installation_path(module_key),
            headers={"Authorization": f"Bearer {admin_token}"},
        ),
        client.delete(
            installation_path(module_key),
            headers={"Authorization": f"Bearer {admin_token}"},
        ),
    )
    assert [response.status_code for response in removed] == [200, 200]
    assert sorted(response.json()["changed"] for response in removed) == [False, True]


@pytest.mark.asyncio
async def test_module_admin_routes_reject_environment_key_auth(
    client,
    test_settings,
):
    response = await client.get(
        "/api/v1/admin/modules/",
        headers={"X-API-Key": test_settings.eneo_super_api_key},
    )

    assert response.status_code == 401, response.text
