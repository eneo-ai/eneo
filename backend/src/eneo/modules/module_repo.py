from collections.abc import Awaitable, Callable
from typing import Optional, cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.repositories.base import BaseRepositoryDelegate
from eneo.database.tables.module_table import Modules
from eneo.database.tables.tenant_table import tenants_modules_table
from eneo.modules.module import ModuleBase, ModuleClientConfig, ModuleInDB


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

    async def get_module(self, module_id: UUID) -> Optional[ModuleInDB]:
        stmt = sa.select(Modules).where(Modules.id == module_id)
        module = await self.session.scalar(stmt)

        if module is None:
            return None

        return ModuleInDB.model_validate(module)

    async def update_client_config(
        self, module_id: UUID, config: ModuleClientConfig
    ) -> Optional[ModuleInDB]:
        stmt = (
            sa.update(Modules)
            .where(Modules.id == module_id)
            .values(**config.model_dump())
            .returning(Modules)
        )
        module = await self.session.scalar(stmt)

        if module is None:
            return None

        return ModuleInDB.model_validate(module)

    async def is_module_in_tenant(self, module_id: UUID, tenant_id: UUID) -> bool:
        stmt = sa.select(
            sa.exists().where(
                tenants_modules_table.c.tenant_id == tenant_id,
                tenants_modules_table.c.module_id == module_id,
            )
        )
        return bool(await self.session.scalar(stmt))
