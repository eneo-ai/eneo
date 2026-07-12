from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from pydantic import BaseModel, ConfigDict

from eneo.flows.domain.flow import (
    FlowPersistedJsonObject,
    FlowRun,
    FlowRunRerunInvalidatedStep,
    FlowRunRerunOperation,
    FlowStepAttempt,
    FlowStepResult,
    FlowVersion,
)
from eneo.flows.flow_run_provenance import normalize_rag_payload
from eneo.flows.flow_run_step_result_file import FlowRunStepResultFile

DEBUG_EXPORT_SCHEMA_VERSION = "eneo.flow.debug-export.v2"


class DebugAttemptProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempt_no: int
    status: str | None
    duration_ms: int | None
    error_code: str | None
    requested_model: str | None
    response_model: str | None
    provider: str | None
    finish_reason: str | None
    provider_response_id: str | None
    num_tokens_input: int | None
    num_tokens_output: int | None


class DebugStepProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: Any
    step_order: Any
    assistant_id: Any
    io_types: dict[str, Any]
    input: dict[str, Any]
    output: dict[str, Any]
    rag: dict[str, Any] | None = None
    attempts: list[DebugAttemptProjection]


class DebugRunTokenUsageProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    num_tokens_input: int
    num_tokens_output: int
    num_tokens_total: int


class DebugRunSummaryProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    steps_count: int
    completed_steps: int
    failed_steps: int
    attempts_count: int
    artifacts_count: int
    duration_ms: int | None
    models_used: list[str]
    token_usage: DebugRunTokenUsageProjection | None = None


def build_debug_export(
    *,
    run: FlowRun,
    version: FlowVersion,
    step_results: list[FlowStepResult] | None = None,
    step_attempts: list[FlowStepAttempt] | None = None,
    result_files: list[FlowRunStepResultFile] | None = None,
    rerun_operations: list[FlowRunRerunOperation] | None = None,
    rerun_invalidated_steps: list[FlowRunRerunInvalidatedStep] | None = None,
) -> dict[str, Any]:
    definition_snapshot = version.definition_json
    evidence_generated_at = _latest_evidence_timestamp(
        run=run,
        version=version,
        step_results=step_results or [],
        step_attempts=step_attempts or [],
        rerun_operations=rerun_operations or [],
        rerun_invalidated_steps=rerun_invalidated_steps or [],
    )
    rag_by_step_order: dict[int, dict[str, Any]] = {}
    for result in step_results or []:
        input_payload = result.input_payload_json
        step_order = result.step_order
        if not isinstance(input_payload, dict):
            continue
        rag_metadata = input_payload.get("rag")
        if not isinstance(rag_metadata, dict):
            continue
        normalized_step_order = parse_step_order(step_order)
        if normalized_step_order is None:
            continue
        rag_by_step_order[normalized_step_order] = rag_metadata
    attempts_by_step_order: dict[int, list[DebugAttemptProjection]] = {}
    for attempt in step_attempts or []:
        normalized_step_order = parse_step_order(attempt.step_order)
        if normalized_step_order is None:
            continue
        attempts_by_step_order.setdefault(normalized_step_order, []).append(
            normalize_debug_attempt(attempt)
        )

    raw_steps = definition_snapshot.get("steps")
    normalized_steps: list[dict[str, Any]] = []
    if isinstance(raw_steps, list):
        for raw_step in cast(list[object], raw_steps):
            if isinstance(raw_step, dict):
                raw_step_dict = cast(FlowPersistedJsonObject, raw_step)
                parsed_step_order = parse_step_order(
                    raw_step_dict.get("step_order"), default=0
                )
                step_order = parsed_step_order if parsed_step_order is not None else 0
                normalized_steps.append(
                    normalize_debug_step(
                        raw_step_dict,
                        rag_metadata=rag_by_step_order.get(step_order),
                        attempts=attempts_by_step_order.get(step_order, []),
                    )
                )
    summary = DebugRunSummaryProjection(
        steps_count=len(normalized_steps),
        completed_steps=sum(
            1
            for result in step_results or []
            if _normalize_status(result.status) == "completed"
        ),
        failed_steps=sum(
            1
            for result in step_results or []
            if _normalize_status(result.status) == "failed"
        ),
        attempts_count=sum(
            len(attempts) for attempts in attempts_by_step_order.values()
        ),
        artifacts_count=len({str(item.file_id) for item in result_files or []}),
        duration_ms=_calculate_duration_ms(run.created_at, run.updated_at),
        models_used=_collect_models_used(step_attempts or []),
        token_usage=_build_run_token_usage_summary(step_attempts or []),
    )

    return {
        "schema_version": DEBUG_EXPORT_SCHEMA_VERSION,
        "generated_at": evidence_generated_at.isoformat(),
        "run": {
            "run_id": str(run.id),
            "flow_id": str(run.flow_id),
            "flow_version": run.flow_version,
            "trace_id": str(run.trace_id),
            "status": run.status.value,
            "summary": summary.model_dump(mode="json"),
        },
        "definition": {
            "flow_id": str(version.flow_id),
            "version": version.version,
            "checksum": version.definition_checksum,
            "steps_count": len(normalized_steps),
        },
        "definition_snapshot": definition_snapshot,
        "steps": normalized_steps,
        "security": {
            "redaction_applied": False,
            "classification_field": "output_classification_override",
        },
    }


def _latest_evidence_timestamp(
    *,
    run: FlowRun,
    version: FlowVersion,
    step_results: list[FlowStepResult],
    step_attempts: list[FlowStepAttempt],
    rerun_operations: list[FlowRunRerunOperation],
    rerun_invalidated_steps: list[FlowRunRerunInvalidatedStep],
) -> datetime:
    timestamps = [run.updated_at, version.updated_at]
    timestamps.extend(result.updated_at for result in step_results)
    timestamps.extend(attempt.updated_at for attempt in step_attempts)
    timestamps.extend(operation.updated_at for operation in rerun_operations)
    timestamps.extend(step.updated_at for step in rerun_invalidated_steps)
    return max(timestamps)


def _build_run_token_usage_summary(
    step_attempts: list[FlowStepAttempt],
) -> DebugRunTokenUsageProjection | None:
    num_tokens_input = sum(attempt.num_tokens_input or 0 for attempt in step_attempts)
    num_tokens_output = sum(attempt.num_tokens_output or 0 for attempt in step_attempts)
    num_tokens_total = num_tokens_input + num_tokens_output
    if num_tokens_total == 0:
        return None
    return DebugRunTokenUsageProjection(
        num_tokens_input=num_tokens_input,
        num_tokens_output=num_tokens_output,
        num_tokens_total=num_tokens_total,
    )


def parse_step_order(value: Any, *, default: int | None = None) -> int | None:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if stripped == "":
            return default
        try:
            return int(stripped)
        except ValueError:
            return default
    return default


def normalize_debug_step(
    step: dict[str, Any],
    *,
    rag_metadata: dict[str, Any] | None = None,
    attempts: list[DebugAttemptProjection] | None = None,
) -> dict[str, Any]:
    input_type = step.get("input_type")
    output_type = step.get("output_type")
    return DebugStepProjection(
        step_id=step.get("step_id"),
        step_order=step.get("step_order"),
        assistant_id=step.get("assistant_id"),
        io_types={
            "input": input_type,
            "output": output_type,
        },
        input={
            "source": step.get("input_source"),
            "type": input_type,
            "contract": step.get("input_contract"),
            "bindings": step.get("input_bindings"),
            "config": step.get("input_config"),
        },
        output={
            "mode": step.get("output_mode"),
            "type": output_type,
            "contract": step.get("output_contract"),
            "classification": step.get("output_classification_override"),
            "config": step.get("output_config"),
        },
        rag=_normalize_debug_rag(rag_metadata),
        attempts=list(attempts or []),
    ).model_dump(mode="json")


def normalize_debug_attempt(attempt: FlowStepAttempt) -> DebugAttemptProjection:
    started_at = attempt.started_at
    finished_at = attempt.finished_at
    duration_ms = None
    attempt_no = attempt.attempt_no
    if finished_at is not None:
        duration_ms = max(
            0,
            int((finished_at - started_at).total_seconds() * 1000),
        )
    model_parameters = None
    if isinstance(attempt.provenance_json, dict):
        llm_payload = attempt.provenance_json.get("llm")
        if isinstance(llm_payload, dict):
            llm_payload_dict = cast(FlowPersistedJsonObject, llm_payload)
            raw_model_parameters = llm_payload_dict.get("model_parameters")
            if isinstance(raw_model_parameters, dict):
                model_parameters = cast(FlowPersistedJsonObject, raw_model_parameters)
    provider = attempt.provider
    if provider is None and isinstance(model_parameters, dict):
        raw_provider = model_parameters.get("provider")
        if isinstance(raw_provider, str) and raw_provider.strip():
            provider = raw_provider.strip()
    return DebugAttemptProjection(
        attempt_no=attempt_no,
        status=_normalize_status(attempt.status),
        duration_ms=duration_ms,
        error_code=attempt.error_code,
        requested_model=attempt.requested_model,
        response_model=attempt.response_model,
        provider=provider,
        finish_reason=attempt.finish_reason,
        provider_response_id=attempt.provider_response_id,
        num_tokens_input=attempt.num_tokens_input,
        num_tokens_output=attempt.num_tokens_output,
    )


def _normalize_status(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    status_value = getattr(value, "value", None)
    return status_value if isinstance(status_value, str) else None


def _normalize_debug_rag(rag_metadata: dict[str, Any] | None) -> dict[str, Any] | None:
    return normalize_rag_payload(rag_metadata)


def _calculate_duration_ms(started_at: Any, finished_at: Any) -> int | None:
    if not isinstance(started_at, datetime) or not isinstance(finished_at, datetime):
        return None
    return max(0, int((finished_at - started_at).total_seconds() * 1000))


def _collect_models_used(step_attempts: list[FlowStepAttempt]) -> list[str]:
    models: list[str] = []
    for attempt in step_attempts:
        candidate = attempt.response_model or attempt.requested_model
        if candidate is None and isinstance(attempt.provenance_json, dict):
            llm_payload = attempt.provenance_json.get("llm")
            if isinstance(llm_payload, dict):
                llm_payload_dict = cast(FlowPersistedJsonObject, llm_payload)
                model_parameters = llm_payload_dict.get("model_parameters")
                if isinstance(model_parameters, dict):
                    model_parameters_dict = cast(
                        FlowPersistedJsonObject, model_parameters
                    )
                    raw_model_name = model_parameters_dict.get("model_name")
                    if isinstance(raw_model_name, str) and raw_model_name.strip():
                        candidate = raw_model_name.strip()
        if isinstance(candidate, str) and candidate.strip():
            models.append(candidate.strip())
    return list(dict.fromkeys(models))
