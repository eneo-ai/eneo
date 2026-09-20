from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, cast

from pydantic import ValidationError

from eneo.flows.domain.runtime_input import build_runtime_input_config
from eneo.flows.domain.step_item_map import build_step_item_map_config
from eneo.flows.domain.text_processing import text_processing_config

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

    try:
        processing = text_processing_config(input_config)
    except ValidationError as exc:
        raise FlowStepMappedExecutionConfigurationError(
            "Step input_config.text_processing must select process_each_section."
        ) from exc
    if processing is not None:
        if per_source_configured or per_item_configured:
            raise FlowStepMappedExecutionConfigurationError(
                "Section processing cannot be nested with item_map or per_source."
            )
        if output_mode != "pass_through" or output_type != "json":
            raise FlowStepMappedExecutionConfigurationError(
                "Section processing requires a pass_through completion step with JSON output."
            )

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


def single_mapped_array_key(contract: dict[str, Any] | None) -> str | None:
    if not isinstance(contract, Mapping):
        return None
    properties = contract.get("properties")
    if not isinstance(properties, Mapping):
        return None
    typed_properties = cast(Mapping[str, object], properties)
    keys = tuple(typed_properties.keys())
    if len(keys) != 1:
        return None
    array_key = keys[0]
    array_schema = typed_properties[array_key]
    if not isinstance(array_schema, Mapping):
        return None
    typed_array_schema = cast(Mapping[str, object], array_schema)
    if typed_array_schema.get("type") != "array":
        return None
    item_schema = typed_array_schema.get("items")
    if not isinstance(item_schema, Mapping):
        return None
    typed_item_schema = cast(Mapping[str, object], item_schema)
    if typed_item_schema.get("type") != "object":
        return None
    return array_key


__all__ = [
    "FlowStepMappedExecution",
    "FlowStepMappedExecutionConfigurationError",
    "FlowStepMappedExecutionMode",
    "resolve_step_mapped_execution",
    "single_mapped_array_key",
]
