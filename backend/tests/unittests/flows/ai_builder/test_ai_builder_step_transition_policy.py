from __future__ import annotations

from intric.flows.ai_builder.ai_builder_models import (
    AssistantSpec,
    FlowDraftSpecCore,
    FormFieldSpec,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
    StepSpec,
)
from intric.flows.ai_builder.ai_builder_step_transition_policy import (
    normalize_ai_builder_spec,
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
    output_config: dict[str, object] | None = None,
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
        output_config=output_config,
    )


def test_normalize_ai_builder_spec_rewires_repeated_all_previous_steps() -> None:
    spec = FlowDraftSpecCore(
        flow_name="Linear report",
        steps=[
            _step(ref="step_a", name="Extract", input_source=InputSource.FLOW_INPUT),
            _step(
                ref="step_b",
                name="Analyze",
                input_source=InputSource.ALL_PREVIOUS_STEPS,
            ),
            _step(
                ref="step_c",
                name="Summarize",
                input_source=InputSource.ALL_PREVIOUS_STEPS,
            ),
        ],
    )

    normalized, changes = normalize_ai_builder_spec(spec)

    assert [step.input_source for step in normalized.steps] == [
        InputSource.FLOW_INPUT,
        InputSource.PREVIOUS_STEP,
        InputSource.ALL_PREVIOUS_STEPS,
    ]
    assert [
        change.code
        for _step_spec, change in changes
        if change.code == "input_source_all_previous_rewired"
    ] == ["input_source_all_previous_rewired"]


def test_normalize_ai_builder_spec_preserves_single_unbound_all_previous_step() -> None:
    spec = FlowDraftSpecCore(
        flow_name="Final synthesis",
        steps=[
            _step(ref="step_a", name="Extract", input_source=InputSource.FLOW_INPUT),
            _step(
                ref="step_b",
                name="Synthesize",
                input_source=InputSource.ALL_PREVIOUS_STEPS,
            ),
        ],
    )

    normalized, changes = normalize_ai_builder_spec(spec)

    assert normalized.steps[1].input_source == InputSource.ALL_PREVIOUS_STEPS
    assert not any(
        change.code == "input_source_all_previous_rewired"
        for _step_spec, change in changes
    )


def test_normalize_ai_builder_spec_keeps_explicit_multi_step_fan_in() -> None:
    spec = FlowDraftSpecCore(
        flow_name="Explicit synthesis",
        steps=[
            _step(ref="step_a", name="Extract A", input_source=InputSource.FLOW_INPUT),
            _step(
                ref="step_b",
                name="Extract B",
                input_source=InputSource.PREVIOUS_STEP,
            ),
            _step(
                ref="step_c",
                name="Compare",
                input_source=InputSource.ALL_PREVIOUS_STEPS,
                input_bindings={
                    "question": ("{{ step_a.output.text }}\n\n{{ step_b.output.text }}")
                },
            ),
        ],
    )

    normalized, changes = normalize_ai_builder_spec(spec)

    assert normalized.steps[2].input_source == InputSource.ALL_PREVIOUS_STEPS
    assert not any(
        change.code == "input_source_all_previous_rewired"
        for _step_spec, change in changes
    )


def test_normalize_ai_builder_spec_rewires_previous_only_binding() -> None:
    spec = FlowDraftSpecCore(
        flow_name="Previous only",
        form_fields=[
            FormFieldSpec(
                name="audience",
                type="text",
                label="Audience",
            )
        ],
        steps=[
            _step(ref="step_a", name="Extract", input_source=InputSource.FLOW_INPUT),
            _step(
                ref="step_b",
                name="Analyze",
                input_source=InputSource.PREVIOUS_STEP,
            ),
            _step(
                ref="step_c",
                name="Summarize",
                input_source=InputSource.ALL_PREVIOUS_STEPS,
                input_bindings={
                    "question": "{{ step_b.output.text }}\n\naudience: {{ audience }}"
                },
            ),
        ],
    )

    normalized, changes = normalize_ai_builder_spec(spec)

    assert normalized.steps[2].input_source == InputSource.PREVIOUS_STEP
    assert any(
        change.code == "input_source_all_previous_rewired"
        for _step_spec, change in changes
    )


def test_normalize_ai_builder_spec_promotes_trailing_text_after_requested_pdf() -> None:
    spec = FlowDraftSpecCore(
        flow_name="Employee review",
        form_fields=[
            FormFieldSpec(
                name="employee_name",
                type="text",
                label="Employee name",
            )
        ],
        steps=[
            _step(
                ref="step_a",
                name="Analyze conversation",
                input_source=InputSource.FLOW_INPUT,
                output_type=OutputType.JSON,
            ),
            _step(
                ref="step_b",
                name="Generate PDF helper",
                instructions="Render the analysis as a PDF.",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.JSON,
                output_type=OutputType.PDF,
                input_bindings={
                    "question": "{{ step_a.output.structured }}",
                },
            ),
            _step(
                ref="step_c",
                name="Create final result",
                instructions="Include the employee metadata in the final result.",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_type=OutputType.TEXT,
                input_bindings={
                    "question": (
                        "{{ step_b.output.text }}\n\nemployee_name: {{ employee_name }}"
                    )
                },
            ),
        ],
    )

    normalized, changes = normalize_ai_builder_spec(
        spec,
        terminal_output_type=OutputType.PDF,
    )

    assert [step.plan_step_ref for step in normalized.steps] == ["step_a", "step_c"]
    terminal = normalized.steps[-1]
    assert terminal.input_type == InputType.JSON
    assert terminal.output_type == OutputType.PDF
    assert terminal.input_bindings == {
        "question": "{{ step_a.output.structured }}\n\nemployee_name: {{ employee_name }}"
    }
    assert "Include the employee metadata" in terminal.assistant_spec.instructions
    assert "Render the analysis as a PDF" in terminal.assistant_spec.instructions
    assert [
        change.code
        for _step_spec, change in changes
        if change.code == "terminal_artifact_helper_folded"
    ] == ["terminal_artifact_helper_folded"]


def test_normalize_ai_builder_spec_renames_pre_terminal_docx_body_step() -> None:
    spec = FlowDraftSpecCore(
        flow_name="Audio DOCX",
        steps=[
            _step(
                ref="step_a",
                name="Identifiera struktur",
                input_source=InputSource.FLOW_INPUT,
                output_type=OutputType.JSON,
            ),
            _step(
                ref="step_b",
                name="Formatera och generera DOCX",
                instructions="Bygg ett DOCX-dokument med rubriker och brödtext.",
                input_source=InputSource.ALL_PREVIOUS_STEPS,
                input_type=InputType.TEXT,
                output_type=OutputType.TEXT,
            ),
            _step(
                ref="step_c",
                name="Skapa DOCX",
                input_source=InputSource.PREVIOUS_STEP,
                output_type=OutputType.DOCX,
            ),
        ],
    )

    normalized, changes = normalize_ai_builder_spec(
        spec,
        terminal_output_type=OutputType.DOCX,
    )

    body_step = normalized.steps[-2]
    assert body_step.name == "Förbered DOCX-innehåll"
    assert body_step.output_type == OutputType.TEXT
    assert normalized.steps[-1].name == "Skapa DOCX"
    assert normalized.steps[-1].output_type == OutputType.DOCX
    assert "terminalsteget ska rendera" in body_step.assistant_spec.instructions
    assert [
        change.code
        for _step_spec, change in changes
        if change.code == "pre_terminal_artifact_body_step_renamed"
    ] == ["pre_terminal_artifact_body_step_renamed"]


def test_normalize_ai_builder_spec_renames_non_adjacent_pdf_body_step() -> None:
    spec = FlowDraftSpecCore(
        flow_name="PDF report",
        steps=[
            _step(ref="step_a", name="Extract", input_source=InputSource.FLOW_INPUT),
            _step(
                ref="step_b",
                name="Skapa PDF-rapport",
                instructions="Skapa en PDF-rapport med slutsats och risker.",
                input_source=InputSource.PREVIOUS_STEP,
                output_type=OutputType.TEXT,
            ),
            _step(
                ref="step_c",
                name="Granska kvalitet",
                input_source=InputSource.PREVIOUS_STEP,
                output_type=OutputType.TEXT,
            ),
            _step(
                ref="step_d",
                name="Skapa PDF",
                input_source=InputSource.PREVIOUS_STEP,
                output_type=OutputType.PDF,
            ),
        ],
    )

    normalized, changes = normalize_ai_builder_spec(
        spec,
        terminal_output_type=OutputType.PDF,
    )

    assert normalized.steps[1].name == "Förbered PDF-innehåll"
    assert normalized.steps[2].name == "Granska kvalitet"
    assert normalized.steps[-1].name == "Skapa PDF"
    assert [
        change.code
        for _step_spec, change in changes
        if change.code == "pre_terminal_artifact_body_step_renamed"
    ] == ["pre_terminal_artifact_body_step_renamed"]


def test_normalize_ai_builder_spec_preserves_artifact_tail_without_output_intent() -> (
    None
):
    spec = FlowDraftSpecCore(
        flow_name="Employee review",
        steps=[
            _step(ref="step_a", name="Analyze", input_source=InputSource.FLOW_INPUT),
            _step(
                ref="step_b",
                name="Generate PDF",
                input_source=InputSource.PREVIOUS_STEP,
                output_type=OutputType.PDF,
            ),
            _step(
                ref="step_c",
                name="Create final result",
                input_source=InputSource.PREVIOUS_STEP,
                output_type=OutputType.TEXT,
            ),
        ],
    )

    normalized, changes = normalize_ai_builder_spec(spec)

    assert [step.plan_step_ref for step in normalized.steps] == [
        "step_a",
        "step_b",
        "step_c",
    ]
    assert not any(
        change.code == "terminal_artifact_helper_folded"
        for _step_spec, change in changes
    )


def test_normalize_ai_builder_spec_promotes_trailing_text_after_requested_docx_template() -> (
    None
):
    spec = FlowDraftSpecCore(
        flow_name="Template report",
        steps=[
            _step(ref="step_a", name="Analyze", input_source=InputSource.FLOW_INPUT),
            _step(
                ref="step_b",
                name="Fill DOCX template",
                input_source=InputSource.PREVIOUS_STEP,
                output_type=OutputType.DOCX,
                output_mode=OutputMode.TEMPLATE_FILL,
                output_config={"template_asset_id": "template-1"},
            ),
            _step(
                ref="step_c",
                name="Create final result",
                input_source=InputSource.PREVIOUS_STEP,
                output_type=OutputType.TEXT,
            ),
        ],
    )

    normalized, _changes = normalize_ai_builder_spec(
        spec,
        terminal_output_type=OutputType.DOCX,
    )

    terminal = normalized.steps[-1]
    assert [step.plan_step_ref for step in normalized.steps] == ["step_a", "step_c"]
    assert terminal.output_type == OutputType.DOCX
    assert terminal.output_mode == OutputMode.TEMPLATE_FILL
    assert terminal.output_config == {"template_asset_id": "template-1"}


def test_normalize_ai_builder_spec_skips_artifact_fold_when_bindings_cannot_rewire() -> (
    None
):
    spec = FlowDraftSpecCore(
        flow_name="Ambiguous artifact report",
        steps=[
            _step(ref="step_a", name="Extract", input_source=InputSource.FLOW_INPUT),
            _step(
                ref="step_b",
                name="Generate PDF",
                input_source=InputSource.ALL_PREVIOUS_STEPS,
                output_type=OutputType.PDF,
            ),
            _step(
                ref="step_c",
                name="Create final result",
                input_source=InputSource.PREVIOUS_STEP,
                output_type=OutputType.TEXT,
                input_bindings={"question": "{{ step_b.output.text }}"},
            ),
        ],
    )

    normalized, changes = normalize_ai_builder_spec(
        spec,
        terminal_output_type=OutputType.PDF,
    )

    assert [step.plan_step_ref for step in normalized.steps] == [
        "step_a",
        "step_b",
        "step_c",
    ]
    assert not any(
        change.code == "terminal_artifact_helper_folded"
        for _step_spec, change in changes
    )


def test_normalize_ai_builder_spec_completes_source_material_underlag() -> None:
    spec = FlowDraftSpecCore(
        flow_name="Mötesprotokoll från ljud",
        steps=[
            _step(
                ref="step_a",
                name="Transkribera ljud",
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.AUDIO,
                output_type=OutputType.TEXT,
                output_mode=OutputMode.TRANSCRIBE_ONLY,
            ),
            _step(
                ref="step_b",
                name="Strukturera transkription",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_type=OutputType.JSON,
            ),
            _step(
                ref="step_c",
                name="Identifiera mötesmetadata",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.JSON,
                output_type=OutputType.JSON,
            ),
            _step(
                ref="step_d",
                name="Skapa DOCX",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.JSON,
                output_type=OutputType.DOCX,
            ),
        ],
    )

    normalized, changes = normalize_ai_builder_spec(
        spec,
        terminal_output_type=OutputType.DOCX,
    )

    assert normalized.steps[2].input_type == InputType.TEXT
    assert normalized.steps[2].input_bindings == {
        "question": (
            "{{ step_b.output.structured }}\n\n"
            "Källmaterial: {{ step_a.output.text }}"
        )
    }
    assert normalized.steps[3].input_type == InputType.TEXT
    assert normalized.steps[3].input_bindings == {
        "question": (
            "{{ step_c.output.structured }}\n\n"
            "Källmaterial: {{ step_a.output.text }}"
        )
    }
    assert [
        change.code
        for _step_spec, change in changes
        if change.code == "source_material_underlag_completed"
    ] == ["source_material_underlag_completed", "source_material_underlag_completed"]


def test_normalize_ai_builder_spec_source_material_underlag_is_idempotent() -> None:
    spec = FlowDraftSpecCore(
        flow_name="Mötesprotokoll från ljud",
        steps=[
            _step(
                ref="step_a",
                name="Transkribera ljud",
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.AUDIO,
                output_type=OutputType.TEXT,
                output_mode=OutputMode.TRANSCRIBE_ONLY,
            ),
            _step(
                ref="step_b",
                name="Strukturera transkription",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_type=OutputType.JSON,
            ),
            _step(
                ref="step_c",
                name="Skapa DOCX",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.JSON,
                output_type=OutputType.DOCX,
            ),
        ],
    )

    normalized_once, first_changes = normalize_ai_builder_spec(
        spec,
        terminal_output_type=OutputType.DOCX,
    )
    normalized_twice, second_changes = normalize_ai_builder_spec(
        normalized_once,
        terminal_output_type=OutputType.DOCX,
    )

    assert normalized_twice == normalized_once
    assert [
        change.code
        for _step_spec, change in first_changes
        if change.code == "source_material_underlag_completed"
    ] == ["source_material_underlag_completed"]
    assert not any(
        change.code == "source_material_underlag_completed"
        for _step_spec, change in second_changes
    )


def test_normalize_ai_builder_spec_preserves_existing_source_material_question_tail() -> (
    None
):
    spec = FlowDraftSpecCore(
        flow_name="Mötesprotokoll från ljud",
        steps=[
            _step(
                ref="step_a",
                name="Transkribera ljud",
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.AUDIO,
                output_type=OutputType.TEXT,
                output_mode=OutputMode.TRANSCRIBE_ONLY,
            ),
            _step(
                ref="step_b",
                name="Strukturera transkription",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_type=OutputType.JSON,
            ),
            _step(
                ref="step_c",
                name="Skapa DOCX",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.JSON,
                output_type=OutputType.DOCX,
                input_bindings={"question": "audience: {{ audience }}"},
            ),
        ],
    )

    normalized, _changes = normalize_ai_builder_spec(
        spec,
        terminal_output_type=OutputType.DOCX,
    )

    assert normalized.steps[2].input_bindings == {
        "question": (
            "{{ step_b.output.structured }}\n\n"
            "Källmaterial: {{ step_a.output.text }}\n\n"
            "audience: {{ audience }}"
        )
    }


def test_normalize_ai_builder_spec_prefers_primary_audio_source_over_prior_text_step() -> (
    None
):
    spec = FlowDraftSpecCore(
        flow_name="Audio report with notes",
        steps=[
            _step(
                ref="step_a",
                name="Read user notes",
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.TEXT,
                output_type=OutputType.TEXT,
            ),
            _step(
                ref="step_b",
                name="Transcribe audio",
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.AUDIO,
                output_type=OutputType.TEXT,
                output_mode=OutputMode.TRANSCRIBE_ONLY,
            ),
            _step(
                ref="step_c",
                name="Structure transcript",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_type=OutputType.JSON,
            ),
            _step(
                ref="step_d",
                name="Create DOCX",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.JSON,
                output_type=OutputType.DOCX,
            ),
        ],
    )

    normalized, _changes = normalize_ai_builder_spec(
        spec,
        terminal_output_type=OutputType.DOCX,
    )

    assert normalized.steps[3].input_bindings == {
        "question": (
            "{{ step_c.output.structured }}\n\n"
            "Source material: {{ step_b.output.text }}"
        )
    }


def test_normalize_ai_builder_spec_uses_english_source_material_label() -> None:
    spec = FlowDraftSpecCore(
        flow_name="Audio report",
        steps=[
            _step(
                ref="step_a",
                name="Transcribe audio",
                instructions="Transcribe the uploaded audio.",
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.AUDIO,
                output_type=OutputType.TEXT,
                output_mode=OutputMode.TRANSCRIBE_ONLY,
            ),
            _step(
                ref="step_b",
                name="Extract action items",
                instructions="Extract action items from the transcript.",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_type=OutputType.JSON,
            ),
            _step(
                ref="step_c",
                name="Create DOCX",
                instructions="Create the final report.",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.JSON,
                output_type=OutputType.DOCX,
            ),
        ],
    )

    normalized, _changes = normalize_ai_builder_spec(
        spec,
        terminal_output_type=OutputType.DOCX,
    )

    assert normalized.steps[2].input_bindings == {
        "question": (
            "{{ step_b.output.structured }}\n\n"
            "Source material: {{ step_a.output.text }}"
        )
    }
