from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import (
    TYPE_CHECKING,
    Any,
)

from intric.flows.ai_builder.ai_builder_backend_question_persistence import (
    BackendQuestionPersistenceResult,
    persist_backend_question,
)
from intric.flows.ai_builder.ai_builder_discovery_models import BackendQuestion
from intric.flows.ai_builder.ai_builder_discovery_runtime import DiscoveryRuntimeResult
from intric.flows.ai_builder.ai_builder_domain_models import (
    BuilderPlan,
    ConversationMessage,
)
from intric.flows.ai_builder.ai_builder_event_models import AIBuilderStreamEvent
from intric.flows.ai_builder.ai_builder_mcp_intent import (
    build_mcp_resource_selection_question,
    find_named_mcp_request_issue,
    mcp_selection_answer_allows_planning,
)
from intric.flows.ai_builder.ai_builder_plan_edit_context import (
    AIBuilderPlanEditContext,
)
from intric.flows.ai_builder.ai_builder_proposal_policy import (
    resolve_ui_language,
)
from intric.flows.ai_builder.ai_builder_proposal_submission import (
    ProposalSubmissionOwner,
)
from intric.flows.ai_builder.ai_builder_proposal_tool_contracts import LLMMessageParam
from intric.flows.ai_builder.ai_builder_repo import AIBuilderRepository
from intric.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderResourceCatalog,
)
from intric.flows.ai_builder.ai_builder_session_turn import SessionSendTurn
from intric.flows.ai_builder.planning_state import PlanningState
from intric.flows.assistant_authoring_snapshot import AssistantAuthoringSnapshots
from intric.main.logging import get_logger

if TYPE_CHECKING:
    from intric.flows.domain.flow import Flow
    from intric.users.user import UserInDB

logger = get_logger(__name__)


def _conversation_user_text(conversation: list[ConversationMessage]) -> str:
    return "\n".join(
        message.content
        for message in conversation
        if message.role == "user" and message.content
    )


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
        if proposal_submission is None:
            proposal_submission = ProposalSubmissionOwner(
                repo=repo,
                litellm_client=litellm_client,
                self_correction_temperature=self_correction_temperature,
                self_correction_bumped_temperature=self_correction_bumped_temperature,
                forced_proposal_temperature=forced_proposal_temperature,
                quality_retry_warning_codes=frozenset(quality_retry_warning_codes),
            )
        self._proposal_submission = proposal_submission

    async def propose_plan(
        self,
        *,
        turn: SessionSendTurn,
        conversation: list[ConversationMessage],
        new_messages_start: int,
        llm_messages: list[LLMMessageParam],
        litellm_model: str,
        litellm_kwargs: dict[str, Any],
        available_model_refs: set[str] | None,
        available_kb_refs: set[str] | None,
        resource_catalog: AIBuilderResourceCatalog,
        max_output_tokens: int,
        proposal_temperature: float,
        request_id: str,
        flow: "Flow | None" = None,
        assistant_snapshots: AssistantAuthoringSnapshots | None = None,
        assistant_metadata: dict[str, Any] | None = None,
        planning_state: PlanningState | None = None,
        plan_edit_context: AIBuilderPlanEditContext | None = None,
        prior_plan_for_revision: BuilderPlan | None = None,
        discovery_runtime: DiscoveryRuntimeResult | None = None,
    ) -> AsyncGenerator[AIBuilderStreamEvent, None]:
        """Run the server-selected plan proposal task.

        This is deliberately narrower than the planner contract: the
        server already selected `propose_plan`, so the model only fills
        the create/edit tool payload.
        """

        mcp_preflight_result = await self._mcp_preflight_events_if_needed(
            turn=turn,
            conversation=conversation,
            new_messages_start=new_messages_start,
            resource_catalog=resource_catalog,
            flow=flow,
            assistant_metadata=assistant_metadata,
        )
        if mcp_preflight_result is not None:
            for event in mcp_preflight_result.events:
                yield event
            return

        async for event in self._proposal_submission.run_active_submission_attempt(
            turn=turn,
            conversation=conversation,
            new_messages_start=new_messages_start,
            llm_messages=llm_messages,
            litellm_model=litellm_model,
            litellm_kwargs=litellm_kwargs,
            available_model_refs=available_model_refs,
            available_kb_refs=available_kb_refs,
            resource_catalog=resource_catalog,
            max_output_tokens=max_output_tokens,
            proposal_temperature=proposal_temperature,
            request_id=request_id,
            flow=flow,
            assistant_snapshots=assistant_snapshots,
            assistant_metadata=assistant_metadata,
            planning_state=planning_state,
            plan_edit_context=plan_edit_context,
            prior_plan_for_revision=prior_plan_for_revision,
            discovery_runtime=discovery_runtime,
        ):
            yield event

    async def _mcp_preflight_events_if_needed(
        self,
        *,
        turn: SessionSendTurn,
        conversation: list[ConversationMessage],
        new_messages_start: int,
        resource_catalog: AIBuilderResourceCatalog | None,
        flow: "Flow | None",
        assistant_metadata: dict[str, Any] | None,
    ) -> BackendQuestionPersistenceResult | None:
        if resource_catalog is None or mcp_selection_answer_allows_planning(
            conversation
        ):
            return None

        issue = find_named_mcp_request_issue(
            catalog=resource_catalog,
            signal_text=_conversation_user_text(conversation),
        )
        if issue is None:
            return None

        question_data, assistant_text = build_mcp_resource_selection_question(
            issue=issue,
            catalog=resource_catalog,
            language=resolve_ui_language(conversation) or "sv",
        )
        logger.info(
            "ai_builder_mcp_preflight_requires_clarification "
            "session_id=%s requested_mcp=%s",
            turn.session_id,
            issue.requested_name,
        )
        return await persist_backend_question(
            repo=self.repo,
            turn=turn,
            conversation=conversation,
            new_messages_start=new_messages_start,
            question=BackendQuestion(
                question_data=question_data,
                assistant_text=assistant_text,
            ),
            assistant_metadata=assistant_metadata,
            tool_content=(
                "MCP selection question presented before proposal because the user "
                "requested an MCP by name and must choose from enabled space MCP resources."
            ),
            flow=flow,
        )
