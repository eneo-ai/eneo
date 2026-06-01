from typing import TYPE_CHECKING

from sqlalchemy.orm import selectinload
from typing_extensions import override

from intric.database.tables.integration_table import (
    TenantIntegration as TenantIntegrationDBModel,
)
from intric.database.tables.integration_table import (
    UserIntegration as UserIntegrationDBModel,
)
from intric.integration.domain.entities.user_integration import UserIntegration
from intric.integration.domain.repositories.user_integration_repo import (
    UserIntegrationRepository,
)
from intric.integration.infrastructure.mappers.user_integration_mapper import (
    UserIntegrationMapper,
)
from intric.integration.infrastructure.repo_impl.base_repo_impl import BaseRepoImpl

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


class UserIntegrationRepoImpl(
    BaseRepoImpl[UserIntegration, UserIntegrationDBModel, UserIntegrationMapper],
    UserIntegrationRepository,
):
    def __init__(self, session: "AsyncSession", mapper: UserIntegrationMapper):
        super().__init__(session=session, model=UserIntegrationDBModel, mapper=mapper)
        self._options = [
            selectinload(self._db_model.tenant_integration).selectinload(
                TenantIntegrationDBModel.integration
            )
        ]

    @override
    async def remove(self, id: "UUID") -> None:
        await self.delete(id=id)
