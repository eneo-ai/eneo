from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from intric.authentication.principal_types import PrincipalType
from intric.flows.domain.flow import FlowRun, FlowRunStatus
from intric.flows.enums import FlowOutputMode
from intric.flows.runtime.models import (
    RunExecutionState,
    RuntimeStep,
    StepExecutionOutput,
    StepInputValue,
)
from intric.flows.runtime.step_execution_result import (
    StepExecutionResult,
    WebhookPayloadRef,
)
from intric.flows.runtime.step_execution_runtime import (
    PreparedStepExecution,
    StepExecutionRuntimeDeps,
)
from intric.flows.runtime.step_handlers import STEP_HANDLER_REGISTRY
from intric.flows.runtime.step_handlers.base import PreparedAssistantStep
from intric.flows.runtime.step_handlers.http_post import HttpPostStepHandler
from intric.flows.runtime.step_handlers.pass_through import PassThroughStepHandler
from intric.flows.runtime.step_handlers.template_fill import TemplateFillStepHandler
from intric.flows.runtime.step_handlers.transcribe_only import TranscribeOnlyStepHandler
from intric.flows.variable_resolver import FlowVariableResolver

FLOW_RUNTIME_ROOT = (
    Path(__file__).resolve().parents[3] / "src" / "intric" / "flows" / "runtime"
)


def _run() -> FlowRun:
    now = datetime.now(timezone.utc)
    return FlowRun(
        id=uuid4(),
        flow_id=uuid4(),
        flow_version=1,
        principal_type=PrincipalType.USER,
        principal_user_id=uuid4(),
        tenant_id=uuid4(),
        trace_id=uuid4(),
        status=FlowRunStatus.RUNNING,
        input_payload_json={"Body": "Transcript"},
        created_at=now,
        updated_at=now,
    )


def _state() -> RunExecutionState:
    return RunExecutionState(
        completed_by_order={},
        prior_results=[],
        assistant_cache={},
        json_mode_supported={},
        file_cache={},
    )


def _step(*, output_mode: str = "pass_through") -> RuntimeStep:
    return RuntimeStep(
        step_id=uuid4(),
        step_order=1,
        assistant_id=uuid4(),
        user_description=None,
        input_source="flow_input",
        input_bindings=None,
        input_config=None,
        output_mode=output_mode,
        output_config=None,
        output_type="text",
        input_type="audio" if output_mode == "transcribe_only" else "text",
    )


def _step_output() -> StepExecutionOutput:
    return StepExecutionOutput(
        input_text="hello",
        source_text="hello",
        input_source="flow_input",
        used_question_binding=False,
        legacy_prompt_binding_used=False,
        full_text="done",
        persisted_text="done",
        generated_file_ids=[],
        tool_calls_metadata=None,
        num_tokens_input=2,
        num_tokens_output=3,
        effective_prompt="prompt",
        model_parameters_json={"temperature": 0.2},
    )


def _prepared_assistant_step(
    *,
    assistant: MagicMock | None = None,
    apply_output_cap: AsyncMock | None = None,
) -> PreparedAssistantStep:
    resolved_assistant = assistant or MagicMock()
    resolved_apply_output_cap = apply_output_cap or AsyncMock(
        return_value=("Transcript", [])
    )
    prepared = PreparedStepExecution(
        assistant=resolved_assistant,
        step_input=StepInputValue(
            text="Transcript",
            source_text="Transcript",
            input_source="flow_input",
            transcription_metadata={"model": "whisper-1"},
        ),
        effective_prompt="unused",
        input_payload_for_result={
            "text": "Transcript",
            "source_text": "Transcript",
            "input_source": "flow_input",
        },
        contract_validation=None,
        diagnostics=[],
        llm_files=[],
    )
    deps = StepExecutionRuntimeDeps(
        variable_resolver=FlowVariableResolver(),
        completion_service=object(),
        load_assistant=AsyncMock(),
        resolve_step_input=AsyncMock(),
        retrieve_rag_chunks=AsyncMock(),
        process_typed_output=AsyncMock(),
        apply_output_cap=resolved_apply_output_cap,
        attach_typed_failure_context=lambda exc, **kwargs: exc,
        effective_model_parameters=lambda assistant_obj: {},
        json_mode_cache_key=lambda assistant_obj: "unused",
        is_json_mode_rejection=lambda exc: False,
        count_tokens=lambda text: len(text),
    )
    return PreparedAssistantStep(prepared=prepared, deps=deps)


class _OutputOnlyHandler:
    output_mode = FlowOutputMode.PASS_THROUGH

    async def execute(
        self,
        *,
        step: RuntimeStep,
        run: FlowRun,
        state: RunExecutionState,
        version_metadata: dict[str, object] | None,
        attempt_no: int | None,
    ) -> StepExecutionResult:
        return StepExecutionResult(output=_step_output())


def test_registry_covers_all_flow_output_modes() -> None:
    assert set(STEP_HANDLER_REGISTRY) == set(FlowOutputMode), (
        "runtime/step_handlers.STEP_HANDLER_REGISTRY is the canonical output_mode "
        "owner. Add one handler entry for every FlowOutputMode instead of branching "
        "in generic runtime code."
    )


def _build_step_handler_match_modes() -> frozenset[FlowOutputMode]:
    tree = ast.parse((FLOW_RUNTIME_ROOT / "executor.py").read_text())
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != "_build_step_handler":
            continue
        modes: set[FlowOutputMode] = set()
        for child in ast.walk(node):
            if not isinstance(child, ast.Match):
                continue
            for case in child.cases:
                pattern = case.pattern
                if not (
                    isinstance(pattern, ast.MatchValue)
                    and isinstance(pattern.value, ast.Attribute)
                    and isinstance(pattern.value.value, ast.Name)
                    and pattern.value.value.id == "FlowOutputMode"
                ):
                    continue
                modes.add(FlowOutputMode[pattern.value.attr])
        return frozenset(modes)
    raise AssertionError("FlowRunExecutor._build_step_handler was not found")


def test_executor_handler_match_cases_cover_registry_modes() -> None:
    match_modes = _build_step_handler_match_modes()

    assert match_modes == set(STEP_HANDLER_REGISTRY), (
        "FlowRunExecutor._build_step_handler is the temporary construction guard "
        "for runtime/step_handlers. Keep its FlowOutputMode match cases in sync "
        "with STEP_HANDLER_REGISTRY until executor.py can use assert_never."
    )


@pytest.mark.asyncio
async def test_http_post_handler_emits_exactly_one_webhook_intent() -> None:
    run = _run()
    step = _step(output_mode="http_post")
    handler = HttpPostStepHandler(completion_handler=_OutputOnlyHandler())

    result = await handler.execute(
        step=step,
        run=run,
        state=_state(),
        version_metadata=None,
        attempt_no=3,
    )

    assert result.output.full_text == "done"
    assert len(result.delivery_intents) == 1
    intent = result.delivery_intents[0]
    assert intent.flow_run_id == run.id
    assert intent.step_id == step.step_id
    assert intent.step_order == step.step_order
    assert intent.attempt_no == 3
    assert intent.idempotency_key
    assert isinstance(intent.payload, WebhookPayloadRef)


@pytest.mark.asyncio
async def test_http_post_handler_requires_attempt_no() -> None:
    handler = HttpPostStepHandler(completion_handler=_OutputOnlyHandler())

    with pytest.raises(ValueError, match="requires attempt_no"):
        await handler.execute(
            step=_step(output_mode="http_post"),
            run=_run(),
            state=_state(),
            version_metadata=None,
            attempt_no=None,
        )


@pytest.mark.asyncio
async def test_pass_through_handler_wraps_completion_output(monkeypatch) -> None:
    completion_output = _step_output()
    complete_step_execution = AsyncMock(return_value=completion_output)
    monkeypatch.setattr(
        "intric.flows.runtime.step_handlers.pass_through.complete_step_execution",
        complete_step_execution,
    )

    async def _prepare(
        *,
        step: RuntimeStep,
        run: FlowRun,
        state: RunExecutionState,
        version_metadata: dict[str, object] | None,
        attempt_no: int | None,
    ) -> PreparedAssistantStep:
        return _prepared_assistant_step()

    run = _run()
    step = _step()
    state = _state()
    handler = PassThroughStepHandler(prepare_assistant_step=_prepare)

    result = await handler.execute(
        step=step,
        run=run,
        state=state,
        version_metadata=None,
        attempt_no=1,
    )

    assert result == StepExecutionResult(output=completion_output)
    complete_step_execution.assert_awaited_once()
    assert complete_step_execution.await_args.kwargs["step"] == step
    assert complete_step_execution.await_args.kwargs["run"] == run
    assert complete_step_execution.await_args.kwargs["state"] == state


@pytest.mark.asyncio
async def test_template_fill_handler_wraps_template_fill_output(monkeypatch) -> None:
    template_output = _step_output()
    execute_template_fill_step = AsyncMock(return_value=template_output)
    monkeypatch.setattr(
        "intric.flows.runtime.step_handlers.template_fill.execute_template_fill_step",
        execute_template_fill_step,
    )

    run = _run()
    step = _step(output_mode="template_fill")
    state = _state()
    deps = MagicMock()
    handler = TemplateFillStepHandler(deps=deps)

    result = await handler.execute(
        step=step,
        run=run,
        state=state,
        version_metadata=None,
        attempt_no=1,
    )

    assert result == StepExecutionResult(output=template_output)
    execute_template_fill_step.assert_awaited_once_with(
        step=step,
        run=run,
        state=state,
        deps=deps,
    )


@pytest.mark.asyncio
async def test_transcribe_only_handler_skips_llm_and_rag() -> None:
    assistant = MagicMock()
    assistant.get_response = AsyncMock()
    prepared_step = _prepared_assistant_step(assistant=assistant)

    async def _prepare(
        *,
        step: RuntimeStep,
        run: FlowRun,
        state: RunExecutionState,
        version_metadata: dict[str, object] | None,
        attempt_no: int | None,
    ) -> PreparedAssistantStep:
        return prepared_step

    handler = TranscribeOnlyStepHandler(prepare_assistant_step=_prepare)
    result = await handler.execute(
        step=_step(output_mode="transcribe_only"),
        run=_run(),
        state=_state(),
        version_metadata=None,
        attempt_no=1,
    )

    assistant.get_response.assert_not_awaited()
    prepared_step.deps.retrieve_rag_chunks.assert_not_awaited()
    assert result.output.full_text == "Transcript"
    assert result.output.num_tokens_input == 0
    assert result.output.num_tokens_output == 0
    assert any(
        diagnostic.code == "audio_transcribe_only_used"
        for diagnostic in result.output.diagnostics
    )
    assert result.output.rag_metadata == {
        "attempted": False,
        "status": "skipped_transcribe_only",
        "version": 1,
        "timeout_seconds": 30,
        "include_info_blobs": False,
        "chunks_retrieved": 0,
        "raw_chunks_count": 0,
        "deduped_chunks_count": 0,
        "unique_sources": 0,
        "source_ids": [],
        "source_ids_short": [],
        "error_code": None,
        "retrieval_duration_ms": None,
        "retrieval_error_type": None,
        "references": [],
        "references_truncated": False,
    }
