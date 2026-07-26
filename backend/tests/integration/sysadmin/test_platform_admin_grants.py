from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import insert, select, update

from eneo.database.tables.users_table import Users
from eneo.users.user import UserState
from eneo.users.user_repo import PlatformAdminGrantIneligible


@pytest.fixture
async def admin_token(db_container, admin_user, patch_auth_service_jwt) -> str:
    async with db_container() as container:
        return container.auth_service().create_access_token_for_user(admin_user)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_platform_admin_grant_is_idempotent_for_eligible_admin(
    db_container, admin_user
) -> None:
    async with db_container() as container:
        repository = container.user_repo()

        assert await repository.set_platform_admin(admin_user.id, enabled=True) == (
            False,
            True,
        )
        assert await repository.set_platform_admin(admin_user.id, enabled=True) == (
            True,
            True,
        )
        assert (
            await container.session().scalar(
                select(Users.is_platform_admin).where(Users.id == admin_user.id)
            )
            is True
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_platform_admin_grant_rejects_system_user(
    db_container, admin_user
) -> None:
    system_user_id = uuid4()
    async with db_container() as container:
        session = container.session()
        await session.execute(
            insert(Users).values(
                id=system_user_id,
                email=f"system+{system_user_id.hex[:8]}@example.com",
                username=f"system+{system_user_id.hex[:8]}",
                email_verified=False,
                is_active=False,
                state=UserState.ACTIVE.value,
                used_tokens=0,
                tenant_id=admin_user.tenant_id,
                is_system_user=True,
            )
        )

        with pytest.raises(PlatformAdminGrantIneligible):
            await container.user_repo().set_platform_admin(system_user_id, enabled=True)
        assert (
            await session.scalar(
                select(Users.is_platform_admin).where(Users.id == system_user_id)
            )
            is False
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_platform_admin_revoke_works_for_dormant_soft_deleted_user(
    db_container, admin_user
) -> None:
    async with db_container() as container:
        session = container.session()
        repository = container.user_repo()
        assert await repository.set_platform_admin(admin_user.id, enabled=True) == (
            False,
            True,
        )

        await session.execute(
            update(Users)
            .where(Users.id == admin_user.id)
            .values(
                state=UserState.DELETED.value,
                deleted_at=datetime.now(timezone.utc),
            )
        )

        assert await repository.set_platform_admin(admin_user.id, enabled=False) == (
            True,
            False,
        )
        assert (
            await session.scalar(
                select(Users.is_platform_admin).where(Users.id == admin_user.id)
            )
            is False
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_platform_admin_revoke_missing_user_returns_none(db_container) -> None:
    async with db_container() as container:
        assert (
            await container.user_repo().set_platform_admin(uuid4(), enabled=False)
            is None
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_platform_admin_endpoint_requires_super_key_and_round_trips(
    client, super_admin_token, admin_user, admin_token
) -> None:
    path = f"/api/v1/sysadmin/users/{admin_user.id}/platform-admin"

    unauthorized = await client.put(path, json={"enabled": True})
    assert unauthorized.status_code == 401

    granted = await client.put(
        path,
        headers={"X-API-Key": super_admin_token},
        json={"enabled": True},
    )
    assert granted.status_code == 200, granted.text
    assert granted.json() == {
        "user_id": str(admin_user.id),
        "is_platform_admin": True,
    }
    current_user = await client.get(
        "/api/v1/users/me/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert current_user.status_code == 200, current_user.text
    assert current_user.json()["is_platform_admin"] is True

    revoked = await client.put(
        path,
        headers={"X-API-Key": super_admin_token},
        json={"enabled": False},
    )
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["is_platform_admin"] is False
    current_user = await client.get(
        "/api/v1/users/me/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert current_user.status_code == 200, current_user.text
    assert current_user.json()["is_platform_admin"] is False
