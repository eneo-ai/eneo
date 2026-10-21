"""Every flow surface answers 404 to a tenant without the flows_core flag."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

SURFACES = (
    ("GET", "/api/v1/flows/"),
    ("GET", "/api/v1/settings/flow-input-limits"),
    ("GET", "/api/v1/settings/flow-runtime-policy"),
    ("POST", "/api/v1/flow-packages/validate/"),
)


async def _set_flag(db_container, tenant_id, *, enabled: bool) -> None:
    async with db_container() as container:
        flag = await container.feature_flag_repo().one(name="flows_core")
        service = container.feature_flag_service()
        if enabled:
            await service.enable_tenant(flag.feature_id, tenant_id)
        else:
            await service.disable_tenant(flag.feature_id, tenant_id)


async def _call(client: AsyncClient, method: str, path: str, key: str):
    return await client.request(
        method,
        path,
        headers={"X-API-Key": key},
        json={} if method == "POST" else None,
    )


@pytest.mark.parametrize(("method", "path"), SURFACES)
async def test_a_tenant_without_the_flag_finds_no_flow_surface(
    client: AsyncClient, db_container, admin_user, admin_user_api_key, method, path
):
    await _set_flag(db_container, admin_user.tenant_id, enabled=False)

    response = await _call(client, method, path, admin_user_api_key.key)

    assert response.status_code == 404


@pytest.mark.parametrize(("method", "path"), SURFACES)
async def test_a_tenant_with_the_flag_reaches_the_flow_surface(
    client: AsyncClient, db_container, admin_user, admin_user_api_key, method, path
):
    await _set_flag(db_container, admin_user.tenant_id, enabled=True)

    response = await _call(client, method, path, admin_user_api_key.key)

    assert response.status_code != 404
