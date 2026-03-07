from __future__ import annotations

from typing import Any
from uuid import UUID

from intric.flows.flow import FlowStepResult, FlowStepResultStatus
from intric.flows.runtime.models import RuntimeStep, StepExecutionOutput


def build_default_failed_input_payload(*, input_source: str) -> dict[str, Any]:
    return {
        "text": "",
        "source_text": "",
        "input_source": input_source,
        "used_question_binding": False,
        "legacy_prompt_binding_used": False,
    }


def build_failed_step_result(
    *,
    claimed: FlowStepResult,
    error_message: str,
    input_payload_json: dict[str, Any] | None = None,
    effective_prompt: str | None = None,
) -> FlowStepResult:
    updates: dict[str, Any] = {
        "status": FlowStepResultStatus.FAILED,
        "error_message": error_message,
    }
    if input_payload_json is not None:
        updates["input_payload_json"] = input_payload_json
    if isinstance(effective_prompt, str):
        updates["effective_prompt"] = effective_prompt
    return claimed.model_copy(update=updates, deep=True)


def build_completed_step_input_payload(output: StepExecutionOutput) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "text": output.input_text,
        "source_text": output.source_text,
        "input_source": output.input_source,
        "used_question_binding": output.used_question_binding,
        "legacy_prompt_binding_used": output.legacy_prompt_binding_used,
    }
    if output.transcription_metadata is not None:
        payload["transcription"] = output.transcription_metadata
    if output.rag_metadata is not None:
        payload["rag"] = output.rag_metadata
    if output.contract_validation is not None:
        payload["contract_validation"] = output.contract_validation
    if output.diagnostics:
        payload["diagnostics"] = [
            {"code": diagnostic.code, "message": diagnostic.message, "severity": diagnostic.severity}
            for diagnostic in output.diagnostics
        ]
    return payload


def build_completed_step_result(
    *,
    claimed: FlowStepResult,
    run_id: UUID,
    flow_id: UUID,
    tenant_id: UUID,
    step: RuntimeStep,
    output: StepExecutionOutput,
    output_payload_json: dict[str, Any],
    execution_hash: str,
) -> FlowStepResult:
    return FlowStepResult(
        id=claimed.id,
        flow_run_id=run_id,
        flow_id=flow_id,
        tenant_id=tenant_id,
        step_id=step.step_id,
        step_order=step.step_order,
        assistant_id=step.assistant_id,
        input_payload_json=build_completed_step_input_payload(output),
        effective_prompt=output.effective_prompt,
        output_payload_json=output_payload_json,
        model_parameters_json=output.model_parameters_json,
        num_tokens_input=output.num_tokens_input,
        num_tokens_output=output.num_tokens_output,
        status=FlowStepResultStatus.COMPLETED,
        error_message=None,
        flow_step_execution_hash=execution_hash,
        tool_calls_metadata=output.tool_calls_metadata,
        created_at=claimed.created_at,
        updated_at=claimed.updated_at,
    )


def build_transcribe_only_rag_metadata(*, timeout_seconds: float) -> dict[str, Any]:
    return {
        "attempted": False,
        "status": "skipped_transcribe_only",
        "version": 1,
        "timeout_seconds": int(timeout_seconds),
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


def with_webhook_delivery_status(
    *,
    step_result: FlowStepResult,
    delivered: bool,
    error: str | None = None,
) -> FlowStepResult:
    output_payload = dict(step_result.output_payload_json or {})
    output_payload["webhook_delivered"] = delivered
    if error is not None:
        output_payload["webhook_error"] = error
    return step_result.model_copy(
        update={"output_payload_json": output_payload},
        deep=True,
    )
