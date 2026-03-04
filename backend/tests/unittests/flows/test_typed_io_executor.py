"""TDD tests for typed I/O in the flow executor — RED phase.

These tests exercise the typed pipeline: JSON output, PDF/DOCX rendering,
input contract validation, file resolution, canary flag, error propagation.
"""
from __future__ import annotations

import ipaddress
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx
import pytest

import intric.flows.runtime.executor as executor_module
from intric.flows.flow import (
    FlowRun,
    FlowRunStatus,
    FlowStepResult,
    FlowStepResultStatus,
)
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.outcome import Outcome
from intric.flows.runtime.executor import FlowRunExecutor, RunExecutionState, RuntimeStep, StepInputValue
from intric.main.exceptions import TypedIOValidationException


def _run(*, status: FlowRunStatus, user, input_payload=None) -> FlowRun:
    now = datetime.now(timezone.utc)
    return FlowRun(
        id=uuid4(),
        flow_id=uuid4(),
        flow_version=1,
        user_id=user.id,
        tenant_id=user.tenant_id,
        status=status,
        cancelled_at=None,
        input_payload_json=input_payload or {"text": "hello"},
        output_payload_json=None,
        error_message=None,
        job_id=None,
        created_at=now,
        updated_at=now,
    )


def _build_executor(user, *, max_inline_text_bytes: int = 1024 * 1024):
    flow_repo = AsyncMock()
    flow_repo.session = AsyncMock()
    flow_repo.session.commit = AsyncMock()
    flow_repo.session.rollback = AsyncMock()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    space_repo = AsyncMock()
    completion_service = AsyncMock()
    file_repo = AsyncMock()
    encryption_service = AsyncMock()
    executor = FlowRunExecutor(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        space_repo=space_repo,
        completion_service=completion_service,
        file_repo=file_repo,
        encryption_service=encryption_service,
        max_inline_text_bytes=max_inline_text_bytes,
    )
    return executor, flow_repo, flow_run_repo, flow_version_repo


def _runtime_step(
    *,
    step_order: int = 1,
    input_source: str = "flow_input",
    input_type: str = "text",
    input_contract: dict | None = None,
    output_type: str = "text",
    output_contract: dict | None = None,
    input_bindings: dict | None = None,
    input_config: dict | None = None,
    output_mode: str = "pass_through",
    output_config: dict | None = None,
) -> RuntimeStep:
    return RuntimeStep(
        step_id=uuid4(),
        step_order=step_order,
        assistant_id=uuid4(),
        user_description=None,
        input_source=input_source,
        input_bindings=input_bindings,
        input_config=input_config,
        output_mode=output_mode,
        output_config=output_config,
        output_type=output_type,
        output_contract=output_contract,
        input_type=input_type,
        input_contract=input_contract,
    )


def _completed_step_result(
    *,
    run_id,
    flow_id,
    tenant_id,
    step_order: int,
    text: str,
    structured: dict | list | None = None,
) -> FlowStepResult:
    now = datetime.now(timezone.utc)
    payload = {"text": text}
    if structured is not None:
        payload["structured"] = structured
    return FlowStepResult(
        id=uuid4(),
        flow_run_id=run_id,
        flow_id=flow_id,
        tenant_id=tenant_id,
        step_id=uuid4(),
        step_order=step_order,
        assistant_id=uuid4(),
        input_payload_json={"text": f"input-{step_order}"},
        effective_prompt="prompt",
        output_payload_json=payload,
        model_parameters_json={},
        num_tokens_input=1,
        num_tokens_output=1,
        status=FlowStepResultStatus.COMPLETED,
        error_message=None,
        flow_step_execution_hash="hash",
        tool_calls_metadata=None,
        created_at=now,
        updated_at=now,
    )


def _mock_assistant_for_execute_step(*, response_text: str = "ok") -> MagicMock:
    assistant = MagicMock()
    assistant.get_prompt_text.return_value = ""
    assistant.completion_model_kwargs = MagicMock()
    assistant.completion_model_kwargs.model_copy.return_value = assistant.completion_model_kwargs
    assistant.completion_model_kwargs.model_dump.return_value = {}
    assistant.completion_model = SimpleNamespace(id=uuid4(), name="test", provider_type="test")
    assistant.get_response = AsyncMock(
        return_value=SimpleNamespace(
            completion=response_text,
            total_token_count=3,
        )
    )
    return assistant


# --- RuntimeStep extended fields ---


def test_runtime_step_has_typed_fields():
    """RuntimeStep must have output_type, output_contract, input_type, input_contract."""
    step = _runtime_step(
        output_type="json",
        output_contract={"type": "object"},
        input_type="document",
        input_contract=None,
    )
    assert step.output_type == "json"
    assert step.output_contract == {"type": "object"}
    assert step.input_type == "document"
    assert step.input_contract is None


# --- StepInputValue dataclass ---


def test_step_input_value_creation():
    """StepInputValue carries text, files, structured data."""
    val = StepInputValue(
        text="hello",
        files=[SimpleNamespace(id=uuid4())],
        structured={"key": "val"},
        input_source="flow_input",
    )
    assert val.text == "hello"
    assert len(val.files) == 1
    assert val.structured == {"key": "val"}


def test_step_input_value_defaults():
    val = StepInputValue(text="hello")
    assert val.files is None
    assert val.structured is None
    assert val.input_source == "flow_input"
    assert val.used_question_binding is False
    assert val.legacy_prompt_binding_used is False


# --- _resolve_step_input async + JSON structured ---


@pytest.mark.asyncio
async def test_resolve_step_input_json_parses_structured(user):
    """When input_type=json, resolve should parse structured data from text."""
    executor, _, _, _ = _build_executor(user)
    run = _run(
        status=FlowRunStatus.RUNNING,
        user=user,
        input_payload={"text": '{"name": "Alice"}'},
    )
    step = _runtime_step(input_type="json")
    context = executor.variable_resolver.build_context(run.input_payload_json, [])

    resolved = await executor._resolve_step_input(
        step=step,
        context=context,
        run=run,
        prior_results=[],
    )

    assert isinstance(resolved, StepInputValue)
    assert resolved.structured == {"name": "Alice"}
    assert resolved.text == '{"name": "Alice"}'


@pytest.mark.asyncio
async def test_resolve_step_input_json_to_json_prefers_structured(user):
    """When chaining json->json, prefer structured from previous step over text."""
    executor, _, _, _ = _build_executor(user)
    run = _run(status=FlowRunStatus.RUNNING, user=user)
    prior = [
        _completed_step_result(
            run_id=run.id,
            flow_id=run.flow_id,
            tenant_id=run.tenant_id,
            step_order=1,
            text="truncated...",  # simulates output cap truncation
            structured={"full": "data", "not_truncated": True},
        )
    ]
    step = _runtime_step(step_order=2, input_source="previous_step", input_type="json")
    context = executor.variable_resolver.build_context(run.input_payload_json, prior)

    resolved = await executor._resolve_step_input(
        step=step,
        context=context,
        run=run,
        prior_results=prior,
    )

    assert resolved.structured == {"full": "data", "not_truncated": True}
    assert resolved.text == json.dumps({"full": "data", "not_truncated": True}, ensure_ascii=False)


@pytest.mark.asyncio
async def test_resolve_step_input_json_previous_step_parses_text_when_structured_missing(user):
    """json previous_step should parse JSON text when structured is absent."""
    executor, _, _, _ = _build_executor(user)
    run = _run(status=FlowRunStatus.RUNNING, user=user)
    prior = [
        _completed_step_result(
            run_id=run.id,
            flow_id=run.flow_id,
            tenant_id=run.tenant_id,
            step_order=1,
            text='{"k": 1}',
            structured=None,
        )
    ]
    step = _runtime_step(step_order=2, input_source="previous_step", input_type="json")
    context = executor.variable_resolver.build_context(run.input_payload_json, prior)

    resolved = await executor._resolve_step_input(
        step=step,
        context=context,
        run=run,
        prior_results=prior,
    )

    assert resolved.source_text == '{"k": 1}'
    assert resolved.structured == {"k": 1}


@pytest.mark.asyncio
async def test_resolve_step_input_document_loads_files(user):
    """When input_type=document with file_ids, files are loaded and text is extracted."""
    executor, _, _, _ = _build_executor(user)
    file_id = uuid4()
    run = _run(
        status=FlowRunStatus.RUNNING,
        user=user,
        input_payload={"text": "fallback", "file_ids": [str(file_id)]},
    )
    fake_file = SimpleNamespace(id=file_id, text="Extracted document text")
    executor.file_repo.get_list_by_id_and_user = AsyncMock(return_value=[fake_file])

    step = _runtime_step(input_type="document")
    context = executor.variable_resolver.build_context(run.input_payload_json, [])

    resolved = await executor._resolve_step_input(
        step=step,
        context=context,
        run=run,
        prior_results=[],
    )

    assert resolved.files == [fake_file]
    assert resolved.text == "Extracted document text"


@pytest.mark.asyncio
async def test_resolve_step_input_document_rejects_extracted_text_over_inline_cap(user):
    """Document extraction larger than max inline bytes should fail deterministically."""
    executor, _, _, _ = _build_executor(user, max_inline_text_bytes=8)
    file_id = uuid4()
    run = _run(
        status=FlowRunStatus.RUNNING,
        user=user,
        input_payload={"text": "", "file_ids": [str(file_id)]},
    )
    fake_file = SimpleNamespace(id=file_id, text="detta ar mycket langre an atta bytes")
    executor.file_repo.get_list_by_id_and_user = AsyncMock(return_value=[fake_file])

    step = _runtime_step(input_type="document")
    context = executor.variable_resolver.build_context(run.input_payload_json, [])

    with pytest.raises(TypedIOValidationException) as exc:
        await executor._resolve_step_input(
            step=step,
            context=context,
            run=run,
            prior_results=[],
        )

    assert exc.value.code == "typed_io_input_too_large"


@pytest.mark.asyncio
async def test_resolve_step_input_file_ids_full_match_enforcement(user):
    """Missing file_id raises TypedIOValidationException."""
    executor, _, _, _ = _build_executor(user)
    file_id_1 = uuid4()
    file_id_2 = uuid4()
    run = _run(
        status=FlowRunStatus.RUNNING,
        user=user,
        input_payload={"text": "x", "file_ids": [str(file_id_1), str(file_id_2)]},
    )
    # Only return one of the two requested files
    fake_file = SimpleNamespace(id=file_id_1, text="doc")
    executor.file_repo.get_list_by_id_and_user = AsyncMock(return_value=[fake_file])

    step = _runtime_step(input_type="document")
    context = executor.variable_resolver.build_context(run.input_payload_json, [])

    with pytest.raises(TypedIOValidationException, match="not found or not accessible"):
        await executor._resolve_step_input(
            step=step,
            context=context,
            run=run,
            prior_results=[],
        )


@pytest.mark.asyncio
async def test_resolve_step_input_invalid_file_ids_type_raises_typed_error(user):
    """Non-list file_ids should fail with typed_io_invalid_file_ids."""
    executor, _, _, _ = _build_executor(user)
    run = _run(
        status=FlowRunStatus.RUNNING,
        user=user,
        input_payload={"text": "x", "file_ids": "not-a-list"},
    )
    step = _runtime_step(input_type="document")
    context = executor.variable_resolver.build_context(run.input_payload_json, [])

    with pytest.raises(TypedIOValidationException) as exc:
        await executor._resolve_step_input(
            step=step,
            context=context,
            run=run,
            prior_results=[],
        )
    assert exc.value.code == "typed_io_invalid_file_ids"


@pytest.mark.asyncio
async def test_resolve_step_input_invalid_file_id_value_raises_typed_error(user):
    """Malformed file ID values should fail with typed_io_invalid_file_ids."""
    executor, _, _, _ = _build_executor(user)
    run = _run(
        status=FlowRunStatus.RUNNING,
        user=user,
        input_payload={"text": "x", "file_ids": ["not-a-uuid"]},
    )
    step = _runtime_step(input_type="document")
    context = executor.variable_resolver.build_context(run.input_payload_json, [])

    with pytest.raises(TypedIOValidationException) as exc:
        await executor._resolve_step_input(
            step=step,
            context=context,
            run=run,
            prior_results=[],
        )
    assert exc.value.code == "typed_io_invalid_file_ids"


@pytest.mark.asyncio
async def test_resolve_step_input_null_payload_safe(user):
    """input_payload_json=None doesn't crash file resolution."""
    executor, _, _, _ = _build_executor(user)
    run = _run(status=FlowRunStatus.RUNNING, user=user, input_payload=None)
    step = _runtime_step(input_type="document")
    context = executor.variable_resolver.build_context(run.input_payload_json, [])

    resolved = await executor._resolve_step_input(
        step=step,
        context=context,
        run=run,
        prior_results=[],
    )

    assert resolved.files is None


@pytest.mark.asyncio
@pytest.mark.parametrize("input_source", ["previous_step", "all_previous_steps"])
async def test_resolve_step_input_step_one_rejects_previous_sources(user, input_source: str):
    """Legacy snapshots should still reject step 1 chaining-only input sources at runtime."""
    executor, _, _, _ = _build_executor(user)
    run = _run(status=FlowRunStatus.RUNNING, user=user, input_payload={"text": "x"})
    step = _runtime_step(step_order=1, input_source=input_source, input_type="text")
    context = executor.variable_resolver.build_context(run.input_payload_json, [])

    with pytest.raises(TypedIOValidationException) as exc:
        await executor._resolve_step_input(
            step=step,
            context=context,
            run=run,
            prior_results=[],
        )

    assert exc.value.code == "typed_io_invalid_input_source_position"


@pytest.mark.asyncio
async def test_resolve_step_input_all_previous_steps_json_rejected_with_specific_code(user):
    executor, _, _, _ = _build_executor(user)
    run = _run(status=FlowRunStatus.RUNNING, user=user)
    prior = [
        _completed_step_result(
            run_id=run.id,
            flow_id=run.flow_id,
            tenant_id=run.tenant_id,
            step_order=1,
            text="x",
        )
    ]
    step = _runtime_step(step_order=2, input_source="all_previous_steps", input_type="json")
    context = executor.variable_resolver.build_context(run.input_payload_json, prior)

    with pytest.raises(TypedIOValidationException) as exc:
        await executor._resolve_step_input(
            step=step,
            context=context,
            run=run,
            prior_results=prior,
        )

    assert exc.value.code == "typed_io_invalid_input_source_combination"


@pytest.mark.asyncio
async def test_resolve_step_input_previous_step_missing_prior_returns_empty_text(user):
    executor, _, _, _ = _build_executor(user)
    run = _run(status=FlowRunStatus.RUNNING, user=user)
    step = _runtime_step(step_order=2, input_source="previous_step", input_type="text")
    context = executor.variable_resolver.build_context(run.input_payload_json, [])

    resolved = await executor._resolve_step_input(
        step=step,
        context=context,
        run=run,
        prior_results=[],
    )

    assert resolved.input_source == "previous_step"
    assert resolved.source_text == ""
    assert resolved.text == ""
    assert len(resolved.diagnostics) == 1
    assert resolved.diagnostics[0].code == "empty_prior_step_input"
    assert "resolved to empty text" in resolved.diagnostics[0].message


@pytest.mark.asyncio
async def test_resolve_step_input_all_previous_steps_empty_content_sets_warning(user):
    executor, _, _, _ = _build_executor(user)
    run = _run(status=FlowRunStatus.RUNNING, user=user)
    prior = [
        _completed_step_result(
            run_id=run.id,
            flow_id=run.flow_id,
            tenant_id=run.tenant_id,
            step_order=1,
            text="",
        )
    ]
    step = _runtime_step(step_order=2, input_source="all_previous_steps", input_type="text")
    context = executor.variable_resolver.build_context(run.input_payload_json, prior)

    resolved = await executor._resolve_step_input(
        step=step,
        context=context,
        run=run,
        prior_results=prior,
    )

    assert resolved.input_source == "all_previous_steps"
    assert len(resolved.diagnostics) == 1
    assert resolved.diagnostics[0].code == "empty_prior_step_input"
    assert "resolved to empty text" in resolved.diagnostics[0].message


@pytest.mark.asyncio
async def test_resolve_step_input_previous_step_with_content_has_no_warning(user):
    executor, _, _, _ = _build_executor(user)
    run = _run(status=FlowRunStatus.RUNNING, user=user)
    prior = [
        _completed_step_result(
            run_id=run.id,
            flow_id=run.flow_id,
            tenant_id=run.tenant_id,
            step_order=1,
            text="Hello world",
        )
    ]
    step = _runtime_step(step_order=2, input_source="previous_step", input_type="text")
    context = executor.variable_resolver.build_context(run.input_payload_json, prior)

    resolved = await executor._resolve_step_input(
        step=step,
        context=context,
        run=run,
        prior_results=prior,
    )

    assert resolved.source_text == "Hello world"
    assert resolved.diagnostics == []


@pytest.mark.asyncio
async def test_resolve_step_input_all_previous_steps_prefers_state_accumulator(user):
    executor, _, _, _ = _build_executor(user)
    run = _run(status=FlowRunStatus.RUNNING, user=user)
    prior = [
        _completed_step_result(
            run_id=run.id,
            flow_id=run.flow_id,
            tenant_id=run.tenant_id,
            step_order=1,
            text="fallback",
        )
    ]
    state = RunExecutionState(
        completed_by_order={},
        prior_results=[],
        all_previous_segments=["<step_1_output>\ncached\n</step_1_output>\n"],
        assistant_cache={},
        json_mode_supported={},
        file_cache={},
    )
    step = _runtime_step(step_order=2, input_source="all_previous_steps", input_type="text")
    context = executor.variable_resolver.build_context(run.input_payload_json, prior)

    resolved = await executor._resolve_step_input(
        step=step,
        context=context,
        run=run,
        prior_results=prior,
        state=state,
    )

    assert resolved.source_text == "<step_1_output>\ncached\n</step_1_output>\n"
    assert resolved.text == "<step_1_output>\ncached\n</step_1_output>\n"


@pytest.mark.asyncio
async def test_resolve_step_input_all_previous_steps_excludes_current_and_future_results(user):
    executor, _, _, _ = _build_executor(user)
    run = _run(status=FlowRunStatus.RUNNING, user=user)
    prior = [
        _completed_step_result(
            run_id=run.id,
            flow_id=run.flow_id,
            tenant_id=run.tenant_id,
            step_order=1,
            text="ONE",
        ),
        _completed_step_result(
            run_id=run.id,
            flow_id=run.flow_id,
            tenant_id=run.tenant_id,
            step_order=3,
            text="CURRENT",
        ),
        _completed_step_result(
            run_id=run.id,
            flow_id=run.flow_id,
            tenant_id=run.tenant_id,
            step_order=4,
            text="FUTURE",
        ),
    ]
    step = _runtime_step(step_order=3, input_source="all_previous_steps", input_type="text")
    context = executor.variable_resolver.build_context(run.input_payload_json, prior)

    resolved = await executor._resolve_step_input(
        step=step,
        context=context,
        run=run,
        prior_results=prior,
    )

    assert "<step_1_output>\nONE\n</step_1_output>" in resolved.source_text
    assert "CURRENT" not in resolved.source_text
    assert "FUTURE" not in resolved.source_text


@pytest.mark.asyncio
async def test_resolve_step_input_all_previous_steps_rejects_text_over_inline_cap(user):
    """Chained all_previous input exceeding inline cap should fail before LLM invocation."""
    executor, _, _, _ = _build_executor(user, max_inline_text_bytes=16)
    run = _run(status=FlowRunStatus.RUNNING, user=user)
    prior = [
        _completed_step_result(
            run_id=run.id,
            flow_id=run.flow_id,
            tenant_id=run.tenant_id,
            step_order=1,
            text="detta steg ar langt",
        ),
        _completed_step_result(
            run_id=run.id,
            flow_id=run.flow_id,
            tenant_id=run.tenant_id,
            step_order=2,
            text="och detta steg ar ocksa langt",
        ),
    ]
    step = _runtime_step(step_order=3, input_source="all_previous_steps", input_type="text")
    context = executor.variable_resolver.build_context(run.input_payload_json, prior)

    with pytest.raises(TypedIOValidationException) as exc:
        await executor._resolve_step_input(
            step=step,
            context=context,
            run=run,
            prior_results=prior,
        )

    assert exc.value.code == "typed_io_input_too_large"


@pytest.mark.asyncio
async def test_resolve_step_input_http_get_uses_interpolated_url_and_timeout(user):
    """http_get should interpolate URL templates and propagate timeout config."""
    executor, _, _, _ = _build_executor(user)
    run = _run(
        status=FlowRunStatus.RUNNING,
        user=user,
        input_payload={"text": "budget", "request_id": "42"},
    )
    step = _runtime_step(
        input_source="http_get",
        input_type="text",
        input_config={
            "url": "https://example.org/items/{{flow_input.request_id}}?q={{flow_input.text}}",
            "timeout_seconds": 7,
        },
    )
    request = httpx.Request("GET", "https://example.org/items/42?q=budget")
    executor._send_http_request = AsyncMock(return_value=httpx.Response(200, request=request, text="remote text"))
    context = executor.variable_resolver.build_context(run.input_payload_json, [])

    resolved = await executor._resolve_step_input(
        step=step,
        context=context,
        run=run,
        prior_results=[],
    )

    assert resolved.text == "remote text"
    assert resolved.source_text == "remote text"
    assert resolved.input_source == "http_get"
    executor._send_http_request.assert_awaited_once()


@pytest.mark.asyncio
async def test_resolve_step_input_http_get_timeout_maps_typed_error(user):
    """http_get timeout should map to deterministic typed_io_http_timeout code."""
    executor, _, _, _ = _build_executor(user)
    run = _run(status=FlowRunStatus.RUNNING, user=user, input_payload={"text": "x"})
    step = _runtime_step(
        input_source="http_get",
        input_type="text",
        input_config={"url": "https://example.org"},
    )
    executor._send_http_request = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
    context = executor.variable_resolver.build_context(run.input_payload_json, [])

    with pytest.raises(TypedIOValidationException) as exc:
        await executor._resolve_step_input(
            step=step,
            context=context,
            run=run,
            prior_results=[],
        )

    assert exc.value.code == "typed_io_http_timeout"


@pytest.mark.asyncio
async def test_resolve_step_input_http_get_non_200_maps_typed_error(user):
    """http_get non-success responses should fail with typed_io_http_non_success."""
    executor, _, _, _ = _build_executor(user)
    run = _run(status=FlowRunStatus.RUNNING, user=user, input_payload={"text": "x"})
    step = _runtime_step(
        input_source="http_get",
        input_type="text",
        input_config={"url": "https://example.org"},
    )
    request = httpx.Request("GET", "https://example.org")
    executor._send_http_request = AsyncMock(
        return_value=httpx.Response(503, request=request, text="service unavailable")
    )
    context = executor.variable_resolver.build_context(run.input_payload_json, [])

    with pytest.raises(TypedIOValidationException) as exc:
        await executor._resolve_step_input(
            step=step,
            context=context,
            run=run,
            prior_results=[],
        )

    assert exc.value.code == "typed_io_http_non_success"


@pytest.mark.asyncio
async def test_resolve_step_input_http_json_malformed_response_maps_typed_error(user):
    """json input over HTTP should fail deterministically on malformed JSON response."""
    executor, _, _, _ = _build_executor(user)
    run = _run(status=FlowRunStatus.RUNNING, user=user, input_payload={"text": "x"})
    step = _runtime_step(
        input_source="http_get",
        input_type="json",
        input_config={"url": "https://example.org/json"},
    )
    request = httpx.Request("GET", "https://example.org/json")
    executor._send_http_request = AsyncMock(
        return_value=httpx.Response(200, request=request, text="not-json")
    )
    context = executor.variable_resolver.build_context(run.input_payload_json, [])

    with pytest.raises(TypedIOValidationException) as exc:
        await executor._resolve_step_input(
            step=step,
            context=context,
            run=run,
            prior_results=[],
        )

    assert exc.value.code == "typed_io_http_malformed_response"


@pytest.mark.asyncio
async def test_resolve_step_input_http_post_uses_body_json_and_interpolated_headers(user):
    """http_post should interpolate url/headers/body_json and send structured JSON payload."""
    executor, _, _, _ = _build_executor(user)
    executor.encryption_service.is_encrypted = MagicMock(return_value=False)
    executor.encryption_service.decrypt = MagicMock(side_effect=lambda value: value)
    run = _run(
        status=FlowRunStatus.RUNNING,
        user=user,
        input_payload={
            "request_id": "42",
            "payload": {"name": "Anna Andersson"},
        },
    )
    step = _runtime_step(
        input_source="http_post",
        input_type="text",
        input_config={
            "url": "https://example.org/webhook/{{flow_input.request_id}}",
            "timeout_seconds": 11,
            "headers": {"X-Request-Id": "{{flow_input.request_id}}"},
            "body_json": {
                "citizen_name": "{{flow_input.payload.name}}",
                "request_id": "{{flow_input.request_id}}",
            },
        },
    )
    request = httpx.Request("POST", "https://example.org/webhook/42")
    executor._send_http_request = AsyncMock(
        return_value=httpx.Response(200, request=request, text="posted")
    )
    context = executor.variable_resolver.build_context(run.input_payload_json, [])

    resolved = await executor._resolve_step_input(
        step=step,
        context=context,
        run=run,
        prior_results=[],
    )

    assert resolved.text == "posted"
    assert resolved.source_text == "posted"
    assert resolved.input_source == "http_post"
    executor._send_http_request.assert_awaited_once()
    kwargs = executor._send_http_request.await_args.kwargs
    assert kwargs["method"] == "POST"
    assert kwargs["url"] == "https://example.org/webhook/42"
    assert kwargs["timeout_seconds"] == 11
    assert kwargs["headers"] == {"X-Request-Id": "42"}
    assert kwargs["body_bytes"] is None
    assert kwargs["json_body"] == {
        "citizen_name": "Anna Andersson",
        "request_id": 42,
    }


@pytest.mark.asyncio
async def test_resolve_step_input_http_post_rejects_conflicting_body_config(user):
    """http_post must reject simultaneous body_template and body_json definitions."""
    executor, _, _, _ = _build_executor(user)
    run = _run(status=FlowRunStatus.RUNNING, user=user, input_payload={"text": "x"})
    step = _runtime_step(
        input_source="http_post",
        input_type="text",
        input_config={
            "url": "https://example.org",
            "body_template": "{\"value\":\"{{flow_input.text}}\"}",
            "body_json": {"value": "{{flow_input.text}}"},
        },
    )
    context = executor.variable_resolver.build_context(run.input_payload_json, [])

    with pytest.raises(TypedIOValidationException) as exc:
        await executor._resolve_step_input(
            step=step,
            context=context,
            run=run,
            prior_results=[],
        )

    assert exc.value.code == "typed_io_http_invalid_config"


@pytest.mark.asyncio
async def test_resolve_step_input_http_post_rejects_non_string_header_keys(user):
    """http_post must reject non-string header keys before sending outbound requests."""
    executor, _, _, _ = _build_executor(user)
    executor.encryption_service.is_encrypted = MagicMock(return_value=False)
    executor.encryption_service.decrypt = MagicMock(side_effect=lambda value: value)
    run = _run(status=FlowRunStatus.RUNNING, user=user, input_payload={"text": "x"})
    step = _runtime_step(
        input_source="http_post",
        input_type="text",
        input_config={
            "url": "https://example.org",
            "headers": {1: "value"},
            "body_json": {"value": "{{flow_input.text}}"},
        },
    )
    context = executor.variable_resolver.build_context(run.input_payload_json, [])

    with pytest.raises(TypedIOValidationException) as exc:
        await executor._resolve_step_input(
            step=step,
            context=context,
            run=run,
            prior_results=[],
        )

    assert exc.value.code == "typed_io_http_invalid_config"


@pytest.mark.asyncio
async def test_send_http_request_stream_cap_raises_typed_error(user, monkeypatch):
    """Streamed HTTP body should enforce max inline bytes before full buffering."""
    executor, _, _, _ = _build_executor(user)
    executor._assert_http_url_allowed = AsyncMock(return_value=None)

    class _FakeNetworkStream:
        def get_extra_info(self, info: str):
            if info == "server_addr":
                return ("93.184.216.34", 443)
            return None

    class _FakeStreamResponse:
        def __init__(self) -> None:
            self.status_code = 200
            self.headers = {}
            self.extensions = {"network_stream": _FakeNetworkStream()}

        async def aiter_bytes(self):
            yield b"1234"
            yield b"56789"

        async def aclose(self) -> None:
            return None

    class _FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def build_request(self, method, url, headers=None, content=None, json=None):
            return httpx.Request(method, url, headers=headers, content=content, json=json)

        async def send(self, request, stream=True):
            return _FakeStreamResponse()

    settings = executor_module.get_settings()
    original_max = settings.flow_max_inline_text_bytes
    monkeypatch.setattr(settings, "flow_max_inline_text_bytes", 8)
    monkeypatch.setattr(executor_module.httpx, "AsyncClient", _FakeClient)

    with pytest.raises(TypedIOValidationException) as exc:
        await executor._send_http_request(
            method="GET",
            url="https://example.org/capped",
            headers={},
            timeout_seconds=5,
        )

    assert exc.value.code == "typed_io_http_response_too_large"
    monkeypatch.setattr(settings, "flow_max_inline_text_bytes", original_max)


@pytest.mark.asyncio
async def test_send_http_request_webhook_mode_skips_body_read(user, monkeypatch):
    """Webhook-mode requests should not read/accumulate response bodies."""
    executor, _, _, _ = _build_executor(user)
    executor._assert_http_url_allowed = AsyncMock(return_value=None)

    class _FakeNetworkStream:
        def get_extra_info(self, info: str):
            if info == "server_addr":
                return ("93.184.216.34", 443)
            return None

    class _FakeStreamResponse:
        def __init__(self) -> None:
            self.status_code = 204
            self.headers = {"X-Test": "1"}
            self.extensions = {"network_stream": _FakeNetworkStream()}

        async def aiter_bytes(self):
            raise AssertionError("aiter_bytes should not be called when read_response_body=False")

        async def aclose(self) -> None:
            return None

    class _FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def build_request(self, method, url, headers=None, content=None, json=None):
            return httpx.Request(method, url, headers=headers, content=content, json=json)

        async def send(self, request, stream=True):
            return _FakeStreamResponse()

    monkeypatch.setattr(executor_module.httpx, "AsyncClient", _FakeClient)
    response = await executor._send_http_request(
        method="POST",
        url="https://example.org/webhook",
        headers={},
        timeout_seconds=5,
        read_response_body=False,
    )

    assert response.status_code == 204


@pytest.mark.asyncio
async def test_send_http_request_blocks_rebound_private_peer(user, monkeypatch):
    """Connection-time peer validation should block DNS rebind to private/local addresses."""
    executor, _, _, _ = _build_executor(user)
    executor._assert_http_url_allowed = AsyncMock(
        return_value={ipaddress.ip_address("93.184.216.34")}
    )

    class _FakeNetworkStream:
        def get_extra_info(self, info: str):
            if info == "server_addr":
                return ("127.0.0.1", 8080)
            return None

    class _FakeStreamResponse:
        def __init__(self) -> None:
            self.status_code = 200
            self.headers = {}
            self.extensions = {"network_stream": _FakeNetworkStream()}

        async def aiter_bytes(self):
            yield b"ok"

        async def aclose(self) -> None:
            return None

    class _FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def build_request(self, method, url, headers=None, content=None, json=None):
            return httpx.Request(method, url, headers=headers, content=content, json=json)

        async def send(self, request, stream=True):
            return _FakeStreamResponse()

    monkeypatch.setattr(executor_module.httpx, "AsyncClient", _FakeClient)

    with pytest.raises(TypedIOValidationException) as exc:
        await executor._send_http_request(
            method="GET",
            url="https://example.org/rebind",
            headers={},
            timeout_seconds=5,
        )

    assert exc.value.code == "typed_io_http_ssrf_blocked"


@pytest.mark.asyncio
async def test_send_http_request_blocks_peer_not_in_preflight_resolution(user, monkeypatch):
    """Connection-time peer must match the preflight DNS set when SSRF guard is enabled."""
    executor, _, _, _ = _build_executor(user)
    executor._assert_http_url_allowed = AsyncMock(
        return_value={ipaddress.ip_address("93.184.216.34")}
    )

    class _FakeNetworkStream:
        def get_extra_info(self, info: str):
            if info == "server_addr":
                return ("93.184.216.35", 443)
            return None

    class _FakeStreamResponse:
        def __init__(self) -> None:
            self.status_code = 200
            self.headers = {}
            self.extensions = {"network_stream": _FakeNetworkStream()}

        async def aiter_bytes(self):
            yield b"ok"

        async def aclose(self) -> None:
            return None

    class _FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def build_request(self, method, url, headers=None, content=None, json=None):
            return httpx.Request(method, url, headers=headers, content=content, json=json)

        async def send(self, request, stream=True):
            return _FakeStreamResponse()

    monkeypatch.setattr(executor_module.httpx, "AsyncClient", _FakeClient)

    with pytest.raises(TypedIOValidationException) as exc:
        await executor._send_http_request(
            method="GET",
            url="https://example.org/rebind",
            headers={},
            timeout_seconds=5,
        )

    assert exc.value.code == "typed_io_http_ssrf_blocked"


# --- Runtime guards for unsupported types ---


@pytest.mark.asyncio
async def test_audio_input_previous_step_rejected_runtime(user):
    """Audio input is flow_input-only at runtime."""
    executor, _, _, _ = _build_executor(user)
    run = _run(status=FlowRunStatus.RUNNING, user=user)
    step = _runtime_step(input_type="audio", input_source="previous_step", step_order=2)
    prev = _completed_step_result(
        run_id=run.id,
        flow_id=run.flow_id,
        tenant_id=run.tenant_id,
        step_order=1,
        text="prior output",
    )
    run_state = RunExecutionState(
        completed_by_order={1: prev},
        prior_results=[prev],
        all_previous_segments=["<step_1_output>\nprior output\n</step_1_output>\n"],
        assistant_cache={},
        json_mode_supported={},
        file_cache={},
    )
    executor._load_assistant = AsyncMock(return_value=_mock_assistant_for_execute_step())

    with pytest.raises(TypedIOValidationException) as exc:
        await executor._execute_step(step=step, run=run, state=run_state)

    assert exc.value.code == "typed_io_audio_source_unsupported"


# --- Typed validation tests ---


@pytest.mark.asyncio
async def test_empty_document_extraction_fails(user):
    """Document extraction producing empty text raises typed_io_empty_extraction."""
    executor, _, _, _ = _build_executor(user)
    file_id = uuid4()
    run = _run(
        status=FlowRunStatus.RUNNING,
        user=user,
        input_payload={"text": "", "file_ids": [str(file_id)]},
    )
    # File exists but has no extracted text
    fake_file = SimpleNamespace(id=file_id, text="")
    executor.file_repo.get_list_by_id_and_user = AsyncMock(return_value=[fake_file])

    step = _runtime_step(input_type="document")
    mock_assistant = MagicMock()
    mock_assistant.get_prompt_text.return_value = ""
    mock_assistant.completion_model_kwargs = MagicMock()
    mock_assistant.completion_model_kwargs.model_copy.return_value = mock_assistant.completion_model_kwargs
    mock_assistant.completion_model_kwargs.model_dump.return_value = {}
    mock_assistant.completion_model = SimpleNamespace(id=uuid4(), name="test", provider_type="test")
    executor._load_assistant = AsyncMock(return_value=mock_assistant)

    with pytest.raises(TypedIOValidationException, match="empty text"):
        await executor._execute_step(step=step, run=run)


@pytest.mark.asyncio
async def test_document_extraction_does_not_fallback_to_payload_text(user):
    """Document extraction must fail when files contain no text even if payload text exists."""
    executor, _, _, _ = _build_executor(user)
    file_id = uuid4()
    run = _run(
        status=FlowRunStatus.RUNNING,
        user=user,
        input_payload={"text": "fallback payload text", "file_ids": [str(file_id)]},
    )
    fake_file = SimpleNamespace(id=file_id, text="")
    executor.file_repo.get_list_by_id_and_user = AsyncMock(return_value=[fake_file])
    step = _runtime_step(input_type="document")
    executor._load_assistant = AsyncMock(return_value=_mock_assistant_for_execute_step())

    with pytest.raises(TypedIOValidationException) as exc:
        await executor._execute_step(step=step, run=run)

    assert exc.value.code == "typed_io_empty_extraction"


@pytest.mark.asyncio
async def test_file_input_uses_extracted_file_text(user):
    """File input should use extracted file text and pass extraction guard."""
    executor, _, _, _ = _build_executor(user)
    file_id = uuid4()
    run = _run(
        status=FlowRunStatus.RUNNING,
        user=user,
        input_payload={"text": "", "file_ids": [str(file_id)]},
    )
    fake_file = SimpleNamespace(id=file_id, text="Extracted file text")
    executor.file_repo.get_list_by_id_and_user = AsyncMock(return_value=[fake_file])
    step = _runtime_step(input_type="file")
    executor._load_assistant = AsyncMock(return_value=_mock_assistant_for_execute_step())

    output = await executor._execute_step(step=step, run=run)

    assert output.input_text == "Extracted file text"
    assert output.full_text == "ok"


@pytest.mark.asyncio
async def test_document_previous_step_rejected_with_specific_code(user):
    """Legacy snapshots using previous_step+document should fail deterministically."""
    executor, _, _, _ = _build_executor(user)
    run = _run(status=FlowRunStatus.RUNNING, user=user)
    step = _runtime_step(step_order=2, input_source="previous_step", input_type="document")
    # Build state with one completed previous result.
    from intric.flows.runtime.executor import RunExecutionState

    prev = _completed_step_result(
        run_id=run.id,
        flow_id=run.flow_id,
        tenant_id=run.tenant_id,
        step_order=1,
        text="prior output",
    )
    run_state = RunExecutionState(
        completed_by_order={1: prev},
        prior_results=[prev],
        all_previous_segments=["<step_1_output>\nprior output\n</step_1_output>\n"],
        assistant_cache={},
        json_mode_supported={},
        file_cache={},
    )
    executor._load_assistant = AsyncMock(return_value=_mock_assistant_for_execute_step())

    with pytest.raises(TypedIOValidationException) as exc:
        await executor._execute_step(step=step, run=run, state=run_state)

    assert exc.value.code == "typed_io_document_source_unsupported"


@pytest.mark.asyncio
async def test_image_requires_valid_files(user):
    """Image input with no image files raises typed_io_missing_required_files."""
    executor, _, _, _ = _build_executor(user)
    run = _run(
        status=FlowRunStatus.RUNNING,
        user=user,
        input_payload={"text": "x", "file_ids": []},
    )

    step = _runtime_step(input_type="image")
    mock_assistant = MagicMock()
    mock_assistant.get_prompt_text.return_value = ""
    executor._load_assistant = AsyncMock(return_value=mock_assistant)

    with pytest.raises(TypedIOValidationException, match="not yet supported|requires"):
        await executor._execute_step(step=step, run=run)


@pytest.mark.asyncio
async def test_audio_step_does_not_forward_audio_files_to_llm(user):
    """Audio input uses transcribed text; raw audio files should not be forwarded to LLM."""
    executor, _, _, _ = _build_executor(user)
    run = _run(
        status=FlowRunStatus.RUNNING,
        user=user,
        input_payload={"file_ids": [str(uuid4())]},
    )
    step = _runtime_step(input_type="audio")
    assistant = _mock_assistant_for_execute_step()
    executor._load_assistant = AsyncMock(return_value=assistant)
    executor._resolve_step_input = AsyncMock(
        return_value=StepInputValue(
            text="Transcribed text",
            source_text="Transcribed text",
            files=[SimpleNamespace(id=uuid4(), mimetype="audio/wav")],
            input_source="flow_input",
        )
    )

    output = await executor._execute_step(step=step, run=run)

    assert output.input_text == "Transcribed text"
    assert assistant.get_response.await_args.kwargs["files"] == []


@pytest.mark.asyncio
async def test_audio_transcribe_only_skips_llm_and_rag(user):
    """Audio + transcribe_only should return transcript directly without LLM/RAG."""
    executor, _, _, _ = _build_executor(user)
    run = _run(
        status=FlowRunStatus.RUNNING,
        user=user,
        input_payload={"file_ids": [str(uuid4())]},
    )
    step = _runtime_step(
        input_type="audio",
        output_type="text",
        output_mode="transcribe_only",
    )
    assistant = _mock_assistant_for_execute_step(response_text="should_not_be_used")
    assistant.get_prompt_text.return_value = "ignore this prompt"
    executor._load_assistant = AsyncMock(return_value=assistant)
    executor._resolve_step_input = AsyncMock(
        return_value=StepInputValue(
            text="Raw transcript text",
            source_text="Raw transcript text",
            files=[SimpleNamespace(id=uuid4(), mimetype="audio/wav")],
            input_source="flow_input",
            transcription_metadata={"model": "whisper-1", "language": "sv"},
        )
    )
    executor._retrieve_rag_chunks = AsyncMock(
        return_value=([], {"status": "should_not_run"}, [])
    )

    output = await executor._execute_step(step=step, run=run)

    assistant.get_response.assert_not_awaited()
    executor._retrieve_rag_chunks.assert_not_awaited()
    assert output.full_text == "Raw transcript text"
    assert output.persisted_text == "Raw transcript text"
    assert output.num_tokens_input == 0
    assert output.num_tokens_output == 0
    assert output.transcription_metadata == {"model": "whisper-1", "language": "sv"}
    assert any(d.code == "audio_transcribe_only_used" for d in output.diagnostics)


@pytest.mark.asyncio
async def test_json_input_contract_rejects_unparseable_json(user):
    executor, _, _, _ = _build_executor(user)
    run = _run(
        status=FlowRunStatus.RUNNING,
        user=user,
        input_payload={"text": "not valid json"},
    )
    step = _runtime_step(
        input_type="json",
        input_contract={"type": "object"},
    )
    mock_assistant = MagicMock()
    mock_assistant.get_prompt_text.return_value = ""
    executor._load_assistant = AsyncMock(return_value=mock_assistant)

    with pytest.raises(TypedIOValidationException) as exc:
        await executor._execute_step(step=step, run=run)

    assert exc.value.code == "typed_io_invalid_json_input"


@pytest.mark.asyncio
async def test_text_input_contract_accepts_json_object_string(user):
    executor, _, _, _ = _build_executor(user)
    run = _run(
        status=FlowRunStatus.RUNNING,
        user=user,
        input_payload={"text": '{"title":"Sakerhetsanalys"}'},
    )
    step = _runtime_step(
        input_type="text",
        input_contract={
            "type": "object",
            "required": ["title"],
            "properties": {"title": {"type": "string"}},
        },
    )
    executor._load_assistant = AsyncMock(return_value=_mock_assistant_for_execute_step())

    output = await executor._execute_step(step=step, run=run)

    assert output.input_text == '{"title":"Sakerhetsanalys"}'
    assert output.full_text == "ok"
    assert output.contract_validation == {
        "schema_type_hint": "object",
        "parse_attempted": True,
        "parse_succeeded": True,
        "candidate_type": "dict",
    }


@pytest.mark.asyncio
async def test_text_input_contract_accepts_json_array_string(user):
    executor, _, _, _ = _build_executor(user)
    run = _run(
        status=FlowRunStatus.RUNNING,
        user=user,
        input_payload={"text": '["a","b"]'},
    )
    step = _runtime_step(
        input_type="text",
        input_contract={
            "type": "array",
            "items": {"type": "string"},
        },
    )
    executor._load_assistant = AsyncMock(return_value=_mock_assistant_for_execute_step())

    output = await executor._execute_step(step=step, run=run)

    assert output.input_text == '["a","b"]'
    assert output.full_text == "ok"
    assert output.contract_validation == {
        "schema_type_hint": "array",
        "parse_attempted": True,
        "parse_succeeded": True,
        "candidate_type": "list",
    }


@pytest.mark.asyncio
async def test_text_input_contract_rejects_non_json_for_object_schema(user):
    executor, _, _, _ = _build_executor(user)
    run = _run(
        status=FlowRunStatus.RUNNING,
        user=user,
        input_payload={"text": "not json at all"},
    )
    step = _runtime_step(
        input_type="text",
        input_contract={
            "type": "object",
            "required": ["title"],
            "properties": {"title": {"type": "string"}},
        },
    )
    executor._load_assistant = AsyncMock(return_value=_mock_assistant_for_execute_step())

    with pytest.raises(TypedIOValidationException) as exc:
        await executor._execute_step(step=step, run=run)

    assert exc.value.code == "typed_io_contract_violation"


@pytest.mark.asyncio
async def test_text_input_contract_string_schema_keeps_string_behavior(user):
    executor, _, _, _ = _build_executor(user)
    run = _run(
        status=FlowRunStatus.RUNNING,
        user=user,
        input_payload={"text": '{"title":"still a string"}'},
    )
    step = _runtime_step(
        input_type="text",
        input_contract={"type": "string"},
    )
    executor._load_assistant = AsyncMock(return_value=_mock_assistant_for_execute_step())

    output = await executor._execute_step(step=step, run=run)

    assert output.input_text == '{"title":"still a string"}'
    assert output.full_text == "ok"
    assert output.contract_validation == {
        "schema_type_hint": "string",
        "parse_attempted": False,
        "parse_succeeded": False,
        "candidate_type": "str",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("output_type", "expected_mimetype", "expected_ext"),
    [
        ("pdf", "application/pdf", ".pdf"),
        ("docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx"),
    ],
)
async def test_document_outputs_generate_downloadable_artifacts(
    user, output_type: str, expected_mimetype: str, expected_ext: str
):
    """PDF/DOCX output types should persist artifact files with download metadata."""
    executor, _, _, _ = _build_executor(user)
    run = _run(status=FlowRunStatus.RUNNING, user=user)
    step = _runtime_step(output_type=output_type)

    stored_file = SimpleNamespace(id=uuid4())
    executor.file_repo.add = AsyncMock(return_value=stored_file)
    executor._load_assistant = AsyncMock(return_value=_mock_assistant_for_execute_step(response_text="Rapport"))

    output = await executor._execute_step(step=step, run=run)

    assert output.artifacts is not None
    assert len(output.artifacts) == 1
    artifact = output.artifacts[0]
    assert artifact["file_id"] == str(stored_file.id)
    assert artifact["mimetype"] == expected_mimetype
    assert artifact["name"].endswith(expected_ext)
    assert artifact["size"] > 0


@pytest.mark.asyncio
async def test_docx_output_handles_empty_assistant_response(user):
    """Empty markdown output should still create a valid DOCX artifact."""
    executor, _, _, _ = _build_executor(user)
    run = _run(status=FlowRunStatus.RUNNING, user=user)
    step = _runtime_step(output_type="docx")

    stored_file = SimpleNamespace(id=uuid4())
    executor.file_repo.add = AsyncMock(return_value=stored_file)
    executor._load_assistant = AsyncMock(return_value=_mock_assistant_for_execute_step(response_text=""))

    output = await executor._execute_step(step=step, run=run)

    assert output.artifacts is not None
    assert output.artifacts[0]["file_id"] == str(stored_file.id)
    assert output.artifacts[0]["mimetype"] == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


# --- _parse_runtime_steps extended fields ---


def test_parse_runtime_steps_includes_typed_fields():
    """Parsed RuntimeStep should include output_type, output_contract, input_type, input_contract."""
    steps = FlowRunExecutor._parse_runtime_steps({
        "steps": [
            {
                "step_id": str(uuid4()),
                "step_order": 1,
                "assistant_id": str(uuid4()),
                "input_source": "flow_input",
                "output_mode": "pass_through",
                "output_type": "json",
                "output_contract": {"type": "object"},
                "input_type": "document",
                "input_contract": {"type": "string"},
            }
        ]
    })
    assert steps[0].output_type == "json"
    assert steps[0].output_contract == {"type": "object"}
    assert steps[0].input_type == "document"
    assert steps[0].input_contract == {"type": "string"}


def test_parse_runtime_steps_defaults_typed_fields():
    """When typed fields are missing from snapshot, default to text/None."""
    steps = FlowRunExecutor._parse_runtime_steps({
        "steps": [
            {
                "step_id": str(uuid4()),
                "step_order": 1,
                "assistant_id": str(uuid4()),
                "input_source": "flow_input",
                "output_mode": "pass_through",
            }
        ]
    })
    assert steps[0].output_type == "text"
    assert steps[0].output_contract is None
    assert steps[0].input_type == "text"
    assert steps[0].input_contract is None


# --- Audit logging tests for HTTP input ---


@pytest.mark.asyncio
async def test_http_input_audit_logged_on_success(user):
    audit_service = AsyncMock()
    audit_service.log_async = AsyncMock(return_value=None)
    executor, _, _, _ = _build_executor(user)
    executor.audit_service = audit_service
    run = _run(status=FlowRunStatus.RUNNING, user=user, input_payload={"text": "hello"})
    step = _runtime_step(
        input_source="http_get",
        input_type="text",
        input_config={"url": "https://example.org/data"},
    )
    request = httpx.Request("GET", "https://example.org/data")
    executor._send_http_request = AsyncMock(
        return_value=httpx.Response(200, request=request, text="fetched")
    )
    context = executor.variable_resolver.build_context(run.input_payload_json, [])

    await executor._resolve_step_input(
        step=step, context=context, run=run, prior_results=[],
    )

    audit_service.log_async.assert_awaited_once()
    call_kwargs = audit_service.log_async.await_args.kwargs
    assert call_kwargs["action"] == ActionType.FLOW_HTTP_OUTBOUND_CALL
    assert call_kwargs["outcome"] == Outcome.SUCCESS
    extra = call_kwargs["metadata"]["extra"]
    assert extra["call_type"] == "http_input"
    assert extra["http_method"] == "GET"
    assert extra["status_code"] == 200
    assert "duration_ms" in extra


# --- Encrypted header tests for HTTP input ---


@pytest.mark.asyncio
async def test_resolve_http_input_decrypts_encrypted_headers(user):
    executor, _, _, _ = _build_executor(user)
    executor.encryption_service.is_encrypted = MagicMock(
        side_effect=lambda v: v.startswith("enc:")
    )
    executor.encryption_service.decrypt = MagicMock(
        side_effect=lambda v: v[len("enc:"):]
    )
    run = _run(status=FlowRunStatus.RUNNING, user=user, input_payload={"text": "x"})
    step = _runtime_step(
        input_source="http_get",
        input_type="text",
        input_config={
            "url": "https://example.org/data",
            "headers": {"Authorization": "enc:Bearer token456", "X-Plain": "visible"},
        },
    )
    request = httpx.Request("GET", "https://example.org/data")
    executor._send_http_request = AsyncMock(
        return_value=httpx.Response(200, request=request, text="ok")
    )
    context = executor.variable_resolver.build_context(run.input_payload_json, [])

    await executor._resolve_step_input(
        step=step, context=context, run=run, prior_results=[],
    )

    executor._send_http_request.assert_awaited_once()
    headers = executor._send_http_request.await_args.kwargs["headers"]
    assert headers["Authorization"] == "Bearer token456"
    assert headers["X-Plain"] == "visible"
    executor.encryption_service.decrypt.assert_called_once_with("enc:Bearer token456")
