from datetime import datetime, timezone
from typing import Any, NamedTuple, Optional
from uuid import UUID

import sqlalchemy as sa
from pydantic import EmailStr
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from intric.database.database import AsyncSession
from intric.database.repositories.base import BaseRepositoryDelegate
from intric.database.tables.assistant_table import Assistants
from intric.database.tables.roles_table import Roles
from intric.database.tables.spaces_table import Spaces
from intric.database.tables.tenant_table import Tenants
from intric.database.tables.users_table import Users
from intric.database.tables.widget_table import Widgets
from intric.main.exceptions import UniqueException
from intric.main.logging import get_logger
from intric.main.models import ModelId
from intric.users.user import (
    PaginatedResult,
    PaginationParams,
    SearchFilters,
    SortField,
    SortOptions,
    SortOrder,
    UserAdd,
    UserInDB,
    UserState,
    UserUpdate,
)

logger = get_logger(__name__)

# Upper bound on the inert-members preview returned by
# `get_group_members_permission_summary`. Keeps the API response
# constant-size for groups with thousands of inert members; the UI renders
# "+N more" when the full count exceeds this.
INERT_SAMPLE_SIZE = 10


class InertMemberPreview(NamedTuple):
    """Row shape for the inert-members preview.

    Named so the service/router boundary isn't positional — reordering the
    underlying SELECT would otherwise silently shift consumer semantics.
    Subscript access is preserved for call sites that still index by
    position.
    """

    id: UUID
    email: str
    username: Optional[str]


class UsersRepository:
    def __init__(self, session: AsyncSession) -> None:
        super().__init__()
        self.delegate: BaseRepositoryDelegate[UserInDB] = BaseRepositoryDelegate(
            session,
            Users,
            UserInDB,
            with_options=self._get_options(),
        )
        self.session = session

    def _get_options(self):
        return [
            selectinload(Users.roles),
            selectinload(Users.tenant).selectinload(Tenants.modules),
            selectinload(Users.api_key),
            selectinload(Users.user_groups),
        ]

    async def _get_model_from_query(
        self, query: sa.Select[tuple[Any]], with_deleted: bool = False
    ) -> UserInDB | None:
        if not with_deleted:
            query = query.where(Users.deleted_at.is_(None))

        return await self.delegate.get_model_from_query(query)

    async def _get_models_from_query(
        self, query: sa.Select[tuple[Any]], with_deleted: bool = False
    ) -> list[UserInDB]:
        if not with_deleted:
            query = query.where(Users.deleted_at.is_(None))

        return await self.delegate.get_models_from_query(query)

    async def get_user_by_email(
        self, email: EmailStr, with_deleted: bool = False
    ) -> UserInDB | None:
        # Allow case-insensitive matching
        query = sa.select(Users).where(
            sa.func.lower(Users.email) == sa.func.lower(email)
        )

        return await self._get_model_from_query(query, with_deleted=with_deleted)

    async def get_user_by_username(
        self, username: str, with_deleted: bool = False
    ) -> UserInDB | None:
        query = sa.select(Users).where(Users.username == username)

        return await self._get_model_from_query(query, with_deleted=with_deleted)

    async def get_user_by_id(
        self, id: UUID, with_deleted: bool = False
    ) -> UserInDB | None:
        query = sa.select(Users).where(Users.id == id)

        return await self._get_model_from_query(query, with_deleted=with_deleted)

    async def get_user_by_assistant_id(
        self, assistant_id: UUID, with_deleted: bool = False
    ) -> UserInDB | None:
        query = sa.select(Users).join(Assistants).where(Assistants.id == assistant_id)

        return await self._get_model_from_query(query, with_deleted=with_deleted)

    async def get_user_by_id_and_tenant_id(
        self, id: UUID, tenant_id: UUID
    ) -> UserInDB | None:
        query = (
            sa.select(Users).where(Users.id == id).where(Users.tenant_id == tenant_id)
        )

        return await self._get_model_from_query(query, with_deleted=False)

    async def get_user_by_widget_id(self, widget_id: UUID) -> UserInDB | None:
        query = sa.select(Users).join(Widgets).where(Widgets.id == widget_id)
        return await self.delegate.get_model_from_query(query)

    async def get_total_count(
        self,
        tenant_id: Optional[UUID] = None,
        filters: Optional[str] = None,
        permission: Optional[str] = None,
    ):
        query = sa.select(sa.func.count(Users.id)).where(Users.deleted_at.is_(None))

        if tenant_id is not None:
            query = query.where(Users.tenant_id == tenant_id)

        if filters is not None:
            query = query.filter(
                sa.func.lower(Users.email).like(f"%{filters.lower()}%")
            )

        if permission:
            # Keep count in sync with get_all_users so pagination is sane
            # when the picker uses `permission=...`.
            # pyright-ignore: PG ARRAY `.any(<scalar>)` is valid at runtime;
            # the typestub annotates `other` as a column expression.
            query = query.where(Users.roles.any(Roles.permissions.any(permission)))  # pyright: ignore[reportArgumentType]

        return await self.session.scalar(query)

    async def get_all_users(
        self,
        tenant_id: UUID | None = None,
        limit: Optional[int] = None,
        cursor: Optional[str] = None,
        previous: bool = False,
        filters: Optional[str] = None,
        permission: Optional[str] = None,
    ) -> list[UserInDB]:
        """
        Retrieves a paginated list of users for a specific tenant,
        with optional filtering and cursor-based pagination.

        `permission` restricts the result to users whose aggregated role
        permissions include the given permission value (e.g. "shared_spaces").
        """
        query = sa.select(Users)

        if tenant_id is not None:
            query = query.where(Users.tenant_id == tenant_id)

        if filters:
            query = query.filter(
                sa.func.lower(Users.email).like(f"%{filters.lower()}%")
            )

        if permission:
            # Narrow to users with at least one role that grants the
            # requested permission. Postgres ARRAY `any()` matches when
            # the permission value appears in the role's permissions[].
            query = query.where(Users.roles.any(Roles.permissions.any(permission)))  # pyright: ignore[reportArgumentType]

        if cursor is not None:
            if previous:
                query = query.where(sa.func.lower(Users.email) <= cursor.lower())
                query = query.order_by(sa.func.lower(Users.email).desc())
                assert limit is not None
                query = query.limit(limit + 1)
                users = await self._get_models_from_query(
                    query=query, with_deleted=False
                )

                return list(reversed(users))
            else:
                query = query.where(sa.func.lower(Users.email) > cursor.lower())

        query = query.order_by(sa.func.lower(Users.email).asc())

        if limit is not None:
            query = query.limit(limit)

        return await self._get_models_from_query(query=query, with_deleted=False)

    async def get_roles_by_ids(
        self, roles: list[ModelId] | None, tenant_id: UUID
    ) -> list[Roles]:
        if roles is None:
            return []

        roles_ids = [role.id for role in roles]
        stmt = sa.select(Roles).filter(
            Roles.id.in_(roles_ids), Roles.tenant_id == tenant_id
        )
        result = await self.session.scalars(stmt)

        return list(result.all())

    async def add(self, user: UserAdd):
        try:
            stmt = (
                sa.insert(Users)
                .values(**user.model_dump(exclude_none=True, exclude={"roles"}))
                .returning(Users)
            )
            entry_in_db = await self.delegate.get_record_from_query(query=stmt)
            assert entry_in_db is not None
            # TODO should be refactored when we will remove int id field from tables
            entry_in_db.roles = await self.get_roles_by_ids(user.roles, user.tenant_id)

            return UserInDB.model_validate(entry_in_db)
        except IntegrityError as e:
            raise UniqueException("User already exists.") from e

    async def update(self, user: UserUpdate):
        stmt = (
            sa.update(Users)
            .values(**user.model_dump(exclude_unset=True, exclude={"id", "roles"}))
            .where(Users.id == user.id)
            .returning(Users)
        )
        entry_in_db = await self.delegate.get_record_from_query(query=stmt)

        if entry_in_db is None:
            return

        # TODO should be refactored when we will remove int id field from tables
        if "roles" in user.model_dump(exclude_unset=True):
            entry_in_db.roles = await self.get_roles_by_ids(
                user.roles, entry_in_db.tenant_id
            )

        return UserInDB.model_validate(entry_in_db)

    async def hard_delete(self, id: UUID):
        return await self.delegate.delete(id)

    async def soft_delete(self, id: UUID):
        # Cleanup personal space
        stmt = sa.delete(Spaces).where(Spaces.user_id == id)
        await self.session.execute(stmt)

        stmt = (
            sa.update(Users)
            .values(deleted_at=datetime.now(timezone.utc), state=UserState.DELETED)
            .where(Users.id == id)
            .returning(Users)
        )
        return await self.delegate.get_model_from_query(stmt)

    async def delete(self, id: UUID, soft_delete: bool = True):
        if soft_delete:
            return await self.soft_delete(id=id)

        return await self.hard_delete(id=id)

    async def get_paginated(
        self,
        tenant_id: UUID,
        pagination: PaginationParams,
        search: SearchFilters,
        sort: SortOptions,
    ) -> PaginatedResult[UserInDB]:
        """
        Get paginated list of users with search and sort capabilities.

        CRITICAL: tenant_id filtering MUST be first WHERE condition for security.

        Performance:
        - Uses composite B-tree indexes for tenant isolation + sorting
        - Uses GIN trigram indexes for fuzzy email/username search
        - Time complexity: O(log n + offset + page_size) for pagination
        - Time complexity: O(log n + matches) for search queries

        Args:
            tenant_id: Tenant UUID for isolation (REQUIRED - security critical)
            pagination: Page number and page size
            search: Optional email and name filters
            sort: Sort field and order

        Returns:
            PaginatedResult with items and metadata (total_count, total_pages, etc.)
        """
        import time

        start_time = time.time()

        # Build base query with tenant isolation (FIRST WHERE condition - security critical!)
        query = sa.select(Users).where(Users.tenant_id == tenant_id)

        # Add soft-delete filter
        query = query.where(Users.deleted_at.is_(None))

        # Add state filter if provided
        # "active" includes both ACTIVE and INVITED states (users who can log in)
        # "inactive" shows only INACTIVE state (temporary leave)
        if search.state_filter == "active":
            query = query.where(Users.state.in_([UserState.ACTIVE, UserState.INVITED]))
        elif search.state_filter == "inactive":
            query = query.where(Users.state == UserState.INACTIVE)
        # If no state_filter, show all non-deleted users (backward compatible)

        # Add email search filter if provided (uses idx_users_email_trgm GIN index)
        if search.email is not None:
            query = query.where(
                sa.func.lower(Users.email).like(f"%{search.email.lower()}%")
            )

        # Add username search filter if provided (uses idx_users_username_trgm GIN index)
        if search.name is not None:
            query = query.where(
                sa.func.lower(Users.username).like(f"%{search.name.lower()}%")
            )

        # Execute COUNT query for total_count (separate query for accuracy)
        count_query = sa.select(sa.func.count()).select_from(query.subquery())
        total_count = await self.session.scalar(count_query) or 0

        # Get counts for both active and inactive states for tab display
        # Uses PostgreSQL FILTER clause for efficient conditional aggregation
        # Single query, single table scan - O(n) where n = users matching filters
        state_counts_query = (
            sa.select(
                sa.func.count(1)
                .filter(Users.state.in_([UserState.ACTIVE, UserState.INVITED]))
                .label("active_count"),
                sa.func.count(1)
                .filter(Users.state == UserState.INACTIVE)
                .label("inactive_count"),
            )
            .select_from(Users)
            .where(Users.tenant_id == tenant_id)
            .where(Users.deleted_at.is_(None))
        )

        # Apply same search filters to counts for consistency
        if search.email is not None:
            state_counts_query = state_counts_query.where(
                sa.func.lower(Users.email).like(f"%{search.email.lower()}%")
            )
        if search.name is not None:
            state_counts_query = state_counts_query.where(
                sa.func.lower(Users.username).like(f"%{search.name.lower()}%")
            )

        # Execute counts query
        counts_result = await self.session.execute(state_counts_query)
        counts_row = counts_result.one()
        state_counts = {
            "active": int(counts_row.active_count or 0),
            "inactive": int(counts_row.inactive_count or 0),
        }

        # Map SortField enum to SQLAlchemy columns
        sort_column_map = {
            SortField.EMAIL: Users.email,
            SortField.USERNAME: Users.username,
            SortField.CREATED_AT: Users.created_at,
        }
        sort_column = sort_column_map[sort.field]

        # Apply sorting with stable tie-breaker (uses composite B-tree indexes: idx_users_tenant_*)
        # CRITICAL: Always add id as secondary sort for pagination stability
        # Without this, rows with identical sort_column values can appear in different positions
        # across pages, causing duplicates/skips when new users are created
        if sort.order == SortOrder.ASC:
            query = query.order_by(sort_column.asc(), Users.id.asc())
        else:
            query = query.order_by(sort_column.desc(), Users.id.desc())

        # Apply pagination (LIMIT + OFFSET)
        query = query.limit(pagination.page_size).offset(pagination.offset)

        # Add eager loading to prevent N+1 queries
        query = query.options(
            selectinload(Users.roles),
            selectinload(Users.tenant).selectinload(Tenants.modules),
            selectinload(Users.api_key),
            selectinload(Users.user_groups),
        )

        # Execute query
        result = await self.session.execute(query)
        users = [UserInDB.model_validate(user) for user in result.scalars().all()]

        # Log query performance
        execution_time = (time.time() - start_time) * 1000  # milliseconds
        logger.info(
            f"get_paginated: tenant={tenant_id}, page={pagination.page}, "
            f"page_size={pagination.page_size}, search_email={search.email}, "
            f"search_name={search.name}, sort={sort.field.value}:{sort.order.value}, "
            f"results={len(users)}, total={total_count}, time={execution_time:.2f}ms"
        )

        return PaginatedResult(
            items=users,
            total_count=total_count,
            page=pagination.page,
            page_size=pagination.page_size,
            counts=state_counts,  # Include counts for both states
        )

    async def list_users_by_tenant_id(self, tenant_id: UUID) -> list[UserInDB]:
        query = sa.select(Users).where(
            Users.deleted_at.is_(None),
            Users.tenant_id == tenant_id,
        )
        return await self._get_models_from_query(query, with_deleted=False)

    async def count_users_with_admin_permission(
        self, tenant_id: UUID, exclude_role_id: UUID | None = None
    ) -> int:
        """Count active, loginable users in tenant who have 'admin' permission."""
        q = (
            sa.select(sa.func.count(sa.distinct(Users.id)))
            .join(Users.roles)
            .where(
                Users.deleted_at.is_(None),
                Users.state.in_(["active", "invited"]),
                Users.tenant_id == tenant_id,
                Roles.permissions.contains(["admin"]),
            )
        )
        if exclude_role_id is not None:
            q = q.where(Roles.id != exclude_role_id)
        return await self.session.scalar(q) or 0

    async def list_tenant_admins(self, tenant_id: UUID) -> list["UserInDB"]:
        """
        Returns active, loginable users in tenant that have the 'admin' permission
        via any of their roles. Excludes inactive and deleted users.
        """
        q = (
            sa.select(Users)
            .join(Users.roles)
            .where(
                Users.deleted_at.is_(None),
                Users.state.in_(["active", "invited"]),
                Users.tenant_id == tenant_id,
                Roles.permissions.contains(["admin"]),
            )
        )
        return await self._get_models_from_query(q, with_deleted=False)

    async def get_group_members_permission_summary(
        self,
        group_id: UUID,
        tenant_id: UUID,
        permission: str,
        sample_size: int = INERT_SAMPLE_SIZE,
    ) -> tuple[int, int, list[InertMemberPreview]]:
        """Return `(loginable_total, missing_count, missing_sample)` for a group.

        Loginable = ACTIVE/INVITED, not soft-deleted. Missing = loginable
        members whose aggregated role permissions don't include `permission`
        (`SpaceActor` will gate them at runtime). `missing_sample` is capped
        server-side by `sample_size` so the response stays constant-size for
        multi-thousand-member groups.

        Correctness notes: anti-join uses `NOT EXISTS` to stay NULL-safe.
        Both legs of the anti-join are tenant-scoped — the outer scan
        filters on `Users.tenant_id`, and the `grant_exists` subquery
        filters on `Roles.tenant_id` so a cross-tenant role edge can't
        suppress a user from the inert set. Expects the composite index
        on `usergroups_users(user_group_id, user_id)`.
        """
        from intric.database.tables.users_table import (
            usergroups_users_table,
            users_roles_table,
        )

        # `users_roles` has no tenant column of its own, so a cross-tenant
        # role edge (user in tenant A linked to a role in tenant B) would
        # satisfy the subquery and falsely mark the user as granted. We
        # defend-in-depth by requiring the role to belong to the same
        # tenant — the outer `Users.tenant_id == tenant_id` then makes
        # both legs of the anti-join tenant-safe.
        grant_exists = (
            sa.select(sa.literal(1))
            .select_from(users_roles_table)
            .join(Roles, Roles.id == users_roles_table.c.role_id)
            .where(
                users_roles_table.c.user_id == Users.id,
                Roles.tenant_id == tenant_id,
                Roles.permissions.any(permission),  # pyright: ignore[reportArgumentType]
            )
            .correlate(Users)
            .exists()
        )

        loginable_clause = sa.and_(
            usergroups_users_table.c.user_group_id == group_id,
            Users.tenant_id == tenant_id,
            Users.deleted_at.is_(None),
            Users.state.in_([UserState.ACTIVE, UserState.INVITED]),
        )

        counts_q = (
            sa.select(
                sa.func.count().label("total"),
                sa.func.count().filter(~grant_exists).label("missing_count"),
            )
            .select_from(usergroups_users_table)
            .join(Users, Users.id == usergroups_users_table.c.user_id)
            .where(loginable_clause)
        )

        counts_row = (await self.session.execute(counts_q)).one()
        total = int(counts_row.total)
        missing_count = int(counts_row.missing_count)

        if missing_count == 0 or sample_size <= 0:
            return total, missing_count, []

        # `order_by(Users.email)` keeps the sample deterministic across calls.
        sample_q = (
            sa.select(Users.id, Users.email, Users.username)
            .join(usergroups_users_table, usergroups_users_table.c.user_id == Users.id)
            .where(loginable_clause, ~grant_exists)
            .order_by(Users.email)
            .limit(sample_size)
        )

        sample_result = await self.session.execute(sample_q)
        sample = [
            InertMemberPreview(id=r.id, email=r.email, username=r.username)
            for r in sample_result
        ]

        return total, missing_count, sample
