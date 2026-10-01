from __future__ import annotations

from typing import Literal, TypeAlias, get_args

BuilderFormFieldType: TypeAlias = Literal[
    "text", "number", "date", "select", "multiselect", "list"
]
FlowInputFieldProvenance: TypeAlias = Literal[
    "user_confirmed",
    "template_derived",
    "runtime_inferred",
    "model_proposed",
]


def builder_form_field_type_values() -> list[str]:
    """LLM-facing form-field types for AI Builder tool schemas."""

    return [value for value in get_args(BuilderFormFieldType) if isinstance(value, str)]


def document_delivery_mode_values() -> list[str]:
    """Document delivery modes an edit may name, derived from the cells a saved
    step may occupy."""

    from eneo.flows.enums import FlowOutputMode, FlowOutputType
    from eneo.flows.flow_capability_manifest import (
        CapabilityProjection,
        projection_cells,
        resolve_document_generation_mode,
    )

    editable = {
        (cell[2], cell[3])
        for cell in projection_cells(CapabilityProjection.EDITABLE_EXISTING)
    }
    values: list[str] = ["not_applicable"]
    for output_type in FlowOutputType:
        for output_mode in FlowOutputMode:
            if (output_type, output_mode) not in editable:
                continue
            mode = resolve_document_generation_mode(
                output_type=output_type,
                output_mode=output_mode,
            )
            if mode is not None and mode not in values:
                values.append(mode)
    return values


__all__ = [
    "BuilderFormFieldType",
    "FlowInputFieldProvenance",
    "builder_form_field_type_values",
    "document_delivery_mode_values",
]
