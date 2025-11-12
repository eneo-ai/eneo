"""SQLAlchemy implementation of audit log repository."""

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from intric.audit.domain.action_types import ActionType
from intric.audit.domain.actor_types import ActorType
from intric.audit.domain.audit_log import AuditLog
from intric.audit.domain.entity_types import EntityType
from intric.audit.domain.outcome import Outcome
from intric.audit.domain.repositories.audit_log_repository import AuditLogRepository
from intric.database.tables.audit_log_table import AuditLog as AuditLogTable

logger = logging.getLogger(__name__)


class AuditLogRepositoryImpl(AuditLogRepository):
    """SQLAlchemy implementation of audit log repository."""

    def __init__(self, session: AsyncSession):
        self.session = session

    def _to_domain(self, table: AuditLogTable) -> AuditLog:
        """Convert SQLAlchemy table to domain model."""
        return AuditLog(
            id=table.id,
            tenant_id=table.tenant_id,
            actor_id=table.actor_id,
            actor_type=ActorType(table.actor_type),
            action=ActionType(table.action),
            entity_type=EntityType(table.entity_type),
            entity_id=table.entity_id,
            timestamp=table.timestamp,
            description=table.description,
            metadata=table.log_metadata,
            outcome=Outcome(table.outcome),
            ip_address=str(table.ip_address) if table.ip_address else None,
            user_agent=table.user_agent,
            request_id=table.request_id,
            error_message=table.error_message,
            deleted_at=table.deleted_at,
            created_at=table.created_at,
            updated_at=table.updated_at,
        )

    async def create(self, audit_log: AuditLog) -> AuditLog:
        """Create a new audit log entry."""
        query = (
            sa.insert(AuditLogTable)
            .values(
                id=audit_log.id,
                tenant_id=audit_log.tenant_id,
                actor_id=audit_log.actor_id,
                actor_type=audit_log.actor_type.value,
                action=audit_log.action.value,
                entity_type=audit_log.entity_type.value,
                entity_id=audit_log.entity_id,
                timestamp=audit_log.timestamp,
                description=audit_log.description,
                log_metadata=audit_log.metadata,
                outcome=audit_log.outcome.value,
                ip_address=audit_log.ip_address,
                user_agent=audit_log.user_agent,
                request_id=audit_log.request_id,
                error_message=audit_log.error_message,
            )
            .returning(AuditLogTable)
        )

        result = await self.session.scalar(query)
        return self._to_domain(result)

    async def get_by_id(self, audit_log_id: UUID, tenant_id: UUID) -> Optional[AuditLog]:
        """Get audit log by ID with tenant isolation."""
        query = sa.select(AuditLogTable).where(
            sa.and_(
                AuditLogTable.id == audit_log_id,
                AuditLogTable.tenant_id == tenant_id,
            )
        )
        result = await self.session.scalar(query)

        if result is None:
            return None

        return self._to_domain(result)

    async def get_logs(
        self,
        tenant_id: UUID,
        actor_id: Optional[UUID] = None,
        action: Optional[ActionType] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        include_deleted: bool = False,
        page: int = 1,
        page_size: int = 100,
    ) -> tuple[list[AuditLog], int]:
        """Get audit logs for a tenant with optional filters."""
        # Build base query with tenant filter
        query = sa.select(AuditLogTable).where(AuditLogTable.tenant_id == tenant_id)

        # Apply filters
        if not include_deleted:
            query = query.where(AuditLogTable.deleted_at.is_(None))

        if actor_id:
            query = query.where(AuditLogTable.actor_id == actor_id)

        if action:
            query = query.where(AuditLogTable.action == action.value)

        if from_date:
            query = query.where(AuditLogTable.timestamp >= from_date)

        if to_date:
            query = query.where(AuditLogTable.timestamp <= to_date)

        # Get total count
        count_query = sa.select(sa.func.count()).select_from(query.subquery())
        count_start = time.time()
        total_count = await self.session.scalar(count_query)
        count_time = (time.time() - count_start) * 1000  # ms

        # Apply ordering with stable pagination (timestamp DESC, id DESC)
        # Secondary id sort prevents row instability when timestamps are identical
        query = query.order_by(AuditLogTable.timestamp.desc(), AuditLogTable.id.desc())
        query = query.limit(min(page_size, 1000))  # Max 1000 records per page
        query = query.offset((page - 1) * page_size)

        # Execute query with performance logging
        query_start = time.time()
        results = await self.session.scalars(query)
        logs = [self._to_domain(result) for result in results]
        query_time = (time.time() - query_start) * 1000  # ms

        logger.debug(
            f"get_logs: tenant={tenant_id}, page={page}, page_size={page_size}, "
            f"actor_id={actor_id}, action={action.value if action else None}, "
            f"results={len(logs)}, total={total_count}, "
            f"count_time={count_time:.2f}ms, query_time={query_time:.2f}ms"
        )

        return logs, total_count or 0

    async def get_user_logs(
        self,
        tenant_id: UUID,
        user_id: UUID,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        page: int = 1,
        page_size: int = 100,
    ) -> tuple[list[AuditLog], int]:
        """Get all logs where user is actor OR target (GDPR export)."""
        # Query for logs where user is actor
        actor_query = sa.select(AuditLogTable).where(
            sa.and_(
                AuditLogTable.tenant_id == tenant_id,
                AuditLogTable.actor_id == user_id,
                AuditLogTable.deleted_at.is_(None),
            )
        )

        # Query for logs where user is target (in log_metadata)
        target_query = sa.select(AuditLogTable).where(
            sa.and_(
                AuditLogTable.tenant_id == tenant_id,
                AuditLogTable.log_metadata["target"]["id"].astext == str(user_id),
                AuditLogTable.deleted_at.is_(None),
            )
        )

        # Combine with UNION and create alias to prevent cross join
        combined = sa.union(actor_query, target_query).alias("user_logs")

        # Build query from the aliased subquery (prevents cartesian product)
        query = sa.select(combined.c)

        # Apply date filters using subquery columns
        if from_date:
            query = query.where(combined.c.timestamp >= from_date)

        if to_date:
            query = query.where(combined.c.timestamp <= to_date)

        # Get total count
        count_query = sa.select(sa.func.count()).select_from(query.subquery())
        count_start = time.time()
        total_count = await self.session.scalar(count_query)
        count_time = (time.time() - count_start) * 1000  # ms

        # Apply ordering with stable pagination (timestamp DESC, id DESC)
        query = query.order_by(combined.c.timestamp.desc(), combined.c.id.desc())
        query = query.limit(min(page_size, 1000))
        query = query.offset((page - 1) * page_size)

        # Execute query with performance logging
        query_start = time.time()
        results = await self.session.execute(query)
        # Convert Row objects to domain models (subquery returns rows, not ORM objects)
        logs = []
        for row in results:
            # Reconstruct AuditLogTable from row columns
            # Note: Column is named "metadata" in DB, but "log_metadata" in ORM
            table_obj = AuditLogTable(
                id=row.id,
                tenant_id=row.tenant_id,
                actor_id=row.actor_id,
                actor_type=row.actor_type,
                action=row.action,
                entity_type=row.entity_type,
                entity_id=row.entity_id,
                timestamp=row.timestamp,
                description=row.description,
                log_metadata=row.metadata,  # DB column is "metadata", ORM is "log_metadata"
                outcome=row.outcome,
                ip_address=row.ip_address,
                user_agent=row.user_agent,
                request_id=row.request_id,
                error_message=row.error_message,
                deleted_at=row.deleted_at,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            logs.append(self._to_domain(table_obj))
        query_time = (time.time() - query_start) * 1000  # ms

        logger.debug(
            f"get_user_logs: tenant={tenant_id}, user_id={user_id}, "
            f"results={len(logs)}, total={total_count}, "
            f"count_time={count_time:.2f}ms, query_time={query_time:.2f}ms"
        )

        return logs, total_count or 0

    async def soft_delete_by_user(
        self,
        tenant_id: UUID,
        user_id: UUID,
    ) -> int:
        """Soft delete all logs for a user (GDPR erasure)."""
        query = (
            sa.update(AuditLogTable)
            .where(
                sa.and_(
                    AuditLogTable.tenant_id == tenant_id,
                    sa.or_(
                        AuditLogTable.actor_id == user_id,
                        AuditLogTable.log_metadata["target"]["id"].astext == str(user_id),
                    ),
                    AuditLogTable.deleted_at.is_(None),
                )
            )
            .values(deleted_at=datetime.now(timezone.utc))
        )

        result = await self.session.execute(query)
        return result.rowcount

    async def soft_delete_old_logs(
        self,
        tenant_id: UUID,
        retention_days: int,
    ) -> int:
        """Soft delete logs older than retention period."""
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=retention_days)

        query = (
            sa.update(AuditLogTable)
            .where(
                sa.and_(
                    AuditLogTable.tenant_id == tenant_id,
                    AuditLogTable.created_at < cutoff_date,
                    AuditLogTable.deleted_at.is_(None),
                )
            )
            .values(deleted_at=datetime.now(timezone.utc))
        )

        result = await self.session.execute(query)
        return result.rowcount
