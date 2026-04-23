"""Integration tests for UsersRepository.get_group_members_permission_summary.

Covers the load-bearing invariants of the inert-member advisory query:

- Tenant scoping on both legs (group membership + role grants): a cross-tenant
  group must not leak rows.
- Soft-deleted users excluded from BOTH the loginable total AND the missing
  subset, so the ratio "N of M missing" is internally consistent.
- Non-loginable states (pending/inactive) excluded.
- NULL-safety: `NOT EXISTS` must not filter rows because of NULL role rows
  the way `NOT IN` would.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from intric.database.tables.roles_table import Roles
from intric.database.tables.tenant_table import Tenants
from intric.database.tables.user_groups_table import UserGroups
from intric.database.tables.users_table import (
    Users,
    usergroups_users_table,
    users_roles_table,
)
from intric.users.user import UserState

SHARED_SPACES = "shared_spaces"


async def _insert_tenant(session) -> UUID:
    tid = uuid4()
    await session.execute(
        sa.insert(Tenants).values(
            id=tid,
            name=f"tenant-{tid.hex[:8]}",
            quota_limit=1_000_000,
        )
    )
    return tid


async def _insert_role(
    session, tenant_id: UUID, name: str, permissions: list[str]
) -> UUID:
    rid = uuid4()
    await session.execute(
        sa.insert(Roles).values(
            id=rid, name=name, permissions=permissions, tenant_id=tenant_id
        )
    )
    return rid


async def _insert_user(
    session,
    *,
    tenant_id: UUID,
    email: str,
    username: str,
    state: str = UserState.ACTIVE,
    deleted: bool = False,
) -> UUID:
    uid = uuid4()
    await session.execute(
        sa.insert(Users).values(
            id=uid,
            email=email,
            username=username,
            state=state,
            tenant_id=tenant_id,
            deleted_at=sa.func.now() if deleted else None,
        )
    )
    return uid


async def _attach_role(session, user_id: UUID, role_id: UUID) -> None:
    await session.execute(
        sa.insert(users_roles_table).values(user_id=user_id, role_id=role_id)
    )


async def _insert_group(session, tenant_id: UUID, name: str) -> UUID:
    gid = uuid4()
    await session.execute(
        sa.insert(UserGroups).values(id=gid, name=name, tenant_id=tenant_id)
    )
    return gid


async def _add_to_group(session, user_id: UUID, group_id: UUID) -> None:
    await session.execute(
        sa.insert(usergroups_users_table).values(
            user_id=user_id, user_group_id=group_id
        )
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_summary_all_granted(db_container):
    async with db_container() as container:
        session = container.session()
        tid = await _insert_tenant(session)
        role_ok = await _insert_role(session, tid, "ok", [SHARED_SPACES])
        gid = await _insert_group(session, tid, "g-ok")

        uid_a = await _insert_user(session, tenant_id=tid, email="a@x", username="a")
        uid_b = await _insert_user(session, tenant_id=tid, email="b@x", username="b")
        await _attach_role(session, uid_a, role_ok)
        await _attach_role(session, uid_b, role_ok)
        await _add_to_group(session, uid_a, gid)
        await _add_to_group(session, uid_b, gid)

        repo = container.user_repo()
        total, missing_count, sample = await repo.get_group_members_permission_summary(
            group_id=gid, tenant_id=tid, permission=SHARED_SPACES
        )
        assert total == 2
        assert missing_count == 0
        assert sample == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_summary_some_missing(db_container):
    async with db_container() as container:
        session = container.session()
        tid = await _insert_tenant(session)
        role_ok = await _insert_role(session, tid, "ok", [SHARED_SPACES])
        role_plain = await _insert_role(session, tid, "plain", ["admin"])
        gid = await _insert_group(session, tid, "g-mix")

        granted = await _insert_user(session, tenant_id=tid, email="g@x", username="g")
        inert = await _insert_user(session, tenant_id=tid, email="i@x", username="i")
        await _attach_role(session, granted, role_ok)
        await _attach_role(session, inert, role_plain)
        await _add_to_group(session, granted, gid)
        await _add_to_group(session, inert, gid)

        repo = container.user_repo()
        total, missing_count, sample = await repo.get_group_members_permission_summary(
            group_id=gid, tenant_id=tid, permission=SHARED_SPACES
        )
        assert total == 2
        assert missing_count == 1
        assert [row.id for row in sample] == [inert]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_summary_all_missing(db_container):
    async with db_container() as container:
        session = container.session()
        tid = await _insert_tenant(session)
        role_plain = await _insert_role(session, tid, "plain", ["admin"])
        gid = await _insert_group(session, tid, "g-none")

        u1 = await _insert_user(session, tenant_id=tid, email="x1@x", username="x1")
        u2 = await _insert_user(session, tenant_id=tid, email="x2@x", username="x2")
        await _attach_role(session, u1, role_plain)
        await _attach_role(session, u2, role_plain)
        await _add_to_group(session, u1, gid)
        await _add_to_group(session, u2, gid)

        repo = container.user_repo()
        total, missing_count, sample = await repo.get_group_members_permission_summary(
            group_id=gid, tenant_id=tid, permission=SHARED_SPACES
        )
        assert total == 2
        assert missing_count == 2
        assert sorted(row.id for row in sample) == sorted([u1, u2])


@pytest.mark.asyncio
@pytest.mark.integration
async def test_summary_excludes_soft_deleted_and_non_loginable(db_container):
    async with db_container() as container:
        session = container.session()
        tid = await _insert_tenant(session)
        role_plain = await _insert_role(session, tid, "plain", ["admin"])
        gid = await _insert_group(session, tid, "g-filter")

        active = await _insert_user(
            session, tenant_id=tid, email="live@x", username="live"
        )
        deleted = await _insert_user(
            session, tenant_id=tid, email="del@x", username="del", deleted=True
        )
        pending = await _insert_user(
            session,
            tenant_id=tid,
            email="pend@x",
            username="pend",
            state=UserState.PENDING,
        )
        for uid in (active, deleted, pending):
            await _attach_role(session, uid, role_plain)
            await _add_to_group(session, uid, gid)

        repo = container.user_repo()
        total, missing_count, sample = await repo.get_group_members_permission_summary(
            group_id=gid, tenant_id=tid, permission=SHARED_SPACES
        )
        # Only the active user counts in the loginable pool; deleted and
        # pending are filtered from both total and missing.
        assert total == 1
        assert missing_count == 1
        assert [row.id for row in sample] == [active]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_summary_tenant_isolated(db_container):
    async with db_container() as container:
        session = container.session()
        tenant_a = await _insert_tenant(session)
        tenant_b = await _insert_tenant(session)

        role_plain_a = await _insert_role(session, tenant_a, "plain", ["admin"])
        gid_a = await _insert_group(session, tenant_a, "group-a")
        u_a = await _insert_user(session, tenant_id=tenant_a, email="a@x", username="a")
        await _attach_role(session, u_a, role_plain_a)
        await _add_to_group(session, u_a, gid_a)

        # Tenant-b user in tenant-b's group (should never surface for tenant-a).
        role_plain_b = await _insert_role(session, tenant_b, "plain", ["admin"])
        gid_b = await _insert_group(session, tenant_b, "group-b")
        u_b = await _insert_user(session, tenant_id=tenant_b, email="b@x", username="b")
        await _attach_role(session, u_b, role_plain_b)
        await _add_to_group(session, u_b, gid_b)

        repo = container.user_repo()
        # Asking for tenant-b's group WITH tenant-a's tenant_id must yield no
        # rows — the loginable join is tenant-scoped.
        total, missing_count, sample = await repo.get_group_members_permission_summary(
            group_id=gid_b, tenant_id=tenant_a, permission=SHARED_SPACES
        )
        assert total == 0
        assert missing_count == 0
        assert sample == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_summary_sample_capped_at_sample_size(db_container):
    """With more inert users than `sample_size`, the full count is accurate
    but the sample is capped. Truncation flag upstream is computed from
    `missing_count > len(sample)`.
    """
    async with db_container() as container:
        session = container.session()
        tid = await _insert_tenant(session)
        role_plain = await _insert_role(session, tid, "plain", ["admin"])
        gid = await _insert_group(session, tid, "g-big")

        for n in range(15):
            uid = await _insert_user(
                session,
                tenant_id=tid,
                email=f"u{n:02}@x",
                username=f"u{n:02}",
            )
            await _attach_role(session, uid, role_plain)
            await _add_to_group(session, uid, gid)

        repo = container.user_repo()
        total, missing_count, sample = await repo.get_group_members_permission_summary(
            group_id=gid, tenant_id=tid, permission=SHARED_SPACES, sample_size=5
        )
        assert total == 15
        assert missing_count == 15
        assert len(sample) == 5
        # Deterministic order — ensures UI preview isn't flickery between calls.
        assert [row.email for row in sample] == [
            "u00@x",
            "u01@x",
            "u02@x",
            "u03@x",
            "u04@x",
        ]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_summary_user_with_no_roles_is_missing(db_container):
    """Regression: a loginable user with zero role grants must count as
    missing the permission (NOT EXISTS correctly returns true for empty set).
    """
    async with db_container() as container:
        session = container.session()
        tid = await _insert_tenant(session)
        gid = await _insert_group(session, tid, "g-roleless")
        roleless = await _insert_user(
            session, tenant_id=tid, email="nr@x", username="nr"
        )
        await _add_to_group(session, roleless, gid)

        repo = container.user_repo()
        total, missing_count, sample = await repo.get_group_members_permission_summary(
            group_id=gid, tenant_id=tid, permission=SHARED_SPACES
        )
        assert total == 1
        assert missing_count == 1
        assert [row.id for row in sample] == [roleless]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_summary_ignores_cross_tenant_role_grants(db_container):
    """Regression: the role-grant leg of the anti-join must be tenant-scoped.

    `users_roles` has no tenant column of its own. If a user in tenant A
    has a cross-tenant role edge pointing at a role that belongs to
    tenant B (ever, even if the API prevents it today), the summary must
    still treat that user as lacking the permission for tenant A — it
    cannot let a foreign-tenant role grant satisfy the subquery.
    """
    async with db_container() as container:
        session = container.session()
        tenant_a = await _insert_tenant(session)
        tenant_b = await _insert_tenant(session)

        # Tenant A has only a plain role without shared_spaces.
        role_plain_a = await _insert_role(session, tenant_a, "plain", ["admin"])
        # Tenant B has a role WITH shared_spaces — attempting to grant it
        # across tenants would otherwise falsely satisfy grant_exists.
        role_shared_b = await _insert_role(session, tenant_b, "shared", [SHARED_SPACES])

        gid = await _insert_group(session, tenant_a, "g-xtenant")
        user = await _insert_user(
            session, tenant_id=tenant_a, email="xt@x", username="xt"
        )
        await _attach_role(session, user, role_plain_a)
        await _attach_role(session, user, role_shared_b)  # foreign role edge
        await _add_to_group(session, user, gid)

        repo = container.user_repo()
        total, missing_count, sample = await repo.get_group_members_permission_summary(
            group_id=gid, tenant_id=tenant_a, permission=SHARED_SPACES
        )
        # The foreign grant must NOT count. User is still missing from A's POV.
        assert total == 1
        assert missing_count == 1
        assert [row.id for row in sample] == [user]
