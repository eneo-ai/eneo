from __future__ import annotations

import logging
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import replace

import pytest

from eneo.flows.ai_builder.ai_builder_assembly import lower as lower_module
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
    PreviousOutputRef,
    StructuredFieldDraft,
)
from eneo.flows.ai_builder.ai_builder_source_reader_contracts import SourceCaptureField
from eneo.flows.ai_builder.ai_builder_validator import validate_spec
from eneo.flows.ai_builder.planning_state import AggregationIntent
from eneo.flows.flow_authoring_spec import (
    FormFieldSpec,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
)


@contextmanager
def _captured_lower_logs() -> Generator[list[logging.LogRecord]]:
    """Capture the module's records directly.

    The application logger is parentless and owns its handler, so ``caplog``
    (a root handler) never sees it.
    """

    records: list[logging.LogRecord] = []

    class CaptureHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = CaptureHandler()
    old_level = lower_module.logger.level
    lower_module.logger.setLevel(logging.INFO)
    lower_module.logger.addHandler(handler)
    try:
        yield records
    finally:
        lower_module.logger.removeHandler(handler)
        lower_module.logger.setLevel(old_level)


def _text_step(
    *,
    name: str = "Write answer",
    instructions: str = "Write the answer.",
    input_source: InputSource = InputSource.FLOW_INPUT,
    input_type: InputType = InputType.TEXT,
    output_type: OutputType = OutputType.TEXT,
    output_mode: OutputMode = OutputMode.PASS_THROUGH,
    underlag_channel: UnderlagChannel = "flow_input",
    semantic_origin_eligible: bool = False,
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
        semantic_origin_eligible=semantic_origin_eligible,
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


def test_lowering_preserves_explicit_compose_output_mode() -> None:
    plan = _plan(
        steps=(
            _text_step(
                name="Compose report",
                output_type=OutputType.TEXT,
                output_mode=OutputMode.COMPOSE_TEXT,
            ),
        )
    )

    lowered = lower_assembly_plan(plan)

    assert lowered.steps[0].output_mode == OutputMode.COMPOSE_TEXT


@pytest.mark.parametrize(
    ("output_type", "output_mode", "citations_requested", "citation_mode_kept"),
    [
        (OutputType.TEXT, OutputMode.PASS_THROUGH, False, False),
        (OutputType.TEXT, OutputMode.PASS_THROUGH, True, True),
        (OutputType.JSON, OutputMode.PASS_THROUGH, False, False),
        (OutputType.JSON, OutputMode.PASS_THROUGH, True, False),
        (OutputType.PDF, OutputMode.RENDER_VERBATIM, True, False),
        (OutputType.DOCX, OutputMode.RENDER_VERBATIM, True, False),
    ],
)
def test_create_lowering_resolves_citation_capability_before_validation(
    output_type: OutputType,
    output_mode: OutputMode,
    citations_requested: bool,
    citation_mode_kept: bool,
) -> None:
    diagnostics = []
    step = _text_step(output_type=output_type, output_mode=output_mode)
    step = replace(step, citations_requested=citations_requested)

    lowered = lower_assembly_plan(
        _plan(steps=(step,)),
        field_diagnostics=diagnostics,
    )

    assert (
        lowered.steps[0].output_config == {"citation_mode": "inline_inref_sidecar"}
    ) is citation_mode_kept
    assert [warning.code for warning in diagnostics] == (
        []
        if not citations_requested or citation_mode_kept
        else ["citation_mode_unsupported"]
    )
    assert validate_spec(lowered).valid


def test_create_lowering_uses_terminal_delivery_for_citations_once_per_flow() -> None:
    diagnostics = []
    cited_text_step = replace(
        _text_step(name="Write cited text"),
        citations_requested=True,
    )
    cited_json_terminal = replace(
        _text_step(
            name="Structure final result",
            input_source=InputSource.PREVIOUS_STEP,
            input_type=InputType.TEXT,
            output_type=OutputType.JSON,
            underlag_channel="implicit_previous",
        ),
        citations_requested=True,
    )

    lowered = lower_assembly_plan(
        _plan(steps=(cited_text_step, cited_json_terminal)),
        field_diagnostics=diagnostics,
    )

    assert [step.output_config for step in lowered.steps] == [None, None]
    assert [
        (warning.code, warning.severity.value, warning.step_ref)
        for warning in diagnostics
    ] == [("citation_mode_unsupported", "warning", "step_a")]
    assert validate_spec(lowered).valid


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


def test_lowering_logs_terminal_output_fields_suppressed_by_schema() -> None:
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

    with _captured_lower_logs() as records:
        lower_assembly_plan(plan)

    record = next(
        item
        for item in records
        if item.getMessage() == "ai_builder_terminal_output_fields_suppressed_by_schema"
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
    first_step = _text_step(
        name="Extract facts",
        output_type=OutputType.JSON,
        output_fields=(_field("summary"),),
    )
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


def test_plan_rejects_previous_ref_missing_from_structured_contract() -> None:
    first_step = _text_step(name="Read source")
    structured_step = _text_step(
        name="Extract facts",
        input_source=InputSource.PREVIOUS_STEP,
        input_type=InputType.TEXT,
        output_type=OutputType.JSON,
        underlag_channel="implicit_previous",
        output_fields=(_field("summary"),),
    )
    unknown_ref_step = _text_step(
        name="Write final",
        input_source=InputSource.PREVIOUS_STEP,
        input_type=InputType.TEXT,
        underlag_channel="field_refs",
        previous_field_refs=(PreviousFieldRef(from_step=2, field_path="details"),),
    )

    with pytest.raises(ValueError, match="undeclared structured field 'details'"):
        _plan(steps=(first_step, structured_step, unknown_ref_step))


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


def test_plan_keeps_declared_field_refs_even_when_they_cover_all_fields() -> None:
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

    plan = _plan(steps=(first_step, field_ref_step))

    assert plan.steps[-1].underlag_channel == "field_refs"

    incorrect_whole_object_step = _text_step(
        name="Write from all facts",
        input_source=InputSource.PREVIOUS_STEP,
        input_type=InputType.TEXT,
        underlag_channel="whole_object",
        previous_field_refs=broad_field_refs,
    )

    with pytest.raises(ValueError, match="expected 'field_refs'"):
        _plan(steps=(first_step, incorrect_whole_object_step))


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


def test_plan_rejects_duplicate_form_field_refs_on_one_target() -> None:
    form_field = FormFieldSpec(
        name="tone",
        label="Tone",
        type="text",
        required=True,
    )

    with pytest.raises(ValueError, match="more than once: tone"):
        FlowAssemblyPlan(
            flow_name="Test flow",
            flow_description="",
            form_fields=(form_field,),
            steps=(
                _text_step(
                    semantic_origin_eligible=True,
                    form_field_refs=("tone", "tone"),
                ),
            ),
            terminal_output_schema=None,
            source_reader_required_fields=(),
            aggregation_intent="linear",
            ui_language=None,
        )


def test_plan_rejects_form_field_on_ineligible_helper() -> None:
    form_field = FormFieldSpec(
        name="tone",
        label="Tone",
        type="text",
        required=True,
    )

    with pytest.raises(ValueError, match="not a legal form-field target"):
        FlowAssemblyPlan(
            flow_name="Test flow",
            flow_description="",
            form_fields=(form_field,),
            steps=(_text_step(form_field_refs=("tone",)),),
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


def test_plan_admits_localized_output_field_schema_keys() -> None:
    # Identity is folded, wording is the author's: a Swedish key survives
    # verbatim instead of being policed into an English lexicon.
    source_reader = _text_step(
        name="Extract facts",
        input_type=InputType.DOCUMENT,
        output_type=OutputType.JSON,
        output_fields=(_field("sammanfattning"),),
    )

    plan = _plan(steps=(source_reader,))

    assert plan.steps[0].output_fields[0].name == "sammanfattning"


def test_plan_rejects_future_previous_output_refs() -> None:
    first_step = _text_step(name="Extract facts", output_type=OutputType.JSON)
    future_ref_step = _text_step(
        name="Write final",
        input_source=InputSource.PREVIOUS_STEP,
        input_type=InputType.TEXT,
        underlag_channel="whole_object",
        previous_output_refs=(PreviousOutputRef(from_step=3, label="Later"),),
    )

    with pytest.raises(ValueError, match="no later than 1"):
        _plan(steps=(first_step, future_ref_step))


def test_flow_input_step_rejects_previous_output_refs() -> None:
    with pytest.raises(ValueError, match="cannot reference previous output"):
        _text_step(
            name="Read input",
            previous_output_refs=(PreviousOutputRef(from_step=1, label="Prior"),),
        )


def test_fan_in_step_rejects_previous_output_refs() -> None:
    with pytest.raises(ValueError, match="cannot combine fan-in"):
        _text_step(
            name="Combine",
            input_source=InputSource.ALL_PREVIOUS_STEPS,
            underlag_channel="fan_in",
            previous_output_refs=(PreviousOutputRef(from_step=1, label="Prior"),),
        )
