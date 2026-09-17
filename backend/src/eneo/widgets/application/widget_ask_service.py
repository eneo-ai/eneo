# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from datetime import date, datetime
from typing import TYPE_CHECKING, AsyncIterator, Optional
from uuid import UUID
from zoneinfo import ZoneInfo

import sqlalchemy as sa

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
from eneo.mcp_servers.domain.entities.mcp_server import CAPABILITY_PURPOSES
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
        return await self._owned_session(principal.widget, session_id)

    async def leave_feedback(
        self, principal: WidgetPrincipal, session_id: UUID, feedback: SessionFeedback
    ) -> SessionInDB:
        widget = principal.widget
        await self._owned_session(widget, session_id)
        if not widget.privacy.store_feedback_text:
            feedback = SessionFeedback(value=feedback.value, text=None)
        return await self.session_service.leave_feedback(
            session_id=session_id, assistant_id=widget.target_id, feedback=feedback
        )

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

        response = await self.assistant_service.ask(
            question=cleaned,
            assistant_id=widget.target_id,
            session_id=session_id,
            stream=True,
            allow_tools=False,
            disabled_capabilities=list(CAPABILITY_PURPOSES),
        )
        # Visitors never learn which model answers; the first chunk would
        # otherwise carry the full model record.
        response.completion_model = None  # type: ignore[assignment]
        answer = response.answer
        assert not isinstance(answer, str)
        response.answer = self._settled(
            answer.__aiter__(),
            widget=widget,
            session_id=response.session.id,
            reservation=reservation,
        )
        return response

    async def _settled(
        self,
        answer: AsyncIterator[Completion],
        *,
        widget: Widget,
        session_id: UUID,
        reservation: BudgetReservation,
    ) -> AsyncIterator[Completion]:
        try:
            async for chunk in answer:
                yield chunk
        finally:
            await self._finish(widget, session_id, reservation)

    async def _finish(
        self, widget: Widget, session_id: UUID, reservation: BudgetReservation
    ) -> None:
        """Settle the budget, record usage and apply "never persist".

        Runs after the stream ends or is aborted; uses its own session because
        the request session may already be closing.
        """
        assert widget.id is not None
        try:
            async with sessionmanager.session() as session, session.begin():
                prompt_tokens, completion_tokens = await self._last_question_tokens(
                    session, session_id
                )
                await self.budget.settle(reservation, prompt_tokens + completion_tokens)
                usage = WidgetUsageRepoImpl(session)
                await usage.record(
                    widget.id,
                    self._today(),
                    questions=1,
                    input_tokens=prompt_tokens,
                    output_tokens=completion_tokens,
                )
                if widget.privacy.retention_days == 0:
                    await usage.delete_session(session_id)
        except Exception:
            logger.exception(
                "Widget answer settlement failed",
                extra={"widget_id": str(widget.id), "session_id": str(session_id)},
            )

    @staticmethod
    async def _last_question_tokens(
        session: AsyncSession, session_id: UUID
    ) -> tuple[int, int]:
        row = (
            await session.execute(
                sa.select(
                    Questions.num_tokens_question,
                    Questions.num_tokens_answer,
                    Questions.context_prompt_tokens,
                    Questions.context_completion_tokens,
                )
                .where(Questions.session_id == session_id)
                .order_by(Questions.created_at.desc())
                .limit(1)
            )
        ).first()
        if row is None:
            return 0, 0
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
            first = await self.budget.redis.set(key, b"1", nx=True, ex=36 * 3600)
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
