from __future__ import annotations

import json
from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

from intric.flows.ai_builder.ai_builder_conversation_metadata import (
    provider_safe_tool_call_id,
)
from intric.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
    TargetKind,
)
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
    ToolProcessingFailureKind,
)
from intric.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    ProposalCompletionFn,
    ProposalCompletionRequest,
    ToolProcessingResult,
    ToolRetryInvocation,
)
from intric.flows.ai_builder.ai_builder_resource_catalog import AIBuilderResourceCatalog
from intric.flows.ai_builder.ai_builder_session_turn import SessionSendTurn
from intric.flows.ai_builder.ai_builder_tools import PROPOSE_FLOW_TOOL_NAME
from intric.main.logging import get_logger

if TYPE_CHECKING:
    from intric.flows.domain.flow import Flow

logger = get_logger(__name__)
_EXTRA_RETRY_FAILURE_KINDS: frozenset[ToolProcessingFailureKind] = frozenset(
    {"recoverable_parse"}
)
EventBatch = tuple[dict[str, str], ...]


@dataclass(frozen=True, slots=True)
class ForcedToolRetryOutcome:
    events: EventBatch | None = None
    feedback: str | None = None
    failure_kind: ToolProcessingFailureKind | None = None


@dataclass(frozen=True, slots=True)
class _ProposalRepairRetryState:
    attempts_remaining: int
    extra_retry_available: bool = True
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

    def can_retry(self, *, failure_kind: ToolProcessingFailureKind | None) -> bool:
        return self.attempts_remaining > 0 or (
            failure_kind in _EXTRA_RETRY_FAILURE_KINDS and self.extra_retry_available
        )

    def can_retry_text_feedback(
        self, *, failure_kind: ToolProcessingFailureKind | None
    ) -> bool:
        return self.text_feedback_retry_available and self.can_retry(
            failure_kind=failure_kind
        )

    def consume(
        self, *, failure_kind: ToolProcessingFailureKind | None
    ) -> "_ProposalRepairRetryState":
        if self.attempts_remaining > 0:
            return replace(
                self,
                attempts_remaining=self.attempts_remaining - 1,
                retry_count=self.retry_count + 1,
            )
        if failure_kind in _EXTRA_RETRY_FAILURE_KINDS and self.extra_retry_available:
            return replace(
                self,
                extra_retry_available=False,
                retry_count=self.retry_count + 1,
            )
        return self

    def consume_text_feedback(
        self, *, failure_kind: ToolProcessingFailureKind | None
    ) -> "_ProposalRepairRetryState":
        return replace(
            self.consume(failure_kind=failure_kind),
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
    if failure_kind in {"parse", "recoverable_parse"}:
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
    if failure_kind in {"parse", "recoverable_parse"}:
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
    turn: SessionSendTurn,
    conversation: list[ConversationMessage],
    new_messages_start: int,
    arguments: dict[str, Any],
    assistant_content: str,
    tool_call_id: str,
    available_model_refs: set[str] | None,
    available_kb_refs: set[str] | None,
    resource_catalog: AIBuilderResourceCatalog | None,
    flow: "Flow | None",
    build_assistant_metadata: Callable[[], dict[str, Any] | None] | None,
) -> ToolRetryInvocation:
    return ToolRetryInvocation(
        turn=turn,
        conversation=conversation,
        new_messages_start=new_messages_start,
        arguments=arguments,
        assistant_content=assistant_content,
        tool_call_id=tool_call_id,
        available_model_refs=available_model_refs,
        available_kb_refs=available_kb_refs,
        resource_catalog=resource_catalog,
        flow=flow,
        assistant_metadata=(
            build_assistant_metadata() if build_assistant_metadata is not None else None
        ),
    )


def build_tool_retry_messages(
    *,
    llm_messages: list[dict[str, Any]],
    tool_call: Any,
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
    failure_kind: ToolProcessingFailureKind | None,
    failure_codes: frozenset[str] = frozenset(),
    retry_count: int = 1,
) -> str:
    suffix = f"Keep valid parts and fix only the listed issues. Return one complete {target_tool_name} call."
    if failure_kind in _EXTRA_RETRY_FAILURE_KINDS:
        suffix = (
            "Arrays like steps[] and form_fields[] must contain only complete JSON objects. "
            "Do not include comments, placeholders, status notes, or quoted fragments inside arrays. "
            f"Rebuild any broken array entries as normal JSON objects and return one complete {target_tool_name} call."
        )
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


async def request_self_correction(
    *,
    turn: SessionSendTurn,
    request_id: str | None = None,
    conversation: list[ConversationMessage],
    new_messages_start: int,
    error_message: str,
    llm_messages: list[dict[str, Any]],
    tool_call: Any,
    tool_schemas: list[dict[str, Any]],
    litellm_model: str,
    litellm_kwargs: dict[str, Any],
    available_model_refs: set[str] | None,
    available_kb_refs: set[str] | None,
    max_output_tokens: int,
    self_correction_temperature: float,
    self_correction_bumped_temperature: float,
    max_self_correction_retries: int,
    forced_proposal_temperature: float,
    call_proposal_completion: ProposalCompletionFn,
    process_tool_invocation: Callable[
        [ToolRetryInvocation], Awaitable[ToolProcessingResult]
    ],
    target_tool_name: str,
    target_kind: TargetKind,
    forced_tool_prompt: str,
    resource_catalog: AIBuilderResourceCatalog | None = None,
    flow: "Flow | None" = None,
    build_assistant_metadata: Callable[[], dict[str, Any] | None] | None = None,
) -> AsyncGenerator[dict[str, str], None]:
    yield build_status_event("repairing")
    correction_messages = build_tool_retry_messages(
        llm_messages=llm_messages,
        tool_call=tool_call,
        tool_feedback=(
            f"VALIDATION FAILED: {error_message}. Please fix and try again."
        ),
    )

    retry_state = _ProposalRepairRetryState.initial(
        max_attempts=max_self_correction_retries
    )
    while True:
        try:
            response = await call_proposal_completion(
                ProposalCompletionRequest(
                    messages=correction_messages,
                    tool_schemas=tool_schemas,
                    litellm_model=litellm_model,
                    litellm_kwargs=litellm_kwargs,
                    max_output_tokens=max_output_tokens,
                    temperature=(
                        self_correction_bumped_temperature
                        if retry_state.use_bumped_temperature
                        else self_correction_temperature
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
                request_id=request_id,
            )
            return

        if not response.choices:
            yield build_ai_builder_error_event(
                message="The AI planner failed to return a valid repair. Please try again.",
                code=AIBuilderErrorCode.PLANNER_INVALID_REPAIR_RESPONSE,
                phase=AIBuilderErrorPhase.SELF_CORRECTION,
                request_id=request_id,
            )
            return

        choice = response.choices[0]
        message = choice.message
        assistant_text = _safe_assistant_text(getattr(message, "content", None))

        if hasattr(message, "tool_calls") and message.tool_calls:
            retry_feedback: (
                tuple[LLMCompletionToolCall, str, ToolProcessingFailureKind | None]
                | None
            ) = None
            for correction_tool_call in message.tool_calls:
                if correction_tool_call.function.name != target_tool_name:
                    continue
                try:
                    arguments = json.loads(correction_tool_call.function.arguments)
                except Exception as error:
                    if retry_state.can_retry(failure_kind="parse"):
                        retry_feedback = (
                            correction_tool_call,
                            _build_retry_feedback(
                                target_tool_name=target_tool_name,
                                target_kind=target_kind,
                                feedback=_invalid_tool_arguments_message(error),
                                failure_kind="parse",
                                failure_codes=frozenset(),
                                retry_count=retry_state.next_retry_count,
                            ),
                            "parse",
                        )
                        break
                    yield build_self_correction_error_event(
                        feedback=_invalid_tool_arguments_message(error),
                        failure_kind="parse",
                        request_id=request_id,
                    )
                    return

                tool_result = await process_tool_invocation(
                    _build_tool_retry_invocation(
                        turn=turn,
                        conversation=conversation,
                        new_messages_start=new_messages_start,
                        arguments=arguments,
                        assistant_content=assistant_text
                        or "Här är mitt korrigerade förslag:",
                        tool_call_id=correction_tool_call.id,
                        available_model_refs=available_model_refs,
                        available_kb_refs=available_kb_refs,
                        resource_catalog=resource_catalog,
                        flow=flow,
                        build_assistant_metadata=build_assistant_metadata,
                    )
                )
                terminal_events = _repair_terminal_events(tool_result)
                if not terminal_events:
                    if retry_state.can_retry(failure_kind=tool_result.failure_kind):
                        retry_feedback = (
                            correction_tool_call,
                            _build_retry_feedback(
                                target_tool_name=target_tool_name,
                                target_kind=target_kind,
                                feedback=tool_result.feedback
                                or "Invalid tool payload.",
                                failure_kind=tool_result.failure_kind,
                                failure_codes=tool_result.failure_codes,
                                retry_count=retry_state.next_retry_count,
                            ),
                            tool_result.failure_kind,
                        )
                        break
                    yield build_self_correction_error_event(
                        feedback=tool_result.feedback,
                        failure_kind=tool_result.failure_kind,
                        request_id=request_id,
                    )
                    return

                for event in terminal_events:
                    yield event
                return

            if retry_feedback is not None:
                correction_tool_call, feedback, failure_kind = retry_feedback
                retry_state = retry_state.consume(failure_kind=failure_kind)
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
            forced_outcome = await retry_forced_tool_after_text(
                correction_messages=correction_messages,
                assistant_text=assistant_text,
                tool_schemas=tool_schemas,
                litellm_model=litellm_model,
                litellm_kwargs=litellm_kwargs,
                turn=turn,
                conversation=conversation,
                new_messages_start=new_messages_start,
                available_model_refs=available_model_refs,
                available_kb_refs=available_kb_refs,
                max_output_tokens=max_output_tokens,
                target_tool_name=target_tool_name,
                forced_tool_prompt=forced_tool_prompt,
                forced_proposal_temperature=forced_proposal_temperature,
                call_proposal_completion=call_proposal_completion,
                process_tool_invocation=process_tool_invocation,
                resource_catalog=resource_catalog,
                flow=flow,
                build_assistant_metadata=build_assistant_metadata,
                request_id=request_id,
            )
            if forced_outcome.events is not None:
                for event in forced_outcome.events:
                    yield event
                return

            forced_failure_kind = forced_outcome.failure_kind or "validation"
            if (
                forced_outcome.feedback is not None
                and retry_state.can_retry_text_feedback(
                    failure_kind=forced_failure_kind
                )
            ):
                text_retry_feedback = _build_retry_feedback(
                    target_tool_name=target_tool_name,
                    target_kind=target_kind,
                    feedback=forced_outcome.feedback,
                    failure_kind=forced_failure_kind,
                    retry_count=retry_state.next_retry_count,
                )
                retry_state = retry_state.consume_text_feedback(
                    failure_kind=forced_failure_kind
                )
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
                request_id=request_id,
            )
            return

        yield build_ai_builder_error_event(
            message="The AI planner failed. Please try again.",
            code=AIBuilderErrorCode.PLANNER_INVALID_REPAIR_RESPONSE,
            phase=AIBuilderErrorPhase.SELF_CORRECTION,
            request_id=request_id,
        )
        return


async def retry_forced_tool_after_text(
    *,
    correction_messages: list[dict[str, Any]],
    assistant_text: str,
    tool_schemas: list[dict[str, Any]],
    litellm_model: str,
    litellm_kwargs: dict[str, Any],
    turn: SessionSendTurn,
    conversation: list[ConversationMessage],
    new_messages_start: int,
    available_model_refs: set[str] | None,
    available_kb_refs: set[str] | None,
    max_output_tokens: int,
    target_tool_name: str,
    forced_tool_prompt: str,
    forced_proposal_temperature: float,
    call_proposal_completion: ProposalCompletionFn,
    process_tool_invocation: Callable[
        [ToolRetryInvocation], Awaitable[ToolProcessingResult]
    ],
    resource_catalog: AIBuilderResourceCatalog | None = None,
    flow: "Flow | None" = None,
    build_assistant_metadata: Callable[[], dict[str, Any] | None] | None = None,
    request_id: str | None = None,
) -> ForcedToolRetryOutcome:
    if looks_like_information_request(assistant_text):
        return ForcedToolRetryOutcome()

    direct_outcome = await _try_process_json_text_as_tool_arguments(
        assistant_text=assistant_text,
        turn=turn,
        conversation=conversation,
        new_messages_start=new_messages_start,
        available_model_refs=available_model_refs,
        available_kb_refs=available_kb_refs,
        target_tool_name=target_tool_name,
        process_tool_invocation=process_tool_invocation,
        resource_catalog=resource_catalog,
        flow=flow,
        build_assistant_metadata=build_assistant_metadata,
    )
    if (
        direct_outcome.events is not None
        or direct_outcome.feedback is not None
        or direct_outcome.failure_kind is not None
    ):
        return direct_outcome

    forced_messages = list(correction_messages) + [
        {"role": "assistant", "content": assistant_text},
        {
            "role": "user",
            "content": forced_tool_prompt,
        },
    ]

    try:
        response = await call_proposal_completion(
            ProposalCompletionRequest(
                messages=forced_messages,
                tool_schemas=tool_schemas,
                litellm_model=litellm_model,
                litellm_kwargs=litellm_kwargs,
                max_output_tokens=max_output_tokens,
                temperature=forced_proposal_temperature,
                tool_choice={
                    "type": "function",
                    "function": {"name": target_tool_name},
                },
                counts_as_repair=True,
            )
        )
    except Exception as error:
        logger.error(
            "Forced proposal retry failed",
            exc_info=error,
            extra={"request_id": request_id},
        )
        return ForcedToolRetryOutcome()

    if not response.choices:
        return ForcedToolRetryOutcome()

    choice = response.choices[0]
    message = choice.message
    if not (hasattr(message, "tool_calls") and message.tool_calls):
        return ForcedToolRetryOutcome()

    for tool_call in message.tool_calls:
        if tool_call.function.name != target_tool_name:
            continue
        try:
            arguments = json.loads(tool_call.function.arguments)
        except Exception as error:
            logger.warning("Forced proposal retry returned invalid payload: %s", error)
            return ForcedToolRetryOutcome(
                feedback=_invalid_tool_arguments_message(error),
                failure_kind="parse",
            )

        tool_result = await process_tool_invocation(
            _build_tool_retry_invocation(
                turn=turn,
                conversation=conversation,
                new_messages_start=new_messages_start,
                arguments=arguments,
                assistant_content=assistant_text,
                tool_call_id=tool_call.id,
                available_model_refs=available_model_refs,
                available_kb_refs=available_kb_refs,
                resource_catalog=resource_catalog,
                flow=flow,
                build_assistant_metadata=build_assistant_metadata,
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


async def _try_process_json_text_as_tool_arguments(
    *,
    assistant_text: str,
    turn: SessionSendTurn,
    conversation: list[ConversationMessage],
    new_messages_start: int,
    available_model_refs: set[str] | None,
    available_kb_refs: set[str] | None,
    target_tool_name: str,
    process_tool_invocation: Callable[
        [ToolRetryInvocation], Awaitable[ToolProcessingResult]
    ],
    resource_catalog: AIBuilderResourceCatalog | None,
    flow: "Flow | None",
    build_assistant_metadata: Callable[[], dict[str, Any] | None] | None = None,
) -> ForcedToolRetryOutcome:
    arguments = _parse_json_object_text(assistant_text)
    if arguments is None:
        return ForcedToolRetryOutcome()

    tool_result = await process_tool_invocation(
        _build_tool_retry_invocation(
            turn=turn,
            conversation=conversation,
            new_messages_start=new_messages_start,
            arguments=arguments,
            assistant_content="Här är mitt korrigerade förslag:",
            tool_call_id=f"call_text_{uuid4().hex}",
            available_model_refs=available_model_refs,
            available_kb_refs=available_kb_refs,
            resource_catalog=resource_catalog,
            flow=flow,
            build_assistant_metadata=build_assistant_metadata,
        )
    )
    terminal_events = _repair_terminal_events(tool_result)
    if terminal_events:
        logger.info(
            "Accepted %s arguments returned as JSON text during forced retry.",
            target_tool_name,
        )
        return ForcedToolRetryOutcome(events=terminal_events)

    logger.warning(
        "JSON text fallback for %s returned %s issue: %s",
        target_tool_name,
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
