from typing import TYPE_CHECKING

from sqlalchemy.exc import IntegrityError
from sqlalchemy.future import select
from typing_extensions import override

from eneo.database.tables.integration_table import Integration as IntegrationDBModel
from eneo.integration.domain.entities.integration import Integration
from eneo.integration.domain.repositories.integration_repo import (
    IntegrationRepository,
)
from eneo.integration.infrastructure.mappers.integration_mapper import (
    IntegrationMapper,
)
from eneo.integration.infrastructure.repo_impl.base_repo_impl import BaseRepoImpl
from eneo.main.exceptions import UniqueException

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class IntegrationRepoImpl(
    BaseRepoImpl[Integration, IntegrationDBModel, IntegrationMapper],
    IntegrationRepository,
):
    def __init__(self, session: "AsyncSession", mapper: IntegrationMapper):
        super().__init__(session=session, model=IntegrationDBModel, mapper=mapper)

    @override
    async def all(self) -> list[Integration]:
        query = select(self._db_model)
        result = await self.session.scalars(query)
        result = result.all()
        if not result:
            return []

        return self.mapper.to_entities(result)

    @override
    async def add(self, obj: Integration) -> Integration:
        try:
            return await super().add(obj)
        except IntegrityError as e:
            raise UniqueException("Integration existed") from e
