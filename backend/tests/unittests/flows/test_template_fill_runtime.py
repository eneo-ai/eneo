from __future__ import annotations

import io
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from docx import Document

from intric.flows.flow import FlowRun, FlowRunStatus, FlowStepResult, FlowStepResultStatus
from intric.flows.runtime.models import RunExecutionState, RuntimeStep
from intric.flows.runtime import template_fill_runtime as template_fill_runtime_module
from intric.flows.runtime.template_fill_runtime import (
    TemplateFillRuntimeDeps,
    execute_template_fill_step,
)
from intric.flows.variable_resolver import FlowVariableResolver
from intric.main.exceptions import TypedIOValidationException


def _build_template_bytes() -> bytes:
    document = Document()
    document.add_paragraph("Titel: {{title}}")
    document.add_paragraph("Författare: {{author}}")
    document.add_paragraph("Sammanfattning: {{summary}}")
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _build_unicode_template_bytes() -> bytes:
    document = Document()
    document.add_paragraph("Ämne: {{ämne}}")
    document.add_paragraph("Sammanfattning: {{summary}}")
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _build_summary_only_template_bytes() -> bytes:
    document = Document()
    document.add_paragraph("Slutsats")
    document.add_paragraph("{{slutsats}}")
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _run() -> FlowRun:
    now = datetime.now(timezone.utc)
    return FlowRun(
        id=uuid4(),
        flow_id=uuid4(),
        flow_version=3,
        user_id=uuid4(),
        tenant_id=uuid4(),
        status=FlowRunStatus.RUNNING,
        input_payload_json={"title": "Social medias påverkan", "author": "Anders Svensson"},
        created_at=now,
        updated_at=now,
    )


def _completed_result(*, run: FlowRun) -> FlowStepResult:
    now = datetime.now(timezone.utc)
    return FlowStepResult(
        id=uuid4(),
        flow_run_id=run.id,
        flow_id=run.flow_id,
        tenant_id=run.tenant_id,
        step_id=uuid4(),
        step_order=1,
        assistant_id=uuid4(),
        input_payload_json={"text": "ignored"},
        effective_prompt="prompt",
        output_payload_json={"text": "Detta är sammanfattningen."},
        model_parameters_json={},
        num_tokens_input=10,
        num_tokens_output=20,
        status=FlowStepResultStatus.COMPLETED,
        error_message=None,
        flow_step_execution_hash="hash",
        tool_calls_metadata=None,
        created_at=now,
        updated_at=now,
    )


def _state(*, result: FlowStepResult) -> RunExecutionState:
    return RunExecutionState(
        completed_by_order={1: result},
        prior_results=[result],
        all_previous_segments=[],
        assistant_cache={},
        json_mode_supported={},
        file_cache={},
        step_names_by_order={1: "Sammanfatta"},
    )


def _step(*, template_file_id, template_checksum: str | None = "checksum") -> RuntimeStep:
    return RuntimeStep(
        step_id=uuid4(),
        step_order=2,
        assistant_id=uuid4(),
        user_description="Assemble report",
        input_source="all_previous_steps",
        input_bindings=None,
        input_config=None,
        output_mode="template_fill",
        output_config={
            "template_file_id": str(template_file_id),
            "template_checksum": template_checksum,
            "bindings": {
                "title": "{{title}}",
                "author": "{{author}}",
                "summary": "{{step_1.output.text}}",
            },
        },
        output_type="docx",
    )


def _logger() -> SimpleNamespace:
    return SimpleNamespace(
        info=lambda *args, **kwargs: None,
        debug=lambda *args, **kwargs: None,
        exception=lambda *args, **kwargs: None,
    )


@pytest.mark.asyncio
async def test_execute_template_fill_step_renders_and_persists_docx() -> None:
    run = _run()
    result = _completed_result(run=run)
    state = _state(result=result)
    template_file_id = uuid4()
    step = _step(template_file_id=template_file_id)
    file_repo = AsyncMock()
    file_repo.get_list_by_id_and_tenant.return_value = [
        SimpleNamespace(
            id=template_file_id,
            checksum="checksum",
            blob=_build_template_bytes(),
        )
    ]
    file_repo.add.return_value = SimpleNamespace(id=uuid4())
    apply_output_cap = AsyncMock()
    deps = TemplateFillRuntimeDeps(
        variable_resolver=FlowVariableResolver(),
        file_repo=file_repo,
        apply_output_cap=apply_output_cap,
        user_id=run.user_id,
        logger=_logger(),
    )

    output = await execute_template_fill_step(
        step=step,
        run=run,
        state=state,
        deps=deps,
    )

    assert output.persisted_text == (
        "## title\n\nSocial medias påverkan\n\n"
        "## author\n\nAnders Svensson\n\n"
        "## summary\n\nDetta är sammanfattningen."
    )
    assert output.artifacts and output.artifacts[0]["mimetype"].endswith("document")
    assert output.model_parameters_json["mode"] == "template_fill"
    assert "Detta är sammanfattningen." in output.full_text
    assert output.output_payload_extensions == {
        "template_fill_debug": {
            "rendered_docx_text_raw": output.full_text,
            "summary_mode": "resolved_bindings",
            "placeholder_count": 3,
        }
    }
    assert '"title": "Social medias påverkan"' in output.input_text
    file_repo.add.assert_awaited_once()
    apply_output_cap.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_template_fill_step_rejects_checksum_drift() -> None:
    run = _run()
    result = _completed_result(run=run)
    state = _state(result=result)
    template_file_id = uuid4()
    file_repo = AsyncMock()
    file_repo.get_list_by_id_and_tenant.return_value = [
        SimpleNamespace(
            id=template_file_id,
            checksum="other-checksum",
            blob=_build_template_bytes(),
        )
    ]
    deps = TemplateFillRuntimeDeps(
        variable_resolver=FlowVariableResolver(),
        file_repo=file_repo,
        apply_output_cap=AsyncMock(),
        user_id=run.user_id,
        logger=_logger(),
    )

    with pytest.raises(TypedIOValidationException, match="checksum"):
        await execute_template_fill_step(
            step=_step(template_file_id=template_file_id, template_checksum="expected-checksum"),
            run=run,
            state=state,
            deps=deps,
        )

    file_repo.add.assert_not_called()


@pytest.mark.asyncio
async def test_execute_template_fill_step_allows_explicit_empty_binding() -> None:
    run = _run()
    result = _completed_result(run=run)
    state = _state(result=result)
    template_file_id = uuid4()
    file_repo = AsyncMock()
    file_repo.get_list_by_id_and_tenant.return_value = [
        SimpleNamespace(
            id=template_file_id,
            checksum="checksum",
            blob=_build_template_bytes(),
        )
    ]
    file_repo.add.return_value = SimpleNamespace(id=uuid4())
    deps = TemplateFillRuntimeDeps(
        variable_resolver=FlowVariableResolver(),
        file_repo=file_repo,
        apply_output_cap=AsyncMock(),
        user_id=run.user_id,
        logger=_logger(),
    )

    step = _step(template_file_id=template_file_id)
    step.output_config["bindings"]["author"] = ""

    output = await execute_template_fill_step(
        step=step,
        run=run,
        state=state,
        deps=deps,
    )

    assert '"author": ""' in output.input_text
    assert "\n\n## author\n\n## summary" in output.persisted_text


@pytest.mark.asyncio
async def test_execute_template_fill_step_strips_duplicate_leading_heading_from_summary_only() -> None:
    run = _run()
    now = datetime.now(timezone.utc)
    result = FlowStepResult(
        id=uuid4(),
        flow_run_id=run.id,
        flow_id=run.flow_id,
        tenant_id=run.tenant_id,
        step_id=uuid4(),
        step_order=1,
        assistant_id=uuid4(),
        input_payload_json={"text": "ignored"},
        effective_prompt="prompt",
        output_payload_json={"text": "Slutsats:\n\nDet här är själva brödtexten."},
        model_parameters_json={},
        num_tokens_input=10,
        num_tokens_output=20,
        status=FlowStepResultStatus.COMPLETED,
        error_message=None,
        flow_step_execution_hash="hash",
        tool_calls_metadata=None,
        created_at=now,
        updated_at=now,
    )
    state = RunExecutionState(
        completed_by_order={1: result},
        prior_results=[result],
        all_previous_segments=[],
        assistant_cache={},
        json_mode_supported={},
        file_cache={},
        step_names_by_order={1: "slutsats"},
    )
    template_file_id = uuid4()
    file_repo = AsyncMock()
    file_repo.get_list_by_id_and_tenant.return_value = [
        SimpleNamespace(
            id=template_file_id,
            checksum="checksum",
            blob=_build_summary_only_template_bytes(),
        )
    ]
    file_repo.add.return_value = SimpleNamespace(id=uuid4())
    deps = TemplateFillRuntimeDeps(
        variable_resolver=FlowVariableResolver(),
        file_repo=file_repo,
        apply_output_cap=AsyncMock(),
        user_id=run.user_id,
        logger=_logger(),
    )
    step = _step(template_file_id=template_file_id)
    step.output_config["bindings"] = {"slutsats": "{{step_1.output.text}}"}
    step.output_config["placeholders"] = ["slutsats"]

    output = await execute_template_fill_step(
        step=step,
        run=run,
        state=state,
        deps=deps,
    )

    assert output.persisted_text == "## slutsats\n\nDet här är själva brödtexten."
    assert "Slutsats:\n\nDet här är själva brödtexten." in output.full_text


@pytest.mark.asyncio
async def test_execute_template_fill_step_reports_failed_upstream_step_clearly() -> None:
    run = _run()
    now = datetime.now(timezone.utc)
    failed_result = FlowStepResult(
        id=uuid4(),
        flow_run_id=run.id,
        flow_id=run.flow_id,
        tenant_id=run.tenant_id,
        step_id=uuid4(),
        step_order=1,
        assistant_id=uuid4(),
        input_payload_json={"text": "ignored"},
        effective_prompt="prompt",
        output_payload_json={},
        model_parameters_json={},
        num_tokens_input=1,
        num_tokens_output=1,
        status=FlowStepResultStatus.FAILED,
        error_message="boom",
        flow_step_execution_hash="hash",
        tool_calls_metadata=None,
        created_at=now,
        updated_at=now,
    )
    state = RunExecutionState(
        completed_by_order={},
        prior_results=[failed_result],
        all_previous_segments=[],
        assistant_cache={},
        json_mode_supported={},
        file_cache={},
        step_names_by_order={1: "Sammanfatta"},
    )
    template_file_id = uuid4()
    file_repo = AsyncMock()
    file_repo.get_list_by_id_and_tenant.return_value = [
        SimpleNamespace(
            id=template_file_id,
            checksum="checksum",
            blob=_build_template_bytes(),
        )
    ]
    deps = TemplateFillRuntimeDeps(
        variable_resolver=FlowVariableResolver(),
        file_repo=file_repo,
        apply_output_cap=AsyncMock(),
        user_id=run.user_id,
        logger=_logger(),
    )

    with pytest.raises(TypedIOValidationException, match="failed earlier in the run"):
        await execute_template_fill_step(
            step=_step(template_file_id=template_file_id),
            run=run,
            state=state,
            deps=deps,
        )


@pytest.mark.asyncio
async def test_execute_template_fill_step_reports_missing_template_blob_clearly() -> None:
    run = _run()
    result = _completed_result(run=run)
    state = _state(result=result)
    template_file_id = uuid4()
    file_repo = AsyncMock()
    file_repo.get_list_by_id_and_tenant.return_value = [
        SimpleNamespace(
            id=template_file_id,
            checksum="checksum",
            blob=None,
        )
    ]
    deps = TemplateFillRuntimeDeps(
        variable_resolver=FlowVariableResolver(),
        file_repo=file_repo,
        apply_output_cap=AsyncMock(),
        user_id=run.user_id,
        logger=_logger(),
    )

    with pytest.raises(TypedIOValidationException, match="could not be read because the saved file content is missing"):
        await execute_template_fill_step(
            step=_step(template_file_id=template_file_id),
            run=run,
            state=state,
            deps=deps,
        )


@pytest.mark.asyncio
async def test_execute_template_fill_step_reports_generated_document_save_failure() -> None:
    run = _run()
    result = _completed_result(run=run)
    state = _state(result=result)
    template_file_id = uuid4()
    file_repo = AsyncMock()
    file_repo.get_list_by_id_and_tenant.return_value = [
        SimpleNamespace(
            id=template_file_id,
            checksum="checksum",
            blob=_build_template_bytes(),
        )
    ]
    file_repo.add.side_effect = RuntimeError("storage unavailable")
    deps = TemplateFillRuntimeDeps(
        variable_resolver=FlowVariableResolver(),
        file_repo=file_repo,
        apply_output_cap=AsyncMock(),
        user_id=run.user_id,
        logger=_logger(),
    )

    with pytest.raises(TypedIOValidationException, match="saving the generated DOCX"):
        await execute_template_fill_step(
            step=_step(template_file_id=template_file_id),
            run=run,
            state=state,
            deps=deps,
        )


@pytest.mark.asyncio
async def test_execute_template_fill_step_reports_generated_document_read_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run()
    result = _completed_result(run=run)
    state = _state(result=result)
    template_file_id = uuid4()
    file_repo = AsyncMock()
    file_repo.get_list_by_id_and_tenant.return_value = [
        SimpleNamespace(
            id=template_file_id,
            checksum="checksum",
            blob=_build_template_bytes(),
        )
    ]
    file_repo.add.return_value = SimpleNamespace(id=uuid4())
    monkeypatch.setattr(
        template_fill_runtime_module,
        "extract_docx_text",
        lambda blob: (_ for _ in ()).throw(RuntimeError("document parse failed")),
    )
    deps = TemplateFillRuntimeDeps(
        variable_resolver=FlowVariableResolver(),
        file_repo=file_repo,
        apply_output_cap=AsyncMock(),
        user_id=run.user_id,
        logger=_logger(),
    )

    with pytest.raises(TypedIOValidationException, match="reading the generated DOCX"):
        await execute_template_fill_step(
            step=_step(template_file_id=template_file_id),
            run=run,
            state=state,
            deps=deps,
        )


@pytest.mark.asyncio
async def test_execute_template_fill_step_rejects_invalid_template_file_id() -> None:
    run = _run()
    result = _completed_result(run=run)
    state = _state(result=result)
    step = _step(template_file_id=uuid4())
    step.output_config["template_file_id"] = "not-a-uuid"
    deps = TemplateFillRuntimeDeps(
        variable_resolver=FlowVariableResolver(),
        file_repo=AsyncMock(),
        apply_output_cap=AsyncMock(),
        user_id=run.user_id,
        logger=_logger(),
    )

    with pytest.raises(TypedIOValidationException, match="valid template_file_id"):
        await execute_template_fill_step(
            step=step,
            run=run,
            state=state,
            deps=deps,
        )


@pytest.mark.asyncio
async def test_execute_template_fill_step_rejects_non_string_binding_values() -> None:
    run = _run()
    result = _completed_result(run=run)
    state = _state(result=result)
    step = _step(template_file_id=uuid4())
    step.output_config["bindings"]["summary"] = {"bad": "value"}
    deps = TemplateFillRuntimeDeps(
        variable_resolver=FlowVariableResolver(),
        file_repo=AsyncMock(),
        apply_output_cap=AsyncMock(),
        user_id=run.user_id,
        logger=_logger(),
    )

    with pytest.raises(TypedIOValidationException, match="must be a string expression"):
        await execute_template_fill_step(
            step=step,
            run=run,
            state=state,
            deps=deps,
        )


@pytest.mark.asyncio
async def test_execute_template_fill_step_reports_missing_published_template_file() -> None:
    run = _run()
    result = _completed_result(run=run)
    state = _state(result=result)
    template_file_id = uuid4()
    file_repo = AsyncMock()
    file_repo.get_list_by_id_and_tenant.return_value = []
    deps = TemplateFillRuntimeDeps(
        variable_resolver=FlowVariableResolver(),
        file_repo=file_repo,
        apply_output_cap=AsyncMock(),
        user_id=run.user_id,
        logger=_logger(),
    )

    with pytest.raises(TypedIOValidationException, match="was not found"):
        await execute_template_fill_step(
            step=_step(template_file_id=template_file_id),
            run=run,
            state=state,
            deps=deps,
        )


@pytest.mark.asyncio
async def test_execute_template_fill_step_reports_render_stage_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run()
    result = _completed_result(run=run)
    state = _state(result=result)
    template_file_id = uuid4()
    file_repo = AsyncMock()
    file_repo.get_list_by_id_and_tenant.return_value = [
        SimpleNamespace(
            id=template_file_id,
            checksum="checksum",
            blob=_build_template_bytes(),
        )
    ]
    monkeypatch.setattr(
        template_fill_runtime_module,
        "render_docx_template",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("render broke")),
    )
    deps = TemplateFillRuntimeDeps(
        variable_resolver=FlowVariableResolver(),
        file_repo=file_repo,
        apply_output_cap=AsyncMock(),
        user_id=run.user_id,
        logger=_logger(),
    )

    with pytest.raises(TypedIOValidationException, match="rendering the DOCX template"):
        await execute_template_fill_step(
            step=_step(template_file_id=template_file_id),
            run=run,
            state=state,
            deps=deps,
        )


@pytest.mark.asyncio
async def test_execute_template_fill_step_supports_datum_system_variable() -> None:
    run = _run()
    result = _completed_result(run=run)
    state = _state(result=result)
    template_file_id = uuid4()
    file_repo = AsyncMock()
    file_repo.get_list_by_id_and_tenant.return_value = [
        SimpleNamespace(
            id=template_file_id,
            checksum="checksum",
            blob=_build_template_bytes(),
        )
    ]
    file_repo.add.return_value = SimpleNamespace(id=uuid4())
    deps = TemplateFillRuntimeDeps(
        variable_resolver=FlowVariableResolver(),
        file_repo=file_repo,
        apply_output_cap=AsyncMock(),
        user_id=run.user_id,
        logger=_logger(),
    )
    step = _step(template_file_id=template_file_id)
    step.output_config["bindings"]["author"] = "{{datum}}"

    output = await execute_template_fill_step(
        step=step,
        run=run,
        state=state,
        deps=deps,
    )

    assert '"author": "' in output.input_text
    assert output.input_text.count("-") >= 2
    assert "## author\n\n" in output.persisted_text


@pytest.mark.asyncio
async def test_execute_template_fill_step_formats_json_binding_in_summary() -> None:
    run = _run()
    result = _completed_result(run=run)
    result = result.model_copy(
        update={
            "output_payload_json": {
                "text": '{"status":"preview"}',
                "structured": {"status": "approved", "score": 5},
            }
        },
        deep=True,
    )
    state = _state(result=result)
    template_file_id = uuid4()
    file_repo = AsyncMock()
    file_repo.get_list_by_id_and_tenant.return_value = [
        SimpleNamespace(id=template_file_id, checksum="checksum", blob=_build_template_bytes())
    ]
    file_repo.add.return_value = SimpleNamespace(id=uuid4())
    deps = TemplateFillRuntimeDeps(
        variable_resolver=FlowVariableResolver(),
        file_repo=file_repo,
        apply_output_cap=AsyncMock(),
        user_id=run.user_id,
        logger=_logger(),
    )
    step = _step(template_file_id=template_file_id)
    step.output_config["bindings"]["summary"] = "{{step_1.output.structured}}"

    output = await execute_template_fill_step(step=step, run=run, state=state, deps=deps)

    assert '## summary\n\n{"status": "approved", "score": 5}' in output.persisted_text


@pytest.mark.asyncio
async def test_execute_template_fill_step_supports_unicode_placeholder_names() -> None:
    run = _run()
    result = _completed_result(run=run)
    state = _state(result=result)
    template_file_id = uuid4()
    file_repo = AsyncMock()
    file_repo.get_list_by_id_and_tenant.return_value = [
        SimpleNamespace(id=template_file_id, checksum="checksum", blob=_build_unicode_template_bytes())
    ]
    file_repo.add.return_value = SimpleNamespace(id=uuid4())
    deps = TemplateFillRuntimeDeps(
        variable_resolver=FlowVariableResolver(),
        file_repo=file_repo,
        apply_output_cap=AsyncMock(),
        user_id=run.user_id,
        logger=_logger(),
    )
    step = _step(template_file_id=template_file_id)
    step.output_config["placeholders"] = ["ämne", "summary"]
    step.output_config["bindings"] = {
        "ämne": "{{title}}",
        "summary": "{{step_1.output.text}}",
    }

    output = await execute_template_fill_step(step=step, run=run, state=state, deps=deps)

    assert output.persisted_text.startswith("## ämne\n\nSocial medias påverkan\n\n## summary")


@pytest.mark.asyncio
async def test_execute_template_fill_step_bypasses_output_cap_for_long_summary() -> None:
    run = _run()
    result = _completed_result(run=run)
    result = result.model_copy(
        update={"output_payload_json": {"text": "L" * 10000}},
        deep=True,
    )
    state = _state(result=result)
    template_file_id = uuid4()
    file_repo = AsyncMock()
    file_repo.get_list_by_id_and_tenant.return_value = [
        SimpleNamespace(id=template_file_id, checksum="checksum", blob=_build_template_bytes())
    ]
    file_repo.add.return_value = SimpleNamespace(id=uuid4())
    apply_output_cap = AsyncMock(side_effect=RuntimeError("should not be called"))
    deps = TemplateFillRuntimeDeps(
        variable_resolver=FlowVariableResolver(),
        file_repo=file_repo,
        apply_output_cap=apply_output_cap,
        user_id=run.user_id,
        logger=_logger(),
    )

    output = await execute_template_fill_step(
        step=_step(template_file_id=template_file_id),
        run=run,
        state=state,
        deps=deps,
    )

    assert "## summary" in output.persisted_text
    apply_output_cap.assert_not_awaited()
