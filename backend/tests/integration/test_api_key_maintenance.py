"""The nightly API key maintenance, run against a real database.

Every check reads committed rows in a new session and signs in with the key,
because sign-in judges a key by its dates, never by the stored ``state``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import pytest
import sqlalchemy as sa

from eneo.authentication.auth_models import ApiKeyV2InDB
from eneo.database.tables.api_keys_v2_table import ApiKeysV2
from eneo.database.tables.tenant_table import Tenants

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

# Any route behind the full API key sign-in chain.
_AUTH_ENDPOINT = "/api/v1/assistants/"


@pytest.fixture
async def token(db_container, patch_auth_service_jwt, admin_user) -> str:
    async with db_container() as container:
        return container.auth_service().create_access_token_for_user(admin_user)


async def create_key(
    client, token: str, *, name: str, expires_at: datetime | None = None
) -> tuple[UUID, str]:
    body: dict[str, object] = {
        "name": name,
        "key_type": "sk_",
        "permission": "read",
        "scope_type": "tenant",
    }
    if expires_at is not None:
        body["expires_at"] = expires_at.isoformat()
    response = await client.post(
        "/api/v1/api-keys",
        json=body,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    return UUID(payload["api_key"]["id"]), payload["secret"]


async def set_key_columns(db_container, key_id: UUID, **values: Any) -> None:
    async with db_container() as container:
        await container.session().execute(
            sa.update(ApiKeysV2).where(ApiKeysV2.id == key_id).values(**values)
        )


async def make_unused(db_container, key_id: UUID, *, days: int) -> None:
    then = datetime.now(timezone.utc) - timedelta(days=days)
    await set_key_columns(db_container, key_id, created_at=then, last_used_at=then)


async def set_unused_days(db_container, tenant_id: UUID, days: int | None) -> None:
    async with db_container() as container:
        await container.session().execute(
            sa.update(Tenants)
            .where(Tenants.id == tenant_id)
            .values(api_key_policy={"auto_expire_unused_days": days})
        )


async def run_maintenance(db_container) -> dict[str, Any]:
    async with db_container() as container:
        return await container.api_key_maintenance_service().run_daily_maintenance()


async def read_key(db_container, key_id: UUID) -> ApiKeyV2InDB:
    async with db_container() as container:
        key = await container.session().scalar(
            sa.select(ApiKeysV2).where(ApiKeysV2.id == key_id)
        )
        return ApiKeyV2InDB.model_validate(key)


async def sign_in_status(client, secret: str) -> int:
    response = await client.get(_AUTH_ENDPOINT, headers={"X-API-Key": secret})
    return response.status_code


async def test_an_unused_key_with_a_future_end_date_stops_working(
    client, db_container, token, admin_user
):
    future = datetime.now(timezone.utc) + timedelta(days=30)
    unused_id, unused_secret = await create_key(
        client, token, name="unused", expires_at=future
    )
    await make_unused(db_container, unused_id, days=10)
    past = datetime.now(timezone.utc) - timedelta(days=1)
    past_id, _ = await create_key(client, token, name="past", expires_at=past)
    await set_unused_days(db_container, admin_user.tenant_id, 7)
    assert await sign_in_status(client, unused_secret) == 200
    await make_unused(db_container, unused_id, days=10)

    result = await run_maintenance(db_container)

    assert result["auto_expired"] == 1
    assert result["expired"] == 1
    unused = await read_key(db_container, unused_id)
    assert unused.state == "expired"
    assert unused.expires_at <= datetime.now(timezone.utc)
    assert await sign_in_status(client, unused_secret) == 401
    # A key whose end date had already passed keeps that date.
    assert (await read_key(db_container, past_id)).expires_at == past


async def rotate(client, token: str, key_id: UUID) -> tuple[UUID, str]:
    response = await client.post(
        f"/api/v1/api-keys/{key_id}/rotate",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    return UUID(payload["api_key"]["id"]), payload["secret"]


async def test_a_rotated_key_is_revoked_when_its_grace_period_ends(
    client, db_container, token
):
    old_id, old_secret = await create_key(client, token, name="rotated")
    new_id, new_secret = await rotate(client, token, old_id)
    ended = datetime.now(timezone.utc) - timedelta(minutes=1)
    await set_key_columns(db_container, old_id, rotation_grace_until=ended)

    result = await run_maintenance(db_container)

    assert result["rotation_revoked"] == 1
    old = await read_key(db_container, old_id)
    assert old.state == "revoked"
    assert old.revoked_reason_code == "rotation_completed"
    assert old.rotation_grace_until == ended
    assert await sign_in_status(client, old_secret) == 401
    assert await sign_in_status(client, new_secret) == 200
    assert (await read_key(db_container, new_id)).state == "active"
