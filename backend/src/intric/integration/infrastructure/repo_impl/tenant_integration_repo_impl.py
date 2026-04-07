from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import selectinload

from intric.database.tables.integration_table import (
    TenantIntegration as TenantIntegrationDBModel,
)
from intric.integration.domain.entities.tenant_integration import TenantIntegration
from intric.integration.domain.repositories.tenant_integration_repo import (
    TenantIntegrationRepository,
)
from intric.integration.infrastructure.mappers.tenant_integration_mapper import (
    TenantIntegrationMapper,
)
from intric.integration.infrastructure.repo_impl.base_repo_impl import BaseRepoImpl
from intric.main.exceptions import NotFoundException

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


class TenantIntegrationRepoImpl(
    BaseRepoImpl[
        TenantIntegration, TenantIntegrationDBModel, TenantIntegrationMapper
    ],
    TenantIntegrationRepository,
):
    def __init__(self, session: "AsyncSession", mapper: TenantIntegrationMapper):
        super().__init__(session=session, model=TenantIntegrationDBModel, mapper=mapper)
        self._options = [selectinload(self._db_model.integration)]

    async def delete_by_tenant(self, id: "UUID", tenant_id: "UUID") -> None:
        """Tenant-bound delete. Returns 404 on no-match (IDOR prevention)."""
        stmt = (
            sa.delete(TenantIntegrationDBModel)
            .where(
                TenantIntegrationDBModel.id == id,
                TenantIntegrationDBModel.tenant_id == tenant_id,
            )
            .returning(TenantIntegrationDBModel.id)
        )
        result = await self.session.execute(stmt)
        if result.scalar_one_or_none() is None:
            raise NotFoundException("TenantIntegration not found")
