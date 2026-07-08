from __future__ import annotations

import logging

import pytest

from eneo.flows.ai_builder.ai_builder_assembly.fixed_steps import (
    fixed_audio_transcription_step,
    render_verbatim_step,
    template_fill_step,
    template_variable_reader_step,
)
from eneo.flows.ai_builder.ai_builder_assembly.lower import lower_assembly_plan
from eneo.flows.ai_builder.ai_builder_assembly.plan import (
    FlowAssemblyPlan,
    PlannedStep,
    UnderlagChannel,
)
from eneo.flows.ai_builder.ai_builder_new_step_models import (
    PreviousFieldRef,
    StructuredFieldDraft,
)
from eneo.flows.ai_builder.ai_builder_source_reader_contracts import SourceCaptureField
from eneo.flows.ai_builder.planning_state import AggregationIntent
from eneo.flows.flow_authoring_spec import (
    FormFieldSpec,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
)

_LOWER_LOGGER_NAME = "eneo.flows.ai_builder.ai_builder_assembly.lower"


def _text_step(
    *,
    name: str = "Write answer",
    instructions: str = "Write the answer.",
    input_source: InputSource = InputSource.FLOW_INPUT,
    input_type: InputType = InputType.TEXT,
    output_type: OutputType = OutputType.TEXT,
    output_mode: OutputMode = OutputMode.PASS_THROUGH,
    underlag_channel: UnderlagChannel = "flow_input",
    form_field_refs: tuple[str, ...] = (),
    previous_field_refs: tuple[PreviousFieldRef, ...] = (),
    output_fields: tuple[StructuredFieldDraft, ...] = (),
) -> PlannedStep:
    return PlannedStep(
        role="transform",
        name=name,
        instructions=instructions,
        input_source=input_source,
        input_type=input_type,
        output_type=output_type,
        output_mode=output_mode,
        underlag_channel=underlag_channel,
        form_field_refs=form_field_refs,
        previous_field_refs=previous_field_refs,
        output_fields=output_fields,
    )


def _field(name: str) -> StructuredFieldDraft:
    return StructuredFieldDraft(
        name=name,
        field_type="string",
        description=f"{name} field.",
    )


def _plan(
    *,
    steps: tuple[PlannedStep, ...],
    aggregation_intent: AggregationIntent = "linear",
) -> FlowAssemblyPlan:
    return FlowAssemblyPlan(
        flow_name="Test flow",
        flow_description="",
        form_fields=(),
        steps=steps,
        terminal_output_schema=None,
        source_reader_required_fields=(),
        aggregation_intent=aggregation_intent,
        ui_language=None,
    )


def test_planned_step_rejects_unsupported_capability_tuple() -> None:
    with pytest.raises(ValueError, match="unsupported capability tuple"):
        _text_step(
            output_type=OutputType.PDF,
            output_mode=OutputMode.PASS_THROUGH,
        )


def test_lowering_rejects_planned_output_mode_divergence() -> None:
    plan = _plan(
        steps=(
            _text_step(
                name="Fill DOCX",
                output_type=OutputType.DOCX,
                output_mode=OutputMode.TEMPLATE_FILL,
            ),
        )
    )

    with pytest.raises(ValueError, match="output_mode diverged"):
        lower_assembly_plan(plan)


def test_fixed_assembly_steps_default_to_swedish_copy() -> None:
    template_reader = template_variable_reader_step(
        runtime_input_type=InputType.DOCUMENT,
        runtime_required=True,
        runtime_max_files=None,
        ui_language=None,
    )
    template_fill = template_fill_step(ui_language=None)
    transcription = fixed_audio_transcription_step(
        runtime_required=True,
        runtime_max_files=None,
        ui_language=None,
    )
    renderer = render_verbatim_step(output_type=OutputType.PDF, ui_language=None)

    assert template_reader.name == "Extrahera mallvariabler"
    assert template_fill.name == "Fyll DOCX-mall"
    assert transcription.name == "Transkribera ljud"
    assert renderer.name == "Rendera PDF"


def test_fixed_assembly_steps_use_english_when_requested() -> None:
    template_reader = template_variable_reader_step(
        runtime_input_type=InputType.DOCUMENT,
        runtime_required=True,
        runtime_max_files=None,
        ui_language="en",
    )
    renderer = render_verbatim_step(output_type=OutputType.PDF, ui_language="en")

    assert template_reader.name == "Extract template variables"
    assert renderer.name == "Render PDF"


def test_lowering_logs_terminal_output_fields_suppressed_by_schema(caplog) -> None:
    caplog.set_level(logging.INFO, logger=_LOWER_LOGGER_NAME)
    plan = FlowAssemblyPlan(
        flow_name="Report",
        flow_description="",
        form_fields=(),
        steps=(
            _text_step(
                output_type=OutputType.JSON,
                output_fields=(_field("model_authored_summary"),),
            ),
        ),
        terminal_output_schema={
            "type": "object",
            "properties": {"model_authored_summary": {"type": "string"}},
        },
        source_reader_required_fields=(),
        aggregation_intent="linear",
        ui_language=None,
    )

    lower_assembly_plan(plan)

    record = next(
        item
        for item in caplog.records
        if item.message == "ai_builder_terminal_output_fields_suppressed_by_schema"
    )
    assert record.step_index == 1
    assert record.step_name == "Write answer"
    assert record.field_names == ["model_authored_summary"]


def test_planned_step_rejects_empty_name_and_instructions() -> None:
    with pytest.raises(ValueError, match="non-empty name"):
        _text_step(name=" ")

    with pytest.raises(ValueError, match="non-empty instructions"):
        _text_step(instructions=" ")


def test_planned_step_rejects_template_variables_in_instructions() -> None:
    with pytest.raises(ValueError, match="must not contain template variables"):
        _text_step(instructions="Use {{ step_input.text }} directly.")


def test_plan_rejects_incompatible_previous_step_chain() -> None:
    docx_step = _text_step(
        name="Fill template",
        output_type=OutputType.DOCX,
        output_mode=OutputMode.TEMPLATE_FILL,
    )
    json_reader = _text_step(
        name="Read previous as JSON",
        input_source=InputSource.PREVIOUS_STEP,
        input_type=InputType.JSON,
        underlag_channel="implicit_previous",
    )

    with pytest.raises(ValueError, match="not chain-compatible"):
        _plan(steps=(docx_step, json_reader))


def test_plan_rejects_non_first_flow_input_step() -> None:
    second_source_step = _text_step(name="Read source again")

    with pytest.raises(ValueError, match="Only the first"):
        _plan(steps=(_text_step(), second_source_step))


def test_plan_allows_earlier_previous_field_refs() -> None:
    first_step = _text_step(name="Extract facts", output_type=OutputType.JSON)
    second_step = _text_step(
        name="Write interim",
        input_source=InputSource.PREVIOUS_STEP,
        input_type=InputType.JSON,
        underlag_channel="implicit_previous",
    )
    stale_ref_step = _text_step(
        name="Write final",
        input_source=InputSource.PREVIOUS_STEP,
        underlag_channel="field_refs",
        previous_field_refs=(
            PreviousFieldRef(
                from_step=1,
                field_path="summary",
                label="Summary",
            ),
        ),
    )

    plan = _plan(steps=(first_step, second_step, stale_ref_step))

    assert plan.steps[-1].previous_field_refs[0].from_step == 1


def test_plan_rejects_future_previous_field_refs() -> None:
    first_step = _text_step(name="Extract facts", output_type=OutputType.JSON)
    future_ref_step = _text_step(
        name="Write final",
        input_source=InputSource.PREVIOUS_STEP,
        input_type=InputType.TEXT,
        underlag_channel="field_refs",
        previous_field_refs=(
            PreviousFieldRef(
                from_step=3,
                field_path="summary",
                label="Summary",
            ),
        ),
    )

    with pytest.raises(ValueError, match="no later than 1"):
        _plan(steps=(first_step, future_ref_step))


def test_plan_requires_whole_object_channel_for_json_previous_text_input() -> None:
    first_step = _text_step(
        name="Extract facts",
        output_type=OutputType.JSON,
        output_fields=(_field("summary"),),
    )
    implicit_step = _text_step(
        name="Write from structured facts",
        input_source=InputSource.PREVIOUS_STEP,
        input_type=InputType.TEXT,
        underlag_channel="implicit_previous",
    )

    with pytest.raises(ValueError, match="expected 'whole_object'"):
        _plan(steps=(first_step, implicit_step))

    whole_object_step = _text_step(
        name="Write from structured facts",
        input_source=InputSource.PREVIOUS_STEP,
        input_type=InputType.TEXT,
        underlag_channel="whole_object",
    )

    plan = _plan(steps=(first_step, whole_object_step))

    assert plan.steps[-1].underlag_channel == "whole_object"


def test_plan_requires_whole_object_channel_for_broad_previous_field_refs() -> None:
    first_step = _text_step(
        name="Extract facts",
        output_type=OutputType.JSON,
        output_fields=(_field("summary"), _field("details")),
    )
    broad_field_refs = (
        PreviousFieldRef(from_step=1, field_path="summary"),
        PreviousFieldRef(from_step=1, field_path="details"),
    )
    field_ref_step = _text_step(
        name="Write from all facts",
        input_source=InputSource.PREVIOUS_STEP,
        input_type=InputType.TEXT,
        underlag_channel="field_refs",
        previous_field_refs=broad_field_refs,
    )

    with pytest.raises(ValueError, match="expected 'whole_object'"):
        _plan(steps=(first_step, field_ref_step))

    whole_object_step = _text_step(
        name="Write from all facts",
        input_source=InputSource.PREVIOUS_STEP,
        input_type=InputType.TEXT,
        underlag_channel="whole_object",
        previous_field_refs=broad_field_refs,
    )

    plan = _plan(steps=(first_step, whole_object_step))

    assert plan.steps[-1].underlag_channel == "whole_object"


def test_plan_rejects_linear_fan_in() -> None:
    fan_in_step = _text_step(
        name="Compose from all prior work",
        input_source=InputSource.ALL_PREVIOUS_STEPS,
        underlag_channel="fan_in",
    )

    with pytest.raises(ValueError, match="fan-in requires aggregate or compare"):
        _plan(steps=(_text_step(), fan_in_step))


def test_plan_allows_aggregate_fan_in() -> None:
    fan_in_step = _text_step(
        name="Compose from all prior work",
        input_source=InputSource.ALL_PREVIOUS_STEPS,
        underlag_channel="fan_in",
    )

    plan = _plan(
        steps=(_text_step(), fan_in_step),
        aggregation_intent="aggregate",
    )

    assert plan.steps[-1].underlag_channel == "fan_in"


def test_plan_rejects_unplaced_form_fields() -> None:
    form_field = FormFieldSpec(
        name="tone",
        label="Tone",
        type="text",
        required=True,
    )

    with pytest.raises(ValueError, match="no step placement: tone"):
        FlowAssemblyPlan(
            flow_name="Test flow",
            flow_description="",
            form_fields=(form_field,),
            steps=(_text_step(),),
            terminal_output_schema=None,
            source_reader_required_fields=(),
            aggregation_intent="linear",
            ui_language=None,
        )


def test_plan_rejects_source_reader_obligation_without_reader_step() -> None:
    with pytest.raises(ValueError, match="source-reader planned step"):
        FlowAssemblyPlan(
            flow_name="Test flow",
            flow_description="",
            form_fields=(),
            steps=(_text_step(),),
            terminal_output_schema=None,
            source_reader_required_fields=(
                SourceCaptureField(name="case_id", description="Case ID"),
            ),
            aggregation_intent="linear",
            ui_language=None,
        )


def test_plan_rejects_incomplete_source_reader_contract() -> None:
    source_reader = _text_step(
        name="Extract facts",
        input_type=InputType.DOCUMENT,
        output_type=OutputType.JSON,
        output_fields=(_field("summary"),),
    )

    with pytest.raises(ValueError, match="must be complete before lowering"):
        FlowAssemblyPlan(
            flow_name="Test flow",
            flow_description="",
            form_fields=(),
            steps=(source_reader,),
            terminal_output_schema=None,
            source_reader_required_fields=(
                SourceCaptureField(name="case_id", description="Case ID"),
            ),
            aggregation_intent="linear",
            ui_language=None,
        )


def test_plan_rejects_localized_output_field_schema_keys() -> None:
    source_reader = _text_step(
        name="Extract facts",
        input_type=InputType.DOCUMENT,
        output_type=OutputType.JSON,
        output_fields=(_field("sammanfattning"),),
    )

    with pytest.raises(ValueError, match="ASCII English schema keys"):
        _plan(steps=(source_reader,))
