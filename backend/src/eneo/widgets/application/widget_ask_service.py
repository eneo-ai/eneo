# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from collections.abc import AsyncGenerator
from datetime import date, datetime
from typing import TYPE_CHECKING, AsyncIterator, Optional
from uuid import UUID
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from anyio import CancelScope

from eneo.ai_models.completion_models.completion_model import Completion
from eneo.assistants.api.assistant_models import AssistantResponse
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.actor_types import ActorType
from eneo.audit.domain.entity_types import EntityType
from eneo.database.database import AsyncSession, sessionmanager
from eneo.database.tables.questions_table import Questions
from eneo.main.config import Settings, get_settings
from eneo.main.exceptions import NotFoundException, UnauthorizedException
from eneo.main.logging import get_logger
from eneo.sessions.session import SessionFeedback, SessionInDB
from eneo.widgets.application.widget_limits import (
    BudgetReservation,
    WidgetBudget,
    WidgetLimiter,
)
from eneo.widgets.domain.exceptions import (
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

    async def _owned_session(self, widget: Widget, session_id: UUID) -> SessionInDB:
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
        if not principal.widget.show_sources:
            for question in session.questions:
                question.info_blobs = []
        return session

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
        updated = await self.session_service.leave_feedback(
            session_id=session_id, assistant_id=widget.target_id, feedback=feedback
        )
        # Daily counters follow the vote: a changed vote moves between the
        # columns on the day it changes, in the same transaction as the vote.
        if previous != feedback.value:
            await self.usage_repo.record(
                widget.id,
                self._today(),
                helpful=(feedback.value == 1) - (previous == 1),
                unhelpful=(feedback.value == -1) - (previous == -1),
            )
        return updated

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

        if session_id is not None:
            session = await self._owned_session(widget, session_id)
            if len(session.questions) >= widget.limits.max_session_turns:
                raise WidgetPublicError(
                    "This conversation has reached its length limit. Start a new one.",
                    code="session_turns_exceeded",
                )

        try:
            reservation = await self.budget.reserve(
                widget, self.settings.widget_budget_reservation_tokens
            )
        except WidgetBudgetExhaustedError:
            await self._record_blocked(widget, blocked_budget=1)
            await self._audit_budget_exhausted(widget)
            raise

        try:
            response = await self.assistant_service.ask(
                question=cleaned,
                assistant_id=widget.target_id,
                session_id=session_id,
                stream=True,
                # The citing protocol: the model tags claims with <inref/> and
                # only cited documents come back as references.
                version=2,
                num_chunks_override=self.settings.widget_retrieval_chunks,
                # The assistant as configured: its MCP servers and capabilities
                # serve visitors too. Approval is never requested for visitors.
                allow_tools=True,
            )
        except BaseException:
            # No stream owns the reservation yet. Cleanup must also run on a
            # disconnected client, without hiding the original provider error.
            with CancelScope(shield=True):
                try:
                    await self.budget.release(reservation)
                except Exception:
                    logger.exception("Widget budget release failed")
            raise
        # Visitors never learn which model answers; the first chunk would
        # otherwise carry the full model record.
        response.completion_model = None  # type: ignore[assignment]
        answer = response.answer
        assert not isinstance(answer, str)
        response.answer = self._settled(
            answer.__aiter__(),
            widget=widget,
            session_id=response.session.id,
            question_id=response.question_id,
            reservation=reservation,
        )
        return response

    async def _settled(
        self,
        answer: AsyncIterator[Completion],
        *,
        widget: Widget,
        session_id: UUID,
        question_id: UUID | None,
        reservation: BudgetReservation,
    ) -> AsyncIterator[Completion]:
        completed = False
        try:
            async for chunk in answer:
                # Hidden sources never leave the server: the visitor gets
                # neither citation targets nor document titles.
                if not widget.show_sources:
                    chunk.reference_chunks = None
                yield chunk
            completed = True
        finally:
            with CancelScope(shield=True):
                try:
                    if isinstance(answer, AsyncGenerator):
                        await answer.aclose()
                finally:
                    await self._finish(
                        widget,
                        session_id,
                        question_id,
                        reservation,
                        completed=completed,
                    )

    async def _finish(
        self,
        widget: Widget,
        session_id: UUID,
        question_id: UUID | None,
        reservation: BudgetReservation,
        *,
        completed: bool,
    ) -> None:
        """Settle the budget, record usage and apply "never persist".

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
            if widget.privacy.never_persists:
                await self.usage_repo.delete_session(session_id)

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
        return (
            int(prompt_tokens if prompt_tokens is not None else question_tokens or 0),
            int(
                completion_tokens
                if completion_tokens is not None
                else answer_tokens or 0
            ),
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
        )
