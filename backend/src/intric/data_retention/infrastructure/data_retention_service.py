from datetime import datetime, timedelta, timezone
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import text

from intric.database.tables.app_table import AppRuns, Apps
from intric.database.tables.assistant_table import Assistants
from intric.database.tables.audit_retention_policy_table import AuditRetentionPolicy
from intric.database.tables.questions_table import Questions
from intric.database.tables.sessions_table import Sessions
from intric.database.tables.spaces_table import Spaces


class DataRetentionService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def delete_old_questions(self):
        """
        Delete old questions using hierarchical retention policy resolution:
        1. Assistant-level retention_days (if set)
        2. Space-level retention_days (if set)
        3. Tenant-level conversation_retention_days (if enabled)
        4. None (keep forever)
        """
        # Calculate effective retention days using COALESCE for hierarchy
        effective_retention_days = sa.func.coalesce(
            Assistants.data_retention_days,
            Spaces.data_retention_days,
            sa.case(
                (AuditRetentionPolicy.conversation_retention_enabled == True,
                 AuditRetentionPolicy.conversation_retention_days),
                else_=None
            )
        )

        subquery = (
            sa.select(Questions.id)
            .join(Assistants, Questions.assistant_id == Assistants.id)
            .join(Spaces, Assistants.space_id == Spaces.id)
            .outerjoin(
                AuditRetentionPolicy,
                Spaces.tenant_id == AuditRetentionPolicy.tenant_id
            )
            .where(
                sa.and_(
                    effective_retention_days.isnot(None),
                    Questions.created_at
                    < sa.func.now() - effective_retention_days * text("INTERVAL '1 day'"),
                )
            )
        )

        query = sa.delete(Questions).where(Questions.id.in_(subquery))
        result = await self.session.execute(query)
        return result.rowcount

    async def delete_old_app_runs(self):
        """
        Delete old app runs using hierarchical retention policy resolution:
        1. App-level retention_days (if set)
        2. Space-level retention_days (if set)
        3. Tenant-level conversation_retention_days (if enabled)
        4. None (keep forever)
        """
        # Calculate effective retention days using COALESCE for hierarchy
        effective_retention_days = sa.func.coalesce(
            Apps.data_retention_days,
            Spaces.data_retention_days,
            sa.case(
                (AuditRetentionPolicy.conversation_retention_enabled == True,
                 AuditRetentionPolicy.conversation_retention_days),
                else_=None
            )
        )

        subquery = (
            sa.select(AppRuns.id)
            .join(Apps, AppRuns.app_id == Apps.id)
            .join(Spaces, Apps.space_id == Spaces.id)
            .outerjoin(
                AuditRetentionPolicy,
                Spaces.tenant_id == AuditRetentionPolicy.tenant_id
            )
            .where(
                sa.and_(
                    effective_retention_days.isnot(None),
                    AppRuns.created_at
                    < sa.func.now() - effective_retention_days * text("INTERVAL '1 day'"),
                )
            )
        )

        query = sa.delete(AppRuns).where(AppRuns.id.in_(subquery))
        result = await self.session.execute(query)
        return result.rowcount

    async def delete_old_sessions(self):
        one_day_ago = datetime.now(timezone.utc) - timedelta(days=1)

        subquery = (
            sa.select(Sessions.id)
            .outerjoin(Questions, Sessions.id == Questions.session_id)
            .where(sa.and_(Sessions.created_at < one_day_ago, Questions.id.is_(None)))
        )

        query = sa.delete(Sessions).where(Sessions.id.in_(subquery))
        result = await self.session.execute(query)
        return result.rowcount

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

        return {
            "questions": questions_result.scalar() or 0,
            "app_runs": app_runs_result.scalar() or 0,
            "total": (questions_result.scalar() or 0) + (app_runs_result.scalar() or 0)
        }
