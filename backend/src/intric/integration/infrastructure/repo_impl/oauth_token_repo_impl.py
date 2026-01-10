from typing import TYPE_CHECKING

from sqlalchemy.orm import selectinload

from intric.database.tables.integration_table import (
    OauthToken as OauthTokenDBModel,
    UserIntegration,
)
from intric.integration.domain.entities.oauth_token import OauthToken
from intric.integration.domain.repositories.oauth_token_repo import (
    OauthTokenRepository,
)
from intric.integration.infrastructure.repo_impl.base_repo_impl import BaseRepoImpl
from intric.integration.infrastructure.mappers.oauth_token_mapper import (
    OauthTokenMapper,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class OauthTokenRepoImpl(
    BaseRepoImpl[OauthToken, OauthTokenDBModel, OauthTokenMapper],
    OauthTokenRepository,
):
    def __init__(self, session: "AsyncSession", mapper: OauthTokenMapper):
        super().__init__(session=session, model=OauthTokenDBModel, mapper=mapper)
        self._options = [
            selectinload(self._db_model.user_integration).selectinload(
                UserIntegration.tenant_integration
            )
        ]
