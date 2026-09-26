from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, NamedTuple
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import QueryableAttribute, aliased, selectinload

from eneo.actors.actors.space_actor import SpaceAccessFacts, SpaceRoleFact
from eneo.database.database import AsyncSession
from eneo.database.repositories.base import BaseRepositoryDelegate
from eneo.database.tables.api_keys_v2_table import ApiKeysV2
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.files_table import Files
from eneo.database.tables.group_chats_table import GroupChatsTable
from eneo.database.tables.help_assistant_runs_table import HelpAssistantRuns
from eneo.database.tables.info_blobs_table import InfoBlobs
from eneo.database.tables.questions_table import (
    InfoBlobReferences,
    QuestionFeedback,
    Questions,
    QuestionsFiles,
)
from eneo.database.tables.sessions_table import Sessions
from eneo.database.tables.spaces_table import Spaces, SpacesUserGroups, SpacesUsers
from eneo.database.tables.user_groups_table import UserGroups
from eneo.database.tables.users_table import Users
from eneo.files.file_content_loader import FileContentLoader
from eneo.info_blobs.info_blob_repo import InfoBlobRepository
from eneo.questions.question import MessageFeedback
from eneo.questions.question_file_projection import attach_question_files
from eneo.sessions.session import (
    SessionAdd,
    SessionFeedback,
    SessionInDB,
    SessionMetadataPublic,
    SessionUpdate,
)
from eneo.user_groups.user_group import UserGroupState


class OwnedChatPartner(NamedTuple):
    assistant_id: UUID | None
    group_chat_id: UUID | None


@dataclass(frozen=True, slots=True)
class ChatPartnerAccess:
    """An assistant or group chat the user has conversations with.

    ``space`` carries what ``SpaceActor`` needs to decide whether the user may
    still open it; ``published`` only matters for group chats.
    """

    assistant_id: UUID | None
    group_chat_id: UUID | None
    name: str
    published: bool
    space_name: str
    space: SpaceAccessFacts

    @property
    def id(self) -> UUID:
        partner_id = self.group_chat_id or self.assistant_id
        assert partner_id is not None
        return partner_id


class RecentSessionRow(NamedTuple):
    id: UUID
    name: str
    created_at: datetime
    last_activity_at: datetime
    assistant_id: UUID | None
    group_chat_id: UUID | None


class SessionRepository:
    def __init__(
        self,
        session: AsyncSession,
        file_content_loader: FileContentLoader | None = None,
    ):
        super().__init__()
        self.delegate: BaseRepositoryDelegate[SessionInDB] = BaseRepositoryDelegate(
            session, Sessions, SessionInDB, with_options=self._options()
        )
        self.session = session
        self.file_content_loader = file_content_loader

    async def _hydrate_sessions(
        self,
        sessions: list[SessionInDB],
    ) -> list[SessionInDB]:
        info_blobs = [
            info_blob
            for session in sessions
            for question in session.questions
            for info_blob in question.info_blobs
        ]
        await InfoBlobRepository(self.session).hydrate_original_availability(info_blobs)
        if self.file_content_loader is None:
            if any(
                question.questions_files
                for session in sessions
                for question in session.questions
            ):
                raise RuntimeError("Session files require FileContentLoader")
            return sessions
        await attach_question_files(
            [question for session in sessions for question in session.questions],
            loader=self.file_content_loader,
        )
        return sessions

    async def _hydrate_optional(
        self,
        session: SessionInDB | None,
    ) -> SessionInDB | None:
        if session is None:
            return None
        return (await self._hydrate_sessions([session]))[0]

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
        return await self._hydrate_optional(await self.delegate.update(session))

    async def add_feedback(self, feedback: SessionFeedback, id: UUID) -> SessionInDB:
        stmt = (
            sa.Update(Sessions)
            .values(feedback_value=feedback.value, feedback_text=feedback.text)
            .where(Sessions.id == id)
            .returning(Sessions)
        )

        stmt_with_options = self._add_options(stmt)
        session = await self.session.scalar(stmt_with_options)

        return (await self._hydrate_sessions([SessionInDB.model_validate(session)]))[0]

    async def get(self, id: UUID) -> SessionInDB | None:
        query = self._exclude_helper_run_sessions(
            sa.select(Sessions).where(Sessions.id == id)
        )
        return await self._hydrate_optional(
            await self.delegate.get_model_from_query(query)
        )

    async def get_owned_chat_partner(
        self,
        *,
        session_id: UUID,
        tenant_id: UUID,
        user_id: UUID,
    ) -> OwnedChatPartner | None:
        """Read only the partner IDs required to authorize diagnostics."""
        query = (
            sa.select(Sessions.assistant_id, Sessions.group_chat_id)
            .join(Users, Sessions.user_id == Users.id)
            .where(Sessions.id == session_id)
            .where(Sessions.user_id == user_id)
            .where(Users.tenant_id == tenant_id)
        )
        query = self._exclude_helper_run_sessions(query)
        row = (await self.session.execute(query)).one_or_none()
        if row is None:
            return None
        return OwnedChatPartner(
            assistant_id=row.assistant_id,
            group_chat_id=row.group_chat_id,
        )

    async def get_chat_partners_of_user(
        self,
        *,
        user_id: UUID,
        tenant_id: UUID,
        user_group_ids: Collection[UUID],
    ) -> list[ChatPartnerAccess]:
        """Every assistant and group chat the user has conversations with.

        Each comes with the facts of its space that decide whether the user
        can still open it: the space's kind and default assistant, the user's
        direct role and the roles of the user's groups. Like
        ``SpaceRepository.get_info_blob_read_access`` these cover the user's
        own membership only; resource-scoped API key ids are left out.
        """
        partners = self._exclude_helper_run_sessions(
            sa.select(Sessions.assistant_id, Sessions.group_chat_id)
            .where(Sessions.user_id == user_id)
            .where(
                sa.or_(
                    Sessions.assistant_id.is_not(None),
                    Sessions.group_chat_id.is_not(None),
                )
            )
            .distinct()
        ).subquery("partners")
        # The space's own assistant, picked the way the space load picks it.
        default_assistants = aliased(Assistants)
        default_assistant_id = (
            sa.select(default_assistants.id)
            .where(default_assistants.space_id == Spaces.id)
            .where(default_assistants.is_default.is_(True))
            .order_by(default_assistants.created_at)
            .limit(1)
            .correlate(Spaces)
            .scalar_subquery()
        )
        query = (
            sa.select(
                partners.c.assistant_id,
                partners.c.group_chat_id,
                Assistants.name.label("assistant_name"),
                GroupChatsTable.name.label("group_chat_name"),
                GroupChatsTable.published.label("group_chat_published"),
                Spaces.id.label("space_id"),
                Spaces.name.label("space_name"),
                Spaces.user_id.label("space_user_id"),
                Spaces.tenant_space_id,
                default_assistant_id.label("default_assistant_id"),
                sa.Nullable(SpacesUsers.role),
            )
            .select_from(partners)
            .outerjoin(GroupChatsTable, GroupChatsTable.id == partners.c.group_chat_id)
            # A group chat conversation belongs to the group chat, whatever
            # assistant answered in it.
            .outerjoin(
                Assistants,
                sa.and_(
                    partners.c.group_chat_id.is_(None),
                    Assistants.id == partners.c.assistant_id,
                ),
            )
            .join(
                Spaces,
                Spaces.id
                == sa.func.coalesce(GroupChatsTable.space_id, Assistants.space_id),
            )
            .outerjoin(
                SpacesUsers,
                sa.and_(
                    SpacesUsers.space_id == Spaces.id,
                    SpacesUsers.user_id == user_id,
                ),
            )
            .where(Spaces.tenant_id == tenant_id)
        )
        rows = (await self.session.execute(query)).all()

        group_roles: dict[UUID, dict[UUID, SpaceRoleFact]] = {}
        space_ids = {row.space_id for row in rows}
        if user_group_ids and space_ids:
            group_rows = await self.session.execute(
                sa.select(
                    SpacesUserGroups.space_id,
                    SpacesUserGroups.user_group_id,
                    SpacesUserGroups.role,
                )
                .join(UserGroups, UserGroups.id == SpacesUserGroups.user_group_id)
                .where(SpacesUserGroups.space_id.in_(space_ids))
                .where(SpacesUserGroups.user_group_id.in_(user_group_ids))
                .where(UserGroups.tenant_id == tenant_id)
                .where(
                    sa.or_(
                        UserGroups.state.is_(None),
                        UserGroups.state != UserGroupState.DELETED.value,
                    )
                )
            )
            for space_id, group_id, role in group_rows.tuples():
                group_roles.setdefault(space_id, {})[group_id] = SpaceRoleFact(
                    id=group_id, role=role
                )

        spaces: dict[UUID, SpaceAccessFacts] = {}
        partner_access: list[ChatPartnerAccess] = []
        for row in rows:
            space = spaces.get(row.space_id)
            if space is None:
                space = spaces[row.space_id] = SpaceAccessFacts(
                    id=row.space_id,
                    user_id=row.space_user_id,
                    tenant_space_id=row.tenant_space_id,
                    members=(
                        {user_id: SpaceRoleFact(id=user_id, role=row.role)}
                        if row.role is not None
                        else {}
                    ),
                    group_members=group_roles.get(row.space_id, {}),
                    default_assistant_id=row.default_assistant_id,
                    assistant_ids=frozenset(),
                    app_ids=frozenset(),
                )
            is_group_chat = row.group_chat_id is not None
            partner_access.append(
                ChatPartnerAccess(
                    assistant_id=None if is_group_chat else row.assistant_id,
                    group_chat_id=row.group_chat_id,
                    name=row.group_chat_name if is_group_chat else row.assistant_name,
                    published=bool(row.group_chat_published),
                    space_name=row.space_name,
                    space=space,
                )
            )
        return partner_access

    async def get_recent_for_user(
        self,
        *,
        user_id: UUID,
        assistant_ids: Collection[UUID],
        group_chat_ids: Collection[UUID],
        limit: int,
    ) -> list[RecentSessionRow]:
        """The user's own conversations with these partners, latest activity first.

        A conversation's activity is its latest question, or its creation when
        it has none. The user's sessions come from
        ``idx_sessions_user_created_at`` and each latest question is one
        index-only probe of ``idx_questions_session_created_id``, so the cost
        follows the size of the user's own history, not the tenant's.
        """
        last_question_at = (
            sa.select(sa.func.max(Questions.created_at))
            .where(Questions.session_id == Sessions.id)
            .correlate(Sessions)
            .scalar_subquery()
        )
        last_activity_at = sa.func.coalesce(
            last_question_at, Sessions.created_at
        ).label("last_activity_at")
        query = self._exclude_helper_run_sessions(
            sa.select(
                Sessions.id,
                Sessions.name,
                Sessions.created_at,
                last_activity_at,
                Sessions.assistant_id,
                Sessions.group_chat_id,
            )
            .where(Sessions.user_id == user_id)
            .where(
                sa.or_(
                    sa.and_(
                        Sessions.group_chat_id.is_(None),
                        Sessions.assistant_id.in_(assistant_ids),
                    ),
                    Sessions.group_chat_id.in_(group_chat_ids),
                )
            )
            .order_by(last_activity_at.desc(), Sessions.id.desc())
            .limit(limit)
        )
        result = await self.session.execute(query)
        return [RecentSessionRow(*row) for row in result.tuples()]

    @staticmethod
    def _owned_by(
        user_id: UUID | None, api_key_id: UUID | None
    ) -> sa.ColumnElement[bool]:
        """Sessions of exactly this principal: a user, or a service API key.

        Never matches NULL against NULL, so a request without either principal
        owns nothing.
        """
        if user_id is not None:
            return Sessions.user_id == user_id
        if api_key_id is not None:
            return Sessions.api_key_id == api_key_id
        return sa.false()

    def _owned_message(
        self,
        *columns: sa.ColumnElement[Any] | QueryableAttribute[Any],
        session_id: UUID,
        message_id: UUID,
        tenant_id: UUID,
        user_id: UUID | None,
        api_key_id: UUID | None,
    ) -> sa.Select[Any]:
        """A message in one of the principal's assistant or group chat conversations."""
        query = (
            sa.select(*columns)
            .select_from(Questions)
            .join(Sessions, Sessions.id == Questions.session_id)
            .where(Questions.id == message_id)
            .where(Questions.session_id == session_id)
            .where(Questions.tenant_id == tenant_id)
            .where(self._owned_by(user_id, api_key_id))
            .where(
                sa.or_(
                    Sessions.assistant_id.is_not(None),
                    Sessions.group_chat_id.is_not(None),
                )
            )
        )
        return self._exclude_helper_run_sessions(query)

    async def get_owned_message_partner(
        self,
        *,
        session_id: UUID,
        message_id: UUID,
        tenant_id: UUID,
        user_id: UUID | None,
        api_key_id: UUID | None,
    ) -> OwnedChatPartner | None:
        """The chat partner of a message in one of the principal's conversations.

        None when the message is not in that session, the session belongs to
        another principal or tenant, or it has no assistant or group chat.
        """
        query = self._owned_message(
            Sessions.assistant_id,
            Sessions.group_chat_id,
            session_id=session_id,
            message_id=message_id,
            tenant_id=tenant_id,
            user_id=user_id,
            api_key_id=api_key_id,
        )
        row = (await self.session.execute(query)).one_or_none()
        if row is None:
            return None
        return OwnedChatPartner(
            assistant_id=row.assistant_id,
            group_chat_id=row.group_chat_id,
        )

    async def set_message_feedback(
        self,
        *,
        session_id: UUID,
        message_id: UUID,
        tenant_id: UUID,
        user_id: UUID | None,
        api_key_id: UUID | None,
        feedback: MessageFeedback,
    ) -> MessageFeedback | None:
        """Rate a message in one of the principal's conversations.

        Replaces an earlier rating of the message. Returns None, and writes
        nothing, when the message is not the principal's.
        """
        source = self._owned_message(
            Questions.id,
            sa.literal(feedback.value, sa.SmallInteger()),
            sa.literal(feedback.text, sa.Text()),
            sa.literal(user_id, PG_UUID(as_uuid=True)),
            sa.literal(api_key_id, PG_UUID(as_uuid=True)),
            session_id=session_id,
            message_id=message_id,
            tenant_id=tenant_id,
            user_id=user_id,
            api_key_id=api_key_id,
        )
        insert = pg_insert(QuestionFeedback).from_select(
            ["question_id", "value", "text", "user_id", "api_key_id"], source
        )
        stmt = insert.on_conflict_do_update(
            index_elements=[QuestionFeedback.question_id],
            set_={
                "value": insert.excluded.value,
                "text": insert.excluded.text,
                "user_id": insert.excluded.user_id,
                "api_key_id": insert.excluded.api_key_id,
                "updated_at": sa.func.now(),
            },
        ).returning(QuestionFeedback.value, QuestionFeedback.text)
        row = (await self.session.execute(stmt)).one_or_none()
        if row is None:
            return None
        return MessageFeedback(value=row.value, text=row.text)

    async def delete_message_feedback(
        self,
        *,
        session_id: UUID,
        message_id: UUID,
        tenant_id: UUID,
        user_id: UUID | None,
        api_key_id: UUID | None,
    ) -> None:
        """Remove the rating of a message in one of the principal's conversations.

        A no-op when the message has no rating or is not the principal's.
        """
        owned = self._owned_message(
            Questions.id,
            session_id=session_id,
            message_id=message_id,
            tenant_id=tenant_id,
            user_id=user_id,
            api_key_id=api_key_id,
        )
        await self.session.execute(
            sa.delete(QuestionFeedback).where(QuestionFeedback.question_id.in_(owned))
        )

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
        return await self._hydrate_optional(
            await self.delegate.get_model_from_query(query)
        )

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
                items = await self._hydrate_sessions(
                    await self.delegate.get_models_from_query(query)
                )
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

        sessions = await self._hydrate_sessions(
            await self.delegate.get_models_from_query(query)
        )
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
                items = await self._hydrate_sessions(
                    await self.delegate.get_models_from_query(query)
                )
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

        sessions = await self._hydrate_sessions(
            await self.delegate.get_models_from_query(query)
        )
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

        sessions = await self._hydrate_sessions(
            await self.delegate.get_models_from_query(query)
        )
        return sessions

    async def delete(self, id: UUID) -> SessionInDB | None:
        """Delete a session and the generated files only its answers owned.

        Questions and their file links cascade with the session, but the
        ``files`` rows do not: a tool-generated image (linked with type
        ``assistant``) has no other owner surface, so it is removed here once
        nothing else references it. Uploads are left alone; the user manages
        those.
        """
        generated_file_ids = list(
            await self.session.scalars(
                sa.select(QuestionsFiles.file_id)
                .join(Questions, Questions.id == QuestionsFiles.question_id)
                .where(Questions.session_id == id, QuestionsFiles.type == "assistant")
            )
        )
        deleted = await self.delegate.delete(id)
        if generated_file_ids:
            still_referenced = sa.select(QuestionsFiles.file_id).where(
                QuestionsFiles.file_id.in_(generated_file_ids)
            )
            await self.session.execute(
                sa.delete(Files).where(
                    Files.id.in_(generated_file_ids),
                    Files.id.not_in(still_referenced),
                )
            )
        return await self._hydrate_optional(deleted)
