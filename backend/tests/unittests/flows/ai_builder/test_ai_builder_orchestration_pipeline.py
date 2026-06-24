"""End-to-end contract tests for the planner-turn pipeline runner.

The pipeline runs one structured-JSON LLM call, validates via
`evaluate_planner_output`, and on eligible rejections retries up to
`MAX_ORCHESTRATOR_REPAIR_RETRIES`. It does
NOT persist anything — the caller owns dispatch and proposal-processor
handoff — so these tests mock the LLM transport only.

Coverage:

- A single happy-path turn returns `accepted` with
  `llm_calls_made=1`, `repair_attempts=0`.
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

from intric.flows.ai_builder.ai_builder_action_policy import (
    build_planner_action_policy,
)
from intric.flows.ai_builder.ai_builder_architecture_commit import (
    canonical_architecture_commit_payload,
)
from intric.flows.ai_builder.ai_builder_litellm_completion import (
    call_planner_completion,
)
from intric.flows.ai_builder.ai_builder_orchestration_pipeline import (
    PipelineOutcome,
    run_planner_pipeline,
)
from intric.flows.ai_builder.ai_builder_orchestrator import OrchestrationContext
from intric.flows.ai_builder.ai_builder_token_usage import (
    TOKEN_USAGE_SOURCE_PROVIDER,
)
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
    asked_question_ids: frozenset[str] = frozenset(),
    required_slot_names: frozenset[str] = frozenset(),
) -> OrchestrationContext:
    return OrchestrationContext(
        current_version=current_version,
        session_state=state if state is not None else _make_planning_state(),
        asked_question_ids=asked_question_ids,
        required_slot_names=required_slot_names,
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
    raise AssertionError(f"unknown kind {kind}")


def _planner_output_json(
    *,
    kind: str,
    architecture_commit: ArchitectureCommit | None = None,
    base_version: int = 0,
) -> str:
    payload: dict[str, Any] = {
        "planning_state_delta": {
            "base_planning_state_version": base_version,
            "signals_added": [],
            "slots_resolved": [],
            "architecture_commit": (
                canonical_architecture_commit_payload(architecture_commit)
                if architecture_commit is not None
                else None
            ),
        },
        "planner_action": {"kind": kind, "payload": _minimal_payload(kind)},
    }
    return json.dumps(payload)


def _ask_question_json(
    *,
    question_id: str,
    slot_name: str,
    base_version: int = 0,
) -> str:
    payload = json.loads(
        _planner_output_json(kind="ask_question", base_version=base_version)
    )
    payload["planner_action"]["payload"] = {
        "question_id": question_id,
        "slot_name": slot_name,
        "prompt": "Which runtime fields should the user provide?",
    }
    return json.dumps(payload)


def _llm_response(
    content: str,
    *,
    finish_reason: str = "stop",
    prompt_tokens: int = 100,
    completion_tokens: int = 50,
    total_tokens: int = 150,
    include_usage: bool = True,
) -> Any:
    choice = AsyncMock()
    choice.message.content = content
    choice.finish_reason = finish_reason
    wrapper = AsyncMock()
    wrapper.choices = [choice]
    if include_usage:
        usage = AsyncMock()
        usage.prompt_tokens = prompt_tokens
        usage.completion_tokens = completion_tokens
        usage.total_tokens = total_tokens
        wrapper.usage = usage
    else:
        wrapper.usage = None
    return wrapper


@pytest.mark.asyncio
class TestPlannerCompletionBoundary:
    async def test_call_planner_completion_returns_raw_content_and_usage(self) -> None:
        llm = AsyncMock()
        llm.acompletion.return_value = _llm_response(
            _planner_output_json(kind="confirm_requirements"),
            finish_reason="stop",
            prompt_tokens=17,
            completion_tokens=9,
            total_tokens=26,
        )

        result = await call_planner_completion(
            litellm_client=llm,
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={"timeout": 30},
            messages=[{"role": "system", "content": "system"}],
        )

        assert result.raw_content == _planner_output_json(kind="confirm_requirements")
        assert result.metadata.finish_reason == "stop"
        assert result.metadata.usage.prompt_tokens == 17
        assert result.metadata.usage.completion_tokens == 9
        assert result.metadata.usage.total_tokens == 26
        assert result.metadata.usage.source == TOKEN_USAGE_SOURCE_PROVIDER
        llm.acompletion.assert_awaited_once_with(
            model="openai/gpt-5.4",
            messages=[{"role": "system", "content": "system"}],
            timeout=30,
        )

    async def test_call_planner_completion_handles_empty_choices(self) -> None:
        llm = AsyncMock()
        response = AsyncMock()
        response.choices = []
        response.usage = None
        llm.acompletion.return_value = response

        result = await call_planner_completion(
            litellm_client=llm,
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
            messages=[{"role": "system", "content": "system"}],
        )

        assert result.raw_content == ""
        assert result.metadata.finish_reason is None
        assert result.metadata.usage.estimated is True


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


@pytest.mark.asyncio
class TestRepairLoop:
    async def test_single_repair_recovers_from_eligible_rejection(self) -> None:
        llm = AsyncMock()
        first_response = _llm_response(
            _ask_question_json(
                question_id="primary_runtime_input",
                slot_name="primary_runtime_input",
            )
        )
        second_response = _llm_response(
            _planner_output_json(kind="confirm_requirements")
        )
        llm.acompletion.side_effect = [first_response, second_response]

        outcome = await run_planner_pipeline(
            litellm_client=llm,
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
            base_messages=[{"role": "system", "content": "system"}],
            orchestration_context=_make_context(
                asked_question_ids=frozenset({"primary_runtime_input"}),
                required_slot_names=frozenset({"primary_runtime_input"}),
            ),
        )

        assert outcome.kind == "accepted"
        assert outcome.accepted_output is not None
        assert outcome.accepted_output.planner_action.kind == "confirm_requirements"
        assert outcome.accepted_output.planning_state_delta.architecture_commit is None
        assert outcome.llm_calls_made == 2
        assert outcome.repair_attempts == 1

    async def test_repair_budget_exhaustion_returns_terminal_rejection(self) -> None:
        llm = AsyncMock()
        bad_response = _llm_response(
            _ask_question_json(
                question_id="primary_runtime_input",
                slot_name="primary_runtime_input",
            )
        )
        llm.acompletion.side_effect = [bad_response] * 4

        outcome = await run_planner_pipeline(
            litellm_client=llm,
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
            base_messages=[{"role": "system", "content": "system"}],
            orchestration_context=_make_context(
                asked_question_ids=frozenset({"primary_runtime_input"}),
                required_slot_names=frozenset({"primary_runtime_input"}),
            ),
        )

        assert outcome.kind == "rejected"
        assert outcome.rejection is not None
        assert outcome.rejection.code == "duplicate_question"
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

    async def test_off_topic_question_repairs_to_canonical_slot(self) -> None:
        """An invented question id is LLM vocabulary drift, not a user-visible
        terminal failure. The guardrail should still reject it, but the
        pipeline gets one bounded repair chance to re-emit a canonical
        ask_question target from the same server-owned slot surface.
        """
        context = OrchestrationContext(
            current_version=0,
            session_state=_make_planning_state(),
            required_slot_names=frozenset({"runtime_metadata_fields"}),
        )
        llm = AsyncMock()
        llm.acompletion.side_effect = [
            _llm_response(
                _ask_question_json(
                    question_id="case_type_scope",
                    slot_name="case_type_scope",
                )
            ),
            _llm_response(
                _ask_question_json(
                    question_id="runtime_metadata_fields",
                    slot_name="runtime_metadata_fields",
                )
            ),
        ]

        outcome = await run_planner_pipeline(
            litellm_client=llm,
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
            base_messages=[{"role": "system", "content": "system"}],
            orchestration_context=context,
        )

        assert outcome.kind == "accepted"
        assert outcome.accepted_output is not None
        accepted_payload = outcome.accepted_output.planner_action.payload
        assert accepted_payload.question_id == "runtime_metadata_fields"
        assert accepted_payload.slot_name == "runtime_metadata_fields"
        assert outcome.llm_calls_made == 2
        assert outcome.repair_attempts == 1

    async def test_disallowed_question_pivots_to_commit_without_repair(self) -> None:
        """When the server policy has closed the question phase, do not ask
        the LLM to repair an impossible question. Commit deterministically
        if the same policy allows the architecture to be pinned.
        """
        state = _make_planning_state(resolve_core_slots=True)
        context = OrchestrationContext(
            current_version=0,
            session_state=state,
            action_policy=build_planner_action_policy(
                session_state=state,
                unresolved_architectural_choices=frozenset(),
                selected_discovery_question_ids=(),
            ),
        )
        llm = AsyncMock()
        llm.acompletion.return_value = _llm_response(
            _ask_question_json(
                question_id="document_material_scope",
                slot_name="document_material_scope",
            )
        )

        outcome = await run_planner_pipeline(
            litellm_client=llm,
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
            base_messages=[{"role": "system", "content": "system"}],
            orchestration_context=context,
        )

        assert outcome.kind == "accepted"
        assert outcome.accepted_output is not None
        assert outcome.accepted_output.planner_action.kind == "commit_architecture"
        assert (
            outcome.accepted_output.planning_state_delta.architecture_commit is not None
        )
        assert outcome.llm_calls_made == 1
        assert outcome.repair_attempts == 0

    async def test_duplicate_question_repairs_to_action_pivot(self) -> None:
        """Repeating an already-asked question without a user reply is model
        loop drift, not a reason to fail the user's turn immediately.

        The guardrail remains strict, but the repair loop gets a bounded
        chance to pivot to a different unresolved slot or another valid
        action before surfacing a terminal error.
        """
        context = OrchestrationContext(
            current_version=0,
            session_state=_make_planning_state(),
            required_slot_names=frozenset(
                {"runtime_metadata_fields", "structured_analysis_need"}
            ),
            asked_question_ids=frozenset({"runtime_metadata_fields"}),
            has_new_evidence=False,
        )
        llm = AsyncMock()
        llm.acompletion.side_effect = [
            _llm_response(
                _ask_question_json(
                    question_id="runtime_metadata_fields",
                    slot_name="runtime_metadata_fields",
                )
            ),
            _llm_response(
                _ask_question_json(
                    question_id="structured_analysis_need",
                    slot_name="structured_analysis_need",
                )
            ),
        ]

        outcome = await run_planner_pipeline(
            litellm_client=llm,
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
            base_messages=[{"role": "system", "content": "system"}],
            orchestration_context=context,
        )

        assert outcome.kind == "accepted"
        assert outcome.accepted_output is not None
        accepted_payload = outcome.accepted_output.planner_action.payload
        assert accepted_payload.question_id == "structured_analysis_need"
        assert accepted_payload.slot_name == "structured_analysis_need"
        assert outcome.llm_calls_made == 2
        assert outcome.repair_attempts == 1

    async def test_parse_repairs_malformed_semantic_repair_output(self) -> None:
        """Parse repair must cover every LLM output, not only the initial call.

        Production failure 2026-04-24: initial output parsed, evaluator
        repair ran, and the repair response was JSON-looking but
        malformed (`json_decode_error="Extra data"`). The pipeline
        surfaced `parse_failed` with `llm_calls_made=2` and
        `parse_repair_attempts=0`, proving parse repair was not wired
        for repair-call outputs.
        """
        context = OrchestrationContext(
            current_version=0,
            session_state=_make_planning_state(),
            required_slot_names=frozenset({"runtime_metadata_fields"}),
        )
        valid_repair = _ask_question_json(
            question_id="runtime_metadata_fields",
            slot_name="runtime_metadata_fields",
        )
        malformed_repair = f"{valid_repair}\n{{}}"
        llm = AsyncMock()
        llm.acompletion.side_effect = [
            _llm_response(
                _ask_question_json(
                    question_id="case_type_scope",
                    slot_name="case_type_scope",
                )
            ),
            _llm_response(malformed_repair),
            _llm_response(valid_repair),
        ]

        outcome = await run_planner_pipeline(
            litellm_client=llm,
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
            base_messages=[{"role": "system", "content": "system"}],
            orchestration_context=context,
        )

        assert outcome.kind == "accepted"
        assert outcome.accepted_output is not None
        assert outcome.accepted_output.planner_action.kind == "ask_question"
        assert outcome.llm_calls_made == 3
        assert outcome.repair_attempts == 1
        assert outcome.parse_repair_attempts == 1

    async def test_missing_commit_delta_is_server_normalized_without_repair(
        self,
    ) -> None:
        """`commit_architecture` is a semantic action; the server owns the
        deterministic architecture draft when resolved slots are sufficient.

        Missing commit body should therefore not spend a repair call or
        rely on the model to re-author tuples/patterns/capabilities.
        """
        context = OrchestrationContext(
            current_version=0,
            session_state=_make_planning_state(),
        )
        llm = AsyncMock()
        llm.acompletion.return_value = _llm_response(
            _planner_output_json(
                kind="commit_architecture",
                architecture_commit=None,
            )
        )

        outcome = await run_planner_pipeline(
            litellm_client=llm,
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
            base_messages=[{"role": "system", "content": "system"}],
            orchestration_context=context,
        )

        assert outcome.kind == "accepted"
        assert outcome.accepted_output is not None
        commit = outcome.accepted_output.planning_state_delta.architecture_commit
        assert commit is not None
        assert [triple.model_dump() for triple in commit.tuples_chain] == [
            {
                "input_type": "text",
                "output_type": "text",
                "output_mode": "pass_through",
            }
        ]
        assert outcome.accepted_output.planner_action.kind == "commit_architecture"
        assert outcome.llm_calls_made == 1
        assert outcome.repair_attempts == 0

    async def test_llm_freehand_commit_tuple_is_replaced_by_server_architecture(
        self,
    ) -> None:
        """The LLM can choose the commit action, but not the canonical tuple.

        A model-specific bad tuple should not create an invalid terminal
        turn when the backend can derive the legal tuple from resolved
        planning state.
        """
        bad_commit = _make_commit()
        bad_commit.tuples_chain = [
            StepTriple(
                input_type="text",
                output_type="text",
                output_mode="template_fill",
            )
        ]
        context = OrchestrationContext(
            current_version=0,
            session_state=_make_planning_state(),
        )
        llm = AsyncMock()
        llm.acompletion.return_value = _llm_response(
            _planner_output_json(
                kind="commit_architecture",
                architecture_commit=bad_commit,
            )
        )

        outcome = await run_planner_pipeline(
            litellm_client=llm,
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
            base_messages=[{"role": "system", "content": "system"}],
            orchestration_context=context,
        )

        assert outcome.kind == "accepted"
        assert outcome.accepted_output is not None
        commit = outcome.accepted_output.planning_state_delta.architecture_commit
        assert commit is not None
        assert [triple.model_dump() for triple in commit.tuples_chain] == [
            {
                "input_type": "text",
                "output_type": "text",
                "output_mode": "pass_through",
            }
        ]
        assert commit.chosen_patterns == ["summarize_text"]
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
        drifted_commit = _make_commit(
            architecture_hash="b" * 64,
        )
        drifted_commit.tuples_chain = [
            StepTriple(
                input_type="text",
                output_type="json",
                output_mode="pass_through",
            )
        ]
        state = _make_planning_state(architecture_commit=original_commit)
        llm = AsyncMock()
        first = _llm_response(
            _ask_question_json(
                question_id="primary_runtime_input",
                slot_name="primary_runtime_input",
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
            orchestration_context=_make_context(
                state=state,
                asked_question_ids=frozenset({"primary_runtime_input"}),
                required_slot_names=frozenset({"primary_runtime_input"}),
            ),
        )

        assert outcome.kind == "rejected"
        assert outcome.rejection is not None
        assert outcome.rejection.code == "repair_attempted_commit_drift"
        assert outcome.llm_calls_made == 2
        assert outcome.repair_attempts == 0

    async def test_parse_repaired_semantic_repair_uses_normal_evaluator_drift_code(
        self,
    ) -> None:
        """A parse-repaired semantic retry re-enters normal evaluation.

        Direct semantic-repair drift is blocked before normalization with
        `repair_attempted_commit_drift`. If that repair response is malformed
        and recovered by parse repair, the historic pipeline path re-ran the
        normal evaluator instead; pin that narrower behavior so the generic
        runner consolidation cannot change retry accounting silently.
        """
        original_commit = _make_commit(architecture_hash="a" * 64)
        drifted_commit = _make_commit(architecture_hash="b" * 64)
        drifted_commit.tuples_chain = [
            StepTriple(
                input_type="text",
                output_type="json",
                output_mode="pass_through",
            )
        ]
        state = _make_planning_state(architecture_commit=original_commit)
        malformed_repair = (
            _planner_output_json(
                kind="confirm_requirements",
                architecture_commit=drifted_commit,
            )
            + "\n{}"
        )
        llm = AsyncMock()
        llm.acompletion.side_effect = [
            _llm_response(
                _ask_question_json(
                    question_id="primary_runtime_input",
                    slot_name="primary_runtime_input",
                )
            ),
            _llm_response(malformed_repair),
            _llm_response(
                _planner_output_json(
                    kind="confirm_requirements",
                    architecture_commit=drifted_commit,
                )
            ),
        ]

        outcome = await run_planner_pipeline(
            litellm_client=llm,
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
            base_messages=[{"role": "system", "content": "system"}],
            orchestration_context=_make_context(
                state=state,
                asked_question_ids=frozenset({"primary_runtime_input"}),
                required_slot_names=frozenset({"primary_runtime_input"}),
            ),
        )

        assert outcome.kind == "rejected"
        assert outcome.rejection is not None
        assert outcome.rejection.code == "architecture_commit_drift_from_pinned"
        assert outcome.llm_calls_made == 3
        assert outcome.repair_attempts == 1
        assert outcome.parse_repair_attempts == 1


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
        assert outcome.final_completion.usage.completion_tokens == 1024
        assert outcome.parse_error_raw is not None
        assert outcome.parse_error_message is not None

    async def test_initial_call_empty_choices_returns_parse_failed(self) -> None:
        llm = AsyncMock()
        response = AsyncMock()
        response.choices = []
        response.usage = None
        llm.acompletion.return_value = response

        outcome = await run_planner_pipeline(
            litellm_client=llm,
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
            base_messages=[{"role": "system", "content": "system"}],
            orchestration_context=_make_context(),
        )

        assert outcome.kind == "parse_failed"
        assert outcome.final_completion is not None
        assert outcome.final_completion.finish_reason is None
        assert outcome.parse_error_raw == ""
        assert outcome.parse_error_message is not None
        assert outcome.llm_calls_made == 2
        assert outcome.parse_repair_attempts == 1

    async def test_repair_call_malformed_json_returns_parse_failed(self) -> None:
        """If a repair turn returns malformed JSON, the pipeline must
        surface parse_failed with the REPAIR call's metadata — not the
        initial call's."""
        llm = AsyncMock()
        first = _llm_response(
            _ask_question_json(
                question_id="primary_runtime_input",
                slot_name="primary_runtime_input",
            ),
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
            orchestration_context=_make_context(
                asked_question_ids=frozenset({"primary_runtime_input"}),
                required_slot_names=frozenset({"primary_runtime_input"}),
            ),
        )

        assert outcome.kind == "parse_failed"
        assert outcome.final_completion is not None
        assert outcome.final_completion.finish_reason == "length"
        assert outcome.final_completion.usage.prompt_tokens == 700
        assert outcome.final_completion.usage.completion_tokens == 1024
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
        assert outcome.final_completion.usage.prompt_tokens == 250
        assert outcome.final_completion.usage.completion_tokens == 80
        assert outcome.final_completion.usage.total_tokens == 330

    async def test_final_completion_from_repair_call_when_repair_accepted(
        self,
    ) -> None:
        """When a repair produces the accepted output, final_completion
        carries the REPAIR call's metadata — so truncation detection
        and token telemetry reflect the final call."""
        llm = AsyncMock()
        first = _llm_response(
            _ask_question_json(
                question_id="primary_runtime_input",
                slot_name="primary_runtime_input",
            ),
            finish_reason="stop",
            prompt_tokens=500,
            completion_tokens=40,
            total_tokens=540,
        )
        second = _llm_response(
            _planner_output_json(kind="confirm_requirements"),
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
            orchestration_context=_make_context(
                asked_question_ids=frozenset({"primary_runtime_input"}),
                required_slot_names=frozenset({"primary_runtime_input"}),
            ),
        )

        assert outcome.kind == "accepted"
        assert outcome.final_completion is not None
        assert outcome.final_completion.finish_reason == "length"
        assert outcome.final_completion.usage.prompt_tokens == 600
        assert outcome.final_completion.usage.completion_tokens == 1024

    async def test_cumulative_token_usage_sums_initial_and_repair_calls(
        self,
    ) -> None:
        llm = AsyncMock()
        first = _llm_response(
            _ask_question_json(
                question_id="primary_runtime_input",
                slot_name="primary_runtime_input",
            ),
            prompt_tokens=100,
            completion_tokens=20,
            total_tokens=120,
        )
        second = _llm_response(
            _planner_output_json(kind="confirm_requirements"),
            prompt_tokens=200,
            completion_tokens=30,
            total_tokens=230,
        )
        llm.acompletion.side_effect = [first, second]

        outcome = await run_planner_pipeline(
            litellm_client=llm,
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
            base_messages=[{"role": "system", "content": "system"}],
            orchestration_context=_make_context(
                asked_question_ids=frozenset({"primary_runtime_input"}),
                required_slot_names=frozenset({"primary_runtime_input"}),
            ),
        )

        assert outcome.kind == "accepted"
        assert outcome.final_completion is not None
        assert outcome.final_completion.usage.prompt_tokens == 200
        assert outcome.cumulative_token_usage is not None
        assert outcome.cumulative_token_usage.prompt_tokens == 300
        assert outcome.cumulative_token_usage.completion_tokens == 50
        assert outcome.cumulative_token_usage.total_tokens == 350
        assert outcome.cumulative_token_usage.source == TOKEN_USAGE_SOURCE_PROVIDER
        assert outcome.cumulative_token_usage.estimated is False
