from __future__ import annotations

from typing import get_args

from eneo.flows.ai_builder.ai_builder_flow_schema_values import (
    FlowInputFieldProvenance,
    document_delivery_mode_values,
)
from eneo.flows.ai_builder.ai_builder_new_step_models import DocumentDeliveryMode
from eneo.flows.enums import (
    FlowAuthoringInputType,
    FlowInputType,
    FlowOutputMode,
    FlowOutputType,
)
from eneo.flows.flow_authoring_spec import InputType
from eneo.flows.flow_capability_manifest import (
    RUNTIME_INPUT_MODE_BY_TYPE,
    CapabilityProjection,
    projection_values,
    resolve_document_generation_mode,
)


def test_wire_vocabulary_per_projection_is_declared_outright() -> None:
    editable = CapabilityProjection.EDITABLE_EXISTING
    proposable = CapabilityProjection.PROPOSABLE_NEW

    assert projection_values(editable, "input_source") == (
        "flow_input",
        "previous_step",
        "all_previous_steps",
    )
    assert projection_values(editable, "input_type") == (
        "text",
        "json",
        "audio",
        "document",
        "file",
        "any",
    )
    assert projection_values(editable, "output_type") == ("text", "json", "pdf", "docx")
    assert projection_values(proposable, "output_mode") == (
        "pass_through",
        "compose_text",
        "transcribe_only",
        "template_fill",
        "render_verbatim",
    )
    assert "speaker_mapping" in projection_values(editable, "output_mode")
    assert "speaker_mapping" not in projection_values(proposable, "output_mode")


def test_flow_input_field_provenance_vocabulary_is_complete_and_ordered() -> None:
    assert get_args(FlowInputFieldProvenance) == (
        "user_confirmed",
        "template_derived",
        "runtime_inferred",
        "model_proposed",
    )


def test_builder_runtime_input_modes_are_covered_by_schema_input_types() -> None:
    assert {input_type.value for input_type in RUNTIME_INPUT_MODE_BY_TYPE} <= set(
        projection_values(CapabilityProjection.PROPOSABLE_NEW, "input_type")
    )


def test_builder_exposed_flow_input_types_bridge_to_authoring_input_type() -> None:
    values = projection_values(CapabilityProjection.PROPOSABLE_NEW, "input_type")
    exposed_flow_input_types = [FlowInputType(value) for value in values]

    assert [InputType(input_type.value) for input_type in exposed_flow_input_types] == [
        FlowAuthoringInputType(value) for value in values
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


def test_the_document_delivery_literal_equals_the_derived_modes() -> None:
    # The typed wire literal cannot be derived under strict typing, so it is
    # pinned to the manifest-derived values the tool schemas offer.
    assert list(get_args(DocumentDeliveryMode)) == document_delivery_mode_values()
