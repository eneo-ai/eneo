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


class QuestionTextRow(NamedTuple):
    """Lightweight question row for insights analysis."""

    question: str
    created_at: datetime.datetime
    session_id: UUID


class AssistantInsightQuestionRow(NamedTuple):
    """Lightweight admin insights question-history row."""

    id: UUID
    question: str
    created_at: datetime.datetime
    session_id: UUID


class AnalysisRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def _get_count(self, table, tenant_id: UUID = None):
        stmt = sa.select(sa.func.count()).select_from(table)

        if tenant_id is not None:
            if table == Questions:
                stmt = stmt.where(Questions.tenant_id == tenant_id)
            else:
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
        tenant_id: UUID = None,
    ):
        if tenant_id is None:
            raise ValueError("tenant_id is required for insights session queries")

        stmt = (
            sa.select(Sessions)
            .join(
                Assistants,
                Sessions.assistant_id == Assistants.id,
            )
            .where(Assistants.id == assistant_id)
        )

        stmt = stmt.join(Users, Sessions.user_id == Users.id).where(
            Users.tenant_id == tenant_id
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
        tenant_id: UUID = None,
    ):
        if tenant_id is None:
            raise ValueError("tenant_id is required for insights session queries")

        stmt = sa.select(Sessions).where(Sessions.group_chat_id == group_chat_id)

        stmt = stmt.join(Users, Sessions.user_id == Users.id).where(
            Users.tenant_id == tenant_id
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
            .options(selectinload(Sessions.group_chat))
            .options(
                selectinload(Sessions.questions).selectinload(
                    Questions.web_search_results
                ),
            )
        )

        sessions = await self.session.scalars(stmt)

        return [SessionInDB.model_validate(session) for session in sessions]

    async def get_assistant_question_texts_since(
        self,
        *,
        assistant_id: UUID,
        from_date: datetime,
        to_date: datetime,
        include_followups: bool,
        tenant_id: UUID,
    ) -> list[QuestionTextRow]:
        return await self._get_question_texts_since(
            from_date=from_date,
            to_date=to_date,
            include_followups=include_followups,
            tenant_id=tenant_id,
            assistant_id=assistant_id,
            group_chat_id=None,
        )

    async def get_group_chat_question_texts_since(
        self,
        *,
        group_chat_id: UUID,
        from_date: datetime,
        to_date: datetime,
        include_followups: bool,
        tenant_id: UUID,
    ) -> list[QuestionTextRow]:
        return await self._get_question_texts_since(
            from_date=from_date,
            to_date=to_date,
            include_followups=include_followups,
            tenant_id=tenant_id,
            assistant_id=None,
            group_chat_id=group_chat_id,
        )

    async def _get_question_texts_since(
        self,
        *,
        from_date: datetime,
        to_date: datetime,
        include_followups: bool,
        tenant_id: UUID,
        assistant_id: UUID | None,
        group_chat_id: UUID | None,
    ) -> list[QuestionTextRow]:
        if tenant_id is None:
            raise ValueError("tenant_id is required for insights question queries")

        if assistant_id is None and group_chat_id is None:
            raise ValueError("Either assistant_id or group_chat_id is required")

        if assistant_id is not None and group_chat_id is not None:
            raise ValueError("Only one of assistant_id or group_chat_id can be set")

        question_rank = sa.func.row_number().over(
            partition_by=Questions.session_id,
            order_by=(Questions.created_at.asc(), Questions.id.asc()),
        ).label("question_rank")

        base_stmt = (
            sa.select(
                Questions.question.label("question"),
                Questions.created_at.label("created_at"),
                Questions.session_id.label("session_id"),
                question_rank,
            )
            .join(Sessions, Questions.session_id == Sessions.id)
            .join(Users, Sessions.user_id == Users.id)
            .where(Users.tenant_id == tenant_id)
            .where(Sessions.created_at >= from_date)
            .where(Sessions.created_at <= to_date)
            .where(Questions.question.isnot(None))
        )

        if assistant_id is not None:
            base_stmt = base_stmt.where(Sessions.assistant_id == assistant_id)
        else:
            base_stmt = base_stmt.where(Sessions.group_chat_id == group_chat_id)

        ranked_questions = base_stmt.subquery()

        stmt = sa.select(
            ranked_questions.c.question,
            ranked_questions.c.created_at,
            ranked_questions.c.session_id,
        )
        if not include_followups:
            stmt = stmt.where(ranked_questions.c.question_rank == 1)

        stmt = stmt.order_by(
            ranked_questions.c.created_at.asc(),
            ranked_questions.c.session_id.asc(),
        )

        result = await self.session.execute(stmt)
        return [
            QuestionTextRow(
                question=row.question,
                created_at=row.created_at,
                session_id=row.session_id,
            )
            for row in result
            if row.question
        ]

    async def get_assistant_question_history_page(
        self,
        *,
        assistant_id: UUID,
        from_date: datetime,
        to_date: datetime,
        include_followups: bool,
        tenant_id: UUID,
        limit: int,
        query: str | None = None,
        cursor_created_at: datetime.datetime | None = None,
        cursor_id: UUID | None = None,
    ) -> tuple[list[AssistantInsightQuestionRow], int, bool]:
        if tenant_id is None:
            raise ValueError("tenant_id is required for insights question queries")

        question_rank = sa.func.row_number().over(
            partition_by=Questions.session_id,
            order_by=(Questions.created_at.asc(), Questions.id.asc()),
        ).label("question_rank")

        base_stmt = (
            sa.select(
                Questions.id.label("id"),
                Questions.question.label("question"),
                Questions.created_at.label("created_at"),
                Questions.session_id.label("session_id"),
                question_rank,
            )
            .join(Sessions, Questions.session_id == Sessions.id)
            .join(Users, Sessions.user_id == Users.id)
            .where(Users.tenant_id == tenant_id)
            .where(Sessions.assistant_id == assistant_id)
            .where(Sessions.created_at >= from_date)
            .where(Sessions.created_at <= to_date)
            .where(Questions.question.isnot(None))
        )
        if query:
            normalized_query = query.strip()
            if normalized_query:
                base_stmt = base_stmt.where(
                    Questions.question.ilike(f"%{normalized_query}%")
                )

        ranked_questions = base_stmt.subquery()
        filtered_stmt = sa.select(
            ranked_questions.c.id,
            ranked_questions.c.question,
            ranked_questions.c.created_at,
            ranked_questions.c.session_id,
        )
        if not include_followups:
            filtered_stmt = filtered_stmt.where(ranked_questions.c.question_rank == 1)

        total_stmt = sa.select(sa.func.count()).select_from(filtered_stmt.subquery())
        total_count = int((await self.session.scalar(total_stmt)) or 0)

        page_stmt = filtered_stmt.order_by(
            ranked_questions.c.created_at.desc(), ranked_questions.c.id.desc()
        )

        if cursor_created_at is not None:
            if cursor_id is not None:
                page_stmt = page_stmt.where(
                    sa.or_(
                        ranked_questions.c.created_at < cursor_created_at,
                        sa.and_(
                            ranked_questions.c.created_at == cursor_created_at,
                            ranked_questions.c.id < cursor_id,
                        ),
                    )
                )
            else:
                page_stmt = page_stmt.where(
                    ranked_questions.c.created_at < cursor_created_at
                )

        page_stmt = page_stmt.limit(limit + 1)

        result = await self.session.execute(page_stmt)
        rows = list(result)
        items = [
            AssistantInsightQuestionRow(
                id=row.id,
                question=row.question,
                created_at=row.created_at,
                session_id=row.session_id,
            )
            for row in rows[:limit]
            if row.question
        ]

        has_more = len(rows) > limit
        return items, total_count, has_more

    async def get_assistant_conversation_counts(
        self,
        assistant_id: UUID,
        from_date: datetime = None,
        to_date: datetime = None,
        tenant_id: UUID = None,
    ) -> tuple[int, int]:
        """Get conversation and question counts for an assistant efficiently.

        Returns a tuple of (session_count, question_count) using optimized COUNT queries
        instead of fetching full session data.
        """
        # Count sessions
        session_count_stmt = sa.select(sa.func.count(Sessions.id)).where(
            Sessions.assistant_id == assistant_id
        )

        if tenant_id is not None:
            session_count_stmt = session_count_stmt.join(
                Users, Sessions.user_id == Users.id
            ).where(Users.tenant_id == tenant_id)

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

        if tenant_id is not None:
            question_count_stmt = question_count_stmt.join(
                Users, Sessions.user_id == Users.id
            ).where(Users.tenant_id == tenant_id)

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

    async def count_assistant_questions_since(
        self,
        *,
        assistant_id: UUID,
        from_date: datetime,
        to_date: datetime,
        tenant_id: UUID,
    ) -> int:
        stmt = (
            sa.select(sa.func.count(Questions.id))
            .join(Sessions, Questions.session_id == Sessions.id)
            .join(Users, Sessions.user_id == Users.id)
            .where(Users.tenant_id == tenant_id)
            .where(Sessions.assistant_id == assistant_id)
            .where(Sessions.created_at >= from_date)
            .where(Sessions.created_at <= to_date)
        )
        return await self.session.scalar(stmt) or 0

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
            .where(Questions.tenant_id == tenant_id)
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
            .where(Questions.tenant_id == tenant_id)
            .where(Questions.session_id.isnot(None))
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
        tenant_id: UUID = None,
    ) -> tuple[int, int]:
        """Get conversation and question counts for a group chat efficiently.

        Returns a tuple of (session_count, question_count) using optimized COUNT queries
        instead of fetching full session data.
        """
        # Count sessions
        session_count_stmt = sa.select(sa.func.count(Sessions.id)).where(
            Sessions.group_chat_id == group_chat_id
        )

        if tenant_id is not None:
            session_count_stmt = session_count_stmt.join(
                Users, Sessions.user_id == Users.id
            ).where(Users.tenant_id == tenant_id)

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

        if tenant_id is not None:
            question_count_stmt = question_count_stmt.join(
                Users, Sessions.user_id == Users.id
            ).where(Users.tenant_id == tenant_id)

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

    async def count_group_chat_questions_since(
        self,
        *,
        group_chat_id: UUID,
        from_date: datetime,
        to_date: datetime,
        tenant_id: UUID,
    ) -> int:
        stmt = (
            sa.select(sa.func.count(Questions.id))
            .join(Sessions, Questions.session_id == Sessions.id)
            .join(Users, Sessions.user_id == Users.id)
            .where(Users.tenant_id == tenant_id)
            .where(Sessions.group_chat_id == group_chat_id)
            .where(Sessions.created_at >= from_date)
            .where(Sessions.created_at <= to_date)
        )
        return await self.session.scalar(stmt) or 0

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
