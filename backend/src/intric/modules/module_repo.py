from collections.abc import Awaitable, Callable
from typing import cast

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from intric.database.repositories.base import BaseRepositoryDelegate
from intric.database.tables.module_table import Modules
from intric.modules.module import ModuleBase, ModuleInDB


class ModuleRepository:
    def __init__(self, session: AsyncSession) -> None:
        super().__init__()
        self.delegate: BaseRepositoryDelegate[ModuleInDB] = BaseRepositoryDelegate(
            session, Modules, ModuleInDB
        )
        self.session = session

    async def add(self, module: ModuleBase) -> ModuleInDB:
        add_module = cast(
            Callable[[ModuleBase], Awaitable[ModuleInDB]],
            self.delegate.add,
        )
        return await add_module(module)

    async def get_all_modules(self) -> list[ModuleInDB]:
        stmt = sa.select(Modules).order_by(Modules.created_at)
        modules = await self.session.scalars(stmt)

        return [ModuleInDB.model_validate(module) for module in modules]
