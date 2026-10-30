"""Module sessions for integration tests: install a module, then sign a user in.

A module backend calls Eneo with its service key plus the signed-in user's
module token; these helpers produce both the way a real installation does.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse
from uuid import UUID, uuid4

from httpx import AsyncClient

from eneo.authentication.auth_models import (
    ApiKeyOwnership,
    ApiKeyPermission,
    ApiKeyScopeType,
    ApiKeyType,
)
from eneo.modules.module import ModuleCreate

REDIRECT_URI = "https://module.example.com/auth/callback"


async def enable_module(db_container, *, tenant_id: UUID) -> str:
    """Register a module and enable it for the tenant; returns its key."""
    async with db_container() as container:
        module = await container.module_repo().add(
            ModuleCreate(name=f"module-{uuid4().hex[:12]}")
        )
        await container.tenant_repo().enable_module(
            tenant_id=tenant_id, module_id=module.id
        )
        return module.name


async def install_module(
    client: AsyncClient,
    *,
    admin_token: str,
    module_key: str,
    resource_permissions: dict[str, str] | None = None,
    space_id: UUID | None = None,
) -> str:
    """Give the module a fresh service key, tenant-wide unless `space_id` scopes
    it to one space; returns the key's secret."""
    body: dict[str, object] = {
        "name": f"module-key-{uuid4().hex[:8]}",
        "key_type": ApiKeyType.SK.value,
        "ownership": ApiKeyOwnership.SERVICE.value,
        "permission": ApiKeyPermission.WRITE.value,
        "scope_type": ApiKeyScopeType.TENANT.value,
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
    }
    if space_id is not None:
        body |= {"scope_type": ApiKeyScopeType.SPACE.value, "scope_id": str(space_id)}
    if resource_permissions is not None:
        body["resource_permissions"] = resource_permissions
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    created = await client.post("/api/v1/api-keys", json=body, headers=admin_headers)
    assert created.status_code == 201, created.text
    service_key = created.json()

    installed = await client.put(
        f"/api/v1/admin/modules/{module_key}/",
        json={
            "redirect_uris": [REDIRECT_URI],
            "service_key_id": service_key["api_key"]["id"],
        },
        headers=admin_headers,
    )
    assert installed.status_code == 200, installed.text
    return service_key["secret"]


async def module_login(
    client: AsyncClient, *, service_key: str, user_token: str, module_key: str
) -> str:
    """The SSO handoff for the user behind `user_token`; returns the module token."""
    ticket_response = await client.post(
        "/api/v1/module-auth/tickets/",
        json={"module_key": module_key, "redirect_uri": REDIRECT_URI, "state": "s"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert ticket_response.status_code == 201, ticket_response.text
    redirect_target = ticket_response.json()["redirect_target"]
    ticket = parse_qs(urlparse(redirect_target).query)["ticket"][0]

    exchange = await client.post(
        "/api/v1/module-auth/token/",
        json={"ticket": ticket},
        headers={"X-API-Key": service_key},
    )
    assert exchange.status_code == 200, exchange.text
    return exchange.json()["access_token"]
