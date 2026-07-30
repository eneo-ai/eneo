from __future__ import annotations

from typing import Any
from uuid import UUID

from eneo.flows.domain.flow import FlowStepResult, FlowStepResultStatus
from eneo.flows.domain.rag_evidence import (
    RetrievedKnowledgeEvidence,
    build_step_result_citation_state,
)
from eneo.flows.domain.runtime import RuntimeStep, StepExecutionOutput
from eneo.flows.flow_run_provenance import (
    AttemptStartProvenance,
    CitationsProvenance,
    FlowAttemptProvenance,
    LlmProvenance,
    RagProvenance,
    normalize_json_preview,
    normalize_text_preview,
)


def build_incomplete_attempt_provenance(
    *,
    attempt_start: AttemptStartProvenance | None,
    rag_metadata: object = None,
) -> dict[str, Any] | None:
    """Build evidence captured before an attempt produced a complete output."""
    rag = (
        RagProvenance.model_validate(rag_metadata)
        if isinstance(rag_metadata, dict)
        else None
    )
    if attempt_start is None and rag is None:
        return None
    return FlowAttemptProvenance(attempt_start=attempt_start, rag=rag).to_payload()


def build_attempt_provenance(
    *,
    output: StepExecutionOutput,
    attempt_start: AttemptStartProvenance | None = None,
) -> dict[str, Any]:
    """Build the v2 attempt-evidence projection from completed runtime output."""
    return FlowAttemptProvenance(
        llm=LlmProvenance(
            effective_prompt=normalize_text_preview(output.effective_prompt),
            model_parameters=output.model_parameters_json,
            tool_calls=(
                normalize_json_preview(output.tool_calls_metadata)
                if output.tool_calls_metadata is not None
                else None
            ),
            raw_completion_text=(
                normalize_text_preview(output.raw_completion_text)
                if isinstance(output.raw_completion_text, str)
                and output.raw_completion_text
                else None
            ),
        ),
        attempt_start=attempt_start,
        rag=(
            RagProvenance.model_validate(output.rag_metadata)
            if output.rag_metadata is not None
            else None
        ),
        citations=(
            CitationsProvenance.model_validate(output.citation_sidecar)
            if output.citation_sidecar is not None
            else None
        ),
    ).to_payload()


def build_default_failed_input_payload(*, input_source: str) -> dict[str, Any]:
    return {
        "text": "",
        "source_text": "",
        "input_source": input_source,
        "used_question_binding": False,
    }


def build_failed_step_result(
    *,
    claimed: FlowStepResult,
    error_code: str,
    error_message: str,
    input_payload_json: dict[str, Any] | None = None,
    effective_prompt: str | None = None,
) -> FlowStepResult:
    updates: dict[str, Any] = {
        "status": FlowStepResultStatus.FAILED,
        "error_code": error_code,
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
    }
    if output.transcription_metadata is not None:
        payload["transcription"] = output.transcription_metadata
    if output.runtime_input_metadata is not None:
        payload["runtime_input"] = output.runtime_input_metadata
    if output.rag_metadata is not None:
        # Verbatim passages live only in attempt provenance; the step result
        # keeps the source identity a later step needs to inherit citations.
        payload["rag"] = build_step_result_citation_state(output.rag_metadata)
    if output.contract_validation is not None:
        payload["contract_validation"] = output.contract_validation
    if output.diagnostics:
        payload["diagnostics"] = [
            {
                "code": diagnostic.code,
                "message": diagnostic.message,
                "severity": diagnostic.severity,
            }
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
        error_code=None,
        error_message=None,
        flow_step_execution_hash=execution_hash,
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
        "embedding_model": None,
        "embedding_model_status": "not_reported",
        **RetrievedKnowledgeEvidence().aggregate_payload(),
        "references": [],
    }
