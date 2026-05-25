from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID

from intric.flows.ai_builder.ai_builder_backend_question_persistence import (
    persist_backend_question,
)
from intric.flows.ai_builder.ai_builder_conversation_metadata import (
    make_persisted_assistant_tool_call,
    requirements_summary_to_metadata,
)
from intric.flows.ai_builder.ai_builder_discovery_runtime import (
    DiscoveryRuntimeResult,
    build_discovery_runtime_result,
)
from intric.flows.ai_builder.ai_builder_domain_models import ConversationMessage
from intric.flows.ai_builder.ai_builder_event_models import (
    RequirementsSummaryPayload,
)
from intric.flows.ai_builder.ai_builder_events import (
    build_requirements_summary_event,
)
from intric.flows.ai_builder.ai_builder_framework_policy import (
    normalize_requirements_summary_for_flow,
)
from intric.flows.ai_builder.ai_builder_proposal_policy import resolve_ui_language
from intric.flows.ai_builder.ai_builder_proposal_telemetry import (
    ProposalTurnTelemetry,
    assistant_metadata_with_usage,
)
from intric.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    ToolProcessingResult,
    ToolRetryConfig,
    ToolRetryInvocation,
)
from intric.flows.ai_builder.ai_builder_repo import AIBuilderRepository
from intric.flows.ai_builder.ai_builder_requirements_state import (
    build_requirements_version,
)
from intric.flows.ai_builder.ai_builder_session_turn import SessionSendTurn
from intric.flows.ai_builder.ai_builder_tool_turn_persistence import persist_tool_turn
from intric.flows.ai_builder.ai_builder_tools import (
    ASK_STRUCTURED_QUESTION_TOOL_NAME,
    CONFIRM_REQUIREMENTS_TOOL_NAME,
    parse_confirm_requirements,
)

if TYPE_CHECKING:
    from intric.flows.domain.flow import Flow


@dataclass(frozen=True, slots=True)
class ConfirmRequirementsProcessingRequest:
    repo: AIBuilderRepository
    turn: SessionSendTurn
    conversation: list[ConversationMessage]
    new_messages_start: int
    arguments: dict[str, Any]
    tool_call_id: str
    flow: "Flow | None"
    litellm_client: Any
    litellm_model: str
    litellm_kwargs: dict[str, Any]
    tenant_id: UUID
    assistant_metadata: dict[str, Any] | None = None
    usage_tracker: ProposalTurnTelemetry | None = None
    allow_discovery_followup: bool = False
    discovery_runtime: DiscoveryRuntimeResult | None = None


@dataclass(frozen=True, slots=True)
class ConfirmRequirementsRetryConfigRequest:
    repo: AIBuilderRepository
    litellm_client: Any
    tenant_id: UUID
    litellm_model: str
    litellm_kwargs: dict[str, Any]


async def process_confirm_requirements(
    request: ConfirmRequirementsProcessingRequest,
) -> ToolProcessingResult:
    try:
        requirements_data = parse_confirm_requirements(request.arguments)
    except ValueError as error:
        return ToolProcessingResult(
            feedback=f"Invalid requirements summary: {error}",
            failure_kind="parse",
        )

    discovery_runtime = (
        request.discovery_runtime
        or await build_discovery_runtime_result(
            request.conversation,
            flow=request.flow,
            litellm_client=request.litellm_client,
            litellm_model=request.litellm_model,
            litellm_kwargs=request.litellm_kwargs,
            tenant_id=request.tenant_id,
        )
    )
    discovery_block_message = discovery_runtime.discovery_block_message
    discovery_analysis = discovery_runtime.discovery_analysis
    if discovery_block_message is not None:
        if request.allow_discovery_followup and discovery_runtime.followup is not None:
            followup_result = await persist_backend_question(
                repo=request.repo,
                turn=request.turn,
                conversation=request.conversation,
                new_messages_start=request.new_messages_start,
                question=discovery_runtime.followup,
                flow=request.flow,
                assistant_metadata=assistant_metadata_with_usage(
                    conversation=request.conversation,
                    base_metadata=request.assistant_metadata,
                    usage_tracker=request.usage_tracker,
                    # Backend-owned follow-ups still need a tool marker so
                    # persisted metadata explains the emitted question.
                    tool_calls=[{"name": ASK_STRUCTURED_QUESTION_TOOL_NAME}],
                ),
            )
            return ToolProcessingResult(
                events=tuple(followup_result.events),
                new_planning_state_version=followup_result.new_planning_state_version,
            )
        return ToolProcessingResult(
            feedback=discovery_block_message,
            failure_kind="validation",
        )

    merged_assumptions = list(
        dict.fromkeys(
            [
                *discovery_analysis.assumptions,
                *requirements_data.get("assumptions", []),
            ]
        )
    )
    requirements_data["assumptions"] = merged_assumptions
    requirements_data = normalize_requirements_summary_for_flow(
        requirements_data,
        conversation=request.conversation,
        flow=request.flow,
        language=resolve_ui_language(request.conversation),
    )

    requirements_payload_model = RequirementsSummaryPayload.model_validate(
        requirements_data
    )
    requirements_version = build_requirements_version(requirements_payload_model)
    requirements_payload = requirements_payload_model.model_copy(
        update={"requirements_version": requirements_version},
        deep=True,
    )

    tool_call = make_persisted_assistant_tool_call(
        tool_call_id=request.tool_call_id,
        tool_name=CONFIRM_REQUIREMENTS_TOOL_NAME,
        arguments=request.arguments,
    )
    new_version = await persist_tool_turn(
        repo=request.repo,
        turn=request.turn,
        conversation=request.conversation,
        new_messages_start=request.new_messages_start,
        tool_call=tool_call,
        arguments=request.arguments,
        tool_content="Requirements presented to user. Awaiting confirmation.",
        metadata=requirements_summary_to_metadata(requirements_payload),
        assistant_metadata=request.assistant_metadata,
        flow=request.flow,
    )
    return ToolProcessingResult(
        event=build_requirements_summary_event(
            requirements_payload.model_dump(mode="json", exclude_none=True)
        ),
        new_planning_state_version=new_version,
    )


def build_confirm_requirements_retry_config(
    request: ConfirmRequirementsRetryConfigRequest,
) -> ToolRetryConfig:
    async def _process_tool_invocation(
        invocation: ToolRetryInvocation,
    ) -> ToolProcessingResult:
        return await process_confirm_requirements(
            ConfirmRequirementsProcessingRequest(
                repo=request.repo,
                turn=invocation.turn,
                conversation=invocation.conversation,
                new_messages_start=invocation.new_messages_start,
                arguments=invocation.arguments,
                tool_call_id=invocation.tool_call_id,
                flow=invocation.flow,
                litellm_client=request.litellm_client,
                litellm_model=request.litellm_model,
                litellm_kwargs=request.litellm_kwargs,
                tenant_id=request.tenant_id,
                assistant_metadata=invocation.assistant_metadata,
            )
        )

    return ToolRetryConfig(
        target_tool_name=CONFIRM_REQUIREMENTS_TOOL_NAME,
        forced_tool_prompt=(
            "Return one valid confirm_requirements tool call. Do not answer with prose."
        ),
        process_tool_invocation=_process_tool_invocation,
    )
