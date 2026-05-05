from __future__ import annotations

import logging
from uuid import uuid4

import pytest

from intric.flows.ai_builder.ai_builder_create_compiler import compile_create_draft
from intric.flows.ai_builder.ai_builder_create_models import (
    CreateFormFieldDraft,
    CreateStepDraft,
    FlowCreateDraft,
    StructuredFieldDraft,
)
from intric.flows.ai_builder.ai_builder_create_outline import (
    _log_form_field_terminal_fallback,
    compile_outline_to_create_draft,
    parse_outline_flow_arguments,
)
from intric.flows.ai_builder.ai_builder_edit_compiler import compile_edit_draft
from intric.flows.ai_builder.ai_builder_edit_models import (
    FlowEditDraft,
    StepEditOperation,
    StepPatch,
)
from intric.flows.ai_builder.ai_builder_models import InputSource, OutputType
from intric.flows.ai_builder.ai_builder_new_step_models import NewStepDraft
from intric.flows.ai_builder.ai_builder_validator import validate_spec
from intric.flows.flow import FlowStep


def test_declared_input_field_without_step_use_attaches_to_final_step(
    caplog: pytest.LogCaptureFixture,
) -> None:
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

    with caplog.at_level(logging.INFO):
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
    assert not _has_terminal_fallback_diagnostic(caplog)


def test_renderer_terminal_form_field_fallback_logs_diagnostic(
    caplog: pytest.LogCaptureFixture,
) -> None:
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "PDF report",
            "plan_rationale": "Analyze the document before rendering PDF.",
            "runtime_input": {"input_type": "document", "required": True},
            "final_output_type": "pdf",
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
                    "task": "Extract risks from the document.",
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
                    "task": "Write the report body from the extracted risks.",
                    "output_type": "text",
                },
                {
                    "name": "Create PDF",
                    "task": "Render the report body as PDF.",
                    "output_type": "pdf",
                },
            ],
        }
    )

    with caplog.at_level(logging.INFO):
        draft = compile_outline_to_create_draft(outline)

    assert draft.steps[-1].uses_form_fields == ["focus_area"]
    diagnostic = next(
        record
        for record in caplog.records
        if record.message == "ai_builder_form_fields_attached_to_document_terminal"
    )
    assert diagnostic.form_field_names == ["focus_area"]
    assert diagnostic.final_step_name == "Create PDF"
    assert diagnostic.final_output_type == "pdf"


def test_single_step_renderer_form_field_fallback_does_not_log_diagnostic(
    caplog: pytest.LogCaptureFixture,
) -> None:
    final_step = NewStepDraft(
        name="Create PDF",
        instructions="Render the submitted material as PDF.",
        input_source=InputSource.FLOW_INPUT,
        output_type=OutputType.PDF,
    )

    with caplog.at_level(logging.INFO):
        _log_form_field_terminal_fallback(
            steps=[final_step],
            final_step=final_step,
            form_field_names=["report_title"],
        )

    assert not _has_terminal_fallback_diagnostic(caplog)


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
    draft = FlowEditDraft(
        operations=[
            StepEditOperation(
                op="modify",
                target_ref="existing_step_1",
                patch=StepPatch(uses_form_fields=["audience"]),
            ),
            StepEditOperation(
                op="modify",
                target_ref="existing_step_2",
                patch=StepPatch(uses_form_fields=["audience"]),
            ),
        ],
    )

    result = compile_edit_draft(
        draft,
        existing,
        base_flow_revision=1,
        current_metadata_json=_form_metadata(
            variable_name="audience", label="Audience"
        ),
    )
    first_question = _question_binding(result.compiled_spec.steps[0].input_bindings)
    final_question = _question_binding(result.compiled_spec.steps[-1].input_bindings)

    assert result.compiled_spec.form_fields is not None
    assert [field.name for field in result.compiled_spec.form_fields] == ["audience"]
    assert first_question.count("{{ audience }}") == 1
    assert final_question.count("{{ audience }}") == 1
    assert validate_spec(result.compiled_spec).valid


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


def _has_terminal_fallback_diagnostic(caplog: pytest.LogCaptureFixture) -> bool:
    return any(
        record.message == "ai_builder_form_fields_attached_to_document_terminal"
        for record in caplog.records
    )


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
