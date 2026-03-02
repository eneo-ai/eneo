from datetime import datetime
from typing import Optional, cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import selectinload

from intric.database.database import AsyncSession
from intric.database.repositories.base import BaseRepositoryDelegate
from intric.database.tables.assistant_table import Assistants
from intric.database.tables.info_blobs_table import InfoBlobs
from intric.database.tables.questions_table import (
    InfoBlobReferences,
    Questions,
    QuestionsFiles,
)
from intric.database.tables.sessions_table import Sessions
from intric.database.tables.users_table import Users
from intric.sessions.session import (
    SessionAdd,
    SessionFeedback,
    SessionInDB,
    SessionMetadataPublic,
    SessionUpdate,
)


class SessionRepository:
    def __init__(self, session: AsyncSession):
        self.delegate = BaseRepositoryDelegate(
            session, Sessions, SessionInDB, with_options=self._options()
        )
        self.session = session

    @staticmethod
    def _options():
        return [
            selectinload(Sessions.questions)
            .selectinload(Questions.info_blob_references)
            .selectinload(InfoBlobReferences.info_blob)
            .selectinload(InfoBlobs.group),
            selectinload(Sessions.questions)
            .selectinload(Questions.info_blob_references)
            .selectinload(InfoBlobReferences.info_blob)
            .selectinload(InfoBlobs.website),
            selectinload(Sessions.questions).selectinload(Questions.logging_details),
            selectinload(Sessions.questions).selectinload(Questions.assistant),
            selectinload(Sessions.questions).selectinload(Questions.completion_model),
            selectinload(Sessions.questions)
            .selectinload(Questions.questions_files)
            .selectinload(QuestionsFiles.file),
            selectinload(Sessions.questions).selectinload(Questions.questions_files),
            selectinload(Sessions.questions).selectinload(Questions.web_search_results),
            selectinload(Sessions.assistant).selectinload(Assistants.user),
        ]

    def _add_options(self, stmt: sa.Select | sa.Insert | sa.Update):
        for option in self._options():
            stmt = stmt.options(option)

        return stmt

    async def add(self, session: SessionAdd) -> SessionInDB:
        return await self.delegate.add(session)

    async def update(self, session: SessionUpdate) -> SessionInDB:
        return await self.delegate.update(session)

    async def add_feedback(self, feedback: SessionFeedback, id: UUID):
        stmt = (
            sa.Update(Sessions)
            .values(feedback_value=feedback.value, feedback_text=feedback.text)
            .where(Sessions.id == id)
            .returning(Sessions)
        )

        stmt_with_options = self._add_options(stmt)
        session = await self.session.scalar(stmt_with_options)

        return SessionInDB.model_validate(session)

    async def get(self, id: Optional[UUID] = None, user_id: UUID = None) -> SessionInDB:
        if id is None and user_id is None:
            raise ValueError("One of id and user_id is required")

        if id is not None:
            return await self.delegate.get(id)

        return await self.delegate.filter_by(conditions={Sessions.user_id: user_id})

    async def _get_total_count(
        self,
        assistant_id: UUID = None,
        user_id: UUID = None,
        group_chat_id: UUID = None,
        name_filter: str = None,
        start_date: datetime = None,
        end_date: datetime = None,
        tenant_id: UUID = None,
    ):
        query = sa.select(sa.func.count()).select_from(Sessions)

        if tenant_id is not None:
            query = query.join(Users, Sessions.user_id == Users.id).where(
                Users.tenant_id == tenant_id
            )

        if assistant_id is not None:
            query = query.where(Sessions.assistant_id == assistant_id)
        if group_chat_id is not None:
            query = query.where(Sessions.group_chat_id == group_chat_id)

        if user_id is not None:
            query = query.where(Sessions.user_id == user_id)

        if name_filter is not None:
            query = query.where(Sessions.name.ilike(f"%{name_filter}%"))

        if start_date is not None:
            query = query.where(Sessions.created_at >= start_date)

        if end_date is not None:
            query = query.where(Sessions.created_at <= end_date)

        count = await self.session.scalar(query)
        return count if count is not None else 0

    async def get_by_assistant(
        self,
        assistant_id: UUID,
        user_id: UUID = None,
        limit: int = None,
        cursor: datetime = None,
        previous: bool = False,
        name_filter: str = None,
        start_date: datetime = None,
        end_date: datetime = None,
        tenant_id: UUID = None,
    ):
        normalized_name_filter = name_filter.strip() if name_filter else None
        query = sa.select(Sessions).where(Sessions.assistant_id == assistant_id)

        if tenant_id is not None:
            query = query.join(Users, Sessions.user_id == Users.id).where(
                Users.tenant_id == tenant_id
            )

        if user_id is not None:
            query = query.where(Sessions.user_id == user_id)

        if normalized_name_filter is not None:
            query = query.where(Sessions.name.ilike(f"%{normalized_name_filter}%"))

        if start_date is not None:
            query = query.where(Sessions.created_at >= start_date)

        if end_date is not None:
            query = query.where(Sessions.created_at <= end_date)

        total_count = await self._get_total_count(
            assistant_id=assistant_id,
            user_id=user_id,
            name_filter=normalized_name_filter,
            start_date=start_date,
            end_date=end_date,
            tenant_id=tenant_id,
        )

        if cursor is not None:
            if previous:
                query = query.where(Sessions.created_at > cursor).order_by(
                    Sessions.created_at.asc(),
                    Sessions.id.asc(),
                )
                if limit is not None:
                    query = query.limit(limit + 1)
                items = await self.delegate.get_models_from_query(query)
                items = cast(list[SessionInDB], items)
                items.reverse()
                return (items, total_count)
            else:
                query = query.where(Sessions.created_at <= cursor).order_by(
                    Sessions.created_at.desc(),
                    Sessions.id.desc(),
                )
        else:
            query = query.order_by(Sessions.created_at.desc(), Sessions.id.desc())

        if limit is not None:
            query = query.limit(limit + 1)

        sessions = await self.delegate.get_models_from_query(query)
        return sessions, total_count

    @staticmethod
    def _to_session_metadata(items) -> list[SessionMetadataPublic]:
        return [
            SessionMetadataPublic(
                id=item.id,
                name=item.name,
                created_at=item.created_at,
                updated_at=item.updated_at,
            )
            for item in items
        ]

    async def get_metadata_by_assistant(
        self,
        assistant_id: UUID,
        user_id: UUID = None,
        limit: int = None,
        cursor: datetime = None,
        previous: bool = False,
        name_filter: str = None,
        start_date: datetime = None,
        end_date: datetime = None,
        tenant_id: UUID = None,
    ) -> tuple[list[SessionMetadataPublic], int]:
        normalized_name_filter = name_filter.strip() if name_filter else None
        query = sa.select(
            Sessions.id, Sessions.name, Sessions.created_at, Sessions.updated_at
        ).where(Sessions.assistant_id == assistant_id)

        if tenant_id is not None:
            query = query.join(Users, Sessions.user_id == Users.id).where(
                Users.tenant_id == tenant_id
            )

        if user_id is not None:
            query = query.where(Sessions.user_id == user_id)

        if normalized_name_filter is not None:
            query = query.where(Sessions.name.ilike(f"%{normalized_name_filter}%"))

        if start_date is not None:
            query = query.where(Sessions.created_at >= start_date)

        if end_date is not None:
            query = query.where(Sessions.created_at <= end_date)

        total_count = await self._get_total_count(
            assistant_id=assistant_id,
            user_id=user_id,
            name_filter=normalized_name_filter,
            start_date=start_date,
            end_date=end_date,
            tenant_id=tenant_id,
        )

        if cursor is not None:
            if previous:
                query = query.where(Sessions.created_at > cursor).order_by(
                    Sessions.created_at.asc(),
                    Sessions.id.asc(),
                )
                if limit is not None:
                    query = query.limit(limit + 1)
                result = await self.session.execute(query)
                items = list(result)
                items.reverse()
                return (self._to_session_metadata(items), total_count)
            else:
                query = query.where(Sessions.created_at <= cursor).order_by(
                    Sessions.created_at.desc(),
                    Sessions.id.desc(),
                )
        else:
            query = query.order_by(Sessions.created_at.desc(), Sessions.id.desc())

        if limit is not None:
            query = query.limit(limit + 1)

        result = await self.session.execute(query)
        items = list(result)
        return self._to_session_metadata(items), total_count

    async def get_by_group_chat(
        self,
        group_chat_id: UUID,
        user_id: UUID = None,
        limit: int = None,
        cursor: datetime = None,
        previous: bool = False,
        name_filter: str = None,
        start_date: datetime = None,
        end_date: datetime = None,
        tenant_id: UUID = None,
    ):
        normalized_name_filter = name_filter.strip() if name_filter else None
        query = sa.select(Sessions).where(Sessions.group_chat_id == group_chat_id)

        if tenant_id is not None:
            query = query.join(Users, Sessions.user_id == Users.id).where(
                Users.tenant_id == tenant_id
            )

        if user_id is not None:
            query = query.where(Sessions.user_id == user_id)

        if normalized_name_filter is not None:
            query = query.where(Sessions.name.ilike(f"%{normalized_name_filter}%"))

        if start_date is not None:
            query = query.where(Sessions.created_at >= start_date)

        if end_date is not None:
            query = query.where(Sessions.created_at <= end_date)

        total_count = await self._get_total_count(
            group_chat_id=group_chat_id,
            user_id=user_id,
            name_filter=normalized_name_filter,
            start_date=start_date,
            end_date=end_date,
            tenant_id=tenant_id,
        )

        if cursor is not None:
            if previous:
                query = query.where(Sessions.created_at > cursor).order_by(
                    Sessions.created_at.asc(),
                    Sessions.id.asc(),
                )
                if limit is not None:
                    query = query.limit(limit + 1)
                items = await self.delegate.get_models_from_query(query)
                items = cast(list[SessionInDB], items)
                items.reverse()
                return (items, total_count)
            else:
                query = query.where(Sessions.created_at <= cursor).order_by(
                    Sessions.created_at.desc(),
                    Sessions.id.desc(),
                )
        else:
            query = query.order_by(Sessions.created_at.desc(), Sessions.id.desc())

        if limit is not None:
            query = query.limit(limit + 1)

        sessions = await self.delegate.get_models_from_query(query)
        return sessions, total_count

    async def get_metadata_by_group_chat(
        self,
        group_chat_id: UUID,
        user_id: UUID = None,
        limit: int = None,
        cursor: datetime = None,
        previous: bool = False,
        name_filter: str = None,
        start_date: datetime = None,
        end_date: datetime = None,
        tenant_id: UUID = None,
    ) -> tuple[list[SessionMetadataPublic], int]:
        normalized_name_filter = name_filter.strip() if name_filter else None
        query = sa.select(
            Sessions.id, Sessions.name, Sessions.created_at, Sessions.updated_at
        ).where(Sessions.group_chat_id == group_chat_id)

        if tenant_id is not None:
            query = query.join(Users, Sessions.user_id == Users.id).where(
                Users.tenant_id == tenant_id
            )

        if user_id is not None:
            query = query.where(Sessions.user_id == user_id)

        if normalized_name_filter is not None:
            query = query.where(Sessions.name.ilike(f"%{normalized_name_filter}%"))

        if start_date is not None:
            query = query.where(Sessions.created_at >= start_date)

        if end_date is not None:
            query = query.where(Sessions.created_at <= end_date)

        total_count = await self._get_total_count(
            group_chat_id=group_chat_id,
            user_id=user_id,
            name_filter=normalized_name_filter,
            start_date=start_date,
            end_date=end_date,
            tenant_id=tenant_id,
        )

        if cursor is not None:
            if previous:
                query = query.where(Sessions.created_at > cursor).order_by(
                    Sessions.created_at.asc(),
                    Sessions.id.asc(),
                )
                if limit is not None:
                    query = query.limit(limit + 1)
                result = await self.session.execute(query)
                items = list(result)
                items.reverse()
                return (self._to_session_metadata(items), total_count)
            else:
                query = query.where(Sessions.created_at <= cursor).order_by(
                    Sessions.created_at.desc(),
                    Sessions.id.desc(),
                )
        else:
            query = query.order_by(Sessions.created_at.desc(), Sessions.id.desc())

        if limit is not None:
            query = query.limit(limit + 1)

        result = await self.session.execute(query)
        items = list(result)
        return self._to_session_metadata(items), total_count

    async def get_by_tenant(
        self, tenant_id: UUID, start_date: datetime = None, end_date: datetime = None
    ):
        query = sa.select(Sessions).join(Users).where(Users.tenant_id == tenant_id)

        if start_date is not None:
            query = query.filter(Sessions.created_at >= start_date)

        if end_date is not None:
            query = query.filter(Sessions.created_at <= end_date)

        sessions = await self.delegate.get_models_from_query(query)
        return sessions

    async def delete(self, id: int) -> SessionInDB:
        return cast(SessionInDB, await self.delegate.delete(id))
