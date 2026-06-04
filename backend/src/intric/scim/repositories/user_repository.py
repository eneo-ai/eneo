from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import Select, asc, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from intric.database.tables.tenant_table import Tenants
from intric.database.tables.users_table import Users, users_roles_table
from intric.main.logging import get_logger
from intric.scim.domain.errors import ScimInvalidFilterError
from intric.scim.schemas.common import ScimFilter, ScimSort

logger = get_logger(__name__)

UserModel = Users

# Keys are SCIM attribute paths lowercased (RFC 7644 paths are case-insensitive).
# `emails.value` is Azure Entra ID's primary filter form for de-dup lookups;
# we map it to the single email column since Eneo's user model is flat.
_ATTR_MAP = {
    "username": Users.username,
    "externalid": Users.external_id,
    "email": Users.email,
    "emails.value": Users.email,
}


def _apply_filter(
    query: Select[tuple[Users]], scim_filter: ScimFilter | None
) -> Select[tuple[Users]]:
    if scim_filter is None:
        return query
    col = _ATTR_MAP.get(scim_filter.attribute.lower())
    if col is None:
        # RFC 7644 §3.4.2.2: reject unsupported filter attributes with 400
        # invalidFilter rather than silently returning the whole tenant — that
        # would break IdP de-dup logic and could cause duplicate provisioning.
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


class ScimUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, model: UserModel) -> UserModel:
        self._session.add(model)
        await self._session.flush()
        await self._assign_default_role(model.id, model.tenant_id)
        return model

    async def _assign_default_role(self, user_id: UUID, tenant_id: UUID) -> None:
        role_id_row = await self._session.execute(
            select(Tenants.default_role_id).where(Tenants.id == tenant_id)
        )
        role_id = role_id_row.scalar_one_or_none()
        if role_id is None:
            # Mirrors the JIT-provisioning flow in
            # authentication/federation_router.py:210-222 — provision the user
            # but emit a WARNING so the tenant misconfiguration shows up in
            # operator monitoring instead of only the audit archive.
            logger.warning(
                "SCIM provisioning: No default role configured for tenant; "
                "creating user without role — user will have zero "
                "permissions until an admin assigns roles",
                extra={
                    "tenant_id": str(tenant_id),
                    "user_id": str(user_id),
                },
            )
            return
        await self._session.execute(
            sa.insert(users_roles_table).values(
                user_id=user_id,
                role_id=role_id,
            )
        )

    async def get_by_id(self, user_id: UUID, tenant_id: UUID) -> UserModel | None:
        result = await self._session.execute(
            select(UserModel).where(
                UserModel.id == user_id,
                UserModel.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_username(
        self, user_name: str, tenant_id: UUID
    ) -> UserModel | None:
        result = await self._session.execute(
            select(UserModel).where(
                UserModel.username == user_name,
                UserModel.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str, tenant_id: UUID) -> UserModel | None:
        result = await self._session.execute(
            select(UserModel).where(
                UserModel.email == email,
                UserModel.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_external_id(
        self, external_id: str, tenant_id: UUID
    ) -> UserModel | None:
        result = await self._session.execute(
            select(UserModel).where(
                UserModel.external_id == external_id,
                UserModel.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def email_exists_in_other_tenant(self, email: str, tenant_id: UUID) -> bool:
        result = await self._session.execute(
            select(UserModel.id).where(
                UserModel.email == email,
                UserModel.tenant_id != tenant_id,
                UserModel.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none() is not None

    def _base_list_query(
        self, tenant_id: UUID, scim_filter: ScimFilter | None
    ) -> Select[tuple[Users]]:
        query = select(UserModel).where(
            UserModel.state == "active",
            UserModel.tenant_id == tenant_id,
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
    ) -> list[UserModel]:
        query = self._base_list_query(tenant_id, scim_filter)
        if scim_sort is not None:
            # RFC 7644 §3.4.2.3: unsupported sortBy falls back to default order
            # (no error). Filter validation is stricter than sort validation.
            sort_col = _ATTR_MAP.get(scim_sort.attribute.lower())
            if sort_col is not None:
                query = query.order_by(
                    asc(sort_col) if scim_sort.order == "ascending" else desc(sort_col)
                )
        query = query.offset(offset)
        if limit is not None:
            query = query.limit(limit)
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def update(self, model: UserModel) -> UserModel:
        await self._session.flush()
        await self._session.refresh(model)
        return model
