"""
Integration tests for deleting a tenant through the sysadmin API.

- DELETE /sysadmin/tenants/{id}/

The route issues a single DELETE on ``tenants`` and leaves everything below
it to the foreign keys. Sessions have no tenant column. Postgres reaches a
service key's session through the key (tenant, key, session) before it
reaches it through its assistant, service or group chat, so the key's foreign
key must delete the session rather than clear ``api_key_id``:
``ck_sessions_user_xor_api_key`` rejects a session with neither a user nor a
key.
"""

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from httpx import AsyncClient

from eneo.ai_models.completion_models.completion_model import (
    Completion,
    CompletionModelResponse,
    ResponseType,
)
from eneo.completion_models.infrastructure.completion_service import CompletionService
from eneo.database.database import sessionmanager
from eneo.database.tables.api_keys_v2_table import ApiKeysV2
from eneo.database.tables.sessions_table import Sessions
from eneo.database.tables.tenant_table import Tenants

_PASSWORD = "IntegrationPass123!"


@pytest.fixture
def stub_completion(monkeypatch):
    async def fake_get_response(self: CompletionService, **kwargs: Any):
        return CompletionModelResponse(
            completion=Completion(text="Stub answer.", response_type=ResponseType.TEXT),
            model=kwargs["model"],
            extended_logging=None,
            total_token_count=42,
            usage=None,
        )

    monkeypatch.setattr(CompletionService, "get_response", fake_get_response)


async def _create_tenant_admin(
    client: AsyncClient, super_admin_token: str
) -> tuple[str, str]:
    """Return the id of a new tenant and a bearer token for its Owner."""
    suffix = uuid4().hex[:8]
    headers = {"X-API-Key": super_admin_token}

    tenant_response = await client.post(
        "/api/v1/sysadmin/tenants/",
        json={"name": f"tenant-deletion-{suffix}"},
        headers=headers,
    )
    assert tenant_response.status_code == 200, tenant_response.text
    tenant_id = tenant_response.json()["id"]

    user_response = await client.post(
        "/api/v1/sysadmin/users/",
        json={
            "email": f"tenant-deletion-{suffix}@example.com",
            "username": f"tenant-deletion-{suffix}",
            "tenant_id": tenant_id,
            "password": _PASSWORD,
            "password_change_required": False,
        },
        headers=headers,
    )
    assert user_response.status_code == 200, user_response.text
    user = user_response.json()

    # Only tenant admins may create service keys.
    async with sessionmanager.session() as session, session.begin():
        owner_role_id = await session.scalar(
            sa.text(
                "SELECT id FROM roles "
                "WHERE predefined_source = 'Owner' AND tenant_id = :tenant_id"
            ),
            {"tenant_id": tenant_id},
        )
        assert owner_role_id is not None
        await session.execute(
            sa.text(
                "INSERT INTO users_roles (user_id, role_id) VALUES (:user_id, :role_id)"
            ),
            {"user_id": user["id"], "role_id": owner_role_id},
        )

    return tenant_id, user["access_token"]["access_token"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_delete_tenant_removes_sessions_owned_by_service_key(
    client: AsyncClient,
    super_admin_token: str,
    patch_auth_service_jwt: None,
    stub_completion: None,
):
    tenant_id, token = await _create_tenant_admin(client, super_admin_token)
    bearer = {"Authorization": f"Bearer {token}"}

    space_response = await client.post(
        "/api/v1/spaces/", json={"name": "tenant-deletion-space"}, headers=bearer
    )
    assert space_response.status_code == 201, space_response.text
    assistant_response = await client.post(
        "/api/v1/assistants/",
        json={
            "name": "tenant-deletion-assistant",
            "space_id": space_response.json()["id"],
        },
        headers=bearer,
    )
    assert assistant_response.status_code == 200, assistant_response.text
    assistant_id = assistant_response.json()["id"]

    key_response = await client.post(
        "/api/v1/api-keys",
        json={
            "name": "tenant-deletion-service-key",
            "key_type": "sk_",
            "permission": "write",
            "scope_type": "assistant",
            "scope_id": assistant_id,
            "ownership": "service",
            # Service write keys need an expiry or an IP allowlist.
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
        },
        headers=bearer,
    )
    assert key_response.status_code == 201, key_response.text
    key_id = UUID(key_response.json()["api_key"]["id"])

    ask_response = await client.post(
        f"/api/v1/assistants/{assistant_id}/sessions/",
        json={"question": "hello", "stream": False},
        headers={"X-API-Key": key_response.json()["secret"]},
    )
    assert ask_response.status_code == 200, ask_response.text
    session_id = UUID(ask_response.json()["session_id"])

    # Guard the test itself: the trap needs a session owned by the key alone.
    async with sessionmanager.session() as session, session.begin():
        owner = (
            await session.execute(
                sa.select(Sessions.user_id, Sessions.api_key_id).where(
                    Sessions.id == session_id
                )
            )
        ).one()
    assert owner.user_id is None
    assert owner.api_key_id == key_id

    delete_response = await client.delete(
        f"/api/v1/sysadmin/tenants/{tenant_id}/",
        headers={"X-API-Key": super_admin_token},
    )
    assert delete_response.status_code == 200, delete_response.text

    async with sessionmanager.session() as session, session.begin():
        remaining = {
            "tenant": await session.scalar(
                sa.select(Tenants.id).where(Tenants.id == UUID(tenant_id))
            ),
            "api key": await session.scalar(
                sa.select(ApiKeysV2.id).where(ApiKeysV2.id == key_id)
            ),
            "sessions": (
                await session.scalars(
                    sa.select(Sessions.id).where(
                        sa.or_(Sessions.id == session_id, Sessions.api_key_id == key_id)
                    )
                )
            ).all(),
        }
    assert remaining == {"tenant": None, "api key": None, "sessions": []}
