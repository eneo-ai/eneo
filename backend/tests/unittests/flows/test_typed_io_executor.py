"""TDD tests for typed I/O in the flow executor — RED phase.

These tests exercise the typed pipeline: JSON output, PDF/DOCX rendering,
input contract validation, file resolution, canary flag, error propagation.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from intric.flows.flow import (
    FlowRun,
    FlowRunStatus,
    FlowStepResult,
    FlowStepResultStatus,
)
from intric.flows.runtime.executor import FlowRunExecutor, RuntimeStep, StepInputValue
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


def _build_executor(user):
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
        max_inline_text_bytes=1024 * 1024,
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
) -> RuntimeStep:
    return RuntimeStep(
        step_id=uuid4(),
        step_order=step_order,
        assistant_id=uuid4(),
        input_source=input_source,
        input_bindings=input_bindings,
        input_config=None,
        output_mode="pass_through",
        output_config=None,
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


# --- Runtime guards for unsupported types ---


@pytest.mark.asyncio
async def test_audio_input_blocked_runtime(user):
    """Audio input type raises at runtime (always active, no canary flag)."""
    executor, _, _, _ = _build_executor(user)
    run = _run(status=FlowRunStatus.RUNNING, user=user)
    step = _runtime_step(input_type="audio")

    mock_assistant = AsyncMock()
    mock_assistant.get_prompt_text.return_value = ""
    executor._load_assistant = AsyncMock(return_value=mock_assistant)

    with pytest.raises(TypedIOValidationException, match="not yet supported"):
        await executor._execute_step(step=step, run=run)


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
