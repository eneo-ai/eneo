from __future__ import annotations

from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import (
    TYPE_CHECKING,
    Any,
)

from eneo.flows.ai_builder.ai_builder_domain_models import (
    BuilderPlan,
    ConversationMessage,
)
from eneo.flows.ai_builder.ai_builder_event_models import AIBuilderStreamEvent
from eneo.flows.ai_builder.ai_builder_output_sections_signals import (
    EMPTY_REQUESTED_OUTPUT_SECTIONS,
    RequestedOutputSections,
)
from eneo.flows.ai_builder.ai_builder_plan_edit_context import (
    AIBuilderPlanEditContext,
)
from eneo.flows.ai_builder.ai_builder_proposal_finalization import (
    CompiledProposalFinalizer,
)
from eneo.flows.ai_builder.ai_builder_proposal_submission import (
    ProposalSubmissionOwner,
)
from eneo.flows.ai_builder.ai_builder_proposal_telemetry import (
    ProposalTurnTelemetry,
)
from eneo.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    ProposalMessageGroup,
    ProposalRequestBudget,
)
from eneo.flows.ai_builder.ai_builder_repo import AIBuilderRepository
from eneo.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderResourceCatalog,
)
from eneo.flows.ai_builder.ai_builder_scoped_plan_revision import (
    ScopedPlanRevisionRequest,
    run_scoped_plan_revision_attempt,
)
from eneo.flows.ai_builder.ai_builder_session_turn import SessionSendTurn
from eneo.flows.ai_builder.planning_state import PlanningState
from eneo.flows.assistant_authoring_snapshot import AssistantAuthoringSnapshots
from eneo.main.logging import get_logger

if TYPE_CHECKING:
    from eneo.completion_models.infrastructure.completion_service import (
        ResolvedCompletionModelRoute,
    )
    from eneo.flows.domain.flow import Flow
    from eneo.users.user import UserInDB

logger = get_logger(__name__)


class AIBuilderProposalProcessor:
    def __init__(
        self,
        *,
        user: "UserInDB",
        repo: AIBuilderRepository,
        litellm_client: Any,
        self_correction_temperature: float,
        self_correction_bumped_temperature: float,
        forced_proposal_temperature: float,
        quality_retry_warning_codes: set[str],
        proposal_submission: ProposalSubmissionOwner | None = None,
    ) -> None:
        self.user = user
        self.repo = repo
        self.litellm_client = litellm_client
        self.self_correction_temperature = self_correction_temperature
        self.self_correction_bumped_temperature = self_correction_bumped_temperature
        self.forced_proposal_temperature = forced_proposal_temperature
        quality_retry_warning_code_set = frozenset(quality_retry_warning_codes)
        self._compiled_proposal_finalizer = CompiledProposalFinalizer(
            repo=repo,
            quality_retry_warning_codes=quality_retry_warning_code_set,
        )
        if proposal_submission is None:
            proposal_submission = ProposalSubmissionOwner(
                repo=repo,
                litellm_client=litellm_client,
                self_correction_temperature=self_correction_temperature,
                self_correction_bumped_temperature=self_correction_bumped_temperature,
                forced_proposal_temperature=forced_proposal_temperature,
                quality_retry_warning_codes=quality_retry_warning_code_set,
                compiled_proposal_finalizer=self._compiled_proposal_finalizer,
            )
        self._proposal_submission = proposal_submission

    async def propose_plan(
        self,
        *,
        turn: SessionSendTurn,
        conversation: list[ConversationMessage],
        new_messages_start: int,
        message_groups: tuple[ProposalMessageGroup, ...],
        completion_model_route: ResolvedCompletionModelRoute,
        available_model_refs: set[str] | None,
        available_kb_refs: set[str] | None,
        resource_catalog: AIBuilderResourceCatalog,
        max_output_tokens: int,
        proposal_temperature: float,
        request_id: str,
        usage_tracker: ProposalTurnTelemetry,
        flow: "Flow | None" = None,
        assistant_snapshots: AssistantAuthoringSnapshots | None = None,
        assistant_metadata: dict[str, Any] | None = None,
        planning_state: PlanningState | None = None,
        requested_output_sections: RequestedOutputSections = (
            EMPTY_REQUESTED_OUTPUT_SECTIONS
        ),
        plan_edit_context: AIBuilderPlanEditContext | None = None,
        prior_plan_for_revision: BuilderPlan | None = None,
        before_provider_call: Callable[[], Awaitable[None]] | None = None,
        proposal_request_budget: ProposalRequestBudget | None = None,
    ) -> AsyncGenerator[AIBuilderStreamEvent, None]:
        """Run the server-selected plan proposal task.

        This is deliberately narrower than the planner contract: the
        server already selected `propose_plan`, so the model only fills
        the create/edit tool payload.
        """

        if flow is None:
            scoped_revision_result = await run_scoped_plan_revision_attempt(
                request=ScopedPlanRevisionRequest(
                    turn=turn,
                    conversation=conversation,
                    new_messages_start=new_messages_start,
                    available_model_refs=available_model_refs,
                    available_kb_refs=available_kb_refs,
                    resource_catalog=resource_catalog,
                    plan_edit_context=plan_edit_context,
                    prior_plan_for_revision=prior_plan_for_revision,
                    request_id=request_id,
                    usage_tracker=usage_tracker,
                    requested_output_sections=requested_output_sections,
                    assistant_metadata=assistant_metadata,
                    flow=flow,
                ),
                finalizer=self._compiled_proposal_finalizer,
            )
            if scoped_revision_result is not None:
                for event in scoped_revision_result.events:
                    yield event
                return

        async for event in self._proposal_submission.run_active_submission_attempt(
            turn=turn,
            conversation=conversation,
            new_messages_start=new_messages_start,
            message_groups=message_groups,
            completion_model_route=completion_model_route,
            available_model_refs=available_model_refs,
            available_kb_refs=available_kb_refs,
            resource_catalog=resource_catalog,
            max_output_tokens=max_output_tokens,
            proposal_temperature=proposal_temperature,
            request_id=request_id,
            usage_tracker=usage_tracker,
            flow=flow,
            assistant_snapshots=assistant_snapshots,
            assistant_metadata=assistant_metadata,
            planning_state=planning_state,
            requested_output_sections=requested_output_sections,
            plan_edit_context=plan_edit_context,
            prior_plan_for_revision=prior_plan_for_revision,
            before_provider_call=before_provider_call,
            proposal_request_budget=proposal_request_budget,
        ):
            yield event
