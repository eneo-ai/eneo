from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from intric.authentication.principal_types import PrincipalType
from intric.flows.domain.flow import FlowRun, FlowRunStatus
from intric.flows.enums import FlowOutputMode
from intric.flows.flow_api_error_code import FlowApiErrorCode
from intric.flows.runtime.executor import FlowRunExecutor
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
from intric.flows.runtime.step_handlers import resolve_handler_mode
from intric.flows.runtime.step_handlers.base import PreparedAssistantStep
from intric.flows.runtime.step_handlers.http_post import HttpPostStepHandler
from intric.flows.runtime.step_handlers.pass_through import PassThroughStepHandler
from intric.flows.runtime.step_handlers.template_fill import TemplateFillStepHandler
from intric.flows.runtime.step_handlers.transcribe_only import TranscribeOnlyStepHandler
from intric.flows.variable_resolver import FlowVariableResolver
from intric.main.exceptions import TypedIOValidationException


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
        attempt_no: int,
    ) -> StepExecutionResult:
        return StepExecutionResult(output=_step_output())


@pytest.mark.parametrize(
    ("mode", "expected_type"),
    [
        (FlowOutputMode.PASS_THROUGH, PassThroughStepHandler),
        (FlowOutputMode.HTTP_POST, HttpPostStepHandler),
        (FlowOutputMode.TRANSCRIBE_ONLY, TranscribeOnlyStepHandler),
        (FlowOutputMode.TEMPLATE_FILL, TemplateFillStepHandler),
    ],
)
def test_executor_builds_expected_step_handler(
    mode: FlowOutputMode,
    expected_type: type[object],
) -> None:
    executor = cast(
        FlowRunExecutor,
        SimpleNamespace(
            _prepare_assistant_step=AsyncMock(),
            _template_fill_runtime_deps=MagicMock(),
        ),
    )

    handler = FlowRunExecutor._build_step_handler(executor, mode)

    assert isinstance(handler, expected_type)


def test_resolve_handler_mode_rejects_unsupported_output_mode() -> None:
    with pytest.raises(TypedIOValidationException) as exc_info:
        resolve_handler_mode("unsupported")

    assert exc_info.value.code == FlowApiErrorCode.UNSUPPORTED_OUTPUT_MODE.value


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
        attempt_no: int,
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
        attempt_no: int,
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
