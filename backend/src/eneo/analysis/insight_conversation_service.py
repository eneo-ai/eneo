"""Application service for the insights analysis chat.

One insights conversation is a persisted chat an operator has with a model
about how a target assistant or group chat is used. Each turn attaches the
loopback insights MCP server (scoped by a short-lived token to that one
target and to this conversation) so the model answers from live tool calls
over the target's conversations rather than from a prompt stuffed with
question texts.

Deliberately its own service rather than an "insight mode" inside
``AssistantService.ask``: that path checks *use* rights and carries skills,
governance and capability plumbing that has no meaning here. Authorisation
is the target's insight-view decision (``AnalysisService.assert_insight_access``),
asked on every turn and every read here and again inside every tool call.

Persistence borrows the regular chat's placeholder and completion helpers,
so the history rows are those of ``/conversations/`` and the answer streams
as the chat's version 3 UI Message Stream. The ``insight_conversations``
link row is written in the same transaction as the session and its first
question, which keeps the session out of every normal listing from its
first commit.

An analysis holds text the tools copied from other conversations, and the
tools record those as its sources. Once one of them is removed, every read
here refuses the analysis with ``DerivedSourceRemovedError`` (after the
caller's ownership and access were checked), the history list leaves it
out, and the derived copies task removes it.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterable
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
    InsightConversationPage,
    InsightConversationRepository,
)
from eneo.analysis.insight_exceptions import (
    InsightsModelUnavailableError,
    InvalidTimezoneError,
)
from eneo.analysis.insight_scope import InsightTargetKind
from eneo.assistants.assistant import Assistant
from eneo.data_retention.derivations import DerivedSourceRemovedError
from eneo.internal_mcp.insights import build_insights_mcp_server, target_label
from eneo.main.exceptions import (
    BadRequestException,
    NotFoundException,
    UnauthorizedException,
)
from eneo.main.logging import get_logger
from eneo.main.stream_lifecycle import (
    OwnedAsyncGenerator,
    aclose_if_possible,
    finalizing,
)
from eneo.questions.question import ToolCallInfo
from eneo.sessions.session import SessionInDB
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

# Chunk types the version 3 stream renders. Anything else (the adapter's
# trailing usage-only chunk without a response type) is read for its token
# counts but not passed on.
_FORWARDED_RESPONSE_TYPES = frozenset(
    {
        ResponseType.TEXT,
        ResponseType.REASONING,
        ResponseType.TOOL_CALL,
        ResponseType.TOOL_CALL_DELTA,
        ResponseType.TOOL_APPROVAL_REQUIRED,
        ResponseType.TOOL_APPROVAL_TIMEOUT,
        ResponseType.FILES,
        ResponseType.ERROR,
    }
)

_TOOL_CALL_RESPONSE_TYPES = frozenset(
    {
        ResponseType.TOOL_CALL,
        ResponseType.TOOL_APPROVAL_REQUIRED,
        ResponseType.TOOL_APPROVAL_TIMEOUT,
    }
)


@dataclass
class InsightTurn:
    """One insights chat turn, for the router to stream."""

    session: SessionInDB
    question: str
    question_id: UUID
    created_at: datetime | None
    completion_model: "CompletionModel"
    answer: AsyncGenerator[Completion, None]
    target_name: str
    space_id: UUID | None


def _tool_call_info(tc: ToolCallMetadata) -> ToolCallInfo:
    return ToolCallInfo(
        server_name=tc.server_name,
        tool_name=tc.tool_name,
        title=tc.title,
        arguments=tc.arguments,
        tool_call_id=tc.tool_call_id,
        approved=tc.approved,
        result_status=tc.result_status,
        result=tc.result,
        mcp_tool_name=tc.mcp_tool_name,
        purpose=tc.purpose,
        is_internal=tc.is_internal,
        is_bundled=tc.is_bundled,
        meta=tc.meta,
        structured_content=tc.structured_content,
        app_view=tc.app_view,
    )


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
            call = _tool_call_info(tc)
            call.approved = approved
            call.result_status = result_status
            tool_calls.append(call)
            continue
        existing.approved = approved
        existing.result_status = result_status
        if tc.arguments is not None:
            existing.arguments = tc.arguments
        if tc.result is not None:
            existing.result = tc.result
        if tc.meta is not None:
            existing.meta = tc.meta
        if tc.structured_content is not None:
            existing.structured_content = tc.structured_content
        if tc.app_view is not None:
            existing.app_view = tc.app_view
        if tc.purpose is not None:
            existing.purpose = tc.purpose


def finished_tool_calls(tool_calls: list[ToolCallInfo]) -> list[ToolCallInfo]:
    """The calls a stopped turn keeps, as the chat does: those that ran (they
    have their result) or were refused. One still being written or run is
    left out, so a reopened turn never shows it as done or failed."""
    return [tc for tc in tool_calls if tc.result is not None or tc.approved is False]


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
        )
        logger.info(
            "insight_conversation_started",
            extra={
                "session_id": str(session.id),
                "target_kind": kind,
                "target_id": str(target_id),
                "completion_model_id": str(model.id),
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
        model = self._resolve_model(target, space)
        zone = self._parse_timezone(link.timezone)
        session = await self._load_session(session_id)

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
        cursor: str | None,
    ) -> InsightConversationPage:
        """The operator's own conversations about the target, newest first.

        An analysis whose source was removed is left out, as the conversation
        list leaves out such copies; opening it answers the refusal.
        """
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
        """One of the operator's own conversations, with every turn."""
        link = await self._own_conversation(session_id)
        await self.analysis_service.assert_insight_access(
            assistant_id=link.assistant_id, group_chat_id=link.group_chat_id
        )
        return await self._load_session(session_id)

    async def get_tool_call_result(
        self, session_id: UUID, tool_call_id: str
    ) -> ToolCallInfo:
        """One tool call of the operator's own conversation, with its result."""
        session = await self.get_conversation(session_id)
        tool_call = await self.session_service.get_tool_call_result(
            session=session, tool_call_id=tool_call_id
        )
        if tool_call is None:
            raise NotFoundException("Tool call not found in this conversation")
        return tool_call

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

    async def _load_session(self, session_id: UUID) -> SessionInDB:
        """The conversation with every turn, for a caller already authorized:
        the refusal of an analysis whose source was removed says it exists."""
        session = await self.session_repo.get_for_insight_conversation(
            session_id, self.user.tenant_id
        )
        if session is None:
            if await self.session_repo.is_removed_copy(session_id):
                raise DerivedSourceRemovedError()
            raise NotFoundException("Insights conversation not found.")
        return session

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
    ) -> AsyncGenerator[Completion, None]:
        # The token names the conversation the tools answer in, next to the
        # target they read, so a tool knows where what it returns ends up.
        token = self.auth_service.create_scoped_mcp_token(
            self.user,
            insight_target=(kind, target_id),
            session_id=session.id,
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
            stream=True,
            # Never extended logging: the analysis is not user content.
            extended_logging=False,
            mcp_servers=[server],
            require_tool_approval=False,
            version=2,
        )
        return self._stream_and_persist(
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
        """Pick the model that answers: it must be accessible, call tools and
        meet the space's security classification, since the tools feed it the
        space's conversations.

        The assistant's own model when it qualifies and is in the space (a
        group chat has none), else the one this space would pick among the
        qualifying models: the organisation default, else the newest.
        """

        def qualifies(model: "CompletionModel | None") -> bool:
            return (
                model is not None
                and model.can_access
                and bool(model.supports_tool_calling)
                and space.allows_security_classification(model)
            )

        if isinstance(target, Assistant):
            own = target.completion_model
            if (
                own is not None
                and qualifies(own)
                and space.is_completion_model_in_space(own.id)
            ):
                return own

        chosen = space.select_default_completion_model(
            model for model in space.completion_models if qualifies(model)
        )
        if chosen is None:
            raise InsightsModelUnavailableError()
        return chosen

    def _stream_and_persist(
        self,
        *,
        response: CompletionModelResponse,
        question_id: UUID,
        model: "CompletionModel",
    ) -> AsyncGenerator[Completion, None]:
        """Pass the answer's chunks on and complete the placeholder at the end.

        Tool calls are accumulated so later turns can replay them. If the
        stream does not reach normal completion (client abort, provider
        error), whatever already streamed (text, reasoning, and the calls
        that ran, which are the turn's evidence) is saved through a fresh
        database session, since the request-scoped one may be gone. The
        completion stream is closed on every exit, releasing the model
        request and the loopback tool connection behind it.
        """
        completion = cast(AsyncIterable[Completion], response.completion)

        async def stream() -> AsyncGenerator[Completion, None]:
            answer = ""
            reasoning = ""
            tool_calls: list[ToolCallInfo] = []
            usage: TokenUsage | None = None
            input_estimate: int | None = None
            output_estimate: int | None = None
            context_input_estimate: int | None = None
            context_output_estimate: int | None = None
            completed = False
            try:
                async for chunk in completion:
                    if chunk.usage is not None:
                        usage = chunk.usage
                    if chunk.input_token_estimate is not None:
                        input_estimate = chunk.input_token_estimate
                    if chunk.output_token_estimate is not None:
                        output_estimate = chunk.output_token_estimate
                    if chunk.context_input_token_estimate is not None:
                        context_input_estimate = chunk.context_input_token_estimate
                    if chunk.context_output_token_estimate is not None:
                        context_output_estimate = chunk.context_output_token_estimate
                    if chunk.response_type == ResponseType.TEXT and chunk.text:
                        answer = f"{answer}{chunk.text}"
                    elif chunk.response_type == ResponseType.REASONING:
                        reasoning = f"{reasoning}{chunk.reasoning_content or ''}"
                    elif chunk.response_type in _TOOL_CALL_RESPONSE_TYPES:
                        merge_tool_call_chunk(tool_calls, chunk)
                    if chunk.response_type in _FORWARDED_RESPONSE_TYPES:
                        yield chunk

                num_tokens_question = (
                    usage.prompt_tokens
                    if usage is not None and usage.prompt_tokens is not None
                    else input_estimate
                    if input_estimate is not None
                    else response.total_token_count
                )
                num_tokens_answer = (
                    usage.completion_tokens
                    if usage is not None and usage.completion_tokens is not None
                    else output_estimate
                    if output_estimate is not None
                    else safe_count_tokens(answer, model.name)
                )
                context_prompt_tokens = (
                    usage.context_prompt_tokens
                    if usage is not None and usage.context_prompt_tokens is not None
                    else context_input_estimate
                    if context_input_estimate is not None
                    else num_tokens_question
                )
                context_completion_tokens = (
                    usage.context_completion_tokens
                    if usage is not None and usage.context_completion_tokens is not None
                    else context_output_estimate
                    if context_output_estimate is not None
                    else num_tokens_answer
                )
                await self.session_service.complete_question_with_answer(
                    question_id=question_id,
                    answer=answer,
                    num_tokens_question=num_tokens_question,
                    num_tokens_answer=num_tokens_answer,
                    context_prompt_tokens=context_prompt_tokens,
                    context_completion_tokens=context_completion_tokens,
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
                        context_prompt_tokens=context_prompt_tokens,
                        context_completion_tokens=context_completion_tokens,
                    ),
                )
            finally:
                finished = finished_tool_calls(tool_calls)
                if not completed and (answer or reasoning or finished):
                    schedule_background_save(
                        persist_partial_question_answer(
                            tenant_id=self.user.tenant_id,
                            question_id=question_id,
                            answer=answer,
                            num_tokens_answer=safe_count_tokens(answer, model.name),
                            completion_model_id=model.id,
                            reasoning=reasoning or None,
                            tool_calls=finished or None,
                        )
                    )
                    logger.info(
                        "Scheduled partial insight answer save on stream abort",
                        extra={
                            "question_id": str(question_id),
                            "answer_chars": len(answer),
                            "tool_calls": len(finished),
                        },
                    )
                with finalizing("completion stream"):
                    await aclose_if_possible(completion)

        async def release_unstarted() -> None:
            with finalizing("completion stream"):
                await aclose_if_possible(completion)

        return OwnedAsyncGenerator(stream(), release=release_unstarted)
