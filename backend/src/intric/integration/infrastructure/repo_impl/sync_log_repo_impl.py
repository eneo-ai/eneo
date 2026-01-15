from typing import TYPE_CHECKING
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.future import select

from intric.database.tables.sync_log_table import SyncLog as SyncLogDBModel
from intric.integration.domain.entities.sync_log import SyncLog
from intric.integration.domain.repositories.sync_log_repo import SyncLogRepository
from intric.integration.infrastructure.repo_impl.base_repo_impl import BaseRepoImpl
from intric.integration.infrastructure.mappers.sync_log_mapper import SyncLogMapper

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class SyncLogRepoImpl(
    BaseRepoImpl[SyncLog, SyncLogDBModel, SyncLogMapper],
    SyncLogRepository,
):
    def __init__(self, session: "AsyncSession", mapper: SyncLogMapper):
        super().__init__(session=session, model=SyncLogDBModel, mapper=mapper)

    async def get_by_id(self, sync_log_id: UUID) -> SyncLog | None:
        return await self.one_or_none(id=sync_log_id)

    async def get_by_integration_knowledge(
        self, integration_knowledge_id: UUID, limit: int = 50, offset: int = 0
    ) -> list[SyncLog]:
        """Get all sync logs for an integration, ordered by most recent first."""
        query = (
            select(self._db_model)
            .where(self._db_model.integration_knowledge_id == integration_knowledge_id)
            .order_by(self._db_model.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.scalars(query)
        records = result.all()
        return self.mapper.to_entities(records)

    async def count_by_integration_knowledge(
        self, integration_knowledge_id: UUID
    ) -> int:
        """Get the total count of sync logs for an integration."""
        query = select(sa.func.count()).select_from(self._db_model).where(
            self._db_model.integration_knowledge_id == integration_knowledge_id
        )
        result = await self.session.scalar(query)
        return result or 0

    async def get_recent_by_integration_knowledge(
        self, integration_knowledge_id: UUID, limit: int = 10
    ) -> list[SyncLog]:
        """Get the most recent sync logs for an integration."""
        return await self.get_by_integration_knowledge(
            integration_knowledge_id=integration_knowledge_id, limit=limit
        )
