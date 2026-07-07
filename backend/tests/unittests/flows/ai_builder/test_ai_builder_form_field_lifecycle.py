from __future__ import annotations

from typing import Any
from uuid import uuid4

from eneo.flows.ai_builder.ai_builder_create_compiler import (
    CreateCompileContext,
    compile_create_intent_to_spec,
    compile_create_steps_to_spec,
)
from eneo.flows.ai_builder.ai_builder_critic_invariants import (
    CRITIC_INVARIANTS,
    CriticContext,
    evaluate_critic_invariants,
)
from eneo.flows.ai_builder.ai_builder_edit_compiler import compile_edit_proposal
from eneo.flows.ai_builder.ai_builder_form_field_usage import find_unused_form_fields
from eneo.flows.ai_builder.ai_builder_framework_policy import OutputIntentResolution
from eneo.flows.ai_builder.ai_builder_new_step_models import (
    NewStepDraft,
    StructuredFieldDraft,
)
from eneo.flows.ai_builder.ai_builder_output_sections_signals import (
    RequestedOutputSections,
)
from eneo.flows.ai_builder.ai_builder_planner_pattern_signals import (
    PlannerPatternSignals,
)
from eneo.flows.ai_builder.ai_builder_proposal_intent import (
    ModifyExistingStep,
    OrderedEditProposal,
    parse_create_flow_intent_arguments,
)
from eneo.flows.ai_builder.ai_builder_validator import validate_spec
from eneo.flows.domain.flow import FlowStep
from eneo.flows.flow_authoring_spec import (
    FlowDraftSpecCore,
    FormFieldSpec,
    InputType,
    OutputType,
)
from eneo.flows.input_binding_contract_rules import effective_question_binding


def _edit_proposal(**kwargs: Any) -> OrderedEditProposal:
    return OrderedEditProposal(plan_rationale="Update the flow.", **kwargs)


def test_declared_input_field_without_step_use_stays_unused_for_multi_step_repair() -> (
    None
):
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Priority review",
            "plan_rationale": "Classify the request before drafting the answer.",
            "input_fields": [
                {
                    "variable_name": "priority",
                    "label": "Priority",
                    "field_type": "text",
                    "required": False,
                }
            ],
            "steps": [
                {
                    "name": "Classify request",
                    "instructions": "Classify the submitted request.",
                    "output_fields": [
                        {
                            "name": "category",
                            "field_type": "string",
                            "description": "Request category.",
                        }
                    ],
                },
                {
                    "name": "Draft answer",
                    "instructions": "Draft the final answer.",
                    "output_type": "text",
                },
            ],
        }
    )

    compiled = compile_create_intent_to_spec(outline)

    assert compiled.form_fields is not None
    assert [field.name for field in compiled.form_fields] == ["priority"]
    assert compiled.steps[-1].input_bindings is None
    assert find_unused_form_fields(compiled) == ["priority"]
    validation = validate_spec(compiled)
    assert validation.valid
    assert any(warning.code == "unused_form_field" for warning in validation.warnings)


def test_renderer_terminal_form_field_fallback_does_not_hide_multi_step_unused_field() -> (
    None
):
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "PDF report",
            "plan_rationale": "Analyze the document before rendering PDF.",
            "input_fields": [
                {
                    "variable_name": "focus_area",
                    "label": "Focus area",
                    "field_type": "text",
                    "required": True,
                }
            ],
            "steps": [
                {
                    "name": "Extract risks",
                    "instructions": "Extract risks from the document.",
                    "output_fields": [
                        {
                            "name": "risks",
                            "field_type": "array",
                            "description": "Risks found in the document.",
                        }
                    ],
                },
                {
                    "name": "Prepare report body",
                    "instructions": "Write the report body from the extracted risks.",
                    "output_type": "text",
                },
                {
                    "name": "Assemble final text",
                    "instructions": "Prepare the final PDF body text.",
                    "output_type": "text",
                },
            ],
        }
    )

    compiled = compile_create_intent_to_spec(
        outline,
        context=CreateCompileContext(
            runtime_input_type=InputType.DOCUMENT,
            final_output_type=OutputType.PDF,
        ),
    )

    assert find_unused_form_fields(compiled) == ["focus_area"]
    assert "form_fields_declared_must_be_referenced" in _critic_issue_ids(compiled)
    validation = validate_spec(compiled)
    assert validation.valid
    assert any(warning.code == "unused_form_field" for warning in validation.warnings)


def test_single_step_outline_unreferenced_form_field_stays_unused_for_repair() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "PDF report",
            "plan_rationale": "Render a short PDF.",
            "input_fields": [
                {
                    "variable_name": "report_title",
                    "label": "Report title",
                    "field_type": "text",
                    "required": True,
                }
            ],
            "steps": [
                {
                    "name": "Write PDF body",
                    "instructions": "Render the submitted material as PDF.",
                    "output_type": "text",
                },
            ],
        }
    )

    compiled = compile_create_intent_to_spec(
        outline,
        context=CreateCompileContext(final_output_type=OutputType.PDF),
    )

    assert find_unused_form_fields(compiled) == ["report_title"]
    assert "form_fields_declared_must_be_referenced" in _critic_issue_ids(compiled)
    validation = validate_spec(compiled)
    assert validation.valid
    assert any(warning.code == "unused_form_field" for warning in validation.warnings)


def test_intermediate_form_field_use_flows_through_structured_previous_field() -> None:
    form_fields = [_form_field(variable_name="case_id", label="Case ID")]
    steps = [
        NewStepDraft(
            name="Score case",
            instructions="Score the case using the runtime identifier.",
            input_source="flow_input",
            input_type="text",
            output_type="json",
            uses_form_fields=["case_id"],
            output_fields=[
                _structured_field(
                    name="risk_score",
                    field_type="number",
                    description="Risk score.",
                )
            ],
        ),
        NewStepDraft(
            name="Write assessment",
            instructions="Write the assessment from the structured score.",
            input_source="previous_step",
            input_type="json",
            output_type="text",
            uses_previous_fields=[
                {
                    "from_step": 1,
                    "field_path": "risk_score",
                    "label": "Risk score",
                }
            ],
        ),
    ]

    compiled = compile_create_steps_to_spec(
        flow_name="Case assessment",
        form_fields=form_fields,
        steps=steps,
    )
    first_question = _question_binding(compiled.steps[0].input_bindings)
    final_question = _question_binding(compiled.steps[-1].input_bindings)

    assert first_question.count("{{ flow_input.case_id }}") == 1
    assert final_question == "Risk score: {{ step_a.output.structured.risk_score }}"
    assert "{{ flow_input.case_id }}" not in final_question
    assert compiled.steps[-1].input_contract is None
    assert validate_spec(compiled).valid


def test_one_input_field_can_feed_two_step_bindings_once_each() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Audience response",
            "plan_rationale": "Classify a request and adapt the answer.",
            "input_fields": [
                {
                    "variable_name": "audience",
                    "label": "Audience",
                    "field_type": "text",
                    "required": False,
                }
            ],
            "steps": [
                {
                    "name": "Classify request",
                    "instructions": "Classify the request for the selected audience.",
                    "uses_form_fields": ["audience"],
                    "output_fields": [
                        {
                            "name": "category",
                            "field_type": "string",
                            "description": "Request category.",
                        }
                    ],
                },
                {
                    "name": "Draft answer",
                    "instructions": "Draft an answer for the selected audience.",
                    "output_type": "text",
                    "uses_form_fields": ["audience"],
                },
            ],
        }
    )

    compiled = compile_create_intent_to_spec(outline)
    first_question = _question_binding(compiled.steps[0].input_bindings)
    final_question = _question_binding(compiled.steps[-1].input_bindings)

    assert compiled.form_fields is not None
    assert [field.name for field in compiled.form_fields] == ["audience"]
    assert first_question.count("{{ flow_input.audience }}") == 1
    assert final_question.count("{{ flow_input.audience }}") == 1
    assert validate_spec(compiled).valid


def test_edit_form_field_multi_reference_feeds_two_step_bindings_once_each() -> None:
    existing = [
        _flow_step(
            step_order=1,
            user_description="Classify request",
            input_source="flow_input",
            input_type="text",
            output_type="json",
            output_contract={
                "type": "object",
                "properties": {"category": {"type": "string"}},
            },
        ),
        _flow_step(
            step_order=2,
            user_description="Draft answer",
            input_source="previous_step",
            input_type="json",
            output_type="text",
        ),
    ]
    proposal = _edit_proposal(
        steps=[
            ModifyExistingStep(
                existing_step_ref="existing_step_1",
                uses_form_fields=["audience"],
            ),
            ModifyExistingStep(
                existing_step_ref="existing_step_2",
                uses_form_fields=["audience"],
            ),
        ],
    )

    result = compile_edit_proposal(
        proposal,
        existing,
        base_flow_revision=1,
        current_metadata_json=_form_metadata(
            variable_name="audience", label="Audience"
        ),
    )
    first_question = _question_binding(result.spec.steps[0].input_bindings)
    final_question = _question_binding(result.spec.steps[-1].input_bindings)

    assert result.spec.form_fields is not None
    assert [field.name for field in result.spec.form_fields] == ["audience"]
    assert first_question.count("{{ flow_input.audience }}") == 1
    assert final_question.count("{{ flow_input.audience }}") == 1
    assert validate_spec(result.spec).valid


def _form_field(*, variable_name: str, label: str) -> FormFieldSpec:
    return FormFieldSpec(
        name=variable_name,
        label=label,
        type="text",
        required=True,
    )


def _structured_field(
    *,
    name: str,
    field_type: str,
    description: str,
) -> StructuredFieldDraft:
    return StructuredFieldDraft(
        name=name,
        field_type=field_type,
        description=description,
    )


def _question_binding(input_bindings: dict[str, object] | None) -> str:
    assert input_bindings is not None
    question = effective_question_binding(input_bindings)
    assert question is not None
    return question


def _critic_issue_ids(spec: FlowDraftSpecCore) -> set[str]:
    context = CriticContext(
        spec=spec,
        flow=None,
        answer_signals={},
        text="",
        requirements_text="",
        signal_text="",
        planner_patterns=PlannerPatternSignals(),
        output_intent=OutputIntentResolution(
            terminal_output=spec.steps[-1].output_type.value
        ),
        mixed_audio_doc_input=False,
        requested_output_sections=RequestedOutputSections.empty(),
    )
    return {
        issue.id
        for issue in evaluate_critic_invariants(context, invariants=CRITIC_INVARIANTS)
    }


def _flow_step(
    *,
    step_order: int,
    user_description: str,
    input_source: str,
    input_type: str,
    output_type: str,
    output_contract: dict[str, object] | None = None,
) -> FlowStep:
    return FlowStep(
        id=uuid4(),
        flow_id=uuid4(),
        tenant_id=uuid4(),
        assistant_id=uuid4(),
        step_order=step_order,
        user_description=user_description,
        input_source=input_source,
        input_type=input_type,
        output_type=output_type,
        output_mode="pass_through",
        mcp_policy="inherit",
        output_contract=output_contract,
    )


def _form_metadata(*, variable_name: str, label: str) -> dict[str, object]:
    return {
        "form_schema": {
            "fields": [
                {
                    "name": variable_name,
                    "type": "text",
                    "label": label,
                    "required": False,
                }
            ]
        }
    }
