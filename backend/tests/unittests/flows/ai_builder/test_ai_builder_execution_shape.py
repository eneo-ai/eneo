from __future__ import annotations

from eneo.flows.ai_builder.ai_builder_domain_models import FlowBuilderProposalContent
from eneo.flows.domain.step_mapped_execution import resolve_step_mapped_execution
from eneo.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
    StepSpec,
)


def _step(
    *,
    ref: str,
    input_source: InputSource = InputSource.FLOW_INPUT,
    input_type: InputType = InputType.TEXT,
    output_mode: OutputMode = OutputMode.PASS_THROUGH,
    output_type: OutputType | None = None,
    input_contract: dict[str, object] | None = None,
    output_contract: dict[str, object] | None = None,
    input_config: dict[str, object] | None = None,
) -> StepSpec:
    return StepSpec(
        plan_step_ref=ref,
        name=ref,
        assistant_spec=AssistantSpec(instructions="Process the input."),
        input_source=input_source,
        input_type=input_type,
        output_mode=output_mode,
        output_type=output_type
        or (OutputType.JSON if output_contract is not None else OutputType.TEXT),
        input_contract=input_contract,
        output_contract=output_contract,
        input_config=input_config,
    )


def _content(*steps: StepSpec) -> FlowBuilderProposalContent:
    return FlowBuilderProposalContent(
        spec=FlowDraftSpecCore(flow_name="Execution shape", steps=list(steps))
    )


def test_execution_shape_counts_model_paths_without_forcing_exclusive_buckets() -> None:
    content = _content(
        _step(
            ref="structured_completion",
            output_contract={"type": "object", "properties": {}},
        ),
        _step(
            ref="audio_completion",
            input_type=InputType.AUDIO,
            input_config={
                "runtime_input": {
                    "enabled": True,
                    "input_format": "audio",
                }
            },
        ),
        _step(
            ref="transcription",
            input_type=InputType.AUDIO,
            output_mode=OutputMode.TRANSCRIBE_ONLY,
        ),
        _step(ref="compose", output_mode=OutputMode.COMPOSE_TEXT),
    )

    assert content.execution_shape.completion_model_step_count == 2
    assert content.execution_shape.transcription_model_step_count == 2
    assert content.execution_shape.deterministic_step_count == 1
    assert content.execution_shape.schema_constrained_step_count == 1


def test_execution_shape_uses_audio_runtime_input_as_transcription_evidence() -> None:
    content = _content(
        _step(
            ref="audio_runtime_input",
            input_config={
                "runtime_input": {
                    "enabled": True,
                    "input_format": "audio",
                }
            },
        )
    )

    assert content.execution_shape.completion_model_step_count == 1
    assert content.execution_shape.transcription_model_step_count == 1
    assert content.execution_shape.deterministic_step_count == 0


def test_execution_shape_reports_authored_mapped_cardinality_in_step_order() -> None:
    source_reader = _step(
        ref="source_reader",
        input_type=InputType.DOCUMENT,
        output_type=OutputType.JSON,
        output_contract={
            "type": "object",
            "properties": {
                "documents": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "source_label": {"type": "string"},
                            "source_file_id": {"type": "string"},
                        },
                        "required": ["source_label", "source_file_id"],
                    },
                }
            },
            "required": ["documents"],
        },
        input_config={
            "runtime_input": {
                "enabled": True,
                "execution_mode": "per_source",
                "max_files": 3,
            }
        },
    )
    item_reader = _step(
        ref="item_reader",
        input_source=InputSource.PREVIOUS_STEP,
        input_type=InputType.JSON,
        output_type=OutputType.JSON,
        input_contract={
            "type": "object",
            "properties": {"items": {"type": "array", "items": {"type": "object"}}},
            "required": ["items"],
        },
        output_contract={
            "type": "object",
            "properties": {"results": {"type": "array", "items": {"type": "object"}}},
            "required": ["results"],
        },
        input_config={"item_map": {"enabled": True, "max_items": 5}},
    )
    content = _content(source_reader, item_reader, _step(ref="single"))

    runtime_resolutions = [
        resolve_step_mapped_execution(
            input_source=step.input_source,
            input_type=step.input_type,
            output_mode=step.output_mode,
            output_type=step.output_type,
            input_config=step.input_config,
        )
        for step in (source_reader, item_reader)
    ]
    assert [
        (resolution.execution_mode, resolution.maximum_items)
        for resolution in runtime_resolutions
        if resolution is not None
    ] == [("per_source", 3), ("per_item", 5)]

    assert [
        bound.model_dump(mode="json")
        for bound in content.execution_shape.mapped_step_upper_bounds
    ] == [
        {
            "plan_step_ref": "source_reader",
            "execution_mode": "per_source",
            "maximum_items": 3,
        },
        {
            "plan_step_ref": "item_reader",
            "execution_mode": "per_item",
            "maximum_items": 5,
        },
    ]


def test_execution_shape_is_output_only_and_cannot_be_model_authored() -> None:
    validation_schema = FlowBuilderProposalContent.model_json_schema(mode="validation")
    serialization_schema = FlowBuilderProposalContent.model_json_schema(
        mode="serialization"
    )

    assert "execution_shape" not in validation_schema["properties"]
    assert serialization_schema["properties"]["execution_shape"]["readOnly"] is True
    assert "execution_shape" in serialization_schema["required"]
