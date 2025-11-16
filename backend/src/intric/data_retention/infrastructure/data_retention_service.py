import logging
from datetime import datetime, timedelta, timezone
from typing import Type, Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase

from intric.data_retention.constants import ORPHANED_SESSION_CLEANUP_DAYS
from intric.database.tables.app_table import AppRuns, Apps
from intric.database.tables.assistant_table import Assistants
from intric.database.tables.audit_retention_policy_table import AuditRetentionPolicy
from intric.database.tables.questions_table import Questions
from intric.database.tables.sessions_table import Sessions
from intric.database.tables.spaces_table import Spaces

logger = logging.getLogger(__name__)


class DataRetentionService:
    """Service for managing data retention and deletion based on hierarchical policies."""

    def __init__(self, session: AsyncSession):
        self.session = session

    def _build_effective_retention_days(
        self,
        entity_retention_col: Any,
        space_retention_col: Any = Spaces.data_retention_days
    ) -> Any:
        """
        Build COALESCE expression for hierarchical retention policy.

        The hierarchy is:
        1. Entity-level retention (Assistant/App specific)
        2. Space-level retention
        3. Tenant-level retention (if enabled)
        4. NULL (keep forever)

        Args:
            entity_retention_col: Column for entity-level retention (e.g., Assistants.data_retention_days)
            space_retention_col: Column for space-level retention (default: Spaces.data_retention_days)

        Returns:
            SQLAlchemy COALESCE expression
        """
        return sa.func.coalesce(
            entity_retention_col,
            space_retention_col,
            sa.case(
                (AuditRetentionPolicy.conversation_retention_enabled.is_(True),
                 AuditRetentionPolicy.conversation_retention_days),
                else_=None
            )
        )

    async def _delete_old_records(
        self,
        record_table: Type[DeclarativeBase],
        entity_table: Type[DeclarativeBase],
        entity_retention_col: Any,
        entity_fk_col: Any,
        record_fk_col: Any,
        record_type: str
    ) -> int:
        """
        Generic method to delete old records based on hierarchical retention policies.

        Args:
            record_table: Table to delete from (e.g., Questions, AppRuns)
            entity_table: Parent entity table (e.g., Assistants, Apps)
            entity_retention_col: Entity's retention days column
            entity_fk_col: Foreign key column in entity table to Space
            record_fk_col: Foreign key column in record table to entity
            record_type: Human-readable record type for logging

        Returns:
            Number of records deleted
        """
        logger.info(f"Starting deletion of old {record_type} based on retention policies")

        # Build effective retention days using hierarchy
        effective_retention_days = self._build_effective_retention_days(entity_retention_col)

        # Build subquery to identify records to delete
        subquery = (
            sa.select(record_table.id)
            .join(entity_table, record_fk_col == entity_table.id)
            .join(Spaces, entity_fk_col == Spaces.id)
            .outerjoin(
                AuditRetentionPolicy,
                Spaces.tenant_id == AuditRetentionPolicy.tenant_id
            )
            .where(
                sa.and_(
                    effective_retention_days.isnot(None),
                    record_table.created_at
                    < sa.func.now() - (effective_retention_days * sa.text("INTERVAL '1 day'")),
                )
            )
        )

        # Delete matching records
        query = sa.delete(record_table).where(record_table.id.in_(subquery))
        result = await self.session.execute(query)
        deleted_count = result.rowcount

        if deleted_count > 0:
            logger.info(f"Deleted {deleted_count} old {record_type} based on retention policies")
        else:
            logger.debug(f"No old {record_type} to delete based on retention policies")

        return deleted_count

    async def delete_old_questions(self) -> int:
        """
        Delete old questions using hierarchical retention policy resolution:
        1. Assistant-level retention_days (if set)
        2. Space-level retention_days (if set)
        3. Tenant-level conversation_retention_days (if enabled)
        4. None (keep forever)

        Returns:
            Number of questions deleted
        """
        return await self._delete_old_records(
            record_table=Questions,
            entity_table=Assistants,
            entity_retention_col=Assistants.data_retention_days,
            entity_fk_col=Assistants.space_id,
            record_fk_col=Questions.assistant_id,
            record_type="questions"
        )

    async def delete_old_app_runs(self) -> int:
        """
        Delete old app runs using hierarchical retention policy resolution:
        1. App-level retention_days (if set)
        2. Space-level retention_days (if set)
        3. Tenant-level conversation_retention_days (if enabled)
        4. None (keep forever)

        Returns:
            Number of app runs deleted
        """
        return await self._delete_old_records(
            record_table=AppRuns,
            entity_table=Apps,
            entity_retention_col=Apps.data_retention_days,
            entity_fk_col=Apps.space_id,
            record_fk_col=AppRuns.app_id,
            record_type="app runs"
        )

    async def delete_old_sessions(self) -> int:
        """
        Delete orphaned sessions that have no questions.

        Sessions without questions are deleted after ORPHANED_SESSION_CLEANUP_DAYS.

        Returns:
            Number of sessions deleted
        """
        logger.info(f"Starting deletion of orphaned sessions older than {ORPHANED_SESSION_CLEANUP_DAYS} day(s)")

        cutoff_date = datetime.now(timezone.utc) - timedelta(days=ORPHANED_SESSION_CLEANUP_DAYS)

        subquery = (
            sa.select(Sessions.id)
            .outerjoin(Questions, Sessions.id == Questions.session_id)
            .where(sa.and_(Sessions.created_at < cutoff_date, Questions.id.is_(None)))
        )

        query = sa.delete(Sessions).where(Sessions.id.in_(subquery))
        result = await self.session.execute(query)
        deleted_count = result.rowcount

        if deleted_count > 0:
            logger.info(f"Deleted {deleted_count} orphaned sessions")
        else:
            logger.debug("No orphaned sessions to delete")

        return deleted_count

    async def get_affected_questions_count_for_assistant(
        self, assistant_id: UUID, retention_days: int
    ) -> int:
        """Get count of questions that would be deleted for a specific assistant."""
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=retention_days)

        query = (
            sa.select(sa.func.count(Questions.id))
            .where(
                sa.and_(
                    Questions.assistant_id == assistant_id,
                    Questions.created_at < cutoff_date
                )
            )
        )

        result = await self.session.execute(query)
        return result.scalar() or 0

    async def get_affected_app_runs_count_for_app(
        self, app_id: UUID, retention_days: int
    ) -> int:
        """Get count of app runs that would be deleted for a specific app."""
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=retention_days)

        query = (
            sa.select(sa.func.count(AppRuns.id))
            .where(
                sa.and_(
                    AppRuns.app_id == app_id,
                    AppRuns.created_at < cutoff_date
                )
            )
        )

        result = await self.session.execute(query)
        return result.scalar() or 0

    async def get_affected_questions_count_for_space(
        self, space_id: UUID, retention_days: int
    ) -> int:
        """Get count of questions that would be deleted across all assistants in a space."""
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=retention_days)

        query = (
            sa.select(sa.func.count(Questions.id))
            .join(Assistants, Questions.assistant_id == Assistants.id)
            .where(
                sa.and_(
                    Assistants.space_id == space_id,
                    Questions.created_at < cutoff_date,
                    # Only count questions that don't have assistant-level retention
                    # (those would use their own retention policy)
                    Assistants.data_retention_days.is_(None)
                )
            )
        )

        result = await self.session.execute(query)
        return result.scalar() or 0

    async def get_affected_app_runs_count_for_space(
        self, space_id: UUID, retention_days: int
    ) -> int:
        """Get count of app runs that would be deleted across all apps in a space."""
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=retention_days)

        query = (
            sa.select(sa.func.count(AppRuns.id))
            .join(Apps, AppRuns.app_id == Apps.id)
            .where(
                sa.and_(
                    Apps.space_id == space_id,
                    AppRuns.created_at < cutoff_date,
                    # Only count app runs that don't have app-level retention
                    Apps.data_retention_days.is_(None)
                )
            )
        )

        result = await self.session.execute(query)
        return result.scalar() or 0

    async def get_affected_total_count_for_tenant(
        self, tenant_id: UUID, retention_days: int
    ) -> dict[str, int]:
        """Get count of questions and app runs that would be deleted tenant-wide."""
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=retention_days)

        # Count questions without assistant or space level retention
        questions_query = (
            sa.select(sa.func.count(Questions.id))
            .join(Assistants, Questions.assistant_id == Assistants.id)
            .join(Spaces, Assistants.space_id == Spaces.id)
            .where(
                sa.and_(
                    Spaces.tenant_id == tenant_id,
                    Questions.created_at < cutoff_date,
                    Assistants.data_retention_days.is_(None),
                    Spaces.data_retention_days.is_(None)
                )
            )
        )

        # Count app runs without app or space level retention
        app_runs_query = (
            sa.select(sa.func.count(AppRuns.id))
            .join(Apps, AppRuns.app_id == Apps.id)
            .join(Spaces, Apps.space_id == Spaces.id)
            .where(
                sa.and_(
                    Spaces.tenant_id == tenant_id,
                    AppRuns.created_at < cutoff_date,
                    Apps.data_retention_days.is_(None),
                    Spaces.data_retention_days.is_(None)
                )
            )
        )

        questions_result = await self.session.execute(questions_query)
        app_runs_result = await self.session.execute(app_runs_query)

        questions_count = questions_result.scalar() or 0
        app_runs_count = app_runs_result.scalar() or 0

        return {
            "questions": questions_count,
            "app_runs": app_runs_count,
            "total": questions_count + app_runs_count
        }
