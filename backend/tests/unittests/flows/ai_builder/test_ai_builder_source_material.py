from __future__ import annotations

from eneo.flows.ai_builder.ai_builder_new_step_models import NewStepDraft
from eneo.flows.ai_builder.ai_builder_source_material import (
    SourceMaterialBindingStatus,
    create_steps_return_material_report,
    iter_compiled_source_material_boundaries,
    primary_source_material_ref_for_steps,
    source_material_binding_status,
    source_material_label_for_text,
    source_material_question_for_boundary,
)
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
    name: str,
    input_source: InputSource,
    instructions: str | None = None,
    input_type: InputType = InputType.TEXT,
    output_type: OutputType = OutputType.TEXT,
    output_mode: OutputMode = OutputMode.PASS_THROUGH,
    input_bindings: dict[str, object] | None = None,
) -> StepSpec:
    return StepSpec(
        plan_step_ref=ref,
        name=name,
        assistant_spec=AssistantSpec(instructions=instructions or f"Run {name}."),
        input_source=input_source,
        input_type=input_type,
        output_mode=output_mode,
        output_type=output_type,
        input_bindings=input_bindings,
    )


def _draft(
    *,
    name: str,
    input_source: InputSource,
    input_type: InputType = InputType.TEXT,
    output_type: OutputType = OutputType.TEXT,
    instructions: str | None = None,
) -> NewStepDraft:
    return NewStepDraft(
        name=name,
        instructions=instructions or f"Run {name}.",
        input_source=input_source,
        input_type=input_type,
        output_type=output_type,
    )


def _report_spec(*, final_question: str | None = None) -> FlowDraftSpecCore:
    final_bindings = (
        {"question": final_question} if final_question is not None else None
    )
    return FlowDraftSpecCore(
        flow_name="Customer meeting report",
        steps=[
            _step(
                ref="step_a",
                name="Transcribe source",
                instructions="Transcribe the uploaded customer meeting.",
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.AUDIO,
                output_type=OutputType.TEXT,
                output_mode=OutputMode.TRANSCRIBE_ONLY,
            ),
            _step(
                ref="step_b",
                name="Extract decisions",
                instructions="Extract decisions from the source material.",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_type=OutputType.JSON,
            ),
            _step(
                ref="step_c",
                name="Write report",
                instructions="Write the final report from analysis and source.",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.JSON,
                output_type=OutputType.TEXT,
                input_bindings=final_bindings,
            ),
        ],
    )


def _only_boundary(spec: FlowDraftSpecCore):
    boundaries = tuple(iter_compiled_source_material_boundaries(spec))
    assert len(boundaries) == 1
    return boundaries[0]


def test_source_material_status_needs_completion_without_question_binding() -> None:
    boundary = _only_boundary(_report_spec())

    assert (
        source_material_binding_status(boundary)
        is SourceMaterialBindingStatus.NEEDS_COMPLETION
    )


def test_source_material_status_needs_completion_for_structured_only_binding() -> None:
    boundary = _only_boundary(
        _report_spec(final_question="{{ step_b.output.structured.decisions }}")
    )

    assert (
        source_material_binding_status(boundary)
        is SourceMaterialBindingStatus.NEEDS_COMPLETION
    )


def test_source_material_status_is_complete_for_structured_and_source_binding() -> None:
    boundary = _only_boundary(
        _report_spec(
            final_question=(
                "{{ step_b.output.structured }}\n\n"
                "Source material: {{ step_a.output.text }}"
            )
        )
    )

    assert (
        source_material_binding_status(boundary) is SourceMaterialBindingStatus.COMPLETE
    )


def test_source_material_status_keeps_source_only_binding_intentional_partial() -> None:
    boundary = _only_boundary(
        _report_spec(final_question="Source material: {{ step_a.output.text }}")
    )

    assert (
        source_material_binding_status(boundary)
        is SourceMaterialBindingStatus.INTENTIONAL_PARTIAL
    )


def test_source_material_question_completion_preserves_prompt_and_appends_source() -> (
    None
):
    boundary = _only_boundary(
        _report_spec(final_question="Audience: {{ flow_input.audience }}")
    )

    assert source_material_question_for_boundary(
        boundary,
        existing_question="Audience: {{ flow_input.audience }}",
    ) == (
        "Audience: {{ flow_input.audience }}\n\n"
        "{{ step_b.output.structured }}\n\n"
        "Source material: {{ step_a.output.text }}"
    )


def test_source_material_label_uses_swedish_when_context_is_swedish() -> None:
    assert source_material_label_for_text("Skapa mötesprotokoll från ljud") == (
        "Källmaterial"
    )
    assert source_material_label_for_text("Create a customer meeting report") == (
        "Source material"
    )


def test_create_steps_return_material_report_for_text_or_document_outputs() -> None:
    assert not create_steps_return_material_report([])
    assert create_steps_return_material_report(
        [
            _draft(name="Extract facts", input_source=InputSource.FLOW_INPUT),
            _draft(
                name="Write report",
                input_source=InputSource.PREVIOUS_STEP,
                output_type=OutputType.TEXT,
            ),
        ]
    )
    assert create_steps_return_material_report(
        [
            _draft(name="Extract facts", input_source=InputSource.FLOW_INPUT),
            _draft(
                name="Create PDF",
                input_source=InputSource.PREVIOUS_STEP,
                output_type=OutputType.PDF,
            ),
        ]
    )
    assert not create_steps_return_material_report(
        [
            _draft(
                name="Extract facts",
                input_source=InputSource.FLOW_INPUT,
                output_type=OutputType.JSON,
            )
        ]
    )


def test_primary_source_material_ref_for_steps_targets_primary_material_upload() -> (
    None
):
    source_ref = primary_source_material_ref_for_steps(
        steps=[
            _draft(
                name="Read notes",
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.TEXT,
                output_type=OutputType.TEXT,
            ),
            _draft(
                name="Transcribe audio",
                instructions="Transcribe the uploaded audio.",
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.AUDIO,
                output_type=OutputType.TEXT,
            ),
            _draft(
                name="Extract actions",
                input_source=InputSource.PREVIOUS_STEP,
                output_type=OutputType.JSON,
            ),
        ],
        flow_name="Skapa mötesprotokoll från ljud",
        flow_description=None,
    )

    assert source_ref is not None
    assert source_ref.from_step == 2
    assert source_ref.label == "Källmaterial"


def test_primary_source_material_ref_for_steps_ignores_plain_text_flow_input() -> None:
    assert (
        primary_source_material_ref_for_steps(
            steps=[
                _draft(
                    name="Read notes",
                    input_source=InputSource.FLOW_INPUT,
                    input_type=InputType.TEXT,
                    output_type=OutputType.TEXT,
                )
            ],
            flow_name="Text summary",
            flow_description=None,
        )
        is None
    )
