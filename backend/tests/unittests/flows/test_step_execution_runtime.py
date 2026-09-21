from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx
import pytest

from eneo.ai_models.completion_models.completion_model import (
    Completion,
    CompletionModel,
    Context,
    ModelKwargs,
    ResponseType,
    TokenUsage,
)
from eneo.authentication.principal_types import PrincipalType
from eneo.completion_models.domain.model_kwargs_capabilities import (
    ModelKwargCapability,
    SupportedModelKwargs,
)
from eneo.completion_models.infrastructure.adapters.base_adapter import ProviderInput
from eneo.completion_models.infrastructure.adapters.tenant_model_adapter import (
    TenantModelAdapter,
)
from eneo.completion_models.infrastructure.completion_service import CompletionService
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
from eneo.flows.domain.step_output import StepOutputValidationException
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_run_provenance import (
    FlowResolvedInputFlowInputSource,
    FlowResolvedInputJsonPath,
    MappedProviderCallProvenance,
    build_resolved_input_edge,
)
from eneo.flows.flow_run_step_result_file import build_step_result_file_references
from eneo.flows.runtime.output_formats import resolve_format_spec
from eneo.flows.runtime.output_formats.base import append_output_format_instructions
from eneo.flows.runtime.output_runtime import TypedOutputProcessingResult
from eneo.flows.runtime.step_attempt_runtime import build_typed_failure_plan
from eneo.flows.runtime.step_execution_runtime import (
    FlowStepCancelledError,
    PreparedStepExecution,
    StepExecutionRuntimeDeps,
    apply_prompt_context_trace,
    attach_typed_failure_context,
    build_output_payload,
    build_prepared_completion_call,
    citation_mode_for_step,
    complete_step_execution,
    detect_native_json_output_support,
    effective_completion_prompt,
    effective_model_parameters,
    execution_hash,
    json_mode_cache_key,
    prepare_step_execution,
    preview_step_execution_context,
)
from eneo.flows.runtime.step_result_builder import build_completed_step_result
from eneo.flows.variable_resolver import FlowVariableResolver
from eneo.main.exceptions import (
    ProviderCapabilityRejectedException,
    TypedIOValidationException,
)
from eneo.model_providers.domain.provider_call_observer import (
    CompletionCallRequestFacts,
    CompletionCallResultFacts,
)
from eneo.tokens.token_utils import measure_provider_input_reserve


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


def _completion_model(
    *, supported_model_kwargs: SupportedModelKwargs
) -> CompletionModel:
    now = datetime.now(timezone.utc)
    return CompletionModel(
        id=uuid4(),
        created_at=now,
        updated_at=now,
        name="gpt-test",
        nickname="gpt-test",
        family="openai",
        max_input_tokens=8_000,
        max_output_tokens=4_000,
        is_deprecated=False,
        stability="stable",
        hosting="eu",
        vision=False,
        reasoning=False,
        supports_tool_calling=True,
        is_org_enabled=True,
        is_org_default=False,
        tenant_id=uuid4(),
        provider_id=uuid4(),
        provider_type="openai",
        model_kwargs_capabilities=supported_model_kwargs,
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
async def test_preview_preflights_both_dispatch_prompts_without_retrieval():
    from eneo.completion_models.domain.model_capacity import ModelCapacity
    from eneo.completion_models.domain.request_preflight import (
        DEFAULT_USEFUL_OUTPUT_RESERVE_TOKENS,
        CompletionRequestPackage,
        CompletionRequestPreflight,
    )
    from eneo.tokens.token_utils import TokenCount, TokenCountSource

    schema = {
        "type": "object",
        "properties": {"answer": {"type": "string", "description": "answer " * 600}},
    }
    assistant = MagicMock()
    assistant.mcp_servers = []
    assistant.get_prompt_text.return_value = "Explain."
    assistant.completion_model = _completion_model(
        supported_model_kwargs=SupportedModelKwargs()
    )
    assistant.completion_model.litellm_model_name = "openai/gpt-4o-mini"
    assistant.completion_model_kwargs = ModelKwargs()
    package = CompletionRequestPackage(
        messages=[],
        tools=[],
        response_format=None,
        input_reserve=TokenCount(tokens=444, source=TokenCountSource.LITELLM),
        useful_output_reserve_tokens=256,
        output_cap_tokens=4000,
    )
    evidence = CompletionRequestPreflight(
        model_route="openai/gpt-4o-mini",
        capacity=ModelCapacity(8000, 4000),
        retrieval_included=False,
        preferred=package,
        fallback=package,
    )
    assistant.preflight_response_context = AsyncMock(return_value=evidence)
    prepared = PreparedStepExecution(
        assistant=assistant,
        step_input=StepInputValue(text="Source"),
        effective_prompt=_prompt_for_output_format(
            output_type="json", output_contract=schema, prompt="Explain."
        ),
        input_payload_for_result={},
        contract_validation=None,
        diagnostics=[],
        llm_files=[],
    )
    deps = SimpleNamespace(completion_service=object(), retrieve_rag_chunks=AsyncMock())
    step = _step(output_type="json", output_contract=schema)
    state = _state()
    expected = build_prepared_completion_call(step=step, state=state, prepared=prepared)

    tokens = await preview_step_execution_context(
        step=step, state=state, prepared=prepared, deps=deps
    )

    assert tokens == 444
    passed = assistant.preflight_response_context.await_args.kwargs
    assert passed["prompt_override"] == expected.effective_prompt
    assert passed["capability_fallback_prompt"] == expected.capability_fallback_prompt
    assert passed["model_kwargs"] == expected.preferred_model_kwargs
    assert passed.get("info_blob_chunks") is None
    assert (
        passed["useful_output_reserve_tokens"] == DEFAULT_USEFUL_OUTPUT_RESERVE_TOKENS
    )
    assert evidence.retrieval_included is False
    deps.retrieve_rag_chunks.assert_not_awaited()


@pytest.fixture
def preflight_dispatch(monkeypatch):
    from eneo.assistants.assistant import Assistant
    from eneo.completion_models.infrastructure.context_builder import ContextBuilder

    model = _completion_model(supported_model_kwargs=SupportedModelKwargs())
    model.name = "gpt-4o-mini"
    model.litellm_model_name = "openai/gpt-4o-mini"
    adapter = object.__new__(TenantModelAdapter)
    adapter.model = model
    adapter.provider_type = "openai"
    adapter.litellm_model = model.litellm_model_name
    adapter.credential_resolver = SimpleNamespace(
        provider_type="openai",
        get_api_key=lambda **kwargs: "test-key",
        get_credential_field=lambda **kwargs: None,
    )
    service = CompletionService(context_builder=ContextBuilder())
    service._get_adapter = AsyncMock(return_value=adapter)
    assistant = Assistant(
        id=None,
        user=MagicMock(),
        name="preflight",
        space_id=uuid4(),
        prompt=None,
        completion_model=model,
        completion_model_kwargs=ModelKwargs(),
        logging_enabled=False,
        websites=[],
        collections=[],
        attachments=[],
        published=False,
    )
    schema = {
        "type": "object",
        "properties": {"answer": {"type": "boolean"}},
        "required": ["answer"],
        "additionalProperties": False,
    }
    step = _step(output_type="json", output_contract=schema)
    prepared = PreparedStepExecution(
        assistant=assistant,
        step_input=StepInputValue(text="Source"),
        effective_prompt=_prompt_for_output_format(
            output_type="json", output_contract=schema, prompt="Explain."
        ),
        input_payload_for_result={},
        contract_validation=None,
        diagnostics=[],
        llm_files=[],
    )
    deps = StepExecutionRuntimeDeps(
        max_inline_text_bytes=1_000_000,
        variable_resolver=FlowVariableResolver(),
        completion_service=service,
        load_assistant=AsyncMock(),
        resolve_step_input=AsyncMock(),
        retrieve_rag_chunks=AsyncMock(return_value=([], None, [])),
        process_typed_output=AsyncMock(return_value=_typed_output_result()),
        apply_output_cap=AsyncMock(return_value=('{"answer":true}', [])),
    )
    transport = AsyncMock(
        return_value=SimpleNamespace(
            id="preflight",
            usage=None,
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content='{"answer":true}', tool_calls=None),
                    finish_reason="stop",
                )
            ],
        )
    )
    monkeypatch.setattr(
        "eneo.completion_models.infrastructure.adapters.tenant_model_adapter._acompletion_call",
        transport,
    )
    return SimpleNamespace(
        model=model,
        adapter=adapter,
        service=service,
        assistant=assistant,
        prepared=prepared,
        deps=deps,
        step=step,
        state=_state(),
        transport=transport,
    )


@pytest.mark.asyncio
async def test_preview_selected_fallback_is_the_package_dispatched(
    preflight_dispatch, monkeypatch
):
    from eneo.tokens.token_utils import TokenCount, TokenCountSource

    h = preflight_dispatch
    h.model.max_input_tokens = 351
    h.model.max_output_tokens = 512

    def measure(messages, tools, route, *, response_format=None):
        return TokenCount(
            tokens=96 if response_format else 83, source=TokenCountSource.LITELLM
        )

    monkeypatch.setattr(
        "eneo.completion_models.infrastructure.adapters.tenant_model_adapter.measure_provider_input_reserve",
        measure,
    )
    await preview_step_execution_context(
        step=h.step, state=h.state, prepared=h.prepared, deps=h.deps
    )
    await complete_step_execution(
        step=h.step, run=_run(), state=h.state, prepared=h.prepared, deps=h.deps
    )

    h.transport.assert_awaited_once()
    sent = h.transport.await_args.kwargs
    assert sent.get("response_format") is None
    assert sent["max_tokens"] == 268
    selected = h.prepared.completion_call.selected_package
    assert json.dumps(sent["messages"]) == json.dumps(selected.messages)


@pytest.mark.asyncio
@pytest.mark.parametrize("cached_rejection", [False, True])
async def test_preview_reuses_measured_fallback_after_capability_rejection(
    preflight_dispatch, cached_rejection
):
    h = preflight_dispatch
    await preview_step_execution_context(
        step=h.step, state=h.state, prepared=h.prepared, deps=h.deps
    )
    fallback = h.prepared.completion_call.preflight.fallback
    if cached_rejection:
        h.state.json_mode_supported[json_mode_cache_key(h.assistant)] = False
    else:
        h.transport.side_effect = [
            ProviderCapabilityRejectedException(
                "Response format unsupported",
                capability="response_format",
                retry_without_capability_safe=True,
                code="provider_capability_rejected",
            ),
            h.transport.return_value,
        ]
    await complete_step_execution(
        step=h.step, run=_run(), state=h.state, prepared=h.prepared, deps=h.deps
    )
    sent = h.transport.await_args.kwargs
    assert sent.get("response_format") is None
    assert json.dumps(sent["messages"]) == json.dumps(fallback.messages)


@pytest.mark.asyncio
@pytest.mark.parametrize("elapsed", [3590, 3601])
@pytest.mark.parametrize("capability_retry", [False, True])
async def test_dispatch_refreshes_expiring_references_and_remeasures(
    preflight_dispatch, monkeypatch, elapsed, capability_retry
):
    from dataclasses import replace

    from eneo.authentication.signed_urls import (
        parse_file_reference_url,
        verify_file_original_download_token,
    )
    from eneo.files.file_models import File, FileType
    from eneo.flows.runtime.step_deadline import StepDeadline

    h = preflight_dispatch
    clock = {"wall": 2_000_000_000, "elapsed": 0}
    monkeypatch.setattr("time.time", lambda: clock["wall"])
    monkeypatch.setattr(
        "eneo.flows.runtime.step_deadline._now", lambda: clock["elapsed"]
    )
    monkeypatch.setattr(
        "eneo.files.file_reference.file_reference_base_url",
        lambda: "https://files.example",
    )
    h.service.config = h.service.config.model_copy(
        update={
            "file_reference_base_url": "https://files.example",
            "file_reference_url_expiry_seconds": 3600,
        }
    )
    h.service.tenant = SimpleNamespace(id=uuid4())
    h.service._build_file_reference_urls = MagicMock(
        wraps=h.service._build_file_reference_urls
    )
    h.deps = replace(h.deps, deadline=StepDeadline.start(7200))
    now = datetime.now(timezone.utc)
    file = File(
        id=uuid4(),
        created_at=now,
        updated_at=now,
        name="source.txt",
        checksum="test",
        size=20,
        file_type=FileType.TEXT,
        text="Attachment marker.",
        owner_type=PrincipalType.USER,
        tenant_id=h.service.tenant.id,
        original_available=True,
    )
    h.prepared.llm_files = [file]
    measured = []

    def measure(messages, tools, route, *, response_format=None):
        measured.append((clock["elapsed"], json.dumps(messages)))
        return measure_provider_input_reserve(
            messages, tools, route, response_format=response_format
        )

    monkeypatch.setattr(
        "eneo.completion_models.infrastructure.adapters.tenant_model_adapter.measure_provider_input_reserve",
        measure,
    )
    await preview_step_execution_context(
        step=h.step, state=h.state, prepared=h.prepared, deps=h.deps
    )
    original = h.prepared.completion_call.preflight.file_reference_urls[file.id]

    def advance():
        clock["wall"] += elapsed
        clock["elapsed"] += elapsed

    if capability_retry:

        async def respond(**kwargs):
            if h.transport.await_count == 1:
                advance()
                raise ProviderCapabilityRejectedException(
                    "Response format unsupported",
                    capability="response_format",
                    retry_without_capability_safe=True,
                    code="provider_capability_rejected",
                )
            return h.transport.return_value

        h.transport.side_effect = respond
    else:
        advance()
    await complete_step_execution(
        step=h.step, run=_run(), state=h.state, prepared=h.prepared, deps=h.deps
    )

    assert h.deps.deadline.remaining() == 7200 - elapsed
    fresh = h.prepared.completion_call.preflight.file_reference_urls[file.id]
    assert fresh != original
    parsed = parse_file_reference_url(fresh)
    assert parsed is not None
    claims = verify_file_original_download_token(parsed[1], expected_file_id=file.id)
    assert claims is not None
    assert claims["expires_at"] == clock["wall"] + 3600
    assert (
        h.prepared.completion_call.preflight.file_reference_urls_expires_at
        == claims["expires_at"]
    )
    sent = h.transport.await_args.kwargs
    assert fresh in json.dumps(sent["messages"])
    assert original not in json.dumps(sent["messages"])
    package = h.prepared.completion_call.selected_package
    assert json.dumps(sent["messages"]) == json.dumps(package.messages)
    assert sent["max_tokens"] == package.output_cap_tokens
    assert (elapsed, json.dumps(package.messages)) in measured
    assert h.service._build_file_reference_urls.call_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("retrieved", [False, True])
async def test_preview_reuses_signed_file_references_at_dispatch(
    preflight_dispatch, retrieved
):
    from eneo.authentication.signed_urls import build_signed_original_download_url
    from eneo.files.file_models import File, FileType
    from eneo.info_blobs.info_blob import InfoBlobChunkInDBWithScore

    h = preflight_dispatch
    now = datetime.now(timezone.utc)
    file = File(
        id=uuid4(),
        created_at=now,
        updated_at=now,
        name="source.txt",
        checksum="test",
        size=20,
        file_type=FileType.TEXT,
        text="Attachment marker.",
        owner_type=PrincipalType.USER,
        tenant_id=uuid4(),
    )
    h.prepared.llm_files = [file]
    original = build_signed_original_download_url(
        file_id=file.id,
        base_url="https://files.example",
        expires_in=3600,
        tenant_id=file.tenant_id,
    )
    changed = build_signed_original_download_url(
        file_id=file.id,
        base_url="https://files.example",
        expires_in=3599,
        tenant_id=file.tenant_id,
    )
    h.service._build_file_reference_urls = MagicMock(
        side_effect=[{file.id: original}, {file.id: changed}]
    )
    await preview_step_execution_context(
        step=h.step, state=h.state, prepared=h.prepared, deps=h.deps
    )
    if retrieved:
        h.deps.retrieve_rag_chunks.return_value = (
            [
                InfoBlobChunkInDBWithScore(
                    id=uuid4(),
                    created_at=now,
                    updated_at=now,
                    text="Late retrieval marker.",
                    chunk_no=0,
                    info_blob_id=uuid4(),
                    tenant_id=uuid4(),
                    info_blob_title="Retrieved source",
                    score=0.9,
                )
            ],
            None,
            [],
        )
    await complete_step_execution(
        step=h.step, run=_run(), state=h.state, prepared=h.prepared, deps=h.deps
    )

    h.service._build_file_reference_urls.assert_called_once()
    sent = h.transport.await_args.kwargs
    assert original in json.dumps(sent["messages"])
    if retrieved:
        assert "Late retrieval marker." in json.dumps(sent["messages"])
        assert h.prepared.completion_call.preflight.retrieval_included is False
    else:
        assert json.dumps(sent["messages"]) == json.dumps(
            h.prepared.completion_call.selected_package.messages
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("preview", [False, True])
@pytest.mark.parametrize("capacity", [398, 399])
async def test_flow_explicit_output_reserve_reaches_dispatch(
    preflight_dispatch, monkeypatch, preview, capacity
):
    from eneo.tokens.token_utils import TokenCount, TokenCountSource

    h = preflight_dispatch
    h.model.max_input_tokens = 399
    monkeypatch.setattr(
        "eneo.completion_models.infrastructure.adapters.tenant_model_adapter.measure_provider_input_reserve",
        lambda *args, **kwargs: TokenCount(tokens=100, source=TokenCountSource.LITELLM),
    )
    h.prepared.completion_call = build_prepared_completion_call(
        step=h.step,
        state=h.state,
        prepared=h.prepared,
        useful_output_reserve_tokens=299,
    )
    if preview:
        await preview_step_execution_context(
            step=h.step, state=h.state, prepared=h.prepared, deps=h.deps
        )
    h.model.max_input_tokens = capacity
    if capacity == 399:
        await complete_step_execution(
            step=h.step, run=_run(), state=h.state, prepared=h.prepared, deps=h.deps
        )
        assert h.transport.await_args.kwargs["max_tokens"] == 299
    else:
        with pytest.raises(TypedIOValidationException) as exc:
            await complete_step_execution(
                step=h.step, run=_run(), state=h.state, prepared=h.prepared, deps=h.deps
            )
        assert exc.value.code == "typed_io_input_exceeds_model_window"
        h.transport.assert_not_awaited()


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
    assistant.get_prompt_text.return_value = ""
    assistant.get_prompt_text.return_value = "Review {{flow_input.text}}"
    step_input = StepInputValue(
        text='{"title":"A"}',
        source_text='{"title":"A"}',
        input_source="flow_input",
    )
    deps = StepExecutionRuntimeDeps(
        max_inline_text_bytes=1_000_000,
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
    assistant.get_prompt_text.return_value = ""
    assistant.get_prompt_text.return_value = "Review {{flow_input.missing}}"
    assistant.get_response = AsyncMock()
    deps = StepExecutionRuntimeDeps(
        max_inline_text_bytes=1_000_000,
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
    assistant.get_prompt_text.return_value = ""
    assistant.get_prompt_text.return_value = "Skapa slutresultatet."
    assistant.get_response = AsyncMock()
    step_input = StepInputValue(
        text="Slutrapport: Saknar underlag\n\nTranskribering: mötesinnehåll",
        source_text='{"final_report":"Saknar underlag"}',
        input_source="previous_step",
        used_question_binding=True,
    )
    deps = StepExecutionRuntimeDeps(
        max_inline_text_bytes=1_000_000,
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
    assistant.get_prompt_text.return_value = ""
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
    assistant.get_prompt_text.return_value = ""
    assistant.get_prompt_text.return_value = "Skapa slutresultatet."
    step_input = StepInputValue(
        text='{"final_report":"Rapport från underlag"}',
        source_text='{"final_report":"Gammal rapport"}',
        structured={"final_report": "Rapport från underlag"},
        input_source="previous_step",
        used_question_binding=True,
    )
    deps = StepExecutionRuntimeDeps(
        max_inline_text_bytes=1_000_000,
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


@pytest.mark.parametrize(
    ("provider", "model"),
    [
        ("hosted_vllm", "locally-hosted-model"),
        ("vllm", "locally-hosted-model"),
        ("openai", "gpt-4.1"),
    ],
)
@pytest.mark.parametrize("array_root", [False, True])
def test_prepared_json_call_includes_nested_output_schema(
    provider, model, array_root, monkeypatch
):
    monkeypatch.setattr(
        "eneo.completion_models.infrastructure.tenant_model_capabilities.supports_response_schema",
        lambda **kwargs: True,
    )
    monkeypatch.setattr(
        "eneo.flows.runtime.step_execution_runtime.detect_native_json_output_support",
        lambda assistant: True,
    )
    schema = {
        "type": "object",
        "required": ["section"],
        "additionalProperties": False,
        "properties": {
            "section": {
                "type": "object",
                "required": ["heading", "facts"],
                "additionalProperties": False,
                "properties": {
                    "heading": {"type": "string"},
                    "facts": {"type": "array", "items": {"type": "string"}},
                },
            }
        },
    }
    if array_root:
        schema = {"type": "array", "items": schema}
    original_schema = json.dumps(schema, sort_keys=True)
    assistant = MagicMock()
    assistant.completion_model = SimpleNamespace(
        id=None,
        name=model,
        provider_type=provider,
        litellm_model_name=f"{provider}/{model}",
        supported_model_kwargs=SupportedModelKwargs(),
    )
    assistant.completion_model_kwargs = ModelKwargs()
    prepared = PreparedStepExecution(
        assistant=assistant,
        step_input=StepInputValue(
            text="Source", source_text="Source", input_source="flow_input"
        ),
        effective_prompt=_prompt_for_output_format(
            output_type="json", output_contract=schema, prompt="Extract the facts"
        ),
        input_payload_for_result={"text": "Source"},
        contract_validation=None,
        diagnostics=[],
        llm_files=[],
    )

    call = build_prepared_completion_call(
        step=_step(output_type="json", output_contract=schema),
        state=_state(),
        prepared=prepared,
    )

    response_format = call.preferred_model_kwargs.response_format
    if array_root and provider == "openai":
        assert response_format is None
        assert call.effective_prompt == prepared.effective_prompt
        return
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["schema"] == schema
    assert json.dumps(schema, sort_keys=True) == original_schema
    assert call.preferred_model_parameters["response_format"] == response_format
    assert original_schema not in call.effective_prompt
    assert call.effective_prompt.startswith("Extract the facts")
    assert "Return ONLY valid JSON" in call.effective_prompt
    assert call.capability_fallback_prompt == prepared.effective_prompt


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
@pytest.mark.parametrize("with_schema", [False, True])
async def test_complete_step_execution_falls_back_when_json_mode_rejected(
    monkeypatch: pytest.MonkeyPatch,
    with_schema: bool,
):
    monkeypatch.setattr(
        "eneo.flows.runtime.step_execution_runtime.detect_native_json_output_support",
        lambda assistant: None,
    )
    run = _run()
    state = _state()
    schema = (
        {"type": "object", "properties": {"ok": {"type": "boolean"}}}
        if with_schema
        else None
    )
    step = _step(output_type="json", output_contract=schema)
    original_kwargs = ModelKwargs(
        temperature=0.2,
        top_p=0.8,
        response_format={"type": "stored_provider_format"},
    )
    assistant = MagicMock()
    assistant.get_prompt_text.return_value = ""
    assistant.completion_model = SimpleNamespace(
        id=None,
        litellm_model_name="openai/gpt-4.1",
        name="gpt-4.1",
        provider_type="openai",
        supported_model_kwargs=SupportedModelKwargs(
            temperature=ModelKwargCapability(supported=True)
        ),
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
        effective_prompt=_prompt_for_output_format(
            output_type="json", output_contract=schema, prompt="Prompt"
        ),
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
        max_inline_text_bytes=1_000_000,
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

    prepared.completion_call = build_prepared_completion_call(
        step=step,
        state=state,
        prepared=prepared,
    )
    assert prepared.completion_call.preferred_model_parameters["response_format"][
        "type"
    ] == ("json_schema" if with_schema else "json_object")
    if with_schema:
        assert (
            "Follow this JSON Schema" not in prepared.completion_call.effective_prompt
        )
        assert (
            "Follow this JSON Schema"
            in prepared.completion_call.capability_fallback_prompt
        )
    assert prepared.completion_call.preferred_model_parameters["temperature"] == 0.2
    assert prepared.completion_call.preferred_model_parameters["top_p"] is None
    assert prepared.completion_call.capability_fallback_model_parameters is not None
    assert (
        prepared.completion_call.capability_fallback_model_parameters["response_format"]
        is None
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
    assert first_kwargs["model_kwargs"].response_format["type"] == (
        "json_schema" if with_schema else "json_object"
    )
    assert first_kwargs["prompt_override"] == prepared.completion_call.effective_prompt
    assert second_kwargs["prompt_override"] == prepared.effective_prompt
    assert output.effective_prompt == prepared.effective_prompt
    assert first_kwargs["model_kwargs"].top_p is None
    assert second_kwargs["model_kwargs"].response_format is None
    assert second_kwargs["model_kwargs"].temperature == 0.2
    assert second_kwargs["model_kwargs"].top_p is None
    if with_schema:
        assert state.json_mode_supported.get("openai:gpt-4.1:none") is not False
        assert "openai:gpt-4.1:none" in state.json_schema_rejected_models
    else:
        assert state.json_mode_supported["openai:gpt-4.1:none"] is False
    assert output.structured_output == {"ok": True}
    assert output.full_text == '{"ok": true}'
    assert (
        output.model_parameters_json
        == prepared.completion_call.capability_fallback_model_parameters
    )

    if with_schema:
        next_step = _step(step_order=2, output_type="json", output_contract=schema)
        prepared.completion_call = build_prepared_completion_call(
            step=next_step, state=state, prepared=prepared
        )
        assistant.get_response.side_effect = None
        assistant.get_response.return_value = SimpleNamespace(
            total_token_count=4, completion='{"ok": true}'
        )
        await complete_step_execution(
            step=next_step, run=run, state=state, prepared=prepared, deps=deps
        )
        assert assistant.get_response.await_count == 3
        assert assistant.get_response.await_args.kwargs[
            "model_kwargs"
        ].response_format == {"type": "json_object"}
        assert (
            assistant.get_response.await_args.kwargs["prompt_override"]
            == prepared.effective_prompt
        )


@pytest.mark.asyncio
async def test_prepared_model_parameters_equal_completion_adapter_kwargs() -> None:
    supported_model_kwargs = SupportedModelKwargs(
        temperature=ModelKwargCapability(supported=True)
    )
    completion_model = _completion_model(supported_model_kwargs=supported_model_kwargs)
    assistant = MagicMock()
    assistant.get_prompt_text.return_value = ""
    assistant.completion_model = completion_model
    assistant.completion_model_kwargs = ModelKwargs(temperature=0.2, top_p=0.8)
    prepared = PreparedStepExecution(
        assistant=assistant,
        step_input=StepInputValue(
            text="hello",
            source_text="hello",
            input_source="flow_input",
        ),
        effective_prompt="Prompt",
        input_payload_for_result={"text": "hello"},
        contract_validation=None,
        diagnostics=[],
        llm_files=[],
    )
    completion_call = build_prepared_completion_call(
        step=_step(output_type="text"),
        state=_state(),
        prepared=prepared,
    )

    context_builder = MagicMock()
    context_builder.build_context.return_value = Context(input="hello", token_count=1)
    adapter = MagicMock()
    adapter.get_token_limit_of_model.return_value = 8_000
    adapter.get_model_route.return_value = "openai/gpt-test"
    adapter.get_response = AsyncMock(
        return_value=Completion(response_type=ResponseType.TEXT, text="ok")
    )
    completion_service = CompletionService(
        context_builder=context_builder,
        tenant=SimpleNamespace(id=uuid4()),
        session=AsyncMock(),
    )
    completion_service._get_adapter = AsyncMock(return_value=adapter)

    await completion_service.get_response(
        model=completion_model,
        text_input=completion_call.question,
        model_kwargs=completion_call.preferred_model_kwargs,
        prompt=completion_call.effective_prompt,
    )

    adapter_model_kwargs = adapter.get_response.await_args.kwargs["model_kwargs"]
    assert adapter_model_kwargs.model_dump(exclude_none=True) == {"temperature": 0.2}
    assert (
        effective_model_parameters(assistant, model_kwargs=adapter_model_kwargs)
        == completion_call.preferred_model_parameters
    )


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
    assistant.get_prompt_text.return_value = ""
    assistant.completion_model = SimpleNamespace(
        id=None,
        litellm_model_name="anthropic/claude-test",
        name="claude-test",
        provider_type="anthropic",
        supported_model_kwargs=SupportedModelKwargs(
            temperature=ModelKwargCapability(supported=True)
        ),
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
        max_inline_text_bytes=1_000_000,
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

    prepared.completion_call = build_prepared_completion_call(
        step=step,
        state=state,
        prepared=prepared,
    )
    assert (
        prepared.completion_call.preferred_model_parameters["response_format"] is None
    )
    assert prepared.completion_call.capability_fallback_model_parameters is None

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
    assert output.model_parameters_json == (
        prepared.completion_call.preferred_model_parameters
    )


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
    assistant.get_prompt_text.return_value = ""
    completion_model_id = uuid4()
    assistant.completion_model = SimpleNamespace(
        id=completion_model_id,
        litellm_model_name="openai/gpt-test",
        name="gpt-test",
        provider_type="openai",
        supported_model_kwargs=SupportedModelKwargs(),
    )
    assistant.completion_model_kwargs = ModelKwargs()
    observer = SimpleNamespace(
        started=AsyncMock(return_value=uuid4()),
        completed=AsyncMock(),
        rejected=AsyncMock(),
        outcome_unknown=AsyncMock(),
    )

    async def _observed_response(**kwargs):
        provider_observer = kwargs["provider_call_observer"]
        call_id = await provider_observer.started(
            CompletionCallRequestFacts(
                request_schema_version=2,
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
            CompletionCallResultFacts(
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
    resolved_input_edge = build_resolved_input_edge(
        binding_ref="question",
        source=FlowResolvedInputFlowInputSource(
            kind="flow_input",
            selector=FlowResolvedInputJsonPath(
                kind="json_path",
                path=("question",),
            ),
        ),
        selected_value="hello",
    )
    prepared = PreparedStepExecution(
        assistant=assistant,
        step_input=StepInputValue(text="hello", source_text="hello"),
        effective_prompt="Prompt",
        input_payload_for_result={"text": "hello", "source_text": "hello"},
        contract_validation=None,
        diagnostics=[],
        llm_files=[],
        resolved_input_edges=(resolved_input_edge,),
        resolved_input_edge_indexes=(0,),
    )

    observed_builder_arguments = []

    def _build_provider_call_observer(
        mapped_call,
        resolved_input_edge_indexes,
        observed_completion_model_id,
    ):
        observed_builder_arguments.append(
            (
                mapped_call,
                resolved_input_edge_indexes,
                observed_completion_model_id,
            )
        )
        return observer

    async def _fail_after_receipt(**_kwargs):
        observer.completed.assert_awaited_once()
        raise RuntimeError("postprocessing failed")

    deps = StepExecutionRuntimeDeps(
        max_inline_text_bytes=1_000_000,
        variable_resolver=FlowVariableResolver(),
        completion_service=object(),
        load_assistant=AsyncMock(),
        resolve_step_input=AsyncMock(),
        retrieve_rag_chunks=AsyncMock(return_value=([], None, [])),
        process_typed_output=AsyncMock(side_effect=_fail_after_receipt),
        apply_output_cap=AsyncMock(),
        build_provider_call_observer=_build_provider_call_observer,
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
    assert observed_builder_arguments == [
        (deps.mapped_call_context, (0,), completion_model_id)
    ]


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
    assistant.get_prompt_text.return_value = ""
    assistant.completion_model = SimpleNamespace(
        id=None,
        litellm_model_name="openai/gpt-test",
        name="gpt-test",
        provider_type="openai",
        supported_model_kwargs=SupportedModelKwargs(),
    )
    assistant.completion_model_kwargs = MagicMock(name="original_kwargs")
    assistant.completion_model_kwargs.filter_unsupported.return_value = (
        assistant.completion_model_kwargs
    )
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
        max_inline_text_bytes=1_000_000,
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
    assistant.get_prompt_text.return_value = ""
    assistant.completion_model = SimpleNamespace(
        id=None,
        litellm_model_name="openai/gpt-test",
        name="gpt-test",
        provider_type="openai",
        supported_model_kwargs=SupportedModelKwargs(),
    )
    assistant.completion_model_kwargs = MagicMock(name="original_kwargs")
    assistant.completion_model_kwargs.filter_unsupported.return_value = (
        assistant.completion_model_kwargs
    )
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
        max_inline_text_bytes=1_000_000,
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
    assistant.get_prompt_text.return_value = ""
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
        max_inline_text_bytes=1_000_000,
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

    assert getattr(exc_info.value, "rejected_output", None) is None
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
async def test_complete_step_execution_translates_missing_capacity():
    from eneo.completion_models.domain.model_capacity import UnknownModelCapacityError

    run = _run()
    state = _state()
    step = _step(output_type="text")
    assistant = MagicMock()
    assistant.get_prompt_text.return_value = ""
    assistant.completion_model_kwargs = MagicMock(name="model_kwargs")
    assistant.get_response = AsyncMock(
        side_effect=UnknownModelCapacityError(("max_output_tokens",))
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
        max_inline_text_bytes=1_000_000,
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

    assert getattr(exc_info.value, "rejected_output", None) is None
    assert exc_info.value.code == "flow_model_capacity_undeclared"
    assert "max_output_tokens" in str(exc_info.value)
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
    from eneo.flows.runtime import step_deadline

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
    assistant.get_prompt_text.return_value = ""
    assistant.completion_model_kwargs = original_kwargs
    assistant.completion_model_kwargs.model_copy.return_value = json_mode_kwargs

    counter = {"n": 0}

    async def fake_get_response(**_kwargs: object):
        step_deadline.mark_provider_request_in_flight(True)
        counter["n"] += 1
        if counter["n"] == 1:
            await asyncio.sleep(0.25)
            step_deadline.settle_provider_request(known=True)
            raise ProviderCapabilityRejectedException(
                "The provider rejected JSON mode.",
                capability="response_format",
                retry_without_capability_safe=True,
                code="provider_capability_rejected",
            )
        try:
            await asyncio.sleep(0.2)
        except asyncio.CancelledError:
            step_deadline.settle_provider_request(known=False)
            raise
        step_deadline.settle_provider_request(known=True)
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
        max_inline_text_bytes=1_000_000,
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

    with (
        step_deadline.step_deadline_scope(
            step_deadline.StepDeadline.start(0.3), step_order=1
        ),
        pytest.raises(TypedIOValidationException) as exc_info,
    ):
        await complete_step_execution(
            step=step,
            run=run,
            state=state,
            prepared=prepared,
            deps=deps,
        )

    assert getattr(exc_info.value, "rejected_output", None) is None
    assert exc_info.value.code == "flow_step_timeout"
    # The request was in flight when the budget ran out, so the refusal says
    # the provider may still complete and bill it.
    assert "provider request" in str(exc_info.value)
    assert "may still complete" in str(exc_info.value)
    assert assistant.get_response.await_count == 2


@pytest.mark.asyncio
async def test_complete_step_execution_keeps_retrieval_evidence_when_finalization_is_cancelled(
    monkeypatch: pytest.MonkeyPatch,
):
    """The executor's backstop cancels finalization; what retrieval read
    before that is evidence and must ride the cancellation out."""
    monkeypatch.setattr(
        "eneo.flows.runtime.step_execution_runtime.detect_native_json_output_support",
        lambda assistant: None,
    )
    run = _run()
    state = _state()
    step = _step(output_type="json")
    assistant = MagicMock()
    assistant.get_prompt_text.return_value = ""
    assistant.completion_model_kwargs = MagicMock()
    assistant.get_response = AsyncMock(
        return_value=SimpleNamespace(total_token_count=4, completion='{"ok": true}')
    )
    prepared = PreparedStepExecution(
        assistant=assistant,
        step_input=StepInputValue(
            text="hello", source_text="hello", input_source="flow_input"
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
    retrieved = {"status": "retrieved", "chunk_count": 2}

    async def cancelled_finalization(**_kwargs: object):
        raise asyncio.CancelledError()

    deps = StepExecutionRuntimeDeps(
        max_inline_text_bytes=1_000_000,
        variable_resolver=FlowVariableResolver(),
        completion_service=object(),
        load_assistant=AsyncMock(),
        resolve_step_input=AsyncMock(),
        retrieve_rag_chunks=AsyncMock(return_value=([], retrieved, [])),
        process_typed_output=AsyncMock(side_effect=cancelled_finalization),
        apply_output_cap=AsyncMock(return_value=('{"ok": true}', [])),
    )

    with pytest.raises(asyncio.CancelledError) as exc_info:
        await complete_step_execution(
            step=step, run=run, state=state, prepared=prepared, deps=deps
        )

    assert getattr(exc_info.value, "rag_metadata") == retrieved


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
    `flow_step_timeout` directly so the executor's failure
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
    assistant.get_prompt_text.return_value = ""
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
        max_inline_text_bytes=1_000_000,
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

    assert getattr(exc_info.value, "rejected_output", None) is None
    assert exc_info.value.code == "flow_step_timeout"
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
    assistant.get_prompt_text.return_value = ""
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
        max_inline_text_bytes=1_000_000,
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

    assert getattr(exc_info.value, "rejected_output", None) is None
    assert exc_info.value.code == "flow_step_timeout"
    assert getattr(exc_info.value, "effective_prompt") == "Prompt"
    failed_input_payload = getattr(exc_info.value, "input_payload_json")
    assert failed_input_payload["input_source"] == "all_previous_steps"


@pytest.mark.asyncio
@pytest.mark.parametrize("ownership_lost", [False, True])
async def test_complete_step_execution_cancels_llm_request_when_run_is_cancelled(
    monkeypatch, ownership_lost
):
    import eneo.flows.runtime.step_execution_runtime as runtime
    from eneo.flows.runtime.execution_heartbeat import FlowExecutionOwnershipLost

    monkeypatch.setattr(
        runtime,
        "execution_ownership_is_lost",
        AsyncMock(return_value=ownership_lost),
        raising=False,
    )
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
    assistant.get_prompt_text.return_value = ""
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
        max_inline_text_bytes=1_000_000,
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

    with pytest.raises(
        FlowExecutionOwnershipLost if ownership_lost else FlowStepCancelledError
    ):
        await complete_step_execution(
            step=step,
            run=run,
            state=state,
            prepared=prepared,
            deps=deps,
        )

    if ownership_lost:
        assistant.get_response.assert_not_awaited()
    else:
        assert cancelled.is_set()
    assert state.in_flight_llm_task is None


@pytest.mark.asyncio
async def test_heartbeat_loss_cancels_an_already_running_provider_child(monkeypatch):
    from contextlib import asynccontextmanager

    from sqlalchemy.ext.asyncio import AsyncSession

    import eneo.flows.runtime.step_execution_runtime as runtime
    from eneo.flows.infrastructure.flow_run_repo import FlowRunExecutionOwner
    from eneo.flows.runtime import execution_heartbeat as heartbeat

    manager = heartbeat.FlowExecutionHeartbeats(max_active=1)
    repo = AsyncMock()
    repo.renew_execution_heartbeats.return_value = set()

    @asynccontextmanager
    async def session_scope():
        yield AsyncMock(spec=AsyncSession)

    monkeypatch.setattr(heartbeat.sessionmanager, "session", session_scope)
    monkeypatch.setattr(heartbeat, "FlowRunRepository", lambda **_: repo)

    monkeypatch.setattr(
        runtime,
        "execution_ownership_is_lost",
        AsyncMock(return_value=False),
        raising=False,
    )
    run = _run()
    state = _state()
    step = _step(output_type="text")
    cancelled = asyncio.Event()
    started = asyncio.Event()

    async def blocked_response(**_kwargs: object) -> object:
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return SimpleNamespace(total_token_count=4, completion="too late")

    assistant = MagicMock()
    assistant.get_prompt_text.return_value = ""
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
        max_inline_text_bytes=1_000_000,
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
        run_cancelled=AsyncMock(return_value=False),
        run_cancel_poll_interval_seconds=0.001,
    )

    async def invoke():
        async with manager.track(
            FlowRunExecutionOwner(run.id, run.tenant_id, run.revision)
        ):
            await complete_step_execution(
                step=step, run=run, state=state, prepared=prepared, deps=deps
            )

    invocation = asyncio.create_task(invoke())
    try:
        await asyncio.wait_for(started.wait(), timeout=2)
        await manager.renew()
        with pytest.raises(heartbeat.FlowExecutionOwnershipLost):
            await asyncio.wait_for(invocation, timeout=2)
        assert cancelled.is_set()
        assert state.in_flight_llm_task is None
        assistant.get_response.assert_awaited_once()
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_cancellation_survives_a_failing_cancel_probe():
    """A blip on the cancel probe must not disarm cancellation for the step.

    This poll is the only thing that stops an in-flight provider call when a user
    cancels, and a provider call can run for minutes. Ending the watch on the
    first failed probe meant a cancel was honoured only once the call finished on
    its own, with the provider spend already incurred.
    """
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
    assistant.get_prompt_text.return_value = ""
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

    probes = 0
    # More failures than the removed five-failure budget allowed: a database
    # disruption lasting several polls must not end the watch, because the only
    # bound that matters is the step's own deadline.
    failures_before_recovery = 12

    async def flaky_run_cancelled(**_kwargs: object) -> bool:
        nonlocal probes
        probes += 1
        if probes <= failures_before_recovery:
            raise RuntimeError("transient cancel probe failure")
        return True

    watch_logger = MagicMock()
    deps = StepExecutionRuntimeDeps(
        max_inline_text_bytes=1_000_000,
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
        run_cancelled=flaky_run_cancelled,
        run_cancel_poll_interval_seconds=0.001,
        logger=watch_logger,
    )

    with pytest.raises(FlowStepCancelledError):
        await complete_step_execution(
            step=step,
            run=run,
            state=state,
            prepared=prepared,
            deps=deps,
        )

    assert probes > failures_before_recovery
    assert cancelled.is_set()
    # An outage leaves a trail without one line per poll: only the first of the
    # twelve failures is logged.
    cancel_watch_warnings = [
        call
        for call in watch_logger.warning.call_args_list
        if "cancel_watch_failed" in call.args[0]
    ]
    assert len(cancel_watch_warnings) == 1
    assert cancel_watch_warnings[0].args[-1] == 1


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
    assistant.get_prompt_text.return_value = ""
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
        max_inline_text_bytes=1_000_000,
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
    assistant.get_prompt_text.return_value = ""
    assistant.completion_model = SimpleNamespace(
        id=None,
        litellm_model_name="openai/gpt-4.1",
        name="gpt-4.1",
        provider_type="openai",
        supported_model_kwargs=SupportedModelKwargs(),
    )
    assistant.completion_model_kwargs = original_kwargs
    original_kwargs.filter_unsupported.return_value = original_kwargs
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
        max_inline_text_bytes=1_000_000,
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
    assistant.get_prompt_text.return_value = ""
    assistant.completion_model = SimpleNamespace(
        id=None,
        litellm_model_name=None,
        name="claude-3-5-haiku",
        provider_type="anthropic",
        supported_model_kwargs=SupportedModelKwargs(),
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
        max_inline_text_bytes=1_000_000,
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
    monkeypatch.setattr(
        "eneo.flows.runtime.step_execution_runtime.detect_native_json_output_support",
        lambda assistant: None,
    )
    monkeypatch.setattr(
        "eneo.flows.runtime.step_execution_runtime.schema_response_format",
        lambda **kwargs: None,
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
    assistant.get_prompt_text.return_value = ""
    assistant.completion_model_kwargs = original_kwargs
    original_kwargs.filter_unsupported.return_value = original_kwargs
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
        max_inline_text_bytes=1_000_000,
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
    assistant.get_prompt_text.return_value = ""
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
        max_inline_text_bytes=1_000_000,
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
    assistant.get_prompt_text.return_value = ""
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
        max_inline_text_bytes=1_000_000,
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
    assistant.get_prompt_text.return_value = ""
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
        max_inline_text_bytes=1_000_000,
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
    assistant.get_prompt_text.return_value = ""
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
        "citation_sources": [
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "id_short": "11111111",
            },
            {
                "id": "22222222-2222-2222-2222-222222222222",
                "id_short": "22222222",
            },
        ],
        "passage_evidence_location": "attempt_provenance",
    }
    deps = StepExecutionRuntimeDeps(
        max_inline_text_bytes=1_000_000,
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
    assistant.get_prompt_text.return_value = ""
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
        max_inline_text_bytes=1_000_000,
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
    assistant.get_prompt_text.return_value = ""
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
        max_inline_text_bytes=1_000_000,
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
                "citation_sources": [
                    {
                        "id": source_id,
                        "id_short": "11111111",
                        "title": source_title,
                        "source_url": "https://example.org/sociologi",
                    }
                ],
                "passage_evidence_location": "attempt_provenance",
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
    assistant.get_prompt_text.return_value = ""
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
        max_inline_text_bytes=1_000_000,
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
    assert output.effective_prompt == effective_completion_prompt(
        step=step,
        state=state,
        prepared=prepared,
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


def test_build_output_payload_refuses_oversized_structured_output(monkeypatch):
    from eneo.main.config import get_settings

    monkeypatch.setattr(get_settings(), "flow_max_inline_text_bytes", 20)
    output = StepExecutionOutput(
        input_text="",
        source_text="",
        input_source="flow_input",
        used_question_binding=False,
        full_text="",
        persisted_text="",
        generated_file_ids=[],
        tool_calls_metadata=None,
        num_tokens_input=None,
        num_tokens_output=None,
        effective_prompt="",
        model_parameters_json={},
        structured_output={"text": "å" * 10},
        rag_metadata={"status": "success"},
    )
    with pytest.raises(TypedIOValidationException) as error:
        build_output_payload(output)
    assert error.value.code == "typed_io_structured_output_exceeds_limit"
    assert error.value.context == {
        "completed_items": 1,
        "total_items": 1,
        "measured_bytes": 32,
        "ceiling_bytes": 20,
    }
    assert error.value.rag_metadata == {"status": "success"}


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


@pytest.mark.xfail(
    strict=True,
    reason=(
        "G acceptance contract (adopted solo program 2026-08-05): report "
        "citations are not yet supported — inline <inref> tags are stripped "
        "before persisted text reaches compose/render, so the published "
        "document carries bare claims. The citation owner must turn "
        "validated tags into stable visible markers plus a deterministic "
        "reference entry BEFORE the stripping boundary; compose and render "
        "stay deterministic and citation-unaware. Delete "
        "assembly_document_report_citations_unsupported only when this test "
        "passes."
    ),
)
@pytest.mark.asyncio
async def test_document_report_citation_survives_compose_render_and_public_artifact() -> (
    None
):
    import io

    from docx import Document as DocxDocument

    from eneo.flows.runtime.document_rendering.service import (
        default_document_render_service,
    )

    run = _run()
    state = _state()
    step = _step(
        output_type="text",
        output_config={"citation_mode": "inline_inref_sidecar"},
    )
    assistant = MagicMock()
    assistant.get_prompt_text.return_value = ""
    assistant.completion_model_kwargs = MagicMock(name="model_kwargs")
    assistant.get_response = AsyncMock(
        return_value=SimpleNamespace(
            total_token_count=4,
            completion='Material claim <inref id="11111111"/>',
            model=SimpleNamespace(name="gpt-5.4-nano", provider_type="openai"),
            knowledge_trace=None,
        )
    )
    prepared = PreparedStepExecution(
        assistant=assistant,
        step_input=StepInputValue(
            text="source material",
            source_text="source material",
            input_source="flow_input",
        ),
        effective_prompt="Prompt",
        input_payload_for_result={
            "text": "source material",
            "source_text": "source material",
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
        "citation_sources": [
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "id_short": "11111111",
                "title": "Källdokumentet",
            }
        ],
        "passage_evidence_location": "attempt_provenance",
    }
    provider_call_counter = AsyncMock(return_value=("Material claim", []))
    deps = StepExecutionRuntimeDeps(
        max_inline_text_bytes=1_000_000,
        variable_resolver=FlowVariableResolver(),
        completion_service=object(),
        load_assistant=AsyncMock(),
        resolve_step_input=AsyncMock(),
        retrieve_rag_chunks=AsyncMock(return_value=([], rag_metadata, [])),
        process_typed_output=AsyncMock(return_value=_typed_output_result()),
        apply_output_cap=provider_call_counter,
    )

    output = await complete_step_execution(
        step=step,
        run=run,
        state=state,
        prepared=prepared,
        deps=deps,
    )

    # The producer's persisted text is what compose/render receive. The
    # citation identity comes from the inherited/tracked source catalog —
    # never prose scanning — so the visible marker and its reference entry
    # must already be present here.
    persisted_text = output.persisted_text
    blob, _, _ = default_document_render_service().render_document(
        persisted_text,
        "docx",
        step_order=5,
    )
    document_text = "\n".join(
        paragraph.text for paragraph in DocxDocument(io.BytesIO(blob)).paragraphs
    )

    assert "Material claim [1]" in document_text
    assert "[1]" in document_text.replace("Material claim [1]", "", 1)
    assert "Källdokumentet" in document_text
    assert output.citation_sidecar is not None
    assert output.citation_sidecar["citation_compliance"] == "observed"
    assert output.citation_sidecar["cited_source_ids"] == [
        "11111111-1111-1111-1111-111111111111"
    ]
    # Compose and render are deterministic: the only provider-facing call
    # in this chain was the producer itself.
    assert assistant.get_response.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["", "invalid å JSON"])
async def test_rejected_completion_attaches_exact_text_without_output_artifact(text):
    assistant = MagicMock()
    assistant.get_prompt_text.return_value = ""
    assistant.completion_model_kwargs = MagicMock()
    assistant.get_response = AsyncMock(
        return_value=SimpleNamespace(
            total_token_count=4,
            completion=Completion(
                text=text,
                finish_reason="stop",
                provider_response_id="rejected-json",
                reasoning_content="hidden reasoning",
            ),
        )
    )
    prepared = PreparedStepExecution(
        assistant=assistant,
        step_input=StepInputValue(
            text="input", source_text="input", input_source="flow_input"
        ),
        effective_prompt="Return JSON",
        input_payload_for_result={"text": "input"},
        contract_validation=None,
        diagnostics=[],
        llm_files=[],
    )
    cap = AsyncMock()
    deps = StepExecutionRuntimeDeps(
        max_inline_text_bytes=1_000_000,
        variable_resolver=FlowVariableResolver(),
        completion_service=object(),
        load_assistant=AsyncMock(),
        resolve_step_input=AsyncMock(),
        retrieve_rag_chunks=AsyncMock(
            return_value=([], {"status": "skipped_no_service"}, [])
        ),
        process_typed_output=AsyncMock(
            side_effect=TypedIOValidationException(
                "Invalid JSON", code="typed_io_output_parse_failed"
            )
        ),
        apply_output_cap=cap,
    )
    with pytest.raises(TypedIOValidationException) as caught:
        await complete_step_execution(
            step=_step(output_type="json"),
            run=_run(),
            state=_state(),
            prepared=prepared,
            deps=deps,
        )
    assert isinstance(caught.value, StepOutputValidationException)
    assert caught.value.rejected_completion.finish_reason == "stop"
    assert caught.value.rejected_completion.provider_response_id == "rejected-json"
    assert getattr(caught.value, "rejected_output", None) == text
    assert caught.value.effective_prompt == "Return JSON"
    cap.assert_not_called()


@pytest.mark.asyncio
async def test_failed_rejected_output_is_unavailable_to_later_step_variables():
    from eneo.flows.domain.step_output import build_rejected_output_payload
    from eneo.main.exceptions import TypedIOValidationException

    run, state = _run(), _state()
    now = datetime.now(timezone.utc)
    state.prior_results.append(
        FlowStepResult(
            id=uuid4(),
            flow_run_id=run.id,
            flow_id=run.flow_id,
            tenant_id=run.tenant_id,
            step_id=uuid4(),
            step_order=1,
            assistant_id=uuid4(),
            status=FlowStepResultStatus.FAILED,
            output_payload_json=build_rejected_output_payload(
                "private rejected", max_inline_bytes=100
            ),
            created_at=now,
            updated_at=now,
        )
    )
    assistant = MagicMock()
    assistant.get_prompt_text.return_value = "Use {{step1.output}}"
    provider = AsyncMock()
    deps = StepExecutionRuntimeDeps(
        max_inline_text_bytes=1000,
        variable_resolver=FlowVariableResolver(),
        completion_service=provider,
        load_assistant=AsyncMock(return_value=assistant),
        resolve_step_input=AsyncMock(
            return_value=StepInputValue(
                text="input", source_text="input", input_source="flow_input"
            )
        ),
        retrieve_rag_chunks=AsyncMock(),
        process_typed_output=AsyncMock(),
        apply_output_cap=AsyncMock(),
    )
    with pytest.raises(TypedIOValidationException) as caught:
        await prepare_step_execution(
            step=_step(step_order=2),
            run=run,
            state=state,
            version_metadata=None,
            requested_file_ids=(),
            deps=deps,
        )
    assert caught.value.code == "typed_io_variable_resolution_failed"
    provider.assert_not_called()


TRANSPORT = "openai"
MODEL = "model-a"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("finish_reason", "output_type", "text"),
    [
        ("length", "text", "Partial"),
        ("length", "json", '{"title":"A"}'),
        ("stop", "text", "Done"),
        ("content_filter", "text", "Answer"),
    ],
)
async def test_reduced_cap_terminal_reason_controls_flow_consumption(
    finish_reason, output_type, text, monkeypatch
):
    monkeypatch.setattr(
        "litellm.get_supported_openai_params",
        lambda **kwargs: [
            "max_tokens",
            "max_completion_tokens",
            "stream",
            "max_retries",
        ],
    )
    adapter = object.__new__(TenantModelAdapter)
    adapter.litellm_model = f"{TRANSPORT}/{MODEL}"
    adapter.provider_type = TRANSPORT
    messages = [{"role": "user", "content": "hello"}]
    reserve = measure_provider_input_reserve(messages, [], adapter.litellm_model).tokens
    adapter.model = SimpleNamespace(token_limit=reserve + 256, max_output_tokens=512)
    adapter.credential_resolver = SimpleNamespace(
        provider_type=TRANSPORT,
        get_api_key=lambda **kwargs: "test-key",
        get_credential_field=lambda **kwargs: None,
    )
    adapter.prepare_provider_input = MagicMock(
        return_value=ProviderInput(messages=messages, tools=[], built_in_tools=[])
    )
    observer = SimpleNamespace(
        started=AsyncMock(return_value=uuid4()),
        completed=AsyncMock(),
        rejected=AsyncMock(),
        outcome_unknown=AsyncMock(),
    )
    requests = []

    async def capture_request(client, request, **kwargs):
        requests.append(json.loads(await request.aread()))
        return httpx.Response(
            200,
            request=request,
            json={
                "id": "response-1",
                "object": "chat.completion",
                "created": 1,
                "model": MODEL,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": text},
                        "finish_reason": finish_reason,
                    }
                ],
                "usage": {
                    "prompt_tokens": reserve,
                    "completion_tokens": 1,
                    "total_tokens": reserve + 1,
                },
            },
        )

    monkeypatch.setattr(httpx.AsyncClient, "send", capture_request)

    async def get_response(**kwargs):
        completion = await adapter.get_response(
            context=SimpleNamespace(),
            model_kwargs={},
            provider_call_observer=kwargs["provider_call_observer"],
            api_base="https://provider.example/v1",
            num_retries=0,
            max_retries=0,
        )
        return SimpleNamespace(completion=completion, total_token_count=reserve + 1)

    assistant = MagicMock()
    assistant.get_prompt_text.return_value = ""
    assistant.completion_model_kwargs = ModelKwargs()
    assistant.get_response = AsyncMock(side_effect=get_response)
    prepared = PreparedStepExecution(
        assistant=assistant,
        step_input=StepInputValue(
            text="hello", source_text="hello", input_source="flow_input"
        ),
        effective_prompt="Answer",
        input_payload_for_result={"text": "hello"},
        contract_validation=None,
        diagnostics=[],
        llm_files=[],
        resolved_input_edge_indexes=(),
    )
    process_output = AsyncMock(return_value=_typed_output_result())
    apply_cap = AsyncMock(return_value=(text, []))
    deps = StepExecutionRuntimeDeps(
        max_inline_text_bytes=1_000_000,
        variable_resolver=FlowVariableResolver(),
        completion_service=object(),
        load_assistant=AsyncMock(),
        resolve_step_input=AsyncMock(),
        retrieve_rag_chunks=AsyncMock(return_value=([], None, [])),
        process_typed_output=process_output,
        apply_output_cap=apply_cap,
        build_provider_call_observer=lambda *args: observer,
    )
    step, run = _step(output_type=output_type), _run()
    claimed = FlowStepResult(
        id=uuid4(),
        flow_run_id=run.id,
        flow_id=run.flow_id,
        tenant_id=run.tenant_id,
        step_id=step.step_id,
        step_order=step.step_order,
        assistant_id=step.assistant_id,
        status=FlowStepResultStatus.RUNNING,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )
    if finish_reason == "length":
        with pytest.raises(TypedIOValidationException) as caught:
            await complete_step_execution(
                step=step, run=run, state=_state(), prepared=prepared, deps=deps
            )
        error = caught.value
        assert error.code == "flow_llm_output_truncated"
        assert error.context == {"finish_reason": "length"}
        assert "length" in str(error)
        rejected_completion = getattr(error, "rejected_completion", None)
        assert rejected_completion is not None
        assert rejected_completion.finish_reason == "length"
        assert rejected_completion.provider_response_id == "response-1"
        assert rejected_completion.output.text == text
        assert rejected_completion.output.evidence.sampling_status == "complete"
        assert getattr(error, "rejected_output", None) is None
        process_output.assert_not_awaited()
        apply_cap.assert_not_awaited()
        failure = build_typed_failure_plan(
            claimed=claimed,
            error_code=FlowApiErrorCode(error.code),
            error_message=str(error),
            input_payload_json=error.input_payload_json,
            effective_prompt=error.effective_prompt,
            rejected_completion=rejected_completion,
            max_inline_text_bytes=deps.max_inline_text_bytes,
        )
        assert failure.failed_result.status == FlowStepResultStatus.FAILED
        assert failure.failed_result.error_code == "flow_llm_output_truncated"
        assert "length" in failure.failed_result.error_message
        assert (
            failure.failed_result.output_payload_json
            == rejected_completion.output.to_payload()
        )
    else:
        output = await complete_step_execution(
            step=step, run=run, state=_state(), prepared=prepared, deps=deps
        )
        process_output.assert_awaited_once()
        assert output.full_text == text
        assert output.finish_reason == finish_reason
        result = build_completed_step_result(
            claimed=claimed,
            run_id=run.id,
            flow_id=run.flow_id,
            tenant_id=run.tenant_id,
            step=step,
            output=output,
            output_payload_json={"text": text},
            execution_hash="hash",
        )
        assert result.status == FlowStepResultStatus.COMPLETED
    assert len(requests) == 1
    assert requests[0]["max_tokens"] == 256
    observer.started.assert_awaited_once()
    observer.completed.assert_awaited_once()
    observer.rejected.assert_not_awaited()
    observer.outcome_unknown.assert_not_awaited()
