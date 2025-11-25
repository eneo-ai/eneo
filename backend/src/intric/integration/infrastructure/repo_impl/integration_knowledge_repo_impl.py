from typing import TYPE_CHECKING, Optional

import sqlalchemy as sa
from sqlalchemy.orm import selectinload

from intric.database.tables.integration_table import (
    IntegrationKnowledge as IntegrationKnowledgeDBModel,
)
from intric.database.tables.integration_table import (
    TenantIntegration as TenantIntegrationDBModel,
)
from intric.database.tables.integration_table import (
    UserIntegration as UserIntegrationDBModel,
)
from intric.integration.domain.entities.integration_knowledge import (
    IntegrationKnowledge,
)
from intric.integration.domain.repositories.integration_knowledge_repo import (
    IntegrationKnowledgeRepository,
)
from intric.integration.infrastructure.mappers.integration_knowledge_mapper import (
    IntegrationKnowledgeMapper,
)
from intric.integration.infrastructure.repo_impl.base_repo_impl import BaseRepoImpl

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from intric.embedding_models.domain.embedding_model_repo import (
        EmbeddingModelRepository,
    )


class IntegrationKnowledgeRepoImpl(
    BaseRepoImpl[IntegrationKnowledge, IntegrationKnowledgeDBModel, IntegrationKnowledgeMapper],
    IntegrationKnowledgeRepository,
):
    def __init__(
        self,
        session: "AsyncSession",
        mapper: IntegrationKnowledgeMapper,
        embedding_model_repo: "EmbeddingModelRepository",
    ):
        super().__init__(session=session, model=IntegrationKnowledgeDBModel, mapper=mapper)
        self.embedding_model_repo = embedding_model_repo
        self._options = [
            selectinload(self._db_model.user_integration)
            .selectinload(UserIntegrationDBModel.tenant_integration)
            .selectinload(TenantIntegrationDBModel.integration),
            selectinload(self._db_model.sharepoint_subscription)
        ]

    async def one_or_none(
        self, id: Optional["UUID"] = None, **filters
    ) -> IntegrationKnowledge | None:
        query = sa.select(self._db_model).where(self._db_model.id == id).options(*self._options)
        record = await self.session.scalar(query)

        if not record:
            return None

        embedding_model = await self.embedding_model_repo.one(model_id=record.embedding_model_id)

        return self.mapper.to_entity(db_model=record, embedding_model=embedding_model)

    async def get_by_ids(self, ids: list["UUID"]) -> list[IntegrationKnowledge]:
        query = sa.select(self._db_model).where(self._db_model.id.in_(ids)).options(*self._options)
        records = await self.session.scalars(query)

        embedding_models = await self.embedding_model_repo.all()

        return self.mapper.to_entities(records, embedding_models)

    async def remove(self, id: "UUID") -> None:
        await self.delete(id=id)
