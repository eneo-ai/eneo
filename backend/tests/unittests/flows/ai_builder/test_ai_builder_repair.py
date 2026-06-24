from __future__ import annotations

from intric.flows.ai_builder.ai_builder_orchestration_pipeline import (
    MAX_ORCHESTRATOR_REPAIR_RETRIES,
    MAX_PARSE_REPAIR_RETRIES,
    build_parse_repair_user_message,
    build_repair_user_message,
)
from intric.flows.ai_builder.ai_builder_orchestrator import RejectionReason


def test_parse_repair_has_separate_single_retry_budget() -> None:
    assert MAX_PARSE_REPAIR_RETRIES == 1


def test_parse_repair_prompt_pins_raw_json_contract() -> None:
    content = build_parse_repair_user_message(
        parse_error_message="missing planner_action"
    )

    assert "single raw JSON object" in content
    assert "Do NOT wrap" in content
    assert "Do NOT add prose" in content
    assert "`architecture_commit: null`" in content
    assert "the server derives the architecture" in content


def test_repair_prompt_includes_rejection_detail_not_code() -> None:
    unique_detail = "question_id='x' already asked this session"
    rejection = RejectionReason(code="duplicate_question", detail=unique_detail)

    content = build_repair_user_message(rejection=rejection)

    assert unique_detail in content
    assert rejection.code not in content


def test_duplicate_question_prompt_forbids_repeating_question() -> None:
    content = build_repair_user_message(
        rejection=RejectionReason(
            code="duplicate_question",
            detail=(
                "question_id='runtime_metadata_fields' already asked this session "
                "and no new evidence arrived since"
            ),
        )
    )

    assert "Do NOT repeat the same `ask_question`" in content
    assert "latest user message" in content
    assert "different unresolved slot" in content


def test_missing_commit_delta_prompt_keeps_commit_server_derived() -> None:
    content = build_repair_user_message(
        rejection=RejectionReason(
            code="architecture_commit_missing_delta",
            detail="commit_architecture action requires a populated architecture_commit delta",
        )
    )

    assert "planning_state_delta.architecture_commit" in content
    assert "server derives" in content
    assert "Flow Capability Manifest" in content
    assert "architecture_hash" in content
    assert "committed_at" in content


def test_max_orchestrator_repair_retries_is_three() -> None:
    assert MAX_ORCHESTRATOR_REPAIR_RETRIES == 3
