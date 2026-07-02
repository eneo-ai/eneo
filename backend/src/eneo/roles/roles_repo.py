# MIT License

from typing import List
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from eneo.database.database import AsyncSession
from eneo.database.repositories.base import BaseRepositoryDelegate
from eneo.database.tables.roles_table import Roles
from eneo.main.exceptions import UniqueException
from eneo.roles.role import RoleCreate, RoleInDB, RoleUpdate


class RolesRepository:
    UNIQUE_EXCEPTION_MSG = "A role with this name already exists for the tenant."

    def __init__(self, session: AsyncSession) -> None:
        super().__init__()
        self.delegate: BaseRepositoryDelegate[RoleInDB] = BaseRepositoryDelegate(
            session, Roles, RoleInDB
        )
        self.session = session

    async def get_role(self, id: UUID) -> RoleInDB | None:
        return await self.delegate.get(id)

    async def create_role(self, role: RoleCreate) -> RoleInDB:
        try:
            return await self.delegate.add(role)
        except IntegrityError as e:
            raise UniqueException(self.UNIQUE_EXCEPTION_MSG) from e

    async def update_role(self, role: RoleUpdate) -> RoleInDB | None:
        try:
            return await self.delegate.update(role)
        except IntegrityError as e:
            raise UniqueException(self.UNIQUE_EXCEPTION_MSG) from e

    async def delete_role_by_id(self, id: UUID) -> RoleInDB | None:
        return await self.delegate.delete(id)

    async def get_by_tenant(self, tenant_id: UUID) -> List[RoleInDB]:
        return await self.delegate.filter_by(conditions={Roles.tenant_id: tenant_id})
