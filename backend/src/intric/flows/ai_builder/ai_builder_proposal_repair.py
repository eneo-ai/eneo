from __future__ import annotations

import inspect
import json
from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol, cast
from uuid import UUID, uuid4

from intric.flows.ai_builder.ai_builder_events import (
    build_error_event,
    build_status_event,
    build_text_event,
)
from intric.flows.ai_builder.ai_builder_interaction_utils import (
    looks_like_information_request,
)
from intric.flows.ai_builder.ai_builder_proposal_telemetry import (
    ToolProcessingFailureKind,
)
from intric.main.logging import get_logger

logger = get_logger(__name__)
_EXTRA_RETRY_FAILURE_KINDS: frozenset[ToolProcessingFailureKind] = frozenset(
    {"recoverable_parse"}
)
EventBatch = tuple[dict[str, str], ...]


class BuildSelfCorrectionErrorEvent(Protocol):
    def __call__(
        self,
        *,
        feedback: str | None,
        failure_kind: ToolProcessingFailureKind | None,
    ) -> dict[str, str]: ...


@dataclass(frozen=True, slots=True)
class _ProposalRepairRetryState:
    attempts_remaining: int
    extra_retry_available: bool = True
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

    def consume(
        self, *, failure_kind: ToolProcessingFailureKind | None
    ) -> "_ProposalRepairRetryState":
        if self.attempts_remaining > 0:
            return _ProposalRepairRetryState(
                attempts_remaining=self.attempts_remaining - 1,
                extra_retry_available=self.extra_retry_available,
                retry_count=self.retry_count + 1,
            )
        if failure_kind in _EXTRA_RETRY_FAILURE_KINDS and self.extra_retry_available:
            return _ProposalRepairRetryState(
                attempts_remaining=self.attempts_remaining,
                extra_retry_available=False,
                retry_count=self.retry_count + 1,
            )
        return self


def _invalid_tool_arguments_message(error: Exception) -> str:
    return f"Invalid tool call arguments: {error}"


def _tool_result_has_events(tool_result: Any) -> bool:
    event = getattr(tool_result, "event", None)
    events = getattr(tool_result, "events", None)
    return event is not None or bool(events)


def _tool_result_events(tool_result: Any) -> EventBatch:
    event = getattr(tool_result, "event", None)
    events = tuple(getattr(tool_result, "events", tuple()) or tuple())
    if event is None:
        return events
    return (event, *events)


def _build_process_tool_kwargs(
    *,
    process_tool_arguments: Callable[..., Awaitable[Any]],
    process_tool_kwargs: dict[str, Any] | None,
    flow: Any,
) -> dict[str, Any]:
    kwargs = dict(process_tool_kwargs or {})
    if "flow" in kwargs:
        return kwargs

    try:
        signature = inspect.signature(process_tool_arguments)
    except (TypeError, ValueError):
        return kwargs

    if "flow" in signature.parameters:
        kwargs["flow"] = flow
    return kwargs


def _add_assistant_metadata_if_supported(
    *,
    process_tool_arguments: Callable[..., Awaitable[Any]],
    invocation_kwargs: dict[str, Any],
    build_assistant_metadata: Callable[[], dict[str, Any] | None] | None,
) -> None:
    if build_assistant_metadata is None:
        return
    try:
        signature = inspect.signature(process_tool_arguments)
    except (TypeError, ValueError):
        return
    accepts_kwargs = any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )
    if "assistant_metadata" in signature.parameters or accepts_kwargs:
        invocation_kwargs["assistant_metadata"] = build_assistant_metadata()


def build_tool_retry_messages(
    *,
    llm_messages: list[dict[str, Any]],
    tool_call: Any,
    tool_feedback: str,
    assistant_content: str | None = None,
) -> list[dict[str, Any]]:
    return list(llm_messages) + [
        {
            "role": "assistant",
            "content": assistant_content,
            "tool_calls": [
                {
                    "id": tool_call.id,
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
            "tool_call_id": tool_call.id,
            "content": tool_feedback,
        },
    ]


def append_retry_feedback_turn(
    *,
    llm_messages: list[dict[str, Any]],
    tool_call: Any,
    assistant_content: str | None,
    tool_feedback: str,
) -> list[dict[str, Any]]:
    return build_tool_retry_messages(
        llm_messages=llm_messages,
        tool_call=tool_call,
        tool_feedback=tool_feedback,
        assistant_content=assistant_content,
    )


def _build_retry_feedback(
    *,
    target_tool_name: str,
    feedback: str,
    failure_kind: ToolProcessingFailureKind | None,
    retry_count: int = 1,
) -> str:
    suffix = f"Keep valid parts and fix only the listed issues. Return one complete {target_tool_name} call."
    if failure_kind in _EXTRA_RETRY_FAILURE_KINDS:
        suffix = (
            "Arrays like steps[] and form_fields[] must contain only complete JSON objects. "
            "Do not include comments, placeholders, status notes, or quoted fragments inside arrays. "
            f"Rebuild any broken array entries as normal JSON objects and return one complete {target_tool_name} call."
        )
    if target_tool_name == "outline_flow":
        suffix = (
            "Every steps[] item must be one complete semantic outline step with at least name and task. "
            "Runtime form inputs belong in top-level input_fields[], and steps should reference them by name in uses_input_fields. "
            "Do not emit input_source, input_type, input_bindings, output_mode, refs, ids, hashes, or timestamps; backend compiles those mechanics. "
            "Keep valid semantic parts and fix only the listed issues. Return one complete outline_flow call."
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
    session_id: UUID,
    conversation: list[Any],
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
    call_repair_completion: Callable[..., Awaitable[Any]],
    process_tool_arguments: Callable[..., Awaitable[Any]],
    target_tool_name: str,
    forced_tool_prompt: str,
    build_self_correction_error_event: BuildSelfCorrectionErrorEvent,
    retry_forced_tool_after_text: Callable[..., Awaitable[EventBatch | None]],
    process_tool_kwargs: dict[str, Any] | None = None,
    flow: Any = None,
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
            response = await call_repair_completion(
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
            )
        except Exception as error:
            logger.error("Self-correction LLM call failed", exc_info=error)
            yield build_error_event(
                message="The AI planner failed. Please try again.",
                code="planner_upstream_error",
                phase="self_correction",
            )
            return

        choice = response.choices[0]
        message = choice.message
        assistant_text = _safe_assistant_text(getattr(message, "content", None))

        if hasattr(message, "tool_calls") and message.tool_calls:
            retry_feedback: tuple[Any, str, str | None] | None = None
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
                                feedback=_invalid_tool_arguments_message(error),
                                failure_kind="parse",
                                retry_count=retry_state.next_retry_count,
                            ),
                            "parse",
                        )
                        break
                    yield build_self_correction_error_event(
                        feedback=_invalid_tool_arguments_message(error),
                        failure_kind="parse",
                    )
                    return

                invocation_kwargs = _build_process_tool_kwargs(
                    process_tool_arguments=process_tool_arguments,
                    process_tool_kwargs=process_tool_kwargs,
                    flow=flow,
                )
                _add_assistant_metadata_if_supported(
                    process_tool_arguments=process_tool_arguments,
                    invocation_kwargs=invocation_kwargs,
                    build_assistant_metadata=build_assistant_metadata,
                )
                tool_result = await process_tool_arguments(
                    session_id=session_id,
                    conversation=conversation,
                    new_messages_start=new_messages_start,
                    arguments=arguments,
                    assistant_content=assistant_text
                    or "Här är mitt korrigerade förslag:",
                    tool_call_id=correction_tool_call.id,
                    available_model_refs=available_model_refs,
                    available_kb_refs=available_kb_refs,
                    **invocation_kwargs,
                )
                if not _tool_result_has_events(tool_result):
                    if retry_state.can_retry(failure_kind=tool_result.failure_kind):
                        retry_feedback = (
                            correction_tool_call,
                            _build_retry_feedback(
                                target_tool_name=target_tool_name,
                                feedback=tool_result.feedback
                                or "Invalid tool payload.",
                                failure_kind=tool_result.failure_kind,
                                retry_count=retry_state.next_retry_count,
                            ),
                            tool_result.failure_kind,
                        )
                        break
                    yield build_self_correction_error_event(
                        feedback=tool_result.feedback,
                        failure_kind=tool_result.failure_kind,
                    )
                    return

                for event in _tool_result_events(tool_result):
                    yield event
                return

            if retry_feedback is not None:
                correction_tool_call, feedback, failure_kind = retry_feedback
                retry_state = retry_state.consume(failure_kind=failure_kind)
                correction_messages = append_retry_feedback_turn(
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
            forced_events = await retry_forced_tool_after_text(
                correction_messages=correction_messages,
                assistant_text=assistant_text,
                tool_schemas=tool_schemas,
                litellm_model=litellm_model,
                litellm_kwargs=litellm_kwargs,
                session_id=session_id,
                conversation=conversation,
                new_messages_start=new_messages_start,
                available_model_refs=available_model_refs,
                available_kb_refs=available_kb_refs,
                max_output_tokens=max_output_tokens,
                target_tool_name=target_tool_name,
                forced_tool_prompt=forced_tool_prompt,
                process_tool_arguments=process_tool_arguments,
                process_tool_kwargs=process_tool_kwargs,
                flow=flow,
                build_assistant_metadata=build_assistant_metadata,
            )
            if forced_events is not None:
                for event in forced_events:
                    yield event
                return

            logger.warning(
                "Self-correction bailed to conversational text after forced retry: %s",
                assistant_text,
            )
            yield build_self_correction_error_event(
                feedback=None,
                failure_kind="validation",
            )
            return

        yield build_error_event(
            message="The AI planner failed. Please try again.",
            code="planner_invalid_repair_response",
            phase="self_correction",
        )
        return


async def retry_forced_tool_after_text(
    *,
    correction_messages: list[dict[str, Any]],
    assistant_text: str,
    tool_schemas: list[dict[str, Any]],
    litellm_model: str,
    litellm_kwargs: dict[str, Any],
    session_id: UUID,
    conversation: list[Any],
    new_messages_start: int,
    available_model_refs: set[str] | None,
    available_kb_refs: set[str] | None,
    max_output_tokens: int,
    target_tool_name: str,
    forced_tool_prompt: str,
    forced_proposal_temperature: float,
    call_repair_completion: Callable[..., Awaitable[Any]],
    process_tool_arguments: Callable[..., Awaitable[Any]],
    process_tool_kwargs: dict[str, Any] | None = None,
    flow: Any = None,
    build_assistant_metadata: Callable[[], dict[str, Any] | None] | None = None,
) -> EventBatch | None:
    if looks_like_information_request(assistant_text):
        return None

    direct_events = await _try_process_json_text_as_tool_arguments(
        assistant_text=assistant_text,
        session_id=session_id,
        conversation=conversation,
        new_messages_start=new_messages_start,
        available_model_refs=available_model_refs,
        available_kb_refs=available_kb_refs,
        target_tool_name=target_tool_name,
        process_tool_arguments=process_tool_arguments,
        process_tool_kwargs=process_tool_kwargs,
        flow=flow,
        build_assistant_metadata=build_assistant_metadata,
    )
    if direct_events is not None:
        return direct_events

    forced_messages = list(correction_messages) + [
        {"role": "assistant", "content": assistant_text},
        {
            "role": "user",
            "content": forced_tool_prompt,
        },
    ]

    try:
        response = await call_repair_completion(
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
        )
    except Exception as error:
        logger.error("Forced proposal retry failed", exc_info=error)
        return None

    choice = response.choices[0]
    message = choice.message
    if not (hasattr(message, "tool_calls") and message.tool_calls):
        return None

    for tool_call in message.tool_calls:
        if tool_call.function.name != target_tool_name:
            continue
        try:
            arguments = json.loads(tool_call.function.arguments)
        except Exception as error:
            logger.warning("Forced proposal retry returned invalid payload: %s", error)
            return None

        invocation_kwargs = _build_process_tool_kwargs(
            process_tool_arguments=process_tool_arguments,
            process_tool_kwargs=process_tool_kwargs,
            flow=flow,
        )
        _add_assistant_metadata_if_supported(
            process_tool_arguments=process_tool_arguments,
            invocation_kwargs=invocation_kwargs,
            build_assistant_metadata=build_assistant_metadata,
        )
        tool_result = await process_tool_arguments(
            session_id=session_id,
            conversation=conversation,
            new_messages_start=new_messages_start,
            arguments=arguments,
            assistant_content=assistant_text,
            tool_call_id=tool_call.id,
            available_model_refs=available_model_refs,
            available_kb_refs=available_kb_refs,
            **invocation_kwargs,
        )
        if not _tool_result_has_events(tool_result):
            logger.warning(
                "Forced tool retry returned %s issue: %s",
                tool_result.failure_kind or "unknown",
                tool_result.feedback or "missing feedback",
            )
            return None

        return _tool_result_events(tool_result)

    return None


async def _try_process_json_text_as_tool_arguments(
    *,
    assistant_text: str,
    session_id: UUID,
    conversation: list[Any],
    new_messages_start: int,
    available_model_refs: set[str] | None,
    available_kb_refs: set[str] | None,
    target_tool_name: str,
    process_tool_arguments: Callable[..., Awaitable[Any]],
    process_tool_kwargs: dict[str, Any] | None,
    flow: Any,
    build_assistant_metadata: Callable[[], dict[str, Any] | None] | None = None,
) -> EventBatch | None:
    arguments = _parse_json_object_text(assistant_text)
    if arguments is None:
        return None

    invocation_kwargs = _build_process_tool_kwargs(
        process_tool_arguments=process_tool_arguments,
        process_tool_kwargs=process_tool_kwargs,
        flow=flow,
    )
    _add_assistant_metadata_if_supported(
        process_tool_arguments=process_tool_arguments,
        invocation_kwargs=invocation_kwargs,
        build_assistant_metadata=build_assistant_metadata,
    )
    tool_result = await process_tool_arguments(
        session_id=session_id,
        conversation=conversation,
        new_messages_start=new_messages_start,
        arguments=arguments,
        assistant_content="Här är mitt korrigerade förslag:",
        tool_call_id=f"call_text_{uuid4().hex}",
        available_model_refs=available_model_refs,
        available_kb_refs=available_kb_refs,
        **invocation_kwargs,
    )
    if _tool_result_has_events(tool_result):
        logger.info(
            "Accepted %s arguments returned as JSON text during forced retry.",
            target_tool_name,
        )
        return _tool_result_events(tool_result)

    logger.warning(
        "JSON text fallback for %s returned %s issue: %s",
        target_tool_name,
        tool_result.failure_kind or "unknown",
        tool_result.feedback or "missing feedback",
    )
    return None


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
