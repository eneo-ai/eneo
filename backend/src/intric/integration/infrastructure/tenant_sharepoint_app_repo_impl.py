from typing import TYPE_CHECKING, Optional
from uuid import UUID

import sqlalchemy as sa
from typing_extensions import override

from intric.database.tables.tenant_sharepoint_app_table import (
    TenantSharePointApp as TenantSharePointAppDBModel,
)
from intric.integration.domain.entities.tenant_sharepoint_app import TenantSharePointApp
from intric.integration.domain.repositories.tenant_sharepoint_app_repo import (
    TenantSharePointAppRepository,
)
from intric.integration.infrastructure.mappers.tenant_sharepoint_app_mapper import (
    TenantSharePointAppMapper,
)
from intric.integration.infrastructure.repo_impl.base_repo_impl import BaseRepoImpl

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class TenantSharePointAppRepositoryImpl(
    BaseRepoImpl[
        TenantSharePointApp, TenantSharePointAppDBModel, TenantSharePointAppMapper
    ],
    TenantSharePointAppRepository,
):
    """SQLAlchemy implementation of TenantSharePointAppRepository."""

    def __init__(self, session: "AsyncSession", mapper: TenantSharePointAppMapper):
        super().__init__(
            session=session, model=TenantSharePointAppDBModel, mapper=mapper
        )

    @override
    async def get_by_tenant(self, tenant_id: UUID) -> Optional[TenantSharePointApp]:
        """Get the SharePoint app configuration for a tenant."""
        stmt = sa.select(TenantSharePointAppDBModel).where(
            TenantSharePointAppDBModel.tenant_id == tenant_id
        )
        result = await self.session.execute(stmt)
        db_obj = result.scalar_one_or_none()

        if db_obj is None:
            return None

        return self.mapper.to_entity(db_obj)

    @override
    async def get_by_id(self, app_id: UUID) -> Optional[TenantSharePointApp]:
        """Get SharePoint app by ID."""
        stmt = sa.select(TenantSharePointAppDBModel).where(
            TenantSharePointAppDBModel.id == app_id
        )
        result = await self.session.execute(stmt)
        db_obj = result.scalar_one_or_none()

        if db_obj is None:
            return None

        return self.mapper.to_entity(db_obj)

    @override
    async def create(self, app: TenantSharePointApp) -> TenantSharePointApp:
        """Create a new tenant SharePoint app configuration."""
        existing = await self.get_by_tenant(app.tenant_id)
        if existing:
            raise ValueError(
                f"SharePoint app already exists for tenant {app.tenant_id}"
            )

        return await self.add(app)

    @override
    async def update(self, obj: TenantSharePointApp) -> TenantSharePointApp:
        """Update an existing tenant SharePoint app configuration."""
        return await super().update(obj)

    @override
    async def delete(self, id: UUID) -> bool:
        """Delete a tenant SharePoint app configuration."""
        return await super().delete(id=id)

    @override
    async def deactivate(self, tenant_id: UUID) -> bool:
        """Deactivate the SharePoint app for a tenant (emergency shutoff)."""
        stmt = (
            sa.update(TenantSharePointAppDBModel)
            .where(TenantSharePointAppDBModel.tenant_id == tenant_id)
            .values(is_active=False)
        )
        result = await self.session.execute(stmt)
        await self.session.commit()

        return result.rowcount > 0
