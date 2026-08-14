"""A Space-scoped key must reach both capacity endpoints.

The first design of the request-capacity route put it inside `api_key_router`,
which is wrapped in an admin scope check — unreachable by a Space-scoped key. Structural tests can show the
route is registered outside that router; only a real authenticated request
shows that authentication, scope resolution and rate-limit enforcement let the
key through, and that the reported count already includes the request asking.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest


@pytest.fixture
async def admin_token(db_container, patch_auth_service_jwt, admin_user):
    async with db_container() as container:
        auth_service = container.auth_service()
        return auth_service.create_access_token_for_user(admin_user)


@pytest.fixture
async def measurement_space_id(client, admin_token) -> str:
    resp = await client.post(
        "/api/v1/spaces/",
        json={"name": f"measurement-{uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


@pytest.fixture
async def space_scoped_secret(client, admin_token, measurement_space_id) -> str:
    """The shape a dedicated measurement key actually has."""
    expires = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    resp = await client.post(
        "/api/v1/api-keys",
        json={
            "name": f"measurement-{uuid4().hex[:8]}",
            "key_type": "sk_",
            "permission": "write",
            "scope_type": "space",
            "scope_id": measurement_space_id,
            "ownership": "service",
            "expires_at": expires,
            # An explicit finite limit, so the count assertion below cannot be
            # skipped by an unlimited deployment default.
            "rate_limit": 20000,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["secret"]


@pytest.mark.asyncio
async def test_a_space_scoped_key_reads_its_own_request_capacity(
    client, space_scoped_secret, measurement_space_id
) -> None:
    resp = await client.get(
        "/api/v1/api-key-capacity/",
        headers={"X-API-Key": space_scoped_secret},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["scope_type"] == "space"
    assert body["scope_id"] == measurement_space_id
    assert body["limit_source"] == "explicit"
    assert body["limit"] == 20000
    # Enforcement counts the request before the handler runs, so this key's
    # first ever call already reports one consumed. That is what makes
    # `remaining` conservative and what the demand subtraction relies on.
    assert body["current_count"] == 1
    assert body["remaining"] == body["limit"] - 1


@pytest.mark.asyncio
async def test_a_space_scoped_key_reads_tenant_runtime_capacity(
    client, space_scoped_secret, admin_user
) -> None:
    resp = await client.get(
        "/api/v1/flows/runs/capacity/",
        headers={"X-API-Key": space_scoped_secret},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["tenant_id"] == str(admin_user.tenant_id)
    assert body["active_runs"] == 0
    assert body["available_slots"] == max(
        0, body["max_concurrent_runs"] - body["active_runs"]
    )


@pytest.mark.asyncio
async def test_a_session_caller_has_no_key_capacity_to_report(
    client, admin_token
) -> None:
    resp = await client.get(
        "/api/v1/api-key-capacity/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert resp.status_code == 403, resp.text
