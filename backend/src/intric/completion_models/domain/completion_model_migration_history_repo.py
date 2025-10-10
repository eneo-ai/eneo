"""Repository for completion model migration history operations."""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from intric.database.tables.completion_model_migration_history_table import CompletionModelMigrationHistory


class CompletionModelMigrationHistoryRepo:
    """Repository for managing completion model migration history."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_migration_history(
        self,
        migration_id: UUID,
        tenant_id: UUID,
        from_model_id: UUID,
        to_model_id: UUID,
        initiated_by: UUID,
        status: str,
        entity_types: Optional[List[str]] = None,
        affected_count: int = 0,
        started_at: Optional[datetime] = None,
    ) -> CompletionModelMigrationHistory:
        """Create a new migration history record."""
        migration_history = CompletionModelMigrationHistory(
            migration_id=migration_id,
            tenant_id=tenant_id,
            from_model_id=from_model_id,
            to_model_id=to_model_id,
            initiated_by=initiated_by,
            status=status,
            entity_types=entity_types,
            affected_count=affected_count,
            migrated_count=0,
            failed_count=0,
            started_at=started_at,
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
        warnings: Optional[List[str]] = None,
        migration_details: Optional[dict] = None,
    ) -> Optional[CompletionModelMigrationHistory]:
        """Update an existing migration history record with type-safe parameters."""
        stmt = (
            select(CompletionModelMigrationHistory)
            .where(
                CompletionModelMigrationHistory.migration_id == migration_id,
                CompletionModelMigrationHistory.tenant_id == tenant_id,
            )
        )
        
        result = await self.session.execute(stmt)
        migration_history = result.scalar_one_or_none()
        
        if migration_history:
            # Update only provided fields
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
        self,
        migration_id: UUID,
        tenant_id: UUID,
    ) -> Optional[CompletionModelMigrationHistory]:
        """Get migration history by migration ID."""
        stmt = (
            select(CompletionModelMigrationHistory)
            .where(
                CompletionModelMigrationHistory.migration_id == migration_id,
                CompletionModelMigrationHistory.tenant_id == tenant_id,
            )
        )
        
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_migration_history_for_model(
        self,
        model_id: UUID,
        tenant_id: UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> List[CompletionModelMigrationHistory]:
        """Get migration history for a specific model (from or to)."""
        stmt = (
            select(CompletionModelMigrationHistory)
            .where(
                CompletionModelMigrationHistory.tenant_id == tenant_id,
                (
                    (CompletionModelMigrationHistory.from_model_id == model_id)
                    | (CompletionModelMigrationHistory.to_model_id == model_id)
                ),
            )
            .order_by(desc(CompletionModelMigrationHistory.created_at))
            .limit(limit)
            .offset(offset)
        )
        
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_migration_history_for_tenant(
        self,
        tenant_id: UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> List[CompletionModelMigrationHistory]:
        """Get all migration history for a tenant."""
        stmt = (
            select(CompletionModelMigrationHistory)
            .where(CompletionModelMigrationHistory.tenant_id == tenant_id)
            .order_by(desc(CompletionModelMigrationHistory.created_at))
            .limit(limit)
            .offset(offset)
        )
        
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def count_migration_history_for_model(
        self,
        model_id: UUID,
        tenant_id: UUID,
    ) -> int:
        """Count migration history records for a specific model."""
        from sqlalchemy import func
        
        stmt = (
            select(func.count(CompletionModelMigrationHistory.id))
            .where(
                CompletionModelMigrationHistory.tenant_id == tenant_id,
                (
                    (CompletionModelMigrationHistory.from_model_id == model_id)
                    | (CompletionModelMigrationHistory.to_model_id == model_id)
                ),
            )
        )
        
        result = await self.session.execute(stmt)
        return result.scalar()

    async def count_migration_history_for_tenant(
        self,
        tenant_id: UUID,
    ) -> int:
        """Count all migration history records for a tenant."""
        from sqlalchemy import func
        
        stmt = (
            select(func.count(CompletionModelMigrationHistory.id))
            .where(CompletionModelMigrationHistory.tenant_id == tenant_id)
        )
        
        result = await self.session.execute(stmt)
        return result.scalar()