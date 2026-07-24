from __future__ import annotations

from typing import Literal, TypeAlias, get_args

BuilderFormFieldType: TypeAlias = Literal[
    "text", "number", "date", "select", "multiselect"
]
FlowInputFieldProvenance: TypeAlias = Literal[
    "user_confirmed",
    "template_derived",
    "runtime_inferred",
    "model_proposed",
]


def builder_input_source_values() -> list[str]:
    """Authorable input-source values for AI Builder tool schemas."""

    from eneo.flows.enums import AIBuilderInputSource

    return [item.value for item in AIBuilderInputSource]


def builder_input_type_values() -> list[str]:
    """Authorable input-type values, filtered by builder-exposed Flow capability."""

    from eneo.flows.enums import AIBuilderInputType

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

    from eneo.flows.enums import FlowOutputType

    return [item.value for item in FlowOutputType]


def builder_output_mode_values() -> list[str]:
    """Output modes AI Builder can author without raw backend config."""

    from eneo.flows.enums import AIBuilderOutputMode

    return [item.value for item in AIBuilderOutputMode]


def builder_form_field_type_values() -> list[str]:
    """LLM-facing form-field types for AI Builder tool schemas."""

    return [value for value in get_args(BuilderFormFieldType) if isinstance(value, str)]


def document_delivery_mode_values() -> list[str]:
    """Document delivery modes derived from Flow output/mode capability rules."""

    from eneo.flows.enums import FlowOutputMode, FlowOutputType
    from eneo.flows.flow_capability_manifest import resolve_document_generation_mode

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
    from eneo.flows.flow_capability_manifest import CAPABILITY_REGISTRY

    return {
        capability_id.removeprefix("input_")
        for capability_id, capability in CAPABILITY_REGISTRY.items()
        if capability.exposure == "builder" and capability_id.startswith("input_")
    }


__all__ = [
    "BuilderFormFieldType",
    "FlowInputFieldProvenance",
    "builder_form_field_type_values",
    "builder_input_source_values",
    "builder_input_type_values",
    "builder_output_mode_values",
    "builder_output_type_values",
    "document_delivery_mode_values",
]
