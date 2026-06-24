from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from pydantic import ValidationError

from intric.flows.ai_builder.ai_builder_litellm_completion import CompletionMetadata
from intric.flows.ai_builder.ai_builder_orchestrator import (
    PlannerOutput,
    parse_planner_output,
    summarize_parse_failure,
)
from intric.flows.ai_builder.ai_builder_structured_turn import (
    Message,
    StructuredCompletion,
    run_structured_turn,
)
from intric.flows.ai_builder.ai_builder_token_usage import CompletionTokenUsage


def _planner_output_payload(kind: str) -> dict[str, Any]:
    if kind == "ask_question":
        action_payload: dict[str, Any] = {
            "question_id": "primary_runtime_input",
            "slot_name": "primary_runtime_input",
            "prompt": "What should the flow receive?",
        }
    elif kind == "commit_architecture":
        action_payload = {"note": ""}
    elif kind == "confirm_requirements":
        action_payload = {
            "summary": "Resolved requirements.",
            "key_decisions": [],
            "input_description": "",
            "output_description": "",
            "assumptions": [],
            "manual_setup_notes": [],
        }
    else:
        action_payload = {}
    return {
        "planning_state_delta": {
            "base_planning_state_version": 0,
            "signals_added": [],
            "slots_resolved": [],
            "architecture_commit": None,
        },
        "planner_action": {
            "kind": kind,
            "payload": action_payload,
        },
    }


def _planner_output_json(kind: str) -> str:
    return json.dumps(_planner_output_payload(kind))


class TestPlannerParserFence:
    @pytest.mark.parametrize(
        "kind",
        [
            "ask_question",
            "commit_architecture",
            "confirm_requirements",
        ],
    )
    def test_accepts_existing_planner_actions(self, kind: str) -> None:
        output = parse_planner_output(_planner_output_json(kind))

        assert output.planner_action.kind == kind

    def test_rejects_propose_flow_as_planner_action(self) -> None:
        with pytest.raises(ValidationError):
            parse_planner_output(_planner_output_json("propose_flow"))

    def test_rejects_unknown_planner_action_kind(self) -> None:
        with pytest.raises(ValidationError):
            parse_planner_output(_planner_output_json("invented_action"))

    def test_rejects_extra_planner_fields(self) -> None:
        payload = _planner_output_payload("confirm_requirements")
        payload["planner_action"]["payload"]["unexpected"] = "extra"

        with pytest.raises(ValidationError):
            parse_planner_output(payload)


class _FakeCompletions:
    def __init__(self, *raw_contents: str, finish_reasons: tuple[str, ...] = ()) -> None:
        self._raw_contents = list(raw_contents)
        self._finish_reasons = list(finish_reasons)
        self.messages: list[list[Message]] = []

    async def complete(self, messages: list[Message]) -> StructuredCompletion:
        self.messages.append(messages)
        raw_content = self._raw_contents.pop(0)
        finish_reason = self._finish_reasons.pop(0) if self._finish_reasons else "stop"
        return StructuredCompletion(
            raw_content=raw_content,
            metadata=CompletionMetadata(
                finish_reason=finish_reason,
                usage=CompletionTokenUsage(
                    prompt_tokens=10,
                    completion_tokens=5,
                    total_tokens=15,
                ),
            ),
        )


def _identity(output: PlannerOutput) -> PlannerOutput:
    return output


def _accept_all(_: PlannerOutput) -> str | None:
    return None


def _reject_ask_question(output: PlannerOutput) -> str | None:
    return "ask_question_not_allowed" if output.planner_action.kind == "ask_question" else None


def _can_retry(reason: str) -> bool:
    return reason == "ask_question_not_allowed"


def _semantic_retry_messages(output: PlannerOutput, reason: str) -> list[Message]:
    return [
        {"role": "assistant", "content": output.model_dump_json()},
        {"role": "user", "content": f"Fix: {reason}"},
    ]


def _parse_retry_messages(
    base_messages: list[Message],
    failed_raw: str,
    failed_error: str,
) -> list[Message]:
    return [
        *base_messages,
        {"role": "assistant", "content": failed_raw},
        {"role": "user", "content": failed_error},
    ]


def _guard_commit_architecture(output: PlannerOutput) -> str | None:
    return (
        "repair_attempted_commit_drift"
        if output.planner_action.kind == "commit_architecture"
        else None
    )


async def _run_planner_structured_turn(
    *,
    complete: Callable[[list[Message]], Awaitable[StructuredCompletion]],
    validate: Callable[[PlannerOutput], str | None],
    repair_guard: Callable[[PlannerOutput], str | None] | None = None,
    max_semantic_retries: int = 3,
) -> Any:
    return await run_structured_turn(
        initial_messages=[{"role": "system", "content": "system"}],
        complete=complete,
        parse=parse_planner_output,
        normalize=_identity,
        validate=validate,
        can_retry_semantic=_can_retry,
        build_semantic_retry_messages=_semantic_retry_messages,
        build_parse_retry_messages=_parse_retry_messages,
        summarize_parse_failure=summarize_parse_failure,
        max_semantic_retries=max_semantic_retries,
        max_parse_retries=1,
        repair_guard=repair_guard,
    )


class TestStructuredTurnRunner:
    @pytest.mark.asyncio
    async def test_accepts_initial_parseable_output(self) -> None:
        completions = _FakeCompletions(_planner_output_json("confirm_requirements"))

        result = await _run_planner_structured_turn(
            complete=completions.complete,
            validate=_accept_all,
        )

        assert result.kind == "accepted"
        assert result.accepted_output is not None
        assert result.accepted_output.planner_action.kind == "confirm_requirements"
        assert result.llm_calls_made == 1
        assert result.semantic_repair_attempts == 0
        assert result.parse_repair_attempts == 0

    @pytest.mark.asyncio
    async def test_length_truncation_skips_parse_repair(self) -> None:
        completions = _FakeCompletions(
            '{"planning_state_delta": {"base',
            finish_reasons=("length",),
        )

        result = await _run_planner_structured_turn(
            complete=completions.complete,
            validate=_accept_all,
        )

        assert result.kind == "parse_failed"
        assert result.llm_calls_made == 1
        assert result.parse_repair_attempts == 0
        assert result.final_completion is not None
        assert result.final_completion.finish_reason == "length"

    @pytest.mark.asyncio
    async def test_semantic_retry_accepts_repaired_output(self) -> None:
        completions = _FakeCompletions(
            _planner_output_json("ask_question"),
            _planner_output_json("confirm_requirements"),
        )

        result = await _run_planner_structured_turn(
            complete=completions.complete,
            validate=_reject_ask_question,
        )

        assert result.kind == "accepted"
        assert result.accepted_output is not None
        assert result.accepted_output.planner_action.kind == "confirm_requirements"
        assert result.llm_calls_made == 2
        assert result.semantic_repair_attempts == 1
        assert result.parse_repair_attempts == 0
        assert completions.messages[1][-1]["content"] == "Fix: ask_question_not_allowed"

    @pytest.mark.asyncio
    async def test_semantic_retry_rejection_does_not_consume_attempt_on_guard(self) -> None:
        completions = _FakeCompletions(
            _planner_output_json("ask_question"),
            _planner_output_json("commit_architecture"),
        )

        result = await _run_planner_structured_turn(
            complete=completions.complete,
            validate=_reject_ask_question,
            repair_guard=_guard_commit_architecture,
        )

        assert result.kind == "rejected"
        assert result.rejection == "repair_attempted_commit_drift"
        assert result.llm_calls_made == 2
        assert result.semantic_repair_attempts == 0

    @pytest.mark.asyncio
    async def test_parse_repair_after_semantic_retry_counts_both_domains(self) -> None:
        completions = _FakeCompletions(
            _planner_output_json("ask_question"),
            "not json",
            _planner_output_json("confirm_requirements"),
        )

        result = await _run_planner_structured_turn(
            complete=completions.complete,
            validate=_reject_ask_question,
        )

        assert result.kind == "accepted"
        assert result.accepted_output is not None
        assert result.accepted_output.planner_action.kind == "confirm_requirements"
        assert result.llm_calls_made == 3
        assert result.semantic_repair_attempts == 1
        assert result.parse_repair_attempts == 1
