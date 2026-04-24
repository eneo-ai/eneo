"""End-to-end contract tests for the planner-turn pipeline runner.

The pipeline runs one structured-JSON LLM call, validates via
`evaluate_planner_output`, and on eligible rejections retries via
`repair_planner_turn` up to `MAX_ORCHESTRATOR_REPAIR_RETRIES`. It does
NOT persist anything — the caller owns dispatch and proposal-processor
handoff — so these tests mock the LLM transport only.

Coverage:

- A single happy-path turn returns `accepted` with
  `llm_calls_made=1`, `repair_attempts=0`.
- A propose_plan action returns `accepted` with the parsed output
  (the caller will route it to the proposal-processor adapter).
- One rejection + one repair that parses clean returns `accepted`
  with `repair_attempts=1`, `llm_calls_made=2`.
- Three consecutive rejections exhaust the budget and return
  `rejected` with `repair_attempts=3`, `llm_calls_made=4`.
- A non-repair-eligible rejection short-circuits immediately with
  `repair_attempts=0`, `llm_calls_made=1` — the repair helper does
  NOT call the LLM on a non-eligible code.
- A repair output that drifts the committed architecture yields a
  terminal `rejected` outcome with `code="repair_attempted_commit_drift"`
  — the LLM ran (`llm_calls_made=2`) but the repair slot is NOT
  consumed (`repair_attempts=0`).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock

import pytest

from intric.flows.ai_builder.ai_builder_orchestration_pipeline import (
    PipelineOutcome,
    run_planner_pipeline,
)
from intric.flows.ai_builder.ai_builder_orchestrator import OrchestrationContext
from intric.flows.ai_builder.planning_state import (
    ArchitectureCommit,
    PlanningState,
    ResolvedSlot,
    StepTriple,
)


def _resolved_core_slots() -> dict[str, ResolvedSlot]:
    return {
        "primary_runtime_input": ResolvedSlot(
            name="primary_runtime_input",
            value="text",
            source="structured_answer",
            confidence="high",
        ),
        "terminal_output": ResolvedSlot(
            name="terminal_output",
            value="text",
            source="structured_answer",
            confidence="high",
        ),
    }


def _make_commit(*, architecture_hash: str = "a" * 64) -> ArchitectureCommit:
    return ArchitectureCommit(
        tuples_chain=[
            StepTriple(
                input_type="text",
                output_type="text",
                output_mode="pass_through",
            )
        ],
        chosen_patterns=["summarize_text"],
        required_capabilities=["input_text", "output_mode_pass_through"],
        committed_at=datetime(2026, 4, 23, tzinfo=timezone.utc),
        architecture_hash=architecture_hash,
    )


def _make_planning_state(
    *,
    architecture_commit: ArchitectureCommit | None = None,
    resolve_core_slots: bool = True,
) -> PlanningState:
    state = PlanningState.empty()
    if architecture_commit is not None:
        state.architecture_commit = architecture_commit
    if resolve_core_slots:
        state.resolved_slots = _resolved_core_slots()
    return state


def _make_context(
    *,
    current_version: int = 0,
    state: PlanningState | None = None,
) -> OrchestrationContext:
    return OrchestrationContext(
        current_version=current_version,
        session_state=state if state is not None else _make_planning_state(),
    )


def _minimal_payload(kind: str) -> dict[str, Any]:
    if kind == "ask_question":
        return {
            "question_id": "primary_runtime_input",
            "slot_name": "primary_runtime_input",
            "prompt": "Vad ska flödet ta emot?",
        }
    if kind == "commit_architecture":
        return {"note": ""}
    if kind == "confirm_requirements":
        return {"summary": "Resolved"}
    if kind == "propose_plan":
        return {"plan_reference": "latest"}
    raise AssertionError(f"unknown kind {kind}")


def _planner_output_json(
    *,
    kind: str,
    architecture_commit: ArchitectureCommit | None = None,
    base_version: int = 0,
    draft_plan: dict[str, Any] | None = None,
) -> str:
    payload: dict[str, Any] = {
        "planning_state_delta": {
            "base_planning_state_version": base_version,
            "signals_added": [],
            "slots_resolved": [],
            "architecture_commit": (
                architecture_commit.model_dump(mode="json")
                if architecture_commit is not None
                else None
            ),
            "draft_plan": draft_plan,
        },
        "planner_action": {"kind": kind, "payload": _minimal_payload(kind)},
    }
    return json.dumps(payload)


def _single_step_draft_plan() -> dict[str, Any]:
    return {
        "plan_id": "plan-1",
        "steps": [{"step_ix": 0}],
        "form_fields": [],
    }


def _llm_response(
    content: str,
    *,
    finish_reason: str = "stop",
    prompt_tokens: int = 100,
    completion_tokens: int = 50,
    total_tokens: int = 150,
) -> Any:
    choice = AsyncMock()
    choice.message.content = content
    choice.finish_reason = finish_reason
    wrapper = AsyncMock()
    wrapper.choices = [choice]
    usage = AsyncMock()
    usage.prompt_tokens = prompt_tokens
    usage.completion_tokens = completion_tokens
    usage.total_tokens = total_tokens
    wrapper.usage = usage
    return wrapper


@pytest.mark.asyncio
class TestHappyPath:
    async def test_accepted_on_single_commit_architecture_turn(self) -> None:
        llm = AsyncMock()
        commit = _make_commit()
        llm.acompletion.return_value = _llm_response(
            _planner_output_json(kind="commit_architecture", architecture_commit=commit)
        )

        outcome: PipelineOutcome = await run_planner_pipeline(
            litellm_client=llm,
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
            base_messages=[{"role": "system", "content": "system"}],
            orchestration_context=_make_context(),
        )

        assert outcome.kind == "accepted"
        assert outcome.accepted_output is not None
        assert outcome.accepted_output.planner_action.kind == "commit_architecture"
        assert outcome.llm_calls_made == 1
        assert outcome.repair_attempts == 0
        assert outcome.rejection is None
        llm.acompletion.assert_awaited_once()

    async def test_propose_plan_returns_accepted_for_external_handoff(self) -> None:
        """The pipeline never dispatches — the caller routes propose_plan
        to the proposal-processor adapter from the accepted output."""
        commit = _make_commit()
        state = _make_planning_state(architecture_commit=commit)
        llm = AsyncMock()
        llm.acompletion.return_value = _llm_response(
            _planner_output_json(
                kind="propose_plan",
                architecture_commit=commit,
                base_version=0,
                draft_plan=_single_step_draft_plan(),
            )
        )

        outcome = await run_planner_pipeline(
            litellm_client=llm,
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
            base_messages=[{"role": "system", "content": "system"}],
            orchestration_context=_make_context(state=state),
        )

        assert outcome.kind == "accepted"
        assert outcome.accepted_output is not None
        assert outcome.accepted_output.planner_action.kind == "propose_plan"


@pytest.mark.asyncio
class TestRepairLoop:
    async def test_single_repair_recovers_from_eligible_rejection(self) -> None:
        commit = _make_commit()
        state = _make_planning_state(architecture_commit=commit)
        llm = AsyncMock()
        first_response = _llm_response(
            _planner_output_json(
                kind="propose_plan",
                architecture_commit=commit,
            )
        )
        second_response = _llm_response(
            _planner_output_json(
                kind="commit_architecture",
                architecture_commit=commit,
            )
        )
        llm.acompletion.side_effect = [first_response, second_response]

        outcome = await run_planner_pipeline(
            litellm_client=llm,
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
            base_messages=[{"role": "system", "content": "system"}],
            orchestration_context=_make_context(state=state),
        )

        assert outcome.kind == "accepted"
        assert outcome.accepted_output is not None
        assert outcome.accepted_output.planner_action.kind == "commit_architecture"
        assert outcome.llm_calls_made == 2
        assert outcome.repair_attempts == 1

    async def test_repair_budget_exhaustion_returns_terminal_rejection(self) -> None:
        commit = _make_commit()
        state = _make_planning_state(architecture_commit=commit)
        llm = AsyncMock()
        bad_response = _llm_response(
            _planner_output_json(
                kind="propose_plan",
                architecture_commit=commit,
            )
        )
        llm.acompletion.side_effect = [bad_response] * 4

        outcome = await run_planner_pipeline(
            litellm_client=llm,
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
            base_messages=[{"role": "system", "content": "system"}],
            orchestration_context=_make_context(state=state),
        )

        assert outcome.kind == "rejected"
        assert outcome.rejection is not None
        assert outcome.rejection.code in {
            "propose_plan_without_architecture_commit",
            "propose_plan_missing_draft_plan",
            "propose_plan_draft_plan_structural_mismatch",
        }
        assert outcome.llm_calls_made == 4
        assert outcome.repair_attempts == 3


@pytest.mark.asyncio
class TestShortCircuits:
    async def test_non_repairable_rejection_short_circuits_without_repair(
        self,
    ) -> None:
        """version_mismatch (non-eligible) must not trigger a repair call."""
        state = _make_planning_state()
        context = OrchestrationContext(current_version=5, session_state=state)
        llm = AsyncMock()
        llm.acompletion.return_value = _llm_response(
            _planner_output_json(kind="ask_question", base_version=0)
        )

        outcome = await run_planner_pipeline(
            litellm_client=llm,
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
            base_messages=[{"role": "system", "content": "system"}],
            orchestration_context=context,
        )

        assert outcome.kind == "rejected"
        assert outcome.rejection is not None
        assert outcome.rejection.code == "version_mismatch"
        assert outcome.llm_calls_made == 1
        assert outcome.repair_attempts == 0


@pytest.mark.asyncio
class TestCommitDriftDuringRepair:
    async def test_drift_in_repair_output_yields_terminal_drift_rejection(
        self,
    ) -> None:
        """If repair drifts the committed architecture, the pipeline surfaces
        `repair_attempted_commit_drift` terminally — the LLM ran
        (llm_calls_made=2) but drift is NOT a consumed retry slot
        (repair_attempts=0)."""
        original_commit = _make_commit(architecture_hash="a" * 64)
        drifted_commit = _make_commit(architecture_hash="b" * 64)
        state = _make_planning_state(architecture_commit=original_commit)
        llm = AsyncMock()
        first = _llm_response(
            _planner_output_json(
                kind="propose_plan",
                architecture_commit=original_commit,
            )
        )
        second = _llm_response(
            _planner_output_json(
                kind="commit_architecture",
                architecture_commit=drifted_commit,
            )
        )
        llm.acompletion.side_effect = [first, second]

        outcome = await run_planner_pipeline(
            litellm_client=llm,
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
            base_messages=[{"role": "system", "content": "system"}],
            orchestration_context=_make_context(state=state),
        )

        assert outcome.kind == "rejected"
        assert outcome.rejection is not None
        assert outcome.rejection.code == "repair_attempted_commit_drift"
        assert outcome.llm_calls_made == 2
        assert outcome.repair_attempts == 0


class TestPublicSurface:
    def test_module_exports(self) -> None:
        from intric.flows.ai_builder import ai_builder_orchestration_pipeline as module

        for symbol in ("run_planner_pipeline", "PipelineOutcome"):
            assert hasattr(module, symbol)


@pytest.mark.asyncio
class TestParseFailures:
    async def test_initial_call_malformed_json_returns_parse_failed(self) -> None:
        """Truncated JSON on the initial call must surface as parse_failed
        with final_completion.finish_reason=="length" populated, so the
        caller can route to planner_output_too_long."""
        llm = AsyncMock()
        llm.acompletion.return_value = _llm_response(
            '{"planning_state_delta": {"base_planning',  # truncated mid-key
            finish_reason="length",
            prompt_tokens=400,
            completion_tokens=1024,
            total_tokens=1424,
        )

        outcome = await run_planner_pipeline(
            litellm_client=llm,
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
            base_messages=[{"role": "system", "content": "system"}],
            orchestration_context=_make_context(),
        )

        assert outcome.kind == "parse_failed"
        assert outcome.final_completion is not None
        assert outcome.final_completion.finish_reason == "length"
        assert outcome.final_completion.completion_tokens == 1024
        assert outcome.parse_error_raw is not None
        assert outcome.parse_error_message is not None

    async def test_repair_call_malformed_json_returns_parse_failed(self) -> None:
        """If a repair turn returns malformed JSON, the pipeline must
        surface parse_failed with the REPAIR call's metadata — not the
        initial call's."""
        commit = _make_commit()
        state = _make_planning_state(architecture_commit=commit)
        llm = AsyncMock()
        first = _llm_response(
            _planner_output_json(kind="propose_plan", architecture_commit=commit),
            finish_reason="stop",
            prompt_tokens=200,
            completion_tokens=60,
            total_tokens=260,
        )
        truncated_repair = _llm_response(
            '{"planning_state_delta": {"base_plan',
            finish_reason="length",
            prompt_tokens=700,
            completion_tokens=1024,
            total_tokens=1724,
        )
        llm.acompletion.side_effect = [first, truncated_repair]

        outcome = await run_planner_pipeline(
            litellm_client=llm,
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
            base_messages=[{"role": "system", "content": "system"}],
            orchestration_context=_make_context(state=state),
        )

        assert outcome.kind == "parse_failed"
        assert outcome.final_completion is not None
        assert outcome.final_completion.finish_reason == "length"
        assert outcome.final_completion.prompt_tokens == 700
        assert outcome.final_completion.completion_tokens == 1024
        assert outcome.llm_calls_made == 2
        assert outcome.repair_attempts == 0
        assert outcome.parse_error_raw is not None
        assert outcome.parse_error_message is not None


@pytest.mark.asyncio
class TestCompletionMetadataThreading:
    async def test_final_completion_from_initial_call_when_no_repair(self) -> None:
        """No-repair happy path: final_completion carries the initial call's
        metadata (finish_reason + token counts)."""
        llm = AsyncMock()
        commit = _make_commit()
        llm.acompletion.return_value = _llm_response(
            _planner_output_json(
                kind="commit_architecture", architecture_commit=commit
            ),
            finish_reason="stop",
            prompt_tokens=250,
            completion_tokens=80,
            total_tokens=330,
        )

        outcome = await run_planner_pipeline(
            litellm_client=llm,
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
            base_messages=[{"role": "system", "content": "system"}],
            orchestration_context=_make_context(),
        )

        assert outcome.final_completion is not None
        assert outcome.final_completion.finish_reason == "stop"
        assert outcome.final_completion.prompt_tokens == 250
        assert outcome.final_completion.completion_tokens == 80
        assert outcome.final_completion.total_tokens == 330

    async def test_final_completion_from_repair_call_when_repair_accepted(
        self,
    ) -> None:
        """When a repair produces the accepted output, final_completion
        carries the REPAIR call's metadata — so truncation detection
        and token telemetry reflect the final call."""
        commit = _make_commit()
        state = _make_planning_state(architecture_commit=commit)
        llm = AsyncMock()
        first = _llm_response(
            _planner_output_json(kind="propose_plan", architecture_commit=commit),
            finish_reason="stop",
            prompt_tokens=500,
            completion_tokens=40,
            total_tokens=540,
        )
        second = _llm_response(
            _planner_output_json(
                kind="commit_architecture", architecture_commit=commit
            ),
            finish_reason="length",
            prompt_tokens=600,
            completion_tokens=1024,
            total_tokens=1624,
        )
        llm.acompletion.side_effect = [first, second]

        outcome = await run_planner_pipeline(
            litellm_client=llm,
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
            base_messages=[{"role": "system", "content": "system"}],
            orchestration_context=_make_context(state=state),
        )

        assert outcome.kind == "accepted"
        assert outcome.final_completion is not None
        assert outcome.final_completion.finish_reason == "length"
        assert outcome.final_completion.prompt_tokens == 600
        assert outcome.final_completion.completion_tokens == 1024
