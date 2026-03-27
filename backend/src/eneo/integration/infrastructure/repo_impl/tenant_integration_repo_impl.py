from typing import TYPE_CHECKING

from sqlalchemy.orm import selectinload

from eneo.database.tables.integration_table import (
    TenantIntegration as TenantIntegrationDBModel,
)
from eneo.integration.domain.entities.tenant_integration import TenantIntegration
from eneo.integration.domain.repositories.tenant_integration_repo import (
    TenantIntegrationRepository,
)
from eneo.integration.infrastructure.mappers.tenant_integration_mapper import (
    TenantIntegrationMapper,
)
from eneo.integration.infrastructure.repo_impl.base_repo_impl import BaseRepoImpl

if TYPE_CHECKING:

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
