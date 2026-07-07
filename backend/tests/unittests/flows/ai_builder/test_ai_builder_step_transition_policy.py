from __future__ import annotations

from eneo.flows.ai_builder.ai_builder_step_transition_policy import (
    normalize_ai_builder_spec,
    supports_inline_inref_citation,
)
from eneo.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    FormFieldSpec,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
    StepSpec,
)
from eneo.flows.input_binding_contract_rules import (
    effective_question_binding,
)
from eneo.flows.template_reference_analyzer import (
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


def _completed_source_refs(
    *,
    structured_step_ref: str,
    source_step_ref: str,
    label: str = "Source material",
) -> dict[str, object]:
    return {
        "source_refs": [
            {"step_ref": structured_step_ref, "output": "structured"},
            {"step_ref": source_step_ref, "output": "text", "label": label},
        ]
    }


def _effective_question(input_bindings: dict[str, object] | None) -> str:
    question = effective_question_binding(input_bindings)
    assert question is not None
    return question


def _is_source_surfacing_text(
    *,
    input_source: InputSource,
    input_type: InputType,
    output_type: OutputType,
) -> bool:
    return (
        input_source == InputSource.FLOW_INPUT
        and input_type in {InputType.AUDIO, InputType.DOCUMENT, InputType.FILE}
        and output_type == OutputType.TEXT
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
        if _is_source_surfacing_text(
            input_source=step.input_source,
            input_type=step.input_type,
            output_type=step.output_type,
        )
    }
    question_step = next(
        step
        for step in spec.steps
        if effective_question_binding(step.input_bindings) == question
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


def test_normalize_ai_builder_spec_clears_invalid_citation_sidecar_config() -> None:
    spec = FlowDraftSpecCore(
        flow_name="Template report",
        steps=[
            _step(
                ref="step_a",
                name="Fill template",
                input_source=InputSource.FLOW_INPUT,
                output_type=OutputType.DOCX,
                output_mode=OutputMode.TEMPLATE_FILL,
                output_config={
                    "citation_mode": "inline_inref_sidecar",
                    "template_asset_id": "template-1",
                },
            ),
        ],
    )

    normalized, changes = normalize_ai_builder_spec(spec)

    assert normalized.steps[0].output_config == {"template_asset_id": "template-1"}
    assert [
        change.code
        for _step_spec, change in changes
        if change.code == "output_config_citation_mode_cleared"
    ] == ["output_config_citation_mode_cleared"]


def test_normalize_ai_builder_spec_clears_stale_template_identity_on_mode_change() -> (
    None
):
    spec = FlowDraftSpecCore(
        flow_name="Template report",
        steps=[
            _step(
                ref="step_a",
                name="Fill template",
                input_source=InputSource.FLOW_INPUT,
                output_type=OutputType.TEXT,
                output_mode=OutputMode.TEMPLATE_FILL,
                output_config={
                    "bindings": {"body": "{{flow_input.title}}"},
                    "template_asset_id": "template-1",
                    "template_file_id": "legacy-file-1",
                    "preserve": "value",
                },
            ),
        ],
    )

    normalized, changes = normalize_ai_builder_spec(spec)

    assert normalized.steps[0].output_mode == OutputMode.PASS_THROUGH
    assert normalized.steps[0].output_config == {"preserve": "value"}
    assert [
        change.code
        for _step_spec, change in changes
        if change.code == "output_config_template_fill_keys_cleared"
    ] == ["output_config_template_fill_keys_cleared"]


def test_supports_inline_inref_citation_uses_flow_output_capability_rules() -> None:
    assert (
        supports_inline_inref_citation(
            output_type=OutputType.TEXT,
            output_mode=OutputMode.PASS_THROUGH,
        )
        is True
    )
    assert (
        supports_inline_inref_citation(
            output_type=OutputType.TEXT,
            output_mode=OutputMode.TRANSCRIBE_ONLY,
        )
        is False
    )
    assert (
        supports_inline_inref_citation(
            output_type=OutputType.DOCX,
            output_mode=OutputMode.TEMPLATE_FILL,
        )
        is False
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


def test_normalize_ai_builder_spec_preserves_requested_artifact_helper_tail() -> None:
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

    assert [step.plan_step_ref for step in normalized.steps] == [
        "step_a",
        "step_b",
        "step_c",
    ]
    assert normalized.steps[-1].output_type == OutputType.TEXT
    assert changes == []


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


def test_normalize_ai_builder_spec_uses_ui_language_for_artifact_body_copy() -> None:
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

    normalized, _changes = normalize_ai_builder_spec(
        spec,
        terminal_output_type=OutputType.DOCX,
        ui_language="en",
    )

    body_step = normalized.steps[-2]
    assert body_step.name == "Prepare DOCX content"
    assert "terminal step will render" in body_step.assistant_spec.instructions
    assert "terminalsteget" not in body_step.assistant_spec.instructions


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
    assert changes == []


def test_normalize_ai_builder_spec_preserves_text_report_complete_underlag() -> None:
    complete_question = (
        "{{ step_c.output.structured }}\n\nSource material: {{ step_a.output.text }}"
    )
    spec = _text_report_source_material_spec(
        final_input_bindings={"question": complete_question}
    )

    normalized, changes = normalize_ai_builder_spec(spec)

    assert normalized.steps[3].input_bindings == {"question": complete_question}
    assert changes == []


def test_normalize_ai_builder_spec_preserves_source_refs_complete_underlag() -> None:
    bindings = {
        "source_refs": [
            {"step_ref": "step_c", "output": "structured"},
            {
                "step_ref": "step_a",
                "output": "text",
                "label": "Source material",
            },
        ]
    }
    spec = _text_report_source_material_spec(final_input_bindings=bindings)

    normalized, changes = normalize_ai_builder_spec(spec)

    assert normalized.steps[3].input_bindings == bindings
    assert changes == []


def test_normalize_ai_builder_spec_dedupes_existing_source_refs() -> None:
    spec = _text_report_source_material_spec(
        final_input_bindings={
            "source_refs": [
                {"step_ref": "step_c", "output": "structured"},
                {"step_ref": "step_a", "output": "text"},
                {
                    "step_ref": "step_a",
                    "output": "text",
                    "label": "Source material",
                },
            ]
        }
    )

    normalized, changes = normalize_ai_builder_spec(spec)

    assert normalized.steps[3].input_bindings == _completed_source_refs(
        structured_step_ref="step_c",
        source_step_ref="step_a",
    )
    assert any(
        step.plan_step_ref == "step_d" and change.code == "source_refs_deduped"
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
    assert changes == []


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
    assert changes == []


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
    assert changes == []
