"""TDD tests for typed I/O in the flow executor — RED phase.

These tests exercise the typed pipeline: JSON output, PDF/DOCX rendering,
input contract validation, file resolution, canary flag, error propagation.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx
import pytest

import eneo.flows.runtime.executor as executor_module
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.outcome import Outcome
from eneo.authentication.principal_types import PrincipalType
from eneo.files.text import PDF_TEXT_LIKELY_REVERSED_WARNING
from eneo.flows.domain.flow import (
    FlowRun,
    FlowRunStatus,
    FlowStepResult,
    FlowStepResultStatus,
    RerunStepInputOverride,
)
from eneo.flows.flow_run_input_envelope import (
    RerunInputOverride,
    build_rerun_execution_input_envelope,
)
from eneo.flows.runtime.document_rendering.limits import DocumentRenderLimits
from eneo.flows.runtime.executor import (
    FlowRunExecutor,
    RunExecutionState,
    RuntimeStep,
    StepInputValue,
)
from eneo.flows.runtime.flow_run_actor import FlowRunActor
from eneo.flows.runtime.models import OUTPUT_TEXT_OVERFLOW_KEY
from eneo.flows.runtime.output_formats import resolve_format_spec
from eneo.flows.runtime.output_formats.base import append_output_format_instructions
from eneo.flows.runtime.step_input_resolution import (
    RUNTIME_INPUT_SOURCE_EMPTY_TEXT_DIAGNOSTIC_CODE,
    RUNTIME_INPUT_SOURCE_EMPTY_TEXT_PLACEHOLDER,
)
from eneo.main.exceptions import TypedIOValidationException


def _run(*, status: FlowRunStatus, user, input_payload=None) -> FlowRun:
    now = datetime.now(timezone.utc)
    return FlowRun(
        id=uuid4(),
        flow_id=uuid4(),
        flow_version=1,
        principal_type=PrincipalType.USER,
        principal_user_id=user.id,
        tenant_id=user.tenant_id,
        trace_id=uuid4(),
        status=status,
        cancelled_at=None,
        input_payload_json=(
            input_payload if input_payload is not None else {"text": "hello"}
        ),
        output_payload_json=None,
        job_id=None,
        created_at=now,
        updated_at=now,
    )


def _build_executor(user, *, max_inline_text_bytes: int = 1024 * 1024):
    flow_repo = AsyncMock()
    session = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    flow_run_repo = AsyncMock()
    flow_run_rerun_repo = AsyncMock()
    flow_run_repo.list_step_input_file_ids = AsyncMock(return_value=[])
    flow_version_repo = AsyncMock()
    flow_run_review_checkpoint_repo = AsyncMock()
    space_repo = AsyncMock()
    completion_service = AsyncMock()
    file_repo = AsyncMock()
    template_asset_repo = AsyncMock()
    encryption_service = AsyncMock()
    flow_run_terminalizer = SimpleNamespace()

    async def _terminalize_run(**kwargs):
        return SimpleNamespace(
            run=SimpleNamespace(status=kwargs["target_status"]),
            did_transition=True,
            target_status=kwargs["target_status"],
            source=kwargs["source"],
            audit_outbox_id=uuid4(),
        )

    flow_run_terminalizer.terminalize_run = AsyncMock(side_effect=_terminalize_run)
    executor = FlowRunExecutor(
        runtime_actor=FlowRunActor.from_user(user=user),
        session=session,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_rerun_repo=flow_run_rerun_repo,
        flow_run_review_checkpoint_repo=flow_run_review_checkpoint_repo,
        flow_version_repo=flow_version_repo,
        space_repo=space_repo,
        completion_service=completion_service,
        file_repo=file_repo,
        template_asset_repo=template_asset_repo,
        encryption_service=encryption_service,
        flow_run_terminalizer=flow_run_terminalizer,
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
    if input_config is None and input_type in {"document", "file"}:
        input_config = {"runtime_input": {"enabled": True, "input_format": "document"}}
    if input_config is None and input_type == "audio":
        input_config = {"runtime_input": {"enabled": True, "input_format": "audio"}}
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


def _completed_step_result(
    *,
    run_id,
    flow_id,
    tenant_id,
    step_order: int,
    text: str,
    structured: dict | list | None = None,
    text_overflow: dict | None = None,
) -> FlowStepResult:
    now = datetime.now(timezone.utc)
    payload: dict[str, object] = {"text": text}
    if structured is not None:
        payload["structured"] = structured
    if text_overflow is not None:
        payload[OUTPUT_TEXT_OVERFLOW_KEY] = text_overflow
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
        flow_step_execution_hash="hash",
        created_at=now,
        updated_at=now,
    )


def _mock_assistant_for_execute_step(*, response_text: str = "ok") -> MagicMock:
    assistant = MagicMock()
    assistant.get_prompt_text.return_value = ""
    assistant.completion_model_kwargs = MagicMock()
    assistant.completion_model_kwargs.model_copy.return_value = (
        assistant.completion_model_kwargs
    )
    assistant.completion_model_kwargs.model_dump.return_value = {}
    assistant.completion_model = SimpleNamespace(
        id=uuid4(),
        name="test",
        provider_type="test",
        litellm_model_name=None,
    )
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
            text_overflow={
                "generated_file_ids": [str(uuid4())],
                "inline_text_bytes": 12,
                "full_text_bytes": 8192,
            },
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
    assert resolved.text == json.dumps(
        {"full": "data", "not_truncated": True}, ensure_ascii=False
    )


@pytest.mark.asyncio
async def test_resolve_step_input_json_question_binding_overrides_previous_structured(
    user,
):
    executor, _, _, _ = _build_executor(user)
    run = _run(status=FlowRunStatus.RUNNING, user=user)
    prior = [
        _completed_step_result(
            run_id=run.id,
            flow_id=run.flow_id,
            tenant_id=run.tenant_id,
            step_order=1,
            text="Transkription med mötesinnehåll.",
        ),
        _completed_step_result(
            run_id=run.id,
            flow_id=run.flow_id,
            tenant_id=run.tenant_id,
            step_order=2,
            text='{"final_report":"Saknar underlag"}',
            structured={"final_report": "Saknar underlag"},
        ),
    ]
    step = _runtime_step(
        step_order=3,
        input_source="previous_step",
        input_type="json",
        input_bindings={
            "question": (
                "Slutrapport: {{ step_2.output.structured.final_report }}\n\n"
                "Transkribering: {{ step_1.output.text }}"
            )
        },
    )
    context = executor.variable_resolver.build_context(run.input_payload_json, prior)

    resolved = await executor._resolve_step_input(
        step=step,
        context=context,
        run=run,
        prior_results=prior,
    )

    assert resolved.text == (
        "Slutrapport: Saknar underlag\n\n"
        "Transkribering: Transkription med mötesinnehåll."
    )
    assert resolved.structured is None
    assert resolved.used_question_binding is True
    summaries = [d for d in resolved.diagnostics if d.code == "flow_underlag_summary"]
    assert len(summaries) == 1


@pytest.mark.asyncio
async def test_resolve_step_input_question_binding_rejects_capped_text_ref(user):
    executor, _, _, _ = _build_executor(user)
    run = _run(status=FlowRunStatus.RUNNING, user=user)
    prior = [
        _completed_step_result(
            run_id=run.id,
            flow_id=run.flow_id,
            tenant_id=run.tenant_id,
            step_order=1,
            text="truncated",
            text_overflow={
                "generated_file_ids": [str(uuid4())],
                "inline_text_bytes": 9,
                "full_text_bytes": 8192,
            },
        )
    ]
    step = _runtime_step(
        step_order=2,
        input_source="flow_input",
        input_type="text",
        input_bindings={"question": "Transkribering: {{ step_1.output.text }}"},
    )
    context = executor.variable_resolver.build_context(run.input_payload_json, prior)

    with pytest.raises(TypedIOValidationException) as exc:
        await executor._resolve_step_input(
            step=step,
            context=context,
            run=run,
            prior_results=prior,
        )

    assert exc.value.code == "typed_io_input_too_large"
    assert "input_bindings.question" in str(exc.value)
    assert "step 1 text" in str(exc.value)


@pytest.mark.asyncio
async def test_resolve_step_input_json_previous_step_parses_text_when_structured_missing(
    user,
):
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
async def test_resolve_step_input_json_previous_step_structured_only_emits_underlag_summary(
    user,
):
    executor, _, _, _ = _build_executor(user)
    run = _run(status=FlowRunStatus.RUNNING, user=user)
    prior = [
        _completed_step_result(
            run_id=run.id,
            flow_id=run.flow_id,
            tenant_id=run.tenant_id,
            step_order=1,
            text="",
            structured={"k": 1},
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

    assert resolved.source_text == ""
    assert resolved.text == json.dumps({"k": 1}, ensure_ascii=False)
    assert not any(d.code == "empty_prior_step_input" for d in resolved.diagnostics)
    summaries = [d for d in resolved.diagnostics if d.code == "flow_underlag_summary"]
    assert len(summaries) == 1
    assert summaries[0].severity == "info"


@pytest.mark.asyncio
async def test_resolve_step_input_json_previous_step_summary_counts_resolved_input_bytes(
    user,
):
    executor, _, _, _ = _build_executor(user)
    run = _run(status=FlowRunStatus.RUNNING, user=user)
    compact_text = '{"a":1}'
    structured = {"a": 1}
    prior = [
        _completed_step_result(
            run_id=run.id,
            flow_id=run.flow_id,
            tenant_id=run.tenant_id,
            step_order=1,
            text=compact_text,
            structured=structured,
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

    expected_text = json.dumps(structured, ensure_ascii=False)
    summaries = [d for d in resolved.diagnostics if d.code == "flow_underlag_summary"]
    assert resolved.source_text == '{"a":1}'
    assert resolved.text == expected_text
    assert len(summaries) == 1
    assert f"{len(expected_text.encode('utf-8'))} bytes" in summaries[0].message
    assert f"{len(compact_text.encode('utf-8'))} bytes" not in summaries[0].message


@pytest.mark.asyncio
async def test_resolve_step_input_document_loads_files(user):
    """When input_type=document with file_ids, files are loaded and text is extracted."""
    executor, _, _, _ = _build_executor(user)
    file_id = uuid4()
    step = _runtime_step(input_type="document")
    run = _run(
        status=FlowRunStatus.RUNNING,
        user=user,
        input_payload={"text": "fallback"},
    )
    fake_file = SimpleNamespace(
        id=file_id,
        text="Extracted document text",
        name="underlag.pdf",
        checksum="checksum-1",
        size=128,
        mimetype="application/pdf",
        file_type="document",
        transcription=None,
    )
    executor.file_repo.get_list_by_id_for_owner = AsyncMock(return_value=[fake_file])

    context = executor.variable_resolver.build_context(run.input_payload_json, [])

    resolved = await executor._resolve_step_input(
        step=step,
        context=context,
        run=run,
        prior_results=[],
        requested_file_ids=[file_id],
    )

    labeled_text = "[SOURCE 1]\nfile_name: underlag.pdf\n\nExtracted document text"
    assert resolved.files == [fake_file]
    assert resolved.text == f"{labeled_text}\n\nfallback"
    assert resolved.runtime_input_metadata == {
        "text": labeled_text,
        "file_ids": [str(file_id)],
        "files_count": 1,
        "files": [
            {
                "id": str(file_id),
                "name": "underlag.pdf",
                "checksum": "checksum-1",
                "size": 128,
                "mimetype": "application/pdf",
                "file_type": "document",
                "text_length": len("Extracted document text"),
                "has_text": True,
                "has_transcription": False,
                "extraction_warnings": [],
            }
        ],
        "source_headers": [
            {
                "source_number": 1,
                "source_label": "underlag.pdf",
                "source_marker": "[SOURCE 1]",
                "file_id": str(file_id),
                "file_name": "underlag.pdf",
                "has_file_name": True,
                "has_text": True,
                "text_length": len("Extracted document text"),
                "extraction_warnings": [],
            }
        ],
        "total_file_size": 128,
        "extracted_text_length": len(labeled_text),
        "input_format": "document",
        "capture_mode": "runtime_input",
    }


@pytest.mark.asyncio
async def test_resolve_step_input_document_labels_multiple_files_in_requested_order(
    user,
):
    executor, _, _, _ = _build_executor(user)
    first_file_id = uuid4()
    second_file_id = uuid4()
    step = _runtime_step(input_type="document")
    run = _run(
        status=FlowRunStatus.RUNNING,
        user=user,
        input_payload={},
    )
    first_file = SimpleNamespace(
        id=first_file_id,
        text="[PAGE 1]\nFirst file text",
        name="first.pdf",
        checksum="checksum-1",
        size=100,
        mimetype="application/pdf",
        file_type="document",
        transcription=None,
    )
    second_file = SimpleNamespace(
        id=second_file_id,
        text="[PAGE 1]\nSecond file text",
        name="second.pdf",
        checksum="checksum-2",
        size=200,
        mimetype="application/pdf",
        file_type="document",
        transcription=None,
    )
    executor.file_repo.get_list_by_id_for_owner = AsyncMock(
        return_value=[second_file, first_file]
    )
    context = executor.variable_resolver.build_context(run.input_payload_json, [])

    resolved = await executor._resolve_step_input(
        step=step,
        context=context,
        run=run,
        prior_results=[],
        requested_file_ids=[first_file_id, second_file_id],
    )

    assert resolved.files == [first_file, second_file]
    assert resolved.text == (
        "[SOURCE 1]\n"
        "file_name: first.pdf\n\n"
        "[PAGE 1]\n"
        "First file text\n\n"
        "[SOURCE 2]\n"
        "file_name: second.pdf\n\n"
        "[PAGE 1]\n"
        "Second file text"
    )
    assert resolved.runtime_input_metadata is not None
    assert resolved.runtime_input_metadata["text"] == resolved.text
    assert resolved.runtime_input_metadata["file_ids"] == [
        str(first_file_id),
        str(second_file_id),
    ]


@pytest.mark.asyncio
async def test_resolve_step_input_document_preserves_empty_source_slot(
    user,
    caplog,
):
    executor, _, _, _ = _build_executor(user)
    first_file_id = uuid4()
    second_file_id = uuid4()
    step = _runtime_step(input_type="document")
    run = _run(
        status=FlowRunStatus.RUNNING,
        user=user,
        input_payload={},
    )
    first_file = SimpleNamespace(
        id=first_file_id,
        text="First file text",
        name="first.pdf",
        checksum="checksum-1",
        size=100,
        mimetype="application/pdf",
        file_type="document",
        transcription=None,
    )
    second_file = SimpleNamespace(
        id=second_file_id,
        text="   ",
        name="second.pdf",
        checksum="checksum-2",
        size=200,
        mimetype="application/pdf",
        file_type="document",
        transcription=None,
    )
    executor.file_repo.get_list_by_id_for_owner = AsyncMock(
        return_value=[first_file, second_file]
    )
    context = executor.variable_resolver.build_context(run.input_payload_json, [])

    with caplog.at_level("WARNING"):
        resolved = await executor._resolve_step_input(
            step=step,
            context=context,
            run=run,
            prior_results=[],
            requested_file_ids=[first_file_id, second_file_id],
        )

    assert resolved.text == (
        "[SOURCE 1]\n"
        "file_name: first.pdf\n\n"
        "First file text\n\n"
        "[SOURCE 2]\n"
        "file_name: second.pdf\n\n"
        f"{RUNTIME_INPUT_SOURCE_EMPTY_TEXT_PLACEHOLDER}"
    )
    assert resolved.runtime_input_metadata is not None
    assert resolved.runtime_input_metadata["text"] == resolved.text
    assert resolved.runtime_input_metadata["files"][1]["has_text"] is False
    assert len(resolved.diagnostics) == 1
    diagnostic = resolved.diagnostics[0]
    assert diagnostic.code == RUNTIME_INPUT_SOURCE_EMPTY_TEXT_DIAGNOSTIC_CODE
    assert diagnostic.severity == "warning"
    assert "[SOURCE 2] (second.pdf)" in diagnostic.message
    assert "flow_executor.runtime_input_source_text_unavailable" in caplog.text


@pytest.mark.asyncio
async def test_resolve_step_input_document_warns_when_pdf_text_looks_reversed(
    user,
    caplog,
):
    executor, _, _, _ = _build_executor(user)
    file_id = uuid4()
    step = _runtime_step(input_type="document")
    run = _run(
        status=FlowRunStatus.RUNNING,
        user=user,
        input_payload={},
    )
    reversed_words = "hco tta ted ned mos dem llit relle aks rah nak etni "
    fake_file = SimpleNamespace(
        id=file_id,
        text=f"[PAGE 1]\n{reversed_words * 4}",
        name="reversed.pdf",
        checksum="checksum-1",
        size=128,
        mimetype="application/pdf",
        file_type="document",
        transcription=None,
    )
    executor.file_repo.get_list_by_id_for_owner = AsyncMock(return_value=[fake_file])
    context = executor.variable_resolver.build_context(run.input_payload_json, [])

    with caplog.at_level("WARNING"):
        resolved = await executor._resolve_step_input(
            step=step,
            context=context,
            run=run,
            prior_results=[],
            requested_file_ids=[file_id],
        )

    assert len(resolved.diagnostics) == 1
    diagnostic = resolved.diagnostics[0]
    assert diagnostic.code == PDF_TEXT_LIKELY_REVERSED_WARNING
    assert diagnostic.severity == "warning"
    assert "[SOURCE 1] (reversed.pdf)" in diagnostic.message
    assert "looks reversed or garbled" in diagnostic.message
    assert resolved.runtime_input_metadata is not None
    assert resolved.runtime_input_metadata["files"][0]["extraction_warnings"] == [
        PDF_TEXT_LIKELY_REVERSED_WARNING
    ]
    assert resolved.runtime_input_metadata["source_headers"][0][
        "extraction_warnings"
    ] == [PDF_TEXT_LIKELY_REVERSED_WARNING]
    assert "flow_executor.runtime_input_source_extraction_warning" in caplog.text


@pytest.mark.asyncio
async def test_resolve_step_input_document_rejects_extracted_text_over_inline_cap(user):
    """Document extraction larger than max inline bytes should fail deterministically."""
    executor, _, _, _ = _build_executor(user, max_inline_text_bytes=8)
    file_id = uuid4()
    step = _runtime_step(input_type="document")
    run = _run(
        status=FlowRunStatus.RUNNING,
        user=user,
        input_payload={},
    )
    fake_file = SimpleNamespace(id=file_id, text="detta ar mycket langre an atta bytes")
    executor.file_repo.get_list_by_id_for_owner = AsyncMock(return_value=[fake_file])

    context = executor.variable_resolver.build_context(run.input_payload_json, [])

    with pytest.raises(TypedIOValidationException) as exc:
        await executor._resolve_step_input(
            step=step,
            context=context,
            run=run,
            prior_results=[],
            requested_file_ids=[file_id],
        )

    assert exc.value.code == "typed_io_input_too_large"


@pytest.mark.asyncio
async def test_resolve_step_input_file_ids_full_match_enforcement(user):
    """Missing file_id raises TypedIOValidationException."""
    executor, _, _, _ = _build_executor(user)
    file_id_1 = uuid4()
    file_id_2 = uuid4()
    step = _runtime_step(input_type="document")
    run = _run(
        status=FlowRunStatus.RUNNING,
        user=user,
        input_payload={"text": "x"},
    )
    # Only return one of the two requested files
    fake_file = SimpleNamespace(id=file_id_1, text="doc")
    executor.file_repo.get_list_by_id_for_owner = AsyncMock(return_value=[fake_file])

    context = executor.variable_resolver.build_context(run.input_payload_json, [])

    with pytest.raises(TypedIOValidationException, match="not found or not accessible"):
        await executor._resolve_step_input(
            step=step,
            context=context,
            run=run,
            prior_results=[],
            requested_file_ids=[file_id_1, file_id_2],
        )


@pytest.mark.asyncio
async def test_resolve_step_input_ignores_removed_top_level_file_ids(user):
    executor, _, _, _ = _build_executor(user)
    file_id = uuid4()
    step = _runtime_step(input_type="document")
    run = _run(
        status=FlowRunStatus.RUNNING,
        user=user,
        input_payload={"text": "fallback", "file_ids": [str(file_id)]},
    )
    context = executor.variable_resolver.build_context(run.input_payload_json, [])

    resolved = await executor._resolve_step_input(
        step=step,
        context=context,
        run=run,
        prior_results=[],
    )

    assert resolved.files is None
    assert resolved.text == "fallback"
    executor.file_repo.get_list_by_id_for_owner.assert_not_awaited()


@pytest.mark.asyncio
async def test_resolve_step_input_uses_relational_selection_over_stale_payload(user):
    executor, _, _, _ = _build_executor(user)
    old_file_id = uuid4()
    new_file_id = uuid4()
    step = _runtime_step(input_type="document")
    execution_payload = build_rerun_execution_input_envelope(
        current={
            "case_id": "before",
            "step_inputs": {str(step.step_id): {"file_ids": [str(old_file_id)]}},
        },
        override=RerunInputOverride(
            inline_payload_json={"case_id": "after"},
            root_step_input=RerunStepInputOverride(
                step_id=step.step_id,
                file_ids=(new_file_id,),
            ),
        ),
    )
    run = _run(
        status=FlowRunStatus.RUNNING,
        user=user,
        input_payload=execution_payload,
    )
    fake_file = SimpleNamespace(
        id=new_file_id,
        text="Replacement file text",
        name="replacement.pdf",
        checksum="checksum-new",
        size=128,
        mimetype="application/pdf",
        file_type="document",
        transcription=None,
    )
    executor.file_repo.get_list_by_id_for_owner = AsyncMock(return_value=[fake_file])
    context = executor.variable_resolver.build_context(run.input_payload_json, [])

    resolved = await executor._resolve_step_input(
        step=step,
        context=context,
        run=run,
        prior_results=[],
        requested_file_ids=[new_file_id],
    )

    assert resolved.source_text == '{"case_id": "after"}'
    assert resolved.files == [fake_file]
    assert resolved.runtime_input_metadata is not None
    assert resolved.runtime_input_metadata["file_ids"] == [str(new_file_id)]
    assert str(old_file_id) not in json.dumps(
        resolved.runtime_input_metadata,
        ensure_ascii=False,
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


@pytest.mark.asyncio
@pytest.mark.parametrize("input_source", ["previous_step", "all_previous_steps"])
async def test_resolve_step_input_step_one_rejects_previous_sources(
    user, input_source: str
):
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
async def test_resolve_step_input_all_previous_steps_json_rejected_with_specific_code(
    user,
):
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
    step = _runtime_step(
        step_order=2, input_source="all_previous_steps", input_type="json"
    )
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
    step = _runtime_step(
        step_order=2, input_source="all_previous_steps", input_type="text"
    )
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
async def test_resolve_step_input_previous_step_with_content_emits_underlag_summary_info(
    user,
):
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
    assert not any(d.code == "empty_prior_step_input" for d in resolved.diagnostics)
    summaries = [d for d in resolved.diagnostics if d.code == "flow_underlag_summary"]
    assert len(summaries) == 1
    assert summaries[0].severity == "info"
    assert "previous_step" in summaries[0].message
    assert "step 1" in summaries[0].message
    assert "11 bytes" in summaries[0].message


@pytest.mark.asyncio
async def test_resolve_step_input_previous_step_rejects_capped_output_stub(user):
    executor, _, _, _ = _build_executor(user)
    run = _run(status=FlowRunStatus.RUNNING, user=user)
    prior = [
        _completed_step_result(
            run_id=run.id,
            flow_id=run.flow_id,
            tenant_id=run.tenant_id,
            step_order=1,
            text="truncated",
            text_overflow={
                "generated_file_ids": [str(uuid4())],
                "inline_text_bytes": 9,
                "full_text_bytes": 8192,
            },
        )
    ]
    step = _runtime_step(step_order=2, input_source="previous_step", input_type="text")
    context = executor.variable_resolver.build_context(run.input_payload_json, prior)

    with pytest.raises(TypedIOValidationException) as exc:
        await executor._resolve_step_input(
            step=step,
            context=context,
            run=run,
            prior_results=prior,
        )

    assert exc.value.code == "typed_io_input_too_large"
    assert "step 1 text" in str(exc.value)
    assert "generated output file" in str(exc.value)


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
    cached = _completed_step_result(
        run_id=run.id,
        flow_id=run.flow_id,
        tenant_id=run.tenant_id,
        step_order=1,
        text="cached",
    )
    state = RunExecutionState(
        completed_by_order={1: cached},
        prior_results=[cached],
        assistant_cache={},
        json_mode_supported={},
        file_cache={},
    )
    step = _runtime_step(
        step_order=2, input_source="all_previous_steps", input_type="text"
    )
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
    summaries = [d for d in resolved.diagnostics if d.code == "flow_underlag_summary"]
    assert len(summaries) == 1
    assert summaries[0].severity == "info"
    assert "all_previous_steps" in summaries[0].message
    assert "1 prior step" in summaries[0].message
    assert f"{len(resolved.text.encode('utf-8'))} bytes" in summaries[0].message


@pytest.mark.asyncio
async def test_resolve_step_input_all_previous_steps_rejects_capped_state_output(user):
    executor, _, _, _ = _build_executor(user)
    run = _run(status=FlowRunStatus.RUNNING, user=user)
    cached = _completed_step_result(
        run_id=run.id,
        flow_id=run.flow_id,
        tenant_id=run.tenant_id,
        step_order=1,
        text="truncated",
        text_overflow={
            "generated_file_ids": [str(uuid4())],
            "inline_text_bytes": 9,
            "full_text_bytes": 8192,
        },
    )
    state = RunExecutionState(
        completed_by_order={1: cached},
        prior_results=[cached],
        assistant_cache={},
        json_mode_supported={},
        file_cache={},
    )
    step = _runtime_step(
        step_order=2, input_source="all_previous_steps", input_type="text"
    )
    context = executor.variable_resolver.build_context(run.input_payload_json, [cached])

    with pytest.raises(TypedIOValidationException) as exc:
        await executor._resolve_step_input(
            step=step,
            context=context,
            run=run,
            prior_results=[cached],
            state=state,
        )

    assert exc.value.code == "typed_io_input_too_large"
    assert "all_previous_steps" in str(exc.value)
    assert "step 1 text" in str(exc.value)


@pytest.mark.asyncio
async def test_resolve_step_input_all_previous_steps_excludes_current_and_future_results(
    user,
):
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
    step = _runtime_step(
        step_order=3, input_source="all_previous_steps", input_type="text"
    )
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
    step = _runtime_step(
        step_order=3, input_source="all_previous_steps", input_type="text"
    )
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
            "auth": {"mode": "none"},
            "timeout_seconds": 7,
        },
    )
    request = httpx.Request("GET", "https://example.org/items/42?q=budget")
    executor._send_http_request = AsyncMock(
        return_value=httpx.Response(200, request=request, text="remote text")
    )
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
        input_config={"url": "https://example.org", "auth": {"mode": "none"}},
    )
    executor._send_http_request = AsyncMock(
        side_effect=httpx.TimeoutException("timeout")
    )
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
        input_config={"url": "https://example.org", "auth": {"mode": "none"}},
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
        input_config={"url": "https://example.org/json", "auth": {"mode": "none"}},
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
async def test_resolve_step_input_http_post_uses_authored_json_template_and_headers(
    user,
):
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
            "auth": {"mode": "none"},
            "timeout_seconds": 11,
            "custom_headers": [
                {
                    "name": "X-Request-Id",
                    "value": "{{flow_input.request_id}}",
                    "secret": False,
                }
            ],
            "body": {
                "mode": "json_template",
                "template": (
                    '{"citizen_name": "{{flow_input.payload.name}}", '
                    '"request_id": {{flow_input.request_id}}}'
                ),
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
async def test_resolve_step_input_http_post_rejects_flat_config_before_send(user):
    executor, _, _, _ = _build_executor(user)
    request = httpx.Request("POST", "https://example.org")
    executor._send_http_request = AsyncMock(
        return_value=httpx.Response(200, request=request, text="ok")
    )
    run = _run(status=FlowRunStatus.RUNNING, user=user, input_payload={"text": "x"})
    step = _runtime_step(
        input_source="http_post",
        input_type="text",
        input_config={"url": "https://example.org"},
    )
    context = executor.variable_resolver.build_context(run.input_payload_json, [])

    with pytest.raises(TypedIOValidationException, match="authored HTTP config") as exc:
        await executor._resolve_step_input(
            step=step,
            context=context,
            run=run,
            prior_results=[],
        )

    assert exc.value.code == "typed_io_http_invalid_config"
    executor._send_http_request.assert_not_awaited()


@pytest.mark.asyncio
async def test_resolve_step_input_rejects_literal_step_input_substring_when_runtime_input_enabled(
    user,
):
    executor, _, _, _ = _build_executor(user)
    file = SimpleNamespace(id=uuid4(), text="transkriberat innehåll")
    executor.file_repo.get_list_by_id_for_owner = AsyncMock(return_value=[file])
    run = _run(
        status=FlowRunStatus.RUNNING,
        user=user,
        input_payload={},
    )
    step = _runtime_step(
        step_order=1,
        input_source="flow_input",
        input_type="document",
        input_bindings={"question": "Literal step_input.text marker"},
        input_config={"runtime_input": {"enabled": True, "input_format": "document"}},
    )
    context = executor.variable_resolver.build_context(run.input_payload_json, [])

    with pytest.raises(TypedIOValidationException, match="step_input"):
        await executor._resolve_step_input(
            step=step,
            context=context,
            run=run,
            prior_results=[],
            requested_file_ids=[file.id],
        )


@pytest.mark.asyncio
async def test_resolve_step_input_runtime_input_does_not_append_internal_orchestration_metadata():
    user = SimpleNamespace(id=uuid4(), tenant_id=uuid4(), active_api_key=None)
    executor, _, _, _ = _build_executor(user)
    file = SimpleNamespace(id=uuid4(), text="runtime step upload test")
    executor.file_repo.get_list_by_id_for_owner = AsyncMock(return_value=[file])
    step = _runtime_step(
        step_order=1,
        input_source="flow_input",
        input_type="document",
        input_config={"runtime_input": {"enabled": True, "input_format": "document"}},
    )
    run = _run(
        status=FlowRunStatus.RUNNING,
        user=user,
        input_payload={"expected_flow_version": 9},
    )
    context = executor.variable_resolver.build_context(run.input_payload_json, [])

    resolved = await executor._resolve_step_input(
        step=step,
        context=context,
        run=run,
        prior_results=[],
        requested_file_ids=[file.id],
    )

    assert resolved.source_text == ""
    assert resolved.text == "[SOURCE 1]\n\nruntime step upload test"


@pytest.mark.asyncio
async def test_resolve_step_input_adds_underlag_summary_diagnostic(user):
    executor, _, _, _ = _build_executor(user)
    file = SimpleNamespace(id=uuid4(), text="transkriberat innehåll")
    executor.file_repo.get_list_by_id_for_owner = AsyncMock(return_value=[file])
    run = _run(
        status=FlowRunStatus.RUNNING,
        user=user,
        input_payload={},
    )
    step = _runtime_step(
        step_order=1,
        input_source="flow_input",
        input_type="document",
        input_bindings={"question": "UNDERLAG:\n{{ step_input.text }}"},
        input_config={"runtime_input": {"enabled": True, "input_format": "document"}},
    )
    context = executor.variable_resolver.build_context(run.input_payload_json, [])

    resolved = await executor._resolve_step_input(
        step=step,
        context=context,
        run=run,
        prior_results=[],
        requested_file_ids=[file.id],
    )

    assert any(d.code == "flow_underlag_summary" for d in resolved.diagnostics)


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
            return httpx.Request(
                method, url, headers=headers, content=content, json=json
            )

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
            raise AssertionError(
                "aiter_bytes should not be called when read_response_body=False"
            )

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
            return httpx.Request(
                method, url, headers=headers, content=content, json=json
            )

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
            return httpx.Request(
                method, url, headers=headers, content=content, json=json
            )

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
async def test_send_http_request_blocks_peer_not_in_preflight_resolution(
    user, monkeypatch
):
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
            return httpx.Request(
                method, url, headers=headers, content=content, json=json
            )

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
        assistant_cache={},
        json_mode_supported={},
        file_cache={},
    )
    executor._load_assistant = AsyncMock(
        return_value=_mock_assistant_for_execute_step()
    )

    with pytest.raises(TypedIOValidationException) as exc:
        await executor._execute_step(step=step, run=run, state=run_state, attempt_no=1)

    assert exc.value.code == "typed_io_audio_source_unsupported"


# --- Typed validation tests ---


@pytest.mark.asyncio
async def test_empty_document_extraction_uses_source_marker_not_payload_fallback(user):
    executor, _, _, _ = _build_executor(user)
    file_id = uuid4()
    step = _runtime_step(input_type="document")
    run = _run(
        status=FlowRunStatus.RUNNING,
        user=user,
        input_payload={"text": "fallback payload text"},
    )
    fake_file = SimpleNamespace(id=file_id, text="", name="empty.pdf")
    executor.file_repo.get_list_by_id_for_owner = AsyncMock(return_value=[fake_file])
    executor.flow_run_repo.list_step_input_file_ids = AsyncMock(return_value=[file_id])
    executor._load_assistant = AsyncMock(
        return_value=_mock_assistant_for_execute_step()
    )

    output = (await executor._execute_step(step=step, run=run, attempt_no=1)).output

    assert output.input_text == (
        "[SOURCE 1]\n"
        "file_name: empty.pdf\n\n"
        f"{RUNTIME_INPUT_SOURCE_EMPTY_TEXT_PLACEHOLDER}\n\n"
        "fallback payload text"
    )
    assert output.input_text != "fallback payload text"
    assert output.diagnostics[0].code == RUNTIME_INPUT_SOURCE_EMPTY_TEXT_DIAGNOSTIC_CODE
    assert output.runtime_input_metadata is not None
    assert output.runtime_input_metadata["files"][0]["has_text"] is False


@pytest.mark.asyncio
async def test_file_input_uses_extracted_file_text(user):
    """File input should use extracted file text and pass extraction guard."""
    executor, _, _, _ = _build_executor(user)
    file_id = uuid4()
    step = _runtime_step(input_type="file")
    run = _run(
        status=FlowRunStatus.RUNNING,
        user=user,
        input_payload={},
    )
    fake_file = SimpleNamespace(id=file_id, text="Extracted file text")
    executor.file_repo.get_list_by_id_for_owner = AsyncMock(return_value=[fake_file])
    executor.flow_run_repo.list_step_input_file_ids = AsyncMock(return_value=[file_id])
    executor._load_assistant = AsyncMock(
        return_value=_mock_assistant_for_execute_step()
    )

    output = (await executor._execute_step(step=step, run=run, attempt_no=1)).output

    assert output.input_text == "[SOURCE 1]\n\nExtracted file text"
    assert output.full_text == "ok"


@pytest.mark.asyncio
async def test_per_source_reader_executes_one_model_call_per_file_and_sets_identity(user):
    executor, _, flow_run_repo, _ = _build_executor(user)
    first_file_id = uuid4()
    second_file_id = uuid4()
    first_file = SimpleNamespace(
        id=first_file_id,
        text="Alpha document text",
        name="alpha.pdf",
        checksum="checksum-a",
        size=100,
        mimetype="application/pdf",
        file_type="document",
        transcription=None,
    )
    second_file = SimpleNamespace(
        id=second_file_id,
        text="Beta document text",
        name="alpha.pdf",
        checksum="checksum-b",
        size=200,
        mimetype="application/pdf",
        file_type="document",
        transcription=None,
    )
    files_by_id = {first_file_id: first_file, second_file_id: second_file}

    async def get_files_by_id(*, ids, **_kwargs):
        return [files_by_id[file_id] for file_id in ids]

    executor.file_repo.get_list_by_id_for_owner = AsyncMock(side_effect=get_files_by_id)
    flow_run_repo.list_step_input_file_ids = AsyncMock(
        return_value=[first_file_id, second_file_id]
    )
    assistant = _mock_assistant_for_execute_step()
    assistant.get_response = AsyncMock(
        side_effect=[
            SimpleNamespace(
                completion=(
                    '{"documents":[{"source_label":"uploaded_source_1",'
                    '"source_file_id":"unspecified","title":"Alpha"}]}'
                ),
                total_token_count=11,
            ),
            SimpleNamespace(
                completion=(
                    '{"documents":[{"source_label":"uploaded_source_2",'
                    '"source_file_id":"unspecified","title":"Beta"}]}'
                ),
                total_token_count=13,
            ),
        ]
    )
    executor._load_assistant = AsyncMock(return_value=assistant)
    original_prepare = executor._prepare_assistant_step
    prepare_in_progress = False

    async def guarded_prepare(**kwargs):
        nonlocal prepare_in_progress
        assert prepare_in_progress is False
        prepare_in_progress = True
        await asyncio.sleep(0)
        try:
            return await original_prepare(**kwargs)
        finally:
            prepare_in_progress = False

    executor._prepare_assistant_step = guarded_prepare
    output_contract = {
        "type": "object",
        "properties": {
            "documents": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "source_label": {"type": "string"},
                        "source_file_id": {"type": "string"},
                        "title": {"type": "string"},
                    },
                    "required": ["source_label", "source_file_id", "title"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["documents"],
        "additionalProperties": False,
    }
    step = _runtime_step(
        input_type="document",
        output_type="json",
        output_contract=output_contract,
        input_config={
            "runtime_input": {
                "enabled": True,
                "input_format": "document",
                "execution_mode": "per_source",
            }
        },
    )
    run = _run(status=FlowRunStatus.RUNNING, user=user, input_payload={})

    output = (await executor._execute_step(step=step, run=run, attempt_no=1)).output

    assert assistant.get_response.await_count == 2
    questions = [
        call.kwargs["question"] for call in assistant.get_response.await_args_list
    ]
    assert any("Alpha document text" in question for question in questions)
    assert any("Beta document text" in question for question in questions)
    assert not any("source_label" in question for question in questions)
    assert not any("source_file_id" in question for question in questions)
    assert not any(
        "Alpha document text" in question and "Beta document text" in question
        for question in questions
    )
    assert output.structured_output == {
        "documents": [
            {
                "title": "Alpha",
                "source_label": "alpha.pdf",
                "source_file_id": str(first_file_id),
            },
            {
                "title": "Beta",
                "source_label": "alpha.pdf (2)",
                "source_file_id": str(second_file_id),
            },
        ]
    }
    assert output.runtime_input_metadata is not None
    assert output.runtime_input_metadata["capture_mode"] == "runtime_input_per_source"
    assert output.runtime_input_metadata["file_ids"] == [
        str(first_file_id),
        str(second_file_id),
    ]
    assert len(output.runtime_input_metadata["per_source_calls"]) == 2


@pytest.mark.asyncio
async def test_per_source_config_fails_closed_when_step_is_not_document_reader(user):
    executor, _, _, _ = _build_executor(user)
    step = _runtime_step(
        input_type="document",
        output_type="text",
        input_config={
            "runtime_input": {
                "enabled": True,
                "input_format": "document",
                "execution_mode": "per_source",
            }
        },
    )
    run = _run(status=FlowRunStatus.RUNNING, user=user, input_payload={})

    with pytest.raises(TypedIOValidationException) as exc:
        await executor._execute_step(step=step, run=run, attempt_no=1)

    assert exc.value.code == "typed_io_contract_violation"


@pytest.mark.asyncio
async def test_per_item_map_executes_one_model_call_per_previous_document_at_scale(
    user,
):
    executor, _, _, _ = _build_executor(user)
    documents = [
        {
            "title": f"Document {index}",
            "summary": f"document-{index:02d}-unique-marker",
            "source_label": f"source-{index:02d}.pdf",
            "source_file_id": f"file-{index:02d}",
        }
        for index in range(1, 41)
    ]
    assistant = _mock_assistant_for_execute_step()
    assistant.get_response = AsyncMock(
        side_effect=[
            SimpleNamespace(
                completion=(
                    '{"sections":[{"heading":"Document '
                    f'{index}","body":"Section {index}"}}]}}'
                ),
                total_token_count=index,
            )
            for index in range(1, 41)
        ]
    )
    executor._load_assistant = AsyncMock(return_value=assistant)
    run = _run(status=FlowRunStatus.RUNNING, user=user, input_payload={})
    previous = _completed_step_result(
        run_id=run.id,
        flow_id=run.flow_id,
        tenant_id=run.tenant_id,
        step_order=1,
        text='{"documents":[]}',
        structured={"documents": documents},
    )
    state = RunExecutionState(
        completed_by_order={1: previous},
        prior_results=[previous],
        assistant_cache={},
        json_mode_supported={},
        file_cache={},
    )
    step = _runtime_step(
        step_order=2,
        input_source="previous_step",
        input_type="json",
        input_contract={
            "type": "object",
            "properties": {
                "documents": {
                    "type": "array",
                    "items": {"type": "object"},
                }
            },
            "required": ["documents"],
        },
        output_type="json",
        output_contract={
            "type": "object",
            "properties": {
                "sections": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "heading": {"type": "string"},
                            "body": {"type": "string"},
                        },
                        "required": ["heading", "body"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["sections"],
            "additionalProperties": False,
        },
        input_config={"item_map": {"enabled": True}},
    )

    output = (
        await executor._execute_step(step=step, run=run, state=state, attempt_no=1)
    ).output

    assert assistant.get_response.await_count == 40
    questions = [
        call.kwargs["question"] for call in assistant.get_response.await_args_list
    ]
    for index, question in enumerate(questions, start=1):
        assert f"document-{index:02d}-unique-marker" in question
        for other_index in range(1, 41):
            if other_index == index:
                continue
            assert f"document-{other_index:02d}-unique-marker" not in question
    assert output.structured_output == {
        "sections": [
            {"heading": f"Document {index}", "body": f"Section {index}"}
            for index in range(1, 41)
        ]
    }
    assert output.model_parameters_json["item_map_execution_mode"] == "per_item"
    assert output.model_parameters_json["per_item_call_count"] == 40
    assert output.num_tokens_input == sum(range(1, 41))
    assert output.runtime_input_metadata is not None
    assert output.runtime_input_metadata["capture_mode"] == "previous_step_item_map"
    assert output.runtime_input_metadata["item_count"] == 40
    assert len(output.runtime_input_metadata["per_item_calls"]) == 40


@pytest.mark.asyncio
async def test_per_item_map_config_fails_closed_when_step_is_not_previous_json(user):
    executor, _, _, _ = _build_executor(user)
    step = _runtime_step(
        input_source="flow_input",
        input_type="text",
        output_type="json",
        output_contract={
            "type": "object",
            "properties": {"sections": {"type": "array", "items": {"type": "object"}}},
            "required": ["sections"],
        },
        input_config={"item_map": {"enabled": True}},
    )
    run = _run(status=FlowRunStatus.RUNNING, user=user, input_payload={})

    with pytest.raises(TypedIOValidationException) as exc:
        await executor._execute_step(step=step, run=run, attempt_no=1)

    assert exc.value.code == "typed_io_contract_violation"


@pytest.mark.asyncio
async def test_document_previous_step_rejected_with_specific_code(user):
    """Legacy snapshots using previous_step+document should fail deterministically."""
    executor, _, _, _ = _build_executor(user)
    run = _run(status=FlowRunStatus.RUNNING, user=user)
    step = _runtime_step(
        step_order=2, input_source="previous_step", input_type="document"
    )
    # Build state with one completed previous result.
    from eneo.flows.runtime.executor import RunExecutionState

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
        assistant_cache={},
        json_mode_supported={},
        file_cache={},
    )
    executor._load_assistant = AsyncMock(
        return_value=_mock_assistant_for_execute_step()
    )

    with pytest.raises(TypedIOValidationException) as exc:
        await executor._execute_step(step=step, run=run, state=run_state, attempt_no=1)

    assert exc.value.code == "typed_io_document_source_unsupported"


@pytest.mark.asyncio
async def test_image_requires_valid_files(user):
    """Image input with no image files raises typed_io_missing_required_files."""
    executor, _, _, _ = _build_executor(user)
    step = _runtime_step(input_type="image")
    run = _run(
        status=FlowRunStatus.RUNNING,
        user=user,
        input_payload={"text": "x"},
    )

    mock_assistant = MagicMock()
    mock_assistant.get_prompt_text.return_value = ""
    executor._load_assistant = AsyncMock(return_value=mock_assistant)

    with pytest.raises(TypedIOValidationException, match="not yet supported|requires"):
        await executor._execute_step(step=step, run=run, attempt_no=1)


@pytest.mark.asyncio
async def test_audio_step_does_not_forward_audio_files_to_llm(user):
    """Audio input uses transcribed text; raw audio files should not be forwarded to LLM."""
    executor, _, _, _ = _build_executor(user)
    run = _run(
        status=FlowRunStatus.RUNNING,
        user=user,
        input_payload={},
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

    output = (await executor._execute_step(step=step, run=run, attempt_no=1)).output

    assert output.input_text == "Transcribed text"
    assert assistant.get_response.await_args.kwargs["files"] == []


@pytest.mark.asyncio
async def test_audio_transcribe_only_skips_llm_and_rag(user):
    """Audio + transcribe_only should return transcript directly without LLM/RAG."""
    executor, _, _, _ = _build_executor(user)
    run = _run(
        status=FlowRunStatus.RUNNING,
        user=user,
        input_payload={},
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

    output = (await executor._execute_step(step=step, run=run, attempt_no=1)).output

    assistant.get_response.assert_not_awaited()
    executor._retrieve_rag_chunks.assert_not_awaited()
    assert output.full_text == "Raw transcript text"
    assert output.persisted_text == "Raw transcript text"
    assert output.num_tokens_input == 0
    assert output.num_tokens_output == 0
    assert output.transcription_metadata == {"model": "whisper-1", "language": "sv"}
    assert any(d.code == "audio_transcribe_only_used" for d in output.diagnostics)


@pytest.mark.asyncio
async def test_render_verbatim_renders_input_text_without_llm_or_rag(user):
    executor, _, _, _ = _build_executor(user)
    executor.document_render_service = SimpleNamespace(
        render_document=lambda text, output_type, step_order: (
            f"{output_type}:{text}".encode("utf-8"),
            "application/pdf",
            f"flow-step-{step_order}.pdf",
        ),
        render_structured_document=MagicMock(
            side_effect=AssertionError("structured rendering is not used here")
        ),
        limits=DocumentRenderLimits(),
    )
    run = _run(
        status=FlowRunStatus.RUNNING,
        user=user,
        input_payload={},
    )
    step = _runtime_step(
        input_type="text",
        output_type="pdf",
        output_mode="render_verbatim",
    )
    assistant = _mock_assistant_for_execute_step(response_text="should_not_be_used")
    executor._load_assistant = AsyncMock(return_value=assistant)
    executor._resolve_step_input = AsyncMock(
        return_value=StepInputValue(
            text="Final report body",
            source_text="Final report body",
            input_source="previous_step",
        )
    )
    executor._retrieve_rag_chunks = AsyncMock(
        return_value=([], {"status": "should_not_run"}, [])
    )
    stored_file = SimpleNamespace(id=uuid4())
    executor.file_repo.add = AsyncMock(return_value=stored_file)

    output = (await executor._execute_step(step=step, run=run, attempt_no=1)).output

    assistant.get_response.assert_not_awaited()
    executor._retrieve_rag_chunks.assert_not_awaited()
    assert output.full_text == "Final report body"
    assert output.persisted_text == "Final report body"
    assert output.num_tokens_input == 0
    assert output.num_tokens_output == 0
    assert output.model_parameters_json == {"mode": "render_verbatim"}
    assert output.artifacts is not None
    assert output.artifacts[0]["file_id"] == str(stored_file.id)
    assert any(d.code == "render_verbatim_used" for d in output.diagnostics)


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
        await executor._execute_step(step=step, run=run, attempt_no=1)

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
    executor._load_assistant = AsyncMock(
        return_value=_mock_assistant_for_execute_step()
    )

    output = (await executor._execute_step(step=step, run=run, attempt_no=1)).output

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
    executor._load_assistant = AsyncMock(
        return_value=_mock_assistant_for_execute_step()
    )

    output = (await executor._execute_step(step=step, run=run, attempt_no=1)).output

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
    raw_text = "not json at all"
    run = _run(
        status=FlowRunStatus.RUNNING,
        user=user,
        input_payload={"text": raw_text},
    )
    step = _runtime_step(
        input_type="text",
        input_contract={
            "type": "object",
            "required": ["title"],
            "properties": {"title": {"type": "string"}},
        },
    )
    executor._load_assistant = AsyncMock(
        return_value=_mock_assistant_for_execute_step()
    )

    with pytest.raises(TypedIOValidationException) as exc:
        await executor._execute_step(step=step, run=run, attempt_no=1)

    assert exc.value.code == "typed_io_contract_violation"
    assert raw_text not in str(exc.value)
    assert len(str(exc.value)) < 200


@pytest.mark.asyncio
async def test_text_input_contract_rejects_extra_properties(user):
    executor, _, _, _ = _build_executor(user)
    run = _run(
        status=FlowRunStatus.RUNNING,
        user=user,
        input_payload={"text": '{"title":"Sakerhetsanalys","extra":"nope"}'},
    )
    step = _runtime_step(
        input_type="text",
        input_contract={
            "type": "object",
            "required": ["title"],
            "properties": {"title": {"type": "string"}},
            "additionalProperties": False,
        },
    )
    executor._load_assistant = AsyncMock(
        return_value=_mock_assistant_for_execute_step()
    )

    with pytest.raises(TypedIOValidationException) as exc:
        await executor._execute_step(step=step, run=run, attempt_no=1)

    assert exc.value.code == "typed_io_contract_violation"
    assert "Additional properties are not allowed" in str(exc.value)


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
    executor._load_assistant = AsyncMock(
        return_value=_mock_assistant_for_execute_step()
    )

    output = (await executor._execute_step(step=step, run=run, attempt_no=1)).output

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
        (
            "docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".docx",
        ),
    ],
)
async def test_document_outputs_generate_downloadable_artifacts(
    user, output_type: str, expected_mimetype: str, expected_ext: str
):
    """PDF/DOCX output types should persist artifact files with download metadata."""
    executor, _, _, _ = _build_executor(user)
    executor.document_render_service = SimpleNamespace(
        render_document=lambda text, output_type, step_order: (
            f"{output_type}:{text}".encode("utf-8"),
            expected_mimetype,
            f"flow-step-{step_order}{expected_ext}",
        ),
        render_structured_document=MagicMock(
            side_effect=AssertionError("structured rendering is not used here")
        ),
        limits=DocumentRenderLimits(),
    )
    run = _run(status=FlowRunStatus.RUNNING, user=user)
    step = _runtime_step(output_type=output_type)

    stored_file = SimpleNamespace(id=uuid4())
    executor.file_repo.add = AsyncMock(return_value=stored_file)
    executor._load_assistant = AsyncMock(
        return_value=_mock_assistant_for_execute_step(response_text="Rapport")
    )

    output = (await executor._execute_step(step=step, run=run, attempt_no=1)).output

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
    executor._load_assistant = AsyncMock(
        return_value=_mock_assistant_for_execute_step(response_text="")
    )

    output = (await executor._execute_step(step=step, run=run, attempt_no=1)).output

    assert output.artifacts is not None
    assert output.artifacts[0]["file_id"] == str(stored_file.id)
    assert (
        output.artifacts[0]["mimetype"]
        == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )


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
        input_config={"url": "https://example.org/data", "auth": {"mode": "none"}},
    )
    request = httpx.Request("GET", "https://example.org/data")
    executor._send_http_request = AsyncMock(
        return_value=httpx.Response(200, request=request, text="fetched")
    )
    context = executor.variable_resolver.build_context(run.input_payload_json, [])

    await executor._resolve_step_input(
        step=step,
        context=context,
        run=run,
        prior_results=[],
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
async def test_resolve_http_input_decrypts_authored_header_secrets(user):
    executor, _, _, _ = _build_executor(user)
    executor.encryption_service.is_encrypted = MagicMock(
        side_effect=lambda v: v.startswith("enc:")
    )
    executor.encryption_service.decrypt = MagicMock(
        side_effect=lambda v: v[len("enc:") :]
    )
    run = _run(status=FlowRunStatus.RUNNING, user=user, input_payload={"text": "x"})
    step = _runtime_step(
        input_source="http_get",
        input_type="text",
        input_config={
            "url": "https://example.org/data",
            "auth": {
                "mode": "bearer_token",
                "token": "enc:token456",
            },
            "custom_headers": [
                {"name": "X-Plain", "value": "visible", "secret": False}
            ],
        },
    )
    request = httpx.Request("GET", "https://example.org/data")
    executor._send_http_request = AsyncMock(
        return_value=httpx.Response(200, request=request, text="ok")
    )
    context = executor.variable_resolver.build_context(run.input_payload_json, [])

    await executor._resolve_step_input(
        step=step,
        context=context,
        run=run,
        prior_results=[],
    )

    executor._send_http_request.assert_awaited_once()
    headers = executor._send_http_request.await_args.kwargs["headers"]
    assert headers["Authorization"] == "Bearer token456"
    assert headers["X-Plain"] == "visible"
    executor.encryption_service.decrypt.assert_called_once_with("enc:token456")


def test_document_output_prompt_instructs_model_to_return_markdown_not_binary() -> None:
    prompt = _prompt_for_output_format(
        output_type="pdf",
        output_contract=None,
        prompt="Generera en PDF-rapport",
    )

    assert "system will render" in prompt
    assert "Markdown/plain text" in prompt
    assert "%PDF-" in prompt


def test_document_output_prompt_with_contract_requests_validated_json() -> None:
    prompt = _prompt_for_output_format(
        output_type="pdf",
        output_contract={"type": "object"},
        prompt="Return report data",
    )

    assert "render it into a PDF file" in prompt
    assert "Return ONLY valid JSON" in prompt
    assert "Use plain text for JSON string values" in prompt
    assert "Follow this JSON Schema exactly" in prompt
