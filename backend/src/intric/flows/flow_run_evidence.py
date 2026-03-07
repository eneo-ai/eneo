from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from intric.flows.flow import FlowRun, FlowStepResult, FlowVersion

DEBUG_EXPORT_SCHEMA_VERSION = "eneo.flow.debug-export.v1"


def build_debug_export(
    *,
    run: FlowRun,
    version: FlowVersion,
    step_results: list[FlowStepResult] | None = None,
) -> dict[str, Any]:
    definition_snapshot = (
        version.definition_json
        if isinstance(version.definition_json, dict)
        else {}
    )
    rag_by_step_order: dict[int, dict[str, Any]] = {}
    for result in step_results or []:
        input_payload = getattr(result, "input_payload_json", None)
        step_order = getattr(result, "step_order", None)
        if not isinstance(input_payload, dict):
            model_dump = getattr(result, "model_dump", None)
            if callable(model_dump):
                dumped = model_dump(mode="json")
                if isinstance(dumped, dict):
                    if step_order is None:
                        step_order = dumped.get("step_order")
                    input_payload = dumped.get("input_payload_json")
        if not isinstance(input_payload, dict):
            continue
        rag_metadata = input_payload.get("rag")
        if not isinstance(rag_metadata, dict):
            continue
        normalized_step_order = parse_step_order(step_order)
        if normalized_step_order is None:
            continue
        rag_by_step_order[normalized_step_order] = rag_metadata

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
                    )
                )

    return {
        "schema_version": DEBUG_EXPORT_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run": {
            "run_id": str(run.id),
            "flow_id": str(run.flow_id),
            "flow_version": run.flow_version,
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
            "redaction_applied": True,
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
) -> dict[str, Any]:
    raw_allowlist = step.get("mcp_tool_allowlist")
    tool_allowlist = raw_allowlist if isinstance(raw_allowlist, list) else []
    input_type = step.get("input_type")
    output_type = step.get("output_type")
    return {
        "step_id": step.get("step_id"),
        "step_order": step.get("step_order"),
        "assistant_id": step.get("assistant_id"),
        "io_types": {
            "input": input_type,
            "output": output_type,
        },
        "input": {
            "source": step.get("input_source"),
            "type": input_type,
            "contract": step.get("input_contract"),
            "bindings": step.get("input_bindings"),
            "config": step.get("input_config"),
        },
        "output": {
            "mode": step.get("output_mode"),
            "type": output_type,
            "contract": step.get("output_contract"),
            "classification": step.get("output_classification_override"),
            "config": step.get("output_config"),
        },
        "mcp": {
            "policy": step.get("mcp_policy"),
            "tool_allowlist": tool_allowlist,
        },
        "rag": rag_metadata if isinstance(rag_metadata, dict) else None,
    }
