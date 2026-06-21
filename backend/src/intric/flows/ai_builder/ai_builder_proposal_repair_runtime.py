from __future__ import annotations

from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from intric.flows.ai_builder.ai_builder_architecture_errors import (
    AIBuilderArchitectureError,
    build_proposal_architecture_error_event,
    record_proposal_architecture_failure,
)
from intric.flows.ai_builder.ai_builder_domain_models import ConversationMessage
from intric.flows.ai_builder.ai_builder_proposal_repair import (
    ForcedToolRetryOutcome,
    request_self_correction,
    retry_forced_tool_after_text,
)
from intric.flows.ai_builder.ai_builder_proposal_telemetry import (
    ProposalTurnTelemetry,
    assistant_metadata_with_usage,
)
from intric.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    ProposalCompletionFn,
    ProposalTurnContext,
    ToolRetryConfig,
)
from intric.flows.ai_builder.ai_builder_resource_catalog import AIBuilderResourceCatalog
from intric.flows.ai_builder.ai_builder_session_turn import SessionSendTurn

if TYPE_CHECKING:
    from intric.flows.domain.flow import Flow

MAX_SELF_CORRECTION_RETRIES = 3


@dataclass(frozen=True, slots=True)
class ProposalSelfCorrectionRequest:
    turn: SessionSendTurn
    request_id: str
    conversation: list[ConversationMessage]
    new_messages_start: int
    error_message: str
    llm_messages: list[dict[str, Any]]
    tool_call: Any
    tool_schemas: list[dict[str, Any]]
    litellm_model: str
    litellm_kwargs: dict[str, Any]
    available_model_refs: set[str] | None
    available_kb_refs: set[str] | None
    max_output_tokens: int
    self_correction_temperature: float
    self_correction_bumped_temperature: float
    max_self_correction_retries: int
    repair_completion: ProposalCompletionFn
    retry_config: ToolRetryConfig
    forced_proposal_temperature: float
    resource_catalog: AIBuilderResourceCatalog | None = None
    flow: "Flow | None" = None
    build_assistant_metadata: Callable[[], dict[str, Any] | None] | None = None
    usage_tracker: ProposalTurnTelemetry | None = None


@dataclass(frozen=True, slots=True)
class ForcedToolAfterTextRequest:
    correction_messages: list[dict[str, Any]]
    assistant_text: str
    tool_schemas: list[dict[str, Any]]
    litellm_model: str
    litellm_kwargs: dict[str, Any]
    turn: SessionSendTurn
    conversation: list[ConversationMessage]
    new_messages_start: int
    available_model_refs: set[str] | None
    available_kb_refs: set[str] | None
    max_output_tokens: int
    retry_config: ToolRetryConfig
    forced_proposal_temperature: float
    repair_completion: ProposalCompletionFn
    resource_catalog: AIBuilderResourceCatalog | None = None
    flow: "Flow | None" = None
    build_assistant_metadata: Callable[[], dict[str, Any] | None] | None = None
    request_id: str | None = None
    usage_tracker: ProposalTurnTelemetry | None = None


def build_proposal_self_correction_request(
    *,
    ctx: ProposalTurnContext,
    error_message: str,
    tool_call: Any,
    retry_config: ToolRetryConfig,
    self_correction_temperature: float,
    self_correction_bumped_temperature: float,
    forced_proposal_temperature: float,
    repair_completion: ProposalCompletionFn,
) -> ProposalSelfCorrectionRequest:
    return ProposalSelfCorrectionRequest(
        turn=ctx.turn,
        request_id=ctx.request_id,
        conversation=ctx.conversation,
        new_messages_start=ctx.new_messages_start,
        error_message=error_message,
        llm_messages=ctx.llm_messages,
        tool_call=tool_call,
        tool_schemas=ctx.tool_schemas,
        litellm_model=ctx.litellm_model,
        litellm_kwargs=ctx.litellm_kwargs,
        available_model_refs=ctx.available_model_refs,
        available_kb_refs=ctx.available_kb_refs,
        max_output_tokens=ctx.max_output_tokens,
        self_correction_temperature=self_correction_temperature,
        self_correction_bumped_temperature=self_correction_bumped_temperature,
        max_self_correction_retries=MAX_SELF_CORRECTION_RETRIES,
        repair_completion=repair_completion,
        retry_config=retry_config,
        forced_proposal_temperature=forced_proposal_temperature,
        resource_catalog=ctx.resource_catalog,
        flow=ctx.flow,
        build_assistant_metadata=lambda: assistant_metadata_with_usage(
            conversation=ctx.conversation,
            base_metadata=ctx.assistant_metadata,
            usage_tracker=ctx.usage_tracker,
        ),
        usage_tracker=ctx.usage_tracker,
    )


async def run_tool_self_correction(
    request: ProposalSelfCorrectionRequest,
) -> AsyncGenerator[dict[str, str], None]:
    try:
        async for event in request_self_correction(
            turn=request.turn,
            request_id=request.request_id,
            conversation=request.conversation,
            new_messages_start=request.new_messages_start,
            error_message=request.error_message,
            llm_messages=request.llm_messages,
            tool_call=request.tool_call,
            tool_schemas=request.tool_schemas,
            litellm_model=request.litellm_model,
            litellm_kwargs=request.litellm_kwargs,
            available_model_refs=request.available_model_refs,
            available_kb_refs=request.available_kb_refs,
            max_output_tokens=request.max_output_tokens,
            self_correction_temperature=request.self_correction_temperature,
            self_correction_bumped_temperature=(
                request.self_correction_bumped_temperature
            ),
            max_self_correction_retries=request.max_self_correction_retries,
            forced_proposal_temperature=request.forced_proposal_temperature,
            call_proposal_completion=request.repair_completion,
            process_tool_invocation=request.retry_config.process_tool_invocation,
            target_tool_name=request.retry_config.target_tool_name,
            target_kind=request.retry_config.target_kind,
            forced_tool_prompt=request.retry_config.forced_tool_prompt,
            resource_catalog=request.resource_catalog,
            flow=request.flow,
            build_assistant_metadata=request.build_assistant_metadata,
        ):
            yield event
    except AIBuilderArchitectureError as error:
        record_proposal_architecture_failure(
            request.usage_tracker,
            request_id=request.request_id,
            tool_name=request.retry_config.target_tool_name,
        )
        yield build_proposal_architecture_error_event(
            error,
            request_id=request.request_id,
            tool_name=request.retry_config.target_tool_name,
        )


async def run_forced_tool_retry_after_text(
    request: ForcedToolAfterTextRequest,
) -> ForcedToolRetryOutcome:
    try:
        return await retry_forced_tool_after_text(
            correction_messages=request.correction_messages,
            assistant_text=request.assistant_text,
            tool_schemas=request.tool_schemas,
            litellm_model=request.litellm_model,
            litellm_kwargs=request.litellm_kwargs,
            turn=request.turn,
            conversation=request.conversation,
            new_messages_start=request.new_messages_start,
            available_model_refs=request.available_model_refs,
            available_kb_refs=request.available_kb_refs,
            max_output_tokens=request.max_output_tokens,
            target_tool_name=request.retry_config.target_tool_name,
            forced_tool_prompt=request.retry_config.forced_tool_prompt,
            forced_proposal_temperature=request.forced_proposal_temperature,
            call_proposal_completion=request.repair_completion,
            process_tool_invocation=request.retry_config.process_tool_invocation,
            resource_catalog=request.resource_catalog,
            flow=request.flow,
            build_assistant_metadata=request.build_assistant_metadata,
            request_id=request.request_id,
        )
    except AIBuilderArchitectureError as error:
        resolved_request_id = request.request_id or (
            request.usage_tracker.request_id
            if request.usage_tracker is not None
            else None
        )
        record_proposal_architecture_failure(
            request.usage_tracker,
            request_id=resolved_request_id,
            tool_name=request.retry_config.target_tool_name,
        )
        return ForcedToolRetryOutcome(
            events=(
                build_proposal_architecture_error_event(
                    error,
                    request_id=resolved_request_id,
                    tool_name=request.retry_config.target_tool_name,
                ),
            )
        )
