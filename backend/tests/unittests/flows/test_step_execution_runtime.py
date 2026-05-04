from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from intric.ai_models.completion_models.completion_model import Completion, TokenUsage
from intric.flows.flow import (
    FlowRun,
    FlowRunStatus,
    FlowStepResult,
    FlowStepResultStatus,
)
from intric.flows.flow_run_step_result_file import build_step_result_file_references
from intric.flows.runtime.models import (
    RunExecutionState,
    RuntimeStep,
    StepExecutionOutput,
    StepInputValue,
)
from intric.flows.runtime.step_execution_runtime import (
    PreparedStepExecution,
    StepExecutionRuntimeDeps,
    apply_prompt_context_trace,
    attach_typed_failure_context,
    augment_prompt_for_typed_output,
    build_output_payload,
    complete_step_execution,
    detect_native_json_output_support,
    effective_model_parameters,
    execution_hash,
    is_json_mode_rejection,
    json_mode_cache_key,
    prepare_step_execution,
)
from intric.flows.variable_resolver import FlowVariableResolver
from intric.main.exceptions import TypedIOValidationException


def _run() -> FlowRun:
    now = datetime.now(timezone.utc)
    return FlowRun(
        id=uuid4(),
        flow_id=uuid4(),
        flow_version=1,
        user_id=uuid4(),
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
    assert (
        prepared.contract_validation
        == prepared.input_payload_for_result["contract_validation"]
    )
    assert prepared.llm_files == []


def test_augment_prompt_for_json_output_appends_schema_instructions():
    prompt = augment_prompt_for_typed_output(
        output_type="json",
        output_contract={"type": "object", "properties": {"ok": {"type": "boolean"}}},
        prompt="Analyze the text",
    )

    assert prompt.startswith("Analyze the text")
    assert "Return ONLY valid JSON." in prompt
    assert "Do not include markdown code fences" in prompt
    assert '"type": "object"' in prompt
    assert '"ok"' in prompt


def test_detect_native_json_output_support_uses_litellm_model_name(
    monkeypatch: pytest.MonkeyPatch,
):
    captured: list[str] = []

    def fake_supported_params(*, model: str):
        captured.append(model)
        return ["response_format", "temperature"]

    monkeypatch.setattr(
        "intric.flows.runtime.step_execution_runtime.get_supported_openai_params",
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
        "intric.flows.runtime.step_execution_runtime.get_supported_openai_params",
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
        "intric.flows.runtime.step_execution_runtime.get_supported_openai_params",
        MagicMock(side_effect=RuntimeError("lookup failed")),
    )
    assistant = SimpleNamespace(
        completion_model=SimpleNamespace(
            litellm_model_name="openai/gpt-4.1",
            name="gpt-4.1",
            provider_type="openai",
        )
    )

    caplog.set_level(logging.WARNING)
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

    counter = {"n": 0}

    async def fake_get_response(**_kwargs: object):
        counter["n"] += 1
        if counter["n"] == 1:
            await asyncio.sleep(0.25)
            raise RuntimeError("response_format json_object unsupported")
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
        process_typed_output=AsyncMock(return_value=({"ok": True}, None)),
        apply_output_cap=AsyncMock(return_value=('{"ok": true}', [])),
        attach_typed_failure_context=attach_typed_failure_context,
        effective_model_parameters=lambda assistant_obj: {"temperature": 0.2},
        json_mode_cache_key=lambda assistant_obj: "provider:model:1",
        is_json_mode_rejection=lambda exc: "response_format" in str(exc),
        count_tokens=lambda text: len(text),
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
        process_typed_output=AsyncMock(return_value=({"ok": True}, None)),
        apply_output_cap=AsyncMock(return_value=('{"ok": true}', [])),
        attach_typed_failure_context=attach_typed_failure_context,
        effective_model_parameters=lambda assistant_obj: {"temperature": 0.2},
        json_mode_cache_key=lambda assistant_obj: "provider:model:1",
        is_json_mode_rejection=lambda exc: "response_format" in str(exc),
        count_tokens=lambda text: len(text),
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
        process_typed_output=AsyncMock(return_value=(None, None)),
        apply_output_cap=AsyncMock(return_value=("too late", [])),
        attach_typed_failure_context=attach_typed_failure_context,
        effective_model_parameters=lambda assistant_obj: {"temperature": 0.2},
        json_mode_cache_key=lambda assistant_obj: "provider:model:1",
        is_json_mode_rejection=lambda exc: False,
        count_tokens=lambda text: len(text),
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
async def test_complete_step_execution_logs_json_mode_kwargs_failures(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    monkeypatch.setattr(
        "intric.flows.runtime.step_execution_runtime.detect_native_json_output_support",
        lambda assistant: None,
    )
    run = _run()
    state = _state()
    step = _step(output_type="json")
    original_kwargs = MagicMock(name="original_kwargs")
    assistant = MagicMock()
    assistant.completion_model = SimpleNamespace(
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
        process_typed_output=AsyncMock(return_value=({"ok": True}, None)),
        apply_output_cap=AsyncMock(return_value=('{"ok": true}', [])),
        attach_typed_failure_context=lambda exc, **kwargs: exc,
        effective_model_parameters=lambda assistant_obj: {"temperature": 0.2},
        json_mode_cache_key=lambda assistant_obj: "provider:model:1",
        is_json_mode_rejection=lambda exc: "response_format" in str(exc),
        count_tokens=lambda text: len(text),
    )

    caplog.set_level(logging.WARNING)
    output = await complete_step_execution(
        step=step,
        run=run,
        state=state,
        prepared=prepared,
        deps=deps,
    )

    assert assistant.get_response.await_count == 1
    assert assistant.get_response.await_args.kwargs["model_kwargs"] is original_kwargs
    assert state.json_mode_supported["provider:model:1"] is False
    assert output.structured_output == {"ok": True}
    assert "Failed to enable native JSON mode for flow step execution." in caplog.text


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
async def test_complete_step_execution_does_not_force_json_object_for_array_document_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _unexpected_json_mode_detection(assistant_obj: object) -> bool | None:
        raise AssertionError("array schemas must not request json_object mode")

    monkeypatch.setattr(
        "intric.flows.runtime.step_execution_runtime.detect_native_json_output_support",
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
        process_typed_output=AsyncMock(return_value=([{"title": "A"}], None)),
        apply_output_cap=AsyncMock(return_value=('[{"title":"A"}]', [])),
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

    assert assistant.completion_model_kwargs.model_copy.call_count == 0
    assert assistant.get_response.await_count == 1
    assert assistant.get_response.await_args.kwargs["model_kwargs"] is original_kwargs
    assert state.json_mode_supported == {}
    assert output.structured_output == [{"title": "A"}]


@pytest.mark.asyncio
async def test_complete_step_execution_prefers_provider_reported_usage() -> None:
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
        process_typed_output=AsyncMock(return_value=(None, None)),
        apply_output_cap=AsyncMock(return_value=("Svar", [])),
        attach_typed_failure_context=lambda exc, **kwargs: exc,
        effective_model_parameters=lambda assistant_obj: {"temperature": 0.2},
        json_mode_cache_key=lambda assistant_obj: "provider:model:1",
        is_json_mode_rejection=lambda exc: "response_format" in str(exc),
        count_tokens=lambda text: len(text) * 10,
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


@pytest.mark.asyncio
async def test_complete_step_execution_falls_back_to_estimated_usage_when_provider_usage_missing() -> (
    None
):
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
        process_typed_output=AsyncMock(return_value=(None, None)),
        apply_output_cap=AsyncMock(return_value=("Svar", [])),
        attach_typed_failure_context=lambda exc, **kwargs: exc,
        effective_model_parameters=lambda assistant_obj: {"temperature": 0.2},
        json_mode_cache_key=lambda assistant_obj: "provider:model:1",
        is_json_mode_rejection=lambda exc: "response_format" in str(exc),
        count_tokens=lambda text: 19,
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
    usage: TokenUsage,
    expected_input_tokens: int,
    expected_output_tokens: int,
) -> None:
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
        process_typed_output=AsyncMock(return_value=(None, None)),
        apply_output_cap=AsyncMock(return_value=("Svar", [])),
        attach_typed_failure_context=lambda exc, **kwargs: exc,
        effective_model_parameters=lambda assistant_obj: {"temperature": 0.2},
        json_mode_cache_key=lambda assistant_obj: "provider:model:1",
        is_json_mode_rejection=lambda exc: "response_format" in str(exc),
        count_tokens=lambda text: 26,
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
    assert output.num_tokens_input == 0
    assert output.num_tokens_output == 0


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
        process_typed_output=AsyncMock(return_value=(None, None)),
        apply_output_cap=AsyncMock(return_value=("Svar med kallor", [])),
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
        process_typed_output=AsyncMock(return_value=(None, None)),
        apply_output_cap=AsyncMock(return_value=("Svar utan kallor", [])),
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
        process_typed_output=AsyncMock(return_value=(None, None)),
        apply_output_cap=AsyncMock(return_value=("Svar utan kallor", [])),
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
        error_message=None,
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
        process_typed_output=AsyncMock(return_value=(None, None)),
        apply_output_cap=AsyncMock(return_value=("Slutrapport", [])),
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


def test_build_output_payload_excludes_artifact_display_keys():
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
        "webhook_delivered": False,
        "structured": {"ok": True},
    }


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
            legacy_prompt_binding_used=False,
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


def test_is_json_mode_rejection_matches_supported_error_phrases():
    assert (
        is_json_mode_rejection(RuntimeError("response_format is unsupported")) is True
    )
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
        completion_model=SimpleNamespace(
            id=uuid4(), name="gpt-4.1", provider_type="openai"
        ),
    )

    params = effective_model_parameters(assistant)

    assert params["model_name"] == "gpt-4.1"
    assert params["provider"] == "openai"
    assert params["temperature"] == 0.2
