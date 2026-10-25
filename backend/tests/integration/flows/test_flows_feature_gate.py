"""Every flow surface answers 404 to a tenant without the flows_core flag, after
the credentials are refused (401) and the key is refused for the route (403),
and before the request body is read (422)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa
from httpx import AsyncClient

from tests.fixtures import mint_v2_api_key
from tests.integration.module_session_support import (
    enable_module,
    install_module,
    module_login,
)

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


@pytest.mark.parametrize("enabled", [True, False])
async def test_the_settings_report_whether_the_tenant_has_flows(
    client: AsyncClient, db_container, admin_user, admin_user_api_key, enabled
):
    await _set_flag(db_container, admin_user.tenant_id, enabled=enabled)

    response = await _call(client, "GET", "/api/v1/settings/", admin_user_api_key.key)

    assert response.status_code == 200, response.text
    assert response.json()["flows_enabled"] is enabled


@pytest.mark.parametrize(("method", "path"), SURFACES)
async def test_a_signed_in_user_without_the_flag_finds_no_flow_surface(
    client: AsyncClient,
    db_container,
    admin_user,
    flow_process_auth_headers,
    method,
    path,
):
    await _set_flag(db_container, admin_user.tenant_id, enabled=False)

    response = await client.request(
        method,
        path,
        headers=dict(flow_process_auth_headers),
        json={} if method == "POST" else None,
    )

    assert response.status_code == 404


@pytest.mark.parametrize(("method", "path"), SURFACES)
async def test_a_caller_without_credentials_is_refused_before_the_flag(
    client: AsyncClient, db_container, admin_user, method, path
):
    await _set_flag(db_container, admin_user.tenant_id, enabled=False)

    response = await client.request(method, path, json={} if method == "POST" else None)

    assert response.status_code == 401


async def test_a_key_refused_for_the_route_is_refused_before_the_flag(
    client: AsyncClient, db_container, admin_user
):
    async with db_container() as container:
        read_key = await mint_v2_api_key(
            container.api_key_v2_repo(),
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            permission="read",
        )
    await _set_flag(db_container, admin_user.tenant_id, enabled=False)

    response = await _call(
        client, "POST", "/api/v1/flow-packages/validate/", read_key.key
    )

    assert response.status_code == 403, response.text


@pytest.mark.parametrize(("enabled", "status_code"), [(True, 422), (False, 404)])
async def test_the_flag_is_checked_before_the_request_body(
    client: AsyncClient,
    db_container,
    admin_user,
    admin_user_api_key,
    enabled,
    status_code,
):
    await _set_flag(db_container, admin_user.tenant_id, enabled=enabled)

    response = await _call(
        client, "POST", "/api/v1/flow-packages/validate/", admin_user_api_key.key
    )

    assert response.status_code == status_code, response.text


@pytest.mark.parametrize("enabled", [True, False])
async def test_module_credentials_are_refused_on_a_route_without_the_opt_in(
    client: AsyncClient,
    db_container,
    admin_user,
    flow_process_auth_headers,
    enabled,
):
    admin_token = flow_process_auth_headers.token
    module_key = await enable_module(db_container, tenant_id=admin_user.tenant_id)
    secret = await install_module(
        client, admin_token=admin_token, module_key=module_key
    )
    module_token = await module_login(
        client, service_key=secret, user_token=admin_token, module_key=module_key
    )
    await _set_flag(db_container, admin_user.tenant_id, enabled=enabled)

    response = await client.get(
        "/api/v1/flows/execution-limits/",
        headers={"X-API-Key": secret, "Authorization": f"Bearer {module_token}"},
    )

    # The route cannot verify a module token, whether or not the tenant has
    # flows: the credentials are refused before the flag is read.
    assert response.status_code == 401, response.text


async def test_a_last_used_bump_skips_a_key_another_transaction_holds(
    db_container, admin_user, admin_user_api_key
):
    """The bump runs in the route's own transaction, which may stay open while
    a response streams; a concurrent request with the same key must not wait."""
    key_id = admin_user_api_key.id
    now = datetime.now(timezone.utc)

    async def bump(container, at: datetime):
        return await asyncio.wait_for(
            container.api_key_v2_repo().update_last_used_at(
                key_id=key_id,
                tenant_id=admin_user.tenant_id,
                last_used_at=at,
                min_interval_seconds=0,
            ),
            timeout=5,
        )

    async with db_container() as holder:
        assert await bump(holder, now) is not None
        async with db_container() as other:
            await other.session().execute(sa.text("SET LOCAL lock_timeout = '3s'"))
            assert await bump(other, now) is None

    async with db_container() as other:
        assert await bump(other, now + timedelta(seconds=1)) is not None
