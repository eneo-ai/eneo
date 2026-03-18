from __future__ import annotations

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
from intric.flows.ai_builder.ai_builder_tools import PROPOSE_FLOW_TOOL_NAME
from intric.main.logging import get_logger

logger = get_logger(__name__)


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
            "tool_calls": [{
                "id": tool_call.id,
                "type": "function",
                "function": {
                    "name": tool_call.function.name,
                    "arguments": tool_call.function.arguments,
                },
            }],
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
    max_self_correction_retries: int,
    call_repair_completion: Callable[..., Awaitable[Any]],
    process_proposal_arguments: Callable[..., Awaitable[Any]],
    build_self_correction_error_event: Callable[..., dict[str, str]],
    retry_forced_proposal_after_text: Callable[..., Awaitable[dict[str, str] | None]],
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
    while True:
        try:
            response = await call_repair_completion(
                messages=correction_messages,
                tool_schemas=tool_schemas,
                litellm_model=litellm_model,
                litellm_kwargs=litellm_kwargs,
                max_output_tokens=max_output_tokens,
                temperature=self_correction_temperature,
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

        if hasattr(message, "tool_calls") and message.tool_calls:
            retry_feedback: tuple[Any, str] | None = None
            for correction_tool_call in message.tool_calls:
                if correction_tool_call.function.name != PROPOSE_FLOW_TOOL_NAME:
                    continue
                try:
                    arguments = json.loads(correction_tool_call.function.arguments)
                except Exception as error:
                    if attempts_remaining > 0:
                        retry_feedback = (
                            correction_tool_call,
                            f"CORRECTION STILL INVALID: Invalid flow specification: {error}. Keep valid parts, but return one complete propose_flow draft that fixes the listed issues.",
                        )
                        break
                    yield build_self_correction_error_event(
                        feedback=f"Invalid flow specification: {error}",
                        failure_kind="parse",
                    )
                    return

                proposal_result = await process_proposal_arguments(
                    session_id=session_id,
                    conversation=conversation,
                    new_messages_start=new_messages_start,
                    arguments=arguments,
                    assistant_content=message.content or "Här är mitt korrigerade förslag:",
                    tool_call_id=correction_tool_call.id,
                    available_model_refs=available_model_refs,
                    available_kb_refs=available_kb_refs,
                    flow=flow,
                )
                if proposal_result.plan_event is None:
                    if attempts_remaining > 0:
                        retry_feedback = (
                            correction_tool_call,
                            "CORRECTION STILL INVALID: "
                            f"{proposal_result.feedback or 'Invalid flow specification.'}\n"
                            "Keep valid parts and fix only the listed issues. Return one complete propose_flow draft.",
                        )
                        break
                    yield build_self_correction_error_event(
                        feedback=proposal_result.feedback,
                        failure_kind=proposal_result.failure_kind,
                    )
                    return

                yield proposal_result.plan_event
                return

            if retry_feedback is not None:
                attempts_remaining -= 1
                correction_tool_call, feedback = retry_feedback
                correction_messages = append_retry_feedback_turn(
                    llm_messages=correction_messages,
                    tool_call=correction_tool_call,
                    assistant_content=message.content,
                    tool_feedback=feedback,
                )
                continue

        if message.content:
            forced_plan = await retry_forced_proposal_after_text(
                correction_messages=correction_messages,
                assistant_text=message.content,
                tool_schemas=tool_schemas,
                litellm_model=litellm_model,
                litellm_kwargs=litellm_kwargs,
                session_id=session_id,
                conversation=conversation,
                new_messages_start=new_messages_start,
                available_model_refs=available_model_refs,
                available_kb_refs=available_kb_refs,
                max_output_tokens=max_output_tokens,
                flow=flow,
            )
            if forced_plan is not None:
                yield forced_plan
                return

            yield build_text_event(message.content)
        return


async def retry_forced_proposal_after_text(
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
    forced_proposal_temperature: float,
    call_repair_completion: Callable[..., Awaitable[Any]],
    process_proposal_arguments: Callable[..., Awaitable[Any]],
    flow: Any = None,
) -> dict[str, str] | None:
    if looks_like_information_request(assistant_text):
        return None

    forced_messages = list(correction_messages) + [
        {"role": "assistant", "content": assistant_text},
        {
            "role": "user",
            "content": (
                "Your previous reply was prose only. "
                "Now call propose_flow with a complete flow draft that includes steps. "
                "Do not answer with prose."
            ),
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
                "function": {"name": PROPOSE_FLOW_TOOL_NAME},
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
        if tool_call.function.name != PROPOSE_FLOW_TOOL_NAME:
            continue
        try:
            arguments = json.loads(tool_call.function.arguments)
        except Exception as error:
            logger.warning("Forced proposal retry returned invalid payload: %s", error)
            return None

        proposal_result = await process_proposal_arguments(
            session_id=session_id,
            conversation=conversation,
            new_messages_start=new_messages_start,
            arguments=arguments,
            assistant_content=assistant_text,
            tool_call_id=tool_call.id,
            available_model_refs=available_model_refs,
            available_kb_refs=available_kb_refs,
            flow=flow,
        )
        if proposal_result.plan_event is None:
            logger.warning(
                "Forced proposal retry returned %s issue: %s",
                proposal_result.failure_kind or "unknown",
                proposal_result.feedback or "missing feedback",
            )
            return None

        return proposal_result.plan_event

    return None
