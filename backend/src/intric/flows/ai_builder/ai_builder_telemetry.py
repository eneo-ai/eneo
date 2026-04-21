from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, cast

from intric.flows.ai_builder.ai_builder_models import ConversationMessage

PLANNER_TELEMETRY_KEY = "planner_telemetry"
SESSION_TELEMETRY_KEY = "session_telemetry"
_ASK_STRUCTURED_QUESTION_TOOL_NAME = "ask_structured_question"


def build_planner_telemetry(
    *,
    request_id: str,
    model: str,
    finish_reason: object,
    prompt_tokens: object,
    completion_tokens: object,
    total_tokens: object,
    tool_call_count: int,
    used_auxiliary_llm: bool,
) -> dict[str, Any]:
    return {
        "request_id": request_id,
        "model": model,
        "finish_reason": _safe_str(finish_reason),
        "prompt_tokens": _safe_int(prompt_tokens),
        "completion_tokens": _safe_int(completion_tokens),
        "total_tokens": _safe_int(total_tokens),
        "tool_call_count": tool_call_count,
        "used_auxiliary_llm": used_auxiliary_llm,
    }


def build_assistant_message_metadata(
    conversation: Sequence[ConversationMessage],
    *,
    planner_telemetry: dict[str, Any] | None = None,
    tool_calls: Sequence[object] | None = None,
    base_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    metadata = dict(base_metadata) if isinstance(base_metadata, Mapping) else {}

    if planner_telemetry is not None:
        metadata[PLANNER_TELEMETRY_KEY] = planner_telemetry

    session_telemetry = advance_session_telemetry(
        conversation,
        planner_telemetry=planner_telemetry,
        tool_calls=tool_calls,
    )
    if session_telemetry is not None:
        metadata[SESSION_TELEMETRY_KEY] = session_telemetry

    return metadata or None


def summarize_session_telemetry(
    conversation: Sequence[ConversationMessage | Mapping[str, Any]],
) -> dict[str, Any] | None:
    latest = _latest_session_telemetry(conversation)
    if latest is not None:
        return latest

    summary = _empty_session_telemetry()
    has_data = False

    for message in conversation:
        metadata = _message_metadata(message)
        planner_telemetry = _planner_telemetry_from_metadata(metadata)
        if planner_telemetry is not None:
            _apply_planner_telemetry(summary, planner_telemetry)
            has_data = True
        question_count = _clarification_question_count(_message_tool_calls(message))
        if question_count:
            summary["clarification_question_count"] += question_count
            has_data = True

    return summary if has_data else None


def advance_session_telemetry(
    conversation: Sequence[ConversationMessage],
    *,
    planner_telemetry: Mapping[str, Any] | None = None,
    tool_calls: Sequence[object] | None = None,
) -> dict[str, Any] | None:
    existing_summary = summarize_session_telemetry(conversation)
    summary = existing_summary or _empty_session_telemetry()
    has_data = existing_summary is not None

    if planner_telemetry is not None:
        _apply_planner_telemetry(summary, planner_telemetry)
        has_data = True

    question_count = _clarification_question_count(tool_calls)
    if question_count:
        summary["clarification_question_count"] += question_count
        has_data = True

    return summary if has_data else None


def _empty_session_telemetry() -> dict[str, Any]:
    return {
        "planner_request_count": 0,
        "clarification_question_count": 0,
        "prompt_tokens_total": 0,
        "completion_tokens_total": 0,
        "total_tokens_total": 0,
        "tool_call_count_total": 0,
        "auxiliary_llm_call_count": 0,
        "last_request_id": None,
        "last_model": None,
        "last_finish_reason": None,
    }


def _latest_session_telemetry(
    conversation: Sequence[ConversationMessage | Mapping[str, Any]],
) -> dict[str, Any] | None:
    for message in reversed(conversation):
        metadata = _message_metadata(message)
        if not metadata:
            continue
        session_telemetry = metadata.get(SESSION_TELEMETRY_KEY)
        if isinstance(session_telemetry, Mapping):
            return _sanitize_session_telemetry(
                cast(Mapping[str, Any], session_telemetry)
            )
    return None


def _sanitize_session_telemetry(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "planner_request_count": _safe_int(value.get("planner_request_count")) or 0,
        "clarification_question_count": _safe_int(
            value.get("clarification_question_count")
        )
        or 0,
        "prompt_tokens_total": _safe_int(value.get("prompt_tokens_total")) or 0,
        "completion_tokens_total": _safe_int(value.get("completion_tokens_total")) or 0,
        "total_tokens_total": _safe_int(value.get("total_tokens_total")) or 0,
        "tool_call_count_total": _safe_int(value.get("tool_call_count_total")) or 0,
        "auxiliary_llm_call_count": _safe_int(value.get("auxiliary_llm_call_count"))
        or 0,
        "last_request_id": _safe_str(value.get("last_request_id")),
        "last_model": _safe_str(value.get("last_model")),
        "last_finish_reason": _safe_str(value.get("last_finish_reason")),
    }


def _apply_planner_telemetry(
    summary: dict[str, Any],
    planner_telemetry: Mapping[str, Any],
) -> None:
    summary["planner_request_count"] += 1
    summary["prompt_tokens_total"] += (
        _safe_int(planner_telemetry.get("prompt_tokens")) or 0
    )
    summary["completion_tokens_total"] += (
        _safe_int(planner_telemetry.get("completion_tokens")) or 0
    )
    summary["total_tokens_total"] += (
        _safe_int(planner_telemetry.get("total_tokens")) or 0
    )
    summary["tool_call_count_total"] += (
        _safe_int(planner_telemetry.get("tool_call_count")) or 0
    )
    if planner_telemetry.get("used_auxiliary_llm") is True:
        summary["auxiliary_llm_call_count"] += 1
    summary["last_request_id"] = _safe_str(planner_telemetry.get("request_id"))
    summary["last_model"] = _safe_str(planner_telemetry.get("model"))
    summary["last_finish_reason"] = _safe_str(planner_telemetry.get("finish_reason"))


def _planner_telemetry_from_metadata(
    metadata: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(metadata, Mapping):
        return None
    planner_telemetry = metadata.get(PLANNER_TELEMETRY_KEY)
    if not isinstance(planner_telemetry, Mapping):
        return None
    return dict(cast(Mapping[str, Any], planner_telemetry))


def _message_metadata(
    message: ConversationMessage | Mapping[str, Any],
) -> Mapping[str, Any] | None:
    if isinstance(message, ConversationMessage):
        return message.metadata if isinstance(message.metadata, Mapping) else None
    metadata = message.get("metadata")
    return cast(Mapping[str, Any], metadata) if isinstance(metadata, Mapping) else None


def _message_tool_calls(
    message: ConversationMessage | Mapping[str, Any],
) -> Sequence[object] | None:
    if isinstance(message, ConversationMessage):
        return message.tool_calls
    tool_calls = message.get("tool_calls")
    return (
        cast(Sequence[object], tool_calls) if isinstance(tool_calls, Sequence) else None
    )


def _clarification_question_count(tool_calls: Sequence[object] | None) -> int:
    if not isinstance(tool_calls, Sequence):
        return 0
    count = 0
    for tool_call in tool_calls:
        if not isinstance(tool_call, Mapping):
            function = getattr(tool_call, "function", None)
            name = getattr(function, "name", None)
        else:
            tool_call_map = cast(Mapping[str, Any], tool_call)
            name = tool_call_map.get("name")
        if name == _ASK_STRUCTURED_QUESTION_TOOL_NAME:
            count += 1
    return count


def _safe_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _safe_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
