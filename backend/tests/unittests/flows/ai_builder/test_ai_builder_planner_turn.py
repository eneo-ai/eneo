"""Contract tests for the planner-turn wiring helper.

`run_planner_turn` is the production glue that composes
`run_planner_pipeline` (LLM call + repair loop) with
`dispatch_planner_action` (atomic persistence). It owns the
caller-facing outcome contract that `send_message` will consume:

- `dispatched` — pipeline accepted, dispatcher persisted, version bumped.
- `rejected` — pipeline returned a terminal rejection.
- `parse_failed` — pipeline surfaced a parse failure (the caller
  distinguishes truncation via `final_completion.finish_reason`).
- `propose_plan_pending_adapter` — pipeline accepted a `propose_plan`
  action; the helper bypasses the dispatcher (the dispatcher would
  raise `NotImplementedError` on this action kind) and surfaces the
  accepted output directly until the proposal-processor adapter is
  wired. The LLM already ran, so telemetry counts still populate.

The tests drive the module with `AsyncMock(AIBuilderRepository)` and a
litellm-shaped AsyncMock so no real transport or DB is touched.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, create_autospec
from uuid import uuid4

import pytest

from intric.flows.ai_builder.ai_builder_domain_models import ConversationMessage
from intric.flows.ai_builder.ai_builder_orchestrator import OrchestrationContext
from intric.flows.ai_builder.ai_builder_planner_turn import (
    PlannerTurnResult,
    TurnTelemetry,
    run_planner_turn,
)
from intric.flows.ai_builder.ai_builder_repo import AIBuilderRepository
from intric.flows.ai_builder.planning_state import (
    ArchitectureCommit,
    PlanningState,
    StepTriple,
)


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


def _make_state(
    *, architecture_commit: ArchitectureCommit | None = None
) -> PlanningState:
    state = PlanningState.empty()
    if architecture_commit is not None:
        state.architecture_commit = architecture_commit
    return state


def _ctx(
    *,
    current_version: int = 0,
    state: PlanningState | None = None,
    required_slot_names: frozenset[str] = frozenset(),
    unresolved_architectural_choices: frozenset[str] = frozenset(),
) -> OrchestrationContext:
    return OrchestrationContext(
        current_version=current_version,
        session_state=state if state is not None else _make_state(),
        required_slot_names=required_slot_names,
        unresolved_architectural_choices=unresolved_architectural_choices,
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


def _autospec_repo() -> AIBuilderRepository:
    return create_autospec(AIBuilderRepository, instance=True)


@pytest.mark.asyncio
class TestDispatchedHappyPaths:
    async def test_ask_question_dispatches_without_commit(self) -> None:
        repo = _autospec_repo()
        repo.commit_turn.return_value = 7
        llm = AsyncMock()
        llm.acompletion.return_value = _llm_response(
            _planner_output_json(kind="ask_question")
        )
        session_id = uuid4()
        tenant_id = uuid4()
        user_message = ConversationMessage(role="user", content="Hi")
        assistant_message = ConversationMessage(
            role="assistant", content="assistant turn rendered after accept"
        )

        def _builder(_accepted: Any, _telemetry: Any) -> list[ConversationMessage]:
            return [user_message, assistant_message]

        result = await run_planner_turn(
            repo=repo,
            litellm_client=llm,
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
            session_id=session_id,
            tenant_id=tenant_id,
            flow=None,
            base_messages=[{"role": "system", "content": "system"}],
            orchestration_context=_ctx(
                required_slot_names=frozenset({"primary_runtime_input"})
            ),
            build_new_messages=_builder,
        )

        assert isinstance(result, PlannerTurnResult)
        assert result.kind == "dispatched"
        assert result.dispatch_result is not None
        assert result.dispatch_result.action_kind == "ask_question"
        assert result.dispatch_result.new_planning_state_version == 7
        assert result.accepted_output is not None
        assert result.accepted_output.planner_action.kind == "ask_question"
        assert result.llm_calls_made == 1
        repo.commit_turn.assert_awaited_once()
        commit_kwargs = repo.commit_turn.await_args.kwargs
        assert commit_kwargs["session_id"] == session_id
        assert commit_kwargs["tenant_id"] == tenant_id
        assert commit_kwargs["architecture_commit"] is None
        assert commit_kwargs["new_messages"] == [user_message, assistant_message]

    async def test_commit_architecture_dispatches_with_commit(self) -> None:
        repo = _autospec_repo()
        repo.commit_turn.return_value = 3
        commit = _make_commit()
        llm = AsyncMock()
        llm.acompletion.return_value = _llm_response(
            _planner_output_json(kind="commit_architecture", architecture_commit=commit)
        )

        result = await run_planner_turn(
            repo=repo,
            litellm_client=llm,
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
            session_id=uuid4(),
            tenant_id=uuid4(),
            flow=None,
            base_messages=[{"role": "system", "content": "system"}],
            orchestration_context=_ctx(),
            build_new_messages=lambda _a, _t: [
                ConversationMessage(role="user", content="Gör så")
            ],
        )

        assert result.kind == "dispatched"
        assert result.dispatch_result is not None
        assert result.dispatch_result.action_kind == "commit_architecture"
        assert result.dispatch_result.new_planning_state_version == 3
        repo.commit_turn.assert_awaited_once()
        committed = repo.commit_turn.await_args.kwargs["architecture_commit"]
        assert committed is not None
        assert committed.architecture_hash == commit.architecture_hash

    async def test_confirm_requirements_dispatches_without_commit(self) -> None:
        repo = _autospec_repo()
        repo.commit_turn.return_value = 12
        commit = _make_commit()
        state = _make_state(architecture_commit=commit)
        llm = AsyncMock()
        llm.acompletion.return_value = _llm_response(
            _planner_output_json(
                kind="confirm_requirements", architecture_commit=commit
            )
        )

        result = await run_planner_turn(
            repo=repo,
            litellm_client=llm,
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
            session_id=uuid4(),
            tenant_id=uuid4(),
            flow=None,
            base_messages=[{"role": "system", "content": "system"}],
            orchestration_context=_ctx(state=state),
            build_new_messages=lambda _a, _t: [
                ConversationMessage(role="user", content="Ja")
            ],
        )

        assert result.kind == "dispatched"
        assert result.dispatch_result is not None
        assert result.dispatch_result.action_kind == "confirm_requirements"
        assert repo.commit_turn.await_args.kwargs["architecture_commit"] is None, (
            "confirm_requirements must not resend the architecture_commit"
        )

    async def test_builder_receives_accepted_output_and_dispatch_forwards_kwargs(
        self,
    ) -> None:
        """The post-accept builder sees the real PlannerOutput, and every
        caller-owned kwarg (flow, request_id, lock_token) reaches commit_turn
        unchanged."""
        from intric.flows.ai_builder.ai_builder_orchestrator import PlannerOutput

        repo = _autospec_repo()
        repo.commit_turn.return_value = 42
        commit = _make_commit()
        llm = AsyncMock()
        llm.acompletion.return_value = _llm_response(
            _planner_output_json(kind="commit_architecture", architecture_commit=commit)
        )
        flow_stub = object()
        request_id = uuid4()
        lock_token = uuid4()
        captured_outputs: list[PlannerOutput] = []

        def _builder(
            accepted: PlannerOutput, _telemetry: Any
        ) -> list[ConversationMessage]:
            captured_outputs.append(accepted)
            return [
                ConversationMessage(role="user", content="trigger"),
                ConversationMessage(
                    role="assistant",
                    content=f"note={accepted.planner_action.payload.note!r}",
                ),
            ]

        result = await run_planner_turn(
            repo=repo,
            litellm_client=llm,
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
            session_id=uuid4(),
            tenant_id=uuid4(),
            flow=flow_stub,  # type: ignore[arg-type]
            base_messages=[{"role": "system", "content": "system"}],
            orchestration_context=_ctx(),
            build_new_messages=_builder,
            request_id=request_id,
            lock_token=lock_token,
        )

        assert result.kind == "dispatched"
        assert len(captured_outputs) == 1
        assert captured_outputs[0].planner_action.kind == "commit_architecture"
        commit_kwargs = repo.commit_turn.await_args.kwargs
        assert commit_kwargs["flow"] is flow_stub
        assert commit_kwargs["request_id"] == request_id
        assert commit_kwargs["lock_token"] == lock_token
        assert len(commit_kwargs["new_messages"]) == 2
        assert commit_kwargs["new_messages"][1].content == "note=''"


@pytest.mark.asyncio
class TestProposePlanPendingAdapter:
    async def test_propose_plan_surfaces_pending_adapter_outcome(self) -> None:
        repo = _autospec_repo()
        commit = _make_commit()
        state = _make_state(architecture_commit=commit)
        llm = AsyncMock()
        llm.acompletion.return_value = _llm_response(
            _planner_output_json(
                kind="propose_plan",
                architecture_commit=commit,
                draft_plan=_single_step_draft_plan(),
            )
        )

        def _should_not_build(_a: Any, _t: Any) -> list[ConversationMessage]:
            raise AssertionError(
                "propose_plan_pending_adapter must not invoke the builder; "
                "nothing is persisted on that outcome"
            )

        result = await run_planner_turn(
            repo=repo,
            litellm_client=llm,
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
            session_id=uuid4(),
            tenant_id=uuid4(),
            flow=None,
            base_messages=[{"role": "system", "content": "system"}],
            orchestration_context=_ctx(state=state),
            build_new_messages=_should_not_build,
        )

        assert result.kind == "propose_plan_pending_adapter"
        assert result.accepted_output is not None
        assert result.accepted_output.planner_action.kind == "propose_plan"
        assert result.dispatch_result is None
        assert result.llm_calls_made == 1
        repo.commit_turn.assert_not_awaited()


@pytest.mark.asyncio
class TestPipelineRejections:
    async def test_rejected_version_mismatch_returns_rejected_outcome(self) -> None:
        repo = _autospec_repo()
        llm = AsyncMock()
        llm.acompletion.return_value = _llm_response(
            _planner_output_json(kind="confirm_requirements", base_version=99)
        )

        def _should_not_build(_a: Any, _t: Any) -> list[ConversationMessage]:
            raise AssertionError(
                "rejected outcome must not invoke the builder; no persistence"
            )

        result = await run_planner_turn(
            repo=repo,
            litellm_client=llm,
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
            session_id=uuid4(),
            tenant_id=uuid4(),
            flow=None,
            base_messages=[{"role": "system", "content": "system"}],
            orchestration_context=_ctx(current_version=3),
            build_new_messages=_should_not_build,
        )

        assert result.kind == "rejected"
        assert result.rejection is not None
        assert result.rejection.code == "version_mismatch"
        assert result.rejection.current_version == 3
        repo.commit_turn.assert_not_awaited()


@pytest.mark.asyncio
class TestPipelineParseFailed:
    async def test_parse_failed_with_length_finish_reason_surfaces_metadata(
        self,
    ) -> None:
        repo = _autospec_repo()
        llm = AsyncMock()
        llm.acompletion.return_value = _llm_response(
            '{"partial":',
            finish_reason="length",
            completion_tokens=1024,
        )

        def _should_not_build(_a: Any, _t: Any) -> list[ConversationMessage]:
            raise AssertionError(
                "parse_failed outcome must not invoke the builder; no persistence"
            )

        result = await run_planner_turn(
            repo=repo,
            litellm_client=llm,
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
            session_id=uuid4(),
            tenant_id=uuid4(),
            flow=None,
            base_messages=[{"role": "system", "content": "system"}],
            orchestration_context=_ctx(),
            build_new_messages=_should_not_build,
        )

        assert result.kind == "parse_failed"
        assert result.final_completion is not None
        assert result.final_completion.finish_reason == "length"
        assert result.final_completion.completion_tokens == 1024
        assert result.parse_error_raw is not None
        repo.commit_turn.assert_not_awaited()


class TestPublicSurface:
    def test_run_planner_turn_is_exported(self) -> None:
        from intric.flows.ai_builder import ai_builder_planner_turn as module

        assert "run_planner_turn" in module.__all__
        assert "PlannerTurnResult" in module.__all__
        assert "PlannerTurnOutcomeKind" in module.__all__
        assert "TurnTelemetry" in module.__all__


@pytest.mark.asyncio
class TestTurnTelemetry:
    async def test_dispatched_commit_populates_turn_telemetry(self) -> None:
        repo = _autospec_repo()
        repo.commit_turn.return_value = 4
        commit = _make_commit()
        llm = AsyncMock()
        llm.acompletion.return_value = _llm_response(
            _planner_output_json(
                kind="commit_architecture", architecture_commit=commit
            ),
            prompt_tokens=321,
            completion_tokens=87,
            total_tokens=408,
        )
        request_id = uuid4()

        result = await run_planner_turn(
            repo=repo,
            litellm_client=llm,
            litellm_model="openai/gpt-5.5",
            litellm_kwargs={},
            session_id=uuid4(),
            tenant_id=uuid4(),
            flow=None,
            base_messages=[{"role": "system", "content": "system"}],
            orchestration_context=_ctx(),
            build_new_messages=lambda _a, _t: [
                ConversationMessage(role="user", content="Commit")
            ],
            request_id=request_id,
        )

        assert result.kind == "dispatched"
        assert result.turn_telemetry is not None
        t: TurnTelemetry = result.turn_telemetry
        assert t.outcome_kind == "dispatched"
        assert t.request_id == str(request_id)
        assert t.model == "openai/gpt-5.5"
        assert t.prompt_tokens == 321
        assert t.completion_tokens == 87
        assert t.total_tokens == 408
        assert t.finish_reason == "stop"
        assert t.llm_calls_made == 1
        assert t.repair_attempts == 0
        assert t.architecture_commit_populated is True
        assert t.wall_clock_ms >= 0

    async def test_dispatched_ask_question_marks_commit_not_populated(self) -> None:
        repo = _autospec_repo()
        repo.commit_turn.return_value = 1
        llm = AsyncMock()
        llm.acompletion.return_value = _llm_response(
            _planner_output_json(kind="ask_question")
        )

        result = await run_planner_turn(
            repo=repo,
            litellm_client=llm,
            litellm_model="openai/gpt-5.5",
            litellm_kwargs={},
            session_id=uuid4(),
            tenant_id=uuid4(),
            flow=None,
            base_messages=[{"role": "system", "content": "system"}],
            orchestration_context=_ctx(
                required_slot_names=frozenset({"primary_runtime_input"})
            ),
            build_new_messages=lambda _a, _t: [
                ConversationMessage(role="user", content="Q")
            ],
        )

        assert result.turn_telemetry is not None
        assert result.turn_telemetry.architecture_commit_populated is False
        assert result.turn_telemetry.outcome_kind == "dispatched"

    async def test_rejected_outcome_populates_telemetry_without_dispatch_fields(
        self,
    ) -> None:
        repo = _autospec_repo()
        llm = AsyncMock()
        llm.acompletion.return_value = _llm_response(
            _planner_output_json(kind="confirm_requirements", base_version=99),
            prompt_tokens=200,
            completion_tokens=40,
            total_tokens=240,
        )

        def _should_not_build(_a: Any, _t: Any) -> list[ConversationMessage]:
            raise AssertionError("rejected outcome must not invoke the builder")

        result = await run_planner_turn(
            repo=repo,
            litellm_client=llm,
            litellm_model="openai/gpt-5.5",
            litellm_kwargs={},
            session_id=uuid4(),
            tenant_id=uuid4(),
            flow=None,
            base_messages=[{"role": "system", "content": "system"}],
            orchestration_context=_ctx(current_version=3),
            build_new_messages=_should_not_build,
        )

        assert result.kind == "rejected"
        assert result.turn_telemetry is not None
        assert result.turn_telemetry.outcome_kind == "rejected"
        assert result.turn_telemetry.prompt_tokens == 200
        assert result.turn_telemetry.architecture_commit_populated is False

    async def test_parse_failed_outcome_populates_telemetry_with_length_finish_reason(
        self,
    ) -> None:
        repo = _autospec_repo()
        llm = AsyncMock()
        llm.acompletion.return_value = _llm_response(
            '{"partial":',
            finish_reason="length",
            completion_tokens=1024,
        )

        def _should_not_build(_a: Any, _t: Any) -> list[ConversationMessage]:
            raise AssertionError("parse_failed outcome must not invoke the builder")

        result = await run_planner_turn(
            repo=repo,
            litellm_client=llm,
            litellm_model="openai/gpt-5.5",
            litellm_kwargs={},
            session_id=uuid4(),
            tenant_id=uuid4(),
            flow=None,
            base_messages=[{"role": "system", "content": "system"}],
            orchestration_context=_ctx(),
            build_new_messages=_should_not_build,
        )

        assert result.kind == "parse_failed"
        assert result.turn_telemetry is not None
        assert result.turn_telemetry.outcome_kind == "parse_failed"
        assert result.turn_telemetry.finish_reason == "length"
        assert result.turn_telemetry.completion_tokens == 1024

    async def test_propose_plan_pending_adapter_populates_telemetry(self) -> None:
        repo = _autospec_repo()
        commit = _make_commit()
        state = _make_state(architecture_commit=commit)
        llm = AsyncMock()
        llm.acompletion.return_value = _llm_response(
            _planner_output_json(
                kind="propose_plan",
                architecture_commit=commit,
                draft_plan=_single_step_draft_plan(),
            )
        )

        def _should_not_build(_a: Any, _t: Any) -> list[ConversationMessage]:
            raise AssertionError("propose_plan_pending_adapter must not build")

        result = await run_planner_turn(
            repo=repo,
            litellm_client=llm,
            litellm_model="openai/gpt-5.5",
            litellm_kwargs={},
            session_id=uuid4(),
            tenant_id=uuid4(),
            flow=None,
            base_messages=[{"role": "system", "content": "system"}],
            orchestration_context=_ctx(state=state),
            build_new_messages=_should_not_build,
        )

        assert result.kind == "propose_plan_pending_adapter"
        assert result.turn_telemetry is not None
        assert result.turn_telemetry.outcome_kind == "propose_plan_pending_adapter"
        assert result.turn_telemetry.llm_calls_made == 1
        # The committed architecture is already on the session state;
        # the planner's propose_plan delta does not _populate_ a new commit.
        assert result.turn_telemetry.architecture_commit_populated is False

    async def test_injectable_clock_produces_deterministic_wall_clock(self) -> None:
        """`telemetry_now_ms` overrides the default `time.perf_counter` source.

        A deterministic tick sequence (start, end) lets the test assert
        `wall_clock_ms == end - start` exactly, so a future refactor that
        silently stops honoring the hook regresses here.
        """
        repo = _autospec_repo()
        repo.commit_turn.return_value = 1
        llm = AsyncMock()
        llm.acompletion.return_value = _llm_response(
            _planner_output_json(kind="ask_question")
        )

        ticks = iter([1_000, 1_725])

        result = await run_planner_turn(
            repo=repo,
            litellm_client=llm,
            litellm_model="openai/gpt-5.5",
            litellm_kwargs={},
            session_id=uuid4(),
            tenant_id=uuid4(),
            flow=None,
            base_messages=[{"role": "system", "content": "system"}],
            orchestration_context=_ctx(
                required_slot_names=frozenset({"primary_runtime_input"})
            ),
            build_new_messages=lambda _a, _t: [
                ConversationMessage(role="user", content="Q")
            ],
            telemetry_now_ms=lambda: next(ticks),
        )

        assert result.turn_telemetry is not None
        assert result.turn_telemetry.wall_clock_ms == 725

    async def test_injectable_clock_clamps_backwards_drift_to_zero(self) -> None:
        """A backwards clock (end < start) must not produce a negative wall_clock."""
        repo = _autospec_repo()
        repo.commit_turn.return_value = 1
        llm = AsyncMock()
        llm.acompletion.return_value = _llm_response(
            _planner_output_json(kind="ask_question")
        )

        ticks = iter([5_000, 4_000])

        result = await run_planner_turn(
            repo=repo,
            litellm_client=llm,
            litellm_model="openai/gpt-5.5",
            litellm_kwargs={},
            session_id=uuid4(),
            tenant_id=uuid4(),
            flow=None,
            base_messages=[{"role": "system", "content": "system"}],
            orchestration_context=_ctx(
                required_slot_names=frozenset({"primary_runtime_input"})
            ),
            build_new_messages=lambda _a, _t: [
                ConversationMessage(role="user", content="Q")
            ],
            telemetry_now_ms=lambda: next(ticks),
        )

        assert result.turn_telemetry is not None
        assert result.turn_telemetry.wall_clock_ms == 0
