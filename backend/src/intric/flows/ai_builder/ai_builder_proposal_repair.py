from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from dataclasses import dataclass, replace
from typing import Any, cast
from uuid import uuid4

from intric.flows.ai_builder.ai_builder_architecture_errors import (
    AIBuilderArchitectureError,
    build_proposal_architecture_error_event,
    record_proposal_architecture_failure,
)
from intric.flows.ai_builder.ai_builder_conversation_metadata import (
    RuntimeToolCall,
    provider_safe_tool_call_id,
)
from intric.flows.ai_builder.ai_builder_domain_models import TargetKind
from intric.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderErrorCode,
    AIBuilderErrorPhase,
    build_ai_builder_error_event,
)
from intric.flows.ai_builder.ai_builder_events import (
    build_status_event,
    build_text_event,
)
from intric.flows.ai_builder.ai_builder_interaction_utils import (
    looks_like_information_request,
)
from intric.flows.ai_builder.ai_builder_litellm_completion import (
    LLMCompletionToolCall,
)
from intric.flows.ai_builder.ai_builder_proposal_telemetry import (
    ProposalTurnTelemetry,
    ToolProcessingFailureKind,
    assistant_metadata_with_usage,
)
from intric.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    ProposalCompletionFn,
    ProposalTurnContext,
    ToolProcessingResult,
    ToolRetryConfig,
    ToolRetryInvocation,
)
from intric.flows.ai_builder.ai_builder_tool_parsing import (
    ToolArgumentParseError,
    parse_tool_call_arguments,
)
from intric.flows.ai_builder.ai_builder_tools import PROPOSE_FLOW_TOOL_NAME
from intric.main.logging import get_logger

logger = get_logger(__name__)
EventBatch = tuple[dict[str, str], ...]
MAX_SELF_CORRECTION_RETRIES = 3


@dataclass(frozen=True, slots=True)
class ForcedToolRetryOutcome:
    events: EventBatch | None = None
    feedback: str | None = None
    failure_kind: ToolProcessingFailureKind | None = None


@dataclass(frozen=True, slots=True)
class ProposalSelfCorrectionRequest:
    ctx: ProposalTurnContext
    error_message: str
    tool_call: RuntimeToolCall
    self_correction_temperature: float
    self_correction_bumped_temperature: float
    max_self_correction_retries: int
    repair_completion: ProposalCompletionFn
    retry_config: ToolRetryConfig
    forced_proposal_temperature: float


@dataclass(frozen=True, slots=True)
class ForcedToolAfterTextRequest:
    ctx: ProposalTurnContext
    correction_messages: list[dict[str, Any]]
    assistant_text: str
    retry_config: ToolRetryConfig
    forced_proposal_temperature: float
    repair_completion: ProposalCompletionFn


@dataclass(frozen=True, slots=True)
class _ProposalRepairRetryState:
    attempts_remaining: int
    text_feedback_retry_available: bool = True
    retry_count: int = 0

    @classmethod
    def initial(cls, *, max_attempts: int) -> "_ProposalRepairRetryState":
        return cls(attempts_remaining=max_attempts)

    @property
    def use_bumped_temperature(self) -> bool:
        return self.retry_count >= 1

    @property
    def next_retry_count(self) -> int:
        return self.retry_count + 1

    def can_retry(self) -> bool:
        return self.attempts_remaining > 0

    def can_retry_text_feedback(self) -> bool:
        return self.text_feedback_retry_available and self.can_retry()

    def consume(self) -> "_ProposalRepairRetryState":
        if self.attempts_remaining > 0:
            return replace(
                self,
                attempts_remaining=self.attempts_remaining - 1,
                retry_count=self.retry_count + 1,
            )
        return self

    def consume_text_feedback(self) -> "_ProposalRepairRetryState":
        return replace(
            self.consume(),
            text_feedback_retry_available=False,
        )


def _invalid_tool_arguments_message(error: Exception) -> str:
    return f"Invalid tool call arguments: {error}"


def build_self_correction_error_event(
    *,
    feedback: str | None,
    failure_kind: ToolProcessingFailureKind | None,
    request_id: str | None = None,
) -> dict[str, str]:
    message = _self_correction_user_message(
        feedback=feedback,
        failure_kind=failure_kind,
    )
    if failure_kind == "parse":
        code = AIBuilderErrorCode.SELF_CORRECTION_INVALID_PAYLOAD
    elif failure_kind == "quality":
        code = AIBuilderErrorCode.SELF_CORRECTION_QUALITY_FAILURE
    else:
        code = AIBuilderErrorCode.SELF_CORRECTION_INVALID_PLAN
    return build_ai_builder_error_event(
        message=message,
        code=code,
        phase=AIBuilderErrorPhase.SELF_CORRECTION,
        request_id=request_id,
    )


def _self_correction_user_message(
    *,
    feedback: str | None,
    failure_kind: ToolProcessingFailureKind | None,
) -> str:
    details = (feedback or "").casefold()
    if failure_kind == "parse":
        return (
            "The AI Builder returned an incomplete plan configuration and could "
            "not repair it automatically. Try again, or use a more capable model "
            "if the same error repeats."
        )
    if "flow must have at least one step" in details or "empty_steps" in details:
        return (
            "The corrected plan did not contain any flow steps. Ask for at least "
            "one concrete step, such as transcribing audio or summarizing text, "
            "then try again."
        )
    if "input_source 'flow_input'" in details or "first step" in details:
        return (
            "The corrected plan still could not connect the flow input to the "
            "first step. For audio or file flows, the first step must receive the "
            "uploaded file at runtime before later steps analyze the result."
        )
    if failure_kind == "quality":
        return (
            "The corrected plan still failed the AI Builder quality checks. "
            "Revise the request with the exact input, output, and main steps you "
            "want, then try again."
        )
    return (
        "The corrected plan is still not a valid flow. Revise the request with "
        "the input, output, and the concrete steps the flow should contain, then "
        "try again."
    )


def _repair_terminal_events(result: ToolProcessingResult) -> EventBatch:
    user_message_events = (
        (build_text_event(result.user_message),)
        if result.user_message is not None
        else tuple()
    )
    if result.event is None:
        return (*result.events, *user_message_events)
    return (result.event, *result.events, *user_message_events)


def _build_tool_retry_invocation(
    *,
    ctx: ProposalTurnContext,
    arguments: dict[str, Any],
    assistant_content: str,
    tool_call_id: str,
) -> ToolRetryInvocation:
    return ToolRetryInvocation(
        turn=ctx.turn,
        conversation=ctx.conversation,
        new_messages_start=ctx.new_messages_start,
        arguments=arguments,
        assistant_content=assistant_content,
        tool_call_id=tool_call_id,
        available_model_refs=ctx.available_model_refs,
        available_kb_refs=ctx.available_kb_refs,
        resource_catalog=ctx.resource_catalog,
        flow=ctx.flow,
        assistant_metadata=assistant_metadata_with_usage(
            conversation=ctx.conversation,
            base_metadata=ctx.assistant_metadata,
            usage_tracker=ctx.usage_tracker,
        ),
    )


def build_tool_retry_messages(
    *,
    llm_messages: list[dict[str, Any]],
    tool_call: RuntimeToolCall,
    tool_feedback: str,
    assistant_content: str | None = None,
) -> list[dict[str, Any]]:
    tool_call_id = provider_safe_tool_call_id(tool_call.id)
    return list(llm_messages) + [
        {
            "role": "assistant",
            "content": assistant_content,
            "tool_calls": [
                {
                    "id": tool_call_id,
                    "type": "function",
                    "function": {
                        "name": tool_call.function.name,
                        "arguments": tool_call.function.arguments,
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": tool_feedback,
        },
    ]


def append_text_retry_feedback_turn(
    *,
    llm_messages: list[dict[str, Any]],
    assistant_content: str,
    feedback: str,
) -> list[dict[str, Any]]:
    return list(llm_messages) + [
        {"role": "assistant", "content": assistant_content},
        {"role": "user", "content": feedback},
    ]


def _build_retry_feedback(
    *,
    target_tool_name: str,
    target_kind: TargetKind,
    feedback: str,
    failure_codes: frozenset[str] = frozenset(),
    retry_count: int = 1,
) -> str:
    suffix = f"Keep valid parts and fix only the listed issues. Return one complete {target_tool_name} call."
    # target_kind is session-scoped; outline repair rules only belong to propose_flow.
    if target_tool_name == PROPOSE_FLOW_TOOL_NAME and target_kind == TargetKind.CREATE:
        outline_rules = [
            "Every steps[] item must be one complete semantic outline step with at least name and task.",
            "Runtime form inputs belong in top-level input_fields[], and steps should reference them by name in uses_input_fields.",
            "Do not emit input_source, input_type, input_bindings, output_mode, refs, ids, hashes, or timestamps; backend compiles those mechanics.",
        ]
        if "duplicate_step_name" in failure_codes:
            outline_rules.append(
                "Every steps[] name must be unique case-insensitively; rename duplicate semantic steps with specific labels."
            )
        suffix = (
            " ".join(outline_rules)
            + f" Keep valid semantic parts and fix only the listed issues. Return one complete {target_tool_name} call."
        )
    if retry_count >= 2:
        preamble = (
            "FINAL CORRECTION ATTEMPT — earlier repairs have failed. "
            "Before responding, identify the exact field or rule named in the failure below "
            "and fix only that. Do not rewrite unrelated parts"
        )
    else:
        preamble = "CORRECTION STILL INVALID"
    return f"{preamble}: {feedback}\n{suffix}"


def build_proposal_self_correction_request(
    *,
    ctx: ProposalTurnContext,
    error_message: str,
    tool_call: RuntimeToolCall,
    retry_config: ToolRetryConfig,
    self_correction_temperature: float,
    self_correction_bumped_temperature: float,
    forced_proposal_temperature: float,
    repair_completion: ProposalCompletionFn,
) -> ProposalSelfCorrectionRequest:
    return ProposalSelfCorrectionRequest(
        ctx=ctx,
        error_message=error_message,
        tool_call=tool_call,
        self_correction_temperature=self_correction_temperature,
        self_correction_bumped_temperature=self_correction_bumped_temperature,
        max_self_correction_retries=MAX_SELF_CORRECTION_RETRIES,
        repair_completion=repair_completion,
        retry_config=retry_config,
        forced_proposal_temperature=forced_proposal_temperature,
    )


async def run_tool_self_correction(
    request: ProposalSelfCorrectionRequest,
) -> AsyncGenerator[dict[str, str], None]:
    try:
        async for event in _request_self_correction_events(request):
            yield event
    except AIBuilderArchitectureError as error:
        for event in _architecture_error_events(
            error=error,
            usage_tracker=request.ctx.usage_tracker,
            request_id=request.ctx.request_id,
            tool_name=request.retry_config.target_tool_name,
        ):
            yield event


def _architecture_error_events(
    *,
    error: AIBuilderArchitectureError,
    usage_tracker: ProposalTurnTelemetry | None,
    request_id: str | None,
    tool_name: str,
) -> EventBatch:
    record_proposal_architecture_failure(
        usage_tracker,
        request_id=request_id,
        tool_name=tool_name,
    )
    return (
        build_proposal_architecture_error_event(
            error,
            request_id=request_id,
            tool_name=tool_name,
        ),
    )


async def _request_self_correction_events(
    request: ProposalSelfCorrectionRequest,
) -> AsyncGenerator[dict[str, str], None]:
    ctx = request.ctx
    retry_config = request.retry_config
    yield build_status_event("repairing")
    correction_messages = build_tool_retry_messages(
        llm_messages=ctx.llm_messages,
        tool_call=request.tool_call,
        tool_feedback=(
            f"VALIDATION FAILED: {request.error_message}. Please fix and try again."
        ),
    )

    retry_state = _ProposalRepairRetryState.initial(
        max_attempts=request.max_self_correction_retries
    )
    while True:
        try:
            response = await request.repair_completion(
                ctx.completion_request(
                    messages=correction_messages,
                    temperature=(
                        request.self_correction_bumped_temperature
                        if retry_state.use_bumped_temperature
                        else request.self_correction_temperature
                    ),
                    counts_as_repair=True,
                )
            )
        except Exception as error:
            logger.error("Self-correction LLM call failed", exc_info=error)
            yield build_ai_builder_error_event(
                message="The AI planner failed. Please try again.",
                code=AIBuilderErrorCode.PLANNER_UPSTREAM_ERROR,
                phase=AIBuilderErrorPhase.SELF_CORRECTION,
                request_id=ctx.request_id,
            )
            return

        if not response.choices:
            yield build_ai_builder_error_event(
                message="The AI planner failed to return a valid repair. Please try again.",
                code=AIBuilderErrorCode.PLANNER_INVALID_REPAIR_RESPONSE,
                phase=AIBuilderErrorPhase.SELF_CORRECTION,
                request_id=ctx.request_id,
            )
            return

        choice = response.choices[0]
        message = choice.message
        assistant_text = _safe_assistant_text(message.content)

        if message.tool_calls:
            retry_feedback: tuple[LLMCompletionToolCall, str] | None = None
            for correction_tool_call in message.tool_calls:
                if correction_tool_call.function.name != retry_config.target_tool_name:
                    continue
                try:
                    arguments = parse_tool_call_arguments(
                        correction_tool_call.function.arguments
                    )
                except ToolArgumentParseError as error:
                    if retry_state.can_retry():
                        retry_feedback = (
                            correction_tool_call,
                            _build_retry_feedback(
                                target_tool_name=retry_config.target_tool_name,
                                target_kind=retry_config.target_kind,
                                feedback=_invalid_tool_arguments_message(error),
                                failure_codes=frozenset(),
                                retry_count=retry_state.next_retry_count,
                            ),
                        )
                        break
                    yield build_self_correction_error_event(
                        feedback=_invalid_tool_arguments_message(error),
                        failure_kind="parse",
                        request_id=ctx.request_id,
                    )
                    return

                tool_result = await retry_config.process_tool_invocation(
                    _build_tool_retry_invocation(
                        ctx=ctx,
                        arguments=arguments,
                        assistant_content=assistant_text
                        or "Här är mitt korrigerade förslag:",
                        tool_call_id=correction_tool_call.id,
                    )
                )
                terminal_events = _repair_terminal_events(tool_result)
                if not terminal_events:
                    if retry_state.can_retry():
                        retry_feedback = (
                            correction_tool_call,
                            _build_retry_feedback(
                                target_tool_name=retry_config.target_tool_name,
                                target_kind=retry_config.target_kind,
                                feedback=tool_result.feedback
                                or "Invalid tool payload.",
                                failure_codes=tool_result.failure_codes,
                                retry_count=retry_state.next_retry_count,
                            ),
                        )
                        break
                    yield build_self_correction_error_event(
                        feedback=tool_result.feedback,
                        failure_kind=tool_result.failure_kind,
                        request_id=ctx.request_id,
                    )
                    return

                for event in terminal_events:
                    yield event
                return

            if retry_feedback is not None:
                correction_tool_call, feedback = retry_feedback
                retry_state = retry_state.consume()
                correction_messages = build_tool_retry_messages(
                    llm_messages=correction_messages,
                    tool_call=correction_tool_call,
                    assistant_content=assistant_text,
                    tool_feedback=feedback,
                )
                continue

        if assistant_text:
            if looks_like_information_request(assistant_text):
                yield build_text_event(assistant_text)
                return
            forced_outcome = await run_forced_tool_retry_after_text(
                ForcedToolAfterTextRequest(
                    ctx=ctx,
                    correction_messages=correction_messages,
                    assistant_text=assistant_text,
                    retry_config=retry_config,
                    forced_proposal_temperature=request.forced_proposal_temperature,
                    repair_completion=request.repair_completion,
                )
            )
            if forced_outcome.events is not None:
                for event in forced_outcome.events:
                    yield event
                return

            forced_failure_kind = forced_outcome.failure_kind or "validation"
            if (
                forced_outcome.feedback is not None
                and retry_state.can_retry_text_feedback()
            ):
                text_retry_feedback = _build_retry_feedback(
                    target_tool_name=retry_config.target_tool_name,
                    target_kind=retry_config.target_kind,
                    feedback=forced_outcome.feedback,
                    retry_count=retry_state.next_retry_count,
                )
                retry_state = retry_state.consume_text_feedback()
                correction_messages = append_text_retry_feedback_turn(
                    llm_messages=correction_messages,
                    assistant_content=assistant_text,
                    feedback=text_retry_feedback,
                )
                continue

            logger.warning(
                "Self-correction bailed to conversational text after forced retry: %s",
                assistant_text,
            )
            yield build_self_correction_error_event(
                feedback=forced_outcome.feedback,
                failure_kind=forced_failure_kind,
                request_id=ctx.request_id,
            )
            return

        yield build_ai_builder_error_event(
            message="The AI planner failed. Please try again.",
            code=AIBuilderErrorCode.PLANNER_INVALID_REPAIR_RESPONSE,
            phase=AIBuilderErrorPhase.SELF_CORRECTION,
            request_id=ctx.request_id,
        )
        return


async def _execute_forced_tool_retry(
    request: ForcedToolAfterTextRequest,
) -> ForcedToolRetryOutcome:
    ctx = request.ctx
    if looks_like_information_request(request.assistant_text):
        return ForcedToolRetryOutcome()

    direct_outcome = await _try_process_json_text_as_tool_arguments(
        ctx=ctx,
        assistant_text=request.assistant_text,
        retry_config=request.retry_config,
    )
    if (
        direct_outcome.events is not None
        or direct_outcome.feedback is not None
        or direct_outcome.failure_kind is not None
    ):
        return direct_outcome

    forced_messages = list(request.correction_messages) + [
        {"role": "assistant", "content": request.assistant_text},
        {
            "role": "user",
            "content": request.retry_config.forced_tool_prompt,
        },
    ]

    try:
        response = await request.repair_completion(
            ctx.completion_request(
                messages=forced_messages,
                temperature=request.forced_proposal_temperature,
                tool_choice={
                    "type": "function",
                    "function": {"name": request.retry_config.target_tool_name},
                },
                counts_as_repair=True,
            )
        )
    except Exception as error:
        logger.error(
            "Forced proposal retry failed",
            exc_info=error,
            extra={"request_id": ctx.request_id},
        )
        return ForcedToolRetryOutcome()

    if not response.choices:
        return ForcedToolRetryOutcome()

    choice = response.choices[0]
    message = choice.message
    if not message.tool_calls:
        return ForcedToolRetryOutcome()

    for tool_call in message.tool_calls:
        if tool_call.function.name != request.retry_config.target_tool_name:
            continue
        try:
            arguments = parse_tool_call_arguments(tool_call.function.arguments)
        except ToolArgumentParseError as error:
            logger.warning("Forced proposal retry returned invalid payload: %s", error)
            return ForcedToolRetryOutcome(
                feedback=_invalid_tool_arguments_message(error),
                failure_kind="parse",
            )

        tool_result = await request.retry_config.process_tool_invocation(
            _build_tool_retry_invocation(
                ctx=ctx,
                arguments=arguments,
                assistant_content=request.assistant_text,
                tool_call_id=tool_call.id,
            )
        )
        terminal_events = _repair_terminal_events(tool_result)
        if not terminal_events:
            logger.warning(
                "Forced tool retry returned %s issue: %s",
                tool_result.failure_kind or "unknown",
                tool_result.feedback or "missing feedback",
            )
            return ForcedToolRetryOutcome(
                feedback=tool_result.feedback,
                failure_kind=tool_result.failure_kind,
            )

        return ForcedToolRetryOutcome(events=terminal_events)

    return ForcedToolRetryOutcome()


async def run_forced_tool_retry_after_text(
    request: ForcedToolAfterTextRequest,
) -> ForcedToolRetryOutcome:
    try:
        return await _execute_forced_tool_retry(request)
    except AIBuilderArchitectureError as error:
        return ForcedToolRetryOutcome(
            events=_architecture_error_events(
                error=error,
                usage_tracker=request.ctx.usage_tracker,
                request_id=request.ctx.request_id,
                tool_name=request.retry_config.target_tool_name,
            )
        )


async def _try_process_json_text_as_tool_arguments(
    *,
    ctx: ProposalTurnContext,
    assistant_text: str,
    retry_config: ToolRetryConfig,
) -> ForcedToolRetryOutcome:
    arguments = _parse_json_object_text(assistant_text)
    if arguments is None:
        return ForcedToolRetryOutcome()

    tool_result = await retry_config.process_tool_invocation(
        _build_tool_retry_invocation(
            ctx=ctx,
            arguments=arguments,
            assistant_content="Här är mitt korrigerade förslag:",
            tool_call_id=f"call_text_{uuid4().hex}",
        )
    )
    terminal_events = _repair_terminal_events(tool_result)
    if terminal_events:
        logger.info(
            "Accepted %s arguments returned as JSON text during forced retry.",
            retry_config.target_tool_name,
        )
        return ForcedToolRetryOutcome(events=terminal_events)

    logger.warning(
        "JSON text fallback for %s returned %s issue: %s",
        retry_config.target_tool_name,
        tool_result.failure_kind or "unknown",
        tool_result.feedback or "missing feedback",
    )
    return ForcedToolRetryOutcome(
        feedback=tool_result.feedback,
        failure_kind=tool_result.failure_kind,
    )


def _parse_json_object_text(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = _strip_json_fence(stripped)
    if not (stripped.startswith("{") and stripped.endswith("}")):
        return None
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    return cast(dict[str, Any], parsed) if isinstance(parsed, dict) else None


def _strip_json_fence(text: str) -> str:
    lines = text.splitlines()
    if not lines or not lines[0].startswith("```"):
        return text
    if lines[-1].strip() == "```":
        lines = lines[1:-1]
    else:
        lines = lines[1:]
    return "\n".join(lines).strip()


def _safe_assistant_text(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None
