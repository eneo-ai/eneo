"""Generic migration-history repository, shared by completion and transcription.

Both model types record migrations in a table with an identical column shape
(`completion_model_migration_history` / `transcription_model_migration_history`),
so the CRUD is written once here and parameterized by the table class.
"""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession


class ModelMigrationHistoryRepo:
    """CRUD for a model-migration-history table, parameterized by the table class."""

    def __init__(self, session: AsyncSession, table: Any):
        super().__init__()
        self.session = session
        self.table = table

    async def create_migration_history(
        self,
        migration_id: UUID,
        tenant_id: UUID,
        from_model_id: UUID,
        to_model_id: UUID,
        initiated_by: UUID,
        status: str,
        entity_types: list[str] | None = None,
        affected_count: int = 0,
        started_at: Optional[datetime] = None,
        from_model_name: Optional[str] = None,
        to_model_name: Optional[str] = None,
        from_provider_type: Optional[str] = None,
        to_provider_type: Optional[str] = None,
    ) -> Any:
        migration_history = self.table(
            **dict(  # type: ignore[call-arg]
                migration_id=migration_id,
                tenant_id=tenant_id,
                from_model_id=from_model_id,
                to_model_id=to_model_id,
                from_model_name=from_model_name,
                to_model_name=to_model_name,
                from_provider_type=from_provider_type,
                to_provider_type=to_provider_type,
                initiated_by=initiated_by,
                status=status,
                entity_types=entity_types,
                affected_count=affected_count,
                migrated_count=0,
                failed_count=0,
                started_at=started_at,
            )
        )
        self.session.add(migration_history)
        await self.session.flush()
        return migration_history

    async def update_migration_history(
        self,
        migration_id: UUID,
        tenant_id: UUID,
        *,
        status: Optional[str] = None,
        migrated_count: Optional[int] = None,
        failed_count: Optional[int] = None,
        started_at: Optional[datetime] = None,
        completed_at: Optional[datetime] = None,
        duration_seconds: Optional[float] = None,
        error_message: Optional[str] = None,
        warnings: list[str] | None = None,
        migration_details: dict[str, int] | None = None,
    ) -> Optional[Any]:
        stmt = select(self.table).where(
            self.table.migration_id == migration_id,
            self.table.tenant_id == tenant_id,
        )
        result = await self.session.execute(stmt)
        migration_history = result.scalar_one_or_none()

        if migration_history:
            if status is not None:
                migration_history.status = status
            if migrated_count is not None:
                migration_history.migrated_count = migrated_count
            if failed_count is not None:
                migration_history.failed_count = failed_count
            if started_at is not None:
                migration_history.started_at = started_at
            if completed_at is not None:
                migration_history.completed_at = completed_at
            if duration_seconds is not None:
                migration_history.duration_seconds = duration_seconds
            if error_message is not None:
                migration_history.error_message = error_message
            if warnings is not None:
                migration_history.warnings = warnings
            if migration_details is not None:
                migration_history.migration_details = migration_details
            await self.session.flush()

        return migration_history

    async def get_migration_history_by_id(
        self, migration_id: UUID, tenant_id: UUID
    ) -> Optional[Any]:
        stmt = select(self.table).where(
            self.table.migration_id == migration_id,
            self.table.tenant_id == tenant_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_migration_history_for_model(
        self, model_id: UUID, tenant_id: UUID, limit: int = 50, offset: int = 0
    ) -> list[Any]:
        stmt = (
            select(self.table)
            .where(
                self.table.tenant_id == tenant_id,
                or_(
                    self.table.from_model_id == model_id,
                    self.table.to_model_id == model_id,
                ),
            )
            .order_by(desc(self.table.created_at))
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()  # type: ignore[return-value]

    async def get_migration_history_for_tenant(
        self, tenant_id: UUID, limit: int = 50, offset: int = 0
    ) -> list[Any]:
        stmt = (
            select(self.table)
            .where(self.table.tenant_id == tenant_id)
            .order_by(desc(self.table.created_at))
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()  # type: ignore[return-value]

    async def count_migration_history_for_model(
        self, model_id: UUID, tenant_id: UUID
    ) -> int:
        stmt = select(func.count(self.table.id)).where(
            self.table.tenant_id == tenant_id,
            or_(
                self.table.from_model_id == model_id,
                self.table.to_model_id == model_id,
            ),
        )
        result = await self.session.execute(stmt)
        return result.scalar()  # type: ignore[return-value]

    async def count_migration_history_for_tenant(self, tenant_id: UUID) -> int:
        stmt = select(func.count(self.table.id)).where(
            self.table.tenant_id == tenant_id
        )
        result = await self.session.execute(stmt)
        return result.scalar()  # type: ignore[return-value]
