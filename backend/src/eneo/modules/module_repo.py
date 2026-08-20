from collections.abc import Awaitable, Callable
from typing import Optional, cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.repositories.base import BaseRepositoryDelegate
from eneo.database.tables.module_table import Modules
from eneo.database.tables.tenant_table import tenants_modules_table
from eneo.main.exceptions import NameCollisionException
from eneo.modules.module import (
    ModuleClientConfig,
    ModuleCreate,
    ModuleInDB,
    ModuleTenantClientConfig,
)

_MODULE_NAME_UNIQUE_CONSTRAINT = "modules_unique"


def _is_module_name_collision(error: IntegrityError) -> bool:
    """Match only the named unique constraint created by the module migration."""
    original = getattr(error, "orig", None)
    reported_name = getattr(original, "constraint_name", None)
    if reported_name is None:
        diagnostic = getattr(original, "diag", None)
        reported_name = getattr(diagnostic, "constraint_name", None)
    if reported_name is not None:
        return reported_name == _MODULE_NAME_UNIQUE_CONSTRAINT

    rendered = str(original if original is not None else error)
    return any(
        quoted_name in rendered
        for quoted_name in (
            f'"{_MODULE_NAME_UNIQUE_CONSTRAINT}"',
            f"'{_MODULE_NAME_UNIQUE_CONSTRAINT}'",
        )
    )


class ModuleRepository:
    def __init__(self, session: AsyncSession) -> None:
        super().__init__()
        self.delegate: BaseRepositoryDelegate[ModuleInDB] = BaseRepositoryDelegate(
            session, Modules, ModuleInDB
        )
        self.session = session

    async def add(self, module: ModuleCreate) -> ModuleInDB:
        add_module = cast(
            Callable[[ModuleCreate], Awaitable[ModuleInDB]],
            self.delegate.add,
        )
        try:
            return await add_module(module)
        except IntegrityError as exc:
            if _is_module_name_collision(exc):
                raise NameCollisionException(
                    f"A module with key '{module.name}' already exists."
                ) from exc
            raise

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

    async def get_module_by_key(self, module_key: str) -> Optional[ModuleInDB]:
        """Resolve the stable public handoff key backed by the unique name."""
        stmt = sa.select(Modules).where(Modules.name == module_key)
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
