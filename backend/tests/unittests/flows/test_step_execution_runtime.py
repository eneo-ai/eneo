from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.ai_models.completion_models.completion_model import (
    Completion,
    ModelKwargs,
    TokenUsage,
)
from eneo.authentication.principal_types import PrincipalType
from eneo.completion_models.domain.provider_call_observer import (
    ProviderCallRequestFacts,
    ProviderCallResultFacts,
)
from eneo.completion_models.infrastructure.context_builder import (
    ContextWindowExceededError,
)
from eneo.flows.citation_sidecar import (
    CITATION_MODE_INLINE_INREF_SIDECAR,
    CITATION_MODE_OFF,
)
from eneo.flows.domain.flow import (
    FlowRun,
    FlowRunStatus,
    FlowStepResult,
    FlowStepResultStatus,
)
from eneo.flows.domain.runtime import (
    RunExecutionState,
    RuntimeStep,
    StepDiagnostic,
    StepExecutionOutput,
    StepInputValue,
)
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_run_provenance import MappedProviderCallProvenance
from eneo.flows.flow_run_step_result_file import build_step_result_file_references
from eneo.flows.runtime.output_formats import resolve_format_spec
from eneo.flows.runtime.output_formats.base import append_output_format_instructions
from eneo.flows.runtime.output_runtime import TypedOutputProcessingResult
from eneo.flows.runtime.step_execution_runtime import (
    FlowStepCancelledError,
    PreparedStepExecution,
    StepExecutionRuntimeDeps,
    apply_prompt_context_trace,
    attach_typed_failure_context,
    build_output_payload,
    citation_mode_for_step,
    complete_step_execution,
    detect_native_json_output_support,
    effective_model_parameters,
    execution_hash,
    json_mode_cache_key,
    prepare_step_execution,
)
from eneo.flows.variable_resolver import FlowVariableResolver
from eneo.main.exceptions import (
    ProviderCapabilityRejectedException,
    TypedIOValidationException,
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
        input_payload_json={"text": '{"title":"A"}'},
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
        step_ref_mapping={},
    )


def _typed_output_result(
    structured_output=None,
    artifacts=None,
    diagnostics=None,
) -> TypedOutputProcessingResult:
    return TypedOutputProcessingResult(
        structured_output=structured_output,
        artifacts=artifacts,
        diagnostics=diagnostics or [],
    )


def _step(
    *,
    step_order: int = 1,
    input_source: str = "flow_input",
    input_type: str = "text",
    output_type: str = "text",
    output_mode: str = "pass_through",
    input_contract: dict[str, object] | None = None,
    output_contract: dict[str, object] | None = None,
    output_config: dict[str, object] | None = None,
    input_bindings: dict[str, object] | None = None,
) -> RuntimeStep:
    return RuntimeStep(
        step_id=uuid4(),
        step_order=step_order,
        assistant_id=uuid4(),
        user_description=None,
        plan_step_ref=None,
        existing_step_ref=None,
        input_source=input_source,
        input_bindings=input_bindings,
        input_config=None,
        output_mode=output_mode,
        output_config=output_config,
        output_type=output_type,
        output_contract=output_contract,
        input_type=input_type,
        input_contract=input_contract,
    )


def _prompt_for_output_format(
    *,
    output_type: str,
    output_contract: dict[str, object] | None,
    prompt: str,
) -> str:
    spec = resolve_format_spec(output_type)
    return append_output_format_instructions(
        prompt, spec.prompt_instructions(output_contract)
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
    )

    prepared = await prepare_step_execution(
        step=step,
        run=run,
        state=state,
        version_metadata=None,
        deps=deps,
        requested_file_ids=(),
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
    assert (
        prepared.contract_validation
        == prepared.input_payload_for_result["contract_validation"]
    )
    assert prepared.llm_files == []


@pytest.mark.asyncio
async def test_prepare_step_execution_reports_prompt_variable_miss_before_provider_io():
    run = _run()
    state = _state()
    step = _step()
    assistant = MagicMock()
    assistant.get_prompt_text.return_value = "Review {{flow_input.missing}}"
    assistant.get_response = AsyncMock()
    deps = StepExecutionRuntimeDeps(
        variable_resolver=FlowVariableResolver(),
        completion_service=object(),
        load_assistant=AsyncMock(return_value=assistant),
        resolve_step_input=AsyncMock(
            return_value=StepInputValue(
                text="Input",
                source_text="Input",
                input_source="flow_input",
            )
        ),
        retrieve_rag_chunks=AsyncMock(),
        process_typed_output=AsyncMock(),
        apply_output_cap=AsyncMock(),
    )

    with pytest.raises(TypedIOValidationException) as exc_info:
        await prepare_step_execution(
            step=step,
            run=run,
            state=state,
            version_metadata=None,
            deps=deps,
            requested_file_ids=(),
        )

    assert (
        exc_info.value.code
        == FlowApiErrorCode.TYPED_IO_VARIABLE_RESOLUTION_FAILED.value
    )
    assert str(exc_info.value) == (
        "Unknown variable reference: 'flow_input.missing'. Missing key 'missing'. "
        "Available keys: text."
    )
    assistant.get_response.assert_not_awaited()


@pytest.mark.asyncio
async def test_prepare_step_execution_rejects_non_json_explicit_binding_before_provider_io():
    run = _run()
    state = _state()
    step = _step(
        step_order=3,
        input_source="previous_step",
        input_type="json",
        input_contract={
            "type": "object",
            "required": ["final_report"],
            "properties": {"final_report": {"type": "string"}},
        },
    )
    assistant = MagicMock()
    assistant.get_prompt_text.return_value = "Skapa slutresultatet."
    assistant.get_response = AsyncMock()
    step_input = StepInputValue(
        text="Slutrapport: Saknar underlag\n\nTranskribering: mötesinnehåll",
        source_text='{"final_report":"Saknar underlag"}',
        input_source="previous_step",
        used_question_binding=True,
    )
    deps = StepExecutionRuntimeDeps(
        variable_resolver=FlowVariableResolver(),
        completion_service=object(),
        load_assistant=AsyncMock(return_value=assistant),
        resolve_step_input=AsyncMock(return_value=step_input),
        retrieve_rag_chunks=AsyncMock(),
        process_typed_output=AsyncMock(),
        apply_output_cap=AsyncMock(),
    )

    with pytest.raises(TypedIOValidationException) as exc_info:
        await prepare_step_execution(
            step=step,
            run=run,
            state=state,
            version_metadata=None,
            deps=deps,
            requested_file_ids=(),
        )

    assert exc_info.value.code == FlowApiErrorCode.TYPED_IO_INVALID_JSON_INPUT.value
    assert "Step 3" in str(exc_info.value)
    assert "input_bindings" in str(exc_info.value)
    assert getattr(exc_info.value, "input_payload_json")["contract_validation"] == {
        "schema_type_hint": "object",
        "parse_attempted": False,
        "parse_succeeded": False,
        "candidate_type": "str",
    }
    assistant.get_response.assert_not_awaited()


@pytest.mark.asyncio
async def test_prepare_step_execution_rejects_combined_interpolated_provider_input_cap():
    run = _run()
    run.input_payload_json = {
        "text": "a" * 24,
        "supporting_context": "b" * 24,
    }
    state = _state()
    step = _step(step_order=2)
    assistant = MagicMock()
    assistant.get_prompt_text.return_value = (
        "Primary: {{flow_input.text}}\nSupporting: {{flow_input.supporting_context}}"
    )
    assistant.get_response = AsyncMock()
    step_input = StepInputValue(
        text="c" * 24,
        source_text="c" * 24,
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
        max_inline_text_bytes=80,
    )

    with pytest.raises(TypedIOValidationException) as exc_info:
        await prepare_step_execution(
            step=step,
            run=run,
            state=state,
            version_metadata=None,
            deps=deps,
            requested_file_ids=(),
        )

    assert exc_info.value.code == FlowApiErrorCode.TYPED_IO_INPUT_TOO_LARGE.value
    assert "Step 2" in str(exc_info.value)
    assert "flow_input" in str(exc_info.value)
    effective_prompt = getattr(exc_info.value, "effective_prompt")
    assert isinstance(effective_prompt, str)
    assert effective_prompt.startswith("Primary: ")
    assert len(effective_prompt.encode("utf-8")) < 80
    assert len(step_input.text.encode("utf-8")) < 80
    assert len((effective_prompt + step_input.text).encode("utf-8")) > 80
    assistant.get_response.assert_not_awaited()


@pytest.mark.asyncio
async def test_prepare_step_execution_validates_json_binding_when_binding_is_json():
    run = _run()
    state = _state()
    step = _step(
        step_order=3,
        input_source="previous_step",
        input_type="json",
        input_contract={
            "type": "object",
            "required": ["final_report"],
            "properties": {"final_report": {"type": "string"}},
        },
    )
    assistant = MagicMock()
    assistant.get_prompt_text.return_value = "Skapa slutresultatet."
    step_input = StepInputValue(
        text='{"final_report":"Rapport från underlag"}',
        source_text='{"final_report":"Gammal rapport"}',
        structured={"final_report": "Rapport från underlag"},
        input_source="previous_step",
        used_question_binding=True,
    )
    deps = StepExecutionRuntimeDeps(
        variable_resolver=FlowVariableResolver(),
        completion_service=object(),
        load_assistant=AsyncMock(return_value=assistant),
        resolve_step_input=AsyncMock(return_value=step_input),
        retrieve_rag_chunks=AsyncMock(),
        process_typed_output=AsyncMock(),
        apply_output_cap=AsyncMock(),
    )

    prepared = await prepare_step_execution(
        step=step,
        run=run,
        state=state,
        version_metadata=None,
        deps=deps,
        requested_file_ids=(),
    )

    assert prepared.contract_validation == {
        "schema_type_hint": "object",
        "parse_attempted": False,
        "parse_succeeded": True,
        "candidate_type": "dict",
    }
    assert (
        prepared.input_payload_for_result["contract_validation"]
        == prepared.contract_validation
    )
    assert not any(
        diagnostic.code == "flow_input_contract_skipped_for_binding"
        for diagnostic in prepared.diagnostics
    )


def test_json_output_format_appends_schema_prompt_instructions():
    prompt = _prompt_for_output_format(
        output_type="json",
        output_contract={"type": "object", "properties": {"ok": {"type": "boolean"}}},
        prompt="Analyze the text",
    )

    assert prompt.startswith("Analyze the text")
    assert "Return ONLY valid JSON." in prompt
    assert "Do not include markdown code fences" in prompt
    assert '"type": "object"' in prompt
    assert '"ok"' in prompt


@pytest.mark.parametrize(
    ("output_config", "expected"),
    [
        ({}, CITATION_MODE_OFF),
        ({"citation_mode": "custom_sidecar"}, "custom_sidecar"),
    ],
)
def test_citation_mode_for_step_preserves_non_inline_modes(
    output_config: dict[str, object], expected: str
) -> None:
    assert citation_mode_for_step(_step(output_config=output_config)) == expected


@pytest.mark.parametrize(
    ("output_type", "output_mode", "expected"),
    [
        ("text", "pass_through", CITATION_MODE_INLINE_INREF_SIDECAR),
        ("json", "pass_through", CITATION_MODE_OFF),
        ("pdf", "pass_through", CITATION_MODE_OFF),
        ("docx", "pass_through", CITATION_MODE_OFF),
        ("text", "template_fill", CITATION_MODE_OFF),
        ("text", "transcribe_only", CITATION_MODE_OFF),
        ("garbage", "pass_through", CITATION_MODE_OFF),
        ("text", "garbage", CITATION_MODE_INLINE_INREF_SIDECAR),
        ("json", "garbage", CITATION_MODE_OFF),
    ],
)
def test_citation_mode_for_step_delegates_inline_eligibility(
    output_type: str, output_mode: str, expected: str
) -> None:
    step = _step(
        output_type=output_type,
        output_mode=output_mode,
        output_config={"citation_mode": CITATION_MODE_INLINE_INREF_SIDECAR},
    )

    assert citation_mode_for_step(step) == expected


def test_detect_native_json_output_support_uses_litellm_model_name(
    monkeypatch: pytest.MonkeyPatch,
):
    captured: list[str] = []

    def fake_supported_params(*, model: str):
        captured.append(model)
        return ["response_format", "temperature"]

    monkeypatch.setattr(
        "eneo.flows.runtime.step_execution_runtime.get_supported_openai_params",
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
        "eneo.flows.runtime.step_execution_runtime.get_supported_openai_params",
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


def test_detect_native_json_output_support_logs_lookup_failures(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    monkeypatch.setattr(
        "eneo.flows.runtime.step_execution_runtime.get_supported_openai_params",
        MagicMock(side_effect=RuntimeError("lookup failed")),
    )
    assistant = SimpleNamespace(
        completion_model=SimpleNamespace(
            litellm_model_name="openai/gpt-4.1",
            name="gpt-4.1",
            provider_type="openai",
        )
    )

    caplog.set_level(
        logging.WARNING,
        logger="eneo.flows.runtime.step_execution_runtime",
    )
    supported = detect_native_json_output_support(assistant)

    assert supported is None


def test_effective_model_parameters_preserves_default_setting_semantics():
    assistant = SimpleNamespace(
        completion_model_kwargs=SimpleNamespace(
            model_dump=lambda **kwargs: {
                "temperature": None,
                "top_p": None,
                "reasoning_effort": None,
                "verbosity": None,
            }
        ),
        completion_model=SimpleNamespace(
            id=uuid4(),
            name="gpt-5.4-nano",
            provider_type="openai",
            reasoning=True,
        ),
    )

    params = effective_model_parameters(assistant)

    assert params["temperature"] is None
    assert params["reasoning_effort"] is None
    assert params["verbosity"] is None
    assert params["parameter_semantics"]["temperature"]["mode"] == "model_default"
    assert params["parameter_semantics"]["reasoning_effort"]["mode"] == "model_default"
    assert params["parameter_semantics"]["verbosity"]["mode"] == "model_default"


def test_apply_prompt_context_trace_marks_inserted_sources() -> None:
    rag_metadata = {
        "status": "success",
        "tracking": {
            "retrieval_tracked": True,
            "prompt_context_inclusion_tracked": False,
            "citation_tracked": False,
            "material_influence_tracked": False,
        },
        "references": [
            {"id": "source-1", "usage_state": "retrieved_candidate"},
            {"id": "source-2", "usage_state": "retrieved_candidate"},
        ],
    }

    traced = apply_prompt_context_trace(
        rag_metadata,
        knowledge_trace={
            "version": 2,
            "selection_basis": "semantic_search_ranked_chunks_grouped_by_source",
            "raw_source_count": 2,
            "raw_chunk_count": 4,
            "included_source_count": 1,
            "not_included_source_count": 1,
            "included_chunk_count": 2,
            "knowledge_tokens": 128,
            "truncated_by_token_budget": True,
            "included_source_ids": ["source-1"],
            "not_included_source_ids": ["source-2"],
            "included_groups": [
                {
                    "source_id": "source-1",
                    "source_id_short": "source-1",
                    "source_title": "Source One",
                    "start_chunk": 1,
                    "end_chunk": 2,
                    "chunk_count": 2,
                    "relevance_score": 1.0,
                }
            ],
        },
    )

    assert traced is not None
    assert traced["tracking"]["prompt_context_inclusion_tracked"] is True
    assert traced["prompt_context"]["included_source_ids"] == ["source-1"]
    assert traced["prompt_context"]["included_source_titles"] == ["Source One"]
    assert traced["references"][0]["usage_state"] == "inserted_into_prompt"
    assert traced["references"][1]["usage_state"] == "retrieved_candidate"


@pytest.mark.asyncio
async def test_complete_step_execution_falls_back_when_json_mode_rejected(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "eneo.flows.runtime.step_execution_runtime.detect_native_json_output_support",
        lambda assistant: None,
    )
    run = _run()
    state = _state()
    step = _step(output_type="json")
    original_kwargs = ModelKwargs(
        temperature=0.2,
        response_format={"type": "stored_provider_format"},
    )
    assistant = MagicMock()
    assistant.completion_model = SimpleNamespace(
        id=None,
        litellm_model_name="openai/gpt-test",
        name="gpt-test",
        provider_type="openai",
    )
    assistant.completion_model_kwargs = original_kwargs
    assistant.get_response = AsyncMock(
        side_effect=[
            ProviderCapabilityRejectedException(
                "The provider rejected JSON mode.",
                capability="response_format",
                retry_without_capability_safe=True,
                code="provider_capability_rejected",
            ),
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
        input_payload_for_result={
            "text": "hello",
            "source_text": "hello",
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
        retrieve_rag_chunks=AsyncMock(
            return_value=([], {"status": "skipped_no_service"}, [])
        ),
        process_typed_output=AsyncMock(return_value=_typed_output_result({"ok": True})),
        apply_output_cap=AsyncMock(return_value=('{"ok": true}', [])),
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
    assert first_kwargs["model_kwargs"].response_format == {"type": "json_object"}
    assert second_kwargs["model_kwargs"].response_format is None
    assert second_kwargs["model_kwargs"].temperature == 0.2
    assert state.json_mode_supported["openai:gpt-test:none"] is False
    assert output.structured_output == {"ok": True}
    assert output.full_text == '{"ok": true}'


@pytest.mark.asyncio
async def test_complete_step_execution_strips_known_unsupported_stored_response_format(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "eneo.flows.runtime.step_execution_runtime.detect_native_json_output_support",
        lambda assistant: False,
    )
    run = _run()
    state = _state()
    step = _step(output_type="json")
    original_kwargs = ModelKwargs(
        temperature=0.2,
        response_format={"type": "stored_provider_format"},
    )
    assistant = MagicMock()
    assistant.completion_model = SimpleNamespace(
        id=None,
        litellm_model_name="anthropic/claude-test",
        name="claude-test",
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
        input_payload_for_result={
            "text": "hello",
            "source_text": "hello",
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
        retrieve_rag_chunks=AsyncMock(
            return_value=([], {"status": "skipped_no_service"}, [])
        ),
        process_typed_output=AsyncMock(return_value=_typed_output_result({"ok": True})),
        apply_output_cap=AsyncMock(return_value=('{"ok": true}', [])),
    )

    output = await complete_step_execution(
        step=step,
        run=run,
        state=state,
        prepared=prepared,
        deps=deps,
    )

    assistant.get_response.assert_awaited_once()
    sent_kwargs = assistant.get_response.await_args.kwargs["model_kwargs"]
    assert sent_kwargs.response_format is None
    assert sent_kwargs.temperature == 0.2
    assert state.json_mode_supported["anthropic:claude-test:none"] is False
    assert output.structured_output == {"ok": True}


@pytest.mark.asyncio
async def test_completed_provider_call_is_observed_before_postprocessing_failure(
    monkeypatch: pytest.MonkeyPatch,
):
    model_names: list[str | None] = []

    def _count_tokens(text: str, model_name: str | None = None) -> int:
        model_names.append(model_name)
        return 3

    monkeypatch.setattr(
        "eneo.flows.runtime.step_execution_runtime.count_tokens", _count_tokens
    )
    run = _run()
    state = _state()
    step = _step(output_type="text")
    assistant = MagicMock()
    assistant.completion_model = SimpleNamespace(
        id=None,
        litellm_model_name="openai/gpt-test",
        name="gpt-test",
        provider_type="openai",
    )
    assistant.completion_model_kwargs = None
    observer = SimpleNamespace(
        started=AsyncMock(return_value=uuid4()),
        completed=AsyncMock(),
        rejected=AsyncMock(),
        outcome_unknown=AsyncMock(),
    )

    async def _observed_response(**kwargs):
        provider_observer = kwargs["provider_call_observer"]
        call_id = await provider_observer.started(
            ProviderCallRequestFacts(
                request_schema_version=1,
                provider_request_hash="f" * 64,
                requested_model="openai/gpt-test",
                provider="openai",
                response_format="none",
                requested_capabilities=(),
                reason="initial",
            )
        )
        await provider_observer.completed(
            call_id,
            ProviderCallResultFacts(
                response_model="gpt-test",
                provider_response_id="observed-response",
                num_tokens_input=7,
                num_tokens_output=None,
            ),
        )
        return SimpleNamespace(
            total_token_count=5,
            completion="answer",
            usage=SimpleNamespace(prompt_tokens=7, completion_tokens=None),
            model=SimpleNamespace(name="gpt-test", provider_type="openai"),
        )

    assistant.get_response = AsyncMock(side_effect=_observed_response)
    prepared = PreparedStepExecution(
        assistant=assistant,
        step_input=StepInputValue(text="hello", source_text="hello"),
        effective_prompt="Prompt",
        input_payload_for_result={"text": "hello", "source_text": "hello"},
        contract_validation=None,
        diagnostics=[],
        llm_files=[],
    )

    async def _fail_after_receipt(**_kwargs):
        observer.completed.assert_awaited_once()
        raise RuntimeError("postprocessing failed")

    deps = StepExecutionRuntimeDeps(
        variable_resolver=FlowVariableResolver(),
        completion_service=object(),
        load_assistant=AsyncMock(),
        resolve_step_input=AsyncMock(),
        retrieve_rag_chunks=AsyncMock(return_value=([], None, [])),
        process_typed_output=AsyncMock(side_effect=_fail_after_receipt),
        apply_output_cap=AsyncMock(),
        build_provider_call_observer=lambda mapped_call: observer,
        mapped_call_context=MappedProviderCallProvenance(
            execution_mode="per_item",
            item_index=1,
        ),
    )

    with pytest.raises(RuntimeError, match="postprocessing failed"):
        await complete_step_execution(
            step=step,
            run=run,
            state=state,
            prepared=prepared,
            deps=deps,
        )

    result = observer.completed.await_args.args[1]
    assert result.num_tokens_input == 7
    assert result.num_tokens_output is None
    assert observer.started.await_args.args[0].provider_request_hash == "f" * 64
    assert model_names == ["openai/gpt-test"]


@pytest.mark.asyncio
async def test_complete_step_execution_does_not_repeat_non_capability_error_with_response_format(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "eneo.flows.runtime.step_execution_runtime.detect_native_json_output_support",
        lambda assistant: None,
    )
    run = _run()
    state = _state()
    step = _step(output_type="json")
    assistant = MagicMock()
    assistant.completion_model = SimpleNamespace(
        id=None,
        litellm_model_name="openai/gpt-test",
        name="gpt-test",
        provider_type="openai",
    )
    assistant.completion_model_kwargs = MagicMock(name="original_kwargs")
    assistant.get_response = AsyncMock(
        side_effect=RuntimeError(
            "Connection failed after logging request parameters: response_format=json_object"
        )
    )
    prepared = PreparedStepExecution(
        assistant=assistant,
        step_input=StepInputValue(text="hello", source_text="hello"),
        effective_prompt="Prompt",
        input_payload_for_result={"text": "hello", "source_text": "hello"},
        contract_validation=None,
        diagnostics=[],
        llm_files=[],
    )
    deps = StepExecutionRuntimeDeps(
        variable_resolver=FlowVariableResolver(),
        completion_service=object(),
        load_assistant=AsyncMock(),
        resolve_step_input=AsyncMock(),
        retrieve_rag_chunks=AsyncMock(return_value=([], None, [])),
        process_typed_output=AsyncMock(),
        apply_output_cap=AsyncMock(),
    )

    with pytest.raises(RuntimeError, match="response_format=json_object"):
        await complete_step_execution(
            step=step,
            run=run,
            state=state,
            prepared=prepared,
            deps=deps,
        )

    assert assistant.get_response.await_count == 1


@pytest.mark.asyncio
async def test_complete_step_execution_does_not_repeat_late_json_mode_rejection(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "eneo.flows.runtime.step_execution_runtime.detect_native_json_output_support",
        lambda assistant: None,
    )
    run = _run()
    state = _state()
    step = _step(output_type="json")
    assistant = MagicMock()
    assistant.completion_model = SimpleNamespace(
        id=None,
        litellm_model_name="openai/gpt-test",
        name="gpt-test",
        provider_type="openai",
    )
    assistant.completion_model_kwargs = MagicMock(name="original_kwargs")
    assistant.get_response = AsyncMock(
        side_effect=ProviderCapabilityRejectedException(
            "The provider rejected JSON mode after earlier provider work.",
            capability="response_format",
            retry_without_capability_safe=False,
            code="provider_capability_rejected",
        )
    )
    prepared = PreparedStepExecution(
        assistant=assistant,
        step_input=StepInputValue(text="hello", source_text="hello"),
        effective_prompt="Prompt",
        input_payload_for_result={"text": "hello", "source_text": "hello"},
        contract_validation=None,
        diagnostics=[],
        llm_files=[],
    )
    deps = StepExecutionRuntimeDeps(
        variable_resolver=FlowVariableResolver(),
        completion_service=object(),
        load_assistant=AsyncMock(),
        resolve_step_input=AsyncMock(),
        retrieve_rag_chunks=AsyncMock(return_value=([], None, [])),
        process_typed_output=AsyncMock(),
        apply_output_cap=AsyncMock(),
    )

    with pytest.raises(ProviderCapabilityRejectedException):
        await complete_step_execution(
            step=step,
            run=run,
            state=state,
            prepared=prepared,
            deps=deps,
        )

    assert assistant.get_response.await_count == 1


@pytest.mark.asyncio
async def test_complete_step_execution_translates_context_window_failure():
    run = _run()
    state = _state()
    step = _step(output_type="text")
    assistant = MagicMock()
    assistant.completion_model_kwargs = MagicMock(name="model_kwargs")
    assistant.get_response = AsyncMock(
        side_effect=ContextWindowExceededError(
            estimated_tokens=42000,
            max_tokens=32000,
        )
    )
    prepared = PreparedStepExecution(
        assistant=assistant,
        step_input=StepInputValue(
            text="large source",
            source_text="large source",
            input_source="flow_input",
            runtime_input_metadata={"files": [{"name": "large-source.pdf"}]},
        ),
        effective_prompt="Prompt",
        input_payload_for_result={
            "text": "large source",
            "source_text": "large source",
            "input_source": "flow_input",
            "runtime_input": {"files": [{"name": "large-source.pdf"}]},
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
        retrieve_rag_chunks=AsyncMock(
            return_value=([], {"status": "skipped_no_service"}, [])
        ),
        process_typed_output=AsyncMock(return_value=_typed_output_result()),
        apply_output_cap=AsyncMock(return_value=("unused", [])),
    )

    with pytest.raises(TypedIOValidationException) as exc_info:
        await complete_step_execution(
            step=step,
            run=run,
            state=state,
            prepared=prepared,
            deps=deps,
        )

    assert (
        exc_info.value.code
        == FlowApiErrorCode.TYPED_IO_INPUT_EXCEEDS_MODEL_WINDOW.value
    )
    assert "large-source.pdf" in str(exc_info.value)
    assert "42000" in str(exc_info.value)
    assert "32000" in str(exc_info.value)
    assert getattr(exc_info.value, "effective_prompt") == "Prompt"
    assert getattr(exc_info.value, "input_payload_json")["runtime_input"] == {
        "files": [{"name": "large-source.pdf"}]
    }
    assert assistant.get_response.await_args.kwargs["reject_context_over_limit"] is True


@pytest.mark.asyncio
async def test_complete_step_execution_shares_deadline_across_json_mode_retry(
    monkeypatch: pytest.MonkeyPatch,
):
    """The json-mode fallback retry must share the step deadline.

    Without a shared deadline, a step that already burned most of its
    budget on the first call gets a fresh per-call timeout for the
    fallback retry, doubling the wall-clock budget for one step. The
    shared deadline keeps a step bounded by the configured timeout
    regardless of how the json-mode retry path branches.
    """
    monkeypatch.setattr(
        "eneo.flows.runtime.step_execution_runtime.detect_native_json_output_support",
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

    counter = {"n": 0}

    async def fake_get_response(**_kwargs: object):
        counter["n"] += 1
        if counter["n"] == 1:
            await asyncio.sleep(0.25)
            raise ProviderCapabilityRejectedException(
                "The provider rejected JSON mode.",
                capability="response_format",
                retry_without_capability_safe=True,
                code="provider_capability_rejected",
            )
        await asyncio.sleep(0.2)
        return SimpleNamespace(total_token_count=4, completion='{"ok": true}')

    assistant.get_response = AsyncMock(side_effect=fake_get_response)
    prepared = PreparedStepExecution(
        assistant=assistant,
        step_input=StepInputValue(
            text="hello",
            source_text="hello",
            input_source="flow_input",
        ),
        effective_prompt="Prompt",
        input_payload_for_result={
            "text": "hello",
            "source_text": "hello",
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
        retrieve_rag_chunks=AsyncMock(
            return_value=([], {"status": "skipped_no_service"}, [])
        ),
        process_typed_output=AsyncMock(return_value=_typed_output_result({"ok": True})),
        apply_output_cap=AsyncMock(return_value=('{"ok": true}', [])),
        llm_request_timeout_seconds=0.3,
    )

    with pytest.raises(TypedIOValidationException) as exc_info:
        await complete_step_execution(
            step=step,
            run=run,
            state=state,
            prepared=prepared,
            deps=deps,
        )

    assert exc_info.value.code == "flow_llm_request_timeout"
    assert assistant.get_response.await_count == 2


@pytest.mark.asyncio
async def test_complete_step_execution_fast_fails_when_deadline_already_exhausted(
    monkeypatch: pytest.MonkeyPatch,
):
    """Json-mode retry must not dispatch when the deadline is already
    spent.

    If the first call burns the entire step budget before raising a
    json-mode rejection, the retry hits `call_assistant_with_timeout`
    with `timeout <= 0`. Dispatching to `assistant.get_response` in
    that state would either block on a still-pending HTTP call or get
    cancelled with an ambiguous TimeoutError. Raise the typed
    `flow_llm_request_timeout` directly so the executor's failure
    handler treats this exactly like the original timeout.
    """
    monkeypatch.setattr(
        "eneo.flows.runtime.step_execution_runtime.detect_native_json_output_support",
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

    async def fake_get_response(**_kwargs: object):
        # Burn the entire step budget on the first call, then reject
        # so the json-mode fallback path runs with timeout=0.
        await asyncio.sleep(0.15)
        raise RuntimeError("response_format json_object unsupported")

    assistant.get_response = AsyncMock(side_effect=fake_get_response)
    prepared = PreparedStepExecution(
        assistant=assistant,
        step_input=StepInputValue(
            text="hello",
            source_text="hello",
            input_source="flow_input",
        ),
        effective_prompt="Prompt",
        input_payload_for_result={
            "text": "hello",
            "source_text": "hello",
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
        retrieve_rag_chunks=AsyncMock(
            return_value=([], {"status": "skipped_no_service"}, [])
        ),
        process_typed_output=AsyncMock(return_value=_typed_output_result({"ok": True})),
        apply_output_cap=AsyncMock(return_value=('{"ok": true}', [])),
        llm_request_timeout_seconds=0.1,
    )

    with pytest.raises(TypedIOValidationException) as exc_info:
        await complete_step_execution(
            step=step,
            run=run,
            state=state,
            prepared=prepared,
            deps=deps,
        )

    assert exc_info.value.code == "flow_llm_request_timeout"
    assert assistant.get_response.await_count == 1, (
        "Retry must not dispatch a second LLM call when the deadline "
        "is already exhausted; doing so blocks on HTTP that the budget "
        "no longer covers."
    )


@pytest.mark.asyncio
async def test_complete_step_execution_times_out_llm_request():
    run = _run()
    state = _state()
    step = _step(output_type="text")

    async def slow_response(**_kwargs: object) -> object:
        await asyncio.sleep(0.05)
        return SimpleNamespace(total_token_count=4, completion="too late")

    assistant = MagicMock()
    assistant.completion_model_kwargs = MagicMock(name="model_kwargs")
    assistant.get_response = AsyncMock(side_effect=slow_response)
    prepared = PreparedStepExecution(
        assistant=assistant,
        step_input=StepInputValue(
            text="hello",
            source_text="hello",
            input_source="all_previous_steps",
        ),
        effective_prompt="Prompt",
        input_payload_for_result={
            "text": "hello",
            "source_text": "hello",
            "input_source": "all_previous_steps",
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
        retrieve_rag_chunks=AsyncMock(
            return_value=([], {"status": "skipped_no_service"}, [])
        ),
        process_typed_output=AsyncMock(return_value=_typed_output_result()),
        apply_output_cap=AsyncMock(return_value=("too late", [])),
        llm_request_timeout_seconds=0.001,
    )

    with pytest.raises(TypedIOValidationException) as exc_info:
        await complete_step_execution(
            step=step,
            run=run,
            state=state,
            prepared=prepared,
            deps=deps,
        )

    assert exc_info.value.code == "flow_llm_request_timeout"
    assert getattr(exc_info.value, "effective_prompt") == "Prompt"
    failed_input_payload = getattr(exc_info.value, "input_payload_json")
    assert failed_input_payload["input_source"] == "all_previous_steps"


@pytest.mark.asyncio
async def test_complete_step_execution_cancels_llm_request_when_run_is_cancelled():
    run = _run()
    state = _state()
    step = _step(output_type="text")
    cancelled = asyncio.Event()

    async def blocked_response(**_kwargs: object) -> object:
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return SimpleNamespace(total_token_count=4, completion="too late")

    assistant = MagicMock()
    assistant.completion_model_kwargs = MagicMock(name="model_kwargs")
    assistant.get_response = AsyncMock(side_effect=blocked_response)
    prepared = PreparedStepExecution(
        assistant=assistant,
        step_input=StepInputValue(
            text="hello",
            source_text="hello",
            input_source="flow_input",
        ),
        effective_prompt="Prompt",
        input_payload_for_result={
            "text": "hello",
            "source_text": "hello",
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
        retrieve_rag_chunks=AsyncMock(
            return_value=([], {"status": "skipped_no_service"}, [])
        ),
        process_typed_output=AsyncMock(return_value=_typed_output_result()),
        apply_output_cap=AsyncMock(return_value=("too late", [])),
        llm_request_timeout_seconds=10,
        run_cancelled=AsyncMock(return_value=True),
        run_cancel_poll_interval_seconds=0.001,
    )

    with pytest.raises(FlowStepCancelledError):
        await complete_step_execution(
            step=step,
            run=run,
            state=state,
            prepared=prepared,
            deps=deps,
        )

    assert cancelled.is_set()
    assert state.in_flight_llm_task is None


@pytest.mark.asyncio
async def test_complete_step_execution_returns_when_cancelled_llm_suppresses_cancel():
    run = _run()
    state = _state()
    step = _step(output_type="text")
    cancelled = asyncio.Event()
    release = asyncio.Event()

    async def blocked_response(**_kwargs: object) -> object:
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            cancelled.set()
            await release.wait()
        return SimpleNamespace(total_token_count=4, completion="too late")

    assistant = MagicMock()
    assistant.completion_model_kwargs = MagicMock(name="model_kwargs")
    assistant.get_response = AsyncMock(side_effect=blocked_response)
    prepared = PreparedStepExecution(
        assistant=assistant,
        step_input=StepInputValue(
            text="hello",
            source_text="hello",
            input_source="flow_input",
        ),
        effective_prompt="Prompt",
        input_payload_for_result={
            "text": "hello",
            "source_text": "hello",
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
        retrieve_rag_chunks=AsyncMock(
            return_value=([], {"status": "skipped_no_service"}, [])
        ),
        process_typed_output=AsyncMock(return_value=_typed_output_result()),
        apply_output_cap=AsyncMock(return_value=("too late", [])),
        llm_request_timeout_seconds=10,
        run_cancelled=AsyncMock(return_value=True),
        run_cancel_poll_interval_seconds=0.001,
        llm_task_cancellation_grace_seconds=0.001,
    )

    with pytest.raises(FlowStepCancelledError):
        await complete_step_execution(
            step=step,
            run=run,
            state=state,
            prepared=prepared,
            deps=deps,
        )

    assert cancelled.is_set()
    assert state.in_flight_llm_task is None
    release.set()
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_complete_step_execution_logs_json_mode_kwargs_failures(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    monkeypatch.setattr(
        "eneo.flows.runtime.step_execution_runtime.detect_native_json_output_support",
        lambda assistant: None,
    )
    run = _run()
    state = _state()
    step = _step(output_type="json")
    original_kwargs = MagicMock(name="original_kwargs")
    assistant = MagicMock()
    assistant.completion_model = SimpleNamespace(
        id=None,
        litellm_model_name="openai/gpt-4.1",
        name="gpt-4.1",
        provider_type="openai",
    )
    assistant.completion_model_kwargs = original_kwargs
    assistant.completion_model_kwargs.model_copy.side_effect = RuntimeError(
        "bad kwargs"
    )
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
        input_payload_for_result={
            "text": "hello",
            "source_text": "hello",
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
        retrieve_rag_chunks=AsyncMock(
            return_value=([], {"status": "skipped_no_service"}, [])
        ),
        process_typed_output=AsyncMock(return_value=_typed_output_result({"ok": True})),
        apply_output_cap=AsyncMock(return_value=('{"ok": true}', [])),
    )

    caplog.set_level(
        logging.WARNING,
        logger="eneo.flows.runtime.step_execution_runtime",
    )
    output = await complete_step_execution(
        step=step,
        run=run,
        state=state,
        prepared=prepared,
        deps=deps,
    )

    assert assistant.get_response.await_count == 1
    assert assistant.get_response.await_args.kwargs["model_kwargs"] is original_kwargs
    assert state.json_mode_supported["openai:gpt-4.1:none"] is False
    assert output.structured_output == {"ok": True}
    assert "Failed to enable native JSON mode for flow step execution." in caplog.text


@pytest.mark.asyncio
async def test_complete_step_execution_skips_native_json_mode_when_capability_is_known_unsupported(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "eneo.flows.runtime.step_execution_runtime.detect_native_json_output_support",
        lambda assistant: False,
    )
    run = _run()
    state = _state()
    step = _step(output_type="json")
    original_kwargs = ModelKwargs()
    assistant = MagicMock()
    assistant.completion_model = SimpleNamespace(
        id=None,
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
        input_payload_for_result={
            "text": "hello",
            "source_text": "hello",
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
        retrieve_rag_chunks=AsyncMock(
            return_value=([], {"status": "skipped_no_service"}, [])
        ),
        process_typed_output=AsyncMock(return_value=_typed_output_result({"ok": True})),
        apply_output_cap=AsyncMock(return_value=('{"ok": true}', [])),
    )

    output = await complete_step_execution(
        step=step,
        run=run,
        state=state,
        prepared=prepared,
        deps=deps,
    )

    assert assistant.get_response.await_count == 1
    assert assistant.get_response.await_args.kwargs["model_kwargs"] is original_kwargs
    assert state.json_mode_supported["anthropic:claude-3-5-haiku:none"] is False
    assert output.structured_output == {"ok": True}


@pytest.mark.asyncio
async def test_complete_step_execution_does_not_force_json_object_for_array_document_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _unexpected_json_mode_detection(assistant_obj: object) -> bool | None:
        raise AssertionError("array schemas must not request json_object mode")

    monkeypatch.setattr(
        "eneo.flows.runtime.step_execution_runtime.detect_native_json_output_support",
        _unexpected_json_mode_detection,
    )
    run = _run()
    state = _state()
    step = _step(
        output_type="docx",
        output_contract={
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"title": {"type": "string"}},
            },
        },
    )
    original_kwargs = MagicMock(name="original_kwargs")
    assistant = MagicMock()
    assistant.completion_model_kwargs = original_kwargs
    assistant.get_response = AsyncMock(
        return_value=SimpleNamespace(
            total_token_count=4,
            completion='[{"title":"A"}]',
        )
    )
    prepared = PreparedStepExecution(
        assistant=assistant,
        step_input=StepInputValue(
            text="hello",
            source_text="hello",
            input_source="flow_input",
        ),
        effective_prompt="Prompt",
        input_payload_for_result={
            "text": "hello",
            "source_text": "hello",
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
        retrieve_rag_chunks=AsyncMock(
            return_value=([], {"status": "skipped_no_service"}, [])
        ),
        process_typed_output=AsyncMock(
            return_value=_typed_output_result([{"title": "A"}])
        ),
        apply_output_cap=AsyncMock(return_value=('[{"title":"A"}]', [])),
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
    assert state.json_mode_supported == {}
    assert output.structured_output == [{"title": "A"}]


@pytest.mark.asyncio
async def test_complete_step_execution_prefers_provider_reported_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token_counter = MagicMock(
        side_effect=AssertionError("provider usage must bypass token estimation")
    )
    monkeypatch.setattr(
        "eneo.flows.runtime.step_execution_runtime.count_tokens",
        token_counter,
    )
    run = _run()
    state = _state()
    step = _step(output_type="text")
    assistant = MagicMock()
    assistant.completion_model_kwargs = MagicMock(name="model_kwargs")
    assistant.get_response = AsyncMock(
        return_value=SimpleNamespace(
            total_token_count=4,
            usage=TokenUsage(prompt_tokens=123, completion_tokens=456),
            completion=Completion(text="Svar", reasoning_token_count=99),
            model=SimpleNamespace(name="gpt-5.4-nano", provider_type="openai"),
            knowledge_trace=None,
        )
    )
    prepared = PreparedStepExecution(
        assistant=assistant,
        step_input=StepInputValue(
            text="hello",
            source_text="hello",
            input_source="flow_input",
        ),
        effective_prompt="Prompt",
        input_payload_for_result={
            "text": "hello",
            "source_text": "hello",
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
        retrieve_rag_chunks=AsyncMock(
            return_value=([], {"status": "skipped_no_service"}, [])
        ),
        process_typed_output=AsyncMock(return_value=_typed_output_result()),
        apply_output_cap=AsyncMock(return_value=("Svar", [])),
    )

    output = await complete_step_execution(
        step=step,
        run=run,
        state=state,
        prepared=prepared,
        deps=deps,
    )

    assert output.num_tokens_input == 123
    assert output.num_tokens_output == 456
    token_counter.assert_not_called()


@pytest.mark.asyncio
async def test_complete_step_execution_falls_back_to_estimated_usage_when_provider_usage_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _count_tokens(_text: str, _model_name: str | None = None) -> int:
        return 19

    monkeypatch.setattr(
        "eneo.flows.runtime.step_execution_runtime.count_tokens",
        _count_tokens,
    )
    run = _run()
    state = _state()
    step = _step(output_type="text")
    assistant = MagicMock()
    assistant.completion_model_kwargs = MagicMock(name="model_kwargs")
    assistant.get_response = AsyncMock(
        return_value=SimpleNamespace(
            total_token_count=41,
            completion=Completion(text="Svar", reasoning_token_count=7),
            model=SimpleNamespace(name="gpt-5.4-nano", provider_type="openai"),
            knowledge_trace=None,
        )
    )
    prepared = PreparedStepExecution(
        assistant=assistant,
        step_input=StepInputValue(
            text="hello",
            source_text="hello",
            input_source="flow_input",
        ),
        effective_prompt="Prompt",
        input_payload_for_result={
            "text": "hello",
            "source_text": "hello",
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
        retrieve_rag_chunks=AsyncMock(
            return_value=([], {"status": "skipped_no_service"}, [])
        ),
        process_typed_output=AsyncMock(return_value=_typed_output_result()),
        apply_output_cap=AsyncMock(return_value=("Svar", [])),
    )

    output = await complete_step_execution(
        step=step,
        run=run,
        state=state,
        prepared=prepared,
        deps=deps,
    )

    assert output.num_tokens_input == 41
    assert output.num_tokens_output == 26


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("usage", "expected_input_tokens", "expected_output_tokens"),
    [
        (TokenUsage(prompt_tokens=None, completion_tokens=222), 31, 222),
        (TokenUsage(prompt_tokens=111, completion_tokens=None), 111, 26),
    ],
)
async def test_complete_step_execution_falls_back_per_usage_field(
    monkeypatch: pytest.MonkeyPatch,
    usage: TokenUsage,
    expected_input_tokens: int,
    expected_output_tokens: int,
) -> None:
    def _count_tokens(_text: str, _model_name: str | None = None) -> int:
        return 26

    monkeypatch.setattr(
        "eneo.flows.runtime.step_execution_runtime.count_tokens",
        _count_tokens,
    )
    run = _run()
    state = _state()
    step = _step(output_type="text")
    assistant = MagicMock()
    assistant.completion_model_kwargs = MagicMock(name="model_kwargs")
    assistant.get_response = AsyncMock(
        return_value=SimpleNamespace(
            total_token_count=31,
            usage=usage,
            completion="Svar",
            model=SimpleNamespace(name="gpt-5.4-nano", provider_type="openai"),
            knowledge_trace=None,
        )
    )
    prepared = PreparedStepExecution(
        assistant=assistant,
        step_input=StepInputValue(
            text="hello",
            source_text="hello",
            input_source="flow_input",
        ),
        effective_prompt="Prompt",
        input_payload_for_result={
            "text": "hello",
            "source_text": "hello",
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
        retrieve_rag_chunks=AsyncMock(
            return_value=([], {"status": "skipped_no_service"}, [])
        ),
        process_typed_output=AsyncMock(return_value=_typed_output_result()),
        apply_output_cap=AsyncMock(return_value=("Svar", [])),
    )

    output = await complete_step_execution(
        step=step,
        run=run,
        state=state,
        prepared=prepared,
        deps=deps,
    )

    assert output.num_tokens_input == expected_input_tokens
    assert output.num_tokens_output == expected_output_tokens


@pytest.mark.asyncio
async def test_complete_step_execution_uses_version_2_and_strips_inline_refs_for_citation_mode() -> (
    None
):
    run = _run()
    state = _state()
    step = _step(
        output_type="text",
        output_config={"citation_mode": "inline_inref_sidecar"},
    )
    assistant = MagicMock()
    assistant.completion_model_kwargs = MagicMock(name="model_kwargs")
    assistant.get_response = AsyncMock(
        return_value=SimpleNamespace(
            total_token_count=4,
            completion='Svar med kallor <inref id="11111111"/><inref id="22222222"/>',
            model=SimpleNamespace(name="gpt-5.4-nano", provider_type="openai"),
            knowledge_trace=None,
        )
    )
    prepared = PreparedStepExecution(
        assistant=assistant,
        step_input=StepInputValue(
            text="hello",
            source_text="hello",
            input_source="flow_input",
        ),
        effective_prompt="Prompt",
        input_payload_for_result={
            "text": "hello",
            "source_text": "hello",
            "input_source": "flow_input",
        },
        contract_validation=None,
        diagnostics=[],
        llm_files=[],
    )
    rag_metadata = {
        "status": "success",
        "tracking": {
            "retrieval_tracked": True,
            "prompt_context_inclusion_tracked": True,
            "citation_tracked": False,
            "material_influence_tracked": False,
        },
        "prompt_context": {
            "tracked": True,
            "included_source_ids": [
                "11111111-1111-1111-1111-111111111111",
                "22222222-2222-2222-2222-222222222222",
            ],
        },
        "references": [
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "id_short": "11111111",
            },
            {
                "id": "22222222-2222-2222-2222-222222222222",
                "id_short": "22222222",
            },
        ],
    }
    deps = StepExecutionRuntimeDeps(
        variable_resolver=FlowVariableResolver(),
        completion_service=object(),
        load_assistant=AsyncMock(),
        resolve_step_input=AsyncMock(),
        retrieve_rag_chunks=AsyncMock(return_value=([], rag_metadata, [])),
        process_typed_output=AsyncMock(return_value=_typed_output_result()),
        apply_output_cap=AsyncMock(return_value=("Svar med kallor", [])),
    )

    output = await complete_step_execution(
        step=step,
        run=run,
        state=state,
        prepared=prepared,
        deps=deps,
    )

    assert assistant.get_response.await_args.kwargs["version"] == 2
    assert deps.apply_output_cap.await_args.kwargs["text"] == "Svar med kallor"
    assert output.full_text == "Svar med kallor"
    assert output.persisted_text == "Svar med kallor"
    assert output.citation_sidecar is not None
    assert output.citation_sidecar["citation_expected"] is True
    assert output.citation_sidecar["citation_observed"] is True
    assert output.citation_sidecar["citation_compliance"] == "observed"
    assert output.citation_sidecar["cited_source_ids"] == [
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
    ]
    assert output.raw_completion_text is not None
    assert output.raw_completion_text.endswith('<inref id="22222222"/>')


@pytest.mark.asyncio
async def test_complete_step_execution_records_missing_citations_without_failing_step() -> (
    None
):
    run = _run()
    state = _state()
    step = _step(
        output_type="text",
        output_config={"citation_mode": "inline_inref_sidecar"},
    )
    assistant = MagicMock()
    assistant.completion_model_kwargs = MagicMock(name="model_kwargs")
    assistant.get_response = AsyncMock(
        return_value=SimpleNamespace(
            total_token_count=4,
            completion="Svar utan kallor",
            model=SimpleNamespace(name="gpt-5.4-nano", provider_type="openai"),
            knowledge_trace=None,
        )
    )
    prepared = PreparedStepExecution(
        assistant=assistant,
        step_input=StepInputValue(
            text="hello",
            source_text="hello",
            input_source="flow_input",
        ),
        effective_prompt="Prompt",
        input_payload_for_result={
            "text": "hello",
            "source_text": "hello",
            "input_source": "flow_input",
        },
        contract_validation=None,
        diagnostics=[],
        llm_files=[],
    )
    rag_metadata = {
        "status": "success",
        "tracking": {
            "retrieval_tracked": True,
            "prompt_context_inclusion_tracked": True,
            "citation_tracked": False,
            "material_influence_tracked": False,
        },
        "prompt_context": {
            "tracked": True,
            "included_source_ids": ["11111111-1111-1111-1111-111111111111"],
        },
        "references": [
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "id_short": "11111111",
            }
        ],
    }
    deps = StepExecutionRuntimeDeps(
        variable_resolver=FlowVariableResolver(),
        completion_service=object(),
        load_assistant=AsyncMock(),
        resolve_step_input=AsyncMock(),
        retrieve_rag_chunks=AsyncMock(return_value=([], rag_metadata, [])),
        process_typed_output=AsyncMock(return_value=_typed_output_result()),
        apply_output_cap=AsyncMock(return_value=("Svar utan kallor", [])),
    )

    output = await complete_step_execution(
        step=step,
        run=run,
        state=state,
        prepared=prepared,
        deps=deps,
    )

    assert output.full_text == "Svar utan kallor"
    assert output.citation_sidecar is not None
    assert output.citation_sidecar["citation_expected"] is True
    assert output.citation_sidecar["citation_observed"] is False
    assert output.citation_sidecar["citation_compliance"] == (
        "missing_required_citations"
    )


@pytest.mark.asyncio
async def test_complete_step_execution_does_not_expect_citations_when_no_knowledge_was_inserted() -> (
    None
):
    run = _run()
    state = _state()
    step = _step(
        output_type="text",
        output_config={"citation_mode": "inline_inref_sidecar"},
    )
    assistant = MagicMock()
    assistant.completion_model_kwargs = MagicMock(name="model_kwargs")
    assistant.get_response = AsyncMock(
        return_value=SimpleNamespace(
            total_token_count=4,
            completion="Svar utan kallor",
            model=SimpleNamespace(name="gpt-5.4-nano", provider_type="openai"),
            knowledge_trace=None,
        )
    )
    prepared = PreparedStepExecution(
        assistant=assistant,
        step_input=StepInputValue(
            text="hello",
            source_text="hello",
            input_source="flow_input",
        ),
        effective_prompt="Prompt",
        input_payload_for_result={
            "text": "hello",
            "source_text": "hello",
            "input_source": "flow_input",
        },
        contract_validation=None,
        diagnostics=[],
        llm_files=[],
    )
    rag_metadata = {
        "status": "success",
        "tracking": {
            "retrieval_tracked": True,
            "prompt_context_inclusion_tracked": True,
            "citation_tracked": False,
            "material_influence_tracked": False,
        },
        "prompt_context": {
            "tracked": True,
            "included_source_ids": [],
        },
        "references": [],
    }
    deps = StepExecutionRuntimeDeps(
        variable_resolver=FlowVariableResolver(),
        completion_service=object(),
        load_assistant=AsyncMock(),
        resolve_step_input=AsyncMock(),
        retrieve_rag_chunks=AsyncMock(return_value=([], rag_metadata, [])),
        process_typed_output=AsyncMock(return_value=_typed_output_result()),
        apply_output_cap=AsyncMock(return_value=("Svar utan kallor", [])),
    )

    output = await complete_step_execution(
        step=step,
        run=run,
        state=state,
        prepared=prepared,
        deps=deps,
    )

    assert output.citation_sidecar is not None
    assert output.citation_sidecar["citation_mode_requested"] is True
    assert output.citation_sidecar["citation_applicable"] is False
    assert output.citation_sidecar["citation_context_kind"] == "none"
    assert output.citation_sidecar["citation_expected"] is False
    assert output.citation_sidecar["citation_compliance"] == "not_requested"


@pytest.mark.asyncio
async def test_complete_step_execution_tracks_inherited_citations_for_synthesis_steps() -> (
    None
):
    run = _run()
    source_id = "11111111-1111-1111-1111-111111111111"
    source_title = "Sociologi och sociala institutioner"
    prior_result = FlowStepResult(
        id=uuid4(),
        flow_run_id=run.id,
        flow_id=run.flow_id,
        tenant_id=run.tenant_id,
        step_id=uuid4(),
        step_order=2,
        assistant_id=uuid4(),
        input_payload_json={
            "rag": {
                "status": "success",
                "tracking": {
                    "retrieval_tracked": True,
                    "prompt_context_inclusion_tracked": True,
                    "citation_tracked": False,
                    "material_influence_tracked": False,
                },
                "prompt_context": {
                    "tracked": True,
                    "included_source_ids": [source_id],
                    "included_source_titles": [source_title],
                    "included_groups": [
                        {
                            "source_id": source_id,
                            "source_id_short": "11111111",
                            "source_title": source_title,
                            "chunk_count": 1,
                        }
                    ],
                },
                "references": [
                    {
                        "id": source_id,
                        "id_short": "11111111",
                        "title": source_title,
                        "source_url": "https://example.org/sociologi",
                    }
                ],
            }
        },
        effective_prompt=None,
        output_payload_json={"text": "Grounded step output"},
        model_parameters_json=None,
        num_tokens_input=None,
        num_tokens_output=None,
        status=FlowStepResultStatus.COMPLETED,
        flow_step_execution_hash=None,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )
    state = RunExecutionState(
        completed_by_order={2: prior_result},
        prior_results=[prior_result],
        assistant_cache={},
        json_mode_supported={},
        file_cache={},
        step_names_by_order={2: "Grounded summary"},
        step_ref_mapping={},
    )
    step = _step(
        step_order=3,
        output_type="text",
        output_config={"citation_mode": "inline_inref_sidecar"},
        input_bindings={"question": "{{step_2.output.text}}"},
    )
    assistant = MagicMock()
    assistant.completion_model_kwargs = MagicMock(name="model_kwargs")
    assistant.get_response = AsyncMock(
        return_value=SimpleNamespace(
            total_token_count=4,
            completion='Slutrapport<inref id="11111111"/>',
            model=SimpleNamespace(name="gpt-5.4-nano", provider_type="openai"),
            knowledge_trace=None,
        )
    )
    prepared = PreparedStepExecution(
        assistant=assistant,
        step_input=StepInputValue(
            text="Grounded step output",
            source_text="Grounded step output",
            input_source="flow_input",
            used_question_binding=True,
        ),
        effective_prompt="Skriv slutrapport",
        input_payload_for_result={
            "text": "Grounded step output",
            "source_text": "Grounded step output",
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
        retrieve_rag_chunks=AsyncMock(return_value=([], None, [])),
        process_typed_output=AsyncMock(return_value=_typed_output_result()),
        apply_output_cap=AsyncMock(return_value=("Slutrapport", [])),
    )

    output = await complete_step_execution(
        step=step,
        run=run,
        state=state,
        prepared=prepared,
        deps=deps,
    )

    assert assistant.get_response.await_args.kwargs["version"] == 2
    assert (
        "Inherited source catalog"
        in assistant.get_response.await_args.kwargs["prompt_override"]
    )
    assert output.full_text == "Slutrapport"
    assert output.persisted_text == "Slutrapport"
    assert output.citation_sidecar is not None
    assert output.citation_sidecar["citation_mode_requested"] is True
    assert output.citation_sidecar["citation_applicable"] is True
    assert output.citation_sidecar["citation_context_kind"] == "inherited"
    assert output.citation_sidecar["citation_expected"] is True
    assert output.citation_sidecar["cited_source_ids"] == [source_id]
    assert output.citation_sidecar["direct_cited_source_ids"] == []
    assert output.citation_sidecar["inherited_cited_source_ids"] == [source_id]
    assert output.citation_sidecar["inherited_available_source_ids"] == [source_id]
    assert output.citation_sidecar["upstream_grounded_step_orders"] == [2]


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


def test_build_output_payload_excludes_artifact_display_keys():
    payload = build_output_payload(
        StepExecutionOutput(
            input_text="hello",
            source_text="hello",
            input_source="flow_input",
            used_question_binding=False,
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
        "structured": {"ok": True},
    }


def test_build_output_payload_preserves_raw_text_for_pruned_structured_output():
    payload = build_output_payload(
        StepExecutionOutput(
            input_text="hello",
            source_text="hello",
            input_source="flow_input",
            used_question_binding=False,
            full_text='{"beslutslista":[{"rubrik_kommentar":"extra"}]}',
            persisted_text='{"beslutslista":[{"rubrik_kommentar":"extra"}]}',
            generated_file_ids=[],
            tool_calls_metadata=None,
            num_tokens_input=1,
            num_tokens_output=1,
            effective_prompt="prompt",
            model_parameters_json={},
            structured_output={"beslutslista": [{"rubrik": "Budget"}]},
            diagnostics=[
                StepDiagnostic(
                    code="typed_output_extra_properties_dropped",
                    message="Dropped 1 undeclared field: /beslutslista/0/rubrik_kommentar",
                    severity="warning",
                )
            ],
        )
    )

    assert payload["text"] == '{"beslutslista":[{"rubrik_kommentar":"extra"}]}'
    assert payload["structured"] == {"beslutslista": [{"rubrik": "Budget"}]}


def test_build_step_result_file_references_classifies_declared_artifacts():
    generated_file_id = uuid4()
    declared_file_id = uuid4()

    references = build_step_result_file_references(
        generated_file_ids=[generated_file_id, declared_file_id],
        artifacts=[{"file_id": str(declared_file_id), "name": "out.pdf"}],
    )

    assert {item.file_id: item.source for item in references} == {
        generated_file_id: "generated_output",
        declared_file_id: "declared_artifact",
    }


def test_build_output_payload_merges_output_payload_extensions():
    payload = build_output_payload(
        StepExecutionOutput(
            input_text="hello",
            source_text="hello",
            input_source="flow_input",
            used_question_binding=False,
            full_text="raw docx text",
            persisted_text="## summary\n\nclean text",
            generated_file_ids=[],
            tool_calls_metadata=None,
            num_tokens_input=0,
            num_tokens_output=0,
            effective_prompt="",
            model_parameters_json={"mode": "template_fill"},
            output_payload_extensions={
                "template_fill_debug": {
                    "rendered_docx_text_raw": "raw docx text",
                    "summary_mode": "resolved_bindings",
                }
            },
        )
    )

    assert payload["text"] == "## summary\n\nclean text"
    assert payload["template_fill_debug"] == {
        "rendered_docx_text_raw": "raw docx text",
        "summary_mode": "resolved_bindings",
    }


def test_json_mode_cache_key_uses_provider_name_and_id():
    assistant = SimpleNamespace(
        completion_model=SimpleNamespace(
            id=uuid4(), name="gpt-4.1", provider_type="openai"
        )
    )

    cache_key = json_mode_cache_key(assistant)

    assert cache_key.startswith("openai:gpt-4.1:")


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
        completion_model=SimpleNamespace(
            id=uuid4(), name="gpt-4.1", provider_type="openai"
        ),
    )

    params = effective_model_parameters(assistant)

    assert params["model_name"] == "gpt-4.1"
    assert params["provider"] == "openai"
    assert params["temperature"] == 0.2
