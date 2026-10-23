from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from typing_extensions import override

from eneo.database.tables.integration_table import (
    OauthToken as OauthTokenDBModel,
)
from eneo.database.tables.integration_table import (
    TenantIntegration,
    UserIntegration,
)
from eneo.integration.domain.entities.oauth_token import OauthToken
from eneo.integration.domain.repositories.oauth_token_repo import (
    OauthTokenRepository,
)
from eneo.integration.infrastructure.mappers.oauth_token_mapper import (
    OauthTokenMapper,
)
from eneo.integration.infrastructure.repo_impl.base_repo_impl import BaseRepoImpl
from eneo.main.exceptions import NotFoundException

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


class OauthTokenRepoImpl(
    BaseRepoImpl[OauthToken, OauthTokenDBModel, OauthTokenMapper],
    OauthTokenRepository,
):
    def __init__(self, session: "AsyncSession", mapper: OauthTokenMapper):
        super().__init__(session=session, model=OauthTokenDBModel, mapper=mapper)
        self._options = [
            selectinload(self._db_model.user_integration)
            .selectinload(UserIntegration.tenant_integration)
            .selectinload(TenantIntegration.integration)
        ]

    @override
    async def one_fresh(self, id: "UUID") -> OauthToken:
        # populate_existing refreshes an instance the identity map already holds,
        # so a token another worker rotated is seen instead of the stale copy.
        query = (
            select(self._db_model)
            .where(self._db_model.id == id)
            .options(*self._options)
            .execution_options(populate_existing=True)
        )
        record = await self.session.scalar(query)
        if record is None:
            raise NotFoundException(f"{self._db_model.__name__} not found")
        return self.mapper.to_entity(record)
