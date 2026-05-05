from __future__ import annotations

from intric.flows.enums import (
    AIBuilderInputSource,
    AIBuilderInputType,
    AIBuilderOutputMode,
    FlowOutputMode,
    FlowOutputType,
)
from intric.flows.flow_capability_manifest import (
    CAPABILITY_REGISTRY,
    resolve_document_generation_mode,
)


def builder_input_source_values() -> list[str]:
    """Authorable input-source values for AI Builder tool schemas."""

    return [item.value for item in AIBuilderInputSource]


def builder_input_type_values() -> list[str]:
    """Authorable input-type values, filtered by builder-exposed Flow capability."""

    exposed_input_types = _builder_exposed_input_types()
    return [
        item.value for item in AIBuilderInputType if item.value in exposed_input_types
    ]


def builder_output_type_values() -> list[str]:
    """Authorable output types for AI Builder.

    Flow output types are already the builder-facing output type enum; capability
    parity is enforced in tests so new Flow output artifacts cannot drift
    silently from the AI Builder schema.
    """

    return [item.value for item in FlowOutputType]


def builder_output_mode_values() -> list[str]:
    """Output modes AI Builder can author without raw backend config."""

    return [item.value for item in AIBuilderOutputMode]


def builder_form_field_type_values() -> list[str]:
    """LLM-facing form-field types for AI Builder tool schemas."""

    return ["text", "number", "date", "select", "multiselect"]


def document_delivery_mode_values() -> list[str]:
    """Document delivery modes derived from Flow output/mode capability rules."""

    values: list[str] = ["not_applicable"]
    seen = set(values)
    for output_type in FlowOutputType:
        for output_mode in FlowOutputMode:
            mode = resolve_document_generation_mode(
                output_type=output_type,
                output_mode=output_mode,
            )
            if mode is not None and mode not in seen:
                values.append(mode)
                seen.add(mode)
    return values


def _builder_exposed_input_types() -> set[str]:
    return {
        capability_id.removeprefix("input_")
        for capability_id, capability in CAPABILITY_REGISTRY.items()
        if capability.exposure == "builder" and capability_id.startswith("input_")
    }


__all__ = [
    "builder_form_field_type_values",
    "builder_input_source_values",
    "builder_input_type_values",
    "builder_output_mode_values",
    "builder_output_type_values",
    "document_delivery_mode_values",
]
