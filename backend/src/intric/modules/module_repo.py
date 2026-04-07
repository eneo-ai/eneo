import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from intric.database.repositories.base import BaseRepositoryDelegate
from intric.database.tables.module_table import Modules
from intric.modules.module import ModuleBase, ModuleInDB


class ModuleRepository:
    def __init__(self, session: AsyncSession):
        self.delegate: BaseRepositoryDelegate[ModuleInDB] = BaseRepositoryDelegate(
            session, Modules, ModuleInDB
        )
        self.session = session

    async def add(self, module: ModuleBase):
        return await self.delegate.add(module)

    async def get_all_modules(self):
        stmt = sa.select(Modules).order_by(Modules.created_at)
        modules = await self.session.scalars(stmt)

        return [ModuleInDB.model_validate(module) for module in modules]
