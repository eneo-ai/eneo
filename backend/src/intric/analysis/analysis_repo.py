# MIT License


import datetime
from typing import NamedTuple
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from intric.database.tables.assistant_table import Assistants
from intric.database.tables.group_chats_table import GroupChatsTable
from intric.database.tables.info_blobs_table import InfoBlobs
from intric.database.tables.questions_table import (
    InfoBlobReferences,
    Questions,
    QuestionsFiles,
)
from intric.database.tables.sessions_table import Sessions
from intric.database.tables.users_table import Users
from intric.sessions.session import SessionInDB


class AssistantMetadataRow(NamedTuple):
    """Lightweight row for assistant metadata (id and created_at only)."""

    id: UUID
    created_at: datetime.datetime


class SessionMetadataRow(NamedTuple):
    """Lightweight row for session metadata."""

    id: UUID
    created_at: datetime.datetime
    assistant_id: UUID | None
    group_chat_id: UUID | None


class QuestionMetadataRow(NamedTuple):
    """Lightweight row for question metadata."""

    id: UUID
    created_at: datetime.datetime
    assistant_id: UUID | None
    session_id: UUID


class CountBucketRow(NamedTuple):
    """Aggregated count row by hour."""

    created_at: datetime.datetime
    total: int


class AnalysisRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def _get_count(self, table, tenant_id: UUID = None):
        stmt = sa.select(sa.func.count()).select_from(table)

        if tenant_id is not None:
            if table == Questions:
                stmt = stmt.join(Sessions)

            stmt = stmt.join(Users).where(Users.tenant_id == tenant_id)

        count = await self.session.scalar(stmt)

        return count

    async def get_assistant_count(self, tenant_id: UUID = None):
        return await self._get_count(Assistants, tenant_id=tenant_id)

    async def get_group_chat_count(self, tenant_id: UUID = None):
        return await self._get_count(table=GroupChatsTable, tenant_id=tenant_id)

    async def get_session_count(self, tenant_id: UUID = None):
        return await self._get_count(Sessions, tenant_id=tenant_id)

    async def get_question_count(self, tenant_id: UUID = None):
        return await self._get_count(Questions, tenant_id=tenant_id)

    async def get_tenant_counts(self, tenant_id: UUID) -> tuple[int, int, int]:
        assistant_count = (
            sa.select(sa.func.count())
            .select_from(Assistants)
            .join(Users, Assistants.user_id == Users.id)
            .where(Users.tenant_id == tenant_id)
            .scalar_subquery()
        )
        session_count = (
            sa.select(sa.func.count())
            .select_from(Sessions)
            .join(Users, Sessions.user_id == Users.id)
            .where(Users.tenant_id == tenant_id)
            .scalar_subquery()
        )
        question_count = (
            sa.select(sa.func.count())
            .select_from(Questions)
            .join(Sessions, Questions.session_id == Sessions.id)
            .join(Users, Sessions.user_id == Users.id)
            .where(Users.tenant_id == tenant_id)
            .scalar_subquery()
        )
        result = await self.session.execute(
            sa.select(assistant_count, session_count, question_count)
        )
        counts = result.one()
        return counts[0], counts[1], counts[2]

    async def get_assistant_sessions_since(
        self,
        assistant_id: UUID,
        from_date: datetime = None,
        to_date: datetime = None,
    ):
        stmt = (
            sa.select(Sessions)
            .join(
                Assistants,
                Sessions.assistant_id == Assistants.id,
            )
            .where(Assistants.id == assistant_id)
        )

        if from_date is not None:
            stmt = stmt.where(Sessions.created_at >= from_date)

        if to_date is not None:
            stmt = stmt.where(Sessions.created_at <= to_date)

        stmt = (
            stmt.order_by(Sessions.created_at)
            .options(
                selectinload(Sessions.questions)
                .selectinload(Questions.info_blob_references)
                .selectinload(InfoBlobReferences.info_blob)
                .selectinload(InfoBlobs.group)
            )
            .options(
                selectinload(Sessions.questions)
                .selectinload(Questions.info_blob_references)
                .selectinload(InfoBlobReferences.info_blob)
                .selectinload(InfoBlobs.website)
            )
            .options(
                selectinload(Sessions.questions).selectinload(Questions.logging_details)
            )
            .options(selectinload(Sessions.questions).selectinload(Questions.assistant))
            .options(
                selectinload(Sessions.questions).selectinload(
                    Questions.completion_model
                )
            )
            .options(
                selectinload(Sessions.questions)
                .selectinload(Questions.questions_files)
                .selectinload(QuestionsFiles.file)
            )
            .options(
                selectinload(Sessions.questions).selectinload(
                    Questions.completion_model
                )
            )
            .options(selectinload(Sessions.assistant).selectinload(Assistants.user))
            .options(
                selectinload(Sessions.questions).selectinload(
                    Questions.web_search_results
                ),
            )
        )

        sessions = await self.session.scalars(stmt)
        return [SessionInDB.model_validate(session) for session in sessions]

    async def get_group_chat_sessions_since(
        self,
        group_chat_id: UUID,
        from_date: datetime = None,
        to_date: datetime = None,
    ):
        stmt = sa.select(Sessions).where(Sessions.group_chat_id == group_chat_id)

        if from_date is not None:
            stmt = stmt.where(Sessions.created_at >= from_date)

        if to_date is not None:
            stmt = stmt.where(Sessions.created_at <= to_date)

        stmt = (
            stmt.order_by(Sessions.created_at)
            .options(
                selectinload(Sessions.questions)
                .selectinload(Questions.info_blob_references)
                .selectinload(InfoBlobReferences.info_blob)
                .selectinload(InfoBlobs.group)
            )
            .options(
                selectinload(Sessions.questions)
                .selectinload(Questions.info_blob_references)
                .selectinload(InfoBlobReferences.info_blob)
                .selectinload(InfoBlobs.website)
            )
            .options(
                selectinload(Sessions.questions).selectinload(Questions.logging_details)
            )
            .options(selectinload(Sessions.questions).selectinload(Questions.assistant))
            .options(
                selectinload(Sessions.questions).selectinload(
                    Questions.completion_model
                )
            )
            .options(
                selectinload(Sessions.questions)
                .selectinload(Questions.questions_files)
                .selectinload(QuestionsFiles.file)
            )
            .options(selectinload(Sessions.group_chat))
            .options(
                selectinload(Sessions.questions).selectinload(
                    Questions.web_search_results
                ),
            )
        )

        sessions = await self.session.scalars(stmt)

        return [SessionInDB.model_validate(session) for session in sessions]

    async def get_assistant_conversation_counts(
        self,
        assistant_id: UUID,
        from_date: datetime = None,
        to_date: datetime = None,
    ) -> tuple[int, int]:
        """Get conversation and question counts for an assistant efficiently.

        Returns a tuple of (session_count, question_count) using optimized COUNT queries
        instead of fetching full session data.
        """
        # Count sessions
        session_count_stmt = sa.select(sa.func.count(Sessions.id)).where(
            Sessions.assistant_id == assistant_id
        )

        if from_date is not None:
            session_count_stmt = session_count_stmt.where(
                Sessions.created_at >= from_date
            )
        if to_date is not None:
            session_count_stmt = session_count_stmt.where(
                Sessions.created_at <= to_date
            )

        session_count = await self.session.scalar(session_count_stmt) or 0

        # Count questions for sessions matching the criteria
        question_count_stmt = (
            sa.select(sa.func.count(Questions.id))
            .join(Sessions, Questions.session_id == Sessions.id)
            .where(Sessions.assistant_id == assistant_id)
        )

        if from_date is not None:
            question_count_stmt = question_count_stmt.where(
                Sessions.created_at >= from_date
            )
        if to_date is not None:
            question_count_stmt = question_count_stmt.where(
                Sessions.created_at <= to_date
            )

        question_count = await self.session.scalar(question_count_stmt) or 0

        return session_count, question_count

    async def get_assistant_metadata_for_tenant(
        self,
        tenant_id: UUID,
        start_date: datetime = None,
        end_date: datetime = None,
    ) -> list[AssistantMetadataRow]:
        """Get lightweight assistant metadata (id, created_at only) for a tenant.

        This is optimized for the metadata-statistics endpoint - only fetches
        the columns that are actually needed instead of full assistant objects.
        """
        stmt = (
            sa.select(Assistants.id, Assistants.created_at)
            .join(Users, Assistants.user_id == Users.id)
            .where(Users.tenant_id == tenant_id)
            .order_by(Assistants.created_at)
        )

        if start_date is not None:
            stmt = stmt.where(Assistants.created_at >= start_date)
        if end_date is not None:
            stmt = stmt.where(Assistants.created_at <= end_date)

        result = await self.session.execute(stmt)
        return [
            AssistantMetadataRow(id=row.id, created_at=row.created_at) for row in result
        ]

    async def get_session_metadata_for_tenant(
        self,
        tenant_id: UUID,
        start_date: datetime = None,
        end_date: datetime = None,
    ) -> list[SessionMetadataRow]:
        """Get lightweight session metadata for a tenant.

        This is optimized for the metadata-statistics endpoint - only fetches
        the columns that are actually needed instead of full session objects
        with all their relationships.
        """
        stmt = (
            sa.select(
                Sessions.id,
                Sessions.created_at,
                Sessions.assistant_id,
                Sessions.group_chat_id,
            )
            .join(Users, Sessions.user_id == Users.id)
            .where(Users.tenant_id == tenant_id)
            .order_by(Sessions.created_at)
        )

        if start_date is not None:
            stmt = stmt.where(Sessions.created_at >= start_date)
        if end_date is not None:
            stmt = stmt.where(Sessions.created_at <= end_date)

        result = await self.session.execute(stmt)
        return [
            SessionMetadataRow(
                id=row.id,
                created_at=row.created_at,
                assistant_id=row.assistant_id,
                group_chat_id=row.group_chat_id,
            )
            for row in result
        ]

    async def get_question_metadata_for_tenant(
        self,
        tenant_id: UUID,
        start_date: datetime = None,
        end_date: datetime = None,
    ) -> list[QuestionMetadataRow]:
        """Get lightweight question metadata for a tenant.

        This is optimized for the metadata-statistics endpoint - only fetches
        the columns that are actually needed instead of full question objects
        with all their relationships.
        """
        stmt = (
            sa.select(
                Questions.id,
                Questions.created_at,
                Questions.assistant_id,
                Questions.session_id,
            )
            .where(Questions.session_id.isnot(None))
            .join(Sessions, Questions.session_id == Sessions.id)
            .join(Users, Sessions.user_id == Users.id)
            .where(Users.tenant_id == tenant_id)
            .order_by(Questions.created_at)
        )

        if start_date is not None:
            stmt = stmt.where(Questions.created_at >= start_date)
        if end_date is not None:
            stmt = stmt.where(Questions.created_at <= end_date)

        result = await self.session.execute(stmt)
        return [
            QuestionMetadataRow(
                id=row.id,
                created_at=row.created_at,
                assistant_id=row.assistant_id,
                session_id=row.session_id,
            )
            for row in result
        ]

    async def get_assistant_counts_by_hour_for_tenant(
        self,
        tenant_id: UUID,
        start_date: datetime = None,
        end_date: datetime = None,
    ) -> list[CountBucketRow]:
        bucket = sa.func.date_trunc("hour", Assistants.created_at).label("created_at")
        stmt = (
            sa.select(bucket, sa.func.count().label("total"))
            .join(Users, Assistants.user_id == Users.id)
            .where(Users.tenant_id == tenant_id)
            .group_by(bucket)
            .order_by(bucket)
        )

        if start_date is not None:
            stmt = stmt.where(Assistants.created_at >= start_date)
        if end_date is not None:
            stmt = stmt.where(Assistants.created_at <= end_date)

        result = await self.session.execute(stmt)
        return [
            CountBucketRow(created_at=row.created_at, total=row.total) for row in result
        ]

    async def get_session_counts_by_hour_for_tenant(
        self,
        tenant_id: UUID,
        start_date: datetime = None,
        end_date: datetime = None,
    ) -> list[CountBucketRow]:
        bucket = sa.func.date_trunc("hour", Sessions.created_at).label("created_at")
        stmt = (
            sa.select(bucket, sa.func.count().label("total"))
            .join(Users, Sessions.user_id == Users.id)
            .where(Users.tenant_id == tenant_id)
            .group_by(bucket)
            .order_by(bucket)
        )

        if start_date is not None:
            stmt = stmt.where(Sessions.created_at >= start_date)
        if end_date is not None:
            stmt = stmt.where(Sessions.created_at <= end_date)

        result = await self.session.execute(stmt)
        return [
            CountBucketRow(created_at=row.created_at, total=row.total) for row in result
        ]

    async def get_question_counts_by_hour_for_tenant(
        self,
        tenant_id: UUID,
        start_date: datetime = None,
        end_date: datetime = None,
    ) -> list[CountBucketRow]:
        bucket = sa.func.date_trunc("hour", Questions.created_at).label("created_at")
        stmt = (
            sa.select(bucket, sa.func.count().label("total"))
            .join(Sessions, Questions.session_id == Sessions.id)
            .join(Users, Sessions.user_id == Users.id)
            .where(Users.tenant_id == tenant_id)
            .group_by(bucket)
            .order_by(bucket)
        )

        if start_date is not None:
            stmt = stmt.where(Questions.created_at >= start_date)
        if end_date is not None:
            stmt = stmt.where(Questions.created_at <= end_date)

        result = await self.session.execute(stmt)
        return [
            CountBucketRow(created_at=row.created_at, total=row.total) for row in result
        ]

    async def get_group_chat_conversation_counts(
        self,
        group_chat_id: UUID,
        from_date: datetime = None,
        to_date: datetime = None,
    ) -> tuple[int, int]:
        """Get conversation and question counts for a group chat efficiently.

        Returns a tuple of (session_count, question_count) using optimized COUNT queries
        instead of fetching full session data.
        """
        # Count sessions
        session_count_stmt = sa.select(sa.func.count(Sessions.id)).where(
            Sessions.group_chat_id == group_chat_id
        )

        if from_date is not None:
            session_count_stmt = session_count_stmt.where(
                Sessions.created_at >= from_date
            )
        if to_date is not None:
            session_count_stmt = session_count_stmt.where(
                Sessions.created_at <= to_date
            )

        session_count = await self.session.scalar(session_count_stmt) or 0

        # Count questions for sessions matching the criteria
        question_count_stmt = (
            sa.select(sa.func.count(Questions.id))
            .join(Sessions, Questions.session_id == Sessions.id)
            .where(Sessions.group_chat_id == group_chat_id)
        )

        if from_date is not None:
            question_count_stmt = question_count_stmt.where(
                Sessions.created_at >= from_date
            )
        if to_date is not None:
            question_count_stmt = question_count_stmt.where(
                Sessions.created_at <= to_date
            )

        question_count = await self.session.scalar(question_count_stmt) or 0

        return session_count, question_count

    async def get_active_assistant_count_for_tenant(
        self,
        tenant_id: UUID,
        start_date: datetime = None,
        end_date: datetime = None,
    ) -> int:
        """Count distinct trackable assistants that have sessions in the given period.

        Only counts assistants that:
        - Are published and have insights enabled (same criteria as trackable)
        - Have at least one session in the date range

        This ensures active_count <= trackable_count, avoiding >100% percentages.
        """
        stmt = (
            sa.select(sa.func.count(sa.distinct(Sessions.assistant_id)))
            .join(Assistants, Sessions.assistant_id == Assistants.id)
            .join(Users, Assistants.user_id == Users.id)
            .where(Users.tenant_id == tenant_id)
            .where(Users.deleted_at.is_(None))  # Exclude deleted users
            .where(Assistants.published.is_(True))
            .where(Assistants.insight_enabled.is_(True))
        )

        if start_date is not None:
            stmt = stmt.where(Sessions.created_at >= start_date)
        if end_date is not None:
            stmt = stmt.where(Sessions.created_at <= end_date)

        result = await self.session.scalar(stmt)
        return result or 0

    async def get_trackable_assistant_count_for_tenant(
        self,
        tenant_id: UUID,
    ) -> int:
        """Count assistants that are published and have insights enabled.

        These are the assistants that can be tracked for analytics.
        """
        stmt = (
            sa.select(sa.func.count())
            .select_from(Assistants)
            .join(Users, Assistants.user_id == Users.id)
            .where(Users.tenant_id == tenant_id)
            .where(Users.deleted_at.is_(None))
            .where(Assistants.published.is_(True))
            .where(Assistants.insight_enabled.is_(True))
        )

        result = await self.session.scalar(stmt)
        return result or 0

    async def get_active_user_count_for_tenant(
        self,
        tenant_id: UUID,
        start_date: datetime = None,
        end_date: datetime = None,
    ) -> int:
        """Count distinct non-deleted users with sessions in the given period.

        Excludes:
        - Service-generated sessions (where service_id is not null)
        - Deleted users (where deleted_at is not null)

        Note: The schema doesn't have is_service_account or is_internal fields,
        so service_id filtering is the best proxy for excluding automated sessions.
        """
        stmt = (
            sa.select(sa.func.count(sa.distinct(Sessions.user_id)))
            .join(Users, Sessions.user_id == Users.id)
            .where(Users.tenant_id == tenant_id)
            .where(Users.deleted_at.is_(None))  # Exclude deleted users
            .where(Sessions.service_id.is_(None))  # Exclude service sessions
        )

        if start_date is not None:
            stmt = stmt.where(Sessions.created_at >= start_date)
        if end_date is not None:
            stmt = stmt.where(Sessions.created_at <= end_date)

        result = await self.session.scalar(stmt)
        return result or 0
