from __future__ import annotations

from intric.flows.ai_builder.ai_builder_create_compiler import compile_create_draft
from intric.flows.ai_builder.ai_builder_create_models import (
    CreateFormFieldDraft,
    CreateStepDraft,
    FlowCreateDraft,
    StructuredFieldDraft,
)
from intric.flows.ai_builder.ai_builder_create_outline import (
    compile_outline_to_create_draft,
    parse_outline_flow_arguments,
)
from intric.flows.ai_builder.ai_builder_validator import validate_spec


def test_declared_input_field_without_step_use_attaches_to_final_step() -> None:
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Priority review",
            "plan_rationale": "Classify the request before drafting the answer.",
            "runtime_input": {"input_type": "text", "required": True},
            "final_output_type": "text",
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
                    "task": "Classify the submitted request.",
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
                    "task": "Draft the final answer.",
                    "output_type": "text",
                },
            ],
        }
    )

    draft = compile_outline_to_create_draft(outline)
    compiled = compile_create_draft(draft)
    final_question = _question_binding(compiled.steps[-1].input_bindings)

    assert [field.variable_name for field in draft.form_fields] == ["priority"]
    assert draft.steps[0].uses_form_fields == []
    assert draft.steps[-1].uses_form_fields == ["priority"]
    assert compiled.form_fields is not None
    assert [field.name for field in compiled.form_fields] == ["priority"]
    assert final_question.count("{{ priority }}") == 1
    assert "priority: {{ priority }}" in final_question
    assert validate_spec(compiled).valid


def test_intermediate_form_field_use_flows_through_structured_previous_field() -> None:
    draft = FlowCreateDraft(
        flow_name="Case assessment",
        plan_rationale="Extract a scored intermediate result before writing.",
        form_fields=[_form_field(variable_name="case_id", label="Case ID")],
        steps=[
            CreateStepDraft(
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
            CreateStepDraft(
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
        ],
    )

    compiled = compile_create_draft(draft)
    first_question = _question_binding(compiled.steps[0].input_bindings)
    final_question = _question_binding(compiled.steps[-1].input_bindings)

    assert draft.steps[0].uses_form_fields == ["case_id"]
    assert draft.steps[-1].uses_form_fields == []
    assert first_question.count("{{ case_id }}") == 1
    assert final_question == "Risk score: {{ step_a.output.structured.risk_score }}"
    assert "{{ case_id }}" not in final_question
    assert compiled.steps[-1].input_contract == compiled.steps[0].output_contract
    assert validate_spec(compiled).valid


def test_one_input_field_can_feed_two_step_bindings_once_each() -> None:
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Audience response",
            "plan_rationale": "Classify a request and adapt the answer.",
            "runtime_input": {"input_type": "text", "required": True},
            "final_output_type": "text",
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
                    "task": "Classify the request for the selected audience.",
                    "uses_input_fields": ["audience"],
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
                    "task": "Draft an answer for the selected audience.",
                    "output_type": "text",
                    "uses_input_fields": ["audience"],
                },
            ],
        }
    )

    draft = compile_outline_to_create_draft(outline)
    compiled = compile_create_draft(draft)
    first_question = _question_binding(compiled.steps[0].input_bindings)
    final_question = _question_binding(compiled.steps[-1].input_bindings)

    assert draft.steps[0].uses_form_fields == ["audience"]
    assert draft.steps[-1].uses_form_fields == ["audience"]
    assert compiled.form_fields is not None
    assert [field.name for field in compiled.form_fields] == ["audience"]
    assert first_question.count("{{ audience }}") == 1
    assert final_question.count("{{ audience }}") == 1
    assert validate_spec(compiled).valid


def _form_field(*, variable_name: str, label: str) -> CreateFormFieldDraft:
    return CreateFormFieldDraft(
        variable_name=variable_name,
        label=label,
        field_type="text",
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
    question = input_bindings["question"]
    assert isinstance(question, str)
    return question
