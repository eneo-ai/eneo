"""Admin filters are applied in SQL before pagination and to both tab counts."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.roles_table import Roles
from eneo.database.tables.tenant_table import Tenants
from eneo.database.tables.users_table import Users, users_roles_table
from eneo.users.user import (
    PaginationParams,
    SearchFilters,
    SortField,
    SortOptions,
    SortOrder,
)


@pytest.mark.integration
async def test_role_and_text_filters_share_counts_and_paginated_results(
    db_container, admin_user
):
    async with db_container() as container:
        session = container.session()
        repo = container.user_repo()
        tenant_id = admin_user.tenant_id
        other_tenant_id = uuid4()
        await session.execute(
            sa.insert(Tenants).values(
                id=other_tenant_id, name=f"other-{other_tenant_id}", quota_limit=1000
            )
        )
        role_id, extra_role_id = uuid4(), uuid4()
        await session.execute(
            sa.insert(Roles),
            [
                {
                    "id": role_id,
                    "name": "Filtered role",
                    "permissions": [],
                    "tenant_id": tenant_id,
                },
                {
                    "id": extra_role_id,
                    "name": "Extra role",
                    "permissions": [],
                    "tenant_id": tenant_id,
                },
            ],
        )
        expected_active = []
        expected_inactive = []
        # Extra-role members, deleted/system users and foreign-tenant users must
        # never inflate either tab count. Two roles must not duplicate a row.
        for index, (state, assigned, system, deleted, owner) in enumerate(
            [
                ("active", True, False, False, tenant_id),
                ("invited", True, False, False, tenant_id),
                ("inactive", True, False, False, tenant_id),
                ("active", False, False, False, tenant_id),
                ("inactive", True, True, False, tenant_id),
                ("inactive", True, False, True, tenant_id),
                ("active", True, False, False, other_tenant_id),
            ]
        ):
            user_id = uuid4()
            await session.execute(
                sa.insert(Users).values(
                    id=user_id,
                    email=f"filter-{index}@example.com",
                    username=f"Anna_{index}",
                    tenant_id=owner,
                    state=state,
                    is_active=state != "inactive",
                    is_system_user=system,
                    deleted_at=datetime.now(timezone.utc) if deleted else None,
                )
            )
            memberships = [{"user_id": user_id, "role_id": extra_role_id}]
            if assigned:
                memberships.append({"user_id": user_id, "role_id": role_id})
            await session.execute(sa.insert(users_roles_table), memberships)
            if index < 2:
                expected_active.append(user_id)
            elif index == 2:
                expected_inactive.append(user_id)
        # A wildcard-looking name must be treated as literal user input.
        await session.execute(
            sa.insert(Users).values(
                id=uuid4(),
                email="filter-lookalike@example.com",
                username="AnnaXlookalike",
                tenant_id=tenant_id,
                state="active",
            )
        )
        await session.flush()
        sort = SortOptions(field=SortField.EMAIL, order=SortOrder.ASC)
        for state, expected in [
            ("active", expected_active),
            ("inactive", expected_inactive),
        ]:
            for page, expected_id in enumerate(expected, start=1):
                result = await repo.get_paginated(
                    tenant_id,
                    PaginationParams(page=page, page_size=1),
                    SearchFilters(
                        email="FILTER-",
                        name="ANNA_",
                        role_id=role_id,
                        state_filter=state,
                    ),
                    sort,
                )
                assert [user.id for user in result.items] == [expected_id]
                assert result.total_count == len(expected)
                assert result.counts == {"active": 2, "inactive": 1}
        literal_name = await repo.get_paginated(
            tenant_id,
            PaginationParams(),
            SearchFilters(email="filter-", name="Anna_"),
            sort,
        )
        assert literal_name.total_count == 4
        assert literal_name.counts == {"active": 3, "inactive": 1}
        missing_role = await repo.get_paginated(
            tenant_id,
            PaginationParams(),
            SearchFilters(role_id=uuid4()),
            sort,
        )
        assert missing_role.items == []
        assert missing_role.counts == {"active": 0, "inactive": 0}
