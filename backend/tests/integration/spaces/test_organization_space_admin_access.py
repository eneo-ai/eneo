"""A revoked admin role takes the organization space with it.

Tenant admins become ADMIN members of the organization space, and that row
outlives the admin role. Access there follows the admin permission held now,
and the next time the organization space is loaded the row is removed.
"""

import hashlib
import secrets
from uuid import UUID

import pytest
import sqlalchemy as sa

from eneo.authentication.auth_models import (
    ApiKeyHashVersion,
    ApiKeyPermission,
    ApiKeyScopeType,
    ApiKeyState,
    ApiKeyType,
)
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.roles_table import Roles
from eneo.database.tables.spaces_table import Spaces, SpacesUsers
from eneo.main.exceptions import NotFoundException

pytestmark = pytest.mark.integration


@pytest.fixture
async def organization_spaces(db_container, tenant_factory, user_factory):
    """Two tenants' private resources; the caller has no organization row."""
    async with db_container() as container:
        session = container.session()
        own = await container.space_service().get_or_create_tenant_space()
        foreign_tenant = await tenant_factory(session)
        foreign_user = await user_factory(session, tenant_id=foreign_tenant.id)
        foreign = Spaces(name="Foreign organization", tenant_id=foreign_tenant.id)
        session.add(foreign)
        await session.flush()
        for space_id, user_id, name in (
            (own.id, container.user().id, "Private own assistant"),
            (foreign.id, foreign_user.id, "Private foreign assistant"),
        ):
            session.add(
                Assistants(
                    name=name,
                    space_id=space_id,
                    user_id=user_id,
                    logging_enabled=False,
                    is_default=False,
                    published=False,
                )
            )
        await session.execute(
            sa.delete(SpacesUsers).where(SpacesUsers.space_id == own.id)
        )
        return own.id, foreign.id


@pytest.mark.parametrize("suffix", ["", "knowledge/", "applications/"])
async def test_session_admin_reads_only_their_own_organization_space(
    client,
    db_container,
    admin_user,
    patch_auth_service_jwt,
    organization_spaces,
    suffix,
):
    own_id, foreign_id = organization_spaces
    async with db_container() as container:
        token = container.auth_service().create_access_token_for_user(admin_user)
    headers = {"Authorization": f"Bearer {token}"}

    own = await client.get(f"/api/v1/spaces/{own_id}/{suffix}", headers=headers)
    assert own.status_code == 200, own.text
    if suffix == "applications/":
        assert "Private own assistant" in {
            assistant["name"] for assistant in own.json()["assistants"]["items"]
        }

    foreign = await client.get(f"/api/v1/spaces/{foreign_id}/{suffix}", headers=headers)
    assert foreign.status_code == 404, foreign.text
    assert "Private foreign assistant" not in foreign.text


async def test_application_projection_does_not_load_another_tenants_resources(
    db_container, organization_spaces
):
    own_id, foreign_id = organization_spaces
    async with db_container() as container:
        repo = container.space_repo()
        with pytest.raises(NotFoundException):
            await repo.get_applications_projection(foreign_id)
        own = await repo.get_applications_projection(own_id)
        assert "Private own assistant" in {item.name for item in own.assistants}


async def test_org_key_owner_check_rejects_a_foreign_tenant_before_route_authorization(
    client, db_container, admin_user, organization_spaces
):
    _, foreign_id = organization_spaces
    # Deliberately inconsistent persisted scope. An admin in the key's tenant
    # must not count as an admin of the foreign organization during authentication.
    secret = await _mint_space_key(db_container, admin_user, str(foreign_id))
    response = await client.get(
        f"/api/v1/spaces/{foreign_id}/applications/", headers={"X-API-Key": secret}
    )
    assert response.status_code == 403, response.text
    assert response.json()["code"] == "owner_membership_revoked"


async def _revoke_admin_role(db_container, user) -> None:
    # The container's session runs in a transaction it commits on exit.
    async with db_container() as container:
        await container.session().execute(
            sa.update(Roles)
            .where(Roles.id.in_([role.id for role in user.roles]))
            .values(permissions=sa.func.array_remove(Roles.permissions, "admin"))
        )


async def _membership_roles(db_container, space_id: str, user_id: UUID) -> list[str]:
    async with db_container() as container:
        result = await container.session().execute(
            sa.select(SpacesUsers.role).where(
                SpacesUsers.space_id == UUID(space_id),
                SpacesUsers.user_id == user_id,
            )
        )
        return list(result.scalars().all())


async def _listed_space_ids(client, headers) -> set[str]:
    response = await client.get("/api/v1/spaces/", headers=headers)
    assert response.status_code == 200
    return {space["id"] for space in response.json()["items"]}


async def test_a_revoked_admin_role_closes_the_organization_space(
    client, db_container, admin_user, patch_auth_service_jwt
):
    # A signed-in session: a tenant-scoped API key already stops working when
    # its owner loses the admin role.
    async with db_container() as container:
        token = container.auth_service().create_access_token_for_user(admin_user)
    headers = {"Authorization": f"Bearer {token}"}
    response = await client.get("/api/v1/spaces/type/organization/", headers=headers)
    assert response.status_code == 200
    org_space_id = response.json()["id"]
    assert await _membership_roles(db_container, org_space_id, admin_user.id) == [
        "admin"
    ]
    assert org_space_id in await _listed_space_ids(client, headers)

    await _revoke_admin_role(db_container, admin_user)

    # The row is still there, but it grants nothing.
    assert await _membership_roles(db_container, org_space_id, admin_user.id) == [
        "admin"
    ]
    paths = [
        f"/api/v1/spaces/{org_space_id}/",
        f"/api/v1/spaces/{org_space_id}/knowledge/",
        f"/api/v1/spaces/{org_space_id}/applications/",
    ]
    codes = [(await client.get(path, headers=headers)).status_code for path in paths]
    assert codes == [403, 403, 403]
    assert org_space_id not in await _listed_space_ids(client, headers)

    # Creating a space loads the organization space, which drops the row.
    response = await client.post(
        "/api/v1/spaces/", json={"name": "Efter rollbytet"}, headers=headers
    )
    assert response.status_code == 201
    assert await _membership_roles(db_container, org_space_id, admin_user.id) == []


async def _mint_space_key(db_container, user, space_id: str) -> str:
    plain_key = f"test_{secrets.token_hex(32)}"
    async with db_container() as container:
        await container.api_key_v2_repo().create(
            tenant_id=user.tenant_id,
            owner_user_id=user.id,
            created_by_user_id=user.id,
            scope_type=ApiKeyScopeType.SPACE.value,
            scope_id=UUID(space_id),
            permission=ApiKeyPermission.READ.value,
            key_type=ApiKeyType.SK.value,
            key_hash=hashlib.sha256(plain_key.encode()).hexdigest(),
            hash_version=ApiKeyHashVersion.SHA256.value,
            key_prefix="test_",
            key_suffix=plain_key[-4:],
            name="Organization space key",
            description=None,
            state=ApiKeyState.ACTIVE.value,
        )
    return plain_key


async def test_an_organization_space_key_follows_its_owners_admin_role(
    client, db_container, admin_user, patch_auth_service_jwt
):
    async with db_container() as container:
        token = container.auth_service().create_access_token_for_user(admin_user)
    response = await client.get(
        "/api/v1/spaces/type/organization/",
        headers={"Authorization": f"Bearer {token}"},
    )
    org_space_id = response.json()["id"]
    key_headers = {
        "X-API-Key": await _mint_space_key(db_container, admin_user, org_space_id)
    }
    # An admin without a row, as after the role was given back.
    async with db_container() as container:
        await container.session().execute(
            sa.delete(SpacesUsers).where(SpacesUsers.space_id == UUID(org_space_id))
        )

    response = await client.get(f"/api/v1/spaces/{org_space_id}/", headers=key_headers)
    assert response.status_code == 200, response.text

    await _revoke_admin_role(db_container, admin_user)

    response = await client.get(f"/api/v1/spaces/{org_space_id}/", headers=key_headers)
    assert response.status_code == 403
    assert response.json()["code"] == "owner_membership_revoked"
