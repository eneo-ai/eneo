# MIT License
from datetime import date, datetime, timedelta
from typing import List, Optional
from uuid import UUID

from intric.analysis.analysis import ConversationInsightResponse, Counts
from intric.analysis.analysis_repo import AnalysisRepository
from intric.assistants.assistant_service import AssistantService
from intric.completion_models.infrastructure.completion_service import CompletionService
from intric.completion_models.infrastructure.static_prompts import ANALYSIS_PROMPT
from intric.group_chat.application.group_chat_service import GroupChatService
from intric.main.exceptions import BadRequestException, UnauthorizedException
from intric.main.logging import get_logger
from intric.questions.questions_repo import QuestionRepository
from intric.roles.permissions import Permission, validate_permissions
from intric.sessions.session import SessionInDB, SessionPublic
from intric.sessions.session_service import SessionService
from intric.sessions.sessions_repo import SessionRepository
from intric.spaces.space_service import SpaceService
from intric.users.user import UserInDB

logger = get_logger(__name__)


class AnalysisService:
    def __init__(
        self,
        user: UserInDB,
        repo: AnalysisRepository,
        assistant_service: AssistantService,
        question_repo: QuestionRepository,
        session_repo: SessionRepository,
        space_service: SpaceService,
        session_service: SessionService,
        group_chat_service: GroupChatService,
        completion_service: CompletionService,
    ):
        self.user = user
        self.repo = repo
        self.assistant_service = assistant_service
        self.session_repo = session_repo
        self.question_repo = question_repo
        self.space_service = space_service
        self.session_service = session_service
        self.group_chat_service = group_chat_service
        self.completion_service = completion_service

    @validate_permissions(Permission.INSIGHTS)
    async def get_tenant_counts(self):
        """Get total counts for assistants, sessions, and questions.

        Uses a single query for consistent results.
        """
        (
            assistant_count,
            session_count,
            questions_count,
        ) = await self.repo.get_tenant_counts(tenant_id=self.user.tenant_id)

        return Counts(
            assistants=assistant_count,
            sessions=session_count,
            questions=questions_count,
        )

    @validate_permissions(Permission.INSIGHTS)
    async def get_metadata_statistics(self, start_date: datetime, end_date: datetime):
        """Get metadata statistics for the tenant using optimized queries.

        Uses column-projection queries that only fetch id, created_at, and
        necessary foreign keys instead of loading full objects with all
        relationships.
        """
        assistants = await self.repo.get_assistant_metadata_for_tenant(
            tenant_id=self.user.tenant_id,
            start_date=start_date,
            end_date=end_date,
        )
        sessions = await self.repo.get_session_metadata_for_tenant(
            tenant_id=self.user.tenant_id,
            start_date=start_date,
            end_date=end_date,
        )
        questions = await self.repo.get_question_metadata_for_tenant(
            tenant_id=self.user.tenant_id,
            start_date=start_date,
            end_date=end_date,
        )

        return assistants, sessions, questions

    @validate_permissions(Permission.INSIGHTS)
    async def get_metadata_statistics_aggregated(
        self, start_date: datetime, end_date: datetime
    ):
        """Get aggregated metadata statistics for the tenant.

        Returns per-hour buckets to keep payloads small for large tenants.
        """
        assistants = await self.repo.get_assistant_counts_by_hour_for_tenant(
            tenant_id=self.user.tenant_id,
            start_date=start_date,
            end_date=end_date,
        )
        sessions = await self.repo.get_session_counts_by_hour_for_tenant(
            tenant_id=self.user.tenant_id,
            start_date=start_date,
            end_date=end_date,
        )
        questions = await self.repo.get_question_counts_by_hour_for_tenant(
            tenant_id=self.user.tenant_id,
            start_date=start_date,
            end_date=end_date,
        )

        return assistants, sessions, questions

    async def _check_space_permissions(self, space_id: UUID):
        space = await self.space_service.get_space(space_id)
        if space.is_personal() and Permission.INSIGHTS not in self.user.permissions:
            raise UnauthorizedException(
                f"Need permission {Permission.INSIGHTS.value} in order to access"
            )

    async def _check_insight_access(
        self,
        group_chat_id: UUID = None,
        assistant_id: UUID = None,
    ):
        if assistant_id:
            space = await self.space_service.get_space_by_assistant(
                assistant_id=assistant_id
            )
            actor = self.space_service.actor_manager.get_space_actor_from_space(
                space=space
            )
            assistant = space.get_assistant(assistant_id=assistant_id)

            if not actor.can_access_insight_assistant(assistant=assistant):
                raise UnauthorizedException(
                    "Insights are not enabled for this assistant"
                )

        elif group_chat_id:
            space = await self.space_service.get_space_by_group_chat(
                group_chat_id=group_chat_id
            )
            actor = self.space_service.actor_manager.get_space_actor_from_space(
                space=space
            )
            group_chat = space.get_group_chat(group_chat_id=group_chat_id)

            if not actor.can_access_insight_group_chat(group_chat=group_chat):
                raise UnauthorizedException(
                    "Insights are not enabled for this group chat"
                )

    async def get_questions_since(
        self,
        assistant_id: UUID,
        from_date: date,
        to_date: date,
        include_followups: bool = False,
    ):
        assistant, _ = await self.assistant_service.get_assistant(assistant_id)
        if assistant.space_id is not None:
            await self._check_space_permissions(assistant.space_id)

        sessions = await self.repo.get_assistant_sessions_since(
            assistant_id=assistant_id,
            from_date=from_date,
            to_date=to_date,
        )

        if include_followups:
            return [question for session in sessions for question in session.questions]

        first_questions = []
        for session in sessions:
            questions = session.questions
            if questions:
                first_questions.append(questions[0])
            else:
                # Session did not contain any questions, log this as an error
                # and don't add anything to the list
                logger.error(
                    "Session was empty",
                    extra=dict(session_id=session.id),
                )

        return first_questions

    async def get_questions_from_group_chat(
        self,
        group_chat_id: UUID,
        from_date: date,
        to_date: date,
        include_followups: bool = False,
    ):
        """Get questions asked to a group chat within a date range"""
        # Get sessions for the group chat
        sessions = await self.repo.get_group_chat_sessions_since(
            group_chat_id=group_chat_id,
            from_date=from_date,
            to_date=to_date,
        )

        if include_followups:
            return [question for session in sessions for question in session.questions]

        first_questions = []
        for session in sessions:
            questions = session.questions
            if questions:
                first_questions.append(questions[0])
            else:
                # Session did not contain any questions, log this as an error
                logger.error(
                    "Session was empty",
                    extra=dict(session_id=session.id),
                )

        return first_questions

    async def ask_question_on_questions(
        self,
        question: str,
        stream: bool,
        assistant_id: UUID,
        from_date: date,
        to_date: date,
        include_followup: bool = False,
    ):
        assistant, _ = await self.assistant_service.get_assistant(assistant_id)

        questions = await self.get_questions_since(
            assistant_id=assistant_id,
            from_date=from_date,
            to_date=to_date,
            include_followups=include_followup,
        )

        days = (to_date - from_date).days
        prompt = ANALYSIS_PROMPT.format(days=days)
        questions_string = "\n".join(
            f'"""{question.question}"""' for question in questions
        )
        prompt = f"{prompt}\n\n{questions_string}"

        ai_response = await assistant.get_response(
            question=question,
            completion_service=self.completion_service,
            prompt=prompt,
            stream=stream,
        )

        return ai_response

    async def unified_ask_question_on_questions(
        self,
        question: str,
        stream: bool,
        from_date: datetime,
        to_date: datetime,
        include_followup: bool = False,
        assistant_id: UUID = None,
        group_chat_id: UUID = None,
    ):
        """
        Ask a question about the questions previously asked to an assistant or group chat.

        Args:
            question: The question to ask about the previous questions
            stream: Whether to stream the response
            from_date: Start date to filter questions
            to_date: End date to filter questions
            include_followup: Whether to include follow-up questions
            assistant_id: UUID of the assistant (optional)
            group_chat_id: UUID of the group chat (optional)

        Returns:
            AI response about the questions

        Raises:
            BadRequestException: If neither assistant_id nor group_chat_id is provided
        """
        if not assistant_id and not group_chat_id:
            raise BadRequestException(
                "Either assistant_id or group_chat_id must be provided"
            )

        if assistant_id and group_chat_id:
            raise BadRequestException(
                "Provide either assistant_id or group_chat_id, not both"
            )

        # Get the appropriate questions based on type
        if assistant_id:
            await self._check_insight_access(assistant_id=assistant_id)
            assistant, _ = await self.assistant_service.get_assistant(assistant_id)
            questions = await self.get_questions_since(
                assistant_id=assistant_id,
                from_date=from_date,
                to_date=to_date,
                include_followups=include_followup,
            )
            # Use the assistant's model for generating the analysis
            model_to_use = assistant
        else:  # group_chat_id is provided
            await self._check_insight_access(group_chat_id=group_chat_id)
            space = await self.space_service.get_space_by_group_chat(
                group_chat_id=group_chat_id
            )
            group_chat = space.get_group_chat(group_chat_id=group_chat_id)

            if not group_chat.assistants:
                raise BadRequestException(
                    "Group chat has no assistants to process the analysis"
                )

            # Use the first assistant from the group chat for analysis
            model_to_use = group_chat.assistants[0].assistant

            # Get questions for the group chat
            questions = await self.get_questions_from_group_chat(
                group_chat_id=group_chat_id,
                from_date=from_date,
                to_date=to_date,
                include_followups=include_followup,
            )

        # Format the questions to pass to the LLM
        days = (to_date - from_date).days
        prompt = ANALYSIS_PROMPT.format(days=days)
        questions_string = "\n".join(
            f'"""{question.question}"""' for question in questions
        )
        prompt = f"{prompt}\n\n{questions_string}"

        # Get the AI response
        ai_response = await model_to_use.get_response(
            completion_service=self.completion_service,
            question=question,
            prompt=prompt,
            stream=stream,
        )

        return ai_response

    async def get_assistant_insight_sessions(
        self,
        assistant_id: UUID,
        limit: int = None,
        cursor: datetime = None,
        previous: bool = False,
        name_filter: str = None,
        start_date: datetime = None,
        end_date: datetime = None,
    ) -> List[SessionInDB]:
        """Get all sessions for an assistant across all users in the tenant (with insight access)

        Args:
            assistant_id: UUID of the assistant
            limit: Maximum number of sessions to return
            cursor: Datetime to start fetching from
            previous: Whether to fetch sessions before or after the cursor
            name_filter: Filter sessions by name
            start_date: Start date to filter sessions (optional)
            end_date: End date to filter sessions (optional)

        Returns:
            List of sessions for the assistant

        Raises:
            UnauthorizedException: If the user doesn't have insight access
        """

        await self._check_insight_access(assistant_id=assistant_id)

        sessions, total = await self.session_repo.get_by_assistant(
            assistant_id=assistant_id,
            limit=limit,
            cursor=cursor,
            previous=previous,
            name_filter=name_filter,
            start_date=start_date,
            end_date=end_date,
        )
        return sessions, total

    async def get_group_chat_insight_sessions(
        self,
        group_chat_id: UUID,
        limit: int = None,
        cursor: datetime = None,
        previous: bool = False,
        name_filter: str = None,
        start_date: datetime = None,
        end_date: datetime = None,
    ) -> List[SessionInDB]:
        """Get all sessions for a group chat across all users in the tenant (with insight access)

        Args:
            group_chat_id: UUID of the group chat
            limit: Maximum number of sessions to return
            cursor: Datetime to start fetching from
            previous: Whether to fetch sessions before or after the cursor
            name_filter: Filter sessions by name
            start_date: Start date to filter sessions (optional)
            end_date: End date to filter sessions (optional)

        Returns:
            List of sessions for the group chat

        Raises:
            UnauthorizedException: If the user doesn't have insight access
        """

        await self._check_insight_access(group_chat_id=group_chat_id)

        sessions, total = await self.session_repo.get_by_group_chat(
            group_chat_id=group_chat_id,
            limit=limit,
            cursor=cursor,
            previous=previous,
            name_filter=name_filter,
            start_date=start_date,
            end_date=end_date,
        )
        return sessions, total

    async def get_insight_session(
        self,
        session_id: UUID,
    ) -> SessionPublic:
        """Get a specific session with insight access

        Args:
            session_id: UUID of the session
            assistant_id: UUID of the assistant (optional)
            group_chat_id: UUID of the group chat (optional)

        Returns:
            Session data

        Raises:
            UnauthorizedException: If the user doesn't have insight access
            BadRequestException: If neither assistant_id nor group_chat_id is provided
        """
        session = await self.session_repo.get(id=session_id)

        if session.group_chat_id is not None:
            await self._check_insight_access(group_chat_id=session.group_chat_id)
        else:
            await self._check_insight_access(assistant_id=session.assistant.id)

        return session

    async def get_conversation_stats(
        self,
        assistant_id: Optional[UUID] = None,
        group_chat_id: Optional[UUID] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> ConversationInsightResponse:
        """
        Get statistics about conversations for either an assistant or a group chat.

        Uses optimized COUNT queries instead of fetching full session data.

        Args:
            assistant_id: UUID of the assistant (optional)
            group_chat_id: UUID of the group chat (optional)
            start_time: Start datetime to filter data (optional)
            end_time: End datetime to filter data (optional)

        Returns:
            ConversationStatsResponse with total conversations and questions

        Raises:
            BadRequestException: If neither assistant_id nor group_chat_id is provided
        """

        # check all permissions
        if not assistant_id and not group_chat_id:
            raise BadRequestException(
                "Either assistant_id or group_chat_id must be provided"
            )

        if assistant_id and group_chat_id:
            raise BadRequestException(
                "Only one of assistant_id or group_chat_id should be provided"
            )

        if assistant_id:
            await self._check_insight_access(assistant_id=assistant_id)
        elif group_chat_id:
            await self._check_insight_access(group_chat_id=group_chat_id)

        # Use default date range if not provided
        if not start_time or not end_time:
            end_time = datetime.now()
            start_time = end_time - timedelta(days=30)

        # Use optimized count queries instead of fetching full session data
        if assistant_id:
            (
                session_count,
                question_count,
            ) = await self.repo.get_assistant_conversation_counts(
                assistant_id=assistant_id,
                from_date=start_time,
                to_date=end_time,
            )
        else:
            (
                session_count,
                question_count,
            ) = await self.repo.get_group_chat_conversation_counts(
                group_chat_id=group_chat_id,
                from_date=start_time,
                to_date=end_time,
            )

        return ConversationInsightResponse(
            total_conversations=session_count,
            total_questions=question_count,
        )
