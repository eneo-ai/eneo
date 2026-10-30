"""System owners are created atomically in the caller's tenant transaction."""

import asyncio
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.users_table import Users
from eneo.main.exceptions import UniqueException
from eneo.tenants.tenant import TenantBase

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_new_system_owners_are_inactive_and_tenant_scoped(
    db_container, admin_user
):
    async with db_container() as container:
        other = await container.tenant_service().create_tenant(
            TenantBase(name=f"system-owner-{uuid4()}")
        )
        assert other is not None
        repo = container.user_repo()
        first = await repo.get_or_create_system_user_id_for_tenant(admin_user.tenant_id)
        second = await repo.get_or_create_system_user_id_for_tenant(other.id)

        assert first != second
        for user_id, tenant_id in [(first, admin_user.tenant_id), (second, other.id)]:
            row = await container.session().get(Users, user_id)
            assert row is not None
            assert row.tenant_id == tenant_id
            assert row.is_system_user is True
            assert row.is_active is False
            assert row.state == "inactive"
            assert row.email_verified is False
            assert row.password is None
            assert row.salt is None
            assert row.email == f"system+{tenant_id}@eneo.local"
            assert user_id not in {
                user.id for user in await repo.get_all_users(tenant_id=tenant_id)
            }


async def test_reuses_existing_system_owner_without_replacing_its_identity(
    db_container, admin_user
):
    async with db_container() as container:
        owner = Users(
            tenant_id=admin_user.tenant_id,
            email="existing-system@example.com",
            state="inactive",
            is_active=False,
            is_system_user=True,
        )
        container.session().add(owner)
        await container.session().flush()

        assert (
            await container.user_repo().get_or_create_system_user_id_for_tenant(
                admin_user.tenant_id
            )
            == owner.id
        )
        assert owner.email == "existing-system@example.com"
        assert (
            await container.session().scalar(
                sa.select(sa.func.count())
                .select_from(Users)
                .where(
                    Users.tenant_id == admin_user.tenant_id,
                    Users.is_system_user.is_(True),
                )
            )
            == 1
        )


async def test_system_owner_creation_rolls_back_with_its_caller(
    db_container, admin_user
):
    with pytest.raises(RuntimeError, match="installation failed"):
        async with db_container() as container:
            await container.user_repo().get_or_create_system_user_id_for_tenant(
                admin_user.tenant_id
            )
            raise RuntimeError("installation failed")

    async with db_container() as container:
        assert (
            await container.user_repo().get_system_user_id_for_tenant(
                admin_user.tenant_id
            )
            is None
        )


async def test_concurrent_first_requests_reuse_one_committed_owner(
    db_container, admin_user, monkeypatch
):
    both_missing = asyncio.Barrier(2)

    async def create() -> UUID:
        async with db_container() as container:
            repo = container.user_repo()
            read = repo.get_system_user_id_for_tenant

            async def read_together(tenant_id: UUID) -> UUID | None:
                owner = await read(tenant_id)
                if owner is None:
                    await both_missing.wait()
                return owner

            monkeypatch.setattr(repo, "get_system_user_id_for_tenant", read_together)
            return await repo.get_or_create_system_user_id_for_tenant(
                admin_user.tenant_id
            )

    async with asyncio.timeout(30):
        first, second = await asyncio.gather(create(), create())
    assert first == second
    async with db_container() as container:
        assert (
            await container.session().scalar(
                sa.select(sa.func.count())
                .select_from(Users)
                .where(
                    Users.tenant_id == admin_user.tenant_id,
                    Users.is_system_user.is_(True),
                )
            )
            == 1
        )


async def test_conflicting_identity_is_not_promoted_to_system_owner(
    db_container, admin_user
):
    async with db_container() as container:
        occupant = Users(
            tenant_id=admin_user.tenant_id,
            email=f"system+{admin_user.tenant_id}@eneo.local",
            state="inactive",
            is_system_user=False,
        )
        container.session().add(occupant)
        await container.session().flush()
        occupant_id = occupant.id

    with pytest.raises(UniqueException):
        async with db_container() as container:
            await container.user_repo().get_or_create_system_user_id_for_tenant(
                admin_user.tenant_id
            )

    async with db_container() as container:
        occupant = await container.session().get(Users, occupant_id)
        assert occupant is not None
        assert occupant.is_system_user is False
        assert (
            await container.user_repo().get_system_user_id_for_tenant(
                admin_user.tenant_id
            )
            is None
        )
