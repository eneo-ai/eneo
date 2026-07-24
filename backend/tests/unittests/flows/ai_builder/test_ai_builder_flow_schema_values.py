from __future__ import annotations

from typing import get_args

from eneo.flows.ai_builder.ai_builder_flow_schema_values import (
    FlowInputFieldProvenance,
    builder_input_source_values,
    builder_input_type_values,
    builder_output_mode_values,
    builder_output_type_values,
    document_delivery_mode_values,
)
from eneo.flows.enums import (
    AIBuilderInputSource,
    AIBuilderInputType,
    AIBuilderOutputMode,
    FlowInputType,
    FlowOutputMode,
    FlowOutputType,
)
from eneo.flows.flow_authoring_spec import InputType
from eneo.flows.flow_capability_manifest import (
    CAPABILITY_REGISTRY,
    RUNTIME_INPUT_MODE_BY_TYPE,
    resolve_document_generation_mode,
)


def test_builder_schema_values_follow_builder_exposed_flow_capabilities() -> None:
    exposed_input_types = {
        capability_id.removeprefix("input_")
        for capability_id, capability in CAPABILITY_REGISTRY.items()
        if capability.exposure == "builder" and capability_id.startswith("input_")
    }

    assert builder_input_source_values() == [
        item.value for item in AIBuilderInputSource
    ]
    assert builder_input_type_values() == [
        item.value for item in AIBuilderInputType if item.value in exposed_input_types
    ]
    assert set(builder_input_type_values()) == exposed_input_types
    assert builder_output_type_values() == [item.value for item in FlowOutputType]
    assert builder_output_mode_values() == [item.value for item in AIBuilderOutputMode]


def test_flow_input_field_provenance_vocabulary_is_complete_and_ordered() -> None:
    assert get_args(FlowInputFieldProvenance) == (
        "user_confirmed",
        "template_derived",
        "runtime_inferred",
        "model_proposed",
    )


def test_builder_runtime_input_modes_are_covered_by_schema_input_types() -> None:
    assert {input_type.value for input_type in RUNTIME_INPUT_MODE_BY_TYPE} <= set(
        builder_input_type_values()
    )


def test_builder_exposed_flow_input_types_bridge_to_authoring_input_type() -> None:
    exposed_flow_input_types = [
        FlowInputType(value) for value in builder_input_type_values()
    ]

    assert [InputType(input_type.value) for input_type in exposed_flow_input_types] == [
        AIBuilderInputType(value) for value in builder_input_type_values()
    ]


def test_document_delivery_modes_are_derived_from_flow_capability_rules() -> None:
    expected = {"not_applicable"}
    for output_type in FlowOutputType:
        for output_mode in FlowOutputMode:
            mode = resolve_document_generation_mode(
                output_type=output_type,
                output_mode=output_mode,
            )
            if mode is not None:
                expected.add(mode)

    assert set(document_delivery_mode_values()) == expected
