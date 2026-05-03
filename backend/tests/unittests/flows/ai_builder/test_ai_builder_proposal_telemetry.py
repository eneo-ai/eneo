from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from typing import get_args
from unittest.mock import MagicMock

from intric.flows.ai_builder.ai_builder_create_outline import OUTLINE_FLOW_TOOL_NAME
from intric.flows.ai_builder.ai_builder_edit_tool_schema import EDIT_FLOW_TOOL_NAME
from intric.flows.ai_builder.ai_builder_proposal_telemetry import (
    PROPOSAL_TELEMETRY_LOG_KEY,
    PROPOSAL_TELEMETRY_SCHEMA_VERSION,
    ProposalTurnTelemetry,
    ToolProcessingFailureKind,
    log_proposal_first_attempt,
    log_proposal_repair_invoked,
    proposal_failure_kind_from_tool_failure,
)

_REPO_ROOT = Path(__file__).resolve().parents[5]
_FAILURE_KIND_SOURCE_FILES = (
    _REPO_ROOT / "backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py",
    _REPO_ROOT / "backend/src/intric/flows/ai_builder/ai_builder_edit_proposal.py",
)


def _make_response(
    *,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="tool_calls",
                message=SimpleNamespace(
                    tool_calls=[],
                    content=None,
                ),
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        ),
    )


def _tool_processing_failure_kinds_from_source() -> set[str]:
    emitted: set[str] = set()
    for path in _FAILURE_KIND_SOURCE_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Name):
                function_name = func.id
            elif isinstance(func, ast.Attribute):
                function_name = func.attr
            else:
                function_name = None
            if function_name != "ToolProcessingResult":
                continue
            for keyword in node.keywords:
                if (
                    keyword.arg == "failure_kind"
                    and isinstance(keyword.value, ast.Constant)
                    and isinstance(keyword.value.value, str)
                ):
                    emitted.add(keyword.value.value)
    return emitted


def test_proposal_turn_telemetry_extends_canonical_planner_payload() -> None:
    telemetry = ProposalTurnTelemetry(
        request_id="req-telemetry",
        model="openai/gpt-5.4-nano",
    )
    telemetry.record_response(
        _make_response(prompt_tokens=10, completion_tokens=3, total_tokens=13),
        messages=[{"role": "user", "content": "Build"}],
    )
    assert telemetry.record_first_attempt(
        tool_name=OUTLINE_FLOW_TOOL_NAME,
        success=False,
        failure_kind="validation",
    )
    telemetry.record_repair_invocation(reason="validation")

    payload = telemetry.build_planner_telemetry(tool_call_count=1)

    assert payload["request_id"] == "req-telemetry"
    assert payload["total_tokens"] == 13
    assert payload["proposal_first_attempt_tool"] == OUTLINE_FLOW_TOOL_NAME
    assert payload["proposal_first_attempt_success"] is False
    assert payload["proposal_first_attempt_failure_kind"] == "validation"
    assert payload["proposal_repair_invocation_count"] == 1
    assert payload["proposal_repair_invocation_reasons"] == ["validation"]


def test_proposal_turn_telemetry_first_attempt_is_first_write_wins() -> None:
    telemetry = ProposalTurnTelemetry(
        request_id="req-first-write",
        model="openai/gpt-5.4-nano",
    )

    assert telemetry.record_first_attempt(
        tool_name=OUTLINE_FLOW_TOOL_NAME,
        success=False,
        failure_kind="missing_submission_tool",
    )
    assert not telemetry.record_first_attempt(
        tool_name=OUTLINE_FLOW_TOOL_NAME,
        success=True,
    )

    payload = telemetry.build_planner_telemetry()
    assert payload["proposal_first_attempt_success"] is False
    assert payload["proposal_first_attempt_failure_kind"] == "missing_submission_tool"


def test_proposal_failure_kind_sanitizes_recoverable_parse() -> None:
    assert proposal_failure_kind_from_tool_failure("recoverable_parse") == "parse"
    assert proposal_failure_kind_from_tool_failure("parse") == "parse"
    assert proposal_failure_kind_from_tool_failure("validation") == "validation"
    assert proposal_failure_kind_from_tool_failure("quality") == "quality"
    assert proposal_failure_kind_from_tool_failure(None) == "validation"


def test_proposal_first_attempt_log_uses_nested_payload() -> None:
    event_logger = MagicMock()

    log_proposal_first_attempt(
        request_id="req-log",
        tool_name=OUTLINE_FLOW_TOOL_NAME,
        success=False,
        failure_kind="quality",
        event_logger=event_logger,
    )

    event_logger.info.assert_called_once()
    (message,) = event_logger.info.call_args.args
    assert message == "ai_builder_proposal_first_attempt"
    payload = event_logger.info.call_args.kwargs["extra"][PROPOSAL_TELEMETRY_LOG_KEY]
    assert payload == {
        "event": "ai_builder.proposal.first_attempt",
        "schema_version": PROPOSAL_TELEMETRY_SCHEMA_VERSION,
        "operation": "first_attempt",
        "request_id": "req-log",
        "tool_name": OUTLINE_FLOW_TOOL_NAME,
        "success": False,
        "failure_kind": "quality",
    }


def test_successful_proposal_first_attempt_log_omits_failure_kind() -> None:
    event_logger = MagicMock()

    log_proposal_first_attempt(
        request_id="req-log",
        tool_name=OUTLINE_FLOW_TOOL_NAME,
        success=True,
        failure_kind=None,
        event_logger=event_logger,
    )

    payload = event_logger.info.call_args.kwargs["extra"][PROPOSAL_TELEMETRY_LOG_KEY]
    assert "failure_kind" not in payload


def test_proposal_repair_log_uses_nested_payload() -> None:
    event_logger = MagicMock()

    log_proposal_repair_invoked(
        request_id="req-log",
        tool_name=EDIT_FLOW_TOOL_NAME,
        reason="parse",
        event_logger=event_logger,
    )

    event_logger.info.assert_called_once()
    (message,) = event_logger.info.call_args.args
    assert message == "ai_builder_proposal_repair_invoked"
    payload = event_logger.info.call_args.kwargs["extra"][PROPOSAL_TELEMETRY_LOG_KEY]
    assert payload == {
        "event": "ai_builder.proposal.repair_invoked",
        "schema_version": PROPOSAL_TELEMETRY_SCHEMA_VERSION,
        "operation": "repair_invoked",
        "request_id": "req-log",
        "tool_name": EDIT_FLOW_TOOL_NAME,
        "reason": "parse",
    }


def test_emitted_failure_kinds_are_a_subset_of_the_taxonomy() -> None:
    emitted = _tool_processing_failure_kinds_from_source()

    assert emitted
    assert emitted <= set(get_args(ToolProcessingFailureKind))
