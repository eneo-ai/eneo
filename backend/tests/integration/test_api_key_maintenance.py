"""The nightly API key maintenance, run against a real database.

Every check reads committed rows in a new session and signs in with the key,
because sign-in judges a key by its dates, never by the stored ``state``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import pytest
import sqlalchemy as sa

from eneo.audit.domain.action_types import ActionType
from eneo.authentication import api_key_maintenance
from eneo.authentication.api_key_v2_repo import ApiKeysV2Repository
from eneo.authentication.auth_models import ApiKeyV2InDB
from eneo.database.tables.api_keys_v2_table import ApiKeysV2
from eneo.database.tables.audit_log_table import AuditLog
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


async def audit_actions(db_container, key_id: UUID) -> list[str]:
    async with db_container() as container:
        rows = await container.session().scalars(
            sa.select(AuditLog.action)
            .where(AuditLog.entity_id == key_id)
            .order_by(AuditLog.timestamp)
        )
        return list(rows)


def after_selection(
    monkeypatch, key_id: UUID, action: Callable[[], Awaitable[None]]
) -> None:
    """Run ``action``, committed in its own session, right after the job has
    selected ``key_id`` and before it changes the key."""
    original = ApiKeysV2Repository.list_matching
    pending = True

    async def list_then_act(self, *args, **kwargs):
        nonlocal pending
        keys = await original(self, *args, **kwargs)
        if pending and any(key.id == key_id for key in keys):
            pending = False
            await action()
        return keys

    monkeypatch.setattr(ApiKeysV2Repository, "list_matching", list_then_act)


def pin_job_clock(monkeypatch, at: datetime) -> None:
    class PinnedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):  # noqa: ARG003 - the job always asks for UTC
            return at

    monkeypatch.setattr(api_key_maintenance, "datetime", PinnedDatetime)


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


async def test_a_key_used_after_selection_keeps_working(
    client, db_container, token, admin_user, monkeypatch
):
    used_id, used_secret = await create_key(client, token, name="used")
    idle_id, idle_secret = await create_key(client, token, name="idle")
    await make_unused(db_container, used_id, days=10)
    await make_unused(db_container, idle_id, days=10)
    await set_unused_days(db_container, admin_user.tenant_id, 7)

    async def use() -> None:
        assert await sign_in_status(client, used_secret) == 200

    after_selection(monkeypatch, used_id, use)
    result = await run_maintenance(db_container)

    assert result["auto_expired"] == 1
    used = await read_key(db_container, used_id)
    assert used.state == "active"
    assert await sign_in_status(client, used_secret) == 200
    assert ActionType.API_KEY_EXPIRED.value not in await audit_actions(
        db_container, used_id
    )
    assert await sign_in_status(client, idle_secret) == 401


async def test_a_key_revoked_after_selection_keeps_its_revocation(
    client, db_container, token, admin_user, monkeypatch
):
    key_id, secret = await create_key(client, token, name="revoked")
    await make_unused(db_container, key_id, days=10)
    await set_unused_days(db_container, admin_user.tenant_id, 7)

    async def revoke() -> None:
        response = await client.post(
            f"/api/v1/api-keys/{key_id}/revoke",
            json={"reason_code": "key_compromised", "reason_text": "Leaked"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200, response.text

    after_selection(monkeypatch, key_id, revoke)
    result = await run_maintenance(db_container)

    assert result["auto_expired"] == 0
    key = await read_key(db_container, key_id)
    assert key.state == "revoked"
    assert key.revoked_reason_code == "key_compromised"
    assert key.revoked_reason_text == "Leaked"
    assert ActionType.API_KEY_EXPIRED.value not in await audit_actions(
        db_container, key_id
    )
    assert await sign_in_status(client, secret) == 401


async def test_a_new_grace_period_after_selection_keeps_the_old_key_working(
    client, db_container, token, monkeypatch
):
    """A key inside its grace period can be rotated again, which moves the
    grace period; a run that selected it under the earlier period must not
    revoke it."""
    old_id, old_secret = await create_key(client, token, name="rotating")
    await rotate(client, token, old_id)
    now = datetime.now(timezone.utc)
    await set_key_columns(
        db_container, old_id, rotation_grace_until=now + timedelta(hours=1)
    )
    pin_job_clock(monkeypatch, now + timedelta(hours=2))

    async def rotate_again() -> None:
        await rotate(client, token, old_id)

    after_selection(monkeypatch, old_id, rotate_again)
    result = await run_maintenance(db_container)

    assert result["rotation_revoked"] == 0
    old = await read_key(db_container, old_id)
    assert old.revoked_at is None
    assert old.rotation_grace_until is not None
    assert old.rotation_grace_until > now + timedelta(hours=2)
    assert ActionType.API_KEY_REVOKED.value not in await audit_actions(
        db_container, old_id
    )
    assert await sign_in_status(client, old_secret) == 200
