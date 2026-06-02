from __future__ import annotations

from uuid import UUID

from sqlalchemy import Select, asc, delete, desc, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from intric.database.tables.user_groups_table import UserGroups
from intric.database.tables.users_table import Users
from intric.database.tables.users_table import (
    usergroups_users_table as usergroups_users,
)
from intric.scim.domain.errors import ScimInvalidFilterError
from intric.scim.schemas.common import ScimFilter, ScimSort
from intric.user_groups.user_group import UserGroupState

GroupModel = UserGroups

_GROUP_ATTR_MAP = {
    "displayname": GroupModel.name,
    "externalid": GroupModel.external_id,
}

_NOT_DELETED = GroupModel.state.is_(None) | (GroupModel.state != UserGroupState.DELETED)


def _apply_filter(
    query: Select[tuple[UserGroups]], scim_filter: ScimFilter | None
) -> Select[tuple[UserGroups]]:
    if scim_filter is None:
        return query
    col = _GROUP_ATTR_MAP.get(scim_filter.attribute.lower())
    if col is None:
        # RFC 7644 §3.4.2.2: reject unsupported filter attributes with 400
        # invalidFilter rather than silently returning the whole tenant.
        raise ScimInvalidFilterError(
            f"Unsupported filter attribute: '{scim_filter.attribute}'"
        )
    op = scim_filter.operator
    v = scim_filter.value
    if op == "eq":
        return query.where(col == v)
    elif op == "ne":
        return query.where(col != v)
    elif op == "co":
        return query.where(col.ilike(f"%{v}%"))
    elif op == "sw":
        return query.where(col.ilike(f"{v}%"))
    elif op == "ew":
        return query.where(col.ilike(f"%{v}"))
    elif op == "pr":
        return query.where(col.is_not(None))
    elif op == "gt":
        return query.where(col > v)
    elif op == "ge":
        return query.where(col >= v)
    elif op == "lt":
        return query.where(col < v)
    elif op == "le":
        return query.where(col <= v)
    return query


class ScimGroupRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, model: GroupModel) -> GroupModel:
        self._session.add(model)
        await self._session.flush()
        return model

    async def get_by_id(self, group_id: UUID, tenant_id: UUID) -> GroupModel | None:
        result = await self._session.execute(
            select(GroupModel)
            .options(selectinload(GroupModel.users))
            .where(
                GroupModel.id == group_id,
                GroupModel.tenant_id == tenant_id,
                _NOT_DELETED,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_id_including_deleted(
        self, group_id: UUID, tenant_id: UUID
    ) -> GroupModel | None:
        result = await self._session.execute(
            select(GroupModel).where(
                GroupModel.id == group_id,
                GroupModel.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_name(self, name: str, tenant_id: UUID) -> GroupModel | None:
        result = await self._session.execute(
            select(GroupModel).where(
                GroupModel.name == name,
                GroupModel.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_user_ids_in_tenant(
        self, user_ids: list[UUID], tenant_id: UUID
    ) -> set[UUID]:
        if not user_ids:
            return set()

        result = await self._session.execute(
            select(Users.id).where(
                Users.id.in_(user_ids),
                Users.tenant_id == tenant_id,
            )
        )
        return set(result.scalars().all())

    def _base_list_query(
        self, tenant_id: UUID, scim_filter: ScimFilter | None
    ) -> Select[tuple[UserGroups]]:
        query = (
            select(GroupModel)
            .options(selectinload(GroupModel.users))
            .where(GroupModel.tenant_id == tenant_id, _NOT_DELETED)
        )
        return _apply_filter(query, scim_filter)

    async def count(
        self, tenant_id: UUID, scim_filter: ScimFilter | None = None
    ) -> int:
        base = self._base_list_query(tenant_id, scim_filter)
        count_query = select(func.count()).select_from(base.subquery())
        result = await self._session.execute(count_query)
        return result.scalar_one()

    async def list(
        self,
        tenant_id: UUID,
        scim_filter: ScimFilter | None = None,
        scim_sort: ScimSort | None = None,
        offset: int = 0,
        limit: int | None = None,
    ) -> list[GroupModel]:
        query = self._base_list_query(tenant_id, scim_filter)
        if scim_sort is not None:
            sort_col = _GROUP_ATTR_MAP.get(scim_sort.attribute.lower())
            if sort_col is not None:
                query = query.order_by(
                    asc(sort_col) if scim_sort.order == "ascending" else desc(sort_col)
                )
        query = query.offset(offset)
        if limit is not None:
            query = query.limit(limit)
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def update(self, model: GroupModel) -> GroupModel:
        await self._session.flush()
        await self._session.refresh(model)
        return model

    async def _group_in_tenant(self, group_id: UUID, tenant_id: UUID) -> bool:
        """Whether ``group_id`` belongs to ``tenant_id``.

        The membership junction table carries no tenant_id column, so member
        mutations can't scope by tenant directly in their own WHERE clause.
        This guard puts tenant_id back into an SQL condition (against the group
        table) before any junction write, so the repository never mutates a
        group outside the caller's tenant even if a caller passes a foreign id.
        """
        result = await self._session.execute(
            select(GroupModel.id).where(
                GroupModel.id == group_id,
                GroupModel.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none() is not None

    async def delete(self, group_id: UUID, tenant_id: UUID) -> None:
        await self._session.execute(
            update(GroupModel)
            .where(GroupModel.id == group_id, GroupModel.tenant_id == tenant_id)
            .values(state=UserGroupState.DELETED)
        )

    async def add_member(self, group_id: UUID, user_id: UUID, tenant_id: UUID) -> None:
        if not await self._group_in_tenant(group_id, tenant_id):
            return
        await self._session.execute(
            pg_insert(usergroups_users)
            .values(user_group_id=group_id, user_id=user_id)
            .on_conflict_do_nothing()
        )

    async def remove_member(
        self, group_id: UUID, user_id: UUID, tenant_id: UUID
    ) -> None:
        if not await self._group_in_tenant(group_id, tenant_id):
            return
        await self._session.execute(
            delete(usergroups_users).where(
                usergroups_users.c.user_group_id == group_id,
                usergroups_users.c.user_id == user_id,
            )
        )

    async def set_members(
        self, group_id: UUID, user_ids: list[UUID], tenant_id: UUID
    ) -> None:
        if not await self._group_in_tenant(group_id, tenant_id):
            return
        await self._session.execute(
            delete(usergroups_users).where(usergroups_users.c.user_group_id == group_id)
        )
        if user_ids:
            await self._session.execute(
                usergroups_users.insert(),
                [{"user_group_id": group_id, "user_id": uid} for uid in user_ids],
            )
