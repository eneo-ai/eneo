"""Session identity regressions against PostgreSQL and the real API routes."""

from uuid import uuid4

import jwt
import pytest
from sqlalchemy import update

from eneo.authentication.federation_router import _jit_provision_user
from eneo.database.tables.spaces_table import Spaces
from eneo.database.tables.users_table import Users
from eneo.tenants.tenant import TenantBase
from eneo.users.user import UserAdd, UserState

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("same_tenant", [False, True])
@pytest.mark.parametrize("login_method", ["jit", "password"])
async def test_colliding_usernames_keep_identity_and_private_resources_isolated(
    client,
    db_container,
    admin_user,
    patch_auth_service_jwt,
    same_tenant: bool,
    login_method: str,
):
    owners = []
    tokens = []
    private_spaces = []
    password = "a sufficiently long test password"
    async with db_container() as container:
        first_tenant_id = admin_user.tenant_id
        second_tenant_id = first_tenant_id
        if not same_tenant:
            other_tenant = await container.tenant_repo().add(
                TenantBase(name=f"session-identity-{uuid4().hex}")
            )
            second_tenant_id = other_tenant.id

        for tenant_id, email in (
            (first_tenant_id, "anna.svensson@sundsvall.se"),
            (second_tenant_id, "anna.svensson@ange.se"),
        ):
            if login_method == "jit":
                owner = await _jit_provision_user(
                    container, tenant_id, email, "session-identity-regression"
                )
                token = container.auth_service().create_access_token_for_user(owner)
            else:
                salt, hashed = container.auth_service().create_salt_and_hashed_password(
                    password
                )
                owner = await container.user_repo().add(
                    UserAdd(
                        email=email,
                        username="anna.svensson",
                        tenant_id=tenant_id,
                        salt=salt,
                        password=hashed,
                        state=UserState.ACTIVE,
                    )
                )
                token = (
                    await container.user_service().login(email=email, password=password)
                ).access_token
            owners.append(owner)
            tokens.append(token)
            private_space = Spaces(
                name="Private", user_id=owner.id, tenant_id=owner.tenant_id
            )
            container.session().add(private_space)
            await container.session().flush()
            private_spaces.append(private_space.id)

    assert owners[0].username == owners[1].username
    for index, (owner, token) in enumerate(zip(owners, tokens, strict=True)):
        headers = {"Authorization": f"Bearer {token}"}
        response = await client.get("/api/v1/users/me/", headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["id"] == str(owner.id)
        assert response.json()["email"] == owner.email
        tenant_response = await client.get("/api/v1/users/tenant/", headers=headers)
        assert tenant_response.status_code == 200, tenant_response.text
        assert tenant_response.json()["id"] == str(owner.tenant_id)
        denied = await client.get(
            f"/api/v1/spaces/{private_spaces[1 - index]}/", headers=headers
        )
        assert denied.status_code in (403, 404), denied.text


async def test_session_stays_with_renamed_account_and_never_with_replacement(
    client,
    db_container,
    admin_user,
    patch_auth_service_jwt,
):
    async with db_container() as container:
        owner = await container.user_repo().add(
            UserAdd(
                email="original@example.com",
                username="original",
                tenant_id=admin_user.tenant_id,
                state=UserState.ACTIVE,
            )
        )
        token = container.auth_service().create_access_token_for_user(owner)
        await container.session().execute(
            update(Users)
            .where(Users.id == owner.id)
            .values(email="renamed@example.com", username="renamed")
        )
        replacement = await container.user_repo().add(
            UserAdd(
                email=owner.email,
                username=owner.username,
                tenant_id=owner.tenant_id,
                state=UserState.ACTIVE,
            )
        )
    assert owner.id != replacement.id
    headers = {"Authorization": f"Bearer {token}"}
    renamed = await client.get("/api/v1/users/me/", headers=headers)
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["id"] == str(owner.id)
    assert renamed.json()["email"] == "renamed@example.com"

    async with db_container() as container:
        await container.user_repo().delete(owner.id)
    deleted = await client.get("/api/v1/users/me/", headers=headers)
    assert deleted.status_code == 401, deleted.text


async def test_correctly_signed_token_cannot_pair_user_with_another_tenant(
    client,
    db_container,
    admin_user,
    patch_auth_service_jwt,
    test_settings,
):
    async with db_container() as container:
        other_tenant = await container.tenant_repo().add(
            TenantBase(name=f"other-{uuid4().hex}")
        )
        token = container.auth_service().create_access_token_for_user(admin_user)
    claims = jwt.decode(
        token,
        test_settings.jwt_secret,
        algorithms=[test_settings.jwt_algorithm],
        audience=test_settings.jwt_audience,
    )
    claims["tenant_id"] = str(other_tenant.id)
    mismatched_token = jwt.encode(
        claims, test_settings.jwt_secret, algorithm=test_settings.jwt_algorithm
    )
    response = await client.get(
        "/api/v1/users/me/", headers={"Authorization": f"Bearer {mismatched_token}"}
    )
    assert response.status_code == 401, response.text
