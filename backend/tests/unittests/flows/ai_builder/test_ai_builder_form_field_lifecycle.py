from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from eneo.flows.ai_builder.ai_builder_architecture_errors import (
    AIBuilderArchitectureError,
)
from eneo.flows.ai_builder.ai_builder_create_compiler import (
    CreateCompileContext,
    compile_create_intent_to_spec,
)
from eneo.flows.ai_builder.ai_builder_critic_invariants import (
    CRITIC_INVARIANTS,
    CriticContext,
    evaluate_critic_invariants,
)
from eneo.flows.ai_builder.ai_builder_edit_compiler import compile_edit_proposal
from eneo.flows.ai_builder.ai_builder_framework_policy import OutputIntentResolution
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
from eneo.flows.ai_builder.ai_builder_runtime_input_fields import (
    RuntimeInputFieldHint,
)
from eneo.flows.ai_builder.ai_builder_validator import validate_spec
from eneo.flows.domain.flow import FlowStep
from eneo.flows.domain.mapped_execution_policy import FlowMappedExecutionPolicy
from eneo.flows.flow_authoring_spec import (
    FlowDraftSpecCore,
    InputType,
    OutputType,
)
from eneo.flows.input_binding_contract_rules import effective_question_binding


def _edit_proposal(**kwargs: Any) -> OrderedEditProposal:
    return OrderedEditProposal(plan_rationale="Update the flow.", **kwargs)


def test_declared_input_field_without_step_use_fails_create_compilation() -> None:
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

    with pytest.raises(AIBuilderArchitectureError) as exc_info:
        compile_create_intent_to_spec(outline)

    assert exc_info.value.public_code == "architecture_materialization_failed"
    assert exc_info.value.log_context["reason"] == "unplaced_form_fields"
    assert exc_info.value.log_context["field_names"] == "priority"


def test_confirmed_input_field_without_semantic_consumer_fails_compilation() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Case review",
            "plan_rationale": "Review the submitted case.",
            "steps": [
                {
                    "name": "Review case",
                    "instructions": "Review the submitted case.",
                    "output_type": "text",
                }
            ],
        }
    )

    with pytest.raises(AIBuilderArchitectureError) as exc_info:
        compile_create_intent_to_spec(
            outline,
            context=CreateCompileContext(
                runtime_input_field_hints=(
                    RuntimeInputFieldHint(
                        "case_type",
                        "Case type",
                        provenance="user_confirmed",
                    ),
                ),
            ),
        )

    assert exc_info.value.public_code == "architecture_materialization_failed"
    assert exc_info.value.log_context["reason"] == "unplaced_form_fields"
    assert exc_info.value.log_context["field_names"] == "case_type"


def test_unknown_semantic_form_field_consumer_fails_compilation() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Case review",
            "plan_rationale": "Review the submitted case.",
            "steps": [
                {
                    "name": "Review case",
                    "instructions": "Review the submitted case.",
                    "uses_form_fields": ["unknown_case_type"],
                    "output_type": "text",
                }
            ],
        }
    )

    with pytest.raises(AIBuilderArchitectureError) as exc_info:
        compile_create_intent_to_spec(outline)

    assert exc_info.value.public_code == "architecture_materialization_failed"
    assert exc_info.value.log_context["reason"] == "unknown_form_field_refs_open"
    assert exc_info.value.log_context["field_names"] == "unknown_case_type"


def test_confirmed_field_contract_rejects_unknown_semantic_consumer() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Case review",
            "plan_rationale": "Review the submitted case.",
            "steps": [
                {
                    "name": "Review case",
                    "instructions": "Review the submitted case.",
                    "uses_form_fields": ["tone"],
                    "output_type": "text",
                }
            ],
        }
    )

    with pytest.raises(AIBuilderArchitectureError) as exc_info:
        compile_create_intent_to_spec(
            outline,
            context=CreateCompileContext(
                runtime_input_field_hints=(
                    RuntimeInputFieldHint(
                        "case_type",
                        "Case type",
                        provenance="user_confirmed",
                    ),
                ),
            ),
        )

    assert exc_info.value.log_context["reason"] == "unknown_form_field_refs_closed"
    assert exc_info.value.log_context["field_names"] == "tone"


def test_inferred_field_context_allows_new_declared_runtime_field() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Case routing",
            "plan_rationale": "Route the case using runtime fields.",
            "input_fields": [
                {"variable_name": "case_type", "label": "Case type"},
                {"variable_name": "tone", "label": "Tone"},
            ],
            "steps": [
                {
                    "name": "Route case",
                    "instructions": "Route the case using its type and tone.",
                    "uses_form_fields": ["case_type", "tone"],
                    "output_type": "text",
                }
            ],
        }
    )

    compiled = compile_create_intent_to_spec(
        outline,
        context=CreateCompileContext(
            runtime_input_field_hints=(
                RuntimeInputFieldHint("case_type", "Case type"),
            ),
        ),
    )

    assert [field.name for field in compiled.form_fields or ()] == [
        "case_type",
        "tone",
    ]


def test_template_field_context_allows_new_declared_runtime_field() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Template report",
            "plan_rationale": "Fill a template using runtime fields.",
            "input_fields": [
                {"variable_name": "tone", "label": "Tone"},
            ],
            "steps": [
                {
                    "name": "Prepare report",
                    "instructions": "Prepare the report for the template.",
                    "uses_form_fields": ["template_value", "tone"],
                    "output_type": "text",
                }
            ],
        }
    )

    compiled = compile_create_intent_to_spec(
        outline,
        context=CreateCompileContext(
            template_placeholder_field_hints=(
                RuntimeInputFieldHint("template_value", "Template value"),
            ),
        ),
    )

    assert [field.name for field in compiled.form_fields or ()] == [
        "tone",
        "template_value",
    ]


def test_renderer_terminal_form_field_without_step_use_fails_create_compilation() -> (
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

    with pytest.raises(AIBuilderArchitectureError) as exc_info:
        compile_create_intent_to_spec(
            outline,
            context=CreateCompileContext(
                runtime_input_type=InputType.DOCUMENT,
                final_output_type=OutputType.PDF,
            ),
        )

    assert exc_info.value.public_code == "architecture_materialization_failed"
    assert exc_info.value.log_context["reason"] == "unplaced_form_fields"
    assert exc_info.value.log_context["field_names"] == "focus_area"


def test_single_step_outline_unreferenced_form_field_fails_create_compilation() -> None:
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

    with pytest.raises(AIBuilderArchitectureError) as exc_info:
        compile_create_intent_to_spec(
            outline,
            context=CreateCompileContext(final_output_type=OutputType.PDF),
        )

    assert exc_info.value.public_code == "architecture_materialization_failed"
    assert exc_info.value.log_context["reason"] == "unplaced_form_fields"
    assert exc_info.value.log_context["field_names"] == "report_title"


def test_intermediate_form_field_use_flows_through_derived_structured_underlag() -> (
    None
):
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Case assessment",
            "plan_rationale": "Score the case before writing the assessment.",
            "input_fields": [
                {
                    "variable_name": "case_id",
                    "label": "Case ID",
                    "field_type": "text",
                    "required": True,
                }
            ],
            "steps": [
                {
                    "name": "Score case",
                    "instructions": "Score the case using the runtime identifier.",
                    "output_type": "json",
                    "uses_form_fields": ["case_id"],
                    "output_fields": [
                        {
                            "name": "risk_score",
                            "field_type": "number",
                            "description": "Risk score.",
                        }
                    ],
                },
                {
                    "name": "Write assessment",
                    "instructions": "Write the assessment from the structured score.",
                    "output_type": "text",
                    "uses_previous_fields": [
                        {
                            "from_step": 1,
                            "field_path": "risk_score",
                            "label": "Risk score",
                        }
                    ],
                },
            ],
        }
    )

    compiled = compile_create_intent_to_spec(outline)
    first_question = _question_binding(compiled.steps[0].input_bindings)
    final_question = _question_binding(compiled.steps[-1].input_bindings)

    assert first_question.count("{{ flow_input.case_id }}") == 1
    assert final_question == "{{ step_a.output.structured }}"
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
    input_config: dict[str, object] | None = None,
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
        input_config=input_config,
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


def test_edit_preserves_authored_bound_and_reports_tightened_policy_conflict() -> None:
    existing = [
        _flow_step(
            step_order=1,
            user_description="Read each document",
            input_source="flow_input",
            input_type="document",
            output_type="json",
            input_config={
                "runtime_input": {
                    "enabled": True,
                    "required": True,
                    "max_files": 5,
                    "execution_mode": "per_source",
                }
            },
        )
    ]
    proposal = _edit_proposal(
        steps=[ModifyExistingStep(existing_step_ref="existing_step_1")]
    )

    result = compile_edit_proposal(
        proposal,
        existing,
        base_flow_revision=1,
        mapped_execution_policy=FlowMappedExecutionPolicy(
            max_provider_calls_per_mapped_step=3
        ),
    )

    runtime_input = result.spec.steps[0].input_config["runtime_input"]
    assert runtime_input["max_files"] == 5
    assert [advisory.code for advisory in result.approval.advisories] == [
        "mapped_file_limit_exceeds_policy"
    ]
