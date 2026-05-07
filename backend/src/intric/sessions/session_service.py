from collections.abc import Sequence
from contextlib import asynccontextmanager
from datetime import datetime
from typing import TYPE_CHECKING, AsyncIterator
from uuid import UUID

from intric.ai_models.completion_models.completion_model import CompletionModel
from intric.assistants.assistant_service import AssistantService
from intric.authentication.auth_models import is_service_api_key
from intric.files.file_models import File
from intric.group_chat.application.group_chat_service import GroupChatService
from intric.info_blobs.info_blob import InfoBlobChunkInDBWithScore
from intric.logging.logging import LoggingDetails
from intric.main.exceptions import (
    BadRequestException,
    NotFoundException,
    UnauthorizedException,
)
from intric.questions.question import QuestionAdd, ToolCallInfo
from intric.questions.questions_repo import QuestionRepository
from intric.sessions.session import (
    SessionAdd,
    SessionFeedback,
    SessionInDB,
    SessionUpdate,
)
from intric.sessions.sessions_repo import SessionRepository
from intric.users.user import UserInDB

if TYPE_CHECKING:
    from intric.completion_models.infrastructure.web_search import WebSearchResult


class SessionService:
    def __init__(
        self,
        session_repo: SessionRepository,
        question_repo: QuestionRepository,
        user: UserInDB,
        assistant_service: AssistantService | None = None,
        group_chat_service: GroupChatService | None = None,
    ):
        super().__init__()
        self.session_repo = session_repo
        self.question_repo = question_repo
        self.user = user
        self.assistant_service = assistant_service
        self.group_chat_service = group_chat_service

    @asynccontextmanager
    async def _write_transaction(self) -> AsyncIterator[None]:
        """Open a short write transaction only when one is not already active."""
        session = self.session_repo.session
        if session.in_transaction():
            yield
            return

        async with session.begin():
            yield

    def _principal_columns(self) -> tuple[UUID | None, UUID | None]:
        """Return (user_id, api_key_id) for the current authenticated principal.

        Service keys resolve to a synthetic UserInDB whose id is not in the
        users table, so we cannot persist self.user.id as sessions.user_id.
        Instead we record the API key id; the resolver-supplied UserInDB
        carries it on .active_api_key.

        Exactly one of the returned values is non-None.
        """
        if is_service_api_key(self.user):
            key = self.user.active_api_key
            assert key is not None  # guaranteed by is_service_api_key
            return None, key.id
        return self.user.id, None

    def _is_owner(self, session: SessionInDB) -> bool:
        """Match the session's principal against the current request's principal.

        Both branches require a non-None match; we never treat NULL == NULL
        as a match (defends against the synthetic-user/no-user trap where two
        unrelated NULL fields would otherwise compare equal).
        """
        user_id, api_key_id = self._principal_columns()
        if user_id is not None:
            return session.user_id == user_id
        if api_key_id is not None:
            return session.api_key_id == api_key_id
        return False

    def _check_exists_and_belongs_to_user(
        self,
        session: SessionInDB | None,
        assistant_id: UUID | None = None,
        group_chat_id: UUID | None = None,
    ) -> SessionInDB:
        if session is None:
            raise NotFoundException("Session not found")

        if not self._is_owner(session):
            raise UnauthorizedException("Session belongs to other principal")

        # Handle cross-endpoint access attempt
        if assistant_id is not None and session.group_chat_id is not None:
            raise BadRequestException(
                "Cannot access a group chat session through the assistant endpoint. "
                "Use the conversation endpoints instead."
            )

        # Verify the session belongs to the specified assistant/group chat
        if (
            assistant_id is not None
            and session.assistant is not None
            and session.assistant.id != assistant_id
        ):
            raise NotFoundException("Session belongs to another assistant")
        if group_chat_id is not None and session.group_chat_id != group_chat_id:
            raise NotFoundException("Session belongs to another group chat")

        return session

    async def get_session_by_uuid(
        self,
        id: UUID,
        assistant_id: UUID | None = None,
        group_chat_id: UUID | None = None,
    ) -> SessionInDB:
        session = await self.session_repo.get(id=id)

        return self._check_exists_and_belongs_to_user(
            session, assistant_id=assistant_id, group_chat_id=group_chat_id
        )

    async def get_sessions_by_assistant(
        self,
        assistant_id: UUID,
        limit: int | None = None,
        cursor: datetime | None = None,
        previous: bool = False,
        name_filter: str | None = None,
    ) -> tuple[list[SessionInDB], int]:
        user_id, api_key_id = self._principal_columns()
        return await self.session_repo.get_by_assistant(
            assistant_id=assistant_id,
            user_id=user_id,
            api_key_id=api_key_id,
            limit=limit,
            cursor=cursor,
            previous=previous,
            name_filter=name_filter,
        )

    async def update_session(self, session_update: SessionUpdate) -> SessionInDB:
        session = await self.session_repo.update(session_update)
        return self._check_exists_and_belongs_to_user(session)

    async def delete(
        self,
        id: UUID,
        assistant_id: UUID | None = None,
        group_chat_id: UUID | None = None,
    ) -> SessionInDB | None:
        session = await self.session_repo.get(id)
        owned_session = self._check_exists_and_belongs_to_user(
            session, assistant_id=assistant_id, group_chat_id=group_chat_id
        )
        return await self.session_repo.delete(owned_session.id)

    async def create_session(
        self,
        name: str,
        assistant_id: UUID | None = None,
        group_chat_id: UUID | None = None,
    ) -> SessionInDB:
        user_id, api_key_id = self._principal_columns()
        session_add = SessionAdd(
            name=name,
            user_id=user_id,
            api_key_id=api_key_id,
            assistant_id=assistant_id,
            group_chat_id=group_chat_id,
        )
        async with self._write_transaction():
            return await self.session_repo.add(session_add)

    async def add_question_to_session(
        self,
        *,
        question: str,
        answer: str,
        num_tokens_question: int,
        num_tokens_answer: int,
        session: SessionInDB,
        completion_model: CompletionModel | None = None,
        info_blob_chunks: list[InfoBlobChunkInDBWithScore],
        files: Sequence[File] | None = None,
        generated_files: Sequence[File] | None = None,
        logging_details: LoggingDetails | None = None,
        assistant_id: UUID | None = None,
        web_search_results: Sequence["WebSearchResult"] | None = None,
        tool_calls: list[ToolCallInfo] | None = None,
    ) -> object:
        completion_model_id = completion_model.id if completion_model else None
        question_add = QuestionAdd(
            tenant_id=self.user.tenant_id,
            question=question,
            answer=answer,
            num_tokens_question=num_tokens_question,
            num_tokens_answer=num_tokens_answer,
            completion_model_id=completion_model_id,
            session_id=session.id,
            logging_details=logging_details,
            assistant_id=assistant_id,
            tool_calls=tool_calls,
        )

        async with self._write_transaction():
            return await self.question_repo.add(
                question_add,
                info_blob_chunks=info_blob_chunks,
                files=list(files or []),
                generated_files=list(generated_files or []),
                web_search_results=list(web_search_results or []),
            )

    async def leave_feedback(
        self,
        session_id: UUID,
        feedback: SessionFeedback,
        assistant_id: UUID | None = None,
        group_chat_id: UUID | None = None,
    ) -> SessionInDB:
        session = await self.session_repo.get(id=session_id)
        owned_session = self._check_exists_and_belongs_to_user(
            session, assistant_id=assistant_id, group_chat_id=group_chat_id
        )
        return await self.session_repo.add_feedback(
            feedback=feedback, id=owned_session.id
        )

    async def get_sessions_by_group_chat(
        self,
        group_chat_id: UUID,
        limit: int | None = None,
        cursor: datetime | None = None,
        previous: bool = False,
        name_filter: str | None = None,
    ) -> tuple[list[SessionInDB], int]:
        user_id, api_key_id = self._principal_columns()
        return await self.session_repo.get_by_group_chat(
            group_chat_id=group_chat_id,
            user_id=user_id,
            api_key_id=api_key_id,
            limit=limit,
            cursor=cursor,
            previous=previous,
            name_filter=name_filter,
        )
