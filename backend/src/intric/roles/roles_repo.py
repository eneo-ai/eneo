# MIT License

from typing import List
from uuid import UUID

from intric.database.database import AsyncSession
from intric.database.repositories.base import BaseRepositoryDelegate
from intric.database.tables.roles_table import Roles
from intric.roles.role import RoleCreate, RoleInDB, RoleUpdate


class RolesRepository:
    def __init__(self, session: AsyncSession) -> None:
        super().__init__()
        self.delegate: BaseRepositoryDelegate[RoleInDB] = BaseRepositoryDelegate(
            session, Roles, RoleInDB
        )
        self.session = session

    async def get_role(self, id: UUID) -> RoleInDB | None:
        return await self.delegate.get(id)

    async def create_role(self, role: RoleCreate) -> RoleInDB:
        return await self.delegate.add(role)

    async def update_role(self, role: RoleUpdate) -> RoleInDB | None:
        return await self.delegate.update(role)

    async def delete_role_by_id(self, id: UUID) -> RoleInDB | None:
        return await self.delegate.delete(id)

    async def get_by_tenant(self, tenant_id: UUID) -> List[RoleInDB]:
        return await self.delegate.filter_by(conditions={Roles.tenant_id: tenant_id})
