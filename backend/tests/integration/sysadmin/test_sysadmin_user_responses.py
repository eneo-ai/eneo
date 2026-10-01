"""
Integration tests for what the sysadmin user endpoints serialise.

The routes require the super API key, but their responses still leave the
process: they end up in operator scripts, shell history and proxy logs. The
stored password hash, its salt, API key hashes and the tenant's encrypted
provider and federation secrets must therefore never be part of them.

- POST /sysadmin/users/
- GET /sysadmin/users/
- GET /sysadmin/users/{user_id}/
- POST /sysadmin/users/{user_id}/
"""

from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from httpx import AsyncClient, Response

from eneo.database.database import sessionmanager
from eneo.database.tables.tenant_table import Tenants
from eneo.database.tables.users_table import Users

_PASSWORD = "IntegrationPass123!"
_PROVIDER_KEY_SENTINEL = "sentinel-encrypted-provider-api-key"
_CLIENT_SECRET_SENTINEL = "sentinel-encrypted-oidc-client-secret"

_FORBIDDEN_USER_FIELDS = ("password", "salt", "active_api_key")
_FORBIDDEN_TENANT_FIELDS = ("api_credentials", "federation_config")


@dataclass(frozen=True)
class _SeededUser:
    id: str
    tenant_id: str
    email: str
    password_hash: str
    salt: str
    create_response: Response


@pytest.fixture
async def seeded_user(client: AsyncClient, super_admin_token: str) -> _SeededUser:
    """A local-password user in a tenant that holds provider and OIDC secrets."""
    suffix = uuid4().hex[:8]
    headers = {"X-API-Key": super_admin_token}

    tenant_response = await client.post(
        "/api/v1/sysadmin/tenants/",
        json={"name": f"sysadmin-user-responses-{suffix}"},
        headers=headers,
    )
    assert tenant_response.status_code == 200, tenant_response.text
    tenant_id = tenant_response.json()["id"]

    # Written straight to the row: the credential and federation endpoints
    # depend on feature flags and IdP discovery that are irrelevant here.
    async with sessionmanager.session() as session, session.begin():
        await session.execute(
            sa.update(Tenants)
            .where(Tenants.id == UUID(tenant_id))
            .values(
                api_credentials={"openai": {"api_key": _PROVIDER_KEY_SENTINEL}},
                federation_config={
                    "provider": "entra",
                    "client_id": "sysadmin-user-responses",
                    "client_secret": _CLIENT_SECRET_SENTINEL,
                    "discovery_endpoint": "https://idp.example.com/.well-known/openid-configuration",
                },
            )
        )

    email = f"sysadmin-user-responses-{suffix}@example.com"
    create_response = await client.post(
        "/api/v1/sysadmin/users/",
        json={
            "email": email,
            "username": f"sysadmin-user-responses-{suffix}",
            "tenant_id": tenant_id,
            "password": _PASSWORD,
        },
        headers=headers,
    )
    assert create_response.status_code == 200, create_response.text
    user_id = create_response.json()["id"]

    async with sessionmanager.session() as session, session.begin():
        row = (
            await session.execute(
                sa.select(Users.password, Users.salt).where(Users.id == UUID(user_id))
            )
        ).one()

    # Guard the test itself: without stored secrets there is nothing to leak.
    assert row.password and row.salt

    return _SeededUser(
        id=user_id,
        tenant_id=tenant_id,
        email=email,
        password_hash=row.password,
        salt=row.salt,
        create_response=create_response,
    )


def _assert_no_credential_material(
    response: Response, user: dict[str, Any], seeded: _SeededUser
) -> None:
    tenant = user.get("tenant") or {}
    leaked = [f for f in _FORBIDDEN_USER_FIELDS if f in user]
    leaked += [f"tenant.{f}" for f in _FORBIDDEN_TENANT_FIELDS if f in tenant]

    # Independent of field names, so a renamed or re-nested field is caught too.
    leaked += [
        f"value of {name}"
        for name, value in (
            ("password hash", seeded.password_hash),
            ("salt", seeded.salt),
            ("provider api key", _PROVIDER_KEY_SENTINEL),
            ("federation client secret", _CLIENT_SECRET_SENTINEL),
        )
        if value in response.text
    ]

    # One assertion, so a failure lists everything that leaked.
    assert leaked == [], f"response exposes credential material: {leaked}"


def _assert_identifies_user(user: dict[str, Any], seeded: _SeededUser) -> None:
    """The fields operators script against must survive the projection."""
    assert user["id"] == seeded.id
    assert user["email"] == seeded.email
    assert user["tenant_id"] == seeded.tenant_id
    assert user["state"] == "active"
    assert isinstance(user["roles"], list)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_user_response_omits_credential_material(
    seeded_user: _SeededUser,
):
    response = seeded_user.create_response
    user = response.json()

    _assert_no_credential_material(response, user, seeded_user)
    _assert_identifies_user(user, seeded_user)
    # The one secret this endpoint is meant to hand out.
    assert user["access_token"]["access_token"]
    assert user["access_token"]["token_type"] == "bearer"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_users_response_omits_credential_material(
    client: AsyncClient, super_admin_token: str, seeded_user: _SeededUser
):
    response = await client.get(
        "/api/v1/sysadmin/users/",
        headers={"X-API-Key": super_admin_token},
    )
    assert response.status_code == 200, response.text

    items = response.json()["items"]
    assert len(items) >= 2, "expected the seeded user and the baseline user"
    for item in items:
        _assert_no_credential_material(response, item, seeded_user)

    user = next(item for item in items if item["id"] == seeded_user.id)
    _assert_identifies_user(user, seeded_user)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_user_response_omits_credential_material(
    client: AsyncClient, super_admin_token: str, seeded_user: _SeededUser
):
    response = await client.get(
        f"/api/v1/sysadmin/users/{seeded_user.id}/",
        headers={"X-API-Key": super_admin_token},
    )
    assert response.status_code == 200, response.text
    user = response.json()

    _assert_no_credential_material(response, user, seeded_user)
    _assert_identifies_user(user, seeded_user)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_update_user_response_omits_credential_material(
    client: AsyncClient, super_admin_token: str, seeded_user: _SeededUser
):
    response = await client.post(
        f"/api/v1/sysadmin/users/{seeded_user.id}/",
        json={"quota_limit": 5000},
        headers={"X-API-Key": super_admin_token},
    )
    assert response.status_code == 200, response.text
    user = response.json()

    _assert_no_credential_material(response, user, seeded_user)
    _assert_identifies_user(user, seeded_user)
    assert user["quota_limit"] == 5000
