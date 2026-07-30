from __future__ import annotations

from eneo.flows.ai_builder.ai_builder_domain_models import FlowBuilderProposalContent
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
    input_type: InputType = InputType.TEXT,
    output_mode: OutputMode = OutputMode.PASS_THROUGH,
    output_contract: dict[str, object] | None = None,
    input_config: dict[str, object] | None = None,
) -> StepSpec:
    return StepSpec(
        plan_step_ref=ref,
        name=ref,
        assistant_spec=AssistantSpec(instructions="Process the input."),
        input_source=InputSource.FLOW_INPUT,
        input_type=input_type,
        output_mode=output_mode,
        output_type=(
            OutputType.JSON if output_contract is not None else OutputType.TEXT
        ),
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
    content = _content(
        _step(
            ref="source_reader",
            input_config={
                "runtime_input": {
                    "enabled": True,
                    "execution_mode": "per_source",
                    "max_files": 3,
                }
            },
        ),
        _step(
            ref="item_reader",
            input_config={"item_map": {"enabled": True, "max_items": 5}},
        ),
        _step(ref="single"),
    )

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
