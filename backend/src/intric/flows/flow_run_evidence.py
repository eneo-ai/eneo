from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict
from intric.flows.domain.flow import FlowRun, FlowStepAttempt, FlowStepResult, FlowVersion

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
    mcp: dict[str, Any]
    rag: dict[str, Any] | None = None
    attempts: list[DebugAttemptProjection]


def build_debug_export(
    *,
    run: FlowRun,
    version: FlowVersion,
    step_results: list[FlowStepResult] | None = None,
    step_attempts: list[FlowStepAttempt] | None = None,
) -> dict[str, Any]:
    definition_snapshot = (
        version.definition_json
        if isinstance(version.definition_json, dict)
        else {}
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
    normalized_steps = []
    if isinstance(raw_steps, list):
        for raw_step in raw_steps:
            if isinstance(raw_step, dict):
                parsed_step_order = parse_step_order(raw_step.get("step_order"), default=0)
                step_order = parsed_step_order if parsed_step_order is not None else 0
                normalized_steps.append(
                    normalize_debug_step(
                        raw_step,
                        rag_metadata=rag_by_step_order.get(step_order),
                        attempts=attempts_by_step_order.get(step_order, []),
                    )
                )

    return {
        "schema_version": DEBUG_EXPORT_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run": {
            "run_id": str(run.id),
            "flow_id": str(run.flow_id),
            "flow_version": run.flow_version,
            "trace_id": str(run.trace_id),
            "status": run.status.value,
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
            "mcp_policy_field": "mcp_policy",
        },
    }


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
    raw_allowlist = step.get("mcp_tool_allowlist")
    tool_allowlist = raw_allowlist if isinstance(raw_allowlist, list) else []
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
        mcp={
            "policy": step.get("mcp_policy"),
            "tool_allowlist": tool_allowlist,
        },
        rag=rag_metadata if isinstance(rag_metadata, dict) else None,
        attempts=attempts or [],
    ).model_dump(mode="json")


def normalize_debug_attempt(attempt: FlowStepAttempt) -> DebugAttemptProjection:
    started_at = attempt.started_at
    finished_at = attempt.finished_at
    duration_ms = None
    attempt_no = attempt.attempt_no
    if started_at is not None and finished_at is not None:
        duration_ms = max(
            0,
            int((finished_at - started_at).total_seconds() * 1000),
        )
    return DebugAttemptProjection(
        attempt_no=attempt_no,
        status=_normalize_status(attempt.status),
        duration_ms=duration_ms,
        error_code=attempt.error_code,
        requested_model=attempt.requested_model,
        response_model=attempt.response_model,
        provider=attempt.provider,
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
