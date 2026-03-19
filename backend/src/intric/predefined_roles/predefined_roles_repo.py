# MIT License


from uuid import UUID

import sqlalchemy as sa

from intric.database.database import AsyncSession
from intric.database.repositories.base import BaseRepositoryDelegate
from intric.database.tables.roles_table import PredefinedRoles
from intric.main.models import IdAndName
from intric.predefined_roles.predefined_role import (
    PredefinedRoleCreate,
    PredefinedRoleInDB,
    PredefinedRoleUpdate,
)


class PredefinedRolesRepository:
    def __init__(self, session: AsyncSession):
        self.delegate: BaseRepositoryDelegate[PredefinedRoleInDB] = (
            BaseRepositoryDelegate(session, PredefinedRoles, PredefinedRoleInDB)
        )

    async def get_predefined_role_by_uuid(self, id: UUID) -> PredefinedRoleInDB | None:
        return await self.delegate.get(id)

    async def get_predefined_role_by_name(self, name: str) -> PredefinedRoleInDB | None:
        return await self.delegate.get_by(conditions={PredefinedRoles.name: name})

    async def create_predefined_role(
        self, role: PredefinedRoleCreate
    ) -> PredefinedRoleInDB:
        return await self.delegate.add(role)

    async def update_predefined_role(
        self, role: PredefinedRoleUpdate
    ) -> PredefinedRoleInDB | None:
        return await self.delegate.update(role)

    async def delete_predefined_role_by_id(self, id: UUID) -> PredefinedRoleInDB:
        stmt = (
            sa.delete(PredefinedRoles)
            .where(PredefinedRoles.id == id)
            .returning(PredefinedRoles)
        )

        await self.delegate.get_record_from_query(stmt)

        return True  # type: ignore[return-value]

    async def get_predefined_roles(self) -> list[PredefinedRoleInDB]:
        return await self.delegate.get_all()

    async def get_ids_and_names(self) -> list[tuple[UUID, str]]:  # type: ignore[type-arg]
        stmt = sa.select(PredefinedRoles)

        roles = await self.delegate.get_records_from_query(stmt)

        return [IdAndName(id=role.id, name=role.name) for role in roles.all()]  # type: ignore[return-value]
