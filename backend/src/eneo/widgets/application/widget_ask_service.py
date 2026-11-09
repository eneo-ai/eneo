# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from collections.abc import AsyncGenerator, Awaitable, Callable
from datetime import date, datetime, timezone
from typing import TYPE_CHECKING, AsyncIterator, Optional, Protocol, runtime_checkable
from uuid import UUID
from zoneinfo import ZoneInfo

import sqlalchemy as sa

from eneo.ai_models.completion_models.completion_model import (
    Completion,
    ResponseType,
    ToolCallMetadata,
)
from eneo.assistants.api.assistant_models import AssistantResponse
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.actor_types import ActorType
from eneo.audit.domain.entity_types import EntityType
from eneo.database.database import AsyncSession, sessionmanager
from eneo.database.tables.questions_table import Questions
from eneo.main.config import Settings, get_settings
from eneo.main.exceptions import NotFoundException, UnauthorizedException
from eneo.main.logging import get_logger
from eneo.main.stream_lifecycle import finalizing
from eneo.sessions.session import SessionFeedback, SessionInDB
from eneo.widgets.application.visitor_view import VisitorView
from eneo.widgets.application.widget_limits import (
    BudgetReservation,
    WidgetBudget,
    WidgetLimiter,
)
from eneo.widgets.domain.exceptions import (
    WidgetAnswerUnavailableError,
    WidgetBudgetExhaustedError,
    WidgetPublicError,
    WidgetRateLimitedError,
)
from eneo.widgets.domain.visitor import WidgetPrincipal
from eneo.widgets.domain.widget import Widget
from eneo.widgets.infrastructure.widget_usage_repo_impl import WidgetUsageRepoImpl

if TYPE_CHECKING:
    from eneo.assistants.assistant_service import AssistantService
    from eneo.audit.application.audit_service import AuditService
    from eneo.sessions.session_service import SessionService
    from eneo.users.user import UserInDB

logger = get_logger(__name__)


class SessionNotOwnedError(WidgetPublicError):
    status_code = 404
    code = "session_not_owned"

    def __init__(self) -> None:
        super().__init__("Session not found.")


@runtime_checkable
class _AsyncClosable(Protocol):
    def aclose(self) -> Awaitable[None]: ...


class WidgetAnswer(AsyncIterator[Completion]):
    """Visitor stream whose settlement also works before its first read.

    ``observe`` sees every pipeline event before the visitor filter, for
    records the organisation keeps of the turn (the external tool calls).
    """

    def __init__(
        self,
        answer: AsyncIterator[Completion],
        view: VisitorView,
        finish: Callable[[bool], Awaitable[None]],
        observe: Optional[Callable[[Completion], Awaitable[None]]] = None,
    ) -> None:
        self._answer = answer
        self._view = view
        self._finish = finish
        self._observe = observe
        self._stream = self._visible()
        self._closed = False

    def __aiter__(self) -> "WidgetAnswer":
        return self

    async def __anext__(self) -> Completion:
        return await anext(self._stream)

    async def _visible(self) -> AsyncGenerator[Completion]:
        completed = False
        try:
            async for chunk in self._answer:
                if self._observe is not None:
                    await self._observe(chunk)
                for visible in self._view.events(chunk):
                    yield visible
            for visible in self._view.finish():
                yield visible
            completed = True
        finally:
            await self._settle(completed)

    async def aclose(self) -> None:
        # Closing an unstarted async generator does not enter its finally.
        try:
            await self._stream.aclose()
        finally:
            await self._settle(False)

    async def _settle(self, completed: bool) -> None:
        if self._closed:
            return
        self._closed = True
        with finalizing("widget answer settlement"):
            try:
                if isinstance(self._answer, _AsyncClosable):
                    await self._answer.aclose()
            finally:
                await self._finish(completed)


# Appended to the assistant's prompt for widget turns only: the answer lands
# in a narrow panel on someone else's website, read by a visitor who did not
# choose the assistant. Tone, length and the assistant's own instructions stay
# the editor's.
WIDGET_STYLE_PROMPT = (
    "You are answering inside a small chat window embedded on a public website. "
    "Keep answers brief and in plain prose. Use a list only for a genuine "
    "enumeration, avoid headings, and do not restate the question."
)

# The persona is presentation, not identity: the name is shown beside every
# answer, so the model must neither sign with it nor claim to be a person.
WIDGET_PERSONA_PROMPT = (
    'In this window you are presented to the visitor under the name "{name}". '
    "It is a display name: you remain an AI assistant and say so if asked who "
    "or what you are. Do not sign your answers with the name or repeat it "
    "unprompted."
)


def widget_prompt_addendum(widget: Widget) -> str:
    """What is appended to the assistant's prompt for this widget's turns."""
    if not widget.persona.is_set:
        return WIDGET_STYLE_PROMPT
    return f"{WIDGET_STYLE_PROMPT} " + WIDGET_PERSONA_PROMPT.format(
        name=widget.persona.name
    )


# The statuses a call ends in once its server has run it. Pending and approval
# events are not the call; a denied call never reached the server.
EXECUTED_STATUSES = frozenset({"succeeded", "failed"})


def is_external_tool_call(call: ToolCallMetadata) -> bool:
    """Whether the call ran on a server outside Eneo.

    Decided like the approval flow: by the server the call was routed to,
    never by its display name. Eneo's own loopback servers are not external.
    Neither is a capability provider (web search, the one capability visitors
    get): the tenant chose it and it only reads. Everything else is one of
    the assistant's own MCP servers, where a tool may write.
    """
    return call.is_internal is not True and call.purpose is None


class ExternalToolCallAudit:
    """One audit entry per external tool call a visitor turn ran.

    Written whatever the widget's retention: the call's effect on the external
    system outlives the conversation, and with retention 0 nothing else of
    the turn is kept. The entry names the widget, the pseudonymous visitor,
    the conversation and the tool. The arguments' values stay out: they are
    the visitor's input and may carry personal data, and the external system
    has its own record of what it received; their names go in.
    """

    def __init__(
        self,
        audit_service: "AuditService",
        widget: Widget,
        *,
        visitor_id: UUID,
        session_id: UUID,
        question_id: Optional[UUID],
    ) -> None:
        self.audit_service = audit_service
        self.widget = widget
        self.visitor_id = visitor_id
        self.session_id = session_id
        self.question_id = question_id
        self._logged: set[str] = set()

    async def observe(self, chunk: Completion) -> None:
        if chunk.response_type != ResponseType.TOOL_CALL:
            return
        for call in chunk.tool_calls_metadata or []:
            if call.result_status not in EXECUTED_STATUSES:
                continue
            if not is_external_tool_call(call):
                continue
            # A call can be reported more than once (per round, on retry).
            if call.tool_call_id is not None:
                if call.tool_call_id in self._logged:
                    continue
                self._logged.add(call.tool_call_id)
            try:
                await self._log(call)
            except Exception:
                # The answer is already under way and the call has happened;
                # the missing entry is the operator's problem, not the visitor's.
                logger.exception(
                    "Widget external tool call audit failed",
                    extra={
                        "widget_id": str(self.widget.id),
                        "tool": call.mcp_tool_name or call.tool_name,
                    },
                )

    async def _log(self, call: ToolCallMetadata) -> None:
        assert self.widget.id is not None
        await self.audit_service.log_async(
            tenant_id=self.widget.tenant_id,
            actor_id=None,
            actor_type=ActorType.WIDGET_VISITOR,
            action=ActionType.WIDGET_EXTERNAL_TOOL_CALLED,
            entity_type=EntityType.WIDGET,
            entity_id=self.widget.id,
            description=(
                f"Widget '{self.widget.name}': an anonymous visitor's turn ran"
                f" tool '{call.tool_name}' on external server '{call.server_name}'"
            ),
            metadata={
                "public_id": self.widget.public_id,
                "visitor_id": str(self.visitor_id),
                "session_id": str(self.session_id),
                "question_id": str(self.question_id) if self.question_id else None,
                "tool_call_id": call.tool_call_id,
                "server_name": call.server_name,
                "tool_name": call.tool_name,
                "mcp_tool_name": call.mcp_tool_name,
                "result_status": call.result_status,
                "argument_names": sorted(call.arguments or {}),
            },
            # The visitor's address and browser stay out of the trail, as for
            # every widget entry; the pseudonymous visitor id is the actor.
            record_client=False,
        )


class WidgetAskService:
    """Runs the ordinary assistant ask pipeline for an anonymous visitor.

    The visitor is the container's user (a synthetic ``UserInDB`` carrying
    ``active_widget``), so authorization, session ownership and persistence
    follow the same paths as everyone else. This service adds what is
    widget-specific: question limits, rate limits, the daily token budget,
    usage accounting and the retention rules.
    """

    def __init__(
        self,
        user: "UserInDB",
        assistant_service: "AssistantService",
        session_service: "SessionService",
        widget_limiter: WidgetLimiter,
        widget_budget: WidgetBudget,
        widget_usage_repo: WidgetUsageRepoImpl,
        audit_service: Optional["AuditService"] = None,
        settings: Optional[Settings] = None,
    ) -> None:
        self.user = user
        self.assistant_service = assistant_service
        self.session_service = session_service
        self.limiter = widget_limiter
        self.budget = widget_budget
        self.usage_repo = widget_usage_repo
        self.audit_service = audit_service
        self.settings = settings or get_settings()

    # --- helpers ----------------------------------------------------------

    def _today(self) -> date:
        return datetime.now(ZoneInfo(self.settings.widget_budget_timezone)).date()

    def _session_day(self, session: SessionInDB) -> date:
        if session.created_at is None:
            return self._today()
        created_at = session.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        return created_at.astimezone(
            ZoneInfo(self.settings.widget_budget_timezone)
        ).date()

    async def _owned_session(self, widget: Widget, session_id: UUID) -> SessionInDB:
        # Retention cut to zero after conversations were stored, by the widget
        # or the tenant policy: they stay closed to visitors (no restore,
        # follow-up or comment) until the retention job removes them.
        if widget.privacy.never_persists:
            raise SessionNotOwnedError()
        try:
            return await self.session_service.get_session_by_uuid(
                id=session_id, assistant_id=widget.target_id
            )
        except (NotFoundException, UnauthorizedException) as exc:
            # Never reveal whether a foreign session exists.
            raise SessionNotOwnedError() from exc

    # --- queries ----------------------------------------------------------

    async def get_session(
        self, principal: WidgetPrincipal, session_id: UUID
    ) -> SessionInDB:
        session = await self._owned_session(principal.widget, session_id)
        return VisitorView(principal.widget).session(session)

    async def leave_feedback(
        self, principal: WidgetPrincipal, session_id: UUID, feedback: SessionFeedback
    ) -> SessionInDB:
        widget = principal.widget
        assert widget.id is not None
        session = await self._owned_session(widget, session_id)
        # Lock the row for the rest of the request transaction so overlapping
        # votes serialise and the second one sees the first one's vote.
        previous = await self.usage_repo.lock_feedback(session.id)
        if not widget.privacy.store_feedback_text:
            feedback = SessionFeedback(value=feedback.value, text=None)
        # The embed page sends a changed vote without the comment it sent
        # earlier; only a new comment replaces the stored one.
        updated = await self.session_service.leave_feedback(
            session_id=session_id,
            assistant_id=widget.target_id,
            feedback=feedback,
            keep_existing_text=True,
        )
        # Daily counters follow the vote, in the same transaction as the vote
        # and always on the conversation's first day, so a vote changed on a
        # later day moves between the columns of that one row instead of
        # leaving a negative count on the day it changed.
        if previous != feedback.value:
            await self.usage_repo.record(
                widget.id,
                self._session_day(session),
                helpful=(feedback.value == 1) - (previous == 1),
                unhelpful=(feedback.value == -1) - (previous == -1),
            )
        return VisitorView(widget).session(updated)

    # --- ask --------------------------------------------------------------

    async def ask(
        self,
        principal: WidgetPrincipal,
        *,
        question: str,
        session_id: Optional[UUID],
        client_ip: Optional[str],
    ) -> AssistantResponse:
        widget = principal.widget
        assert widget.id is not None
        cleaned = question.strip()
        if not cleaned:
            raise WidgetPublicError(
                "Question must not be empty.", code="question_empty"
            )
        if len(cleaned) > widget.limits.max_question_chars:
            raise WidgetPublicError(
                f"Question exceeds {widget.limits.max_question_chars} characters.",
                code="question_too_long",
            )

        try:
            await self.limiter.check_message(widget, principal.visitor_id, client_ip)
        except WidgetRateLimitedError:
            await self._record_blocked(widget, blocked_rate=1)
            raise

        hold: Optional[str] = None
        try:
            if session_id is not None:
                # Ownership before the hold: the hold is keyed by the session
                # id alone, so a visitor who knows another conversation's id
                # must get its 404 without ever holding that conversation.
                await self._owned_session(widget, session_id)
                # Held until the answer ends (_finish) or the request fails
                # before it: the turn count is only exact for one follow-up at
                # a time, so the conversation is read again under the hold.
                hold = await self.limiter.hold_turn(widget, session_id)
                session = await self._owned_session(widget, session_id)
                if len(session.questions) >= widget.limits.max_session_turns:
                    raise WidgetPublicError(
                        "This conversation has reached its length limit. Start a new one.",
                        code="session_turns_exceeded",
                    )
            return await self._ask_admitted(
                widget, cleaned, session_id, principal=principal, hold=hold
            )
        except BaseException:
            if session_id is not None and hold is not None:
                with finalizing("widget turn release"):
                    await self.limiter.release_turn(widget, session_id, hold)
            raise

    async def _ask_admitted(
        self,
        widget: Widget,
        cleaned: str,
        session_id: Optional[UUID],
        *,
        principal: WidgetPrincipal,
        hold: Optional[str],
    ) -> AssistantResponse:
        assert widget.id is not None
        try:
            reservation = await self.budget.reserve(
                widget, self.settings.widget_budget_reservation_tokens
            )
        except WidgetBudgetExhaustedError:
            await self._record_blocked(widget, blocked_budget=1)
            await self._audit_budget_exhausted(widget)
            raise

        try:
            response = await self._start_turn(widget, cleaned, session_id)
        except BaseException:
            # No stream owns the reservation yet. Cleanup must also run on a
            # disconnected client, without hiding the error being raised.
            with finalizing("widget reservation release"):
                try:
                    await self.budget.release(reservation)
                except Exception:
                    logger.exception("Widget budget release failed")
            raise
        answer = response.answer
        assert not isinstance(answer, str)
        visible = VisitorView(widget).response(response)
        audit = (
            ExternalToolCallAudit(
                self.audit_service,
                widget,
                visitor_id=principal.visitor_id,
                session_id=response.session.id,
                question_id=response.question_id,
            )
            if self.audit_service is not None
            else None
        )
        visible.answer = WidgetAnswer(
            answer.__aiter__(),
            VisitorView(widget),
            lambda completed: self._finish(
                widget,
                response.session.id,
                response.question_id,
                reservation,
                completed=completed,
                asked_in=session_id,
                hold=hold,
            ),
            observe=audit.observe if audit is not None else None,
        )
        return visible

    async def _start_turn(
        self, widget: Widget, cleaned: str, session_id: Optional[UUID]
    ) -> AssistantResponse:
        try:
            # The assistant as configured, MCP servers and capabilities
            # included, less what a visitor cannot run (AssistantService,
            # VISITOR_CAPABILITY_PURPOSES). Approval is never requested.
            return await self.assistant_service.ask(
                question=cleaned,
                assistant_id=widget.target_id,
                session_id=session_id,
                stream=True,
                # The citing protocol: the model tags claims with <inref/> and
                # only cited documents come back as references.
                version=2,
                num_chunks_override=self.settings.widget_retrieval_chunks,
                prompt_addendum=widget_prompt_addendum(widget),
            )
        except WidgetPublicError:
            raise
        except Exception as exc:
            # Every other failure carries text written for the people running
            # the assistant, with its model, provider or configuration.
            logger.exception(
                "Widget turn failed before the answer started",
                extra={"widget_id": str(widget.id)},
            )
            raise WidgetAnswerUnavailableError() from exc

    async def _finish(
        self,
        widget: Widget,
        session_id: UUID,
        question_id: UUID | None,
        reservation: BudgetReservation,
        *,
        completed: bool,
        asked_in: UUID | None = None,
        hold: Optional[str] = None,
    ) -> None:
        """Settle the budget, record usage, apply "never persist" and release
        the conversation's turn hold (``asked_in`` is the follow-up's session,
        ``hold`` the marker ``hold_turn`` returned for it).

        Runs when the answer stream ends. The ask pipeline has by then stored
        the answer and its token counts, but only inside the request
        transaction, which commits after the response is sent; reading them
        through the same session is the only way to see them here.
        """
        assert widget.id is not None
        try:
            usage = self.usage_repo
            # An interrupted stream has uncertain provider usage: retain the
            # reservation for this day rather than refunding unknown costs.
            if completed and question_id is not None:
                prompt_tokens, completion_tokens = await self._question_tokens(
                    usage.session, question_id
                )
                await self.budget.settle(reservation, prompt_tokens, completion_tokens)
        except Exception:
            logger.exception(
                "Widget answer settlement failed",
                extra={"widget_id": str(widget.id), "session_id": str(session_id)},
            )
        finally:
            # Retention is not conditional on successful budget/statistics
            # writes. Failure here propagates and rolls back the chat write.
            try:
                if widget.privacy.never_persists:
                    await self.usage_repo.delete_session(session_id)
            finally:
                if asked_in is not None:
                    await self.limiter.release_turn(widget, asked_in, hold)

    @staticmethod
    async def _question_tokens(
        session: AsyncSession, question_id: UUID
    ) -> tuple[int, int]:
        row = (
            await session.execute(
                sa.select(
                    Questions.num_tokens_question,
                    Questions.num_tokens_answer,
                    Questions.context_prompt_tokens,
                    Questions.context_completion_tokens,
                ).where(Questions.id == question_id)
            )
        ).first()
        if row is None:
            raise RuntimeError("Widget answer usage is missing; reservation retained.")
        question_tokens, answer_tokens, prompt_tokens, completion_tokens = row
        # The num_tokens_* columns add up every provider request of the turn,
        # tool rounds included, which is what the provider bills. The context
        # columns keep only the final request and serve headroom, not cost.
        return (
            int(question_tokens if question_tokens is not None else prompt_tokens or 0),
            int(answer_tokens if answer_tokens is not None else completion_tokens or 0),
        )

    async def _record_blocked(
        self, widget: Widget, *, blocked_rate: int = 0, blocked_budget: int = 0
    ) -> None:
        """Blocked requests end in an error response that rolls the request
        transaction back, so the counter gets its own committed session."""
        assert widget.id is not None
        try:
            async with sessionmanager.session() as session, session.begin():
                await WidgetUsageRepoImpl(session).record(
                    widget.id,
                    self._today(),
                    blocked_rate=blocked_rate,
                    blocked_budget=blocked_budget,
                )
        except Exception:
            logger.exception(
                "Widget blocked-request accounting failed",
                extra={"widget_id": str(widget.id)},
            )

    async def _audit_budget_exhausted(self, widget: Widget) -> None:
        if self.audit_service is None or widget.id is None:
            return
        key = f"widget:{widget.id}:budget-audited:{self._today().isoformat()}"
        try:
            first = await self.limiter.redis.set(key, b"1", nx=True, ex=36 * 3600)
        except Exception:
            first = True
        if not first:
            return
        await self.audit_service.log_async(
            tenant_id=widget.tenant_id,
            actor_id=None,
            actor_type=ActorType.SYSTEM,
            action=ActionType.WIDGET_BUDGET_EXHAUSTED,
            entity_type=EntityType.WIDGET,
            entity_id=widget.id,
            description=f"Widget '{widget.name}' exhausted its daily token budget",
            metadata={
                "public_id": widget.public_id,
                "daily_token_budget": widget.limits.daily_token_budget,
            },
            # The visitor who happened to trip the budget is not the actor:
            # their address and browser stay out of the tenant's audit trail.
            record_client=False,
        )
