"""Application service for the insights analysis chat.

One insights conversation is a persisted chat an operator has with the model
about how a target assistant or group chat is used. Each turn attaches the
loopback insights MCP server (scoped by a short-lived token to that one
target) so the model answers from live tool calls over the target's
conversations rather than from a prompt stuffed with question texts.

Deliberately its own service rather than an "insight mode" inside
``AssistantService.ask``: that path checks *use* rights and carries skills,
governance and capability plumbing that has no meaning here. Authorisation
is the target's insight-view right (``AnalysisService.assert_insight_access``)
plus the personal-space rule, re-checked on every turn and again inside every
tool call.

Persistence borrows the regular chat's placeholder/complete helpers so the
wire format and history rows are identical to ``/conversations/``. The
``insight_conversations`` link row is written in the same transaction as the
session and placeholder, which is what keeps the session out of every normal
listing from the very first commit.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING, cast
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from eneo.ai_models.completion_models.completion_model import (
    Completion,
    CompletionModelResponse,
    ResponseType,
    TokenUsage,
    ToolCallMetadata,
)
from eneo.analysis.insight_chat_prompt import build_insights_system_prompt
from eneo.analysis.insight_conversation_repo import (
    InsightConversation,
    InsightConversationRepository,
)
from eneo.analysis.insight_exceptions import (
    InsightsModelUnavailableError,
    InvalidTimezoneError,
)
from eneo.analysis.insight_scope import InsightTargetKind
from eneo.assistants.assistant import Assistant
from eneo.internal_mcp.insights import build_insights_mcp_server, target_label
from eneo.main.datetime_utils import datetime_or_utc_min
from eneo.main.exceptions import (
    BadRequestException,
    NotFoundException,
    UnauthorizedException,
)
from eneo.main.logging import get_logger
from eneo.questions.question import ToolCallInfo
from eneo.sessions.session import SessionInDB, SessionMetadataPublic
from eneo.sessions.session_service import (
    persist_partial_question_answer,
    safe_count_tokens,
    schedule_background_save,
)
from eneo.users.user import UserInDB

if TYPE_CHECKING:
    from eneo.ai_models.completion_models.completion_model import (
        CompletionModel as AICompletionModel,
    )
    from eneo.analysis.analysis_service import AnalysisService
    from eneo.authentication.auth_service import AuthService
    from eneo.completion_models.domain.completion_model import CompletionModel
    from eneo.completion_models.infrastructure.completion_service import (
        CompletionService,
    )
    from eneo.database.database import AsyncSession
    from eneo.group_chat.domain.entities.group_chat import GroupChat
    from eneo.sessions.session_service import SessionService
    from eneo.sessions.sessions_repo import SessionRepository
    from eneo.spaces.space import Space

logger = get_logger(__name__)

# Lifetime of the loopback token for one turn. Longer than the knowledge
# token's default because an analysis turn may page through many tool calls.
INSIGHT_TOKEN_MINUTES = 30

# Chunk types the conversation SSE protocol renders. Anything else (e.g. the
# adapter's trailing usage-only chunk with no response type) is consumed for
# its token counts but never forwarded: the protocol would render it as an
# ``error`` event and the client would mark a finished turn as failed.
_FORWARDED_RESPONSE_TYPES = frozenset(
    {
        ResponseType.TEXT,
        ResponseType.REASONING,
        ResponseType.TOOL_CALL,
        ResponseType.TOOL_APPROVAL_REQUIRED,
        ResponseType.TOOL_APPROVAL_TIMEOUT,
        ResponseType.FILES,
        ResponseType.ENEO_EVENT,
        ResponseType.ERROR,
    }
)


@dataclass
class InsightTurn:
    """Result of one insights chat turn, for the router to render."""

    session: SessionInDB
    question: str
    question_id: UUID
    created_at: datetime | None
    completion_model: "CompletionModel"
    answer: str | AsyncGenerator[Completion, None]
    target_name: str
    space_id: UUID | None


def _tool_call_info(tc: ToolCallMetadata, **overrides: object) -> ToolCallInfo:
    fields: dict[str, object] = dict(
        server_name=tc.server_name,
        tool_name=tc.tool_name,
        title=tc.title,
        arguments=tc.arguments,
        tool_call_id=tc.tool_call_id,
        approved=tc.approved,
        result_status=tc.result_status,
        result=tc.result,
        mcp_tool_name=tc.mcp_tool_name,
        meta=getattr(tc, "meta", None),
    )
    fields.update(overrides)
    return ToolCallInfo(**fields)  # type: ignore[arg-type]


def merge_tool_call_chunk(tool_calls: list[ToolCallInfo], chunk: Completion) -> None:
    """Fold a tool-call stream chunk into the turn's persisted tool calls.

    A call is announced while its arguments are still streaming ("pending"),
    then again once executed with the result; approval chunks update the
    same entry. Matching on ``tool_call_id`` keeps one row per call, and a
    later chunk only overwrites fields it actually carries so a pending
    entry's arguments are filled in rather than blanked.
    """
    for tc in chunk.tool_calls_metadata or []:
        existing = next(
            (
                t
                for t in tool_calls
                if t.tool_call_id and t.tool_call_id == tc.tool_call_id
            ),
            None,
        )
        if chunk.response_type == ResponseType.TOOL_APPROVAL_TIMEOUT:
            approved: bool | None = False
            result_status = tc.result_status or "timeout_denied"
        elif chunk.response_type == ResponseType.TOOL_APPROVAL_REQUIRED:
            approved = None
            result_status = tc.result_status
        else:
            approved = tc.approved
            result_status = tc.result_status

        if existing is None:
            tool_calls.append(
                _tool_call_info(tc, approved=approved, result_status=result_status)
            )
            continue
        existing.approved = approved
        existing.result_status = result_status
        if tc.arguments is not None:
            existing.arguments = cast(dict[str, object] | None, tc.arguments)
        if tc.result is not None:
            existing.result = tc.result
        meta = getattr(tc, "meta", None)
        if meta is not None:
            existing.meta = meta


class InsightConversationService:
    def __init__(
        self,
        user: UserInDB,
        analysis_service: "AnalysisService",
        session_service: "SessionService",
        completion_service: "CompletionService",
        auth_service: "AuthService",
        session_repo: "SessionRepository",
        insight_conversation_repo: InsightConversationRepository,
    ) -> None:
        self.user = user
        self.analysis_service = analysis_service
        self.session_service = session_service
        self.completion_service = completion_service
        self.auth_service = auth_service
        self.session_repo = session_repo
        self.insight_conversation_repo = insight_conversation_repo

    async def start(
        self,
        *,
        assistant_id: UUID | None,
        group_chat_id: UUID | None,
        question: str,
        timezone: str,
        stream: bool,
        selected_range: tuple[date, date] | None,
    ) -> InsightTurn:
        """Start a new insights conversation with its first turn."""
        if (assistant_id is None) == (group_chat_id is None):
            raise BadRequestException(
                "Provide exactly one of assistant_id or group_chat_id"
            )
        zone = self._parse_timezone(timezone)
        target, space = await self.analysis_service.assert_insight_access(
            assistant_id=assistant_id, group_chat_id=group_chat_id
        )
        await self.analysis_service.check_space_permissions(space.id)
        model = self._resolve_model(target, space)

        kind: InsightTargetKind = (
            "assistant" if assistant_id is not None else "group_chat"
        )
        target_id = cast(
            UUID, assistant_id if assistant_id is not None else group_chat_id
        )

        async def link_conversation(db_session: "AsyncSession", session: SessionInDB):
            await InsightConversationRepository(db_session).add(
                tenant_id=self.user.tenant_id,
                session_id=session.id,
                actor_user_id=self.user.id,
                timezone=timezone,
                assistant_id=assistant_id,
                group_chat_id=group_chat_id,
                completion_model_id=model.id,
            )

        (
            session,
            question_id,
            created_at,
        ) = await self.session_service.create_session_with_question_placeholder(
            name=question,
            question=question,
            session_assistant_id=assistant_id,
            question_assistant_id=assistant_id,
            group_chat_id=group_chat_id,
            completion_model=cast("AICompletionModel", model),
            on_created=link_conversation,
        )

        answer = await self._run_turn(
            session=session,
            question=question,
            question_id=question_id,
            model=model,
            kind=kind,
            target_id=target_id,
            target_name=target.name,
            timezone=timezone,
            zone=zone,
            selected_range=selected_range,
            stream=stream,
        )
        logger.info(
            "insight_conversation_started",
            extra={
                "session_id": str(session.id),
                "target_kind": kind,
                "target_id": str(target_id),
                "completion_model_id": str(model.id),
                "stream": stream,
            },
        )
        return InsightTurn(
            session=session,
            question=question,
            question_id=question_id,
            created_at=created_at,
            completion_model=model,
            answer=answer,
            target_name=target.name,
            space_id=space.id,
        )

    async def continue_turn(
        self,
        *,
        session_id: UUID,
        question: str,
        stream: bool,
        selected_range: tuple[date, date] | None,
    ) -> InsightTurn:
        """Append a follow-up turn to one of the operator's own conversations.

        Access and model resolution are re-run every turn: insights may have
        been disabled for the target, or its model replaced, since the
        conversation started. Prior turns replay through the session's
        history, tool calls included.
        """
        link = await self._own_conversation(session_id)
        target, space = await self.analysis_service.assert_insight_access(
            assistant_id=link.assistant_id, group_chat_id=link.group_chat_id
        )
        await self.analysis_service.check_space_permissions(space.id)
        model = self._resolve_model(target, space)
        zone = self._parse_timezone(link.timezone)

        session = await self.session_repo.get_for_insight_conversation(
            session_id, self.user.tenant_id
        )
        if session is None:
            raise NotFoundException("Insights conversation not found.")

        (
            question_id,
            created_at,
        ) = await self.session_service.create_question_placeholder(
            question=question,
            session=session,
            assistant_id=link.assistant_id,
            completion_model=cast("AICompletionModel", model),
        )
        answer = await self._run_turn(
            session=session,
            question=question,
            question_id=question_id,
            model=model,
            kind=link.target_kind,
            target_id=link.target_id,
            target_name=target.name,
            timezone=link.timezone,
            zone=zone,
            selected_range=selected_range,
            stream=stream,
        )
        return InsightTurn(
            session=session,
            question=question,
            question_id=question_id,
            created_at=created_at,
            completion_model=model,
            answer=answer,
            target_name=target.name,
            space_id=space.id,
        )

    async def list_conversations(
        self,
        *,
        assistant_id: UUID | None,
        group_chat_id: UUID | None,
        limit: int,
        cursor: datetime | None,
    ) -> tuple[list[SessionMetadataPublic], int, datetime | None]:
        """The operator's own conversations about the target, newest first."""
        if (assistant_id is None) == (group_chat_id is None):
            raise BadRequestException(
                "Provide exactly one of assistant_id or group_chat_id"
            )
        await self.analysis_service.assert_insight_access(
            assistant_id=assistant_id, group_chat_id=group_chat_id
        )
        return await self.insight_conversation_repo.list_for_actor(
            tenant_id=self.user.tenant_id,
            actor_user_id=self.user.id,
            assistant_id=assistant_id,
            group_chat_id=group_chat_id,
            limit=limit,
            cursor=cursor,
        )

    async def get_conversation(self, session_id: UUID) -> SessionInDB:
        link = await self._own_conversation(session_id)
        await self.analysis_service.assert_insight_access(
            assistant_id=link.assistant_id, group_chat_id=link.group_chat_id
        )
        session = await self.session_repo.get_for_insight_conversation(
            session_id, self.user.tenant_id
        )
        if session is None:
            raise NotFoundException("Insights conversation not found.")
        return session

    async def delete_conversation(self, session_id: UUID) -> InsightConversation:
        """Delete one of the operator's own conversations; the link row
        cascades with the session. Returns the link for the audit entry."""
        link = await self._own_conversation(session_id)
        deleted = await self.session_repo.delete(session_id)
        if deleted is None:
            raise NotFoundException("Insights conversation not found.")
        return link

    async def _own_conversation(self, session_id: UUID) -> InsightConversation:
        """The link row, provided the caller is the operator who started it."""
        link = await self.insight_conversation_repo.get_by_session_id(
            session_id, self.user.tenant_id
        )
        if link is None:
            raise NotFoundException("Insights conversation not found.")
        if link.actor_user_id != self.user.id:
            raise UnauthorizedException(
                "You do not have access to this insights conversation.",
                code="forbidden_action",
            )
        return link

    async def _run_turn(
        self,
        *,
        session: SessionInDB,
        question: str,
        question_id: UUID,
        model: "CompletionModel",
        kind: InsightTargetKind,
        target_id: UUID,
        target_name: str,
        timezone: str,
        zone: ZoneInfo,
        selected_range: tuple[date, date] | None,
        stream: bool,
    ) -> str | AsyncGenerator[Completion, None]:
        token = self.auth_service.create_scoped_mcp_token(
            self.user,
            insight_target=(kind, target_id),
            expires_in=INSIGHT_TOKEN_MINUTES,
        )
        server = await build_insights_mcp_server(
            token=token,
            tenant_id=self.user.tenant_id,
            target_label=target_label(kind, target_name),
        )
        prompt = build_insights_system_prompt(
            now=datetime.now(zone),
            timezone=timezone,
            target_kind=kind,
            target_name=target_name,
            selected_range=selected_range,
        )
        response = await self.completion_service.get_response(
            model=cast("AICompletionModel", model),
            text_input=question,
            prompt=prompt,
            session=session,
            stream=stream,
            # Never extended logging: the analysis is not user content.
            extended_logging=False,
            mcp_servers=[server],
            require_tool_approval=False,
            version=2,
        )
        if stream:
            return self._stream_and_persist(
                response=response, question_id=question_id, model=model
            )
        return await self._persist_answer(
            response=response, question_id=question_id, model=model
        )

    @staticmethod
    def _parse_timezone(timezone: str) -> ZoneInfo:
        try:
            return ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError, TypeError):
            raise InvalidTimezoneError(timezone)

    @staticmethod
    def _resolve_model(
        target: "Assistant | GroupChat", space: "Space"
    ) -> "CompletionModel":
        """Pick the model that answers: it must be accessible and call tools.

        Order: the assistant's own model when it qualifies and is in the
        space (group chats skip this), then the space default, then the
        newest tool-capable model in the space.
        """

        def qualifies(model: "CompletionModel | None") -> bool:
            return (
                model is not None
                and model.can_access
                and bool(model.supports_tool_calling)
            )

        if isinstance(target, Assistant):
            own = target.completion_model
            if qualifies(own) and space.is_completion_model_in_space(
                cast("CompletionModel", own).id
            ):
                return cast("CompletionModel", own)

        try:
            default = space.get_default_completion_model()
        except BadRequestException:
            default = None
        if qualifies(default):
            return cast("CompletionModel", default)

        candidates = [m for m in space.completion_models if qualifies(m)]
        if candidates:
            return max(candidates, key=lambda m: datetime_or_utc_min(m.created_at))
        raise InsightsModelUnavailableError()

    async def _persist_answer(
        self,
        *,
        response: CompletionModelResponse,
        question_id: UUID,
        model: "CompletionModel",
    ) -> str:
        completion = response.completion
        tool_calls: list[ToolCallInfo] = []
        reasoning: str | None = None
        if isinstance(completion, str):
            answer = completion
        elif completion is None:
            answer = ""
        else:
            answer = getattr(completion, "text", "") or ""
            reasoning = getattr(completion, "reasoning_content", None) or None
            metadata = cast(
                list[ToolCallMetadata],
                getattr(completion, "tool_calls_metadata", None) or [],
            )
            tool_calls = [_tool_call_info(tc) for tc in metadata]

        usage = response.usage
        num_tokens_question = (
            usage.prompt_tokens
            if usage is not None and usage.prompt_tokens is not None
            else response.total_token_count
        )
        num_tokens_answer = (
            usage.completion_tokens
            if usage is not None and usage.completion_tokens is not None
            else safe_count_tokens(answer, model.name)
        )
        await self.session_service.complete_question_with_answer(
            question_id=question_id,
            answer=answer,
            num_tokens_question=num_tokens_question,
            num_tokens_answer=num_tokens_answer,
            completion_model=cast("AICompletionModel", model),
            info_blob_chunks=[],
            tool_calls=tool_calls or None,
            reasoning=reasoning,
        )
        return answer

    async def _stream_and_persist(
        self,
        *,
        response: CompletionModelResponse,
        question_id: UUID,
        model: "CompletionModel",
    ) -> AsyncGenerator[Completion, None]:
        """Yield stream chunks and complete the placeholder row at the end.

        Tool calls are accumulated so later turns can replay them. If the
        stream does not reach normal completion (client abort, provider
        error), whatever text or reasoning already streamed is saved through
        a fresh DB session, since the request-scoped one may be gone.
        """
        completion = response.completion
        if isinstance(completion, str) or completion is None:
            return

        answer = ""
        reasoning = ""
        tool_calls: list[ToolCallInfo] = []
        stream_usage: TokenUsage | None = None
        input_estimate: int | None = None
        output_estimate: int | None = None
        completed = False
        try:
            async for chunk in completion:
                if chunk.usage is not None:
                    stream_usage = chunk.usage
                if chunk.input_token_estimate is not None:
                    input_estimate = chunk.input_token_estimate
                if chunk.output_token_estimate is not None:
                    output_estimate = chunk.output_token_estimate
                if chunk.response_type == ResponseType.TEXT and chunk.text:
                    answer = f"{answer}{chunk.text}"
                elif chunk.response_type == ResponseType.REASONING:
                    reasoning = f"{reasoning}{chunk.reasoning_content or ''}"
                elif chunk.response_type in (
                    ResponseType.TOOL_CALL,
                    ResponseType.TOOL_APPROVAL_REQUIRED,
                    ResponseType.TOOL_APPROVAL_TIMEOUT,
                ):
                    merge_tool_call_chunk(tool_calls, chunk)
                if chunk.response_type in _FORWARDED_RESPONSE_TYPES:
                    yield chunk

            num_tokens_question = (
                stream_usage.prompt_tokens
                if stream_usage is not None and stream_usage.prompt_tokens is not None
                else input_estimate
                if input_estimate is not None
                else response.total_token_count
            )
            num_tokens_answer = (
                stream_usage.completion_tokens
                if stream_usage is not None
                and stream_usage.completion_tokens is not None
                else output_estimate
                if output_estimate is not None
                else safe_count_tokens(answer, model.name)
            )
            await self.session_service.complete_question_with_answer(
                question_id=question_id,
                answer=answer,
                num_tokens_question=num_tokens_question,
                num_tokens_answer=num_tokens_answer,
                completion_model=cast("AICompletionModel", model),
                info_blob_chunks=[],
                tool_calls=tool_calls or None,
                reasoning=reasoning or None,
            )
            completed = True
            yield Completion(
                text="",
                response_type=ResponseType.TOKEN_USAGE,
                usage=TokenUsage(
                    prompt_tokens=num_tokens_question,
                    completion_tokens=num_tokens_answer,
                    context_prompt_tokens=num_tokens_question,
                    context_completion_tokens=num_tokens_answer,
                ),
            )
        finally:
            if not completed and (answer or reasoning):
                schedule_background_save(
                    persist_partial_question_answer(
                        tenant_id=self.user.tenant_id,
                        question_id=question_id,
                        answer=answer,
                        num_tokens_answer=safe_count_tokens(answer, model.name),
                        completion_model_id=model.id,
                        reasoning=reasoning or None,
                    )
                )
                logger.info(
                    "Scheduled partial insight answer save on stream abort",
                    extra={
                        "question_id": str(question_id),
                        "answer_chars": len(answer),
                    },
                )
