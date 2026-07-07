from __future__ import annotations

import pytest

from eneo.flows.ai_builder.ai_builder_assembly.plan import (
    FlowAssemblyPlan,
    PlannedStep,
    UnderlagChannel,
)
from eneo.flows.ai_builder.ai_builder_new_step_compiler import SourceCaptureField
from eneo.flows.ai_builder.ai_builder_new_step_models import (
    PreviousFieldRef,
    PreviousOutputRef,
    StructuredFieldDraft,
)
from eneo.flows.ai_builder.planning_state import AggregationIntent
from eneo.flows.flow_authoring_spec import (
    FormFieldSpec,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
)


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
    previous_output_refs: tuple[PreviousOutputRef, ...] = (),
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
        previous_output_refs=previous_output_refs,
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


def test_plan_rejects_non_immediate_previous_field_refs() -> None:
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

    with pytest.raises(ValueError, match="expected immediate previous step 2"):
        _plan(steps=(first_step, second_step, stale_ref_step))


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
