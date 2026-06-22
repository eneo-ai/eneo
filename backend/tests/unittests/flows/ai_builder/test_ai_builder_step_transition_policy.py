from __future__ import annotations

from intric.flows.ai_builder.ai_builder_step_transition_policy import (
    normalize_ai_builder_spec,
)
from intric.flows.ai_builder.ai_builder_underlag_policy import is_source_surfacing_text
from intric.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    FormFieldSpec,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
    StepSpec,
)
from intric.flows.input_binding_contract_rules import question_binding
from intric.flows.template_reference_analyzer import (
    TemplateReferenceKind,
    analyze_template,
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
    input_contract: dict[str, object] | None = None,
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
        input_contract=input_contract,
        output_config=output_config,
    )


def _text_report_source_material_spec(
    *,
    final_input_bindings: dict[str, object] | None = None,
    source_input_type: InputType = InputType.AUDIO,
    source_output_mode: OutputMode = OutputMode.TRANSCRIBE_ONLY,
) -> FlowDraftSpecCore:
    return FlowDraftSpecCore(
        flow_name="Customer meeting report",
        steps=[
            _step(
                ref="step_a",
                name="Transcribe source",
                instructions="Transcribe the uploaded customer meeting.",
                input_source=InputSource.FLOW_INPUT,
                input_type=source_input_type,
                output_type=OutputType.TEXT,
                output_mode=source_output_mode,
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
                name="Extract actions",
                instructions="Extract action items from the source material.",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.JSON,
                output_type=OutputType.JSON,
            ),
            _step(
                ref="step_d",
                name="Write final report",
                instructions="Write the final report from the analysis and source.",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.JSON,
                output_type=OutputType.TEXT,
                input_bindings=final_input_bindings,
            ),
        ],
    )


def _question_metrics(
    question: str,
    *,
    spec: FlowDraftSpecCore,
) -> dict[str, int]:
    step_refs = {
        step.plan_step_ref: step_order
        for step_order, step in enumerate(spec.steps, start=1)
    }
    references = analyze_template(
        question,
        step_refs=step_refs,
        form_field_names=set(),
    )
    step_references = [
        reference
        for reference in references
        if reference.kind is TemplateReferenceKind.STEP
        and reference.path_error_code is None
    ]
    source_step_refs = {
        step.plan_step_ref
        for step in spec.steps
        if is_source_surfacing_text(
            input_source=step.input_source,
            input_type=step.input_type,
            output_type=step.output_type,
        )
    }
    question_step = next(
        step for step in spec.steps if question_binding(step.input_bindings) == question
    )
    return {
        "binding_byte_size": len(question.encode("utf-8")),
        "fan_in_width": len(
            {reference.step_ref or reference.head for reference in step_references}
        ),
        "structured_field_count": sum(
            1
            for reference in step_references
            if reference.tail.startswith("output.structured.")
        ),
        "whole_output_reference_count": sum(
            1
            for reference in step_references
            if reference.tail in {"output.text", "output.structured"}
        ),
        "source_duplication_count": sum(
            1
            for reference in step_references
            if (reference.step_ref or reference.head) in source_step_refs
            and reference.tail == "output.text"
        ),
        "all_previous_steps_count": (
            1 if question_step.input_source is InputSource.ALL_PREVIOUS_STEPS else 0
        ),
    }


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


def test_normalize_ai_builder_spec_clears_all_previous_input_contract() -> None:
    spec = FlowDraftSpecCore(
        flow_name="Final structured synthesis",
        steps=[
            _step(ref="step_a", name="Extract", input_source=InputSource.FLOW_INPUT),
            _step(
                ref="step_b",
                name="Synthesize",
                input_source=InputSource.ALL_PREVIOUS_STEPS,
                input_type=InputType.TEXT,
                output_type=OutputType.JSON,
                input_contract={
                    "type": "object",
                    "properties": {"summary": {"type": "string"}},
                },
            ),
        ],
    )

    normalized, changes = normalize_ai_builder_spec(spec)

    assert normalized.steps[1].input_source == InputSource.ALL_PREVIOUS_STEPS
    assert normalized.steps[1].input_contract is None
    assert any(
        change.code == "all_previous_input_contract_cleared"
        for _step_spec, change in changes
    )


def test_normalize_ai_builder_spec_clears_explicit_question_input_contract() -> None:
    spec = FlowDraftSpecCore(
        flow_name="Explicit underlag",
        steps=[
            _step(ref="step_a", name="Extract", input_source=InputSource.FLOW_INPUT),
            _step(
                ref="step_b",
                name="Write",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                input_bindings={"question": "{{ step_a.output.structured.title }}"},
                input_contract={
                    "type": "object",
                    "properties": {"title": {"type": "string"}},
                },
            ),
        ],
    )

    normalized, changes = normalize_ai_builder_spec(spec)

    assert normalized.steps[1].input_contract is None
    assert any(
        change.code == "explicit_question_input_contract_cleared"
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


def test_normalize_ai_builder_spec_promotes_terminal_text_to_requested_docx() -> None:
    spec = FlowDraftSpecCore(
        flow_name="Transkribering till DOCX",
        steps=[
            _step(
                ref="step_a",
                name="Transkribera ljud",
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.AUDIO,
                output_type=OutputType.TEXT,
            ),
            _step(
                ref="step_b",
                name="Skriv slutrapport",
                instructions="Skriv en tydlig slutrapport med rubriker och punktlistor.",
                input_source=InputSource.PREVIOUS_STEP,
                output_type=OutputType.TEXT,
            ),
        ],
    )

    normalized, changes = normalize_ai_builder_spec(
        spec,
        terminal_output_type=OutputType.DOCX,
    )

    assert [step.plan_step_ref for step in normalized.steps] == ["step_a", "step_b"]
    terminal = normalized.steps[-1]
    assert terminal.output_type == OutputType.DOCX
    assert terminal.output_mode == OutputMode.PASS_THROUGH
    assert terminal.output_contract is None
    assert terminal.output_config is None
    assert "Create the final DOCX file" in terminal.assistant_spec.instructions
    assert [
        change.code
        for _step_spec, change in changes
        if change.code == "terminal_artifact_contract_promoted"
    ] == ["terminal_artifact_contract_promoted"]


def test_normalize_ai_builder_spec_does_not_promote_unfoldable_artifact_helper_tail() -> (
    None
):
    spec = FlowDraftSpecCore(
        flow_name="Ambiguous PDF tail",
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
    assert normalized.steps[-1].output_type == OutputType.TEXT
    assert not any(
        change.code == "terminal_artifact_contract_promoted"
        for _step_spec, change in changes
    )


def test_normalize_ai_builder_spec_disambiguates_duplicate_step_names() -> None:
    spec = FlowDraftSpecCore(
        flow_name="Duplicate names",
        steps=[
            _step(
                ref="step_a",
                name="Förbered DOCX-innehåll",
                input_source=InputSource.FLOW_INPUT,
            ),
            _step(
                ref="step_b",
                name="förbered docx-innehåll",
                input_source=InputSource.PREVIOUS_STEP,
            ),
            _step(
                ref="step_c",
                name="Förbered DOCX-innehåll (2)",
                input_source=InputSource.PREVIOUS_STEP,
            ),
            _step(
                ref="step_d",
                name="Förbered DOCX-innehåll",
                input_source=InputSource.PREVIOUS_STEP,
            ),
        ],
    )

    normalized, changes = normalize_ai_builder_spec(
        spec,
        disambiguate_duplicate_step_names=True,
    )

    assert [step.name for step in normalized.steps] == [
        "Förbered DOCX-innehåll",
        "förbered docx-innehåll (2)",
        "Förbered DOCX-innehåll (2) (2)",
        "Förbered DOCX-innehåll (3)",
    ]
    assert [
        change.code
        for _step_spec, change in changes
        if change.code == "duplicate_step_name_disambiguated"
    ] == [
        "duplicate_step_name_disambiguated",
        "duplicate_step_name_disambiguated",
        "duplicate_step_name_disambiguated",
    ]


def test_normalize_ai_builder_spec_promotes_trailing_text_after_requested_json() -> (
    None
):
    spec = FlowDraftSpecCore(
        flow_name="Structured comparison",
        form_fields=[
            FormFieldSpec(
                name="audience",
                type="text",
                label="Audience",
            )
        ],
        steps=[
            _step(
                ref="step_a",
                name="Extract source facts",
                input_source=InputSource.FLOW_INPUT,
                output_type=OutputType.JSON,
            ),
            _step(
                ref="step_b",
                name="Prepare JSON result",
                instructions="Create the final structured JSON object.",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.JSON,
                output_type=OutputType.JSON,
                input_bindings={
                    "question": "{{ step_a.output.structured }}",
                },
            ),
            _step(
                ref="step_c",
                name="Create final result",
                instructions="Include the audience metadata in the final result.",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_type=OutputType.TEXT,
                input_bindings={
                    "question": (
                        "{{ step_b.output.structured }}\n\naudience: {{ audience }}"
                    )
                },
            ),
        ],
    )

    normalized, changes = normalize_ai_builder_spec(
        spec,
        terminal_output_type=OutputType.JSON,
    )

    assert [step.plan_step_ref for step in normalized.steps] == ["step_a", "step_c"]
    terminal = normalized.steps[-1]
    assert terminal.input_source == InputSource.PREVIOUS_STEP
    assert terminal.input_type == InputType.JSON
    assert terminal.output_type == OutputType.JSON
    assert terminal.input_bindings == {
        "question": "{{ step_a.output.structured }}\n\naudience: {{ audience }}"
    }
    assert "Include the audience metadata" in terminal.assistant_spec.instructions
    assert "Create the final structured JSON object" in (
        terminal.assistant_spec.instructions
    )
    assert [
        change.code
        for _step_spec, change in changes
        if change.code == "terminal_artifact_helper_folded"
    ] == ["terminal_artifact_helper_folded"]
    assert len(normalized.steps) == len(spec.steps) - 1


def test_normalize_ai_builder_spec_promotes_json_tail_without_terminal_bindings() -> (
    None
):
    spec = FlowDraftSpecCore(
        flow_name="Structured summary",
        steps=[
            _step(
                ref="step_a",
                name="Extract source facts",
                input_source=InputSource.FLOW_INPUT,
                output_type=OutputType.JSON,
            ),
            _step(
                ref="step_b",
                name="Prepare JSON result",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.JSON,
                output_type=OutputType.JSON,
                input_bindings={"question": "{{ step_a.output.structured }}"},
            ),
            _step(
                ref="step_c",
                name="Create final result",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.JSON,
                output_type=OutputType.TEXT,
            ),
        ],
    )

    normalized, changes = normalize_ai_builder_spec(
        spec,
        terminal_output_type=OutputType.JSON,
    )

    assert [step.plan_step_ref for step in normalized.steps] == ["step_a", "step_c"]
    assert normalized.steps[-1].output_type == OutputType.JSON
    assert normalized.steps[-1].input_bindings == {
        "question": "{{ step_a.output.structured }}"
    }
    assert [
        change.code
        for _step_spec, change in changes
        if change.code == "terminal_artifact_helper_folded"
    ] == ["terminal_artifact_helper_folded"]


def test_normalize_ai_builder_spec_preserves_json_all_previous_tail() -> None:
    spec = FlowDraftSpecCore(
        flow_name="Structured comparison",
        steps=[
            _step(
                ref="step_a",
                name="Extract source facts",
                input_source=InputSource.FLOW_INPUT,
                output_type=OutputType.JSON,
            ),
            _step(
                ref="step_b",
                name="Prepare JSON result",
                input_source=InputSource.ALL_PREVIOUS_STEPS,
                input_type=InputType.JSON,
                output_type=OutputType.JSON,
            ),
            _step(
                ref="step_c",
                name="Create final result",
                input_source=InputSource.ALL_PREVIOUS_STEPS,
                input_type=InputType.JSON,
                output_type=OutputType.TEXT,
            ),
        ],
    )

    normalized, changes = normalize_ai_builder_spec(
        spec,
        terminal_output_type=OutputType.JSON,
    )

    assert [step.plan_step_ref for step in normalized.steps] == [
        "step_a",
        "step_b",
        "step_c",
    ]
    assert normalized.steps[-1].input_source == InputSource.ALL_PREVIOUS_STEPS
    assert normalized.steps[-1].output_type == OutputType.TEXT
    assert not any(
        change.code == "terminal_artifact_helper_folded"
        for _step_spec, change in changes
    )


def test_normalize_ai_builder_spec_preserves_unfoldable_json_all_previous_tail() -> (
    None
):
    spec = FlowDraftSpecCore(
        flow_name="Ambiguous structured comparison",
        steps=[
            _step(
                ref="step_a",
                name="Extract source facts",
                input_source=InputSource.FLOW_INPUT,
                output_type=OutputType.JSON,
            ),
            _step(
                ref="step_b",
                name="Prepare JSON result",
                input_source=InputSource.ALL_PREVIOUS_STEPS,
                input_type=InputType.JSON,
                output_type=OutputType.JSON,
            ),
            _step(
                ref="step_c",
                name="Create final result",
                input_source=InputSource.ALL_PREVIOUS_STEPS,
                input_type=InputType.JSON,
                output_type=OutputType.TEXT,
                input_bindings={"question": "{{ step_b.output.structured }}"},
            ),
        ],
    )

    normalized, changes = normalize_ai_builder_spec(
        spec,
        terminal_output_type=OutputType.JSON,
    )

    assert [step.plan_step_ref for step in normalized.steps] == [
        "step_a",
        "step_b",
        "step_c",
    ]
    assert normalized.steps[-1].output_type == OutputType.TEXT
    assert not any(
        change.code == "terminal_artifact_helper_folded"
        for _step_spec, change in changes
    )


def test_normalize_ai_builder_spec_preserves_json_tail_with_non_pass_through_terminal() -> (
    None
):
    spec = FlowDraftSpecCore(
        flow_name="Structured comparison",
        steps=[
            _step(
                ref="step_a",
                name="Extract source facts",
                input_source=InputSource.FLOW_INPUT,
                output_type=OutputType.JSON,
            ),
            _step(
                ref="step_b",
                name="Prepare JSON result",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.JSON,
                output_type=OutputType.JSON,
            ),
            _step(
                ref="step_c",
                name="Create final result",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.JSON,
                output_type=OutputType.TEXT,
                output_mode=OutputMode.TEMPLATE_FILL,
            ),
        ],
    )

    normalized, changes = normalize_ai_builder_spec(
        spec,
        terminal_output_type=OutputType.JSON,
    )

    assert [step.plan_step_ref for step in normalized.steps] == [
        "step_a",
        "step_b",
        "step_c",
    ]
    assert normalized.steps[-1].output_type == OutputType.TEXT
    assert not any(
        change.code == "terminal_artifact_helper_folded"
        for _step_spec, change in changes
    )


def test_normalize_ai_builder_spec_preserves_existing_json_terminal() -> None:
    spec = FlowDraftSpecCore(
        flow_name="Structured comparison",
        steps=[
            _step(
                ref="step_a",
                name="Extract source facts",
                input_source=InputSource.FLOW_INPUT,
                output_type=OutputType.JSON,
            ),
            _step(
                ref="step_b",
                name="Create JSON result",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.JSON,
                output_type=OutputType.JSON,
            ),
        ],
    )

    normalized, changes = normalize_ai_builder_spec(
        spec,
        terminal_output_type=OutputType.JSON,
    )

    assert [step.plan_step_ref for step in normalized.steps] == ["step_a", "step_b"]
    assert normalized.steps[-1].output_type == OutputType.JSON
    assert not any(
        change.code == "terminal_artifact_helper_folded"
        for _step_spec, change in changes
    )


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


def test_normalize_ai_builder_spec_keeps_distinct_names_for_multiple_artifact_body_steps() -> (
    None
):
    # When several pre-terminal steps look like artifact-body work, flattening
    # them all to the single canonical name only manufactures confusing "(2)"
    # collisions. Keep the planner's distinct names; the terminal step still owns
    # file creation.
    spec = FlowDraftSpecCore(
        flow_name="Audio DOCX",
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
                name="Skapa rapportutkast",
                instructions="Generera DOCX-innehåll med rubriker från transkriptionen.",
                input_source=InputSource.PREVIOUS_STEP,
                output_type=OutputType.TEXT,
            ),
            _step(
                ref="step_c",
                name="Skapa DOCX-rapport",
                instructions="Skapa DOCX-dokumentets slutliga textinnehåll.",
                input_source=InputSource.PREVIOUS_STEP,
                output_type=OutputType.TEXT,
            ),
            _step(
                ref="step_d",
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

    assert [step.name for step in normalized.steps] == [
        "Transkribera ljud",
        "Skapa rapportutkast",
        "Skapa DOCX-rapport",
        "Skapa DOCX",
    ]
    assert [
        change.code
        for _step_spec, change in changes
        if change.code == "pre_terminal_artifact_body_step_renamed"
    ] == []


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
                input_contract={
                    "type": "object",
                    "properties": {"agenda": {"type": "array"}},
                },
            ),
            _step(
                ref="step_d",
                name="Skapa DOCX",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.JSON,
                output_type=OutputType.DOCX,
                input_contract={
                    "type": "object",
                    "properties": {"metadata": {"type": "object"}},
                },
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
            "{{ step_b.output.structured }}\n\nKällmaterial: {{ step_a.output.text }}"
        )
    }
    assert normalized.steps[2].input_contract is None
    assert normalized.steps[3].input_type == InputType.TEXT
    assert normalized.steps[3].input_bindings == {
        "question": (
            "{{ step_c.output.structured }}\n\nKällmaterial: {{ step_a.output.text }}"
        )
    }
    assert normalized.steps[3].input_contract is None
    assert [
        change.code
        for _step_spec, change in changes
        if change.code == "source_material_underlag_completed"
    ] == ["source_material_underlag_completed", "source_material_underlag_completed"]
    assert all(
        step.input_contract is None
        for step in normalized.steps
        if question_binding(step.input_bindings) is not None
    )


def test_normalize_ai_builder_spec_completes_source_material_for_text_report() -> None:
    spec = _text_report_source_material_spec()

    normalized, changes = normalize_ai_builder_spec(spec)

    final_step = normalized.steps[3]
    assert final_step.input_source == InputSource.PREVIOUS_STEP
    assert final_step.input_type == InputType.TEXT
    assert final_step.input_bindings == {
        "question": (
            "{{ step_c.output.structured }}\n\n"
            "Source material: {{ step_a.output.text }}"
        )
    }
    assert [
        change.code
        for _step_spec, change in changes
        if change.code == "source_material_underlag_completed"
    ] == [
        "source_material_underlag_completed",
        "source_material_underlag_completed",
    ]

    metrics = _question_metrics(
        question=question_binding(final_step.input_bindings) or "",
        spec=normalized,
    )
    assert metrics["fan_in_width"] == 2
    assert metrics["whole_output_reference_count"] == 2
    assert metrics["source_duplication_count"] == 1
    assert metrics["all_previous_steps_count"] == 0


def test_normalize_ai_builder_spec_bounds_material_metrics_for_section_chain() -> None:
    spec = FlowDraftSpecCore(
        flow_name="Section report",
        steps=[
            _step(
                ref="step_a",
                name="Transcribe meeting",
                instructions="Transcribe the uploaded meeting.",
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.AUDIO,
                output_type=OutputType.TEXT,
                output_mode=OutputMode.TRANSCRIBE_ONLY,
            ),
            _step(
                ref="step_b",
                name="Extract summary",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_type=OutputType.JSON,
            ),
            _step(
                ref="step_c",
                name="Extract decisions",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.JSON,
                output_type=OutputType.JSON,
            ),
            _step(
                ref="step_d",
                name="Extract risks",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.JSON,
                output_type=OutputType.JSON,
            ),
            _step(
                ref="step_e",
                name="Write report",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.JSON,
                output_type=OutputType.TEXT,
            ),
        ],
    )

    normalized, _changes = normalize_ai_builder_spec(spec)

    for step in normalized.steps[2:]:
        question = question_binding(step.input_bindings) or ""
        metrics = _question_metrics(question=question, spec=normalized)
        assert metrics["binding_byte_size"] <= 96
        assert metrics["fan_in_width"] == 2
        assert metrics["structured_field_count"] == 0
        assert metrics["whole_output_reference_count"] == 2
        assert metrics["source_duplication_count"] == 1
        assert metrics["all_previous_steps_count"] == 0


def test_normalize_ai_builder_spec_treats_immediate_structured_only_as_incomplete() -> (
    None
):
    spec = _text_report_source_material_spec(
        final_input_bindings={"question": "{{ step_c.output.structured }}"}
    )

    normalized, _changes = normalize_ai_builder_spec(spec)

    assert normalized.steps[3].input_type == InputType.TEXT
    assert normalized.steps[3].input_bindings == {
        "question": (
            "{{ step_c.output.structured }}\n\n"
            "Source material: {{ step_a.output.text }}"
        )
    }


def test_normalize_ai_builder_spec_preserves_text_report_complete_underlag() -> None:
    complete_question = (
        "{{ step_c.output.structured }}\n\nSource material: {{ step_a.output.text }}"
    )
    spec = _text_report_source_material_spec(
        final_input_bindings={"question": complete_question}
    )

    normalized, changes = normalize_ai_builder_spec(spec)

    assert normalized.steps[3].input_bindings == {"question": complete_question}
    assert not any(
        step.plan_step_ref == "step_d"
        and change.code == "source_material_underlag_completed"
        for step, change in changes
    )


def test_normalize_ai_builder_spec_treats_source_only_underlag_as_intentional_partial() -> (
    None
):
    spec = _text_report_source_material_spec(
        final_input_bindings={"question": "Source material: {{ step_a.output.text }}"}
    )

    normalized, changes = normalize_ai_builder_spec(spec)

    assert normalized.steps[3].input_bindings == {
        "question": "Source material: {{ step_a.output.text }}"
    }
    assert not any(
        step.plan_step_ref == "step_d"
        and change.code == "source_material_underlag_completed"
        for step, change in changes
    )


def test_normalize_ai_builder_spec_completes_empty_source_material_question() -> None:
    spec = _text_report_source_material_spec(final_input_bindings={"question": ""})

    normalized, _changes = normalize_ai_builder_spec(spec)

    assert normalized.steps[3].input_bindings == {
        "question": (
            "{{ step_c.output.structured }}\n\n"
            "Source material: {{ step_a.output.text }}"
        )
    }


def test_normalize_ai_builder_spec_does_not_add_source_material_without_json_predecessor() -> (
    None
):
    spec = FlowDraftSpecCore(
        flow_name="Linear text flow",
        steps=[
            _step(
                ref="step_a",
                name="Read source",
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.TEXT,
                output_type=OutputType.TEXT,
            ),
            _step(
                ref="step_b",
                name="Draft response",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_type=OutputType.TEXT,
            ),
            _step(
                ref="step_c",
                name="Finalize response",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_type=OutputType.TEXT,
            ),
        ],
    )

    normalized, changes = normalize_ai_builder_spec(spec)

    assert normalized == spec
    assert not any(
        change.code == "source_material_underlag_completed"
        for _step_spec, change in changes
    )


def test_normalize_ai_builder_spec_does_not_add_source_material_to_pure_json_chain() -> (
    None
):
    spec = FlowDraftSpecCore(
        flow_name="Structured only",
        steps=[
            _step(
                ref="step_a",
                name="Read source",
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.AUDIO,
                output_type=OutputType.TEXT,
                output_mode=OutputMode.TRANSCRIBE_ONLY,
            ),
            _step(
                ref="step_b",
                name="Extract facts",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_type=OutputType.JSON,
            ),
            _step(
                ref="step_c",
                name="Extract decisions",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.JSON,
                output_type=OutputType.JSON,
            ),
        ],
    )

    normalized, changes = normalize_ai_builder_spec(spec)

    assert normalized == spec
    assert not any(
        change.code == "source_material_underlag_completed"
        for _step_spec, change in changes
    )


def test_normalize_ai_builder_spec_uses_text_flow_input_as_primary_source() -> None:
    spec = _text_report_source_material_spec(
        source_input_type=InputType.TEXT,
        source_output_mode=OutputMode.PASS_THROUGH,
    )

    normalized, _changes = normalize_ai_builder_spec(spec)

    assert normalized.steps[3].input_bindings == {
        "question": (
            "{{ step_c.output.structured }}\n\n"
            "Source material: {{ step_a.output.text }}"
        )
    }


def test_source_material_question_for_boundary_is_idempotent() -> None:
    spec = _text_report_source_material_spec()
    normalized, _changes = normalize_ai_builder_spec(spec)
    normalized_again, second_changes = normalize_ai_builder_spec(normalized)

    assert normalized_again == normalized
    assert not any(
        change.code == "source_material_underlag_completed"
        for _step_spec, change in second_changes
    )


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
            "audience: {{ audience }}\n\n"
            "{{ step_b.output.structured }}\n\n"
            "Källmaterial: {{ step_a.output.text }}"
        )
    }


def test_normalize_ai_builder_spec_preserves_intentional_structured_field_underlag() -> (
    None
):
    spec = FlowDraftSpecCore(
        flow_name="IBIC till DOCX",
        form_fields=[
            FormFieldSpec(
                name="Brukarens namn",
                type="text",
                label="Brukarens namn",
            )
        ],
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
                name="Extrahera IBIC",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_type=OutputType.JSON,
            ),
            _step(
                ref="step_c",
                name="Skapa genomförandeplan",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.JSON,
                output_type=OutputType.DOCX,
                input_bindings={
                    "question": (
                        "Brukare: {{ Brukarens namn }}\n"
                        "Behov: {{ step_b.output.structured.brukare.kan_uttrycka_behov_sjalv }}"
                    )
                },
            ),
        ],
    )

    normalized, changes = normalize_ai_builder_spec(
        spec,
        terminal_output_type=OutputType.DOCX,
    )

    assert normalized.steps[2].input_bindings == spec.steps[2].input_bindings
    assert not any(
        change.code == "source_material_underlag_completed"
        for _step_spec, change in changes
    )


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
