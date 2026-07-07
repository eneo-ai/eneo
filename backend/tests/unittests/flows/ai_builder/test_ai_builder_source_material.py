from __future__ import annotations

from eneo.flows.ai_builder.ai_builder_new_step_models import NewStepDraft
from eneo.flows.ai_builder.ai_builder_source_material import (
    SourceMaterialBindingStatus,
    create_steps_return_material_report,
    iter_compiled_source_material_boundaries,
    source_material_binding_status,
    source_material_bindings_for_boundary,
    source_material_label_for_language,
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


def _report_spec(
    *,
    final_question: str | None = None,
    final_bindings: dict[str, object] | None = None,
) -> FlowDraftSpecCore:
    if final_bindings is None and final_question is not None:
        final_bindings = {"question": final_question}
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


def test_source_material_status_reads_authoring_source_refs() -> None:
    boundary = _only_boundary(
        _report_spec(
            final_bindings={
                "source_refs": [
                    {"step_ref": "step_b", "output": "structured"},
                    {
                        "step_ref": "step_a",
                        "output": "text",
                        "label": "Source material",
                    },
                ]
            },
        )
    )

    assert (
        source_material_binding_status(boundary) is SourceMaterialBindingStatus.COMPLETE
    )


def test_source_material_status_treats_typed_structured_fields_as_structured() -> None:
    boundary = _only_boundary(
        _report_spec(
            final_bindings={
                "source_refs": [
                    {
                        "step_ref": "step_b",
                        "output": "structured",
                        "field_path": "decisions",
                        "label": "Decisions",
                    },
                    {
                        "step_ref": "step_a",
                        "output": "text",
                        "label": "Source material",
                    },
                ]
            },
        )
    )

    assert (
        source_material_binding_status(boundary) is SourceMaterialBindingStatus.COMPLETE
    )


def test_source_material_status_reads_source_only_source_refs_as_partial() -> None:
    boundary = _only_boundary(
        _report_spec(
            final_bindings={
                "source_refs": [
                    {
                        "step_ref": "step_a",
                        "output": "text",
                        "label": "Source material",
                    }
                ]
            },
        )
    )

    assert (
        source_material_binding_status(boundary)
        is SourceMaterialBindingStatus.INTENTIONAL_PARTIAL
    )


def test_source_material_status_combines_question_and_source_refs() -> None:
    boundary = _only_boundary(
        _report_spec(
            final_bindings={
                "question": "{{ step_b.output.structured }}",
                "source_refs": [
                    {
                        "step_ref": "step_a",
                        "output": "text",
                        "label": "Source material",
                    }
                ],
            },
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


def test_source_material_bindings_for_boundary_completes_typed_refs() -> None:
    boundary = _only_boundary(_report_spec())

    assert source_material_bindings_for_boundary(boundary, ui_language="en") == {
        "source_refs": [
            {"step_ref": "step_b", "output": "structured"},
            {"step_ref": "step_a", "output": "text", "label": "Source material"},
        ]
    }


def test_source_material_bindings_for_boundary_preserves_prompt_copy() -> None:
    boundary = _only_boundary(
        _report_spec(final_question="Audience: {{ flow_input.audience }}")
    )

    assert source_material_bindings_for_boundary(boundary, ui_language="en") == {
        "question": "Audience: {{ flow_input.audience }}",
        "source_refs": [
            {"step_ref": "step_b", "output": "structured"},
            {"step_ref": "step_a", "output": "text", "label": "Source material"},
        ],
    }


def test_source_material_label_uses_ui_language_not_text_content() -> None:
    assert source_material_label_for_language("sv") == "Källmaterial"
    assert source_material_label_for_language("en") == "Source material"
    assert source_material_label_for_language(None) == "Källmaterial"


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
