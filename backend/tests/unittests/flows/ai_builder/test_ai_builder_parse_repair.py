"""Tests for parse-failure recovery in the AI Builder planner pipeline.

Covers three lanes that keep the user out of the red banner when the
LLM produces unparseable bytes:

- `parse_planner_output` unwraps an exact whole-response markdown code
  fence before `json.loads`. Greedy extraction from inside prose is
  explicitly NOT supported — accepting a fenced rationale block as the
  real planner output would defeat `extra="forbid"`.
- `summarize_parse_failure` produces a privacy-safe log summary
  (fingerprint + validation `loc/type` + shape hints) without ever
  surfacing the raw body.
- `run_planner_pipeline` calls `repair_parse_failure` once when the
  initial LLM call returns unparseable bytes AND the initial
  completion was not truncation. Successful repair routes through the
  normal evaluator path; failed repair bubbles `parse_failed` with
  `parse_repair_attempts=1` so operators can distinguish
  parse-domain from evaluator-domain retries.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from intric.flows.ai_builder.ai_builder_orchestration_pipeline import (
    PipelineOutcome,
    run_planner_pipeline,
)
from intric.flows.ai_builder.ai_builder_orchestrator import (
    OrchestrationContext,
    parse_planner_output,
    summarize_parse_failure,
)
from intric.flows.ai_builder.ai_builder_repair import (
    MAX_PARSE_REPAIR_RETRIES,
    repair_parse_failure,
)
from intric.flows.ai_builder.planning_state import PlanningState  # noqa: F401


def _valid_ask_question_raw() -> str:
    return json.dumps(
        {
            "planning_state_delta": {
                "base_planning_state_version": 0,
                "signals_added": [],
                "slots_resolved": [],
            },
            "planner_action": {
                "kind": "ask_question",
                "payload": {
                    "question_id": "primary_runtime_input",
                    "slot_name": "primary_runtime_input",
                    "prompt": "What is the input?",
                },
            },
        }
    )


def _orchestration_context() -> OrchestrationContext:
    return OrchestrationContext(
        current_version=0,
        session_state=PlanningState.empty(),
        asked_question_ids=frozenset(),
        has_new_evidence=False,
        unresolved_architectural_choices=frozenset({"primary_runtime_input"}),
        required_slot_names=frozenset({"primary_runtime_input"}),
    )


def _litellm_response(raw: str, *, finish_reason: str = "stop") -> Any:
    class _Message:
        def __init__(self, content: str) -> None:
            self.content = content

    class _Choice:
        def __init__(self, content: str, reason: str) -> None:
            self.message = _Message(content)
            self.finish_reason = reason

    class _Usage:
        prompt_tokens = 123
        completion_tokens = 45
        total_tokens = 168

    class _Response:
        def __init__(self, content: str, reason: str) -> None:
            self.choices = [_Choice(content, reason)]
            self.usage = _Usage()

    return _Response(raw, finish_reason)


class TestParsePlannerOutputFenceUnwrap:
    def test_strips_json_language_fence(self) -> None:
        raw = "```json\n" + _valid_ask_question_raw() + "\n```"
        output = parse_planner_output(raw)
        assert output.planner_action.kind == "ask_question"

    def test_strips_bare_fence(self) -> None:
        raw = "```\n" + _valid_ask_question_raw() + "\n```"
        output = parse_planner_output(raw)
        assert output.planner_action.kind == "ask_question"

    def test_fence_with_trailing_whitespace_unwrapped(self) -> None:
        raw = "```json\n" + _valid_ask_question_raw() + "\n```\n\n"
        output = parse_planner_output(raw)
        assert output.planner_action.kind == "ask_question"

    def test_no_fence_unchanged(self) -> None:
        output = parse_planner_output(_valid_ask_question_raw())
        assert output.planner_action.kind == "ask_question"

    def test_fence_embedded_in_prose_not_extracted(self) -> None:
        raw = (
            "Here is my response:\n"
            "```json\n" + _valid_ask_question_raw() + "\n```\n"
            "Done."
        )
        with pytest.raises(json.JSONDecodeError):
            parse_planner_output(raw)


class TestSummarizeParseFailure:
    def test_validation_error_emits_kind_and_locs(self) -> None:
        bad = json.dumps(
            {
                "planning_state_delta": {
                    "base_planning_state_version": 0,
                    "signals_added": [],
                    "slots_resolved": [],
                    "ghost_field": "boo",
                },
                "planner_action": {
                    "kind": "ask_question",
                    "payload": {
                        "question_id": "q-1",
                        "slot_name": "primary_runtime_input",
                        "prompt": "?",
                    },
                },
            }
        )
        summary: dict[str, Any]
        try:
            parse_planner_output(bad)
            pytest.fail("expected validation error")
        except ValidationError as exc:
            summary = summarize_parse_failure(bad, exc)

        assert summary["parse_error_kind"] == "validation_error"
        assert isinstance(summary["validation_locs"], list)
        assert summary["validation_locs"]
        assert all(
            "loc" in item and "type" in item for item in summary["validation_locs"]
        )
        assert summary["raw_length"] == len(bad.encode("utf-8"))
        assert len(summary["raw_sha256_prefix"]) == 16
        assert summary["starts_with_json_object"] is True
        assert summary["looks_like_markdown_fence"] is False

    def test_json_decode_error_emits_kind_and_message(self) -> None:
        bad = "not a json body at all"
        summary: dict[str, Any]
        try:
            parse_planner_output(bad)
            pytest.fail("expected decode error")
        except json.JSONDecodeError as exc:
            summary = summarize_parse_failure(bad, exc)

        assert summary["parse_error_kind"] == "json_decode_error"
        assert isinstance(summary["json_decode_message"], str)
        assert summary["starts_with_json_object"] is False
        assert summary["looks_like_markdown_fence"] is False

    def test_raw_body_never_in_summary(self) -> None:
        secret = "SECRET_USER_CONTENT_42"
        body = f'{{"planning_state_delta": "{secret}"}}'
        summary: dict[str, Any]
        try:
            parse_planner_output(body)
            pytest.fail("expected parse error")
        except (ValidationError, json.JSONDecodeError) as exc:
            summary = summarize_parse_failure(body, exc)

        rendered = json.dumps(summary)
        assert secret not in rendered

    def test_fence_detector_on_fence_wrapped_body(self) -> None:
        body = "```json\n{not valid}\n```"
        summary: dict[str, Any]
        try:
            parse_planner_output(body)
            pytest.fail("expected parse error")
        except (ValidationError, json.JSONDecodeError) as exc:
            summary = summarize_parse_failure(body, exc)

        assert summary["looks_like_markdown_fence"] is True


class TestRepairParseFailure:
    @pytest.mark.asyncio
    async def test_returns_repaired_when_llm_emits_valid_json(self) -> None:
        litellm_client = AsyncMock()
        litellm_client.acompletion.return_value = _litellm_response(
            _valid_ask_question_raw()
        )

        outcome = await repair_parse_failure(
            litellm_client=litellm_client,
            litellm_model="openai/gpt-5.4-mini",
            litellm_kwargs={},
            base_messages=[{"role": "user", "content": "build a flow"}],
            failed_output_raw="not json",
            parse_error_message="Expecting value",
        )

        assert outcome.kind == "repaired"
        assert outcome.repaired_output is not None
        assert outcome.repaired_output.planner_action.kind == "ask_question"

    @pytest.mark.asyncio
    async def test_returns_parse_failed_with_diagnostics_when_still_malformed(
        self,
    ) -> None:
        litellm_client = AsyncMock()
        litellm_client.acompletion.return_value = _litellm_response("still not json")

        outcome = await repair_parse_failure(
            litellm_client=litellm_client,
            litellm_model="openai/gpt-5.4-mini",
            litellm_kwargs={},
            base_messages=[{"role": "user", "content": "build a flow"}],
            failed_output_raw="not json",
            parse_error_message="Expecting value",
        )

        assert outcome.kind == "parse_failed"
        assert outcome.parse_failure_diagnostics is not None
        assert outcome.parse_failure_diagnostics["parse_error_kind"] == (
            "json_decode_error"
        )

    @pytest.mark.asyncio
    async def test_prompt_includes_parse_error_message(self) -> None:
        litellm_client = AsyncMock()
        litellm_client.acompletion.return_value = _litellm_response(
            _valid_ask_question_raw()
        )

        await repair_parse_failure(
            litellm_client=litellm_client,
            litellm_model="openai/gpt-5.4-mini",
            litellm_kwargs={},
            base_messages=[{"role": "user", "content": "build a flow"}],
            failed_output_raw="not json at all",
            parse_error_message="Expecting value: line 1 column 1",
        )

        call_kwargs = litellm_client.acompletion.call_args.kwargs
        corrective_user = call_kwargs["messages"][-1]
        assert corrective_user["role"] == "user"
        assert "Expecting value: line 1 column 1" in corrective_user["content"]
        assert "markdown code fences" in corrective_user["content"]


class TestPipelineParseRepair:
    @pytest.mark.asyncio
    async def test_initial_parse_fail_then_repair_success_accepts(self) -> None:
        litellm_client = AsyncMock()
        litellm_client.acompletion.side_effect = [
            _litellm_response("prose before json"),
            _litellm_response(_valid_ask_question_raw()),
        ]

        outcome: PipelineOutcome = await run_planner_pipeline(
            litellm_client=litellm_client,
            litellm_model="openai/gpt-5.4-mini",
            litellm_kwargs={},
            base_messages=[{"role": "user", "content": "build a flow"}],
            orchestration_context=_orchestration_context(),
        )

        assert outcome.kind == "accepted"
        assert outcome.llm_calls_made == 2
        assert outcome.parse_repair_attempts == 1
        assert outcome.repair_attempts == 0

    @pytest.mark.asyncio
    async def test_initial_parse_fail_and_repair_also_fails_returns_parse_failed(
        self,
    ) -> None:
        litellm_client = AsyncMock()
        litellm_client.acompletion.side_effect = [
            _litellm_response("prose before json"),
            _litellm_response("still prose after the retry"),
        ]

        outcome = await run_planner_pipeline(
            litellm_client=litellm_client,
            litellm_model="openai/gpt-5.4-mini",
            litellm_kwargs={},
            base_messages=[{"role": "user", "content": "build a flow"}],
            orchestration_context=_orchestration_context(),
        )

        assert outcome.kind == "parse_failed"
        assert outcome.llm_calls_made == 2
        assert outcome.parse_repair_attempts == 1
        assert outcome.parse_failure_diagnostics is not None
        assert outcome.parse_failure_diagnostics["parse_error_kind"] == (
            "json_decode_error"
        )

    @pytest.mark.asyncio
    async def test_initial_length_truncation_skips_parse_repair(self) -> None:
        litellm_client = AsyncMock()
        litellm_client.acompletion.side_effect = [
            _litellm_response(
                '{"planning_state_delta": {"base_planning_state_version"',
                finish_reason="length",
            ),
        ]

        outcome = await run_planner_pipeline(
            litellm_client=litellm_client,
            litellm_model="openai/gpt-5.4-mini",
            litellm_kwargs={},
            base_messages=[{"role": "user", "content": "build a flow"}],
            orchestration_context=_orchestration_context(),
        )

        assert outcome.kind == "parse_failed"
        assert outcome.llm_calls_made == 1
        assert outcome.parse_repair_attempts == 0
        assert outcome.final_completion is not None
        assert outcome.final_completion.finish_reason == "length"

    @pytest.mark.asyncio
    async def test_initial_parse_ok_leaves_parse_repair_attempts_zero(self) -> None:
        litellm_client = AsyncMock()
        litellm_client.acompletion.return_value = _litellm_response(
            _valid_ask_question_raw()
        )

        outcome = await run_planner_pipeline(
            litellm_client=litellm_client,
            litellm_model="openai/gpt-5.4-mini",
            litellm_kwargs={},
            base_messages=[{"role": "user", "content": "build a flow"}],
            orchestration_context=_orchestration_context(),
        )

        assert outcome.kind == "accepted"
        assert outcome.llm_calls_made == 1
        assert outcome.parse_repair_attempts == 0

    @pytest.mark.asyncio
    async def test_max_parse_repair_retries_is_one(self) -> None:
        assert MAX_PARSE_REPAIR_RETRIES == 1


class TestParseFailureDiagnosticsFlow:
    @pytest.mark.asyncio
    async def test_diagnostics_surfaced_on_pipeline_parse_failed(self) -> None:
        litellm_client = AsyncMock()
        litellm_client.acompletion.side_effect = [
            _litellm_response("```json\nnot valid\n```"),
            _litellm_response("still not json"),
        ]

        outcome = await run_planner_pipeline(
            litellm_client=litellm_client,
            litellm_model="openai/gpt-5.4-mini",
            litellm_kwargs={},
            base_messages=[{"role": "user", "content": "build a flow"}],
            orchestration_context=_orchestration_context(),
        )

        assert outcome.kind == "parse_failed"
        diag = outcome.parse_failure_diagnostics
        assert diag is not None
        assert diag["parse_error_kind"] == "json_decode_error"
        assert "raw_sha256_prefix" in diag
        assert diag["looks_like_markdown_fence"] is False
