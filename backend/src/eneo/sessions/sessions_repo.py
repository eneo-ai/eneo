from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import selectinload

from eneo.database.database import AsyncSession
from eneo.database.repositories.base import BaseRepositoryDelegate
from eneo.database.tables.api_keys_v2_table import ApiKeysV2
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.help_assistant_runs_table import HelpAssistantRuns
from eneo.database.tables.info_blobs_table import InfoBlobs
from eneo.database.tables.questions_table import (
    InfoBlobReferences,
    Questions,
    QuestionsFiles,
)
from eneo.database.tables.sessions_table import Sessions
from eneo.database.tables.users_table import Users
from eneo.sessions.session import (
    SessionAdd,
    SessionFeedback,
    SessionInDB,
    SessionMetadataPublic,
    SessionUpdate,
)


class SessionRepository:
    def __init__(self, session: AsyncSession):
        super().__init__()
        self.delegate: BaseRepositoryDelegate[SessionInDB] = BaseRepositoryDelegate(
            session, Sessions, SessionInDB, with_options=self._options()
        )
        self.session = session

    @staticmethod
    def _options() -> list[Any]:
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
            selectinload(Sessions.questions).selectinload(
                Questions.mcp_tool_references
            ),
            selectinload(Sessions.assistant).selectinload(Assistants.user),
        ]

    def _add_options(
        self, stmt: sa.Select[Any] | sa.Insert | sa.Update
    ) -> sa.Select[Any] | sa.Insert | sa.Update:
        for option in self._options():
            stmt = stmt.options(option)

        return stmt

    @staticmethod
    def _filter_by_tenant(query: sa.Select[Any], tenant_id: UUID) -> sa.Select[Any]:
        """Restrict a sessions query to a single tenant.

        Sessions.user_id is NULL for service-key sessions (the principal is on
        api_key_id instead), so an INNER JOIN on Users would silently drop
        them. We LEFT JOIN both principal tables and match against whichever
        tenant_id is present.
        """
        return (
            query.outerjoin(Users, Sessions.user_id == Users.id)
            .outerjoin(ApiKeysV2, Sessions.api_key_id == ApiKeysV2.id)
            .where(sa.func.coalesce(Users.tenant_id, ApiKeysV2.tenant_id) == tenant_id)
        )

    # IMPORTANT: every method in this repo that returns session or question
    # rows must apply this filter. If you add a new such method, either call
    # this helper or document the explicit exception in a comment on the new
    # method. See PRD §4.
    @staticmethod
    def _exclude_helper_run_sessions(query: sa.Select[Any]) -> sa.Select[Any]:
        """Exclude sessions referenced by a help_assistant_runs row.

        Helper conversations live in the regular sessions/questions tables so
        streaming, RAG, model selection, and tool calling all work — but they
        must never appear in normal session / conversation / insights / export
        endpoints. This is the single rule, one place. Every method in this
        repo that returns session rows must apply it. See PRD §4.
        """
        return query.where(
            ~sa.exists(
                sa.select(HelpAssistantRuns.id).where(
                    HelpAssistantRuns.session_id == Sessions.id
                )
            )
        )

    async def add(self, session: SessionAdd) -> SessionInDB:
        return await self.delegate.add(session)

    async def update(self, session: SessionUpdate) -> SessionInDB | None:
        return await self.delegate.update(session)

    async def add_feedback(self, feedback: SessionFeedback, id: UUID) -> SessionInDB:
        stmt = (
            sa.Update(Sessions)
            .values(feedback_value=feedback.value, feedback_text=feedback.text)
            .where(Sessions.id == id)
            .returning(Sessions)
        )

        stmt_with_options = self._add_options(stmt)
        session = await self.session.scalar(stmt_with_options)

        return SessionInDB.model_validate(session)

    async def get(self, id: UUID) -> SessionInDB | None:
        query = self._exclude_helper_run_sessions(
            sa.select(Sessions).where(Sessions.id == id)
        )
        return await self.delegate.get_model_from_query(query)

    async def get_for_helper_run(self, id: UUID, tenant_id: UUID) -> SessionInDB | None:
        """Load a helper-run session with its prior questions eager-loaded.

        Documented exception to ``_exclude_helper_run_sessions``: the
        HelperRunService follow-up-turn path needs the session row that
        ``help_assistant_runs`` points at, so the completion call can rebuild
        prior conversation context. Tenant-scoped defensively via
        :meth:`_filter_by_tenant` — the caller already authorized against the
        run's actor, but a stray cross-tenant lookup must still fail. No
        other code path may call this method. See PRD §4 + §6.
        """
        query = self._filter_by_tenant(
            sa.select(Sessions).where(Sessions.id == id), tenant_id
        )
        return await self.delegate.get_model_from_query(query)

    async def _get_total_count(
        self,
        assistant_id: UUID | None = None,
        user_id: UUID | None = None,
        api_key_id: UUID | None = None,
        group_chat_id: UUID | None = None,
        name_filter: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        tenant_id: UUID | None = None,
    ) -> int:
        query = sa.select(sa.func.count()).select_from(Sessions)

        if tenant_id is not None:
            query = self._filter_by_tenant(query, tenant_id)
        query = self._exclude_helper_run_sessions(query)

        if assistant_id is not None:
            query = query.where(Sessions.assistant_id == assistant_id)
        if group_chat_id is not None:
            query = query.where(Sessions.group_chat_id == group_chat_id)

        # Principal scoping: user_id and api_key_id are mutually exclusive in
        # session_service callers (exactly one is non-None per request).
        if user_id is not None:
            query = query.where(Sessions.user_id == user_id)
        if api_key_id is not None:
            query = query.where(Sessions.api_key_id == api_key_id)

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
        user_id: UUID | None = None,
        api_key_id: UUID | None = None,
        limit: int | None = None,
        cursor: datetime | None = None,
        previous: bool = False,
        name_filter: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        tenant_id: UUID | None = None,
    ) -> tuple[list[SessionInDB], int]:
        normalized_name_filter = name_filter.strip() if name_filter else None
        query = sa.select(Sessions).where(Sessions.assistant_id == assistant_id)

        if tenant_id is not None:
            query = self._filter_by_tenant(query, tenant_id)
        query = self._exclude_helper_run_sessions(query)

        if user_id is not None:
            query = query.where(Sessions.user_id == user_id)
        if api_key_id is not None:
            query = query.where(Sessions.api_key_id == api_key_id)

        if normalized_name_filter is not None:
            query = query.where(Sessions.name.ilike(f"%{normalized_name_filter}%"))

        if start_date is not None:
            query = query.where(Sessions.created_at >= start_date)

        if end_date is not None:
            query = query.where(Sessions.created_at <= end_date)

        total_count = await self._get_total_count(
            assistant_id=assistant_id,
            user_id=user_id,
            api_key_id=api_key_id,
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
    def _to_session_metadata(
        items: Sequence[tuple[UUID, str, datetime | None, datetime | None]],
    ) -> list[SessionMetadataPublic]:
        return [
            SessionMetadataPublic(
                id=item[0],
                name=item[1],
                created_at=item[2],
                updated_at=item[3],
            )
            for item in items
        ]

    async def get_metadata_by_assistant(
        self,
        assistant_id: UUID,
        user_id: UUID | None = None,
        api_key_id: UUID | None = None,
        limit: int | None = None,
        cursor: datetime | None = None,
        previous: bool = False,
        name_filter: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        tenant_id: UUID | None = None,
    ) -> tuple[list[SessionMetadataPublic], int]:
        normalized_name_filter = name_filter.strip() if name_filter else None
        query = sa.select(
            Sessions.id, Sessions.name, Sessions.created_at, Sessions.updated_at
        ).where(Sessions.assistant_id == assistant_id)

        if tenant_id is not None:
            query = self._filter_by_tenant(query, tenant_id)
        query = self._exclude_helper_run_sessions(query)

        if user_id is not None:
            query = query.where(Sessions.user_id == user_id)
        if api_key_id is not None:
            query = query.where(Sessions.api_key_id == api_key_id)

        if normalized_name_filter is not None:
            query = query.where(Sessions.name.ilike(f"%{normalized_name_filter}%"))

        if start_date is not None:
            query = query.where(Sessions.created_at >= start_date)

        if end_date is not None:
            query = query.where(Sessions.created_at <= end_date)

        total_count = await self._get_total_count(
            assistant_id=assistant_id,
            user_id=user_id,
            api_key_id=api_key_id,
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
                items = list(result.tuples())
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
        items = list(result.tuples())
        return self._to_session_metadata(items), total_count

    async def get_by_group_chat(
        self,
        group_chat_id: UUID,
        user_id: UUID | None = None,
        api_key_id: UUID | None = None,
        limit: int | None = None,
        cursor: datetime | None = None,
        previous: bool = False,
        name_filter: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        tenant_id: UUID | None = None,
    ) -> tuple[list[SessionInDB], int]:
        normalized_name_filter = name_filter.strip() if name_filter else None
        query = sa.select(Sessions).where(Sessions.group_chat_id == group_chat_id)

        if tenant_id is not None:
            query = self._filter_by_tenant(query, tenant_id)
        query = self._exclude_helper_run_sessions(query)

        if user_id is not None:
            query = query.where(Sessions.user_id == user_id)
        if api_key_id is not None:
            query = query.where(Sessions.api_key_id == api_key_id)

        if normalized_name_filter is not None:
            query = query.where(Sessions.name.ilike(f"%{normalized_name_filter}%"))

        if start_date is not None:
            query = query.where(Sessions.created_at >= start_date)

        if end_date is not None:
            query = query.where(Sessions.created_at <= end_date)

        total_count = await self._get_total_count(
            group_chat_id=group_chat_id,
            user_id=user_id,
            api_key_id=api_key_id,
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
        user_id: UUID | None = None,
        api_key_id: UUID | None = None,
        limit: int | None = None,
        cursor: datetime | None = None,
        previous: bool = False,
        name_filter: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        tenant_id: UUID | None = None,
    ) -> tuple[list[SessionMetadataPublic], int]:
        normalized_name_filter = name_filter.strip() if name_filter else None
        query = sa.select(
            Sessions.id, Sessions.name, Sessions.created_at, Sessions.updated_at
        ).where(Sessions.group_chat_id == group_chat_id)

        if tenant_id is not None:
            query = self._filter_by_tenant(query, tenant_id)
        query = self._exclude_helper_run_sessions(query)

        if user_id is not None:
            query = query.where(Sessions.user_id == user_id)
        if api_key_id is not None:
            query = query.where(Sessions.api_key_id == api_key_id)

        if normalized_name_filter is not None:
            query = query.where(Sessions.name.ilike(f"%{normalized_name_filter}%"))

        if start_date is not None:
            query = query.where(Sessions.created_at >= start_date)

        if end_date is not None:
            query = query.where(Sessions.created_at <= end_date)

        total_count = await self._get_total_count(
            group_chat_id=group_chat_id,
            user_id=user_id,
            api_key_id=api_key_id,
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
                items = list(result.tuples())
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
        items = list(result.tuples())
        return self._to_session_metadata(items), total_count

    async def get_by_tenant(
        self,
        tenant_id: UUID,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[SessionInDB]:
        query = self._filter_by_tenant(sa.select(Sessions), tenant_id)
        query = self._exclude_helper_run_sessions(query)

        if start_date is not None:
            query = query.filter(Sessions.created_at >= start_date)

        if end_date is not None:
            query = query.filter(Sessions.created_at <= end_date)

        sessions = await self.delegate.get_models_from_query(query)
        return sessions

    async def delete(self, id: UUID) -> SessionInDB | None:
        return await self.delegate.delete(id)
