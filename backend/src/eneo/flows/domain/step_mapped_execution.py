from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from eneo.flows.domain.runtime_input import build_runtime_input_config
from eneo.flows.domain.step_item_map import build_step_item_map_config

FlowStepMappedExecutionMode = Literal["per_source", "per_item"]

_MAPPED_COMPLETION_OUTPUT_MODES = frozenset({"pass_through", "http_post"})


class FlowStepMappedExecutionConfigurationError(ValueError):
    """The authored mapping configuration cannot be dispatched by runtime."""


@dataclass(frozen=True, slots=True)
class FlowStepMappedExecution:
    execution_mode: FlowStepMappedExecutionMode
    maximum_items: int | None


def resolve_step_mapped_execution(
    *,
    input_source: str,
    input_type: str,
    output_mode: str,
    output_type: str,
    input_config: dict[str, Any] | None,
) -> FlowStepMappedExecution | None:
    """Resolve the mapped mode runtime will dispatch for one step."""

    runtime_input = build_runtime_input_config(input_config)
    item_map = build_step_item_map_config(input_config)
    per_source_configured = (
        runtime_input.enabled and runtime_input.execution_mode == "per_source"
    )
    per_item_configured = item_map.enabled

    if per_source_configured and per_item_configured:
        raise FlowStepMappedExecutionConfigurationError(
            "Configure only one mapped execution mode: per_source or per_item."
        )

    supports_mapped_completion = output_mode in _MAPPED_COMPLETION_OUTPUT_MODES
    if per_source_configured:
        if not (
            supports_mapped_completion
            and input_source == "flow_input"
            and input_type in {"document", "file"}
            and output_type == "json"
        ):
            raise FlowStepMappedExecutionConfigurationError(
                "Per-source mapped execution requires flow_input document or file "
                "input and JSON output on a completion step."
            )
        return FlowStepMappedExecution(
            execution_mode="per_source",
            maximum_items=runtime_input.max_files,
        )

    if per_item_configured:
        if not (
            supports_mapped_completion
            and input_source == "previous_step"
            and input_type == "json"
            and output_type == "json"
        ):
            raise FlowStepMappedExecutionConfigurationError(
                "Per-item mapped execution requires previous_step JSON input and "
                "JSON output on a completion step."
            )
        return FlowStepMappedExecution(
            execution_mode="per_item",
            maximum_items=item_map.max_items,
        )

    return None


__all__ = [
    "FlowStepMappedExecution",
    "FlowStepMappedExecutionConfigurationError",
    "FlowStepMappedExecutionMode",
    "resolve_step_mapped_execution",
]
