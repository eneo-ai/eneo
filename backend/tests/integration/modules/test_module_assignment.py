import asyncio
from uuid import uuid4

import pytest

from eneo.modules.module import ModuleCreate

pytestmark = pytest.mark.integration

REDIRECT_URI = "https://module.example.com/auth/callback"


def client_config_path(*, tenant_id, module_id) -> str:
    return f"/api/v1/modules/{tenant_id}/{module_id}/client-config/"


@pytest.mark.asyncio
async def test_registering_duplicate_module_key_returns_name_collision(
    client,
    db_container,
    test_settings,
):
    module_key = f"duplicate-{uuid4().hex[:12]}"
    async with db_container() as container:
        await container.module_repo().add(ModuleCreate(name=module_key))

    response = await client.post(
        "/api/v1/modules/",
        json={"name": module_key},
        headers={"X-API-Key": test_settings.eneo_super_duper_api_key},
    )

    assert response.status_code == 409, response.text
    assert response.json()["eneo_error_code"] == 9017


@pytest.mark.asyncio
async def test_targeted_module_enable_and_disable_preserve_other_assignments(
    client,
    db_container,
    admin_user,
    test_settings,
):
    async with db_container() as container:
        first_module = await container.module_repo().add(
            ModuleCreate(name=f"first-{uuid4().hex[:12]}")
        )
        target_module = await container.module_repo().add(
            ModuleCreate(name=f"target-{uuid4().hex[:12]}")
        )

    headers = {"X-API-Key": test_settings.eneo_super_duper_api_key}
    first_enable = await client.put(
        f"/api/v1/modules/{admin_user.tenant_id}/{first_module.id}/",
        headers=headers,
    )
    assert first_enable.status_code == 200, first_enable.text
    assert first_enable.json() == {
        "tenant_id": str(admin_user.tenant_id),
        "module_id": str(first_module.id),
        "module_key": first_module.name,
        "enabled": True,
        "changed": True,
    }
    async with db_container() as container:
        tenant = await container.tenant_repo().get(admin_user.tenant_id)
        assert tenant is not None
        initial_ids = {module.id for module in tenant.modules}
    assert first_module.id in initial_ids

    target_path = f"/api/v1/modules/{admin_user.tenant_id}/{target_module.id}/"
    target_enable = await client.put(target_path, headers=headers)
    assert target_enable.status_code == 200, target_enable.text
    assert target_enable.json()["changed"] is True
    async with db_container() as container:
        tenant = await container.tenant_repo().get(admin_user.tenant_id)
        assert tenant is not None
        enabled_ids = {module.id for module in tenant.modules}
    assert enabled_ids == initial_ids | {target_module.id}

    repeated_enable = await client.put(target_path, headers=headers)
    assert repeated_enable.status_code == 200, repeated_enable.text
    assert repeated_enable.json()["enabled"] is True
    assert repeated_enable.json()["changed"] is False

    config_response = await client.patch(
        client_config_path(tenant_id=admin_user.tenant_id, module_id=target_module.id),
        json={"redirect_uris": [REDIRECT_URI]},
        headers=headers,
    )
    assert config_response.status_code == 200, config_response.text

    disable = await client.delete(target_path, headers=headers)
    assert disable.status_code == 200, disable.text
    assert disable.json()["enabled"] is False
    assert disable.json()["changed"] is True

    async with db_container() as container:
        tenant = await container.tenant_repo().get(admin_user.tenant_id)
        assert tenant is not None
        assert {module.id for module in tenant.modules} == initial_ids
        assert (
            await container.module_repo().get_module_client_config(
                tenant_id=admin_user.tenant_id,
                module_id=target_module.id,
            )
            is None
        )

    repeated_disable = await client.delete(target_path, headers=headers)
    assert repeated_disable.status_code == 200, repeated_disable.text
    assert repeated_disable.json()["enabled"] is False
    assert repeated_disable.json()["changed"] is False


@pytest.mark.asyncio
async def test_targeted_assignment_is_atomic_under_concurrent_retries(
    client,
    db_container,
    admin_user,
    test_settings,
):
    async with db_container() as container:
        module = await container.module_repo().add(
            ModuleCreate(name=f"concurrent-{uuid4().hex[:12]}")
        )

    path = f"/api/v1/modules/{admin_user.tenant_id}/{module.id}/"
    headers = {"X-API-Key": test_settings.eneo_super_duper_api_key}

    enabled = await asyncio.gather(
        client.put(path, headers=headers),
        client.put(path, headers=headers),
    )
    assert [response.status_code for response in enabled] == [200, 200]
    assert sorted(response.json()["changed"] for response in enabled) == [False, True]

    async with db_container() as container:
        tenant = await container.tenant_repo().get(admin_user.tenant_id)
        assert tenant is not None
        assert [item.id for item in tenant.modules].count(module.id) == 1

    disabled = await asyncio.gather(
        client.delete(path, headers=headers),
        client.delete(path, headers=headers),
    )
    assert [response.status_code for response in disabled] == [200, 200]
    assert sorted(response.json()["changed"] for response in disabled) == [False, True]

    async with db_container() as container:
        tenant = await container.tenant_repo().get(admin_user.tenant_id)
        assert tenant is not None
        assert module.id not in {item.id for item in tenant.modules}


@pytest.mark.asyncio
async def test_legacy_bulk_assignment_remains_full_set_replacement(
    client,
    db_container,
    admin_user,
    test_settings,
):
    async with db_container() as container:
        first_module = await container.module_repo().add(
            ModuleCreate(name=f"bulk-first-{uuid4().hex[:12]}")
        )
        replacement_module = await container.module_repo().add(
            ModuleCreate(name=f"bulk-replacement-{uuid4().hex[:12]}")
        )
        await container.tenant_repo().enable_module(
            tenant_id=admin_user.tenant_id,
            module_id=first_module.id,
        )

    response = await client.post(
        f"/api/v1/modules/{admin_user.tenant_id}/",
        json=[{"id": str(replacement_module.id)}],
        headers={"X-API-Key": test_settings.eneo_super_duper_api_key},
    )

    assert response.status_code == 200, response.text
    assert {module["id"] for module in response.json()["modules"]} == {
        str(replacement_module.id)
    }


@pytest.mark.asyncio
async def test_bulk_assignment_rejects_partial_unknown_set_before_replacement(
    client,
    db_container,
    admin_user,
    test_settings,
):
    async with db_container() as container:
        existing_module = await container.module_repo().add(
            ModuleCreate(name=f"bulk-existing-{uuid4().hex[:12]}")
        )
        valid_replacement = await container.module_repo().add(
            ModuleCreate(name=f"bulk-valid-{uuid4().hex[:12]}")
        )
        await container.tenant_repo().enable_module(
            tenant_id=admin_user.tenant_id,
            module_id=existing_module.id,
        )

    path = f"/api/v1/modules/{admin_user.tenant_id}/"
    headers = {"X-API-Key": test_settings.eneo_super_duper_api_key}
    rejected = await client.post(
        path,
        json=[{"id": str(valid_replacement.id)}, {"id": str(uuid4())}],
        headers=headers,
    )
    assert rejected.status_code == 404, rejected.text

    async with db_container() as container:
        tenant = await container.tenant_repo().get(admin_user.tenant_id)
        assert tenant is not None
        assert {module.id for module in tenant.modules} == {existing_module.id}

    cleared = await client.post(path, json=[], headers=headers)
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["modules"] == []


@pytest.mark.asyncio
async def test_targeted_enable_rejects_unknown_module_without_side_effects(
    client,
    db_container,
    admin_user,
    test_settings,
):
    async with db_container() as container:
        tenant_before = await container.tenant_repo().get(admin_user.tenant_id)
        assert tenant_before is not None
        before_ids = {module.id for module in tenant_before.modules}

    response = await client.put(
        f"/api/v1/modules/{admin_user.tenant_id}/{uuid4()}/",
        headers={"X-API-Key": test_settings.eneo_super_duper_api_key},
    )

    assert response.status_code == 404, response.text
    async with db_container() as container:
        tenant_after = await container.tenant_repo().get(admin_user.tenant_id)
        assert tenant_after is not None
        assert {module.id for module in tenant_after.modules} == before_ids
