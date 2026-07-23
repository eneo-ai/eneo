"""AI Builder turn + session telemetry.

The session aggregator here reads metrics out of persisted assistant
messages. By design it covers **committed turns only** — turns that
became part of the durable conversation history the user sees.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, cast

from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    loose_tool_call_name,
    loose_tool_call_names_from_message,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
)
from eneo.flows.ai_builder.ai_builder_tool_names import (
    ASK_STRUCTURED_QUESTION_TOOL_NAME,
)

PLANNER_TELEMETRY_KEY = "planner_telemetry"
SESSION_TELEMETRY_KEY = "session_telemetry"


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
    auxiliary_llm_call_count: int | None = None,
    token_usage_source: object | None = None,
    token_usage_estimated: bool = False,
    outcome_kind: object | None = None,
    wall_clock_ms: int = 0,
    llm_calls_made: int = 1,
    repair_attempts: int = 0,
    parse_repair_attempts: int = 0,
    architecture_commit_populated: bool = False,
    proposal_first_attempt_tool: str | None = None,
    proposal_target_kind: str | None = None,
    proposal_first_attempt_success: bool | None = None,
    proposal_first_attempt_failure_kind: str | None = None,
    proposal_repair_invocation_count: int | None = None,
    proposal_repair_invocation_reasons: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Build the persisted assistant-message telemetry payload.

    Proposal fields stay string-typed here so this canonical builder does not
    import proposal-specific Literal taxonomies.
    """
    total = _safe_int(total_tokens)
    telemetry: dict[str, Any] = {
        "request_id": request_id,
        "model": model,
        "finish_reason": _safe_str(finish_reason),
        "prompt_tokens": _safe_int(prompt_tokens),
        "completion_tokens": _safe_int(completion_tokens),
        "total_tokens": total,
        "tool_call_count": tool_call_count,
        "used_auxiliary_llm": used_auxiliary_llm,
        "auxiliary_llm_call_count": (
            _non_negative_int(auxiliary_llm_call_count)
            if auxiliary_llm_call_count is not None
            else int(used_auxiliary_llm)
        ),
        "token_usage_source": _safe_str(token_usage_source)
        or ("provider" if total is not None else None),
        "token_usage_estimated": token_usage_estimated,
        "outcome_kind": _safe_str(outcome_kind),
        "wall_clock_ms": wall_clock_ms,
        "llm_calls_made": llm_calls_made,
        "repair_attempts": repair_attempts,
        "parse_repair_attempts": parse_repair_attempts,
        "architecture_commit_populated": architecture_commit_populated,
    }
    if proposal_first_attempt_success is not None:
        telemetry["proposal_first_attempt_tool"] = _safe_str(
            proposal_first_attempt_tool
        )
        telemetry["proposal_target_kind"] = _safe_str(proposal_target_kind)
        telemetry["proposal_first_attempt_success"] = proposal_first_attempt_success
        telemetry["proposal_first_attempt_failure_kind"] = _safe_str(
            proposal_first_attempt_failure_kind
        )
    if proposal_repair_invocation_count is not None:
        telemetry["proposal_repair_invocation_count"] = _non_negative_int(
            proposal_repair_invocation_count
        )
        telemetry["proposal_repair_invocation_reasons"] = list(
            proposal_repair_invocation_reasons or ()
        )
    return telemetry


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
    """Aggregate committed-turn metrics from the persisted conversation.

    Only turns that became assistant messages contribute; rejected and
    parse-failed turns are absent from the conversation history and
    therefore from this summary. See the module docstring for the
    committed-turns-only contract.
    """
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
        question_count = _count_ask_question_names(
            loose_tool_call_names_from_message(message)
        )
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

    question_count = _count_ask_question_names(
        name
        for tool_call in tool_calls or ()
        if (name := loose_tool_call_name(tool_call)) is not None
    )
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
        "architecture_commit_count": 0,
        "repair_attempts_total": 0,
        "parse_repair_attempts_total": 0,
        "wall_clock_ms_total": 0,
        "llm_calls_made_total": 0,
        "token_usage_estimated": False,
        "last_request_id": None,
        "last_model": None,
        "last_finish_reason": None,
        "last_outcome_kind": None,
        "last_token_usage_source": None,
        "last_token_usage_estimated": False,
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
        "planner_request_count": _non_negative_int(value.get("planner_request_count")),
        "clarification_question_count": _non_negative_int(
            value.get("clarification_question_count")
        ),
        "prompt_tokens_total": _non_negative_int(value.get("prompt_tokens_total")),
        "completion_tokens_total": _non_negative_int(
            value.get("completion_tokens_total")
        ),
        "total_tokens_total": _non_negative_int(value.get("total_tokens_total")),
        "tool_call_count_total": _non_negative_int(value.get("tool_call_count_total")),
        "auxiliary_llm_call_count": _non_negative_int(
            value.get("auxiliary_llm_call_count")
        ),
        "architecture_commit_count": _non_negative_int(
            value.get("architecture_commit_count")
        ),
        "repair_attempts_total": _non_negative_int(value.get("repair_attempts_total")),
        "parse_repair_attempts_total": _non_negative_int(
            value.get("parse_repair_attempts_total")
        ),
        "wall_clock_ms_total": _non_negative_int(value.get("wall_clock_ms_total")),
        "llm_calls_made_total": _non_negative_int(value.get("llm_calls_made_total")),
        "token_usage_estimated": value.get("token_usage_estimated") is True,
        "last_request_id": _safe_str(value.get("last_request_id")),
        "last_model": _safe_str(value.get("last_model")),
        "last_finish_reason": _safe_str(value.get("last_finish_reason")),
        "last_outcome_kind": _safe_str(value.get("last_outcome_kind")),
        "last_token_usage_source": _safe_str(value.get("last_token_usage_source")),
        "last_token_usage_estimated": value.get("last_token_usage_estimated") is True,
    }


def _apply_planner_telemetry(
    summary: dict[str, Any],
    planner_telemetry: Mapping[str, Any],
) -> None:
    summary["planner_request_count"] += 1
    summary["prompt_tokens_total"] += _non_negative_int(
        planner_telemetry.get("prompt_tokens")
    )
    summary["completion_tokens_total"] += _non_negative_int(
        planner_telemetry.get("completion_tokens")
    )
    summary["total_tokens_total"] += _non_negative_int(
        planner_telemetry.get("total_tokens")
    )
    summary["tool_call_count_total"] += _non_negative_int(
        planner_telemetry.get("tool_call_count")
    )
    summary["auxiliary_llm_call_count"] += _non_negative_int(
        planner_telemetry.get("auxiliary_llm_call_count")
    )
    if planner_telemetry.get("architecture_commit_populated") is True:
        summary["architecture_commit_count"] += 1
    summary["repair_attempts_total"] += _non_negative_int(
        planner_telemetry.get("repair_attempts")
    )
    summary["parse_repair_attempts_total"] += _non_negative_int(
        planner_telemetry.get("parse_repair_attempts")
    )
    summary["wall_clock_ms_total"] += _non_negative_int(
        planner_telemetry.get("wall_clock_ms")
    )
    summary["llm_calls_made_total"] += _non_negative_int(
        planner_telemetry.get("llm_calls_made")
    )
    if planner_telemetry.get("token_usage_estimated") is True:
        summary["token_usage_estimated"] = True
    summary["last_request_id"] = _safe_str(planner_telemetry.get("request_id"))
    summary["last_model"] = _safe_str(planner_telemetry.get("model"))
    summary["last_finish_reason"] = _safe_str(planner_telemetry.get("finish_reason"))
    summary["last_outcome_kind"] = _safe_str(planner_telemetry.get("outcome_kind"))
    summary["last_token_usage_source"] = _safe_str(
        planner_telemetry.get("token_usage_source")
    )
    summary["last_token_usage_estimated"] = (
        planner_telemetry.get("token_usage_estimated") is True
    )


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


def _count_ask_question_names(names: Iterable[str]) -> int:
    return sum(1 for name in names if name == ASK_STRUCTURED_QUESTION_TOOL_NAME)


def _safe_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _non_negative_int(value: object) -> int:
    parsed = _safe_int(value)
    if parsed is None or parsed < 0:
        return 0
    return parsed


def _safe_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
