from datetime import datetime
from typing import TYPE_CHECKING, Optional
from uuid import UUID

from intric.ai_models.completion_models.completion_model import CompletionModel
from intric.assistants.assistant_service import AssistantService
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
from intric.sessions.session import SessionAdd, SessionFeedback, SessionInDB
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
        assistant_service: AssistantService = None,
        group_chat_service: GroupChatService = None,
    ):
        self.session_repo = session_repo
        self.question_repo = question_repo
        self.user = user
        self.assistant_service = assistant_service
        self.group_chat_service = group_chat_service

    def _check_exists_and_belongs_to_user(
        self,
        session: SessionInDB,
        assistant_id: UUID = None,
        group_chat_id: UUID = None,
    ):
        if session is None:
            raise NotFoundException("Session not found")

        if session.user_id != self.user.id:
            raise UnauthorizedException("Session belongs to other user")

        # Handle cross-endpoint access attempt
        if assistant_id is not None and session.group_chat_id is not None:
            raise BadRequestException(
                "Cannot access a group chat session through the assistant endpoint. "
                "Use the conversation endpoints instead."
            )

        # Verify the session belongs to the specified assistant/group chat
        if assistant_id is not None and session.assistant.id != assistant_id:
            raise NotFoundException("Session belongs to another assistant")
        if group_chat_id is not None and session.group_chat_id != group_chat_id:
            raise NotFoundException("Session belongs to another group chat")

    async def get_session_by_uuid(
        self, id: UUID, assistant_id: UUID = None, group_chat_id: UUID = None
    ):
        session = await self.session_repo.get(id=id)

        self._check_exists_and_belongs_to_user(
            session, assistant_id=assistant_id, group_chat_id=group_chat_id
        )

        return session

    async def get_sessions_by_assistant(
        self,
        assistant_id: UUID,
        limit: int = None,
        cursor: datetime = None,
        previous: bool = False,
        name_filter: str = None,
    ):
        return await self.session_repo.get_by_assistant(
            assistant_id=assistant_id,
            user_id=self.user.id,
            limit=limit,
            cursor=cursor,
            previous=previous,
            name_filter=name_filter,
        )

    async def update_session(self, session_update):
        session = await self.session_repo.update(session_update)
        self._check_exists_and_belongs_to_user(session)
        return session

    async def delete(self, id: UUID, assistant_id: UUID = None, group_chat_id: UUID = None):
        session = await self.session_repo.get(id)
        self._check_exists_and_belongs_to_user(
            session, assistant_id=assistant_id, group_chat_id=group_chat_id
        )
        return await self.session_repo.delete(session.id)

    async def create_session(
        self, name: str, assistant_id: UUID = None, group_chat_id: UUID = None
    ):
        session_add = SessionAdd(
            name=name,
            user_id=self.user.id,
            assistant_id=assistant_id,
            group_chat_id=group_chat_id,
        )

        return await self.session_repo.add(session_add)

    async def add_question_to_session(
        self,
        *,
        question: str,
        answer: str,
        num_tokens_question: int,
        num_tokens_answer: int,
        session: SessionInDB,
        completion_model: CompletionModel = None,
        info_blob_chunks: list[InfoBlobChunkInDBWithScore],
        files: list[File] = [],
        generated_files: list[File] = [],
        logging_details: LoggingDetails = None,
        assistant_id: Optional[UUID] = None,
        web_search_results: list["WebSearchResult"] = [],
        tool_calls: Optional[list[ToolCallInfo]] = None,
    ):
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

        return await self.question_repo.add(
            question_add,
            info_blob_chunks=info_blob_chunks,
            files=files,
            generated_files=generated_files,
            web_search_results=web_search_results,
        )

    async def leave_feedback(
        self,
        session_id: UUID,
        feedback: SessionFeedback,
        assistant_id: UUID = None,
        group_chat_id: UUID = None,
    ):
        session = await self.session_repo.get(id=session_id)
        self._check_exists_and_belongs_to_user(
            session, assistant_id=assistant_id, group_chat_id=group_chat_id
        )
        return await self.session_repo.add_feedback(feedback=feedback, id=session.id)

    async def get_sessions_by_group_chat(
        self,
        group_chat_id: UUID,
        limit: int = None,
        cursor: datetime = None,
        previous: bool = False,
        name_filter: str = None,
    ):
        return await self.session_repo.get_by_group_chat(
            group_chat_id=group_chat_id,
            user_id=self.user.id,
            limit=limit,
            cursor=cursor,
            previous=previous,
            name_filter=name_filter,
        )
