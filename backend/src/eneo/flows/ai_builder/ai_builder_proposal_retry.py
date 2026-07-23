from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from dataclasses import dataclass, replace
from hashlib import sha256
from typing import Any, cast
from uuid import uuid4

from eneo.flows.ai_builder.ai_builder_architecture_errors import (
    AIBuilderArchitectureError,
    build_proposal_architecture_error_event,
    record_proposal_architecture_failure,
)
from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    RuntimeToolCall,
    provider_safe_tool_call_id,
)
from eneo.flows.ai_builder.ai_builder_domain_models import TargetKind
from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderErrorCode,
    AIBuilderErrorEvent,
    AIBuilderErrorPhase,
    AIBuilderProviderOutcomeUnknownException,
    JsonScalar,
    build_ai_builder_error_event,
)
from eneo.flows.ai_builder.ai_builder_event_models import (
    AIBuilderStatus,
    AIBuilderStreamEvent,
)
from eneo.flows.ai_builder.ai_builder_events import (
    build_status_event,
    build_text_event,
)
from eneo.flows.ai_builder.ai_builder_interaction_utils import (
    looks_like_information_request,
)
from eneo.flows.ai_builder.ai_builder_litellm_completion import (
    LLMCompletionToolCall,
)
from eneo.flows.ai_builder.ai_builder_proposal_telemetry import (
    ProposalAttemptFailureKind,
    ProposalFailedTurnBranch,
    ProposalTerminalFailureKind,
    ProposalTurnTelemetry,
    ToolProcessingFailureKind,
    assistant_metadata_with_usage,
    log_proposal_failed_turn,
)
from eneo.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    LLMMessageParam,
    ProposalCompletionFn,
    ProposalTurnContext,
    ToolProcessingResult,
    ToolRetryConfig,
    ToolRetryInvocation,
    forced_tool_choice,
)
from eneo.flows.ai_builder.ai_builder_tool_parsing import (
    ToolArgumentParseError,
    parse_tool_call_arguments,
)
from eneo.flows.ai_builder.ai_builder_tools import PROPOSE_FLOW_TOOL_NAME
from eneo.main.logging import get_logger

logger = get_logger(__name__)
_MAX_PUBLIC_FAILURE_CODES = 3


@dataclass(frozen=True, slots=True)
class ForcedToolRetryOutcome:
    events: tuple[AIBuilderStreamEvent, ...] | None = None
    feedback: str | None = None
    failure_kind: ToolProcessingFailureKind | None = None
    failure_codes: frozenset[str] = frozenset()
    failure_fingerprint: str | None = None


@dataclass(frozen=True, slots=True)
class ProposalSelfCorrectionRequest:
    ctx: ProposalTurnContext
    error_message: str
    tool_call: RuntimeToolCall
    self_correction_temperature: float
    self_correction_bumped_temperature: float
    repair_completion: ProposalCompletionFn
    retry_config: ToolRetryConfig
    forced_proposal_temperature: float
    initial_failure_kind: ToolProcessingFailureKind
    failure_codes: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class ForcedToolAfterTextRequest:
    ctx: ProposalTurnContext
    correction_messages: list[LLMMessageParam]
    assistant_text: str
    retry_config: ToolRetryConfig
    forced_proposal_temperature: float
    repair_completion: ProposalCompletionFn
    truncation_error_phase: AIBuilderErrorPhase = AIBuilderErrorPhase.SELF_CORRECTION


@dataclass(frozen=True, slots=True)
class _ProposalRepairRetryState:
    previous_failure_fingerprint: str
    last_failure_kind: ToolProcessingFailureKind
    last_failure_codes: frozenset[str]
    text_feedback_retry_available: bool = True
    retry_count: int = 0

    @classmethod
    def initial(
        cls,
        *,
        failure_fingerprint: str,
        failure_kind: ToolProcessingFailureKind,
        failure_codes: frozenset[str],
    ) -> "_ProposalRepairRetryState":
        return cls(
            previous_failure_fingerprint=failure_fingerprint,
            last_failure_kind=failure_kind,
            last_failure_codes=failure_codes,
        )

    @property
    def use_bumped_temperature(self) -> bool:
        return self.retry_count >= 1

    @property
    def next_retry_count(self) -> int:
        return self.retry_count + 1

    def progressing_fingerprint(
        self,
        *,
        failure_fingerprint: str | None,
        calls_remaining: int,
    ) -> str | None:
        if (
            failure_fingerprint is None
            or failure_fingerprint == self.previous_failure_fingerprint
            or calls_remaining == 0
        ):
            return None
        return failure_fingerprint

    def progressing_text_fingerprint(
        self,
        *,
        failure_fingerprint: str | None,
        calls_remaining: int,
    ) -> str | None:
        if not self.text_feedback_retry_available:
            return None
        return self.progressing_fingerprint(
            failure_fingerprint=failure_fingerprint,
            calls_remaining=calls_remaining,
        )

    def record_progress(
        self,
        *,
        failure_fingerprint: str,
        failure_kind: ToolProcessingFailureKind,
        failure_codes: frozenset[str],
        consume_text_feedback: bool = False,
    ) -> "_ProposalRepairRetryState":
        return replace(
            self,
            previous_failure_fingerprint=failure_fingerprint,
            last_failure_kind=failure_kind,
            last_failure_codes=failure_codes,
            text_feedback_retry_available=(
                False if consume_text_feedback else self.text_feedback_retry_available
            ),
            retry_count=self.retry_count + 1,
        )


def _start_repair_attempt(ctx: ProposalTurnContext) -> None:
    if ctx.usage_tracker is not None:
        ctx.usage_tracker.start_attempt(counts_as_repair=True)


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


def _provider_truncation_error_event(
    *,
    ctx: ProposalTurnContext,
    phase: AIBuilderErrorPhase,
) -> AIBuilderErrorEvent:
    if ctx.usage_tracker is not None:
        log_proposal_failed_turn(
            usage_tracker=ctx.usage_tracker,
            session_id=ctx.session_id,
            branch="provider_truncation",
            final_failure_kind="provider_truncation",
            final_error_code=AIBuilderErrorCode.PLANNER_OUTPUT_TOO_LONG.value,
        )
    return build_ai_builder_error_event(
        message=(
            "The AI planner output was cut off before it returned a complete "
            "flow proposal. Try again with a shorter request or a model with "
            "a larger output limit."
        ),
        code=AIBuilderErrorCode.PLANNER_OUTPUT_TOO_LONG,
        phase=phase,
        request_id=ctx.request_id,
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


def _repair_terminal_events(
    result: ToolProcessingResult,
) -> tuple[AIBuilderStreamEvent, ...]:
    user_message_events = (
        (build_text_event(result.user_message),)
        if result.user_message is not None
        else tuple()
    )
    return (*result.events, *user_message_events)


def _proposal_failure_fingerprint(
    candidate: object,
    *,
    failure_kind: ToolProcessingFailureKind,
    failure_codes: frozenset[str],
) -> str:
    if isinstance(candidate, str):
        try:
            parsed_candidate = json.loads(candidate)
        except json.JSONDecodeError:
            parsed_candidate = candidate
        candidate_value: object = parsed_candidate
    else:
        candidate_value = candidate
    fingerprint_payload = json.dumps(
        {
            "candidate": candidate_value,
            "failure_codes": sorted(failure_codes),
            "failure_kind": failure_kind,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return sha256(fingerprint_payload.encode()).hexdigest()


async def _classify_processed_repair_attempt(
    *,
    retry_config: ToolRetryConfig,
    invocation: ToolRetryInvocation,
) -> ForcedToolRetryOutcome:
    tool_result = await retry_config.process_tool_invocation(invocation)
    terminal_events = _repair_terminal_events(tool_result)
    if terminal_events:
        return ForcedToolRetryOutcome(events=terminal_events)
    failure_kind = tool_result.failure_kind or "validation"
    return ForcedToolRetryOutcome(
        feedback=tool_result.feedback,
        failure_kind=failure_kind,
        failure_codes=tool_result.failure_codes,
        failure_fingerprint=_proposal_failure_fingerprint(
            invocation.arguments,
            failure_kind=failure_kind,
            failure_codes=tool_result.failure_codes,
        ),
    )


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
    llm_messages: list[LLMMessageParam],
    tool_call: RuntimeToolCall,
    tool_feedback: str,
    assistant_content: str | None = None,
) -> list[LLMMessageParam]:
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
    llm_messages: list[LLMMessageParam],
    assistant_content: str,
    feedback: str,
) -> list[LLMMessageParam]:
    return list(llm_messages) + [
        {"role": "assistant", "content": assistant_content},
        {"role": "user", "content": feedback},
    ]


def _build_retry_feedback(
    *,
    target_kind: TargetKind,
    feedback: str,
    failure_codes: frozenset[str] = frozenset(),
    retry_count: int = 1,
) -> str:
    suffix = (
        "Keep valid parts and fix only the listed issues. Return one complete "
        f"{PROPOSE_FLOW_TOOL_NAME} call."
    )
    if target_kind == TargetKind.CREATE:
        intent_rules = [
            "Every steps[] item must be one complete semantic intent step with at least name and instructions.",
            "Runtime form inputs belong in top-level input_fields[], and steps should reference them by name in uses_form_fields.",
        ]
        if "json_output_no_contract" in failure_codes:
            intent_rules.append(
                "For every JSON semantic step that feeds later steps, set output_fields with named fields that match the step's extracted data."
            )
        if "duplicate_step_name" in failure_codes:
            intent_rules.append(
                "Every steps[] name must be unique case-insensitively; rename duplicate semantic steps with specific labels."
            )
        suffix = (
            " ".join(intent_rules)
            + " Keep valid semantic parts and fix only the listed issues. "
            f"Return one complete {PROPOSE_FLOW_TOOL_NAME} call."
        )
    if retry_count <= 0:
        # retry_count=0 is the initial correction before any repair result exists.
        preamble = "VALIDATION FAILED"
    elif retry_count >= 2:
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
    initial_failure_kind: ToolProcessingFailureKind,
    failure_codes: frozenset[str] = frozenset(),
) -> ProposalSelfCorrectionRequest:
    return ProposalSelfCorrectionRequest(
        ctx=ctx,
        error_message=error_message,
        tool_call=tool_call,
        self_correction_temperature=self_correction_temperature,
        self_correction_bumped_temperature=self_correction_bumped_temperature,
        repair_completion=repair_completion,
        retry_config=retry_config,
        forced_proposal_temperature=forced_proposal_temperature,
        initial_failure_kind=initial_failure_kind,
        failure_codes=failure_codes,
    )


async def run_tool_self_correction(
    request: ProposalSelfCorrectionRequest,
) -> AsyncGenerator[AIBuilderStreamEvent, None]:
    try:
        async for event in _request_self_correction_events(request):
            yield event
    except AIBuilderArchitectureError as error:
        for event in _architecture_error_events(
            error=error,
            usage_tracker=request.ctx.usage_tracker,
            request_id=request.ctx.request_id,
            tool_name=PROPOSE_FLOW_TOOL_NAME,
        ):
            yield event


def _architecture_error_events(
    *,
    error: AIBuilderArchitectureError,
    usage_tracker: ProposalTurnTelemetry | None,
    request_id: str | None,
    tool_name: str,
) -> tuple[AIBuilderStreamEvent, ...]:
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
) -> AsyncGenerator[AIBuilderStreamEvent, None]:
    ctx = request.ctx
    retry_config = request.retry_config
    yield build_status_event(AIBuilderStatus.REPAIRING)
    correction_messages = build_tool_retry_messages(
        llm_messages=ctx.llm_messages,
        tool_call=request.tool_call,
        tool_feedback=_build_retry_feedback(
            target_kind=retry_config.target_kind,
            feedback=request.error_message,
            failure_codes=request.failure_codes,
            retry_count=0,
        ),
    )

    retry_state = _ProposalRepairRetryState.initial(
        failure_fingerprint=_proposal_failure_fingerprint(
            request.tool_call.function.arguments,
            failure_kind=request.initial_failure_kind,
            failure_codes=request.failure_codes,
        ),
        failure_kind=request.initial_failure_kind,
        failure_codes=request.failure_codes,
    )
    while True:
        if not ctx.proposal_call_budget.try_start_call():
            _log_self_correction_validation_failed_turn(
                ctx=ctx,
                branch="self_correction_invalid_tool_result",
                failure_kind=retry_state.last_failure_kind,
            )
            yield build_self_correction_error_event(
                feedback=None,
                failure_kind=retry_state.last_failure_kind,
                failure_codes=retry_state.last_failure_codes,
                request_id=ctx.request_id,
            )
            return
        _start_repair_attempt(ctx)
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
        except AIBuilderProviderOutcomeUnknownException:
            raise
        except Exception as error:
            _record_attempt_failure(ctx, failure_kind="provider_error")
            logger.error("Self-correction LLM call failed", exc_info=error)
            _log_self_correction_failed_turn(
                ctx=ctx,
                branch="self_correction_completion_error",
                final_failure_kind="provider_error",
                final_error_code=AIBuilderErrorCode.PLANNER_UPSTREAM_ERROR,
            )
            yield build_ai_builder_error_event(
                message="The AI planner failed. Please try again.",
                code=AIBuilderErrorCode.PLANNER_UPSTREAM_ERROR,
                phase=AIBuilderErrorPhase.SELF_CORRECTION,
                request_id=ctx.request_id,
            )
            return

        if not response.choices:
            _record_attempt_failure(ctx, failure_kind="missing_submission_tool")
            _log_self_correction_failed_turn(
                ctx=ctx,
                branch="self_correction_empty_completion_choices",
                final_failure_kind="invalid_repair_response",
                final_error_code=AIBuilderErrorCode.PLANNER_INVALID_REPAIR_RESPONSE,
            )
            yield build_ai_builder_error_event(
                message="The AI planner failed to return a valid repair. Please try again.",
                code=AIBuilderErrorCode.PLANNER_INVALID_REPAIR_RESPONSE,
                phase=AIBuilderErrorPhase.SELF_CORRECTION,
                request_id=ctx.request_id,
            )
            return

        choice = response.choices[0]
        if choice.finish_reason == "length":
            _record_attempt_failure(ctx, failure_kind="provider_truncation")
            yield _provider_truncation_error_event(
                ctx=ctx,
                phase=AIBuilderErrorPhase.SELF_CORRECTION,
            )
            return

        message = choice.message
        assistant_text = _safe_assistant_text(message.content)

        if message.tool_calls:
            retry_feedback: (
                tuple[
                    LLMCompletionToolCall,
                    str,
                    str,
                    ToolProcessingFailureKind,
                    frozenset[str],
                ]
                | None
            ) = None
            for correction_tool_call in message.tool_calls:
                if correction_tool_call.function.name != PROPOSE_FLOW_TOOL_NAME:
                    continue
                try:
                    arguments = parse_tool_call_arguments(
                        correction_tool_call.function.arguments
                    )
                except ToolArgumentParseError as error:
                    failure_kind: ToolProcessingFailureKind = "parse"
                    failure_codes = frozenset[str]()
                    failure_fingerprint = _proposal_failure_fingerprint(
                        correction_tool_call.function.arguments,
                        failure_kind=failure_kind,
                        failure_codes=failure_codes,
                    )
                    _record_attempt_failure(
                        ctx,
                        failure_kind=failure_kind,
                        failure_codes=failure_codes,
                    )
                    progressing_fingerprint = retry_state.progressing_fingerprint(
                        failure_fingerprint=failure_fingerprint,
                        calls_remaining=ctx.proposal_call_budget.calls_remaining,
                    )
                    if progressing_fingerprint is not None:
                        retry_feedback = (
                            correction_tool_call,
                            _build_retry_feedback(
                                target_kind=retry_config.target_kind,
                                feedback=_invalid_tool_arguments_message(error),
                                failure_codes=frozenset(),
                                retry_count=retry_state.next_retry_count,
                            ),
                            progressing_fingerprint,
                            failure_kind,
                            failure_codes,
                        )
                        break
                    _log_self_correction_validation_failed_turn(
                        ctx=ctx,
                        branch="self_correction_malformed_tool_arguments",
                        failure_kind="parse",
                    )
                    yield build_self_correction_error_event(
                        feedback=_invalid_tool_arguments_message(error),
                        failure_kind="parse",
                        request_id=ctx.request_id,
                    )
                    return

                repair_outcome = await _classify_processed_repair_attempt(
                    retry_config=retry_config,
                    invocation=_build_tool_retry_invocation(
                        ctx=ctx,
                        arguments=arguments,
                        assistant_content=assistant_text
                        or "Här är mitt korrigerade förslag:",
                        tool_call_id=correction_tool_call.id,
                    ),
                )
                if repair_outcome.events is None:
                    failure_kind = repair_outcome.failure_kind or "validation"
                    failure_fingerprint = repair_outcome.failure_fingerprint
                    _record_attempt_failure(
                        ctx,
                        failure_kind=failure_kind,
                        failure_codes=repair_outcome.failure_codes,
                    )
                    progressing_fingerprint = retry_state.progressing_fingerprint(
                        failure_fingerprint=failure_fingerprint,
                        calls_remaining=ctx.proposal_call_budget.calls_remaining,
                    )
                    if progressing_fingerprint is not None:
                        retry_feedback = (
                            correction_tool_call,
                            _build_retry_feedback(
                                target_kind=retry_config.target_kind,
                                feedback=repair_outcome.feedback
                                or "Invalid tool payload.",
                                failure_codes=repair_outcome.failure_codes,
                                retry_count=retry_state.next_retry_count,
                            ),
                            progressing_fingerprint,
                            failure_kind,
                            repair_outcome.failure_codes,
                        )
                        break
                    _log_self_correction_validation_failed_turn(
                        ctx=ctx,
                        branch="self_correction_invalid_tool_result",
                        failure_kind=repair_outcome.failure_kind,
                    )
                    yield build_self_correction_error_event(
                        feedback=repair_outcome.feedback,
                        failure_kind=repair_outcome.failure_kind,
                        failure_codes=repair_outcome.failure_codes,
                        request_id=ctx.request_id,
                    )
                    return

                for event in repair_outcome.events:
                    yield event
                return

            if retry_feedback is not None:
                (
                    correction_tool_call,
                    feedback,
                    failure_fingerprint,
                    failure_kind,
                    failure_codes,
                ) = retry_feedback
                retry_state = retry_state.record_progress(
                    failure_fingerprint=failure_fingerprint,
                    failure_kind=failure_kind,
                    failure_codes=failure_codes,
                )
                correction_messages = build_tool_retry_messages(
                    llm_messages=correction_messages,
                    tool_call=correction_tool_call,
                    assistant_content=assistant_text,
                    tool_feedback=feedback,
                )
                continue

        if assistant_text:
            _record_attempt_failure(ctx, failure_kind="missing_submission_tool")
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
            progressing_text_fingerprint = retry_state.progressing_text_fingerprint(
                failure_fingerprint=forced_outcome.failure_fingerprint,
                calls_remaining=ctx.proposal_call_budget.calls_remaining,
            )
            if (
                forced_outcome.feedback is not None
                and progressing_text_fingerprint is not None
            ):
                text_retry_feedback = _build_retry_feedback(
                    target_kind=retry_config.target_kind,
                    feedback=forced_outcome.feedback,
                    retry_count=retry_state.next_retry_count,
                )
                retry_state = retry_state.record_progress(
                    failure_fingerprint=progressing_text_fingerprint,
                    failure_kind=forced_failure_kind,
                    failure_codes=forced_outcome.failure_codes,
                    consume_text_feedback=True,
                )
                correction_messages = append_text_retry_feedback_turn(
                    llm_messages=correction_messages,
                    assistant_content=assistant_text,
                    feedback=text_retry_feedback,
                )
                continue

            logger.warning(
                "Self-correction bailed to conversational text after forced retry",
                extra={
                    "failure_kind": forced_failure_kind,
                    "failure_codes_count": len(forced_outcome.failure_codes),
                    "assistant_text_present": True,
                    "assistant_text_length": len(assistant_text),
                },
            )
            _log_self_correction_validation_failed_turn(
                ctx=ctx,
                branch="self_correction_text_forced_retry_failed",
                failure_kind=forced_failure_kind,
            )
            yield build_self_correction_error_event(
                feedback=forced_outcome.feedback,
                failure_kind=forced_failure_kind,
                failure_codes=forced_outcome.failure_codes,
                request_id=ctx.request_id,
            )
            return

        _log_self_correction_failed_turn(
            ctx=ctx,
            branch="self_correction_missing_tool_response",
            final_failure_kind="invalid_repair_response",
            final_error_code=AIBuilderErrorCode.PLANNER_INVALID_REPAIR_RESPONSE,
        )
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

    if not ctx.proposal_call_budget.try_start_call():
        return ForcedToolRetryOutcome(failure_kind="validation")
    _start_repair_attempt(ctx)

    try:
        response = await request.repair_completion(
            ctx.completion_request(
                messages=forced_messages,
                temperature=request.forced_proposal_temperature,
                tool_choice=forced_tool_choice(PROPOSE_FLOW_TOOL_NAME),
                counts_as_repair=True,
            )
        )
    except AIBuilderProviderOutcomeUnknownException:
        raise
    except Exception as error:
        _record_attempt_failure(ctx, failure_kind="provider_error")
        logger.error(
            "Forced proposal retry failed",
            exc_info=error,
            extra={"request_id": ctx.request_id},
        )
        return ForcedToolRetryOutcome()

    if not response.choices:
        _record_attempt_failure(ctx, failure_kind="missing_submission_tool")
        return ForcedToolRetryOutcome()

    choice = response.choices[0]
    if choice.finish_reason == "length":
        _record_attempt_failure(ctx, failure_kind="provider_truncation")
        return ForcedToolRetryOutcome(
            events=(
                _provider_truncation_error_event(
                    ctx=ctx,
                    phase=request.truncation_error_phase,
                ),
            )
        )

    message = choice.message
    if not message.tool_calls:
        _record_attempt_failure(ctx, failure_kind="missing_submission_tool")
        return ForcedToolRetryOutcome()

    for tool_call in message.tool_calls:
        if tool_call.function.name != PROPOSE_FLOW_TOOL_NAME:
            continue
        try:
            arguments = parse_tool_call_arguments(tool_call.function.arguments)
        except ToolArgumentParseError as error:
            _record_attempt_failure(ctx, failure_kind="parse")
            logger.warning("Forced proposal retry returned invalid payload: %s", error)
            return ForcedToolRetryOutcome(
                feedback=_invalid_tool_arguments_message(error),
                failure_kind="parse",
                failure_fingerprint=_proposal_failure_fingerprint(
                    tool_call.function.arguments,
                    failure_kind="parse",
                    failure_codes=frozenset(),
                ),
            )

        repair_outcome = await _classify_processed_repair_attempt(
            retry_config=request.retry_config,
            invocation=_build_tool_retry_invocation(
                ctx=ctx,
                arguments=arguments,
                assistant_content=request.assistant_text,
                tool_call_id=tool_call.id,
            ),
        )
        if repair_outcome.events is None:
            _record_attempt_failure(
                ctx,
                failure_kind=repair_outcome.failure_kind or "validation",
                failure_codes=repair_outcome.failure_codes,
            )
            logger.warning(
                "Forced tool retry returned an invalid result",
                extra={
                    "failure_kind": repair_outcome.failure_kind or "unknown",
                    "failure_codes_count": len(repair_outcome.failure_codes),
                    "feedback_present": bool(repair_outcome.feedback),
                    "feedback_length": len(repair_outcome.feedback or ""),
                },
            )

        return repair_outcome

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
                tool_name=PROPOSE_FLOW_TOOL_NAME,
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

    repair_outcome = await _classify_processed_repair_attempt(
        retry_config=retry_config,
        invocation=_build_tool_retry_invocation(
            ctx=ctx,
            arguments=arguments,
            assistant_content="Här är mitt korrigerade förslag:",
            tool_call_id=f"call_text_{uuid4().hex}",
        ),
    )
    if repair_outcome.events is not None:
        logger.info(
            "Accepted %s arguments returned as JSON text during forced retry.",
            PROPOSE_FLOW_TOOL_NAME,
        )
        return repair_outcome

    _record_attempt_failure(
        ctx,
        failure_kind=repair_outcome.failure_kind or "validation",
        failure_codes=repair_outcome.failure_codes,
    )

    logger.warning(
        "JSON text fallback for propose_flow returned an invalid result",
        extra={
            "failure_kind": repair_outcome.failure_kind or "unknown",
            "failure_codes_count": len(repair_outcome.failure_codes),
            "feedback_present": bool(repair_outcome.feedback),
            "feedback_length": len(repair_outcome.feedback or ""),
        },
    )
    return repair_outcome


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
