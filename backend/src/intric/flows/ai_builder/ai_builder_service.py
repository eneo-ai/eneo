"""AI Builder service facade.

This module is intentionally small: session CRUD stays here, while the planner
conversation loop and plan lifecycle live in focused collaborators.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, AsyncGenerator
from uuid import UUID

import litellm

from intric.flows.ai_builder.ai_builder_events import (
    SSE_EVENT_DONE as _SSE_EVENT_DONE,
    SSE_EVENT_ERROR as _SSE_EVENT_ERROR,
    SSE_EVENT_PLAN as _SSE_EVENT_PLAN,
    SSE_EVENT_QUESTION as _SSE_EVENT_QUESTION,
    SSE_EVENT_STATUS as _SSE_EVENT_STATUS,
    SSE_EVENT_TEXT as _SSE_EVENT_TEXT,
)
from intric.flows.ai_builder.ai_builder_settings import AIBuilderBudgetPolicy
from intric.flows.ai_builder.ai_builder_models import (
    ApplyResultResponse,
    BuilderPlan,
    BuilderSession,
    SessionListItemResponse,
    TargetKind,
)
from intric.flows.ai_builder.ai_builder_plan_lifecycle import AIBuilderPlanLifecycle
from intric.flows.ai_builder.ai_builder_planner import AIBuilderPlanner
from intric.flows.ai_builder.ai_builder_repo import AIBuilderRepository
from intric.main.exceptions import BadRequestException

if TYPE_CHECKING:
    from intric.completion_models.infrastructure.completion_service import (
        CompletionService,
    )
    from intric.flows.flow import Flow
    from intric.flows.flow_service import FlowService
    from intric.spaces.space_service import SpaceService
    from intric.users.user import UserInDB

DISCOVERY_TEMPERATURE = 0.6  # Higher for creative question-asking
PLANNER_TEMPERATURE = 0.4  # Lower for precise proposal generation
SELF_CORRECTION_TEMPERATURE = 0.35
FORCED_PROPOSAL_TEMPERATURE = 0.1
QUALITY_RETRY_WARNING_CODES = {
    "json_output_no_contract",
    "contract_missing_descriptions",
    "contract_instruction_mismatch",
    "multi_goal_prompt",
}

SSE_EVENT_TEXT = _SSE_EVENT_TEXT
SSE_EVENT_PLAN = _SSE_EVENT_PLAN
SSE_EVENT_QUESTION = _SSE_EVENT_QUESTION
SSE_EVENT_ERROR = _SSE_EVENT_ERROR
SSE_EVENT_STATUS = _SSE_EVENT_STATUS
SSE_EVENT_DONE = _SSE_EVENT_DONE

logger = logging.getLogger(__name__)


class AIBuilderService:
    """Composition root for AI Builder session, planner, and apply flows."""

    def __init__(
        self,
        user: "UserInDB",
        repo: AIBuilderRepository,
        flow_service: "FlowService",
        completion_service: "CompletionService",
        space_service: "SpaceService | None" = None,
    ) -> None:
        self.user = user
        self.repo = repo
        self.flow_service = flow_service
        self.completion_service = completion_service
        self.space_service = space_service

    async def create_session(
        self,
        *,
        space_id: UUID,
        target_kind: TargetKind,
        flow_id: UUID | None = None,
        force_new: bool = False,
    ) -> BuilderSession:
        if target_kind == TargetKind.EDIT and flow_id is None:
            raise BadRequestException("flow_id is required for edit sessions.")

        if flow_id is not None:
            await self.flow_service.get_flow(flow_id)

        should_resume_existing = target_kind == TargetKind.EDIT and not force_new
        if should_resume_existing:
            existing_session = await self.repo.find_latest_resumable_session(
                tenant_id=self.user.tenant_id,
                actor_user_id=self.user.id,
                space_id=space_id,
                target_kind=target_kind,
                flow_id=flow_id,
            )
            if existing_session is not None:
                return existing_session

        if force_new:
            await self.repo.cancel_matching_active_sessions(
                tenant_id=self.user.tenant_id,
                actor_user_id=self.user.id,
                space_id=space_id,
                target_kind=target_kind,
                flow_id=flow_id,
            )

        return await self.repo.create_session(
            tenant_id=self.user.tenant_id,
            space_id=space_id,
            actor_user_id=self.user.id,
            target_kind=target_kind,
            flow_id=flow_id,
        )

    async def get_session(self, session_id: UUID) -> BuilderSession:
        return await self.repo.get_session(
            session_id=session_id,
            tenant_id=self.user.tenant_id,
        )

    async def get_plan(self, plan_id: UUID) -> BuilderPlan:
        return await self.repo.get_plan(
            plan_id=plan_id,
            tenant_id=self.user.tenant_id,
        )

    async def list_session_plans(self, session_id: UUID) -> list[BuilderPlan]:
        return await self.repo.list_session_plans(
            session_id=session_id,
            tenant_id=self.user.tenant_id,
        )

    async def list_sessions(self) -> list[SessionListItemResponse]:
        sessions = await self.repo.list_sessions_for_user(
            tenant_id=self.user.tenant_id,
            actor_user_id=self.user.id,
        )
        summaries: list[SessionListItemResponse] = []
        for session in sessions:
            draft_title = None
            if session.latest_plan_id is not None:
                try:
                    plan = await self.repo.get_plan(
                        plan_id=session.latest_plan_id,
                        tenant_id=self.user.tenant_id,
                    )
                    draft_title = plan.spec.flow_name
                except Exception:
                    logger.warning(
                        "Failed to resolve AI builder draft title for session list item.",
                        extra={
                            "session_id": str(session.id),
                            "latest_plan_id": str(session.latest_plan_id),
                            "tenant_id": str(self.user.tenant_id),
                        },
                        exc_info=True,
                    )
                    draft_title = None

            summaries.append(
                SessionListItemResponse(
                    session_id=session.id,
                    space_id=session.space_id,
                    status=session.status,
                    target_kind=session.target_kind,
                    flow_id=session.flow_id,
                    latest_plan_id=session.latest_plan_id,
                    draft_title=draft_title,
                    created_at=session.created_at,
                    updated_at=session.updated_at,
                )
            )
        return summaries

    async def cancel_session(self, session_id: UUID) -> BuilderSession:
        await self.get_session(session_id)
        await self.repo.cancel_session(
            session_id=session_id,
            tenant_id=self.user.tenant_id,
        )
        return await self.get_session(session_id)

    async def send_message(
        self,
        *,
        session_id: UUID,
        message: str,
        question_answer: dict[str, Any] | None = None,
        litellm_model: str,
        litellm_kwargs: dict[str, Any],
        available_models: list[dict[str, Any]] | None = None,
        available_kbs: list[dict[str, Any]] | None = None,
        flow: "Flow | None" = None,
        assistant_snapshots: dict[UUID, dict[str, Any]] | None = None,
        max_input_tokens: int | None = None,
        max_output_tokens: int | None = None,
        budget_policy: AIBuilderBudgetPolicy | None = None,
    ) -> AsyncGenerator[dict[str, str], None]:
        planner = self._build_planner()
        async for event in planner.send_message(
            session_id=session_id,
            message=message,
            question_answer=question_answer,
            litellm_model=litellm_model,
            litellm_kwargs=litellm_kwargs,
            available_models=available_models,
            available_kbs=available_kbs,
            flow=flow,
            assistant_snapshots=assistant_snapshots,
            max_input_tokens=max_input_tokens,
            max_output_tokens=max_output_tokens,
            budget_policy=budget_policy,
        ):
            yield event

    async def approve_plan(self, *, plan_id: UUID) -> BuilderPlan:
        return await self._build_plan_lifecycle().approve_plan(plan_id=plan_id)

    async def apply_plan(
        self,
        *,
        plan_id: UUID,
        expected_revision: int | None = None,
    ) -> ApplyResultResponse:
        return await self._build_plan_lifecycle().apply_plan(
            plan_id=plan_id,
            expected_revision=expected_revision,
        )

    def _build_planner(self) -> AIBuilderPlanner:
        return AIBuilderPlanner(
            user=self.user,
            repo=self.repo,
            litellm_client=litellm,
            discovery_temperature=DISCOVERY_TEMPERATURE,
            planner_temperature=PLANNER_TEMPERATURE,
            self_correction_temperature=SELF_CORRECTION_TEMPERATURE,
            forced_proposal_temperature=FORCED_PROPOSAL_TEMPERATURE,
            quality_retry_warning_codes=QUALITY_RETRY_WARNING_CODES,
        )

    def _build_plan_lifecycle(self) -> AIBuilderPlanLifecycle:
        return AIBuilderPlanLifecycle(
            user=self.user,
            repo=self.repo,
            flow_service=self.flow_service,
            space_service=self.space_service,
        )
