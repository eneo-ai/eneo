"""AI Builder service facade.

This module is intentionally small: session CRUD stays here, while the planner
conversation loop and plan lifecycle live in focused collaborators.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, AsyncGenerator, Protocol, cast
from uuid import UUID

import litellm

from intric.flows.ai_builder.ai_builder_context import (
    AIBuilderPlannerContext,
    build_planner_context,
)
from intric.flows.ai_builder.ai_builder_events import (
    SSE_EVENT_DONE as _SSE_EVENT_DONE,
)
from intric.flows.ai_builder.ai_builder_events import (
    SSE_EVENT_ERROR as _SSE_EVENT_ERROR,
)
from intric.flows.ai_builder.ai_builder_events import (
    SSE_EVENT_PLAN as _SSE_EVENT_PLAN,
)
from intric.flows.ai_builder.ai_builder_events import (
    SSE_EVENT_QUESTION as _SSE_EVENT_QUESTION,
)
from intric.flows.ai_builder.ai_builder_events import (
    SSE_EVENT_STATUS as _SSE_EVENT_STATUS,
)
from intric.flows.ai_builder.ai_builder_events import (
    SSE_EVENT_TEXT as _SSE_EVENT_TEXT,
)
from intric.flows.ai_builder.ai_builder_models import (
    ApplyResultResponse,
    BuilderPlan,
    BuilderSession,
    PlanStatus,
    SessionListItemResponse,
    TargetKind,
)
from intric.flows.ai_builder.ai_builder_plan_lifecycle import AIBuilderPlanLifecycle
from intric.flows.ai_builder.ai_builder_planner import AIBuilderPlanner
from intric.flows.ai_builder.ai_builder_repo import AIBuilderRepository
from intric.flows.ai_builder.ai_builder_settings import AIBuilderBudgetPolicy
from intric.flows.ai_builder.ai_builder_validation_common import (
    LintWarning,
    SpecValidationError,
)
from intric.main.exceptions import BadRequestException

if TYPE_CHECKING:
    from intric.completion_models.infrastructure.completion_service import (
        CompletionService,
    )
    from intric.flows.application.flow_service import FlowService
    from intric.flows.domain.flow import Flow
    from intric.spaces.space import Space
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


class _CredentialResolverProtocol(Protocol):
    def get_api_key(self) -> str | None: ...

    def get_credential_field(self, *, field: str) -> str | None: ...


class _CompletionModelAdapterProtocol(Protocol):
    credential_resolver: _CredentialResolverProtocol
    litellm_model: str


@dataclass(frozen=True)
class PreparedMessageContext:
    """Pre-fetched planner and flow context for AI Builder message handling."""

    planner_context: AIBuilderPlannerContext
    litellm_model: str
    litellm_kwargs: dict[str, object]
    flow: "Flow | None"
    assistant_snapshots: dict[UUID, dict[str, Any]] | None


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
            flow = await self.flow_service.get_flow(flow_id)
            self._assert_flow_in_space(flow=flow, space_id=space_id)

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
            cancelled_session_ids = await self.repo.cancel_matching_active_sessions(
                tenant_id=self.user.tenant_id,
                actor_user_id=self.user.id,
                space_id=space_id,
                target_kind=target_kind,
                flow_id=flow_id,
            )
            await self._supersede_cancelled_session_plans(cancelled_session_ids)

        return await self.repo.create_session(
            tenant_id=self.user.tenant_id,
            space_id=space_id,
            actor_user_id=self.user.id,
            target_kind=target_kind,
            flow_id=flow_id,
        )

    async def _supersede_cancelled_session_plans(
        self,
        cancelled_session_ids: object,
    ) -> None:
        """Supersede actionable plans from sessions replaced by a fresh start."""

        if not isinstance(cancelled_session_ids, list | tuple | set):
            return

        for session_id in cast(
            list[object] | tuple[object, ...] | set[object], cancelled_session_ids
        ):
            if isinstance(session_id, UUID):
                await self.repo.supersede_existing_plans(
                    session_id=session_id,
                    tenant_id=self.user.tenant_id,
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

    async def resolve_planner_params(self, model: Any) -> tuple[str, dict[str, object]]:
        """Resolve LiteLLM model name and provider kwargs for the planner model."""
        resolve_params = getattr(
            self.completion_service, "resolve_litellm_params", None
        )
        if callable(resolve_params):
            resolved_candidate = resolve_params(model)
            if inspect.isawaitable(resolved_candidate):
                resolved_candidate = await resolved_candidate
            resolved_tuple = (
                cast(tuple[object, ...], resolved_candidate)
                if isinstance(resolved_candidate, tuple)
                else None
            )
            if (
                resolved_tuple is not None
                and len(resolved_tuple) == 2
                and isinstance(resolved_tuple[0], str)
                and isinstance(resolved_tuple[1], dict)
            ):
                return cast(tuple[str, dict[str, object]], resolved_tuple)

        adapter = cast(
            _CompletionModelAdapterProtocol,
            await self.completion_service._get_adapter(model),  # pyright: ignore[reportPrivateUsage]
        )
        litellm_kwargs: dict[str, object] = {}
        api_key = adapter.credential_resolver.get_api_key()
        if api_key:
            litellm_kwargs["api_key"] = api_key

        field_mapping = {
            "endpoint": "api_base",
            "api_version": "api_version",
            "api_type": "api_type",
            "organization": "organization",
            "deployment_name": "deployment_name",
        }
        for field, key in field_mapping.items():
            value = adapter.credential_resolver.get_credential_field(field=field)
            if value:
                litellm_kwargs[key] = value

        return adapter.litellm_model, litellm_kwargs

    async def prepare_message_context(
        self,
        *,
        session: BuilderSession,
        space: "Space",
        model_id: UUID | None,
        tenant_flow_settings: dict[str, Any] | None,
        planner_params_resolver: Callable[
            [Any], Awaitable[tuple[str, dict[str, object]]]
        ]
        | None = None,
    ) -> PreparedMessageContext:
        """Pre-fetch planner, provider, and flow-edit context before SSE streaming."""
        planner_context = build_planner_context(
            space,
            model_id=model_id,
            tenant_flow_settings=tenant_flow_settings,
        )
        resolve_planner_params = planner_params_resolver or self.resolve_planner_params
        litellm_model, litellm_kwargs = await resolve_planner_params(
            planner_context.model
        )

        flow = None
        assistant_snapshots = None
        if session.flow_id is not None:
            flow = await self.flow_service.get_flow(session.flow_id)
            self._assert_flow_in_space(flow=flow, space_id=session.space_id)
            assistant_snapshots = await self.flow_service.get_flow_assistant_snapshots(
                flow
            )

        return PreparedMessageContext(
            planner_context=planner_context,
            litellm_model=litellm_model,
            litellm_kwargs=litellm_kwargs,
            flow=flow,
            assistant_snapshots=assistant_snapshots,
        )

    @staticmethod
    def _assert_flow_in_space(*, flow: Any, space_id: UUID) -> None:
        if getattr(flow, "space_id", None) != space_id:
            raise BadRequestException(
                "Flow space does not match the AI builder session space.",
                code="flow_space_mismatch",
            )

    async def send_message(
        self,
        *,
        session_id: UUID,
        message: str,
        question_answer: dict[str, Any] | None = None,
        ui_language: str | None = None,
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
            ui_language=ui_language,
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

    async def revise_plan(
        self,
        *,
        plan_id: UUID,
        revision_type: str,
    ) -> BuilderPlan:
        """Create a new plan version with a structured revision.

        - keep_current_description: copies spec with description_override_manual=True
        """
        from intric.flows.ai_builder.ai_builder_plan_store import (
            build_plan_envelope,
            persist_plan,
        )

        plan = await self.repo.get_plan(
            plan_id=plan_id,
            tenant_id=self.user.tenant_id,
        )
        if plan.status != PlanStatus.PROPOSED:
            raise BadRequestException(
                "Can only revise proposed plans.",
                code="plan_not_proposed",
            )

        session = await self.repo.get_session(
            session_id=plan.session_id,
            tenant_id=self.user.tenant_id,
        )
        if session.actor_user_id != self.user.id:
            from intric.main.exceptions import UnauthorizedException

            raise UnauthorizedException(
                "Only the session creator can revise plans.",
                code="session_creator_required",
            )

        if revision_type == "keep_current_description":
            # Create new plan version with description_override_manual flag
            # The spec stays the same — the flag is stored in edit_result_json
            revised_edit_result = dict(plan.edit_result_json or {})
            revised_edit_result["description_override_manual"] = True

            envelope = build_plan_envelope(
                spec=plan.spec,
                assumptions=plan.envelope.assumptions,
                plan_rationale=plan.envelope.plan_rationale,
                reasoning=None,
                validation=_empty_validation(),
            )
            new_plan = await persist_plan(
                repo=self.repo,
                tenant_id=self.user.tenant_id,
                session_id=plan.session_id,
                spec=plan.spec,
                envelope=envelope,
                edit_result_json=revised_edit_result,
            )
            return new_plan

        raise BadRequestException(
            f"Unsupported revision type: {revision_type}",
            code="unsupported_revision_type",
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


class _EmptyValidation:
    """Stub validation result with no warnings/errors for plan revisions."""

    warnings: list[LintWarning] = []
    errors: list[SpecValidationError] = []


def _empty_validation() -> _EmptyValidation:
    return _EmptyValidation()
