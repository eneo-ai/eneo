"""AI Builder turn + session telemetry.

The session aggregator here reads metrics out of persisted assistant
messages. By design it covers **committed turns only** — turns that
became part of the durable conversation history the user sees.

Rejected planner outputs and parse failures never persist assistant-
message metadata. Their metrics therefore do not appear in
``summarize_session_telemetry`` and do not influence session health
scores. That is intentional: the session aggregator is the contract
for "what the user experienced," not "what the planner attempted."

Observability for failed turns lives on the structured log stream
(``logger.info`` lines emitted around ``run_planner_turn`` already
record every outcome including ``rejected`` / ``parse_failed`` with
their ``TurnTelemetry``). Operators who need failed-turn aggregates
consume those logs.

Extending the session aggregator to include failed-turn metrics is
tracked as deferred work; the trigger is the first downstream
consumer that needs failed-turn counts inline with committed-turn
metrics (e.g. a future observability dashboard that cannot join
against the log stream). That enhancement must add a dedicated
side-channel rather than mutate the current committed-turns-only
contract.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, cast

from intric.flows.ai_builder.ai_builder_models import ConversationMessage

if TYPE_CHECKING:
    from intric.flows.ai_builder.ai_builder_planner_turn import TurnTelemetry

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


def build_planner_telemetry_from_turn(
    telemetry: "TurnTelemetry",
    *,
    used_auxiliary_llm: bool = False,
    tool_call_count: int = 0,
) -> dict[str, Any]:
    """Render a `TurnTelemetry` dataclass into the persisted dict shape.

    The per-turn record on assistant-message metadata has lived as a
    dict since the legacy function-calling transport. This helper
    keeps that shape stable across the orchestrator migration while
    adding the new per-turn fields (`wall_clock_ms`, `llm_calls_made`,
    `repair_attempts`, `parse_repair_attempts`,
    `architecture_commit_populated`, `outcome_kind`) so the session
    aggregator can reason about commit-populated rate, repair-loop
    trigger rate, and parse-repair trigger rate without peeking at
    domain objects.

    `repair_attempts` and `parse_repair_attempts` are intentionally
    separate counters. `repair_attempts` counts evaluator-domain
    corrective turns (the planner's parsed output violated an
    invariant). `parse_repair_attempts` counts parse-domain corrective
    turns (the LLM's raw bytes could not be decoded into a
    PlannerOutput at all). Conflating the two would obscure whether a
    session is hitting schema drift vs. transport-level malformation.

    `used_auxiliary_llm` and `tool_call_count` carry their legacy
    meaning — they are set by the caller's own bookkeeping (auxiliary
    adjudication LLM for free-form answers, and any structured-question
    assistant messages the caller materializes from ask_question
    actions). Both default to ``False`` / ``0`` when the caller does
    not populate them.
    """
    return {
        "request_id": telemetry.request_id,
        "model": telemetry.model,
        "finish_reason": telemetry.finish_reason,
        "prompt_tokens": telemetry.prompt_tokens,
        "completion_tokens": telemetry.completion_tokens,
        "total_tokens": telemetry.total_tokens,
        "tool_call_count": tool_call_count,
        "used_auxiliary_llm": used_auxiliary_llm,
        "outcome_kind": telemetry.outcome_kind,
        "wall_clock_ms": telemetry.wall_clock_ms,
        "llm_calls_made": telemetry.llm_calls_made,
        "repair_attempts": telemetry.repair_attempts,
        "parse_repair_attempts": telemetry.parse_repair_attempts,
        "architecture_commit_populated": telemetry.architecture_commit_populated,
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
        "architecture_commit_count": 0,
        "repair_attempts_total": 0,
        "parse_repair_attempts_total": 0,
        "wall_clock_ms_total": 0,
        "llm_calls_made_total": 0,
        "last_request_id": None,
        "last_model": None,
        "last_finish_reason": None,
        "last_outcome_kind": None,
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
        "last_request_id": _safe_str(value.get("last_request_id")),
        "last_model": _safe_str(value.get("last_model")),
        "last_finish_reason": _safe_str(value.get("last_finish_reason")),
        "last_outcome_kind": _safe_str(value.get("last_outcome_kind")),
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
    if planner_telemetry.get("used_auxiliary_llm") is True:
        summary["auxiliary_llm_call_count"] += 1
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
    summary["last_request_id"] = _safe_str(planner_telemetry.get("request_id"))
    summary["last_model"] = _safe_str(planner_telemetry.get("model"))
    summary["last_finish_reason"] = _safe_str(planner_telemetry.get("finish_reason"))
    summary["last_outcome_kind"] = _safe_str(planner_telemetry.get("outcome_kind"))


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


def _non_negative_int(value: object) -> int:
    parsed = _safe_int(value)
    if parsed is None or parsed < 0:
        return 0
    return parsed


def _safe_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
