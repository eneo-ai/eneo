"""SQLAlchemy implementation of audit log repository."""

import logging
import time
from collections.abc import AsyncIterator
from datetime import datetime
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

# Batch size for retention deletions to prevent transaction timeouts
RETENTION_BATCH_SIZE = 5000

# Warning threshold for purge duration - signals need for COALESCE optimization
PURGE_DURATION_WARNING_THRESHOLD_SECONDS = 300  # 5 minutes


def escape_like(value: str) -> str:
    """Escape SQL LIKE/ILIKE wildcard characters to treat them as literals.

    Prevents wildcard injection where user input like "100% CPU" would have
    the % treated as a wildcard instead of a literal character.

    Order matters: escape backslashes first (the escape char), then wildcards.

    Args:
        value: User input string to escape

    Returns:
        Escaped string safe for use in LIKE/ILIKE patterns
    """
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


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
        actions: Optional[list[ActionType]] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        search: Optional[str] = None,
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

        # Support both single action (deprecated) and multiple actions
        if actions:
            action_values = [a.value for a in actions]
            query = query.where(AuditLogTable.action.in_(action_values))
        elif action:
            query = query.where(AuditLogTable.action == action.value)

        if from_date:
            query = query.where(AuditLogTable.timestamp >= from_date)

        if to_date:
            query = query.where(AuditLogTable.timestamp <= to_date)

        # Search entity names in description (uses pg_trgm GIN index)
        # Escape wildcards to prevent injection (e.g., "100% CPU" -> "100\% CPU")
        if search:
            safe_search = escape_like(search)
            search_pattern = f"%{safe_search}%"
            query = query.where(
                AuditLogTable.description.ilike(search_pattern, escape="\\")
            )

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
            f"actions={[a.value for a in actions] if actions else None}, "
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
        """Permanently delete all logs for a user (GDPR Article 17 - Right to Erasure).

        Note: This is a HARD delete - logs are permanently removed from the database
        and cannot be recovered. This ensures true compliance with GDPR erasure requirements.

        Finds and deletes logs where the user is either:
        - The actor (performed the action)
        - The target (was affected by the action)
        """
        query = sa.delete(AuditLogTable).where(
            sa.and_(
                AuditLogTable.tenant_id == tenant_id,
                sa.or_(
                    AuditLogTable.actor_id == user_id,
                    AuditLogTable.log_metadata["target"]["id"].astext == str(user_id),
                ),
            )
        )

        result = await self.session.execute(query)
        return result.rowcount

    async def hard_delete_old_logs(
        self,
        tenant_id: UUID,
        retention_days: int,
    ) -> int:
        """Permanently delete logs older than retention period.

        Note: This is a HARD delete - logs are permanently removed from the database
        and cannot be recovered. This ensures compliance with data retention regulations
        that require true deletion after the retention period expires.

        Uses batch deletion to prevent transaction timeouts on large datasets.
        """
        # Use DB time (sa.func.now()) for consistency with all deletion logic
        # make_interval signature: (years, months, weeks, days, hours, mins, secs)
        cutoff_expr = sa.func.now() - sa.func.make_interval(0, 0, 0, retention_days)

        # Build base subquery to identify logs to delete (will be limited per batch)
        base_subquery = (
            sa.select(AuditLogTable.id)
            .where(
                sa.and_(
                    AuditLogTable.tenant_id == tenant_id,
                    AuditLogTable.created_at < cutoff_expr,
                )
            )
        )

        # Batch deletion to prevent transaction timeouts on large datasets
        # Note: No ORDER BY needed for deletions - any matching rows are valid targets
        # This avoids O(N²) sorting overhead when filtering by created_at
        total_deleted = 0
        start_time = time.time()
        while True:
            batch_subquery = base_subquery.limit(RETENTION_BATCH_SIZE)
            query = sa.delete(AuditLogTable).where(AuditLogTable.id.in_(batch_subquery))
            result = await self.session.execute(query)
            batch_deleted = result.rowcount

            if batch_deleted == 0:
                break

            total_deleted += batch_deleted
            logger.debug(
                f"Deleted batch of {batch_deleted} audit logs for tenant {tenant_id} "
                f"(total: {total_deleted})"
            )

        duration_seconds = time.time() - start_time
        if total_deleted > 0:
            logger.info(
                f"Purge completed: {total_deleted} rows in {duration_seconds:.2f}s "
                f"(tenant={tenant_id}, retention={retention_days}d)"
            )

        if duration_seconds > PURGE_DURATION_WARNING_THRESHOLD_SECONDS:
            logger.warning(
                f"Purge took {duration_seconds:.2f}s - consider COALESCE optimization"
            )

        return total_deleted

    async def stream_logs(
        self,
        tenant_id: UUID,
        actor_id: Optional[UUID] = None,
        action: Optional[ActionType] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        batch_size: int = 20000,
    ) -> AsyncIterator[AuditLog]:
        """Stream audit logs using server-side cursor for memory efficiency.

        Uses yield_per to fetch records in batches without loading all into memory.
        Ideal for exporting millions of records.

        Args:
            tenant_id: Tenant ID for isolation
            actor_id: Optional filter by actor
            action: Optional filter by action type
            from_date: Optional filter from date
            to_date: Optional filter to date
            batch_size: Records to fetch per DB round-trip (default 20000)

        Yields:
            AuditLog domain objects one at a time
        """
        # Build query with filters
        query = sa.select(AuditLogTable).where(
            sa.and_(
                AuditLogTable.tenant_id == tenant_id,
                AuditLogTable.deleted_at.is_(None),
            )
        )

        if actor_id:
            query = query.where(AuditLogTable.actor_id == actor_id)

        if action:
            query = query.where(AuditLogTable.action == action.value)

        if from_date:
            query = query.where(AuditLogTable.timestamp >= from_date)

        if to_date:
            query = query.where(AuditLogTable.timestamp <= to_date)

        # Order by timestamp desc for consistent export ordering
        query = query.order_by(AuditLogTable.timestamp.desc(), AuditLogTable.id.desc())

        # Use execution_options for server-side cursor with yield_per
        query = query.execution_options(yield_per=batch_size)

        # Stream results using stream_scalars() to get ORM objects directly (not Row tuples)
        # Per SQLAlchemy docs: stream() returns Row tuples, stream_scalars() returns scalar ORM objects
        async for row in await self.session.stream_scalars(query):
            yield self._to_domain(row)


    async def stream_logs_raw(
        self,
        tenant_id: UUID,
        actor_id: Optional[UUID] = None,
        action: Optional[ActionType] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        batch_size: int = 20000,
    ) -> AsyncIterator[dict]:
        """Stream audit logs as raw dicts using SQLAlchemy Core (no ORM hydration).

        Performance optimization: Bypasses ORM object creation and domain conversion,
        returning dicts directly from database rows. ~2-3x faster than stream_logs().

        Uses explicit column selection to avoid ORM hydration overhead.
        Ideal for high-volume exports where raw data is sufficient.

        Args:
            tenant_id: Tenant ID for isolation
            actor_id: Optional filter by actor
            action: Optional filter by action type
            from_date: Optional filter from date
            to_date: Optional filter to date
            batch_size: Records to fetch per DB round-trip (default 20000)

        Yields:
            Dict representation of each audit log
        """
        # Use SQLAlchemy Core - explicit column selection (no ORM hydration)
        query = sa.select(
            AuditLogTable.id,
            AuditLogTable.tenant_id,
            AuditLogTable.timestamp,
            AuditLogTable.actor_id,
            AuditLogTable.actor_type,
            AuditLogTable.action,
            AuditLogTable.entity_type,
            AuditLogTable.entity_id,
            AuditLogTable.description,
            AuditLogTable.outcome,
            AuditLogTable.log_metadata,  # Maps to 'metadata' column in DB
            AuditLogTable.ip_address,
            AuditLogTable.user_agent,
            AuditLogTable.request_id,
            AuditLogTable.error_message,
        ).where(
            sa.and_(
                AuditLogTable.tenant_id == tenant_id,
                AuditLogTable.deleted_at.is_(None),
            )
        )

        if actor_id:
            query = query.where(AuditLogTable.actor_id == actor_id)

        if action:
            query = query.where(AuditLogTable.action == action.value)

        if from_date:
            query = query.where(AuditLogTable.timestamp >= from_date)

        if to_date:
            query = query.where(AuditLogTable.timestamp <= to_date)

        # Order by timestamp desc for consistent export ordering
        query = query.order_by(AuditLogTable.timestamp.desc(), AuditLogTable.id.desc())

        # Use execution_options for server-side cursor with yield_per
        query = query.execution_options(yield_per=batch_size)

        # Use stream() (not stream_scalars) - returns Row objects with _mapping
        async for row in await self.session.stream(query):
            # Convert Row to dict directly - no ORM/domain overhead
            yield {
                "id": str(row.id),
                "tenant_id": str(row.tenant_id),
                "timestamp": row.timestamp.isoformat(),
                "actor_id": str(row.actor_id),
                "actor_type": row.actor_type,
                "action": row.action,
                "entity_type": row.entity_type,
                "entity_id": str(row.entity_id),
                "description": row.description,
                "outcome": row.outcome,
                "metadata": row.log_metadata,  # Already a dict from JSONB
                "ip_address": str(row.ip_address) if row.ip_address else None,
                "user_agent": row.user_agent,
                "request_id": str(row.request_id) if row.request_id else None,
                "error_message": row.error_message,
            }

    async def stream_user_logs(
        self,
        tenant_id: UUID,
        user_id: UUID,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        batch_size: int = 20000,
    ) -> AsyncIterator[AuditLog]:
        """Stream user logs (GDPR export) using server-side cursor.

        Returns logs where user is actor OR target.

        Args:
            tenant_id: Tenant ID for isolation
            user_id: User ID to search for
            from_date: Optional filter from date
            to_date: Optional filter to date
            batch_size: Records to fetch per DB round-trip

        Yields:
            AuditLog domain objects one at a time
        """
        # Query for logs where user is actor
        actor_query = sa.select(AuditLogTable).where(
            sa.and_(
                AuditLogTable.tenant_id == tenant_id,
                AuditLogTable.actor_id == user_id,
                AuditLogTable.deleted_at.is_(None),
            )
        )

        # Query for logs where user is target
        target_query = sa.select(AuditLogTable).where(
            sa.and_(
                AuditLogTable.tenant_id == tenant_id,
                AuditLogTable.log_metadata["target"]["id"].astext == str(user_id),
                AuditLogTable.deleted_at.is_(None),
            )
        )

        # Combine with UNION
        combined = sa.union(actor_query, target_query).alias("user_logs")
        query = sa.select(combined.c)

        if from_date:
            query = query.where(combined.c.timestamp >= from_date)

        if to_date:
            query = query.where(combined.c.timestamp <= to_date)

        query = query.order_by(combined.c.timestamp.desc(), combined.c.id.desc())

        # Use execution_options for server-side cursor
        query = query.execution_options(yield_per=batch_size)

        # Stream results using direct iteration pattern (per SQLAlchemy async docs)
        # Pattern: `async for row in await session.stream(query):` - WITH await, NO context manager
        async for row in await self.session.stream(query):
            # Reconstruct domain model from row
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
                log_metadata=row.metadata,
                outcome=row.outcome,
                ip_address=row.ip_address,
                user_agent=row.user_agent,
                request_id=row.request_id,
                error_message=row.error_message,
                deleted_at=row.deleted_at,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            yield self._to_domain(table_obj)


    async def stream_user_logs_raw(
        self,
        tenant_id: UUID,
        user_id: UUID,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        batch_size: int = 20000,
    ) -> AsyncIterator[dict]:
        """Stream user logs (GDPR export) as raw dicts using SQLAlchemy Core.

        Performance optimization: Bypasses ORM object creation and domain conversion,
        returning dicts directly from database rows. ~2-3x faster than stream_user_logs().

        Returns logs where user is actor OR target.

        Args:
            tenant_id: Tenant ID for isolation
            user_id: User ID to search for
            from_date: Optional filter from date
            to_date: Optional filter to date
            batch_size: Records to fetch per DB round-trip

        Yields:
            Dict representation of each audit log
        """
        # Query for logs where user is actor - explicit columns
        actor_query = sa.select(
            AuditLogTable.id,
            AuditLogTable.tenant_id,
            AuditLogTable.timestamp,
            AuditLogTable.actor_id,
            AuditLogTable.actor_type,
            AuditLogTable.action,
            AuditLogTable.entity_type,
            AuditLogTable.entity_id,
            AuditLogTable.description,
            AuditLogTable.outcome,
            AuditLogTable.log_metadata,
            AuditLogTable.ip_address,
            AuditLogTable.user_agent,
            AuditLogTable.request_id,
            AuditLogTable.error_message,
        ).where(
            sa.and_(
                AuditLogTable.tenant_id == tenant_id,
                AuditLogTable.actor_id == user_id,
                AuditLogTable.deleted_at.is_(None),
            )
        )

        # Query for logs where user is target
        target_query = sa.select(
            AuditLogTable.id,
            AuditLogTable.tenant_id,
            AuditLogTable.timestamp,
            AuditLogTable.actor_id,
            AuditLogTable.actor_type,
            AuditLogTable.action,
            AuditLogTable.entity_type,
            AuditLogTable.entity_id,
            AuditLogTable.description,
            AuditLogTable.outcome,
            AuditLogTable.log_metadata,
            AuditLogTable.ip_address,
            AuditLogTable.user_agent,
            AuditLogTable.request_id,
            AuditLogTable.error_message,
        ).where(
            sa.and_(
                AuditLogTable.tenant_id == tenant_id,
                AuditLogTable.log_metadata["target"]["id"].astext == str(user_id),
                AuditLogTable.deleted_at.is_(None),
            )
        )

        # Combine with UNION
        combined = sa.union(actor_query, target_query).alias("user_logs")
        query = sa.select(combined.c)

        if from_date:
            query = query.where(combined.c.timestamp >= from_date)

        if to_date:
            query = query.where(combined.c.timestamp <= to_date)

        query = query.order_by(combined.c.timestamp.desc(), combined.c.id.desc())

        # Use execution_options for server-side cursor
        query = query.execution_options(yield_per=batch_size)

        # Stream results - direct row to dict conversion
        async for row in await self.session.stream(query):
            yield {
                "id": str(row.id),
                "tenant_id": str(row.tenant_id),
                "timestamp": row.timestamp.isoformat(),
                "actor_id": str(row.actor_id),
                "actor_type": row.actor_type,
                "action": row.action,
                "entity_type": row.entity_type,
                "entity_id": str(row.entity_id),
                "description": row.description,
                "outcome": row.outcome,
                "metadata": row.log_metadata,
                "ip_address": str(row.ip_address) if row.ip_address else None,
                "user_agent": row.user_agent,
                "request_id": str(row.request_id) if row.request_id else None,
                "error_message": row.error_message,
            }

    async def count_logs(
        self,
        tenant_id: UUID,
        actor_id: Optional[UUID] = None,
        action: Optional[ActionType] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
    ) -> int:
        """Count total logs matching filters (for progress calculation).

        Args:
            tenant_id: Tenant ID
            actor_id: Optional filter by actor
            action: Optional filter by action type
            from_date: Optional filter from date
            to_date: Optional filter to date

        Returns:
            Total count of matching logs
        """
        query = sa.select(sa.func.count()).select_from(AuditLogTable).where(
            sa.and_(
                AuditLogTable.tenant_id == tenant_id,
                AuditLogTable.deleted_at.is_(None),
            )
        )

        if actor_id:
            query = query.where(AuditLogTable.actor_id == actor_id)

        if action:
            query = query.where(AuditLogTable.action == action.value)

        if from_date:
            query = query.where(AuditLogTable.timestamp >= from_date)

        if to_date:
            query = query.where(AuditLogTable.timestamp <= to_date)

        return await self.session.scalar(query) or 0

    async def count_user_logs(
        self,
        tenant_id: UUID,
        user_id: UUID,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
    ) -> int:
        """Count user logs (GDPR export) for progress calculation.

        Args:
            tenant_id: Tenant ID
            user_id: User ID to search for
            from_date: Optional filter from date
            to_date: Optional filter to date

        Returns:
            Total count of matching logs
        """
        # Query for logs where user is actor
        actor_query = sa.select(AuditLogTable).where(
            sa.and_(
                AuditLogTable.tenant_id == tenant_id,
                AuditLogTable.actor_id == user_id,
                AuditLogTable.deleted_at.is_(None),
            )
        )

        # Query for logs where user is target
        target_query = sa.select(AuditLogTable).where(
            sa.and_(
                AuditLogTable.tenant_id == tenant_id,
                AuditLogTable.log_metadata["target"]["id"].astext == str(user_id),
                AuditLogTable.deleted_at.is_(None),
            )
        )

        combined = sa.union(actor_query, target_query).alias("user_logs")
        query = sa.select(sa.func.count()).select_from(combined)

        if from_date:
            query = query.where(combined.c.timestamp >= from_date)

        if to_date:
            query = query.where(combined.c.timestamp <= to_date)

        return await self.session.scalar(query) or 0
