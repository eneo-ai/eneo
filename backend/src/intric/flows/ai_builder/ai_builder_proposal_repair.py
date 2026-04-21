from __future__ import annotations

import inspect
import json
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import Any
from uuid import UUID

from intric.flows.ai_builder.ai_builder_events import (
    build_error_event,
    build_status_event,
    build_text_event,
)
from intric.flows.ai_builder.ai_builder_interaction_utils import (
    looks_like_information_request,
)
from intric.main.logging import get_logger

logger = get_logger(__name__)
_EXTRA_RETRY_FAILURE_KINDS = frozenset({"recoverable_parse"})


def _invalid_tool_arguments_message(error: Exception) -> str:
    return f"Invalid tool call arguments: {error}"


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


def _retry_budget_available(
    *,
    attempts_remaining: int,
    failure_kind: str | None,
    extra_retry_available: bool,
) -> bool:
    return attempts_remaining > 0 or (
        failure_kind in _EXTRA_RETRY_FAILURE_KINDS and extra_retry_available
    )


def _consume_retry_budget(
    *,
    attempts_remaining: int,
    failure_kind: str | None,
    extra_retry_available: bool,
) -> tuple[int, bool]:
    if attempts_remaining > 0:
        return attempts_remaining - 1, extra_retry_available
    if failure_kind in _EXTRA_RETRY_FAILURE_KINDS and extra_retry_available:
        return attempts_remaining, False
    return attempts_remaining, extra_retry_available


def _build_retry_feedback(
    *,
    target_tool_name: str,
    feedback: str,
    failure_kind: str | None,
    retry_count: int = 1,
) -> str:
    suffix = f"Keep valid parts and fix only the listed issues. Return one complete {target_tool_name} call."
    if failure_kind in _EXTRA_RETRY_FAILURE_KINDS:
        suffix = (
            "Arrays like steps[] and form_fields[] must contain only complete JSON objects. "
            "Do not include comments, placeholders, status notes, or quoted fragments inside arrays. "
            f"Rebuild any broken array entries as normal JSON objects and return one complete {target_tool_name} call."
        )
    if target_tool_name == "create_flow":
        suffix = (
            "Every steps[] item must be one complete create step object with at least name, instructions, input_source, and output_type. "
            "Structured field definitions belong only in output_fields on a JSON step, and runtime form fields belong only in form_fields[]. "
            "Keep valid parts and fix only the listed issues. Return one complete create_flow call."
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
    build_self_correction_error_event: Callable[..., dict[str, str]],
    retry_forced_tool_after_text: Callable[..., Awaitable[dict[str, str] | None]],
    process_tool_kwargs: dict[str, Any] | None = None,
    flow: Any = None,
) -> AsyncGenerator[dict[str, str], None]:
    yield build_status_event("repairing")
    correction_messages = build_tool_retry_messages(
        llm_messages=llm_messages,
        tool_call=tool_call,
        tool_feedback=(
            f"VALIDATION FAILED: {error_message}. Please fix and try again."
        ),
    )

    attempts_remaining = max_self_correction_retries
    extra_retry_available = True
    retry_count = 0  # 0 = initial correction, 1 = first retry, 2 = second retry, …
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
                    if retry_count >= 1
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
                    if _retry_budget_available(
                        attempts_remaining=attempts_remaining,
                        failure_kind="parse",
                        extra_retry_available=extra_retry_available,
                    ):
                        retry_feedback = (
                            correction_tool_call,
                            _build_retry_feedback(
                                target_tool_name=target_tool_name,
                                feedback=_invalid_tool_arguments_message(error),
                                failure_kind="parse",
                                retry_count=retry_count + 1,
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
                if tool_result.event is None:
                    if _retry_budget_available(
                        attempts_remaining=attempts_remaining,
                        failure_kind=tool_result.failure_kind,
                        extra_retry_available=extra_retry_available,
                    ):
                        retry_feedback = (
                            correction_tool_call,
                            _build_retry_feedback(
                                target_tool_name=target_tool_name,
                                feedback=tool_result.feedback
                                or "Invalid tool payload.",
                                failure_kind=tool_result.failure_kind,
                                retry_count=retry_count + 1,
                            ),
                            tool_result.failure_kind,
                        )
                        break
                    yield build_self_correction_error_event(
                        feedback=tool_result.feedback,
                        failure_kind=tool_result.failure_kind,
                    )
                    return

                yield tool_result.event
                return

            if retry_feedback is not None:
                correction_tool_call, feedback, failure_kind = retry_feedback
                attempts_remaining, extra_retry_available = _consume_retry_budget(
                    attempts_remaining=attempts_remaining,
                    failure_kind=failure_kind,
                    extra_retry_available=extra_retry_available,
                )
                retry_count += 1
                correction_messages = append_retry_feedback_turn(
                    llm_messages=correction_messages,
                    tool_call=correction_tool_call,
                    assistant_content=assistant_text,
                    tool_feedback=feedback,
                )
                continue

        if assistant_text:
            forced_event = await retry_forced_tool_after_text(
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
            )
            if forced_event is not None:
                yield forced_event
                return

            yield build_text_event(assistant_text)
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
) -> dict[str, str] | None:
    if looks_like_information_request(assistant_text):
        return None

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
        if tool_result.event is None:
            logger.warning(
                "Forced tool retry returned %s issue: %s",
                tool_result.failure_kind or "unknown",
                tool_result.feedback or "missing feedback",
            )
            return None

        return tool_result.event

    return None


def _safe_assistant_text(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None
