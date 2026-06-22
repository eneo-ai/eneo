from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, AsyncGenerator, TypeAlias

from intric.flows.ai_builder.ai_builder_backend_question_persistence import (
    persist_backend_question,
)
from intric.flows.ai_builder.ai_builder_discovery import (
    build_registry_question_followup,
)
from intric.flows.ai_builder.ai_builder_discovery_runtime import (
    build_discovery_runtime_result,
)
from intric.flows.ai_builder.ai_builder_domain_models import ConversationMessage
from intric.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderErrorCode,
    AIBuilderErrorPhase,
    build_ai_builder_error_event,
)
from intric.flows.ai_builder.ai_builder_events import (
    build_status_event,
    build_text_event,
)
from intric.flows.ai_builder.ai_builder_framework_policy import (
    is_supported_structured_question_id,
    normalize_structured_question_payload,
)
from intric.flows.ai_builder.ai_builder_interaction_utils import (
    analyze_discovery_ready,
    build_question_fallback_text,
)
from intric.flows.ai_builder.ai_builder_litellm_completion import (
    call_proposal_completion,
)
from intric.flows.ai_builder.ai_builder_proposal_repair import (
    build_tool_retry_messages,
)
from intric.flows.ai_builder.ai_builder_proposal_telemetry import (
    ProposalTurnTelemetry,
    assistant_metadata_with_usage,
)
from intric.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    ProposalCompletionRequest,
)
from intric.flows.ai_builder.ai_builder_repo import AIBuilderRepository
from intric.flows.ai_builder.ai_builder_session_turn import SessionSendTurn
from intric.flows.ai_builder.ai_builder_tool_turn_persistence import (
    persist_tool_turn,
)
from intric.flows.ai_builder.ai_builder_tools import (
    ASK_STRUCTURED_QUESTION_TOOL_NAME,
    CONFIRM_REQUIREMENTS_TOOL_NAME,
    PROPOSE_FLOW_TOOL_NAME,
    build_discovery_complete_tool_schemas,
    parse_structured_question,
)
from intric.main.logging import get_logger

if TYPE_CHECKING:
    from intric.flows.domain.flow import Flow

logger = get_logger(__name__)
_QUESTION_RECOVERY_REQUEST_ID = "question-recovery"


@dataclass(frozen=True)
class StructuredQuestionRecoveryRequest:
    turn: SessionSendTurn
    conversation: list[ConversationMessage]
    new_messages_start: int
    llm_messages: list[dict[str, Any]]
    tool_call: Any
    tool_schemas: list[dict[str, Any]]
    litellm_model: str
    litellm_kwargs: dict[str, Any]
    max_output_tokens: int
    flow: Flow | None
    assistant_metadata: dict[str, Any] | None
    usage_tracker: ProposalTurnTelemetry | None


@dataclass(frozen=True)
class RecoveredToolDispatchRequest:
    tool_calls: list[Any]
    text_content: str | None
    llm_messages: list[dict[str, Any]]
    tool_schemas: list[dict[str, Any]]
    request_id: str


QuestionRecoveryItem: TypeAlias = dict[str, str] | RecoveredToolDispatchRequest


async def stream_structured_question_tool_call(
    *,
    repo: AIBuilderRepository,
    litellm_client: Any,
    self_correction_temperature: float,
    request: StructuredQuestionRecoveryRequest,
) -> AsyncGenerator[QuestionRecoveryItem, None]:
    # Self-correction can add or replace conversation context, so reuse of a
    # prepared discovery snapshot would risk asking a stale backend question.
    discovery_runtime = await build_discovery_runtime_result(
        request.conversation,
        flow=request.flow,
        litellm_client=litellm_client,
        litellm_model=request.litellm_model,
        litellm_kwargs=request.litellm_kwargs,
        tenant_id=request.turn.tenant_id,
    )
    if discovery_runtime.followup is not None:
        followup_result = await persist_backend_question(
            repo=repo,
            turn=request.turn,
            conversation=request.conversation,
            new_messages_start=request.new_messages_start,
            question=discovery_runtime.followup,
            flow=request.flow,
            assistant_metadata=assistant_metadata_with_usage(
                conversation=request.conversation,
                base_metadata=request.assistant_metadata,
                usage_tracker=request.usage_tracker,
                tool_calls=[{"name": ASK_STRUCTURED_QUESTION_TOOL_NAME}],
            ),
        )
        for event in followup_result.events:
            yield event
        return

    try:
        arguments = json.loads(request.tool_call.function.arguments)
    except json.JSONDecodeError as error:
        yield build_ai_builder_error_event(
            message=f"Invalid question: {error}",
            code=AIBuilderErrorCode.INVALID_QUESTION_PAYLOAD,
            phase=AIBuilderErrorPhase.QUESTION,
        )
        return

    try:
        question_data = parse_structured_question(arguments)
    except ValueError:
        fallback_text = build_question_fallback_text(arguments)
        if not fallback_text:
            yield build_ai_builder_error_event(
                message="Invalid question: could not build fallback prompt",
                code=AIBuilderErrorCode.INVALID_QUESTION_PAYLOAD,
                phase=AIBuilderErrorPhase.QUESTION,
            )
            return

        await persist_tool_turn(
            repo=repo,
            turn=request.turn,
            conversation=request.conversation,
            new_messages_start=request.new_messages_start,
            tool_call=request.tool_call,
            arguments=arguments,
            tool_content=(
                "Structured question payload was invalid; rendered fallback text question."
            ),
            assistant_metadata=assistant_metadata_with_usage(
                conversation=request.conversation,
                base_metadata=request.assistant_metadata,
                usage_tracker=request.usage_tracker,
                tool_calls=[request.tool_call],
            ),
            flow=request.flow,
        )
        yield build_text_event(fallback_text)
        return

    question_data = normalize_structured_question_payload(question_data)
    question_id = question_data["question_id"]
    registry_followup = (
        build_registry_question_followup(
            question_id,
            request.conversation,
            flow=request.flow,
        )
        if is_supported_structured_question_id(question_id)
        else None
    )
    if registry_followup is not None:
        persisted_question = await persist_backend_question(
            repo=repo,
            turn=request.turn,
            conversation=request.conversation,
            new_messages_start=request.new_messages_start,
            question=registry_followup,
            assistant_metadata=assistant_metadata_with_usage(
                conversation=request.conversation,
                base_metadata=request.assistant_metadata,
                usage_tracker=request.usage_tracker,
                tool_calls=[request.tool_call],
            ),
            tool_content=(
                "Backend-owned discovery question presented to user after model signal."
            ),
            flow=request.flow,
        )
        for event in persisted_question.events:
            yield event
        return

    async for item in _stream_non_question_continuation(
        repo=repo,
        litellm_client=litellm_client,
        self_correction_temperature=self_correction_temperature,
        request=request,
        original_question_id=question_id,
    ):
        yield item


async def _stream_non_question_continuation(
    *,
    repo: AIBuilderRepository,
    litellm_client: Any,
    self_correction_temperature: float,
    request: StructuredQuestionRecoveryRequest,
    original_question_id: str | None,
) -> AsyncGenerator[QuestionRecoveryItem, None]:
    submission_tool_name = PROPOSE_FLOW_TOOL_NAME
    filtered_tool_schemas = [
        schema
        for schema in request.tool_schemas
        if schema.get("function", {}).get("name") != ASK_STRUCTURED_QUESTION_TOOL_NAME
    ]
    discovery_ready = analyze_discovery_ready(request.conversation, flow=request.flow)
    if not filtered_tool_schemas:
        # No tool remains to repair the repeated question. Re-evaluate after
        # self-correction instead of threading an earlier discovery snapshot.
        discovery_runtime = await build_discovery_runtime_result(
            request.conversation,
            flow=request.flow,
            litellm_client=litellm_client,
            litellm_model=request.litellm_model,
            litellm_kwargs=request.litellm_kwargs,
            tenant_id=request.turn.tenant_id,
        )
        if discovery_runtime.followup is not None:
            followup_result = await persist_backend_question(
                repo=repo,
                turn=request.turn,
                conversation=request.conversation,
                new_messages_start=request.new_messages_start,
                question=discovery_runtime.followup,
                flow=request.flow,
                assistant_metadata=assistant_metadata_with_usage(
                    conversation=request.conversation,
                    base_metadata=None,
                    usage_tracker=request.usage_tracker,
                    tool_calls=[{"name": ASK_STRUCTURED_QUESTION_TOOL_NAME}],
                ),
            )
            for event in followup_result.events:
                yield event
            return

        if discovery_ready:
            filtered_tool_schemas = build_discovery_complete_tool_schemas()
        if not filtered_tool_schemas:
            yield build_ai_builder_error_event(
                message=(
                    "The AI planner lost track of the next clarification step. "
                    "Please try again."
                ),
                code=AIBuilderErrorCode.QUESTION_RECOVERY_UNAVAILABLE,
                phase=AIBuilderErrorPhase.QUESTION_RECOVERY,
            )
            return

    yield build_status_event("repairing")
    forced_tool_choice = (
        {"type": "function", "function": {"name": CONFIRM_REQUIREMENTS_TOOL_NAME}}
        if discovery_ready
        else None
    )
    correction_messages = build_tool_retry_messages(
        llm_messages=request.llm_messages,
        tool_call=request.tool_call,
        tool_feedback=(
            "Structured discovery questions are backend-owned. "
            f"Do not call {ASK_STRUCTURED_QUESTION_TOOL_NAME} again"
            + (
                f" for question_id '{original_question_id}'."
                if original_question_id
                else "."
            )
            + " Continue without inventing a new user-facing question. "
            "If enough information exists, call confirm_requirements. "
            f"If requirements are already confirmed, call {submission_tool_name}. "
            "Otherwise ask for clarification in concise free text only."
        ),
    )

    retries_remaining = 1
    active_messages = correction_messages
    while True:
        try:
            response = await call_proposal_completion(
                litellm_client=litellm_client,
                usage_tracker=request.usage_tracker,
                request=ProposalCompletionRequest(
                    messages=active_messages,
                    tool_schemas=filtered_tool_schemas,
                    litellm_model=request.litellm_model,
                    litellm_kwargs=request.litellm_kwargs,
                    max_output_tokens=request.max_output_tokens,
                    temperature=self_correction_temperature,
                    tool_choice=forced_tool_choice,
                    counts_as_repair=True,
                ),
            )
        except Exception as error:
            logger.error(
                "Unexpected structured-question continuation retry failed",
                exc_info=error,
            )
            yield build_ai_builder_error_event(
                message="The AI planner failed. Please try again.",
                code=AIBuilderErrorCode.PLANNER_UPSTREAM_ERROR,
                phase=AIBuilderErrorPhase.QUESTION_RECOVERY,
            )
            return

        if not response.choices:
            yield build_ai_builder_error_event(
                message=(
                    "The AI planner failed to return a valid clarification "
                    "repair. Please try again."
                ),
                code=AIBuilderErrorCode.PLANNER_INVALID_REPAIR_RESPONSE,
                phase=AIBuilderErrorPhase.QUESTION_RECOVERY,
            )
            return

        message = response.choices[0].message
        tool_calls = message.tool_calls if hasattr(message, "tool_calls") else None
        if tool_calls:
            repeated_question_call = next(
                (
                    tc
                    for tc in tool_calls
                    if tc.function.name == ASK_STRUCTURED_QUESTION_TOOL_NAME
                ),
                None,
            )
            if repeated_question_call is not None:
                if retries_remaining <= 0:
                    yield build_ai_builder_error_event(
                        message=(
                            "The AI planner kept proposing unsupported discovery "
                            "questions."
                        ),
                        code=AIBuilderErrorCode.QUESTION_RECOVERY_EXHAUSTED,
                        phase=AIBuilderErrorPhase.QUESTION_RECOVERY,
                    )
                    return
                retries_remaining -= 1
                active_messages = build_tool_retry_messages(
                    llm_messages=active_messages,
                    tool_call=repeated_question_call,
                    assistant_content=message.content,
                    tool_feedback=(
                        "Structured discovery questions remain backend-owned. "
                        "Do not call ask_structured_question. "
                        f"Continue with confirm_requirements, {submission_tool_name}, "
                        "or concise free text only."
                    ),
                )
                continue

            yield RecoveredToolDispatchRequest(
                tool_calls=list(tool_calls),
                text_content=message.content,
                llm_messages=active_messages,
                tool_schemas=filtered_tool_schemas,
                request_id=_QUESTION_RECOVERY_REQUEST_ID,
            )
            return

        if message.content:
            yield build_text_event(message.content)
        return
