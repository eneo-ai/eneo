"""A locked, fresh page of failures outside the Builder ledger's read window."""

from collections.abc import Sequence
from datetime import datetime, timedelta
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.data_retention.domain.retention import RetentionKeyset
from eneo.data_retention.infrastructure.retention_sql import uuid_in
from eneo.database.tables.flow_tables import BuilderClientErrors
from eneo.flows.ai_builder.ai_builder_failure_ledger import MAX_WINDOW_DAYS


class BuilderClientErrorRetentionRepository:
    def __init__(self, session: AsyncSession, *, now: datetime) -> None:
        self.session = session
        self.cutoff = now - timedelta(days=MAX_WINDOW_DAYS)

    async def lock_due_page(
        self, cursor: RetentionKeyset | None, limit: int
    ) -> Sequence[RetentionKeyset]:
        statement = sa.select(
            BuilderClientErrors.id, BuilderClientErrors.created_at
        ).where(BuilderClientErrors.created_at < self.cutoff)
        if cursor is not None:
            statement = statement.where(
                sa.tuple_(BuilderClientErrors.created_at, BuilderClientErrors.id)
                > (cursor.at, cursor.id)
            )
        statement = (
            statement.order_by(BuilderClientErrors.created_at, BuilderClientErrors.id)
            .limit(limit)
            .with_for_update(of=BuilderClientErrors, skip_locked=True)
        )
        rows = (await self.session.execute(statement)).tuples().all()
        return tuple(RetentionKeyset(id=identifier, at=at) for identifier, at in rows)

    async def delete_due(self, ids: Sequence[UUID]) -> Sequence[tuple[UUID, UUID]]:
        statement = (
            sa.delete(BuilderClientErrors)
            .where(
                uuid_in(BuilderClientErrors.id, ids),
                BuilderClientErrors.created_at < self.cutoff,
            )
            .returning(BuilderClientErrors.id, BuilderClientErrors.tenant_id)
        )
        return tuple((await self.session.execute(statement)).tuples().all())
