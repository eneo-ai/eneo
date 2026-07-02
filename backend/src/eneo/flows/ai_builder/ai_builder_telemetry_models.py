from __future__ import annotations

from pydantic import BaseModel


class SessionTelemetrySummary(BaseModel):
    planner_request_count: int = 0
    clarification_question_count: int = 0
    prompt_tokens_total: int = 0
    completion_tokens_total: int = 0
    total_tokens_total: int = 0
    tool_call_count_total: int = 0
    auxiliary_llm_call_count: int = 0
    architecture_commit_count: int = 0
    repair_attempts_total: int = 0
    parse_repair_attempts_total: int = 0
    wall_clock_ms_total: int = 0
    llm_calls_made_total: int = 0
    token_usage_estimated: bool = False
    last_request_id: str | None = None
    last_model: str | None = None
    last_finish_reason: str | None = None
    last_outcome_kind: str | None = None
    last_token_usage_source: str | None = None
    last_token_usage_estimated: bool = False


__all__ = ["SessionTelemetrySummary"]
