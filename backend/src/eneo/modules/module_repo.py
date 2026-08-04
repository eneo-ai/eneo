from collections.abc import Awaitable, Callable
from typing import Optional, cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.repositories.base import BaseRepositoryDelegate
from eneo.database.tables.module_table import Modules
from eneo.database.tables.tenant_table import tenants_modules_table
from eneo.modules.module import (
    ModuleBase,
    ModuleClientConfig,
    ModuleInDB,
    ModuleTenantClientConfig,
)


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
        self, tenant_id: UUID, module_id: UUID, config: ModuleClientConfig
    ) -> Optional[ModuleTenantClientConfig]:
        updates = config.update_values()
        if not updates:
            raise ValueError("Module client config PATCH requires at least one field.")

        stmt = (
            sa.update(tenants_modules_table)
            .where(
                tenants_modules_table.c.tenant_id == tenant_id,
                tenants_modules_table.c.module_id == module_id,
            )
            .values(**updates)
            .returning(
                tenants_modules_table.c.tenant_id,
                tenants_modules_table.c.module_id,
                tenants_modules_table.c.redirect_uris,
                tenants_modules_table.c.service_key_id,
            )
        )
        result = await self.session.execute(stmt)
        row = result.mappings().first()

        if row is None:
            return None

        return ModuleTenantClientConfig.model_validate(dict(row))

    async def get_module_client_config(
        self, tenant_id: UUID, module_id: UUID
    ) -> Optional[ModuleTenantClientConfig]:
        stmt = sa.select(
            tenants_modules_table.c.tenant_id,
            tenants_modules_table.c.module_id,
            tenants_modules_table.c.redirect_uris,
            tenants_modules_table.c.service_key_id,
        ).where(
            tenants_modules_table.c.tenant_id == tenant_id,
            tenants_modules_table.c.module_id == module_id,
        )
        result = await self.session.execute(stmt)
        row = result.mappings().first()

        if row is None:
            return None

        return ModuleTenantClientConfig.model_validate(dict(row))
