from collections.abc import Mapping
from typing import TYPE_CHECKING
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.future import select
from typing_extensions import override

from eneo.database.tables.sync_log_table import SyncLog as SyncLogDBModel
from eneo.integration.domain.entities.sync_log import SyncLog
from eneo.integration.domain.repositories.sync_log_repo import (
    SyncLogPage,
    SyncLogRepository,
)
from eneo.integration.infrastructure.mappers.sync_log_mapper import SyncLogMapper
from eneo.integration.infrastructure.repo_impl.base_repo_impl import BaseRepoImpl

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class SyncLogRepoImpl(
    BaseRepoImpl[SyncLog, SyncLogDBModel, SyncLogMapper],
    SyncLogRepository,
):
    def __init__(self, session: "AsyncSession", mapper: SyncLogMapper):
        super().__init__(session=session, model=SyncLogDBModel, mapper=mapper)

    @override
    async def add(self, obj: SyncLog) -> SyncLog:
        # A log is best-effort, but catching an SQL error alone leaves PostgreSQL's
        # transaction aborted. Roll back only this write so the caller can still
        # commit the documents, status and delta token from the completed pass.
        async with self.session.begin_nested():
            return await super().add(obj)

    @override
    async def get_by_id(self, sync_log_id: UUID) -> SyncLog | None:
        return await self.one_or_none(id=sync_log_id)

    def _owned_by(
        self, integration_knowledge_id: UUID, tenant_id: UUID
    ) -> sa.ColumnElement[bool]:
        """Logs of one knowledge, only when that knowledge belongs to the tenant."""
        return sa.and_(
            self._db_model.integration_knowledge_id == integration_knowledge_id,
            self._db_model.integration_knowledge.has(tenant_id=tenant_id),
        )

    @override
    async def get_by_integration_knowledge(
        self,
        integration_knowledge_id: UUID,
        *,
        tenant_id: UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> list[SyncLog]:
        """Get all sync logs for an integration, ordered by most recent first."""
        query = (
            select(self._db_model)
            .where(self._owned_by(integration_knowledge_id, tenant_id))
            .order_by(self._db_model.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.scalars(query)
        records = result.all()
        return self.mapper.to_entities(records)

    @override
    async def count_by_integration_knowledge(
        self, integration_knowledge_id: UUID, *, tenant_id: UUID
    ) -> int:
        """Get the total count of sync logs for an integration."""
        query = (
            select(sa.func.count())
            .select_from(self._db_model)
            .where(self._owned_by(integration_knowledge_id, tenant_id))
        )
        result = await self.session.scalar(query)
        return result or 0

    @override
    async def get_recent_by_integration_knowledge(
        self, integration_knowledge_id: UUID, *, tenant_id: UUID, limit: int = 10
    ) -> list[SyncLog]:
        """Get the most recent sync logs for an integration."""
        return await self.get_by_integration_knowledge(
            integration_knowledge_id=integration_knowledge_id,
            tenant_id=tenant_id,
            limit=limit,
        )

    @override
    async def get_windows(
        self, offsets: Mapping[UUID, int], *, tenant_id: UUID, limit: int
    ) -> dict[UUID, SyncLogPage]:
        """Independent history pages in two queries, regardless of item count.

        Rank ids only; load full log payloads only for the requested windows.
        Count separately so an empty page beyond the end still has its total.
        The tenant predicate remains even after the application's access check.
        """
        if not offsets:
            return {}
        log = self._db_model
        owned = sa.and_(
            log.integration_knowledge_id.in_(offsets),
            log.integration_knowledge.has(tenant_id=tenant_id),
        )
        counts = await self.session.execute(
            select(log.integration_knowledge_id, sa.func.count())
            .where(owned)
            .group_by(log.integration_knowledge_id)
        )
        totals = {knowledge_id: total for knowledge_id, total in counts}
        pages = {
            knowledge_id: SyncLogPage(logs=[], total=totals.get(knowledge_id, 0))
            for knowledge_id in offsets
        }
        ranked = (
            select(
                log.id,
                log.integration_knowledge_id,
                sa.func.row_number()
                .over(
                    partition_by=log.integration_knowledge_id,
                    order_by=(log.created_at.desc(), log.id.desc()),
                )
                .label("position"),
            )
            .where(owned)
            .subquery()
        )
        offset = sa.case(
            dict(offsets), value=ranked.c.integration_knowledge_id, else_=0
        )
        query = (
            select(log)
            .join(ranked, ranked.c.id == log.id)
            .where(ranked.c.position > offset, ranked.c.position <= offset + limit)
            .order_by(ranked.c.integration_knowledge_id, ranked.c.position)
        )
        records = await self.session.scalars(query)
        for record in records:
            pages[record.integration_knowledge_id].logs.append(
                self.mapper.to_entity(record)
            )
        return pages
