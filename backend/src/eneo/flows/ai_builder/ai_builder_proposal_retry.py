"""One proposal turn's repair loop, bounded by the turn's call budget.

The initial call, every repair and one forced-tool continuation share
`MAX_PROPOSAL_PROVIDER_CALLS`. A `CorrectableFailure` buys one more call while
budget remains; a `TerminalFailure` ends the turn with its typed error; text
without a tool call gets exactly one forced-tool continuation and then a
typed terminal failure. Every repair request carries the latest failed payload
once, never a history of failed payloads, so the prompt does not grow per
attempt. Producers decide the variant; nothing here inspects failure codes.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Sequence
from dataclasses import dataclass
from typing import Any

from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    RuntimeToolCall,
    provider_safe_tool_call_id,
)
from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderBadRequestException,
    AIBuilderErrorCode,
    AIBuilderErrorEvent,
    AIBuilderErrorPhase,
    JsonScalar,
    build_ai_builder_error_event,
)
from eneo.flows.ai_builder.ai_builder_event_models import (
    AIBuilderStatus,
    AIBuilderStreamEvent,
)
from eneo.flows.ai_builder.ai_builder_events import build_status_event
from eneo.flows.ai_builder.ai_builder_litellm_completion import (
    LLMCompletionToolCall,
)
from eneo.flows.ai_builder.ai_builder_proposal_capture import (
    capture_malformed_proposal_arguments,
)
from eneo.flows.ai_builder.ai_builder_proposal_telemetry import (
    PROPOSAL_PARSE_JSON_FAILURE_CODE,
    ProposalAttemptFailureKind,
    ProposalFailedTurnBranch,
    ProposalTerminalFailureKind,
    ToolProcessingFailureKind,
    assistant_metadata_with_usage,
    log_proposal_failed_turn,
)
from eneo.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    CorrectableFailure,
    LLMMessageParam,
    ProposalCallBudgetExhausted,
    ProposalCompleted,
    ProposalCompletionFn,
    ProposalMessageGroup,
    ProposalTurnContext,
    SubmissionOutcome,
    TerminalFailure,
    ToolRetryConfig,
    ToolRetryInvocation,
    replace_repair_group,
)
from eneo.flows.ai_builder.ai_builder_tool_names import PROPOSE_FLOW_TOOL_NAME
from eneo.flows.ai_builder.ai_builder_tool_parsing import (
    ToolArgumentParseError,
    parse_tool_call_arguments,
)
from eneo.main.logging import get_logger

logger = get_logger(__name__)
_MAX_PUBLIC_FAILURE_CODES = 3


@dataclass(frozen=True, slots=True)
class ProposalSelfCorrectionRequest:
    ctx: ProposalTurnContext
    failure: CorrectableFailure
    tool_call: RuntimeToolCall
    self_correction_temperature: float
    forced_proposal_temperature: float
    repair_completion: ProposalCompletionFn
    retry_config: ToolRetryConfig


@dataclass(frozen=True, slots=True)
class ForcedToolAfterTextRequest:
    ctx: ProposalTurnContext
    correction_message_groups: tuple[ProposalMessageGroup, ...]
    assistant_text: str
    retry_config: ToolRetryConfig
    forced_proposal_temperature: float
    repair_completion: ProposalCompletionFn
    truncation_error_phase: AIBuilderErrorPhase = AIBuilderErrorPhase.SELF_CORRECTION


@dataclass(frozen=True, slots=True)
class ForcedToolContinuation:
    """What one forced-tool continuation produced, with the call it came from."""

    outcome: SubmissionOutcome
    tool_call: LLMCompletionToolCall | None = None


@dataclass(frozen=True, slots=True)
class _RepairCallResult:
    outcome: SubmissionOutcome
    tool_call: LLMCompletionToolCall | None
    assistant_text: str | None


def missing_tool_call_failure() -> TerminalFailure:
    """The model answered without the proposal tool after being told to use it."""

    return TerminalFailure(
        kind="missing_submission_tool",
        message=(
            "The AI planner did not return a flow proposal. Try again, or use a "
            "more capable model if the same error repeats."
        ),
        code=AIBuilderErrorCode.PROPOSAL_TOOL_MISSING,
        phase=AIBuilderErrorPhase.SELF_CORRECTION,
    )


def provider_truncation_failure(*, phase: AIBuilderErrorPhase) -> TerminalFailure:
    return TerminalFailure(
        kind="provider_truncation",
        message=(
            "The AI planner output was cut off before it returned a complete "
            "flow proposal. Try again with a shorter request or a model with "
            "a larger output limit."
        ),
        code=AIBuilderErrorCode.PLANNER_OUTPUT_TOO_LONG,
        phase=phase,
    )


def terminal_failure_event(
    failure: TerminalFailure, *, request_id: str | None
) -> AIBuilderErrorEvent:
    return build_ai_builder_error_event(
        message=failure.message,
        code=failure.code,
        phase=failure.phase,
        request_id=request_id,
        details=failure.details,
    )


def _record_attempt_failure(
    ctx: ProposalTurnContext,
    *,
    failure_kind: ProposalAttemptFailureKind,
    failure_codes: frozenset[str] = frozenset(),
) -> None:
    if ctx.usage_tracker is not None:
        ctx.usage_tracker.record_attempt_failure(
            failure_kind=failure_kind,
            failure_codes=failure_codes,
        )


def _invalid_tool_arguments_message(error: Exception) -> str:
    return f"Invalid tool call arguments: {error}"


def _self_correction_error_code(
    failure_kind: ToolProcessingFailureKind | None,
) -> AIBuilderErrorCode:
    if failure_kind == "parse":
        return AIBuilderErrorCode.SELF_CORRECTION_INVALID_PAYLOAD
    if failure_kind == "quality":
        return AIBuilderErrorCode.SELF_CORRECTION_QUALITY_FAILURE
    return AIBuilderErrorCode.SELF_CORRECTION_INVALID_PLAN


def _self_correction_terminal_failure_kind(
    failure_kind: ToolProcessingFailureKind | None,
) -> ProposalTerminalFailureKind:
    if failure_kind == "parse":
        return "invalid_repair_payload"
    if failure_kind == "quality":
        return "repair_quality_failure"
    return "invalid_repair_plan"


def _log_self_correction_failed_turn(
    *,
    ctx: ProposalTurnContext,
    branch: ProposalFailedTurnBranch,
    final_failure_kind: ProposalTerminalFailureKind,
    final_error_code: AIBuilderErrorCode,
) -> None:
    if ctx.usage_tracker is None:
        return
    log_proposal_failed_turn(
        usage_tracker=ctx.usage_tracker,
        session_id=ctx.session_id,
        branch=branch,
        final_failure_kind=final_failure_kind,
        final_error_code=final_error_code.value,
    )


def _log_self_correction_validation_failed_turn(
    *,
    ctx: ProposalTurnContext,
    branch: ProposalFailedTurnBranch,
    failure_kind: ToolProcessingFailureKind | None,
) -> None:
    _log_self_correction_failed_turn(
        ctx=ctx,
        branch=branch,
        final_failure_kind=_self_correction_terminal_failure_kind(failure_kind),
        final_error_code=_self_correction_error_code(failure_kind),
    )


def _log_terminal_failure(ctx: ProposalTurnContext, failure: TerminalFailure) -> None:
    if failure.kind == "provider_truncation":
        _log_self_correction_failed_turn(
            ctx=ctx,
            branch="provider_truncation",
            final_failure_kind="provider_truncation",
            final_error_code=failure.code,
        )
    elif failure.kind == "missing_submission_tool":
        _log_self_correction_failed_turn(
            ctx=ctx,
            branch="self_correction_missing_tool_response",
            final_failure_kind="missing_submission_tool",
            final_error_code=failure.code,
        )


def build_self_correction_error_event(
    *,
    feedback: str | None,
    failure_kind: ToolProcessingFailureKind | None,
    failure_codes: frozenset[str] = frozenset(),
    request_id: str | None = None,
) -> AIBuilderErrorEvent:
    message = _self_correction_user_message(
        failure_kind=failure_kind,
        failure_codes=failure_codes,
    )
    return build_ai_builder_error_event(
        message=message,
        code=_self_correction_error_code(failure_kind),
        phase=AIBuilderErrorPhase.SELF_CORRECTION,
        request_id=request_id,
        details=_self_correction_error_details(
            failure_kind=failure_kind,
            failure_codes=failure_codes,
        ),
    )


def _self_correction_error_details(
    *,
    failure_kind: ToolProcessingFailureKind | None,
    failure_codes: frozenset[str],
) -> dict[str, JsonScalar] | None:
    if not failure_codes:
        return None
    sorted_codes = sorted(failure_codes)
    public_codes = sorted_codes[:_MAX_PUBLIC_FAILURE_CODES]
    detail_key = (
        "quality_failure_codes" if failure_kind == "quality" else "failure_codes"
    )
    details: dict[str, JsonScalar] = {
        detail_key: ",".join(public_codes),
    }
    if len(sorted_codes) > len(public_codes):
        details[f"{detail_key}_count"] = len(sorted_codes)
    return details


def _self_correction_user_message(
    *,
    failure_kind: ToolProcessingFailureKind | None,
    failure_codes: frozenset[str],
) -> str:
    if failure_kind == "parse":
        return (
            "The AI Builder returned an incomplete plan configuration and could "
            "not repair it automatically. Try again, or use a more capable model "
            "if the same error repeats."
        )
    if "empty_steps" in failure_codes:
        return (
            "The corrected plan did not contain any flow steps. Ask for at least "
            "one concrete step, such as transcribing audio or summarizing text, "
            "then try again."
        )
    if failure_codes.intersection(
        {"first_step_invalid_source", "flow_input_not_first"}
    ):
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


def _build_tool_retry_invocation(
    *,
    ctx: ProposalTurnContext,
    arguments: dict[str, Any],
    assistant_content: str,
    tool_call_id: str,
) -> ToolRetryInvocation:
    assistant_metadata = ctx.assistant_metadata
    if ctx.usage_tracker is not None:
        assistant_metadata = assistant_metadata_with_usage(
            conversation=ctx.conversation,
            base_metadata=ctx.assistant_metadata,
            usage_tracker=ctx.usage_tracker,
        )
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
        assistant_metadata=assistant_metadata,
    )


def build_tool_retry_messages(
    *,
    llm_messages: list[LLMMessageParam],
    tool_call: RuntimeToolCall,
    tool_feedback: str,
    assistant_content: str | None = None,
) -> list[LLMMessageParam]:
    return [
        *llm_messages,
        *_tool_retry_group_messages(
            tool_call=tool_call,
            tool_feedback=tool_feedback,
            assistant_content=assistant_content,
        ),
    ]


def _tool_retry_group_messages(
    *,
    tool_call: RuntimeToolCall,
    tool_feedback: str,
    assistant_content: str | None = None,
) -> tuple[LLMMessageParam, ...]:
    tool_call_id = provider_safe_tool_call_id(tool_call.id)
    return (
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
    )


def append_text_retry_feedback_turn(
    *,
    llm_messages: list[LLMMessageParam],
    assistant_content: str,
    feedback: str,
) -> list[LLMMessageParam]:
    return [
        *llm_messages,
        *_text_retry_group_messages(
            assistant_content=assistant_content,
            feedback=feedback,
        ),
    ]


def _text_retry_group_messages(
    *,
    assistant_content: str,
    feedback: str,
) -> tuple[LLMMessageParam, ...]:
    return (
        {"role": "assistant", "content": assistant_content},
        {"role": "user", "content": feedback},
    )


def repair_feedback(failure: CorrectableFailure) -> str:
    """The whole correction brief: the producer's feedback plus one instruction."""

    return (
        f"{failure.feedback}\nKeep valid parts and fix only the listed issues. "
        f"Return one complete {PROPOSE_FLOW_TOOL_NAME} call."
    )


def build_proposal_self_correction_request(
    *,
    ctx: ProposalTurnContext,
    failure: CorrectableFailure,
    tool_call: RuntimeToolCall,
    retry_config: ToolRetryConfig,
    self_correction_temperature: float,
    forced_proposal_temperature: float,
    repair_completion: ProposalCompletionFn,
) -> ProposalSelfCorrectionRequest:
    return ProposalSelfCorrectionRequest(
        ctx=ctx,
        failure=failure,
        tool_call=tool_call,
        self_correction_temperature=self_correction_temperature,
        forced_proposal_temperature=forced_proposal_temperature,
        repair_completion=repair_completion,
        retry_config=retry_config,
    )


async def run_tool_self_correction(
    request: ProposalSelfCorrectionRequest,
) -> AsyncGenerator[AIBuilderStreamEvent, None]:
    """Spend the remaining call budget on repairs of one correctable failure."""

    ctx = request.ctx
    yield build_status_event(AIBuilderStatus.REPAIRING)
    failure = request.failure
    tool_call: RuntimeToolCall | LLMCompletionToolCall = request.tool_call
    assistant_text: str | None = None
    while True:
        message_groups = replace_repair_group(
            ctx.message_groups,
            _tool_retry_group_messages(
                tool_call=tool_call,
                tool_feedback=repair_feedback(failure),
                assistant_content=assistant_text,
            ),
        )
        try:
            response = await request.repair_completion(
                ctx.completion_request(
                    message_groups=message_groups,
                    temperature=request.self_correction_temperature,
                    counts_as_repair=True,
                )
            )
        except ProposalCallBudgetExhausted:
            _log_self_correction_validation_failed_turn(
                ctx=ctx,
                branch="self_correction_invalid_tool_result",
                failure_kind=failure.kind,
            )
            yield build_self_correction_error_event(
                feedback=failure.feedback,
                failure_kind=failure.kind,
                failure_codes=failure.codes,
                request_id=ctx.request_id,
            )
            return
        except AIBuilderBadRequestException:
            raise
        except Exception as error:
            if ctx.usage_tracker is not None:
                ctx.usage_tracker.finalize_pending_attempt()
            logger.error("Self-correction completion processing failed", exc_info=error)
            _log_self_correction_failed_turn(
                ctx=ctx,
                branch="self_correction_completion_error",
                final_failure_kind="internal_error",
                final_error_code=AIBuilderErrorCode.PLANNER_UPSTREAM_ERROR,
            )
            yield build_ai_builder_error_event(
                message="The AI planner failed. Please try again.",
                code=AIBuilderErrorCode.PLANNER_UPSTREAM_ERROR,
                phase=AIBuilderErrorPhase.SELF_CORRECTION,
                request_id=ctx.request_id,
            )
            return
        result = await _repair_call_result(
            response,
            ctx=ctx,
            retry_config=request.retry_config,
            forced_proposal_temperature=request.forced_proposal_temperature,
            repair_completion=request.repair_completion,
            message_groups=message_groups,
        )
        outcome = result.outcome
        if isinstance(outcome, ProposalCompleted):
            for event in outcome.events:
                yield event
            return
        if isinstance(outcome, TerminalFailure):
            _log_terminal_failure(ctx, outcome)
            yield terminal_failure_event(outcome, request_id=ctx.request_id)
            return
        if result.tool_call is None or ctx.proposal_call_budget.calls_remaining == 0:
            _log_self_correction_validation_failed_turn(
                ctx=ctx,
                branch="self_correction_invalid_tool_result",
                failure_kind=outcome.kind,
            )
            yield build_self_correction_error_event(
                feedback=outcome.feedback,
                failure_kind=outcome.kind,
                failure_codes=outcome.codes,
                request_id=ctx.request_id,
            )
            return
        failure = outcome
        tool_call = result.tool_call
        assistant_text = result.assistant_text


async def _repair_call_result(
    response: Any,
    *,
    ctx: ProposalTurnContext,
    retry_config: ToolRetryConfig,
    forced_proposal_temperature: float,
    repair_completion: ProposalCompletionFn,
    message_groups: tuple[ProposalMessageGroup, ...],
) -> _RepairCallResult:
    """Classify one repair completion; text without a tool gets one forced call."""

    if not response.choices:
        _record_attempt_failure(ctx, failure_kind="missing_submission_tool")
        return _RepairCallResult(missing_tool_call_failure(), None, None)
    choice = response.choices[0]
    if choice.finish_reason == "length":
        _record_attempt_failure(ctx, failure_kind="provider_truncation")
        return _RepairCallResult(
            provider_truncation_failure(phase=AIBuilderErrorPhase.SELF_CORRECTION),
            None,
            None,
        )
    message = choice.message
    assistant_text = _safe_assistant_text(message.content)
    tool_call = _sole_proposal_tool_call(message.tool_calls)
    if tool_call is not None:
        outcome = await _process_tool_call(
            tool_call,
            ctx=ctx,
            retry_config=retry_config,
            assistant_content=assistant_text or "Här är mitt korrigerade förslag:",
        )
        return _RepairCallResult(outcome, tool_call, assistant_text)
    _record_attempt_failure(ctx, failure_kind="missing_submission_tool")
    if not assistant_text:
        return _RepairCallResult(missing_tool_call_failure(), None, None)
    continuation = await _execute_forced_tool_retry(
        ForcedToolAfterTextRequest(
            ctx=ctx,
            correction_message_groups=message_groups,
            assistant_text=assistant_text,
            retry_config=retry_config,
            forced_proposal_temperature=forced_proposal_temperature,
            repair_completion=repair_completion,
        )
    )
    if isinstance(continuation.outcome, TerminalFailure):
        _log_self_correction_validation_failed_turn(
            ctx=ctx,
            branch="self_correction_text_forced_retry_failed",
            failure_kind=None,
        )
    return _RepairCallResult(
        continuation.outcome, continuation.tool_call, assistant_text
    )


async def _process_tool_call(
    tool_call: LLMCompletionToolCall,
    *,
    ctx: ProposalTurnContext,
    retry_config: ToolRetryConfig,
    assistant_content: str,
) -> SubmissionOutcome:
    try:
        arguments = parse_tool_call_arguments(tool_call.function.arguments)
    except ToolArgumentParseError as error:
        capture_malformed_proposal_arguments(
            tool_call.function.arguments,
            session_id=str(ctx.session_id),
            error_message=str(error),
        )
        failure_codes = frozenset({PROPOSAL_PARSE_JSON_FAILURE_CODE})
        _record_attempt_failure(ctx, failure_kind="parse", failure_codes=failure_codes)
        return CorrectableFailure(
            feedback=_invalid_tool_arguments_message(error),
            kind="parse",
            codes=failure_codes,
        )
    outcome = await retry_config.process_tool_invocation(
        _build_tool_retry_invocation(
            ctx=ctx,
            arguments=arguments,
            assistant_content=assistant_content,
            tool_call_id=tool_call.id,
        )
    )
    if isinstance(outcome, CorrectableFailure):
        _record_attempt_failure(
            ctx, failure_kind=outcome.kind, failure_codes=outcome.codes
        )
    elif isinstance(outcome, TerminalFailure):
        _record_attempt_failure(
            ctx, failure_kind=outcome.kind, failure_codes=outcome.codes
        )
    return outcome


async def _execute_forced_tool_retry(
    request: ForcedToolAfterTextRequest,
) -> ForcedToolContinuation:
    ctx = request.ctx
    forced_message_groups = replace_repair_group(
        request.correction_message_groups,
        _text_retry_group_messages(
            assistant_content=request.assistant_text,
            feedback=request.retry_config.forced_tool_prompt,
        ),
    )
    try:
        response = await request.repair_completion(
            ctx.completion_request(
                message_groups=forced_message_groups,
                temperature=request.forced_proposal_temperature,
                counts_as_repair=True,
            )
        )
    except ProposalCallBudgetExhausted:
        return ForcedToolContinuation(missing_tool_call_failure())
    except AIBuilderBadRequestException:
        raise
    except Exception as error:
        if ctx.usage_tracker is not None:
            ctx.usage_tracker.finalize_pending_attempt()
        logger.error(
            "Forced proposal retry completion processing failed",
            exc_info=error,
            extra={"request_id": ctx.request_id},
        )
        return ForcedToolContinuation(missing_tool_call_failure())
    if not response.choices:
        _record_attempt_failure(ctx, failure_kind="missing_submission_tool")
        return ForcedToolContinuation(missing_tool_call_failure())
    choice = response.choices[0]
    if choice.finish_reason == "length":
        _record_attempt_failure(ctx, failure_kind="provider_truncation")
        return ForcedToolContinuation(
            provider_truncation_failure(phase=request.truncation_error_phase)
        )
    tool_call = _sole_proposal_tool_call(choice.message.tool_calls)
    if tool_call is None:
        _record_attempt_failure(ctx, failure_kind="missing_submission_tool")
        return ForcedToolContinuation(missing_tool_call_failure())
    outcome = await _process_tool_call(
        tool_call,
        ctx=ctx,
        retry_config=request.retry_config,
        assistant_content=request.assistant_text,
    )
    if isinstance(outcome, CorrectableFailure):
        logger.warning(
            "Forced tool retry returned an invalid result",
            extra={
                "failure_kind": outcome.kind,
                "failure_codes_count": len(outcome.codes),
                "feedback_length": len(outcome.feedback),
            },
        )
    return ForcedToolContinuation(outcome, tool_call)


async def run_forced_tool_retry_after_text(
    request: ForcedToolAfterTextRequest,
) -> ForcedToolContinuation:
    """One forced-tool continuation after a text-only initial response."""

    return await _execute_forced_tool_retry(request)


def _sole_proposal_tool_call(
    tool_calls: Sequence[LLMCompletionToolCall] | None,
) -> LLMCompletionToolCall | None:
    if not tool_calls or len(tool_calls) != 1:
        return None
    tool_call = tool_calls[0]
    if tool_call.function.name != PROPOSE_FLOW_TOOL_NAME:
        return None
    return tool_call


def _safe_assistant_text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None
