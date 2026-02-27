# MIT License
import asyncio
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from time import perf_counter
from typing import List, Optional, Tuple, cast
from uuid import UUID

from intric.analysis.analysis import (
    AnalysisProcessingMode,
    AssistantInsightQuestion,
    ConversationInsightResponse,
    Counts,
)
from intric.analysis.analysis_repo import AnalysisRepository
from intric.assistants.assistant_service import AssistantService
from intric.completion_models.infrastructure.completion_service import CompletionService
from intric.completion_models.infrastructure.static_prompts import ANALYSIS_PROMPT
from intric.group_chat.application.group_chat_service import GroupChatService
from intric.main.exceptions import (
    BadRequestException,
    NotFoundException,
    UnauthorizedException,
)
from intric.main.logging import get_logger
from intric.questions.questions_repo import QuestionRepository
from intric.roles.permissions import Permission, validate_permissions
from intric.sessions.session import SessionInDB
from intric.sessions.session import SessionMetadataPublic
from intric.sessions.session_service import SessionService
from intric.sessions.sessions_repo import SessionRepository
from intric.spaces.space_service import SpaceService
from intric.users.user import UserInDB

logger = get_logger(__name__)

MAX_DIRECT_QUESTION_COUNT = 250
MAX_DIRECT_PROMPT_CHARS = 35_000
ASYNC_AUTO_QUESTION_THRESHOLD = 600
MAP_CHUNK_MAX_QUESTIONS = 80
MAP_CHUNK_MAX_CHARS = 8_000
_CHUNK_CONCURRENCY = 4
_CHUNK_TIMEOUT_SECONDS = 60

CHUNK_SUMMARY_PROMPT = """You are summarizing assistant usage analytics.

Time window: last {days} days.
Chunk {chunk_index} of {chunk_total}.

Summarize recurring topics, intent clusters, and notable phrasing from these user questions.
Keep the summary concise and factual.

User questions:
{questions}
"""

REDUCE_SUMMARY_PROMPT = """You are answering a product analytics question using chunk summaries from many user questions.

Time window: last {days} days.

Chunk summaries:
{summaries}

Answer style requirements:
- Directly answer the question.
- Mention top themes and notable examples.
- If evidence is weak, say so.
- Keep the answer language aligned with the user's language.
"""

NO_QUESTIONS_ANSWER = (
    "No questions were found in the selected timeframe, so there is not enough data to generate insights."
)


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

    @staticmethod
    def _normalize_question_text(text: str) -> str:
        return " ".join(text.split())

    @staticmethod
    def _deduplicate_questions(questions: list[str]) -> list[str]:
        counts = Counter(questions)
        result = []
        for question, count in counts.most_common():
            if count > 1:
                result.append(f"[x{count}] {question}")
            else:
                result.append(question)
        return result

    @staticmethod
    def _encode_question_cursor(created_at: datetime, question_id: UUID) -> str:
        return f"{created_at.isoformat()}|{question_id}"

    @staticmethod
    def _decode_question_cursor(
        cursor: str | None,
    ) -> tuple[datetime | None, UUID | None]:
        if not cursor:
            return None, None

        try:
            created_at_raw, question_id_raw = cursor.split("|", 1)
        except ValueError as exc:
            raise BadRequestException("Invalid cursor format") from exc

        try:
            created_at = datetime.fromisoformat(created_at_raw)
        except ValueError as exc:
            raise BadRequestException("Invalid cursor datetime") from exc

        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)

        try:
            question_id = UUID(question_id_raw)
        except ValueError as exc:
            raise BadRequestException("Invalid cursor id") from exc

        return created_at, question_id

    def _build_question_chunks(self, questions: list[str]) -> list[list[str]]:
        chunks: list[list[str]] = []
        current_chunk: list[str] = []
        current_chars = 0

        for question in questions:
            normalized = self._normalize_question_text(question)
            if not normalized:
                continue

            would_exceed_chars = (current_chars + len(normalized)) > MAP_CHUNK_MAX_CHARS
            would_exceed_count = len(current_chunk) >= MAP_CHUNK_MAX_QUESTIONS

            if current_chunk and (would_exceed_chars or would_exceed_count):
                chunks.append(current_chunk)
                current_chunk = []
                current_chars = 0

            current_chunk.append(normalized)
            current_chars += len(normalized)

        if current_chunk:
            chunks.append(current_chunk)

        return chunks

    async def _summarize_single_chunk(
        self,
        *,
        sem: asyncio.Semaphore,
        model,
        chunk: list[str],
        index: int,
        total: int,
        days: int,
    ) -> str:
        async with sem:
            chunk_questions = "\n".join(f'- "{item}"' for item in chunk)
            prompt = CHUNK_SUMMARY_PROMPT.format(
                days=days,
                chunk_index=index,
                chunk_total=total,
                questions=chunk_questions,
            )
            summary_response = await asyncio.wait_for(
                model.get_response(
                    question="Summarize these usage questions",
                    completion_service=self.completion_service,
                    prompt=prompt,
                    stream=False,
                ),
                timeout=_CHUNK_TIMEOUT_SECONDS,
            )
            return (summary_response.completion.text or "").strip()

    async def _summarize_question_chunks(
        self,
        *,
        model,
        questions: list[str],
        days: int,
    ) -> list[str]:
        chunks = self._build_question_chunks(questions)
        sem = asyncio.Semaphore(_CHUNK_CONCURRENCY)

        results = await asyncio.gather(
            *(
                self._summarize_single_chunk(
                    sem=sem,
                    model=model,
                    chunk=chunk,
                    index=i,
                    total=len(chunks),
                    days=days,
                )
                for i, chunk in enumerate(chunks, start=1)
            ),
            return_exceptions=True,
        )

        summaries: list[str] = []
        for i, result in enumerate(results):
            if isinstance(result, BaseException):
                logger.warning(
                    "analysis_chunk_failed",
                    extra={"chunk_index": i + 1, "error": str(result)},
                )
            elif result:
                summaries.append(result)

        return summaries

    async def _answer_with_adaptive_budget(
        self,
        *,
        model,
        question: str,
        from_date: datetime,
        to_date: datetime,
        question_texts: list[str],
        stream: bool,
    ):
        from intric.ai_models.completion_models.completion_model import (
            Completion,
            CompletionModelResponse,
        )

        started = perf_counter()
        cleaned_questions = [
            self._normalize_question_text(item) for item in question_texts if item and item.strip()
        ]

        if not cleaned_questions:
            no_data_completion = Completion(text=NO_QUESTIONS_ANSWER, stop=True)
            if stream:
                async def _no_data_stream():
                    yield no_data_completion

                response = CompletionModelResponse(
                    completion=_no_data_stream(),
                    model=model.completion_model,
                    total_token_count=0,
                )
            else:
                response = CompletionModelResponse(
                    completion=no_data_completion,
                    model=model.completion_model,
                    total_token_count=0,
                )
            logger.info(
                "analysis_pipeline_summary",
                extra={
                    "mode": "no_data",
                    "question_count": 0,
                    "unique_count": 0,
                    "chunk_count": 0,
                    "llm_calls": 0,
                    "prompt_chars": 0,
                    "duration_ms": round((perf_counter() - started) * 1000, 2),
                },
            )
            return response

        deduped_questions = self._deduplicate_questions(cleaned_questions)
        days = max((to_date - from_date).days, 1)

        direct_questions = deduped_questions[:MAX_DIRECT_QUESTION_COUNT]
        direct_text = "\n".join(f'"""{item}"""' for item in direct_questions)
        direct_prompt = f"{ANALYSIS_PROMPT.format(days=days)}\n\n{direct_text}"

        if (
            len(deduped_questions) <= MAX_DIRECT_QUESTION_COUNT
            and len(direct_prompt) <= MAX_DIRECT_PROMPT_CHARS
        ):
            result = await model.get_response(
                question=question,
                completion_service=self.completion_service,
                prompt=direct_prompt,
                stream=stream,
            )
            logger.info(
                "analysis_pipeline_summary",
                extra={
                    "mode": "direct",
                    "question_count": len(cleaned_questions),
                    "unique_count": len(deduped_questions),
                    "chunk_count": 0,
                    "llm_calls": 1,
                    "prompt_chars": len(direct_prompt),
                    "duration_ms": round((perf_counter() - started) * 1000, 2),
                },
            )
            return result

        chunks = self._build_question_chunks(deduped_questions)
        summaries = await self._summarize_question_chunks(
            model=model,
            questions=deduped_questions,
            days=days,
        )

        if not summaries:
            summaries = [
                "Unable to summarize questions due to processing errors. "
                "Please try again or narrow the timeframe."
            ]

        summaries_text = "\n\n".join(
            f"Summary {idx + 1}:\n{summary}" for idx, summary in enumerate(summaries)
        )
        reduce_prompt = REDUCE_SUMMARY_PROMPT.format(days=days, summaries=summaries_text)

        result = await model.get_response(
            question=question,
            completion_service=self.completion_service,
            prompt=reduce_prompt,
            stream=stream,
        )
        logger.info(
            "analysis_pipeline_summary",
            extra={
                "mode": "map_reduce",
                "question_count": len(cleaned_questions),
                "unique_count": len(deduped_questions),
                "chunk_count": len(chunks),
                "llm_calls": len(chunks) + 1,
                "prompt_chars": len(reduce_prompt),
                "duration_ms": round((perf_counter() - started) * 1000, 2),
            },
        )
        return result

    async def _get_question_texts_for_unified_analysis(
        self,
        *,
        assistant_id: UUID | None,
        group_chat_id: UUID | None,
        from_date: datetime,
        to_date: datetime,
        include_followup: bool,
    ) -> tuple[object, list[str]]:
        if assistant_id:
            await self._check_insight_access(assistant_id=assistant_id)
            assistant, _ = await self.assistant_service.get_assistant(assistant_id)
            rows = await self.repo.get_assistant_question_texts_since(
                assistant_id=assistant_id,
                from_date=from_date,
                to_date=to_date,
                include_followups=include_followup,
                tenant_id=self.user.tenant_id,
            )
            return assistant, [row.question for row in rows]

        await self._check_insight_access(group_chat_id=group_chat_id)
        space = await self.space_service.get_space_by_group_chat(group_chat_id=group_chat_id)
        group_chat = space.get_group_chat(group_chat_id=group_chat_id)

        if not group_chat.assistants:
            raise BadRequestException(
                "Group chat has no assistants to process the analysis"
            )

        model_to_use = group_chat.assistants[0].assistant
        rows = await self.repo.get_group_chat_question_texts_since(
            group_chat_id=group_chat_id,
            from_date=from_date,
            to_date=to_date,
            include_followups=include_followup,
            tenant_id=self.user.tenant_id,
        )
        return model_to_use, [row.question for row in rows]

    async def should_queue_unified_analysis_job(
        self,
        *,
        assistant_id: UUID | None,
        group_chat_id: UUID | None,
        from_date: datetime,
        to_date: datetime,
        mode: AnalysisProcessingMode,
    ) -> bool:
        if mode != AnalysisProcessingMode.AUTO:
            return False

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
            question_count = await self.repo.count_assistant_questions_since(
                assistant_id=assistant_id,
                from_date=from_date,
                to_date=to_date,
                tenant_id=self.user.tenant_id,
            )
        else:
            await self._check_insight_access(group_chat_id=group_chat_id)
            question_count = await self.repo.count_group_chat_questions_since(
                group_chat_id=group_chat_id,
                from_date=from_date,
                to_date=to_date,
                tenant_id=self.user.tenant_id,
            )

        return question_count > ASYNC_AUTO_QUESTION_THRESHOLD

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

    @validate_permissions(Permission.INSIGHTS)
    async def get_assistant_activity_stats(
        self, start_date: datetime, end_date: datetime
    ):
        """Get assistant activity statistics for the tenant.

        Returns counts of active assistants, trackable assistants, and active users.
        """
        from intric.analysis.analysis import AssistantActivityStats

        active_count = await self.repo.get_active_assistant_count_for_tenant(
            tenant_id=self.user.tenant_id,
            start_date=start_date,
            end_date=end_date,
        )
        trackable_count = await self.repo.get_trackable_assistant_count_for_tenant(
            tenant_id=self.user.tenant_id,
        )
        active_users = await self.repo.get_active_user_count_for_tenant(
            tenant_id=self.user.tenant_id,
            start_date=start_date,
            end_date=end_date,
        )

        # Calculate percentage, handling division by zero
        active_pct = (
            round((active_count / trackable_count) * 100, 1)
            if trackable_count > 0
            else 0.0
        )

        return AssistantActivityStats(
            active_assistant_count=active_count,
            total_trackable_assistants=trackable_count,
            active_assistant_pct=active_pct,
            active_user_count=active_users,
        )

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
            tenant_id=self.user.tenant_id,
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
            tenant_id=self.user.tenant_id,
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
        if assistant.space_id is not None:
            await self._check_space_permissions(assistant.space_id)
        rows = await self.repo.get_assistant_question_texts_since(
            assistant_id=assistant_id,
            from_date=from_date,
            to_date=to_date,
            include_followups=include_followup,
            tenant_id=self.user.tenant_id,
        )
        return await self._answer_with_adaptive_budget(
            model=assistant,
            question=question,
            from_date=from_date,
            to_date=to_date,
            question_texts=[row.question for row in rows],
            stream=stream,
        )

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

        started = perf_counter()
        model_to_use, question_texts = await self._get_question_texts_for_unified_analysis(
            assistant_id=assistant_id,
            group_chat_id=group_chat_id,
            from_date=from_date,
            to_date=to_date,
            include_followup=include_followup,
        )
        response = await self._answer_with_adaptive_budget(
            model=model_to_use,
            question=question,
            from_date=from_date,
            to_date=to_date,
            question_texts=question_texts,
            stream=stream,
        )
        logger.info(
            "analysis_ask_completed",
            extra={
                "duration_ms": round((perf_counter() - started) * 1000, 2),
                "tenant_id": str(self.user.tenant_id),
                "assistant_id": str(assistant_id) if assistant_id else None,
                "group_chat_id": str(group_chat_id) if group_chat_id else None,
                "question_count": len(question_texts),
                "stream": stream,
            },
        )
        return response

    async def get_assistant_question_history_page(
        self,
        *,
        assistant_id: UUID,
        from_date: datetime,
        to_date: datetime,
        include_followups: bool,
        limit: int,
        query: str | None = None,
        cursor: str | None = None,
    ) -> tuple[list[AssistantInsightQuestion], int, str | None]:
        assistant, _ = await self.assistant_service.get_assistant(assistant_id)
        if assistant.space_id is not None:
            await self._check_space_permissions(assistant.space_id)

        cursor_created_at, cursor_id = self._decode_question_cursor(cursor)
        started = perf_counter()
        rows, total_count, has_more = await self.repo.get_assistant_question_history_page(
            assistant_id=assistant_id,
            from_date=from_date,
            to_date=to_date,
            include_followups=include_followups,
            tenant_id=self.user.tenant_id,
            limit=limit,
            query=query,
            cursor_created_at=cursor_created_at,
            cursor_id=cursor_id,
        )

        next_cursor: str | None = None
        if has_more and rows:
            last_row = rows[-1]
            next_cursor = self._encode_question_cursor(
                created_at=last_row.created_at,
                question_id=last_row.id,
            )

        logger.info(
            "analysis_question_history_page_loaded",
            extra={
                "duration_ms": round((perf_counter() - started) * 1000, 2),
                "tenant_id": str(self.user.tenant_id),
                "assistant_id": str(assistant_id),
                "returned_count": len(rows),
                "total_count": total_count,
                "has_more": has_more,
            },
        )

        return (
            [
                AssistantInsightQuestion(
                    id=row.id,
                    question=row.question,
                    created_at=row.created_at,
                    session_id=row.session_id,
                )
                for row in rows
            ],
            total_count,
            next_cursor,
        )

    async def get_assistant_insight_sessions(
        self,
        assistant_id: UUID,
        limit: int = None,
        cursor: datetime = None,
        previous: bool = False,
        name_filter: str = None,
        start_date: datetime = None,
        end_date: datetime = None,
    ) -> Tuple[List[SessionMetadataPublic], int]:
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

        sessions, total = await self.session_repo.get_metadata_by_assistant(
            assistant_id=assistant_id,
            limit=limit,
            cursor=cursor,
            previous=previous,
            name_filter=name_filter,
            start_date=start_date,
            end_date=end_date,
            tenant_id=self.user.tenant_id,
        )
        return cast(List[SessionMetadataPublic], sessions), int(total or 0)

    async def get_group_chat_insight_sessions(
        self,
        group_chat_id: UUID,
        limit: int = None,
        cursor: datetime = None,
        previous: bool = False,
        name_filter: str = None,
        start_date: datetime = None,
        end_date: datetime = None,
    ) -> Tuple[List[SessionMetadataPublic], int]:
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

        sessions, total = await self.session_repo.get_metadata_by_group_chat(
            group_chat_id=group_chat_id,
            limit=limit,
            cursor=cursor,
            previous=previous,
            name_filter=name_filter,
            start_date=start_date,
            end_date=end_date,
            tenant_id=self.user.tenant_id,
        )
        return cast(List[SessionMetadataPublic], sessions), int(total or 0)

    async def get_insight_session(
        self,
        session_id: UUID,
    ) -> SessionInDB:
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
            if session.assistant is None:
                raise NotFoundException("Session assistant not found")
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
        if start_time is None:
            start_time = datetime.now(timezone.utc) - timedelta(days=30)
        if end_time is None:
            end_time = datetime.now(timezone.utc)

        started = perf_counter()
        # Use optimized count queries instead of fetching full session data
        if assistant_id:
            (
                session_count,
                question_count,
            ) = await self.repo.get_assistant_conversation_counts(
                assistant_id=assistant_id,
                from_date=start_time,
                to_date=end_time,
                tenant_id=self.user.tenant_id,
            )
        else:
            (
                session_count,
                question_count,
            ) = await self.repo.get_group_chat_conversation_counts(
                group_chat_id=group_chat_id,
                from_date=start_time,
                to_date=end_time,
                tenant_id=self.user.tenant_id,
            )

        logger.info(
            "analysis_conversation_stats_loaded",
            extra={
                "duration_ms": round((perf_counter() - started) * 1000, 2),
                "tenant_id": str(self.user.tenant_id),
                "assistant_id": str(assistant_id) if assistant_id else None,
                "group_chat_id": str(group_chat_id) if group_chat_id else None,
                "total_conversations": session_count,
                "total_questions": question_count,
            },
        )

        return ConversationInsightResponse(
            total_conversations=session_count,
            total_questions=question_count,
        )

    async def generate_unified_analysis_answer(
        self,
        *,
        question: str,
        assistant_id: UUID | None,
        group_chat_id: UUID | None,
        from_date: datetime,
        to_date: datetime,
        include_followup: bool,
    ) -> str:
        response = await self.unified_ask_question_on_questions(
            question=question,
            stream=False,
            from_date=from_date,
            to_date=to_date,
            include_followup=include_followup,
            assistant_id=assistant_id,
            group_chat_id=group_chat_id,
        )
        return response.completion.text or ""
