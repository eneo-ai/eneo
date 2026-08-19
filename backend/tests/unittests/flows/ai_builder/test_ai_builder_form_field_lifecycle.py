from __future__ import annotations

from typing import Any
from uuid import uuid4

from eneo.flows.ai_builder.ai_builder_edit_compiler import compile_edit_proposal
from eneo.flows.ai_builder.ai_builder_proposal_intent import (
    ModifyExistingStep,
    OrderedEditProposal,
)
from eneo.flows.ai_builder.ai_builder_validator import validate_spec
from eneo.flows.domain.flow import FlowStep
from eneo.flows.domain.mapped_execution_policy import FlowMappedExecutionPolicy
from eneo.flows.flow_authoring_spec import InputType
from eneo.flows.input_binding_contract_rules import effective_question_binding


def _edit_proposal(**kwargs: Any) -> OrderedEditProposal:
    return OrderedEditProposal(plan_rationale="Update the flow.", **kwargs)


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
    assert result.spec.steps[-1].input_type == InputType.TEXT
    assert result.spec.steps[-1].input_contract is None
    assert validate_spec(result.spec).valid


def _question_binding(input_bindings: dict[str, object] | None) -> str:
    assert input_bindings is not None
    question = effective_question_binding(input_bindings)
    assert question is not None
    return question


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
