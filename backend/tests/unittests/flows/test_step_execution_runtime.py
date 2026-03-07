from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from intric.flows.flow import FlowRun, FlowRunStatus
from intric.flows.runtime.models import RunExecutionState, RuntimeStep, StepExecutionOutput, StepInputValue
from intric.flows.runtime.step_execution_runtime import (
    PreparedStepExecution,
    StepExecutionRuntimeDeps,
    attach_typed_failure_context,
    augment_prompt_for_json_output,
    build_output_payload,
    complete_step_execution,
    detect_native_json_output_support,
    effective_model_parameters,
    execution_hash,
    is_json_mode_rejection,
    json_mode_cache_key,
    prepare_step_execution,
)
from intric.main.exceptions import TypedIOValidationException
from intric.flows.variable_resolver import FlowVariableResolver


def _run() -> FlowRun:
    now = datetime.now(timezone.utc)
    return FlowRun(
        id=uuid4(),
        flow_id=uuid4(),
        flow_version=1,
        user_id=uuid4(),
        tenant_id=uuid4(),
        status=FlowRunStatus.RUNNING,
        input_payload_json={"text": '{"title":"A"}'},
        created_at=now,
        updated_at=now,
    )


def _state() -> RunExecutionState:
    return RunExecutionState(
        completed_by_order={},
        prior_results=[],
        all_previous_segments=[],
        assistant_cache={},
        json_mode_supported={},
        file_cache={},
    )


def _step(
    *,
    input_type: str = "text",
    output_type: str = "text",
    output_mode: str = "pass_through",
    input_contract: dict[str, object] | None = None,
) -> RuntimeStep:
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
        output_type=output_type,
        input_type=input_type,
        input_contract=input_contract,
    )


@pytest.mark.asyncio
async def test_prepare_step_execution_interpolates_prompt_and_records_contract_validation():
    run = _run()
    state = _state()
    step = _step(
        input_contract={
            "type": "object",
            "required": ["title"],
            "properties": {"title": {"type": "string"}},
        }
    )
    assistant = MagicMock()
    assistant.get_prompt_text.return_value = "Review {{flow_input.text}}"
    step_input = StepInputValue(
        text='{"title":"A"}',
        source_text='{"title":"A"}',
        input_source="flow_input",
    )
    deps = StepExecutionRuntimeDeps(
        variable_resolver=FlowVariableResolver(),
        completion_service=object(),
        load_assistant=AsyncMock(return_value=assistant),
        resolve_step_input=AsyncMock(return_value=step_input),
        retrieve_rag_chunks=AsyncMock(),
        process_typed_output=AsyncMock(),
        apply_output_cap=AsyncMock(),
        attach_typed_failure_context=lambda exc, **kwargs: exc,
        effective_model_parameters=lambda assistant_obj: {},
        json_mode_cache_key=lambda assistant_obj: "unused",
        is_json_mode_rejection=lambda exc: False,
        count_tokens=lambda text: len(text),
    )

    prepared = await prepare_step_execution(
        step=step,
        run=run,
        state=state,
        version_metadata=None,
        deps=deps,
    )

    assert prepared.effective_prompt.startswith('Review {"title":"A"}')
    assert "Return ONLY valid JSON." not in prepared.effective_prompt
    assert prepared.input_payload_for_result["text"] == '{"title":"A"}'
    assert prepared.input_payload_for_result["contract_validation"] == {
        "schema_type_hint": "object",
        "parse_attempted": True,
        "parse_succeeded": True,
        "candidate_type": "dict",
    }
    assert prepared.contract_validation == prepared.input_payload_for_result["contract_validation"]
    assert prepared.llm_files == []


def test_augment_prompt_for_json_output_appends_schema_instructions():
    prompt = augment_prompt_for_json_output(
        output_type="json",
        output_contract={"type": "object", "properties": {"ok": {"type": "boolean"}}},
        prompt="Analyze the text",
    )

    assert prompt.startswith("Analyze the text")
    assert "Return ONLY valid JSON." in prompt
    assert "Do not include markdown code fences" in prompt
    assert '"type": "object"' in prompt
    assert '"ok"' in prompt


def test_detect_native_json_output_support_uses_litellm_model_name(monkeypatch: pytest.MonkeyPatch):
    captured: list[str] = []

    def fake_supported_params(*, model: str):
        captured.append(model)
        return ["response_format", "temperature"]

    monkeypatch.setattr(
        "intric.flows.runtime.step_execution_runtime._litellm_get_supported_openai_params",
        fake_supported_params,
    )
    assistant = SimpleNamespace(
        completion_model=SimpleNamespace(
            litellm_model_name="azure/gpt-4.1-mini",
            name="ignored-name",
            provider_type="ignored-provider",
        )
    )

    supported = detect_native_json_output_support(assistant)

    assert supported is True
    assert captured == ["azure/gpt-4.1-mini"]


def test_detect_native_json_output_support_falls_back_to_provider_prefixed_name(
    monkeypatch: pytest.MonkeyPatch,
):
    captured: list[str] = []

    def fake_supported_params(*, model: str):
        captured.append(model)
        return ["temperature"]

    monkeypatch.setattr(
        "intric.flows.runtime.step_execution_runtime._litellm_get_supported_openai_params",
        fake_supported_params,
    )
    assistant = SimpleNamespace(
        completion_model=SimpleNamespace(
            litellm_model_name=None,
            name="claude-3-5-haiku",
            provider_type="anthropic",
        )
    )

    supported = detect_native_json_output_support(assistant)

    assert supported is False
    assert captured == ["anthropic/claude-3-5-haiku"]


@pytest.mark.asyncio
async def test_complete_step_execution_falls_back_when_json_mode_rejected(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "intric.flows.runtime.step_execution_runtime.detect_native_json_output_support",
        lambda assistant: None,
    )
    run = _run()
    state = _state()
    step = _step(output_type="json")
    original_kwargs = MagicMock(name="original_kwargs")
    json_mode_kwargs = MagicMock(name="json_mode_kwargs")
    assistant = MagicMock()
    assistant.completion_model_kwargs = original_kwargs
    assistant.completion_model_kwargs.model_copy.return_value = json_mode_kwargs
    assistant.get_response = AsyncMock(
        side_effect=[
            RuntimeError("response_format json_object unsupported"),
            SimpleNamespace(total_token_count=4, completion='{"ok": true}'),
        ]
    )
    prepared = PreparedStepExecution(
        assistant=assistant,
        step_input=StepInputValue(
            text="hello",
            source_text="hello",
            input_source="flow_input",
        ),
        effective_prompt="Prompt",
        input_payload_for_result={"text": "hello", "source_text": "hello", "input_source": "flow_input"},
        contract_validation=None,
        diagnostics=[],
        llm_files=[],
    )
    deps = StepExecutionRuntimeDeps(
        variable_resolver=FlowVariableResolver(),
        completion_service=object(),
        load_assistant=AsyncMock(),
        resolve_step_input=AsyncMock(),
        retrieve_rag_chunks=AsyncMock(return_value=([], {"status": "skipped_no_service"}, [])),
        process_typed_output=AsyncMock(return_value=({"ok": True}, None)),
        apply_output_cap=AsyncMock(return_value=('{"ok": true}', [])),
        attach_typed_failure_context=lambda exc, **kwargs: exc,
        effective_model_parameters=lambda assistant_obj: {"temperature": 0.2},
        json_mode_cache_key=lambda assistant_obj: "provider:model:1",
        is_json_mode_rejection=lambda exc: "response_format" in str(exc),
        count_tokens=lambda text: len(text),
    )

    output = await complete_step_execution(
        step=step,
        run=run,
        state=state,
        prepared=prepared,
        deps=deps,
    )

    assert assistant.get_response.await_count == 2
    first_kwargs = assistant.get_response.await_args_list[0].kwargs
    second_kwargs = assistant.get_response.await_args_list[1].kwargs
    assert first_kwargs["model_kwargs"] is json_mode_kwargs
    assert second_kwargs["model_kwargs"] is original_kwargs
    assert state.json_mode_supported["provider:model:1"] is False
    assert output.structured_output == {"ok": True}
    assert output.full_text == '{"ok": true}'


@pytest.mark.asyncio
async def test_complete_step_execution_skips_native_json_mode_when_capability_is_known_unsupported(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "intric.flows.runtime.step_execution_runtime.detect_native_json_output_support",
        lambda assistant: False,
    )
    run = _run()
    state = _state()
    step = _step(output_type="json")
    original_kwargs = MagicMock(name="original_kwargs")
    assistant = MagicMock()
    assistant.completion_model = SimpleNamespace(
        litellm_model_name=None,
        name="claude-3-5-haiku",
        provider_type="anthropic",
    )
    assistant.completion_model_kwargs = original_kwargs
    assistant.get_response = AsyncMock(
        return_value=SimpleNamespace(total_token_count=4, completion='{"ok": true}')
    )
    prepared = PreparedStepExecution(
        assistant=assistant,
        step_input=StepInputValue(
            text="hello",
            source_text="hello",
            input_source="flow_input",
        ),
        effective_prompt="Prompt",
        input_payload_for_result={"text": "hello", "source_text": "hello", "input_source": "flow_input"},
        contract_validation=None,
        diagnostics=[],
        llm_files=[],
    )
    deps = StepExecutionRuntimeDeps(
        variable_resolver=FlowVariableResolver(),
        completion_service=object(),
        load_assistant=AsyncMock(),
        resolve_step_input=AsyncMock(),
        retrieve_rag_chunks=AsyncMock(return_value=([], {"status": "skipped_no_service"}, [])),
        process_typed_output=AsyncMock(return_value=({"ok": True}, None)),
        apply_output_cap=AsyncMock(return_value=('{"ok": true}', [])),
        attach_typed_failure_context=lambda exc, **kwargs: exc,
        effective_model_parameters=lambda assistant_obj: {"temperature": 0.2},
        json_mode_cache_key=lambda assistant_obj: "anthropic:haiku:1",
        is_json_mode_rejection=lambda exc: "response_format" in str(exc),
        count_tokens=lambda text: len(text),
    )

    output = await complete_step_execution(
        step=step,
        run=run,
        state=state,
        prepared=prepared,
        deps=deps,
    )

    assert assistant.completion_model_kwargs.model_copy.call_count == 0
    assert assistant.get_response.await_count == 1
    assert assistant.get_response.await_args.kwargs["model_kwargs"] is original_kwargs
    assert state.json_mode_supported["anthropic:haiku:1"] is False
    assert output.structured_output == {"ok": True}


@pytest.mark.asyncio
async def test_complete_step_execution_transcribe_only_skips_llm_and_rag():
    run = _run()
    state = _state()
    step = _step(input_type="audio", output_type="text", output_mode="transcribe_only")
    assistant = MagicMock()
    assistant.get_response = AsyncMock()
    prepared = PreparedStepExecution(
        assistant=assistant,
        step_input=StepInputValue(
            text="Transcript",
            source_text="Transcript",
            input_source="flow_input",
            transcription_metadata={"model": "whisper-1"},
        ),
        effective_prompt="unused",
        input_payload_for_result={"text": "Transcript", "source_text": "Transcript", "input_source": "flow_input"},
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
        apply_output_cap=AsyncMock(return_value=("Transcript", [])),
        attach_typed_failure_context=lambda exc, **kwargs: exc,
        effective_model_parameters=lambda assistant_obj: {},
        json_mode_cache_key=lambda assistant_obj: "unused",
        is_json_mode_rejection=lambda exc: False,
        count_tokens=lambda text: len(text),
    )

    output = await complete_step_execution(
        step=step,
        run=run,
        state=state,
        prepared=prepared,
        deps=deps,
    )

    assistant.get_response.assert_not_awaited()
    deps.retrieve_rag_chunks.assert_not_awaited()
    assert output.full_text == "Transcript"
    assert output.rag_metadata == {
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
    assert any(d.code == "audio_transcribe_only_used" for d in output.diagnostics)


def test_attach_typed_failure_context_backfills_payload_and_prompt():
    exc = TypedIOValidationException("bad input", code="typed_io_contract_violation")

    updated = attach_typed_failure_context(
        exc,
        input_payload_for_result={"input_source": "flow_input"},
        effective_prompt="Prompt",
    )

    assert updated.input_payload_json == {
        "input_source": "flow_input",
        "text": "",
        "source_text": "",
        "used_question_binding": False,
        "legacy_prompt_binding_used": False,
    }
    assert updated.effective_prompt == "Prompt"


def test_attach_typed_failure_context_preserves_existing_payload_and_prompt():
    exc = TypedIOValidationException("bad input", code="typed_io_contract_violation")
    exc.input_payload_json = {"text": "keep"}
    exc.effective_prompt = "Keep prompt"

    updated = attach_typed_failure_context(
        exc,
        input_payload_for_result={"input_source": "flow_input"},
        effective_prompt="New prompt",
    )

    assert updated.input_payload_json == {"text": "keep"}
    assert updated.effective_prompt == "Keep prompt"


def test_build_output_payload_includes_structured_and_artifacts():
    payload = build_output_payload(
        StepExecutionOutput(
            input_text="hello",
            source_text="hello",
            input_source="flow_input",
            used_question_binding=False,
            legacy_prompt_binding_used=False,
            full_text="done",
            persisted_text="done",
            generated_file_ids=[],
            tool_calls_metadata=None,
            num_tokens_input=1,
            num_tokens_output=1,
            effective_prompt="prompt",
            model_parameters_json={},
            structured_output={"ok": True},
            artifacts=[{"file_id": "1", "name": "out.pdf"}],
        )
    )

    assert payload == {
        "text": "done",
        "generated_file_ids": [],
        "file_ids": [],
        "webhook_delivered": False,
        "structured": {"ok": True},
        "artifacts": [{"file_id": "1", "name": "out.pdf"}],
    }


def test_json_mode_cache_key_uses_provider_name_and_id():
    assistant = SimpleNamespace(
        completion_model=SimpleNamespace(id=uuid4(), name="gpt-4.1", provider_type="openai")
    )

    cache_key = json_mode_cache_key(assistant)

    assert cache_key.startswith("openai:gpt-4.1:")


def test_is_json_mode_rejection_matches_supported_error_phrases():
    assert is_json_mode_rejection(RuntimeError("response_format is unsupported")) is True
    assert is_json_mode_rejection(RuntimeError("JSON_OBJECT mode unavailable")) is True
    assert is_json_mode_rejection(RuntimeError("some other transport failure")) is False


def test_execution_hash_is_stable_for_same_payload():
    run_id = uuid4()
    step_id = uuid4()

    first = execution_hash(
        run_id=run_id,
        step_id=step_id,
        prompt="Prompt",
        model_parameters={"temperature": 0.2, "top_p": 1.0},
    )
    second = execution_hash(
        run_id=run_id,
        step_id=step_id,
        prompt="Prompt",
        model_parameters={"top_p": 1.0, "temperature": 0.2},
    )

    assert first == second


def test_effective_model_parameters_collects_model_metadata():
    kwargs = MagicMock()
    kwargs.model_dump.return_value = {"temperature": 0.2}
    assistant = SimpleNamespace(
        completion_model_kwargs=kwargs,
        completion_model=SimpleNamespace(id=uuid4(), name="gpt-4.1", provider_type="openai"),
    )

    params = effective_model_parameters(assistant)

    assert params["model_name"] == "gpt-4.1"
    assert params["provider"] == "openai"
    assert params["temperature"] == 0.2
