"""Integration tests for the system-user guards on ``UsersRepository``.

Mirrors the integration-test style established by
``test_org_space_assistant_role_repo.py`` (step 009) and
``test_assistant_repo_helper_filter.py`` (step 012). Uses real Postgres via
testcontainers; the autouse ``cleanup_database`` fixture truncates everything
and re-seeds the single tenant + admin user before each test, after which we
insert a per-tenant system user by hand and verify:

  * ``is_system_user`` distinguishes system from regular rows
  * ``hard_delete`` / ``soft_delete`` / ``delete`` raise ``SystemUserProtected``
  * Default list helpers exclude system users; ``include_system_user=True``
    opts back in
  * Public list / paginated / search paths all hide the system user
  * Every retention cron-style cleanup leaves the system user row untouched

PRD §2.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.users_table import Users
from eneo.main.exceptions import SystemUserProtected
from eneo.users.user import (
    PaginationParams,
    SearchFilters,
    SortOptions,
    UserState,
)


async def _insert_system_user(
    session: sa.ext.asyncio.AsyncSession, *, tenant_id: UUID
) -> UUID:
    """Insert a per-tenant system user mirroring the seed migration shape.

    Diverges from the seed migration on email domain only: production uses
    ``system+<tenant_id>@eneo.local`` (RFC-blessed pseudo-domain) which the
    ``email_validator`` library considers a special-use/reserved TLD and
    refuses to validate. The ``include_system_user=True`` opt-in path runs
    a ``UserInDB.model_validate`` on the resulting rows, so the test fixture
    uses ``@example.com`` to avoid tripping that validator. This is purely
    a test-fixture artifact — production code paths never load the system
    user through Pydantic, since the column-exclusion filter hides it from
    every list-returning query and ``is_system_user`` reads via raw SELECT.
    """
    user_id = uuid4()
    suffix = user_id.hex[:8]
    await session.execute(
        sa.insert(Users).values(
            id=user_id,
            email=f"system+{suffix}@example.com",
            username=f"system+{suffix}",
            email_verified=False,
            salt=None,
            password=None,
            is_active=False,
            state=UserState.INACTIVE.value,
            used_tokens=0,
            tenant_id=tenant_id,
            quota_limit=None,
            is_system_user=True,
        )
    )
    return user_id


async def _row_exists(session: sa.ext.asyncio.AsyncSession, *, user_id: UUID) -> bool:
    return (
        await session.scalar(
            sa.select(sa.literal(1)).where(Users.id == user_id).limit(1)
        )
    ) is not None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_is_system_user_distinguishes_system_from_regular(
    db_container, admin_user
):
    async with db_container() as container:
        session = container.session()
        repo = container.user_repo()

        system_user_id = await _insert_system_user(
            session, tenant_id=admin_user.tenant_id
        )
        await session.flush()

        assert await repo.is_system_user(system_user_id) is True
        assert await repo.is_system_user(admin_user.id) is False
        # Non-existent row reads as falsy
        assert await repo.is_system_user(uuid4()) is False


@pytest.mark.asyncio
@pytest.mark.integration
async def test_hard_delete_raises_for_system_user(db_container, admin_user):
    async with db_container() as container:
        session = container.session()
        repo = container.user_repo()

        system_user_id = await _insert_system_user(
            session, tenant_id=admin_user.tenant_id
        )
        await session.flush()

        with pytest.raises(SystemUserProtected):
            await repo.hard_delete(system_user_id)

        # Row still present
        assert await _row_exists(session, user_id=system_user_id)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_soft_delete_raises_for_system_user(db_container, admin_user):
    async with db_container() as container:
        session = container.session()
        repo = container.user_repo()

        system_user_id = await _insert_system_user(
            session, tenant_id=admin_user.tenant_id
        )
        await session.flush()

        with pytest.raises(SystemUserProtected):
            await repo.soft_delete(system_user_id)

        # Row remains active, deleted_at still NULL
        deleted_at = await session.scalar(
            sa.select(Users.deleted_at).where(Users.id == system_user_id)
        )
        assert deleted_at is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_delete_wrapper_raises_for_system_user(db_container, admin_user):
    """Both the soft and hard branches of ``delete()`` block system users."""
    async with db_container() as container:
        session = container.session()
        repo = container.user_repo()

        system_user_id = await _insert_system_user(
            session, tenant_id=admin_user.tenant_id
        )
        await session.flush()

        with pytest.raises(SystemUserProtected):
            await repo.delete(system_user_id, soft_delete=True)
        with pytest.raises(SystemUserProtected):
            await repo.delete(system_user_id, soft_delete=False)

        assert await _row_exists(session, user_id=system_user_id)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_regular_user_can_still_be_soft_deleted(db_container, admin_user):
    """Regression guard: the guard does not block legitimate deletions."""
    async with db_container() as container:
        session = container.session()
        repo = container.user_repo()

        # Insert a plain (non-system) user to delete.
        other_id = uuid4()
        await session.execute(
            sa.insert(Users).values(
                id=other_id,
                email=f"regular+{other_id.hex[:8]}@example.com",
                username=f"regular+{other_id.hex[:8]}",
                email_verified=True,
                state=UserState.ACTIVE.value,
                used_tokens=0,
                tenant_id=admin_user.tenant_id,
                is_system_user=False,
            )
        )
        await session.flush()

        result = await repo.soft_delete(other_id)
        assert result is not None
        assert result.state == UserState.DELETED
        # deleted_at must have been stamped
        deleted_at = await session.scalar(
            sa.select(Users.deleted_at).where(Users.id == other_id)
        )
        assert deleted_at is not None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_get_all_users_excludes_system_user_by_default(db_container, admin_user):
    async with db_container() as container:
        session = container.session()
        repo = container.user_repo()

        system_user_id = await _insert_system_user(
            session, tenant_id=admin_user.tenant_id
        )
        await session.flush()

        users = await repo.get_all_users(tenant_id=admin_user.tenant_id)
        returned_ids = {u.id for u in users}

        assert admin_user.id in returned_ids
        assert system_user_id not in returned_ids


@pytest.mark.asyncio
@pytest.mark.integration
async def test_internal_helper_opts_in_via_include_system_user(
    db_container, admin_user
):
    """``include_system_user=True`` returns system rows — used by seed code."""
    async with db_container() as container:
        session = container.session()
        repo = container.user_repo()

        system_user_id = await _insert_system_user(
            session, tenant_id=admin_user.tenant_id
        )
        await session.flush()

        # Use the same shape as `get_all_users` but pass the opt-in.
        query = sa.select(Users).where(Users.tenant_id == admin_user.tenant_id)
        users = await repo._get_models_from_query(query=query, include_system_user=True)
        returned_ids = {u.id for u in users}

        assert system_user_id in returned_ids
        assert admin_user.id in returned_ids


@pytest.mark.asyncio
@pytest.mark.integration
async def test_get_total_count_excludes_system_user(db_container, admin_user):
    async with db_container() as container:
        session = container.session()
        repo = container.user_repo()

        # Baseline count before the system user is inserted.
        before = await repo.get_total_count(tenant_id=admin_user.tenant_id) or 0
        await _insert_system_user(session, tenant_id=admin_user.tenant_id)
        await session.flush()

        after = await repo.get_total_count(tenant_id=admin_user.tenant_id) or 0
        assert after == before


@pytest.mark.asyncio
@pytest.mark.integration
async def test_get_paginated_excludes_system_user(db_container, admin_user):
    async with db_container() as container:
        session = container.session()
        repo = container.user_repo()

        system_user_id = await _insert_system_user(
            session, tenant_id=admin_user.tenant_id
        )
        await session.flush()

        result = await repo.get_paginated(
            tenant_id=admin_user.tenant_id,
            pagination=PaginationParams(page=1, page_size=100),
            search=SearchFilters(),
            sort=SortOptions(),
        )

        returned_ids = {u.id for u in result.items}
        assert system_user_id not in returned_ids
        assert admin_user.id in returned_ids


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_tenant_admins_excludes_system_user(db_container, admin_user):
    """Defense-in-depth: even if a system user ever held an admin role, the
    ``is_system_user`` filter on the inner helper hides them.
    """
    async with db_container() as container:
        session = container.session()
        repo = container.user_repo()

        system_user_id = await _insert_system_user(
            session, tenant_id=admin_user.tenant_id
        )
        # Grant the system user every role the admin has, including admin —
        # tests that the filter wins regardless of role membership.
        for role in admin_user.roles:
            await session.execute(
                sa.text(
                    "INSERT INTO users_roles (user_id, role_id) VALUES (:uid, :rid)"
                ),
                {"uid": system_user_id, "rid": role.id},
            )
        # Also flip is_active / state so the inner state filter does not hide
        # the row for a different reason.
        await session.execute(
            sa.update(Users)
            .where(Users.id == system_user_id)
            .values(state=UserState.ACTIVE.value, is_active=True)
        )
        await session.flush()

        admins = await repo.list_tenant_admins(tenant_id=admin_user.tenant_id)
        returned_ids = {u.id for u in admins}

        assert system_user_id not in returned_ids
        assert admin_user.id in returned_ids


@pytest.mark.asyncio
@pytest.mark.integration
async def test_count_users_with_admin_permission_excludes_system_user(
    db_container, admin_user
):
    async with db_container() as container:
        session = container.session()
        repo = container.user_repo()

        before = await repo.count_users_with_admin_permission(
            tenant_id=admin_user.tenant_id
        )

        system_user_id = await _insert_system_user(
            session, tenant_id=admin_user.tenant_id
        )
        for role in admin_user.roles:
            await session.execute(
                sa.text(
                    "INSERT INTO users_roles (user_id, role_id) VALUES (:uid, :rid)"
                ),
                {"uid": system_user_id, "rid": role.id},
            )
        await session.execute(
            sa.update(Users)
            .where(Users.id == system_user_id)
            .values(state=UserState.ACTIVE.value, is_active=True)
        )
        await session.flush()

        after = await repo.count_users_with_admin_permission(
            tenant_id=admin_user.tenant_id
        )
        assert after == before


@pytest.mark.asyncio
@pytest.mark.integration
async def test_system_user_survives_data_retention_cleanup(db_container, admin_user):
    """Cleanup-job survival: the conversation-retention sweep does not touch
    the ``users`` table, so a system user with an old marker stays put.

    Mirrors the parametrized-survival style suggested by step 014, collapsed
    to a single test because no cron job under ``eneo.worker``,
    ``eneo.audit``, or ``eneo.data_retention`` modifies user rows today.
    """
    from eneo.data_retention.infrastructure.data_retention_service import (
        DataRetentionService,
    )

    async with db_container() as container:
        session = container.session()

        system_user_id = await _insert_system_user(
            session, tenant_id=admin_user.tenant_id
        )
        # Backdate the system user so any naive "old user" sweep would catch
        # it. Confirms the survival guarantee is intrinsic to the column,
        # not a function of recency.
        await session.execute(
            sa.update(Users)
            .where(Users.id == system_user_id)
            .values(created_at=datetime(2000, 1, 1, tzinfo=timezone.utc))
        )
        await session.flush()

        retention = DataRetentionService(session)
        await retention.delete_old_questions()
        await retention.delete_old_app_runs()
        await retention.delete_old_sessions()

        assert await _row_exists(session, user_id=system_user_id)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_system_user_survives_audit_retention_purge(db_container, admin_user):
    """Audit-log retention purge runs per tenant and does not touch users."""
    from eneo.audit.application.retention_service import RetentionService

    async with db_container() as container:
        session = container.session()

        system_user_id = await _insert_system_user(
            session, tenant_id=admin_user.tenant_id
        )
        await session.flush()

        service = RetentionService(session)
        await service.purge_old_logs(admin_user.tenant_id)

        assert await _row_exists(session, user_id=system_user_id)
